from flask import Flask
import threading
from bot import run_bot

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running!"

if __name__ == "__main__":
    # Discord Bot を別スレッドで起動
    threading.Thread(target=run_bot).start()

    # Flask をPORT=8080で起動（Cloud Run 要件）
    app.run(host="0.0.0.0", port=8080)
