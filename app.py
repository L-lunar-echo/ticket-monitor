import os
import time
import random
import logging
import threading
import re
from datetime import datetime

from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# ---------- 1. 場次設定 ----------
EVENTS = [
    {
        "id": "tixcraft-mayday-test",
        "platform": "tixcraft",
        "name": "｜測試｜",
        "url": "https://tixcraft.com/ticket/area/26_maydaytp/22480",
    },
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

# ⚙️ 密集自動循環間隔：一輪跑完後，只休息 3~7 秒就立刻自動重啟下一輪重新整理
CHECK_INTERVAL_MIN = 3
CHECK_INTERVAL_MAX = 7

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

events_status = {}
status_lock = threading.Lock()

def clean_and_parse_status(text_content: str) -> str:
    """精準清洗票池張數文字"""
    if any(k in text_content for k in ["售完", "無法選購", "🔒", "Closed"]):
        return "已售完"
    
    digits = re.findall(r'\d+', text_content)
    if digits:
        return f"剩餘 {digits[0]} 張"
        
    return "有票可買"


def monitor_with_playwright():
    """全自動、無間斷的票池背景監控核心執行緒"""
    from playwright.sync_api import sync_playwright
    
    logging.info("[自動化啟動] 正在初始化持久化瀏覽器核心...")
    
    with sync_playwright() as p:
        profile_dir = os.path.join(os.getcwd(), "browser_profile")
        
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,  # 必須保持打開視窗，以便保持登入 Session 狀態
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            no_viewport=True
        )
        
        page = context.new_page()
        page.set_extra_http_headers({"User-Agent": USER_AGENT})
        
        logging.info("【重要提示】瀏覽器已啟動。請確保已在視窗內登入售票會員。程式即將進入『全自動無限循環監控模式』...")
        page.goto("https://tixcraft.com/user/login")
        page.wait_for_timeout(4000) 
        
        # 進入全自動無限死迴圈
        while True:
            for ev in EVENTS:
                logging.info(f"🔄 [全自動監控中] 正在刷新並讀取票池：{ev['name']} ...")
                result = {}
                
                try:
                    # 強制跳轉，等同於對該選區頁面自動按 F5 重新整理
                    page.goto(ev["url"], timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1200)  # 微幅等待防截圖或防載入延遲
                    
                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    
                    # 依平台精準解析當前所有選區的最新狀態
                    if ev["platform"] == "tixcraft":
                        rows = soup.select("table#ticketPriceCategory tr, div.zone-item, li.zone-item")
                        for row in rows:
                            text = row.get_text(strip=True)
                            if not text or "區" not in text: continue
                            zone_name = text.split("(")[0].split("NT$")[0].strip()
                            result[zone_name] = clean_and_parse_status(text)
                            
                    elif ev["platform"] == "ibon":
                        table_rows = soup.select("table tr")
                        for row in table_rows:
                            tds = [td.get_text(strip=True) for td in row.find_all("td")]
                            if len(tds) >= 2 and any(k in tds[0] for k in ["區", "樓"]):
                                zone_name = tds[0]
                                result[zone_name] = clean_and_parse_status(" ".join(tds))
                                
                    elif ev["platform"] == "kktix":
                        items = soup.select("div.ticket-reg-form li, ul.tickets li")
                        for item in items:
                            text = item.get_text(strip=True)
                            if text:
                                zone_name = text.split("NT$")[0].strip()
                                result[zone_name] = clean_and_parse_status(text)
                    
                    # 只要抓到有效票池，立即寫入全域快取鎖，前端 15 秒更新時就能立刻看到
                    if result:
                        with status_lock:
                            events_status[ev["id"]] = {
                                "name": ev["name"], 
                                "url": ev["url"], 
                                "platform": ev["platform"],
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "tickets": result, 
                                "error": None,
                            }
                        logging.info(f"✅ [狀態更新成功] {ev['name']} -> 最新的選區資料已同步到記憶體快取。")
                    
                except Exception as e:
                    logging.error(f"❌ [監控突發異常] {ev['name']} 發生錯誤: {e}，自動跳過本輪，保留上次成功的數據。")
                
                # 場次和場次之間微調休息，避免因為切換網頁太神速而被售票系統防火牆風控
                page.wait_for_timeout(1000)
            
            # 整輪全部巡邏完完畢，休息個 3~7 秒，立刻重啟下一輪大巡邏
            sleep_time = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
            logging.info(f"⏳ [一輪巡邏完畢] 背景微調休息 {sleep_time} 秒，即將自動重刷下一輪票池...")
            time.sleep(sleep_time)


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

# 初始化預設狀態
for ev in EVENTS:
    events_status[ev["id"]] = {
        "name": ev["name"], "url": ev["url"], "platform": ev["platform"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tickets": {"自動監控中": "請稍候首次刷新..."}, "error": None
    }

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    # 確保自動監控核心在獨立執行緒背景 24 小時不斷線運作
    threading.Thread(target=monitor_with_playwright, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
    
