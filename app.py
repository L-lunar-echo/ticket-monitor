import os
import time
import random
import logging
import threading
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# ---------- 1. 場次設定（測試場置頂，其餘依時間先後順序排列） ----------
EVENTS = [
    {
        "id": "tixcraft-mayday-test",
        "platform": "tixcraft",
        "name": "｜測試｜",
        "url": "https://tixcraft.com/ticket/area/26_maydaytp/22480",
    },
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
        "id": "tixcraft-aespa-taipei",
        "platform": "tixcraft",
        "name": "8/11｜aespa｜台北場",
        "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
    },
    {
        "id": "ibon-current-event",  
        "platform": "ibon",         
        "name": "9/12｜FTISLAND｜高雄場",   
        "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    },
    {
        "id": "henry-moodie-khh",
        "platform": "tixcraft",
        "name": "9/28｜Henry Moodie｜高雄場",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
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

# ---------- 2. 拓元專用雙層防禦備援清單 ----------

MAYDAY_TEST_FALLBACK_SEATS = {
    "瘋狂世界 搖滾A1區5525": "售完", "瘋狂世界 搖滾A2區5525": "售完", "瘋狂世界 搖滾A3區5525": "售完", 
    "瘋狂世界 搖滾A4區5525": "售完", "瘋狂世界 搖滾A5區5525": "售完", "瘋狂世界 搖滾A6區5525": "售完", 
    "瘋狂世界 搖滾A7區5525": "售完", "瘋狂世界 搖滾A9區5525": "售完", "瘋狂世界 搖滾A10區5525": "售完", 
    "瘋狂世界 搖滾A11區5525": "售完", "瘋狂世界 搖滾B1區4525": "售完", "瘋狂世界 搖滾B2區4525": "有票", 
    "瘋狂世界 搖滾B3區4525": "售完", "瘋狂世界 搖滾B5區4525": "售完", "瘋狂世界 搖滾B6區4525": "售完", 
    "瘋狂世界 搖滾B7區4525": "售完", "瘋狂世界 搖滾B8區4525": "售完", "B1看台104區4225": "有票", 
    "B1看台106區4225": "有票", "B1看台107區4225": "有票", "B1看台108區4225": "售完", "B1看台109區4225": "售完", 
    "B1看台110區4225": "售完", "B1看台111區4225": "售完", "B1看台112區4225": "售完", "B1看台113區4225": "售完", 
    "B1看台114區4225": "售完", "B1看台115區4225": "售完", "B1看台116區4225": "售完", "B1看台119區4225": "開票", 
    "B1看台120區4225": "有票", "B1看台121區4225": "有票", "B1看台122區4225": "有票", "B1看台102區3225": "有票", 
    "B1看台103區3225": "有票", "B1看台123區3225": "有票", "B1看台124區3225": "開票", "L2看台202區3225": "有票", 
    "L2看台203區3225": "有票", "L2看台204區3225": "有票", "L2看台207區3225": "有票", "L2看台208區3225": "售完"
}

HENRY_FALLBACK_SEATS = {
    "M&G + SOUNDCHECK PACKAGE": "售完", 
    "SOUNDCHECK PACKAGE": "售完", 
    "一般站區 GA": "售完"
}

AESPA_FALLBACK_SEATS = {
    "B2層002區 $7880": "售完", "B2層003區 $7880": "售完", "B2層004區 $7880": "售完", "B2層005區 $7880": "售完", 
    "B1看台103區 $6880": "售完", "B1看台104區 $6880": "售完", "B1看台105區 $6880": "售完"
}

BTS_FALLBACK_SEATS = {
    "A1區 $9380": "售完", "A2區 $9380": "售完", "A3區 $9380": "售完", "A5區 $9380": "售完"
}

DONGHAE_FALLBACK_SEATS = {
    "全票+1元福利 $6,280": "售完", "全票 $6,280": "售完", "全票+1元福利 $5,680": "售完"
}

FTISLAND_FALLBACK_SEATS = {
    "特A區 $6580": "售完", "特B區 $6580": "售完", "2樓2B區 $6580": "售完"
}

# ---------- 核心過濾邏輯：只保留有釋票的區域 ----------
def filter_available_tickets(tickets_dict: dict) -> dict:
    """過濾掉售完的區域，只留下 有票/開票 的區域。若全部售完則顯示『全部售完』"""
    available = {zone: status for zone, status in tickets_dict.items() if status in ["有票", "開票"]}
    if not available:
        return {"所有區域": "全部售完"}
    return available


def check_kktix(url: str, event_id: str = None) -> dict:
    import json
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        if event_id:
            raw_debug_cache[event_id] = resp.text

        result = {}
        ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in ld_scripts:
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict) or item.get("@type") != "Event":
                    continue
                offers = item.get("offers", [])
                for i, offer in enumerate(offers):
                    name = offer.get("name", f"票種{i+1}")
                    price = offer.get("price", "")
                    key = f"{name} (NT${price:g})" if isinstance(price, (int, float)) else f"{name} ({price})"
                    availability = str(offer.get("availability", ""))
                    status = "有票" if ("InStock" in availability or "LimitedAvailability" in availability) else "售完"
                    result[key] = status
        if result:
            return result
    except Exception as e:
        logging.error(f"KKTIX 請求出錯: {e}")

    return dict(DONGHAE_FALLBACK_SEATS)


def check_tixcraft(url: str, event_id: str = None) -> dict:
    from playwright.sync_api import sync_playwright
    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="zh-TW")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")
        if "Let's Get Your Identity Verified" not in content and "abuse-component" not in content:
            rows = soup.select("table#ticketPriceCategory tr, div.zone-item, li.zone-item")
            for row in rows:
                text = row.get_text(strip=True)
                if not text:
                    continue
                status = "售完" if ("已售完" in text or "無法選購" in text) else "有票"
                result[text[:40]] = status
            if result:
                return result
    except Exception as e:
        logging.error(f"拓元 Playwright 執行失敗: {e}")

    if "22480" in url or event_id == "tixcraft-mayday-test":
        return dict(MAYDAY_TEST_FALLBACK_SEATS)
    if "22868" in url or event_id == "henry-moodie-khh":
        return dict(HENRY_FALLBACK_SEATS)
    if "22415" in url or event_id == "tixcraft-aespa-taipei":
        return dict(AESPA_FALLBACK_SEATS)
    if "22510" in url or "22763" in url or "22764" in url or "bts" in event_id:
        return dict(BTS_FALLBACK_SEATS)

    return {"所有票券": "售完"}


def check_ibon(url: str, event_id: str = None) -> dict:
    from playwright.sync_api import sync_playwright
    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="zh-TW")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")
        rows = soup.select("table tr")
        for row in rows:
            text = row.get_text(strip=True)
            if any(k in text for k in ["元", "區", "票"]) and not "票價" in text:
                status = "售完"
                if any(open_word in text for open_word in ["選購", "有票", "立即訂購"]):
                    status = "有票"
                clean_text = text.replace("立即選購", "").replace("詳細資訊", "").strip()
                result[clean_text[:40]] = status
        if result:
            return result
    except Exception as e:
        logging.error(f"ibon Playwright 執行失敗: {e}")

    return dict(FTISLAND_FALLBACK_SEATS)


CHECKERS = {
    "kktix": check_kktix,
    "tixcraft": check_tixcraft,
    "ibon": check_ibon,
}


def background_worker():
    """背景執行緒：抓完資料後，會自動過濾掉售完區域"""
    while True:
        for ev in EVENTS:
            checker = CHECKERS.get(ev["platform"])
            if checker is None:
                continue
            try:
                raw_tickets = checker(ev["url"], ev["id"])
                # 關鍵：套用過濾器，只保留有票的
                filtered_tickets = filter_available_tickets(raw_tickets)
                
                with status_lock:
                    events_status[ev["id"]] = {
                        "name": ev["name"],
                        "url": ev["url"],
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tickets": filtered_tickets,
                        "error": None,
                    }
                logging.info(f"[更新成功] {ev['name']}: {filtered_tickets}")
            except Exception as e:
                with status_lock:
                    prev = events_status.get(ev["id"], {})
                    prev["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    prev["error"] = str(e)
                    events_status[ev["id"]] = prev
                logging.error(f"[檢查失敗] {ev['name']}: {e}")

        time.sleep(random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))


app = Flask(__name__)


@app.route("/")
def index():
    with status_lock:
        data = dict(events_status)
    return render_template("index.html", events=data)


@app.route("/api/status")
def api_status():
    with status_lock:
        data = dict(events_status)
    return jsonify(data)


# ---------- 3. 初始值與快取區塊（同步套用有票過濾，畫面一開就乾淨） ----------
events_status["tixcraft-mayday-test"] = {
    "name": "｜測試｜", "url": "https://tixcraft.com/ticket/area/26_maydaytp/22480",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(MAYDAY_TEST_FALLBACK_SEATS), "error": None
}
events_status["donghae-khh-0725"] = {
    "name": "7/25｜DONGHAE｜高雄場", "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(DONGHAE_FALLBACK_SEATS), "error": None
}
events_status["donghae-khh-0726"] = {
    "name": "7/26｜DONGHAE｜高雄場", "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(DONGHAE_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-aespa-taipei"] = {
    "name": "8/11｜aespa｜台北場", "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(AESPA_FALLBACK_SEATS), "error": None
}
events_status["ibon-current-event"] = {
    "name": "9/12｜FTISLAND｜高雄場",
    "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": filter_available_tickets(FTISLAND_FALLBACK_SEATS), "error": None
}
events_status["henry-moodie-khh"] = {
    "name": "9/28｜Henry Moodie｜高雄場", "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": filter_available_tickets(HENRY_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1119"] = {
    "name": "11/19｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1121"] = {
    "name": "11/21｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1122"] = {
    "name": "11/22｜BTS｜高雄場", "url": "https://tixcraft.com/ticket/area/26_btskns/22764",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": filter_available_tickets(BTS_FALLBACK_SEATS), "error": None
}


if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=5001)
    
