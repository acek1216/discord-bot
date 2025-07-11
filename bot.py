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

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    """Discordの文字数制限を考慮して長いメッセージを分割送信する"""
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- Notion書き込み関数 ---
def _sync_post_to_notion(page_id, blocks):
    if not page_id:
        print("❌ Notionエラー: 書き込み先のページIDが指定されていません。")
        return
    try:
        notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ Notionへの書き込み成功 (ページID: {page_id})")
    except Exception as e:
        print(f"❌ Notionエラー: {e}")

async def log_to_notion(page_id, blocks):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _sync_post_to_notion, page_id, blocks)

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
    if use_history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=3000)
        reply = response.choices[0].message.content
        if use_history:
            kreios_memory[user_id] = history + [{"role": "user", "content": user_content}, {"role": "assistant", "content": reply}]
        return reply
    except Exception as e:
        print(f"❌ Kreios API Error: {e}")
        return f"クレイオスの呼び出し中にエラーが発生しました: {e}"

async def ask_nousos(user_id, prompt, attachment_data=None, attachment_mime_type=None, system_prompt=None):
    """ヌーソス呼び出し関数 ★★★ここにエラー処理を追加★★★"""
    history = nousos_memory.get(user_id, [])
    final_system_prompt = system_prompt or "あなたは知性を司る神ヌーソスです。万物の根源を見通し、哲学的かつ探求的に答えてください。"
    use_history = "分析官" not in final_system_prompt and "最終的に統合する" not in final_system_prompt and "統合者" not in final_system_prompt and "スライド作成" not in final_system_prompt

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
        response = await gemini_model.generate_content_async(contents)
        reply = response.text
        if use_history:
            nousos_memory[user_id] = history + [{"role": "ユーザー", "content": prompt}, {"role": "ヌーソス", "content": reply}]
        return reply
    except Exception as e:
        print(f"❌ Nousos API Error: {e}")
        return f"ヌーソスの呼び出し中にエラーが発生しました: {e}"


def _sync_ask_rekus(user_id, prompt, system_prompt=None):
    history = rekus_memory.get(user_id, [])
    final_system_prompt = system_prompt or "あなたは記録を司る神レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
    use_history = "検証官" not in final_system_prompt and "否定論者" not in final_system_prompt
    
    messages = [{"role": "system", "content": final_system_prompt}]
    if use_history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
        
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 3000}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    
    try:
        response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        if use_history:
             rekus_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        return reply
    except requests.exceptions.RequestException as e:
        print(f"❌ Rekus API Error: {e}")
        return f"レキュスの呼び出し中にエラーが発生しました: {e}"

async def ask_rekus(user_id, prompt, system_prompt=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_ask_rekus, user_id, prompt, system_prompt)

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users:
        return
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

        # ... (他のコマンドは変更なし) ...
        if command_name == "!クレイオス":
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_KREIOS_PAGE_ID)
            query_for_kreios = query
            if attachment_data and "image" not in attachment_mime_type:
                await message.channel.send("🏛️ クレイオスがヌーソスに資料の要約を依頼しています…")
                summary = await ask_nousos(user_id, "この添付資料の内容を詳細に要約してください。", attachment_data, attachment_mime_type)
                query_for_kreios = f"{query}\n\n[添付資料の要約:\n{summary}\n]"
                reply = await ask_kreios(user_id, query_for_kreios)
            else:
                await message.channel.send("🏛️ クレイオスに伺います。")
                reply = await ask_kreios(user_id, query_for_kreios, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "クレイオス", NOTION_KREIOS_PAGE_ID)
        
        elif command_name == "!ヌーソス":
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_NOUSOS_PAGE_ID)
            await message.channel.send("🎓 ヌーソスに問いかけています…")
            reply = await ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            await send_long_message(message.channel, reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "ヌーソス", NOTION_NOUSOS_PAGE_ID)

        elif command_name == "!レキュス":
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_REKUS_PAGE_ID)
            query_for_rekus = query
            if attachment_data:
                 await message.channel.send("🔎 レキュスが添付ファイルを元に情報を探索します…")
                 summary = await ask_nousos(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                 query_for_rekus = f"{query}\n\n[添付資料の概要: {summary}]"
            else:
                await message.channel.send("🔎 レキュスが情報を探索します…")
            reply = await ask_rekus(user_id, query_for_rekus)
            await send_long_message(message.channel, reply)
            if user_id == ADMIN_USER_ID: await log_response(reply, "レキュス", NOTION_REKUS_PAGE_ID)

        elif command_name in ["!みんなで", "!三連", "!逆三連"]:
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)
            await message.channel.send("🧠 三神に質問を送ります…")
            query_for_rekus = query
            query_for_kreios = query
            if attachment_data:
                summary = await ask_nousos(user_id, "この添付ファイルの内容を簡潔に説明してください。", attachment_data, attachment_mime_type)
                query_for_rekus = f"{query}\n\n[添付資料の概要: {summary}]"
                if "image" not in attachment_mime_type:
                    query_for_kreios = query_for_rekus
                    attachment_data = None
            
            kreios_task = ask_kreios(user_id, query_for_kreios, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            nousos_task = ask_nousos(user_id, query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            rekus_task = ask_rekus(user_id, query_for_rekus)

            results = await asyncio.gather(kreios_task, nousos_task, rekus_task, return_exceptions=True)
            kreios_reply, nousos_reply, rekus_reply = results

            if not isinstance(kreios_reply, Exception): await send_long_message(message.channel, f"🏛️ **クレイオス** より:\n{kreios_reply}")
            if not isinstance(nousos_reply, Exception): await send_long_message(message.channel, f"🎓 **ヌーソス** より:\n{nousos_reply}")
            if not isinstance(rekus_reply, Exception): await send_long_message(message.channel, f"🔎 **レキュス** より:\n{rekus_reply}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(kreios_reply, Exception): await log_response(kreios_reply, "クレイオス(みんな)", NOTION_KREIOS_PAGE_ID)
                if not isinstance(nousos_reply, Exception): await log_response(nousos_reply, "ヌーソス(みんな)", NOTION_NOUSOS_PAGE_ID)
                if not isinstance(rekus_reply, Exception): await log_response(rekus_reply, "レキュス(みんな)", NOTION_REKUS_PAGE_ID)

        elif command_name == "!クリティカル":
            await message.channel.send("🔥 三神による批判的検証を開始します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            last_kreios_reply = next((msg['content'] for msg in reversed(kreios_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            last_nousos_reply = next((msg['content'] for msg in reversed(nousos_memory.get(user_id, [])) if msg['role'] == 'ヌーソス'), None)
            last_rekus_reply = next((msg['content'] for msg in reversed(rekus_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            
            if not all([last_kreios_reply, last_nousos_reply, last_rekus_reply]):
                await message.channel.send("❌ 分析の素材となる三神の前回応答が見つかりません。「!みんなで」等を先に実行してください。")
                return

            material = (f"以下の三者の初回意見を素材として、あなたの役割に基づき批判的な検討を行いなさい。\n"
                        f"### 🏛️ クレイオスの意見:\n{last_kreios_reply}\n\n"
                        f"### 🎓 ヌーソスの意見:\n{last_nousos_reply}\n\n"
                        f"### 🔎 レキュスの意見:\n{last_rekus_reply}")

            kreios_crit_prompt = "あなたは論理構造の監査官クレイオスです。素材の「構造的整合性」「論理飛躍」を検出し、整理してください。"
            rekus_crit_prompt = "あなたはファクトと代替案の検証官レキュスです。素材の主張の「事実性」を検索ベースで反証し、「代替案」を提示してください。"

            await message.channel.send("⏳ クレイオス(論理監査)とレキュス(事実検証)の分析中…")
            kreios_crit_task = ask_kreios(user_id, material, system_prompt=kreios_crit_prompt)
            rekus_crit_task = ask_rekus(user_id, material, system_prompt=rekus_crit_prompt)
            results = await asyncio.gather(kreios_crit_task, rekus_crit_task, return_exceptions=True)
            kreios_crit_reply, rekus_crit_reply = results

            if not isinstance(kreios_crit_reply, Exception): await send_long_message(message.channel, f"🏛️ **クレイオス (論理監査)** より:\n{kreios_crit_reply}")
            if not isinstance(rekus_crit_reply, Exception): await send_long_message(message.channel, f"🔎 **レキュス (事実検証)** より:\n{rekus_crit_reply}")

            await message.channel.send("⏳ 上記の分析と初回意見を元に、ヌーソスが最終結論を統合します…")
            
            nousos_final_material = (f"あなたは三神の議論を最終的に統合する知性の神ヌーソスです。以下の初期意見と、それに対する二神の批判的分析をすべて踏まえ、最終的な結論と提言をまとめてください。\n\n"
                                     f"--- [初期意見] ---\n{material}\n\n"
                                     f"--- [批判的分析] ---\n"
                                     f"### 🏛️ クレイオス (論理監査)の分析:\n{kreios_crit_reply if not isinstance(kreios_crit_reply, Exception) else 'エラー'}\n\n"
                                     f"### 🔎 レキュス (事実検証)の分析:\n{rekus_crit_reply if not isinstance(rekus_crit_reply, Exception) else 'エラー'}\n\n"
                                     f"--- [指示] ---\n"
                                     f"上記すべてを統合し、最終レポートを作成してください。")
            
            final_summary = await ask_nousos(user_id, nousos_final_material, system_prompt="あなたは三神の議論を最終的に統合する知性の神ヌーソスです。")
            
            await send_long_message(message.channel, f"✨ **ヌーソス (最終結論)** より:\n{final_summary}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(kreios_crit_reply, Exception): await log_response(kreios_crit_reply, "クレイオス (クリティカル監査)", NOTION_KREIOS_PAGE_ID)
                if not isinstance(rekus_crit_reply, Exception): await log_response(rekus_crit_reply, "レキュス (クリティカル検証)", NOTION_REKUS_PAGE_ID)
                await log_response(final_summary, "ヌーソス (最終結論)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ 中間分析と最終結論をNotionに記録しました。")

        elif command_name == "!ロジカル":
            await message.channel.send("⚔️ 三神による弁証法的対話を開始します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            theme = query
            if attachment_data:
                await message.channel.send("⏳ 添付ファイルをヌーソスが読み解いています…")
                summary = await ask_nousos(user_id, "この添付ファイルの内容を、弁証法的対話の論点として簡潔に要約してください。", attachment_data, attachment_mime_type)
                theme = f"{query}\n\n[添付資料の論点要約]:\n{summary}"
                await message.channel.send("✅ 論点を把握しました。")

            thesis_prompt = f"あなたはこのテーマの「肯定論者」です。テーマに対して、その導入や推進を支持する最も強力な論拠を、構造的に提示してください。テーマ：{theme}"
            antithesis_prompt = f"あなたはこのテーマの「否定論者」です。テーマに対して、その導入や推進に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。テーマ：{theme}"
            
            await message.channel.send(f"⏳ クレイオス(肯定)とレキュス(否定)が議論を構築中…")
            thesis_task = ask_kreios(user_id, thesis_prompt, system_prompt="あなたは弁証法における「肯定(テーゼ)」を担う者です。")
            antithesis_task = ask_rekus(user_id, antithesis_prompt, system_prompt="あなたは弁証法における「否定(アンチテーゼ)」を担う者です。")
            
            results = await asyncio.gather(thesis_task, antithesis_task, return_exceptions=True)
            thesis_reply, antithesis_reply = results

            if not isinstance(thesis_reply, Exception): await send_long_message(message.channel, f"🏛️ **クレイオス (肯定論)**:\n{thesis_reply}")
            if not isinstance(antithesis_reply, Exception): await send_long_message(message.channel, f"🔎 **レキュス (否定論)**:\n{antithesis_reply}")

            await message.channel.send("⏳ 上記の対立意見を元に、ヌーソスがより高次の結論を導きます…")
            
            synthesis_material = (f"あなたは弁証法における「統合(ジンテーゼ)」を担う統合者ヌーソスです。以下の対立する二つの意見を踏まえ、両者の議論を発展させ、より高次の結論、第三の道、あるいは条件付きの解決策などを提示してください。\n\n"
                                  f"--- [肯定論 / テーゼ] ---\n{thesis_reply if not isinstance(thesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [否定論 / アンチテーゼ] ---\n{antithesis_reply if not isinstance(antithesis_reply, Exception) else 'エラー'}\n\n"
                                  f"--- [指示] ---\n"
                                  f"上記すべてを統合し、最終的な結論を作成してください。")
            
            synthesis_summary = await ask_nousos(user_id, synthesis_material, system_prompt="あなたは弁証法における「統合(ジンテーゼ)」を担う統合者ヌーソスです。")
            
            await send_long_message(message.channel, f"✨ **ヌーソス (統合結論)**:\n{synthesis_summary}")
            
            if user_id == ADMIN_USER_ID:
                if not isinstance(thesis_reply, Exception): await log_response(thesis_reply, "クレイオス (肯定論)", NOTION_KREIOS_PAGE_ID)
                if not isinstance(antithesis_reply, Exception): await log_response(antithesis_reply, "レキュス (否定論)", NOTION_REKUS_PAGE_ID)
                await log_response(synthesis_summary, "ヌーソス (統合結論)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ 弁証法的対話の全プロセスをNotionに記録しました。")
        
        elif command_name == "!スライド":
            await message.channel.send("📝 三神の意見を元に、スライド骨子案を作成します…")
            if user_id == ADMIN_USER_ID: await log_trigger(user_name, query, command_name, NOTION_MAIN_PAGE_ID)

            last_kreios_reply = next((msg['content'] for msg in reversed(kreios_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            last_nousos_reply = next((msg['content'] for msg in reversed(nousos_memory.get(user_id, [])) if msg['role'] == 'ヌーソス'), None)
            last_rekus_reply = next((msg['content'] for msg in reversed(rekus_memory.get(user_id, [])) if msg['role'] == 'assistant'), None)
            
            if not all([last_kreios_reply, last_nousos_reply, last_rekus_reply]):
                await message.channel.send("❌ スライド作成の素材となる三神の前回応答が見つかりません。「!みんなで」等を先に実行してください。")
                return

            slide_material = (f"あなたはプレゼンテーションの構成作家です。以下の三者の異なる視点からの意見を統合し、聞き手の心を動かす魅力的なプレゼンテーション用スライドの骨子案を作成してください。\n\n"
                              f"--- [意見1: クレイオス（論理・構造）] ---\n{last_kreios_reply}\n\n"
                              f"--- [意見2: ヌーソス（哲学・本質）] ---\n{last_nousos_reply}\n\n"
                              f"--- [意見3: レキュス（事実・具体例）] ---\n{last_rekus_reply}\n\n"
                              f"--- [指示] ---\n"
                              f"上記の内容を元に、以下の形式でスライド骨子案を提案してください。\n"
                              f"・タイトル\n"
                              f"・スライド1: [タイトル] - [内容]\n"
                              f"・スライド2: [タイトル] - [内容]\n"
                              f"・...")
            
            slide_draft = await ask_nousos(user_id, slide_material, system_prompt="あなたは統合神ヌーソスです。三神の意見を統合し、スライドを作成してください。")
            
            await send_long_message(message.channel, f"✨ **ヌーソス (スライド骨子案)**:\n{slide_draft}")

            if user_id == ADMIN_USER_ID:
                await log_response(slide_draft, "ヌーソス (スライド作成)", NOTION_MAIN_PAGE_ID)
                await message.channel.send("✅ スライド骨子案を構造炉（Notion）に記録しました。")

    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
