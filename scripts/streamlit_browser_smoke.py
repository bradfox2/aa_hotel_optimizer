"""Exercise the actual Cloud entrypoint and shared UI with fictional provider IO."""

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

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


with tempfile.TemporaryDirectory(prefix="lp-streamlit-test-") as temp:
    # All production code, including streamlit_app.py, is executed unchanged.
    # Only external AA provider functions are replaced; no real credentials.
    fixture = Path(temp) / "fixture.py"
    fixture.write_text(
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from aa_hotel_optimizer import main as provider\n"
        "provider.discover_place_ids=lambda *a, **kw: [('Fixture City', 'fixture')]\n"
        "provider.search_aadvantage_hotels=lambda *a, **kw: 'fixture'\n"
        "provider.get_hotel_results=lambda *a, **kw: {'results': [{'hotel': {'id': 'fixture', 'name': 'Fixture Hotel'}, 'grandTotalPublishedPriceInclusiveWithFees': {'amount': 125}, 'rewards': 5000}]}\n"
        f"runpy.run_path({str(ROOT / 'streamlit_app.py')!r}, run_name='__main__')\n"
    )
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
                browser = p.chromium.launch(
                    **({"executable_path": str(cached[-1])} if cached else {})
                )
                context = browser.new_context(viewport={"width": 1440, "height": 1100})
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
                page.locator("#session-curl").fill(
                    "curl https://other.example -H 'Cookie: fixture-only-secret'"
                )
                page.locator("#session-connect").click()
                expect(page.locator("#dialog-error")).to_be_visible(timeout=15000)
                expect(page.locator("#session-curl")).to_have_value("")
                page.locator("#session-curl").fill(
                    "curl https://www.aadvantagehotels.com/rest/aadvantage-hotels/searchRequest -H 'Cookie: fixture-only-secret'"
                )
                page.locator("#session-connect").click()
                expect(page.locator("#dialog")).not_to_be_visible(timeout=15000)
                expect(page.locator("#connection-title")).to_have_text("AA Hotels session added")
                assert "fixture-only-secret" not in page.locator(".lp-app").inner_text()
                passed(
                    "Temporary connection validates requests and removes pasted credentials from the form"
                )

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

                mobile = browser.new_context(
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
                passed(
                    "Phone layout fits; another browser session cannot access connections or search history"
                )

                page.locator("#connect-button").click()
                page.locator("#session-disconnect").click()
                expect(page.locator("#connection-title")).to_have_text(
                    "Connect AA Hotels", timeout=15000
                )
                expect(page.locator('[data-testid="stException"]')).to_have_count(0)
                assert not errors, errors
                passed("Disconnect clears connection; no browser or Streamlit errors")
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
(ARTIFACTS / "report.json").write_text(json.dumps(reports, indent=2))
