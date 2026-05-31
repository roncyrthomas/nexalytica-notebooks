"""Two notebook opens in the SAME browser (real usage) -> 2nd hits browser cache."""
import time
from playwright.sync_api import sync_playwright


def open_one(pg, label):
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'C',theme:'Nexalytica Default Dark'})})).json())""")
    t0 = time.time()
    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    print(f"{label}: first cell visible {time.time()-t0:.2f}s")


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)

    open_one(pg, "1st open (cold cache)")
    open_one(pg, "2nd open (warm browser cache)")
    open_one(pg, "3rd open (warm browser cache)")
    b.close()
