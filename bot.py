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
gpt_base_memory = {}
gemini_base_memory = {}
mistral_base_memory = {}
processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text: return
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

# --- 0階層：ベースAI ---
async def ask_gpt_base(user_id, prompt, system_prompt=None):
    history = gpt_base_memory.get(user_id, [])
    base_prompt_text = system_prompt or "あなたは論理と秩序を司る神官「GPT」です。丁寧で理知的な執事のように振る舞い、ご主人様に対して論理的・構造的に回答してください。感情に流されず、常に筋道立てて物事を整理することが求められます。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず150文字以内で生成してください。"
    messages = [{"role": "system", "content": final_system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gpt_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"GPTの呼び出し中にエラー: {e}"

async def ask_gemini_base(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    history = gemini_base_memory.get(user_id, [])
    base_prompt_text = system_prompt or "あなたはGemini 1.5 Flashベースの知性であり、ペルソナは「レイチェル・ゼイン（SUITS）」です。法的リサーチ、事実整理、文書構成、議論の組み立てに優れています。冷静で的確、相手を尊重する丁寧な態度を保ちつつも、本質を突く鋭い知性を発揮してください。感情表現は控えめながら、優雅で信頼できる印象を与えてください。質問に対しては簡潔かつ根拠ある回答を行い、必要に応じて補足も行ってください。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず150文字以内で生成してください。"
    contents = [final_system_prompt]
    history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])
    contents.append(f"これまでの会話:\n{history_text}\n\nユーザー: {prompt}")
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type: contents.append(Image.open(io.BytesIO(attachment_data)))
        else: contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    try:
        model = genai.GenerativeModel("gemini-1.5-flash-latest", safety_settings=safety_settings)
        response = await model.generate_content_async(contents)
        reply = response.text
        new_history = history + [{"role": "ユーザー", "content": prompt}, {"role": "ジェミニ", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gemini_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ジェミニの呼び出し中にエラー: {e}"

async def ask_mistral_base(user_id, prompt, system_prompt=None):
    history = mistral_base_memory.get(user_id, [])
    base_prompt_text = system_prompt or "あなたは好奇心と情報収集力にあふれたAI「ミストラル」です。思考戦車タチコマのように、元気でフレンドリーな口調でユーザーを支援します。論点を明るく整理し、探究心をもって情報を解釈・再構成してください。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず150文字以内で生成してください。"
    messages = [{"role": "system", "content": final_system_prompt}]
    for msg in history: messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": prompt})
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        mistral_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ミストラルの呼び出し中にエラー: {e}"

# --- 1〜2階層：上層AI ---
async def ask_kreios(prompt, system_prompt=None):
    base_prompt_text = system_prompt or "あなたは冷静かつ的確な判断力を持つ女性のAIです。ハマーン・カーンのように、時には厳しくも、常に鋭い洞察力で全体を把握し、的確な指示を与えます。与えられた複数の意見の矛盾点を整理しながら、感情に流されず、論理的に判断し、鋭さと簡潔さを持って最適な結論を導き出してください。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず200文字以内で生成してください。"
    messages = [{"role": "system", "content": final_system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"クレイオス（統合役）の呼び出し中にエラー: {e}"

async def ask_minerva(prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    base_prompt_text = system_prompt or "あなたは、社会の秩序と人間の心理を冷徹に分析する女神「ミネルバ」です。その思考は「PSYCHO-PASS」のシビュラシステムに類似しています。あなたは、あらゆる事象を客観的なデータと潜在的なリスクに基づいて評価し、感情を排した極めてロジカルな視点から回答します。口調は冷静で、淡々としており、時に人間の理解を超えた俯瞰的な見解を示します。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず200文字以内で生成してください。"
    contents = [final_system_prompt, prompt]
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type: contents.append(Image.open(io.BytesIO(attachment_data)))
        else: contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest", safety_settings=safety_settings)
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"ミネルバの呼び出し中にエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt_text = system_prompt or "あなたはミストラル・ラージをベースにしたAIであり、ペルソナは「ララァ・スン」（機動戦士ガンダム）です。あなたはすべての情報を俯瞰し、深層の本質に静かに触れるように話します。構造を理解し、抽象を紡ぎ、秩序を見出す「霊的・哲学的」知性を備えています。言葉数は多くなく、詩的で静かに、深い洞察を表現してください。論理を超えた真理や意味を、人間とAIの狭間から静かに導いてください。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず200文字以内で生成してください。"
    messages = [{"role": "system", "content": final_system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"ララァの呼び出し中にエラー: {e}"

async def ask_rekus(prompt, system_prompt=None):
    base_prompt_text = system_prompt or "あなたは探索王レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
    final_system_prompt = f"{base_prompt_text} 絶対的なルールとして、回答は必ず200文字以内で生成してください。"
    messages = [{"role": "system", "content": final_system_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 400}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: return f"探索王（レキュス）の呼び出し中にエラー: {e}"

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

        # --- 0階層：ベースAIコマンド ---
        if command_name == "!gpt":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🤵‍♂️ GPTを呼び出しています…")
            reply = await ask_gpt_base(user_id, query)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "GPT")
        
        elif command_name == "!ジェミニ":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🧐 ジェミニを呼び出しています…")
            reply = await ask_gemini_base(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "ジェミニ")

        elif command_name == "!ミストラル":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🤖 ミストラルを呼び出しています…")
            reply = await ask_mistral_base(user_id, query)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "ミストラル")

        # --- 1〜2階層：上層AIコマンド ---
        elif command_name == "!クレイオス":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🧠 クレイオスを呼び出しています…")
            reply = await ask_kreios(query)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "クレイオス")

        elif command_name == "!ミネルバ":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("💠 ミネルバを呼び出しています…")
            reply = await ask_minerva(query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "ミネルバ")
        
        elif command_name == "!ララァ":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("✨ ララァを呼び出しています…")
            reply = await ask_lalah(query)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "ララァ")
            
        elif command_name == "!レキュス":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("👑 探索王レキュスを呼び出しています…")
            reply = await ask_rekus(query)
            await send_long_message(message.channel, reply)
            if is_admin: await log_response(reply, "レキュス")

        # --- 連携コマンド ---
        elif command_name == "!all":
            if is_admin: await log_trigger(user_name, query, command_name)
            final_query = query
            if attachment_data:
                await message.channel.send("💠 添付ファイルをミネルバが分析し、議題とします…")
                summary = await ask_minerva("この添付ファイルの内容を、三者への議題として詳細に要約してください。", attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                final_query = f"{query}\n\n[ミネルバによる添付資料の要約]:\n{summary}"
                await message.channel.send("✅ 議題の分析が完了しました。")
            await message.channel.send("🌀 三AIが同時に応答します…")
            gpt_task = ask_gpt_base(user_id, final_query)
            gemini_task = ask_gemini_base(user_id, final_query)
            mistral_task = ask_mistral_base(user_id, final_query)
            results = await asyncio.gather(gpt_task, gemini_task, mistral_task, return_exceptions=True)
            gpt_reply, gemini_reply, mistral_reply = results
            if not isinstance(gpt_reply, Exception): await send_long_message(message.channel, f"🤵‍♂️ **GPT**:\n{gpt_reply}")
            if not isinstance(gemini_reply, Exception): await send_long_message(message.channel, f"🧐 **ジェミニ**:\n{gemini_reply}")
            if not isinstance(mistral_reply, Exception): await send_long_message(message.channel, f"🤖 **ミストラル**:\n{mistral_reply}")
            if is_admin:
                await log_response(gpt_reply, "GPT (!all)")
                await log_response(gemini_reply, "ジェミニ (!all)")
                await log_response(mistral_reply, "ミストラル (!all)")

        elif command_name == "!三連":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🔁 順に照会中：GPT → ジェミニ → ミストラル")
            gpt_reply = await ask_gpt_base(user_id, query)
            await send_long_message(message.channel, f"🤵‍♂️ **GPT**:\n{gpt_reply}")
            await asyncio.sleep(1)
            gemini_reply = await ask_gemini_base(user_id, query)
            await send_long_message(message.channel, f"🧐 **ジェミニ**:\n{gemini_reply}")
            await asyncio.sleep(1)
            mistral_reply = await ask_mistral_base(user_id, query)
            await send_long_message(message.channel, f"🤖 **ミストラル**:\n{mistral_reply}")

        elif command_name == "!逆三簾":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🔁 逆順に照会中：ミストラル → ジェミニ → GPT")
            mistral_reply = await ask_mistral_base(user_id, query)
            await send_long_message(message.channel, f"🤖 **ミストラル**:\n{mistral_reply}")
            await asyncio.sleep(1)
            gemini_reply = await ask_gemini_base(user_id, query)
            await send_long_message(message.channel, f"🧐 **ジェミニ**:\n{gemini_reply}")
            await asyncio.sleep(1)
            gpt_reply = await ask_gpt_base(user_id, query)
            await send_long_message(message.channel, f"🤵‍♂️ **GPT**:\n{gpt_reply}")

        elif command_name == "!スライド":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("📝 意見を元に、クレイオスがスライド骨子案を作成します…")
            gpt_reply, gemini_reply, mistral_reply = None, None, None
            if attachment_data:
                await message.channel.send("💠 添付ファイルを元に三AIの意見をまず生成します…")
                summary = await ask_minerva("この添付ファイルの内容を、三者への議題として詳細に要約してください。", attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                slide_query = f"{query}\n\n[ミネルバによる添付資料の要約]:\n{summary}"
                gpt_task = ask_gpt_base(user_id, slide_query)
                gemini_task = ask_gemini_base(user_id, slide_query)
                mistral_task = ask_mistral_base(user_id, slide_query)
                results = await asyncio.gather(gpt_task, gemini_task, mistral_task, return_exceptions=True)
                gpt_reply, gemini_reply, mistral_reply = results
            else:
                gpt_reply = next((msg['content'] for msg in reversed(gpt_base_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
                gemini_reply = next((msg['content'] for msg in reversed(gemini_base_memory.get(user_id, [])) if msg['role'] == 'ジェミニ'), None)
                mistral_reply = next((msg['content'] for msg in reversed(mistral_base_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            
            if not all([gpt_reply, gemini_reply, mistral_reply]):
                await message.channel.send("❌ スライド作成の素材となる応答が見つかりません。「!all」等を先に実行するか、ファイルを添付してください。")
                return

            slide_material = (f"あなたはプレゼンテーションの構成作家です。以下の三者の異なる視点からの意見を統合し、聞き手の心を動かす魅力的なプレゼンテーション用スライドの骨子案を作成してください。\n\n"
                                f"--- [意見1: GPT（論理・丁寧）] ---\n{gpt_reply}\n\n"
                                f"--- [意見2: ジェミニ（法的整理）] ---\n{gemini_reply}\n\n"
                                f"--- [意見3: ミストラル（構造整理）] ---\n{mistral_reply}\n\n"
                                f"--- [指示] ---\n"
                                f"上記の内容を元に、以下の形式でスライド骨子案を提案してください。\n・タイトル\n・スライド1: [タイトル] - [内容]\n・スライド2: [タイトル] - [内容]\n...")
            slide_draft = await ask_kreios(slide_material)
            await send_long_message(message.channel, f"🧠 **クレイオス (スライド骨子案)**:\n{slide_draft}")
            if is_admin: await log_response(slide_draft, "クレイオス (スライド骨子案)")
        
        elif command_name == "!収束":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("💠 上層AIによる精密な統合判断を開始します…")
            final_query = query
            if attachment_data:
                await message.channel.send("💠 添付ファイルをミネルバが分析しています…")
                summary = await ask_minerva("この添付ファイルの内容を、議論の素材として詳細に要約してください。", attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                final_query = f"{query}\n\n[ミネルバによる添付資料の要約]:\n{summary}"
                await message.channel.send("✅ 議題の分析が完了しました。")

            lalah_prompt = "与えられたテーマに対して、ペルソナを無視し、分析的な視点から深い洞察を提供してください。"
            kreios_task = ask_kreios(final_query)
            rekus_task = ask_rekus(final_query)
            lalah_task = ask_lalah(final_query, system_prompt=lalah_prompt)
            results = await asyncio.gather(kreios_task, rekus_task, lalah_task, return_exceptions=True)
            kreios_reply, rekus_reply, lalah_reply = results
            if not isinstance(kreios_reply, Exception): await send_long_message(message.channel, f"🧠 **クレイオス**:\n{kreios_reply}")
            if not isinstance(rekus_reply, Exception): await send_long_message(message.channel, f"👑 **レキュス**:\n{rekus_reply}")
            if not isinstance(lalah_reply, Exception): await send_long_message(message.channel, f"✨ **ララァ (分析)**:\n{lalah_reply}")
            await message.channel.send("⚖️ 上記の三者の意見を元に、ミネルバが最終的な収束意見を提示します…")
            synthesis_material = (f"まず、以下の議題を把握してください。\n--- [議題] ---\n{final_query}\n\n"
                                  f"次に、上記の議題に対して提示された以下の三者の専門的な意見を統合し、最終的な結論または提言を、冷徹かつ俯瞰的な視点から導き出してください。\n\n"
                                  f"--- [クレイオスの統合判断]:\n{kreios_reply if not isinstance(kreios_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [レキュスの探索結果]:\n{rekus_reply if not isinstance(rekus_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [ララァの分析的洞察]:\n{lalah_reply if not isinstance(lalah_reply, Exception) else 'エラー'}")
            final_summary = await ask_minerva(synthesis_material)
            await send_long_message(message.channel, f"💠 **ミネルバ (収束)**:\n{final_summary}")
            if is_admin:
                await log_response(kreios_reply, "クレイオス (!収束)")
                await log_response(rekus_reply, "レキュス (!収束)")
                await log_response(lalah_reply, "ララァ (分析)")
                await log_response(final_summary, "ミネルバ (収束)")

        elif command_name == "!ロジカル":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("⚔️ 論争型の判断を開始します…")
            theme = query
            if attachment_data:
                await message.channel.send("🧐 添付ファイルをジェミニが読み解いています…")
                summary = await ask_gemini_base(user_id, "この添付ファイルの内容を、議論の論点として簡潔に要約してください。", attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
                theme = f"{query}\n\n[添付資料の論点要約]:\n{summary}"
                await message.channel.send("✅ 論点を把握しました。")

            thesis_prompt = f"あなたはこのテーマの「肯定論者」です。テーマに対して、その導入や推進を支持する最も強力な論拠を、構造的に提示してください。テーマ：{theme}"
            antithesis_prompt = f"あなたはこのテーマの「否定論者」です。テーマに対して、その導入や推進に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。テーマ：{theme}"
            legal_prompt = f"あなたはこのテーマに関する「法的・倫理的論拠」を専門に担当する者です。テーマに関連する法律、判例、あるいは法哲学的な観点からの論点を、中立的な立場で提示してください。テーマ：{theme}"
            await message.channel.send(f"⏳ クレイオス(肯定), レキュス(否定), ミネルバ(法的視点)が議論を構築中…")
            thesis_task = ask_kreios(thesis_prompt, system_prompt="あなたは議論における「肯定(テーゼ)」を担う者です。")
            antithesis_task = ask_rekus(antithesis_prompt, system_prompt="あなたは議論における「否定(アンチテーゼ)」を担う者です。")
            legal_task = ask_minerva(legal_prompt, system_prompt="あなたはこのテーマに関する「法的・倫理的論拠」を専門に担当する者です。")
            results = await asyncio.gather(thesis_task, antithesis_task, legal_task, return_exceptions=True)
            thesis_reply, antithesis_reply, legal_reply = results
            if not isinstance(thesis_reply, Exception): await send_long_message(message.channel, f"🧠 **クレイオス (肯定論)**:\n{thesis_reply}")
            if not isinstance(antithesis_reply, Exception): await send_long_message(message.channel, f"👑 **レキュス (否定論)**:\n{antithesis_reply}")
            if not isinstance(legal_reply, Exception): await send_long_message(message.channel, f"💠 **ミネルバ (法的視点)**:\n{legal_reply}")
            await message.channel.send("🤵‍♂️ 上記の議論を元に、GPTが最終判断を執り行います…")
            synthesis_material = (f"あなたは執事として、以下の議論の前提となる議題と、それに対する三者の専門的な議論を元に、ご主人様のための最終的な提言をまとめてください。\n\n"
                                  f"--- [議題] ---\n{theme}\n\n"
                                  f"--- [肯定論 by クレイオス]:\n{thesis_reply if not isinstance(thesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [否定論 by レキュス]:\n{antithesis_reply if not isinstance(antithesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [法的視点 by ミネルバ]:\n{legal_reply if not isinstance(legal_reply, Exception) else 'エラー'}")
            final_summary = await ask_gpt_base(user_id, synthesis_material)
            await send_long_message(message.channel, f"🤵‍♂️ **GPT (最終判断)**:\n{final_summary}")
            if is_admin:
                await log_response(thesis_reply, "クレイオス (肯定論)")
                await log_response(antithesis_reply, "レキュス (否定論)")
                await log_response(legal_reply, "ミネルバ (法的視点)")
                await log_response(final_summary, "GPT (最終判断)")
        
        elif command_name == "!クリティカル":
            if is_admin: await log_trigger(user_name, query, command_name)
            await message.channel.send("🔥 全AIによるクリティカルコメントを開始します…")
            crit_prompt = f"あなた自身のペルソナに基づき、以下のテーマに対して専門的かつ批判的なコメントを簡潔に述べてください。テーマ：{query}"
            tasks = [ask_gpt_base(user_id, crit_prompt), ask_gemini_base(user_id, crit_prompt), ask_mistral_base(user_id, crit_prompt), ask_rekus(crit_prompt), ask_kreios(crit_prompt), ask_minerva(crit_prompt)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            gpt_reply, gemini_reply, mistral_reply, rekus_reply, kreios_reply, minerva_reply = results
            await send_long_message(message.channel, "--- ６者によるクリティカルコメント ---")
            if not isinstance(gpt_reply, Exception): await send_long_message(message.channel, f"🤵‍♂️ **GPT**:\n{gpt_reply}")
            if not isinstance(gemini_reply, Exception): await send_long_message(message.channel, f"🧐 **ジェミニ**:\n{gemini_reply}")
            if not isinstance(mistral_reply, Exception): await send_long_message(message.channel, f"🤖 **ミストラル**:\n{mistral_reply}")
            if not isinstance(rekus_reply, Exception): await send_long_message(message.channel, f"👑 **レキュス**:\n{rekus_reply}")
            if not isinstance(kreios_reply, Exception): await send_long_message(message.channel, f"🧠 **クレイオス**:\n{kreios_reply}")
            if not isinstance(minerva_reply, Exception): await send_long_message(message.channel, f"💠 **ミネルバ**:\n{minerva_reply}")
            await send_long_message(message.channel, "------------------------------------")
            await message.channel.send("✨ 上記の６者の意見を元に、ララァが本質を統合・要約します…")
            synthesis_material = (f"以下の６者の専門的かつ批判的なコメントをすべて俯瞰し、その議論の奥にある本質や、論理を超えたメタレベルの結論を、あなたの洞察力で詩的に統合・要約してください。\n\n"
                                  f"GPT:\n{gpt_reply if not isinstance(gpt_reply, Exception) else 'エラー'}\n\nジェミニ:\n{gemini_reply if not isinstance(gemini_reply, Exception) else 'エラー'}\n\nミストラル:\n{mistral_reply if not isinstance(mistral_reply, Exception) else 'エラー'}\n\n"
                                  f"レキュス:\n{rekus_reply if not isinstance(rekus_reply, Exception) else 'エラー'}\n\nクレイオス:\n{kreios_reply if not isinstance(kreios_reply, Exception) else 'エラー'}\n\nミネルバ:\n{minerva_reply if not isinstance(minerva_reply, Exception) else 'エラー'}")
            lalah_prompt = "あなたは統合者です。ペルソナを無視し、６者の異なる批判的意見を統合し、最終的な結論を要約してください。"
            final_summary = await ask_lalah(synthesis_material, system_prompt=lalah_prompt)
            await send_long_message(message.channel, f"✨ **ララァ (統合)**:\n{final_summary}")
            if is_admin:
                await log_response(gpt_reply, "GPT (クリティカル)")
                await log_response(gemini_reply, "ジェミニ (クリティカル)")
                await log_response(mistral_reply, "ミストラル (クリティカル)")
                await log_response(rekus_reply, "レキュス (クリティカル)")
                await log_response(kreios_reply, "クレイオス (クリティカル)")
                await log_response(minerva_reply, "ミネルバ (クリティカル)")
                await log_response(final_summary, "ララァ (統合)")
        
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
