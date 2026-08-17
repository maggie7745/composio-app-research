"""
Phase 2a - Composio registry lookup.

Answers, for each of the 100 apps: does Composio already ship a toolkit for it,
and if so what does Composio itself say the auth method and tool count are?

Why this matters beyond "nice to have": Composio's toolkit doc pages are public
Markdown with a structured header --

    - **Category:** crm
    - **Auth:** OAUTH2, S2S_OAUTH2
    - **Composio Managed App Available?** Yes
    - **Tools:** 223
    - **Slug:** `SALESFORCE`

-- which gives us a second, independent opinion on auth for every app that is
already in the registry. Pass 2 uses that as a cross-check against what the LLM
read off the vendor's own docs. Where the two disagree, the app is flagged for
human verification. That disagreement signal is the backbone of the accuracy
loop, so it is worth getting the slug matching right rather than guessing.

No API key required -- the docs site is public. The slug universe comes from
docs.composio.dev/sitemap.xml so we never invent a slug.

Run:  python agent/composio_registry.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITEMAP = "https://docs.composio.dev/sitemap.xml"
TOOLKIT_MD = "https://docs.composio.dev/toolkits/{slug}.md"
UA = {"User-Agent": "composio-app-research/1.0 (take-home research script)"}

# Matches an app name to a registry slug where normalisation alone cannot.
# Every entry here is a human decision -- these are recorded rather than
# silently applied so the writeup can be honest about which of the 100 were
# matched by the machine and which needed a person to adjudicate.
#
# How these were found: the automatic pass matched 56/100. The 44 misses were
# put through a near-match report (prefix + difflib against the 1187 known
# slugs), and every candidate it surfaced was opened and read before being
# accepted or thrown out. Five were real; two were traps.
HUMAN_SLUG_OVERRIDES: dict[str, str] = {
    # Composio's slug is the ads product, which is what the brief's hint
    # (developers.pinterest.com) and category (Marketing/Ads) point at.
    "Pinterest":   "pinterest_ads",
    # Composio drops the "Go": highlevel == gohighlevel.com.
    "GoHighLevel": "highlevel",
    # Confirmed same product: toolkit page describes the B2B support platform
    # at usepylon.com, not some other Pylon.
    "Pylon":       "pylon_mcp",
    # Toolkit page says "NotebookLM Enterprise ... Google's licensed,
    # source-grounded notebook service" -- matches the brief's "Enterprise API".
    "NotebookLM":  "notebook_lm",
    # Cognition's Devin. Narrower than Devin's full API (this is the repo
    # documentation/codebase-analysis MCP, 4 tools), but it is the same vendor,
    # so it counts as registry presence with that caveat noted in the writeup.
    "Devin":       "devin_mcp",
}

# Near-matches that were surfaced, inspected, and deliberately NOT used.
# Kept in the code because a silent rejection is indistinguishable from a
# missed match when someone reviews this later.
REJECTED_MATCHES: dict[str, tuple[str, str]] = {
    "Mermaid CLI": (
        "mermaid_chart_mcp",
        "Different product. mermaid_chart_mcp is Mermaid Chart, the hosted SaaS "
        "diagram editor. The brief's app is mermaid-js/mermaid-cli, the "
        "open-source npm CLI. Same diagram syntax, different vendor surface.",
    ),
    "Squarespace": (
        "square",
        "Different company. SQUARE is Block's payment processor; Squarespace is "
        "the website/commerce builder. Name collision only.",
    ),
}


def fetch(url: str, timeout: int = 30) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def load_slug_universe(cache: pathlib.Path) -> set[str]:
    """All toolkit slugs Composio publishes docs for."""
    if cache.exists():
        return {l.strip() for l in cache.read_text().splitlines() if l.strip()}
    status, xml = fetch(SITEMAP)
    if status != 200:
        sys.exit(f"could not read Composio sitemap (http {status})")
    slugs = sorted(set(re.findall(r"toolkits/([a-z0-9_-]+)", xml)))
    cache.write_text("\n".join(slugs) + "\n")
    return set(slugs)


def candidates(name: str) -> list[str]:
    """Plausible slug spellings for an app name, most-likely first.

    Composio's slugs are inconsistent enough (active_campaign vs firecrawl vs
    _1password) that one normalisation rule does not cover it, so we try a few
    and take the first that actually exists in the sitemap.
    """
    base = name.lower()
    stripped = re.sub(r"\(.*?\)", "", base).strip()          # "Lark (Larksuite)" -> "lark"
    inner = (re.search(r"\((.*?)\)", base) or [None, ""])[1]  # -> "larksuite"

    forms = [stripped, inner, base]
    # "Zoho CRM" -> also try "zoho", "Amazon Selling Partner" -> "amazon"
    forms.append(stripped.split()[0] if stripped.split() else "")
    # ".com"/".io" suffixed names: "Monday.com" -> "monday", "systeme.io" -> "systeme"
    forms.append(re.sub(r"\.(com|io|ai|app|video|dev)$", "", stripped))

    out = []
    for f in forms:
        f = f.strip()
        if not f:
            continue
        snake = re.sub(r"[^a-z0-9]+", "_", f).strip("_")
        flat = re.sub(r"[^a-z0-9]+", "", f)
        for s in (snake, flat, snake.replace("_", "-")):
            if s and s not in out:
                out.append(s)
    return out


HEADER_PATTERNS = {
    "composio_category": r"\*\*Category:\*\*\s*(.+)",
    "composio_auth": r"\*\*Auth:\*\*\s*(.+)",
    "composio_managed": r"\*\*Composio Managed App Available\?\*\*\s*(.+)",
    "composio_tools": r"\*\*Tools:\*\*\s*(\d+)",
    "composio_triggers": r"\*\*Triggers:\*\*\s*(\d+)",
    "composio_slug_canonical": r"\*\*Slug:\*\*\s*`?([A-Z0-9_]+)`?",
    "composio_version": r"\*\*Version:\*\*\s*(\S+)",
}


def parse_toolkit_md(md: str) -> dict:
    """Pull the structured header block off a toolkit doc page."""
    head = md[:4000]                       # header block is always at the top
    out: dict = {}
    for key, pat in HEADER_PATTERNS.items():
        m = re.search(pat, head)
        out[key] = m.group(1).strip() if m else None
    if out.get("composio_auth"):
        out["composio_auth_list"] = [
            a.strip() for a in out["composio_auth"].split(",") if a.strip()
        ]
    for k in ("composio_tools", "composio_triggers"):
        if out.get(k):
            out[k] = int(out[k])
    # First non-heading line is Composio's own one-line description of the app.
    for line in md.splitlines()[1:8]:
        line = line.strip()
        if line and not line.startswith(("#", "-", "*")):
            out["composio_description"] = line
            break
    return out


def resolve(app: dict, universe: set[str]) -> dict:
    """Find this app's toolkit (if any) and read its metadata."""
    name = app["name"]

    if name in HUMAN_SLUG_OVERRIDES:
        slug, how = HUMAN_SLUG_OVERRIDES[name], "human_override"
    else:
        slug = next((c for c in candidates(name) if c in universe), None)
        how = "sitemap_match" if slug else "no_match"

    if slug is None:
        rec = {"in_composio_registry": False, "composio_slug": None,
               "match_method": how, "match_candidates_tried": candidates(name)}
        if name in REJECTED_MATCHES:
            rejected, why = REJECTED_MATCHES[name]
            rec["rejected_near_match"] = rejected
            rec["rejection_reason"] = why
        return rec

    status, md = fetch(TOOLKIT_MD.format(slug=slug))
    if status != 200:
        return {"in_composio_registry": False, "composio_slug": slug,
                "match_method": how, "fetch_status": status}

    rec = {"in_composio_registry": True, "composio_slug": slug,
           "match_method": how, "fetch_status": 200,
           "composio_doc_url": f"https://docs.composio.dev/toolkits/{slug}"}
    rec.update(parse_toolkit_md(md))
    return rec


def main() -> None:
    apps = json.loads((ROOT / "data" / "apps.json").read_text())["apps"]
    universe = load_slug_universe(ROOT / "data" / "composio_toolkit_slugs.txt")
    print(f"registry universe: {len(universe)} toolkit slugs")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda a: resolve(a, universe), apps))

    out = {}
    for app, rec in zip(apps, results):
        out[str(app["id"])] = {"name": app["name"],
                               "category": app["category"], **rec}

    path = ROOT / "data" / "composio_registry.json"
    path.write_text(json.dumps(out, indent=2) + "\n")

    hit = [r for r in out.values() if r["in_composio_registry"]]
    miss = [r for r in out.values() if not r["in_composio_registry"]]
    print(f"wrote {path}  ({time.time()-t0:.1f}s)")
    print(f"  in Composio registry: {len(hit)}/100")
    print(f"  not in registry:      {len(miss)}/100")
    print("\n  not in registry:")
    for r in miss:
        print(f"    - {r['name']} ({r['category']})")


if __name__ == "__main__":
    main()
