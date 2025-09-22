# -*- coding: utf-8 -*-
"""
レート制限管理システム
各AIサービスの呼び出し制限を統一管理
"""

import asyncio
import time
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
from utils import safe_log

class RateLimitStatus(Enum):
    """レート制限ステータス"""
    ALLOWED = "allowed"
    LIMITED = "limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    ERROR = "error"

@dataclass
class RateLimitConfig:
    """レート制限設定"""
    service_name: str
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000
    burst_limit: int = 10  # 連続リクエスト制限
    cooldown_seconds: float = 1.0  # 最小リクエスト間隔
    priority_weight: float = 1.0  # 優先度（低いほど優先）

@dataclass
class RateLimitResult:
    """レート制限チェック結果"""
    status: RateLimitStatus
    allowed: bool
    wait_time: float = 0.0
    remaining_requests: int = 0
    reset_time: Optional[float] = None
    message: str = ""

class RateLimitBucket:
    """レート制限バケット（トークンバケット方式）"""

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.minute_requests: deque = deque()
        self.hour_requests: deque = deque()
        self.day_requests: deque = deque()
        self.last_request_time = 0.0
        self.burst_count = 0
        self.burst_reset_time = 0.0
        self.total_requests = 0
        self.denied_requests = 0

    def check_rate_limit(self) -> RateLimitResult:
        """レート制限をチェック"""
        current_time = time.time()

        # 古いリクエストを削除
        self._cleanup_old_requests(current_time)

        # バースト制限チェック
        if current_time - self.burst_reset_time > 60:  # 1分でリセット
            self.burst_count = 0
            self.burst_reset_time = current_time

        # クールダウンチェック
        if current_time - self.last_request_time < self.config.cooldown_seconds:
            wait_time = self.config.cooldown_seconds - (current_time - self.last_request_time)
            self.denied_requests += 1
            return RateLimitResult(
                status=RateLimitStatus.LIMITED,
                allowed=False,
                wait_time=wait_time,
                message=f"クールダウン中: {wait_time:.1f}秒待機"
            )

        # バースト制限チェック
        if self.burst_count >= self.config.burst_limit:
            wait_time = 60 - (current_time - self.burst_reset_time)
            self.denied_requests += 1
            return RateLimitResult(
                status=RateLimitStatus.LIMITED,
                allowed=False,
                wait_time=wait_time,
                message=f"バースト制限: {wait_time:.1f}秒待機"
            )

        # 分単位制限チェック
        if len(self.minute_requests) >= self.config.requests_per_minute:
            oldest_minute_request = self.minute_requests[0]
            wait_time = 60 - (current_time - oldest_minute_request)
            self.denied_requests += 1
            return RateLimitResult(
                status=RateLimitStatus.LIMITED,
                allowed=False,
                wait_time=wait_time,
                remaining_requests=0,
                reset_time=oldest_minute_request + 60,
                message=f"分間制限到達: {wait_time:.1f}秒待機"
            )

        # 時間単位制限チェック
        if len(self.hour_requests) >= self.config.requests_per_hour:
            oldest_hour_request = self.hour_requests[0]
            wait_time = 3600 - (current_time - oldest_hour_request)
            self.denied_requests += 1
            return RateLimitResult(
                status=RateLimitStatus.QUOTA_EXCEEDED,
                allowed=False,
                wait_time=wait_time,
                remaining_requests=0,
                reset_time=oldest_hour_request + 3600,
                message=f"時間制限到達: {wait_time/60:.1f}分待機"
            )

        # 日単位制限チェック
        if len(self.day_requests) >= self.config.requests_per_day:
            oldest_day_request = self.day_requests[0]
            wait_time = 86400 - (current_time - oldest_day_request)
            self.denied_requests += 1
            return RateLimitResult(
                status=RateLimitStatus.QUOTA_EXCEEDED,
                allowed=False,
                wait_time=wait_time,
                remaining_requests=0,
                reset_time=oldest_day_request + 86400,
                message=f"日間制限到達: {wait_time/3600:.1f}時間待機"
            )

        # リクエスト許可
        remaining_minute = self.config.requests_per_minute - len(self.minute_requests)
        return RateLimitResult(
            status=RateLimitStatus.ALLOWED,
            allowed=True,
            remaining_requests=remaining_minute,
            message="リクエスト許可"
        )

    def record_request(self) -> None:
        """リクエストを記録"""
        current_time = time.time()

        self.minute_requests.append(current_time)
        self.hour_requests.append(current_time)
        self.day_requests.append(current_time)

        self.last_request_time = current_time
        self.burst_count += 1
        self.total_requests += 1

    def _cleanup_old_requests(self, current_time: float) -> None:
        """古いリクエスト記録を削除"""
        # 1分より古いものを削除
        while self.minute_requests and current_time - self.minute_requests[0] > 60:
            self.minute_requests.popleft()

        # 1時間より古いものを削除
        while self.hour_requests and current_time - self.hour_requests[0] > 3600:
            self.hour_requests.popleft()

        # 1日より古いものを削除
        while self.day_requests and current_time - self.day_requests[0] > 86400:
            self.day_requests.popleft()

    def get_stats(self) -> Dict[str, any]:
        """統計情報を取得"""
        current_time = time.time()
        self._cleanup_old_requests(current_time)

        success_rate = (self.total_requests - self.denied_requests) / max(self.total_requests, 1)

        return {
            "service_name": self.config.service_name,
            "total_requests": self.total_requests,
            "denied_requests": self.denied_requests,
            "success_rate": f"{success_rate:.1%}",
            "current_usage": {
                "minute": f"{len(self.minute_requests)}/{self.config.requests_per_minute}",
                "hour": f"{len(self.hour_requests)}/{self.config.requests_per_hour}",
                "day": f"{len(self.day_requests)}/{self.config.requests_per_day}",
            },
            "burst_count": self.burst_count,
            "last_request": self.last_request_time
        }

class GlobalRateLimiter:
    """グローバルレート制限管理"""

    def __init__(self):
        self.buckets: Dict[str, RateLimitBucket] = {}
        self.default_configs = self._get_default_configs()
        self.global_lock = asyncio.Lock()

    def _get_default_configs(self) -> Dict[str, RateLimitConfig]:
        """デフォルト設定を取得"""
        return {
            "openai": RateLimitConfig(
                service_name="OpenAI",
                requests_per_minute=100,
                requests_per_hour=6000,
                requests_per_day=100000,
                burst_limit=10,
                cooldown_seconds=0.5,
                priority_weight=1.0
            ),
            "gemini": RateLimitConfig(
                service_name="Google Gemini",
                requests_per_minute=40,
                requests_per_hour=2000,
                requests_per_day=20000,
                burst_limit=3,
                cooldown_seconds=1.5,
                priority_weight=1.2
            ),
            "claude": RateLimitConfig(
                service_name="Anthropic Claude",
                requests_per_minute=30,
                requests_per_hour=1500,
                requests_per_day=15000,
                burst_limit=3,
                cooldown_seconds=2.0,
                priority_weight=1.1
            ),
            "grok": RateLimitConfig(
                service_name="Grok (X.AI)",
                requests_per_minute=25,
                requests_per_hour=1000,
                requests_per_day=10000,
                burst_limit=2,
                cooldown_seconds=2.4,
                priority_weight=1.3
            ),
            "perplexity": RateLimitConfig(
                service_name="Perplexity AI",
                requests_per_minute=35,
                requests_per_hour=1800,
                requests_per_day=18000,
                burst_limit=4,
                cooldown_seconds=1.7,
                priority_weight=1.1
            ),
            "mistral": RateLimitConfig(
                service_name="Mistral AI",
                requests_per_minute=45,
                requests_per_hour=2500,
                requests_per_day=25000,
                burst_limit=4,
                cooldown_seconds=1.3,
                priority_weight=1.0
            ),
            "llama": RateLimitConfig(
                service_name="Llama (Vertex AI)",
                requests_per_minute=30,
                requests_per_hour=1200,
                requests_per_day=12000,
                burst_limit=2,
                cooldown_seconds=2.0,
                priority_weight=1.2
            ),
        }

    def get_bucket(self, service_name: str) -> RateLimitBucket:
        """レート制限バケットを取得"""
        if service_name not in self.buckets:
            config = self.default_configs.get(service_name,
                RateLimitConfig(service_name=service_name))
            self.buckets[service_name] = RateLimitBucket(config)
        return self.buckets[service_name]

    async def check_rate_limit(self, service_name: str, priority: float = 1.0) -> RateLimitResult:
        """レート制限をチェック"""
        async with self.global_lock:
            bucket = self.get_bucket(service_name)
            result = bucket.check_rate_limit()

            # 優先度による調整
            if not result.allowed and priority < 0.5:  # 高優先度リクエスト
                result.wait_time *= 0.7  # 待機時間を短縮

            return result

    async def acquire_request_slot(self, service_name: str, priority: float = 1.0) -> RateLimitResult:
        """リクエストスロットを取得"""
        max_retries = 3
        for attempt in range(max_retries):
            result = await self.check_rate_limit(service_name, priority)

            if result.allowed:
                async with self.global_lock:
                    bucket = self.get_bucket(service_name)
                    bucket.record_request()
                    safe_log(f"🟢 レート制限OK: ", f"{service_name} - 残り{result.remaining_requests}回")
                return result
            else:
                if attempt < max_retries - 1:
                    safe_log(f"🟡 レート制限待機: ", f"{service_name} - {result.wait_time:.1f}秒")
                    await asyncio.sleep(min(result.wait_time, 30))  # 最大30秒待機
                else:
                    safe_log(f"🔴 レート制限拒否: ", f"{service_name} - {result.message}")

        return result

    def get_all_stats(self) -> Dict[str, Dict]:
        """全サービスの統計を取得"""
        stats = {}
        for service_name, bucket in self.buckets.items():
            stats[service_name] = bucket.get_stats()
        return stats

    def get_service_health(self) -> Dict[str, str]:
        """各サービスの健全性を取得"""
        health = {}
        for service_name, bucket in self.buckets.items():
            stats = bucket.get_stats()
            current_minute_usage = len(bucket.minute_requests)
            max_minute = bucket.config.requests_per_minute

            if current_minute_usage < max_minute * 0.5:
                health[service_name] = "healthy"
            elif current_minute_usage < max_minute * 0.8:
                health[service_name] = "warning"
            else:
                health[service_name] = "critical"

        return health

    async def reset_service_limits(self, service_name: str) -> bool:
        """特定サービスの制限をリセット（管理者用）"""
        if service_name in self.buckets:
            async with self.global_lock:
                del self.buckets[service_name]
                safe_log(f"🔄 レート制限リセット: ", service_name)
                return True
        return False

    def update_service_config(self, service_name: str, config: RateLimitConfig) -> None:
        """サービス設定を更新"""
        self.default_configs[service_name] = config
        if service_name in self.buckets:
            self.buckets[service_name].config = config

# グローバルレートリミッター
_global_rate_limiter: Optional[GlobalRateLimiter] = None

def get_rate_limiter() -> GlobalRateLimiter:
    """グローバルレートリミッターを取得"""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = GlobalRateLimiter()
        safe_log("✅ グローバルレートリミッター初期化完了", "")
    return _global_rate_limiter

async def rate_limited_request(service_name: str, request_func, *args, priority: float = 1.0, **kwargs):
    """レート制限付きリクエスト実行"""
    rate_limiter = get_rate_limiter()

    # レート制限チェック＆スロット取得
    result = await rate_limiter.acquire_request_slot(service_name, priority)

    if not result.allowed:
        raise Exception(f"レート制限により拒否: {result.message}")

    # 実際のリクエスト実行
    try:
        start_time = time.time()
        response = await request_func(*args, **kwargs)
        end_time = time.time()

        safe_log(f"⚡ API呼び出し成功: ",
                f"{service_name} - {end_time - start_time:.2f}秒")
        return response

    except Exception as e:
        safe_log(f"🚨 API呼び出しエラー: ", f"{service_name} - {e}")
        raise

# 便利なデコレータ
def with_rate_limit(service_name: str, priority: float = 1.0):
    """レート制限デコレータ"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await rate_limited_request(service_name, func, *args, priority=priority, **kwargs)
        return wrapper
    return decorator