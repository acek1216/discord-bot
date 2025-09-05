# notion_utils.py

import asyncio
import os
import re # 正規表現ライブラリをインポート
from notion_client import Client

# グローバル変数 (Notionクライアント)
notion: Client = None

# (NOTION_PAGE_MAPの読み込み部分は変更なし)
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

# (log_to_notion, log_response, _sync_get_notion_page_text, get_notion_page_text, get_memory_flag_from_notion は変更なし)

# ▼▼▼ ここから新しい関数を追加 ▼▼▼

async def find_latest_section_id(page_id: str) -> str:
    """
    Notionページの一番下からブロックを遡って最新のセクションIDを探し、次のIDを返す。
    """
    try:
        # Notion APIを使用してページの全ブロックを取得
        response = await notion.blocks.children.list(block_id=page_id, page_size=100)
        all_blocks = response.get("results", [])
        
        # 下のブロックから順にチェックする
        for block in reversed(all_blocks):
            # paragraphブロックで、中にテキストがある場合のみ処理
            if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                # テキストコンテンツを取得
                text = block["paragraph"]["rich_text"][0]["plain_text"]
                
                # 正規表現で「§ + 数字」のパターンにマッチするか確認
                match = re.match(r'§(\d+)', text)
                if match:
                    # マッチした場合、数字部分を取得して+1する
                    last_num = int(match.group(1))
                    new_num = last_num + 1
                    # 3桁のゼロ埋め形式で新しいIDを返す (例: §011)
                    return f"§{new_num:03d}"

        # ループを抜けても見つからなかった場合（ページが空など）は、最初のIDを返す
        return "§001"


async def append_summary_to_kb(page_id: str, section_id: str, summary: str):
    """
    指定されたNotionページに、セクションID付きの要約を追記する。
    find_latest_section_idが読み取れる形式で書き込む。
    """
    try:
        # GPT-4oが生成した要約は「1行目=タイトル、2行目以降=本文」の形式
        summary_lines = summary.strip().split('\n')
        title = summary_lines[0]
        # 本文がない場合も考慮
        body = "\n".join(summary_lines[1:]).strip()

        # 書き込むテキストを「§011: タイトル\n\n本文」の形式に整形
        # このフォーマットは上のfind_latest_section_id関数が認識できるものと一致させる
        final_text = f"{section_id}: {title}"
        if body: # 本文があれば改行を2つ入れて追記
            final_text += f"\n\n{body}"

        # Notion APIで新しいparagraphブロックとして追記
        await notion.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": final_text}}]
                    }
                }
            ]
        )
        print(f" ナレッジベースに {section_id} を追記しました。")

    except Exception as e:
        print(f"🚨 ナレッジベースへの追記中にエラー: {e}")

# ▲▲▲ ここまで新しい関数を追加 ▲▲▲

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
