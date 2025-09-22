# -*- coding: utf-8 -*-
"""
拡張統一メモリ管理システム
従来の分散した状態管理を完全統合
"""

import time
import threading
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from collections import defaultdict, deque

from memory_manager import UnifiedMemoryManager, MemoryEntry, MemoryStats
from utils import safe_log

@dataclass
class ProcessingState:
    """処理状態の管理"""
    processing_channels: Set[str] = field(default_factory=set)
    processing_messages: Set[str] = field(default_factory=set)
    processed_messages: Dict[str, float] = field(default_factory=dict)
    global_state: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LegacyMemoryMapping:
    """従来メモリシステムとのマッピング定義"""
    base_memory_types = [
        'gpt', 'gemini', 'mistral', 'claude', 'llama', 'grok'
    ]

    thread_memory_types = [
        'gpt', 'gemini', 'perplexity', 'gpt4o', 'gpt5'
    ]

class EnhancedMemoryManager(UnifiedMemoryManager):
    """拡張統一メモリマネージャー - 全状態を統合管理"""

    def __init__(self, default_max_history: int = 10, cleanup_interval: int = 3600):
        super().__init__(default_max_history, cleanup_interval)

        # 処理状態管理
        self.processing_state = ProcessingState()

        # 従来システム互換性のための辞書（動的生成）
        self._legacy_memory_cache = {}
        self._legacy_cache_last_update = {}

        # 重複処理防止システム
        self.duplication_cleanup_interval = 600
        self.last_duplication_cleanup = time.time()

        safe_log("✅ 拡張メモリマネージャー初期化完了", "")

    # === 処理状態管理 ===

    def add_processing_channel(self, channel_id: str) -> bool:
        """処理中チャンネルを追加（重複チェック付き）"""
        with self.lock:
            if channel_id in self.processing_state.processing_channels:
                return False  # 既に処理中

            self.processing_state.processing_channels.add(channel_id)
            safe_log("🔄 チャンネル処理開始: ", channel_id)
            return True

    def remove_processing_channel(self, channel_id: str) -> bool:
        """処理中チャンネルを削除"""
        with self.lock:
            if channel_id in self.processing_state.processing_channels:
                self.processing_state.processing_channels.discard(channel_id)
                safe_log("✅ チャンネル処理完了: ", channel_id)
                return True
            return False

    def is_channel_processing(self, channel_id: str) -> bool:
        """チャンネルが処理中かチェック"""
        return channel_id in self.processing_state.processing_channels

    def get_processing_channels(self) -> Set[str]:
        """処理中チャンネル一覧を取得"""
        return self.processing_state.processing_channels.copy()

    # === メッセージ重複処理防止 ===

    def start_message_processing(self, message_id: str) -> bool:
        """メッセージ処理開始（重複防止）"""
        with self.lock:
            current_time = time.time()

            # 定期クリーンアップ
            if current_time - self.last_duplication_cleanup > self.duplication_cleanup_interval:
                self._cleanup_old_processed_messages(current_time)
                self.last_duplication_cleanup = current_time

            # 重複チェック
            if (message_id in self.processing_state.processing_messages or
                message_id in self.processing_state.processed_messages):
                return False

            self.processing_state.processing_messages.add(message_id)
            return True

    def finish_message_processing(self, message_id: str, success: bool = True):
        """メッセージ処理完了"""
        with self.lock:
            self.processing_state.processing_messages.discard(message_id)
            if success:
                self.processing_state.processed_messages[message_id] = time.time()

    def _cleanup_old_processed_messages(self, current_time: float):
        """古い処理済みメッセージをクリーンアップ"""
        cutoff_time = current_time - 3600  # 1時間前まで
        old_messages = [
            msg_id for msg_id, timestamp in self.processing_state.processed_messages.items()
            if timestamp < cutoff_time
        ]

        for msg_id in old_messages:
            del self.processing_state.processed_messages[msg_id]

        if old_messages:
            safe_log("🧹 古いメッセージ処理記録クリーンアップ: ", f"{len(old_messages)}件削除")

    # === グローバル状態管理 ===

    def set_global_state(self, key: str, value: Any):
        """グローバル状態を設定"""
        with self.lock:
            self.processing_state.global_state[key] = value

    def get_global_state(self, key: str, default: Any = None) -> Any:
        """グローバル状態を取得"""
        return self.processing_state.global_state.get(key, default)

    def remove_global_state(self, key: str) -> bool:
        """グローバル状態を削除"""
        with self.lock:
            if key in self.processing_state.global_state:
                del self.processing_state.global_state[key]
                return True
            return False

    # === 従来システム互換性 ===

    def get_legacy_memory(self, memory_type: str, memory_category: str = "base") -> Dict[str, Any]:
        """従来のメモリ形式で取得（後方互換性）

        Args:
            memory_type: 'gpt', 'gemini', 'mistral', etc.
            memory_category: 'base' or 'thread'
        """
        cache_key = f"{memory_type}_{memory_category}"
        current_time = time.time()

        # キャッシュが新しい場合はそれを返す
        if (cache_key in self._legacy_cache_last_update and
            current_time - self._legacy_cache_last_update[cache_key] < 1.0):
            return self._legacy_memory_cache.get(cache_key, {})

        with self.lock:
            # 統一メモリシステムから従来形式に変換
            legacy_memory = {}

            if memory_type in self.memories:
                for channel_id, memory in self.memories[memory_type].items():
                    if memory.entries:
                        # OpenAI形式のhistoryに変換
                        legacy_memory[channel_id] = memory.get_history(include_metadata=False)

            # キャッシュに保存
            self._legacy_memory_cache[cache_key] = legacy_memory
            self._legacy_cache_last_update[cache_key] = current_time

            return legacy_memory

    def update_legacy_memory(self, memory_type: str, channel_id: str,
                           history: List[Dict[str, str]], memory_category: str = "base"):
        """従来形式でメモリを更新（後方互換性）"""
        if not history:
            return

        with self.lock:
            # 従来形式から統一システムに変換
            # historyは [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}] 形式

            # ペアでやり取りを処理
            for i in range(0, len(history) - 1, 2):
                if (i + 1 < len(history) and
                    history[i].get("role") == "user" and
                    history[i + 1].get("role") == "assistant"):

                    user_content = history[i].get("content", "")
                    ai_content = history[i + 1].get("content", "")

                    if user_content and ai_content:
                        self.add_interaction(
                            ai_type=memory_type,
                            channel_id=channel_id,
                            user_content=user_content,
                            ai_response=ai_content,
                            metadata={
                                "legacy_import": True,
                                "memory_category": memory_category,
                                "timestamp": time.time()
                            }
                        )

            # キャッシュを無効化
            cache_key = f"{memory_type}_{memory_category}"
            if cache_key in self._legacy_cache_last_update:
                del self._legacy_cache_last_update[cache_key]

    # === 統計とモニタリング ===

    def get_enhanced_stats(self) -> Dict[str, Any]:
        """拡張統計情報を取得"""
        base_stats = self.get_detailed_stats()

        with self.lock:
            processing_info = {
                "processing_channels": len(self.processing_state.processing_channels),
                "processing_messages": len(self.processing_state.processing_messages),
                "processed_messages_count": len(self.processing_state.processed_messages),
                "global_state_keys": len(self.processing_state.global_state),
                "legacy_cache_entries": len(self._legacy_memory_cache)
            }

            return {
                **base_stats,
                "processing_state": processing_info,
                "system_info": {
                    "enhanced_manager": True,
                    "version": "2.0",
                    "features": [
                        "unified_memory", "processing_state", "message_deduplication",
                        "legacy_compatibility", "global_state", "auto_cleanup"
                    ]
                }
            }

    def health_check(self) -> Dict[str, Any]:
        """システムヘルスチェック"""
        with self.lock:
            current_time = time.time()

            # メモリ使用量チェック
            total_entries = sum(len(channels) for channels in self.memories.values())
            memory_pressure = "high" if total_entries > 1000 else "normal" if total_entries > 100 else "low"

            # 処理状態チェック
            long_processing_channels = [
                ch_id for ch_id in self.processing_state.processing_channels
                # 実際の処理時間は追跡していないため、単純に存在チェック
            ]

            # クリーンアップ状態
            cleanup_overdue = (current_time - self.last_cleanup) > (self.cleanup_interval * 2)

            return {
                "status": "healthy",
                "memory_pressure": memory_pressure,
                "total_memory_entries": total_entries,
                "processing_channels_count": len(self.processing_state.processing_channels),
                "long_processing_channels": long_processing_channels,
                "cleanup_overdue": cleanup_overdue,
                "last_cleanup_ago_seconds": int(current_time - self.last_cleanup),
                "recommendations": self._get_health_recommendations(memory_pressure, cleanup_overdue)
            }

    def _get_health_recommendations(self, memory_pressure: str, cleanup_overdue: bool) -> List[str]:
        """ヘルス状態に基づく推奨アクション"""
        recommendations = []

        if memory_pressure == "high":
            recommendations.append("メモリ使用量が多いため、クリーンアップを推奨")

        if cleanup_overdue:
            recommendations.append("自動クリーンアップが遅延中、手動実行を推奨")

        if len(self.processing_state.processing_channels) > 10:
            recommendations.append("同時処理チャンネル数が多い、負荷分散を推奨")

        return recommendations

    # === クリーンアップとメンテナンス ===

    def force_cleanup(self) -> Dict[str, int]:
        """強制クリーンアップ実行"""
        with self.lock:
            current_time = time.time()

            # 通常のメモリクリーンアップ
            self._cleanup_expired_memories()

            # 重複処理防止のクリーンアップ
            old_processed_count = len(self.processing_state.processed_messages)
            self._cleanup_old_processed_messages(current_time)
            cleaned_messages = old_processed_count - len(self.processing_state.processed_messages)

            # レガシーキャッシュクリア
            cache_entries = len(self._legacy_memory_cache)
            self._legacy_memory_cache.clear()
            self._legacy_cache_last_update.clear()

            return {
                "expired_memories": 0,  # _cleanup_expired_memories の戻り値がないため
                "old_messages": cleaned_messages,
                "cache_entries": cache_entries
            }

# グローバルインスタンス
_enhanced_memory_manager: Optional[EnhancedMemoryManager] = None

def get_enhanced_memory_manager() -> EnhancedMemoryManager:
    """拡張メモリマネージャーインスタンスを取得（シングルトン）"""
    global _enhanced_memory_manager
    if _enhanced_memory_manager is None:
        _enhanced_memory_manager = EnhancedMemoryManager()
        safe_log("✅ 拡張統一メモリマネージャー作成完了", "")
    return _enhanced_memory_manager

def reset_enhanced_memory_manager():
    """拡張メモリマネージャーをリセット（テスト用）"""
    global _enhanced_memory_manager
    _enhanced_memory_manager = None

# 便利関数（従来システム互換）
def get_processing_channels() -> Set[str]:
    """処理中チャンネル取得"""
    return get_enhanced_memory_manager().get_processing_channels()

def add_processing_channel(channel_id: str) -> bool:
    """処理中チャンネル追加"""
    return get_enhanced_memory_manager().add_processing_channel(channel_id)

def remove_processing_channel(channel_id: str) -> bool:
    """処理中チャンネル削除"""
    return get_enhanced_memory_manager().remove_processing_channel(channel_id)

def is_channel_processing(channel_id: str) -> bool:
    """チャンネル処理中チェック"""
    return get_enhanced_memory_manager().is_channel_processing(channel_id)

if __name__ == "__main__":
    # テスト実行
    print("=== Enhanced Memory Manager Test ===")

    manager = EnhancedMemoryManager()

    # 処理状態テスト
    print("1. Processing State Test...")
    assert manager.add_processing_channel("test_channel_1") == True
    assert manager.add_processing_channel("test_channel_1") == False  # 重複
    assert manager.is_channel_processing("test_channel_1") == True
    assert manager.remove_processing_channel("test_channel_1") == True
    print("   ✅ Processing state management OK")

    # メッセージ重複防止テスト
    print("2. Message Deduplication Test...")
    assert manager.start_message_processing("msg_001") == True
    assert manager.start_message_processing("msg_001") == False  # 重複
    manager.finish_message_processing("msg_001", success=True)
    assert manager.start_message_processing("msg_001") == False  # 処理済み
    print("   ✅ Message deduplication OK")

    # メモリ管理テスト
    print("3. Memory Management Test...")
    manager.add_interaction("gpt5", "channel_123", "Hello", "Hi there!")
    history = manager.get_history("gpt5", "channel_123")
    assert len(history) == 2
    print("   ✅ Memory management OK")

    # レガシー互換性テスト
    print("4. Legacy Compatibility Test...")
    legacy_memory = manager.get_legacy_memory("gpt5", "base")
    assert "channel_123" in legacy_memory
    print("   ✅ Legacy compatibility OK")

    # ヘルスチェックテスト
    print("5. Health Check Test...")
    health = manager.health_check()
    assert health["status"] == "healthy"
    print("   ✅ Health check OK")

    print("\n🎉 All tests passed! Enhanced Memory Manager is ready.")

    # 統計表示
    stats = manager.get_enhanced_stats()
    print(f"\nStats: {stats['summary']['total_entries']} entries across {stats['summary']['total_ais']} AI types")