"""Owner-app flows against the running stack."""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000/cv"


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/", wait_until="networkidle", timeout=60000)
        page.get_by_text("T426").first.wait_for()
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.get_by_text("Lot 2").first.wait_for()
        lot2 = page.locator("article").filter(has_text="Lot 2 ·").get_by_role("button")
        if lot2.get_attribute("aria-label") != "Unselect":
            lot2.click()
        page.reload(wait_until="networkidle")
        page.locator("article").filter(has_text="Lot 2 ·").get_by_role("button", name="Unselect").wait_for()
        page.locator('a[href$="-2"]').click()
        page.get_by_role("button", name="Market", exact=True).click()
        page.locator(".recharts-surface").wait_for()
        page.get_by_text("£").first.wait_for()
        page.get_by_role("button", name="Costs & taxes", exact=True).click()
        page.get_by_text("Customs duty").wait_for()
        page.get_by_label("Current bid GBP").fill("1500")
        page.get_by_role("button", name="Save bid").click()
        page.get_by_text("£1,500").wait_for()
        page.get_by_role("button", name="Why this tax?", exact=True).click()
        page.get_by_text("SAFE GB IMPORT").or_(page.get_by_text("SAFE WITHOUT NI PROOF")).or_(page.get_by_text("SAFE MAX BID")).or_(page.get_by_text("ESTIMATED MAX BID")).first.wait_for()
        page.get_by_role("button", name="Evidence", exact=True).click()
        page.get_by_label("Reference").fill("owner-note-1")
        page.get_by_role("button", name="Save evidence").click()
        page.get_by_text("Evidence recorded", exact=False).wait_for(timeout=120000)
        page.goto(BASE + "/", wait_until="networkidle")
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.get_by_role("button", name="REJECT").click()
        page.locator('a[href$="-3"]').click()
        page.get_by_role("heading", name="Lot 3").wait_for()
        page.get_by_text("REJECT").first.wait_for()
        assert page.get_by_text("BUY READY").count() == 0
        page.goto(BASE + "/auctions", wait_until="networkidle")
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.get_by_role("button", name="NEED MARKET DATA").click()
        page.get_by_text("NEED MARKET DATA").first.wait_for()
        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(BASE + "/", wait_until="networkidle", timeout=60000)
        mobile.get_by_role("link", name="Auctions").last.click()
        mobile.get_by_role("link", name="Mid Ulster T426").click()
        mobile.locator('a[href$="-2"]').click()
        mobile.get_by_role("button", name="Why this tax?", exact=True).click()
        mobile.get_by_text("SAFE GB IMPORT").or_(mobile.get_by_text("SAFE WITHOUT NI PROOF")).or_(mobile.get_by_text("SAFE MAX BID")).or_(mobile.get_by_text("ESTIMATED MAX BID")).first.wait_for()
        browser.close()
    print("e2e-pass")


if __name__ == "__main__":
    main()
