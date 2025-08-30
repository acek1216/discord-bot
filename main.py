import threading
from flask import Flask
import os
import asyncio

# Flaskアプリの生成
app = Flask(__name__)

# --- Bot起動を管理するためのグローバル変数 ---
bot_thread = None
bot_startup_lock = threading.Lock()
bot_ready_event = threading.Event() # Botの準備完了を待つためのフラグ

def run_discord_bot(ready_event):
    """Botのロジックをインポートし、非同期ループを開始する関数"""
    print("🤖 Importing bot application logic...")
    import bot
    print("▶️ Starting bot's async event loop...")
    try:
        # bot.pyのasync関数を、asyncioで安全に実行します
        asyncio.run(bot.start_async(ready_event))
    except Exception as e:
        print(f"🚨 Bot thread crashed with an exception: {e}")

@app.route("/")
def index():
    """ヘルスチェック用エンドポイント。Botが完全に準備完了するまで待機する。"""
    global bot_thread
    with bot_startup_lock:
        if bot_thread is None:
            # Bot起動スレッドに、準備完了を知らせるためのイベントを渡す
            bot_thread = threading.Thread(target=run_discord_bot, args=(bot_ready_event,), daemon=True)
            bot_thread.start()
            print("🚀 Kicked off Discord Bot thread. Waiting for bot to be ready...")
    
    # Botスレッドが準備完了の合図を出すのを最大60秒間待つ
    is_ready = bot_ready_event.wait(timeout=60)
    
    if is_ready:
        print("✅ Health check successful: Bot is ready.")
        return "ok"
    else:
        print("❌ Health check failed: Bot did not become ready in time.")
        return "Bot is not ready", 503
