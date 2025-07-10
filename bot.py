import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
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
notion_api_key = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

# ▼▼▼ 記録先のページIDを全て読み込みます ▼▼▼
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") # 「三神構造炉」のID
NOTION_KREIOS_PAGE_ID = os.getenv("NOTION_KREIOS_PAGE_ID") # 旧フィリポ
NOTION_NOUSOS_PAGE_ID = os.getenv("NOTION_NOUSOS_PAGE_ID") # 旧ジェミニ
NOTION_REKUS_PAGE_ID = os.getenv("NOTION_REKUS_PAGE_ID") # 旧パープレ


# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
gemini_model = genai.GenerativeModel("gemini-1.5-pro", safety_settings=safety_settings)
notion = Client(auth=notion_api_key)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- メモリ管理 ---
kreios_memory = {}
nousos_memory = {}
rekus_memory = {}
processing_users = set()

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks):
    """Notionにブロックを書き込む同期的なコア処理"""
    if not page_id:
        print("❌ Notionエラー: 書き込み先のページIDが指定されていません。")
        return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notionへの書き込み成功 (ページID: {page_id})")
    except Exception as e:
        print(f"❌ Notionエラー: {e}")

async def log_to_notion(page_id, blocks):
    """Notionへの書き込みを非同期で安全に呼び出す"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

async def log_trigger(user_name, query, command_name, page_id):
    """コマンドの実行ログを記録する"""
    blocks = [{
        "object": "block", "type": "paragraph", "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]
        }
    }]
    await log_to_notion(page_id, blocks)

async def log_response(answer, bot_name, page_id):
    """AIの応答を記録する"""
    if len(answer) > 1900:
        answer = answer[:1900] + "... (文字数制限のため省略)"
    blocks = [{
        "object": "block", "type": "paragraph", "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}: {answer}"}}]
        }
    }]
    await log_to_notion(page_id, blocks)


# --- 各AIモデル呼び出し関数 ---
async def ask_kreios(user_id, prompt, attachment_data=None, attachment_mime_type=None):
    """論理を司る神クレイオス（旧フィリポ）を呼び出す"""
    history = kreios_memory.get(user_id, [])
    system_message = {"role": "system", "content": "あなたは論理を司る神クレイオスです。冷静かつ構造的に答えてください。"}
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        image_url_content = f"data:{attachment_mime_type};base64,{base64_image}"
        user_content.append({"type": "image_url", "image_url": {"url": image_url_content}})
    user_message = {"role": "user", "content": user_content}
    messages = [system_message] + history + [user_message]
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2000)
    reply = response.choices[0].message.content
    kreios_memory[user_id] = history + [user_message, {"role": "assistant", "content": reply}]
    return reply

async def ask_nousos(user_id, prompt, attachment_data=None, attachment_mime_type=None):
    """知性を司る神ヌーソス（旧ジェミニ）を呼び出す"""
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in nousos_memory.get(user_id, [])])
    system_prompt = "あなたは知性を司る神ヌーソスです。万物の根源を見通し、哲学的かつ探求的に答えてください。"
    contents = [system_prompt, f"これまでの会話:\n{history_text}\n\nユーザー: {prompt}"]
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            img = Image.open(io.BytesIO(attachment_data))
            contents.append(img)
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    response = await gemini_model.generate_content_async(contents)
    reply = response.text
    current_history = nousos_memory.get(user_id, [])
    nousos_memory[user_id] = current_history + [{"role": "ユーザー", "content": prompt}, {"role": "ヌーソス", "content": reply}]
    return reply

def _sync_ask_rekus(user_id, prompt):
    """記録を司る神レキュス（旧パープレ）を同期的に呼び出す"""
    history = rekus_memory.get(user_id, [])
    messages = [{"role": "system", "content": "あなたは記録を司る神レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"}] + history + [{"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
    response.raise_for_status()
    reply = response.json()["choices"][0]["message"]["content"]
    rekus_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
    return reply

async def ask_rekus(user_id, prompt):
    """記録を司る神レキュスを非同期で呼び出す"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_ask_rekus, user_id, prompt)

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id in processing_users:
        return
    processing_users.add(message.author.id)

    try:
        content = message.content
        user_id = str(message.author.id)
        user_name = message.author.display_name

        attachment_data = None
        attachment_mime_type = None
        if message.attachments:
            attachment = message.attachments[0]
            attachment_data = await attachment.read()
            attachment_mime_type = attachment.content_type

        # --- コマンド分岐 ---
        command_name = content.split(' ')[0]
        query = content[len(command_name):].strip()

        # --- 単独コマンド ---
        if command_name == "!クレイオス":
            if user_id == ADMIN_USER_ID:
                await log_trigger(user_name, query, command_name, NOTION_KREIOS_PAGE_ID)

            query_for_kreios = query
            attachment_for_kreios = attachment_data
            if attachment_data and "image" not in attachment_mime_type:
                await message.channel.send("🏛️ クレイオスがヌーソスに資料の要約を依頼しています…")
                summary = await ask_nousos(user_id, "この添付資料の内容を詳細に要約してください。", attachment_data, attachment_mime_type)
                query_for_kreios = f"{query}\n\n[添付資料の要約:\n{summary}\n]"
                attachment_for_kreios = None
                await message.channel.send("🏛️ 要約を元に、考察します。")
            else:
                if attachment_data:
                    await message.channel.send("🏛️ クレイオスが画像を拝見し、伺います。")
                else:
                    await message.channel.send("🏛️ クレイオスに伺いますので、しばしお待ちください。")

            reply = await ask_kreios(user_id, query_for_kreios, attachment_data=attachment_for_kreios, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)

            if user_id == ADMIN_USER_ID:
                await log_response(reply, "クレイオス", NOTION_KREIOS_PAGE_ID)
        
        elif command_name == "!ヌーソス":
            if user_id == ADMIN_USER_ID:
                await log_trigger(user_name, query, command_name, NOTION_NOUSOS_PAGE_ID)
            
            await message.channel.send("🎓 ヌーソスに問いかけています…")
            reply = await ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)

            if user_id == ADMIN_USER_ID:
                await log_response(reply, "ヌーソス", NOTION_NOUSOS_PAGE_ID)

        elif command_name == "!レキュス":
            if user_id == ADMIN_USER_ID:
                await log_trigger(user_name, query, command_name, NOTION_REKUS_PAGE_ID)
            
            if attachment_data:
                 await message.channel.send("🔎 レキュスが添付ファイルを元に情報を探索します…")
                 summary = await ask_nousos(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                 query_for_rekus = f"{query}\n\n[添付資料の概要: {summary}]"
                 reply = await ask_rekus(user_id, query_for_rekus)
            else:
                await message.channel.send("🔎 レキュスが情報を探索します…")
                reply = await ask_rekus(user_id, query)

            await message.channel.send(reply)

            if user_id == ADMIN_USER_ID:
                await log_response(reply, "レキュス", NOTION_REKUS_PAGE_ID)

        # --- 複合コマンド ---
        elif command_name in ["!みんなで", "!三連", "!逆三連"]:
            if user_id == ADMIN_USER_ID:
                await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            if command_name == "!みんなで":
                await message.channel.send("🧠 三神に質問を送ります…")
                query_for_rekus = query
                query_for_kreios = query
                attachment_for_kreios = attachment_data

                if attachment_data:
                    summary = await ask_nousos(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                    query_for_rekus = f"{query}\n\n[添付資料の概要: {summary}]"
                    if "image" not in attachment_mime_type:
                        query_for_kreios = query_for_rekus
                        attachment_for_kreios = None

                kreios_task = ask_kreios(user_id, query_for_kreios, attachment_data=attachment_for_kreios, attachment_mime_type=attachment_mime_type)
                nousos_task = ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                rekus_task = ask_rekus(user_id, query_for_rekus)

                results = await asyncio.gather(kreios_task, nousos_task, rekus_task, return_exceptions=True)
                kreios_reply, nousos_reply, rekus_reply = results

                if not isinstance(kreios_reply, Exception):
                    await message.channel.send(f"🏛️ **クレイオス** より:\n{kreios_reply}")
                    if user_id == ADMIN_USER_ID: await log_response(kreios_reply, "クレイオス(みんな)", NOTION_KREIOS_PAGE_ID)
                
                if not isinstance(nousos_reply, Exception):
                    await message.channel.send(f"🎓 **ヌーソス** より:\n{nousos_reply}")
                    if user_id == ADMIN_USER_ID: await log_response(nousos_reply, "ヌーソス(みんな)", NOTION_NOUSOS_PAGE_ID)

                if not isinstance(rekus_reply, Exception):
                    await message.channel.send(f"🔎 **レキュス** より:\n{rekus_reply}")
                    if user_id == ADMIN_USER_ID: await log_response(rekus_reply, "レキュス(みんな)", NOTION_REKUS_PAGE_ID)


            elif command_name == "!三連":
                # (ロジックは省略)
                pass
            elif command_name == "!逆三連":
                # (ロジックは後で対応)
                pass

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
