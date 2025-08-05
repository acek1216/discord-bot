import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests # Rekus用

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") 

# ▼▼▼ Renderの環境変数から対応表を読み込み、辞書を作成 ▼▼▼
NOTION_PAGE_MAP_STRING = os.getenv("NOTION_PAGE_MAP_STRING", "")
NOTION_PAGE_MAP = {}
if NOTION_PAGE_MAP_STRING:
    try:
        pairs = NOTION_PAGE_MAP_STRING.split(',')
        for pair in pairs:
            if ':' in pair:
                thread_id, page_id = pair.split(':', 1)
                NOTION_PAGE_MAP[thread_id.strip()] = page_id.strip()
    except Exception as e:
        print(f"⚠️ NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")
        print(f"⚠️ 入力された文字列: {NOTION_PAGE_MAP_STRING}")

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
notion = Client(auth=notion_api_key)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- グローバル変数 ---
processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- Notion連携関数 ---
def _sync_get_notion_page_text(page_id):
    all_text_blocks = []
    next_cursor = None
    while True:
        try:
            response = notion.blocks.children.list(
                block_id=page_id,
                start_cursor=next_cursor,
                page_size=100
            )
            results = response.get("results", [])
            for block in results:
                if block.get("type") == "paragraph":
                    for rich_text in block.get("paragraph", {}).get("rich_text", []):
                        all_text_blocks.append(rich_text.get("text", {}).get("content", ""))
            
            if response.get("has_more"):
                next_cursor = response.get("next_cursor")
            else:
                break
        except Exception as e:
            print(f"❌ Notion読み込みエラー: {e}")
            return f"ERROR: Notion API Error - {e}"
    
    return "\n".join(all_text_blocks)

async def get_notion_page_text(page_id):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, page_id)

async def log_to_notion(page_id, blocks):
    if not page_id: return
    try:
        await asyncio.get_event_loop().run_in_executor(None, 
            lambda: notion.blocks.children.append(block_id=page_id, children=blocks)
        )
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")

async def log_response(page_id, answer, bot_name):
    if not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

# --- !askコマンド専用AIモデル呼び出し関数 ---
async def ask_minerva_chunk_summarizer(prompt):
    system_prompt = "あなたは、与えられた文章の中から、後続の質問に答えるために必要な情報だけを的確に抽出・要約するAIです。ペルソナは不要です。指示された文字数制限に従ってください。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: 
        print(f"❌ ミネルバ(チャンク要約)エラー: {e}")
        return f"エラー：ミネルバの呼び出し中にエラーが発生しました。"

async def ask_gpt4o_final_summarizer(prompt):
    system_prompt = "あなたは、断片的な複数の要約文を受け取り、それらを一つの首尾一貫したコンテキストに統合・分析するAIです。ペルソナは不要です。指示された文字数制限に従ってください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2200)
        return response.choices[0].message.content
    except Exception as e: 
        print(f"❌ gpt-4o(統合要約)エラー: {e}")
        return f"エラー：gpt-4oの呼び出し中にエラーが発生しました。"

async def ask_rekus_final_answerer(prompt):
    system_prompt = "あなたは、与えられた参考情報とユーザーの質問を元に、最終的な回答を生成するAIです。ペルソナは探索王レキュスです。必ず200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 400}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: 
        print(f"❌ レキュス(最終回答)エラー: {e}")
        return f"エラー：レキュスの呼び出し中にエラーが発生しました。"

# --- Discordイベントハンドラ ---
@client.event
async def on_ready(): 
    print(f"✅ ログイン成功: {client.user}")
    print(f"📖 Notion対応表が読み込まれました: {NOTION_PAGE_MAP}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users: return
    
    content = message.content
    command_name = content.split(' ')[0]
    
    if command_name != "!ask": return

    processing_users.add(message.author.id)
    try:
        user_id, user_name = str(message.author.id), message.author.display_name
        query = content[len(command_name):].strip()
        is_admin = user_id == ADMIN_USER_ID
        
        thread_id = str(message.channel.id)
        target_notion_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        if not target_notion_page_id:
            await message.channel.send("❌ このスレッドに対応するNotionページが設定されていません。")
            return

        if is_admin:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
            await log_to_notion(target_notion_page_id, log_blocks)

        await message.channel.send(f"🧠 Notionページを読み込んでいます…")
        
        notion_text = await get_notion_page_text(target_notion_page_id)
        if notion_text.startswith("ERROR:"):
            print(f"Notion Error Details: {notion_text}")
            await message.channel.send("❌ Notionページの読み込み中にエラーが発生しました。詳細はコンソールログを確認してください。")
            return
        if not notion_text.strip():
            await message.channel.send("❌ Notionページからテキストを取得できませんでした。ページが空か、権限がない可能性があります。")
            return

        await message.channel.send(f"📄 ステップ1/3: 全文読み込み完了。ミネルバが内容を分割して要約します…")

        chunk_size = 8000
        text_chunks = [notion_text[i:i + chunk_size] for i in range(0, len(notion_text), chunk_size)]
        
        chunk_summaries = []
        for i, chunk in enumerate(text_chunks):
            await message.channel.send(f"🔄 チャンク {i+1}/{len(text_chunks)} をミネルバが要約中…")
            chunk_summary_prompt = f"以下の文章は、あるNotionページのログの一部です。最終的にユーザーの質問「{query}」に答えるため、この部分から関連性の高い情報を2000文字以内で抽出・要約してください。\n\n【ログの一部】\n{chunk}"
            chunk_summary = await ask_minerva_chunk_summarizer(chunk_summary_prompt)
            if "エラー" in chunk_summary:
                await message.channel.send(f"⚠️ チャンク {i+1} の要約中にエラーが発生しました。スキップします。")
                continue
            chunk_summaries.append(chunk_summary)
            await asyncio.sleep(3)

        if not chunk_summaries:
            await message.channel.send("❌ Notionページの内容を要約できませんでした。")
            return

        await message.channel.send("✅ ステップ2/3: 全チャンクの要約完了。gpt-4oが統合・分析します…")
        
        combined_summaries = "\n\n---\n\n".join(chunk_summaries)
        integration_prompt = f"以下の複数の要約は、一つのNotionページを分割して要約したものです。これらの要約全体を元に、ユーザーの質問に答えるための最終的な参考情報を2000文字以内で統合・分析してください。\n\n【ユーザーの質問】\n{query}\n\n【各部分の要約】\n{combined_summaries}"
        final_context = await ask_gpt4o_final_summarizer(integration_prompt)

        if "エラー" in final_context:
            await message.channel.send(f"⚠️ 統合中にエラーが発生しました。\n{final_context}")
            return

        await message.channel.send("✅ ステップ3/3: コンテキスト生成完了。レキュスが最終回答を生成します…")
        
        final_prompt = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{query}\n\n【参考情報】\n{final_context}"
        final_reply = await ask_rekus_final_answerer(final_prompt)
        
        await send_long_message(message.channel, f"**🤖 最終回答 (by レキュス):**\n{final_reply}")
        
        if is_admin: 
            await log_response(target_notion_page_id, final_context, "gpt-4o (統合コンテキスト)")
            await log_response(target_notion_page_id, final_reply, "レキュス (最終回答)")

    except Exception as e:
        print(f"An error occurred in on_message: {e}")
        error_message = str(e)
        display_error = (error_message[:300] + '...') if len(error_message) > 300 else error_message
        await message.channel.send(f"予期せぬエラーが発生しました: ```{display_error}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)

