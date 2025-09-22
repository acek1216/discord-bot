import discord
from discord.ext import commands
import asyncio
import traceback
import time
import threading
from typing import Set, Dict, Callable, Any, Optional
from dataclasses import dataclass

# --- 統一タスクエンジン使用 ---
from unified_task_engine import get_unified_task_engine, TaskResult
from utils import safe_log

# --- レガシーインポート（後方互換性のため保持） ---
from notion_utils import (
    NOTION_PAGE_MAP, get_notion_page_text, log_to_notion, log_user_message,
    log_response, get_memory_flag_from_notion,
    find_latest_section_id, append_summary_to_kb
)
from ai_clients import (
    ask_gpt5, ask_gpt5_mini, ask_gemini_2_5_pro, ask_rekus,
    ask_gpt4o
)
from ai_manager import get_ai_manager
from enhanced_memory_manager import get_enhanced_memory_manager
from async_optimizer import process_with_parallel_context, multi_ai_council_parallel, AsyncOptimizer, AsyncTask
from utils import (
    safe_log, send_long_message, analyze_attachment_for_gemini, get_notion_context_for_message
)
from enhanced_cache import get_cache_manager
from config_manager import get_config_manager

# 重複処理防止クラス（既存のものをそのまま利用）
class MessageDuplicationHandler:
    def __init__(self):
        self.processing_messages: Set[str] = set()
        self.processed_messages: Dict[str, float] = {}
        self.lock = threading.Lock()
        self.cleanup_interval = 600
        self.last_cleanup = time.time()

    def start_processing(self, message_id: str) -> bool:
        with self.lock:
            current_time = time.time()
            if current_time - self.last_cleanup > self.cleanup_interval:
                self._cleanup_old_messages(current_time)
                self.last_cleanup = current_time
            
            if message_id in self.processing_messages or message_id in self.processed_messages:
                return False
            
            self.processing_messages.add(message_id)
            return True

    def finish_processing(self, message_id: str, success: bool = True):
        with self.lock:
            self.processing_messages.discard(message_id)
            if success:
                self.processed_messages[message_id] = time.time()

    def _cleanup_old_messages(self, current_time: float):
        cutoff_time = current_time - 3600
        self.processed_messages = {
            msg_id: timestamp for msg_id, timestamp in self.processed_messages.items()
            if timestamp > cutoff_time
        }

duplicate_handler = MessageDuplicationHandler()

@dataclass
class AIConfig:
    """AI設定の定義"""
    ai_function: Callable
    ai_name: str
    needs_kb_log: bool = True  # KBへのログ記録が必要か
    needs_summary: bool = True  # 要約が必要か
    special_handler: Optional[str] = None  # 特別な処理が必要な場合

# AI設定マップ（新旧両方をサポート）
# Legacy config system removed - using unified system only

def get_unified_ai_configs():
    """新しい統一AI設定システム"""
    return {
        "gpt5": AIConfig(
            ai_function=None,  # AIManagerを使用
            ai_name="GPT-5",
            needs_summary=True,
            special_handler="unified"
        ),
        "gpt4o": AIConfig(
            ai_function=None,
            ai_name="GPT-4o",
            needs_summary=True,
            special_handler="unified_memory"
        ),
        "gemini": AIConfig(
            ai_function=None,
            ai_name="Gemini 2.5 Pro",
            needs_summary=True,
            special_handler="unified"
        ),
        "claude": AIConfig(
            ai_function=None,
            ai_name="Claude",
            needs_summary=True,
            special_handler="unified"
        ),
        "mistral": AIConfig(
            ai_function=None,
            ai_name="Mistral",
            needs_summary=True,
            special_handler="unified"
        ),
        "grok": AIConfig(
            ai_function=None,
            ai_name="Grok",
            needs_summary=True,
            special_handler="unified"
        ),
        "llama": AIConfig(
            ai_function=None,
            ai_name="Llama",
            needs_summary=True,
            special_handler="unified"
        ),
        "o1_pro": AIConfig(
            ai_function=None,
            ai_name="O1 Pro",
            needs_summary=True,
            special_handler="unified_memory"
        ),
        "genius_pro": AIConfig(
            ai_function=None,
            ai_name="Genius Pro",
            needs_summary=True,
            special_handler="genius_pro"
        ),
        "genius_light": AIConfig(
            ai_function=None,
            ai_name="Genius Light",
            needs_summary=False,
            special_handler="unified"
        ),
    }

async def run_unified_ai_task(bot: commands.Bot, message: discord.Message, ai_type: str):
    """統一AIタスク処理 - 新しい統一エンジン使用"""
    try:
        # 統一タスクエンジンを使用
        task_engine = get_unified_task_engine()
        result = await task_engine.execute_task(bot, message, ai_type)

        if not result.success and result.response:
            await message.channel.send(result.response)

        # 統計ログ
        if result.execution_time > 0:
            safe_log(f"⚡ タスク完了 ({ai_type}): ", f"{result.execution_time:.2f}s")

    except Exception as e:
        safe_log("🚨 統一タスクエラー: ", e)
        await message.channel.send(f"❌ {ai_type}タスクエラー: {str(e)[:100]}")
        traceback.print_exc()

# --- レガシーハンドラー（統一エンジンに統合済み） ---
# 以下の関数は統一タスクエンジン (unified_task_engine.py) に統合されました
# 後方互換性のため関数名は残しますが、実装は統一エンジンにリダイレクトします

async def _handle_unified_ai_task(bot: commands.Bot, message: discord.Message, config, page_ids: list, ai_type: str):
    """レガシーハンドラー - 統一エンジンにリダイレクト"""
    safe_log("⚠️ レガシーハンドラー呼び出し: ", "統一エンジンに移行してください")

    # 統一エンジンにリダイレクト
    task_engine = get_unified_task_engine()
    result = await task_engine.execute_task(bot, message, ai_type)

    if not result.success and result.response:
        await message.channel.send(result.response)


# --- レガシー関数（統一エンジンに統合済み） ---
# これらの関数は unified_task_engine.py の各戦略・処理クラスに統合されました
# 後方互換性のため関数名は残しますが、統一エンジンの使用を推奨します

async def _get_context_by_strategy(bot, message, page_ids, ai_type, use_memory):
    """レガシー関数 - 統一エンジンのContextStrategyに移行"""
    safe_log("⚠️ レガシーコンテキスト取得: ", "ContextStrategyクラスの使用を推奨")
    # 最小限の実装
    return {"message_content": message.content, "legacy_call": True}

def _build_prompt(message, context_data, use_memory):
    """レガシー関数 - 統一エンジンのプロンプトテンプレートに移行"""
    safe_log("⚠️ レガシープロンプト構築: ", "プロンプトテンプレートシステムの使用を推奨")
    return context_data.get("message_content", message.content)

async def _update_memory(bot, ai_type, message, reply):
    """レガシー関数 - 統一メモリマネージャーに移行済み"""
    memory_manager = get_enhanced_memory_manager()
    memory_manager.add_interaction(
        ai_type=ai_type,
        channel_id=str(message.channel.id),
        user_content=message.content,
        ai_response=reply
    )

async def _handle_summary_and_kb(bot, reply, kb_page_id, author):
    """レガシー関数 - 統一エンジンのPostProcessorに移行"""
    safe_log("⚠️ レガシーKB処理: ", "PostProcessorクラスの使用を推奨")
    return reply  # 簡単な実装


# --- genius/genius_proチャンネルタスク（特別処理のため個別実装） ---
async def run_genius_pro_task(bot: commands.Bot, message: discord.Message):
    """Genius Pro部屋のタスク処理（AI評議会・Notion連携）"""
    message_id = str(message.id)
    thread_id = str(message.channel.id)

    if not duplicate_handler.start_processing(message_id):
        safe_log("⚠️ genius_proタスク: ", f"メッセージ {message_id} は既に処理中または処理済み")
        return

    prompt = message.content

    # 添付ファイルがある場合は解析を追加
    if message.attachments:
        try:
            attachment_info = await analyze_attachment_for_gemini(message.attachments[0])
            prompt += f"\n\n{attachment_info}"
            safe_log("📎 Genius Pro部屋添付ファイル解析完了: ", f"{message.attachments[0].filename}")
        except Exception as e:
            safe_log("🚨 Genius Pro部屋添付ファイル解析エラー: ", e)

    # タイピングインジケーター開始
    async with message.channel.typing():
        try:
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ Notion未連携")
                return

            initial_summary = await get_notion_context_for_message(bot, message, page_ids[0], prompt, "gpt5mini")
            if not initial_summary:
                await message.channel.send(f"❌ 初回要約に失敗")
                return

            await send_long_message(bot.openai_client, message.channel, f"**gpt5miniによる論点サマリー:**\n{initial_summary}")

            # 論点サマリーを0ページに保存
            kb_page_id = page_ids[0]
            await log_response(kb_page_id, f"論点サマリー:\n{initial_summary}", "gpt5mini")

            # 最適化された並列AI評議会
            council_prompt = f"論点: {initial_summary}\n\n議題「{prompt}」を分析してください。"

            # 直接関数呼び出しで並列処理
            from ai_clients import ask_claude, ask_llama
            tasks = {
                "Perplexity": ask_rekus(bot.perplexity_api_key, council_prompt),
                "Claude": ask_claude(bot.openrouter_api_key, str(message.author.id), council_prompt),
                "Llama": ask_llama(bot.llama_model, str(message.author.id), council_prompt)
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            council_reports = {name: (f"エラー: {res}" if isinstance(res, Exception) else res) for name, res in zip(tasks.keys(), results)}

            for name, report in council_reports.items():
                await send_long_message(bot.openai_client, message.channel, f"**分析 by {name}:**\n{report}")
                # 各分析を0ページに保存
                await log_response(kb_page_id, f"分析 by {name}:\n{report}", name)

            synthesis_material = "以下のレポートを統合してください。\n\n" + "\n\n".join(f"--- [{name}] ---\n{report}" for name, report in council_reports.items())

            # Gemini 2.5 Proで最終統合レポートを生成
            final_report = await ask_gemini_2_5_pro(synthesis_material)
            await send_long_message(bot.openai_client, message.channel, f"**最終統合レポート:**\n{final_report}")

            # 最終レポートを0ページに保存
            await log_response(kb_page_id, f"最終統合レポート:\n{final_report}", "Gemini 2.5 Pro")

            # KB用要約も保存（1ページがある場合のみ）
            if len(page_ids) >= 2:
                log_page_id = page_ids[1]
                summary_prompt = f"以下のAI評議会最終レポートを150字以内で要約してください。\n\n{final_report}"
                log_summary = await ask_gpt5_mini(bot.openai_client, summary_prompt)
                new_section_id = await find_latest_section_id(log_page_id)
                await append_summary_to_kb(log_page_id, new_section_id, log_summary)

        except Exception as e:
            safe_log("🚨 genius_proタスクエラー: ", e)
            await message.channel.send(f"分析シーケンスエラー: {e}")
            duplicate_handler.finish_processing(message_id, success=False)
        else:
            duplicate_handler.finish_processing(message_id, success=True)
        finally:
            bot.processing_channels.discard(thread_id)

async def run_genius_task(bot: commands.Bot, message: discord.Message):
    """軽量版Genius部屋 - シンプルなAI応答のみ"""
    message_id = str(message.id)
    thread_id = str(message.channel.id)

    if not duplicate_handler.start_processing(message_id):
        safe_log("⚠️ geniusタスク: ", f"メッセージ {message_id} は既に処理中または処理済み")
        return

    prompt = message.content

    # 添付ファイルがある場合は解析を追加
    if message.attachments:
        try:
            attachment_info = await analyze_attachment_for_gemini(message.attachments[0])
            prompt += f"\n\n{attachment_info}"
            safe_log("📎 Genius部屋添付ファイル解析完了: ", f"{message.attachments[0].filename}")
        except Exception as e:
            safe_log("🚨 Genius部屋添付ファイル解析エラー: ", e)

    # タイピングインジケーター開始
    async with message.channel.typing():
        try:
            # 統一タスクエンジンを使用してシンプルな応答
            task_engine = get_unified_task_engine()
            result = await task_engine.execute_task(bot, message, "genius_light")

            if not result.success and result.response:
                await message.channel.send(result.response)

        except Exception as e:
            safe_log("🚨 geniusタスクエラー: ", e)
            await message.channel.send(f"❌ Genius応答エラー: {str(e)[:100]}")
            duplicate_handler.finish_processing(message_id, success=False)
        else:
            duplicate_handler.finish_processing(message_id, success=True)
        finally:
            bot.processing_channels.discard(thread_id)

# 🎯 Phase 3: 完全統一タスクエンジン実装完了
# 旧：複数の重複ハンドラー → 新：統一タスクエンジン (unified_task_engine.py)
# 設定駆動型アーキテクチャで拡張性と保守性を大幅向上
# - コンテキスト戦略パターン実装
# - 後処理コマンドパターン実装
# - YAML設定による外部化
# - 完全な後方互換性維持