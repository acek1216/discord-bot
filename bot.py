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
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID")
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

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks, bot_name):
    if not page_id:
        print(f"❌ Notion Log Error for {bot_name}: Target Page ID is not set in environment variables.")
        return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notion Log Success for {bot_name} to Page ID: {page_id}")
    except Exception as e:
        print(f"❌ Notion API Error for {bot_name}: {e}")

async def log_to_notion(page_id, blocks, bot_name):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks, bot_name)

async def log_trigger_and_response(user_id, user_name, query, command_name, reply, bot_name):
    # ▼▼▼【デバッグ用】IDチェックのログを出力 ▼▼▼
    print("\n--- Notion Logging Check ---")
    print(f"Command: {command_name}, Bot: {bot_name}")
    print(f"Message Author ID: {user_id}")
    print(f"Admin ID from Env: {ADMIN_USER_ID}")

    if user_id != ADMIN_USER_ID:
        print("ID Mismatch. Skipping Notion log.")
        print("--------------------------\n")
        return

    print("✅ Admin ID MATCH. Proceeding to log.")

    # 応答を記録するページのIDを決定
    response_page_id = NOTION_MAIN_PAGE_ID # デフォルト
    if "フィリポ" in bot_name and NOTION_PHILIPO_PAGE_ID: response_page_id = NOTION_PHILIPO_PAGE_ID
    elif ("ジェミニ" in bot_name or "先生" in bot_name) and NOTION_GEMINI_PAGE_ID: response_page_id = NOTION_GEMINI_PAGE_ID
    elif "パープレ" in bot_name and NOTION_PERPLEXITY_PAGE_ID: response_page_id = NOTION_PERPLEXITY_PAGE_ID
    
    print(f"Target Response Page ID: {response_page_id}")

    # 応答ブロックを作成
    if len(reply) > 1900: reply = reply[:1900] + "... (truncated)"
    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": f"🤖 {bot_name}: {reply}"}]}}]
    
    # 応答を記録
    await log_to_notion(response_page_id, response_blocks, bot_name)

    # 実行ログを記録するページのIDを決定
    trigger_page_id = response_page_id # デフォルトは応答と同じページ
    if command_name in ["!みんなで", "!三連", "!逆三連"]:
        trigger_page_id = NOTION_MAIN_PAGE_ID # 複合コマンドはメインページに記録
    
    print(f"Target Trigger Log Page ID: {trigger_page_id}")

    # 実行ログブロックを作成
    trigger_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": f"👤 {user_name}: {command_name} {query}"}]}}]
    
    # 実行ログを記録
    if trigger_page_id != response_page_id:
        await log_to_notion(trigger_page_id, trigger_blocks, f"{command_name} Trigger")
    else:
        # 応答とトリガーが同じページの場合、まとめて書き込む
        all_blocks = trigger_blocks + response_blocks
        await log_to_notion(response_page_id, all_blocks, bot_name)

    print("--------------------------\n")


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

        command_name = content.split(' ')[0]
        query = content[len(command_name):].strip()

        # --- 単独コマンド ---
        if command_name == "!フィリポ":
            query_for_philipo = query
            attachment_for_philipo = attachment_data
            if attachment_data and "image" not in attachment_mime_type:
                await message.channel.send("🎩 執事がジェミニ先生に資料の要約を依頼しております…")
                summary = await ask_gemini(user_id, "この添付資料の内容を詳細に要約してください。", attachment_data, attachment_mime_type)
                query_for_philipo = f"{query}\n\n[添付資料の要約:\n{summary}\n]"
                attachment_for_philipo = None
                await message.channel.send("🎩 要約を元に、考察いたします。")
            else:
                if attachment_data: await message.channel.send("🎩 執事が画像を拝見し、伺います。しばしお待ちくださいませ。")
                else: await message.channel.send("🎩 執事に伺わせますので、しばしお待ちくださいませ。")
            
            reply = await ask_philipo(user_id, query_for_philipo, attachment_data=attachment_for_philipo, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)
            await log_trigger_and_response(user_id, user_name, query, command_name, reply, "フィリポ")
        
        # (他のコマンドは後で対応)

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
