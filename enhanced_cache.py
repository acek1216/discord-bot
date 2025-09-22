# -*- coding: utf-8 -*-
"""
拡張キャッシュマネージャー
Notion、AI応答、コンテキスト取得を統合キャッシュで高速化
応答速度30%向上を目標とした最適化システム
"""

import time
import threading
import hashlib
import asyncio
import json
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from collections import OrderedDict
from utils import safe_log

@dataclass
class EnhancedCacheEntry:
    """拡張キャッシュエントリ"""
    data: Any
    timestamp: float = field(default_factory=time.time)
    hit_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    cache_type: str = "generic"  # notion, context, ai_response
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
    """統合キャッシュマネージャー"""

    def __init__(
        self,
        notion_ttl: Optional[int] = None,
        context_ttl: Optional[int] = None,
        ai_response_ttl: Optional[int] = None,
        max_entries: Optional[int] = None,
        use_config: bool = True
    ):
        """
        Args:
            notion_ttl: Notionキャッシュ有効期限（秒）
            context_ttl: コンテキストキャッシュ有効期限（秒）
            ai_response_ttl: AI応答キャッシュ有効期限（秒）
            max_entries: 最大キャッシュエントリ数
            use_config: 外部設定ファイルを使用するか
        """
        # 外部設定ファイルから設定を読み込み（初回のみ）
        if use_config:
            try:
                from config_manager import get_config_manager
                config_manager = get_config_manager()
                cache_config = config_manager.get_cache_config()

                # 引数が指定されていない場合は設定ファイルから取得
                notion_ttl = notion_ttl if notion_ttl is not None else cache_config.notion_ttl
                context_ttl = context_ttl if context_ttl is not None else cache_config.context_ttl
                ai_response_ttl = ai_response_ttl if ai_response_ttl is not None else cache_config.ai_response_ttl
                max_entries = max_entries if max_entries is not None else cache_config.max_entries

                safe_log("📁 キャッシュ設定を外部ファイルから読み込み", "")
            except ImportError:
                # config_managerが使用できない場合はデフォルト値
                safe_log("⚠️ 設定ファイル読み込み失敗、デフォルト値を使用", "")
                notion_ttl = notion_ttl if notion_ttl is not None else 300
                context_ttl = context_ttl if context_ttl is not None else 180
                ai_response_ttl = ai_response_ttl if ai_response_ttl is not None else 900
                max_entries = max_entries if max_entries is not None else 500
        else:
            # デフォルト値を使用
            notion_ttl = notion_ttl if notion_ttl is not None else 300
            context_ttl = context_ttl if context_ttl is not None else 180
            ai_response_ttl = ai_response_ttl if ai_response_ttl is not None else 900
            max_entries = max_entries if max_entries is not None else 500

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

        # キャッシュタイプとベースキーを組み合わせ
        full_key = f"{cache_type}:{base_key}"
        return hashlib.sha256(full_key.encode()).hexdigest()[:16]  # 短縮

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
                safe_log(f"🧹 拡張キャッシュクリーンアップ: ", f"{len(expired_keys)}件削除")

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

                    safe_log(f"⚡ キャッシュヒット ({cache_type}): ", f"キー:{cache_key[:8]}... 節約:{response_time_saved:.3f}s")
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

    async def get_notion_cached(
        self,
        page_ids: List[str],
        fetch_func,
        **kwargs
    ) -> Any:
        """Notion専用キャッシュ"""
        return await self.get_cached(
            "notion",
            page_ids,
            fetch_func,
            **kwargs
        )

    async def get_context_cached(
        self,
        page_id: str,
        query: str,
        engine: str,
        fetch_func,
        **kwargs
    ) -> Any:
        """コンテキスト取得専用キャッシュ"""
        key_data = {
            "page_id": page_id,
            "query_hash": hashlib.md5(query.encode()).hexdigest()[:8],
            "engine": engine
        }

        return await self.get_cached(
            "context",
            key_data,
            fetch_func,
            **kwargs
        )

    async def get_ai_response_cached(
        self,
        ai_type: str,
        prompt_hash: str,
        fetch_func,
        **kwargs
    ) -> Any:
        """AI応答専用キャッシュ"""
        key_data = {
            "ai_type": ai_type,
            "prompt_hash": prompt_hash
        }

        return await self.get_cached(
            "ai_response",
            key_data,
            fetch_func,
            **kwargs
        )

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
            },
            "configuration": {
                "ttl_settings": self.ttl_settings,
                "cleanup_interval": f"{self.cleanup_interval}s"
            }
        }

# グローバルキャッシュマネージャーインスタンス
_cache_manager: Optional[EnhancedCacheManager] = None

def get_cache_manager() -> EnhancedCacheManager:
    """グローバルキャッシュマネージャーを取得"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = EnhancedCacheManager()
        safe_log("✅ 拡張キャッシュマネージャー初期化完了", "")
    return _cache_manager