# Python 3.11 の軽量イメージをベースにする
FROM python:3.10-slim

# 作業ディレクトリを設定
WORKDIR /app

# 必要なライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# プロジェクトの全てのファイルをコンテナにコピー
COPY . .

# Uvicorn Webサーバーを起動するコマンド
CMD ["python", "-m", "uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]