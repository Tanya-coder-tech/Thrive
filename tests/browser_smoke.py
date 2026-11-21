"""Exercise the dinner and trip fund workflows in Chromium against an isolated demo database."""

from argparse import ArgumentParser
from io import BytesIO
import logging
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread

from playwright.sync_api import expect, sync_playwright
from PIL import Image, ImageDraw, ImageFont
from werkzeug.serving import make_server

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app import create_app
from receipt_extraction import start_worker


def check_site(base_url, screenshots):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, color_scheme="light")
        page.set_default_timeout(8000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url + "/workspace")
        expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
        expect(page.locator(".hero-balance strong")).to_have_text("₹577.50")
        expect(page.get_by_role("button", name="Open navigation")).to_be_hidden()
        dinner = page.locator(".data-table").get_by_role("link", name="The Campus Kitchen")
        expect(dinner).to_be_visible()
        if screenshots:
            page.screenshot(path=screenshots / "overview.png", full_page=True)

        theme = page.get_by_role("switch", name="Dark mode")
        document = page.locator("html")
        topbar = page.locator(".topbar")
        light_background = topbar.evaluate("element => getComputedStyle(element).backgroundColor")
        expect(theme).to_have_attribute("aria-checked", "false")
        expect(document).to_have_attribute("data-theme", "light")
        theme.click()
        expect(theme).to_have_attribute("aria-checked", "true")
        expect(document).to_have_attribute("data-theme", "dark")
        expect(topbar).not_to_have_css("background-color", light_background)
        page.reload()
        expect(theme).to_have_attribute("aria-checked", "true")
        expect(document).to_have_attribute("data-theme", "dark")
        if screenshots:
            page.screenshot(path=screenshots / "dark-overview.png", full_page=True)
        theme.press("Space")
        expect(theme).to_have_attribute("aria-checked", "false")
        expect(document).to_have_attribute("data-theme", "light")
        expect(topbar).to_have_css("background-color", light_background)

        dinner.click()
        expect(page.get_by_role("heading", name="Posted expense")).to_be_visible()
        expect(page.get_by_alt_text("Original receipt for campus-kitchen.png")).to_be_visible()
        posted = page.locator("section.card").filter(has=page.get_by_role("heading", name="Posted expense"))
        expect(posted.get_by_text("₹315.00", exact=True)).to_be_visible()

        page.get_by_role("button", name="Account menu").click()
        page.get_by_role("button", name="Simran", exact=True).click()
        page.get_by_role("link", name="Balances", exact=True).click()
        expect(page.get_by_role("heading", name="Balances", exact=True)).to_be_visible()
        page.get_by_role("button", name="Record", exact=True).click()
        expect(page.get_by_label("Amount (₹)")).to_have_value("262.50")
        page.get_by_role("dialog").get_by_role("button", name="Record payment").click()
        expect(page.get_by_text("Awaiting recipient")).to_be_visible()
        page.get_by_role("button", name="Account menu").click()
        page.get_by_role("button", name="Aman", exact=True).click()
        page.get_by_role("button", name="Confirm receipt").click()
        page.get_by_role("button", name="Confirm received").click()
        expect(page.get_by_text("Confirmed", exact=True)).to_be_visible()
        expect(page.locator(".balance-row").filter(has_text="Simran Kaur")).to_contain_text("₹0.00")

        page.get_by_role("link", name="Expenses", exact=True).click()
        page.get_by_role("link", name="The Campus Kitchen").click()
        page.get_by_role("button", name="Ask a question").click()
        page.get_by_label("Receipt item").select_option(label="Drinks")
        page.get_by_label("What should the group review?").fill("Karan did not share the drinks.")
        page.get_by_role("button", name="Submit question").click()
        expect(page.get_by_text("Karan did not share the drinks.")).to_be_visible()
        page.get_by_role("button", name="Propose correction").click()
        group = page.get_by_role("group", name="Participants for Drinks")
        group.get_by_role("checkbox", name="Karan").uncheck()
        expect(page.get_by_role("heading", name="Proposed shares")).to_be_visible()
        page.get_by_role("button", name="Approve correction").click()
        expect(page.get_by_text("Version 2 · Current · ₹840.00")).to_be_visible()

        page.get_by_role("link", name="Receipts", exact=True).click()
        page.get_by_role("button", name="Upload receipt").click()
        page.get_by_text("Demo receipt samples", exact=True).click()
        sample_link = page.get_by_role("link", name="Second photo of the same bill")
        photo = page.request.get(base_url + sample_link.get_attribute("href"))
        assert photo.ok
        page.locator('input[type="file"]').set_input_files(
            {"name": "second-photo.png", "mimeType": "image/png", "buffer": photo.body()})
        page.get_by_role("dialog").get_by_role("button", name="Upload receipt").click()
        expect(page.get_by_text("Scan ready", exact=True)).to_be_visible(timeout=8000)
        expect(page.get_by_label("Merchant", exact=True)).to_have_value("The Campus Kitchen")
        comparison = page.locator(".duplicate-review")
        expect(comparison.get_by_role("heading", name="Possible duplicate receipts")).to_be_visible()
        comparison.locator("summary").filter(has_text="campus-kitchen.png").click()
        expect(comparison.get_by_alt_text("This receipt, second-photo.png")).to_be_visible()
        expect(comparison.get_by_alt_text("Matching receipt, campus-kitchen.png")).to_be_visible()
        if screenshots:
            page.locator(".duplicate-review").screenshot(path=screenshots / "duplicate-receipt-review.png")
        expect(comparison.get_by_text("Matching receipt number", exact=True)).to_be_visible()
        comparison.get_by_role("button", name="Mark as duplicate").click()
        expect(comparison.get_by_text("Confirmed duplicate", exact=True)).to_be_visible()
        comparison.locator("summary").filter(has_text="campus-kitchen.png").click()
        page.get_by_role("group", name="Participants for Margherita pizza").get_by_role("checkbox", name="Aman").check()
        page.get_by_role("group", name="Participants for Margherita pizza").get_by_role("checkbox", name="Simran").check()
        page.get_by_role("group", name="Participants for Punjabi thali").get_by_role("checkbox", name="Karan").check()
        for name in ("Aman", "Simran", "Karan"):
            page.get_by_role("group", name="Participants for Drinks").get_by_role("checkbox", name=name).check()
        page.get_by_role("button", name="Remove adjustment 1").click()
        expect(page.get_by_text("₹40.00 unaccounted for", exact=False)).to_be_visible()
        page.get_by_role("button", name="Add adjustment").click()
        page.get_by_label("Amount (₹)", exact=True).fill("40")
        expect(page.get_by_text("Shares match the reviewed receipt total.")).to_be_visible()
        theme.click()
        expect(theme).to_have_attribute("aria-checked", "true")
        expect(page.get_by_label("Amount (₹)", exact=True)).to_have_value("40")
        if screenshots:
            page.screenshot(path=screenshots / "dark-receipt-review.png", full_page=True)
        theme.click()
        page.get_by_role("button", name="Save draft").click()
        expect(page.get_by_role("status").filter(has_text="Draft saved.")).to_be_visible()
        page.reload()
        expect(page.get_by_role("group", name="Participants for Drinks").get_by_role("checkbox", name="Karan")).to_be_checked()
        expect(page.get_by_label("Amount (₹)", exact=True)).to_have_value("40.00")
        if screenshots:
            page.screenshot(path=screenshots / "receipt-review.png", full_page=True)
        page.get_by_role("button", name="Post expense").click()
        expect(page.get_by_role("alert")).to_contain_text("This receipt was confirmed as a duplicate of a posted expense.")

        page.get_by_role("link", name="Expenses", exact=True).click()
        page.get_by_role("button", name="New expense").click()
        expect(page.get_by_role("heading", name="New expense", exact=True)).to_be_visible()
        page.get_by_label("Merchant", exact=True).fill("Workshop registration")
        page.get_by_label("Purchase date").fill("2026-11-20")
        page.get_by_label("Receipt total (₹)").fill("100")
        page.get_by_role("button", name="Add payer").click()
        first_payer = page.get_by_role("group", name="Payer contribution 1", exact=True)
        first_payer.get_by_label("Paid by").select_option(label="Aman Sharma")
        first_payer.get_by_label("Amount paid (₹)").fill("60")
        first_payer.get_by_label("Payment method").select_option("cash")
        second_payer = page.get_by_role("group", name="Payer contribution 2", exact=True)
        second_payer.get_by_label("Paid by").select_option(label="Simran Kaur")
        second_payer.get_by_label("Payment method").select_option("upi")
        second_payer.get_by_label("Amount paid (₹)").fill("30")
        expect(page.locator("#funding-summary")).to_contain_text("₹10.00 is still unfunded.")
        second_payer.get_by_label("Amount paid (₹)").fill("40")
        expect(page.locator("#funding-summary .amount")).to_have_text("₹100.00")
        expect(page.get_by_text("An extra paise goes to Aman.")).to_be_visible()
        page.get_by_role("button", name="Post expense").click()
        expect(page.get_by_role("heading", name="Posted expense")).to_be_visible()
        posted = page.locator("section.card").filter(has=page.get_by_role("heading", name="Posted expense"))
        expect(posted.get_by_text("₹33.34", exact=True)).to_be_visible()
        expect(posted.locator(".selection-summary").filter(has_text="Aman Sharma · Cash")).to_contain_text("₹60.00")
        expect(posted.locator(".selection-summary").filter(has_text="Simran Kaur · UPI")).to_contain_text("₹40.00")

        page.get_by_role("link", name="Receipts", exact=True).click()
        page.get_by_role("button", name="Upload receipt").click()
        pdf_buffer = BytesIO()
        image = Image.new("RGB", (500, 600), "#ffffff")
        ImageDraw.Draw(image).text((30, 30), "THRIVE PDF RECEIPT", fill="#151d32", font=ImageFont.load_default(size=35))
        second = Image.new("RGB", (500, 600), "#fff5e5")
        ImageDraw.Draw(second).text((30, 30), "RECEIPT PAGE TWO", fill="#151d32", font=ImageFont.load_default(size=35))
        image.save(pdf_buffer, format="PDF", save_all=True, append_images=[second])
        page.locator('input[type="file"]').set_input_files(
            {"name": "private.pdf", "mimeType": "application/pdf", "buffer": pdf_buffer.getvalue()})
        with page.expect_response(lambda response: response.url.endswith("/pdf-preview/1")) as preview:
            page.get_by_role("dialog").get_by_role("button", name="Upload receipt").click()
        assert preview.value.ok
        assert preview.value.headers["content-type"] == "image/png"
        expect(page.get_by_alt_text("Original PDF receipt, page 1")).to_have_js_property("complete", True)
        assert page.get_by_alt_text("Original PDF receipt, page 1").evaluate("image => image.naturalWidth") > 0
        expect(page.get_by_role("link", name="Open PDF")).to_be_visible()
        expect(page.get_by_role("button", name="Retry scan")).to_be_visible(timeout=8000)
        page.get_by_role("button", name="Next page").click()
        expect(page.get_by_text("Page 2 of 2")).to_be_visible()
        expect(page.get_by_alt_text("Original PDF receipt, page 2")).to_have_js_property("complete", True)
        assert page.get_by_alt_text("Original PDF receipt, page 2").evaluate("image => image.naturalWidth") > 0
        if screenshots:
            page.locator(".receipt-panel").screenshot(path=screenshots / "pdf-preview.png")

        mobile = browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, color_scheme="light")
        mobile.goto(base_url + "/workspace")
        expect(mobile.locator(".hero-balance strong")).to_be_visible()
        mobile_theme = mobile.get_by_role("switch", name="Dark mode")
        expect(mobile_theme).to_be_visible()
        mobile_theme.tap()
        expect(mobile.locator("html")).to_have_attribute("data-theme", "dark")
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile viewport scrolls sideways"
        assert mobile.locator(".expense-table").evaluate(
            "table => table.scrollWidth <= table.parentElement.clientWidth"), "Mobile expense status is clipped"
        mobile_theme.tap()
        expect(mobile.locator("html")).to_have_attribute("data-theme", "light")
        mobile.get_by_role("button", name="Open navigation").click()
        mobile.get_by_role("link", name="Members", exact=True).click()
        expect(mobile.get_by_role("heading", name="Members", exact=True)).to_be_visible()
        if screenshots:
            mobile.goto(base_url + "/workspace")
            expect(mobile.locator(".hero-balance strong")).to_be_visible()
            mobile.screenshot(path=screenshots / "mobile-overview.png", full_page=True)

        page.locator(".group-toggle").click()
        page.get_by_role("button", name="Jaipur Trip", exact=True).click()
        expect(page.get_by_role("heading", name="Jaipur Trip", exact=True)).to_be_visible()
        page.get_by_role("link", name="Expenses", exact=True).click()
        page.locator(".expense-table").get_by_role("link", name="The Campus Kitchen").click()
        posted = page.locator("section.card").filter(has=page.get_by_role("heading", name="Posted expense"))
        expect(posted.locator(".selection-summary").filter(has_text="Aman Sharma · Cash")).to_contain_text("₹500.00")
        expect(posted.locator(".selection-summary").filter(has_text="Simran Kaur · UPI")).to_contain_text("₹340.00")

        page.get_by_role("link", name="Trip fund", exact=True).click()
        expect(page.get_by_role("heading", name="Trip fund", exact=True)).to_be_visible()
        cash = page.locator(".fund-cash .amount")
        expect(cash).to_have_text("₹800.00")
        totals = page.locator(".fund-totals > div")
        expect(totals.filter(has_text="Advances collected").locator("dd")).to_have_text("₹4,000.00")
        expect(totals.filter(has_text="Paid from fund").locator("dd")).to_have_text("₹3,200.00")
        aman_fund = page.locator(".fund-table").get_by_role("row").filter(has_text="Aman Sharma")
        expect(aman_fund.get_by_text("₹1,062.50", exact=True)).to_be_visible()
        expect(aman_fund.get_by_text("₹800.00", exact=True)).to_be_visible()
        expect(aman_fund.get_by_text("Unused advance")).to_be_visible()
        if screenshots:
            page.screenshot(path=screenshots / "jaipur-trip-fund.png", full_page=True)

        mobile.get_by_role("button", name="Open navigation").click()
        mobile.locator(".group-toggle").click()
        mobile.get_by_role("button", name="Jaipur Trip", exact=True).click()
        expect(mobile.get_by_role("heading", name="Jaipur Trip", exact=True)).to_be_visible()
        mobile.get_by_role("button", name="Open navigation").click()
        mobile.get_by_role("link", name="Trip fund", exact=True).click()
        expect(mobile.locator(".fund-cash .amount")).to_have_text("₹800.00")
        assert mobile.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile fund overflows horizontally"

        page.get_by_role("button", name="Begin refunds", exact=True).click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_role("button", name="Begin refunds", exact=True).click()
        expect(page.get_by_text("Refunds in progress", exact=True)).to_be_visible()
        aman_fund.get_by_role("button", name="Record refund").click()
        expect(dialog.get_by_label("Amount (₹)")).to_have_value("200.00")
        dialog.get_by_role("button", name="Record refund", exact=True).click()
        expect(cash).to_have_text("₹600.00")
        expect(aman_fund.get_by_text("Settled", exact=True)).to_be_visible()
        expect(aman_fund.get_by_text("₹200.00", exact=True)).to_be_visible()
        expect(page.locator(".fund-history-row").filter(has_text="Refund to Aman Sharma")).to_contain_text("₹200.00")
        assert not errors, errors
        browser.close()


if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
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
            print("Chromium desktop and mobile workflow passed.")
        finally:
            stop.set()
            worker.join()
            server.shutdown()
            server.server_close()
            serving.join()
