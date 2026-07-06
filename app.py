"""
演唱會釋票監控網站
==================
背景執行緒每隔一段時間檢查票況,結果存進記憶體(events_status),
所有訪客看到的都是同一份快取結果,不會讓每個訪客各自觸發一次爬蟲請求。
"""

import os
import time
import random
import logging
import threading
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# ---------- 1. 場次設定 ----------
EVENTS = [
    {
        "id": "donghae-khh-0725",
        "platform": "kktix",
        "name": "7/25｜DONGHAE｜高雄場",
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    },
    {
        "id": "donghae-khh-0726",
        "platform": "kktix",
        "name": "7/26｜DONGHAE｜高雄場",
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    },
    {
        "id": "henry-moodie-khh",
        "platform": "tixcraft",
        "name": "9/28｜Henry Moodie｜高雄場",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    },
    {
        "id": "ibon-current-event",  
        "platform": "ibon",        
        "name": "9/12｜FTISLAND｜高雄場",   
        "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    },
    {
        "id": "tixcraft-aespa-taipei",
        "platform": "tixcraft",
        "name": "8/11｜aespa｜台北場",
        "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
    },
    {
        "id": "tixcraft-bts-1119",
        "platform": "tixcraft",
        "name": "11/19｜BTS｜高雄場",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
    },
    {
        "id": "tixcraft-bts-1121",
        "platform": "tixcraft",
        "name": "11/21｜BTS｜高雄場",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
    },
    {
        "id": "tixcraft-bts-1122",
        "platform": "tixcraft",
        "name": "11/22｜BTS｜高雄場",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22764",
    },
    {
        "id": "test-mayday",
        "platform": "tixcraft",
        "name": "測試｜五月天｜場次",
        "url": "https://tixcraft.com/ticket/area/26_maydaytp/22480",
    },
]

# 間隔時間
CHECK_INTERVAL_MIN = 120
CHECK_INTERVAL_MAX = 180

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://ticket.ibon.com.tw/",
    "Connection": "keep-alive",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

events_status = {}
status_lock = threading.Lock()
raw_debug_cache = {}

# ---------- 2. 拓元專用防禦備援 (請保留您完整的防禦清單) ----------
BTS_FALLBACK_SEATS = {"A1區 (NT$9380)": "售完"} # 為了精簡程式碼，此處示意
AESPA_FALLBACK_SEATS = {"B2層002區7880": "售完"}

def check_kktix(url: str, event_id: str = None) -> dict:
    import json
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        result = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                candidates = data if isinstance(data, list) else [data]
                for item in candidates:
                    if isinstance(item, dict) and item.get("@type") == "Event":
                        for offer in item.get("offers", []):
                            name = offer.get("name", "票種")
                            result[name] = "有票" if "InStock" in str(offer.get("availability", "")) else "售完"
            except: continue
        return result if result else {"所有票券": "售完"}
    except: return {"所有票券": "售完"}

def check_tixcraft(url: str, event_id: str = None) -> dict:
    from playwright.sync_api import sync_playwright
    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=30000)
            page.wait_for_timeout(4000)
            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()
            for row in soup.select("table#ticketPriceCategory tr, div.zone-item"):
                text = row.get_text(strip=True)
                if text: result[text[:20]] = "售完" if "已售完" in text else "有票"
        return result if result else {"所有票券": "售完"}
    except: return {"所有票券": "售完"}

def check_ibon(url: str, event_id: str = None) -> dict:
    from playwright.sync_api import sync_playwright
    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=30000)
            page.wait_for_timeout(4000)
            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()
            for row in soup.select("table tr"):
                text = row.get_text(strip=True)
                if "區" in text: result[text[:25]] = "有票" if "選購" in text else "售完"
        return result if result else {"所有票券": "售完"}
    except: return {"所有票券": "售完"}

CHECKERS = {"kktix": check_kktix, "tixcraft": check_tixcraft, "ibon": check_ibon}

def background_worker():
    while True:
        for ev in EVENTS:
            checker = CHECKERS.get(ev["platform"])
            if checker:
                try:
                    tickets = checker(ev["url"], ev["id"])
                    with status_lock:
                        events_status[ev["id"]] = {"name": ev["name"], "tickets": tickets, "updated_at": datetime.now().strftime("%H:%M:%S")}
                    logging.info(f"[更新] {ev['name']}")
                except Exception as e: logging.error(f"[失敗] {ev['name']}: {e}")
        time.sleep(random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

app = Flask(__name__)

@app.route("/")
def index():
    with status_lock: return render_template("index.html", events=dict(events_status))

# 初始化狀態
for ev in EVENTS:
    events_status[ev["id"]] = {"name": ev["name"], "tickets": {"載入中...": "檢查中"}, "updated_at": "等待中"}

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
    
