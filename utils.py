# notion_utils.py

import os
import sys
import asyncio
from typing import List, Dict, Any, Optional
from notion_client import Client
import json

# --- グローバル変数と初期化 ---
notion: Client = None

# --- ヘルパー関数 ---
def safe_log(prefix: str, obj):
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list, tuple)) else str(obj)
        print(f"{prefix}{s[:2000]}")
    except Exception as e:
        print(f"{prefix}(log skipped: {e})")

# --- Notion関数 ---
async def get_notion_page_text(page_ids: List[str]) -> str:
    """Notionのページからテキストコンテンツを非同期で取得する"""
    if notion is None:
        return "ERROR: Notionクライアントが初期化されていません。"
    
    full_text = ""
    for page_id in page_ids:
        try:
            # ページからブロックを取得（子ブロックの取得）
            print(f"📖 Notion: ページID {page_id} のブロックを取得中...")
            response = await asyncio.to_thread(notion.blocks.children.list, block_id=page_id, page_size=100)
            blocks = response.get("results", [])
            print(f"✅ Notion: ページID {page_id} から {len(blocks)} 個のブロックを取得しました。")

            text_content_list = []
            for block in blocks:
                block_type = block.get("type")
                try:
                    if block_type == "paragraph":
                        text_parts = block["paragraph"]["rich_text"]
                        text = "".join([part["plain_text"] for part in text_parts])
                        text_content_list.append(text)
                    elif block_type == "heading_1":
                        text = "".join([part["plain_text"] for part in block["heading_1"]["rich_text"]])
                        text_content_list.append(f"# {text}")
                    elif block_type == "heading_2":
                        text = "".join([part["plain_text"] for part in block["heading_2"]["rich_text"]])
                        text_content_list.append(f"## {text}")
                    elif block_type == "heading_3":
                        text = "".join([part["plain_text"] for part in block["heading_3"]["rich_text"]])
                        text_content_list.append(f"### {text}")
                    elif block_type == "bulleted_list_item":
                        text = "".join([part["plain_text"] for part in block["bulleted_list_item"]["rich_text"]])
                        text_content_list.append(f"- {text}")
                    elif block_type == "numbered_list_item":
                        text = "".join([part["plain_text"] for part in block["numbered_list_item"]["rich_text"]])
                        text_content_list.append(f"1. {text}")
                    elif block_type == "to_do":
                        text = "".join([part["plain_text"] for part in block["to_do"]["rich_text"]])
                        checked = block["to_do"]["checked"]
                        text_content_list.append(f"- [{'x' if checked else ' '}] {text}")
                    elif block_type == "code":
                        text = block["code"]["rich_text"][0]["plain_text"] if block["code"]["rich_text"] else ""
                        text_content_list.append(f"```{block['code'].get('language', '')}\n{text}\n```")
                    elif block_type == "quote":
                        text = "".join([part["plain_text"] for part in block["quote"]["rich_text"]])
                        text_content_list.append(f"> {text}")
                    elif block_type == "callout":
                        text = "".join([part["plain_text"] for part in block["callout"]["rich_text"]])
                        text_content_list.append(f"> {text}")
                    elif block_type == "divider":
                        text_content_list.append("---")
                    elif block_type == "child_page":
                        text = block["child_page"]["title"]
                        text_content_list.append(f"[子ページ: {text}]")
                    # その他のブロックタイプは無視
                except KeyError as ke:
                    print(f"⚠️ Notion: ブロックタイプ '{block_type}' の解析中にキーエラーが発生: {ke}")
                except Exception as e:
                    print(f"🚨 Notion: ブロックタイプ '{block_type}' の解析中に予期せぬエラー: {e}")
            
            full_text += "\n".join(text_content_list) + "\n\n"

        except Exception as e:
            error_message = f"🚨 Notion APIの呼び出し中に致命的なエラーが発生: {e}"
            print(error_message)
            return "ERROR: " + error_message
    
    return full_text.strip()
    
# --- ログ・メッセージ送信 ---
async def log_to_notion(page_id: str, blocks: List[Dict[str, Any]]):
    if notion is None: return safe_log("⚠️ Notionクライアントが未初期化のためログをスキップしました。", None)
    try:
        await asyncio.to_thread(notion.blocks.children.append, block_id=page_id, children=blocks)
    except Exception as e:
        safe_log("🚨 Notionへのログ書き込みに失敗しました:", e)

async def log_response(page_id: str, text: str, source: str):
    if notion is None: return
    blocks_to_add = [
        {"object": "block", "type": "divider", "divider": {}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {source}:\n{text}"}}]}}
    ]
    try:
        await asyncio.to_thread(notion.blocks.children.append, block_id=page_id, children=blocks_to_add)
    except Exception as e:
        safe_log(f"🚨 Notionへの応答ログ書き込みに失敗しました ({source}):", e)

# ... (他のNotion関数は省略)
