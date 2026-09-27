# Product interface

The audience is an AAdvantage member choosing hotel reservations for a known trip,
or finding stays that close a status gap. The page's job is to turn date and hotel
combinations into an understandable booking plan.

Palette: cloud `#F3F6FA`, paper `#FFFFFF`, ink `#162B43`, slate `#55667A`,
cobalt `#225DD8`, sea `#136B63`. Secondary tints derive from these six colors.
Barlow Condensed carries short travel-oriented headlines; DM Sans handles forms
and explanations; the system monospace face handles dates and reference values.
Fonts are served locally. Keep the surrounding page quiet and spacious.

Layout: a narrow planning column sits beside a wider comparison, with the booking
sequence as the primary visual. On mobile, the form precedes the comparison.

```
wordmark          saved searches / agents          sign in
Same trip. More Loyalty Points.       connection status
┌ trip / status ─────────┐  ┌ example label / result ──────────┐
│ destination           │  │ hotel + expected LP / cost      │
│ check-in / check-out  │  │ Mon ┃ Tue ┃ Wed ┃ Thu           │
│ budget + preferences  │  │ separate booking segments       │
│ compare / try example │  │ continuous booking comparison   │
└───────────────────────┘  └ itemized booking plan ────────────┘
```

Signature: the night-by-night strip uses joined reservation segments to show
whether nights belong to one booking or several. Its divisions encode actual
dates and reservations, not decoration. Numbers must always separate hotel LP,
card LP, active partner bonuses, cost, and redeemable miles.

Pre-build critique: a generic subscription dashboard would emphasize account
metrics and upgrade cards. This design instead leads with the user's actual
booking decision and includes an immediately usable, explicitly fictional
example. Billing and developer controls belong in account dialogs. Avoid AA
logos or styling that suggests affiliation. Motion is limited to loading and
dialog entry; reduced-motion disables it. Keyboard focus, explicit field labels,
and small-screen overflow checks are required before review.

## Purchase flow follow-through

Kept the existing ink/cloud/cobalt/sea tokens and display/body pairing. The
upgrade dialog uses two stacked purchase rows with clear price, allowance and
renewal terms; the itinerary stays visible underneath. It appears on the next
search after the two-search trial, and saved results remain available. Reviewed
desktop and 390px phone screenshots in `.local/browser-smoke/paywall-*.png`; both
purchase buttons fit, and the dialogue can scroll on a short viewport.
