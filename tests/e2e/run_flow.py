"""Critical user flow in a real browser against the running development stack.

register -> verify email -> create firm -> invite colleague -> colleague joins ->
a third user has no access. Also captures screenshots for review.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import uuid
from datetime import date
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("BASE_URL", "http://web:8000")
MAILPIT = os.environ.get("MAILPIT_URL", "http://mailpit:8025")
SHOTS = Path(os.environ.get("SHOTS_DIR", "/tmp/shots"))  # noqa: S108
PASSWORD = "o-parola-de-test-lunga"  # noqa: S105


def latest_link(recipient, fragment):
    url = f"{MAILPIT}/api/v1/search?query=" + urllib.parse.quote(f'to:"{recipient}"')
    with urllib.request.urlopen(url) as response:  # noqa: S310
        messages = json.load(response)["messages"]
    assert messages, f"no mail for {recipient}"
    for message in messages:
        with urllib.request.urlopen(f"{MAILPIT}/api/v1/message/{message['ID']}") as response:  # noqa: S310
            body = json.load(response)["Text"]
        link = re.search(rf"https?://\S*{fragment}\S*", body)
        if link:
            return link.group(0)
    raise AssertionError(f"no {fragment} link in mail for {recipient}")


def register(page, email):
    page.goto(f"{BASE}/inregistrare/")
    page.get_by_label("Nume complet").fill("Utilizator Test")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Parolă").fill(PASSWORD)
    page.get_by_role("button", name="Creează contul").click()
    expect(page.get_by_role("heading", name="Verifică emailul")).to_be_visible()
    page.goto(latest_link(email, "verificare-email"))
    expect(page.get_by_role("heading", name="Adresă confirmată")).to_be_visible()


def sign_in(page, login, password=PASSWORD):
    page.goto(f"{BASE}/autentificare/")
    page.get_by_label("Email sau utilizator").fill(login)
    page.get_by_label("Parolă").fill(password)
    page.get_by_role("button", name="Intră în cont").click()


def finance_flow(page, run):
    """Create records by hand and by import, then read them back on the dashboard."""
    errors_before = []

    def keep_real_errors(message):
        # This header needs HTTPS or localhost, and the test browser reaches http://web.
        if message.type == "error" and "Cross-Origin-Opener-Policy" not in message.text:
            errors_before.append(message.text)

    page.on("console", keep_real_errors)
    expect(page.get_by_text("Nu există încă date pentru grafic")).to_be_visible()

    page.get_by_role("link", name="Vânzări", exact=True).click()
    page.get_by_role("link", name="Clienți").click()
    page.get_by_role("link", name="Client nou").click()
    page.get_by_label("Denumire").fill("Client E2E SRL")
    page.get_by_role("button", name="Salvează").click()
    expect(page.get_by_text("Clientul a fost adăugat")).to_be_visible()

    today = date.today().isoformat()
    page.get_by_role("link", name="Vânzări", exact=True).click()
    page.get_by_role("link", name="Factură nouă").click()
    page.get_by_label("Număr").fill(f"E2E-{run}")
    page.get_by_label("Client").select_option(label="Client E2E SRL")
    page.get_by_label("Data emiterii").fill(today)
    page.get_by_label("Valoare fără TVA").fill("1.000,00")
    page.get_by_label(re.compile("^TVA")).fill("190,00")
    page.get_by_label("Total").fill("1.190,00")
    page.get_by_role("button", name="Salvează factura").click()
    expect(page.get_by_text("a fost înregistrată")).to_be_visible()
    page.get_by_label("Sumă încasată").fill("190")
    page.get_by_role("button", name="Salvează încasarea").click()
    expect(page.get_by_text("Încasarea a fost înregistrată")).to_be_visible()
    expect(page.get_by_text("1.000,00 lei").first).to_be_visible()

    page.get_by_role("link", name="Importuri").click()
    page.get_by_label("Ce imporți").select_option("expenses")
    content = (
        "data;furnizor;numar_document;categorie;net;tva;total\n"
        f"{date.today():%d.%m.%Y};Enel;A1;Utilități;100,00;19,00;119,00\n"
        f"{date.today():%d.%m.%Y};Greșit;A2;;10,00;0,00;11,00\n"
    )
    page.get_by_label("Fișier").set_input_files(
        {"name": "cheltuieli.csv", "mimeType": "text/csv", "buffer": content.encode()}
    )
    page.get_by_role("button", name="Verifică fișierul").click()
    expect(page.get_by_text("Nu dovedește că datele contabile")).to_be_visible()
    page.screenshot(path=SHOTS / "import-preview.png", full_page=True)
    page.get_by_role("button", name="Importă rândurile valide (1)").click()
    expect(page.get_by_text("Rânduri importate: 1")).to_be_visible()

    page.get_by_role("link", name="Prezentare generală").click()
    expect(page.get_by_text("1.000,00 lei").first).to_be_visible()
    expect(page.get_by_text("Nu este profit contabil")).to_be_visible()
    expect(page.locator("canvas")).to_be_visible()
    page.wait_for_function("window.Chart && Object.keys(window.Chart.instances).length === 1")
    drawn = page.evaluate(
        "Object.values(window.Chart.instances)[0].data.datasets.map(d => d.data.at(-1))"
    )
    assert drawn == [1000, 100], drawn
    page.get_by_text("Vezi cifrele ca tabel").click()
    page.screenshot(path=SHOTS / "finance-dashboard.png", full_page=True)

    page.set_viewport_size({"width": 400, "height": 800})
    firm = page.url.split("/t/")[1].split("/")[0]
    for route in ("", "vanzari/", "cheltuieli/", "stocuri/", "importuri/", "rapoarte/"):
        page.goto(f"{BASE}/t/{firm}/{route}")
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{route} scrolls sideways at 400px by {overflow}px"
    page.screenshot(path=SHOTS / "finance-mobile.png", full_page=True)
    page.set_viewport_size({"width": 1280, "height": 900})
    assert not errors_before, errors_before


def main():
    run = uuid.uuid4().hex[:8]
    owner, colleague, outsider = (f"{who}-{run}@example.test" for who in ("o", "c", "x"))
    SHOTS.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        errors = []

        def session():
            context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ro-RO")
            page = context.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            return page

        page = session()
        page.goto(BASE)
        expect(page.get_by_text("Aplicație în construcție")).to_be_visible()
        expect(page.get_by_text("Exemplu ilustrativ")).to_be_visible()
        page.screenshot(path=SHOTS / "landing-desktop.png", full_page=True)
        page.set_viewport_size({"width": 400, "height": 800})
        page.goto(BASE)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"landing scrolls sideways at 400px by {overflow}px"
        page.get_by_role("button", name="Meniu").click()
        expect(page.get_by_role("link", name="Prețuri").first).to_be_visible()
        page.screenshot(path=SHOTS / "landing-mobile.png", full_page=True)
        page.set_viewport_size({"width": 1280, "height": 900})

        register(page, owner)
        sign_in(page, owner)
        expect(page.get_by_role("heading", name="Firmele mele")).to_be_visible()
        page.get_by_role("link", name="Adaugă o firmă").click()
        page.get_by_label("Numele firmei").fill(f"E2E {run} SRL")
        page.get_by_role("button", name="Creează firma").click()
        expect(page.get_by_role("heading", name="Prezentare generală")).to_be_visible()
        dashboard = page.url
        page.screenshot(path=SHOTS / "tenant-dashboard.png", full_page=True)

        finance_flow(page, run)

        page.goto(dashboard)
        page.get_by_role("link", name="Membri").click()
        page.get_by_label("Email").fill(colleague)
        page.get_by_label("Rol").select_option("accountant")
        page.get_by_role("button", name="Trimite invitația").click()
        expect(page.get_by_text("Invitația a fost trimisă")).to_be_visible()

        guest = session()
        register(guest, colleague)
        invitation = latest_link(colleague, "invitatii")
        sign_in(guest, colleague)
        guest.goto(invitation)
        guest.get_by_role("button", name="Acceptă invitația").click()
        expect(guest.get_by_role("heading", name="Prezentare generală")).to_be_visible()
        assert guest.url == dashboard
        assert guest.goto(dashboard.rstrip("/") + "/membri/").status == 403

        stranger = session()
        register(stranger, outsider)
        sign_in(stranger, outsider)
        assert stranger.goto(dashboard).status == 404

        staff = session()
        sign_in(staff, "superadmin", "1234")
        expect(staff.get_by_role("heading", name="Prezentare generală")).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-overview.png", full_page=True)
        staff.get_by_role("link", name="Firme").click()
        with staff.expect_response(lambda r: "q=E2E" in r.url):
            staff.get_by_label("Caută după nume").fill(f"E2E {run}")
        row = staff.get_by_role("row").filter(has_text=f"E2E {run} SRL")
        expect(row).to_be_visible()
        expect(staff.get_by_role("row")).to_have_count(2)
        assert owner not in staff.content()
        staff.screenshot(path=SHOTS / "platform-tenants.png", full_page=True)

        row.get_by_label(f"Motiv pentru E2E {run} SRL").fill("test E2E")
        row.get_by_role("button", name="Suspendă").click()
        expect(staff.get_by_text("Starea firmei a fost schimbată")).to_be_visible()
        assert page.goto(dashboard).status == 403
        staff.get_by_role("link", name="Jurnal de audit").click()
        expect(staff.get_by_text("test E2E").first).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-audit.png", full_page=True)

        # AI consumption is for the superadmin only: a firm's owner sees no trace of it.
        # Needs seed_ai_dev and one run of run_ai_diagnostic.
        demo = session()
        sign_in(demo, "admin", "1234")
        expect(demo.get_by_role("heading", name="Prezentare generală")).to_be_visible()
        expect(demo.get_by_text("Consum AI")).to_have_count(0)
        demo.screenshot(path=SHOTS / "tenant-no-ai-usage.png", full_page=True)

        staff.get_by_role("link", name="Utilizare AI").click()
        expect(staff.get_by_role("cell", name="Firmă Demo SRL (fictivă)").first).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-ai-usage.png", full_page=True)
        staff.get_by_role("link", name="Costuri AI").click()
        expect(staff.get_by_text("fake:fake-small").first).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-ai-costs.png", full_page=True)

        staff.get_by_role("link", name="Surse legislative").click()
        expect(staff.get_by_role("heading", name="Portal Legislativ")).to_be_visible()
        expect(staff.get_by_text("Sursele pornesc dezactivate")).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-legal-sources.png", full_page=True)
        staff.get_by_role("link", name="Actualizări legislative").click()
        expect(staff.get_by_role("heading", name="Actualizări legislative")).to_be_visible()
        staff.screenshot(path=SHOTS / "platform-legal-changes.png", full_page=True)

        browser.close()

    if errors:
        print("JavaScript errors:", errors)
        return 1
    print("OK: full browser flow passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
