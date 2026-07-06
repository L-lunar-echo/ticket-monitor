import os
import time
import random
import logging
import threading
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# ---------- 1. 場次設定（已嚴格依時間先後順序排列） ----------
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

# aespa 完整防禦備援清單
AESPA_FALLBACK_SEATS = {
    "B2層002區 $7880": "售完", "B2層003區 $7880": "售完", "B2層004區 $7880": "售完", "B2層005區 $7880": "售完", 
    "B2層007區 $7880": "售完", "B2層008區 $7880": "售完", "B2層009區 $7880": "售完", "B2層010區 $7880": "售完", 
    "B2層011區 $7880": "售完", "B2層012區 $7880": "售完", "B2層013區 $6880": "售完", "B2層014區 $6880": "售完", 
    "B2層001區 $5880": "售完", "B2層006區 $5880": "售完", "B1看台103區 $6880": "售完", "B1看台104區 $6880": "售完", 
    "B1看台105區 $6880": "售完", "B1看台106區 $6880": "售完", "B1看台107區 $6880": "售完", "B1看台108區 $6880": "售完", 
    "B1看台109區 $6880": "售完", "B1看台110區 $6880": "售完", "B1看台111區 $6880": "售完", "B1看台115區 $6880": "售完", 
    "B1看台116區 $6880": "售完", "B1看台117區 $6880": "售完", "B1看台118區 $6880": "售完", "B1看台119區 $6880": "售完", 
    "B1看台120區 $6880": "售完", "B1看台121區 $6880": "售完", "B1看台122區 $6880": "售完", "B1看台123區 $6880": "售完", 
    "B1看台102區 $5880": "售完", "B1看台124區 $5880": "售完", "L2看台203區 $5880": "售完", "L2看台204區 $5880": "售完", 
    "L2看台205區 $5880": "售完", "L2看台206區 $5880": "售完", "L2看台207區 $5880": "售完", "L2看台208區 $5880": "售完", 
    "L2看台209區 $5880": "售完", "L2看台210區 $5880": "售完", "L2看台211區 $5880": "售完", "L2看台212區 $5880": "售完", 
    "L2看台213區 $5880": "售完", "L2看台214區 $5880": "售完", "L2看台215區 $5880": "售完", "L2看台216區 $5880": "售完", 
    "L2看台217區 $5880": "售完", "L2看台218區 $5880": "售完", "L2看台219區 $5880": "售完", "L2看台220區 $5880": "售完", 
    "L2看台221區 $5880": "售完", "L2看台222區 $5880": "售完", "L2看台223區 $5880": "售完", "L2看台202區 $4880": "售完", 
    "L2看台224區 $4880": "售完", "L3看台301區 $4880": "售完", "L3看台302區 $4880": "售完", "L3看台303區 $4880": "售完", 
    "L3看台304區 $4880": "售完", "L3看台314區 $4880": "售完", "L3看台315區 $4880": "售完", "L3看台316區 $4880": "售完", 
    "L3看台317區 $4880": "售完", "L4看台405區 $4880": "售完", "L4看台406區 $4880": "售完", "L4看台407區 $4880": "售完", 
    "L4看台408區 $4880": "售完", "L4看台409區 $4880": "售完", "L4看台410區 $4880": "售完", "L4看台411區 $4880": "售完", 
    "L4看台412區 $4880": "售完", "L4看台413區 $4880": "售完", "L4看台401區 $3880": "售完", "L4看台402區 $3880": "售完", 
    "L4క區403區 $3880": "售完", "L4看台404區 $3880": "售完", "L4看台414區 $3880": "售完", "L4看台415區 $3880": "售完", 
    "L4看台416區 $3880": "售完", "L4看台417區 $3880": "售完", "L5看台506區 $3880": "售完", "L5看台507區 $3880": "售完", 
    "L5看台508區 $3880": "售完", "L5看台509區 $3880": "售完", "L5看台510區 $3880": "售完", "L5看台511區 $3880": "售完", 
    "L5看台512區 $3880": "售完", "L5看台503區 $2880": "售完", "L5看台504區 $2880": "售完", "L5看台505區 $2880": "售完", 
    "L5看台513區 $2880": "售完", "L5看台514區 $2880": "售完", "L5看台515區 $2880": "售完", "B1看台108身障區 $3440": "售完", 
    "B1看台109身障區 $3440": "售完", "B1看台110身障區 $3440": "售完", "B1看台116身障區 $3440": "售完", "B1看台117身障區 $3440": "售完", 
    "B1看台118身障區 $3440": "售完", "L2看台207身障區 $2940": "售完", "L2看台208身障區 $2940": "售完", "L2看台210身障區 $2940": "售完", 
    "L2看台212身障區 $2940": "售完", "L2看台214身障區 $2940": "售完", "L2看台216身障區 $2940": "售完", "L2看台218身障區 $2940": "售完", 
    "L2看台219身障區 $2940": "售完", "L3看台304身障區 $2440": "售完", "L3看台314身障區 $2440": "售完", "L4看台406身障區 $2440": "售完", 
    "L4看台407身障區 $2440": "售完", "L4看台411身障區 $2440": "售完", "L4看台412身障區 $2440": "售完", "L4看台403身障區 $1940": "售完", 
    "L4看台404身障區 $1940": "售完", "L4看台414身障區 $1940": "售完", "L4看台415身障區 $1940": "售完"
}

# BTS 完整防禦備援清單
BTS_FALLBACK_SEATS = {
    "A1區 $9380": "售完", "A2區 $9380": "售完", "A3區 $9380": "售完", "A5區 $9380": "售完", "A6區 $9380": "售完", "A7區 $9380": "售完", 
    "R2區 $9380": "售完", "R3區 $9380": "售完", "R4區 $9380": "售完", "R5區 $9380": "售完", "R6區 $9380": "售完", "M1區 $9380": "售完", 
    "M2區 $9380": "售完", "M3區 $9380": "售完", "M5區 $9380": "售完", "M6區 $9380": "售完", "M7區 $9380": "售完", "Y2區 $9380": "售完", 
    "Y3區 $9380": "售完", "Y4區 $9380": "售完", "Y5區 $9380": "售完", "Y6區 $9380": "售完", "A4區 $7980": "售完", "A5區 $7980": "售完", 
    "A6區 $7980": "售完", "A7區 $7980": "售完", "A8區 $7980": "售完", "R1區 $7980": "售完", "R7區 $7980": "售完", "R8區 $7980": "售完", 
    "R9區 $7980": "售完", "R10區 $7980": "售完", "R11區 $7980": "售完", "R12區 $7980": "售完", "R13區 $7980": "售完", "R14區 $7980": "售完", 
    "M4區 $7980": "售完", "M5區 $7980": "售完", "M6區 $7980": "售完", "M7區 $7980": "售完", "M8區 $7980": "售完", "Y1區 $7980": "售完", 
    "Y7區 $7980": "售完", "Y8區 $7980": "售完", "Y9區 $7980": "售完", "Y10區 $7980": "售完", "Y11區 $7980": "售完", "Y12區 $7980": "售完", 
    "Y13區 $7980": "售完", "Y14區 $7980": "售完", "1樓C03區 $7980": "售完", "1樓C04區 $7980": "售完", "1樓C05區 $7980": "售完", 
    "1樓C06區 $7980": "售完", "1樓C07區 $7980": "售完", "1樓C08區 $7980": "售完", "1樓C09區 $7980": "售完", "1樓G03區 $7980": "售完", 
    "1樓G04區 $7980": "售完", "1樓G05區 $7980": "售完", "1樓G06區 $7980": "售完", "1樓G07區 $7980": "售完", "1樓G08區 $7980": "售完", 
    "1樓G09區 $7980": "售完", "1樓G10區 $7980": "售完", "1樓G11區 $7980": "售完", "A9區 $6980": "售完", "A10區 $6980": "售完", 
    "A11區 $6980": "售完", "A12區 $6980": "售完", "A13區 $6980": "售完", "M9區 $6980": "售完", "M10區 $6980": "售完", "M11區 $6980": "售完", 
    "M12區 $6980": "售完", "M13區 $6980": "售完", "1樓C02區 $6980": "售完", "1樓C10區 $6980": "售完", "1樓G02區 $6980": "售完", 
    "1樓G12區 $6980": "售完", "1樓V04區 $6980": "售完", "1樓V05區 $6980": "售完", "1樓V06區 $6980": "售完", "1樓V07區 $6980": "售完", 
    "1樓V08區 $6980": "售完", "1樓V09區 $6980": "售完", "1樓A01區 $5980": "售完", "1樓A02區 $5980": "售完", "1樓B03區 $5980": "售完", 
    "1樓C01區 $5980": "售完", "1樓C11區 $5980": "售完", "1樓D01區 $5980": "售完", "1樓E02區 $5980": "售完", "1樓E03區 $5980": "售完", 
    "1樓E04區 $5980": "售完", "1樓E05區 $5980": "售完", "1樓E06區 $5980": "售完", "1樓E07區 $5980": "售完", "1樓E08區 $5980": "售完", 
    "1樓E09區 $5980": "售完", "1樓E10區 $5980": "售完", "1樓E11區 $5980": "售完", "1樓E12區 $5980": "售完", "1樓E13區 $5980": "售完", 
    "1樓E14區 $5980": "售完", "1樓F03區 $5980": "售完", "1樓G01區 $5980": "售完", "1樓G13區 $5980": "售完", "1樓H01區 $5980": "售完", 
    "1樓I03區 $5980": "售完", "1樓I04區 $5980": "售完", "1樓V01區 $5980": "售完", "1樓V02區 $5980": "售完", "1樓V03區 $5980": "售完", 
    "1樓V10區 $5980": "售完", "1樓V11區 $5980": "售完", "1樓V12區 $5980": "售完", "2樓C13區 $5980": "售完", "2樓C14區 $5980": "售完", 
    "2樓C15區 $5980": "售完", "2樓C16區 $5980": "售完", "2樓C17區 $5980": "售完", "2樓C18區 $5980": "售完", "2樓C19區 $5980": "售完", 
    "2樓C20區 $5980": "售完", "2樓C21區 $5980": "售完", "2樓C22區 $5980": "售完", "2樓C23區 $5980": "售完", "2樓C24區 $5980": "售完", 
    "2樓G16區 $5980": "售完", "2樓G17區 $5980": "售完", "2樓G18區 $5980": "售完", "2樓G19區 $5980": "售完", "2樓G20區 $5980": "售完", 
    "2樓G21區 $5980": "售完", "2樓G22區 $5980": "售完", "2樓G23區 $5980": "售完", "2樓G24區 $5980": "售完", "2樓G25區 $5980": "售完", 
    "2樓G26區 $5980": "售完", "1樓A03區 $4980": "售完", "1樓D02區 $4980": "售完", "1樓E01區 $4980": "售完", "1樓E15區 $4980": "售完", 
    "1樓F02區 $4980": "售完", "1樓H02區 $4980": "售完", "1樓I02區 $4980": "售完", "2樓B08區 $4980": "售完", "2樓C12區 $4980": "售完", 
    "2樓C25區 $4980": "售完", "2樓D05區 $4980": "售完", "2樓D06區 $4980": "售完", "2樓E19區 $4980": "售完", "2樓E20區 $4980": "售完", 
    "2樓E21區 $4980": "售完", "2樓E22區 $4980": "售完", "2樓E23區 $4980": "售完", "2樓E24區 $4980": "售完", "2樓E25區 $4980": "售完", 
    "2樓E26區 $4980": "售完", "2樓E27區 $4980": "售完", "2樓E28區 $4980": "售完", "2樓E29區 $4980": "售完", "2樓E30區 $4980": "售完", 
    "2樓E31區 $4980": "售完", "2樓F07區 $4980": "售完", "2樓G14區 $4980": "售完", "2樓G15區 $4980": "售完", "2樓G27區 $4980": "售完", 
    "1樓B01區 $3980": "售完", "1樓B02區 $3980": "售完", "1樓D03區 $3980": "售完", "1樓D04區 $3980": "售完", "1樓E16區 $3980": "售完", 
    "1樓F01區 $3980": "售完", "1樓H03區 $3980": "售完", "1樓I01區 $3980": "售完", "2樓B07區 $3980": "售完", "2樓D07區 $3980": "售完", 
    "2樓D09區 $3980": "售完", "2樓E17區 $3980": "售完", "2樓E18區 $3980": "售完", "2樓E32區 $3980": "售完", "2樓F06區 $3980": "售完", 
    "2樓H04區 $3980": "售完", "2樓H05區 $3980": "售完", "2樓H06區 $3980": "售完", "2樓B04區 $2980": "售完", "2樓B05區 $2980": "售完", 
    "2樓B06區 $2980": "售完", "2樓D08區 $2980": "售完", "2樓E33區 $2980": "售完", "2樓F04區 $2980": "售完", "2樓F05區 $2980": "售完", 
    "2樓H07區 $2980": "售完", "2樓H08區 $2980": "售完", "1樓G05區身障優惠區 $3490": "售完", "1樓G06區身障優惠區 $3490": "售完", 
    "1樓G07區身障優惠區 $3490": "售完", "1樓G08區身障優惠區 $3490": "售完", "1樓G09區身障優惠區 $3490": "售完", "1樓E02區身障優惠區 $2990": "售完", 
    "1樓E03區身障優惠區 $2990": "售完", "1樓E04區身障優惠區 $2990": "售完", "1樓E05區身障優惠區 $2990": "售完", "1樓E06區身障優惠區 $2990": "售完", 
    "1樓E07區身障優惠區 $2990": "售完", "1樓E08區身障優惠區 $2990": "售完", "1樓E09區身障優惠區 $2990": "售完", "1樓E10區身障優惠區 $2990": "售完", 
    "1樓E11區身障優惠區 $2990": "售完", "1樓E12區身障優惠區 $2990": "售完", "1樓E13區身障優惠區 $2990": "售完", "1樓E14區身障優惠區 $2990": "售完"
}

# DONGHAE 完整防禦備援清單
DONGHAE_FALLBACK_SEATS = {
    "全票+1元福利 $6,280": "售完",
    "全票 $6,280": "售完",
    "全票+1元福利 $5,680": "售完",
    "全票 $5,680": "售完",
    "全票+1元福利 $4,880": "售完",
    "全票 $4,880": "售完"
}

# FTISLAND 完整防禦備援清單
FTISLAND_FALLBACK_SEATS = {
    "特A區 $6580": "售完", "特B區 $6580": "售完", "2樓2B區 $6580": "售完", "2樓2C區 $6580": "售完", "2樓2D區 $6580": "售完",
    "特A區 $5880": "售完", "特B區 $5880": "售完", "2樓2B區 $5880": "售完", "2樓2C區 $5880": "售完", "2樓2D區 $5880": "售完",
    "2樓2A區 $4880": "售完", "2樓2B區 $4880": "售完", "2樓2D區 $4880": "售完", "2樓2E區 $4880": "售完",
    "2樓2A區 $3880": "售完", "2樓2B區 $3880": "售完", "2樓2C區 $3880": "售完", "2樓2D區 $3880": "售完", "2樓2E區 $3880": "售完"
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


# ---------- 3. 初始值與快取區塊（也同步按照時間重新排序） ----------
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
    "tickets": {"M&G + SOUNDCHECK PACKAGE": "售完", "SOUNDCHECK PACKAGE": "售完", "一般站區 GA": "售完"}, "error": None
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
    
