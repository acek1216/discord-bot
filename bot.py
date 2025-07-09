import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests # Perplexity用
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
NOTION_PHILIPO_PAGE_ID = os.getenv("NOTION_PHILIPO_PAGE_ID")
NOTION_GEMINI_PAGE_ID = os.getenv("NOTION_GEMINI_PAGE_ID")
NOTION_PERPLEXITY_PAGE_ID = os.getenv("NOTION_PERPLEXITY_PAGE_ID")

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
philipo_memory = {}
gemini_memory = {}
perplexity_memory = {}
processing_users = set()

# --- Notion書き込み関数 (★ここを全面的に修正しました) ---
def _sync_post_to_notion(page_id, blocks):
    """Notionにブロックを書き込む同期的なコア処理"""
    if not page_id:
        # 書き込み先IDがない場合は何もしない
        print("❌ Notion Log Error: Target Page ID is not provided or not set in environment variables.")
        return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notion Log Success to Page ID: {page_id}")
    except Exception as e:
        print(f"❌ Notion API Error: {e}")

async def log_to_notion(page_id, blocks):
    """Notionへの書き込みを非同期で安全に呼び出す"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

# --- 各AIモデル呼び出し関数 (変更なし) ---
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
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2000)
    reply = response.choices[0].message.content
    philipo_memory[user_id] = history + [user_message, {"role": "assistant", "content": reply}]
    return reply

async def ask_gemini(user_id, prompt, attachment_data=None, attachment_mime_type=None):
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in gemini_memory.get(user_id, [])])
    system_prompt = "あなたは論理と感情の架け橋となるAI教師です。哲学・構造・言語表現に長けており、質問には冷静かつ丁寧に答えてください。"
    contents = [system_prompt, f"これまでの会話:\n{history_text}\n\nユーザー: {prompt}"]
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            img = Image.open(io.BytesIO(attachment_data))
            contents.append(img)
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    response = await gemini_model.generate_content_async(contents)
    reply = response.text
    current_history = gemini_memory.get(user_id, [])
    gemini_memory[user_id] = current_history + [{"role": "ユーザー", "content": prompt}, {"role": "先生", "content": reply}]
    return reply

def _sync_ask_perplexity(user_id, prompt):
    history = perplexity_memory.get(user_id, [])
    messages = [{"role": "system", "content": "あなたは探索神パープレです。情報収集と構造整理を得意とし、簡潔にお答えします。"}] + history + [{"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
    response.raise_for_status()
    reply = response.json()["choices"][0]["message"]["content"]
    perplexity_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
    return reply

async def ask_perplexity(user_id, prompt):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_ask_perplexity, user_id, prompt)

# --- Discordイベントハンドラ (★ここを全面的に修正しました) ---
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

        command_name = content.split(' ')[0]
        query = content[len(command_name):].strip()

        # --- 単独コマンド ---
        if command_name == "!フィリポ":
            if attachment_data and "image" not in attachment_mime_type:
                # (PDF処理のロジックは変更なし)
                pass
            else:
                # (通常の応答メッセージロジックは変更なし)
                pass
            
            reply = await ask_philipo(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)
            
            if user_id == ADMIN_USER_ID:
                blocks = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: {query}"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ: {reply}"}}]}}
                ]
                await log_to_notion(NOTION_PHILIPO_PAGE_ID, blocks)
        
        # (ジェミニとパープレのコマンドは後で対応)

        # --- 複合コマンド ---
        elif command_name in ["!みんなで", "!三連", "!逆三連"]:
            # 実行ログをメインページに記録
            if user_id == ADMIN_USER_ID:
                trigger_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
                await log_to_notion(NOTION_MAIN_PAGE_ID, trigger_blocks)

            if command_name == "!みんなで":
                # (AI呼び出しロジックは変更なし)
                pass
                
                # 各AIの応答をそれぞれのページに記録
                if user_id == ADMIN_USER_ID:
                    if not isinstance(philipo_reply, Exception): 
                        response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ(みんな): {philipo_reply}"}}]}}]
                        await log_to_notion(NOTION_PHILIPO_PAGE_ID, response_blocks)
                    # (ジェミニとパープレのログも同様に)

            elif command_name == "!三連":
                # (AI呼び出しロジックは変更なし)
                pass
                
                # 各AIの応答をそれぞれのページに記録
                if user_id == ADMIN_USER_ID:
                    # (フィリポ、ジェミニ、パープレのログをそれぞれのページに記録)
                    pass

            elif command_name == "!逆三連":
                # (AI呼び出しロジックは変更なし)
                pass

                # 各AIの応答をそれぞれのページに記録
                if user_id == ADMIN_USER_ID:
                    # (パープレ、ジェミニ、フィリポのログをそれぞれのページに記録)
                    pass

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
