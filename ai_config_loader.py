# -*- coding: utf-8 -*-
"""
AI設定ローダー - YAML設定ファイルからAI設定を読み込む
"""

import yaml
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import threading

from utils import safe_log

@dataclass
class AIModelConfig:
    """YAML設定ファイルから読み込むAI設定"""
    name: str
    description: str
    client_type: str  # "openai", "gemini", "external_api", "vertex_ai", "mistral"
    model: str
    max_tokens: int = 1000
    temperature: float = 0.7
    timeout: float = 30.0
    retry_count: int = 2
    system_prompt: Optional[str] = None
    supports_memory: bool = False
    supports_attachments: bool = False
    rate_limit_service: str = "default"
    api_function: Optional[str] = None  # 外部API用の関数名

@dataclass
class SpecialConfigs:
    """特殊設定"""
    summary_engines: Dict[str, str] = field(default_factory=dict)
    council_ais: List[str] = field(default_factory=list)
    default_context_engine: str = "gpt5mini"

class AIConfigLoader:
    """AI設定ローダー（シングルトン）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized'):
            return

        self._ai_configs: Dict[str, AIModelConfig] = {}
        self._special_configs: SpecialConfigs = SpecialConfigs()
        self._config_file_path = Path(__file__).parent / "config" / "ai_models.yaml"
        self._last_modified = 0
        self._initialized = True

        # 初回読み込み
        self.load_configs()

    def load_configs(self, force_reload: bool = False) -> None:
        """設定ファイルを読み込み"""
        try:
            if not self._config_file_path.exists():
                raise FileNotFoundError(f"設定ファイルが見つかりません: {self._config_file_path}")

            # ファイルの更新時刻をチェック
            current_modified = os.path.getmtime(self._config_file_path)
            if not force_reload and current_modified <= self._last_modified:
                return  # 更新されていない場合はスキップ

            with open(self._config_file_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            self._parse_ai_models(config_data.get('ai_models', {}))
            self._parse_special_configs(config_data.get('special_configs', {}))

            self._last_modified = current_modified
            safe_log("✅ AI設定読み込み完了: ", f"{len(self._ai_configs)}個のAIモデル設定")

        except Exception as e:
            safe_log("🚨 AI設定読み込みエラー: ", e)
            if not self._ai_configs:
                # フォールバック：最低限の設定
                self._create_fallback_configs()
                safe_log("⚠️ フォールバック設定を適用", "")

    def _parse_ai_models(self, ai_models_data: Dict[str, Any]) -> None:
        """AIモデル設定をパース"""
        self._ai_configs.clear()

        for ai_type, config_dict in ai_models_data.items():
            try:
                # 必須フィールドの検証
                required_fields = ['name', 'description', 'client_type', 'model']
                missing_fields = [field for field in required_fields if field not in config_dict]

                if missing_fields:
                    safe_log(f"⚠️ AI設定エラー ({ai_type}): ", f"必須フィールドが不足: {missing_fields}")
                    continue

                # AIModelConfigオブジェクトを作成
                ai_config = AIModelConfig(**config_dict)
                self._ai_configs[ai_type] = ai_config

            except TypeError as e:
                safe_log(f"⚠️ AI設定パースエラー ({ai_type}): ", e)
            except Exception as e:
                safe_log(f"🚨 予期しない設定エラー ({ai_type}): ", e)

    def _parse_special_configs(self, special_configs_data: Dict[str, Any]) -> None:
        """特殊設定をパース"""
        self._special_configs = SpecialConfigs(
            summary_engines=special_configs_data.get('summary_engines', {}),
            council_ais=special_configs_data.get('council_ais', []),
            default_context_engine=special_configs_data.get('default_context_engine', 'gpt5mini')
        )

    def _create_fallback_configs(self) -> None:
        """フォールバック用の最低限設定"""
        fallback_configs = {
            "gpt5": AIModelConfig(
                name="GPT-5",
                description="フォールバック設定",
                client_type="openai",
                model="gpt-5",
                max_tokens=1000,
                system_prompt="あなたはGPT-5です。"
            ),
            "gemini": AIModelConfig(
                name="Gemini",
                description="フォールバック設定",
                client_type="gemini",
                model="gemini-2.5-pro",
                max_tokens=1000,
                system_prompt="あなたはGeminiです。"
            )
        }

        self._ai_configs = fallback_configs
        safe_log("⚠️ フォールバック設定適用: ", f"{len(fallback_configs)}個のAI設定")

    def get_ai_config(self, ai_type: str) -> Optional[AIModelConfig]:
        """特定のAI設定を取得"""
        self.load_configs()  # 必要に応じて再読み込み
        return self._ai_configs.get(ai_type)

    def get_all_ai_configs(self) -> Dict[str, AIModelConfig]:
        """全AI設定を取得"""
        self.load_configs()  # 必要に応じて再読み込み
        return self._ai_configs.copy()

    def get_special_configs(self) -> SpecialConfigs:
        """特殊設定を取得"""
        self.load_configs()  # 必要に応じて再読み込み
        return self._special_configs

    def get_available_ai_types(self) -> List[str]:
        """利用可能なAIタイプのリストを取得"""
        self.load_configs()
        return list(self._ai_configs.keys())

    def is_ai_type_available(self, ai_type: str) -> bool:
        """指定されたAIタイプが利用可能かチェック"""
        return ai_type in self.get_available_ai_types()

    def reload_config(self) -> None:
        """設定を強制的に再読み込み"""
        self.load_configs(force_reload=True)
        safe_log("🔄 AI設定強制リロード完了", "")

    def get_config_summary(self) -> Dict[str, Any]:
        """設定サマリーを取得（デバッグ用）"""
        self.load_configs()

        return {
            "total_ai_models": len(self._ai_configs),
            "ai_types": list(self._ai_configs.keys()),
            "summary_engines": self._special_configs.summary_engines,
            "council_ais": self._special_configs.council_ais,
            "default_context_engine": self._special_configs.default_context_engine,
            "config_file_path": str(self._config_file_path),
            "last_modified": self._last_modified
        }

    def validate_config(self) -> Dict[str, Any]:
        """設定の妥当性を検証"""
        self.load_configs()

        issues = []
        warnings = []

        # AI設定の検証
        for ai_type, config in self._ai_configs.items():
            if not config.name or not config.name.strip():
                issues.append(f"AI '{ai_type}' の名前が空です")

            if config.max_tokens <= 0:
                issues.append(f"AI '{ai_type}' のmax_tokensが無効です: {config.max_tokens}")

            if config.temperature < 0 or config.temperature > 2:
                warnings.append(f"AI '{ai_type}' のtemperatureが推奨範囲外です: {config.temperature}")

            if config.timeout <= 0:
                issues.append(f"AI '{ai_type}' のtimeoutが無効です: {config.timeout}")

        # 特殊設定の検証
        council_ais = self._special_configs.council_ais
        for council_ai in council_ais:
            if council_ai not in self._ai_configs:
                issues.append(f"Council AI '{council_ai}' が見つかりません")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "total_checks": len(self._ai_configs) + len(council_ais)
        }

# グローバルインスタンス取得用の関数
def get_ai_config_loader() -> AIConfigLoader:
    """AI設定ローダーのインスタンスを取得"""
    return AIConfigLoader()

# 便利関数
def get_ai_config(ai_type: str) -> Optional[AIModelConfig]:
    """AI設定を取得する便利関数"""
    return get_ai_config_loader().get_ai_config(ai_type)

def get_all_ai_configs() -> Dict[str, AIModelConfig]:
    """全AI設定を取得する便利関数"""
    return get_ai_config_loader().get_all_ai_configs()

def get_special_configs() -> SpecialConfigs:
    """特殊設定を取得する便利関数"""
    return get_ai_config_loader().get_special_configs()

def reload_ai_configs() -> None:
    """AI設定を再読み込みする便利関数"""
    get_ai_config_loader().reload_config()

if __name__ == "__main__":
    # テスト実行
    print("=== AI Config Loader Test ===")

    loader = AIConfigLoader()

    # 設定サマリー表示
    summary = loader.get_config_summary()
    print(f"設定ファイル: {summary['config_file_path']}")
    print(f"AIモデル数: {summary['total_ai_models']}")
    print(f"AIタイプ: {', '.join(summary['ai_types'])}")

    # 検証実行
    validation_result = loader.validate_config()
    print(f"\n検証結果: {'✅ OK' if validation_result['valid'] else '❌ エラーあり'}")

    if validation_result['issues']:
        print("問題:")
        for issue in validation_result['issues']:
            print(f"  - {issue}")

    if validation_result['warnings']:
        print("警告:")
        for warning in validation_result['warnings']:
            print(f"  - {warning}")

    # 個別設定テスト
    print(f"\n=== 設定テスト ===")
    for ai_type in ["gpt5", "gemini", "nonexistent"]:
        config = loader.get_ai_config(ai_type)
        if config:
            print(f"{ai_type}: {config.name} ({config.client_type})")
        else:
            print(f"{ai_type}: 設定なし")