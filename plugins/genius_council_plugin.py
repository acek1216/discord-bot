# -*- coding: utf-8 -*-
"""
Genius Council Plugin - AI評議会システム
既存のrun_genius_taskをプラグイン化
"""

import asyncio
import time
from typing import Dict, Any, List

import discord
from discord.ext import commands

from plugin_system import Plugin, HookResult
from utils import safe_log, send_long_message, get_notion_context_for_message
from notion_utils import NOTION_PAGE_MAP, log_response, log_user_message, find_latest_section_id, append_summary_to_kb
from async_optimizer import multi_ai_council_parallel
from ai_clients import ask_gpt5, ask_gpt5_mini, ask_gemini_2_5_pro, ask_rekus, ask_lalah
from config_manager import get_config_manager

class GeniusCouncilPlugin(Plugin):
    """AI評議会プラグイン"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.council_engines = config.get("council_engines", ["gpt5", "perplexity", "gemini"])
        self.max_ai_count = config.get("max_ai_count", 5)
        self.parallel_execution = config.get("parallel_execution", True)
        self.synthesis_required = config.get("synthesis_required", True)
        self.council_timeout = config.get("council_timeout", 120)
        self.summary_engine = config.get("summary_engine", "gpt5mini")
        self.synthesis_engine = config.get("synthesis_engine", "mistral_large")  # 最終統合エンジン
        self.enable_critique = config.get("enable_critique", True)

        # 統計
        self.council_sessions = 0
        self.total_execution_time = 0
        self.successful_syntheses = 0

    async def initialize(self) -> bool:
        """プラグイン初期化"""
        try:
            safe_log("🏛️ Genius Council Plugin初期化中", "")

            # 必要なAIエンジンが利用可能かチェック
            available_engines = []
            for engine in self.council_engines:
                # ここでAIエンジンの可用性をチェック（簡単な実装）
                available_engines.append(engine)

            if len(available_engines) < 2:
                safe_log("⚠️ AI評議会には最低2つのAIエンジンが必要です", "")
                return False

            safe_log(f"✅ Genius Council Plugin初期化完了: {len(available_engines)}個のAI利用可能", "")
            return True

        except Exception as e:
            safe_log("🚨 Genius Council Plugin初期化エラー: ", e)
            return False

    async def cleanup(self):
        """プラグインクリーンアップ"""
        safe_log("🧹 Genius Council Plugin クリーンアップ", "")

    @property
    def name(self) -> str:
        return "genius_council"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "AI評議会システム - 複数のAIが協力して高度な分析を実行"

    async def task_execution(self, bot: commands.Bot, message: discord.Message,
                           ai_type: str, context: Dict[str, Any]) -> HookResult:
        """AI評議会メインタスク実行"""
        if ai_type != "genius":
            return HookResult(success=False, error="Not a genius council task")

        start_time = time.time()
        self.council_sessions += 1

        try:
            # Notion設定確認
            thread_id = str(message.channel.id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)

            if not page_ids:
                return HookResult(success=False, error="❌ Notion未連携")

            # Phase 0: ユーザーメッセージをログ記録
            await log_user_message(page_ids[0], message.author.display_name, message.content)

            # Phase 1: 論点整理
            initial_summary = await self._create_initial_summary(bot, message, page_ids[0])
            if not initial_summary:
                return HookResult(success=False, error="❌ 初回要約に失敗")

            # 論点サマリーを送信・保存
            await send_long_message(bot.openai_client, message.channel, f"**{self.summary_engine}による論点サマリー:**\n{initial_summary}")
            await log_response(page_ids[0], f"論点サマリー:\n{initial_summary}", self.summary_engine)

            # Phase 2: AI評議会実行
            council_reports = await self._execute_council_analysis(bot, message.content, initial_summary)

            # Phase 3: 各AI分析を送信・保存
            for ai_name, report in council_reports.items():
                await send_long_message(bot.openai_client, message.channel, f"**分析 by {ai_name}:**\n{report}")
                await log_response(page_ids[0], f"分析 by {ai_name}:\n{report}", ai_name)

            # Phase 4: 統合レポート作成
            if self.synthesis_required:
                final_report = await self._create_synthesis_report(bot, council_reports)
                await send_long_message(bot.openai_client, message.channel, f"**最終統合レポート（by {self.synthesis_engine}）:**\n{final_report}")
                await log_response(page_ids[0], f"最終統合レポート:\n{final_report}", self.synthesis_engine)

                self.successful_syntheses += 1
                response_text = final_report
            else:
                response_text = "\n\n".join([f"**{name}:**\n{report}" for name, report in council_reports.items()])

            # Phase 5: KB用要約保存
            if len(page_ids) >= 2:
                await self._save_kb_summary(bot, response_text, page_ids[1])

            execution_time = time.time() - start_time
            self.total_execution_time += execution_time

            safe_log(f"🏛️ AI評議会完了: ", f"{len(council_reports)}個のAI分析, {execution_time:.2f}s")

            return HookResult(
                success=True,
                modified=True,
                data=response_text,
                execution_time=execution_time
            )

        except Exception as e:
            safe_log("🚨 AI評議会実行エラー: ", e)
            return HookResult(success=False, error=f"AI評議会エラー: {str(e)[:200]}")

    async def _create_initial_summary(self, bot, message, page_id) -> str:
        """初回論点サマリーを作成"""
        try:
            summary = await get_notion_context_for_message(bot, message, page_id, message.content, self.summary_engine)
            return summary or ""
        except Exception as e:
            safe_log("⚠️ 論点サマリー作成エラー: ", e)
            return ""

    async def _execute_council_analysis(self, bot, original_prompt, initial_summary) -> Dict[str, str]:
        """AI評議会分析を実行"""
        council_prompt = f"論点: {initial_summary}\n\n議題「{original_prompt}」を分析してください。"

        try:
            if self.parallel_execution:
                # 最適化された並列処理を使用
                council_reports_raw = await multi_ai_council_parallel(bot, council_prompt, self.council_engines)

                # 結果をマッピング
                council_reports = {}
                for ai_type in self.council_engines:
                    if ai_type in council_reports_raw:
                        ai_display_name = self._get_ai_display_name(ai_type)
                        council_reports[ai_display_name] = council_reports_raw[ai_type]

                safe_log(f"⚡ AI評議会並列処理完了: ", f"{len(council_reports)}個の成功応答")
                return council_reports

            else:
                # 逐次実行（フォールバック）
                return await self._execute_council_sequential(bot, council_prompt)

        except Exception as e:
            safe_log(f"⚠️ AI評議会フォールバック: ", e)
            return await self._execute_council_sequential(bot, council_prompt)

    async def _execute_council_sequential(self, bot, council_prompt) -> Dict[str, str]:
        """AI評議会の逐次実行"""
        tasks = {}

        for ai_type in self.council_engines[:self.max_ai_count]:
            if ai_type == "gpt5":
                tasks["GPT-5"] = ask_gpt5(bot.openai_client, council_prompt)
            elif ai_type == "perplexity":
                tasks["Perplexity"] = ask_rekus(bot.perplexity_api_key, council_prompt)
            elif ai_type == "gemini":
                tasks["Gemini 2.5 Pro"] = ask_gemini_2_5_pro(council_prompt)

        if tasks:
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            return {
                name: (f"エラー: {res}" if isinstance(res, Exception) else res)
                for name, res in zip(tasks.keys(), results)
            }

        return {}

    def _get_ai_display_name(self, ai_type: str) -> str:
        """AIタイプから表示名を取得"""
        display_names = {
            "gpt5": "GPT-5",
            "perplexity": "Perplexity",
            "gemini": "Gemini 2.5 Pro",
            "claude": "Claude",
            "grok": "Grok"
        }
        return display_names.get(ai_type, ai_type)

    async def _create_synthesis_report(self, bot, council_reports) -> str:
        """統合レポートを作成"""
        try:
            synthesis_material = "以下のレポートを統合してください。各AIの見解を整理し、相互補完的な観点から包括的な分析を提供してください。\n\n" + "\n\n".join(
                f"--- [{name}] ---\n{report}" for name, report in council_reports.items()
            )

            # Mistral Largeで最終統合レポートを生成
            if self.synthesis_engine == "mistral_large":
                final_report = await ask_lalah(bot.mistral_client, synthesis_material)
            else:
                # フォールバック: GPT-5を使用
                final_report = await ask_gpt5(bot.openai_client, synthesis_material)

            return final_report or "統合レポートの生成に失敗しました。"

        except Exception as e:
            safe_log("⚠️ 統合レポート作成エラー: ", e)
            # エラー時はGPT-5でフォールバック
            try:
                synthesis_material = "以下のレポートを統合してください。\n\n" + "\n\n".join(
                    f"--- [{name}] ---\n{report}" for name, report in council_reports.items()
                )
                fallback_report = await ask_gpt5(bot.openai_client, synthesis_material)
                return fallback_report or f"統合レポート作成エラー: {str(e)[:100]}"
            except Exception as fallback_e:
                return f"統合レポート作成エラー: {str(e)[:100]}"

    async def _save_kb_summary(self, bot, response_text, log_page_id):
        """KB用要約を保存"""
        try:
            summary_prompt = f"以下のAI評議会最終レポートを150字以内で要約してください。\n\n{response_text}"
            log_summary = await ask_gpt5_mini(bot.openai_client, summary_prompt)

            new_section_id = await find_latest_section_id(log_page_id)
            await append_summary_to_kb(log_page_id, new_section_id, log_summary)

            safe_log("📝 AI評議会KB要約保存完了: ", new_section_id)

        except Exception as e:
            safe_log("⚠️ KB要約保存エラー: ", e)

    async def pre_task_execution(self, bot: commands.Bot, message: discord.Message,
                               ai_type: str, context: Dict[str, Any]) -> HookResult:
        """タスク実行前の前処理"""
        if ai_type == "genius":
            # 重複処理防止の追加チェック
            thread_id = str(message.channel.id)
            if thread_id in bot.processing_channels:
                return HookResult(
                    success=False,
                    error="⏳ AI評議会は既に実行中です...",
                    modified=True
                )

            # processing状態を設定
            bot.processing_channels.add(thread_id)

        return HookResult(success=True, modified=False)

    async def post_task_execution(self, bot: commands.Bot, message: discord.Message,
                                ai_type: str, response: str, context: Dict[str, Any]) -> HookResult:
        """タスク実行後の後処理"""
        if ai_type == "genius":
            # processing状態をクリア
            thread_id = str(message.channel.id)
            bot.processing_channels.discard(thread_id)

        return HookResult(success=True, modified=False, data=response)

    def get_stats(self) -> Dict[str, Any]:
        """プラグイン専用統計"""
        base_stats = super().get_stats()
        avg_execution_time = self.total_execution_time / max(self.council_sessions, 1)
        synthesis_rate = self.successful_syntheses / max(self.council_sessions, 1)

        base_stats.update({
            "council_sessions": self.council_sessions,
            "avg_session_time": f"{avg_execution_time:.2f}s",
            "successful_syntheses": self.successful_syntheses,
            "synthesis_success_rate": f"{synthesis_rate:.1%}",
            "council_engines": self.council_engines,
            "max_ai_count": self.max_ai_count
        })

        return base_stats