import os
import time
import random
import logging
import threading
import re
from datetime import datetime

from bs4 import BeautifulSoup
from flask import Flask, render_template, jsonify

# ---------- 1. 場次設定（請確保這些 URL 是點進去後的「選區頁面」網址） ----------
# 提示：如果是拓元，網址通常長得像 .../ticket/area/...
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

# 監控間隔：內部選區抓取為了安全，將頻率稍微拉長，避免頻繁刷頁面被鎖
CHECK_INTERVAL_MIN = 120
CHECK_INTERVAL_MAX = 180

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

events_status = {}
status_lock = threading.Lock()

# ---------- 2. 初始化防禦備援原始清單 ----------
MAYDAY_TEST_FALLBACK_SEATS = {"瘋狂世界 搖滾B2區4525": "剩餘 4 張", "B1看台104區4225": "剩餘 2 張", "B1看台119區4225": "已售完"}
HENRY_FALLBACK_SEATS = {"M&G + SOUNDCHECK PACKAGE": "已售完", "SOUNDCHECK PACKAGE": "已售完", "一般站區 GA": "已售完"}
AESPA_FALLBACK_SEATS = {"B2層002區 $7880": "已售完", "B1看台103區 $6880": "已售完"}
BTS_FALLBACK_SEATS = {"A1區 $9380": "已售完"}
DONGHAE_FALLBACK_SEATS = {"全票 $6,280": "已售完"}
FTISLAND_FALLBACK_SEATS = {"特A區 $6580": "已售完"}

# ---------- 3. 核心精準張數過濾與清洗邏輯 ----------
def clean_and_parse_status(text_content: str) -> str:
    """
    根據傳入的網頁區塊文字，精準抓取張數。
    1. 含有『售完』、『無法選購』 -> 返回『已售完』
    2. 含有數字（例如 剩餘 5 張、或是 ibon 表格裡的純數字 12） -> 返回『剩餘 X 張』
    3. 什麼都沒有但非售完 -> 預設返回『有票可買』
    """
    if any(k in text_content for k in ["售完", "無法選購", "🔒", "Closed"]):
        return "已售完"
    
    # 尋找文字中的數字
    digits = re.findall(r'\d+', text_content)
    if digits:
        return f"剩餘 {digits[0]} 張"
        
    return "有票可買"


def monitor_with_playwright():
    """使用單一持久化瀏覽器視窗，依序輪詢所有場次選區頁面"""
    from playwright.sync_api import sync_playwright
    
    logging.info("[系統啟動] 正在初始化自動化瀏覽器...")
    
    with sync_playwright() as p:
        # 建立本地瀏覽器暫存資料夾，自動儲存登入 Cookie
        profile_dir = os.path.join(os.getcwd(), "browser_profile")
        
        context = p.chromium.launch_persistent_context(
            profile_dir,
            headless=False,  # ⚠️ 必須為 False，這樣才會彈出視窗讓你手動登入！
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            no_viewport=True
        )
        
        page = context.new_page()
        page.set_extra_http_headers({"User-Agent": USER_AGENT})
        
        # 第一次啟動時，先開啟拓元首頁，方便你手動登入
        logging.info("【提示】瀏覽器已開啟。如果是第一次運行，請在彈出的視窗中完成售票系統會員登入。")
        page.goto("https://tixcraft.com/user/login")
        page.wait_for_timeout(5000) # 給你 5 秒反應時間
        
        while True:
            for ev in EVENTS:
                logging.info(f"[進行監測] 正在掃描場次：{ev['name']} ...")
                result = {}
                
                try:
                    # 前往該場次的內部選區網址
                    page.goto(ev["url"], timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)  # 等待網頁元件載入
                    
                    content = page.content()
                    soup = BeautifulSoup(content, "html.parser")
                    
                    # 判斷平台並精準解析內部張數
                    if ev["platform"] == "tixcraft":
                        # 拓元選區按鈕結構通常在 table#ticketPriceCategory 裡的 a 標籤
                        rows = soup.select("table#ticketPriceCategory tr, div.zone-item, li.zone-item")
                        for row in rows:
                            text = row.get_text(strip=True)
                            if not text or "區" not in text: continue
                            
                            # 提取區域名稱 (去除後方括號)
                            zone_name = text.split("(")[0].split("NT$")[0].strip()
                            result[zone_name[:30]] = clean_and_parse_status(text)
                            
                    elif ev["platform"] == "ibon":
                        # ibon 內部選區是一個表格，包含 區域名稱欄、剩餘張數欄
                        table_rows = soup.select("table tr")
                        for row in table_rows:
                            tds = [td.get_text(strip=True) for td in row.find_all("td")]
                            if len(tds) >= 2 and any(k in tds[0] for k in ["區", "樓"]):
                                zone_name = tds[0]
                                # 把整列文字丟進去解析看有沒有剩餘張數數字
                                full_row_text = " ".join(tds)
                                result[zone_name[:30]] = clean_and_parse_status(full_row_text)
                                
                    elif ev["platform"] == "kktix":
                        # KKTIX 內部選區通常由 <li> 組成
                        items = soup.select("div.ticket-reg-form li, ul.tickets li")
                        for item in items:
                            text = item.get_text(strip=True)
                            if text:
                                zone_name = text.split("NT$")[0].strip()
                                result[zone_name[:30]] = clean_and_parse_status(text)
                    
                    # 如果成功抓到網頁內部選區資料，就更新狀態
                    if result:
                        with status_lock:
                            events_status[ev["id"]] = {
                                "name": ev["name"], "url": ev["url"],
                                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "tickets": result, "error": None,
                            }
                        logging.info(f"[掃描成功] {ev['name']}: {result}")
                    else:
                        raise Exception("未能成功解析到選區列表，可能需要手動通過驗證碼或登入")
                        
                except Exception as e:
                    logging.error(f"[解析失敗] {ev['name']} 發生錯誤: {e}。將自動倒回安全清單。")
                    # 發生錯誤（如被防火牆擋掉或未登入），自動倒回預設防禦清單
                    fallback = {"tixcraft-mayday-test": MAYDAY_TEST_FALLBACK_SEATS, "donghae-khh-0725": DONGHAE_FALLBACK_SEATS,
                                "donghae-khh-0726": DONGHAE_FALLBACK_SEATS, "tixcraft-aespa-taipei": AESPA_FALLBACK_SEATS,
                                "ibon-current-event": FTISLAND_FALLBACK_SEATS, "henry-moodie-khh": HENRY_FALLBACK_SEATS,
                                "tixcraft-bts-1119": BTS_FALLBACK_SEATS, "tixcraft-bts-1121": BTS_FALLBACK_SEATS, "tixcraft-bts-1122": BTS_FALLBACK_SEATS}.get(ev["id"], {"全區": "已售完"})
                    
                    with status_lock:
                        events_status[ev["id"]] = {
                            "name": ev["name"], "url": ev["url"],
                            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "tickets": fallback, "error": str(e),
                        }
            
            # 全跑完一輪後，隨機休息再跑下一輪
            sleep_time = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
            logging.info(f"[輪詢結束] 休息 {sleep_time} 秒後進行下一輪精準掃描...")
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

# ---------- 4. 初始快取（一開網頁時的預設值） ----------
for ev_id, fb in [
    ("tixcraft-mayday-test", MAYDAY_TEST_FALLBACK_SEATS), ("donghae-khh-0725", DONGHAE_FALLBACK_SEATS),
    ("donghae-khh-0726", DONGHAE_FALLBACK_SEATS), ("tixcraft-aespa-taipei", AESPA_FALLBACK_SEATS),
    ("ibon-current-event", FTISLAND_FALLBACK_SEATS), ("henry-moodie-khh", HENRY_FALLBACK_SEATS),
    ("tixcraft-bts-1119", BTS_FALLBACK_SEATS), ("tixcraft-bts-1121", BTS_FALLBACK_SEATS), ("tixcraft-bts-1122", BTS_FALLBACK_SEATS)
]:
    target_ev = next(e for e in EVENTS if e["id"] == ev_id)
    events_status[ev_id] = {
        "name": target_ev["name"], "url": target_ev["url"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tickets": fb, "error": None
    }

if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    # 啟動 Playwright 核心監控執行緒
    threading.Thread(target=monitor_with_playwright, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
    
