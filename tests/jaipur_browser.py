"""Verify the standalone Jaipur dashboard at the reference size and on mobile."""

from argparse import ArgumentParser
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


PROJECT = Path(__file__).resolve().parents[1]
DASHBOARD = PROJECT / "static" / "jaipur" / "index.html"
REFERENCE_VIEWPORT = {"width": 1271, "height": 827}
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def near(actual, expected, label, tolerance=6):
    assert abs(actual - expected) <= tolerance, (
        f"{label} was {actual:.1f}px, expected {expected}px ± {tolerance}px"
    )


def bounds(locator):
    expect(locator).to_be_visible()
    box = locator.bounding_box()
    assert box is not None, f"No visible box for {locator}"
    return box


def right(box):
    return box["x"] + box["width"]


def bottom(box):
    return box["y"] + box["height"]


def expense(page, name):
    return page.locator(f'[data-expense="{name}"]')


def expect_no_horizontal_scroll(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (
        "Dashboard overflows the viewport horizontally"
    )


def check_reference_geometry(page):
    shell = bounds(page.locator(".dashboard-shell"))
    sidebar = bounds(page.locator(".sidebar"))
    workspace = bounds(page.locator(".workspace-grid"))
    header = bounds(page.locator(".group-header"))
    feed = bounds(page.locator(".expense-feed"))
    review = bounds(page.locator(".review-card"))
    inbox = bounds(page.locator(".inbox-card"))
    spending = bounds(page.locator(".spending-card"))

    near(shell["x"], 31, "Shell left")
    near(shell["y"], 14, "Shell top")
    near(shell["width"], 1204, "Shell width")
    near(shell["height"], 788, "Shell height")
    near(sidebar["x"], shell["x"], "Sidebar left", 2)
    near(sidebar["height"], shell["height"], "Sidebar height", 2)
    near(sidebar["width"], 198, "Sidebar width", 3)
    near(workspace["x"], 249, "Workspace grid left")
    near(header["x"], feed["x"], "Heading and feed left alignment", 2)
    near(feed["x"], 249, "Expense feed left")
    near(feed["width"], 630, "Expense feed width")
    near(review["x"], 886, "Right column left")
    near(review["width"], 316, "Right column width")
    near(review["x"] - right(feed), 8, "Desktop column gap", 2)
    near(review["y"], header["y"], "Review card and heading area top alignment", 2)
    near(review["height"], 150, "Review card height")
    near(inbox["height"], 295, "Receipt inbox height")
    near(spending["height"], 170, "Group spending height")

    rows = page.locator(".expense-feed .expense-row")
    expect(rows).to_have_count(3)
    row_boxes = [bounds(rows.nth(index)) for index in range(3)]
    for index, (box, height) in enumerate(zip(row_boxes, (128, 220, 124)), start=1):
        near(box["height"], height, f"Expense row {index} height")
    near(row_boxes[0]["y"], 295, "First expense row top")
    near(inbox["y"], row_boxes[0]["y"], "Receipt inbox and first expense row top alignment", 2)
    near(bottom(row_boxes[-1]), bottom(spending), "Last expense row and group spending bottom alignment", 2)
    near(bottom(spending), 769, "Aligned column bottom")
    assert row_boxes[1]["height"] > max(row_boxes[0]["height"], row_boxes[2]["height"])
    assert bottom(shell) < REFERENCE_VIEWPORT["height"], "Shell should fit vertically at the reference size"
    expect_no_horizontal_scroll(page)


def check_expense_controls(page, screenshots):
    transport = expense(page, "transport")
    dinner = expense(page, "dinner")
    refreshments = expense(page, "refreshments")
    expect(transport).to_contain_text("Transport booking")
    expect(dinner).to_contain_text("Group dinner")
    expect(dinner).to_contain_text("₹840")
    expect(refreshments).to_contain_text("Refreshments")

    dinner_select = dinner.locator('[data-select="dinner"]')
    transport_select = transport.locator('[data-select="transport"]')
    expect(dinner_select).to_have_attribute("aria-pressed", "true")
    transport_select.press("Enter")
    expect(transport_select).to_have_attribute("aria-pressed", "true")
    expect(dinner_select).to_have_attribute("aria-pressed", "false")
    dinner_select.click()
    expect(dinner_select).to_have_attribute("aria-pressed", "true")

    review_filter = page.get_by_role("button", name="Needs review", exact=True)
    settled_filter = page.get_by_role("button", name="Settled", exact=True)
    all_filter = page.get_by_role("button", name="All expenses", exact=True)
    expect(all_filter).to_have_attribute("data-filter", "all")
    expect(all_filter).to_have_attribute("aria-pressed", "true")
    expect(review_filter).to_have_attribute("data-filter", "review")
    expect(settled_filter).to_have_attribute("data-filter", "settled")

    review_filter.click()
    expect(review_filter).to_have_attribute("aria-pressed", "true")
    expect(dinner).to_be_visible()
    expect(transport).to_be_hidden()
    expect(refreshments).to_be_hidden()
    settled_filter.click()
    expect(settled_filter).to_have_attribute("aria-pressed", "true")
    expect(dinner).to_be_hidden()
    expect(transport).to_be_visible()
    expect(refreshments).to_be_visible()
    all_filter.click()
    expect(all_filter).to_have_attribute("aria-pressed", "true")
    expect(dinner).to_be_visible()

    dinner_select.click()
    review_button = dinner.get_by_role("button", name="Review receipt", exact=True)
    review_button.click()
    review = page.locator("#receipt-review")
    expect(review).to_be_visible()
    expect(review).to_contain_text(re.compile("₹40"))
    if screenshots:
        page.screenshot(path=screenshots / "jaipur-receipt-review.png", animations="disabled")
    page.keyboard.press("Escape")
    expect(review).to_be_hidden()
    expect(review_button).to_be_focused()


def check_mobile(page, screenshots):
    expect(page.get_by_role("heading", name="Jaipur Industrial Visit")).to_be_visible()
    expect_no_horizontal_scroll(page)
    feed = bounds(page.locator(".expense-feed"))
    cards = [bounds(page.locator(selector)) for selector in (".review-card", ".inbox-card", ".spending-card")]
    for index, card in enumerate(cards, start=1):
        near(card["x"], feed["x"], f"Mobile card {index} left edge", 2)
        near(card["width"], feed["width"], f"Mobile card {index} width", 2)
    for previous, current in zip(cards, cards[1:]):
        assert current["y"] >= bottom(previous), "Mobile cards should be stacked in order"

    for name in ("transport", "dinner", "refreshments"):
        row = bounds(expense(page, name))
        assert row["x"] >= 0 and right(row) <= MOBILE_VIEWPORT["width"], f"{name} is clipped on mobile"
    if screenshots:
        page.screenshot(path=screenshots / "jaipur-mobile.png", full_page=True, animations="disabled")

    expense(page, "dinner").get_by_role("button", name="Review receipt", exact=True).tap()
    review = page.locator("#receipt-review")
    review_box = bounds(review)
    assert review_box["x"] >= 0 and right(review_box) <= MOBILE_VIEWPORT["width"]
    expect(review).to_contain_text(re.compile("₹40"))
    review.locator('[data-action="close-review"]').tap()
    expect(review).to_be_hidden()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path, help="Write desktop, mobile, and receipt review screenshots")
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)

    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        desktop = browser.new_page(viewport=REFERENCE_VIEWPORT, device_scale_factor=1)
        desktop.on("pageerror", lambda error: errors.append(str(error)))
        desktop.goto(DASHBOARD.as_uri())
        expect(desktop.get_by_role("heading", name="Jaipur Industrial Visit")).to_be_visible()
        desktop.evaluate("document.fonts.ready")
        if args.screenshots:
            desktop.screenshot(path=args.screenshots / "jaipur-desktop.png", animations="disabled")
        check_reference_geometry(desktop)
        check_expense_controls(desktop, args.screenshots)

        mobile = browser.new_page(viewport=MOBILE_VIEWPORT, is_mobile=True, has_touch=True)
        mobile.on("pageerror", lambda error: errors.append(str(error)))
        mobile.goto(DASHBOARD.as_uri())
        check_mobile(mobile, args.screenshots)
        assert not errors, errors
        browser.close()
    print("Jaipur reference geometry, mobile layout, and receipt interactions passed.")


if __name__ == "__main__":
    main()
