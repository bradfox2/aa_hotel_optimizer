# Implementation follow-through

Branch: `feature/paid-beta`. The original audit describes commit `66678a3` and
remains unchanged as historical evidence. This document describes the new code.

## Corrected and implemented

| Audit findings | Result |
| --- | --- |
| F01 | Added complete-trip interval comparison, including mixed booking lengths, budget, full night coverage and hotel-change constraints. The original one-night workflow remains available. |
| F02–F05 | Explicit, dated promotion eligibility replaces inferred threshold crossings. Bonus allowance is shared across the plan; LP bonuses do not add redeemable miles. All legacy strategies return a consistent projected balance. |
| F06–F07 | Minimum-cost selection retains cheaper offers on the same date and includes active bonus capacity in its state. Randomized small cases match exhaustive enumeration. |
| F08–F09 | Paginated collection, finite completion/retry states, row-level normalization and invalid-price/currency rejection. A truncated or failed search does not become a completed plan. |
| F10–F11 | Quoted cURL/header variants and browser cookie flags are parsed without shell execution. Header allowlist, redacted errors, ignored credential files and no import-time root logging. The new service never accepts AA session headers. |
| F12 | Input/combination/state/request bounds, one active search per account, task lease attempts, provider spacing/backoff and server-enforced account allowances. Production concurrency/edge limits still need deployment validation. |
| F13 | Streamlit preserves its previous result across reruns; the service persists owned searches, quotes and plans in SQL. |
| F14 | Email-link app sign-in and a functioning Chrome companion replace the consumer cURL workflow. Full browser tests load the real extension. Store publication and live-account compatibility remain open. |
| F15 | Service statuses distinguish running, reconnect, no results, failed and cancelled. Incomplete legacy date/city fetches now stop the search. |
| F16 | Application accounts, scoped keys, ownership, durable tasks, Stripe integration, entitlement enforcement, hosted cancellation, account export/deletion and typed agent API. |
| F17 | Removed development-container flags disabling CORS and XSRF protections. |
| F18 | Refreshed dependencies and lockfile. A scan of the exported runtime requirements reported zero known vulnerabilities. This is a scan result, not proof that the app has no security defects. |
| F19 | Stable normalized offer identities and set-based deduplication replace quadratic matching. |
| F22 | Python 3.12 service environment, package entry point, wheel, local run commands, migration history, documentation and CI checks. |

## Still open or intentionally limited

- **F20:** Quotes have property/rate identifiers and observation times, and saved
  plans can be refreshed through a new search. A verified booking deep link and
  a provider-confirmed offer revalidation endpoint are not implemented. “Open AA
  Hotels” opens the actual provider homepage; it does not pretend to book a rate.
- **F21:** The browser design keeps AA sessions local, but does not establish a
  permitted commercial data agreement. The extension is packaged, not published.
  Default development live acquisition is disabled until explicitly enabled.
- **F23:** The provider `rewards` field remains an estimated base-LP input until
  its personalized breakdown is verified against a real account. Status windows
  cannot combine nights across March 1, but full posting-date and qualification
  modeling is not implemented. Card-spend timing and no-show eligibility are
  disclosed assumptions; the app makes no guarantee of posting or status.
- Real Stripe payments/webhook delivery, SMTP delivery and PostgreSQL runtime
  integration require configured external services. Automated billing tests use
  real signature verification with simulated Stripe API responses.
- Phone layouts work; live AA acquisition requires a connected desktop Chromium
  browser. Independent phone-only live search is not implemented.
- Customer terms, operator/support details, retention/refund policy, tax setup,
  backups, alerting and staging validation remain release work. See
  [B2C_BETA.md](../../B2C_BETA.md).

## Verification

- `pytest`: 40 passing tests covering optimization, reward dates/caps, exhaustive
  cost comparisons, invalid quotes, legacy paging/horizon, auth, tenant isolation,
  scopes, CSRF, request size, task replay/expiry, quotas, cancellation, deletion,
  webhook signatures/duplicates/order, duplicate-checkout prevention, trip-pass
  payment/refund/dispute accounting, email delivery boundaries and staging controls.
- Full Playwright flow: actual MV3 companion in a fresh browser profile, mocked
  AA endpoints, app sign-in, key creation/revocation, companion pairing, completed
  browser-driven search, persistence/reload/export, status search, phone layout,
  account deletion and no JavaScript errors. No real AA credentials were used.
- Streamlit AppTest: startup, mocked search rendering, and result persistence after
  a widget change, with no runtime exceptions.
- Ruff lint/format and JavaScript syntax checks; installable wheel includes the
  customer UI and locally served licensed fonts.
- All three Alembic revisions apply cleanly on SQLite and leave no model/schema drift.
  PostgreSQL migration SQL can be generated offline; no PostgreSQL server was
  provisioned or used for these local checks.
- `pip-audit` on the newly exported runtime lock: zero known vulnerabilities;
  machine-readable output is [dependency-audit-current.json](dependency-audit-current.json).

The 12 browser checks now also cover the two-free-search paywall and preservation
of search details across mocked Stripe checkout cancellation.

Browser screenshots and the latest smoke report are generated under
`.local/browser-smoke/` (ignored by Git). The local preview is
`http://127.0.0.1:8787`. No public deployment, real charge, hotel booking, account
message, Chrome-store upload or external production change was performed.
