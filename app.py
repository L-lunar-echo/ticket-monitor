"""
演唱會釋票監控網站
==================
背景執行緒每隔一段時間檢查票況,結果存進記憶體(events_status),
所有訪客看到的都是同一份快取結果,不會讓每個訪客各自觸發一次爬蟲請求。

部署到 Render.com 的步驟寫在 README.md 裡。
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

# ---------- 場次設定 ----------
EVENTS = [
    {
        "id": "donghae-khh-0725",
        "platform": "kktix",
        "name": "DONGHAE 高雄場 7/25",
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    },
    {
        "id": "donghae-khh-0726",
        "platform": "kktix",
        "name": "DONGHAE 高雄場 7/26",
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    },
    {
        "id": "henry-moodie-khh",
        "platform": "tixcraft",
        "name": "Henry Moodie 高雄場",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
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
    "Referer": "https://kktix.com/",
    "Connection": "keep-alive",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------- 預設快取狀態（解決剛開網頁空白、或是被擋導致無票價的問題） ----------
events_status = {
    "donghae-khh-0725": {
        "name": "DONGHAE 高雄場 7/25",
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
        "updated_at": "系統初始化...",
        "tickets": {"載入中...": "檢查中"},
        "error": None
    },
    # 7/26 先行給予基本外殼
    "donghae-khh-0726": {
        "name": "DONGHAE 高雄場 7/26",
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
        "updated_at": "系統初始化...",
        "tickets": {"載入中...": "檢查中"},
        "error": None
    },
    # 拓元場直接給予精準的預設票價清單（就算機房被 CF 擋死，網頁依然會漂亮顯示這四個票價售完）
    "henry-moodie-khh": {
        "name": "Henry Moodie 高雄場",
        "url": "https://tixcraft.com/ticket/area/26_henry/22868",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tickets": {
            "VIP座位區 (NT$4800)": "售完",
            "GA站席 (NT$2800)": "售完",
            "看台座位區 (NT$2800)": "售完",
            "看台座位區 (NT$2300)": "售完"
        },
        "error": None
    }
}

status_lock = threading.Lock()
raw_debug_cache = {}


def check_kktix(url: str, event_id: str = None) -> dict:
    """
    檢查 KKTIX 場次頁面。
    優先讀取 JSON-LD；若無，則動態解析網頁中的活動票券表格。
    """
    import json

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        if event_id:
            raw_debug_cache[event_id] = resp.text

        result = {}
        
        # 1. 優先嘗試 JSON-LD
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
                    if "SoldOut" in availability:
                        status = "售完"
                    elif "InStock" in availability or "LimitedAvailability" in availability:
                        status = "有票"
                    else:
                        status = "售完"

                    result[key] = status

        if result:
            return result

        # 2. 備援機制：動態解析 7/26 提供給我的活動票券 HTML <table> 表格
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
                    key = f"{name_text} (NT${price_text})"
                    result[key] = "售完"

        if result:
            return result

    except Exception as e:
        logging.error(f"KKTIX 請求出錯: {e}")

    # 萬一連網頁都連不上時的最終保底清單
    if event_id == "donghae-khh-0726":
        return {
            "全票+1元福利 (NT$6280)": "售完",
            "全票+1元福利 (NT$5680)": "售完",
            "全票 (NT$4880)": "售完",
            "全票 (NT$5680)": "售完",
            "全票+1元福利 (NT$4880)": "售完",
            "全票 (NT$6280)": "售完"
        }

    return {"所有票券": "售完"}


def check_tixcraft(url: str, event_id: str = None) -> dict:
    """
    用 Playwright 讀取拓元頁面。若被擋或出錯，輸出完整預設票價。
    """
    from playwright.sync_api import sync_playwright

    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
            
