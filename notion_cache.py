# -*- coding: utf-8 -*-
"""
Notionキャッシュシステム
Notionページの取得を最適化するキャッシュ機構
"""

import time
import threading
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
from utils import safe_log

@dataclass
class CacheEntry:
    """キャッシュエントリ"""
    data: str
    timestamp: float = field(default_factory=time.time)
    hit_count: int = 0
    last_accessed: float = field(default_factory=time.time)

@dataclass
class CacheStats:
    """キャッシュ統計"""
    hit_count: int = 0
    miss_count: int = 0
    total_entries: int = 0
    memory_usage_mb: float = 0.0
    hit_rate: float = 0.0
    avg_response_time: float = 0.0

class NotionCache:
    """Notionページキャッシュシステム"""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 100):
        """
        Args:
            ttl_seconds: キャッシュの有効期限（秒）
            max_entries: 最大キャッシュエントリ数
        """
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = threading.RLock()

        # 統計
        self.hit_count = 0
        self.miss_count = 0
        self.total_response_time = 0.0
        self.cleanup_count = 0

        # 自動クリーンアップ設定
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # 1分間隔

    def _generate_cache_key(self, page_ids: List[str], extra_params: Optional[str] = None) -> str:
        """キャッシュキーを生成"""
        base_key = "|".join(sorted(page_ids))
        if extra_params:
            base_key += f"#{extra_params}"

        # ハッシュ化してキーを短縮
        return hashlib.md5(base_key.encode()).hexdigest()

    def _is_expired(self, entry: CacheEntry) -> bool:
        """エントリが期限切れかチェック"""
        return (time.time() - entry.timestamp) > self.ttl_seconds

    def _cleanup_expired(self) -> int:
        """期限切れエントリをクリーンアップ"""
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
            self.cleanup_count += 1

            if expired_keys:
                safe_log(f"🧹 Notionキャッシュクリーンアップ: ", f"{len(expired_keys)}件削除")

            return len(expired_keys)

    def _evict_lru(self) -> None:
        """LRU方式で古いエントリを削除"""
        with self.lock:
            while len(self.cache) >= self.max_entries:
                # OrderedDictの最初のエントリ（最も古い）を削除
                oldest_key, _ = self.cache.popitem(last=False)
                safe_log("💾 Notionキャッシュ容量制限: ", f"LRU削除 {oldest_key[:8]}...")

    async def get_cached_page_text(self, page_ids: List[str],
                                 fallback_func,
                                 extra_params: Optional[str] = None) -> str:
        """
        キャッシュ付きでNotionページテキストを取得

        Args:
            page_ids: ページIDのリスト
            fallback_func: キャッシュミス時の取得関数
            extra_params: 追加のキャッシュキーパラメータ

        Returns:
            ページテキスト
        """
        cache_key = self._generate_cache_key(page_ids, extra_params)
        start_time = time.time()

        # クリーンアップ実行
        self._cleanup_expired()

        with self.lock:
            # キャッシュヒット確認
            if cache_key in self.cache:
                entry = self.cache[cache_key]

                if not self._is_expired(entry):
                    # キャッシュヒット
                    entry.hit_count += 1
                    entry.last_accessed = time.time()
                    self.hit_count += 1

                    # 最近使用したものを最後に移動（LRU更新）
                    self.cache.move_to_end(cache_key)

                    response_time = time.time() - start_time
                    self.total_response_time += response_time

                    safe_log(f"🎯 Notionキャッシュヒット: ",
                            f"{cache_key[:8]}... ({response_time:.3f}s)")

                    return entry.data
                else:
                    # 期限切れエントリを削除
                    del self.cache[cache_key]

        # キャッシュミス：実際にデータを取得
        self.miss_count += 1
        safe_log(f"❌ Notionキャッシュミス: ", f"{cache_key[:8]}... ページ取得中")

        try:
            # フォールバック関数でデータ取得
            data = await fallback_func(page_ids)

            if data and not data.startswith("ERROR:"):
                # キャッシュに保存
                with self.lock:
                    # 容量制限確認
                    self._evict_lru()

                    # 新しいエントリを追加
                    self.cache[cache_key] = CacheEntry(
                        data=data,
                        timestamp=time.time()
                    )

                response_time = time.time() - start_time
                self.total_response_time += response_time

                safe_log(f"💾 Notionキャッシュ保存: ",
                        f"{cache_key[:8]}... ({len(data)}文字, {response_time:.3f}s)")

            return data

        except Exception as e:
            safe_log(f"🚨 Notionキャッシュ取得エラー: ", e)
            return f"ERROR: キャッシュ取得失敗 - {str(e)[:100]}"

    def get_cache_stats(self) -> CacheStats:
        """キャッシュ統計を取得"""
        with self.lock:
            total_requests = self.hit_count + self.miss_count
            hit_rate = (self.hit_count / total_requests) if total_requests > 0 else 0.0
            avg_response_time = (self.total_response_time / total_requests) if total_requests > 0 else 0.0

            # メモリ使用量推定（文字数ベース）
            memory_usage = sum(len(entry.data) for entry in self.cache.values())
            memory_usage_mb = memory_usage * 2 / (1024 * 1024)  # UTF-8で約2バイト/文字

            return CacheStats(
                hit_count=self.hit_count,
                miss_count=self.miss_count,
                total_entries=len(self.cache),
                memory_usage_mb=memory_usage_mb,
                hit_rate=hit_rate,
                avg_response_time=avg_response_time
            )

    async def clear_cache(self) -> int:
        """キャッシュをクリア"""
        with self.lock:
            cleared_count = len(self.cache)
            self.cache.clear()
            safe_log(f"🗑️ Notionキャッシュクリア: ", f"{cleared_count}件削除")
            return cleared_count

    def get_detailed_stats(self) -> Dict[str, Any]:
        """詳細統計を取得"""
        stats = self.get_cache_stats()

        with self.lock:
            entry_details = {}
            for key, entry in list(self.cache.items())[:10]:  # 上位10件のみ表示
                entry_details[key[:8]] = {
                    "data_length": len(entry.data),
                    "hit_count": entry.hit_count,
                    "age_seconds": int(time.time() - entry.timestamp),
                    "is_expired": self._is_expired(entry)
                }

        return {
            "summary": {
                "hit_rate": f"{stats.hit_rate:.1%}",
                "total_entries": stats.total_entries,
                "memory_usage_mb": round(stats.memory_usage_mb, 2),
                "avg_response_time": f"{stats.avg_response_time:.3f}s",
                "cleanup_count": self.cleanup_count
            },
            "config": {
                "ttl_seconds": self.ttl_seconds,
                "max_entries": self.max_entries,
                "cleanup_interval": self.cleanup_interval
            },
            "sample_entries": entry_details
        }

    def preload_cache(self, page_id: str, data: str) -> None:
        """キャッシュを事前に設定（テスト用）"""
        with self.lock:
            cache_key = self._generate_cache_key([page_id])
            self._evict_lru()
            self.cache[cache_key] = CacheEntry(data=data)
            safe_log(f"🔄 Notionキャッシュ事前設定: ", f"{cache_key[:8]}...")


# グローバルキャッシュインスタンス
_notion_cache: Optional[NotionCache] = None

def get_notion_cache(ttl_seconds: int = 300) -> NotionCache:
    """Notionキャッシュインスタンスを取得（シングルトン）"""
    global _notion_cache
    if _notion_cache is None:
        _notion_cache = NotionCache(ttl_seconds=ttl_seconds)
        safe_log("✅ Notionキャッシュ初期化完了", f"TTL: {ttl_seconds}秒")
    return _notion_cache

def clear_notion_cache():
    """キャッシュをリセット（テスト用）"""
    global _notion_cache
    _notion_cache = None