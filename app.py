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

# 純 KKTIX API 爬蟲負擔極小，可以保持 30 ~ 60 秒的靈敏頻率
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
    檢查 KKTIX 場次票況。
    直接對 KKTIX 內部的票況 API 進行請求，精準解析「按下一步」才能拿到的即時庫存。
    """
    import json
    import re

    # 1. 從輸入網址提取活動代碼 (slug)
    # 例如: https://daydreamerstudio.kktix.cc/events/cd3b83be -> cd3b83be
    slug = url.split("/events/")[-1].split("?")[0]
    
    # KKTIX 點擊下一步時，後台用來查詢庫存張數的即時 API 網址
    api_url = f"https://kktix.com/g/events/{slug}/register_info"
    
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        
        if event_id:
            raw_debug_cache[event_id] = json.dumps(data, ensure_ascii=False, indent=2)
            
    except Exception as api_err:
        logging.warning(f"KKTIX API 請求失敗，嘗試改用購票頁 HTML 備援: {api_err}")
        # 備援：若直接請求 API 被擋，強攻實體購票頁面中的 window.initData 變數
        reg_url = f"https://kktix.com/events/{slug}/registrations/new"
        resp = requests.get(reg_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        
        if event_id:
            raw_debug_cache[event_id] = resp.text
            
        soup = BeautifulSoup(resp.text, "html.parser")
        result = {}
        
        # 尋找購票頁面內嵌的庫存資料區塊
        match = re.search(r"window\.initData\s*=\s*({.*?});", resp.text, re.DOTALL)
        if match:
            try:
                init_data = json.loads(match.group(1))
                inventory = init_data.get("inventory", {})
                ticket_types = init_data.get("ticketTypes", [])
                for t in ticket_types:
                    name = t.get("name")
                    id_ = str(t.get("id"))
                    price = t.get("price", "0")
                    key = f"{name} (NT${price})"
                    
                    count = inventory.get(id_, 0)
                    result[key] = "有票" if count > 0 else "售完"
                if result:
                    return result
            except Exception as parse_err:
                logging.error(f"備援 initData 解析失敗: {parse_err}")

        # 終極文字備援
        page_text = soup.get_text()
        status = "售完" if "已售完" in page_text or "暫時無張數" in page_text else "有票"
        result["整體頁面"] = status
        return result

    # 2. 順利取得 API 資料，精準分析每種票的庫存張數
    result = {}
    inventory = data.get("inventory", {})  # 各票種的真實剩餘庫存數量，如: {"12345": 0, "67890": 2}
    order_info = data.get("order_info", {})
    ticket_types = order_info.get("ticket_types", [])

    for t in ticket_types:
        name = t.get("name")
        id_ = str(t.get("id"))
        price = t.get("price", "0")
        key = f"{name} (NT${price})"
        
        # 判斷一：是否已被隱藏，或根本不在販售時間內（徹底解決 7/26 的過期/死掉場次誤判）
        if t.get("is_hidden") or not t.get("in_sale_period"):
            result[key] = "售完"
            continue
            
        # 判斷二：檢查真實剩餘庫存張數
        count = inventory.get(id_, 0)
        result[key] = "有票" if count > 0 else "售完"

    if not result:
        # 保險文字降級機制
        page_text = json.dumps(data)
        status = "有票" if '"count":' in page_text and not '"count":0' in page_text else "售完"
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
    
