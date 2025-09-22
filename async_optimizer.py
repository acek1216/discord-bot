# -*- coding: utf-8 -*-
"""
非同期処理最適化システム
asyncio.gatherを活用した並列処理の改善
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass
from utils import safe_log

@dataclass
class AsyncTask:
    """非同期タスクの定義"""
    name: str
    coro: Callable
    args: tuple = ()
    kwargs: dict = None
    timeout: Optional[float] = None
    required: bool = True  # 必須タスクかどうか

    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}

@dataclass
class AsyncResult:
    """非同期タスクの結果"""
    name: str
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    duration: float = 0.0

class AsyncOptimizer:
    """非同期処理最適化クラス"""

    def __init__(self):
        self.total_tasks = 0
        self.total_time_saved = 0.0
        self.execution_count = 0

    async def execute_parallel(self, tasks: List[AsyncTask]) -> Dict[str, AsyncResult]:
        """複数タスクを並列実行"""
        if not tasks:
            return {}

        start_time = time.time()
        self.execution_count += 1
        self.total_tasks += len(tasks)

        # タスクを非同期実行用に準備
        async_tasks = []
        task_info = {}

        for task in tasks:
            # タイムアウト付きタスクの作成
            if task.timeout:
                coro = asyncio.wait_for(
                    task.coro(*task.args, **task.kwargs),
                    timeout=task.timeout
                )
            else:
                coro = task.coro(*task.args, **task.kwargs)

            async_task = asyncio.create_task(coro, name=task.name)
            async_tasks.append(async_task)
            task_info[task.name] = task

        # 並列実行
        safe_log(f"🚀 並列実行開始: ", f"{len(tasks)}個のタスク")

        results = {}
        try:
            # return_exceptions=Trueで例外も結果として取得
            raw_results = await asyncio.gather(*async_tasks, return_exceptions=True)

            # 結果の処理
            for i, (task_name, raw_result) in enumerate(zip([t.name for t in tasks], raw_results)):
                task_start = time.time()

                if isinstance(raw_result, Exception):
                    # エラーの場合
                    task_required = task_info[task_name].required
                    error_msg = str(raw_result)

                    results[task_name] = AsyncResult(
                        name=task_name,
                        success=False,
                        error=raw_result,
                        duration=0.0
                    )

                    if task_required:
                        safe_log(f"🚨 必須タスクエラー: ", f"{task_name} - {error_msg[:100]}")
                    else:
                        safe_log(f"⚠️ オプションタスクエラー: ", f"{task_name} - {error_msg[:50]}")
                else:
                    # 成功の場合
                    results[task_name] = AsyncResult(
                        name=task_name,
                        success=True,
                        result=raw_result,
                        duration=time.time() - task_start
                    )

        except Exception as e:
            safe_log(f"🚨 並列実行で予期しないエラー: ", e)
            # フォールバック：個別実行
            results = await self._fallback_sequential(tasks)

        end_time = time.time()
        total_duration = end_time - start_time

        # 統計更新
        estimated_sequential_time = sum(0.5 for _ in tasks)  # 推定逐次実行時間
        time_saved = max(0, estimated_sequential_time - total_duration)
        self.total_time_saved += time_saved

        safe_log(f"✅ 並列実行完了: ",
                f"{len(tasks)}タスク、{total_duration:.2f}秒、推定短縮:{time_saved:.2f}秒")

        return results

    async def _fallback_sequential(self, tasks: List[AsyncTask]) -> Dict[str, AsyncResult]:
        """フォールバック：逐次実行"""
        safe_log("🔄 フォールバック逐次実行: ", f"{len(tasks)}タスク")

        results = {}
        for task in tasks:
            start_time = time.time()
            try:
                if task.timeout:
                    result = await asyncio.wait_for(
                        task.coro(*task.args, **task.kwargs),
                        timeout=task.timeout
                    )
                else:
                    result = await task.coro(*task.args, **task.kwargs)

                results[task.name] = AsyncResult(
                    name=task.name,
                    success=True,
                    result=result,
                    duration=time.time() - start_time
                )
            except Exception as e:
                results[task.name] = AsyncResult(
                    name=task.name,
                    success=False,
                    error=e,
                    duration=time.time() - start_time
                )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """最適化統計を取得"""
        avg_tasks = self.total_tasks / max(self.execution_count, 1)
        return {
            "execution_count": self.execution_count,
            "total_tasks": self.total_tasks,
            "avg_tasks_per_execution": round(avg_tasks, 1),
            "total_time_saved": round(self.total_time_saved, 2),
            "avg_time_saved": round(self.total_time_saved / max(self.execution_count, 1), 2)
        }

# 具体的な最適化関数群

async def get_notion_contexts_parallel(bot, message, page_ids: List[str], query: str) -> Dict[str, str]:
    """Notionコンテキストを並列取得"""
    from notion_utils import get_notion_page_text
    from utils import get_notion_context_for_message

    if not page_ids:
        return {}

    optimizer = AsyncOptimizer()
    tasks = []

    # 複数ページの並列取得
    for i, page_id in enumerate(page_ids):
        task_name = f"notion_page_{i}"
        if i == 0:
            # メインページ（ログ用）
            tasks.append(AsyncTask(
                name=task_name,
                coro=get_notion_page_text,
                args=([page_id],),
                timeout=10.0,
                required=True
            ))
        else:
            # KBページ（要約付き）
            tasks.append(AsyncTask(
                name=f"notion_context_{i}",
                coro=get_notion_context_for_message,
                args=(bot, message, page_id, query, "gpt5mini"),
                timeout=15.0,
                required=False
            ))

    results = await optimizer.execute_parallel(tasks)

    # 結果をまとめる
    contexts = {}
    for task_name, result in results.items():
        if result.success:
            contexts[task_name] = result.result
        else:
            contexts[task_name] = ""

    return contexts

async def analyze_attachment_parallel(bot, attachments) -> List[str]:
    """添付ファイルを並列解析"""
    from utils import analyze_attachment_for_gpt5

    if not attachments:
        return []

    optimizer = AsyncOptimizer()
    tasks = []

    for i, attachment in enumerate(attachments[:3]):  # 最大3つまで
        tasks.append(AsyncTask(
            name=f"attachment_{i}",
            coro=analyze_attachment_for_gpt5,
            args=(bot.openai_client, attachment),
            timeout=20.0,
            required=False
        ))

    results = await optimizer.execute_parallel(tasks)

    # 成功した解析結果のみ返す
    analyses = []
    for result in results.values():
        if result.success and result.result:
            analyses.append(result.result)

    return analyses

async def multi_ai_council_parallel(bot, prompt: str, ai_types: List[str]) -> Dict[str, str]:
    """複数AIに並列で同じ質問"""
    from ai_manager import get_ai_manager

    ai_manager = get_ai_manager()
    if not ai_manager.initialized:
        ai_manager.initialize(bot)

    optimizer = AsyncOptimizer()
    tasks = []

    for ai_type in ai_types:
        if ai_type in ai_manager.get_available_ais():
            tasks.append(AsyncTask(
                name=f"ai_{ai_type}",
                coro=ai_manager.ask_ai,
                args=(ai_type, prompt),
                timeout=30.0,
                required=False
            ))

    results = await optimizer.execute_parallel(tasks)

    # AI名をキーとした結果辞書
    ai_responses = {}
    for task_name, result in results.items():
        ai_name = task_name.replace("ai_", "")
        if result.success:
            ai_responses[ai_name] = result.result
        else:
            ai_responses[ai_name] = f"エラー: {result.error}"

    return ai_responses

async def process_with_parallel_context(bot, message, page_ids: List[str], ai_type: str) -> Dict[str, Any]:
    """メッセージ処理用の最適化された並列処理"""
    optimizer = AsyncOptimizer()
    tasks = []

    # 1. Notionコンテキスト取得
    if page_ids:
        from utils import get_notion_context_for_message

        # KB用ページ（要約付き）
        if len(page_ids) > 1:
            tasks.append(AsyncTask(
                name="kb_context",
                coro=get_notion_context_for_message,
                args=(bot, message, page_ids[1], message.content, "gpt5mini"),
                timeout=10.0,
                required=False
            ))

        # ログ用ページ（生テキスト）
        from notion_utils import get_notion_page_text
        tasks.append(AsyncTask(
            name="log_context",
            coro=get_notion_page_text,
            args=([page_ids[0]],),
            timeout=8.0,
            required=False
        ))

    # 2. 添付ファイル解析
    if message.attachments:
        tasks.append(AsyncTask(
            name="attachment_analysis",
            coro=analyze_attachment_parallel,
            args=(bot, message.attachments),
            timeout=15.0,
            required=False
        ))

    # 3. メモリ取得（非同期化可能な場合）
    from memory_manager import get_memory_manager
    from notion_utils import get_memory_flag_from_notion

    tasks.append(AsyncTask(
        name="memory_flag",
        coro=get_memory_flag_from_notion,
        args=(str(message.channel.id),),
        timeout=5.0,
        required=False
    ))

    # 並列実行
    results = await optimizer.execute_parallel(tasks)

    # 結果の整理
    context_data = {
        "kb_context": results.get("kb_context", AsyncResult("kb_context", False)).result or "",
        "log_context": results.get("log_context", AsyncResult("log_context", False)).result or "",
        "attachment_analyses": results.get("attachment_analysis", AsyncResult("attachment_analysis", False)).result or [],
        "is_memory_on": results.get("memory_flag", AsyncResult("memory_flag", False)).result or False,
        "optimizer_stats": optimizer.get_stats()
    }

    return context_data

# グローバル最適化統計
global_optimizer_stats = {
    "total_optimizations": 0,
    "total_time_saved": 0.0
}

def get_global_optimization_stats() -> Dict[str, Any]:
    """グローバル最適化統計を取得"""
    return global_optimizer_stats.copy()

def update_global_stats(time_saved: float):
    """グローバル統計を更新"""
    global_optimizer_stats["total_optimizations"] += 1
    global_optimizer_stats["total_time_saved"] += time_saved