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

# [設定區域維持不變]
# ... (請保留您原有的 EVENTS 設定)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

events_status = {}
status_lock = threading.Lock()
raw_debug_cache = {}

# --- 改進後的爬蟲核心 ---

def fetch_content_with_playwright(url):
    """通用爬蟲引擎：處理所有 JavaScript 動態網頁"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        page.goto(url, timeout=45000, wait_until="networkidle")
        page.wait_for_timeout(5000) # 給予頁面渲染時間
        content = page.content()
        browser.close()
        return content

def check_tixcraft(url, event_id=None):
    try:
        content = fetch_content_with_playwright(url)
        if event_id: raw_debug_cache[event_id] = content
        
        soup = BeautifulSoup(content, "html.parser")
        result = {}
        # 廣泛搜尋：包含 td, li, div 等所有票價相關容器
        for element in soup.select("tr, li, div"):
            text = element.get_text(" ", strip=True)
            # 過濾：只要包含關鍵字且長度合理的文字
            if ("元" in text or "區" in text) and len(text) < 40:
                status = "售完" if any(s in text for s in ["售完", "無法選購", "Sold Out"]) else "有票"
                result[text[:25]] = status
        return result if result else {"查無票券": "售完"}
    except Exception as e:
        logging.error(f"拓元爬蟲錯誤: {e}")
        return {"所有票券": "售完"}

def check_kktix(url, event_id=None):
    # KKTIX 建議直接用 requests 抓 API 或解析 HTML，上面 fetch_content_with_playwright 也適用
    return check_tixcraft(url, event_id) # 暫時共用邏輯

def check_ibon(url, event_id=None):
    return check_tixcraft(url, event_id)

# [其餘結構請保持原樣，並確保 background_worker 正確調用上述函式]
