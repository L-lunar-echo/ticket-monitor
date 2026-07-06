import os
import time
import random
import logging
import threading
import re
import sys
from datetime import datetime

from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# 如果在 Windows 系統，導入 winsound 發出警報聲
if sys.platform == "win32":
    import winsound
else:
    winsound = None

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

# 🚨 全自動密集監控間隔 (秒)：設為 5 ~ 10 秒隨機，模擬真人重新整理，防止被封鎖
CHECK_INTERVAL_MIN = 5
CHECK_INTERVAL_MAX = 10

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

events_status = {}
status_lock = threading.Lock()

def trigger_auto_alarm(event_name, zone_details):
    """【自動化核心】當發現有票時，後端主動執行的自動警報"""
    logging.info(f"🚨🚨🚨 [發現釋票!!!] {event_name} -> {zone_details}")
    
    # 讓電腦主動發出嗶嗶聲 (Windows 適用)
    if winsound:
        for _ in range(5):
            winsound.Beep(1000, 500) # 頻率 1000Hz，持續 0.5 秒
    else:
        # Mac / Linux 終端機蜂鳴聲
        for _ in range(5):
            sys.stdout.write('\a')
            sys.stdout.flush()
            time.sleep(0.2)

def clean_and_parse_status(text_content: str) -> str:
    if any(k in text_content for k in ["售完", "無法選購", "🔒", "Closed"]):
        return "已售完"
    
    digits = re.findall(r'\d+', text_content)
    if digits:
        return f"剩餘 {digits[0]} 張"
        
    return "有票可買"


def monitor_with_playwright():
    """全自動後端輪詢監控核心"""
    from playwright.sync_api import sync_playwright
    
    logging.info("[自動監控] 正在啟動自動化無痕瀏覽器...")
    
    with sync_playwright() as p:
        profile_dir = os.path.join(os.getcwd(), "browser_profile")
        
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,  # 保持打開瀏覽器，方便你確認它有在自動刷頁面
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            no_viewport=True
        )
        
        page = context.new_page()
        page.set_extra_http_headers({"User-Agent": USER_AGENT})
        
        logging.info("【重要提示】請在彈出的 Chrome 視窗中完成登入。5 秒後開始全自動背景監控...")
        page.goto("https://tixcraft.com/user/login")
        page.wait_for_timeout(5000) 
        
        while True:
            for ev in EVENTS:
                logging.info(f"[自動監控] 正在刷新：{ev['name']} ...")
                result = {}
                
                try:
                    # 每次都強制連過去刷新頁面
                    page.goto(ev["url"], timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)  # 稍微等待元件渲染
                    
                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    
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
                    
                    if result:
                        # 檢查是否有任何一區不是「已售完」
                        available_zones = [f"{z}({status})" for z, status in result.items() if status != "已售完"]
                        if available_zones:
                            # 🎯 抓到了！直接觸發後端自動警報
                            trigger_auto_alarm(ev["name"], ", ".join(available_zones))
                        
                        with status_lock:
                            events_status[ev["id"]] = {
                                "name": ev["name"], "url": ev["url"], "platform": ev["platform"],
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "tickets": result, "error": None,
                            }
                    
                except Exception as e:
                    logging.error(f"[監控異常] {ev['name']} 錯誤: {e}")
                
                # 每個場次切換之間微幅休息，避免操作太密被偵測
                page.wait_for_timeout(1000)
            
            # 全跑完一輪後，隨機休息 5~10 秒，緊接著自動跑下一輪重新整理
            sleep_time = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
            logging.info(f"⏳ 全自動監控完畢。背景等待 {sleep_time} 秒後自動重刷下一輪...")
            time.sleep(sleep_time)


app = Flask(__name__)

@app.route("/")
def index():
    with status_lock: data = dict(events_status)
    return render_template("index.html", events=data)

@app.route("/api/status")
def api_status():
    with status_lock: data = dict(events_status)
    return jsonify(data)

# 初始化快取
for ev in EVENTS:
    events_status[ev["id"]] = {
        "name": ev["name"], "url": ev["url"], "platform": ev["platform"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tickets": {"確認中...": "請稍候"}, "error": None
    }

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    threading.Thread(target=monitor_with_playwright, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
    
