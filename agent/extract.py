"""
Phase 2c - Extraction. The one step in the pipeline that needs an LLM.

Reads data/apps.json + data/pages/*.json (fetched docs), batches apps into
prompts, sends each batch to a backend, validates every returned record
against agent/schema.py, and writes data/results_pass{N}.json.

Backends (pick with --backend):

  claude-cli       Pipes the prompt into `claude -p --output-format json`
                    over STDIN (argv was tried first and produced broken
                    output on a long prompt -- stdin is what actually works).
                    Uses the caller's existing Claude Code subscription
                    login (`claude login`), NOT a paid API key. This is the
                    default because it is what is actually available in this
                    project -- there is no ANTHROPIC_API_KEY here.

  anthropic-api     Calls the Messages API directly. Only runs if
                    ANTHROPIC_API_KEY is set. Not used in this run, kept
                    because it's ~15 lines and makes the repo useful to a
                    reviewer who does have a key.

  claude-code       Writes batches to work/queue/ and reads work/done/ for a
                    human-in-the-loop Claude Code session to fill by hand.
                    The no-credentials-at-all fallback.

Batching exists for one reason: a single claude-cli call was measured at
~15.8k tokens of fixed overhead (the CLI's own system prompt), regardless of
how small the actual question is. Run 100 apps one-at-a-time and you pay that
overhead 100 times and risk a rate-limit mid-run. Batching ~8 apps per call
amortizes it to ~13 calls a pass.

Every batch is checkpointed to work/pass{N}/batch_{i}.json as soon as it
validates, so a throttle or crash resumes instead of restarting from zero.

Run:
  python agent/extract.py --pass 1 --backend claude-cli
  python agent/extract.py --pass 1 --dry-run          # no calls, just report volume
  python agent/extract.py --validate-only data/results_pass1.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schema import (ACCESS_MODEL_ENUM, API_STYLE_ENUM, AUTH_ENUM,
                     BASE_RULES, BUILDABLE_ENUM, REQUIRED_FIELDS)
from fetch_docs import AUTH_SIGNAL_WORDS

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE_CHARS_IN_PROMPT = 4500   # trimmed from the 18k cached per page, per app -- see select_excerpt()

PASS2_ADDENDUM_PATH = ROOT / "agent" / "pass2_rules.md"


# --------------------------------------------------------------------------
# Batch construction
# --------------------------------------------------------------------------

def load_inputs():
    apps = json.loads((ROOT / "data" / "apps.json").read_text())["apps"]
    pages = {}
    for app in apps:
        p = ROOT / "data" / "pages" / f"{app['id']}.json"
        pages[app["id"]] = json.loads(p.read_text()) if p.exists() else None
    return apps, pages


def select_excerpt(text: str, max_chars: int) -> str:
    """Pick the slice of a cached page to actually put in the prompt.

    Tier-2 verification (Salesforce, Mailchimp, Shopify) found the real bug
    here: fetch_docs.py landed on the correct developer-docs page, and that
    page DID contain real auth/signup language -- it just wasn't in the first
    N characters, so a naive head-truncation cut it out before the model ever
    saw it, and the model correctly declined to guess from what was left.
    A page that's front-loaded with nav chrome and cards easily buries the
    one paragraph that matters past character 4500 of an 18000-char page.

    Fix: if the page is longer than the budget, center the excerpt on the
    first auth-signal word found anywhere in the full cached text, with
    lead-in context before it, rather than always starting at position 0.
    Falls back to a head-truncation if no signal word is found anywhere (the
    page genuinely may not have the answer, which is a legitimate "unclear").
    """
    if len(text) <= max_chars:
        return text
    low = text.lower()
    hit_pos = min((low.find(w) for w in AUTH_SIGNAL_WORDS if w in low), default=-1)
    if hit_pos == -1:
        return text[:max_chars]
    lead_in = 600
    start = max(0, hit_pos - lead_in)
    return text[start:start + max_chars]


def build_prompt(batch: list[dict], pages: dict, pass_rules_addendum: str) -> str:
    parts = [BASE_RULES]
    if pass_rules_addendum:
        parts.append("\nADDITIONAL RULES FOR THIS RUN (fixes from a prior pass):\n" + pass_rules_addendum)
    parts.append(f"\nReturn a JSON array of exactly {len(batch)} objects, one per app below, in order.\n")
    for app in batch:
        page = pages.get(app["id"])
        if page and page.get("fetched"):
            text = select_excerpt(page["text"] or "", PAGE_CHARS_IN_PROMPT)
            src = page["source_url"]
        else:
            text = "(no page could be fetched for this app -- answer every field null except id, and set access_model to \"unclear\")"
            src = "(none -- fetch failed)"
        parts.append(
            f"\n--- App id={app['id']}  name=\"{app['name']}\"  category=\"{app['category']}\" ---\n"
            f"SOURCE_URL: {src}\nPAGE TEXT:\n{text}\n"
        )
    return "\n".join(parts)


def batches(apps: list[dict], size: int):
    for i in range(0, len(apps), size):
        yield apps[i:i + size]


# --------------------------------------------------------------------------
# Backends -- all return the raw string the model produced
# --------------------------------------------------------------------------

def backend_claude_cli(prompt: str, model: str = "sonnet") -> str:
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model,
         "--disallowedTools", "Bash,Edit,Write,WebFetch,WebSearch"],
        input=prompt, capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.stderr[:500]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude -p reported error: {envelope.get('result')}")
    return envelope.get("result", "")


def backend_anthropic_api(prompt: str, model: str = "claude-sonnet-4-5") -> str:
    import os
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set -- this backend is unused in this project")
    import urllib.request
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({
            "model": model, "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }).encode(),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", []))


BACKENDS = {"claude-cli": backend_claude_cli, "anthropic-api": backend_anthropic_api}


# --------------------------------------------------------------------------
# Parsing + validation
# --------------------------------------------------------------------------

def strip_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


def validate_record(rec: dict, expected_id: int, source_text: str | None) -> list[str]:
    errs = []
    if rec.get("id") != expected_id:
        errs.append(f"id mismatch: expected {expected_id}, got {rec.get('id')}")
    for f in REQUIRED_FIELDS:
        if f not in rec:
            errs.append(f"missing field {f}")
    auth = rec.get("auth_methods")
    if auth is not None:
        if not isinstance(auth, list) or any(a not in AUTH_ENUM for a in auth):
            errs.append(f"auth_methods invalid: {auth}")
    if rec.get("access_model") not in ACCESS_MODEL_ENUM:
        errs.append(f"access_model invalid: {rec.get('access_model')}")
    if rec.get("api_style") not in API_STYLE_ENUM and not (
        rec.get("api_style") is None and source_text is None
    ):
        errs.append(f"api_style invalid: {rec.get('api_style')}")
    if rec.get("buildable_verdict") not in BUILDABLE_ENUM:
        errs.append(f"buildable_verdict invalid: {rec.get('buildable_verdict')}")
    conf = rec.get("confidence")
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        errs.append(f"confidence out of range: {conf}")
    quote = rec.get("evidence_quote")
    if quote and source_text:
        norm = lambda s: re.sub(r"\s+", " ", s).strip()
        if norm(quote) not in norm(source_text):
            errs.append("evidence_quote not found verbatim in source text (possible fabrication)")
    return errs


# --------------------------------------------------------------------------
# Main run
# --------------------------------------------------------------------------

def run(pass_n: int, backend_name: str, batch_size: int, dry_run: bool,
        limit: int | None, model: str) -> None:
    apps, pages = load_inputs()
    if limit:
        apps = apps[:limit]

    addendum = ""
    if pass_n >= 2 and PASS2_ADDENDUM_PATH.exists():
        addendum = PASS2_ADDENDUM_PATH.read_text()
        print(f"pass 2: loaded {len(addendum)} chars of hardened rules from {PASS2_ADDENDUM_PATH.name}")

    work_dir = ROOT / "work" / f"pass{pass_n}"
    work_dir.mkdir(parents=True, exist_ok=True)

    batch_list = list(batches(apps, batch_size))
    print(f"{len(apps)} apps -> {len(batch_list)} batches of ~{batch_size}")

    if dry_run:
        total_chars = 0
        for b in batch_list:
            total_chars += len(build_prompt(b, pages, addendum))
        print(f"dry run: {len(batch_list)} calls, ~{total_chars:,} prompt chars total "
              f"(~{total_chars // 4:,} tokens, plus ~15.8k fixed overhead per call "
              f"= ~{len(batch_list) * 15800 + total_chars // 4:,} tokens total)")
        return

    backend = BACKENDS[backend_name]
    all_records: dict[int, dict] = {}
    failures: list[dict] = []

    for bi, batch in enumerate(batch_list):
        ckpt = work_dir / f"batch_{bi}.json"
        if ckpt.exists():
            cached = json.loads(ckpt.read_text())
            for rec in cached["records"]:
                all_records[rec["id"]] = rec
            print(f"batch {bi+1}/{len(batch_list)}: resumed from checkpoint")
            continue

        prompt = build_prompt(batch, pages, addendum)
        t0 = time.time()
        try:
            raw = backend(prompt, model=model)
            parsed = json.loads(strip_fence(raw))
            if not isinstance(parsed, list):
                raise ValueError("model did not return a JSON array")
        except Exception as e:
            print(f"batch {bi+1}/{len(batch_list)}: FAILED to get valid JSON ({e})")
            failures.append({"batch": bi, "app_ids": [a["id"] for a in batch], "error": str(e)})
            continue

        by_id = {r.get("id"): r for r in parsed if isinstance(r, dict)}
        batch_ok = []
        for app in batch:
            rec = by_id.get(app["id"])
            page = pages.get(app["id"])
            src_text = page["text"] if page and page.get("fetched") else None
            if rec is None:
                failures.append({"app_id": app["id"], "name": app["name"], "error": "no record returned"})
                continue
            errs = validate_record(rec, app["id"], src_text)
            if errs:
                failures.append({"app_id": app["id"], "name": app["name"], "errors": errs, "record": rec})
                continue
            rec["source_url"] = page["source_url"] if page else None
            rec["fetched"] = bool(page and page.get("fetched"))
            rec["name"] = app["name"]
            rec["category"] = app["category"]
            batch_ok.append(rec)
            all_records[app["id"]] = rec

        ckpt.write_text(json.dumps({"records": batch_ok}, indent=2) + "\n")
        print(f"batch {bi+1}/{len(batch_list)}: {len(batch_ok)}/{len(batch)} valid  "
              f"({time.time()-t0:.1f}s)")

    out = [all_records[a["id"]] for a in apps if a["id"] in all_records]
    out_path = ROOT / "data" / f"results_pass{pass_n}.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")

    fail_path = ROOT / "data" / f"extract_failures_pass{pass_n}.json"
    fail_path.write_text(json.dumps(failures, indent=2) + "\n")

    print(f"\nwrote {out_path}  ({len(out)}/{len(apps)} apps extracted)")
    print(f"wrote {fail_path}  ({len(failures)} failures)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pass_n", type=int, default=1)
    ap.add_argument("--backend", default="claude-cli", choices=list(BACKENDS))
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="only process first N apps (testing)")
    ap.add_argument("--validate-only", metavar="FILE",
                     help="re-validate an existing results file, no calls made")
    args = ap.parse_args()

    if args.validate_only:
        apps, pages = load_inputs()
        by_id = {a["id"]: a for a in apps}
        recs = json.loads(pathlib.Path(args.validate_only).read_text())
        bad = 0
        for rec in recs:
            page = pages.get(rec.get("id"))
            src_text = page["text"] if page and page.get("fetched") else None
            errs = validate_record(rec, rec.get("id"), src_text)
            if errs:
                bad += 1
                print(f"  {by_id.get(rec['id'], {}).get('name', rec.get('id'))}: {errs}")
        print(f"{len(recs)-bad}/{len(recs)} valid")
        return

    run(args.pass_n, args.backend, args.batch_size, args.dry_run, args.limit, args.model)


if __name__ == "__main__":
    main()
