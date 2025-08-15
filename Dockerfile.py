# 1. ベースイメージの指定
# Python 3.9のスリムバージョンをベースにします。軽量でオススメです。
FROM python:3.9-slim

# 2. 環境変数の設定
# これを設定しておくと、Pythonのログが即座に出力されるようになります。
ENV PYTHONUNBUFFERED True

# 3. コンテナ内の作業ディレクトリを作成
WORKDIR /app

# 4. 依存ライブラリのインストール
# まずrequirements.txtだけをコピーして、ライブラリをインストールします。
# こうすることで、コードを変更しただけの再ビルドが高速になります。
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. アプリケーションコードのコピー
# プロジェクトの全てのファイルをコンテナにコピーします。
COPY . .

# 6. コンテナ実行コマンド
# Cloud Runからのリクエストを待ち受けるために、Flaskアプリを起動します。
# bot.pyの中でFlaskアプリが 'app' という名前で定義されていると仮定しています。
# GunicornというWebサーバーを使って、8080ポートで起動します。
CMD exec gunicorn --bind :8080 --workers 1 --threads 8 --timeout 0 "bot:app"