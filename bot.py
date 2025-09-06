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
# .envファイルをロード (最初に行う)
from dotenv import load_dotenv
load_dotenv()

# 各種クライアントの初期化関数や設定関数
import ai_clients
import notion_utils
import utils

# グローバルな状態を管理するモジュール
import state

# --- UTF-8 出力ガード ---
# (元のコードと同じため変更なし)
os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("PYTHONIOENCODING", "UTF-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# --- サーバーアプリケーションの準備 ---
app = FastAPI()

# --- 環境変数の読み込みと必須チェック ---
def get_env_variable(var_name: str, is_secret: bool = True) -> str:
    """環境変数を読み込む。存在しない場合はエラーを発生させる。"""
    value = os.getenv(var_name)
    if not value:
        print(f"🚨 致命的なエラー: 環境変数 '{var_name}' が設定されていません。")
        sys.exit(1)
    # 起動ログを見やすくするため、シークレットでない場合は値を表示
    if is_secret:
        print(f"🔑 環境変数 '{var_name}' を読み込みました (Value: ...{value[-4:]})")
    else:
        print(f"✅ 環境変数 '{var_name}' を読み込みました (Value: {value})")
    return value

# APIキーと設定
DISCORD_TOKEN = get_env_variable("DISCORD_BOT_TOKEN")
GUILD_ID_STR = os.getenv("GUILD_ID", "").strip()
ADMIN_USER_ID = get_env_variable("ADMIN_USER_ID", is_secret=False)

# --- Discord Bot クライアントの準備 ---
intents = discord.Intents.default()
intents.message_content = True
# Cogsを利用するため、discord.Client の代わりに commands.Bot を使用
bot = commands.Bot(command_prefix="/", intents=intents)


# --- FastAPIイベントハンドラ ---

app.on_event("startup")
async def startup_event():
    """サーバー起動時に各種クライアントを初期化し、Botをバックグラウンドで起動する"""
    print("🚀 サーバーの起動処理を開始します...")

    try:
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

        # --- 2. Cogs（機能モジュール）を読み込む関数 ---
        async def load_cogs():
            print("📚 機能モジュール (Cogs) を読み込み中...")
            cogs_to_load = ["cogs.commands", "cogs.message_handler"]
            for cog in cogs_to_load:
                try:
                    await bot.load_extension(cog)
                    print(f"  ✅ {cog} を正常に読み込みました。")
                except Exception as e:
                    print(f"  🚨 {cog} の読み込み中にエラー: {e}")
                    import traceback
                    traceback.print_exc()
        
        # --- 3. Discord Botを起動するメインの非同期タスク ---
        async def start_bot():
            # ▼▼▼【ここが修正点】▼▼▼
            # Botを起動する前に、必ずCogsを読み込む
            await load_cogs()
            await bot.start(DISCORD_TOKEN)
            # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

        asyncio.create_task(start_bot())
        print("✅ Discord Botの起動タスクが作成されました。")

    except Exception as e:
        print(f"🚨🚨🚨 致命的な起動エラーが発生しました: {e} 🚨🚨🚨")
        import traceback
        traceback.print_exc()

@app.get("/")
def health_check():
    """ヘルスチェック用のエンドポイント"""
    return {"status": "ok", "bot_is_connected": bot.is_ready()}

# --- Discord Bot イベントハンドラ ---
# on_messageなどのイベントは cogs/message_handler.py に移動

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


# --- メインの実行ブロック ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    # UvicornでFastAPIアプリを実行
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=True)
