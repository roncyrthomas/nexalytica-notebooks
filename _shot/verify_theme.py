"""End-to-end: in the REAL shell, type into a cell, change theme via the dropdown,
confirm the cell content survives and the theme actually changed."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1320, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)

    pg.click("#new-btn")
    pg.wait_for_selector("iframe.active", timeout=40000)
    fr = pg.frame_locator("iframe.active")
    fr.locator(".jp-CodeCell .cm-content").first.wait_for(timeout=60000)
    pg.wait_for_timeout(5000)

    fr.locator(".jp-CodeCell .cm-content").first.fill("KEEP_ME_42 = 1+1")
    pg.wait_for_timeout(500)
    before = pg.frame_locator("iframe.active").locator("body").get_attribute("data-jp-theme-name")

    # change theme via the actual sidebar dropdown
    pg.select_option("#theme", "violet-light")
    pg.wait_for_timeout(2500)

    after = pg.frame_locator("iframe.active").locator("body").get_attribute("data-jp-theme-name")
    content = fr.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("theme before:", before, "-> after:", after)
    print("content preserved:", "KEEP_ME_42" in content, "| text:", repr(content))
    pg.screenshot(path="verify-theme.png")
    b.close()
