"""
Phase 3, Tier 1 - automated cross-check.

For the 61 apps that already have a Composio toolkit, we have two independent
readings of the auth method:

  1. The extraction agent's answer, read off the VENDOR's own docs page.
  2. Composio's own `Auth:` field, published on their toolkit doc page --
     presumably derived from actually building and shipping that integration.

These are genuinely independent (different source, different process), so
agreement between them is real signal, not a rubber stamp. This is Tier 1 of
the verification loop: free, covers 61/100 apps (vs. ~18 a human can hand-check
in the time budget), and its job is less "prove the LLM is right" and more
"find the disagreements worth a human's limited time" -- Tier 2 samples those
disagreements first.

No credentials required -- reads files already on disk from
composio_registry.py and extract.py.

Run:  python agent/crosscheck.py [--pass 1]
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Composio's auth vocabulary and ours don't fully align (they distinguish
# S2S_OAUTH2 from OAUTH2, use DCR_OAUTH for a couple of MCP-native toolkits,
# etc). This maps their tokens onto our AUTH_ENUM so "agreement" means the
# same real-world thing rather than penalizing a naming difference.
COMPOSIO_TO_OUR_ENUM = {
    "OAUTH2": "OAUTH2", "S2S_OAUTH2": "OAUTH2", "DCR_OAUTH": "OAUTH2",
    "OAUTH1": "OAUTH2",
    "API_KEY": "API_KEY", "BASIC": "BASIC", "BEARER_TOKEN": "BEARER_TOKEN",
    "NO_AUTH": "NO_AUTH",
}


def normalize(composio_auth_list: list[str] | None) -> set[str]:
    if not composio_auth_list:
        return set()
    return {COMPOSIO_TO_OUR_ENUM.get(a, "OTHER") for a in composio_auth_list}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass", dest="pass_n", type=int, default=1)
    args = ap.parse_args()

    results_path = ROOT / "data" / f"results_pass{args.pass_n}.json"
    if not results_path.exists():
        raise SystemExit(f"{results_path} not found -- run extract.py first")

    results = {r["id"]: r for r in json.loads(results_path.read_text())}
    registry = json.loads((ROOT / "data" / "composio_registry.json").read_text())

    checked, agree, disagree, skipped_no_registry, skipped_no_extract = [], [], [], [], []

    for app_id_str, reg in registry.items():
        app_id = int(app_id_str)
        if not reg.get("in_composio_registry"):
            skipped_no_registry.append(reg["name"])
            continue
        rec = results.get(app_id)
        if rec is None:
            skipped_no_extract.append(reg["name"])
            continue

        composio_set = normalize(reg.get("composio_auth_list"))
        our_set = normalize(rec.get("auth_methods"))
        row = {
            "id": app_id, "name": reg["name"], "category": reg["category"],
            "composio_auth": reg.get("composio_auth_list"),
            "our_auth": rec.get("auth_methods"),
            "composio_normalized": sorted(composio_set),
            "our_normalized": sorted(our_set),
            "our_confidence": rec.get("confidence"),
            "our_evidence_quote": rec.get("evidence_quote"),
            "our_source_url": rec.get("source_url"),
            "composio_doc_url": reg.get("composio_doc_url"),
        }
        checked.append(row)

        if not our_set:
            # We answered null/empty -- not a contradiction, just "no data
            # extracted." Worth a human look (are we under-extracting?) but
            # it's a different failure mode than an active disagreement.
            row["verdict"] = "we_extracted_nothing"
            disagree.append(row)
        elif our_set == composio_set:
            row["verdict"] = "agree"
            agree.append(row)
        elif our_set & composio_set:
            row["verdict"] = "partial_overlap"
            disagree.append(row)
        else:
            row["verdict"] = "disagree"
            disagree.append(row)

    has_overlap = sum(1 for r in checked if r["verdict"] in ("agree", "partial_overlap"))

    out = {
        "pass": args.pass_n,
        "checked": len(checked),
        "agree": len(agree),
        "disagree_or_partial": len(disagree),
        "agreement_rate": round(len(agree) / len(checked), 3) if checked else None,
        "overlap_rate": round(has_overlap / len(checked), 3) if checked else None,
        "overlap_rate_note": "exact-match agreement understates real accuracy: Composio's Auth field "
            "is a terse one-line summary and often omits a secondary method the vendor's own page "
            "documents (e.g. GitHub's page genuinely describes both OAuth2 AND personal-access-token "
            "auth; Composio's field lists only OAUTH2). overlap_rate counts any shared method as a "
            "correct partial hit, which is the fairer number; agreement_rate (exact set equality) is "
            "kept alongside it rather than hidden, since it's the stricter and more conservative claim.",
        "skipped_not_in_composio_registry": len(skipped_no_registry),
        "skipped_no_extraction_yet": skipped_no_extract,
        "rows": sorted(checked, key=lambda r: (r["verdict"] != "agree", r["name"])),
    }
    out_path = ROOT / "data" / f"crosscheck_pass{args.pass_n}.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")

    print(f"cross-checked {len(checked)}/{sum(1 for r in registry.values() if r['in_composio_registry'])} "
          f"registry apps against pass {args.pass_n} extraction")
    print(f"  agree:    {len(agree)}")
    print(f"  disagree/partial/empty: {len(disagree)}")
    if checked:
        print(f"  agreement rate: {out['agreement_rate']*100:.1f}%")
    print(f"\nwrote {out_path}")
    if disagree:
        print("\ndisagreements (prioritize these for Tier 2 human review):")
        for r in disagree:
            print(f"  - {r['name']:24s} composio={r['composio_normalized']}  ours={r['our_normalized']}  ({r['verdict']})")


if __name__ == "__main__":
    main()
