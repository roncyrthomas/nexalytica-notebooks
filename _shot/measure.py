"""Measure where new-notebook boot time goes: claim vs asset-proxy vs kernel."""
import time
from playwright.sync_api import sync_playwright

resp = []   # (url_tail, duration_ms, size)

def on_response(r):
    if "/nb/" in r.url:
        try:
            t = r.request.timing
            dur = t["responseEnd"] - t["requestStart"]
        except Exception:
            dur = -1
        try:
            size = len(r.body())
        except Exception:
            size = 0
        resp.append((r.url.split("/nb/")[-1][:48], dur, size))

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)

    t0 = time.time()
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'Measure',theme:'Nexalytica Default Dark'})})).json())""")
    t_claim = time.time() - t0
    print(f"CLAIM (POST /api/notebooks): {t_claim:.2f}s  running={nb['running']}")

    pg.on("response", on_response)
    t0 = time.time()
    pg.goto("http://127.0.0.1:8010" + nb["url"], wait_until="domcontentloaded", timeout=90000)
    t_dom = time.time() - t0
    pg.wait_for_selector(".jp-Notebook .jp-CodeCell", timeout=90000)
    t_cell = time.time() - t0
    print(f"DOMContentLoaded: {t_dom:.2f}s   first code cell visible: {t_cell:.2f}s")

    pg.wait_for_timeout(1500)   # let the boot's asset requests settle
    durs = [d for _, d, _ in resp if d >= 0]
    total = sum(durs)
    print(f"\n/nb/ requests: {len(resp)}  | sum proxy time: {total/1000:.2f}s  "
          f"| total bytes: {sum(s for _,_,s in resp)/1e6:.1f} MB")
    print("slowest 8 proxied assets (ms):")
    for u, d, s in sorted(resp, key=lambda x: -x[1])[:8]:
        print(f"  {d:7.0f} ms  {s/1000:6.0f} KB  {u}")
    # connection reuse check: how many distinct slow (>200ms) small assets?
    slow_small = [1 for _, d, s in resp if d > 200 and s < 50000]
    print(f"slow(>200ms) small(<50KB) assets: {sum(slow_small)} "
          f"(high count => per-request connection overhead in the proxy)")
    b.close()
