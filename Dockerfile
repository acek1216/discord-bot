# Pythonの公式イメージをベースにする
FROM python:3.11-slim

# 環境変数を設定
ENV APP_HOME /app
ENV LANG C.UTF-8
WORKDIR $APP_HOME

# 最初にライブラリをインストール
COPY requirements.txt .
# Gunicorn/Flaskを削除し、モダンなサーバー(FastAPI, Uvicorn)を追加
RUN pip install --no-cache-dir -r requirements.txt fastapi "uvicorn[standard]"

# アプリケーションのコードをコンテナにコピーします
COPY bot.py .

# コンテナ起動時にUvicornを実行します
# Command to run the application
CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8080"]
