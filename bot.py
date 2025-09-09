# bot.py (推奨される修正版)
import asyncio
import os
import traceback
import discord
from discord.ext import commands
from fastapi import FastAPI
import uvicorn
from notion_client import Client
import vertexai
from dotenv import load_dotenv
from vertexai.generative_models import GenerativeModel
import ai_clients
import notion_utils

# --- 初期設定 ---
load_dotenv()
os.environ.setdefault("LANG", "C.UTF-8")

# --- FastAPIとDiscord Botの準備 ---
app = FastAPI()
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- ヘルスチェック用エンドポイント ---
@app.get("/")
def health_check():
    return {"status": "ok", "bot_is_connected": bot.is_ready()}

# --- Botのセットアップ関数を新設 ---
async def setup_bot():
    """全ての初期化とCogの読み込みを行う"""
    print("--- Botセットアップ開始 ---")
    try:
        # APIクライアント初期化
        print("⏳ APIクライアントを初期化中...")
        ai_clients.initialize_clients()
        notion_utils.notion = Client(auth=os.getenv("NOTION_API_KEY"))
        print("✅ APIクライアント初期化完了。")

        # Vertex AI初期化
        print("⏳ Vertex AIを初期化中...")
        vertexai.init(project=os.getenv("GCP_PROJECT_ID"), location=os.getenv("GCP_LOCATION", "us-central1"))
        ai_clients.set_llama_model(GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas"))
        print("✅ Vertex AI初期化完了。")

        # Cogs読み込み
        print("⏳ 機能モジュール (Cogs) を読み込み中...")
        # commands.pyを先に読み込むように変更
        cogs_to_load = ["cogs.commands", "cogs.message_handler", "cogs.test_cog"]
        for cog in cogs_to_load:
            try:
                await bot.load_extension(cog)
                print(f"  ➡️ `{cog}` を読み込みました。")
            except Exception:
                print(f"❌ `{cog}` の読み込み中にエラーが発生しました:")
                traceback.print_exc()
        print("✅ 全てのCogs読み込み完了。")

    except Exception as e:
        print(f"❌ セットアップ中に致命的なエラーが発生しました:\n{traceback.format_exc()}")
        raise e # エラーが発生したら起動を中断

# --- on_readyイベントは同期と通知に専念 ---
@bot.event
async def on_ready():
    diag_channel = None
    diag_channel_id_str = os.getenv("DIAGNOSTIC_CHANNEL_ID")
    if diag_channel_id_str and diag_channel_id_str.isdigit():
        diag_channel = bot.get_channel(int(diag_channel_id_str))

    async def send_diag(message):
        if diag_channel:
            await diag_channel.send(message)
        print(message)

    await send_diag("--- 起動シーケンス開始 ---")
    await send_diag(f"✅ Discordにログイン成功: **{bot.user}**")

    try:
        guild_id_str = os.getenv("GUILD_ID", "").strip()
        if guild_id_str and guild_id_str.isdigit():
            target_guild_id = int(guild_id_str)
            guild_obj = discord.Object(id=target_guild_id)
            await send_diag(f"⏳ スラッシュコマンドをギルド `{target_guild_id}` に同期します...")
            # 既存のコマンドを一度クリアしてから同期する
            await bot.tree.clear_commands(guild=guild_obj)
            synced_commands = await bot.tree.sync(guild=guild_obj)
            await send_diag(f"✅ **同期成功！** `{len(synced_commands)}`個のコマンドがDiscordに登録されました。")
            command_names = [cmd.name for cmd in synced_commands]
            await send_diag(f"登録されたコマンド: `{'`, `'.join(command_names)}`")
        else:
            await send_diag("⚠️ **警告:** GUILD_IDが設定されていません。グローバル同期を試みます。")
            # 既存のコマンドを一度クリアしてから同期する
            await bot.tree.clear_commands(guild=None)
            synced_commands = await bot.tree.sync()
            await send_diag(f"✅ グローバル同期成功！`{len(synced_commands)}`個のコマンドがDiscordに登録されました。")


    except Exception as e:
        await send_diag(f"❌ **同期中にエラーが発生しました:**\n```py\n{traceback.format_exc()}\n```")

    await send_diag("--- 🚀 Bot起動完了 ---")


# --- メインの起動ロジック ---
@app.on_event("startup")
async def startup_event():
    DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not DISCORD_TOKEN:
        print("致命的エラー: DISCORD_BOT_TOKENがありません。")
        return

    # Botの実行前にセットアップを完了させる
    await setup_bot()
    asyncio.create_task(bot.start(DISCORD_TOKEN))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
