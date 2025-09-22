# -*- coding: utf-8 -*-
"""
完全統合テスト - 全4フェーズの統合動作確認
"""

import asyncio
import sys
from datetime import datetime

print("=== 完全統合テスト開始 ===")

async def test_phase1_ai_config_externalization():
    """フェーズ1: AI設定外部化テスト"""
    print("\n【フェーズ1】AI設定外部化テスト...")

    try:
        from ai_config_loader import get_ai_config_loader

        loader = get_ai_config_loader()

        # 設定読み込み確認
        gpt5_config = loader.get_ai_config("gpt5")
        assert gpt5_config is not None, "GPT-5設定が読み込めません"
        assert gpt5_config.name == "GPT-5", "GPT-5設定が正しくありません（設定ファイルではGPT-5）"

        gemini_config = loader.get_ai_config("gemini")
        assert gemini_config is not None, "Gemini設定が読み込めません"

        # 全AI設定確認
        all_configs = loader.get_all_ai_configs()
        assert len(all_configs) >= 8, f"AI設定数が不足: {len(all_configs)}"

        print(f"   ✅ AI設定読み込み: {len(all_configs)}個のAI設定")
        print("   ✅ フェーズ1: 完了")
        return True

    except Exception as e:
        print(f"   🚨 フェーズ1エラー: {e}")
        return False

async def test_phase2_unified_memory():
    """フェーズ2: 統一メモリ管理テスト"""
    print("\n【フェーズ2】統一メモリ管理テスト...")

    try:
        from enhanced_memory_manager import get_enhanced_memory_manager

        memory_manager = get_enhanced_memory_manager()

        # メモリ管理機能確認（継承された機能を使用）
        test_key = "test_channel_123"
        test_memory = {"role": "user", "content": "テスト会話", "timestamp": datetime.now().isoformat()}

        # メモリ追加（継承メソッド）
        memory_manager.add_conversation_memory(test_key, test_memory)

        # メモリ取得（継承メソッド）
        retrieved = memory_manager.get_conversation_memory(test_key, limit=1)
        assert len(retrieved) > 0, "メモリ取得に失敗"

        # 処理状態管理
        memory_manager.start_message_processing("test_message_123")
        assert memory_manager.is_processing("test_message_123"), "処理状態管理に失敗"

        memory_manager.finish_message_processing("test_message_123")
        assert not memory_manager.is_processing("test_message_123"), "処理完了状態に失敗"

        print("   ✅ メモリ追加・取得: OK")
        print("   ✅ 処理状態管理: OK")
        print("   ✅ フェーズ2: 完了")
        return True

    except Exception as e:
        print(f"   🚨 フェーズ2エラー: {e}")
        return False

async def test_phase3_unified_task_engine():
    """フェーズ3: 統一タスクエンジンテスト"""
    print("\n【フェーズ3】統一タスクエンジンテスト...")

    try:
        from unified_task_engine import UnifiedTaskEngine, TaskConfigLoader
        from config_manager import get_config_manager

        # エンジン初期化
        config_manager = get_config_manager()
        engine = UnifiedTaskEngine(config_manager)

        # 設定ローダーテスト
        config_loader = TaskConfigLoader()

        # AI設定確認（タスク設定として）
        gpt5_config = config_loader.get_task_config("gpt5")
        assert gpt5_config is not None, "GPT-5タスク設定が見つかりません"

        genius_config = config_loader.get_task_config("genius")
        assert genius_config is not None, "Genius評議会設定が見つかりません"
        assert genius_config.task_type == "council", "Genius評議会のタスクタイプが正しくありません"

        # 戦略パターン確認
        from unified_task_engine import ContextStrategyFactory

        strategies = ["minimal", "cached", "parallel_memory", "council_optimized"]
        for strategy_name in strategies:
            strategy = ContextStrategyFactory.get_strategy(strategy_name)
            assert strategy is not None, f"{strategy_name}戦略が取得できません"

        print("   ✅ エンジン初期化: OK")
        print("   ✅ AI設定読み込み: OK")
        print("   ✅ 戦略パターン: OK")
        print("   ✅ フェーズ3: 完了")
        return True

    except Exception as e:
        print(f"   🚨 フェーズ3エラー: {e}")
        return False

async def test_phase4_plugin_system():
    """フェーズ4: プラグインシステムテスト"""
    print("\n【フェーズ4】プラグインシステムテスト...")

    try:
        from plugin_system import get_plugin_manager, HookType
        from unified_task_engine import UnifiedTaskEngine
        from config_manager import get_config_manager

        # プラグインシステム
        plugin_manager = get_plugin_manager()

        # プラグインがまだ読み込まれていない場合は読み込む
        if not plugin_manager.plugins:
            await plugin_manager.load_plugins()

        # プラグイン読み込み確認
        loaded_plugins = list(plugin_manager.plugins.keys())
        assert len(loaded_plugins) > 0, "プラグインが読み込まれていません"
        assert "genius_council" in loaded_plugins, "Genius Councilプラグインが見つかりません"

        # フック登録確認
        task_execution_plugins = len(plugin_manager.hooks[HookType.TASK_EXECUTION])
        assert task_execution_plugins > 0, "task_executionフックが登録されていません"

        # 統一エンジンとの統合確認
        config_manager = get_config_manager()
        engine = UnifiedTaskEngine(config_manager)
        assert hasattr(engine, "plugin_manager"), "プラグインマネージャーが統合されていません"
        assert engine.plugin_manager is plugin_manager, "プラグインマネージャーが正しく統合されていません"

        print(f"   ✅ プラグイン読み込み: {len(loaded_plugins)}個")
        print("   ✅ フック登録: OK")
        print("   ✅ 統一エンジン統合: OK")
        print("   ✅ フェーズ4: 完了")
        return True

    except Exception as e:
        print(f"   🚨 フェーズ4エラー: {e}")
        return False

async def test_backwards_compatibility():
    """後方互換性テスト"""
    print("\n【後方互換性】既存API維持テスト...")

    try:
        # 既存のインポートが動作するか確認
        from enhanced_memory_manager import get_enhanced_memory_manager
        from ai_manager import get_ai_manager
        from config_manager import get_config_manager
        from enhanced_cache import get_cache_manager

        # 既存のメソッドが動作するか確認（継承されたメソッド）
        memory_manager = get_enhanced_memory_manager()
        assert hasattr(memory_manager, "get_conversation_memory"), "get_conversation_memoryメソッドが見つかりません"
        assert hasattr(memory_manager, "add_conversation_memory"), "add_conversation_memoryメソッドが見つかりません"
        assert hasattr(memory_manager, "start_message_processing"), "start_message_processingメソッドが見つかりません"

        ai_manager = get_ai_manager()
        cache_manager = get_cache_manager()
        config_manager = get_config_manager()

        print("   ✅ 既存インポート: OK")
        print("   ✅ 既存メソッド: OK")
        print("   ✅ 後方互換性: 完了")
        return True

    except Exception as e:
        print(f"   🚨 後方互換性エラー: {e}")
        return False

async def run_full_integration_test():
    """完全統合テスト実行"""
    print("4フェーズ完全統合テスト実行中...")

    test_functions = [
        ("フェーズ1: AI設定外部化", test_phase1_ai_config_externalization),
        ("フェーズ2: 統一メモリ管理", test_phase2_unified_memory),
        ("フェーズ3: 統一タスクエンジン", test_phase3_unified_task_engine),
        ("フェーズ4: プラグインシステム", test_phase4_plugin_system),
        ("後方互換性", test_backwards_compatibility)
    ]

    results = []
    for phase_name, test_func in test_functions:
        try:
            result = await test_func()
            results.append((phase_name, result))
        except Exception as e:
            print(f"   🚨 {phase_name}テスト実行エラー: {e}")
            results.append((phase_name, False))

    # 結果集計
    passed = sum(1 for _, result in results if result)
    total = len(results)
    pass_rate = (passed / total) * 100

    print(f"\n=== 完全統合テスト結果 ===")
    print(f"実行フェーズ数: {total}")
    print(f"成功フェーズ: {passed}")
    print(f"失敗フェーズ: {total - passed}")
    print(f"成功率: {pass_rate:.1f}%")

    print(f"\n=== フェーズ別結果 ===")
    for phase_name, result in results:
        status = "✅ 成功" if result else "❌ 失敗"
        print(f"{phase_name}: {status}")

    if pass_rate == 100:
        print("\n🎉 全フェーズが正常に動作しています！")
        print("🚀 Discord Bot アーキテクチャ刷新プロジェクト完了！")
    elif pass_rate >= 80:
        print("\n⚠️ ほとんどのフェーズが動作していますが、一部改善が必要です。")
    else:
        print("\n🚨 複数のフェーズに問題があります。修正が必要です。")

    return pass_rate == 100

if __name__ == "__main__":
    # Windows環境での文字化け対策
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    try:
        result = asyncio.run(run_full_integration_test())
        sys.exit(0 if result else 1)
    except Exception as e:
        print(f"🚨 統合テスト実行中に予期しないエラーが発生しました: {e}")
        sys.exit(1)