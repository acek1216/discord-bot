# -*- coding: utf-8 -*-
"""
プラグインシステム - 動的機能拡張アーキテクチャ
"""

import asyncio
import importlib
import importlib.util
import inspect
import time
import yaml
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Type
from pathlib import Path
from enum import Enum

import discord
from discord.ext import commands

from utils import safe_log

class HookType(Enum):
    """フックタイプの定義"""
    PRE_TASK_EXECUTION = "pre_task_execution"
    TASK_EXECUTION = "task_execution"
    POST_TASK_EXECUTION = "post_task_execution"
    AI_CLIENT_CREATION = "ai_client_creation"

@dataclass
class PluginInfo:
    """プラグイン情報"""
    name: str
    class_name: str
    module: str
    description: str
    version: str
    priority: int = 50
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)
    hooks: List[str] = field(default_factory=list)

@dataclass
class HookResult:
    """フック実行結果"""
    success: bool
    modified: bool = False
    data: Any = None
    error: Optional[str] = None
    execution_time: float = 0

class Plugin(ABC):
    """プラグインの基底クラス"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = True
        self.execution_count = 0
        self.error_count = 0

    @abstractmethod
    async def initialize(self) -> bool:
        """プラグイン初期化"""
        pass

    @abstractmethod
    async def cleanup(self):
        """プラグインクリーンアップ"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """プラグイン名"""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """プラグインバージョン"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """プラグイン説明"""
        pass

    # フックメソッド（オプション実装）
    async def pre_task_execution(self, bot: commands.Bot, message: discord.Message,
                               ai_type: str, context: Dict[str, Any]) -> HookResult:
        """タスク実行前フック"""
        return HookResult(success=True, modified=False)

    async def task_execution(self, bot: commands.Bot, message: discord.Message,
                           ai_type: str, context: Dict[str, Any]) -> HookResult:
        """タスク実行フック（メインロジック置き換え）"""
        return HookResult(success=False, error="Not implemented")

    async def post_task_execution(self, bot: commands.Bot, message: discord.Message,
                                ai_type: str, response: str, context: Dict[str, Any]) -> HookResult:
        """タスク実行後フック"""
        return HookResult(success=True, modified=False, data=response)

    async def ai_client_creation(self, ai_type: str, client_config: Dict[str, Any]) -> HookResult:
        """AIクライアント作成フック"""
        return HookResult(success=True, modified=False)

    def get_stats(self) -> Dict[str, Any]:
        """プラグイン統計を取得"""
        error_rate = self.error_count / max(self.execution_count, 1)
        return {
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "executions": self.execution_count,
            "errors": self.error_count,
            "error_rate": f"{error_rate:.1%}"
        }

class PluginManager:
    """プラグインマネージャー"""

    def __init__(self):
        self.plugins: Dict[str, Plugin] = {}
        self.plugin_infos: Dict[str, PluginInfo] = {}
        self.hooks: Dict[HookType, List[Plugin]] = {hook: [] for hook in HookType}
        self.config: Dict[str, Any] = {}
        self.config_file = Path(__file__).parent / "config" / "plugin_config.yaml"

        # 統計
        self.total_hook_calls = 0
        self.total_execution_time = 0

        self._load_config()

    def _load_config(self):
        """設定読み込み"""
        try:
            if not self.config_file.exists():
                safe_log("⚠️ プラグイン設定ファイルが見つかりません: ", str(self.config_file))
                self.config = {"plugin_system": {"enabled": True}, "plugins": {}}
                return

            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)

            safe_log("✅ プラグイン設定読み込み完了: ", f"{len(self.config.get('plugins', {}))}個のプラグイン設定")

        except Exception as e:
            safe_log("🚨 プラグイン設定読み込みエラー: ", e)
            self.config = {"plugin_system": {"enabled": True}, "plugins": {}}

    async def load_plugins(self):
        """プラグインを読み込み"""
        if not self.config.get("plugin_system", {}).get("enabled", True):
            safe_log("ℹ️ プラグインシステムは無効化されています", "")
            return

        plugin_configs = self.config.get("plugins", {})
        loaded_count = 0

        for plugin_name, plugin_config in plugin_configs.items():
            if not plugin_config.get("enabled", True):
                safe_log(f"⏭️ プラグインスキップ: ", f"{plugin_name} (無効化)")
                continue

            try:
                # プラグイン情報作成
                plugin_info = PluginInfo(
                    name=plugin_name,
                    class_name=plugin_config["class_name"],
                    module=plugin_config["module"],
                    description=plugin_config.get("description", ""),
                    version=plugin_config.get("version", "1.0.0"),
                    priority=plugin_config.get("priority", 50),
                    enabled=True,
                    config=plugin_config.get("config", {}),
                    hooks=plugin_config.get("hooks", [])
                )

                # プラグインロード
                plugin_instance = await self._load_plugin_instance(plugin_info)
                if plugin_instance:
                    self.plugins[plugin_name] = plugin_instance
                    self.plugin_infos[plugin_name] = plugin_info
                    self._register_plugin_hooks(plugin_name, plugin_instance, plugin_info.hooks)
                    loaded_count += 1

                    safe_log(f"✅ プラグイン読み込み成功: ", f"{plugin_name} v{plugin_info.version}")

            except Exception as e:
                safe_log(f"🚨 プラグイン読み込みエラー ({plugin_name}): ", e)

        safe_log(f"🔌 プラグインシステム初期化完了: ", f"{loaded_count}個のプラグインを読み込み")

    async def _load_plugin_instance(self, plugin_info: PluginInfo) -> Optional[Plugin]:
        """プラグインインスタンスを読み込み"""
        try:
            # モジュールのパス設定
            plugin_dirs = self.config.get("plugin_system", {}).get("plugin_directories", ["plugins"])

            plugin_instance = None
            for plugin_dir in plugin_dirs:
                module_path = Path(__file__).parent / plugin_dir / f"{plugin_info.module}.py"

                if module_path.exists():
                    # 動的インポート
                    spec = importlib.util.spec_from_file_location(plugin_info.module, module_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # クラス取得
                        plugin_class = getattr(module, plugin_info.class_name)
                        plugin_instance = plugin_class(plugin_info.config)

                        # 初期化
                        if await plugin_instance.initialize():
                            return plugin_instance
                        else:
                            safe_log(f"⚠️ プラグイン初期化失敗: ", plugin_info.name)
                            return None

            if not plugin_instance:
                # フォールバック：モックプラグイン
                plugin_instance = await self._create_mock_plugin(plugin_info)
                return plugin_instance

        except Exception as e:
            safe_log(f"🚨 プラグインインスタンス作成エラー ({plugin_info.name}): ", e)
            return None

    async def _create_mock_plugin(self, plugin_info: PluginInfo) -> Plugin:
        """モックプラグインを作成（プラグインファイルが見つからない場合）"""

        class MockPlugin(Plugin):
            def __init__(self, config):
                super().__init__(config)
                self._name = plugin_info.name
                self._version = plugin_info.version
                self._description = plugin_info.description

            async def initialize(self) -> bool:
                safe_log(f"🔧 モックプラグイン作成: ", self._name)
                return True

            async def cleanup(self):
                pass

            @property
            def name(self) -> str:
                return self._name

            @property
            def version(self) -> str:
                return self._version

            @property
            def description(self) -> str:
                return self._description

        return MockPlugin(plugin_info.config)

    def _register_plugin_hooks(self, plugin_name: str, plugin: Plugin, hook_names: List[str]):
        """プラグインのフックを登録"""
        for hook_name in hook_names:
            try:
                hook_type = HookType(hook_name)

                # プラグインがフックメソッドを実装しているかチェック
                if hasattr(plugin, hook_name):
                    self.hooks[hook_type].append(plugin)
                    safe_log(f"🔗 フック登録: ", f"{plugin_name} -> {hook_name}")

            except ValueError:
                safe_log(f"⚠️ 未知のフックタイプ: ", f"{hook_name} ({plugin_name})")

    async def execute_hook(self, hook_type: HookType, **kwargs) -> List[HookResult]:
        """フックを実行"""
        if hook_type not in self.hooks:
            return []

        start_time = time.time()
        results = []
        plugins = self.hooks[hook_type]

        # 優先度順にソート
        plugins.sort(key=lambda p: self.plugin_infos.get(p.name, PluginInfo("", "", "", "", "")).priority, reverse=True)

        for plugin in plugins:
            try:
                plugin.execution_count += 1

                # フックメソッド実行
                hook_method = getattr(plugin, hook_type.value)
                result = await hook_method(**kwargs)

                if result.success:
                    results.append(result)
                else:
                    plugin.error_count += 1
                    safe_log(f"⚠️ プラグインフックエラー ({plugin.name}): ", result.error or "Unknown error")

            except Exception as e:
                plugin.error_count += 1
                safe_log(f"🚨 プラグインフック実行エラー ({plugin.name}): ", e)
                results.append(HookResult(success=False, error=str(e)))

        # 統計更新
        self.total_hook_calls += len(plugins)
        self.total_execution_time += time.time() - start_time

        return results

    async def reload_plugins(self):
        """プラグインをリロード"""
        safe_log("🔄 プラグインリロード開始", "")

        # 既存プラグインのクリーンアップ
        for plugin in self.plugins.values():
            try:
                await plugin.cleanup()
            except Exception as e:
                safe_log(f"⚠️ プラグインクリーンアップエラー: ", e)

        # リセット
        self.plugins.clear()
        self.plugin_infos.clear()
        for hook_list in self.hooks.values():
            hook_list.clear()

        # 設定再読み込み
        self._load_config()

        # プラグイン再読み込み
        await self.load_plugins()

    def get_plugin_stats(self) -> Dict[str, Any]:
        """プラグイン統計を取得"""
        plugin_stats = {name: plugin.get_stats() for name, plugin in self.plugins.items()}

        hook_stats = {}
        for hook_type, plugins in self.hooks.items():
            hook_stats[hook_type.value] = {
                "registered_plugins": len(plugins),
                "plugin_names": [p.name for p in plugins]
            }

        avg_execution_time = self.total_execution_time / max(self.total_hook_calls, 1)

        return {
            "system_info": {
                "total_plugins": len(self.plugins),
                "enabled_plugins": len([p for p in self.plugins.values() if p.enabled]),
                "total_hook_calls": self.total_hook_calls,
                "avg_hook_execution_time": f"{avg_execution_time:.3f}s"
            },
            "plugins": plugin_stats,
            "hooks": hook_stats
        }

    def get_plugin(self, plugin_name: str) -> Optional[Plugin]:
        """特定のプラグインを取得"""
        return self.plugins.get(plugin_name)

    def enable_plugin(self, plugin_name: str) -> bool:
        """プラグインを有効化"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name].enabled = True
            safe_log(f"✅ プラグイン有効化: ", plugin_name)
            return True
        return False

    def disable_plugin(self, plugin_name: str) -> bool:
        """プラグインを無効化"""
        if plugin_name in self.plugins:
            self.plugins[plugin_name].enabled = False
            safe_log(f"⏸️ プラグイン無効化: ", plugin_name)
            return True
        return False

    async def cleanup_all_plugins(self):
        """全プラグインをクリーンアップ"""
        for plugin in self.plugins.values():
            try:
                await plugin.cleanup()
            except Exception as e:
                safe_log(f"⚠️ プラグインクリーンアップエラー ({plugin.name}): ", e)

        safe_log("🧹 全プラグインクリーンアップ完了", "")

# グローバルインスタンス
_plugin_manager: Optional[PluginManager] = None

def get_plugin_manager() -> PluginManager:
    """プラグインマネージャーインスタンスを取得"""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
        safe_log("✅ プラグインマネージャー初期化完了", "")
    return _plugin_manager

async def initialize_plugin_system():
    """プラグインシステムを初期化"""
    plugin_manager = get_plugin_manager()
    await plugin_manager.load_plugins()

async def cleanup_plugin_system():
    """プラグインシステムをクリーンアップ"""
    plugin_manager = get_plugin_manager()
    await plugin_manager.cleanup_all_plugins()

if __name__ == "__main__":
    # テスト実行
    async def test_plugin_system():
        print("=== Plugin System Test ===")

        plugin_manager = PluginManager()
        await plugin_manager.load_plugins()

        stats = plugin_manager.get_plugin_stats()
        print(f"読み込みプラグイン数: {stats['system_info']['total_plugins']}")

        for plugin_name in stats['plugins'].keys():
            print(f"  - {plugin_name}")

    asyncio.run(test_plugin_system())