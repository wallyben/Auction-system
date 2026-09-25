from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("artifacts/runtime/ui-proof")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto("http://127.0.0.1:8000/cv/", wait_until="networkidle", timeout=60000)
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.locator('a[href$="-8"]').click()
        page.get_by_text("Max bid").first.wait_for()
        page.screenshot(path=str(OUT / "lot8-scenarios-desktop.png"), full_page=True)
        page.goto("http://127.0.0.1:8000/cv/", wait_until="networkidle")
        page.get_by_role("link", name="Mid Ulster T426").click()
        page.locator('a[href$="-13"]').click()
        page.get_by_text("LIKELY NORTHERN IRELAND").first.wait_for()
        page.screenshot(path=str(OUT / "lot13-ni-scenarios-desktop.png"), full_page=True)
        browser.close()
    print("shots-ok")


if __name__ == "__main__":
    main()
