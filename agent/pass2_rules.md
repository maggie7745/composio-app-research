<!--
Hardened rules for pass 2, each one traced to a real pass-1 failure found via
Tier-1 automated crosscheck (data/crosscheck_pass1.json, 58 registry apps,
10.3% agreement) and spot-checks against the raw fetched pages. Not
hypothetical -- every rule below names the app it came from.
-->

1. **Nav-shell / thin-page problem (the dominant failure, ~39/58 registry
   apps showed `auth_methods: []`).** This was a FETCH bug, not a prompt bug:
   `docs.github.com/rest` fetched cleanly (HTTP 200, 1744 chars) but that page
   is a table-of-contents shell -- it contains the phrase "Authenticating to
   the REST API" only as a truncated link title, not real content. The model
   correctly refused to guess rather than fabricate, which is why the
   crosscheck showed empty answers instead of wrong ones -- but empty is
   still a miss. **Fixed at the pipeline level**, not the prompt: `is_thin()`
   now flags any page under 3000 chars regardless of keyword hits, and
   `find_auth_link()` parses the thin page's own `<a>` tags and follows the
   one that actually looks like the auth page (e.g. GitHub's index page
   links straight to `/en/rest/authentication/authenticating-to-the-rest-api`,
   9783 chars of real content) instead of guessing conventional paths blind.
   Re-fetching all 100 with this fix is what pass 2's `data/pages/` reflects.

2. **Stop-at-first-auth-method.** Sentry (`docs.sentry.io/api`) and Asana
   (`developers.asana.com`) both document TWO separate auth paths: a personal
   API token for quick scripts, and a separate OAuth2 flow for building
   public/third-party integrations. Pass 1 read the token quickstart, reported
   `auth_methods: ["API_KEY"]`, and stopped -- missing the OAuth2 path
   entirely (Composio's own registry lists both for each). Rule: if the page
   describes more than one way to authenticate (a personal-token/quickstart
   path AND a separate app-registration/OAuth path), report ALL of them in
   auth_methods, not just the first one you find.

3. **Generic CTA accepted as auth evidence.** YouTube Transcript
   (transcriptapi.com) got `auth_methods: ["API_KEY", "BEARER_TOKEN"]` with
   `evidence_quote: "Get Started Free"` -- a signup button, not a statement
   about how auth actually works. Rule: `evidence_quote` must contain the
   actual auth mechanism by name (the words "API key", "OAuth", "Bearer",
   "token", "Basic auth", etc. used to describe HOW you authenticate) -- a
   generic signup/pricing call-to-action is NOT evidence for any specific
   auth_methods value. If that is the only evidence on the page, auth_methods
   should be `[]`, not a guess dressed up with an unrelated quote.
