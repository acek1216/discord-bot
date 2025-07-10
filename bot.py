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
NOTION_KREIOS_PAGE_ID = os.getenv("NOTION_KREIOS_PAGE_ID")
NOTION_NOUSOS_PAGE_ID = os.getenv("NOTION_NOUSOS_PAGE_ID")
NOTION_REKUS_PAGE_ID = os.getenv("NOTION_REKUS_PAGE_ID")


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
        # Notionのブロック上限は2000文字なので、少し余裕を持たせる
        chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)]
    else:
        chunks = [answer]
    
    blocks = []
    # 初回ブロックにタイトルを付与
    blocks.append({
        "object": "block", "type": "paragraph", "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]
        }
    })
    # 2回目以降のチャンクを追記
    for chunk in chunks[1:]:
        blocks.append({
            "object": "block", "type": "paragraph", "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            }
        })

    await log_to_notion(page_id, blocks)


# --- 各AIモデル呼び出し関数 ---
async def ask_kreios(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    """論理を司る神クレイオスを呼び出す"""
    history = kreios_memory.get(user_id, [])
    if system_prompt is None:
        system_prompt = "あなたは論理を司る神クレイオスです。冷静かつ構造的に答えてください。"
    system_message = {"role": "system", "content": system_prompt}
    
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        image_url_content = f"data:{attachment_mime_type};base64,{base64_image}"
        user_content.append({"type": "image_url", "image_url": {"url": image_url_content}})
    
    user_message = {"role": "user", "content": user_content}
    # クリティカルコマンドでは履歴を使わない
    messages = [system_message, user_message] if "監査官" in system_prompt else [system_message] + history + [user_message]
    
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2000)
    reply = response.choices[0].message.content
    kreios_memory[user_id] = history + [user_message, {"role": "assistant", "content": reply}]
    return reply

async def ask_nousos(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    """知性を司る神ヌーソスを呼び出す"""
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in nousos_memory.get(user_id, [])])
    if system_prompt is None:
        system_prompt = "あなたは知性を司る神ヌーソスです。万物の根源を見通し、哲学的かつ探求的に答えてください。"
    
    # クリティカルコマンドでは履歴を使わない
    if "分析官" in system_prompt:
        contents = [system_prompt, prompt]
    else:
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

def _sync_ask_rekus(user_id, prompt, system_prompt=None):
    """記録を司る神レキュスを同期的に呼び出す"""
    history = rekus_memory.get(user_id, [])
    if system_prompt is None:
        system_prompt = "あなたは記録を司る神レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
    
    # クリティカルコマンドでは履歴を使わない
    if "検証官" in system_prompt:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    else:
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
        
    payload = {"model": "sonar-pro", "messages": messages}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
    response.raise_for_status()
    reply = response.json()["choices"][0]["message"]["content"]
    rekus_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
    return reply

async def ask_rekus(user_id, prompt, system_prompt=None):
    """記録を司る神レキュスを非同期で呼び出す"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_ask_rekus, user_id, prompt, system_prompt)

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
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_KREIOS_PAGE_ID)
            query_for_kreios = query
            attachment_for_kreios = attachment_data
            if attachment_data and "image" not in attachment_mime_type:
                await message.channel.send("🏛️ クレイオスがヌーソスに資料の要約を依頼しています…")
                summary = await ask_nousos(user_id, "この添付資料の内容を詳細に要約してください。", attachment_data, attachment_mime_type)
                query_for_kreios = f"{query}\n\n[添付資料の要約:\n{summary}\n]"
                attachment_for_kreios = None
                await message.channel.send("🏛️ 要約を元に、考察します。")
            else:
                await message.channel.send("🏛️ クレイオスに伺います。")
            reply = await ask_kreios(user_id, query_for_kreios, attachment_data=attachment_for_kreios, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "クレイオス", NOTION_KREIOS_PAGE_ID)
        
        elif command_name == "!ヌーソス":
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_NOUSOS_PAGE_ID)
            await message.channel.send("🎓 ヌーソスに問いかけています…")
            reply = await ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await message.channel.send(reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "ヌーソス", NOTION_NOUSOS_PAGE_ID)

        elif command_name == "!レキュス":
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_REKUS_PAGE_ID)
            if attachment_data:
                 await message.channel.send("🔎 レキュスが添付ファイルを元に情報を探索します…")
                 summary = await ask_nousos(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                 query_for_rekus = f"{query}\n\n[添付資料の概要: {summary}]"
                 reply = await ask_rekus(user_id, query_for_rekus)
            else:
                await message.channel.send("🔎 レキュスが情報を探索します…")
                reply = await ask_rekus(user_id, query)
            await message.channel.send(reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "レキュス", NOTION_REKUS_PAGE_ID)

        # --- 複合コマンド ---
        elif command_name in ["!みんなで", "!三連", "!逆三連"]:
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)
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

        # --- ★★★ クリティカルコマンド ★★★ ---
        elif command_name == "!クリティカル":
            await message.channel.send("🔥 三神が前回の回答を批判的に再検証します…")
            if user_id == ADMIN_USER_ID:
                await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            # --- 直前の各AIの応答をメモリから取得 ---
            last_kreios_reply = next((msg['content'] for msg in reversed(kreios_memory.get(user_id, [])) if msg['role'] == 'assistant'), "（前回の応答なし）")
            last_nousos_reply = next((msg['content'] for msg in reversed(nousos_memory.get(user_id, [])) if msg['role'] == 'ヌーソス'), "（前回の応答なし）")
            last_rekus_reply = next((msg['content'] for msg in reversed(rekus_memory.get(user_id, [])) if msg['role'] == 'assistant'), "（前回の応答なし）")
            
            if "（前回の応答なし）" in [last_kreios_reply, last_nousos_reply, last_rekus_reply]:
                await message.channel.send("❌ クリティカル分析の素材となる、三神の前回の応答が見つかりませんでした。先に「!みんなで」などを実行してください。")
                return

            material = (f"以下の三者の初回意見を素材として、あなたの役割に基づき批判的な検討を行い、結論を述べなさい。\n"
                        f"なお、今回のあなたの応答は、素材となった意見への批評そのものであり、ユーザーとの対話ではありません。\n\n"
                        f"--- [素材] ---\n"
                        f"### 🏛️ クレイオスの意見:\n{last_kreios_reply}\n\n"
                        f"### 🎓 ヌーソスの意見:\n{last_nousos_reply}\n\n"
                        f"### 🔎 レキュスの意見:\n{last_rekus_reply}\n"
                        f"--- [ここまで] ---")

            # --- クリティカル用のプロンプト定義 ---
            kreios_crit_prompt = "あなたは論理構造の監査官クレイオスです。素材の「構造的整合性」「論理飛躍」を検出し、整理してください。"
            nousos_crit_prompt = "あなたは意味と感情の深層分析官ヌーソスです。素材の「曖昧性・詩的要素・感情含意」に注目し、逆の視点から再解釈・補完してください。"
            rekus_crit_prompt = "あなたはファクトと代替案の検証官レキュスです。素材の主張の「事実性」を検索ベースで反証し、「代替案」を提示してください。"

            # --- 各AIを並列で実行 ---
            kreios_crit_task = ask_kreios(user_id, material, system_prompt=kreios_crit_prompt)
            nousos_crit_task = ask_nousos(user_id, material, system_prompt=nousos_crit_prompt)
            rekus_crit_task = ask_rekus(user_id, material, system_prompt=rekus_crit_prompt)
            
            results = await asyncio.gather(kreios_crit_task, nousos_crit_task, rekus_crit_task, return_exceptions=True)
            kreios_crit_reply, nousos_crit_reply, rekus_crit_reply = results

            # --- Discordに応答を送信 ---
            if not isinstance(kreios_crit_reply, Exception):
                await message.channel.send(f"🏛️ **クレイオス (論理監査)** より:\n{kreios_crit_reply}")
            if not isinstance(nousos_crit_reply, Exception):
                await message.channel.send(f"🎓 **ヌーソス (深層分析)** より:\n{nousos_crit_reply}")
            if not isinstance(rekus_crit_reply, Exception):
                await message.channel.send(f"🔎 **レキュス (事実検証)** より:\n{rekus_crit_reply}")
            
            # --- Notionに最終レポートを書き込み ---
            if user_id == ADMIN_USER_ID:
                final_report = (f"### クリティカル分析レポート\n\n"
                                f"**🏛️ クレイオス (論理監査)の結論:**\n{kreios_crit_reply if not isinstance(kreios_crit_reply, Exception) else 'エラーが発生しました'}\n\n"
                                f"---\n\n"
                                f"**🎓 ヌーソス (深層分析)の結論:**\n{nousos_crit_reply if not isinstance(nousos_crit_reply, Exception) else 'エラーが発生しました'}\n\n"
                                f"---\n\n"
                                f"**🔎 レキュス (事実検証)の結論:**\n{rekus_crit_reply if not isinstance(rekus_crit_reply, Exception) else 'エラーが発生しました'}")
                await log_response(final_report, "三神構造炉", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ 最終分析レポートを構造炉（Notion）に記録しました。")


    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
