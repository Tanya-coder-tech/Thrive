"""Verify the new notifications dropdown, group switcher, settings page, and AI-900 guide."""

import sys
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server
from threading import Thread, Event
from tempfile import TemporaryDirectory

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app import create_app
from receipt_extraction import start_worker

def main():
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "test.db"
        app = create_app({"DATABASE": str(db_path), "DEMO": True})
        stop = Event()
        worker = start_worker(app, stop)
        server = make_server("127.0.0.1", 0, app, threaded=True)
        ready = Event()

        def run_server():
            ready.set()
            server.serve_forever()

        thread = Thread(target=run_server, daemon=True)
        thread.start()
        ready.wait()
        base_url = f"http://127.0.0.1:{server.server_port}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.goto(f"{base_url}/static/jaipur/index.html")

                # 1. Test Group Switcher
                group_toggle = page.locator("#group-toggle")
                expect(group_toggle).to_be_visible()
                expect(page.locator("#active-group-label")).to_contain_text("Jaipur Industrial Visit")
                
                # Click to open dropdown
                group_toggle.click()
                group_dropdown = page.locator("#group-dropdown")
                expect(group_dropdown).to_be_visible()
                expect(group_dropdown.locator(".group-item")).to_have_count(3)
                
                # Switch to another group (e.g. Jaipur Trip)
                trip_btn = group_dropdown.locator(".group-item", has_text="Jaipur Trip")
                trip_btn.click()
                expect(group_dropdown).to_be_hidden()
                expect(page.locator("#active-group-label")).to_contain_text("Jaipur Trip")

                # Switch back to Jaipur Industrial Visit
                group_toggle.click()
                jaipur_btn = page.locator("#group-dropdown .group-item", has_text="Jaipur Industrial Visit")
                jaipur_btn.click()
                expect(page.locator("#active-group-label")).to_contain_text("Jaipur Industrial Visit")

                # 2. Test Notifications Dropdown
                notice_btn = page.locator(".notice-button")
                expect(notice_btn).to_be_visible()
                notif_dropdown = page.locator("#notifications-dropdown")
                expect(notif_dropdown).to_be_hidden()

                # Open notifications dropdown
                notice_btn.click()
                expect(notif_dropdown).to_be_visible()
                expect(notif_dropdown.locator(".notif-badge")).to_contain_text("1 pending")
                expect(notif_dropdown.locator(".notif-item")).to_have_count(3)
                
                # Tool dialog should NOT be open
                tool_dialog = page.locator("#dashboard-tool")
                expect(tool_dialog).to_be_hidden()

                # Click outside to close notifications dropdown
                page.locator("h1#group-title").click()
                expect(notif_dropdown).to_be_hidden()

                # 3. Test Settings Page
                settings_nav = page.locator('[data-nav="settings"]')
                expect(settings_nav).to_be_visible()
                settings_nav.click()

                view_settings = page.locator("#view-settings")
                expect(view_settings).to_be_visible()
                expect(page.locator("#view-overview")).to_be_hidden()
                expect(settings_nav).to_have_attribute("aria-current", "page")
                expect(page.locator("#crumb-view-title")).to_contain_text("Settings")

                # Verify Settings fields
                name_input = page.locator("#settings-group-name")
                expect(name_input).to_have_value("Jaipur Industrial Visit")
                expect(page.locator("#settings-members-body tr")).to_have_count(3)

                # Return to overview via Back button
                page.locator('#view-settings [data-action="back-to-overview"]').click()
                expect(page.locator("#view-overview")).to_be_visible()
                expect(view_settings).to_be_hidden()
                expect(page.locator('[data-nav="overview"]')).to_have_attribute("aria-current", "page")

                # 4. Test AI-900 & Guide Page
                ai_nav = page.locator('[data-nav="ai-guide"]')
                expect(ai_nav).to_be_visible()
                ai_nav.click()

                view_ai = page.locator("#view-ai-guide")
                expect(view_ai).to_be_visible()
                expect(page.locator("#view-overview")).to_be_hidden()
                expect(ai_nav).to_have_attribute("aria-current", "page")
                expect(page.locator("#crumb-view-title")).to_contain_text("AI-900 & Architecture")

                # Check pipeline steps
                expect(page.locator(".pipeline-step")).to_have_count(6)

                # Check case study table
                expect(page.locator(".case-table")).to_be_visible()
                expect(page.locator(".case-table")).to_contain_text("Margherita pizza")
                expect(page.locator(".case-table")).to_contain_text("₹262.50")
                expect(page.locator(".case-table")).to_contain_text("₹315.00")

                # Check interactive split sandbox
                calc_total = page.locator("#calc-total-display")
                expect(calc_total).to_contain_text("₹840.00")
                expect(page.locator("#calc-aman-display")).to_contain_text("₹262.50")
                expect(page.locator("#calc-karan-display")).to_contain_text("₹315.00")
                expect(page.locator("#calc-check-display")).to_contain_text("✓ Exact (0 diff)")

                # Test modifying tax in the interactive calculator
                tax_input = page.locator("#calc-tax")
                tax_input.fill("80")
                expect(calc_total).to_contain_text("₹880.00")
                expect(page.locator("#calc-check-display")).to_contain_text("✓ Exact (0 diff)")

                # Check AI-900 domains
                expect(page.locator(".ai900-card")).to_have_count(4)
                expect(view_ai).to_contain_text("Describe Artificial Intelligence Workloads")
                expect(view_ai).to_contain_text("Fundamental Principles of ML on Azure")
                expect(view_ai).to_contain_text("Microsoft Responsible AI Standard")
                expect(view_ai).to_contain_text("Model Evaluation & Quality Benchmarking")

                # Return to overview via nav
                page.locator('[data-nav="overview"]').click()
                expect(page.locator("#view-overview")).to_be_visible()
                expect(view_ai).to_be_hidden()

                # 5. Verify that Settings and AI-900 are visible in Jaipur index
                for v in ["overview", "settings", "ai-guide"]:
                    page.locator(f'[data-nav="{v}"]').click()
                    target_view = page.locator(f"#view-{v}")
                    expect(target_view).to_be_visible()
                    expect(page.locator(f'[data-nav="{v}"]')).to_have_attribute("aria-current", "page")
                    expect(page.locator('[data-nav="settings"]')).to_be_visible()
                    expect(page.locator('[data-nav="ai-guide"]')).to_be_visible()

                # 6. Verify that on EVERY page in /workspace, Settings and AI-900 are in the sidebar
                page.goto(f"{base_url}/workspace?group=3")
                workspace_sections = ["overview", "expenses", "receipts", "balances", "fund", "members", "ai-guide", "settings", "activity"]
                for s in workspace_sections:
                    page.goto(f"{base_url}/workspace?group=3#{s}")
                    # Sidebar navigation links
                    nav = page.locator(".navigation")
                    expect(nav).to_be_visible()
                    expect(nav.locator('a[href="#settings"]')).to_be_visible()
                    expect(nav.locator('a[href="#ai-guide"]')).to_be_visible()

                browser.close()
                print("All new feature tests passed successfully!")
        finally:
            server.shutdown()
            stop.set()

if __name__ == "__main__":
    main()
