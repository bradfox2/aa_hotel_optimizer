# LP Optimizer

Compare combinations of AA Hotels reservations to earn more AAdvantage Loyalty
Points for a trip, or find stays that close a status gap. The original Streamlit
and CLI workflows are preserved. A customer service now wraps the shared engine.

## Try the local app

```bash
./dev --reload
```

Open **<http://127.0.0.1:8787>**. Requires Python 3.11+ and uv (local default: 3.12). The app starts with
an explicitly fictional example; no AA login or payment is needed to explore it.
Local sign-in displays a development link until email delivery is configured.

Read [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for the browser companion,
environment variables, tests, migrations, Stripe test mode, and legacy commands.

## What is implemented

- Planned trips: compare single-night, multi-night and mixed booking combinations
  while covering every night, respecting budget, hotel changes and booking limits.
- Status searches: multiple cities, LP balances and targets, value/cost/points/
  earliest-finish strategies, and explicit overlap limits. No-show rewards are
  not assumed to be guaranteed.
- Accurate accounting contracts: earned versus projected LP, separate redeemable
  miles, explicit active partner promotion dates and remaining bonus allowance.
- Responsive customer interface: a night-by-night booking strip, itemized plans,
  saved search history, JSON export and copyable booking checklists.
- Email-link login, ownership checks, hashed credentials, session cookies, CSRF
  protection, scoped/revocable agent keys, account export and account deletion.
- Chrome MV3 companion: uses the user's AA Hotels tab without exporting their
  provider session. Reconnect states, finite task leases, retries and request
  budgets keep browser work durable and bounded.
- Stripe Checkout and Customer Portal integration, signed/idempotent webhooks,
  server-controlled prices, reusable checkout sessions, subscription entitlements
  and included-search limits. Two free searches, $9/20-search passes and $19/month
  memberships; unused pass searches survive membership cancellation.
- Typed [agent API guide](aa_hotel_optimizer/service/static/agents.html), OpenAPI
  at `/openapi.json`, idempotent submission, polling, cancellation and saved plans.
- SQLAlchemy persistence, SQLite for local development, PostgreSQL deployment
  configuration, Alembic migrations, dependency lock and CI checks.

Minimum-cost status selection is exact among the available quotes with one
booking per date. Other status strategies are heuristics. No result guarantees
market-wide inventory, reward posting, or that a quoted room remains bookable.

## Current release boundary

This is a **local/private-beta implementation**, not a launched paid service.
The full app and actual Chrome companion are exercised with mocked provider
responses. A real personalized AA Hotels session, live Stripe test account,
Email delivery and deployed PostgreSQL still need integration validation.

The companion has not been published in the Chrome Web Store. The live provider
adapter is opt-in (`LP_PROVIDER_ENABLED=true`); provider commercial access must be
resolved before a paid release. The app does not contain a public third-party
OAuth integration or book hotels automatically.

The quote adapter uses the provider's `rewards` field as an estimated hotel LP
amount and labels this assumption. A verified base-LP/promotion breakdown and a
confirmed booking deep link are still needed for stronger live quote guarantees.
Saved quotes are timestamped; users should run a fresh comparison before booking.

The legacy public URL is <https://aahoteloptimizer.streamlit.app/>. The full
consumer service has a prepared [Render deployment](DEPLOYMENT.md), Resend email
delivery, invite controls and a Stripe sandbox path. These need owner-controlled
accounts before the hosted integrations can be verified.

## Repository map

| Path | Responsibility |
| --- | --- |
| `aa_hotel_optimizer/domain.py` | Validated requests, quotes and reward accounting |
| `aa_hotel_optimizer/solver.py` | Cost selection and complete-trip comparison |
| `aa_hotel_optimizer/legacy.py` | Existing function contracts and cURL parser |
| `aa_hotel_optimizer/main.py` | Original provider client and CLI orchestration |
| `aa_hotel_optimizer/service/` | API, accounts, jobs, billing, database and customer UI |
| `companion/` | Domain-bound Chrome browser companion |
| `migrations/` | Versioned database schema |
| `tests/`, `scripts/browser_smoke.py` | Engine, security, billing and full browser checks |
| `audit/2026-09-27/` | Original audit evidence, product plan and remediation status |

The audit's original expected-failure tests document the old app at commit
`66678a3`; they are historical evidence, not the current regression suite.

Independent tool; not affiliated with American Airlines or AAdvantage Hotels.
