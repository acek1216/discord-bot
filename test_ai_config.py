# -*- coding: utf-8 -*-
"""
AI設定システムのテスト（単体）
"""

import yaml
import os
import sys
from pathlib import Path
from typing import Dict, Any

def simple_safe_log(label: str, message: str):
    """シンプルなログ関数（Unicode問題回避）"""
    try:
        print(f"{label}{message}")
    except UnicodeEncodeError:
        print(f"{label}[Unicode Error]")

def test_yaml_config():
    """YAML設定ファイルのテスト"""
    config_file = Path(__file__).parent / "config" / "ai_models.yaml"

    print(f"設定ファイルパス: {config_file}")
    print(f"ファイル存在: {config_file.exists()}")

    if not config_file.exists():
        print("ERROR: 設定ファイルが見つかりません")
        return False

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        print(f"YAML読み込み成功")

        # AI models の確認
        ai_models = config_data.get('ai_models', {})
        print(f"AIモデル数: {len(ai_models)}")

        # 各AIモデルの確認
        for ai_type, config in ai_models.items():
            print(f"  - {ai_type}: {config.get('name', 'N/A')} ({config.get('client_type', 'N/A')})")

            # 必須フィールドの確認
            required = ['name', 'description', 'client_type', 'model']
            missing = [field for field in required if field not in config]
            if missing:
                print(f"    警告: 必須フィールド不足: {missing}")

        # 特殊設定の確認
        special_configs = config_data.get('special_configs', {})
        print(f"\n特殊設定:")
        print(f"  - 要約エンジン: {special_configs.get('summary_engines', {})}")
        print(f"  - AI評議会: {special_configs.get('council_ais', [])}")
        print(f"  - デフォルトコンテキスト: {special_configs.get('default_context_engine', 'N/A')}")

        return True

    except Exception as e:
        print(f"YAML読み込みエラー: {e}")
        return False

def test_config_loader():
    """設定ローダーのテスト（importなし）"""
    print("\n=== 設定ローダーテスト ===")

    try:
        # 最低限のテスト用設定データクラス
        from dataclasses import dataclass
        from typing import Optional

        @dataclass
        class TestAIConfig:
            name: str
            description: str
            client_type: str
            model: str
            max_tokens: int = 1000
            temperature: float = 0.7
            system_prompt: Optional[str] = None

        config_file = Path(__file__).parent / "config" / "ai_models.yaml"

        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        ai_configs = {}
        for ai_type, config_dict in config_data.get('ai_models', {}).items():
            try:
                ai_configs[ai_type] = TestAIConfig(**config_dict)
                simple_safe_log(f"作成成功: ", f"{ai_type}")
            except TypeError as e:
                simple_safe_log(f"作成失敗 ({ai_type}): ", str(e))

        print(f"設定オブジェクト作成: {len(ai_configs)}個")
        return True

    except Exception as e:
        print(f"設定ローダーテストエラー: {e}")
        return False

if __name__ == "__main__":
    print("=== AI Config System Test ===")

    # YAML設定ファイルのテスト
    yaml_ok = test_yaml_config()

    # 設定ローダーのテスト
    loader_ok = test_config_loader()

    print(f"\n=== テスト結果 ===")
    print(f"YAML設定: {'OK' if yaml_ok else 'NG'}")
    print(f"設定ローダー: {'OK' if loader_ok else 'NG'}")
    print(f"総合結果: {'ALL OK' if yaml_ok and loader_ok else 'NG'}")