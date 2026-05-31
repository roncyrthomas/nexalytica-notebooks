"""Dump the live notebook DOM structure to get exact selectors."""
import sys, json
from playwright.sync_api import sync_playwright

url = sys.argv[1]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 950})
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(5000)
    data = pg.evaluate(
        """() => {
        const ids = ['top-panel','menu-panel','spacer-widget-top','main-panel','jp-top-bar','jp-MainLogo'];
        const regions = ids.map(id => ({id, present: !!document.getElementById(id),
            text: (document.getElementById(id)?.innerText||'').replace(/\\s+/g,' ').slice(0,70)}));
        const menubars = [...document.querySelectorAll('.lm-MenuBar')]
            .map(e => ({parentId: e.closest('[id]')?.id, text: e.innerText.replace(/\\s+/g,' ').slice(0,80)}));
        const toolbarItems = [...document.querySelectorAll('.jp-Toolbar-item')].map(e => ({
            name: e.getAttribute('data-jp-item-name'),
            cls: e.className.replace('jp-Toolbar-item','').trim(),
            label: (e.innerText||'').replace(/\\s+/g,' ').slice(0,24),
            title: e.querySelector('[title]')?.getAttribute('title') || ''
        }));
        const tableCls = [...new Set([...document.querySelectorAll('.jp-OutputArea table')].map(t=>t.className))];
        return {regions, menubars, toolbarItems, tableCls};
    }"""
    )
    print(json.dumps(data, indent=1))
    b.close()
