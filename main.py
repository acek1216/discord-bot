import threading
from flask import Flask
import os

# Flaskアプリの生成
app = Flask(__name__)

# --- Bot起動を管理するためのグローバル変数 ---
bot_thread = None
bot_startup_lock = threading.Lock()

def run_discord_bot():
    """Botのロジックをインポートし、実行する関数"""
    print("🤖 Importing bot application logic...")
    # 'bot.py' という名前のファイルをインポートします
    import bot
    print("▶️ Starting bot...")
    bot.start()

@app.route("/")
def index():
    """ヘルスチェック用エンドポイント。初回アクセス時にBotを起動する。"""
    global bot_thread
    with bot_startup_lock:
        if bot_thread is None:
            bot_thread = threading.Thread(target=run_discord_bot, daemon=True)
            bot_thread.start()
            print("🚀 Kicked off Discord Bot thread by the first request.")
    return "ok"

# ローカル実行時のためのコード
if __name__ == "__main__":
    print("🚀 Starting Flask + Discord bot (local)...")
    index() # Bot起動をトリガー
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
