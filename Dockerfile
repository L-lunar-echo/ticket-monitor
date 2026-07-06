# 用微軟官方的 Playwright 映像檔,裡面已經裝好 Chromium 跟所有系統相依套件
# 不需要自己在 build 階段跑 playwright install --with-deps
FROM mcr.microsoft.com/playwright/python:v1.45.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render 會用環境變數 PORT 指定要監聽的埠號,這裡給預設值 10000
ENV PORT=10000
EXPOSE 10000

CMD gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT
