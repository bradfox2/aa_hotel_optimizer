# Local development

Python 3.11+ and uv are required; `.python-version` selects 3.12 locally. The
existing Streamlit Cloud app uses 3.11, and CI covers both versions. The original `.venv` on this laptop references a
removed Python 3.10; it is left untouched. The service uses `.venv-service`.

```bash
./dev --reload
```

Open <http://127.0.0.1:8787>. The sample needs no account or external credentials.
Sign-in shows a **development-only** link when SMTP is absent. Production refuses
to start without HTTPS, email delivery and PostgreSQL. Staging also requires HTTPS
and PostgreSQL; missing email disables sign-in without exposing local links. Do not expose the development server
through a public tunnel: its email link shortcut is deliberately local-only.

To edit settings, copy `.env.example` to `.env`. Real secrets, local databases,
browser profiles, session files and downloaded test artifacts are ignored by Git.
`LP_PUBLIC_URL` must match the URL in the browser (including its port).

## Browser companion beta

The source companion is bound to `http://127.0.0.1:8787`. To test it locally, load
the `companion` directory as an unpacked extension in Chrome/Chromium. The
consumer release should be installed from the Chrome Web Store; that listing
does not exist yet, and the UI says so when no companion is detected.

1. Set `LP_PROVIDER_ENABLED=true` and restart this service.
2. Sign in to LP Optimizer, then open AA Hotels in the **same browser profile**
   and sign in normally. Do not export cookies or cURL commands.
3. Click **Connect AA Hotels → Connect this browser**. Keep the provider tab open.
4. Start with a one-night, one-city search and compare the result with AA Hotels.

Only the provider's fixed read-only places, session, search-request and search
result routes are callable. Raw sessions stay in the page; the server gets
normalized quotes, a first-name label, and a hashed account fingerprint. Session
expiry, provider throttling and account changes stop work rather than bypassing
login or challenges. A stored **optimizer bridge key** can only claim and return
that connection's work; it cannot access app accounts or billing.

The adapter follows the original working routes plus the session shape observed
in the provider's public client. Real personalized account integration remains
unverified until this smoke test is performed. A schema mismatch fails explicitly.
Results paginate until a short page, bounded at 20 pages and 1,000 calls/search.
The service does not treat truncated results as a completed optimization.

Build a domain-specific package without publishing:

```bash
python3 scripts/build_companion.py --origin https://YOUR-APP-DOMAIN --output .local/companion.zip
```

## Checks

```bash
UV_PROJECT_ENVIRONMENT=.venv-service uv sync --frozen --extra dev
.venv-service/bin/pytest -q
.venv-service/bin/ruff check aa_hotel_optimizer tests scripts migrations
.venv-service/bin/ruff format --check aa_hotel_optimizer tests scripts migrations
.venv-service/bin/python scripts/browser_smoke.py
.venv-service/bin/python scripts/streamlit_browser_smoke.py
```

The browser smoke script starts its own isolated local server/database and uses
fictional provider responses. It never signs in to a real AA account. Install a
Playwright Chromium build (`.venv-service/bin/playwright install chromium`) if
there is none cached. Test output and screenshots go in `.local`.

## Existing workflows

```bash
UV_PROJECT_ENVIRONMENT=.venv-service uv run --frozen streamlit run streamlit_app.py
UV_PROJECT_ENVIRONMENT=.venv-service uv run --frozen python -m aa_hotel_optimizer.main --help
```

Their function signatures are preserved. They use the corrected shared selection
logic, bounded pagination, secret-safe errors and consistent projected balances.
Streamlit opens the same planner UI as the service and keeps form values and
results across component reruns. It uses a session-only transport for the
optimizer, with a temporary cURL connection for live searches. The Chrome
companion, email accounts, billing and agent API require the standalone service.
The original single-night search UI remains at `?view=classic`. No future
threshold bonus is silently assumed. Both browser test scripts use fictional
provider responses; they do not validate a real AA login or real email/payment.

## Database migrations

Development initializes an empty SQLite database automatically. Production does
not. Apply Alembic migrations before starting a production instance:

```bash
# LP_DATABASE_URL is supplied by the environment, not a command-line secret.
.venv-service/bin/alembic upgrade head
```

For an existing local database made by this version's development bootstrap,
`alembic stamp head` records the already-created schema. Never stamp a production
database without first verifying its schema. Use a fresh database for migration
tests, and take a backup before production migrations.

## Stripe and email

Use Stripe **test mode** first. Configure the $9 one-time Price and $19 monthly
Price, then enable the hosted Customer Portal (including cancellation). Set both
Price IDs, the test secret key and webhook signing secret from `.env.example`.
The full event list and hosted setup are in [DEPLOYMENT.md](DEPLOYMENT.md).

The server chooses the Price and customer. Only signed, deduplicated webhooks
change entitlements; the current subscription is fetched after locking the user
row. Redirecting back from Checkout never unlocks access. Cancelled, unpaid or
expired subscriptions have no paid allowance. Search quotas use calendar months
in UTC; trials receive two searches total. Trip passes add 20 searches without expiry. Started provider work consumes a
search if the customer cancels it. Provider failures return the search allowance;
new-search creation is also limited to ten per hour to bound retries. Sample
comparisons never consume the allowance.

Configure Resend HTTPS delivery or SMTP with STARTTLS, sender verification and
an owned sending domain. `LP_BETA_EMAILS` restricts sign-in to invited addresses.
Local links are single-use, expire after 15 minutes, and travel in URL fragments
so access logs don't capture them. App sessions are HttpOnly cookies; hashed
agent keys are revocable and expire after 90 days.

Stripe, delivered email, production PostgreSQL and a real AA session have **not** been
provisioned or used by the local automated tests. Do not describe the preview as
a launched paid service.
