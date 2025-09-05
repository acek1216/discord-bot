# notion_utils.py

import asyncio
import os
import re
from notion_client import Client

# グローバル変数 (Notionクライアント)
notion: Client = None

# NOTION_PAGE_MAPの読み込み
NOTION_PAGE_MAP_STRING = os.getenv("NOTION_PAGE_MAP_STRING", "")
NOTION_PAGE_MAP = {}
if NOTION_PAGE_MAP_STRING:
    try:
        pairs = NOTION_PAGE_MAP_STRING.split(',')
        for pair in pairs:
            if ':' in pair:
                thread_id, page_ids_str = pair.split(':', 1)
                page_ids = [pid.strip() for pid in page_ids_str.split(';')]
                NOTION_PAGE_MAP[thread_id.strip()] = page_ids
    except Exception as e:
        print(f"⚠️ NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")

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
        summary_lines = summary.strip().split('\n')
        title = summary_lines[0]
        body = "\n".join(summary_lines[1:]).strip()
        final_text = f"{section_id}: {title}"
        if body:
            final_text += f"\n\n{body}"
        
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

async def get_notion_page_text(page_ids: list):
    if not isinstance(page_ids, list):
        page_ids = [page_ids]
    tasks = [asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, pid) for pid in page_ids]
    results = await asyncio.gather(*tasks)
    separator = "\n\n--- (次のページ) ---\n\n"
    return separator.join(results)

async def log_to_notion(page_id, blocks):
    if not page_id: return
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.append(block_id=page_id, children=blocks))
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")

async def log_response(page_id, answer, bot_name):
    if not page_id or not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
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

