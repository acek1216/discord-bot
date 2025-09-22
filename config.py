# -*- coding: utf-8 -*-
"""
Bot設定管理モジュール
環境変数の検証と設定を一元管理
"""

import os
import sys
from typing import Dict, Optional, Any
from dataclasses import dataclass

@dataclass
class ConfigItem:
    """設定項目の定義"""
    env_var: str
    description: str
    required: bool = True
    default: Optional[str] = None
    is_secret: bool = True

class BotConfig:
    """Bot設定管理クラス"""

    # 設定項目の定義
    CONFIG_ITEMS = {
        # 必須設定
        "DISCORD_TOKEN": ConfigItem(
            "DISCORD_BOT_TOKEN",
            "Discord Bot Token",
            required=True
        ),
        "OPENAI_API_KEY": ConfigItem(
            "OPENAI_API_KEY",
            "OpenAI API Key",
            required=True
        ),
        "GEMINI_API_KEY": ConfigItem(
            "GEMINI_API_KEY",
            "Google Gemini API Key",
            required=True
        ),
        "PERPLEXITY_API_KEY": ConfigItem(
            "PERPLEXITY_API_KEY",
            "Perplexity AI API Key",
            required=True
        ),
        "MISTRAL_API_KEY": ConfigItem(
            "MISTRAL_API_KEY",
            "Mistral AI API Key",
            required=True
        ),
        "NOTION_API_KEY": ConfigItem(
            "NOTION_API_KEY",
            "Notion Integration Token",
            required=True
        ),
        "GROK_API_KEY": ConfigItem(
            "GROK_API_KEY",
            "Grok (X.AI) API Key",
            required=True
        ),
        "OPENROUTER_API_KEY": ConfigItem(
            "OPENROUTER_API_KEY",
            "OpenRouter API Key",
            required=True
        ),
        "ADMIN_USER_ID": ConfigItem(
            "ADMIN_USER_ID",
            "Discord Admin User ID",
            required=True,
            is_secret=False
        ),

        # オプション設定
        "GUILD_ID": ConfigItem(
            "GUILD_ID",
            "Discord Guild ID",
            required=False,
            default="",
            is_secret=False
        ),
        "NOTION_PAGE_MAP_STRING": ConfigItem(
            "NOTION_PAGE_MAP_STRING",
            "Notion Page Mapping",
            required=False,
            default="",
            is_secret=False
        ),
    }

    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.missing_required: list = []
        self.warnings: list = []

    @classmethod
    def load_and_validate(cls) -> 'BotConfig':
        """設定を読み込み、検証する"""
        instance = cls()
        instance._load_config()
        instance._validate_config()

        if instance.missing_required:
            instance._print_validation_errors()
            sys.exit(1)

        if instance.warnings:
            instance._print_warnings()

        instance._print_success_summary()
        return instance

    def _load_config(self):
        """環境変数から設定を読み込む"""
        for key, config_item in self.CONFIG_ITEMS.items():
            value = os.getenv(config_item.env_var, config_item.default)

            if value is None or (config_item.required and not value.strip()):
                if config_item.required:
                    self.missing_required.append((key, config_item))
                value = config_item.default or ""

            self.config[key] = value.strip() if isinstance(value, str) else value

    def _validate_config(self):
        """設定値の妥当性をチェック"""
        # Discord関連の検証
        if self.config.get("ADMIN_USER_ID"):
            try:
                int(self.config["ADMIN_USER_ID"])
            except ValueError:
                self.warnings.append("ADMIN_USER_IDが数値ではありません")

        if self.config.get("GUILD_ID"):
            try:
                int(self.config["GUILD_ID"])
            except ValueError:
                self.warnings.append("GUILD_IDが数値ではありません")



    def _print_validation_errors(self):
        """検証エラーを表示"""
        print("ERROR: Required environment variables are missing\n")

        for key, config_item in self.missing_required:
            print(f"MISSING: {config_item.env_var}")
            print(f"   Description: {config_item.description}")
            print(f"   Example: export {config_item.env_var}='your_value_here'")
            print()

        print("TIP: Consider using a .env file for configuration")

    def _print_warnings(self):
        """警告を表示"""
        print("WARNING: Configuration issues found:")
        for warning in self.warnings:
            print(f"   - {warning}")
        print()

    def _print_success_summary(self):
        """設定成功サマリーを表示"""
        required_count = sum(1 for item in self.CONFIG_ITEMS.values() if item.required)
        optional_count = len(self.CONFIG_ITEMS) - required_count
        configured_optional = sum(1 for key, item in self.CONFIG_ITEMS.items()
                                if not item.required and self.config.get(key))

        print("SUCCESS: Configuration validation completed")
        print(f"   Required configs: {required_count}/{required_count} OK")
        print(f"   Optional configs: {configured_optional}/{optional_count}")

        if configured_optional < optional_count:
            print(f"   Unconfigured optional: {optional_count - configured_optional} items")

    def get(self, key: str, default: Any = None) -> Any:
        """設定値を取得"""
        return self.config.get(key, default)

    def get_required(self, key: str) -> str:
        """必須設定値を取得（存在しない場合は例外）"""
        value = self.config.get(key)
        if not value:
            raise ValueError(f"Required config '{key}' is not set")
        return value



    def get_config_summary(self) -> Dict[str, Any]:
        """設定サマリーを取得（デバッグ用）"""
        return {
            "total_configs": len(self.CONFIG_ITEMS),
            "required_configs": sum(1 for item in self.CONFIG_ITEMS.values() if item.required),
            "optional_configs": sum(1 for item in self.CONFIG_ITEMS.values() if not item.required),
            "warnings_count": len(self.warnings)
        }

# グローバル設定インスタンス（遅延初期化）
_config_instance: Optional[BotConfig] = None

def get_config() -> BotConfig:
    """設定インスタンスを取得（シングルトン）"""
    global _config_instance
    if _config_instance is None:
        _config_instance = BotConfig.load_and_validate()
    return _config_instance

def reload_config() -> BotConfig:
    """設定を再読み込み"""
    global _config_instance
    _config_instance = BotConfig.load_and_validate()
    return _config_instance

# 便利関数
def get_env(key: str, default: Any = None) -> Any:
    """環境変数を取得する便利関数"""
    return get_config().get(key, default)

def get_required_env(key: str) -> str:
    """必須環境変数を取得する便利関数"""
    return get_config().get_required(key)

if __name__ == "__main__":
    # テスト実行
    print("=== Bot Config Test ===")
    try:
        config = BotConfig.load_and_validate()
        print("設定読み込み成功！")
        print(f"サマリー: {config.get_config_summary()}")
    except SystemExit:
        print("設定エラーによりテスト終了")