# Chrome Web Store submission package

Status: prepared for owner registration and submission; **not submitted or published**.

- Name: LP Optimizer Companion
- Short description: Compare AA Hotels offers for searches you start in LP Optimizer. Your AA session stays in your browser.
- Category: Travel (choose the closest category the dashboard currently offers).
- Homepage: https://aahoteloptimizer.streamlit.app/
- Privacy policy: https://aahoteloptimizer.streamlit.app/?view=privacy
- Support: https://github.com/bradfox2/aa_hotel_optimizer/issues
- Version: 0.3.0

## Listing description

Make your hotel nights count toward AAdvantage status. LP Optimizer compares
whole stays and separate bookings across dates, hotels, prices, and estimated
Loyalty Points. The companion connects your personal AA Hotels offers to the
planner without copying commands or login tokens.

Connect the companion, sign in to AA Hotels normally, and start a comparison
in LP Optimizer. Your browser remembers the connection across visits and can
reopen the hotel tab when needed. If AA expires your session, sign in again.
Your browser must be running while offers are compared.

Review the booking checklist and make reservations directly with AA Hotels.
The companion never books a stay, makes a payment, or guarantees reward
posting. The current preview is free; account and payment services are not live.
Independent tool, not affiliated with American Airlines or AAdvantage Hotels.

## Single purpose and permissions

Single purpose: supply a user's personal AA Hotels quotes to hotel comparisons
they initiate in LP Optimizer.

- Storage: remember the connection and account fingerprint across browser visits.
- Scripting: run a fixed read-only adapter inside the signed-in AA Hotels tab.
- AA Hotels host: fetch that user's session status, cities, and hotel quotes.
- Optimizer host: relay the user's searches and normalized results to the planner.
- Frames: Streamlit hosts the planner inside its own same-origin application frame.
- No remotely hosted executable code; all adapter code is bundled.

The public Streamlit build omits the alarm permission; the separate full-service
build uses alarms to resume its durable task queue. No all-sites, history, or
raw-cookie permission is requested. Disclose the first name, account fingerprint,
search criteria and normalized offers in the store's current data-use form;
do not describe the extension as collecting no user data.

## Owner steps

Google requires the owner to register a developer account, pay its registration
fee, and enable two-step verification. No publisher account is connected here.
An upload package alone does not constitute publication or approval.

Build with `python scripts/build_companion.py --origin https://aahoteloptimizer.streamlit.app --output .local/chrome-store/lp-optimizer-companion-0.3.0.zip`.
Use the icons in `companion/icon-*.png` and the actual UI screenshot produced by
`scripts/streamlit_browser_smoke.py`. Upload the ZIP, complete the listing and
data-use forms using the above facts, then submit for review. The published
listing URL can replace the manual beta download once Google approves it.

Real personalized AA session lifetime and live quote accuracy still need the
owner's signed-in test. Automated checks use simulated AA responses and never
claim that one sign-in lasts forever.

References: [registration](https://developer.chrome.com/docs/webstore/register),
[publication](https://developer.chrome.com/docs/webstore/publish),
[API and account prerequisites](https://developer.chrome.com/docs/webstore/using-api).
