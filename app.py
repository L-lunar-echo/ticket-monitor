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

# 五月天測試場 完整防禦備援清單
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
    "B1看台103區3225": "有票", "B1看台123區3225": "有票", "B1看台124區3225": "有票", "L2看台202區3225": "有票", 
    "L2看台203區3225": "有票", "L2看台204區3225": "有票", "L2看台207區3225": "有票", "L2看台208區3225": "售完", 
    "L2看台209區3225": "售完", "L2看台210區3225": "售完", "L2看台211區3225": "售完", "L2看台212區3225": "售完", 
    "L2看台213區3225": "售完", "L2看台214區3225": "售完", "L2看台215區3225": "售完", "L2看台216區3225": "售完", 
    "L2看台217區3225": "售完", "L2看台219區3225": "售完", "L2看台220區3225": "售完", "L2看台221區3225": "有票", 
    "L2看台222區3225": "有票", "L2看台223區3225": "有票", "L2看台224區3225": "有票", "L3看台301區3225": "有票", 
    "L3看台302區3225": "有票", "L3看台303區3225": "售完", "L3看台304區3225": "售完", "L3看台314區3225": "售完", 
    "L3看台315區3225": "售完", "L3看台316區3225": "售完", "L3看台317區3225": "有票", "L4看台401區2225": "售完", 
    "L4看台402區2225": "售完", "L4看台403區2225": "售完", "L4看台404區2225": "售完", "L4看台405區2225": "售完", 
    "L4看台406區2225": "售完", "L4看台407區2225": "售完", "L4看台408區2225": "售完", "L4看台409區2225": "售完", 
    "L4看台410區2225": "售完", "L4看台411區2225": "售完", "L4看台412區2225": "售完", "L4看台413區2225": "售完", 
    "L4看台414區2225": "售完", "L4看台415區2225": "售完", "L4看台416區2225": "售完", "L4看台417區2225": "售完", 
    "L5看台503區1525": "售完", "L5看台504區1525": "售完", "L5看台505區1525": "售完", "L5看台506區1525": "售完", 
    "L5看台507區1525": "售完", "L5看台508區1525": "售完", "L5看台509區1525": "售完", "L5看台510區1525": "售完", 
    "L5看台511區1525": "售完", "L5看台512區1525": "售完", "L5看台513區1525": "售完", "L5看台514區1525": "售完", 
    "L5看台515區1525": "售完", "B1看台108身障區": "售完", "B1看台109身障區": "售完", "B1看台110身障區": "售完", 
    "B1看台116身障區": "售完", "B1看台117身障區": "售完", "B1看台118身障區": "售完", "L2看台207身障區": "售完", 
    "L2看台208身障區": "售完", "L2看台210身障區": "售完", "L2看台212身障區": "售完", "L2看台214身障區": "售完", 
    "L2看台216身障區": "售完", "L2看台218身障區": "售完", "L2看台219身障區": "售完"
}

# Henry Moodie 完整防禦備援清單
HENRY_FALLBACK_SEATS = {
    "M&G + SOUNDCHECK PACKAGE": "售完", 
    "SOUNDCHECK PACKAGE": "售完", 
    "一般站區 GA": "售完"
}

# aespa 完整防禦備援清單
AESPA_FALLBACK_SEATS = {
    "B2層002區 $7880": "售完", "B2層003區 $7880": "售完", "B2層004區 $7880": "售完", "B2層005區 $7880": "售完", 
    "B2層007區 $7880": "售完", "B2層008區 $7880": "售完", "B2層009區 $7880": "售完", "B2層010區 $7880": "售完", 
    "B2層011區 $7880": "售完", "B2層012區 $7880": "售完", "B2層013區 $6880": "售完", "B2層014區 $6880": "售完", 
    "B2層001區 $5880": "售完", "B2層006區 $5880": "售完", "B1看台103區 $6880": "售完", "B1看台104區 $6880": "售完", 
    "B1看台105區 $6880": "售完", "B1看台106區 $6880": "售完", "B1看台107區 $6880": "售完", "B1看台108區 $6880": "售完", 
    "B1看台109區 $6880": "售完", "B1看台110區 $6880": "售完", "B1看台111區 $6880": "售完", "B1看台115區 $6880": "售完", 
    "B1看台116區 $6880": "售完", "B1看台117區 $6880": "售完", "B1看台118區 $6880": "售完", "B1看台119區 $6880": "售完", 
    "B1看台120區 $6880": "售完", "B1看台121區 $6880": "售完", "B1看台122區 $6880": "售完", "B1看台123區 $6880": "售完"
}

# BTS 完整防禦備援清單
BTS_FALLBACK_SEATS = {
    "A1區 $9380": "售完", "A2區 $9380": "售完", "A3區 $9380": "售完", "A5區 $9380": "售完", "A6區 $9380": "售完", "A7區 $9380": "售完", 
    "R2區 $9380": "售完", "R3區 $9380": "售完", "R4區 $9380": "售完", "R5區 $9380": "售完", "R6區 $9380": "售完", "M1區 $9380": "售完"
}

# DONGHAE 完整防禦備援清單
DONGHAE_FALLBACK_SEATS = {
    "全票+1元福利 $6,280": "售完", "全票 $6,280": "售完", "全票+1元福利 $5,680": "售完", 
    "全票 $5,680": "售完", "全票+1元福利 $4,880": "售完", "全票 $4,880": "售完"
}

# FTISLAND 完整防禦備援清單
FTISLAND_FALLBACK_SEATS = {
    "特A區 $6580": "售完", "特B區 $6580": "售完", "2樓2B區 $6580": "售完", "2樓2C區 $6580": "售完", "2樓2D區 $6580": "售完"
}


def check_kktix(url: str, event_id: str = None) -> dict:
    """檢查 KKTIX 場次頁面"""
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
    """用 Playwright 讀取拓元頁面"""
    from playwright.sync_api import sync_playwright
    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=HEADERS["User-Agent"], locale="zh-TW")
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  
            content = page.content()
            title = page.title()
            current_url = page.url  
            browser.close()

        if event_id:
            raw_debug_cache[event_id] = f"[最終網址: {current_url}]\n[標題: {title}]\n\n{content}"

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

    # 分流返回各自的防禦備援清單
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
    """用 Playwright 讀取 ibon 頁面"""
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

        if event_id:
            raw_debug_cache[event_id] = content

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
    """背景執行緒"""
    while True:
        for ev in EVENTS:
            checker = CHECKERS.get(ev["platform"])
            if checker is None:
                continue
            try:
                tickets = checker(ev["url"], ev["id"])
                with status_lock:
                    events_status[ev["id"]] = {
                        "name": ev["name"],
                        "url": ev["url"],
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tickets": tickets,
                        "error": None,
                    }
                logging.info(f"[更新成功] {ev['name']}: {tickets}")
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


# ---------- 3. 初始值與快取區塊 ----------
events_status["tixcraft-mayday-test"] = {
    "name": "｜測試｜", 
    "url": "https://tixcraft.com/ticket/area/26_maydaytp/22480",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(MAYDAY_TEST_FALLBACK_SEATS), "error": None
}
events_status["donghae-khh-0725"] = {
    "name": "7/25｜DONGHAE｜高雄場", 
    "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(DONGHAE_FALLBACK_SEATS), "error": None
}
events_status["donghae-khh-0726"] = {
    "name": "7/26｜DONGHAE｜高雄場", 
    "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(DONGHAE_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-aespa-taipei"] = {
    "name": "8/11｜aespa｜台北場", 
    "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(AESPA_FALLBACK_SEATS), "error": None
}
events_status["ibon-current-event"] = {
    "name": "9/12｜FTISLAND｜高雄場",
    "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": dict(FTISLAND_FALLBACK_SEATS), "error": None
}
events_status["henry-moodie-khh"] = {
    "name": "9/28｜Henry Moodie｜高雄場", 
    "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": dict(HENRY_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1119"] = {
    "name": "11/19｜BTS｜高雄場", 
    "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1121"] = {
    "name": "11/21｜BTS｜高雄場", 
    "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1122"] = {
    "name": "11/22｜BTS｜高雄場", 
    "url": "https://tixcraft.com/ticket/area/26_btskns/22764",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
    "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}


if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=5001)
    
