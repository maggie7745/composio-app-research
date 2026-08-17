"""
Phase 5 - Deliverable. Renders data/patterns.json + data/crosscheck_pass*.json +
verification/*.json into a single self-contained site/index.html.

No build step, no framework: one Jinja-free f-string template, Tailwind via
CDN for layout, vanilla JS for the table filter. Everything the brief asks to
be visible in ~2 minutes with no narration lives on this one page:
patterns headline -> findings table -> the agent -> verification -> proof.

Run:  python agent/build_site.py
"""

from __future__ import annotations

import html
import json
import pathlib
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name, default=None):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else default


def load_verification(name, default=None):
    p = ROOT / "verification" / name
    return json.loads(p.read_text()) if p.exists() else default


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def badge(text, kind):
    colors = {
        "self_serve": "bg-emerald-900/40 text-emerald-300 border-emerald-700/50",
        "gated_paid": "bg-amber-900/40 text-amber-300 border-amber-700/50",
        "gated_approval": "bg-amber-900/40 text-amber-300 border-amber-700/50",
        "gated_partnership": "bg-rose-900/40 text-rose-300 border-rose-700/50",
        "unclear": "bg-slate-800 text-slate-400 border-slate-700",
        "buildable_now": "bg-emerald-900/40 text-emerald-300 border-emerald-700/50",
        "buildable_with_workaround": "bg-amber-900/40 text-amber-300 border-amber-700/50",
        "blocked": "bg-rose-900/40 text-rose-300 border-rose-700/50",
    }
    cls = colors.get(kind, "bg-slate-800 text-slate-400 border-slate-700")
    return f'<span class="inline-block px-2 py-0.5 rounded text-xs border {cls}">{esc(text)}</span>'


def main():
    patterns = load("patterns.json")
    apps = load("apps.json")["apps"]
    results = {r["id"]: r for r in load("results_pass2.json", load("results_pass1.json", []))}
    registry = load("composio_registry.json", {})
    crosscheck1 = load("crosscheck_pass1.json")
    crosscheck2 = load("crosscheck_pass2.json")
    tier2_p1 = load_verification("sample_pass1.json")
    tier2_p2 = load_verification("sample_pass2.json")

    pass_used = 2 if (ROOT / "data" / "results_pass2.json").exists() else 1

    rows_html = []
    for a in apps:
        r = results.get(a["id"], {})
        reg = registry.get(str(a["id"]), {})
        auth = ", ".join(r.get("auth_methods") or []) or "—"
        rows_html.append(f"""
        <tr class="border-b border-slate-800 hover:bg-slate-900/60 app-row"
            data-category="{esc(a['category'])}" data-access="{esc(r.get('access_model','unclear'))}"
            data-auth="{esc(auth)}" data-buildable="{esc(r.get('buildable_verdict','unclear'))}"
            data-name="{esc(a['name'].lower())}">
          <td class="px-3 py-2 font-medium text-slate-100">{esc(a['name'])}</td>
          <td class="px-3 py-2 text-slate-400 text-xs">{esc(a['category'])}</td>
          <td class="px-3 py-2 text-slate-300 text-xs max-w-xs">{esc(r.get('one_liner') or '—')}</td>
          <td class="px-3 py-2 text-xs">{esc(auth)}</td>
          <td class="px-3 py-2">{badge(r.get('access_model','unclear'), r.get('access_model','unclear'))}</td>
          <td class="px-3 py-2">{badge(r.get('buildable_verdict','unclear'), r.get('buildable_verdict','unclear'))}</td>
          <td class="px-3 py-2 text-xs text-slate-400">{'✅ ' + esc(reg.get('composio_slug')) if reg.get('in_composio_registry') else '—'}</td>
          <td class="px-3 py-2 text-xs">
            {f'<a href="{esc(r.get("source_url"))}" target="_blank" class="text-sky-400 hover:underline">source</a>' if r.get('source_url') else '<span class="text-slate-600">unverified</span>'}
          </td>
        </tr>""")

    cat_summary_rows = "".join(f"""
        <tr class="border-b border-slate-800">
          <td class="px-3 py-1.5 text-slate-200">{esc(c['category'])}</td>
          <td class="px-3 py-1.5 text-right font-mono">{c['self_serve_pct']}%</td>
          <td class="px-3 py-1.5 text-right text-slate-400 font-mono text-xs">{c['self_serve']}/{c['total']}</td>
        </tr>""" for c in patterns["self_serve_by_category"])

    auth_bars = "".join(f"""
        <div class="flex items-center gap-2 text-sm">
          <div class="w-28 text-slate-400 text-xs">{esc(k)}</div>
          <div class="flex-1 bg-slate-800 rounded h-4 overflow-hidden">
            <div class="bg-sky-500 h-4" style="width:{100*v/patterns['total_apps']:.0f}%"></div>
          </div>
          <div class="w-10 text-right text-xs text-slate-400 font-mono">{v}</div>
        </div>""" for k, v in patterns["auth_distribution"].items())

    blocker_rows = "".join(f"""
        <tr class="border-b border-slate-800">
          <td class="px-3 py-1.5 text-slate-200">{esc(k.replace('_',' '))}</td>
          <td class="px-3 py-1.5 text-right font-mono">{v}</td>
        </tr>""" for k, v in patterns["blocker_taxonomy"].items())

    easy_wins_html = "".join(
        f'<li class="py-1"><span class="font-medium text-slate-100">{esc(r["name"])}</span> '
        f'<span class="text-slate-500 text-xs">— {esc(r["category"])}</span></li>'
        for r in patterns["easy_wins"][:20])

    outreach_html = "".join(
        f'<li class="py-1"><span class="font-medium text-slate-100">{esc(r["name"])}</span> '
        f'<span class="text-slate-500 text-xs">— {esc(r["category"])} · {esc(r["blocker_bucket"].replace("_"," "))}</span></li>'
        for r in patterns["needs_outreach"][:20])

    # --- Verification section -------------------------------------------
    def tier1_block(cc, label):
        if not cc:
            return f'<p class="text-slate-500 text-sm">{label}: not yet run.</p>'
        rate = cc["agreement_rate"]
        return f"""
        <div class="rounded-lg border border-slate-800 p-4">
          <div class="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
          <div class="text-3xl font-bold {'text-emerald-400' if rate and rate>0.8 else 'text-amber-400'}">{rate*100:.0f}%</div>
          <div class="text-xs text-slate-500">{cc['agree']}/{cc['checked']} agree with Composio's own auth field</div>
        </div>"""

    tier1_html = tier1_block(crosscheck1, "Tier 1 · Pass 1 vs Composio registry") + \
                 tier1_block(crosscheck2, "Tier 1 · Pass 2 vs Composio registry")

    def tier2_summary(data, label):
        if not data:
            return f'<p class="text-slate-500 text-sm">{label}: not yet run.</p>'
        return f"""
        <div class="rounded-lg border border-slate-800 p-4">
          <div class="text-xs text-slate-500 uppercase tracking-wide">{label}</div>
          <div class="text-3xl font-bold {'text-emerald-400' if data['field_accuracy_pct']>80 else 'text-amber-400'}">{data['field_accuracy_pct']:.0f}%</div>
          <div class="text-xs text-slate-500">{data['hits']}/{data['total_judgments']} field-level judgments correct, {data['n_apps']} apps hand-checked</div>
        </div>"""

    tier2_html = tier2_summary(tier2_p1, "Tier 2 · Pass 1 hand-verified sample") + \
                 tier2_summary(tier2_p2, "Tier 2 · Pass 2 hand-verified sample")

    def misses_table(data):
        if not data:
            return ""
        rows = "".join(f"""
          <tr class="border-b border-slate-800">
            <td class="px-3 py-2 font-medium">{esc(m['app'])}</td>
            <td class="px-3 py-2 text-xs">{esc(m['field'])}</td>
            <td class="px-3 py-2 text-xs text-rose-300">{esc(m['agent_answer'])}</td>
            <td class="px-3 py-2 text-xs text-emerald-300">{esc(m['correct_answer'])}</td>
            <td class="px-3 py-2 text-xs text-slate-400">{esc(m['why_wrong'])}</td>
          </tr>""" for m in data.get("misses", []))
        if not rows:
            return '<p class="text-emerald-400 text-sm">No misses in this pass\'s sample.</p>'
        return f"""
        <table class="w-full text-sm mt-3">
          <thead><tr class="text-left text-xs text-slate-500 border-b border-slate-700">
            <th class="px-3 py-1">App</th><th class="px-3 py-1">Field</th>
            <th class="px-3 py-1">Agent said</th><th class="px-3 py-1">Actually</th>
            <th class="px-3 py-1">Why wrong</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    misses_p1 = misses_table(tier2_p1)
    misses_p2 = misses_table(tier2_p2)

    ew_gap = patterns.get("easy_wins_composio_gap", [])
    ew_gap_html = "".join(f'<li>{esc(r["name"])}</li>' for r in ew_gap[:12])

    today = date.today().isoformat()

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Composio App Research — 100 Apps</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body {{ background:#0b0f17; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
  ::-webkit-scrollbar {{ height:8px; width:8px; }}
  ::-webkit-scrollbar-thumb {{ background:#334155; border-radius:4px; }}
</style>
</head>
<body class="max-w-6xl mx-auto px-4 md:px-8 py-10">

  <header class="mb-10">
    <div class="text-xs uppercase tracking-widest text-sky-400 mb-2">Composio take-home · AI Product Ops Intern</div>
    <h1 class="text-3xl md:text-4xl font-bold text-white mb-3">Researching 100 apps for agent-toolkit buildability</h1>
    <p class="text-slate-400 max-w-3xl">100 apps across 10 categories, researched by an agent pipeline (not by hand), cross-checked against Composio's own toolkit registry, and hand-verified on a stratified sample. Generated {today} · Pass {pass_used} shown below.</p>
  </header>

  <!-- PATTERNS HEADLINE -->
  <section class="mb-12">
    <h2 class="text-lg font-semibold text-white mb-4 flex items-center gap-2"><span class="text-sky-400">01</span> The patterns</h2>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="rounded-lg border border-slate-800 p-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide">Dominant auth</div>
        <div class="text-2xl font-bold text-white">{esc(patterns['headline']['dominant_auth'][0]) if patterns['headline']['dominant_auth'] else '—'}</div>
        <div class="text-xs text-slate-500">{patterns['headline']['dominant_auth'][1] if patterns['headline']['dominant_auth'] else ''} of {patterns['total_apps']} apps</div>
      </div>
      <div class="rounded-lg border border-slate-800 p-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide">Self-serve overall</div>
        <div class="text-2xl font-bold text-emerald-400">{patterns['headline']['self_serve_pct_overall']}%</div>
      </div>
      <div class="rounded-lg border border-slate-800 p-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide">Gated overall</div>
        <div class="text-2xl font-bold text-amber-400">{patterns['headline']['gated_pct_overall']}%</div>
      </div>
      <div class="rounded-lg border border-slate-800 p-4">
        <div class="text-xs text-slate-500 uppercase tracking-wide">Easy wins today</div>
        <div class="text-2xl font-bold text-white">{patterns['headline']['easy_wins_count']}</div>
        <div class="text-xs text-slate-500">self-serve + buildable now</div>
      </div>
    </div>

    <div class="grid md:grid-cols-2 gap-6">
      <div>
        <h3 class="text-sm font-semibold text-slate-300 mb-2">Auth method distribution</h3>
        <div class="space-y-1.5">{auth_bars}</div>
      </div>
      <div>
        <h3 class="text-sm font-semibold text-slate-300 mb-2">Self-serve % by category</h3>
        <table class="w-full text-sm"><tbody>{cat_summary_rows}</tbody></table>
      </div>
    </div>

    <div class="grid md:grid-cols-3 gap-6 mt-6">
      <div>
        <h3 class="text-sm font-semibold text-slate-300 mb-2">Blocker taxonomy (when not self-serve)</h3>
        <table class="w-full text-sm"><tbody>{blocker_rows}</tbody></table>
      </div>
      <div>
        <h3 class="text-sm font-semibold text-emerald-300 mb-2">Easy wins ({len(patterns['easy_wins'])})</h3>
        <ul class="text-sm max-h-64 overflow-y-auto pr-2">{easy_wins_html}</ul>
      </div>
      <div>
        <h3 class="text-sm font-semibold text-amber-300 mb-2">Needs outreach ({len(patterns['needs_outreach'])})</h3>
        <ul class="text-sm max-h-64 overflow-y-auto pr-2">{outreach_html}</ul>
      </div>
    </div>

    <div class="mt-6 rounded-lg border border-slate-800 p-4 text-sm text-slate-400">
      <span class="text-slate-200 font-medium">Composio cross-reference:</span>
      of the {len(patterns['easy_wins'])} "easy win" apps this research flags as self-serve + buildable now,
      {patterns['easy_wins_already_a_composio_toolkit']} already have a Composio toolkit — validating those verdicts against
      Composio's own shipped decisions. The remaining {len(ew_gap)} are apps that look buildable but Composio hasn't covered yet:
      <ul class="list-disc list-inside mt-2 columns-2 md:columns-3 text-xs">{ew_gap_html}</ul>
    </div>
  </section>

  <!-- FINDINGS TABLE -->
  <section class="mb-12">
    <h2 class="text-lg font-semibold text-white mb-4 flex items-center gap-2"><span class="text-sky-400">02</span> The findings — all 100 apps</h2>
    <div class="flex flex-wrap gap-2 mb-3">
      <input id="search" placeholder="Search app…" class="bg-slate-900 border border-slate-700 rounded px-3 py-1.5 text-sm w-48">
      <select id="f-category" class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm"><option value="">All categories</option></select>
      <select id="f-access" class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm">
        <option value="">All access models</option>
        <option value="self_serve">self_serve</option><option value="gated_paid">gated_paid</option>
        <option value="gated_approval">gated_approval</option><option value="gated_partnership">gated_partnership</option>
        <option value="unclear">unclear</option>
      </select>
      <select id="f-buildable" class="bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm">
        <option value="">All buildability</option>
        <option value="buildable_now">buildable_now</option>
        <option value="buildable_with_workaround">buildable_with_workaround</option>
        <option value="blocked">blocked</option>
      </select>
      <span id="row-count" class="text-xs text-slate-500 self-center ml-auto"></span>
    </div>
    <p class="text-xs text-slate-500 mb-2">Scrolls inside this box — all 100 rows are here, filter or scroll to browse.</p>
    <div class="overflow-auto rounded-lg border border-slate-800" style="max-height:420px">
      <table class="w-full text-sm" id="app-table">
        <thead class="bg-slate-900/95 text-left text-xs text-slate-400 sticky top-0 backdrop-blur">
          <tr>
            <th class="px-3 py-2">App</th><th class="px-3 py-2">Category</th><th class="px-3 py-2">What it does</th>
            <th class="px-3 py-2">Auth</th><th class="px-3 py-2">Access</th><th class="px-3 py-2">Buildable</th>
            <th class="px-3 py-2">Composio toolkit</th><th class="px-3 py-2">Evidence</th>
          </tr>
        </thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>
  </section>

  <!-- THE AGENT -->
  <section class="mb-12">
    <h2 class="text-lg font-semibold text-white mb-4 flex items-center gap-2"><span class="text-sky-400">03</span> The agent</h2>
    <div class="grid md:grid-cols-2 gap-6 text-sm text-slate-300">
      <div class="rounded-lg border border-slate-800 p-4">
        <h3 class="font-semibold text-slate-100 mb-2">What it does (fully automated)</h3>
        <ol class="list-decimal list-inside space-y-1.5 text-slate-400">
          <li><b class="text-slate-200">Registry lookup</b> — checks Composio's public toolkit docs (no API key) for all 100 apps; found 61 already have a toolkit, with Composio's own auth/tool-count metadata.</li>
          <li><b class="text-slate-200">Docs fetch + cache</b> — resolves each app's real developer-docs URL (tries the brief's hint, then conventional docs subpaths), fetches and caches the page text, records the exact source URL used.</li>
          <li><b class="text-slate-200">Structured extraction</b> — batches ~8 apps per call into an LLM (via the Claude Code CLI, subscription-authenticated, no paid API key needed) with a strict JSON schema and a hard "answer only from the page, null beats a guess" rule.</li>
          <li><b class="text-slate-200">Validation</b> — every record is checked: enum fields match, evidence quotes must appear verbatim in the source page (catches fabrication), ids match. Invalid records are rejected, not silently kept.</li>
          <li><b class="text-slate-200">Cross-check</b> — the 61 registry apps get their LLM-extracted auth compared against Composio's own auth field — a second, independent source, for free.</li>
          <li><b class="text-slate-200">Synthesis</b> — clusters the 100 records into the patterns shown above via plain Python aggregation, not another LLM call.</li>
        </ol>
      </div>
      <div class="rounded-lg border border-slate-800 p-4">
        <h3 class="font-semibold text-slate-100 mb-2">Where a human was needed</h3>
        <ul class="list-disc list-inside space-y-1.5 text-slate-400">
          <li>Matching 5 app names to non-obvious Composio slugs (e.g. GoHighLevel → <code class="text-xs bg-slate-800 px-1 rounded">highlevel</code>) and <b class="text-rose-300">rejecting 2 false-positive near-matches</b> (Squarespace ≠ Square; Mermaid CLI ≠ Mermaid Chart MCP) that automated fuzzy-matching surfaced but were the wrong product.</li>
          <li>Discovering that the brief's own hint URL for GoHighLevel (a Stoplight workspace) is dead, and finding the real current docs location by hand.</li>
          <li>Capturing 4 apps' docs via the browser tool by hand — their real developer docs are JS-rendered SPAs that plain HTTP fetch returns empty for (Lark, Gumroad, QuickBooks, GoHighLevel).</li>
          <li>Designing and pre-registering the stratified verification sample (see below) <i>before</i> reading pass-1 results, so it couldn't be biased toward apps the agent got right.</li>
          <li>Every hand-check in Tier 2 below, and turning each confirmed miss into an explicit rule fed back into the pass-2 prompt.</li>
          <li>3 apps the pipeline could not get real evidence for at all: Binance (bot/geo-gated JS docs), Paygent Connect (the brief's own hint isn't a resolvable domain), PitchBook (403, consistent with it being an enterprise contact-sales product) — reported here rather than papered over.</li>
        </ul>
      </div>
    </div>
  </section>

  <!-- VERIFICATION -->
  <section class="mb-12">
    <h2 class="text-lg font-semibold text-white mb-4 flex items-center gap-2"><span class="text-sky-400">04</span> Verification — is any of this trustworthy?</h2>
    <p class="text-sm text-slate-400 mb-4 max-w-3xl">Two independent tiers. Tier 1 is machine cross-checking against Composio's own registry (free, covers 61 apps). Tier 2 is a human, using the browser tool, hand-checking a 22-app sample against real vendor docs — the sample was picked and written down <i>before</i> pass 1 was read, so it can't be cherry-picked to look good.</p>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">{tier1_html}{tier2_html}</div>

    <h3 class="text-sm font-semibold text-slate-300 mt-6 mb-1">Pass 1 misses (hand-verified sample)</h3>
    {misses_p1}
    <h3 class="text-sm font-semibold text-slate-300 mt-6 mb-1">Pass 2 misses (after hardening the prompt)</h3>
    {misses_p2}
  </section>

  <!-- PROOF -->
  <section class="mb-12">
    <h2 class="text-lg font-semibold text-white mb-4 flex items-center gap-2"><span class="text-sky-400">05</span> Proof</h2>
    <div class="grid md:grid-cols-2 gap-4 text-sm">
      <a href="https://github.com/maggie7745/composio-app-research" target="_blank" class="rounded-lg border border-slate-800 p-4 hover:border-sky-600 transition block">
        <div class="text-slate-200 font-medium mb-1">📦 Source repo</div>
        <div class="text-slate-500 text-xs">Full pipeline, README with run instructions, all data files.</div>
      </a>
      <a href="https://github.com/maggie7745/composio-app-research#readme" target="_blank" class="rounded-lg border border-slate-800 p-4 hover:border-sky-600 transition block">
        <div class="text-slate-200 font-medium mb-1">▶️ Runnable trigger</div>
        <div class="text-slate-500 text-xs">python agent/fetch_docs.py → extract.py → crosscheck.py → synthesize.py → build_site.py</div>
      </a>
    </div>
  </section>

  <footer class="text-xs text-slate-600 border-t border-slate-800 pt-6 mt-10">
    Built for the Composio AI Product Ops Intern take-home. All evidence links are the actual fetched source URLs; apps with no verifiable page are marked "unverified" rather than guessed.
  </footer>

<script>
  const rows = [...document.querySelectorAll('.app-row')];
  const catSel = document.getElementById('f-category');
  const cats = [...new Set(rows.map(r => r.dataset.category))].sort();
  cats.forEach(c => {{ const o = document.createElement('option'); o.value = c; o.textContent = c; catSel.appendChild(o); }});

  function applyFilters() {{
    const q = document.getElementById('search').value.toLowerCase();
    const cat = catSel.value, acc = document.getElementById('f-access').value, build = document.getElementById('f-buildable').value;
    let shown = 0;
    rows.forEach(r => {{
      const ok = (!q || r.dataset.name.includes(q)) &&
                 (!cat || r.dataset.category === cat) &&
                 (!acc || r.dataset.access === acc) &&
                 (!build || r.dataset.buildable === build);
      r.style.display = ok ? '' : 'none';
      if (ok) shown++;
    }});
    document.getElementById('row-count').textContent = shown + ' / ' + rows.length + ' apps';
  }}
  ['search','f-category','f-access','f-buildable'].forEach(id => {{
    document.getElementById(id).addEventListener('input', applyFilters);
  }});
  applyFilters();
</script>
</body>
</html>"""

    out = ROOT / "site" / "index.html"
    out.write_text(page)
    print(f"wrote {out}  ({len(page):,} bytes)")


if __name__ == "__main__":
    main()
