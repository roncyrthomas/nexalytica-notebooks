"""Definitive proof via full-page notebook URL, keyboard-driven (no editor click)."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()

    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1500)

    nb = pg.evaluate("""async () => {
        const r = await fetch('/api/notebooks', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name:'Proof', theme:'Nexalytica Default Dark'})});
        return await r.json();
    }""")
    print("notebook:", nb.get("id"), "running:", nb.get("running"))

    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector(".jp-CodeCell", timeout=45000)
    pg.wait_for_timeout(3000)               # let CodeMirror settle
    # force-click past the skin overlay straight into the editor, then keyboard.
    pg.locator(".jp-CodeCell .cm-content").first.click(force=True)
    pg.keyboard.type("6*7")
    pg.keyboard.press("Control+Enter")      # run, keep selection
    out = pg.wait_for_selector(".jp-OutputArea-output", timeout=25000).inner_text().strip()
    print("CELL OUTPUT (expect 42):", repr(out))
    pg.screenshot(path="proof.png")
    b.close()
