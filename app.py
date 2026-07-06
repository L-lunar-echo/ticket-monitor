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

# 純 KKTIX 爬蟲負擔較小，可以把檢查間隔適度縮短（例如 30 ~ 60 秒），若想維持原樣也可以改回 120 ~ 180
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
    檢查 KKTIX 場次頁面。
    優先嘗試 JSON-LD，若失敗則改用 HTML 表格精準備援。
    """
    import json

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    if event_id:
        raw_debug_cache[event_id] = resp.text

    result = {}

    # 1. 優先使用 JSON-LD 結構化資料
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
                    status = f"未知狀態({availability})"

                result[key] = status

    if result:
        return result

    # 2. 精準備援: 找不到 JSON-LD 就解析 HTML 表格結構
    ticket_rows = soup.select(".tickets table tbody tr")
    if ticket_rows:
        page_text = soup.get_text()
        is_all_sold_out = "已售完" in page_text or "SOLD OUT" in page_text.upper()
        
        for row in ticket_rows:
            name_td = row.select_one("td.name")
            if not name_td:
                continue
            
            # 使用分隔符切開，只取第一段以避開下方福利文字干擾
            name = name_td.get_text(separator="|", strip=True).split("|")[0]
            
            # 提取售價
            price_el = row.select_one("td.price .currency-value")
            price = price_el.get_text(strip=True) if price_el else "未知"
            
            # 組合出不重複的 key
            key = f"{name} (NT${price})"
            result[key] = "售完" if is_all_sold_out else "有票"

    if result:
        return result

    # 3. 終極備援: 萬一連表格都改版找不到
    page_text = soup.get_text()
    status = "售完" if "已售完" in page_text else "未知(需確認頁面結構)"
    result["整體頁面"] = status
    return result


CHECKERS = {
    "kktix": check_kktix,
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
