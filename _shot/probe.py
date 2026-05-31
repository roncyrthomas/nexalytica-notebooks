"""Probe: can we switch theme LIVE (no reload) and does it preserve cell edits?
Also: is jupyter-collaboration installed (for 2-tab live sync)?"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'Probe',theme:'Nexalytica Default Dark'})})).json())""")
    uuid = nb["id"]
    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    pg.wait_for_timeout(6000)

    # type a unique marker into the first cell
    pg.locator(".jp-CodeCell .cm-content").first.fill("MARKER_12345 = 99")
    pg.wait_for_timeout(500)

    # 1) is the app exposed globally?
    has_app = pg.evaluate("() => typeof window.jupyterapp !== 'undefined'")
    print("window.jupyterapp present:", has_app)

    # 2) list theme-related commands if app present
    cmds = pg.evaluate("""() => {
        try { return window.jupyterapp.commands.listCommands()
                .filter(c => c.toLowerCase().includes('theme')); }
        catch(e){ return 'ERR ' + e.message; }
    }""")
    print("theme commands:", cmds)

    # 3) try a LIVE theme switch via command, then check the marker survived
    res = pg.evaluate("""async () => {
        try {
            await window.jupyterapp.commands.execute('apputils:change-theme',
                { theme: 'Nexalytica Sky Dark' });
            return 'ok';
        } catch(e){ return 'ERR ' + e.message; }
    }""")
    pg.wait_for_timeout(2500)
    marker = pg.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("live change-theme:", res)
    print("marker after live switch:", repr(marker), "| preserved:", "MARKER_12345" in marker)
    pg.screenshot(path="probe.png")
    b.close()
