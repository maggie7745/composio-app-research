"""
Phase 4 - Pattern synthesis. The actual point of the assignment: cluster the
100 rows into insight, not just present them.

Reads data/results_pass{N}.json + data/apps.json + data/composio_registry.json,
writes data/patterns.json:

  - auth method distribution (which auth dominates)
  - self-serve % by category (which categories are self-serve vs gated)
  - blocker taxonomy (the most common blocker, via keyword clustering over the
    free-text `blocker` field -- simple on purpose, see cluster_blocker())
  - easy wins: self-serve + documented API + buildable now, today, no outreach needed
  - needs outreach: gated behind paid/approval/partnership
  - cross-reference against the Composio registry: how many "easy wins" are
    already toolkits (validates the buildability verdict against Composio's
    own shipped decisions) vs. how many are gaps Composio hasn't covered yet

Run:  python agent/synthesize.py [--pass 2]
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Keyword -> blocker bucket. Order matters: first match wins, so more specific
# buckets are listed before generic ones. This is a simple classifier over
# free text the model wrote, not a second LLM call -- deliberately legible
# and auditable rather than another black box on top of the first one.
BLOCKER_TAXONOMY = [
    ("contact_sales_or_partnership", ["contact sales", "partnership", "partner program",
                                       "reach out", "request access", "sales team", "book a demo",
                                       "talk to sales", "get in touch"]),
    ("paid_plan_required", ["paid plan", "premium", "upgrade", "subscription required",
                             "paid tier", "enterprise plan", "paywall"]),
    ("admin_approval_required", ["admin approval", "org admin", "workspace admin",
                                  "app review", "approval process", "app must be installed",
                                  "review process"]),
    ("no_public_docs", ["no api documentation", "no public", "not documented",
                         "no developer", "could not find", "not publicly",
                         "no evidence of", "page does not"]),
    ("enterprise_only", ["enterprise only", "enterprise-only", "enterprise tier",
                          "enterprise customers", "enterprise plan"]),
    ("fetch_or_evidence_failure", ["fetch fail", "no page", "unable to access",
                                    "unable to fetch", "blocked", "403", "bot protection"]),
]


def cluster_blocker(text: str | None) -> str:
    if not text:
        return "none_or_not_applicable"
    low = text.lower()
    for bucket, keywords in BLOCKER_TAXONOMY:
        if any(k in low for k in keywords):
            return bucket
    return "other_unclassified"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pass_n", type=int, default=1)
    args = ap.parse_args()

    apps = {a["id"]: a for a in json.loads((ROOT / "data" / "apps.json").read_text())["apps"]}
    results_path = ROOT / "data" / f"results_pass{args.pass_n}.json"
    results = {r["id"]: r for r in json.loads(results_path.read_text())}
    registry = json.loads((ROOT / "data" / "composio_registry.json").read_text())

    rows = []
    for app_id, app in apps.items():
        rec = results.get(app_id, {})
        reg = registry.get(str(app_id), {})
        rows.append({
            "id": app_id, "name": app["name"], "category": app["category"],
            "auth_methods": rec.get("auth_methods") or [],
            "access_model": rec.get("access_model") or "unclear",
            "buildable_verdict": rec.get("buildable_verdict") or "unclear",
            "blocker_bucket": cluster_blocker(rec.get("blocker")),
            "blocker_raw": rec.get("blocker"),
            "has_official_mcp": rec.get("has_official_mcp"),
            "in_composio_registry": reg.get("in_composio_registry", False),
            "composio_tools": reg.get("composio_tools"),
            "fetched": rec.get("fetched", False),
            "confidence": rec.get("confidence"),
        })

    total = len(rows)

    # --- auth distribution ---------------------------------------------
    auth_counter = Counter()
    for r in rows:
        for a in r["auth_methods"]:
            auth_counter[a] += 1
    no_auth_data = sum(1 for r in rows if not r["auth_methods"])

    # --- access model distribution + by category -------------------------
    access_counter = Counter(r["access_model"] for r in rows)
    by_category = defaultdict(lambda: Counter())
    for r in rows:
        by_category[r["category"]][r["access_model"]] += 1

    category_summary = []
    for cat, counter in by_category.items():
        cat_total = sum(counter.values())
        self_serve = counter.get("self_serve", 0)
        category_summary.append({
            "category": cat, "total": cat_total,
            "self_serve": self_serve,
            "self_serve_pct": round(100 * self_serve / cat_total, 1) if cat_total else 0,
            "gated_paid": counter.get("gated_paid", 0),
            "gated_approval": counter.get("gated_approval", 0),
            "gated_partnership": counter.get("gated_partnership", 0),
            "unclear": counter.get("unclear", 0),
        })
    category_summary.sort(key=lambda c: -c["self_serve_pct"])

    # --- blocker taxonomy -------------------------------------------------
    blocker_counter = Counter(r["blocker_bucket"] for r in rows)

    # --- buildability verdicts --------------------------------------------
    verdict_counter = Counter(r["buildable_verdict"] for r in rows)

    # --- easy wins vs needs outreach ---------------------------------------
    easy_wins = [r for r in rows if r["access_model"] == "self_serve"
                 and r["buildable_verdict"] == "buildable_now"]
    needs_outreach = [r for r in rows if r["access_model"] in
                      ("gated_paid", "gated_approval", "gated_partnership")]

    # --- Composio cross-reference -------------------------------------------
    easy_win_ids = {r["id"] for r in easy_wins}
    easy_win_already_toolkit = sum(1 for r in easy_wins if r["in_composio_registry"])
    easy_win_gap = [r for r in easy_wins if not r["in_composio_registry"]]

    gated_but_in_registry = [r for r in needs_outreach if r["in_composio_registry"]]

    patterns = {
        "pass": args.pass_n,
        "total_apps": total,
        "headline": {
            "dominant_auth": auth_counter.most_common(1)[0] if auth_counter else None,
            "self_serve_pct_overall": round(100 * access_counter.get("self_serve", 0) / total, 1),
            "gated_pct_overall": round(100 * sum(access_counter.get(k, 0) for k in
                ("gated_paid", "gated_approval", "gated_partnership")) / total, 1),
            "top_blocker": blocker_counter.most_common(2),
            "easy_wins_count": len(easy_wins),
            "needs_outreach_count": len(needs_outreach),
        },
        "auth_distribution": dict(auth_counter.most_common()),
        "apps_with_no_auth_data_extracted": no_auth_data,
        "access_model_distribution": dict(access_counter),
        "self_serve_by_category": category_summary,
        "blocker_taxonomy": dict(blocker_counter.most_common()),
        "buildability_verdicts": dict(verdict_counter),
        "easy_wins": sorted(easy_wins, key=lambda r: r["name"]),
        "easy_wins_already_a_composio_toolkit": easy_win_already_toolkit,
        "easy_wins_composio_gap": sorted(easy_win_gap, key=lambda r: r["name"]),
        "needs_outreach": sorted(needs_outreach, key=lambda r: r["name"]),
        "needs_outreach_but_composio_already_shipped_it": sorted(
            gated_but_in_registry, key=lambda r: r["name"]),
        "rows": rows,
    }

    out_path = ROOT / "data" / "patterns.json"
    out_path.write_text(json.dumps(patterns, indent=2) + "\n")

    print(f"wrote {out_path}")
    print(f"\nHEADLINE (pass {args.pass_n}, {total} apps):")
    print(f"  dominant auth: {patterns['headline']['dominant_auth']}")
    print(f"  self-serve overall: {patterns['headline']['self_serve_pct_overall']}%")
    print(f"  gated overall: {patterns['headline']['gated_pct_overall']}%")
    print(f"  top blockers: {patterns['headline']['top_blocker']}")
    print(f"  easy wins: {len(easy_wins)}  ({easy_win_already_toolkit} already a Composio toolkit, "
          f"{len(easy_win_gap)} are a gap)")
    print(f"  needs outreach: {len(needs_outreach)}  ({len(gated_but_in_registry)} Composio shipped anyway)")
    print("\nself-serve % by category:")
    for c in category_summary:
        print(f"  {c['category']:38s} {c['self_serve_pct']:5.1f}%  ({c['self_serve']}/{c['total']})")


if __name__ == "__main__":
    main()
