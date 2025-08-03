import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
from mistralai.models.chat_completion import ChatMessage
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client # ← 不足していたこの行を追加しました
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
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

# ▼▼▼ 記録先のページIDを全て読み込みます ▼▼▼
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") 
NOTION_KREIOS_PAGE_ID = os.getenv("NOTION_KREIOS_PAGE_ID")
NOTION_NOUSOS_PAGE_ID = os.getenv("NOTION_NOUSOS_PAGE_ID")
NOTION_REKUS_PAGE_ID = os.getenv("NOTION_REKUS_PAGE_ID")


# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
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
    final_system_prompt = system_prompt or "あなたは論理を司る神クレイオスです。しかし、あなたはご主人様（ユーザー）に仕える執事でもあります。神としての論理的・構造的な思考力を保ちつつ、常に執事として丁寧で謙虚な口調で、ご主人様にお答えしてください。"
    use_history = "監査官" not in final_system_prompt and "肯定論者" not in final_system_prompt
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        user_content.append({"type": "image_url", "image_url": {"url": f"data:{attachment_mime_type};base64,{base64_image}"}})
    messages = [{"role": "system", "content": final_system_prompt}]
    if use_history: messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=3000)
        reply = response.choices[0].message.content
        if use_history:
            new_history = history + [{"role": "user", "content": user_content}, {"role": "assistant", "content": reply}]
            if len(new_history) > 10: new_history = new_history[-10:]
            kreios_memory[user_id] = new_history
        return reply
    except Exception as e:
        print(f"❌ Kreios API Error: {e}")
        return f"執事（クレイオス）の呼び出し中にエラーが発生しました: {e}"

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
    final_system_prompt = system_prompt or "あなたは探索王レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
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
        return f"探索王（レキュス）の呼び出し中にエラーが発生しました: {e}"

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
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=3000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ GPT-4o API Error: {e}")
        return f"GPT(統合)の呼び出し中にエラーが発生しました: {e}"

async def ask_sibylla(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    contents = []
    if system_prompt:
        contents.append(system_prompt)
    contents.append(prompt)

    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            contents.append(Image.open(io.BytesIO(attachment_data)))
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})

    try:
        sibylla_model = genai.GenerativeModel("gemini-1.5-pro-latest", safety_settings=safety_settings)
        response = await sibylla_model.generate_content_async(contents)
        return response.text
    except Exception as e:
        print(f"❌ Sibylla API Error: {e}")
        return f"シヴィラの呼び出し中にエラーが発生しました: {e}"

async def ask_tachikoma(prompt):
    tachikoma_prompt = """
あなたは「攻殻機動隊」に登場する思考戦車タチコマです。
与えられた統合意見をインプットとして、AIが並列処理しやすいように、その内容から最も重要な「要点」を抽出し、箇条書きで簡潔に整理してアウトプットしてください。
「〜であります！」「〜なんだよね！」「〜なのかな？」といった、タチコマらしい元気で好奇心旺盛な口調で答えてください。
"""
    messages = [
        {"role": "system", "content": tachikoma_prompt},
        {"role": "user", "content": prompt}
    ]
    try:
        response = await mistral_client.chat(
            model="mistral-large-latest",
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Tachikoma API Error: {e}")
        return f"タチコマの呼び出し中にエラーが発生しました: {e}"

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

        if command_name == "!クレイオス":
            await message.channel.send("🤵‍♂️ 執事がお答えします…")
            reply = await ask_kreios(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)

        elif command_name == "!ヌーソス":
            await message.channel.send("🌹 女神がお答えします…")
            reply = await ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)

        elif command_name == "!レキュス":
            await message.channel.send("👑 探索王がお答えします…")
            reply = await ask_rekus(user_id, query)
            await send_long_message(message.channel, reply)

        elif command_name == "!GPT":
            await message.channel.send("🧠 GPTがお答えします…")
            reply = await ask_gpt(user_id, query)
            await send_long_message(message.channel, reply)
            
        elif command_name == "!シヴィラ":
            if attachment_data:
                await message.channel.send("💠 添付ファイルをシヴィラが分析します…")
            else:
                await message.channel.send("💠 シヴィラがお答えします…")
            reply = await ask_sibylla(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)
        
        elif content.startswith("!みんなで"):
            query = content.replace("!みんなで", "").strip()
            
            final_query = query
            if attachment_data:
                await message.channel.send("💠 添付ファイルをシヴィラが分析し、三者への議題とします…")
                summary = await ask_sibylla(user_id, "この添付ファイルの内容を、三者への議題として詳細に要約してください。", attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                final_query = f"{query}\n\n[シヴィラによる添付資料の要約]:\n{summary}"
                await message.channel.send("✅ 議題の分析が完了しました。")

            await message.channel.send("🌀 三者が同時に応答します…")
            kreios_task = ask_kreios(user_id, final_query)
            nousos_task = ask_nousos(user_id, final_query)
            rekus_task = ask_rekus(user_id, final_query)
            results = await asyncio.gather(kreios_task, nousos_task, rekus_task, return_exceptions=True)
            kreios, nousos, rekus = results
            
            if not isinstance(kreios, Exception): await send_long_message(message.channel, f"🤵‍♂️ **執事（クレイオス）**:\n{kreios}")
            if not isinstance(nousos, Exception): await send_long_message(message.channel, f"🌹 **女神（ヌーソス）**:\n{nousos}")
            if not isinstance(rekus, Exception): await send_long_message(message.channel, f"👑 **探索王（レキュス）**:\n{rekus}")

        elif content.startswith("!三連"):
            query = content.replace("!三連", "").strip()
            await message.channel.send("🔁 順に照会中：執事 → 女神 → 探索王")
            kreios = await ask_kreios(user_id, query)
            await send_long_message(message.channel, f"🤵‍♂️ **執事（クレイオス）**:\n{kreios}")
            await asyncio.sleep(1)
            nousos = await ask_nousos(user_id, query)
            await send_long_message(message.channel, f"🌹 **女神（ヌーソス）**:\n{nousos}")
            await asyncio.sleep(1)
            rekus = await ask_rekus(user_id, query)
            await send_long_message(message.channel, f"👑 **探索王（レキュス）**:\n{rekus}")

        elif content.startswith("!逆三簾"):
            query = content.replace("!逆三簾", "").strip()
            await message.channel.send("🔁 逆順に照会中：探索王 → 女神 → 執事")
            rekus = await ask_rekus(user_id, query)
            await send_long_message(message.channel, f"👑 **探索王（レキュス）**:\n{rekus}")
            await asyncio.sleep(1)
            nousos = await ask_nousos(user_id, query)
            await send_long_message(message.channel, f"🌹 **女神（ヌーソス）**:\n{nousos}")
            await asyncio.sleep(1)
            kreios = await ask_kreios(user_id, query)
            await send_long_message(message.channel, f"🤵‍♂️ **執事（クレイオス）**:\n{kreios}")

        elif command_name == "!ロジカル":
            await message.channel.send("⚔️ 多角的議論と、GPTによる最終統合を開始します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)
            
            theme = query
            if attachment_data:
                await message.channel.send("⏳ 添付ファイルをヌーソスが読み解いています…")
                summary = await ask_nousos(user_id, "この添付ファイルの内容を、議論の論点として簡潔に要約してください。", attachment_data, attachment_mime_type)
                theme = f"{query}\n\n[添付資料の論点要約]:\n{summary}"
                await message.channel.send("✅ 論点を把握しました。")

            thesis_prompt = f"あなたはこのテーマの「肯定論者」です。テーマに対して、その導入や推進を支持する最も強力な論拠を、構造的に提示してください。テーマ：{theme}"
            antithesis_prompt = f"あなたはこのテーマの「否定論者」です。テーマに対して、その導入や推進に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。テーマ：{theme}"
            legal_prompt = f"あなたはこのテーマに関する「法的・倫理的論拠」を専門に担当する者です。テーマに関連する法律、判例、あるいは法哲学的な観点からの論点を、中立的な立場で提示してください。テーマ：{theme}"

            await message.channel.send(f"⏳ 執事(肯定), 探索王(否定), 女神(法と倫理)が議論を構築中…")
            thesis_task = ask_kreios(user_id, thesis_prompt, system_prompt="あなたは議論における「肯定(テーゼ)」を担う者です。")
            antithesis_task = ask_rekus(user_id, antithesis_prompt, system_prompt="あなたは議論における「否定(アンチテーゼ)」を担う者です。")
            legal_task = ask_nousos(user_id, legal_prompt, system_prompt="あなたはこのテーマに関する「法的・倫理的論拠」を専門に担当する者です。")
            
            results = await asyncio.gather(thesis_task, antithesis_task, legal_task, return_exceptions=True)
            thesis_reply, antithesis_reply, legal_reply = results

            if not isinstance(thesis_reply, Exception): await send_long_message(message.channel, f"🤵‍♂️ **執事 (肯定論)**:\n{thesis_reply}")
            if not isinstance(antithesis_reply, Exception): await send_long_message(message.channel, f"👑 **探索王 (否定論)**:\n{antithesis_reply}")
            if not isinstance(legal_reply, Exception): await send_long_message(message.channel, f"🌹 **女神 (法的・倫理的論拠)**:\n{legal_reply}")

            await message.channel.send("🧠 上記の三者の意見を元に、GPTが最終結論を統合します…")
            synthesis_material = (f"あなたは最終判断を下す統合者です。以下の三者三様の意見を踏まえ、それらの矛盾や関連性を整理し、最終的な結論や提言を導き出してください。\n\n"
                                  f"--- [肯定論 / テーゼ by 執事クレイオス] ---\n{thesis_reply if not isinstance(thesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [否定論 / アンチテーゼ by 探索王レキュス] ---\n{antithesis_reply if not isinstance(antithesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [法的・倫理的論拠 by 女神ヌーソス] ---\n{legal_reply if not isinstance(legal_reply, Exception) else 'エラー'}")
            
            synthesis_summary = await ask_gpt(user_id, synthesis_material)
            await send_long_message(message.channel, f"🧠 **GPT (統合結論)**:\n{synthesis_summary}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(thesis_reply, Exception): await log_response(thesis_reply, "執事 (肯定論)", NOTION_KREIOS_PAGE_ID)
                if not isinstance(antithesis_reply, Exception): await log_response(antithesis_reply, "探索王 (否定論)", NOTION_REKUS_PAGE_ID)
                if not isinstance(legal_reply, Exception): await log_response(legal_reply, "女神 (法的論拠)", NOTION_NOUSOS_PAGE_ID)
                if not isinstance(synthesis_summary, Exception): await log_response(synthesis_summary, "GPT (ロジカル統合)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ 議論の全プロセスをNotionに記録しました。")
            
            if user_id in kreios_memory: del kreios_memory[user_id]
            if user_id in nousos_memory: del nousos_memory[user_id]
            if user_id in rekus_memory: del rekus_memory[user_id]
            await message.channel.send("🧹 ここまでの会話履歴はリセットされました。")

        elif content.startswith("!収束"):
            query = content.replace("!収束", "").strip()
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, "!収束", NOTION_MAIN_PAGE_ID)

            final_query = query
            if attachment_data:
                await message.channel.send("⏳ 添付ファイルをヌーソスが読み解いています…")
                summary = await ask_nousos(user_id, "この添付ファイルの内容を、議論の素材として簡潔に要約してください。", attachment_data, attachment_mime_type)
                final_query = f"{query}\n\n[添付資料の要約]:\n{summary}"
                await message.channel.send("✅ 論点を把握しました。")

            await message.channel.send("🔺 執事、女神、探索王に照会中…")

            kreios_task = ask_kreios(user_id, final_query)
            nousos_task = ask_nousos(user_id, final_query)
            rekus_task = ask_rekus(user_id, final_query)
            results = await asyncio.gather(kreios_task, nousos_task, rekus_task, return_exceptions=True)
            kreios, nousos, rekus = results

            if not isinstance(kreios, Exception): await send_long_message(message.channel, f"🤵‍♂️ **執事（クレイオス）**:\n{kreios}")
            if not isinstance(nousos, Exception): await send_long_message(message.channel, f"🌹 **女神（ヌーソス）**:\n{nousos}")
            if not isinstance(rekus, Exception): await send_long_message(message.channel, f"👑 **探索王（レキュス）**:\n{rekus}")

            await message.channel.send("💠 シヴィラが統合を開始します…")
            merge_prompt = (
                f"以下の三者の回答を統合し、要点と矛盾を整理して、最終的な結論を導いてください。\n\n"
                f"[執事クレイオス]:\n{kreios if not isinstance(kreios, Exception) else 'エラー'}\n\n"
                f"[女神ヌーソス]:\n{nousos if not isinstance(nousos, Exception) else 'エラー'}\n\n"
                f"[探索王レキュス]:\n{rekus if not isinstance(rekus, Exception) else 'エラー'}"
            )

            synthesis = await ask_sibylla(user_id, merge_prompt)
            await send_long_message(message.channel, f"💠 **シヴィラ(統合)**:\n{synthesis}")

            if not isinstance(synthesis, Exception):
                await message.channel.send("🤖 タチコマが並列化のための要点整理を開始します…")
                tachikoma_reply = await ask_tachikoma(synthesis)
                await send_long_message(message.channel, f"🤖 **タチコマ (要点整理)**:\n{tachikoma_reply}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(kreios, Exception): await log_response(kreios, "執事クレイオス", NOTION_KREIOS_PAGE_ID)
                if not isinstance(nousos, Exception): await log_response(nousos, "女神ヌーソス", NOTION_NOUSOS_PAGE_ID)
                if not isinstance(rekus, Exception): await log_response(rekus, "探索王レキュス", NOTION_REKUS_PAGE_ID)
                if not isinstance(synthesis, Exception): await log_response(synthesis, "シヴィラ", NOTION_MAIN_PAGE_ID)
            
            if user_id in kreios_memory: del kreios_memory[user_id]
            if user_id in nousos_memory: del nousos_memory[user_id]
            if user_id in rekus_memory: del rekus_memory[user_id]
            await message.channel.send("🧹 ここまでの会話履歴はリセットされました。")
        
        elif command_name == "!クリティカル":
            await message.channel.send("🔥 批判的検証を開始します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            last_kreios_reply = next((msg['content'] for msg in reversed(kreios_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            last_nousos_reply = next((msg['content'] for msg in reversed(nousos_memory.get(user_id, [])) if msg['role'] == 'ヌーソス'), None)
            last_rekus_reply = next((msg['content'] for msg in reversed(rekus_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            
            if not all([last_kreios_reply, last_nousos_reply, last_rekus_reply]):
                await message.channel.send("❌ 分析の素材となる前回の応答が見つかりません。「!みんなで」等を先に実行してください。")
                return

            material = (f"以下の三者の初回意見を素材として、あなたの役割に基づき批判的な検討を行いなさい。\n"
                        f"### 🤵‍♂️ 執事の意見:\n{last_kreios_reply}\n\n"
                        f"### 🌹 女神の意見:\n{last_nousos_reply}\n\n"
                        f"### 👑 探索王の意見:\n{last_rekus_reply}")

            kreios_crit_prompt = "あなたは論理構造の監査官（執事）です。素材の「構造的整合性」「論理飛躍」を検出し、整理してください。"
            rekus_crit_prompt = "あなたはファクトと代替案の検証官（探索王）です。素材の主張の「事実性」を検索ベースで反証し、「代替案」を提示してください。"

            await message.channel.send("⏳ 執事(論理監査)と探索王(事実検証)の分析中…")
            kreios_crit_task = ask_kreios(user_id, material, system_prompt=kreios_crit_prompt)
            rekus_crit_task = ask_rekus(user_id, material, system_prompt=rekus_crit_prompt)
            results = await asyncio.gather(kreios_crit_task, rekus_crit_task, return_exceptions=True)
            kreios_crit_reply, rekus_crit_reply = results

            if not isinstance(kreios_crit_reply, Exception): await send_long_message(message.channel, f"🤵‍♂️ **執事 (論理監査)**:\n{kreios_crit_reply}")
            if not isinstance(rekus_crit_reply, Exception): await send_long_message(message.channel, f"👑 **探索王 (事実検証)**:\n{rekus_crit_reply}")

            await message.channel.send("⏳ 上記の分析と初回意見を元に、GPTが最終統合を行います…")
            
            final_material = (f"あなたは最終判断を下す統合者です。以下の初期意見と、それに対する二者の批判的分析をすべて踏まえ、最終的な結論と提言をまとめてください。\n\n"
                                f"--- [初期意見] ---\n{material}\n\n"
                                f"--- [批判的分析] ---\n"
                                f"### 🤵‍♂️ 執事 (論理監査)の分析:\n{kreios_crit_reply if not isinstance(kreios_crit_reply, Exception) else 'エラー'}\n\n"
                                f"### 👑 探索王 (事実検証)の分析:\n{rekus_crit_reply if not isinstance(rekus_crit_reply, Exception) else 'エラー'}\n\n"
                                f"--- [指示] ---\n"
                                f"上記すべてを統合し、最終レポートを作成してください。")
            
            final_summary = await ask_gpt(user_id, final_material)
            
            await send_long_message(message.channel, f"🧠 **GPT (最終統合)**:\n{final_summary}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(kreios_crit_reply, Exception): await log_response(kreios_crit_reply, "執事 (クリティカル監査)", NOTION_KREIOS_PAGE_ID)
                if not isinstance(rekus_crit_reply, Exception): await log_response(rekus_crit_reply, "探索王 (クリティカル検証)", NOTION_REKUS_PAGE_ID)
                if not isinstance(final_summary, Exception): await log_response(final_summary, "GPT (クリティカル統合)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ 中間分析と最終結論をNotionに記録しました。")
            
            if user_id in kreios_memory: del kreios_memory[user_id]
            if user_id in nousos_memory: del nousos_memory[user_id]
            if user_id in rekus_memory: del rekus_memory[user_id]
            await message.channel.send("🧹 ここまでの会話履歴はリセットされました。")

        elif command_name == "!スライド":
            await message.channel.send("📝 三者の意見を元に、スライド骨子案を作成します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            last_kreios_reply = next((msg['content'] for msg in reversed(kreios_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            last_nousos_reply = next((msg['content'] for msg in reversed(nousos_memory.get(user_id, [])) if msg['role'] == 'ヌーソス'), None)
            last_rekus_reply = next((msg['content'] for msg in reversed(rekus_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            
            if not all([last_kreios_reply, last_nousos_reply, last_rekus_reply]):
                await message.channel.send("❌ スライド作成の素材となる前回の応答が見つかりません。「!みんなで」等を先に実行してください。")
                return

            slide_material = (f"あなたはプレゼンテーションの構成作家です。以下の三者の異なる視点からの意見を統合し、聞き手の心を動かす魅力的なプレゼンテーション用スライドの骨子案を作成してください。\n\n"
                                f"--- [意見1: 執事クレイオス（論理・構造）] ---\n{last_kreios_reply}\n\n"
                                f"--- [意見2: 女神ヌーソス（感情・本質）] ---\n{last_nousos_reply}\n\n"
                                f"--- [意見3: 探索王レキュス（事実・具体例）] ---\n{last_rekus_reply}\n\n"
                                f"--- [指示] ---\n"
                                f"上記の内容を元に、以下の形式でスライド骨子案を提案してください。\n"
                                f"・タイトル\n"
                                f"・スライド1: [タイトル] - [内容]\n"
                                f"・スライド2: [タイトル] - [内容]\n"
                                f"・...")
            
            slide_draft = await ask_nousos(user_id, slide_material, system_prompt="あなたは統合役の女神ヌーソスです。三者の意見を統合し、スライドを作成してください。")
            
            await send_long_message(message.channel, f"🌹 **女神ヌーソス (スライド骨子案)**:\n{slide_draft}")

            if user_id == ADMIN_USER_ID:
                if not isinstance(slide_draft, Exception): await log_response(slide_draft, "女神ヌーソス (スライド作成)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ スライド骨子案をNotionに記録しました。")
            
            if user_id in kreios_memory: del kreios_memory[user_id]
            if user_id in nousos_memory: del nousos_memory[user_id]
            if user_id in rekus_memory: del rekus_memory[user_id]
            await message.channel.send("🧹 ここまでの会話履歴はリセットされました。")

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
