# LP Optimizer Companion privacy

Effective September 27, 2026. This policy covers the Chrome companion and the
new LP Optimizer planner at https://aahoteloptimizer.streamlit.app/.

The companion runs read-only hotel searches in your AA Hotels browser tab.
Your browser sends its existing AA credentials directly to AA Hotels. The
companion does not read, copy, or send your AA password, cookies, or login
tokens to LP Optimizer. It does not make reservations or purchases.

The planner receives your search criteria, normalized hotel offers, your first
name, and a one-way fingerprint of the AA session identifier. The fingerprint
detects account changes; the raw identifier and membership number are not sent.
Offers include dates, property and rate identifiers, price, quoted rewards,
hotel class, rating, room description, and refundability when supplied.

Chrome stores your connection preference, account fingerprint, and first name
locally so the companion can reconnect after you return or restart Chrome.
When necessary it opens an AA Hotels tab in the background. If AA expires your
sign-in, you must sign in again. Disconnecting removes the remembered connection
and stops further search tasks. An already-running request may finish.

The Streamlit preview keeps your last ten searches in memory for that browser
session. Reloading, closing the session, or restarting the service can remove
them. Download a plan to keep your own copy. The preview does not create an
email account or accept payments. Hosting providers may process routine network
and operational logs under their own policies; AA Hotels handles your sign-in
and booking activity under its policies. We do not sell data or send offers to
advertising services.

The extension is limited to AA Hotels and the configured LP Optimizer site.
It does not collect your general browsing history. Uninstalling removes the
extension's local data. For support or privacy requests, use the project's
[support page](https://github.com/bradfox2/aa_hotel_optimizer/issues); do not
include passwords, tokens, payment details, or copied network requests.

The separate original interface at `?view=classic` uses the older manual
connection workflow. This companion policy describes the new planner; using
the original interface is not required to connect or search with the companion.
