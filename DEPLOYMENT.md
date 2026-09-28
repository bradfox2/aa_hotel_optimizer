# Hosted beta setup

The public planner is <https://aahoteloptimizer.streamlit.app/>.
Its repository is <https://github.com/bradfox2/aa_hotel_optimizer>. Before this
change, `main` at `66678a3` had no GitHub Actions workflows or commit checks.
The live Streamlit metadata confirms branch `main`, entrypoint `streamlit_app.py`,
Python 3.11 and Streamlit 1.45.1 before this release. Its direct branch deployment
is separate from CI. Python 3.11 compatibility is preserved; no deletion or
redeployment of the existing app is needed to change the interpreter. The new GitHub workflow checks the engine, accounts, billing,
actual companion with mocked AA responses, and SQLite/PostgreSQL migrations.

`streamlit_app.py` now opens the shared redesigned planner. Its Streamlit v2
component sends only a fixed set of planner actions over the session's widget
channel. Live searches use the original provider functions with temporary cURL
credentials, bounded background jobs, whole-stay/split comparisons, and in-memory
session history. Credentials expire after 30 minutes; there is no shared cache,
account database or payment bypass. `?view=classic` opens the original UI.

The full login, companion bridge, Stripe webhook and agent API are served by
FastAPI. The Streamlit preview explicitly disables those features and checkout.
Deploy the full service using the prepared Render Blueprint, then link the
existing public URL to that service after its integrations have been verified.
CI now runs browser checks on the actual Streamlit entrypoint as well as the
standalone service, so a successful legacy-only deployment cannot pass as the
redesigned planner again. All AA/Stripe/Resend responses in these checks are simulated.

## What is ready, and what needs account access

`render.yaml` defines a Python web service and a private PostgreSQL 17 database
in Oregon, applies migrations before deployment, checks `/health`, and waits for
successful GitHub checks before later automatic deployments. It uses small paid
compute plans; review Render's displayed cost before provisioning. No hosting
resources have been purchased or created by preparing this file.

Create a Blueprint from this repository and the beta branch. `scripts/serve.py`
uses Render's actual HTTPS URL automatically, so no custom domain is needed to
see the product. Override `LP_PUBLIC_URL` when a custom domain is attached. The
web service starts in **staging**: public example viewing works, but email sign-in
is unavailable until delivery is configured. It never exposes local login links.

Use the host's protected environment settings for all secrets. Do not put them
in this document, GitHub, a public issue, or a chat message.

## Email

Recommended delivery: Resend's HTTPS API. Configure:

- `LP_RESEND_API_KEY`: sending key from the owner-controlled account.
- `LP_EMAIL_FROM`: a verified sender, e.g. `LP Optimizer <login@YOUR-DOMAIN>`.
- `LP_BETA_EMAILS`: comma-separated invited email addresses for the private beta.

Verify the sending domain in Resend and install its DNS records. For an initial
owner-only test, Resend's test sender can deliver only to the account's own email
address; it is not a sender for invited customers. SMTP remains supported as an
alternative through the settings in `.env.example`.

A sign-in email contains text and HTML versions of a one-use, 15-minute link.
Delivery errors are redacted. Confirm actual arrival, spam placement, desktop and
phone link handling, reuse rejection, and a clean expired-link recovery.

## Stripe sandbox first

Create these prices in a Stripe sandbox/test account:

| Product | Price | Type | Included searches |
| --- | --- | --- | --- |
| Trip pass | USD 9.00 | One-time | 20, no expiry |
| Monthly membership | USD 19.00 | Recurring monthly | 100/calendar month |

Set `LP_STRIPE_SECRET_KEY`, `LP_STRIPE_TRIP_PASS_PRICE_ID`, `LP_STRIPE_PRICE_ID`
(monthly), and `LP_STRIPE_WEBHOOK_SECRET`. Only server-selected prices can be
purchased. The current UI labels must agree with these amounts.

Create a webhook to `https://YOUR-HOST/v1/billing/webhook` for:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded` and `.async_payment_failed`
- `customer.subscription.created`, `.updated`, `.deleted`
- `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed`

Enable Stripe Customer Portal payment-method updates, invoice history and
subscription cancellation at the end of the billing period. Enable successful
payment receipts in Stripe; trip-pass checkout also supplies the receipt email.
Test renewal, failed payment, cancellation and account deletion as well as the
first purchase. The app never grants access from the success URL alone.

Keep `LP_LIVE_BILLING_ENABLED=false`. Staging accepts only sandbox checkout.
Actual charging requires production mode, enabled real provider searches, the
published Chrome Web Store URL and the live-billing flag, plus completion of
[B2C_BETA.md](B2C_BETA.md)'s release work.

## Companion and real search

Build the companion for the **actual deployed origin**:

```bash
python3 scripts/build_companion.py --origin https://YOUR-HOST --output .local/companion-beta.zip
```

Developer loading is acceptable for the owner's integration test. Customer
onboarding needs Chrome Web Store publication. Set `LP_COMPANION_URL` to the
listing when published, and `LP_PROVIDER_ENABLED=true` for the invited live test.
The customer signs in normally to AA Hotels in the same desktop Chrome profile.

## Verification and recovery

- `/health`, `/v1/config`, public example and agent docs load over HTTPS.
- Production uses a persistent PostgreSQL database, with automatic schema checks
  in CI. Take a backup before later schema changes; rehearse restoration.
- Confirm no development sign-in link is returned, session cookies are Secure,
  another account cannot read a saved search, and agent keys cannot buy access.
- Deliver a real email, buy with a Stripe test card, verify webhook delivery,
  refresh and restart the service, and confirm searches/entitlements persist.
- Compare actual AA quotes before opening customer checkout. Browser tests use
  fictional AA quotes and simulated Stripe responses, not live integrations.
- A code rollback must remain compatible with the database schema. Do not
  automatically downgrade or reset a database containing customer records.

References: [Render FastAPI](https://render.com/docs/deploy-fastapi),
[Blueprint specification](https://render.com/docs/blueprint-spec),
[Resend Python delivery](https://resend.com/docs/send-with-python),
[Stripe Checkout](https://docs.stripe.com/checkout/quickstart).
