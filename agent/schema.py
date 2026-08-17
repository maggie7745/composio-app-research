"""
Shared extraction schema. One place, so extract.py (writes it), crosscheck.py
(reads composio_auth_list against it), and build_site.py (renders it) never
drift from each other.
"""

AUTH_ENUM = ["OAUTH2", "API_KEY", "BASIC", "BEARER_TOKEN", "NO_AUTH", "OTHER"]
ACCESS_MODEL_ENUM = ["self_serve", "gated_paid", "gated_approval",
                     "gated_partnership", "unclear"]
API_STYLE_ENUM = ["REST", "GraphQL", "REST_and_GraphQL", "other", "unclear"]
BUILDABLE_ENUM = ["buildable_now", "buildable_with_workaround", "blocked"]

# Field -> (required, type-check fn). Used by extract.py's validator.
REQUIRED_FIELDS = [
    "id", "one_liner", "auth_methods", "access_model", "access_evidence",
    "api_surface", "api_style", "has_official_mcp", "mcp_evidence",
    "buildable_verdict", "blocker", "rate_limits",
    "paid_tier_required_for_api", "sandbox_available", "confidence",
    "evidence_quote",
]

RECORD_SCHEMA_TEXT = """{
  "id": <int, must match the app id given>,
  "one_liner": <string, <=20 words, what the app does>,
  "auth_methods": [<zero or more of: OAUTH2, API_KEY, BASIC, BEARER_TOKEN, NO_AUTH, OTHER>],
  "access_model": <one of: self_serve, gated_paid, gated_approval, gated_partnership, unclear>,
  "access_evidence": <string, 1 sentence explaining the access_model verdict, or null>,
  "api_surface": <string, e.g. "REST, ~40 endpoints across contacts/deals" or "not documented publicly">,
  "api_style": <one of: REST, GraphQL, REST_and_GraphQL, other, unclear>,
  "has_official_mcp": <true, false, or null if the page does not say>,
  "mcp_evidence": <string or null>,
  "buildable_verdict": <one of: buildable_now, buildable_with_workaround, blocked>,
  "blocker": <string, the main blocker if not buildable_now, else null>,
  "rate_limits": <string describing rate limits if stated, else null>,
  "paid_tier_required_for_api": <true, false, or null if unclear>,
  "sandbox_available": <true, false, or null if unclear>,
  "confidence": <float 0.0-1.0, your own confidence in this record>,
  "evidence_quote": <string, copied VERBATIM from the page text below, backing your access_model verdict; null only if the page truly has nothing usable>
}"""

BASE_RULES = """You are extracting structured facts about developer APIs from real fetched documentation pages, for a research database an agent-toolkit team will rely on.

Hard rules, no exceptions:
1. Answer ONLY from the PAGE TEXT given for each app. Never use outside knowledge of the company, even if you are confident you know the answer.
2. If the page text does not state something, output null for that field. A plausible guess is a wrong answer here -- null is correct and expected to happen often.
3. evidence_quote must be copied verbatim (exact substring) from the page text you were given for that app. Do not paraphrase it into the quote field.
4. "self_serve" means the page describes a developer being able to sign up / get an API key / start a free trial without contacting sales or needing admin approval. Words like "login" or "connect your account" alone are NOT evidence of self-serve OAuth -- look for actual developer-facing signup/key-generation language. If the page only shows END-USER login (not a developer registering an app), do not call that self-serve API access.
5. "gated_partnership" requires actual evidence of a contact-sales / partner-application / request-access gate -- a marketing page alone being scarce on detail is not evidence of gating; in that case use "unclear".
6. Output a JSON array with exactly one object per app, in the same order given, matching the schema below. No prose before or after the array, no markdown code fence.

SCHEMA (per app):
""" + RECORD_SCHEMA_TEXT
