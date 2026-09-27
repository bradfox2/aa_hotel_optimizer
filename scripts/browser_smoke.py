"""Isolated UI + provider-adapter smoke test. No real provider or billing calls."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".local" / "browser-smoke"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
origin = f"http://127.0.0.1:{port}"
reports = []


def passed(name):
    reports.append(name)
    print(f"PASS {name}", flush=True)


with tempfile.TemporaryDirectory(prefix="lp-browser-test-") as temp:
    env = os.environ | {
        "LP_ENVIRONMENT": "development",
        "LP_PUBLIC_URL": origin,
        "LP_DATABASE_URL": f"sqlite:///{temp}/test.sqlite3",
        "LP_PROVIDER_ENABLED": "true",
        "LP_SMTP_HOST": "",
        "LP_RESEND_API_KEY": "",
        "LP_EMAIL_FROM": "",
        "LP_BETA_EMAILS": "",
        "LP_STRIPE_SECRET_KEY": "",
        "LP_STRIPE_PRICE_ID": "",
        "LP_STRIPE_WEBHOOK_SECRET": "",
    }
    with (ARTIFACTS / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "aa_hotel_optimizer.service.app:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(origin + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError(
                            "Test server failed; see .local/browser-smoke/server.log"
                        ) from None
                    time.sleep(0.1)
            else:
                raise RuntimeError("Test server did not become ready")
            with sync_playwright() as playwright:
                cached = sorted(
                    (Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux64/chrome")
                )
                extension = Path(temp) / "companion"
                shutil.copytree(ROOT / "companion", extension)
                (extension / "config.js").write_text(
                    f"globalThis.LP_APP_ORIGIN = {json.dumps(origin)};\n"
                )
                context = playwright.chromium.launch_persistent_context(
                    str(Path(temp) / "profile"),
                    headless=True,
                    **({"executable_path": str(cached[-1])} if cached else {"channel": "chromium"}),
                    args=[
                        f"--disable-extensions-except={extension}",
                        f"--load-extension={extension}",
                    ],
                    ignore_default_args=["--disable-extensions"],
                    viewport={"width": 1440, "height": 1100},
                    reduced_motion="reduce",
                )
                if not context.service_workers:
                    context.wait_for_event("serviceworker", timeout=15000)
                passed("Chrome MV3 companion loads in an isolated browser profile")
                page = context.new_page()

                def sandbox_config(route):
                    response = route.fetch()
                    config = response.json()
                    config.update(billing_enabled=True, billing_test_mode=True)
                    route.fulfill(response=response, json=config)

                page.route("**/v1/config", sandbox_config)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)
                page.get_by_text("Your stay, optimized").wait_for()
                assert page.get_by_text("EXAMPLE · FICTIONAL QUOTES").is_visible()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(ARTIFACTS / "desktop.png"), full_page=True)
                passed("Desktop example comparison and layout")

                page.get_by_role("button", name="Sign in", exact=True).click()
                page.get_by_label("Email address", exact=True).fill("browser-test@example.com")
                page.get_by_role("button", name="Send me a sign-in link").click()
                login_url = page.get_by_role("link", name="Continue to the app").get_attribute(
                    "href"
                )
                page.goto(login_url)
                page.get_by_role("button", name="My account", exact=True).wait_for()
                assert "#login=" not in page.url
                page.reload()
                page.get_by_role("button", name="My account", exact=True).wait_for()
                assert context.cookies()[0]["httpOnly"]
                passed("Email-link account flow and persistent HttpOnly session")

                page.get_by_role("button", name="For agents").click()
                page.get_by_role("button", name="Create a key", exact=True).click()
                page.get_by_text("Copy this key now.", exact=False).wait_for()
                key = page.locator(".key-output").inner_text()
                assert key.startswith("lp_agent_")
                assert context.request.get(
                    origin + "/v1/searches", headers={"Authorization": "Bearer " + key}
                ).ok
                page.get_by_role("button", name="Close dialog").click()
                page.get_by_role("button", name="For agents").click()
                page.get_by_role("button", name="Revoke", exact=True).click()
                page.get_by_role("button", name="Revoke", exact=True).wait_for(state="detached")
                assert (
                    context.request.get(
                        origin + "/v1/searches", headers={"Authorization": "Bearer " + key}
                    ).status
                    == 401
                )
                page.get_by_role("button", name="Close dialog").click()
                passed("Create and revoke a scoped agent key in the UI")

                # Mock every AA request. This is a fresh browser context with no AA cookies.
                provider_calls = []

                def provider_route(route):
                    url = route.request.url
                    provider_calls.append(url)
                    if "/session" in url:
                        data = {
                            "uuid": "fictional-account",
                            "firstName": "Example",
                            "rewardAccountNumber": "DO-NOT-EXPORT",
                            "secret": "DO-NOT-EXPORT",
                        }
                    elif "/places" in url:
                        data = [
                            {
                                "id": "AGODA_CITY_1",
                                "name": "Phoenix, Arizona",
                                "type": "AGODA_CITY",
                                "secret": "DO-NOT-EXPORT",
                            }
                        ]
                    elif "/searchRequest" in url:
                        data = {"uuid": "fictional-search"}
                    elif "/search/fictional-search" in url:
                        data = {
                            "results": [
                                {
                                    "id": "rate-1",
                                    "hotel": {"id": "hotel-1", "name": "Fictional Test Hotel"},
                                    "rewards": 4000,
                                    "grandTotalPublishedPriceInclusiveWithFees": {
                                        "amount": 100,
                                        "currency": "USD",
                                    },
                                    "secret": "DO-NOT-EXPORT",
                                }
                            ]
                        }
                    else:
                        route.fulfill(
                            status=200,
                            content_type="text/html",
                            body="<!doctype html><title>Fictional provider</title>",
                        )
                        return
                    route.fulfill(
                        status=200, content_type="application/json", body=json.dumps(data)
                    )

                context.route("https://www.aadvantagehotels.com/**", provider_route)
                provider = context.new_page()
                provider.goto("https://www.aadvantagehotels.com/")
                source = (ROOT / "companion/provider.js").read_text()
                function = source[source.index("export async function") :].replace(
                    "export async function providerRequest", "async function", 1
                )
                session = provider.evaluate(f"({function})", {"kind": "session"})
                assert session["status"] == "ok" and "DO-NOT-EXPORT" not in json.dumps(session)
                page.bring_to_front()
                page.locator("#connect-button").click()
                page.locator("#pair-button").click(timeout=15000)
                page.get_by_role("button", name="AA Hotels connected", exact=False).wait_for(
                    timeout=15000
                )
                passed(
                    "Customer connects AA Hotels through the actual companion UI (mock provider)"
                )
                # The actual service worker claims, executes and returns all tasks.
                start = page.locator("#check-in").input_value()
                from datetime import date, timedelta

                page.locator("#check-out").fill(str(date.fromisoformat(start) + timedelta(days=1)))
                page.get_by_role("button", name="Compare my stay", exact=False).click()
                page.get_by_text("Comparing your dates…").wait_for()
                page.get_by_role("heading", name="Fictional Test Hotel", exact=True).first.wait_for(
                    timeout=45000
                )
                passed(
                    "Browser provider adapter to durable search to customer result (all AA responses mocked)"
                )

                page.reload()
                page.get_by_role("button", name="Saved searches", exact=True).click()
                page.locator("[data-search]").first.click()
                page.get_by_role(
                    "heading", name="Fictional Test Hotel", exact=True
                ).first.wait_for()
                with page.expect_download() as downloaded:
                    page.get_by_role("button", name="Download JSON", exact=True).click()
                assert downloaded.value.suggested_filename.endswith(".json")
                passed("Saved result survives reload and exports a booking plan")

                page.locator("#check-out").fill(str(date.fromisoformat(start) + timedelta(days=1)))
                page.get_by_role("button", name="Compare my stay", exact=False).click()
                page.get_by_text("Comparing your dates…").wait_for()
                page.get_by_role("heading", name="Fictional Test Hotel", exact=True).first.wait_for(
                    timeout=45000
                )
                page.get_by_role("button", name="Compare my stay", exact=False).click()
                page.get_by_role("heading", name="Keep comparing your options.").wait_for()
                assert page.locator("#dialog-content").get_by_text("$9", exact=False).count()
                assert page.locator("#dialog-content").get_by_text("$19/month", exact=True).count()
                page.screenshot(path=str(ARTIFACTS / "paywall-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(ARTIFACTS / "paywall-mobile.png"), full_page=True)
                passed("Two free searches, then an accessible $9/$19 choice on desktop and phone")

                checkout_requests = []

                def checkout_route(route):
                    checkout_requests.append(route.request.post_data_json)
                    route.fulfill(json={"url": "https://checkout.stripe.com/mock-pass"})

                page.route("**/v1/billing/checkout", checkout_route)
                context.route(
                    "https://checkout.stripe.com/**",
                    lambda route: route.fulfill(
                        content_type="text/html", body="<h1>Mock Stripe checkout</h1>"
                    ),
                )
                selected_date = page.locator("#check-in").input_value()
                page.locator("#buy-pass").click()
                page.get_by_role("heading", name="Mock Stripe checkout").wait_for()
                assert checkout_requests == [{"product": "trip_pass"}]
                page.goto(origin + "/?billing=cancelled")
                page.get_by_text(
                    "Checkout cancelled. Your search details are ready below."
                ).wait_for()
                assert page.locator("#check-in").input_value() == selected_date
                page.set_viewport_size({"width": 1440, "height": 1100})
                passed(
                    "Trip-pass checkout intent and search restoration after cancellation (Stripe mocked)"
                )

                page.get_by_role("tab", name="Reach a status goal", exact=True).click()
                page.get_by_role("button", name="Try an example first", exact=True).click()
                page.get_by_text("Your status plan", exact=True).wait_for()
                passed("Status-gap search through the customer UI")

                page.set_viewport_size({"width": 390, "height": 844})
                page.get_by_role("tab", name="Plan a trip", exact=True).click()
                page.get_by_role("button", name="Try an example first", exact=True).click()
                page.get_by_text("Your stay, optimized", exact=True).wait_for()
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
                page.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
                page.get_by_role("button", name="My account", exact=True).click()
                page.get_by_role("button", name="Delete account", exact=True).click()
                page.get_by_label("Type “delete my account” to confirm").fill("delete my account")
                page.get_by_role("button", name="Delete my account", exact=True).click()
                page.get_by_role("button", name="Sign in", exact=True).wait_for()
                assert context.request.get(origin + "/v1/me").status == 401
                passed("Phone layout and self-service account deletion")
                assert not errors, errors
                passed("No browser JavaScript errors")
                context.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
(ARTIFACTS / "report.json").write_text(
    json.dumps({"passed": reports, "real_provider_used": False}, indent=2) + "\n"
)
