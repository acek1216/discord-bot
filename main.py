from flask import Flask
import os
import threading

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

if __name__ == "__main__":
    from bot import run_bot

    # Discord Bot を別スレッドで実行
    threading.Thread(target=run_bot).start()

    # Flask サーバ起動（Cloud RunのPORT環境変数に対応）
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

