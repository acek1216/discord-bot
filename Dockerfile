# Python 3.10 の軽量イメージをベースにする
FROM python:3.10-slim

# 必要なシステムパッケージをインストール
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリを設定
WORKDIR /app

# pipをアップグレード
RUN pip install --upgrade pip

# 必要なライブラリをインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# プロジェクトの全てのファイルをコンテナにコピー
COPY . .

# ポートを公開
EXPOSE 8080

# 修正箇所：コンテナが起動したら、このコマンドを実行する
CMD ["python", "bot.py"]