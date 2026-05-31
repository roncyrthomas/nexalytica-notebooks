"""Validate LIVE theme swap via DOM (no reload): marker must survive, look must change."""
from playwright.sync_api import sync_playwright

SWAP = """(id) => {
  const f = document.querySelector('iframe.active') || document.querySelector('iframe');
  const doc = f.contentDocument;
  const base = id.endsWith('-dark') ? 'theme-dark-extension' : 'theme-light-extension';
  const links = [...doc.querySelectorAll('link[rel=stylesheet]')];
  // base light/dark link
  const baseLink = links.find(l => /theme-(dark|light)-extension/.test(l.href));
  if (baseLink) baseLink.href = baseLink.href.replace(/theme-(dark|light)-extension/, base);
  // nexalytica palette link
  const palLink = links.find(l => /nexalytica-themes\\/nex-/.test(l.href));
  if (palLink) palLink.href = palLink.href.replace(/nex-[a-z-]+\\.css/, 'nex-' + id + '.css');
  doc.body.setAttribute('data-jp-theme-name', 'Nexalytica ' + id.split('-').map(s=>s[0].toUpperCase()+s.slice(1)).join(' '));
  doc.body.setAttribute('data-jp-theme-light', id.endsWith('-dark') ? 'false' : 'true');
  return {base, name: doc.body.getAttribute('data-jp-theme-name')};
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto("http://127.0.0.1:8010/login", wait_until="networkidle", timeout=60000)
    pg.fill("#email", "alice@example.com"); pg.fill("#password", "secret123")
    pg.click("button[type=submit]"); pg.wait_for_timeout(1200)
    nb = pg.evaluate("""async () => (await (await fetch('/api/notebooks',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({name:'P3',theme:'Nexalytica Default Dark'})})).json())""")
    # use the real shell (index.html) so an iframe exists
    pg.goto("http://127.0.0.1:8010/n/" + nb["id"], wait_until="domcontentloaded", timeout=90000)
    pg.wait_for_selector("iframe", timeout=30000)
    fr = pg.frame_locator("iframe").first
    fr.locator(".jp-CodeCell .cm-content").first.wait_for(timeout=60000)
    pg.wait_for_timeout=getattr(pg,'wait_for_timeout'); pg.wait_for_timeout(5000)
    fr.locator(".jp-CodeCell .cm-content").first.fill("MARKER_98765")
    pg.wait_for_timeout(400)

    r1 = pg.evaluate(SWAP, "sky-dark"); pg.wait_for_timeout(2000)
    m1 = fr.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("swap->sky-dark:", r1, "| marker:", "MARKER_98765" in m1)
    pg.screenshot(path="theme-sky.png")

    r2 = pg.evaluate(SWAP, "default-light"); pg.wait_for_timeout(2000)
    m2 = fr.locator(".jp-CodeCell .cm-content").first.inner_text()
    print("swap->default-light:", r2, "| marker:", "MARKER_98765" in m2)
    pg.screenshot(path="theme-light.png")
    b.close()
