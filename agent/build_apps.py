"""
Phase 1 - Data prep.

Turns the 100 apps from the assignment brief into data/apps.json.

Everything here is transcribed verbatim from the PDF's tables: app name, the
"Website / hint" column, and any parenthetical the brief added. Nothing is
inferred at this stage on purpose -- the research agent has to discover the
rest itself, so that apps.json stays a clean record of "what we were given"
rather than a place where a human quietly pre-answered the questions.

Run:  python agent/build_apps.py
"""

import json
import pathlib
import re

# (name, hint from brief's "Website / hint" column, brief's parenthetical or "")
CATEGORIES = {
    "CRM and Sales": [
        ("Salesforce",                  "salesforce.com", ""),
        ("HubSpot",                     "hubspot.com", ""),
        ("Pipedrive",                   "pipedrive.com", ""),
        ("Attio",                       "attio.com", ""),
        ("Twenty",                      "twenty.com", "open-source CRM"),
        ("Podio",                       "podio.com", ""),
        ("Zoho CRM",                    "zoho.com/crm", ""),
        ("Close",                       "close.com", ""),
        ("Copper",                      "copper.com", ""),
        ("DealCloud",                   "api.docs.dealcloud.com", ""),
    ],
    "Support and Helpdesk": [
        ("Zendesk",                     "zendesk.com", ""),
        ("Intercom",                    "intercom.com", ""),
        ("Freshdesk",                   "freshdesk.com", ""),
        ("Front",                       "front.com", ""),
        ("Pylon",                       "usepylon.com", ""),
        ("LiveAgent",                   "liveagent.com", ""),
        ("Plain",                       "plain.com", ""),
        ("Help Scout",                  "helpscout.com", ""),
        ("Gorgias",                     "gorgias.com", ""),
        ("Gladly",                      "gladly.com", ""),
    ],
    "Communications and Messaging": [
        ("Slack",                       "slack.com", ""),
        ("Twilio",                      "twilio.com", ""),
        ("Zoho Cliq",                   "zoho.com/cliq", ""),
        ("Lark (Larksuite)",            "open.larksuite.com", ""),
        ("Pumble",                      "pumble.com", ""),
        ("Discord",                     "discord.com", ""),
        ("Telegram",                    "core.telegram.org", ""),
        ("WhatsApp Business",           "developers.facebook.com/docs/whatsapp", ""),
        ("Aircall",                     "aircall.io", ""),
        ("Vonage",                      "developer.vonage.com", ""),
    ],
    "Marketing, Ads, Email and Social": [
        ("Google Ads",                  "developers.google.com/google-ads", ""),
        ("Meta Ads",                    "developers.facebook.com/docs/marketing-apis", ""),
        ("LinkedIn Ads",                "learn.microsoft.com/linkedin/marketing", ""),
        ("GoHighLevel",                 "highlevel.stoplight.io", ""),
        ("Mailchimp",                   "mailchimp.com/developer", ""),
        ("Klaviyo",                     "developers.klaviyo.com", ""),
        ("systeme.io",                  "systeme.io", "funnel builder"),
        ("Pinterest",                   "developers.pinterest.com", ""),
        ("Threads (Meta)",              "developers.facebook.com/docs/threads", ""),
        ("SendGrid",                    "sendgrid.com", ""),
    ],
    "Ecommerce": [
        ("Shopify",                     "shopify.dev", ""),
        ("WooCommerce",                 "woocommerce.com/document/woocommerce-rest-api", ""),
        ("BigCommerce",                 "developer.bigcommerce.com", ""),
        ("Salesforce Commerce Cloud",   "developer.salesforce.com/docs/commerce", ""),
        ("Magento (Adobe Commerce)",    "developer.adobe.com/commerce", ""),
        ("Squarespace",                 "developers.squarespace.com", ""),
        ("Ecwid",                       "api-docs.ecwid.com", ""),
        ("Gumroad",                     "gumroad.com/api", ""),
        ("Amazon Selling Partner",      "developer-docs.amazon.com/sp-api", ""),
        ("fanbasis",                    "fanbasis.com", ""),
    ],
    "Data, SEO and Scraping": [
        ("DataForSEO",                  "docs.dataforseo.com", ""),
        ("SE Ranking",                  "seranking.com/api", ""),
        ("Ahrefs",                      "ahrefs.com/api", ""),
        ("MrScraper",                   "docs.mrscraper.com", ""),
        ("Apify",                       "docs.apify.com", ""),
        ("Firecrawl",                   "firecrawl.dev", ""),
        ("Bright Data",                 "brightdata.com", ""),
        ("Sherlock",                    "github.com/sherlock-project/sherlock", ""),
        ("Waterfall.io",                "waterfall.io", "contact/company intel"),
        ("Clay",                        "clay.com", ""),
    ],
    "Developer, Infra and Data platforms": [
        ("GitHub",                      "docs.github.com/rest", ""),
        ("Vercel",                      "vercel.com/docs/rest-api", ""),
        ("Netlify",                     "docs.netlify.com/api", ""),
        ("Cloudflare",                  "developers.cloudflare.com/api", ""),
        ("Supabase",                    "supabase.com/docs", ""),
        ("Neo4j",                       "neo4j.com/docs/api", ""),
        ("Snowflake",                   "docs.snowflake.com", ""),
        ("MongoDB Atlas",               "mongodb.com/docs/atlas/api", ""),
        ("Datadog",                     "docs.datadoghq.com/api", ""),
        ("Sentry",                      "docs.sentry.io/api", ""),
    ],
    "Productivity and Project Management": [
        ("Notion",                      "developers.notion.com", ""),
        ("Airtable",                    "airtable.com/developers", ""),
        ("Linear",                      "developers.linear.app", ""),
        ("Jira",                        "developer.atlassian.com", ""),
        ("Asana",                       "developers.asana.com", ""),
        ("Monday.com",                  "developer.monday.com", ""),
        ("ClickUp",                     "clickup.com/api", ""),
        ("Coda",                        "coda.io/developers", ""),
        ("Smartsheet",                  "smartsheet.com/developers", ""),
        ("Harvest",                     "harvestapp.com", "help.getharvest.com/api-v2"),
    ],
    "Finance and Fintech": [
        ("Stripe",                      "stripe.com/docs/api", ""),
        ("Plaid",                       "plaid.com/docs", ""),
        ("Binance",                     "binance-docs.github.io", ""),
        ("Paygent Connect",             "paygent", "NMI-powered"),
        ("iPayX",                       "ipayx.ai/docs", ""),
        ("QuickBooks",                  "developer.intuit.com", ""),
        ("Xero",                        "developer.xero.com", ""),
        ("Brex",                        "developer.brex.com", ""),
        ("Ramp",                        "docs.ramp.com", ""),
        ("PitchBook",                   "pitchbook.com", "research API"),
    ],
    "AI, Research and Media-native": [
        ("NotebookLM",                  "cloud.google.com/gemini", "Enterprise API"),
        ("Otter AI",                    "help.otter.ai", "MCP server"),
        ("Fathom",                      "fathom.video", ""),
        ("Consensus",                   "consensus.app", "OAuth requested"),
        ("Reducto",                     "reducto.ai", "document parsing"),
        ("Devin",                       "docs.devin.ai", "MCP"),
        ("higgsfield",                  "higgsfield.ai/cli", "content suite"),
        ("Mermaid CLI",                 "github.com/mermaid-js/mermaid-cli", ""),
        ("YouTube Transcript",          "transcriptapi.com", ""),
        ("Grain",                       "grain.com", "meeting notes"),
    ],
}

# Fields the research agent is responsible for filling in. Listed here so the
# schema is declared in one place and the extraction prompt can be generated
# from it rather than drifting from it.
RESEARCH_FIELDS = [
    "one_liner",
    "auth_methods",
    "access_model",
    "access_evidence",
    "api_surface",
    "api_breadth",
    "has_official_mcp",
    "mcp_evidence",
    "in_composio_registry",
    "buildable",
    "blocker",
    "rate_limits",
    "paid_tier_required_for_api",
    "sandbox_available",
    "sources",
]


def slugify(name: str) -> str:
    """Best-effort Composio toolkit slug, e.g. 'Zoho CRM' -> 'zoho_crm'.

    A guess only. The agent confirms it against the live Composio toolkit list
    and overwrites `composio_slug` with the real one (or null) in pass 1.
    """
    s = name.lower()
    s = re.sub(r"\(.*?\)", "", s)          # drop "(Meta)", "(Larksuite)" etc.
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def normalize_url(hint: str) -> str | None:
    """The brief's hint column mixes bare domains, paths, and one non-URL."""
    if not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}", hint):
        return None                        # e.g. "paygent" -- not a URL
    return "https://" + hint


def build() -> list[dict]:
    apps, app_id = [], 0
    for cat_idx, (category, entries) in enumerate(CATEGORIES.items(), start=1):
        for name, hint, note in entries:
            app_id += 1
            url = normalize_url(hint)
            apps.append({
                "id": app_id,
                "name": name,
                "category": category,
                "category_id": cat_idx,
                # --- given by the brief, verbatim ---
                "hint_raw": hint,
                "hint_url": url,
                "hint_note": note,
                # True when the brief already pointed at developer docs, so the
                # agent can skip the docs-discovery step. Tracked because it
                # affects how much work the agent actually did per app.
                "hint_is_docs_url": bool(url) and bool(
                    re.search(r"develop|docs|/api|/rest|api\.|open\.", hint)
                ),
                # --- to be filled by the agent ---
                "composio_slug_guess": slugify(name),
                "research": {f: None for f in RESEARCH_FIELDS},
            })
    return apps


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    apps = build()
    assert len(apps) == 100, f"expected 100 apps, built {len(apps)}"
    assert len({a["name"] for a in apps}) == 100, "duplicate app name"

    out = root / "data" / "apps.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "source": "AI Product Ops Intern - take-home assignment brief (PDF), 'The 100 apps (research set)'",
        "count": len(apps),
        "categories": list(CATEGORIES),
        "research_fields": RESEARCH_FIELDS,
        "apps": apps,
    }, indent=2) + "\n")

    no_url = [a["name"] for a in apps if not a["hint_url"]]
    seeded = sum(a["hint_is_docs_url"] for a in apps)
    print(f"wrote {out}  ({len(apps)} apps, {len(CATEGORIES)} categories)")
    print(f"  hints that are already developer-docs URLs: {seeded}/100")
    print(f"  hints that are not URLs at all: {no_url or 'none'}")


if __name__ == "__main__":
    main()
