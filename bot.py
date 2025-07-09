import discord
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
from openai import AsyncOpenAI

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- 各種クライアントの初期化 ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
notion = Client(auth=NOTION_API_KEY)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# --- このボットが処理中かどうかを管理するセット ---
processing_lock = set()

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks):
    """Notionにブロックを書き込む同期的なコア処理"""
    # 書き込み先のページIDがあるか、徹底的にチェック
    if not page_id:
        print("❌ [FATAL] Notion書き込み失敗: NOTION_PAGE_IDが環境変数に設定されていません。")
        return
    
    print(f"✅ [DEBUG] Notion書き込み準備完了。宛先ページID: {page_id}")
    
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ [SUCCESS] Notionへの書き込みに成功しました。")
    except Exception as e:
        print(f"❌ [FATAL] Notion APIへのリクエストでエラーが発生しました: {e}")

async def log_to_notion(page_id, blocks):
    """Notionへの書き込みを非同期で安全に呼び出す"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print("--- ボット起動 ---")
    print(f"✅ ログイン成功: {client.user}")
    print(f"✅ Notion記録先ページID: {NOTION_PAGE_ID}")
    print("--------------------")

@client.event
async def on_message(message):
    # ボット自身のメッセージは無視
    if message.author.bot:
        return

    # 多重応答を防止するロック
    if message.id in processing_lock:
        return
    processing_lock.add(message.id)

    try:
        # !フィリポ コマンドにのみ反応
        if message.content.startswith("!フィリポ"):
            print("\n--- !フィリポ コマンド受信 ---")
            
            # ユーザー情報を取得
            user_name = message.author.display_name
            query = message.content[len("!フィリポ "):].strip()
            
            # 応答メッセージを送信
            await message.channel.send("🎩 執事に伺わせますので、しばしお待ちくださいませ。")
            
            # OpenAIに質問を投げる
            print("[DEBUG] OpenAIにリクエストを送信します...")
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "あなたは執事フィリポです。礼儀正しく対応してください。"},
                    {"role": "user", "content": query}
                ]
            )
            reply = response.choices[0].message.content
            print("[DEBUG] OpenAIから応答を受信しました。")
            
            # Discordに応答を返す
            await message.channel.send(reply)
            
            # Notionに記録するためのブロックを作成
            print("[DEBUG] Notionに記録するためのブロックを作成します...")
            blocks_to_write = [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: !フィリポ {query}"}}]}},
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ: {reply}"}}]}}
            ]
            
            # Notionに書き込む
            await log_to_notion(NOTION_PAGE_ID, blocks_to_write)
            
            print("--- 処理完了 ---\n")

    finally:
        # ロックを解除
        processing_lock.remove(message.id)

# --- 起動 ---
print("🚀 ボットを起動します...")
client.run(DISCORD_TOKEN)
