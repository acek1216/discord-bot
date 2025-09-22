from dotenv import load_dotenv
load_dotenv()

# --- 標準ライブラリ ---
import asyncio
import os
import sys
import io

# --- 外部ライブラリ ---
from fastapi import FastAPI, Request
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
from google.cloud import secretmanager

# --- 自作モジュール ---
import utils
import notion_utils
from config import get_config
from enhanced_memory_manager import get_enhanced_memory_manager

# --- 初期設定 ---
os.environ.setdefault("LANG", "C.UTF-8")

# Secret Manager クライアント
def load_secret(secret_name: str, project_id: str = "stunning-agency-469102-b5") -> str:
    """Google Secret Manager からシークレットを取得"""
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Error loading secret {secret_name}: {e}")
        return os.environ.get(secret_name, "")

# 環境変数をSecret Managerから読み込み
def load_environment_variables():
    """Secret Manager または環境変数から必要な値を読み込み"""
    secrets = [
        "DISCORD_BOT_TOKEN",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "PERPLEXITY_API_KEY",
        "MISTRAL_API_KEY"
    ]

    for secret in secrets:
        if not os.environ.get(secret):
            secret_value = load_secret(secret)
            if secret_value:
                os.environ[secret] = secret_value
                print(f"✅ Loaded {secret} from Secret Manager")
            else:
                print(f"⚠️  Could not load {secret}")

# 環境変数を読み込み
load_environment_variables()

# --- 設定読み込み ---
print("🔧 Bot設定を読み込み中...")
config = get_config()

# APIキーの取得（新しい設定システム使用）
DISCORD_TOKEN = config.get_required("DISCORD_TOKEN")
OPENAI_API_KEY = config.get_required("OPENAI_API_KEY")
GEMINI_API_KEY = config.get_required("GEMINI_API_KEY")
PERPLEXITY_API_KEY = config.get_required("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = config.get_required("MISTRAL_API_KEY")
NOTION_API_KEY = config.get_required("NOTION_API_KEY")
GROK_API_KEY = config.get_required("GROK_API_KEY")
OPENROUTER_API_KEY = config.get_required("OPENROUTER_API_KEY")
ADMIN_USER_ID = config.get_required("ADMIN_USER_ID")

# オプション設定
GUILD_ID = config.get("GUILD_ID", "")

# --- FastAPIとDiscord Botの準備 ---
app = FastAPI()

# Cloud Run用のヘルスチェックエンドポイント
@app.get("/")
async def health_check():
    return {"status": "ok", "service": "discord-genius-bot"}

@app.get("/health")
async def detailed_health():
    return {
        "status": "healthy",
        "service": "discord-genius-bot",
        "version": "4.0",
        "features": ["plugin-system", "unified-task-engine", "ai-council"]
    }

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=None, intents=intents)

# 動的プロパティ設定用の拡張クラスメソッド
def _setup_legacy_memory_properties(self):
    """従来メモリ変数を動的プロパティとして設定"""
    from enhanced_memory_manager import LegacyMemoryMapping

    # 動的プロパティで統一メモリシステムにリダイレクト
    for memory_type in LegacyMemoryMapping.base_memory_types:
        prop_name = f"{memory_type}_base_memory"
        setattr(self.__class__, prop_name,
               property(
                   lambda self, mt=memory_type: self.memory_manager.get_legacy_memory(mt, "base"),
                   lambda self, value, mt=memory_type: self.memory_manager.update_legacy_memory(mt, "__dict_update__", list(value.items()) if isinstance(value, dict) else value, "base")
               ))

    for memory_type in LegacyMemoryMapping.thread_memory_types:
        prop_name = f"{memory_type}_thread_memory"
        setattr(self.__class__, prop_name,
               property(
                   lambda self, mt=memory_type: self.memory_manager.get_legacy_memory(mt, "thread"),
                   lambda self, value, mt=memory_type: self.memory_manager.update_legacy_memory(mt, "__dict_update__", list(value.items()) if isinstance(value, dict) else value, "thread")
               ))

    # processing_channels プロパティ
    setattr(self.__class__, 'processing_channels',
           property(
               lambda self: self.memory_manager.get_processing_channels(),
               lambda self, value: None  # 書き込みは無視（メソッド経由で操作）
           ))

# Botクラスにメソッドを動的追加
commands.Bot._setup_legacy_memory_properties = _setup_legacy_memory_properties

# --- FastAPIのエンドポイント ---
@app.get("/")
def health_check():
    """ヘルスチェックエンドポイント（設定情報付き）"""
    return {
        "status": "ok",
        "bot_is_connected": bot.is_ready(),
        "config_summary": config.get_config_summary(),
        "features": {}
    }

@app.get("/config")
def config_status():
    """設定状況確認用エンドポイント"""
    return {
        "config_summary": config.get_config_summary()
    }

@app.get("/memory")
def memory_status():
    """メモリ状況確認用エンドポイント"""
    try:
        memory_manager = get_memory_manager()
        return {
            "status": "ok",
            "memory_stats": memory_manager.get_detailed_stats()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@app.post("/memory/clear")
def clear_memory(ai_type: str = None, channel_id: str = None):
    """メモリクリア用エンドポイント"""
    try:
        memory_manager = get_memory_manager()

        if ai_type and channel_id:
            cleared = memory_manager.clear_channel_memory(ai_type, channel_id)
            return {"status": "ok", "cleared_entries": cleared, "scope": f"{ai_type}#{channel_id}"}
        elif ai_type:
            cleared = memory_manager.clear_ai_memory(ai_type)
            return {"status": "ok", "cleared_entries": cleared, "scope": ai_type}
        else:
            cleared = memory_manager.clear_all_memory()
            return {"status": "ok", "cleared_entries": cleared, "scope": "all"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.get("/performance")
def performance_stats():
    """パフォーマンス統計確認用エンドポイント"""
    try:
        from async_optimizer import get_global_optimization_stats
        from ai_manager import get_ai_manager

        stats = {
            "async_optimization": get_global_optimization_stats(),
            "memory_stats": get_memory_manager().get_memory_stats(),
        }

        # AIマネージャーが初期化済みの場合は統計を追加
        ai_manager = get_ai_manager()
        if ai_manager.initialized:
            stats["ai_stats"] = ai_manager.get_all_stats()

        return {
            "status": "ok",
            "performance": stats
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@app.get("/rate-limits")
def rate_limit_status():
    """レート制限状況確認用エンドポイント"""
    try:
        from rate_limiter import get_rate_limiter

        rate_limiter = get_rate_limiter()
        return {
            "status": "ok",
            "rate_limits": rate_limiter.get_all_stats(),
            "service_health": rate_limiter.get_service_health()
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }

@app.post("/rate-limits/reset")
def reset_rate_limits(service_name: str = None):
    """レート制限リセット用エンドポイント（管理者用）"""
    try:
        from rate_limiter import get_rate_limiter

        rate_limiter = get_rate_limiter()

        if service_name:
            import asyncio
            result = asyncio.run(rate_limiter.reset_service_limits(service_name))
            return {
                "status": "ok" if result else "not_found",
                "message": f"Service '{service_name}' rate limits reset" if result else f"Service '{service_name}' not found"
            }
        else:
            # 全サービスリセット
            reset_count = 0
            for service in list(rate_limiter.buckets.keys()):
                import asyncio
                if asyncio.run(rate_limiter.reset_service_limits(service)):
                    reset_count += 1

            return {
                "status": "ok",
                "message": f"{reset_count} services reset"
            }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# --- Botの起動とcogsの読み込み ---
@bot.event
async def on_ready():
    print(f"✅ Login successful: {bot.user} (PID: {os.getpid()})")
    print(f"🔍 Bot instance ID: {id(bot)}")
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
            
        # 重複防止機能の定期クリーンアップを開始（一時的に無効化）
        # try:
        #     from channel_tasks import start_periodic_cleanup
        #     asyncio.create_task(start_periodic_cleanup())
        #     print("✅ 定期クリーンアップタスク開始")
        # except Exception as cleanup_error:
        #     print(f"⚠️ 定期クリーンアップの開始に失敗: {cleanup_error}")
        print("ℹ️ 定期クリーンアップは一時的に無効化されています")

        # AIマネージャー初期化
        try:
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            ai_manager.initialize(bot)
            print("✅ AIマネージャー初期化完了")
        except Exception as ai_init_error:
            print(f"⚠️ AIマネージャーの初期化に失敗: {ai_init_error}")
            
    except Exception as e:
        print(f"🚨 FATAL ERROR on ready/sync: {e}")
        import traceback
        traceback.print_exc()

@app.on_event("startup")
async def startup_event():
    print("🤖 Initializing API clients and bot state...")
    try:
        # APIクライアントとキーをbotインスタンスに格納
        # httpxのバージョン互換性対応
        import httpx
        http_client = httpx.AsyncClient()
        bot.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)
        bot.mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
        notion_utils.notion = Client(auth=NOTION_API_KEY)
        genai.configure(api_key=GEMINI_API_KEY)
        bot.perplexity_api_key = PERPLEXITY_API_KEY
        bot.openrouter_api_key = OPENROUTER_API_KEY
        bot.grok_api_key = GROK_API_KEY

        # 拡張統一メモリマネージャーを初期化
        bot.memory_manager = get_enhanced_memory_manager()

        # 従来のメモリ変数を動的プロパティとして設定（完全後方互換性）
        bot._setup_legacy_memory_properties()

        print("✅ 拡張統一メモリマネージャー準備完了")
        
        # 定数もbotインスタンスに格納
        bot.ADMIN_USER_ID = ADMIN_USER_ID
        bot.GUILD_ID = GUILD_ID

        # Llamaモデルの初期化
        bot.llama_model = None
        try:
            vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
            bot.llama_model = GenerativeModel("llama-3.3-70b-instruct-maas")
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