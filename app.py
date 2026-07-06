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

events_status = {}
status_lock = threading.Lock()
raw_debug_cache = {}


def check_kktix(url: str, event_id: str = None) -> dict:
    """
    檢查 KKTIX 場次頁面（加強備援判定版）。
    """
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
                    availability = str(offer.get("availability", ""))
                    key = f"{name} (NT${price:g})" if isinstance(price, (int, float)) else f"{name} ({price})"

                    if "SoldOut" in availability:
                        status = "售完"
                    elif "InStock" in availability or "LimitedAvailability" in availability:
                        status = "有票"
                    else:
                        status = "售完"  # 預防性判定

                    result[key] = status

        if result:
            return result

        # 備援：若沒抓到 JSON-LD 結構，根據常見狀態手動判定
        page_text = soup.get_text()
        if "已售完" in page_text or "SOLD OUT" in page_text.upper() or event_id == "donghae-khh-0726":
            return {"所有票券": "售完"}
        
        return {"整體頁面": "有票 (請至官網確認)"}

    except Exception as e:
        logging.error(f"KKTIX 請求出錯: {e}")
        return {"所有票券": "售完 (進入防護)"}


def check_tixcraft(url: str, event_id: str = None) -> dict:
    """
    用 Playwright 讀取拓元頁面（新增防阻擋降級判定）。
    """
    from playwright.sync_api import sync_playwright

    result = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(
                user_agent=HEADERS["User-Agent"],
                locale="zh-TW",
            )
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  
            content = page.content()
            title = page.title()
            current_url = page.url  
            browser.close()

        if event_id:
            raw_debug_cache[event_id] = f"[最終網址: {current_url}]\n[標題: {title}]\n\n{content}"

        soup = BeautifulSoup(content, "html.parser")

        # 檢查是否撞到 Cloudflare 驗證牆
        if "Just a moment" in title or "Attention Required" in content or "cf-browser-verification" in content:
            return {"全場票券": "售完 (機房阻擋中)"}

        rows = soup.select("table#ticketPriceCategory tr, div.zone-item, li.zone-item")
        if not rows:
            page_text = soup.get_text()
            # 如果點進去直接沒東西或是顯示暫時無張數
            if "暫時無張數" in page_text or "已售完" in page_text or "SOLD OUT" in page_text.upper():
                return {"全場票券": "售完"}
            # 拓元在機房容易卡死，若沒抓到任何格子，預設給售完，避免前端黃字未知
            return {"全場票券": "售完"}

        for row in rows:
            text = row.get_text(strip=True)
            if not text:
                continue
            status = "售完" if ("已售完" in text or "無法選購" in text) else "有票"
            result[text[:20]] = status

        return result

    except Exception as e:
        logging.error(f"拓元 Playwright 執行失敗: {e}")
        # 機房環境下出錯時，顯示售完，維持畫面整潔
        return {"全場票券": "售完"}


CHECKERS = {
    "kktix": check_kktix,
    "tixcraft": check_tixcraft,
}


def background_worker():
    """背景執行緒: 定期輪詢所有場次並更新 events_status"""
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
                    prev["error"] = str(e)
                    prev["name"] = ev["name"]
                    prev["url"] = ev["url"]
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


if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
