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
def _sync_post_to_notion(page_id, blocks):
    if not page_id:
        print("❌ Notion Log Error: Target Page ID is not provided or not set in environment variables.")
        return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notion Log Success to Page ID: {page_id}")
    except Exception as e:
        print(f"❌ Notion API Error: {e}")

async def log_to_notion(page_id, blocks):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

# --- 各AIモデル呼び出し関数 ---
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

        is_admin = (user_id == ADMIN_USER_ID)

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
            
            if is_admin:
                blocks = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: {command_name} {query}"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ: {reply}"}}]}}
                ]
                await log_to_notion(NOTION_PHILIPO_PAGE_ID, blocks)
        
        elif command_name == "!ジェミニ":
            if attachment_data: await message.channel.send("🧑‍🏫 先生が資料を拝見し、考察中です。少々お待ちください。")
            else: await message.channel.send("🧑‍🏫 先生が考察中です。少々お待ちください。")
            reply = await ask_gemini(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)
            if is_admin:
                blocks = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: {command_name} {query}"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 ジェミニ先生: {reply}"}}]}}
                ]
                await log_to_notion(NOTION_GEMINI_PAGE_ID, blocks)

        elif command_name == "!パープレ":
            if attachment_data: await message.channel.send("🔎 パープレさんは画像を直接見ることができません。テキストのみで回答します。")
            else: await message.channel.send("🔎 パープレさんが検索中です…")
            reply = await ask_perplexity(user_id, query)
            await message.channel.send(reply)
            if is_admin:
                blocks = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name}: {command_name} {query}"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 パープレさん: {reply}"}}]}}
                ]
                await log_to_notion(NOTION_PERPLEXITY_PAGE_ID, blocks)

        # --- 複合コマンド ---
        elif command_name in ["!みんなで", "!三連", "!逆三連"]:
            if is_admin:
                trigger_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
                await log_to_notion(NOTION_MAIN_PAGE_ID, trigger_blocks)

            if command_name == "!みんなで":
                await message.channel.send("🧠 みんなに質問を送ります…")
                query_for_perplexity = query
                query_for_philipo = query
                attachment_for_philipo = attachment_data
                if attachment_data:
                    summary = await ask_gemini(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                    query_for_perplexity = f"{query}\n\n[添付資料の概要: {summary}]"
                    if "image" not in attachment_mime_type:
                        query_for_philipo = query_for_perplexity
                        attachment_for_philipo = None
                
                philipo_task = ask_philipo(user_id, query_for_philipo, attachment_data=attachment_for_philipo, attachment_mime_type=attachment_mime_type)
                gemini_task = ask_gemini(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                perplexity_task = ask_perplexity(user_id, query_for_perplexity)
                results = await asyncio.gather(philipo_task, gemini_task, perplexity_task, return_exceptions=True)
                philipo_reply, gemini_reply, perplexity_reply = results
                
                if not isinstance(philipo_reply, Exception): 
                    await message.channel.send(f"🧤 **フィリポ** より:\n{philipo_reply}")
                    if is_admin:
                        response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ(みんな): {philipo_reply}"}}]}}]
                        await log_to_notion(NOTION_PHILIPO_PAGE_ID, response_blocks)
                
                if not isinstance(gemini_reply, Exception): 
                    await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")
                    if is_admin:
                        response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 ジェミニ先生(みんな): {gemini_reply}"}}]}}]
                        await log_to_notion(NOTION_GEMINI_PAGE_ID, response_blocks)

                if not isinstance(perplexity_reply, Exception): 
                    await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")
                    if is_admin:
                        response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 パープレさん(みんな): {perplexity_reply}"}}]}}]
                        await log_to_notion(NOTION_PERPLEXITY_PAGE_ID, response_blocks)

            elif command_name == "!三連":
                if attachment_data and "image" not in attachment_mime_type:
                    await message.channel.send("🎩 執事がジェミニ先生に資料の要約を依頼しております…")
                    summary = await ask_gemini(user_id, "この添付資料の内容を詳細に要約してください。", attachment_data, attachment_mime_type)
                    query_for_philipo = f"{query}\n\n[添付資料の要約:\n{summary}\n]"
                    attachment_for_philipo = None
                    await message.channel.send("🎩 要約を元に、考察いたします。")
                else:
                    if attachment_data: await message.channel.send("🎩 執事が画像を拝見し、伺います。")
                    else: await message.channel.send("🎩 執事に伺わせますので、しばしお待ちくださいませ。")

                philipo_reply = await ask_philipo(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                await message.channel.send(f"🧤 **フィリポ** より:\n{philipo_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ(三連): {philipo_reply}"}}]}}]
                    await log_to_notion(NOTION_PHILIPO_PAGE_ID, response_blocks)

                await message.channel.send("🎓 ジェミニ先生に引き継ぎます…")
                gemini_reply = await ask_gemini(user_id, philipo_reply)
                await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 ジェミニ先生(三連): {gemini_reply}"}}]}}]
                    await log_to_notion(NOTION_GEMINI_PAGE_ID, response_blocks)

                await message.channel.send("🔎 パープレさんに情報確認を依頼します…")
                perplexity_reply = await ask_perplexity(user_id, gemini_reply)
                await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 パープレさん(三連): {perplexity_reply}"}}]}}]
                    await log_to_notion(NOTION_PERPLEXITY_PAGE_ID, response_blocks)

            elif command_name == "!逆三連":
                query_for_perplexity = query
                if attachment_data:
                    await message.channel.send("🔎 画像を認識して、パープレさんに伝えます…")
                    image_description = await ask_gemini(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                    query_for_perplexity = f"{query}\n\n[添付資料の概要: {image_description}]"
                
                perplexity_reply = await ask_perplexity(user_id, query_for_perplexity)
                await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 パープレさん(逆三連): {perplexity_reply}"}}]}}]
                    await log_to_notion(NOTION_PERPLEXITY_PAGE_ID, response_blocks)

                await message.channel.send("🎓 ジェミニ先生に引き継ぎます…")
                gemini_reply = await ask_gemini(user_id, perplexity_reply)
                await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 ジェミニ先生(逆三連): {gemini_reply}"}}]}}]
                    await log_to_notion(NOTION_GEMINI_PAGE_ID, response_blocks)

                await message.channel.send("🎩 フィリポが最終まとめを行います…")
                philipo_reply = await ask_philipo(user_id, gemini_reply)
                await message.channel.send(f"🎩 **フィリポ** より:\n{philipo_reply}")
                if is_admin:
                    response_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 フィリポ(逆三連): {philipo_reply}"}}]}}]
                    await log_to_notion(NOTION_PHILIPO_PAGE_ID, response_blocks)

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
