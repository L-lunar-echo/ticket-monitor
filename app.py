import os
import time
import random
import logging
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 設定
app = Flask(__name__)
events_status = {}
status_lock = threading.Lock()

# 你的場次資料
EVENTS = [
    {"id": "donghae-khh-0725", "platform": "kktix", "name": "[7/25] DONGHAE CONCERT", "url": "https://daydreamerstudio.kktix.cc/events/b14fcf04"},
    {"id": "donghae-khh-0726", "platform": "kktix", "name": "[7/26] DONGHAE CONCERT", "url": "https://daydreamerstudio.kktix.cc/events/cd3b83be"}
]

# 爬蟲函式
def check_kktix(url):
    try:
        import requests
        resp = requests.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        # 這裡根據 KKTIX 結構抓取 (簡化邏輯)
        return {"全區": "有票" if "立即訂購" in resp.text else "售完"}
    except: return {"狀態": "檢查失敗"}

def background_worker():
    while True:
        for ev in EVENTS:
            try:
                # 執行檢查
                tickets = check_kktix(ev["url"])
                with status_lock:
                    events_status[ev["id"]] = {
                        "name": ev["name"],
                        "url": ev["url"],
                        "updated_at": datetime.now().strftime("%H:%M:%S"),
                        "tickets": tickets
                    }
            except Exception as e:
                logging.error(f"爬蟲錯誤: {e}")
        time.sleep(30) # 每 30 秒更新一次

@app.route("/")
def index():
    return render_template("index.html", events=events_status)

@app.route("/api/status")
def api_status():
    return jsonify(events_status)

if __name__ == "__main__":
    threading.Thread(target=background_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
    
