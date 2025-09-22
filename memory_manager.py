# -*- coding: utf-8 -*-
"""
統一メモリ管理システム
AIの会話履歴を効率的に管理
"""

import time
import threading
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from utils import safe_log

@dataclass
class MemoryEntry:
    """メモリエントリの定義"""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class MemoryStats:
    """メモリ統計情報"""
    total_entries: int = 0
    total_channels: int = 0
    total_ais: int = 0
    oldest_entry: Optional[float] = None
    newest_entry: Optional[float] = None
    memory_size_mb: float = 0.0

class ChannelMemory:
    """チャンネル別メモリ管理"""

    def __init__(self, max_history: int = 10, ttl_hours: int = 24):
        self.max_history = max_history  # 最大保持エントリ数（往復数 x 2）
        self.ttl_seconds = ttl_hours * 3600  # TTL（秒）
        self.entries: deque = deque(maxlen=max_history)
        self.created_at = time.time()
        self.last_accessed = time.time()
        self.access_count = 0

    def add_interaction(self, user_content: str, ai_response: str, metadata: Optional[Dict] = None) -> None:
        """ユーザーとAIのやり取りを追加"""
        current_time = time.time()

        # ユーザーメッセージ
        user_entry = MemoryEntry(
            role="user",
            content=user_content,
            timestamp=current_time,
            metadata=metadata
        )

        # AI応答
        ai_entry = MemoryEntry(
            role="assistant",
            content=ai_response,
            timestamp=current_time,
            metadata=metadata
        )

        self.entries.extend([user_entry, ai_entry])
        self.last_accessed = current_time
        self.access_count += 1

    def get_history(self, include_metadata: bool = False) -> List[Dict[str, str]]:
        """履歴を取得（OpenAI形式）"""
        self.last_accessed = time.time()
        self.access_count += 1

        result = []
        for entry in self.entries:
            item = {"role": entry.role, "content": entry.content}
            if include_metadata and entry.metadata:
                item["metadata"] = entry.metadata
            result.append(item)

        return result

    def get_history_text(self) -> str:
        """履歴をテキスト形式で取得"""
        self.last_accessed = time.time()
        return "\n".join([f"{entry.role}: {entry.content}" for entry in self.entries])

    def clear_history(self) -> int:
        """履歴をクリアして削除した件数を返す"""
        count = len(self.entries)
        self.entries.clear()
        self.last_accessed = time.time()
        return count

    def is_expired(self) -> bool:
        """TTLに基づいて期限切れかチェック"""
        return (time.time() - self.last_accessed) > self.ttl_seconds

    def get_stats(self) -> Dict[str, Any]:
        """チャンネルメモリの統計を取得"""
        if not self.entries:
            return {
                "entry_count": 0,
                "created_at": self.created_at,
                "last_accessed": self.last_accessed,
                "access_count": self.access_count,
                "is_expired": self.is_expired()
            }

        return {
            "entry_count": len(self.entries),
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "oldest_entry": self.entries[0].timestamp if self.entries else None,
            "newest_entry": self.entries[-1].timestamp if self.entries else None,
            "is_expired": self.is_expired()
        }

class UnifiedMemoryManager:
    """統一メモリ管理システム"""

    def __init__(self, default_max_history: int = 10, cleanup_interval: int = 3600):
        # AI種別 -> チャンネルID -> ChannelMemory
        self.memories: Dict[str, Dict[str, ChannelMemory]] = defaultdict(dict)
        self.default_max_history = default_max_history
        self.cleanup_interval = cleanup_interval  # クリーンアップ間隔（秒）
        self.last_cleanup = time.time()
        self.lock = threading.RLock()  # 再帰ロック

        # 統計
        self.total_interactions = 0
        self.cleanup_count = 0

    def get_memory(self, ai_type: str, channel_id: str, max_history: Optional[int] = None) -> ChannelMemory:
        """メモリを取得（存在しない場合は作成）"""
        with self.lock:
            if channel_id not in self.memories[ai_type]:
                self.memories[ai_type][channel_id] = ChannelMemory(
                    max_history=max_history or self.default_max_history
                )
            return self.memories[ai_type][channel_id]

    def add_interaction(self, ai_type: str, channel_id: str, user_content: str,
                       ai_response: str, metadata: Optional[Dict] = None) -> None:
        """やり取りを追加"""
        with self.lock:
            memory = self.get_memory(ai_type, channel_id)
            memory.add_interaction(user_content, ai_response, metadata)
            self.total_interactions += 1

            # 定期クリーンアップ
            if time.time() - self.last_cleanup > self.cleanup_interval:
                self._cleanup_expired_memories()

    def get_history(self, ai_type: str, channel_id: str,
                   include_metadata: bool = False) -> List[Dict[str, str]]:
        """履歴を取得"""
        with self.lock:
            if channel_id in self.memories[ai_type]:
                return self.memories[ai_type][channel_id].get_history(include_metadata)
            return []

    def get_history_text(self, ai_type: str, channel_id: str) -> str:
        """履歴をテキスト形式で取得"""
        with self.lock:
            if channel_id in self.memories[ai_type]:
                return self.memories[ai_type][channel_id].get_history_text()
            return "なし"

    def clear_channel_memory(self, ai_type: str, channel_id: str) -> int:
        """特定チャンネルのメモリをクリア"""
        with self.lock:
            if channel_id in self.memories[ai_type]:
                count = self.memories[ai_type][channel_id].clear_history()
                safe_log(f"🗑️ メモリクリア: ", f"{ai_type}#{channel_id} - {count}件削除")
                return count
            return 0

    def clear_ai_memory(self, ai_type: str) -> int:
        """特定AIの全メモリをクリア"""
        with self.lock:
            total_cleared = 0
            if ai_type in self.memories:
                for channel_id, memory in self.memories[ai_type].items():
                    total_cleared += memory.clear_history()
                self.memories[ai_type].clear()
                safe_log(f"🗑️ AI全メモリクリア: ", f"{ai_type} - {total_cleared}件削除")
            return total_cleared

    def clear_all_memory(self) -> int:
        """全メモリをクリア"""
        with self.lock:
            total_cleared = 0
            for ai_type in self.memories:
                total_cleared += self.clear_ai_memory(ai_type)
            self.memories.clear()
            safe_log(f"🗑️ 全メモリクリア: ", f"{total_cleared}件削除")
            return total_cleared

    def _cleanup_expired_memories(self) -> None:
        """期限切れメモリを削除"""
        with self.lock:
            current_time = time.time()
            expired_count = 0

            for ai_type in list(self.memories.keys()):
                for channel_id in list(self.memories[ai_type].keys()):
                    memory = self.memories[ai_type][channel_id]
                    if memory.is_expired():
                        del self.memories[ai_type][channel_id]
                        expired_count += 1

                # AIタイプ自体が空になった場合は削除
                if not self.memories[ai_type]:
                    del self.memories[ai_type]

            self.last_cleanup = current_time
            self.cleanup_count += 1

            if expired_count > 0:
                safe_log(f"🧹 メモリクリーンアップ: ", f"{expired_count}件の期限切れメモリを削除")

    def get_memory_stats(self) -> MemoryStats:
        """メモリ統計を取得"""
        with self.lock:
            total_entries = 0
            total_channels = 0
            oldest_timestamp = None
            newest_timestamp = None

            for ai_type, channels in self.memories.items():
                for channel_id, memory in channels.items():
                    total_channels += 1
                    entry_count = len(memory.entries)
                    total_entries += entry_count

                    if memory.entries:
                        first_entry = memory.entries[0].timestamp
                        last_entry = memory.entries[-1].timestamp

                        if oldest_timestamp is None or first_entry < oldest_timestamp:
                            oldest_timestamp = first_entry
                        if newest_timestamp is None or last_entry > newest_timestamp:
                            newest_timestamp = last_entry

            # 大まかなメモリサイズ計算（文字数ベース）
            estimated_size = sum(
                len(entry.content) for ai_memories in self.memories.values()
                for channel_memory in ai_memories.values()
                for entry in channel_memory.entries
            )
            memory_size_mb = estimated_size * 2 / (1024 * 1024)  # 概算（UTF-8で2バイト/文字）

            return MemoryStats(
                total_entries=total_entries,
                total_channels=total_channels,
                total_ais=len(self.memories),
                oldest_entry=oldest_timestamp,
                newest_entry=newest_timestamp,
                memory_size_mb=memory_size_mb
            )

    def get_detailed_stats(self) -> Dict[str, Any]:
        """詳細統計を取得"""
        with self.lock:
            stats = self.get_memory_stats()

            ai_stats = {}
            for ai_type, channels in self.memories.items():
                channel_stats = {}
                for channel_id, memory in channels.items():
                    channel_stats[channel_id] = memory.get_stats()
                ai_stats[ai_type] = {
                    "channel_count": len(channels),
                    "channels": channel_stats
                }

            return {
                "summary": {
                    "total_entries": stats.total_entries,
                    "total_channels": stats.total_channels,
                    "total_ais": stats.total_ais,
                    "memory_size_mb": round(stats.memory_size_mb, 2),
                    "total_interactions": self.total_interactions,
                    "cleanup_count": self.cleanup_count
                },
                "ai_breakdown": ai_stats,
                "timestamps": {
                    "oldest_entry": stats.oldest_entry,
                    "newest_entry": stats.newest_entry,
                    "last_cleanup": self.last_cleanup
                }
            }

    def export_memory(self, ai_type: Optional[str] = None,
                     channel_id: Optional[str] = None) -> Dict[str, Any]:
        """メモリをエクスポート（バックアップ用）"""
        with self.lock:
            if ai_type and channel_id:
                # 特定チャンネルのみ
                if ai_type in self.memories and channel_id in self.memories[ai_type]:
                    memory = self.memories[ai_type][channel_id]
                    return {
                        f"{ai_type}#{channel_id}": [
                            {
                                "role": entry.role,
                                "content": entry.content,
                                "timestamp": entry.timestamp,
                                "metadata": entry.metadata
                            } for entry in memory.entries
                        ]
                    }
                return {}
            elif ai_type:
                # 特定AIのみ
                if ai_type not in self.memories:
                    return {}

                result = {}
                for ch_id, memory in self.memories[ai_type].items():
                    result[f"{ai_type}#{ch_id}"] = [
                        {
                            "role": entry.role,
                            "content": entry.content,
                            "timestamp": entry.timestamp,
                            "metadata": entry.metadata
                        } for entry in memory.entries
                    ]
                return result
            else:
                # 全メモリ
                result = {}
                for ai, channels in self.memories.items():
                    for ch_id, memory in channels.items():
                        result[f"{ai}#{ch_id}"] = [
                            {
                                "role": entry.role,
                                "content": entry.content,
                                "timestamp": entry.timestamp,
                                "metadata": entry.metadata
                            } for entry in memory.entries
                        ]
                return result

# グローバルインスタンス
_memory_manager: Optional[UnifiedMemoryManager] = None

def get_memory_manager() -> UnifiedMemoryManager:
    """メモリマネージャーインスタンスを取得（シングルトン）"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = UnifiedMemoryManager()
        safe_log("✅ 統一メモリマネージャー初期化完了", "")
    return _memory_manager

def clear_memory_manager():
    """メモリマネージャーをリセット（テスト用）"""
    global _memory_manager
    _memory_manager = None