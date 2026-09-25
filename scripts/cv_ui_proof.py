"""Capture owner-app screenshots against the local stack."""

from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("artifacts/runtime/ui-proof")
BASE = "http://127.0.0.1:8000"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE}/cv/", wait_until="networkidle", timeout=60000)
        page.get_by_text("T426").first.wait_for()
        page.screenshot(path=str(OUT / "overview-desktop.png"), full_page=True)
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.get_by_text("Lot 2").first.wait_for()
        page.screenshot(path=str(OUT / "auction-desktop.png"), full_page=True)
        page.get_by_role("link", name="2021 ford transit").first.click()
        page.get_by_text("Final safe hammer").wait_for()
        page.screenshot(path=str(OUT / "vehicle-desktop.png"), full_page=True)
        page.get_by_role("button", name="Market").click()
        page.screenshot(path=str(OUT / "market-desktop.png"), full_page=True)
        page.get_by_role("button", name="Costs").click()
        page.get_by_text("UNKNOWN").first.wait_for()
        page.screenshot(path=str(OUT / "costs-desktop.png"), full_page=True)
        page.get_by_role("button", name="Diligence").click()
        page.screenshot(path=str(OUT / "diligence-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 768, "height": 1024})
        page.screenshot(path=str(OUT / "vehicle-tablet.png"), full_page=True)
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(f"{BASE}/cv/", wait_until="networkidle", timeout=60000)
        mobile.get_by_text("Auctions").last.click()
        mobile.get_by_text("T426").first.wait_for()
        mobile.get_by_role("link", name="Mid Ulster T426").click()
        mobile.get_by_text("Lot 2").first.wait_for()
        mobile.screenshot(path=str(OUT / "auction-mobile.png"), full_page=True)
        mobile.get_by_role("link", name="2021 ford transit").first.click()
        mobile.get_by_text("Final safe hammer").wait_for()
        mobile.screenshot(path=str(OUT / "vehicle-mobile.png"), full_page=True)
        browser.close()
    print("wrote", OUT)


if __name__ == "__main__":
    main()
