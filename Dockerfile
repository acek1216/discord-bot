# Python 3.11 の軽量イメージをベースにする
FROM python:3.11-slim

# 作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリをインストールするためのファイルをコピー
COPY requirements.txt .

# requirements.txt に書かれたライブラリをインストール
# --no-cache-dir オプションでイメージサイズを削減
RUN pip install --no-cache-dir -r requirements.txt

# プロジェクトの全てのファイルをコンテナにコピー
COPY . .

# Cloud Runがコンテナを起動する際に実行するコマンド
# bot.pyの中のFastAPIアプリ(app)をUvicornで起動する
# Uvicornがbot.pyを正しく見つけられるよう、pythonのモジュールパスを指定
CMD ["python", "-m", "uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080"]
