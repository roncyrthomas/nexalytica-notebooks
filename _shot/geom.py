"""Dump geometry + computed bg of the layout containers to find wasted width
and the 'floating panel' background."""
import sys, json
from playwright.sync_api import sync_playwright

url = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(5000)
    data = pg.evaluate(
        """() => {
        const sels = ['body','#main-panel','.jp-NotebookPanel','.jp-WindowedPanel-outer',
            '.jp-WindowedPanel-viewport','.jp-Notebook','.jp-NotebookPanel-toolbar',
            '.jp-CodeCell','.jp-MarkdownCell'];
        return sels.map(s => {
            const e = document.querySelector(s);
            if (!e) return {s, missing: true};
            const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
            return {s, x: Math.round(r.x), w: Math.round(r.width),
                bg: cs.backgroundColor, mL: cs.marginLeft, mR: cs.marginRight,
                pL: cs.paddingLeft, pR: cs.paddingRight, pT: cs.paddingTop,
                br: cs.borderTopLeftRadius, shadow: cs.boxShadow.slice(0,24),
                border: cs.borderTopWidth + ' ' + cs.borderTopStyle};
        });
    }"""
    )
    print("viewport width = 1280")
    print(json.dumps(data, indent=1))
    b.close()
