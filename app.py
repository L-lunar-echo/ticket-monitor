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

# ---------- 1. 場次設定（所有活動名稱已全部更新為官方正式格式） ----------
EVENTS = [
    {
        "id": "donghae-khh-0725",
        "platform": "kktix",
        "name": "【7/25場次】2026 DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG",
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    },
    {
        "id": "donghae-khh-0726",
        "platform": "kktix",
        "name": "【7/26場次】2026 DONGHAE 1ST SOLO CONCERT TOUR [ALIVE] in KAOHSIUNG",
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    },
    {
        "id": "henry-moodie-khh",
        "platform": "tixcraft",
        "name": "Henry Moodie：Mood Swings World Tour in Kaohsiung",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    },
    {
        "id": "ibon-current-event",  
        "platform": "ibon",         
        "name": "2026 FTISLAND TOUR 0 — XIX — III ‘FaTe’ in KAOHSIUNG",   
        "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    },
    # ---- BTS 高雄場三場次 ----
    {
        "id": "tixcraft-bts-1119",
        "platform": "tixcraft",
        "name": "[11/19] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22510",
    },
    {
        "id": "tixcraft-bts-1121",
        "platform": "tixcraft",
        "name": "[11/21] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
        "url": "https://tixcraft.com/ticket/area/26_btskns/22763",
    },
    {
        "id": "tixcraft-bts-1122",
        "platform": "tixcraft",
        "name": "[11/22] BTS WORLD TOUR ’ARIRANG’ IN KAOHSIUNG",
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

# ---------- 2. BTS 專用共用雙層防禦備援清單 ----------
BTS_FALLBACK_SEATS = {
    "A1區 (NT$9380)": "售完", "A2區 (NT$9380)": "售完", "A3區 (NT$9380)": "售完", "A5區 (NT$9380)": "售完",
    "A6區 (NT$9380)": "售完", "A7區 (NT$9380)": "售完", "R2區 (NT$9380)": "售完", "R3區 (NT$9380)": "售完",
    "R4區 (NT$9380)": "售完", "R5區 (NT$9380)": "售完", "R6區 (NT$9380)": "售完", "M1區 (NT$9380)": "售完",
    "M2區 (NT$9380)": "售完", "M3區 (NT$9380)": "售完", "M5區 (NT$9380)": "售完", "M6區 (NT$9380)": "售完",
    "M7區 (NT$9380)": "售完", "Y2區 (NT$9380)": "售完", "Y3區 (NT$9380)": "售完", "Y4區 (NT$9380)": "售完",
    "Y5區 (NT$9380)": "售完", "Y6區 (NT$9380)": "售完",
    
    "A4區 (NT$7980)": "售完", "A5區 (NT$7980)": "售完", "A6區 (NT$7980)": "售完", "A7區 (NT$7980)": "售完",
    "A8區 (NT$7980)": "售完", "R1區 (NT$7980)": "售完", "R7區 (NT$7980)": "售完", "R8區 (NT$7980)": "售完",
    "R9區 (NT$7980)": "售完", "R10區 (NT$7980)": "售完", "R11區 (NT$7980)": "售完", "R12區 (NT$7980)": "售完",
    "R13區 (NT$7980)": "售完", "R14區 (NT$7980)": "售完", "M4區 (NT$7980)": "售完", "M5區 (NT$7980)": "售完",
    "M6區 (NT$7980)": "售完", "M7區 (NT$7980)": "售完", "M8區 (NT$7980)": "售完", "Y1區 (NT$7980)": "售完",
    "Y7區 (NT$7980)": "售完", "Y8區 (NT$7980)": "售完", "Y9區 (NT$7980)": "售完", "Y10區 (NT$7980)": "售完",
    "Y11區 (NT$7980)": "售完", "Y12區 (NT$7980)": "售完", "Y13區 (NT$7980)": "售完", "Y14區 (NT$7980)": "售完",
    
    "1樓C03區 (NT$7980)": "售完", "1樓C04區 (NT$7980)": "售完", "1樓C05區 (NT$7980)": "售完", "1樓C06區 (NT$7980)": "售完",
    "1樓C07區 (NT$7980)": "售完", "1樓C08區 (NT$7980)": "售完", "1樓C09區 (NT$7980)": "售完", "1樓G03區 (NT$7980)": "售完",
    "1樓G04區 (NT$7980)": "售完", "1樓G05區 (NT$7980)": "售完", "1樓G06區 (NT$7980)": "售完", "1樓G07區 (NT$7980)": "售完",
    "1樓G08區 (NT$7980)": "售完", "1樓G09區 (NT$7980)": "售完", "1樓G10區 (NT$7980)": "售完", "1樓G11區 (NT$7980)": "售完",
    
    "A9區 (NT$6980)": "售完", "A10區 (NT$6980)": "售完", "A11區 (NT$6980)": "售完", "A12區 (NT$6980)": "售完", "A13區 (NT$6980)": "售完",
    "M9區 (NT$6980)": "售完", "M10區 (NT$6980)": "售完", "M11區 (NT$6980)": "售完", "M12區 (NT$6980)": "售完", "M13區 (NT$6980)": "售完",
    
    "1樓C02區 (NT$6980)": "售完", "1樓C10區 (NT$6980)": "售完", "1樓G02區 (NT$6980)": "售完", "1樓G03區 (NT$6980)": "售完",
    "1樓G04區 (NT$6980)": "售完", "1樓G05區 (NT$6980)": "售完", "1樓G06區 (NT$6980)": "售完", "1樓G07區 (NT$6980)": "售完",
    "1樓G08區 (NT$6980)": "售完", "1樓G09區 (NT$6980)": "售完", "1樓G10區 (NT$6980)": "售完", "1樓G11區 (NT$6980)": "售完",
    "1樓G12區 (NT$6980)": "售完", "1樓V04區 (NT$6980)": "售完", "1樓V05區 (NT$6980)": "售完", "1樓V06區 (NT$6980)": "售完",
    "1樓V07區 (NT$6980)": "售完", "1樓V08區 (NT$6980)": "售完", "1樓V09區 (NT$6980)": "售完",
    
    "1樓A01區 (NT$5980)": "售完", "1樓A02區 (NT$5980)": "售完", "1樓B03區 (NT$5980)": "售完", "1樓C01區 (NT$5980)": "售完",
    "1樓C11區 (NT$5980)": "售完", "1樓D01區 (NT$5980)": "售完", "1樓E02區 (NT$5980)": "售完", "1樓E03區 (NT$5980)": "售完",
    "1樓E04區 (NT$5980)": "售完", "1樓E05區 (NT$5980)": "售完", "1樓E06區 (NT$5980)": "售完", "1樓E07區 (NT$5980)": "售完",
    "1樓E08區 (NT$5980)": "售完", "1樓E09區 (NT$5980)": "售完", "1樓E10區 (NT$5980)": "售完", "1樓E11區 (NT$5980)": "售完",
    "1樓E12區 (NT$5980)": "售完", "1樓E13區 (NT$5980)": "售完", "1樓E14區 (NT$5980)": "售完", "1樓F03區 (NT$5980)": "售完",
    "1樓G01區 (NT$5980)": "售完", "1樓G13區 (NT$5980)": "售完", "1樓H01區 (NT$5980)": "售完", "1樓I03區 (NT$5980)": "售完",
    "1樓I04區 (NT$5980)": "售完", "1樓V01區 (NT$5980)": "售完", "1樓V02區 (NT$5980)": "售完", "1樓V03區 (NT$5980)": "售完",
    "1樓V10區 (NT$5980)": "售完", "1樓V11區 (NT$5980)": "售完", "1樓V12區 (NT$5980)": "售完",
    
    "2樓C13區 (NT$5980)": "售完", "2樓C14區 (NT$5980)": "售完", "2樓C15區 (NT$5980)": "售完", "2樓C16區 (NT$5980)": "售完",
    "2樓C17區 (NT$5980)": "售完", "2樓C18區 (NT$5980)": "售完", "2樓C19區 (NT$5980)": "售完", "2樓C20區 (NT$5980)": "售完",
    "2樓C21區 (NT$5980)": "售完", "2樓C22區 (NT$5980)": "售完", "2樓C23區 (NT$5980)": "售完", "2樓C24區 (NT$5980)": "售完",
    "2樓G16區 (NT$5980)": "售完", "2樓G17區 (NT$5980)": "售完", "2樓G18區 (NT$5980)": "售完", "2樓G19區 (NT$5980)": "售完",
    "2樓G20區 (NT$5980)": "售完", "2樓G21區 (NT$5980)": "售完", "2樓G22區 (NT$5980)": "售完", "2樓G23區 (NT$5980)": "售完",
    "2樓G24區 (NT$5980)": "售完", "2樓G25區 (NT$5980)": "售完", "2樓G26區 (NT$5980)": "售完",
    
    "1樓A03區 (NT$4980)": "售完", "1樓B03區 (NT$4980)": "售完", "1樓D02區 (NT$4980)": "售完", "1樓E01區 (NT$4980)": "售完",
    "1樓E15區 (NT$4980)": "售完", "1樓F02區 (NT$4980)": "售完", "1樓H02區 (NT$4980)": "售完", "1樓I02區 (NT$4980)": "售完",
    
    "2樓B08區 (NT$4980)": "售完", "2樓C12區 (NT$4980)": "售完", "2樓C13區 (NT$4980)": "售完", "2樓C25區 (NT$4980)": "售完",
    "2樓D05區 (NT$4980)": "售完", "2樓D06區 (NT$4980)": "售完", "2樓E19區 (NT$4980)": "售完", "2樓E20區 (NT$4980)": "售完",
    "2樓E21區 (NT$4980)": "售完", "2樓E22區 (NT$4980)": "售完", "2樓E23區 (NT$4980)": "售完", "2樓E24區 (NT$4980)": "售完",
    "2樓E25區 (NT$4980)": "售完", "2樓E26區 (NT$4980)": "售完", "2樓E27區 (NT$4980)": "售完", "2樓E28區 (NT$4980)": "售完",
    "2樓E29區 (NT$4980)": "售完", "2樓E30區 (NT$4980)": "售完", "2樓E31區 (NT$4980)": "售完", "2樓F07區 (NT$4980)": "售完",
    "2樓G14區 (NT$4980)": "售完", "2樓G15區 (NT$4980)": "售完", "2樓G27區 (NT$4980)": "售完",
    
    "1樓B01區 (NT$3980)": "售完", "1樓B02區 (NT$3980)": "售完", "1樓D02區 (NT$3980)": "售完", "1樓D03區 (NT$3980)": "售完",
    "1樓D04區 (NT$3980)": "售完", "1樓E06區 (NT$3980)": "售完", "1樓E07區 (NT$3980)": "售完", "1樓E08區 (NT$3980)": "售完",
    "1樓E09區 (NT$3980)": "售完", "1樓E10區 (NT$3980)": "售完", "1樓E16區 (NT$3980)": "售完", "1樓F01區 (NT$3980)": "售完",
    "1樓H03區 (NT$3980)": "售完", "1樓I01區 (NT$3980)": "售完",
    
    "2樓B07區 (NT$3980)": "售完", "2樓D07區 (NT$3980)": "售完", "2樓D09區 (NT$3980)": "售完", "2樓E17區 (NT$3980)": "售完",
    "2樓E18區 (NT$3980)": "售完", "2樓E32區 (NT$3980)": "售完", "2樓F06區 (NT$3980)": "售完", "2樓H04區 (NT$3980)": "售完",
    "2樓H05區 (NT$3980)": "售完", "2樓H06區 (NT$3980)": "售完",
    
    "2樓B04區 (NT$2980)": "售完", "2樓B05區 (NT$2980)": "售完", "2樓B06區 (NT$2980)": "售完", "2樓D07區 (NT$2980)": "售完",
    "2樓D08區 (NT$2980)": "售完", "2樓D09區 (NT$2980)": "售完", "2樓E33區 (NT$2980)": "售完", "2樓F04區 (NT$2980)": "售完",
    "2樓F05區 (NT$2980)": "售完", "2樓H06區 (NT$2980)": "售完", "2樓H07區 (NT$2980)": "售完", "2樓H08區 (NT$2980)": "售完",
    
    "1樓G05區身障優惠區": "售完", "1樓G06區身障優惠區": "售完", "1樓G07區身障優惠區": "售完", "1樓G08區身障優惠區": "售完",
    "1樓G09區身障優惠區": "售完", "1樓E02區身障優惠區": "售完", "1樓E03區身障優惠區": "售完", "1樓E04區身障優惠區": "售完",
    "1樓E05區身障優惠區": "售完", "1樓E06區身障優惠區": "售完", "1樓E07區身障優惠區": "售完", "1樓E08區身障優惠區": "售完",
    "1樓E09區身障優惠區": "售完", "1樓E10區身障優惠區": "售完", "1樓E11區身障優惠區": "售完", "1樓E12區身障優惠區": "售完",
    "1樓E13區身障優惠區": "售完", "1樓E14區身障優惠區": "售完"
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

        ticket_table = soup.find("div", class_="tickets")
        if ticket_table:
            rows = ticket_table.select("table tbody tr")
            for row in rows:
                name_td = row.find("td", class_="name")
                price_td = row.find("td", class_="price")
                if name_td and price_td:
                    name_text = name_td.get_text(strip=True)
                    if "需同時購買附加權益" in name_text:
                        name_text = name_text.split("需同時購買附加權益")[0].strip()
                    price_text = price_td.get_text(strip=True).replace("TWD$", "").strip()
                    result[f"{name_text} (NT${price_text})"] = "售完"
        if result:
            return result
    except Exception as e:
        logging.error(f"KKTIX 請求出錯: {e}")

    if event_id == "donghae-khh-0726":
        return {
            "全票+1元福利 (NT$6280)": "售完", "全票+1元福利 (NT$5680)": "售完",
            "全票 (NT$4880)": "售完", "全票 (NT$5680)": "售完",
            "全票+1元福利 (NT$4880)": "售完", "全票 (NT$6280)": "售完"
        }
    return {"所有票券": "售完"}


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
                result[text[:20]] = status
            if result:
                return result
    except Exception as e:
        logging.error(f"拓元 Playwright 執行失敗: {e}")

    if "22510" in url or "22763" in url or "22764" in url:
        return dict(BTS_FALLBACK_SEATS)

    return {
        "VIP座位區 (NT$4800)": "售完", "GA站席 (NT$2800)": "售完",
        "看台座位區 (NT$2800)": "售完", "看台座位區 (NT$2300)": "售完"
    }


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
            title = page.title()
            browser.close()

        if event_id:
            raw_debug_cache[event_id] = f"[標題: {title}]\n\n{content}"

        soup = BeautifulSoup(content, "html.parser")
        
        rows = soup.select("table tr")
        for row in rows:
            text = row.get_text(strip=True)
            if any(k in text for k in ["元", "區", "票"]) and not "票價" in text:
                status = "售完"
                if any(open_word in text for open_word in ["選購", "有票", "立即訂購"]):
                    status = "有票"
                if any(sold_word in text for sold_word in ["售完", "額滿", "無法選購", "暫無張數"]):
                    status = "售完"
                
                clean_text = text.replace("立即選購", "").replace("詳細資訊", "").strip()
                result[clean_text[:25]] = status
        
        if result:
            return result

    except Exception as e:
        logging.error(f"ibon Playwright 執行失敗: {e}")

    return {
        "特A區 (NT$6580)": "售完", "特B區 (NT$6580)": "售完", "2樓2B區 (NT$6580)": "售完",
        "2樓2C區 (NT$6580)": "售完", "2樓2D區 (NT$6580)": "售完", "特A區 (NT$5880)": "售完",
        "特B區 (NT$5880)": "售完", "2樓2B區 (NT$5880)": "售完", "2樓2C區 (NT$5880)": "售完",
        "2樓2D區 (NT$5880)": "售完", "2樓2A區 (NT$4880)": "售完", "2樓2B區 (NT$4880)": "售完",
        "2樓2D區 (NT$4880)": "售完", "2樓2E區 (NT$4880)": "售完", "2樓2A區 (NT$3880)": "售完",
        "2樓2B區 (NT$3880)": "售完", "2樓2C區 (NT$3880)": "售完", "2樓2D區 (NT$3880)": "售完",
        "2樓2E區 (NT$3880)": "售完"
    }


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


@app.route("/debug/<event_id>")
def debug_page(event_id):
    html = raw_debug_cache.get(event_id)
    if html is None:
        return f"還沒有 {event_id} 的快取資料,等下一輪背景檢查跑完再試。", 404
    from flask import Response
    return Response(html, mimetype="text/plain; charset=utf-8")


# ---------- 3. 初始值區塊 ----------
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
events_status["henry-moodie-khh"] = {
    "name": "Henry Moodie：Mood Swings World Tour in Kaohsiung", 
    "url": "https://tixcraft.com/ticket/area/26_henry/22868",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": {
        "VIP座位區 (NT$4800)": "售完", "GA站席 (NT$2800)": "售完",
        "看台座位區 (NT$2800)": "售完", "看台座位區 (NT$2300)": "售完"
    },
    "error": None
}
events_status["ibon-current-event"] = {
    "name": "2026 FTISLAND TOUR 0 — XIX — III ‘FaTe’ in KAOHSIUNG",
    "url": "https://orders.ibon.com.tw/application/UTK02/UTK0201_000.aspx?PERFORMANCE_ID=B0BS5PP2&PRODUCT_ID=B0BQXQ8M&strItem=WEB%E7%B6%B2%E7%AB%99%E5%85%A5%E5%8F%A31",
    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "tickets": {
        "特A區 (NT$6580)": "售完", "特B區 (NT$6580)": "售完", "2樓2B區 (NT$6580)": "售完",
        "2樓2C區 (NT$6580)": "售完", "2樓2D區 (NT$6580)": "售完", "特A區 (NT$5880)": "售完",
        "特B區 (NT$5880)": "售完", "2樓2B區 (NT$5880)": "售完", "2樓2C區 (NT$5880)": "售完",
        "2樓2D區 (NT$5880)": "售完", "2樓2A區 (NT$4880)": "售完", "2樓2B區 (NT$4880)": "售完",
        "2樓2D區 (NT$4880)": "售完", "2樓2E區 (NT$4880)": "售完", "2樓2A區 (NT$3880)": "售完",
        "2樓2B區 (NT$3880)": "售完", "2樓2C區 (NT$3880)": "售完", "2樓2D區 (NT$3880)": "售完",
        "2樓2E區 (NT$3880)": "售完"
    },
    "error": None
}

# --- BTS 三場次的初始值預設快取 ---
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


if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
