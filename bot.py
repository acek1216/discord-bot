# bot.py

# --- 標準ライブラリ ---
import asyncio
import io
import os
import sys

# --- 外部ライブラリ ---
import discord
from discord.ext import commands
from fastapi import FastAPI
import uvicorn
from notion_client import Client
import google.generativeai as genai
import vertexai

# --- 自作モジュール ---
from dotenv import load_dotenv
load_dotenv()

import ai_clients
import notion_utils
import utils
import state

# --- UTF-8 出力ガード ---
# (元のコードと同じため変更なし)
os.environ.setdefault("LANG", "C.UTF-8")
# (以下略)

# --- サーバーアプリケーションの準備 ---
app = FastAPI()

# --- 環境変数の読み込み ---
# (get_env_variable と APIキー読み込みは元のコードと同じ)
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

# --- Discord Bot クライアントの準備 ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- ヘルスチェック用エンドポイント ---
@app.get("/")
def health_check():
    """Cloud Runのヘルスチェックに応答するための窓口"""
    return {"status": "ok", "bot_is_connected": bot.is_ready()}

# --- Botイベントハンドラ ---
@bot.event
async def on_ready():
    """Botの準備が完了したときの処理"""
    print("-" * 30)
    print(f"✅ Discordにログインしました: {bot.user} (ID: {bot.user.id})")
    
    # ギルドコマンドの同期
    try:
        if GUILD_ID_STR:
            guild_obj = discord.Object(id=int(GUILD_ID_STR))
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"✅ {len(synced)}個のギルドコマンドをサーバーID {GUILD_ID_STR} に同期しました。")
        else:
            synced = await bot.tree.sync()
            print(f"✅ {len(synced)}個のグローバルコマンドを同期しました。")
    except Exception as e:
        print(f"🚨 コマンドの同期中にエラーが発生しました: {e}")
    
    print("-" * 30)
    print("サーバーが正常に起動し、Botがオンラインになりました。")

# --- メインの起動ロジック ---
async def main():
    """全ての初期化と起動を行うメイン関数"""
    print("🚀 サーバーの起動処理を開始します...")

    # --- 1. APIクライアントの初期化 ---
    print("🤖 APIクライアントを初期化中...")
    ai_clients.initialize_clients()
    notion_utils.notion = Client(auth=os.getenv("NOTION_API_KEY"))
    utils.set_openai_client(ai_clients.openai_client)

    try:
        print("🤖 Vertex AIを初期化中...")
        vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
        llama_model = ai_clients.GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas")
        ai_clients.set_llama_model(llama_model)
        print("✅ Vertex AIが正常に初期化されました。")
    except Exception as e:
        print(f"⚠️ Vertex AIの初期化に失敗しました: {e}")

    # --- 2. Cogsの読み込み ---
    print("📚 機能モジュール (Cogs) を読み込み中...")
    cogs_to_load = ["cogs.commands", "cogs.message_handler"]
    for cog in cogs_to_load:
        await bot.load_extension(cog)
        print(f"  ✅ {cog} を正常に読み込みました。")

    # --- 3. WebサーバーとDiscord Botを並行して起動 ---
    uvicorn_config = uvicorn.Config("bot:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), log_level="info")
    server = uvicorn.Server(uvicorn_config)
    
    # Uvicorn(Webサーバー)とbot.start()(Discord Bot)を一緒に動かす
    await asyncio.gather(
        server.serve(),
        bot.start(DISCORD_TOKEN)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("手動でシャットダウンします。")
