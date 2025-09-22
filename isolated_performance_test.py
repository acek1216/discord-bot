# -*- coding: utf-8 -*-
"""
独立パフォーマンステスト（依存関係なし）
拡張キャッシュシステムの効果を測定
"""

import asyncio
import time
import statistics
import threading
import hashlib
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from collections import OrderedDict

# ログ機能の簡単な実装
def safe_log(prefix: str, message: str = ""):
    """安全なログ出力"""
    try:
        print(f"{prefix} {message}")
    except UnicodeEncodeError:
        # Unicodeエラーを回避
        print(f"{prefix.encode('ascii', 'ignore').decode()} {str(message).encode('ascii', 'ignore').decode()}")

@dataclass
class EnhancedCacheEntry:
    """拡張キャッシュエントリ"""
    data: Any
    timestamp: float = field(default_factory=time.time)
    hit_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    cache_type: str = "generic"
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CachePerformanceStats:
    """キャッシュパフォーマンス統計"""
    hit_count: int = 0
    miss_count: int = 0
    total_entries: int = 0
    memory_usage_mb: float = 0.0
    hit_rate: float = 0.0
    avg_response_time_saved: float = 0.0
    cache_types: Dict[str, int] = field(default_factory=dict)

class EnhancedCacheManager:
    """統合キャッシュマネージャー（独立版）"""

    def __init__(
        self,
        notion_ttl: int = 300,
        context_ttl: int = 180,
        ai_response_ttl: int = 900,
        max_entries: int = 500
    ):
        self.ttl_settings = {
            "notion": notion_ttl,
            "context": context_ttl,
            "ai_response": ai_response_ttl,
            "generic": 300
        }
        self.max_entries = max_entries
        self.cache: OrderedDict[str, EnhancedCacheEntry] = OrderedDict()
        self.lock = threading.RLock()

        # パフォーマンス統計
        self.stats = CachePerformanceStats()
        self.total_response_time_saved = 0.0

        # 自動クリーンアップ
        self.last_cleanup = time.time()
        self.cleanup_interval = 60

    def _generate_cache_key(
        self,
        cache_type: str,
        key_data: Union[str, List[str], Dict[str, Any]]
    ) -> str:
        """汎用キャッシュキー生成"""
        if isinstance(key_data, str):
            base_key = key_data
        elif isinstance(key_data, list):
            base_key = "|".join(sorted(str(item) for item in key_data))
        elif isinstance(key_data, dict):
            base_key = json.dumps(key_data, sort_keys=True)
        else:
            base_key = str(key_data)

        full_key = f"{cache_type}:{base_key}"
        return hashlib.sha256(full_key.encode()).hexdigest()[:16]

    def _is_expired(self, entry: EnhancedCacheEntry) -> bool:
        """エントリの期限切れチェック"""
        ttl = self.ttl_settings.get(entry.cache_type, self.ttl_settings["generic"])
        return (time.time() - entry.timestamp) > ttl

    def _cleanup_expired(self) -> int:
        """期限切れエントリの自動クリーンアップ"""
        with self.lock:
            current_time = time.time()

            if current_time - self.last_cleanup < self.cleanup_interval:
                return 0

            expired_keys = [
                key for key, entry in self.cache.items()
                if self._is_expired(entry)
            ]

            for key in expired_keys:
                del self.cache[key]

            self.last_cleanup = current_time

            if expired_keys:
                safe_log(f"クリーンアップ完了: {len(expired_keys)}件削除")

            return len(expired_keys)

    def _evict_lru(self) -> None:
        """LRU方式での領域確保"""
        with self.lock:
            while len(self.cache) >= self.max_entries:
                oldest_key, _ = self.cache.popitem(last=False)

    async def get_cached(
        self,
        cache_type: str,
        key_data: Union[str, List[str], Dict[str, Any]],
        fetch_func=None,
        **fetch_kwargs
    ) -> Optional[Any]:
        """汎用キャッシュ取得"""
        cache_key = self._generate_cache_key(cache_type, key_data)
        start_time = time.time()

        # クリーンアップ実行
        self._cleanup_expired()

        with self.lock:
            if cache_key in self.cache:
                entry = self.cache[cache_key]

                if not self._is_expired(entry):
                    # キャッシュヒット
                    entry.hit_count += 1
                    entry.last_accessed = time.time()
                    self.stats.hit_count += 1

                    # LRUのため最後に移動
                    self.cache.move_to_end(cache_key)

                    response_time_saved = time.time() - start_time
                    self.total_response_time_saved += response_time_saved

                    safe_log(f"キャッシュヒット ({cache_type}): 節約時間 {response_time_saved:.3f}s")
                    return entry.data
                else:
                    # 期限切れエントリを削除
                    del self.cache[cache_key]

            # キャッシュミス
            self.stats.miss_count += 1

            if fetch_func:
                # データを取得してキャッシュ
                if asyncio.iscoroutinefunction(fetch_func):
                    data = await fetch_func(**fetch_kwargs)
                else:
                    data = fetch_func(**fetch_kwargs)

                await self.set_cached(cache_type, key_data, data)
                return data

            return None

    async def set_cached(
        self,
        cache_type: str,
        key_data: Union[str, List[str], Dict[str, Any]],
        data: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """キャッシュにデータを保存"""
        cache_key = self._generate_cache_key(cache_type, key_data)

        with self.lock:
            # 領域確保
            self._evict_lru()

            entry = EnhancedCacheEntry(
                data=data,
                cache_type=cache_type,
                metadata=metadata or {}
            )

            self.cache[cache_key] = entry
            self.stats.total_entries = len(self.cache)

            # 統計更新
            if cache_type not in self.stats.cache_types:
                self.stats.cache_types[cache_type] = 0
            self.stats.cache_types[cache_type] += 1

    def invalidate_cache(self, cache_type: Optional[str] = None) -> int:
        """キャッシュ無効化"""
        with self.lock:
            if cache_type:
                # 特定タイプのみ削除
                keys_to_delete = [
                    key for key, entry in self.cache.items()
                    if entry.cache_type == cache_type
                ]
                for key in keys_to_delete:
                    del self.cache[key]
                return len(keys_to_delete)
            else:
                # 全削除
                count = len(self.cache)
                self.cache.clear()
                return count

    def get_performance_stats(self) -> CachePerformanceStats:
        """パフォーマンス統計を取得"""
        with self.lock:
            total_requests = self.stats.hit_count + self.stats.miss_count
            self.stats.hit_rate = (
                self.stats.hit_count / total_requests * 100
                if total_requests > 0 else 0.0
            )
            self.stats.avg_response_time_saved = (
                self.total_response_time_saved / self.stats.hit_count
                if self.stats.hit_count > 0 else 0.0
            )
            self.stats.total_entries = len(self.cache)

            return self.stats

    def get_detailed_stats(self) -> Dict[str, Any]:
        """詳細統計情報"""
        stats = self.get_performance_stats()

        return {
            "cache_performance": {
                "hit_rate": f"{stats.hit_rate:.1f}%",
                "total_hits": stats.hit_count,
                "total_misses": stats.miss_count,
                "avg_time_saved_per_hit": f"{stats.avg_response_time_saved:.3f}s",
                "total_time_saved": f"{self.total_response_time_saved:.3f}s"
            },
            "cache_entries": {
                "total": stats.total_entries,
                "max_capacity": self.max_entries,
                "utilization": f"{(stats.total_entries / self.max_entries * 100):.1f}%",
                "by_type": stats.cache_types
            }
        }

# シミュレーション関数群
async def simulate_notion_fetch(page_ids: List[str]) -> str:
    """Notion API呼び出しをシミュレート"""
    await asyncio.sleep(0.2)  # 200ms遅延
    return f"Notionページテキスト（{len(page_ids)}ページ）"

async def simulate_context_fetch(page_id: str, query: str, engine: str) -> str:
    """コンテキスト取得をシミュレート"""
    await asyncio.sleep(0.3)  # 300ms遅延
    return f"コンテキストデータ（{engine}）: {query}の結果"

async def simulate_ai_response(ai_type: str, prompt_hash: str) -> str:
    """AI応答をシミュレート"""
    await asyncio.sleep(0.8)  # 800ms遅延
    return f"AI応答（{ai_type}）: プロンプト{prompt_hash}への回答"

# テスト関数群
async def test_notion_cache_performance(cache_manager: EnhancedCacheManager) -> Dict[str, Any]:
    """Notionキャッシュのパフォーマンステスト"""
    page_ids = ["page-1", "page-2", "page-3"]

    # キャッシュなし（初回）の測定
    uncached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_cached(
            "notion",
            page_ids,
            simulate_notion_fetch,
            page_ids=page_ids
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)
        cache_manager.invalidate_cache("notion")
        await asyncio.sleep(0.1)

    # キャッシュあり（ヒット）の測定
    await cache_manager.get_cached("notion", page_ids, simulate_notion_fetch, page_ids=page_ids)

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_cached(
            "notion",
            page_ids,
            simulate_notion_fetch,
            page_ids=page_ids
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def test_context_cache_performance(cache_manager: EnhancedCacheManager) -> Dict[str, Any]:
    """コンテキストキャッシュのパフォーマンステスト"""
    key_data = {
        "page_id": "context-page-1",
        "query_hash": hashlib.md5("テストクエリ".encode()).hexdigest()[:8],
        "engine": "gpt4o"
    }

    # キャッシュなしの測定
    uncached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_cached(
            "context",
            key_data,
            simulate_context_fetch,
            page_id="context-page-1", query="テストクエリ", engine="gpt4o"
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)
        cache_manager.invalidate_cache("context")
        await asyncio.sleep(0.1)

    # キャッシュありの測定
    await cache_manager.get_cached(
        "context", key_data, simulate_context_fetch,
        page_id="context-page-1", query="テストクエリ", engine="gpt4o"
    )

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_cached(
            "context", key_data, simulate_context_fetch,
            page_id="context-page-1", query="テストクエリ", engine="gpt4o"
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def test_ai_response_cache_performance(cache_manager: EnhancedCacheManager) -> Dict[str, Any]:
    """AI応答キャッシュのパフォーマンステスト"""
    key_data = {
        "ai_type": "gpt4o",
        "prompt_hash": "test_prompt_hash_123"
    }

    # キャッシュなしの測定
    uncached_times = []
    for i in range(3):  # AI応答は重いので3回のみ
        start_time = time.time()
        result = await cache_manager.get_cached(
            "ai_response",
            key_data,
            simulate_ai_response,
            ai_type="gpt4o", prompt_hash="test_prompt_hash_123"
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)
        cache_manager.invalidate_cache("ai_response")
        await asyncio.sleep(0.1)

    # キャッシュありの測定
    await cache_manager.get_cached(
        "ai_response", key_data, simulate_ai_response,
        ai_type="gpt4o", prompt_hash="test_prompt_hash_123"
    )

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_cached(
            "ai_response", key_data, simulate_ai_response,
            ai_type="gpt4o", prompt_hash="test_prompt_hash_123"
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def comprehensive_performance_test():
    """総合パフォーマンステスト"""
    print("キャッシュパフォーマンステスト開始")
    print("=" * 50)

    # キャッシュマネージャー初期化
    cache_manager = EnhancedCacheManager()

    # Notionキャッシュテスト
    print("Notionキャッシュテスト実行中...")
    notion_results = await test_notion_cache_performance(cache_manager)

    # コンテキストキャッシュテスト
    print("コンテキストキャッシュテスト実行中...")
    context_results = await test_context_cache_performance(cache_manager)

    # AI応答キャッシュテスト
    print("AI応答キャッシュテスト実行中...")
    ai_results = await test_ai_response_cache_performance(cache_manager)

    # 結果レポート
    print("\n" + "=" * 50)
    print("パフォーマンステスト結果レポート")
    print("=" * 50)

    print(f"\nNotionキャッシュ:")
    print(f"  キャッシュなし平均: {notion_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {notion_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {notion_results['improvement_ratio']:.1f}%")

    print(f"\nコンテキストキャッシュ:")
    print(f"  キャッシュなし平均: {context_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {context_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {context_results['improvement_ratio']:.1f}%")

    print(f"\nAI応答キャッシュ:")
    print(f"  キャッシュなし平均: {ai_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {ai_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {ai_results['improvement_ratio']:.1f}%")

    # 総合評価
    overall_improvement = (
        notion_results['improvement_ratio'] +
        context_results['improvement_ratio'] +
        ai_results['improvement_ratio']
    ) / 3

    print("\n" + "=" * 50)
    print(f"総合パフォーマンス向上率: {overall_improvement:.1f}%")

    if overall_improvement >= 30:
        print("目標の30%性能向上を達成しました！")
    else:
        print(f"目標の30%に対して {overall_improvement:.1f}% の向上")

    # キャッシュ統計情報
    detailed_stats = cache_manager.get_detailed_stats()

    print(f"\nキャッシュ統計詳細:")
    print(f"  ヒット率: {detailed_stats['cache_performance']['hit_rate']}")
    print(f"  総ヒット数: {detailed_stats['cache_performance']['total_hits']}")
    print(f"  総ミス数: {detailed_stats['cache_performance']['total_misses']}")
    print(f"  ヒット当たり節約時間: {detailed_stats['cache_performance']['avg_time_saved_per_hit']}")
    print(f"  総節約時間: {detailed_stats['cache_performance']['total_time_saved']}")

    print(f"  総エントリ数: {detailed_stats['cache_entries']['total']}")
    print(f"  キャッシュ利用率: {detailed_stats['cache_entries']['utilization']}")
    print(f"  タイプ別エントリ数: {detailed_stats['cache_entries']['by_type']}")

    return overall_improvement

if __name__ == "__main__":
    asyncio.run(comprehensive_performance_test())