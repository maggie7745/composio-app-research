# Composio App Research — 100 apps, researched by an agent

Take-home for the AI Product Ops Intern role at Composio. Researches 100 apps
(10 categories × 10 apps, from the assignment brief) for auth method,
self-serve-vs-gated access, API surface, and agent-toolkit buildability —
with the pipeline itself as the deliverable, not just the output table.

**Live page:** https://maggie7745.github.io/composio-app-research/
**This repo:** https://github.com/maggie7745/composio-app-research

## What's here

```
data/apps.json               100 apps transcribed verbatim from the brief, all-null "research" block
data/composio_registry.json  Composio's own toolkit registry, matched against all 100 (no API key needed)
data/pages/*.json            cached fetched docs pages, one per app (gitignored — regenerate, don't commit)
data/results_pass1.json      pass-1 structured extraction
data/results_pass2.json      pass-2, after hardening the prompt from verified pass-1 failures
data/crosscheck_pass{1,2}.json  Tier-1 automated verification vs Composio's own auth field
data/patterns.json           the clustered findings (auth distribution, self-serve %, blockers, easy wins)
verification/sample_plan.json      Tier-2 stratified sample, pre-registered BEFORE reading pass-1 results
verification/sample_pass{1,2}.json hand-verification hits/misses, with a reason for every miss
agent/*.py                   the pipeline, one script per phase (see below)
site/index.html              the single-page deliverable
```

## Why it's built this way

The brief explicitly asks for the pipeline to be built "with an agent, not by
hand" and says accuracy is what matters most — more than any other single
line in the brief. Two decisions follow directly from that:

1. **Only one step needs an LLM.** Registry lookup, docs fetching, the
   Tier-1 cross-check, and pattern synthesis are all plain Python over public
   HTTP — no credentials, fully deterministic, free to re-run. That leaves a
   small, auditable surface (`extract.py`) where the LLM's answers could
   plausibly be wrong, instead of spreading "trust me" across the whole
   pipeline.
2. **The verification loop is two independent tiers, not one.** Tier 1 (free,
   61 apps) cross-checks the LLM's auth answer against Composio's own
   published `Auth:` field for every app that already has a toolkit — a
   second, genuinely independent source, for zero extra cost. Tier 2 (a
   human + the browser tool, ~22 apps) hand-checks a **pre-registered**
   sample against real docs. Pre-registering the sample before reading pass-1
   results is deliberate: picking the sample after seeing the answers would
   let it quietly favor apps the agent got right.

## No paid API key was used

There is no `ANTHROPIC_API_KEY` in this project. The extraction step
(`agent/extract.py`) defaults to the `claude-cli` backend, which pipes
prompts into `claude -p --output-format json` — using the same Claude Code
CLI subscription login (`claude login`) as an interactive session, not a
metered API key. `--backend anthropic-api` exists and works if a reviewer
does have a key, but it is not what produced the data in this repo.

A single `claude -p` call was measured at ~15.8k tokens of fixed overhead
(the CLI's own system prompt) regardless of question size — so extraction
batches ~8 apps per call (~13 calls/pass) rather than calling once per app,
and every batch is checkpointed to `work/pass{N}/batch_{i}.json` so a
throttle or crash resumes instead of restarting.

## Running it

Requires Python 3.10+ (standard library only) and the `claude` CLI on PATH,
logged in (`claude login`) — no other credentials needed for the default path.

```bash
python agent/build_apps.py          # data/apps.json — the 100-app input set
python agent/composio_registry.py   # data/composio_registry.json — Composio's own registry, no key
python agent/fetch_docs.py          # data/pages/*.json — cached developer-docs text, no key

python agent/extract.py --pass 1                     # data/results_pass1.json (the only step needing an LLM)
python agent/crosscheck.py --pass 1                   # data/crosscheck_pass1.json — Tier 1, no key

# Tier 2: hand-verify verification/sample_plan.json against real docs,
# write verification/sample_pass1.json, then hand-write agent/pass2_rules.md
# from the confirmed misses.

python agent/extract.py --pass 2                      # data/results_pass2.json, hardened prompt
python agent/crosscheck.py --pass 2

python agent/synthesize.py --pass 2                    # data/patterns.json
python agent/build_site.py                             # site/index.html
```

`extract.py --dry-run` prints the projected call count and token volume
before spending anything. `extract.py --validate-only data/results_pass1.json`
re-runs the schema/evidence validator against an existing results file with
no network calls at all.

### Cold-start check

`data/pages/` (the fetched doc caches) is gitignored — it's regenerable, and
committing ~100 scraped vendor pages verbatim isn't something this repo
should redistribute. A fresh clone reproduces everything downstream of
`fetch_docs.py` by re-fetching live pages, which is the actual reproducibility
guarantee (not "trust the committed cache").

## Honest misses

The brief asks for failures to be reported on the page, not hidden. Specific
things that didn't work cleanly:

- **Paygent Connect** — the brief's own hint (`paygent`) isn't a resolvable
  domain; no public docs were found for it at all.
- **Binance** — real docs are bot/geo-gated even against a real browser render
  in this environment; recorded as unfetched rather than filled from memory.
- **PitchBook** — the marketing site 403s a scripted fetch; consistent with
  it being an enterprise, contact-sales research product, but genuinely
  unverified rather than confirmed.
- **2 Composio slug near-matches were rejected**, not silently used:
  `Squarespace ≠ square` (Block's payment processor, name collision) and
  `Mermaid CLI ≠ mermaid_chart_mcp` (hosted SaaS vs. the OSS npm package).
- Full pass-1 → pass-2 hit/miss detail, including anything that did **not**
  improve on the second pass, is in `verification/sample_pass1.json` /
  `sample_pass2.json` and rendered plainly on the site's verification section.
