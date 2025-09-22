# notion_utils.py

import asyncio
import os
import re
import time
from datetime import datetime, timezone, timedelta
from notion_client import Client
from typing import Dict, Tuple, Optional

# グローバル変数 (Notionクライアント)
notion: Client = None

# Notionキャッシュクラス
class NotionCache:
    def __init__(self, ttl: int = 300):  # 5分キャッシュ
        self.cache: Dict[str, Tuple[str, float]] = {}
        self.ttl = ttl
        self.lock = asyncio.Lock()
        self.hit_count = 0
        self.miss_count = 0

    async def get_cached_page_text(self, page_ids: list) -> str:
        """キャッシュ付きでNotionページテキストを取得"""
        cache_key = "_".join(sorted(page_ids))  # ソートして一意性を保証
        current_time = time.time()

        async with self.lock:
            # キャッシュヒット確認
            if cache_key in self.cache:
                data, timestamp = self.cache[cache_key]
                if current_time - timestamp < self.ttl:
                    self.hit_count += 1
                    print(f"✅ Notionキャッシュヒット: {cache_key[:20]}... (ヒット率: {self.get_hit_rate():.1%})")
                    return data
                else:
                    # 期限切れキャッシュを削除
                    del self.cache[cache_key]

            # キャッシュミス - 新しいデータを取得
            self.miss_count += 1
            print(f"🔄 Notionキャッシュミス: {cache_key[:20]}... データを取得中...")

        # ロック外でAPI呼び出し（パフォーマンス向上）
        text = await get_notion_page_text_original(page_ids)

        async with self.lock:
            # キャッシュに保存
            self.cache[cache_key] = (text, current_time)
            print(f"💾 Notionキャッシュ保存: {cache_key[:20]}... (サイズ: {len(text)}文字)")

            # 古いキャッシュエントリをクリーンアップ（メモリ効率化）
            self._cleanup_expired_entries(current_time)

        return text

    def _cleanup_expired_entries(self, current_time: float):
        """期限切れのキャッシュエントリを削除"""
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if current_time - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

        if expired_keys:
            print(f"🗑️ 期限切れキャッシュを{len(expired_keys)}件削除")

    def get_hit_rate(self) -> float:
        """キャッシュヒット率を計算"""
        total = self.hit_count + self.miss_count
        return self.hit_count / total if total > 0 else 0.0

    def get_cache_stats(self) -> dict:
        """キャッシュ統計を取得"""
        return {
            "hit_count": self.hit_count,
            "miss_count": self.miss_count,
            "hit_rate": self.get_hit_rate(),
            "cache_size": len(self.cache),
            "ttl_seconds": self.ttl
        }

    async def clear_cache(self):
        """キャッシュを手動でクリア"""
        async with self.lock:
            cleared_count = len(self.cache)
            self.cache.clear()
            print(f"🧹 Notionキャッシュを手動クリア: {cleared_count}件削除")

# グローバルキャッシュインスタンス
notion_cache = NotionCache(ttl=300)  # 5分キャッシュ

# 日本時間の日時フォーマット関数
def get_jst_timestamp(include_seconds: bool = False) -> str:
    """
    日本時間の現在時刻を取得してフォーマット
    include_seconds: Trueの場合は秒まで、Falseの場合は分まで
    """
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    
    if include_seconds:
        return now.strftime("%m/%d %H:%M:%S")
    else:
        return now.strftime("%m/%d %H:%M")

def format_with_timestamp(text: str, prefix: str = "", include_seconds: bool = False) -> str:
    """
    テキストに小さな日時を付加
    """
    timestamp = get_jst_timestamp(include_seconds)
    if prefix:
        return f"{prefix} ({timestamp})\n{text}"
    else:
        return f"({timestamp}) {text}"

# デバッグ用: 日時フォーマット関数のテスト
def test_timestamp():
    """日時フォーマット関数のテスト"""
    try:
        timestamp = get_jst_timestamp()
        print(f"🕐 デバッグ: 現在の日時 = {timestamp}")
        return timestamp
    except Exception as e:
        print(f"🚨 日時フォーマットエラー: {e}")
        return f"時刻取得エラー: {e}"

# NOTION_PAGE_MAPの読み込み
NOTION_PAGE_MAP_STRING = os.getenv("NOTION_PAGE_MAP_STRING", "")
NOTION_PAGE_MAP = {}
if NOTION_PAGE_MAP_STRING:
    try:
        pairs = NOTION_PAGE_MAP_STRING.split(',')
        print(f"🔍 NOTION_PAGE_MAP解析開始: {len(pairs)}個のペアを処理")
        for pair in pairs:
            if ':' in pair:
                thread_id, page_ids_str = pair.split(':', 1)
                page_ids = [pid.strip() for pid in page_ids_str.split(';')]
                NOTION_PAGE_MAP[thread_id.strip()] = page_ids
                print(f"✅ マッピング追加: チャンネルID {thread_id.strip()} -> ページID {page_ids}")
        print(f"✅ NOTION_PAGE_MAP解析完了: {len(NOTION_PAGE_MAP)}個のマッピング")
    except Exception as e:
        print(f"⚠️ NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")
        print(f"🔍 問題のある文字列: {NOTION_PAGE_MAP_STRING}")
else:
    print("⚠️ NOTION_PAGE_MAP_STRINGが設定されていません")

# ▼▼▼ ここからが修正箇所 ▼▼▼

def _sync_find_latest_section_id(page_id: str) -> str:
    """[同期] Notionページの一番下からブロックを遡って最新のセクションIDを探す"""
    try:
        response = notion.blocks.children.list(block_id=page_id, page_size=100)
        all_blocks = response.get("results", [])
        for block in reversed(all_blocks):
            if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                text = block["paragraph"]["rich_text"][0]["plain_text"]
                match = re.match(r'§(\d+)', text)
                if match:
                    last_num = int(match.group(1))
                    new_num = last_num + 1
                    return f"§{new_num:03d}"
        return "§001"
    except Exception as e:
        print(f"🚨 最新セクションIDの検索中に同期エラー: {e}")
        return "§001"

async def find_latest_section_id(page_id: str) -> str:
    """[非同期ラッパー] _sync_find_latest_section_id を呼び出す"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_find_latest_section_id, page_id)

def _sync_append_summary_to_kb(page_id: str, section_id: str, summary: str):
    """[同期] 指定されたNotionページにセクションID付きの要約を追記する"""
    try:
        timestamp = get_jst_timestamp()
        final_text = f"{section_id} {summary.strip()} ({timestamp})"
        
        notion.blocks.children.append(
            block_id=page_id,
            children=[
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": final_text}}]}}
            ]
        )
        print(f"✅ ナレッジベースに {section_id} を追記しました。")
    except Exception as e:
        print(f"🚨 ナレッジベースへの追記中に同期エラー: {e}")

async def append_summary_to_kb(page_id: str, section_id: str, summary: str):
    """[非同期ラッパー] _sync_append_summary_to_kb を呼び出す"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_append_summary_to_kb, page_id, section_id, summary)

# ▲▲▲ ここまでが修正箇所 ▲▲▲


def _sync_get_notion_page_text(page_id):
    all_text_blocks = []
    next_cursor = None
    print(f" Notionページ(ID: {page_id})の読み込みを開始します...")
    while True:
        try:
            response = notion.blocks.children.list(
                block_id=page_id,
                start_cursor=next_cursor,
                page_size=100
            )
            results = response.get("results", [])
            if not results and not all_text_blocks:
                print(f"⚠️ ページ(ID: {page_id})からブロックが1件も返されませんでした。")
            for block in results:
                block_type = block.get("type")
                text_content = ""
                if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "quote", "callout"]:
                    rich_text_list = block.get(block_type, {}).get("rich_text", [])
                    if rich_text_list:
                        text_content = "".join([rich_text.get("plain_text", "") for rich_text in rich_text_list])
                if text_content:
                    all_text_blocks.append(text_content)
            if response.get("has_more"):
                next_cursor = response.get("next_cursor")
            else:
                break
        except Exception as e:
            print(f"❌ Notion APIからの読み込み中にエラー(ID: {page_id}): {e}")
            return f"ERROR: Notion API Error - {e}"
    return "\n".join(all_text_blocks)

async def get_notion_page_text_original(page_ids: list):
    """キャッシュなしの元の実装（内部使用）"""
    if not isinstance(page_ids, list):
        page_ids = [page_ids]
    tasks = [asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, pid) for pid in page_ids]
    results = await asyncio.gather(*tasks)
    separator = "\n\n--- (次のページ) ---\n\n"
    return separator.join(results)

async def get_notion_page_text(page_ids: list):
    """キャッシュ付きNotionページテキスト取得（公開API）"""
    if not isinstance(page_ids, list):
        page_ids = [page_ids]

    # キャッシュを使用
    return await notion_cache.get_cached_page_text(page_ids)

async def log_to_notion(page_id, blocks):
    if not page_id: 
        print("⚠️ Notion書き込みスキップ: page_idが空です")
        return
    try:
        print(f"🔍 Notion書き込み試行: ページID {page_id}")
        await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.append(block_id=page_id, children=blocks))
        print(f"✅ Notion書き込み成功: ページID {page_id}")
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")
        print(f"🔍 問題のページID: {page_id}")
        print(f"🔍 書き込み予定ブロック数: {len(blocks) if blocks else 0}")
        # ページIDの形式チェック
        if not page_id or len(page_id) != 36 or page_id.count('-') != 4:
            print(f"⚠️ 無効なページID形式: {page_id} (正しい形式: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")

async def log_user_message(page_id, user_display_name, message_content):
    """ユーザーメッセージを日時付きでNotionにログ記録"""
    if not page_id: return
    timestamp = get_jst_timestamp()
    content = f"👤 {user_display_name} ({timestamp}):\n{message_content}"
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]}}]
    await log_to_notion(page_id, blocks)

async def log_response(page_id, answer, bot_name):
    if not page_id or not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    
    # 最初のチャンクに日時付きのbot名を追加
    timestamp = get_jst_timestamp()
    first_content = f"🤖 {bot_name} ({timestamp}):\n{chunks[0]}"
    
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": first_content}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

async def get_memory_flag_from_notion(thread_id: str) -> bool:
    page_ids = NOTION_PAGE_MAP.get(thread_id)
    if not page_ids: return False
    first_page_id = page_ids[0]
    try:
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.list(block_id=first_page_id, page_size=1))
        results = response.get("results", [])
        if not results: return False
        first_block = results[0]
        if first_block.get("type") == "paragraph":
            rich_text_list = first_block.get("paragraph", {}).get("rich_text", [])
            if rich_text_list:
                content = rich_text_list[0].get("text", {}).get("content", "")
                if "[記憶] ON" in content: return True
    except Exception as e:
        print(f"❌ Notionから記憶フラグの読み取り中にエラー: {e}")

    return False

