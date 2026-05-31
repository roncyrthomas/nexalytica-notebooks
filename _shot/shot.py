"""Headless screenshot of a notebook URL, for visual QA of the skin.

Usage: python shot.py <url> <out.png> [width] [height]
"""
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
out = sys.argv[2]
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
h = int(sys.argv[4]) if len(sys.argv) > 4 else 900

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
    page.goto(url, wait_until="networkidle", timeout=60000)
    # let the notebook frontend mount, apply the theme, and render cells
    page.wait_for_timeout(5000)
    page.screenshot(path=out, full_page=False)
    browser.close()
print("saved", out)
