"""Diagnose the kernel WS in a real browser: capture ws lifecycle + frames."""
from playwright.sync_api import sync_playwright

EV = []
def hook_ws(ws):
    tag = "channels" if "channels" in ws.url else "other"
    EV.append(f"WS OPEN {tag}")
    ws.on("close", lambda *a: EV.append(f"WS CLOSE {tag}"))
    ws.on("socketerror", lambda e: EV.append(f"WS ERROR {tag}: {e}"))
    if tag == "channels":
        ws.on("framesent", lambda pl: EV.append("  -> sent " + str(pl)[:50]))
        ws.on("framereceived", lambda pl: EV.append("  <- recv " + str(pl)[:50]))

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.on("websocket", hook_ws)
    pg.on("console", lambda m: EV.append("CONSOLE " + m.type + ": " + m.text[:90]) if m.type in ("error", "warning") else None)

    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1500)
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'Diag',theme:'Nexalytica Default Dark'})})).json())""")
    uuid = nb["id"]; print("UUID", uuid)
    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector(".jp-CodeCell", timeout=45000)
    pg.wait_for_timeout(4000)
    pg.locator(".jp-CodeCell .cm-content").first.click(force=True)
    pg.keyboard.type("6*7"); pg.keyboard.press("Control+Enter")
    pg.wait_for_timeout(8000)
    prompt = pg.locator(".jp-InputArea-prompt").first.inner_text()
    has_out = pg.locator(".jp-OutputArea-output").count()
    print("INPUT PROMPT:", repr(prompt), "| output nodes:", has_out)
    pg.screenshot(path="diag.png")
    print("UUID_FOR_LOG", uuid)
    for e in EV: print(e)
    b.close()
