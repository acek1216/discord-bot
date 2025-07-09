import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests
import io
from PIL import Image
import base64

# --- 環境変数読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
NOTION_PAGE_ID = os.getenv("NOTION_PAGE_ID")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")  # 文字列として保持

# --- API初期化 ---
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

# --- Discord設定 ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- 状態管理 ---
philipo_memory = {}
processing_users = set()

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks):
    try:
        if not page_id:
            print("❌ [Notion] ページIDが未設定です。")
            return
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notionに書き込み成功: {page_id}")
    except Exception as e:
        print(f"❌ Notionエラー: {e}")

async def log_to_notion(page_id, blocks):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

# --- AI応答関数 ---
async def ask_philipo(user_id, prompt, attachment_data=None, attachment_mime_type=None):
    history = philipo_memory.get(user_id, [])
    system_message = {"role": "system", "content": "あなたは執事フィリポです。礼儀正しく対応してください。"}
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        image_url_content = f"data:{attachment_mime_type};base64,{base64_image}"
        user_content.append({"type": "image_url", "image_url": {"url": image_url_content}})
    user_message = {"role": "user", "content": user_content}
    messages = [system_message] + history + [user_message]
    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=2000
    )
    reply = response.choices[0].message.content
    philipo_memory[user_id] = history + [user_message, {"role": "assistant", "content": reply}]
    return reply

async def ask_gemini_for_summary(user_id, prompt, attachment_data=None, attachment_mime_type=None):
    contents = [prompt]
    if attachment_data and attachment_mime_type:
        contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    response = await gemini_model.generate_content_async(contents)
    return response.text

# --- Discordイベント ---
@client.event
async def on_ready():
    print("✅ ログイン成功")
    print(f"✅ NotionページID: {NOTION_PAGE_ID}")
    print(f"✅ 管理者ID: {ADMIN_USER_ID}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = str(message.author.id)
    if user_id in processing_users:
        return
    processing_users.add(user_id)

    try:
        if message.content.startswith("!フィリポ"):
            user_name = message.author.display_name
            command_name = "!フィリポ"
            query = message.content[len(command_name):].strip()

            attachment_data = None
            attachment_mime_type = None
            if message.attachments:
                attachment = message.attachments[0]
                attachment_data = await attachment.read()
                attachment_mime_type = attachment.content_type

            if attachment_data and "image" not in attachment_mime_type:
                await message.channel.send("🎩 資料要約中です…")
                summary = await ask_gemini_for_summary(user_id, "この資料を要約して", attachment_data, attachment_mime_type)
                query += f"\n\n[要約]: {summary}"
                await message.channel.send("🎩 要約を元に応答します。")

            else:
                await message.channel.send("🎩 考察中です…")

            reply = await ask_philipo(user_id, query, attachment_data, attachment_mime_type)
            await message.channel.send(reply)

            if user_id == ADMIN_USER_ID:
                blocks = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: {command_name} {query}"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ: {reply}"}}]}}
                ]
                await log_to_notion(NOTION_PAGE_ID, blocks)

    finally:
        if user_id in processing_users:
            processing_users.remove(user_id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
