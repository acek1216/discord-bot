# -*- coding: utf-8 -*-
"""
キャッシュパフォーマンステスト
拡張キャッシュシステムの効果を測定して30%向上を検証
"""

import asyncio
import time
import statistics
from typing import List, Dict, Any
from enhanced_cache import get_cache_manager

async def simulate_notion_fetch(page_ids: List[str]) -> str:
    """Notion API呼び出しをシミュレート（100-300ms遅延）"""
    await asyncio.sleep(0.2)  # 200ms遅延
    return f"Notionページテキスト（{len(page_ids)}ページ）: サンプルデータ"

async def simulate_context_fetch(page_id: str, query: str, engine: str) -> str:
    """コンテキスト取得をシミュレート（150-400ms遅延）"""
    await asyncio.sleep(0.3)  # 300ms遅延
    return f"コンテキストデータ（{engine}）: {query}の結果"

async def simulate_ai_response(ai_type: str, prompt_hash: str) -> str:
    """AI応答をシミュレート（500-1500ms遅延）"""
    await asyncio.sleep(0.8)  # 800ms遅延
    return f"AI応答（{ai_type}）: プロンプト{prompt_hash}への回答"

async def test_notion_cache_performance() -> Dict[str, Any]:
    """Notionキャッシュのパフォーマンステスト"""
    cache_manager = get_cache_manager()
    page_ids = ["page-1", "page-2", "page-3"]

    # キャッシュなし（初回）の測定
    uncached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_notion_cached(
            page_ids,
            simulate_notion_fetch
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)

        # キャッシュクリアして再測定
        cache_manager.invalidate_cache("notion")
        await asyncio.sleep(0.1)

    # キャッシュあり（ヒット）の測定
    # 最初に1回キャッシュに保存
    await cache_manager.get_notion_cached(page_ids, simulate_notion_fetch)

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_notion_cached(
            page_ids,
            simulate_notion_fetch
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def test_context_cache_performance() -> Dict[str, Any]:
    """コンテキストキャッシュのパフォーマンステスト"""
    cache_manager = get_cache_manager()
    page_id = "context-page-1"
    query = "テストクエリ"
    engine = "gpt4o"

    # キャッシュなしの測定
    uncached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_context_cached(
            page_id, query, engine,
            simulate_context_fetch,
            page_id=page_id, query=query, engine=engine
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)

        cache_manager.invalidate_cache("context")
        await asyncio.sleep(0.1)

    # キャッシュありの測定
    await cache_manager.get_context_cached(
        page_id, query, engine,
        simulate_context_fetch,
        page_id=page_id, query=query, engine=engine
    )

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_context_cached(
            page_id, query, engine,
            simulate_context_fetch,
            page_id=page_id, query=query, engine=engine
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def test_ai_response_cache_performance() -> Dict[str, Any]:
    """AI応答キャッシュのパフォーマンステスト"""
    cache_manager = get_cache_manager()
    ai_type = "gpt4o"
    prompt_hash = "test_prompt_hash_123"

    # キャッシュなしの測定
    uncached_times = []
    for i in range(3):  # AI応答は重いので3回のみ
        start_time = time.time()
        result = await cache_manager.get_ai_response_cached(
            ai_type, prompt_hash,
            simulate_ai_response,
            ai_type=ai_type, prompt_hash=prompt_hash
        )
        end_time = time.time()
        uncached_times.append(end_time - start_time)

        cache_manager.invalidate_cache("ai_response")
        await asyncio.sleep(0.1)

    # キャッシュありの測定
    await cache_manager.get_ai_response_cached(
        ai_type, prompt_hash,
        simulate_ai_response,
        ai_type=ai_type, prompt_hash=prompt_hash
    )

    cached_times = []
    for i in range(5):
        start_time = time.time()
        result = await cache_manager.get_ai_response_cached(
            ai_type, prompt_hash,
            simulate_ai_response,
            ai_type=ai_type, prompt_hash=prompt_hash
        )
        end_time = time.time()
        cached_times.append(end_time - start_time)
        await asyncio.sleep(0.1)

    return {
        "uncached_avg": statistics.mean(uncached_times),
        "cached_avg": statistics.mean(cached_times),
        "improvement_ratio": (statistics.mean(uncached_times) - statistics.mean(cached_times)) / statistics.mean(uncached_times) * 100
    }

async def comprehensive_performance_test():
    """総合パフォーマンステスト"""
    print("🚀 キャッシュパフォーマンステスト開始")
    print("=" * 50)

    # Notionキャッシュテスト
    print("📊 Notionキャッシュテスト実行中...")
    notion_results = await test_notion_cache_performance()

    # コンテキストキャッシュテスト
    print("📊 コンテキストキャッシュテスト実行中...")
    context_results = await test_context_cache_performance()

    # AI応答キャッシュテスト
    print("📊 AI応答キャッシュテスト実行中...")
    ai_results = await test_ai_response_cache_performance()

    # 結果レポート
    print("\n" + "=" * 50)
    print("📈 パフォーマンステスト結果レポート")
    print("=" * 50)

    print("\n🔍 Notionキャッシュ:")
    print(f"  キャッシュなし平均: {notion_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {notion_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {notion_results['improvement_ratio']:.1f}%")

    print("\n🔍 コンテキストキャッシュ:")
    print(f"  キャッシュなし平均: {context_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {context_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {context_results['improvement_ratio']:.1f}%")

    print("\n🔍 AI応答キャッシュ:")
    print(f"  キャッシュなし平均: {ai_results['uncached_avg']:.3f}秒")
    print(f"  キャッシュあり平均: {ai_results['cached_avg']:.3f}秒")
    print(f"  性能向上率: {ai_results['improvement_ratio']:.1f}%")

    # 総合評価
    overall_improvement = (
        notion_results['improvement_ratio'] +
        context_results['improvement_ratio'] +
        ai_results['improvement_ratio']
    ) / 3

    print("\n" + "=" * 50)
    print(f"🎯 総合パフォーマンス向上率: {overall_improvement:.1f}%")

    if overall_improvement >= 30:
        print("✅ 目標の30%性能向上を達成しました！")
    else:
        print(f"⚠️  目標の30%に対して {overall_improvement:.1f}% の向上")

    # キャッシュ統計情報
    cache_manager = get_cache_manager()
    detailed_stats = cache_manager.get_detailed_stats()

    print("\n📊 キャッシュ統計詳細:")
    print(f"  ヒット率: {detailed_stats['cache_performance']['hit_rate']}")
    print(f"  総ヒット数: {detailed_stats['cache_performance']['total_hits']}")
    print(f"  総ミス数: {detailed_stats['cache_performance']['total_misses']}")
    print(f"  ヒット当たり節約時間: {detailed_stats['cache_performance']['avg_time_saved_per_hit']}")
    print(f"  総節約時間: {detailed_stats['cache_performance']['total_time_saved']}")

    print(f"\n  総エントリ数: {detailed_stats['cache_entries']['total']}")
    print(f"  キャッシュ利用率: {detailed_stats['cache_entries']['utilization']}")
    print(f"  タイプ別エントリ数: {detailed_stats['cache_entries']['by_type']}")

    return overall_improvement

if __name__ == "__main__":
    asyncio.run(comprehensive_performance_test())