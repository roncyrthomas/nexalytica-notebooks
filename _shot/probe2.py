"""Find a live theme-switch + save hook inside the Notebook 7 page (same-origin)."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'P2',theme:'Nexalytica Default Dark'})})).json())""")
    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    pg.wait_for_timeout(6000)

    print("window keys (jupyter/lab/app):", pg.evaluate(
        "() => Object.keys(window).filter(k => /jupyter|lab|app|_JUP/i.test(k))"))
    print("body data-jp-theme-name:", pg.evaluate(
        "() => document.body.getAttribute('data-jp-theme-name')"))
    # theme stylesheet links currently in <head>?
    print("theme <link>s:", pg.evaluate(
        "() => [...document.querySelectorAll('link')].map(l=>l.href).filter(h=>/theme|nex-/i.test(h))"))
    # Does setting the body attribute alone change anything visible? (likely needs CSS loaded)
    # Probe the token/app via the labextension data
    print("jupyter-config-data app?:", pg.evaluate("""() => {
        const el = document.getElementById('jupyter-config-data');
        if(!el) return 'none';
        const d = JSON.parse(el.textContent);
        return {appName: d.appName, notebookPage: d.notebookPage, themesUrl: d.themesUrl};
    }"""))
    b.close()
