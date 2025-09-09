from dotenv import load_dotenv
load_dotenv()

# --- 標準ライブラリ ---
import asyncio
import os
import sys
import io

# --- 外部ライブラリ ---
from fastapi import FastAPI
import uvicorn
import discord
from discord.ext import commands
import google.generativeai as genai
from mistralai.async_client import MistralAsyncClient
from notion_client import Client
from openai import AsyncOpenAI
import vertexai
# 修正: 正しいクラス名をインポート
from vertexai.generative_models import GenerativeModel

# --- 自作モジュール ---
import utils
import notion_utils

# --- 初期設定 ---
os.environ.setdefault("LANG", "C.UTF-8")

# --- 環境変数の読み込み ---
def get_env_variable(var_name: str, is_secret: bool = True) -> str:
    value = os.getenv(var_name)
    if not value:
        print(f"🚨 致命的なエラー: 環境変数 '{var_name}' が設定されていません。")
        sys.exit(1)
    return value

DISCORD_TOKEN = get_env_variable("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = get_env_variable("OPENAI_API_KEY")
GEMINI_API_KEY = get_env_variable("GEMINI_API_KEY")
PERPLEXITY_API_KEY = get_env_variable("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = get_env_variable("MISTRAL_API_KEY")
NOTION_API_KEY = get_env_variable("NOTION_API_KEY")
GROK_API_KEY = get_env_variable("GROK_API_KEY")
ADMIN_USER_ID = get_env_variable("ADMIN_USER_ID", is_secret=False)
GUILD_ID = os.getenv("GUILD_ID", "").strip()
OPENROUTER_API_KEY = get_env_variable("CLOUD_API_KEY")

# --- FastAPIとDiscord Botの準備 ---
app = FastAPI()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FastAPIのエンドポイント ---
@app.get("/")
def health_check():
    return {"status": "ok", "bot_is_connected": bot.is_ready()}

# --- Botの起動とcogsの読み込み ---
@bot.event
async def on_ready():
    print(f"✅ Login successful: {bot.user}")
    try:
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py") and not filename.startswith("_"):
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"✅ Cog loaded: {filename}")

        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild_obj)
            cmds = await bot.tree.sync(guild=guild_obj)
            print(f"✅ Synced {len(cmds)} guild commands to {GUILD_ID}")
        else:
            cmds = await bot.tree.sync()
            print(f"✅ Synced {len(cmds)} global commands")
    except Exception as e:
        print(f"🚨 FATAL ERROR on ready/sync: {e}")
        import traceback
        traceback.print_exc()

@app.on_event("startup")
async def startup_event():
    print("🤖 Initializing API clients and bot state...")
    try:
        # APIクライアントとキーをbotインスタンスに格納
        bot.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        bot.mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
        notion_utils.notion = Client(auth=NOTION_API_KEY)
        genai.configure(api_key=GEMINI_API_KEY)
        bot.perplexity_api_key = PERPLEXITY_API_KEY
        bot.openrouter_api_key = OPENROUTER_API_KEY
        bot.grok_api_key = GROK_API_KEY

        # メモリ管理用の変数をbotインスタンスに格納
        bot.gpt_base_memory, bot.gemini_base_memory, bot.mistral_base_memory = {}, {}, {}
        bot.claude_base_memory, bot.llama_base_memory, bot.grok_base_memory = {}, {}, {}
        bot.gpt_thread_memory, bot.gemini_thread_memory, bot.perplexity_thread_memory = {}, {}, {}
        bot.processing_channels = set()
        
        # 定数もbotインスタンスに格納
        bot.ADMIN_USER_ID = ADMIN_USER_ID
        bot.GUILD_ID = GUILD_ID

        # Llamaモデルの初期化
        bot.llama_model = None
        try:
            vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
            bot.llama_model = GenerativeModel("Llama-3.3-70B")
            print("✅ Vertex AI initialized successfully.")
        except Exception as e:
            print(f"🚨 Vertex AI init failed: {e}")

        asyncio.create_task(bot.start(DISCORD_TOKEN))
        print("✅ Discord Bot startup task has been created.")

    except Exception as e:
        print(f"🚨🚨🚨 FATAL ERROR during startup event: {e} 🚨🚨🚨")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)