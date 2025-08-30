# Pythonの公式イメージをベースにする
FROM python:3.11-slim

# 環境変数を設定
ENV APP_HOME /app
ENV LANG C.UTF-8
WORKDIR $APP_HOME

# 最初にライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションのコードをコンテナにコピーします
COPY main.py .
COPY bot.py .

# コンテナ起動時にGunicornを実行します
CMD exec gunicorn --bind :$PORT --workers 1 --threads 1 --timeout 0 main:app
