# -*- coding: utf-8 -*-
"""
統一タスクエンジン - 全てのAI処理を統合する設定駆動型システム
"""

import asyncio
import time
import hashlib
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from abc import ABC, abstractmethod
import yaml
from pathlib import Path

import discord
from discord.ext import commands

from utils import safe_log, send_long_message, analyze_attachment_for_gpt5, get_notion_context_for_message
from enhanced_memory_manager import get_enhanced_memory_manager
from ai_manager import get_ai_manager
from enhanced_cache import get_cache_manager
from notion_utils import (
    NOTION_PAGE_MAP, log_user_message, log_response, get_memory_flag_from_notion,
    find_latest_section_id, append_summary_to_kb
)
from async_optimizer import process_with_parallel_context, multi_ai_council_parallel
from ai_clients import ask_gpt5_mini
from plugin_system import HookType

@dataclass
class TaskConfig:
    """タスク設定"""
    task_type: str
    description: str
    use_memory: bool = False
    use_kb: bool = True
    use_summary: bool = True
    context_strategy: str = "cached"
    prompt_template: str = "standard"
    special_handler: Optional[str] = None
    post_processing: List[str] = None
    priority: float = 1.0
    timeout: int = 30
    max_retries: int = 2

@dataclass
class TaskResult:
    """タスク実行結果"""
    success: bool
    response: str
    metadata: Dict[str, Any]
    execution_time: float
    error: Optional[str] = None

class TaskConfigLoader:
    """タスク設定ローダー"""

    def __init__(self):
        self.config_file = Path(__file__).parent / "config" / "task_configs.yaml"
        self.config_data: Dict[str, Any] = {}
        self.last_modified = 0
        self._load_config()

    def _load_config(self):
        """設定ファイルを読み込み"""
        try:
            if not self.config_file.exists():
                safe_log("⚠️ タスク設定ファイルが見つかりません: ", str(self.config_file))
                self._create_default_config()
                return

            current_modified = self.config_file.stat().st_mtime
            if current_modified <= self.last_modified:
                return  # 更新されていない

            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)

            self.last_modified = current_modified
            safe_log("✅ タスク設定読み込み完了: ", f"{len(self.config_data.get('ai_task_mapping', {}))}個のAI設定")

        except Exception as e:
            safe_log("🚨 タスク設定読み込みエラー: ", e)
            self._create_default_config()

    def _create_default_config(self):
        """デフォルト設定を作成"""
        self.config_data = {
            "task_types": {
                "standard": {
                    "description": "標準AIタスク",
                    "use_memory": False,
                    "use_kb": True,
                    "use_summary": True,
                    "context_strategy": "cached",
                    "prompt_template": "standard"
                }
            },
            "ai_task_mapping": {
                "gpt5": {"task_type": "standard", "priority": 1.0}
            }
        }

    def get_task_config(self, ai_type: str) -> TaskConfig:
        """AIタイプからタスク設定を取得"""
        self._load_config()  # 必要に応じて再読み込み

        # AI設定を取得
        ai_config = self.config_data.get("ai_task_mapping", {}).get(ai_type, {})
        task_type = ai_config.get("task_type", "standard")

        # タスクタイプ設定を取得
        task_type_config = self.config_data.get("task_types", {}).get(task_type, {})

        # TaskConfigオブジェクトを作成
        return TaskConfig(
            task_type=task_type,
            description=task_type_config.get("description", ""),
            use_memory=task_type_config.get("use_memory", False),
            use_kb=task_type_config.get("use_kb", True),
            use_summary=task_type_config.get("use_summary", True),
            context_strategy=task_type_config.get("context_strategy", "cached"),
            prompt_template=task_type_config.get("prompt_template", "standard"),
            special_handler=task_type_config.get("special_handler"),
            post_processing=task_type_config.get("post_processing", ["log_response"]),
            priority=ai_config.get("priority", 1.0),
            timeout=ai_config.get("timeout", 30),
            max_retries=ai_config.get("max_retries", 2)
        )

    def get_context_strategy(self, strategy_name: str) -> Dict[str, Any]:
        """コンテキスト戦略を取得"""
        return self.config_data.get("context_strategies", {}).get(strategy_name, {})

    def get_prompt_template(self, template_name: str) -> str:
        """プロンプトテンプレートを取得"""
        return self.config_data.get("prompt_templates", {}).get(template_name, {}).get("template", "{message_content}")

# コンテキスト戦略（Strategy Pattern）
class ContextStrategy(ABC):
    """コンテキスト取得戦略の抽象基底クラス"""

    @abstractmethod
    async def get_context(self, bot: commands.Bot, message: discord.Message,
                         config: TaskConfig, page_ids: List[str]) -> Dict[str, Any]:
        pass

class MinimalContextStrategy(ContextStrategy):
    """最小コンテキスト戦略"""

    async def get_context(self, bot: commands.Bot, message: discord.Message,
                         config: TaskConfig, page_ids: List[str]) -> Dict[str, Any]:
        return {"message_content": message.content}

class CachedContextStrategy(ContextStrategy):
    """キャッシュ最適化コンテキスト戦略"""

    async def get_context(self, bot: commands.Bot, message: discord.Message,
                         config: TaskConfig, page_ids: List[str]) -> Dict[str, Any]:
        cache_manager = get_cache_manager()
        page_id = page_ids[0] if page_ids else None

        context = {"message_content": message.content}

        if page_id and config.use_kb:
            # 直接関数を呼び出し（キャッシュを一時的にスキップ）
            notion_context = await get_notion_context_for_message(
                bot=bot,
                message=message,
                page_id=page_id,
                query=message.content,
                model_choice="gpt5mini"
            )
            context["notion_context"] = notion_context or ""

        return context

class ParallelMemoryContextStrategy(ContextStrategy):
    """並列メモリコンテキスト戦略"""

    async def get_context(self, bot: commands.Bot, message: discord.Message,
                         config: TaskConfig, page_ids: List[str]) -> Dict[str, Any]:
        context = {"message_content": message.content}

        try:
            # 並列コンテキスト取得を試行
            context_data = await process_with_parallel_context(bot, message, page_ids, "unified")
            context["kb_context"] = context_data.get("kb_context", "")

            # メモリ履歴の取得
            if config.use_memory:
                memory_manager = get_enhanced_memory_manager()
                is_memory_on = await get_memory_flag_from_notion(str(message.channel.id))

                if is_memory_on:
                    history = memory_manager.get_history("unified", str(message.channel.id))
                    context["memory_history"] = "\n".join([f"{m['role']}: {m['content']}" for m in history]) if history else "なし"
                else:
                    context["memory_history"] = "なし"

        except Exception as e:
            safe_log("⚠️ 並列コンテキスト取得エラー: ", e)
            # フォールバック：キャッシュ戦略を使用
            fallback_strategy = CachedContextStrategy()
            context.update(await fallback_strategy.get_context(bot, message, config, page_ids))

        return context

class CouncilOptimizedContextStrategy(ContextStrategy):
    """AI評議会用最適化戦略"""

    async def get_context(self, bot: commands.Bot, message: discord.Message,
                         config: TaskConfig, page_ids: List[str]) -> Dict[str, Any]:
        context = {"message_content": message.content}

        if page_ids:
            # 初回要約の取得
            initial_summary = await get_notion_context_for_message(bot, message, page_ids[0], message.content, "gpt5mini")
            context["initial_summary"] = initial_summary or ""

        return context

class ContextStrategyFactory:
    """コンテキスト戦略ファクトリー"""

    _strategies = {
        "minimal": MinimalContextStrategy(),
        "cached": CachedContextStrategy(),
        "parallel_memory": ParallelMemoryContextStrategy(),
        "council_optimized": CouncilOptimizedContextStrategy()
    }

    @classmethod
    def get_strategy(cls, strategy_name: str) -> ContextStrategy:
        return cls._strategies.get(strategy_name, cls._strategies["cached"])

# 後処理ハンドラー（Command Pattern）
class PostProcessor(ABC):
    """後処理の抽象基底クラス"""

    @abstractmethod
    async def process(self, bot: commands.Bot, message: discord.Message,
                     response: str, config: TaskConfig, context: Dict[str, Any],
                     page_ids: List[str]) -> str:
        pass

class LogResponseProcessor(PostProcessor):
    """応答ログ記録処理"""

    async def process(self, bot: commands.Bot, message: discord.Message,
                     response: str, config: TaskConfig, context: Dict[str, Any],
                     page_ids: List[str]) -> str:
        if page_ids:
            await log_response(page_ids[0], response, config.description)
        return response

class UpdateMemoryProcessor(PostProcessor):
    """メモリ更新処理"""

    async def process(self, bot: commands.Bot, message: discord.Message,
                     response: str, config: TaskConfig, context: Dict[str, Any],
                     page_ids: List[str]) -> str:
        if config.use_memory and "エラー" not in response:
            memory_manager = get_enhanced_memory_manager()
            memory_manager.add_interaction(
                ai_type="unified",
                channel_id=str(message.channel.id),
                user_content=message.content,
                ai_response=response,
                metadata={
                    "task_type": config.task_type,
                    "timestamp": time.time()
                }
            )
        return response

class KBSummaryProcessor(PostProcessor):
    """KB要約処理"""

    async def process(self, bot: commands.Bot, message: discord.Message,
                     response: str, config: TaskConfig, context: Dict[str, Any],
                     page_ids: List[str]) -> str:
        if config.use_summary and len(page_ids) > 1:
            try:
                cache_manager = get_cache_manager()
                summary_prompt = f"以下のテキストをNotion KB用に150字以内で簡潔に要約せよ。\n\n{response}"
                summary_hash = hashlib.md5(summary_prompt.encode()).hexdigest()[:12]

                official_summary = await cache_manager.get_ai_response_cached(
                    ai_type="gpt5mini",
                    prompt_hash=summary_hash,
                    fetch_func=ask_gpt5_mini,
                    openai_client=bot.openai_client,
                    prompt=summary_prompt
                )

                if official_summary:
                    kb_page_id = page_ids[1]
                    new_section_id = await find_latest_section_id(kb_page_id)
                    await append_summary_to_kb(kb_page_id, new_section_id, official_summary)

                    return f"{response}\n\n---\n*この回答はKBに **{new_section_id}** として記録されました。*"

            except Exception as e:
                safe_log("⚠️ KB要約処理エラー: ", e)

        return response

class PostProcessorFactory:
    """後処理ファクトリー"""

    _processors = {
        "log_response": LogResponseProcessor(),
        "update_memory": UpdateMemoryProcessor(),
        "kb_summary": KBSummaryProcessor()
    }

    @classmethod
    def get_processor(cls, processor_name: str) -> Optional[PostProcessor]:
        return cls._processors.get(processor_name)

# 統一タスクエンジン
class UnifiedTaskEngine:
    """統一タスクエンジン - 全てのAI処理を統合"""

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        self.config_loader = TaskConfigLoader()
        self.ai_manager = get_ai_manager()
        self.memory_manager = get_enhanced_memory_manager()
        self.cache_manager = get_cache_manager()

        # プラグインシステム統合
        from plugin_system import get_plugin_manager
        self.plugin_manager = get_plugin_manager()

        # 統計
        self.task_count = 0
        self.error_count = 0
        self.total_execution_time = 0

    async def execute_task(self, bot: commands.Bot, message: discord.Message, ai_type: str) -> TaskResult:
        """タスク実行のメインエントリーポイント"""
        start_time = time.time()
        self.task_count += 1

        try:
            # 重複処理防止
            message_id = str(message.id)
            if not self.memory_manager.start_message_processing(message_id):
                return TaskResult(
                    success=False,
                    response="メッセージは既に処理中または処理済みです",
                    metadata={"duplicate": True},
                    execution_time=0,
                    error="Duplicate message"
                )

            # 設定読み込み
            config = self.config_loader.get_task_config(ai_type)

            # Phase 2: プラグイン task_execution フックで特殊処理チェック
            task_results = await self.plugin_manager.execute_hook(
                HookType.TASK_EXECUTION,
                bot=bot, message=message, ai_type=ai_type, context={}
            )

            # プラグインがタスクを処理した場合
            for result in task_results:
                if result.success and result.modified:
                    self.plugin_tasks += 1
                    safe_log(f"🔌 プラグインタスク実行: ", ai_type)

                    # Phase 3: post_task_execution フック
                    post_results = await self.plugin_manager.execute_hook(
                        HookType.POST_TASK_EXECUTION,
                        bot=bot, message=message, ai_type=ai_type,
                        response=result.data, context={}
                    )

                    return TaskResult(
                        success=True,
                        response=result.data,
                        metadata={
                            "plugin_handled": True,
                            "execution_time": getattr(result, 'execution_time', 0)
                        },
                        execution_time=time.time() - start_time
                    )

            # Notion設定確認（genius_lightはスキップ）
            page_ids = []
            if ai_type == "genius_pro":
                page_ids = NOTION_PAGE_MAP.get(str(message.channel.id))
                if not page_ids:
                    return TaskResult(
                        success=False,
                        response="❌ Notion未連携",
                        metadata={"no_notion": True},
                        execution_time=time.time() - start_time,
                        error="No Notion configuration"
                    )
            else:
                page_ids = []

            # 標準タスク実行フロー
            result = await self._execute_standard_task(bot, message, ai_type, config, page_ids)

            # 処理完了
            self.memory_manager.finish_message_processing(message_id, success=result.success)
            result.execution_time = time.time() - start_time

            if result.success:
                self.total_execution_time += result.execution_time
            else:
                self.error_count += 1

            return result

        except Exception as e:
            self.error_count += 1
            safe_log("🚨 統一タスクエンジンエラー: ", e)
            self.memory_manager.finish_message_processing(message_id, success=False)

            return TaskResult(
                success=False,
                response=f"タスク実行エラー: {str(e)[:100]}",
                metadata={"exception": str(e)},
                execution_time=time.time() - start_time,
                error=str(e)
            )

    async def _execute_standard_task(self, bot: commands.Bot, message: discord.Message,
                                   ai_type: str, config: TaskConfig, page_ids: List[str]) -> TaskResult:
        """標準タスクの実行"""

        async with message.channel.typing():
            # 1. コンテキスト取得（戦略パターン）
            strategy = ContextStrategyFactory.get_strategy(config.context_strategy)
            context = await strategy.get_context(bot, message, config, page_ids)

            # 2. プロンプト構築
            prompt = self._build_prompt(config, context)

            # 3. ユーザーメッセージログ記録（genius_proのみ）
            if ai_type == "genius_pro" and page_ids:
                await log_user_message(page_ids[0], message.author.display_name, message.content)

            # 4. AI実行（キャッシュ統合）
            response = await self._execute_ai(ai_type, prompt, config, bot)

            # 5. 後処理（コマンドパターン）
            final_response = await self._execute_post_processing(
                bot, message, response, config, context, page_ids
            )

            # 6. 応答送信
            await send_long_message(bot.openai_client, message.channel, final_response)

            return TaskResult(
                success=True,
                response=final_response,
                metadata={
                    "ai_type": ai_type,
                    "task_type": config.task_type,
                    "context_strategy": config.context_strategy,
                    "post_processing": config.post_processing
                },
                execution_time=0  # 後で設定される
            )

    def _build_prompt(self, config: TaskConfig, context: Dict[str, Any]) -> str:
        """プロンプト構築"""
        template = self.config_loader.get_prompt_template(config.prompt_template)

        try:
            return template.format(**context)
        except KeyError as e:
            safe_log("⚠️ プロンプトテンプレートエラー: ", f"Missing key {e}")
            return context.get("message_content", "")

    async def _execute_ai(self, ai_type: str, prompt: str, config: TaskConfig, bot=None) -> str:
        """AI実行（キャッシュ統合）"""
        try:
            # AIマネージャーを初期化
            if not self.ai_manager.initialized and bot:
                self.ai_manager.initialize(bot)

            # キャッシュハッシュ作成
            prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:12]

            # キャッシュから応答を試行取得
            cache_key = f"{ai_type}:{prompt_hash}"
            cached_response = await self.cache_manager.get_cached(
                "ai_response",
                {"ai_type": ai_type, "prompt_hash": prompt_hash},
                None
            )

            if cached_response:
                safe_log(f"⚡ AI応答キャッシュヒット ({ai_type}): ", f"ハッシュ:{prompt_hash}")
                return cached_response

            # キャッシュミス：AI実行
            response = await self.ai_manager.ask_ai(ai_type, prompt, priority=config.priority)

            # レスポンスをキャッシュに保存
            if response:
                await self.cache_manager.set_cached(
                    "ai_response",
                    {"ai_type": ai_type, "prompt_hash": prompt_hash},
                    response
                )

            return response or f"申し訳ありません。{ai_type}からの応答が空でした。"

        except Exception as e:
            return f"{ai_type}エラー: {str(e)[:200]}"

    async def _execute_post_processing(self, bot: commands.Bot, message: discord.Message,
                                     response: str, config: TaskConfig, context: Dict[str, Any],
                                     page_ids: List[str]) -> str:
        """後処理実行"""
        current_response = response

        for processor_name in (config.post_processing or []):
            processor = PostProcessorFactory.get_processor(processor_name)
            if processor:
                try:
                    current_response = await processor.process(
                        bot, message, current_response, config, context, page_ids
                    )
                except Exception as e:
                    safe_log(f"⚠️ 後処理エラー ({processor_name}): ", e)

        return current_response

    # _handle_genius_council はプラグインシステムに移行済み

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        avg_time = self.total_execution_time / max(self.task_count, 1)
        error_rate = self.error_count / max(self.task_count, 1)

        return {
            "total_tasks": self.task_count,
            "errors": self.error_count,
            "error_rate": f"{error_rate:.1%}",
            "avg_execution_time": f"{avg_time:.2f}s",
            "engine_version": "3.0"
        }

# グローバルインスタンス
_unified_task_engine: Optional[UnifiedTaskEngine] = None

def get_unified_task_engine() -> UnifiedTaskEngine:
    """統一タスクエンジンインスタンスを取得"""
    global _unified_task_engine
    if _unified_task_engine is None:
        _unified_task_engine = UnifiedTaskEngine()
        safe_log("✅ 統一タスクエンジン初期化完了", "")
    return _unified_task_engine

if __name__ == "__main__":
    # テスト実行
    print("=== Unified Task Engine Test ===")

    engine = UnifiedTaskEngine()
    config = engine.config_loader.get_task_config("gpt5")
    print(f"GPT-5設定: {config}")

    print("✅ Unified Task Engine is ready!")