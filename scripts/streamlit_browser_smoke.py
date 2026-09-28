"""Exercise the actual Cloud entrypoint and shared UI with fictional provider IO."""

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile

from browser_provider_fixture import provider_fixture
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".local" / "streamlit-browser"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
origin = f"http://127.0.0.1:{port}"
reports = []


def passed(message):
    reports.append(message)
    print("PASS " + message, flush=True)


with tempfile.TemporaryDirectory(prefix="lp-streamlit-test-") as temp, ExitStack() as fixtures:
    fixture = Path(temp) / "fixture.py"
    fixture.write_text(
        "import runpy, sys\n"
        + f"sys.path.insert(0, {str(ROOT)!r})\n"
        + f"runpy.run_path({str(ROOT / 'streamlit_app.py')!r}, run_name='__main__')\n"
    )
    extension = Path(temp) / "companion"
    shutil.copytree(ROOT / "companion", extension)
    (extension / "config.js").write_text(f"globalThis.LP_APP_ORIGIN = {json.dumps(origin)};\n")
    with (ARTIFACTS / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(fixture),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(60):
                try:
                    with urllib.request.urlopen(origin + "/_stcore/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("Streamlit did not start.")
            with sync_playwright() as p:
                cached = sorted(
                    (Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux64/chrome")
                )
                launch_args = (
                    {"executable_path": str(cached[-1])} if cached else {"channel": "chromium"}
                )

                def launch():
                    return p.chromium.launch_persistent_context(
                        str(Path(temp) / "profile"),
                        headless=True,
                        **launch_args,
                        args=[
                            *provider_args,
                            f"--disable-extensions-except={extension}",
                            f"--load-extension={extension}",
                        ],
                        ignore_default_args=["--disable-extensions"],
                        viewport={"width": 1440, "height": 1100},
                    )

                signed_in = False
                account_id = "fixture-account"
                provider_calls = []
                delay_document = False
                document_ready = threading.Event()
                document_ready.set()

                def provider_response(url):
                    provider_calls.append(url)
                    if url == "/fixture-pending":
                        document_ready.wait(timeout=10)
                        return "image/svg+xml", '<svg xmlns="http://www.w3.org/2000/svg"/>'
                    elif "/session" in url:
                        data = (
                            {"uuid": account_id, "firstName": "Example", "secret": "DO-NOT-EXPORT"}
                            if signed_in
                            else None
                        )
                    elif "/places" in url:
                        data = [
                            {
                                "id": "fixture-city",
                                "name": "Chicago, Illinois",
                                "type": "AGODA_CITY",
                            }
                        ]
                    elif "/searchRequest" in url:
                        data = {"uuid": "fixture-search"}
                    elif "/search/fixture-search" in url:
                        data = {
                            "results": [
                                {
                                    "hotel": {"id": "fixture", "name": "Fixture Hotel"},
                                    "grandTotalPublishedPriceInclusiveWithFees": {"amount": 125},
                                    "rewards": 5000,
                                    "secret": "DO-NOT-EXPORT",
                                }
                            ]
                        }
                    else:
                        return (
                            "text/html",
                            "<!doctype html><title>Fixture AA Hotels</title>"
                            + ('<img src="/fixture-pending">' if delay_document else ""),
                        )
                    return "application/json", json.dumps(data)

                provider_args = fixtures.enter_context(provider_fixture(provider_response))
                context = launch()
                if not context.service_workers:
                    context.wait_for_event("serviceworker", timeout=15000)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)
                expect(page.locator(".result-card")).to_be_visible(timeout=30000)
                expect(page.locator("#page-title")).to_have_text("Same trip. More Loyalty Points.")
                expect(page.locator(".tag.sample")).to_contain_text("FICTIONAL QUOTES")
                assert (
                    page.locator(".lp-app")
                    .evaluate("e=>getComputedStyle(e).fontFamily")
                    .startswith('"DM Sans"')
                )
                page.screenshot(path=str(ARTIFACTS / "desktop.png"), full_page=True)
                page.set_viewport_size({"width": 1280, "height": 800})
                page.screenshot(path=str(ARTIFACTS / "store-screenshot-1280x800.png"))
                page.set_viewport_size({"width": 1440, "height": 1100})
                passed("New planner is the default and loads the shared design and optimizer")

                page.locator("#city").fill("Chicago, Illinois")
                page.locator("#split").uncheck()
                page.locator("#demo-button").click()
                expect(page.locator(".booking-row")).to_have_count(1, timeout=15000)
                expect(page.locator("#city")).to_have_value("Chicago, Illinois")
                assert not page.locator("#split").is_checked()
                page.locator("#status-tab").click()
                page.locator("#objective").select_option("cost")
                page.locator("#demo-button").click()
                expect(page.locator(".result-heading h2")).to_have_text(
                    "Your status plan", timeout=15000
                )
                passed("Trip edits survive reruns; whole stays and status comparisons work")

                page.locator("#pricing-button").click()
                expect(page.locator("#dialog-eyebrow")).to_have_text("PLANNED PRICING")
                expect(page.locator("#dialog-content")).to_contain_text("$9")
                expect(page.locator("#dialog-content")).to_contain_text("$19/month")
                expect(page.locator("#buy-pass")).to_be_disabled()
                expect(page.locator("#buy-membership")).to_be_disabled()
                page.locator("#close-dialog").click()
                page.locator("#account-button").click()
                expect(page.locator("#dialog-content")).to_contain_text("still being connected")
                page.locator("#close-dialog").click()
                passed(
                    "Email and payment availability are explicit; no chargeable preview checkout"
                )

                page.locator("#connect-button").click()
                expect(page.locator("#session-curl")).to_have_count(0)
                expect(page.locator("#pair-button")).to_be_enabled(timeout=10000)
                page.locator("#pair-button").click()
                expect(page.locator("#dialog-error")).to_contain_text(
                    "sign in normally", timeout=30000
                )
                signed_in = True
                page.locator("#pair-button").click()
                expect(page.locator("#dialog")).not_to_be_visible(timeout=30000)
                expect(page.locator("#connection-title")).to_have_text("AA Hotels connected")
                assert "DO-NOT-EXPORT" not in page.locator(".lp-app").inner_text()
                passed(
                    "Actual Chrome companion connects through the AA tab; no cURL or copied credentials"
                )
                page.reload()
                expect(page.locator("#connection-title")).to_have_text(
                    "AA Hotels connected", timeout=30000
                )
                expect(page.locator(".result-card")).to_be_visible()
                passed("Remembered connection restores after app reload without another login")

                # Reconnecting during an existing AA tab's load must wait for its
                # document, without asking the customer to repeat setup.
                aa_tab = next(
                    tab
                    for tab in context.pages
                    if tab.url.startswith("https://www.aadvantagehotels.com")
                )
                delay_document = True
                document_ready.clear()
                aa_tab.reload(wait_until="domcontentloaded")
                calls_before = sum("/session" in url for url in provider_calls)
                page.reload()
                expect(page.locator(".result-card")).to_be_visible()
                page.wait_for_timeout(500)
                assert sum("/session" in url for url in provider_calls) == calls_before
                document_ready.set()
                delay_document = False
                expect(page.locator("#connection-title")).to_have_text(
                    "AA Hotels connected", timeout=15000
                )
                passed("Reconnection waits for an existing AA tab to finish loading")
                page.locator("#city").fill("Chicago, Illinois")
                for tab in context.pages:
                    if tab.url.startswith("https://www.aadvantagehotels.com"):
                        tab.close()
                page.locator("#trip-tab").click()
                start = date.today() + timedelta(days=28)
                page.locator("#check-in").fill(start.isoformat())
                page.locator("#check-out").fill((start + timedelta(days=1)).isoformat())
                page.locator("#search-button").click()
                expect(page.locator(".result-top h2")).to_have_text("Fixture Hotel", timeout=20000)
                expect(page.locator(".tag")).to_have_text("LIVE QUOTE COMPARISON")
                expect(page.locator("#city")).to_have_value("Chicago, Illinois")
                page.locator("#history-button").click()
                expect(page.locator(".history-row")).to_have_count(1)
                page.locator("[data-search]").click()
                expect(page.locator(".result-top h2")).to_have_text("Fixture Hotel")
                with page.expect_download() as download:
                    page.locator("#download-plan").click()
                data = json.loads(Path(download.value.path()).read_text())
                assert data["plan"]["earned_lp"] == 5000 and not data["sample"]
                passed(
                    "Search-to-results, session history and JSON download work with simulated AA responses"
                )

                phone_browser = p.chromium.launch(
                    **({"executable_path": str(cached[-1])} if cached else {})
                )
                mobile = phone_browser.new_context(
                    viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
                )
                phone = mobile.new_page()
                phone.on("pageerror", lambda error: errors.append(str(error)))
                phone.goto(origin)
                expect(phone.locator(".result-card")).to_be_visible(timeout=30000)
                expect(phone.locator("#connection-title")).to_have_text("Connect AA Hotels")
                phone.locator("#history-button").click()
                expect(phone.locator(".history-row")).to_have_count(0)
                phone.locator("#close-dialog").click()
                assert phone.locator(".lp-app").evaluate("e=>e.scrollWidth<=window.innerWidth")
                phone.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)
                phone.locator("#pricing-button").click()
                expect(phone.locator("#buy-pass")).to_be_disabled()
                phone.screenshot(path=str(ARTIFACTS / "pricing-mobile.png"), full_page=True)
                phone.locator("#close-dialog").click()
                phone.locator("#connect-button").click()
                expect(phone.locator("#session-curl")).to_have_count(0)
                with phone.expect_download() as package:
                    phone.locator("#download-companion").click()
                with ZipFile(package.value.path()) as zip_file:
                    manifest = json.loads(zip_file.read("manifest.json"))
                    assert "alarms" not in manifest["permissions"]
                    assert manifest["content_scripts"][0]["matches"] == [
                        "https://aahoteloptimizer.streamlit.app/*"
                    ]
                    assert "icon-128.png" in zip_file.namelist()
                phone.screenshot(path=str(ARTIFACTS / "connection-mobile.png"), full_page=True)
                passed(
                    "Published app can deliver the actual domain-bound beta package without cURL"
                )
                passed(
                    "Phone layout fits; another browser session cannot access connections or search history"
                )

                context.close()
                context = launch()
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)
                expect(page.locator("#connection-title")).to_have_text(
                    "AA Hotels connected", timeout=30000
                )
                passed("Remembered connection also restores after restarting Chrome")
                signed_in = False
                page.reload()
                expect(page.locator("#connection-title")).to_have_text(
                    "Sign in to AA Hotels again", timeout=30000
                )
                signed_in = True
                page.locator("#connect-button").click()
                page.locator("#pair-button").click()
                expect(page.locator("#dialog")).not_to_be_visible(timeout=30000)
                expect(page.locator("#connection-title")).to_have_text("AA Hotels connected")
                passed("Only an expired AA session requires sign-in again; reconnect recovers")
                account_id = "different-account"
                previous_calls = len(provider_calls)
                page.locator("#city").fill("Chicago, Illinois")
                page.locator("#check-in").fill(start.isoformat())
                page.locator("#check-out").fill((start + timedelta(days=1)).isoformat())
                page.locator("#search-button").click()
                expect(page.locator("#connection-title")).to_have_text(
                    "Sign in to AA Hotels again", timeout=30000
                )
                assert not any(
                    "/places" in url or "/searchRequest" in url
                    for url in provider_calls[previous_calls:]
                )
                passed(
                    "Changing AA accounts stops comparison before fetching another account's offers"
                )
                page.locator("#connect-button").click()
                page.locator("#pair-button").click()
                expect(page.locator("#dialog")).not_to_be_visible(timeout=30000)
                page.locator("#connect-button").click()
                page.locator("#session-disconnect").click()
                expect(page.locator("#connection-title")).to_have_text(
                    "Connect AA Hotels", timeout=15000
                )
                expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                assert not errors, errors
                passed("Disconnect clears connection; no browser or Streamlit errors")
                context.close()
                phone_browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
(ARTIFACTS / "report.json").write_text(json.dumps(reports, indent=2))
