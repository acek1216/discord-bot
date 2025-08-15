from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running"

if __name__ == "__main__":
    from bot import run_bot
    import threading

    # Discord Bot を別スレッドで実行
    threading.Thread(target=run_bot).start()

    # Flask サーバ起動（Cloud Runのポート）
    app.run(host="0.0.0.0", port=8080)
