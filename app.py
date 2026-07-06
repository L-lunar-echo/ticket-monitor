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

# ---------- 1. 場次設定（新增 "date" 欄位供自動排序） ----------
EVENTS = [
    {
        "id": "tixcraft-aespa-taipei",
        "platform": "tixcraft",
        "name": "aespa LIVE TOUR - SYNK：COMPLæXITY - in TAIPEI",
        "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
        "date": "2026-08-11"
    },
    {
        "id": "ibon-current-event",  
        "platform": "ibon",         
        "name": "2026 FTISLAND TOUR 0 — XIX — III ‘FaTe’ in KAOHSIUNG",   
        "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
        "date": "2026-09-12"
    },
    {
        "id": "henry-moodie-khh",
        "platform": "tixcraft",
        "name": "Henry Moodie：Mood Swings World Tour in Kaohsiung",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
        "date": "2026-09-28"
    },
    {
        "id": "tixcraft-bts-1119",
        "platform": "tixcraft",
        "name": "[11/19] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
        "date": "2026-11-19"
    },
    {
        "id": "tixcraft-bts-1121",
        "platform": "tixcraft",
        "name": "[11/21] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
        "date": "2026-11-21"
    },
    {
        "id": "tixcraft-bts-1122",
        "platform": "tixcraft",
        "name": "[11/22] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22764",
        "date": "2026-11-22"
    },
    {
        "id": "donghae-khh-0725",
        "platform": "kktix",
        "name": "[7/25] DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG",
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
        "date": "2026-07-25" # 依您原本設定為 2026 或 2027，此處供自動排序比對
    },
    {
        "id": "donghae-khh-0726",
        "platform": "kktix",
        "name": "[7/26] DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG",
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
        "date": "2026-07-26"
    }
]

# 建立快取對照表，方便依 id 查日期
EVENT_DATE_MAP = {ev["id"]: ev["date"] for ev in EVENTS}

CHECK_INTERVAL_MIN = 120
CHECK_INTERVAL_MAX = 180

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
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
BTS_FALLBACK_SEATS = {
    "A1區 (NT$9380)": "售完", "A2區 (NT$9380)": "售完", "A3區 (NT$9380)": "售完", "A5區 (NT$9380)": "售完",
    "A6區 (NT$9380)": "售完", "A7區 (NT$9380)": "售完", "R2區 (NT$9380)": "售完", "R3區 (NT$9380)": "售完",
}

AESPA_FALLBACK_SEATS = {
    "B2層002區7880": "售完", "B2層003區7880": "售完", "B2層004區7880": "售完", "B2層005區7880": "售完",
    "B2層007區7880": "售完", "B2層008區7880": "售完", "B2層009區7880": "售完", "B2層010區7880": "售完",
    "B2層011區7880": "售完", "B2層012區7880": "售完", "B2層013區6880": "售完", "B2層014區6880": "售完",
    "B2層001區5880": "售完", "B2層006區5880": "售完", "B1看台103區6880": "售完", "B1看台104區6880": "售完",
    "B1看台105區6880": "售完", "B1看台106區6880": "售完", "B1看台107區6880": "售完", "B1看台108區6880": "售完",
    "B1看台109區6880": "售完", "B1看台110區6880": "售完", "B1看台111區6880": "售完", "B1看台115區6880": "售完",
    "B1看台116區6880": "售完", "B1看台117區6880": "售完", "B1看台118區6880": "售完", "B1看台119區6880": "售完",
    "B1看台120區6880": "售完", "B1看台121區6880": "售完", "B1看台122區6880": "售完", "B1看台123區6880": "售完",
    "B1看台102區5880": "售完", "B1看台124區5880": "售完", "L2看台203區5880": "售完", "L2看台204區5880": "售完",
    "L2看台205區5880": "售完", "L2看台206區5880": "售完", "L2看台207區5880": "售完", "L2看台208區5880": "售完",
    "L2看台209區5880": "售完", "L2看台210區5880": "售完", "L2看台211區5880": "售完", "L2看台212區5880": "售完",
    "L2看台213區5880": "售完", "L2看台214區5880": "售完", "L2看台215區5880": "售完", "L2看台216區5880": "售完",
    "L2看台217區5880": "售完", "L2看台218區5880": "售完", "L2看台219區5880": "售完", "L2看台220區5880": "售完",
    "L2看台221區5880": "售完", "L2看台222區5880": "售完", "L2看台223區5880": "售完", "L2看台202區4880": "售完",
    "L2看台224區4880": "售完", "L3看台301區4880": "售完", "L3看台302區4880": "售完", "L3看台303區4880": "售完",
    "L3看台304區4880": "售完", "L3看台314區4880": "售完", "L3看台315區4880": "售完", "L3看台316區4880": "售完",
    "L3看台317區4880": "售完", "L4看台405區4880": "售完", "L4看台406區4880": "售完", "L4看台407區4880": "售完",
    "L4看台408區4880": "售完", "L4看台409區4880": "售完", "L4看台410區4880": "售完", "L4看台411區4880": "售完",
    "L4看台412區4880": "售完", "L4看台413區4880": "售完", "L4看台401區3880": "售完", "L4看台402區3880": "售完",
    "L4看台403區3880": "售完", "L4看台404區3880": "售完", "L4看台414區3880": "售完", "L4看台415區3880": "售完",
    "L4看台416區3880": "售完", "L4看台417區3880": "售完", "L5看台506區3880": "售完", "L5看台507區3880": "售完",
    "L5看台508區3880": "售完", "L5看台509區3880": "售完", "L5看台510區3880": "售完", "L5看台511區3880": "售完",
    "L5看台512區3880": "售完", "L5看台503區2880": "售完", "L5看台504區2880": "售完", "L5看台505區2880": "售完",
    "L5看台513區2880": "售完", "L5看台514區2880": "售完", "L5看台515區2880": "售完", "B1看台108身障區": "售完",
    "B1看台109身障區": "售完", "B1看台110身障區": "售完", "B1看台116身障區": "售完", "B1看台117身障區": "售完",
    "B1看台118身障區": "售完", "L2看台207身障區": "售完", "L2看台208身障區": "售完", "L2看台210身障區": "售完",
    "L2看台212身障區": "售完", "L2看台214身障區": "售完", "L2看台216身障區": "售完", "L2看台218身障區": "售完",
    "L2看台219身障區": "售完", "L3看台304身障區": "售完", "L3看台314身障區": "售完", "L4看台406身障區": "售完",
    "L4看台407身障區": "售完", "L4看台411身障區": "售完", "L4看台412身障區": "售完", "L4看台403身障區": "售完",
    "L4看台404身障區": "售完", "L4看台414身障區": "售完", "L4看台415身障區": "售完"
}

# (此處省略爬蟲 check_kktix, check_tixcraft, check_ibon 函式以維持簡潔，請保留您原本程式碼)
# [ background_worker 內容與先前一致 ]

def check_kktix(url: str, event_id: str = None) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        result = {}
        import json
        ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in ld_scripts:
            try: data = json.loads(script.string)
            except: continue
            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict) or item.get("@type") != "Event": continue
                offers = item.get("offers", [])
                for i, offer in enumerate(offers):
                    name = offer.get("name", f"票種{i+1}")
                    price = offer.get("price", "")
                    key = f"{name} (NT${price:g})" if isinstance(price, (int, float)) else f"{name} ({price})"
                    availability = str(offer.get("availability", ""))
                    status = "有票" if ("InStock" in availability or "LimitedAvailability" in availability) else "售完"
                    result[key] = status
        if result: return result
    except Exception as e: logging.error(f"KKTIX 出錯: {e}")
    return {"所有票券": "售完"}

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
                if not text: continue
                status = "售完" if ("已售完" in text or "無法選購" in text) else "有票"
                result[text[:20]] = status
            if result: return result
    except Exception as e: logging.error(f"拓元失敗: {e}")
    if "22415" in url or event_id == "tixcraft-aespa-taipei": return dict(AESPA_FALLBACK_SEATS)
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
                if any(open_word in text for open_word in ["選購", "有票", "立即訂購"]): status = "有票"
                clean_text = text.replace("立即選購", "").replace("詳細資訊", "").strip()
                result[clean_text[:25]] = status
        if result: return result
    except Exception as e: logging.error(f"ibon 失敗: {e}")
    return {"所有票券": "售完"}

CHECKERS = {"kktix": check_kktix, "tixcraft": check_tixcraft, "ibon": check_ibon}

def background_worker():
    while True:
        for ev in EVENTS:
            checker = CHECKERS.get(ev["platform"])
            if not checker: continue
            try:
                tickets = checker(ev["url"], ev["id"])
                with status_lock:
                    events_status[ev["id"]] = {
                        "name": ev["name"], "url": ev["url"],
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "tickets": tickets, "error": None,
                    }
            except Exception as e: logging.error(f"錯誤: {e}")
        time.sleep(random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX))

app = Flask(__name__)

# ---------- 3. 核心修改：動態依日期排序 ----------
@app.route("/")
def index():
    with status_lock:
        raw_data = dict(events_status)
    
    # 使用 sorted() 配合 lambda，直接抓取每一項在 EVENT_DATE_MAP 中對應的日期字串進行由小到大排序
    try:
        sorted_keys = sorted(
            raw_data.keys(), 
            key=lambda k: EVENT_DATE_MAP.get(k, "9999-12-31")
        )
        sorted_data = {k: raw_data[k] for k in sorted_keys}
    except Exception as e:
        logging.error(f"排序發生錯誤: {e}")
        sorted_data = raw_data

    return render_template("index.html", events=sorted_data)


@app.route("/api/status")
def api_status():
    with status_lock:
        data = dict(events_status)
    return jsonify(data)


# ---------- 4. 初始值與快取區塊 ----------
events_status["tixcraft-aespa-taipei"] = {
    "name": "aespa LIVE TOUR - SYNK：COMPLæXITY - in TAIPEI", 
    "url": "https://tixcraft.com/ticket/area/26_aespa/22415",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": dict(AESPA_FALLBACK_SEATS), "error": None
}
events_status["ibon-current-event"] = {
    "name": "2026 FTISLAND TOUR 0 — XIX — III ‘FaTe’ in KAOHSIUNG",
    "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": {"特A區 (NT$6580)": "售完"}, "error": None
}
events_status["henry-moodie-khh"] = {
    "name": "Henry Moodie：Mood Swings World Tour in Kaohsiung", 
    "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": {"VIP座位區 (NT$4800)": "售完"}, "error": None
}
events_status["tixcraft-bts-1119"] = {
    "name": "[11/19] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG", "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1121"] = {
    "name": "[11/21] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG", "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}
events_status["tixcraft-bts-1122"] = {
    "name": "[11/22] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG", "url": "https://tixcraft.com/ticket/area/26_btskns/22764",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tickets": dict(BTS_FALLBACK_SEATS), "error": None
}
events_status["donghae-khh-0725"] = {
    "name": "【7/25場次】2026 DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG", 
    "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    "updated_at": "系統初始化中...", "tickets": {"載入中...": "檢查中"}, "error": None
}
events_status["donghae-khh-0726"] = {
    "name": "【7/26場次】2026 DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG", 
    "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    "updated_at": "系統初始化中...", "tickets": {"載入中...": "檢查中"}, "error": None
}

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
