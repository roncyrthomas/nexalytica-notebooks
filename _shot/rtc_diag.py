"""Diagnose RTC: is the collaboration WS attempted, and what URLs?"""
from playwright.sync_api import sync_playwright

WS = []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 860})
    a = ctx.new_page()
    a.on("websocket", lambda ws: WS.append(ws.url.split("/nb/")[-1]))
    a.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    a.fill("#email", "alice@example.com"); a.fill("#password", "secret123")
    a.click("button[type=submit]"); a.wait_for_timeout(1200)
    nb = a.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'D',theme:'Nexalytica Default Dark'})})).json())""")
    uuid = nb["id"]
    a.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=90000)
    a.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    a.wait_for_timeout(7000)

    print("WS urls seen:", WS)
    # server config: collaborative / ydoc enabled?
    cfg = a.evaluate("""() => {
        const el = document.getElementById('jupyter-config-data');
        const d = JSON.parse(el.textContent);
        return {collaborative: d.collaborative, disabledExtensions: d.disabledExtensions,
                fullStaticUrl: d.fullStaticUrl ? 'set' : 'none',
                exts: (d.federated_extensions||[]).map(e=>e.name)};
    }""")
    print("config:", cfg)
    print("UUID", uuid)
    b.close()
