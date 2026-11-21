"""Verify the live Jaipur dashboard and its saved workflows in Chromium."""

from argparse import ArgumentParser
import logging
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app import create_app
from receipt_extraction import start_worker


def dashboard(page, base_url):
    page.goto(base_url + "/")
    expect(page).to_have_url(re.compile(r"/static/jaipur/index\.html(?:\?.*)?$"))
    expect(page.get_by_role("heading", name="Jaipur Industrial Visit", exact=True)).to_be_visible()
    expect(page.locator(".expense-row[data-expense]").first).to_have_attribute("data-expense", re.compile(r"^\d+$"))


def expense_row(page, title):
    return page.locator(".expense-row").filter(has=page.get_by_role("heading", name=title, exact=True))


def read_group(page, base_url):
    groups = page.request.get(base_url + "/api/groups")
    assert groups.ok
    group_id = next(group["id"] for group in groups.json()["groups"] if group["name"] == "Jaipur Industrial Visit")
    response = page.request.get(f"{base_url}/api/groups/{group_id}")
    assert response.ok
    return response.json()


def check_filters_and_search(page):
    rows = page.locator(".expense-row")
    expect(rows).to_have_count(3)
    dinner = expense_row(page, "Group dinner")
    transport = expense_row(page, "Transport booking")
    refreshments = expense_row(page, "Refreshments")
    expect(dinner.locator("[data-select]")).to_have_attribute("aria-pressed", "true")
    expect(dinner).to_contain_text("₹840.00")
    transport.locator("[data-select]").press("Enter")
    expect(transport.locator("[data-select]")).to_have_attribute("aria-pressed", "true")
    expect(dinner.locator("[data-select]")).to_have_attribute("aria-pressed", "false")

    page.get_by_role("button", name="Needs review", exact=True).click()
    expect(dinner).to_be_visible()
    expect(transport).to_be_hidden()
    expect(refreshments).to_be_hidden()
    page.get_by_role("button", name="Posted", exact=True).click()
    expect(transport).to_be_visible()
    expect(refreshments).to_be_visible()
    expect(dinner).to_be_hidden()
    page.get_by_role("button", name="All expenses", exact=True).click()
    expect(dinner).to_be_visible()

    page.locator('[data-action="search"]').click()
    tool = page.locator("#dashboard-tool")
    tool.locator('input[type="search"]').fill("Refresh")
    tool.get_by_role("button", name=re.compile("Refreshments")).click()
    expect(tool).to_be_hidden()
    expect(refreshments.locator("[data-select]")).to_have_attribute("aria-pressed", "true")


def reconcile_dinner(page, base_url, screenshots):
    dinner = expense_row(page, "Group dinner")
    dinner.locator("[data-select]").click()
    dinner.get_by_role("button", name="Review receipt", exact=True).click()
    review = page.locator("#receipt-review")
    expect(review).to_be_visible()
    expect(review).to_contain_text(re.compile(r"₹40(?:\.00)?"))
    expect(review).to_contain_text("The Campus Kitchen")
    if screenshots:
        page.screenshot(path=screenshots / "jaipur-live-review.png", animations="disabled")
    review.locator('[data-action="edit-receipt"]').click()
    expect(page).to_have_url(re.compile(r"/workspace\?group=\d+#expense/\d+$"))
    expect(page.get_by_text("₹40.00 unaccounted for", exact=False)).to_be_visible()
    page.get_by_role("button", name="Add adjustment").click()
    page.get_by_label("Amount (₹)", exact=True).fill("40")
    expect(page.get_by_text("Shares match the reviewed receipt total.")).to_be_visible()
    page.get_by_role("button", name="Post expense", exact=True).click()
    posted = page.locator("section.card").filter(has=page.get_by_role("heading", name="Posted expense"))
    expect(posted).to_be_visible()
    expect(posted.get_by_text("₹262.50", exact=True)).to_have_count(2)
    expect(posted.get_by_text("₹315.00", exact=True)).to_be_visible()
    assert read_group(page, base_url)["ledger"]["total_paise"] == 449000

    dashboard(page, base_url)
    expect(expense_row(page, "Group dinner")).to_contain_text("Posted")
    expect(page.locator(".spending-total")).to_have_text("₹4,490.00")
    page.get_by_role("button", name="Needs review", exact=True).click()
    expect(page.locator("#feed-empty")).to_be_visible()
    page.get_by_role("button", name="All expenses", exact=True).click()


def check_add_expense(page, base_url):
    count_before = len(read_group(page, base_url)["expenses"])
    page.get_by_role("button", name="Add expense", exact=True).click()
    expect(page).to_have_url(re.compile(r"/workspace\?group=\d+#expense/\d+$"))
    expect(page.get_by_role("heading", name="New expense", exact=True)).to_be_visible()
    page.get_by_label("Merchant", exact=True).fill("Extension cords")
    page.get_by_label("Purchase date", exact=True).fill("2026-11-18")
    page.get_by_label("Receipt total (₹)", exact=True).fill("90")
    page.get_by_role("button", name="Save draft", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Draft saved.")).to_be_visible()
    dashboard(page, base_url)
    expect(expense_row(page, "Extension cords")).to_contain_text("₹90.00")
    group_after = read_group(page, base_url)
    assert len(group_after["expenses"]) == count_before + 1
    assert group_after["ledger"]["total_paise"] == 449000


def check_invitation(browser, page, base_url):
    page.locator('[data-action="add-member"]').click()
    tool = page.locator("#dashboard-tool")
    tool.locator('input[type="email"]').fill("tara@example.test")
    tool.get_by_role("button", name="Create invitation", exact=True).click()
    invite = tool.locator("a[href*='invite=']")
    expect(invite).to_be_visible()
    invitation_url = urljoin(base_url, invite.get_attribute("href"))
    guest = browser.new_page()
    try:
        guest.goto(invitation_url)
        guest.get_by_role("button", name="Create an account", exact=True).click()
        guest.get_by_label("Full name").fill("Tara Mehta")
        guest.get_by_label("Email", exact=True).fill("tara@example.test")
        guest.get_by_label("Password", exact=True).fill("demo-test-password")
        guest.get_by_role("button", name="Create account", exact=True).click()
        guest.get_by_role("button", name="Accept invitation", exact=True).click()
        expect(guest.get_by_text("You joined the group.")).to_be_visible()
        group = read_group(guest, base_url)
        assert any(member["name"] == "Tara Mehta" for member in group["members"])
    finally:
        guest.close()
    dashboard(page, base_url)
    expect(page.locator("#group-summary")).to_contain_text("4 members")


def check_upload(page, base_url):
    page.get_by_role("button", name="Upload receipt", exact=True).click()
    tool = page.locator("#dashboard-tool")
    sample = page.request.get(base_url + "/api/demo/receipt?sample=second-photo")
    assert sample.ok
    tool.locator('input[type="file"]').set_input_files(
        {"name": "jaipur-live-upload.png", "mimeType": "image/png", "buffer": sample.body()}
    )
    tool.get_by_role("button", name="Upload receipt", exact=True).click()
    expect(page).to_have_url(re.compile(r"/workspace\?group=\d+#expense/\d+$"))
    expect(page.get_by_text("Scan ready", exact=True)).to_be_visible(timeout=10000)
    expect(page.get_by_alt_text("Original receipt for jaipur-live-upload.png")).to_be_visible()
    group = read_group(page, base_url)
    expense_id = int(page.url.rsplit("/", 1)[-1])
    matching_upload = next(expense for expense in group["expenses"] if expense["id"] == expense_id)
    assert matching_upload["receipt_id"] and matching_upload["scan_status"] == "ready"


def check_sidebar(page, base_url):
    for destination, title in (("expenses", "Expenses"), ("receipts", "Receipts"), ("balances", "Balances"),
                               ("fund", "Trip fund"), ("members", "Members")):
        dashboard(page, base_url)
        page.locator(f'[data-nav="{destination}"]').click()
        expect(page).to_have_url(re.compile(rf"/workspace\?group=\d+#{destination}$"))
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()


def check_site(base_url, screenshots):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1271, "height": 827})
        page.set_default_timeout(8000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        dashboard(page, base_url)
        expect(page.locator("#group-summary")).to_contain_text("3 members")
        expect(page.locator(".spending-total")).to_have_text("₹3,650.00")
        if screenshots:
            page.screenshot(path=screenshots / "jaipur-live-desktop.png", animations="disabled")
        check_filters_and_search(page)
        reconcile_dinner(page, base_url, screenshots)
        check_add_expense(page, base_url)
        check_invitation(browser, page, base_url)
        check_upload(page, base_url)
        check_sidebar(page, base_url)
        assert not errors, errors
        browser.close()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    instance = PROJECT / "instance"
    instance.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=instance) as directory:
        app = create_app({"DEMO": True, "DATA_DIR": Path(directory), "AZURE_ENDPOINT": "", "AZURE_KEY": ""})
        server = make_server("127.0.0.1", 0, app, threaded=True)
        serving = Thread(target=server.serve_forever, daemon=True)
        serving.start()
        stop = Event()
        worker = start_worker(app, stop)
        try:
            check_site(f"http://127.0.0.1:{server.server_port}", args.screenshots)
            print("Live Jaipur dashboard, receipt correction, invitations, uploads, and sidebar navigation passed.")
        finally:
            stop.set()
            worker.join()
            server.shutdown()
            server.server_close()
            serving.join()


if __name__ == "__main__":
    main()
