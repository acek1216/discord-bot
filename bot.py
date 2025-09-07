# bot.py (修正版)

# --- ライブラリとモジュールのインポート ---
import asyncio
import os
import sys
import discord
from discord.ext import commands
from fastapi import FastAPI
import uvicorn
from notion_client import Client
import google.generativeai as genai
import vertexai
from dotenv import load_dotenv

# GenerativeModelを直接インポート
from vertexai.generative_models import GenerativeModel

import ai_clients
import notion_utils
import utils
import state

# --- 初期設定 ---
load_dotenv()
os.environ.setdefault("LANG", "C.UTF-8")

# --- FastAPIとDiscord Botの準備 ---
app = FastAPI()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID", "").strip()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- ヘルスチェック用エンドポイント ---
@app.get("/")
def health_check():
    return {"status": "ok", "bot_is_connected": bot.is_ready()}

# --- Botイベントハンドラ ---
@bot.event
async def on_ready():
    print("-" * 30)
    print(f"✅ Discordにログインしました: {bot.user} (ID: {bot.user.id})")
    try:
        if GUILD_ID_STR:
            guild_obj = discord.Object(id=int(GUILD_ID_STR))
            await bot.tree.sync(guild=guild_obj)
            print("✅ スラッシュコマンドをサーバーに同期しました。")
        else:
            await bot.tree.sync()
            print("✅ スラッシュコマンドをグローバルに同期しました。")
        print("-" * 30)
    except Exception as e:
        print(f"❌ スラッシュコマンドの同期に失敗しました: {e}")

@app.on_event("startup")
async def startup_event():
    print("🚀 サーバーの起動処理を開始します...")
    
    try:
        # 1. APIクライアント初期化
        print("🤖 APIクライアントを初期化中...")
        ai_clients.initialize_clients()
        notion_utils.notion = Client(auth=os.getenv("NOTION_API_KEY"))
        utils.set_openai_client(ai_clients.openai_client)

        try:
            print("🤖 Vertex AIを初期化中...")
            vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
            llama_model = GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas")
            ai_clients.set_llama_model(llama_model)
            print("✅ Vertex AIが正常に初期化されました。")
        except Exception as e:
            print(f"⚠️ Vertex AIの初期化に失敗しました: {e}")

        # 2. Cogs読み込み
        print("📚 機能モジュール (Cogs) を読み込み中...")
        cogs_to_load = ["cogs.commands", "cogs.message_handler"]

        for cog in cogs_to_load:
            try:
                await bot.load_extension(cog)
                print(f"  ✅ {cog} を正常に読み込みました。")
            except Exception as e:
                print(f"  ❌ {cog} のロードに失敗しました: {e}")
                import traceback
                traceback.print_exc()
                continue

        # 3. Discord Botをバックグラウンドタスクとして起動
        asyncio.create_task(bot.start(DISCORD_TOKEN))
        print("✅ Discord Botの起動タスクが作成されました。")

    except Exception as e:
        print(f"🚨🚨🚨 致命的な起動エラーが発生しました 🚨🚨🚨")
        import traceback
        traceback.print_exc()

# --- メイン実行部分（Uvicorn用） ---
if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
