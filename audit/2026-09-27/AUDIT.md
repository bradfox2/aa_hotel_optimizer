**AAdvantage Hotel Optimizer — full code and service-readiness audit**

Audited September 27, 2026, at commit `66678a3` in `/home/brad/Projects/aa_hotel_scrape`. Production application files were not changed. Evidence and recommendations are in this directory.

**Decision: expand, polish, and monetize the existing app incrementally. A wholesale rewrite is not justified.** Brad used the app extensively to reach Executive Platinum and received positive Reddit feedback; manual cURL acquisition was the reported usability problem. That sustained use validates the core search/split-booking workflow. Prioritize a simple account connection, the reproduced correctness defects, persistent results, and a small paid-service layer. Evaluate expansion opportunities separately by customer value. Several defects affect spend or expected points and deserve fixes, but they do not invalidate the product's demonstrated utility.

Brad clarified two paid use cases during the audit:

| Mode | Customer objective | Constraints that matter |
|---|---|---|
| Optimize my trip | Find the best combination of hotel, price, booking duration, and split bookings for a trip already planned | Cover every night; exact checkout; occupancy; budget; hotel/room preferences; acceptable hotel changes and booking count |
| Close my status gap | Find high LP-per-dollar bookings, potentially in multiple cities, to earn a remaining LP amount | Total spend; dates; eligibility; posting/qualification deadlines; optional overlaps; explicit assumptions for unattended/phantom bookings |

Both workflows already have useful support in the app. Complete-trip constraints and mixed-length partitions are expansion opportunities; they are not grounds to discard the working single-night optimizer. The broad search that produced Brad's historical approximately 40 LP/$ bookings should remain. A future clearer interface can distinguish these two customer intents without exposing more algorithm controls.

**Scope and evidence**

Reviewed all 18 original tracked files: six Python files totaling 2,558 lines, dependency manifests and lockfile, launch/development configuration, README, example headers, and both screenshots. Read every application function and the two informational pages. The [scope manifest](scope-manifest.json) records the original file hashes.

The original `.venv/bin/python` points to the missing `/usr/bin/python3.10`. I reproduced the locked dependency versions in an isolated Python 3.12 environment under `/tmp/aadvantage-audit-20260927/venv`. This is a finding about this checkout's local environment; it does not establish that Brad's running deployment is broken.

The [offline audit tests](test_audit.py) ran 26 checks: five baseline checks passed, and 21 cases reproduced identified defects or missing product requirements. Those 21 are deliberately marked `expectedFailure`; the test runner's successful exit means the evidence reproduced, not that production is fixed. Four of the cases assert new paid-product requirements: complete-trip coverage, checkout semantics, continuous-stay comparison, and requiring a verified connection for personalized search. The other 17 expose current calculation/data/UI behavior. See [results](test-results.json) and [test output](test-output.txt).

All outbound Requests traffic was blocked in the test suite. Hotel responses and credentials were synthetic. Public provider documentation and dependency advisories were researched separately. No live authenticated hotel search, real booking, account-token extraction, penetration/load attack, deployment inspection, or actual reward-posting validation was performed. Streamlit AppTest exercises the app, not a full browser/mobile visual audit.

To rerun in the isolated environment created for this audit, from the repository root: `/tmp/aadvantage-audit-20260927/venv/bin/python audit/2026-09-27/test_audit.py`. The dependency inventory records exact versions if the temporary environment needs to be recreated. These tests do not fix production behavior.

**Prioritized findings**

P0 means an unresolved dependency for a commercial launch; P1 means fix or explicitly bound before paid access; P2 means beta polish or later expansion, as specified. Expansion opportunities are labeled separately from defects in the existing personal-tool contract. Neither the number of audit cases nor missing future features measures whether the app solved Brad's original problem; his extensive successful use establishes that it did.

| ID | Priority | Finding | Evidence type |
|---|---|---|---|
| F21 | P0 | Commercial data access and account connection need a permitted, supportable path | Provider terms and architecture review |
| F01 | P2 | Optional expansion: complete-trip constraints and mixed-duration comparisons | Product-gap reproductions, not a rejection of the validated workflow |
| F02 | P1 | LP bonus rules are obsolete and eligibility cannot be represented | Official 2026 rules + reproduction |
| F03 | P1 | LP-only bonuses incorrectly increase redeemable miles | Official rules + reproduction |
| F04 | P1 | Strategies return inconsistent totals, corrupting metrics and iterative stopping | Reproductions |
| F05 | P1 | Greedy strategies award bonuses in price order instead of stay order | Reproductions |
| F06 | P1 | “Minimum cost” DP discards cheaper sufficient bookings | Reproduction |
| F07 | P1 | DP can reject attainable targets because it ignores bonuses when selecting | Reproduction |
| F08 | P1 | Search reads only the first results page and has no completion protocol | Static review + mocked paging case |
| F09 | P1 | Malformed upstream data can erase a date; missing prices become free stays | Reproductions |
| F11 | P1 | A malformed credential header can put its value into server logs | Synthetic-secret reproduction |
| F12 | P1 | Search/solver work has no effective service-wide resource budget | Reproduction + complexity review |
| F14 | P1 | Login/token workflow fails the simple-onboarding requirement | AppTest + product gap |
| F16 | P1 | Authentication, billing enforcement, ownership, durable jobs, and agent API are absent | Whole-repository inventory |
| F18 | P1 | Locked dependencies have known advisories requiring upgrade and triage | Dependency scan + maintainer advisories |
| F23 | P1 | Reward eligibility, posting, and unattended-stay assumptions are not modeled | Provider FAQ + code review |
| F10 | P2 | cURL parsing silently loses common header formats | Reproduction |
| F13 | P2 | Search results disappear on the next widget rerun | AppTest reproduction |
| F15 | P2 | Partial/failing searches look like completed optimization | AppTest + static review |
| F17 | P2 | Devcontainer disables CORS and XSRF safeguards | Configuration review |
| F19 | P2 | Deduplication is quadratic and uses an unreliable offer identity | Static review |
| F20 | P2 | Results cannot reliably identify or revalidate a bookable offer | Data-contract review |
| F22 | P2 | Packaging, documentation, and operational checks have drifted | Whole-repository review |

**F01 — Preserve splitting; treat broader trip constraints as an expansion.**

[main.py:815](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:815) always requests checkout = check-in + one day. [main.py:412](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:412) treats both ends of the search window as possible check-in dates. Every strategy stops at a target; none requires a complete set of nights. The trip data model has no checkout, multi-night interval, occupancy preferences, stable property ID, room consistency, hotel-change limit, or budget constraint.

For a seven-night search with a low target, the current engine can return just one night. Interpreting its inclusive “End Date” as a travel checkout produces an extra search night; that is a proposed UX-contract change, not an off-by-one defect in its existing search-window contract. There is no comparison between a seven-night booking, 3+4 nights, 2+2+3 nights, or seven individual bookings. Single-night splitting is a useful existing capability, but cannot prove that a plan is best across durations.

For the paid beta, keep the current behavior, clearly describe search-window semantics, and make any missing nights visible rather than calling a partial selection a complete trip. When expanding to mixed-duration optimization, add a `TripRequest` and interval-based solver behind the existing interface, retaining single-night candidates. Keep status-run constraints separate. The [service plan](SERVICE_PLAN.md) makes this a later expansion rather than a prerequisite for monetizing the current useful workflow.

**F02 — Replace hardcoded 2025 bonus logic with dated eligibility.**

[main.py:421](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:421) applies 20% after 60,000 LP and 30% after 100,000, indefinitely and solely from balance. As of March 1, 2026, American increased the relevant partner bonus to 25% at 60,000, requires registration for a six-month window, caps additional LP at 25,000, and removed the 100,000-level 30% reward. This is a current correctness defect. [American's program updates](https://www.aa.com/web/i18n/aadvantage-program/aadvantage-program-updates.html).

The function has no inputs for qualifying year, registration, expiration, bonus already consumed, posting chronology, or exceptions carried over from prior periods. Changing `0.20` to `0.25` alone does not fix it. A synthetic eligible 1,000-base-LP stay returns 200 extra LP instead of 250. Model rule version and actual eligibility; keep observed provider rewards separate from estimated supplements. The detailed terms also specify a registration deadline and treatment of overlapping prior-year benefits. [Loyalty Point Rewards terms](https://www.aa.com/web/i18n/aadvantage-program/aadvantage-status/loyalty-point-rewards.html).

**F03 — LP and redeemable miles are different currencies.**

[main.py:449](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:449) adds the partner LP bonus to `miles_earned`, then to the displayed monetary value. American explicitly excludes redeemable bonus miles from this LP reward. A 1,000-mile stay becomes 1,200 miles under the legacy 20% calculation, incorrectly adding $3 at the default 1.5 cents/mile. [Loyalty Point Rewards terms](https://www.aa.com/web/i18n/aadvantage-program/aadvantage-status/loyalty-point-rewards.html).

The API normalizer also treats the entire `rewards` field as both base LP and miles without an explicit schema or promotion breakdown. That field's exact live semantics were not verified. Maintain separate hotel base miles/LP, promotional miles, card LP, card miles, partner LP bonus, and eligibility evidence. Base hotel miles qualify for LP while certain promotional miles do not, per the [provider FAQ](https://www.aadvantagehotels.com/faq).

The pre-status code correctly distinguishes 1x card LP from the selectable card-mile rate; preserve that separation. A generic “AA card bonus” checkbox does not identify the card product or payment eligibility. Citi advertises 10x hotel miles for eligible Executive-card purchases, not as a universal benefit of all AA cards. [Citi card comparison](https://www.citi.com/credit-cards/credit-card-miles/which-aadvantage-credit-card-should-you-get).

**F04 — Return one explicit kind of points total from every strategy.**

PPD and cheapest return newly earned points at [main.py:503](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:503) and [main.py:556](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:556); DP and fastest return starting balance plus earned points. [streamlit_app.py:461](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:461), CLI reporting, and [main.py:1140](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:1140) assume an overall balance.

Reproduction: start at 50,000 LP, target 51,000, select a $100/1,000-LP stay. Greedy returns 1,000; DP and fastest return 51,000. The UI subtracts 50,000 again and displays zero LP/$ for greedy. Iterative greedy search continues after the target is already met, potentially scanning the entire configured horizon. The audit's tiny four-date scenario performs four fetches instead of one.

Return a named result with `starting_lp`, `earned_lp`, `projected_lp`, `target_met`, and `shortfall_lp`; stop relying on an ambiguous fourth tuple element. Correct empty/already-qualified paths and CLI output too.

**F05 — Chronological bonus application is inconsistent.**

[main.py:487](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:487) and [main.py:540](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:540) award bonuses in PPD/price selection order and sort by date only afterwards. Under the app's own legacy rules, an October 2 booking can qualify an October 1 booking for a bonus.

Reproduction: initial 59,000 LP; October 1 earns 10,000 for $100, October 2 earns 2,000 for $10. Both greedy strategies select October 2 first and estimate 14,000 earned LP. Re-evaluating their displayed chronological itinerary under those same rules gives 12,400. This can falsely indicate a status target is attainable. Fix selection/state transitions and revalidate any selected plan; chronological sorting alone is insufficient. Actual posting/registration timing needs the richer eligibility model in F02/F23.

**F06 — The DP strategy is not minimum-cost even without any bonuses.**

[main.py:691](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:691) retains only the highest-points stay for each date before cost optimization. Two same-day offers, $100 for 1,000 LP and $1,000 for 1,100 LP, produce a $1,000 recommendation for a 1,000-LP target. The sufficient $100 stay was discarded.

Keep non-dominated alternatives by date/interval and solve a multiple-choice or interval problem. Do not keep a single “best” offer independently of the objective. Until repaired, remove the UI's suggestion that this strategy finds the true minimum cost.

**F07 — DP can reject a target its own reward model can achieve.**

[main.py:716](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:716) builds the table with pre-bonus points, then applies status bonuses only after selecting a path at line 795. With current LP = 60,000, target = 61,200, and a 1,000-base-LP stay, it returns no itinerary even though its own helper gives 1,200 LP. It can also buy unnecessary stays when a cheaper bonus-adjusted combination suffices.

Represent point eligibility in the optimization state, or use conservatively fixed, validated account eligibility for a search and explicitly state its limits. Test small instances against brute-force enumeration. The existing assumptions page admits a simplification but does not make the paid recommendation accurate.

**F08 — Searches are incomplete by construction.**

[main.py:242](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:242) defaults to page 1 with 45 results; [main.py:836](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:836) calls it once. There is no loop to fetch further pages or provider-completion polling. A mocked 90-result response is consumed with one results call. This proves the missing paging loop; it does not establish the current live API's pagination metadata.

Build bounded pagination/completion handling from captured, sanitized provider fixtures. Report searched dates, intervals, properties/pages, failures, and truncation. “Best found within this coverage” is appropriate when provider coverage is partial. Do not advertise an exhaustive maximum from one page.

**F09 — Validate upstream data before arithmetic.**

[main.py:297](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:297) assumes dictionaries and numerical fields. `hotel: null` raises; a missing price becomes `0.0`; no currency, finiteness, range, or reward-type validation exists. A malformed item after valid items aborts the entire batch, and the caller drops that date. PPD and fastest accept a positive-points stay with zero price; cheapest and DP filter it differently.

Use typed normalized offers, integer minor currency units or decimal arithmetic, separate invalid-record diagnostics, and consistent validity checks across strategies. Unknown prices must remain unknown, not turn into free accommodation. Reject NaN/infinity, negative values, and invalid dates. One bad record should not erase valid offers.

**F10/F14 — Manual header acquisition and silent fallback are unsuitable onboarding.**

[main.py:46](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:46) recognizes only single-quoted `-H` headers and limited URL/cookie forms. `-H "Cookie: ..."` is silently dropped, despite the UI mentioning Windows cURL. Long header options, escaped quotes, and case handling are incomplete. The parser does not execute cURL; I found no shell-execution path here.

[streamlit_app.py:255](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:255) still searches after missing/invalid credentials. This unauthenticated mode is an existing feature, but it is not a verified personalized search. AppTest confirms that a blank login state reaches the search backend. Expired sessions, wrong-account sessions, and authentication failures have no explicit state machine or reconnect flow.

Separate login to the paid app from connecting an AA Hotels account. Replace manual cURL, cookie, XSRF, and JSON entry in the customer path with a verified connection and automatic lifecycle handling, subject to F21. If anonymous discovery remains, label it clearly and do not present it as the user's confirmed reward quote. Agent responses should expose `connection_required` or `reauth_required`, never instructions to paste raw secrets into a prompt.

**F11 — Credential-bearing errors need redaction.**

[main.py:235](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:235) logs Requests exceptions verbatim. Supplying a Cookie value with leading whitespace produces an `InvalidHeader` exception containing that value; the synthetic audit secret appears in captured server logs. Other request functions follow the same pattern. [streamlit_app.py:805](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:805) also exposes exception details and stack traces to the UI.

Validate and allowlist credential/header inputs, redact secrets before logs or error reporting, and show a safe error code to customers. Real tokens are not deliberately written to disk by this app, and I found no global credential cache or demonstrated cross-session leak. Raw session credentials are held in Streamlit widget/session memory and readable inputs; that still requires a defined retention/disconnect model before hosting.

**F12 — One user can consume disproportionate compute and provider calls.**

[streamlit_app.py:957](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:957) allows an unbounded LP target, city lists and date windows have no service budget, and [main.py:730](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:730) allocates arrays/list objects proportional to that target. Its time is approximately O(candidate dates × target-point range), with additional memory for copied paths. Do not load-test extreme values in the working app; the resource growth is visible statically.

[main.py:1009](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:1009) creates up to ten threads per search and schedules all dates immediately. Ten users can create roughly 100 simultaneous provider requests; there is no global provider limiter, fair queue, cancellation contract, or per-user quota. Requests have timeouts, which is good, but no overall job deadline, retry budget/backoff, or explicit 429/401/403 handling.

The initial date window is never clipped to `max_search_days_iterative`; the reproduced 11-date request exceeds a configured two-day-ahead limit. Bound dates, cities, intervals, pages, target LP, runtime, memory and requests on the server. Use cancellable queued jobs and cache by the full request/account context. See the service plan's request-cost model.

**F13 — Ordinary UI interaction discards results.**

The entire output is inside [streamlit_app.py:255](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:255)'s button branch; results are not persisted. AppTest confirms that changing mileage valuation after a successful search removes all six metrics and returns to the initial prompt. A customer must search again to see results, adding latency and provider load.

Store search inputs/results under a durable search ID, separate rendering from submission, and re-rank cached offers for changes that do not require new quotes. Even before a new frontend, keeping an explicit result object in session state would address the immediate rerun defect.

**F15 — Distinguish no offers, partial data, failure, and unmet target.**

[main.py:1040](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:1040) logs per-date exceptions and continues. HTTP failures return `None`; empty inventory and authentication/rate-limit/network failures become indistinguishable at the top level. [streamlit_app.py:448](/home/brad/Projects/aa_hotel_scrape/streamlit_app.py:448) labels any nonempty itinerary “Optimal Loyalty Points Strategy,” including a 1,000-LP plan for a 200,000-LP target. AppTest finds no explicit shortfall warning.

Return structured search health, coverage, target status and missing-night information. An already-met target should say no additional bookings are needed, not “could not form an itinerary.” Never convert an incomplete provider response into an apparent exhaustive recommendation.

**F16 — The commercial service and agent interface do not yet exist.**

The repository contains no customer identity, subscription ledger, backend authorization, database/migrations, durable job ownership, payment integration, API key lifecycle, stable JSON API, OpenAPI schema, MCP tools, or user data export/deletion flow. Streamlit session state is not customer identity or paid entitlement. This is expected scope for a personal tool, but cannot be replaced by hiding the Search button behind checkout.

Enforce identity, entitlement, ownership and request limits in the backend for both UI and agents. Persist search history/results, record usage, and process signed/idempotent billing webhooks. Stripe documents subscription state changes as asynchronous events; paid access should not be granted solely from a browser redirect. [Stripe subscription webhook documentation](https://docs.stripe.com/billing/subscriptions/webhooks).

Use the same typed service functions for web and agent requests; expose safe structured error states and cancellable job IDs. No LLM is needed in the reward arithmetic or optimizer. An optional MCP adapter should wrap the existing authorized API, not become a second search implementation.

**F17 — Development flags must not become production settings.**

[.devcontainer/devcontainer.json:22](/home/brad/Projects/aa_hotel_scrape/.devcontainer/devcontainer.json:22) launches with both `--server.enableCORS false` and `--server.enableXsrfProtection false` and forwards port 8501. This is a concrete development-config weakness if copied to public hosting, not evidence that Brad's current deployment uses it. The ordinary `run.sh` does not set those flags. Retain protections, establish allowed origins, and verify the reverse-proxy/session configuration for the actual deployment.

**F18 — Update dependencies and assess reachability; do not equate scan hits with exploits.**

The locked stack includes Streamlit 1.45.1, Tornado 6.5, Requests 2.32.3 and urllib3 2.4.0. `pip-audit` scanned all 45 locked registry packages and returned 125 advisory records; duplicate records collapse to 74 distinct package/advisory IDs in 11 packages. These are inventory matches, not 74 demonstrated vulnerabilities in the application. See the deduplicated [dependency inventory](dependency-inventory.json).

The most immediately relevant verified example is Tornado's multipart-parser denial of service: versions through 6.5.4 are affected and 6.5.5 contains that particular fix. This application uses Streamlit's upload functionality, so request parsing deserves priority. Later advisories exist in the inventory; 6.5.5 is not asserted to be a sufficient overall upgrade target. [Tornado maintainer advisory](https://github.com/tornadoweb/tornado/security/advisories/GHSA-qjxf-f2mg-c6mc).

Conversely, the scanned Streamlit NTLM/SSRF advisory affects Windows hosts, so it is not evidence of that exposure on this Linux laptop. Several dependency findings require unused Git, font-processing, cache, or utility paths. Upgrade a complete compatible set on a branch, rerun functionality tests, rescan, and document any accepted non-reachable findings. [Streamlit maintainer advisory](https://github.com/streamlit/streamlit/security/advisories/GHSA-7p48-42j8-8846).

**F19 — Deduplication becomes expensive and can lose distinct offers.**

[main.py:1064](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:1064) computes an unused set, then compares every new offer against all existing offers. This is O(N²). At the built-in 26-city scale, 30 dates and 45 results per date would produce up to 35,100 rows and about 616 million pair comparisons if all keys are unique; that is a calculation, not a measured load benchmark.

The key uses name/location/date/price but excludes property ID, rate plan, refundability, room and rewards. Distinct offers can collapse, preserving whichever thread completed first. Switch to stable provider property/rate/interval identity and a dictionary/set; define how refreshed or conflicting quotes replace earlier ones. Keep genuine rate alternatives.

**F20 — A recommendation needs enough data to book and verify it.**

[main.py:325](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:325) drops provider hotel IDs, rate IDs, checkout, currency, account/eligibility context, observation time, room type, payment terms, cancellation deadline, extra fees breakdown and booking references. There are no booking handoff links. Name + date + price is not enough to identify an offer after the user returns to the provider.

Location discovery also silently chooses a shortest/first city match at [main.py:942](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:942), using an ID-string heuristic rather than preserving the typed location returned by the API. Cities with ambiguous names can be misselected. Provide a disambiguated location picker and preserve stable IDs. Revalidate the chosen plan before handoff, mark stale/changed quotes, and use provider-approved links.

**F21 — Data rights and connection feasibility are commercial dependencies.**

The API URLs at [main.py:38](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:38) are website endpoints, not a documented integration agreement. The public CMS response for the AA Hotels site slug delivered generic Rocket Travel terms restricting commercial reuse, automated access, and deep-linking without written permission. I retrieved Terms/FAQ content via the public CMS models referenced by the site's JavaScript because the initial pages are client-rendered; I did not verify the final Terms rendering in a browser. Those generic terms display an April 17, 2020 update date; applicability/current contractual arrangements need confirmation. [Hotel provider terms](https://www.aadvantagehotels.com/terms).

American's platform terms separately restrict commercial content reuse and mileage-management services without authorization. Treat permission, reward-data availability and account linking as launch dependencies to resolve with the provider and qualified counsel; this audit is not a legal determination. The existing disclaimer page does not grant data rights. [American platform terms](https://www.aa.com/pubcontent/en_US/customer-service/support/legal-information.html).

Rocket Travel publicly offers accommodation APIs and documents the AA platform's own SSO integration. That establishes a potential partner route, not a promise that a small third party can obtain AA-specific personalized rewards or reuse that SSO. No public third-party AA Hotels OAuth integration was verified in this audit. [Rocket Travel](https://www.rockettravel.com/), [AA platform announcement](https://www.rockettravel.com/blog-articles/aa-launch-announcement).

The account-connection proof should precede a large UI rebuild. A browser extension can be evaluated as a user-mediated technical option, but it is not a permission workaround and its mobile/unattended-agent limitations are material. See the explicit connection alternatives in the service plan.

**F22 — Simplify the structure and make it reproducible.**

`main.py` combines provider transport, reward rules, four solvers, orchestration, logging and CLI. The 986-line Streamlit script combines UI, state, submission and rendering. `__init__.py` imports `main`, which configures the root logger and attaches a handler as an import side effect. Global logging therefore gets configured by importing a reusable library.

The project has no original tests or CI. `.python-version` says 3.10, the devcontainer uses 3.11, and this checkout's Python 3.10 environment is broken. `run.sh` contains a relative `uv run` command without a shebang and assumes the working directory; the README also offers an unpinned pip installation path. `requirements.txt` allows Altair 5.0 while `pyproject.toml` requires 5.5. There is no declared package build backend or CLI entry point. Local imports currently make this work, but packaging/deployment behavior is not well-defined.

Several comments and UI messages say only the first city is searched, while the backend and audited UI call actually process the full city list. The assumptions page describes 10x card points even though code correctly separates 1x card LP. Greedy/DP status behavior, dynamic mileage valuation tooltips, and “optimal” wording have drifted. `.gitignore` does not exclude the real headers JSON that the README recommends creating; the tracked example itself contains placeholders. The images illustrate the flow and one exposes membership tier, but I did not find a usable account credential in the reviewed screenshots.

Extract modules as they are touched for connection, correctness and API work, using explicit result types. Retain Streamlit for the paid beta if the polished onboarding meets the customer experience; a frontend replacement is not a prerequisite. Standardize a supported Python runtime and frozen install, add a smoke/contract/solver test pipeline, and move sensitive local inputs outside version control. A future paid service also needs health checks, deployment rollback, job failure metrics, secret-free error reporting, database backups and a tested restore path. None was established by this repository audit.

**F23 — Model eligibility and time separately from a quoted LP ratio.**

[main.py:596](/home/brad/Projects/aa_hotel_scrape/aa_hotel_optimizer/main.py:596) defines fastest completion as next-day checkout, and all strategies assume rewards from selected stays will be earned. The provider FAQ describes typical posting weeks after completion, with a transaction date reflecting check-in; it also distinguishes promotional miles from qualifying base miles and discusses no-show cancellation. Do not conflate checkout, posting, qualification credit, and activation of a new benefit. [Provider FAQ](https://www.aadvantagehotels.com/faq).

There is no code to validate consecutive-reservation reward treatment, property no-show terms, physical check-in, or whether a guest occupies the room. The FAQ's discussion of managing consecutive reservations is not evidence that every split yields additive LP. Brad's historical phantom bookings are useful product context, not proof that today's unattended bookings always qualify. Preserve the broad-search mode, but expose quoted rewards, eligibility assumptions, and any unverified posting conditions separately. Establish provider rules and sanitized real-world reconciliation cases before making guarantees about these uses.

**What is worth keeping**

- Existing single-night splitting, multiple-city searches, and comparison of price against LP provide a useful foundation for both modes.
- The Python normalization/optimization boundary is already partly separated from the UI and is straightforward to test.
- Every HTTP call has a timeout, HTTPS validation is not disabled, and cURL text is parsed rather than executed.
- Credential dictionaries are passed per search; no shared authenticated client or global token cache was found.
- Card miles and card LP are separately computed before the erroneous partner-bonus step.
- A lockfile exists, and the exact package versions could be installed and the UI exercised in isolation.

The immediate next engineering work is eliminating cURL acquisition, fixing the concrete regression cases, preserving results, and adding paid access with a thin agent API. Keep the current UI/search workflow through that work. The [service plan](SERVICE_PLAN.md) separates the small paid beta from later search enhancements.
