"""Ask the real assistant from a real browser, on the fictional demo firm.

Separate from run_flow.py on purpose: each run spends a little on the configured provider.
Run it with the e2e profile, as python assistant_flow.py after installing playwright.
"""

import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("BASE_URL", "http://web:8000")
SHOTS = Path(os.environ.get("SHOTS_DIR", "/tmp/shots"))  # noqa: S108


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(f"{BASE}/autentificare/")
        page.get_by_label("Email sau utilizator").fill("admin")
        page.get_by_label("Parolă").fill("1234")
        page.get_by_role("button", name="Intră în cont").click()
        page.get_by_role("link", name="Asistent AI").click()
        expect(page.get_by_role("heading", name="Asistent AI")).to_be_visible()
        if page.get_by_role("button", name="Întreabă").count():
            page.screenshot(path=SHOTS / "assistant-empty.png", full_page=True)

        page.get_by_role("button", name="Ce facturi sunt depășite?").click()
        expect(page.get_by_label("Întrebarea ta")).to_have_value("Ce facturi sunt depășite?")
        page.get_by_label("Întrebarea ta").fill("Ce s-a întâmplat cu veniturile mele luna aceasta?")
        page.get_by_role("button", name="Întreabă").click()
        expect(page.get_by_text("Cifre calculate de aplicație").first).to_be_visible(timeout=60000)
        page.screenshot(path=SHOTS / "assistant-answer.png", full_page=True)

        expect(page.get_by_label("Întrebarea ta")).to_be_visible(timeout=30000)
        page.get_by_label("Întrebarea ta").fill("Care este capitala Franței?")
        page.get_by_role("button", name="Întreabă").click()
        first = page.locator("details.message").first
        expect(first).to_contain_text("capitala Franței", timeout=5000)
        expect(first.get_by_text(re.compile("Nu am găsit"))).to_be_visible(timeout=60000)
        expect(first).not_to_contain_text("Paris")

        page.reload()
        with page.expect_response(lambda r: "q=venituri" in r.url):
            page.get_by_label("Caută în întrebări și răspunsuri").fill("venituri")
        expect(page.locator("#history")).not_to_contain_text("capitala")
        page.screenshot(path=SHOTS / "assistant-search.png", full_page=True)

        page.set_viewport_size({"width": 400, "height": 800})
        page.reload()
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"scrolls sideways at 400px by {overflow}px"
        page.screenshot(path=SHOTS / "assistant-mobile.png", full_page=True)
        assert not errors, errors
    print("OK: assistant flow passed")


if __name__ == "__main__":
    main()
