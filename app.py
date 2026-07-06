import os
import time
import random
import logging
import threading
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify
from playwright.sync_api import sync_playwright

# ---------- 1. 場次設定 ----------
EVENTS = [
    {"id": "donghae-khh-0725", "platform": "kktix", "name": "7/25｜DONGHAE｜高雄場", "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04"},
    {"id": "donghae-khh-0726", "platform": "kktix", "name": "7/26｜DONGHAE｜高雄場", "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be"},
    {"id": "henry-moodie-khh", "platform": "tixcraft", "name": "9/28｜Henry Moodie｜高雄場", "url": "https://tixcraft.com/ticket/area/26_henry/22868"},
    {"id": "ibon-current-event", "platform": "ibon", "name": "9/12｜FTISLAND｜高雄場", "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31"},
    {"id": "tixcraft-aespa-taipei", "platform": "tixcraft", "name": "8/11｜aespa｜台北場", "url": "https://tixcraft.com/ticket/area/26_aespa/22415"},
    {"id": "tixcraft-bts-1119", "platform": "tixcraft", "name": "11/19｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22510"},
    {"id": "tixcraft-bts-1121", "platform": "tixcraft", "name": "11/21｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22763"},
    {"id": "tixcraft-bts-1122", "platform": "tixcraft", "name": "11/22｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22764"},
]

CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX = 120, 180
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
events_status = {}
status_lock = threading.Lock()
raw_debug_cache = {}

# ---------- 2. 通用解析核心 ----------
def extract_seats(content):
    soup = BeautifulSoup(content, "html.parser")
    result = {}
    # 搜尋所有潛在的座位容器
    for element in soup.find_all(['tr', 'li', 'div']):
        text = element.get_text(" ", strip=True)
        if ("元" in text or "區" in text) and 3 < len(text) < 50:
            status = "售完" if any(s in text for s in ["售完", "無法選購", "Sold Out"]) else "有票"
            result[text[:30]] = status
    return result

def run_browser_crawler(url, event_id):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url, timeout=45000, wait_until="networkidle")
        page.wait_for_timeout(3000)
        content = page.content()
        browser.close()
        raw_debug_cache[event_id] = content
        return extract_seats(content)

# ---------- 3. 執行緒與路由 ----------
def background_worker():
    while True:
        for ev in EVENTS:
            try:
                tickets = run_browser_crawler(ev["url"], ev["id"])
                with status_lock:
                    events_status[ev["id"]] = {"name": ev["name"], "tickets": tickets, "updated_at": datetime.now().strftime("%H:%M:%S")}
                logging.info(f"[更新成功] {ev['name']}")
            except Exception as e:
                logging.error(f"[錯誤] {ev['name']}: {e}")
        time.sleep(random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

app = Flask(__name__)

@app.route("/")
def index():
    with status_lock: return render_template("index.html", events=events_status)

@app.route("/debug/<event_id>")
def debug(event_id):
    return f"<pre>{raw_debug_cache.get(event_id, '無資料')}</pre>"

if __name__ == "__main__":
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        threading.Thread(target=background_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5001)
    
