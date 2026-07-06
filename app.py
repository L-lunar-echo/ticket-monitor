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
]

# 保持 30 ~ 60 秒的輪詢頻率
CHECK_INTERVAL_MIN = 30
CHECK_INTERVAL_MAX = 60

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

events_status = {}
status_lock = threading.Lock()
raw_debug_cache = {}


def check_kktix(url: str, event_id: str = None) -> dict:
    """
    檢查 KKTIX 場次票況（防 403 封鎖安全升級版）。
    優先嘗試即時 API 路線，若遭遇 Cloudflare 403 阻擋，自動降級至安全的網頁表格解析，
    並針對已知的過期/結束場次進行精準修復。
    """
    import json
    import re

    slug = url.split("/events/")[-1].split("?")[0]
    api_url = f"https://kktix.com/g/events/{slug}/register_info"
    
    # 建立擬真的 AJAX 請求標頭，降低 API 被 403 的機率
    ajax_headers = dict(HEADERS)
    ajax_headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"https://kktix.com/events/{slug}/registrations/new"
    })
    
    try:
        # 1. 優先嘗試即時 API 路線
        resp = requests.get(api_url, headers=ajax_headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if event_id:
            raw_debug_cache[event_id] = json.dumps(data, ensure_ascii=False, indent=2)
            
        result = {}
        inventory = data.get("inventory", {})
        order_info = data.get("order_info", {})
        ticket_types = order_info.get("ticket_types", [])

        for t in ticket_types:
            name = t.get("name")
            id_ = str(t.get("id"))
            price = t.get("price", "0")
            key = f"{name} (NT${price})"
            
            # 如果不在販售時間內，直接顯示售完
            if t.get("is_hidden") or not t.get("in_sale_period"):
                result[key] = "售完"
                continue
                
            count = inventory.get(id_, 0)
            result[key] = "有票" if count > 0 else "售完"
            
        if result:
            return result

    except Exception as e:
        logging.warning(f"[{event_id}] API 路線失敗或遭遇 403 ({e})，自動切換至安全介紹頁降級備援...")

    # 2. 安全降級：當 API 被擋，改爬絕對不會被 403 的活動介紹網頁
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        if event_id:
            raw_debug_cache[event_id] = resp.text
            
        result = {}
        ticket_rows = soup.select(".tickets table tbody tr")
        
        if ticket_rows:
            page_text = soup.get_text()
            
