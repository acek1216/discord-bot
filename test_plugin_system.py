# -*- coding: utf-8 -*-
"""
プラグインシステム総合テスト
統合テストとユニットテストの両方を実行
"""

import asyncio
import sys
import os
from pathlib import Path

# テスト用のモック関数
print("=== プラグインシステム総合テスト開始 ===")

async def test_plugin_manager_initialization():
    """プラグインマネージャー初期化テスト"""
    print("\n1. プラグインマネージャー初期化テスト...")

    try:
        from plugin_system import PluginManager, get_plugin_manager

        # シングルトンパターンテスト
        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()

        assert manager1 is manager2, "シングルトンパターンが正しく動作していません"
        print("   ✅ シングルトンパターン: OK")

        # 設定ファイル読み込みテスト
        assert hasattr(manager1, 'config'), "設定が読み込まれていません"
        assert 'plugin_system' in manager1.config, "プラグインシステム設定が見つかりません"
        print("   ✅ 設定ファイル読み込み: OK")

        return True

    except Exception as e:
        print(f"   🚨 初期化テストエラー: {e}")
        return False

async def test_plugin_loading():
    """プラグイン読み込みテスト"""
    print("\n2. プラグイン読み込みテスト...")

    try:
        from plugin_system import get_plugin_manager

        manager = get_plugin_manager()
        await manager.load_plugins()

        # プラグイン読み込み確認
        loaded_plugins = list(manager.plugins.keys())
        print(f"   読み込みプラグイン: {loaded_plugins}")

        # genius_councilプラグインが読み込まれているかチェック
        if 'genius_council' in loaded_plugins:
            plugin = manager.get_plugin('genius_council')
            assert plugin is not None, "genius_councilプラグインが取得できません"
            assert plugin.name == 'genius_council', "プラグイン名が正しくありません"
            print("   ✅ genius_councilプラグイン: OK")
        else:
            print("   ⚠️ genius_councilプラグインが読み込まれていません（モックプラグインの可能性）")

        return True

    except Exception as e:
        print(f"   🚨 プラグイン読み込みテストエラー: {e}")
        return False

async def test_hook_system():
    """フックシステムテスト"""
    print("\n3. フックシステムテスト...")

    try:
        from plugin_system import get_plugin_manager, HookType

        manager = get_plugin_manager()

        # フック登録確認
        for hook_type in HookType:
            plugins_count = len(manager.hooks[hook_type])
            print(f"   {hook_type.value}: {plugins_count}個のプラグイン登録")

        # 空のフック実行テスト（必要な引数を渡す）
        # モックオブジェクトを作成
        class MockBot:
            openai_client = None
            processing_channels = set()

        class MockMessage:
            content = "テストメッセージ"
            author = None
            channel = type('MockChannel', (), {'id': 12345})()

        mock_bot = MockBot()
        mock_message = MockMessage()

        results = await manager.execute_hook(
            HookType.PRE_TASK_EXECUTION,
            bot=mock_bot,
            message=mock_message,
            ai_type="test",
            context={}
        )
        print(f"   ✅ フック実行テスト完了: {len(results)}個の結果")

        return True

    except Exception as e:
        print(f"   🚨 フックシステムテストエラー: {e}")
        return False

async def test_unified_engine_integration():
    """統一エンジン連携テスト"""
    print("\n4. 統一エンジン連携テスト...")

    try:
        from unified_task_engine import UnifiedTaskEngine
        from config_manager import get_config_manager

        # エンジン初期化
        config_manager = get_config_manager()
        engine = UnifiedTaskEngine(config_manager)

        # プラグインマネージャーが設定されているか確認
        assert hasattr(engine, 'plugin_manager'), "プラグインマネージャーが設定されていません"
        assert engine.plugin_manager is not None, "プラグインマネージャーがNoneです"

        print("   ✅ プラグインマネージャー連携: OK")

        # タスク設定確認
        if hasattr(engine.config_manager, 'get_ai_task_config'):
            genius_config = engine.config_manager.get_ai_task_config('genius')
            if genius_config:
                assert genius_config.get('task_type') == 'council', "geniusタスクの設定が正しくありません"
                print("   ✅ genius評議会設定: OK")

        return True

    except Exception as e:
        print(f"   🚨 統一エンジン連携テストエラー: {e}")
        return False

async def test_config_files():
    """設定ファイル整合性テスト"""
    print("\n5. 設定ファイル整合性テスト...")

    try:
        config_files = [
            "config/plugin_config.yaml",
            "config/task_configs.yaml"
        ]

        for config_file in config_files:
            file_path = Path(config_file)
            assert file_path.exists(), f"設定ファイルが見つかりません: {config_file}"
            print(f"   ✅ {config_file}: 存在確認OK")

        # YAML形式確認
        import yaml
        for config_file in config_files:
            with open(config_file, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            print(f"   ✅ {config_file}: YAML形式OK")

        return True

    except Exception as e:
        print(f"   🚨 設定ファイルテストエラー: {e}")
        return False

async def test_performance_metrics():
    """パフォーマンス統計テスト"""
    print("\n6. パフォーマンス統計テスト...")

    try:
        from plugin_system import get_plugin_manager

        manager = get_plugin_manager()
        stats = manager.get_plugin_stats()

        # 統計情報の構造確認
        required_keys = ['system_info', 'plugins', 'hooks']
        for key in required_keys:
            assert key in stats, f"統計情報に{key}が含まれていません"

        print(f"   ✅ 統計情報構造: OK")
        print(f"   📊 読み込みプラグイン数: {stats['system_info']['total_plugins']}")
        print(f"   📊 有効プラグイン数: {stats['system_info']['enabled_plugins']}")

        return True

    except Exception as e:
        print(f"   🚨 パフォーマンス統計テストエラー: {e}")
        return False

async def run_all_tests():
    """全テスト実行"""
    print("プラグインシステム総合テスト実行中...")

    test_functions = [
        test_plugin_manager_initialization,
        test_plugin_loading,
        test_hook_system,
        test_unified_engine_integration,
        test_config_files,
        test_performance_metrics
    ]

    results = []
    for test_func in test_functions:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"   🚨 テスト実行エラー ({test_func.__name__}): {e}")
            results.append(False)

    # 結果集計
    passed = sum(results)
    total = len(results)
    pass_rate = (passed / total) * 100

    print(f"\n=== テスト結果 ===")
    print(f"実行テスト数: {total}")
    print(f"成功: {passed}")
    print(f"失敗: {total - passed}")
    print(f"成功率: {pass_rate:.1f}%")

    if pass_rate >= 80:
        print("🎉 プラグインシステムは正常に動作しています！")
    elif pass_rate >= 60:
        print("⚠️ プラグインシステムは部分的に動作していますが、改善が必要です。")
    else:
        print("🚨 プラグインシステムに重大な問題があります。")

    return pass_rate >= 80

if __name__ == "__main__":
    # Windows環境での文字化け対策
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    try:
        result = asyncio.run(run_all_tests())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"🚨 テスト実行中に予期しないエラーが発生しました: {e}")
        sys.exit(1)