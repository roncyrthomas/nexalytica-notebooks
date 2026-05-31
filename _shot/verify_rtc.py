"""Two tabs, same notebook: type in A -> must appear in B (live RTC sync)."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 860})
    a = ctx.new_page()
    a.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    a.fill("#email", "alice@example.com"); a.fill("#password", "secret123")
    a.click("button[type=submit]"); a.wait_for_timeout(1200)
    nb = a.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'RTC',theme:'Nexalytica Default Dark'})})).json())""")
    url = "http://127.0.0.1:8010" + nb["url"]

    # Tab A
    a.goto(url, wait_until="domcontentloaded", timeout=90000)
    a.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    a.wait_for_timeout(7000)

    # Tab B (same browser context -> same session cookie -> same notebook)
    bp = ctx.new_page()
    bp.goto(url, wait_until="domcontentloaded", timeout=90000)
    bp.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    bp.wait_for_timeout(7000)

    # Type a unique string in A
    a.locator(".jp-CodeCell .cm-content").first.click()
    a.locator(".jp-CodeCell .cm-content").first.fill("SYNC_TOKEN_2468")
    a.wait_for_timeout(4000)   # allow RTC propagation

    b_text = bp.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("Tab B sees A's edit:", "SYNC_TOKEN_2468" in b_text, "| B text:", repr(b_text))

    # And the reverse: type in B, see in A
    bp.locator(".jp-CodeCell .cm-content").first.click()
    bp.keyboard.press("End"); bp.keyboard.type(" + REVERSE_99")
    bp.wait_for_timeout(4000)
    a_text = a.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("Tab A sees B's edit:", "REVERSE_99" in a_text, "| A text:", repr(a_text))

    a.screenshot(path="rtc-a.png"); bp.screenshot(path="rtc-b.png")
    b.close()
