"""
Phase 2b - Docs fetcher.

For every app, get real page text for the extraction step to read -- and record
the exact URL each answer will trace back to. This is the one hard rule for the
whole pipeline: an app with no fetched page gets no invented answer. It is
marked unverified and reported that way on the final page.

Two situations:

1. hint_is_docs_url=True (51/100) -- the brief already points at developer
   docs. Fetch it directly.
2. hint_is_docs_url=False (49/100, e.g. "salesforce.com", or a marketing/root
   domain) -- the root site rarely has auth/pricing detail. Try a short list of
   conventional developer-docs paths on the same domain, keep the first that
   returns real content, and record which guess worked (transparency: this is
   a heuristic, not a search).

Composio's own toolkit pages (already fetched in composio_registry.py) are
reused as a *second* source for the 61 registry apps rather than re-fetched,
since re-fetching the same URL twice would be wasted work.

Output: data/pages/<app_id>.json  (cached; re-running is free and idempotent)
        data/fetch_report.json    (what worked, what didn't, per app)

Run:  python agent/fetch_docs.py [--refresh]
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
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "data" / "pages"
UA = {"User-Agent": "composio-app-research/1.0 (take-home research script; contact via github)"}
TIMEOUT = 20
MAX_CHARS = 18_000          # keep prompts affordable; auth/pricing info is rarely deep in a page

# Content-aware second pass. Landing on the right docs SUBDOMAIN is not the
# same as landing on a page that actually states auth/access mechanics --
# Tier-2 verification found this repeatedly (Salesforce, Mailchimp, Shopify:
# all fetched a real developer-docs page, all still landed on a marketing/
# overview page that doesn't say how you actually get a key or sign up, so
# the extractor correctly-but-uselessly said "unclear"). If the fetched page
# doesn't contain any of these signal words, it's "thin" for our purposes and
# worth spending a couple more requests trying to find the real getting-
# started/auth page on the same site before giving up.
AUTH_SIGNAL_WORDS = [
    "api key", "oauth", "authenticat", "access token", "bearer token",
    "sign up", "sign in to", "generate a token", "create an app",
    "get started", "getting started", "quickstart", "quick start",
    "sandbox", "free trial", "rate limit", "client id", "client secret",
]
THIN_PAGE_FOLLOWUPS = [
    "{base}/getting-started", "{base}/authentication", "{base}/auth",
    "{base}/quickstart", "{base}/docs/getting-started",
]


def is_thin(text: str) -> bool:
    """A page counts as thin if it's short (nav-shell docs portals routinely
    land under ~3000 chars of real body text) OR if it never mentions any
    auth/access signal word at all.

    Found via Tier-1 crosscheck on pass 1: 51/100 fetched pages were under
    3000 chars, and the keyword-only check (below) missed most of them,
    because a docs-portal INDEX page still contains words like "authenticat"
    as a link title -- e.g. GitHub's docs.github.com/rest fetched clean (200,
    real HTML) but only yielded 1744 chars, all sidebar/breadcrumb links plus
    a truncated one-line teaser ending "...to the REST A" -- the real content
    is one click away on the page it links to. The char-count threshold below
    is what actually catches that shape of failure; the keyword check alone
    left ~39 registry apps with auth_methods=[] in pass 1.
    """
    low = text.lower()
    if len(text) < 3000:
        return True
    return not any(w in low for w in AUTH_SIGNAL_WORDS)


ANCHOR_RE = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def find_auth_link(body_html: str, page_url: str) -> str | None:
    """Best same-domain link whose href or visible text looks auth-shaped.

    This is what makes the thin-page recovery actually work: rather than
    guessing conventional paths blind, read the LINKS the page itself offers
    and follow the one it is pointing at (e.g. "Authenticating to the REST
    API" on GitHub's docs index) -- the page is telling us where the real
    content is, we just weren't looking.
    """
    from urllib.parse import urljoin, urlparse
    origin = urlparse(page_url)
    best, best_score = None, 0
    for href, inner in ANCHOR_RE.findall(body_html):
        text = TAG_RE.sub(" ", inner).strip().lower()
        href_l = href.lower()
        score = 0
        for w in ("authenticat", "auth", "quickstart", "quick-start",
                  "getting-started", "getting started", "api-key", "api key"):
            if w in text or w in href_l:
                score += 2 if w.startswith("authenticat") else 1
        if score <= best_score:
            continue
        full = urljoin(page_url, href)
        if urlparse(full).netloc != origin.netloc:
            continue
        best, best_score = full, score
    return best


# Conventional developer-docs subpaths/subdomains to try when the brief's hint
# is just a marketing root domain. Ordered most-to-least likely.
DOCS_GUESSES = [
    "https://developers.{domain}",
    "https://developer.{domain}",
    "https://docs.{domain}",
    "https://{domain}/developers",
    "https://{domain}/developer",
    "https://{domain}/docs",
    "https://{domain}/api",
    "https://{domain}/api-docs",
    "https://api.{domain}",
]

# Human corrections after the automated guess list came up short on the first
# run (8/100 apps). Each is a specific, checked reason -- not a blanket retry --
# because the goal is a defensible trail, not a higher hit-rate for its own sake.
#
# Two different fixes show up here:
#  - a corrected URL (the guess heuristic tried the wrong path; a human found
#    the right one and it fetches fine with plain HTTP), or
#  - a `browser_capture` string (the real docs are a JS-rendered SPA that plain
#    HTTP cannot read at all; this is literal rendered page text pulled by
#    hand via the browser tool, pasted in verbatim, not paraphrased).
HUMAN_URL_OVERRIDES: dict[int, dict] = {
    # GoHighLevel: the brief's own hint (highlevel.stoplight.io) is a dead
    # Stoplight workspace -- confirmed by hand, the page literally reads
    # "Workspace does not exist." GHL moved their docs; the live location,
    # found via web search and confirmed by fetching it, is the marketplace
    # developer portal below.
    34: {"url": "https://marketplace.gohighlevel.com/docs/",
         "reason": "human_corrected_dead_hint",
         "note": "brief's hint URL highlevel.stoplight.io is a dead Stoplight workspace"},
    # SE Ranking: seranking.com/api (the brief's own hint) 404s; the live API
    # marketing/docs page is api.html.
    52: {"url": "https://seranking.com/api.html",
         "reason": "human_corrected_path"},
    # Lark: open.larksuite.com is a client-rendered SPA -- curl gets an empty
    # shell. Captured via browser tool 2026-08-17.
    24: {"browser_capture": "lark_open_larksuite_com_document.txt",
         "url": "https://open.larksuite.com/document",
         "reason": "browser_capture_js_spa"},
    # Gumroad: developers.gumroad.com (the automated guess's top candidate) is
    # NOT Gumroad -- it resolves to an unrelated personal site (title "Sanjay
    # Yadav"), confirmed by hand. The real docs are gumroad.com/api, which is
    # also JS-rendered.
    48: {"browser_capture": "gumroad_com_api.txt",
         "url": "https://gumroad.com/api",
         "reason": "browser_capture_js_spa",
         "note": "developers.gumroad.com is NOT Gumroad's docs -- unrelated site, do not use"},
    # QuickBooks: developer.intuit.com is client-rendered.
    86: {"browser_capture": "developer_intuit_com_get_started.txt",
         "url": "https://developer.intuit.com/app/developer/qbo/docs/get-started",
         "reason": "browser_capture_js_spa"},
    # Zendesk: the automated guess (developers.zendesk.com) is a DEAD page --
    # "It looks like the help centre that you're trying to reach no longer
    # exists." Confirmed by hand via Tier-2 verification; extraction correctly
    # abstained rather than hallucinate, but the underlying page was wrong.
    # Real API docs live at developer.zendesk.com/api-reference/.
    11: {"url": "https://developer.zendesk.com/api-reference/",
         "reason": "human_corrected_dead_page",
         "note": "developers.zendesk.com resolves to a defunct help-center page, not docs"},
    # Twilio: automated guess (developers.twilio.com) landed on an
    # events/webinars hub, not API reference. Confirmed by hand via Tier-2
    # verification -- same failure shape as Zendesk: extraction correctly
    # said "unclear" off a page that was never going to have the answer.
    22: {"url": "https://www.twilio.com/docs/usage/api",
         "reason": "human_corrected_wrong_page",
         "note": "developers.twilio.com is a training/events hub, not API reference"},
}


class TextExtractor(HTMLParser):
    """Minimal HTML->text: drop script/style/nav/footer noise, keep body text."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header"}

    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            s = data.strip()
            if s:
                self.chunks.append(s)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.chunks))


def fetch(url: str) -> tuple[int, str, str]:
    """Returns (status, content_type, body)."""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read(2_000_000).decode("utf-8", "replace")
            return r.status, ctype, body
    except urllib.error.HTTPError as e:
        return e.code, "", ""
    except Exception as e:
        return 0, "", str(e)


def crude_text(body: str) -> str:
    """Tag-stripping fallback with no tag-tracking to derail.

    Deliberately simple: strip <script>...</script> blocks (the biggest
    source of junk), then strip every remaining tag, then collapse
    whitespace. A fancier version that also tried to strip <style> blocks
    measurably threw away real content on at least one real page (an
    over-eager alternation pattern ate more than intended) -- so this stays
    as plain as it can while still being useful.
    """
    stripped = re.sub(r"<script.*?</script>", " ", body, flags=re.S | re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def to_text(url: str, ctype: str, body: str) -> str:
    if url.endswith(".md") or "markdown" in ctype or (
        not ctype and body.lstrip().startswith("#")
    ):
        return body
    try:
        p = TextExtractor()
        p.feed(body)
        parsed = p.text()
    except Exception:
        parsed = ""
    # Guard against the parser silently stalling (observed on ipayx.ai/docs:
    # an unbalanced/odd attribute mid-page left skip_depth stuck above zero,
    # so handle_data stopped firing after the <title> with no exception
    # raised at all). A body this much longer than what came out means the
    # tag-aware parser lost the thread -- fall back to the dumber, more
    # robust regex stripper rather than ship a truncated page.
    if len(parsed) < 200 and len(body) > 2000:
        return crude_text(body)
    return parsed


def domain_of(hint_url: str | None, name: str) -> str:
    if hint_url:
        return re.sub(r"^https?://", "", hint_url).split("/")[0]
    return re.sub(r"[^a-z0-9]", "", name.lower()) + ".com"


def resolve_and_fetch(app: dict) -> dict:
    name, hint_url = app["name"], app["hint_url"]
    tried: list[dict] = []
    last_raw = {"body": "", "url": ""}   # for find_auth_link on the thin-page path

    def attempt(url: str, why: str) -> dict | None:
        status, ctype, body = fetch(url)
        tried.append({"url": url, "status": status, "reason": why})
        if status == 200 and len(body) > 200:
            last_raw["body"], last_raw["url"] = body, url
            text = to_text(url, ctype, body)
            if len(text) > 150:
                return {"url": url, "text": text[:MAX_CHARS], "how": why}
        return None

    override = HUMAN_URL_OVERRIDES.get(app["id"])
    if override and "browser_capture" in override:
        cap_path = ROOT / "data" / "browser_captures" / override["browser_capture"]
        text = cap_path.read_text()
        tried.append({"url": override["url"], "status": "browser",
                      "reason": override["reason"]})
        return {"id": app["id"], "name": name, "fetched": True,
                "source_url": override["url"], "fetch_method": override["reason"],
                "text": text[:MAX_CHARS], "attempts": tried}
    if override and "url" in override:
        result = attempt(override["url"], override["reason"])
        if result:
            return {"id": app["id"], "name": name, "fetched": True,
                     "source_url": result["url"], "fetch_method": result["how"],
                     "text": result["text"], "attempts": tried}

    result = None
    if app["hint_is_docs_url"] and hint_url:
        result = attempt(hint_url, "brief_hint_is_docs")

    # When the brief only handed us a marketing root (e.g. "salesforce.com"),
    # prefer a real developer-docs subdomain over accepting the root the
    # moment it returns any 200 -- a marketing homepage almost never states
    # auth/API/pricing detail, so settling for it here would make extraction
    # correctly-but-uselessly answer "unclear" for most of this cohort. Try
    # the docs-path guesses FIRST; only fall back to the bare root as a last
    # resort so the app still gets *some* page rather than none.
    if result is None:
        domain = domain_of(hint_url, name)
        for tmpl in DOCS_GUESSES:
            result = attempt(tmpl.format(domain=domain), "docs_path_guess")
            if result:
                break

    if result is None and hint_url and not app["hint_is_docs_url"]:
        result = attempt(hint_url, "brief_hint_root_fallback")

    if result is None and hint_url is None:
        # e.g. "Paygent Connect" -> hint_raw "paygent", not a real domain.
        # Recorded honestly rather than fabricating a URL to try.
        tried.append({"url": None, "status": None,
                      "reason": "brief_hint_not_a_url"})

    # We're on the right docs site but the page may still be a thin nav-shell
    # or marketing/overview page with no real auth/access content on it (see
    # is_thin() -- this is the fix that came out of Tier-1 crosscheck finding
    # 51/100 fetched pages under 3000 chars). Prefer following a real link
    # the page itself offers (find_auth_link) over guessing conventional
    # paths -- it is reading what the page says, not pattern-guessing.
    if result is not None and is_thin(result["text"]):
        followed = None
        if last_raw["body"] and last_raw["url"] == result["url"]:
            link = find_auth_link(last_raw["body"], result["url"])
            if link:
                followed = attempt(link, "thin_page_link_followed")
        if followed and not is_thin(followed["text"]):
            result = followed
        else:
            import re as _re
            m = _re.match(r"(https?://[^/]+)", result["url"])
            base = m.group(1) if m else None
            if base:
                for tmpl in THIN_PAGE_FOLLOWUPS:
                    richer = attempt(tmpl.format(base=base), "thin_page_followup")
                    if richer and not is_thin(richer["text"]):
                        result = richer
                        break

    out = {
        "id": app["id"], "name": app["name"],
        "fetched": result is not None,
        "source_url": result["url"] if result else None,
        "fetch_method": result["how"] if result else None,
        "text": result["text"] if result else None,
        "attempts": tried,
    }
    return out


def main() -> None:
    refresh = "--refresh" in sys.argv
    apps = json.loads((ROOT / "data" / "apps.json").read_text())["apps"]
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    to_fetch = []
    cached = 0
    for app in apps:
        cache_path = PAGES_DIR / f"{app['id']}.json"
        if cache_path.exists() and not refresh:
            cached += 1
            continue
        to_fetch.append(app)

    print(f"apps: {len(apps)}  |  cached: {cached}  |  to fetch: {len(to_fetch)}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(resolve_and_fetch, to_fetch))

    for app, rec in zip(to_fetch, results):
        (PAGES_DIR / f"{app['id']}.json").write_text(json.dumps(rec, indent=2) + "\n")

    # Build the report over ALL apps (cached + freshly fetched) for an honest total.
    report = []
    for app in apps:
        rec = json.loads((PAGES_DIR / f"{app['id']}.json").read_text())
        report.append({
            "id": app["id"], "name": app["name"], "category": app["category"],
            "fetched": rec["fetched"], "source_url": rec["source_url"],
            "fetch_method": rec["fetch_method"],
            "chars": len(rec["text"]) if rec["text"] else 0,
        })

    (ROOT / "data" / "fetch_report.json").write_text(json.dumps(report, indent=2) + "\n")

    ok = sum(r["fetched"] for r in report)
    print(f"fetched OK: {ok}/{len(apps)}  ({time.time()-t0:.1f}s this run)")
    print("\nfailed to fetch (will be marked unverified downstream):")
    for r in report:
        if not r["fetched"]:
            print(f"  - {r['name']} ({r['category']})")


if __name__ == "__main__":
    main()
