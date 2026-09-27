# First paid beta

The optimizer already solves a validated problem: compare hotel/date/booking
combinations for an actual trip or a status gap. Brad used it to reach Executive
Platinum. The existing public app is <https://aahoteloptimizer.streamlit.app/>;
[the original Reddit announcement](https://www.reddit.com/r/americanairlines/comments/1krplke/aadvantage_hotels_loyalty_points_per_dollar/)
links to it. cURL acquisition was the principal onboarding complaint.

## Decisions recorded September 27, 2026

- Two free real searches per account, no card required. Examples stay free.
- $9 trip pass: 20 additional searches, no expiry or renewal. This is a search
  pack usable for either trip or status planning, not a restriction to one date/city.
  Brad selected $9 passes; the 20-search allowance is an initial implementation
  assumption to validate with actual cost and usage.
- $19 monthly membership: 100 searches per calendar month (UTC), with self-service
  cancellation. The price is an experiment, not evidence of willingness to pay.
- Both options include agent API access. Agents cannot authorize purchases.
- US audience, USD; invited beta drawn from existing interested Reddit users.
- Desktop Chrome first, with the companion published before charging customers.
- Customers use their own AA accounts. No existing provider business relationship.
- No business, brand/domain, Stripe account, email provider or hosting account has
  been designated yet. LP Optimizer is a working name.

Free searches are used first, then active monthly searches, then purchased passes.
Provider failures restore the allowance. Cancelling already-started provider work
uses a search. Saved results remain readable after all included searches are used.
Unused pass searches survive membership cancellation; full pass refunds or open/
lost payment disputes revoke that purchase's remaining allowance.

## The purchase experience

Example → email sign-in → connect existing AA Hotels tab → two useful real
searches → choose a pass or membership → Stripe Checkout → return to the same
search details. Signed webhooks confirm access; a redirect alone grants nothing.
The app preserves search details across checkout cancellation and shows renewals,
allowances and cancellation terms before purchase. Stripe holds card details.

## Road to a paid launch

[DEPLOYMENT.md](DEPLOYMENT.md) contains the prepared hosting, email and billing
setup. The service can run on a provider HTTPS subdomain before a brand is chosen.

1. Connect owner-controlled Render, Resend and Stripe accounts. Deploy the prepared
   staging configuration and PostgreSQL migrations. Verify restart persistence.
2. Deliver an actual sign-in email, consume it on desktop and phone, verify DNS
   for an owned sending domain before inviting other customers, and set invited emails.
3. Exercise Stripe sandbox pass purchase, subscription, cancellation, failed
   payment, duplicate webhook, refund and account deletion end to end.
4. Verify one-night, split-stay and broad searches against actual personalized AA
   quotes. Check prices, eligible LP, pagination, expired login and changed accounts.
5. Confirm the provider's applicable commercial-access conditions. Customer-owned
   sessions solve credential handling; they do not themselves establish an agreement.
6. Choose the domain, publish the Chrome companion, and finalize operator/contact,
   privacy/retention, refund, support and tax details. Verify backups and alerts.
7. Enable real checkout only after these checks, then invite the small cohort.

The software keeps live checkout off by default. Enabling it requires production
settings, live search, a published companion URL and an explicit live-billing flag.
Stripe test-mode checkout is available for staging once its credentials are set.
These switches are deployment controls, not independent proof of release readiness.

## Learn from the first customers

Measure signup → connection → first completed search → useful plan → payment,
then repeat use, request counts, provider failures, support time and refunds.
The database records signups, completed searches, provider calls and entitlements;
there is no external analytics or acquisition attribution service yet.

Potential expansions remain saved-trip monitoring, quote revalidation, booking
links, posting-date/qualification modeling and phone-independent access through
an approved provider feed. Preserve the working optimizer as the core product.
