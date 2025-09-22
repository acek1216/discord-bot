# -*- coding: utf-8 -*-
"""
設定管理システム
外部YAMLファイルからの設定読み込みとキャッシュ
"""

import yaml
import os
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass
from utils import safe_log

@dataclass
class ChannelMapping:
    """チャンネルマッピング設定"""
    patterns: List[str]
    ai_type: str
    description: str = ""
    special_processing: bool = False

@dataclass
class CacheConfig:
    """キャッシュ設定"""
    notion_ttl: int = 300
    context_ttl: int = 180
    ai_response_ttl: int = 900
    generic_ttl: int = 300
    max_entries: int = 500
    cleanup_interval: int = 60

@dataclass
class AIEngineConfig:
    """AIエンジン設定"""
    default_context_engine: str = "gpt5mini"
    default_summary_engine: str = "gpt5mini"
    gemini_summary_engine: str = "gemini_flash"
    kb_summary_engine: str = "gpt5mini_summary"
    council_ai_types: List[str] = None

    def __post_init__(self):
        if self.council_ai_types is None:
            self.council_ai_types = ["gpt5", "perplexity", "gemini"]

class ConfigManager:
    """設定管理クラス"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None
        self._channel_mappings: Optional[List[ChannelMapping]] = None
        self._cache_config: Optional[CacheConfig] = None
        self._ai_engine_config: Optional[AIEngineConfig] = None

        # 設定ファイル監視用
        self._last_modified = 0

    def _load_config(self) -> Dict[str, Any]:
        """YAMLファイルから設定を読み込み"""
        try:
            if not os.path.exists(self.config_path):
                safe_log(f"⚠️ 設定ファイルが見つかりません: ", self.config_path)
                return self._get_default_config()

            # ファイル更新チェック
            current_modified = os.path.getmtime(self.config_path)
            if current_modified <= self._last_modified and self._config:
                return self._config

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            self._config = config
            self._last_modified = current_modified

            safe_log("✅ 設定ファイル読み込み完了: ", self.config_path)
            return config

        except Exception as e:
            safe_log(f"🚨 設定ファイル読み込みエラー: ", e)
            safe_log("📁 デフォルト設定を使用します", "")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """デフォルト設定を返す（フォールバック用）"""
        return {
            "channel_routing": {
                "mappings": [
                    {"patterns": ["gpt4o"], "ai_type": "gpt4o"},
                    {"patterns": ["gpt"], "ai_type": "gpt5"},
                    {"patterns": ["gemini"], "ai_type": "gemini"},
                    {"patterns": ["claude"], "ai_type": "claude"},
                    {"patterns": ["mistral"], "ai_type": "mistral"},
                    {"patterns": ["grok"], "ai_type": "grok"},
                    {"patterns": ["llama", "ラマ"], "ai_type": "llama"},
                    {"patterns": ["o1", "o1-pro"], "ai_type": "o1_pro"},
                    {"patterns": ["genius"], "ai_type": "genius", "special_processing": True}
                ]
            },
            "cache": {
                "ttl": {"notion": 300, "context": 180, "ai_response": 900, "generic": 300},
                "max_entries": 500,
                "cleanup_interval": 60
            },
            "ai_engines": {
                "context": {"default": "gpt5mini"},
                "summary": {"default": "gpt5mini", "gemini_summary": "gemini_flash", "kb_summary": "gpt5mini_summary"},
                "council": {"default_types": ["gpt5", "perplexity", "gemini"]}
            }
        }

    def get_channel_mappings(self) -> List[ChannelMapping]:
        """チャンネルマッピング設定を取得"""
        if self._channel_mappings:
            return self._channel_mappings

        config = self._load_config()
        mappings = []

        routing_config = config.get("channel_routing", {})
        for mapping_data in routing_config.get("mappings", []):
            mapping = ChannelMapping(
                patterns=mapping_data.get("patterns", []),
                ai_type=mapping_data.get("ai_type", ""),
                description=mapping_data.get("description", ""),
                special_processing=mapping_data.get("special_processing", False)
            )
            mappings.append(mapping)

        self._channel_mappings = mappings
        return mappings

    def get_cache_config(self) -> CacheConfig:
        """キャッシュ設定を取得"""
        if self._cache_config:
            return self._cache_config

        config = self._load_config()
        cache_data = config.get("cache", {})
        ttl_data = cache_data.get("ttl", {})

        cache_config = CacheConfig(
            notion_ttl=ttl_data.get("notion", 300),
            context_ttl=ttl_data.get("context", 180),
            ai_response_ttl=ttl_data.get("ai_response", 900),
            generic_ttl=ttl_data.get("generic", 300),
            max_entries=cache_data.get("max_entries", 500),
            cleanup_interval=cache_data.get("cleanup_interval", 60)
        )

        self._cache_config = cache_config
        return cache_config

    def get_ai_engine_config(self) -> AIEngineConfig:
        """AIエンジン設定を取得"""
        if self._ai_engine_config:
            return self._ai_engine_config

        config = self._load_config()
        ai_engines = config.get("ai_engines", {})

        context_config = ai_engines.get("context", {})
        summary_config = ai_engines.get("summary", {})
        council_config = ai_engines.get("council", {})

        ai_engine_config = AIEngineConfig(
            default_context_engine=context_config.get("default", "gpt5mini"),
            default_summary_engine=summary_config.get("default", "gpt5mini"),
            gemini_summary_engine=summary_config.get("gemini_summary", "gemini_flash"),
            kb_summary_engine=summary_config.get("kb_summary", "gpt5mini_summary"),
            council_ai_types=council_config.get("default_types", ["gpt5", "perplexity", "gemini"])
        )

        self._ai_engine_config = ai_engine_config
        return ai_engine_config

    def get_channel_mapping_tuples(self) -> List[Tuple[Tuple[str, ...], str]]:
        """events.pyで使用する形式でチャンネルマッピングを取得"""
        mappings = self.get_channel_mappings()
        return [(tuple(mapping.patterns), mapping.ai_type) for mapping in mappings]

    def reload_config(self):
        """設定を強制リロード"""
        self._config = None
        self._channel_mappings = None
        self._cache_config = None
        self._ai_engine_config = None
        self._last_modified = 0
        safe_log("🔄 設定をリロードしました", "")

    def get_config_summary(self) -> Dict[str, Any]:
        """設定サマリーを取得（デバッグ用）"""
        config = self._load_config()
        channel_mappings = self.get_channel_mappings()
        cache_config = self.get_cache_config()
        ai_engine_config = self.get_ai_engine_config()

        return {
            "config_file": self.config_path,
            "file_exists": os.path.exists(self.config_path),
            "last_modified": self._last_modified,
            "channel_mappings_count": len(channel_mappings),
            "cache_config": {
                "notion_ttl": cache_config.notion_ttl,
                "max_entries": cache_config.max_entries
            },
            "ai_engines": {
                "context_engine": ai_engine_config.default_context_engine,
                "summary_engine": ai_engine_config.default_summary_engine
            }
        }

# グローバル設定マネージャーインスタンス
_config_manager: Optional[ConfigManager] = None

def get_config_manager(config_path: str = "config.yaml") -> ConfigManager:
    """グローバル設定マネージャーを取得（シングルトン）"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
        safe_log("✅ 設定マネージャー初期化完了", "")
    return _config_manager

def reload_config():
    """設定を強制リロード"""
    global _config_manager
    if _config_manager:
        _config_manager.reload_config()