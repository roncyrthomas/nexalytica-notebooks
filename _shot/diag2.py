"""Robust proof: fill the cell, run it, confirm execute_request + '42' output."""
from playwright.sync_api import sync_playwright

EXEC_SENT = []
def hook_ws(ws):
    if "channels" in ws.url:
        ws.on("framesent", lambda pl: EXEC_SENT.append(1)
              if isinstance(pl, str) and "execute_request" in pl else None)

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.on("websocket", hook_ws)

    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1500)
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'Run',theme:'Nexalytica Default Dark'})})).json())""")
    print("notebook:", nb["id"], "running:", nb["running"])

    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=45000)
    # wait for the kernel to settle (status no longer 'starting'/'connecting')
    pg.wait_for_timeout(9000)

    cell = pg.locator(".jp-CodeCell .cm-content").first
    cell.fill("6*7")                       # fill works on contenteditable CodeMirror
    pg.keyboard.press("Shift+Enter")
    try:
        out = pg.wait_for_selector(".jp-OutputArea-output", timeout=30000).inner_text().strip()
    except Exception as e:
        out = "NO OUTPUT: " + str(e)[:80]
    print("EXEC_REQUEST sent:", bool(EXEC_SENT))
    print("CELL OUTPUT (expect 42):", repr(out))
    pg.screenshot(path="diag2.png")
    b.close()
