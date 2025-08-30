# Pythonの公式イメージをベースにする
FROM python:3.11-slim

# 環境変数を設定
ENV APP_HOME /app
ENV LANG C.UTF-8
WORKDIR $APP_HOME

# 必要なライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 最後のCMD命令を以下のように変更
CMD exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 0 main:app
