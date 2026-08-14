import time
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

BASE = "http://161.104.107.172:8091/"
PAGES = ["overview","alerts","events","decisions","systems","users","routing","incidents"]
o = Options()
o.add_argument("--headless")
o.binary_location = "/snap/firefox/current/usr/lib/firefox/firefox"
d = webdriver.Firefox(service=Service("/snap/bin/firefox.geckodriver"), options=o)
d.set_window_size(1500, 1050)
try:
    for p in PAGES:
        d.get(BASE + "#" + p)
        time.sleep(4)
        d.save_screenshot(f"/home/aleks/.cache/ff-{p}.png")
        print(p, "ok", flush=True)
finally:
    d.quit()
