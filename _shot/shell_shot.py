"""Screenshot the broker shell (waits extra for the embedded notebook)."""
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
out = sys.argv[2]
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
h = int(sys.argv[4]) if len(sys.argv) > 4 else 880

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
    pg.goto(url, wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(9000)  # let the iframe notebook fully render
    pg.screenshot(path=out, full_page=False)
    b.close()
print("saved", out)
