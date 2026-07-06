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
# 之後要加拓元/ibon,就在這裡加一筆,並在 CHECKERS 裡對應到解析函式
EVENTS = [
    {
        "id": "donghae-khh-0725",
        "platform": "kktix",
        "name": "DONGHAE 高雄場 7/25",
        # 注意: 用不含 registrations/new 的活動介紹頁,那個購票頁需要先建立訂購 session
        "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04",
    },
    {
        "id": "donghae-khh-0726",
        "platform": "kktix",
        "name": "DONGHAE 高雄場 7/26",
        # 注意: 用不含 registrations/new 的活動介紹頁,那個購票頁需要先建立訂購 session
        "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be",
    },
]

# 拓元用 Playwright 較耗資源,間隔拉長一點,對伺服器跟對方網站都比較友善
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

# 全站共用的快取狀態: { event_id: {"name":..., "url":..., "updated_at":..., "tickets": {票種: 狀態}} }
events_status = {}
status_lock = threading.Lock()

# 除錯用: 存最後一次抓到的原始頁面內容(文字化後),方便用 /debug/<event_id> 查看
raw_debug_cache = {}


def check_kktix(url: str, event_id: str = None) -> dict:
    """
    檢查 KKTIX 場次頁面。
    KKTIX 會在頁面內嵌一段 schema.org 的 JSON-LD 結構化資料,
    裡面的 offers 陣列就是各票種的名稱/價格/availability,比用 CSS class 猜測穩定很多。
    """
    import json

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

        # 有些頁面是單一物件,有些是陣列,統一轉成 list 處理
        candidates = data if isinstance(data, list) else [data]

        for item in candidates:
            if not isinstance(item, dict) or item.get("@type") != "Event":
                continue
            offers = item.get("offers", [])
            for i, offer in enumerate(offers):
                name = offer.get("name", f"票種{i+1}")
                price = offer.get("price", "")
                availability = str(offer.get("availability", ""))
                # 同名票種可能有不同價格(不同梯次),用價格區分開來避免互相覆蓋
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

    # 備援: 找不到 JSON-LD 就退回用整頁文字關鍵字判斷
    page_text = soup.get_text()
    status = "售完" if "已售完" in page_text else "未知(需確認頁面結構)"
    result["整體頁面"] = status
    return result


def check_tixcraft(url: str, event_id: str = None) -> dict:
    """
    用 Playwright 開一個真的無頭瀏覽器讀取拓元頁面。
    注意: 拓元有 Cloudflare 防護,這是誠實的基本嘗試,不保證能穩定通過;
    若持續失敗代表被判定為機器人,不會在這裡做進一步的偽裝/繞過處理。
    """
    from playwright.sync_api import sync_playwright

    result = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="zh-TW",
        )
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)  # 等待可能的 JS 渲染 / Cloudflare 檢查頁
        content = page.content()
        title = page.title()
        current_url = page.url  # 記錄最終網址,若被導向排隊頁/首頁就看得出來
        browser.close()

    if event_id:
        raw_debug_cache[event_id] = f"[最終網址: {current_url}]\n[標題: {title}]\n\n{content}"

    soup = BeautifulSoup(content, "html.parser")

    # 常見的 Cloudflare 檢查頁會有這些關鍵字或標題
    if "Just a moment" in title or "Attention Required" in content or "cf-browser-verification" in content:
        result["整體頁面"] = "被 Cloudflare 阻擋(未通過機器人驗證)"
        return result

    rows = soup.select("table#ticketPriceCategory tr, div.zone-item, li.zone-item")
    if not rows:
        page_text = soup.get_text()
        if "已售完" in page_text or "SOLD OUT" in page_text.upper():
            result["整體頁面"] = "售完"
        else:
            result["整體頁面"] = "未知(頁面結構與預期不同,需人工確認)"
        return result

    for row in rows:
        text = row.get_text(strip=True)
        if not text:
            continue
        status = "售完" if ("已售完" in text or "無法選購" in text) else "有票"
        result[text[:20]] = status

    return result


CHECKERS = {
    "kktix": check_kktix,
    "tixcraft": check_tixcraft,
    # "ibon": check_ibon,           # 之後找到 API 路徑再補上
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
    """給前端 JS 或其他程式輪詢用的 JSON API"""
    with status_lock:
        data = dict(events_status)
    return jsonify(data)


@app.route("/debug/<event_id>")
def debug_page(event_id):
    """
    除錯用: 顯示最後一次實際抓到的原始頁面內容(純文字呈現,方便複製)。
    正式上線給一般人用時建議拿掉這個路由,現在是為了排查 selector 問題先留著。
    """
    html = raw_debug_cache.get(event_id)
    if html is None:
        return f"還沒有 {event_id} 的快取資料,等下一輪背景檢查跑完再試。", 404
    from flask import Response
    return Response(html, mimetype="text/plain; charset=utf-8")


# 啟動背景執行緒(避免 Flask debug reloader 啟動兩次背景執行緒)
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=background_worker, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
