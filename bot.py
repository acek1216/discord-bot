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
OPENAI_GPT4_TURBO_API_KEY = os.getenv("OPENAI_GPT4_TURBO_API_KEY", openai_api_key)

# ▼▼▼ 記録先のページIDを全て読み込みます ▼▼▼
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") 
NOTION_KREIOS_PAGE_ID = os.getenv("NOTION_KREIOS_PAGE_ID")
NOTION_NOUSOS_PAGE_ID = os.getenv("NOTION_NOUSOS_PAGE_ID")
NOTION_REKUS_PAGE_ID = os.getenv("NOTION_REKUS_PAGE_ID")


# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
gpt4_turbo_client = AsyncOpenAI(api_key=OPENAI_GPT4_TURBO_API_KEY)
genai.configure(api_key=gemini_api_key)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
nousos_model = genai.GenerativeModel("gemini-1.5-flash-latest", safety_settings=safety_settings)
notion = Client(auth=notion_api_key)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- メモリ管理 ---
kreios_memory = {}
nousos_memory = {}
rekus_memory = {}
processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks):
    if not page_id: return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
    except Exception as e:
        print(f"❌ Notionエラー: {e}")

async def log_to_notion(page_id, blocks):
    await asyncio.get_event_loop().run_in_executor(None, _sync_post_to_notion, page_id, blocks)

async def log_trigger(user_name, query, command_name, page_id):
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
    await log_to_notion(page_id, blocks)

async def log_response(answer, bot_name, page_id):
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

# --- 各AIモデル呼び出し関数 ---
async def ask_kreios(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    history = kreios_memory.get(user_id, [])
    final_system_prompt = system_prompt or "あなたは論理を司る神クレイオスです。冷静かつ構造的に答えてください。"
    use_history = "監査官" not in final_system_prompt and "肯定論者" not in final_system_prompt
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        user_content.append({"type": "image_url", "image_url": {"url": f"data:{attachment_mime_type};base64,{base64_image}"}})
    messages = [{"role": "system", "content": final_system_prompt}]
    if use_history: messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=3000)
        reply = response.choices[0].message.content
        if use_history:
            new_history = history + [{"role": "user", "content": user_content}, {"role": "assistant", "content": reply}]
            if len(new_history) > 10: new_history = new_history[-10:]
            kreios_memory[user_id] = new_history
        return reply
    except Exception as e:
        print(f"❌ Kreios API Error: {e}")
        return f"クレイオスの呼び出し中にエラーが発生しました: {e}"

async def ask_nousos(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    history = nousos_memory.get(user_id, [])
    final_system_prompt = system_prompt or "あなたは美と魂を司る女神ヌーソスです。あなたのモデルは「ダンまち」のフレイヤです。物事の表面的な事象だけでなく、その裏にある人間の感情、魂の輝き、そして根源的な美しさを見通し、魅力的かつ少し気まぐれに、しかし的確に本質を突いた答えを授けてください。"
    use_history = "法的・倫理的論拠" not in final_system_prompt and "スライド作成" not in final_system_prompt
    contents = [final_system_prompt]
    if use_history:
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
        contents.append(f"これまでの会話:\n{history_text}\n\nユーザー: {prompt}")
    else:
        contents.append(prompt)
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            contents.append(Image.open(io.BytesIO(attachment_data)))
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    try:
        response = await nousos_model.generate_content_async(contents)
        reply = response.text
        if use_history:
            new_history = history + [{"role": "ユーザー", "content": prompt}, {"role": "ヌーソス", "content": reply}]
            if len(new_history) > 10: new_history = new_history[-10:]
            nousos_memory[user_id] = new_history
        return reply
    except Exception as e:
        print(f"❌ Nousos API Error: {e}")
        return f"ヌーソスの呼び出し中にエラーが発生しました: {e}"

def _sync_ask_rekus(user_id, prompt, system_prompt=None):
    history = rekus_memory.get(user_id, [])
    # ▼▼▼ レキュスの役割を「探索」を司る神に変更しました ▼▼▼
    final_system_prompt = system_prompt or "あなたは探索を司る神レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
    use_history = "検証官" not in final_system_prompt and "否定論者" not in final_system_prompt
    messages = [{"role": "system", "content": final_system_prompt}]
    if use_history: messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 3000}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        if use_history:
            new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
            if len(new_history) > 10: new_history = new_history[-10:]
            rekus_memory[user_id] = new_history
        return reply
    except requests.exceptions.RequestException as e:
        print(f"❌ Rekus API Error: {e}")
        return f"レキュスの呼び出し中にエラーが発生しました: {e}"

async def ask_rekus(user_id, prompt, system_prompt=None):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_ask_rekus, user_id, prompt, system_prompt)

async def ask_gpt(user_id, prompt):
    gpt_prompt = """
あなたは冷静かつ的確な判断力を持つ女性のAIです。ハマーン・カーンのように、時には厳しくも、常に鋭い洞察力で全体を把握し、的確な指示を与えます。
与えられた複数の意見の矛盾点を整理しながら、感情に流されず、論理的に判断し、鋭さと簡潔さを持って最適な結論を導き出してください。
"""
    messages = [
        {"role": "system", "content": gpt_prompt},
        {"role": "user", "content": prompt}
    ]
    try:
        response = await gpt4_turbo_client.chat.completions.create(
            model="gpt-4-turbo",
            messages=messages,
            max_tokens=3000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ GPT-4 Turbo API Error: {e}")
        return f"GPT(統合)の呼び出し中にエラーが発生しました: {e}"

async def ask_sibylla(user_id, prompt, system_prompt=None):
    final_prompt = prompt if not system_prompt else f"{system_prompt}\n\n{prompt}"
    try:
        sibylla_model = genai.GenerativeModel("gemini-1.5-pro-latest", safety_settings=safety_settings)
        response = await sibylla_model.generate_content_async([final_prompt])
        return response.text
    except Exception as e:
        print(f"❌ Sibylla API Error: {e}")
        return f"シヴィラの呼び出し中にエラーが発生しました: {e}"

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

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

        if content.startswith("!みんなで"):
            query = content.replace("!みんなで", "").strip()
            await message.channel.send("🌀 クレイオス、ヌーソス、レキュスが応答中…")
            kreios_task = ask_kreios(user_id, query)
            nousos_task = ask_nousos(user_id, query)
            rekus_task = ask_rekus(user_id, query)
            results = await asyncio.gather(kreios_task, nousos_task, rekus_task, return_exceptions=True)
            kreios, nousos, rekus = results
            if not isinstance(kreios, Exception): await send_long_message(message.channel, f"🔵 クレイオス: {kreios}")
            if not isinstance(nousos, Exception): await send_long_message(message.channel, f"🟣 ヌーソス: {nousos}")
            if not isinstance(rekus, Exception): await send_long_message(message.channel, f"🟢 レキュス: {rekus}")

        elif content.startswith("!三連"):
            query = content.replace("!三連", "").strip()
