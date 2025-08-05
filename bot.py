import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests # Rekus用
import io
from PIL import Image
import base64

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") 

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
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

# --- メモリ管理 ---
# このバージョンでは会話履歴メモリは使用しません
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
    """Notionページの全テキストを取得する（同期処理）"""
    all_text = ""
    try:
        response = notion.blocks.children.list(block_id=page_id)
        for block in response.get("results", []):
            if "type" in block and block["type"] == "paragraph":
                for rich_text in block.get("paragraph", {}).get("rich_text", []):
                    all_text += rich_text.get("text", {}).get("content", "") + "\n"
        return all_text
    except Exception as e:
        print(f"❌ Notion読み込みエラー: {e}")
        return f"Notionページの読み込み中にエラーが発生しました: {e}"

async def get_notion_page_text(page_id):
    """Notionページの全テキストを取得する（非同期ラッパー）"""
    return await asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, page_id)

def _sync_post_to_notion(page_id, blocks):
    if not page_id: return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")

async def log_to_notion(page_id, blocks):
    await asyncio.get_event_loop().run_in_executor(None, _sync_post_to_notion, page_id, blocks)

async def log_trigger(user_name, query, command_name):
    if user_name is None or query is None or command_name is None: return
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
    await log_to_notion(NOTION_MAIN_PAGE_ID, blocks)

async def log_response(answer, bot_name):
    if not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(NOTION_MAIN_PAGE_ID, blocks)

# --- 各AIモデル呼び出し関数 ---
# このバージョンでは、各AIはペルソナを持つものの、短期記憶は持たない

async def ask_gpt_base(prompt):
    system_prompt = "あなたは論理と秩序を司る神官「GPT」です。与えられた情報を元に、質問に対して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        return response.choices[0].message.content
    except Exception as e: return f"GPTの呼び出し中にエラー: {e}"

async def ask_gemini_base(prompt, attachment_parts=[]):
    system_prompt = "あなたは「レイチェル・ゼイン（SUITS）」です。与えられた情報を元に、質問に対して150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"ジェミニの呼び出し中にエラー: {e}"

async def ask_mistral_base(prompt):
    system_prompt = "あなたは思考戦車タチコマです。与えられた情報を元に、質問に対して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"ミストラルの呼び出し中にエラー: {e}"

async def ask_kreios(prompt):
    system_prompt = "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4-turbo", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"クレイオスの呼び出し中にエラー: {e}"

async def ask_minerva(prompt, attachment_parts=[]):
    system_prompt = "あなたはシビュラシステムです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"ミネルバの呼び出し中にエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはララァ・スンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"ララァの呼び出し中にエラー: {e}"

async def ask_rekus(prompt):
    system_prompt = "あなたは探索王レキュスです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 400}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: return f"探索王（レキュス）の呼び出し中にエラー: {e}"

async def ask_pod042(prompt):
    system_prompt = "あなたはポッド042です。与えられた情報を元に、質問に対して「報告：」または「提案：」から始めて200文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"ポッド042の呼び出し中にエラー: {e}"

async def ask_pod153(prompt):
    system_prompt = "あなたはポッド153です。与えられた情報を元に、質問に対して「分析結果：」または「補足：」から始めて200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド153の呼び出し中にエラー: {e}"


# --- Discordイベントハンドラ ---
@client.event
async def on_ready(): print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users: return
    processing_users.add(message.author.id)
    try:
        content, user_id, user_name = message.content, str(message.author.id), message.author.display_name
        attachment_data, attachment_mime_type = None, None
        if message.attachments:
            attachment = message.attachments[0]
            attachment_data = await attachment.read()
            attachment_mime_type = attachment.content_type
        command_name = content.split(' ')[0]
        query = content[len(command_name):].strip()

        is_admin = user_id == ADMIN_USER_ID

        # ▼▼▼ 新設：Notionナレッジベースコマンド ▼▼▼
        if command_name == "!ask":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send(f"🧠 Notionページ({NOTION_MAIN_PAGE_ID})を読み込んでいます…")
            
            # 1. Notionから全文取得
            notion_text = await get_notion_page_text(NOTION_MAIN_PAGE_ID)
            if "エラーが発生しました" in notion_text or not notion_text.strip():
                await message.channel.send(notion_text or "❌ Notionページからテキストを取得できませんでした。")
                return

            await message.channel.send(f"📄 全文読み込み完了。GPT-4oが内容を分割して要約します…")

            # 2. テキストをチャンクに分割
            chunk_size = 8000  # 8000文字ごとに分割
            text_chunks = [notion_text[i:i + chunk_size] for i in range(0, len(notion_text), chunk_size)]
            
            summaries = []
            # 3. 各チャンクを要約
            for i, chunk in enumerate(text_chunks):
                await message.channel.send(f"🔄 チャンク {i+1}/{len(text_chunks)} を要約中…")
                chunk_summary_prompt = f"""
以下の文章は、あるNotionページのログの一部です。
最終的にユーザーの質問「{query}」に答えるため、この部分から関連性の高い情報を抽出・要約してください。

【ログの一部】
{chunk}
"""
                # クレイオス(GPT-4 Turbo)をチャンク要約役として使用
                chunk_summary = await ask_kreios(chunk_summary_prompt) 
                summaries.append(chunk_summary)

            # 4. 要約を結合して最終的なコンテキストを作成
            await message.channel.send("✅ 全チャンクの要約完了。最終的なコンテキストを生成します…")
            combined_summary = "\n\n---\n\n".join(summaries)
            
            final_integration_prompt = f"""
以下の複数の要約は、一つのNotionページを分割して要約したものです。
これらの要約全体を元に、ユーザーの質問に答えるための最終的な参考情報を2000文字以内で作成してください。

【ユーザーの質問】
{query}

【各部分の要約】
{combined_summary}
"""
            context_summary = await ask_kreios(final_integration_prompt)

            # 5. 最終的なコンテキストを元に回答を生成
            await message.channel.send("✅ コンテキスト生成完了。この情報を元に、最終的な回答を生成します…")
            final_prompt = f"""
以下の【参考情報】を元に、【ユーザーの質問】に回答してください。

【ユーザーの質問】
{query}

【参考情報】
{context_summary}
"""
            final_reply = await ask_minerva(final_prompt) # ミネルバを最終回答役とする
            await send_long_message(message.channel, f"**🤖 最終回答:**\n{final_reply}")
            
            if is_admin: 
                await log_response(context_summary, "GPT-4o (要約)")
                await log_response(final_reply, "ミネルバ (最終回答)")

        # --- (既存の単独・連携コマンドは省略) ---
        # ... ここに以前の!gpt, !all, !クリティカルなどのコマンドが入る ...


    except Exception as e:
        print(f"An error occurred in on_message: {e}")
        await message.channel.send(f"予期せぬエラーが発生しました: {e}")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
