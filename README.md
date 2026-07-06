# 演唱會釋票監控網站 - 部署教學(新手版)

這份教學假設你完全沒架過站,照著步驟做就好。

## 這個網站在做什麼

- 背景會固定每 1~2 分鐘檢查一次 KKTIX 場次的票況
- 網頁顯示目前票況,所有訪客看到的是同一份快取結果,不會因為訪客變多就一直打票務網站
- 目前只做了 KKTIX,拓元/ibon 之後用同樣架構加

## 第一步:把程式碼放上 GitHub

1. 到 https://github.com 註冊帳號(免費)
2. 右上角 `+` -> `New repository`,取名例如 `ticket-monitor`,設為 Public 或 Private 都可以,建立
3. 進到新建立的 repo 頁面,點 `Add file` -> `Upload files`
4. 把這個資料夾裡的所有檔案(`app.py`、`requirements.txt`、`render.yaml`、`templates/index.html`)拖進去上傳
   - 注意 `templates/index.html` 要維持在 `templates` 資料夾裡面,上傳時網頁會自動幫你建資料夾結構
5. 按 `Commit changes`

## 第二步:部署到 Render.com(Docker 版)

因為拓元監控需要瀏覽器環境,這個專案改用 Docker 部署,不用自己裝任何東西,Render 會自動處理:

1. 到 https://render.com 註冊帳號,選擇「用 GitHub 登入」最快
2. 登入後點 `New` -> `Web Service`
3. 選擇剛剛建立的 `ticket-monitor` repo,授權 Render 存取
4. Render 偵測到 repo 裡有 `Dockerfile`,通常會自動把 **Environment / Language** 設成 `Docker`,不需要再填 Build Command / Start Command(這些都寫在 `Dockerfile` 裡了)
   - 如果沒自動偵測到,手動把 Environment 選單改成 `Docker`
5. Instance Type 選 `Free`
6. 點 `Create Web Service`
7. **這次 Build 時間會比較久(10 分鐘以上都正常)**,因為要下載一個內建瀏覽器的完整映像檔,體積比較大,耐心等
8. 完成後 Render 會給你一個網址,例如 `https://ticket-monitor-xxxx.onrender.com`,打開就能看到票況頁面

## 重要限制(新手一定要知道)

- **免費方案會「睡著」**:Render 免費方案在沒人訪問 15 分鐘後會自動休眠,下次有人打開網頁時要等 30~60 秒喚醒,而且睡著期間背景監控也會停止。
  - 如果你想要 24 小時不間斷監控,之後可以升級付費方案(最低約每月 $7 美金),或是另外找一個免費的「定時 ping」服務(例如 UptimeRobot)每 10 分鐘打一次你的網址讓它保持醒著,但這是繞過限制的做法,不是真正的解決方案。
- **`--workers 1` 不要隨便改成更多**:因為背景監控執行緒是跟著 Flask app 一起啟動的,如果開多個 workers 會變成好幾組背景執行緒同時去檢查,加重對票務網站的請求頻率,也可能造成資料不一致。之後如果流量大到需要多個 workers,背景檢查要拆成獨立的排程服務(Render 的 `Cron Job` 或 `Background Worker` 類型),不要跟著網頁 process 綁在一起。
- **拓元需要 Playwright**,Render 免費方案的環境要另外安裝瀏覽器套件,設定會複雜一些,等你 KKTIX 這版跑順了我再幫你加。
- **拓元有 Cloudflare 防護,免費方案很可能不穩定或直接失敗**:Build 時間會拉長到 5~10 分鐘(要下載 Chromium),而且免費方案只有 512MB 記憶體,無頭瀏覽器很吃記憶體,可能出現 Out of Memory 導致服務重啟。如果 Logs 出現 `Worker was sent SIGKILL` 或類似訊息,代表記憶體不夠,這種情況只能靠升級付費方案解決,不是程式碼能修的問題。
- **就算資源夠,拓元的 Cloudflare 也可能直接判定為機器人**,Logs 裡如果看到「被 Cloudflare 阻擋」的訊息,代表這次嘗試沒有通過,這是拓元刻意設計的防護,本工具不會進一步做規避處理。

## 之後要修改內容

- 加新場次:改 `app.py` 裡的 `EVENTS` 清單
- 改版面:改 `templates/index.html`
- 改完後一樣上傳到 GitHub,Render 會自動偵測並重新部署
