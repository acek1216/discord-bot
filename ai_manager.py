# -*- coding: utf-8 -*-
"""
統一AIクライアント管理システム
"""

import asyncio
import functools
import time
from typing import Dict, Callable, Any, Optional, List
from dataclasses import dataclass
from abc import ABC, abstractmethod

from utils import safe_log
from rate_limiter import get_rate_limiter, rate_limited_request
from ai_config_loader import get_ai_config_loader, AIModelConfig

# AIClientConfig は ai_config_loader.AIModelConfig に移行
# 後方互換性のためのエイリアス
AIClientConfig = AIModelConfig

class AIClientError(Exception):
    """AI関連エラーの基底クラス"""
    def __init__(self, ai_name: str, message: str, original_error: Exception = None):
        self.ai_name = ai_name
        self.original_error = original_error
        super().__init__(f"{ai_name}エラー: {message}")

def with_ai_error_handling(ai_name: str, max_retries: int = 2):
    """AIエラーハンドリングデコレータ"""
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    start_time = time.time()
                    result = await func(*args, **kwargs)
                    end_time = time.time()

                    # 結果検証
                    if not result or not str(result).strip():
                        raise AIClientError(ai_name, "応答が空でした")

                    # 成功ログ
                    if attempt > 0:
                        safe_log(f"✅ {ai_name}復旧成功: ", f"試行{attempt + 1}回目で成功 ({end_time - start_time:.2f}s)")

                    return result

                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        wait_time = 2 ** attempt  # 指数バックオフ
                        safe_log(f"⚠️ {ai_name}エラー（試行{attempt + 1}）: ", f"{str(e)[:100]}... {wait_time}秒後に再試行")
                        await asyncio.sleep(wait_time)
                    else:
                        safe_log(f"🚨 {ai_name}最終エラー: ", e)

            # 全試行失敗時
            error_msg = str(last_error)[:200] if last_error else "不明なエラー"
            return f"{ai_name}エラー: {error_msg}"

        return wrapper
    return decorator

class AIClient(ABC):
    """AI クライアントの抽象基底クラス"""

    def __init__(self, config: AIModelConfig):
        self.config = config
        self.call_count = 0
        self.error_count = 0
        self.total_response_time = 0.0

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """AI応答を生成"""
        pass

    def get_stats(self) -> Dict[str, Any]:
        """統計情報を取得"""
        avg_time = self.total_response_time / max(self.call_count, 1)
        error_rate = self.error_count / max(self.call_count, 1)

        return {
            "name": self.config.name,
            "calls": self.call_count,
            "errors": self.error_count,
            "error_rate": f"{error_rate:.1%}",
            "avg_response_time": f"{avg_time:.2f}s"
        }

class OpenAIClient(AIClient):
    """OpenAI系クライアント"""
    def __init__(self, config: AIModelConfig, openai_client, model: str = None):
        super().__init__(config)
        self.openai_client = openai_client
        self.model = model or config.model

    @with_ai_error_handling("OpenAI")
    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        self.call_count += 1
        start_time = time.time()

        try:
            messages = []
            if system_prompt or self.config.system_prompt:
                messages.append({"role": "system", "content": system_prompt or self.config.system_prompt})
            messages.append({"role": "user", "content": prompt})

            # モデルによってmax_tokensかmax_completion_tokensかを判断
            completion_params = {
                "model": self.model,
                "messages": messages,
                "temperature": self.config.temperature
            }

            # デバッグ用：モデル名をログ出力
            print(f"🔍 使用モデル: {self.model}")

            # max_tokensとtemperatureのフォールバック処理
            try:
                completion_params["max_tokens"] = 2000
                print(f"🔄 max_tokens試行: {2000}")
                response = await self.openai_client.chat.completions.create(**completion_params)
            except Exception as e:
                error_str = str(e)
                if "max_tokens" in error_str:
                    # max_tokensがサポートされていない場合、パラメータなしで試行
                    print(f"🔄 max_tokensパラメータなしで試行")
                    completion_params.pop("max_tokens", None)
                    try:
                        response = await self.openai_client.chat.completions.create(**completion_params)
                    except Exception as e2:
                        if "temperature" in str(e2):
                            print(f"🔄 temperatureパラメータもなしで試行")
                            completion_params.pop("temperature", None)
                            response = await self.openai_client.chat.completions.create(**completion_params)
                        else:
                            raise e2
                elif "temperature" in error_str:
                    # temperatureがサポートされていない場合、パラメータなしで試行
                    print(f"🔄 temperatureパラメータなしで試行")
                    completion_params.pop("temperature", None)
                    response = await self.openai_client.chat.completions.create(**completion_params)
                else:
                    raise e

            result = response.choices[0].message.content
            self.total_response_time += time.time() - start_time
            return result

        except Exception as e:
            self.error_count += 1
            raise e

class GeminiClient(AIClient):
    """Gemini系クライアント"""
    def __init__(self, config: AIModelConfig, generate_func: Callable):
        super().__init__(config)
        self.generate_func = generate_func

    @with_ai_error_handling("Gemini")
    async def generate(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        self.call_count += 1
        start_time = time.time()

        try:
            # system_promptが指定されている場合は統合
            if system_prompt or self.config.system_prompt:
                full_prompt = f"{system_prompt or self.config.system_prompt}\n\n{prompt}"
            else:
                full_prompt = prompt

            result = await self.generate_func(full_prompt)
            self.total_response_time += time.time() - start_time
            return result

        except Exception as e:
            self.error_count += 1
            raise e

class ExternalAPIClient(AIClient):
    """外部API系クライアント（Claude, Grok, Perplexity等）"""
    def __init__(self, config: AIModelConfig, api_func: Callable, api_key: str):
        super().__init__(config)
        self.api_func = api_func
        self.api_key = api_key

    @with_ai_error_handling("ExternalAPI")
    async def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        start_time = time.time()

        try:
            result = await self.api_func(self.api_key, "user", prompt)
            self.total_response_time += time.time() - start_time
            return result

        except Exception as e:
            self.error_count += 1
            raise e

class AIClientManager:
    """統一AIクライアント管理システム"""

    def __init__(self):
        self.clients: Dict[str, AIClient] = {}
        self.initialized = False

    def initialize(self, bot) -> None:
        """Botインスタンスを使ってクライアントを初期化（YAML設定使用）"""
        if self.initialized:
            return

        # 外部設定ローダーを使用
        config_loader = get_ai_config_loader()
        ai_configs = config_loader.get_all_ai_configs()

        if not ai_configs:
            safe_log("😨 AI設定が空です。フォールバック設定を使用します", "")
            config_loader.reload_config()  # リロードしてフォールバックを適用
            ai_configs = config_loader.get_all_ai_configs()

        from ai_clients import (
            ask_gpt5, ask_gpt4o, ask_gpt5_mini, ask_gemini_2_5_pro,
            ask_claude, ask_grok, ask_llama, ask_lalah, ask_rekus, ask_o1_pro
        )

        # YAML設定からクライアントを動的生成
        self._create_clients_from_config(bot, ai_configs, {
            'ask_gpt5': ask_gpt5,
            'ask_gpt4o': ask_gpt4o,
            'ask_gpt5_mini': ask_gpt5_mini,
            'ask_gemini_2_5_pro': ask_gemini_2_5_pro,
            'ask_claude': ask_claude,
            'ask_grok': ask_grok,
            'ask_llama': ask_llama,
            'ask_lalah': ask_lalah,
            'ask_rekus': ask_rekus,
            'ask_o1_pro': ask_o1_pro
        })

        self.initialized = True
        safe_log("✅ AIClientManager初期化完了: ", f"{len(self.clients)}個のクライアント登録")

    def _create_clients_from_config(self, bot, ai_configs: Dict[str, AIModelConfig], api_functions: Dict[str, Callable]):
        """設定からクライアントを動的生成"""
        for ai_type, config in ai_configs.items():
            try:
                if config.client_type == "openai":
                    # OpenAI系クライアント
                    self.clients[ai_type] = OpenAIClient(
                        config,
                        bot.openai_client
                    )

                elif config.client_type == "gemini":
                    # Gemini系クライアント
                    # モデル名によってAPI関数を選択
                    if "2.5" in config.model:
                        api_func = api_functions.get('ask_gemini_2_5_pro')
                    elif "1.5" in config.model:
                        api_func = api_functions.get('ask_gemini_2_5_pro')
                    else:
                        api_func = api_functions.get('ask_gemini_2_5_pro')  # デフォルト

                    if api_func:
                        self.clients[ai_type] = GeminiClient(config, api_func)

                elif config.client_type == "external_api":
                    # 外部API系クライアント
                    api_func = api_functions.get(config.api_function)
                    if api_func and config.api_function == "ask_claude":
                        self.clients[ai_type] = ExternalAPIClient(
                            config, api_func, bot.openrouter_api_key
                        )
                    elif api_func and config.api_function == "ask_grok":
                        self.clients[ai_type] = ExternalAPIClient(
                            config, api_func, bot.grok_api_key
                        )
                    elif api_func and config.api_function == "ask_rekus":
                        # Perplexity用
                        self.clients[ai_type] = GeminiClient(
                            config, lambda prompt: api_func(bot.perplexity_api_key, prompt)
                        )
                    elif api_func and config.api_function == "ask_lalah":
                        # Mistral用
                        self.clients[ai_type] = GeminiClient(
                            config, lambda prompt: api_func(bot.mistral_client, prompt)
                        )

                elif config.client_type == "vertex_ai":
                    # Vertex AI (Llama)系クライアント
                    if hasattr(bot, 'llama_model') and bot.llama_model:
                        api_func = api_functions.get('ask_llama')
                        if api_func:
                            self.clients[ai_type] = GeminiClient(
                                config,
                                lambda prompt: api_func(bot.llama_model, "llama_user", prompt)
                            )

                elif config.client_type == "mistral":
                    # Mistral系クライアント
                    api_func = api_functions.get('ask_lalah')
                    if api_func:
                        self.clients[ai_type] = GeminiClient(
                            config, lambda prompt: api_func(bot.mistral_client, prompt)
                        )

                if ai_type in self.clients:
                    safe_log(f"✅ AIクライアント生成: ", f"{ai_type} -> {config.name}")
                else:
                    safe_log(f"⚠️ AIクライアント生成失敗: ", f"{ai_type} ({config.client_type})")

            except Exception as e:
                safe_log(f"😨 AIクライアント初期化エラー ({ai_type}): ", e)

        # 旧のハードコード設定を削除し、動的設定に置き換え

    async def ask_ai(self, ai_type: str, prompt: str, priority: float = 1.0, **kwargs) -> str:
        """レート制限付き統一AI呼び出しインターフェース"""
        if not self.initialized:
            raise RuntimeError("AIClientManagerが初期化されていません")

        if ai_type not in self.clients:
            available = ", ".join(self.clients.keys())
            raise ValueError(f"不明なAIタイプ: {ai_type}. 利用可能: {available}")

        client = self.clients[ai_type]

        # レート制限付きでリクエスト実行
        service_name = self._get_service_name(ai_type)
        return await rate_limited_request(
            service_name,
            client.generate,
            prompt,
            priority=priority,
            **kwargs
        )

    def _get_service_name(self, ai_type: str) -> str:
        """AIタイプからサービス名を取得"""
        service_mapping = {
            "gpt5": "openai",
            "gpt4o": "openai",
            "gpt5mini": "openai",
            "gemini": "gemini",
            "claude": "claude",
            "grok": "grok",
            "mistral": "mistral",
            "llama": "llama",
            "perplexity": "perplexity",
            "o3": "openai",
            "genius": "openai"
        }
        return service_mapping.get(ai_type, ai_type)

    def get_available_ais(self) -> List[str]:
        """利用可能なAIリストを取得"""
        return list(self.clients.keys())

    def get_ai_info(self, ai_type: str) -> Dict[str, Any]:
        """AI情報を取得"""
        if ai_type not in self.clients:
            return {"error": "AI not found"}

        client = self.clients[ai_type]
        return {
            "name": client.config.name,
            "description": client.config.description,
            "supports_memory": client.config.supports_memory,
            "supports_attachments": client.config.supports_attachments,
            "stats": client.get_stats()
        }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """全AI統計を取得"""
        ai_stats = {ai_type: client.get_stats() for ai_type, client in self.clients.items()}

        # レート制限統計も追加
        rate_limiter = get_rate_limiter()
        rate_limit_stats = rate_limiter.get_all_stats()
        service_health = rate_limiter.get_service_health()

        return {
            "ai_performance": ai_stats,
            "rate_limits": rate_limit_stats,
            "service_health": service_health
        }

# グローバルインスタンス
ai_manager = AIClientManager()

def get_ai_manager() -> AIClientManager:
    """AIマネージャーインスタンスを取得"""
    return ai_manager