import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests
import aiohttp
import fitz  # PyMuPDF

#--- 環境変数の読み込み
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID")

# Renderの環境変数から対応表を読み込み、辞書を作成
NOTION_PAGE_MAP_STRING = os.getenv("NOTION_PAGE_MAP_STRING", "")
NOTION_PAGE_MAP = {}
if NOTION_PAGE_MAP_STRING:
    try:
        pairs = NOTION_PAGE_MAP_STRING.split(',')
        for pair in pairs:
            if ':' in pair:
                thread_id, page_id = pair.split(':', 1)
                NOTION_PAGE_MAP[thread_id.strip()] = page_id.strip()
    except Exception as e:
        print(f"Error: NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")

#--- 各種クライアントの初期化
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

#--- メモリ管理
gpt_base_memory = {}
gemini_base_memory = {}
mistral_base_memory = {}
processing_users = set()

#--- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# Notion連携関数
def _sync_get_notion_page_text(page_id):
    all_text_blocks = []
    next_cursor = None
    while True:
        try:
            response = notion.blocks.children.list(block_id=page_id, start_cursor=next_cursor, page_size=100)
            results = response.get("results", [])
            for block in results:
                if block.get("type") == "paragraph":
                    for rich_text in block.get("paragraph", {}).get("rich_text", []):
                        all_text_blocks.append(rich_text.get("text", {}).get("content", ""))
            if response.get("has_more"):
                next_cursor = response.get("next_cursor")
            else:
                break
        except Exception as e:
            print(f"Notion読み込みエラー: {e}")
            return f"ERROR: Notion API Error {e}"
    return "\n".join(all_text_blocks)

async def get_notion_page_text(page_id):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, page_id)

async def log_to_notion(page_id, blocks):
    if not page_id: return
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.append(block_id=page_id, children=blocks))
    except Exception as e:
        print(f"Notion書き込みエラー: {e}")

async def log_response(page_id, answer, bot_name):
    if not page_id or not answer or isinstance(answer, Exception):
        return
    chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"<{bot_name}>:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

#--- AIモデル呼び出し関数 ---

# (階層1: 下位AI)
async def ask_pod042(prompt):
    system_prompt = "あなたはポッド042です。与えられた情報を元に、質問に対して「報告:」または「提案:」から始めて200文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"ポッド042エラー: {e}"

async def ask_pod153(prompt):
    system_prompt = "あなたはポッド153です。与えられた情報を元に、質問に対して「分析結果:」または「補足」 から始めて200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド153エラー: {e}"

# (階層2: ベースAI)
async def ask_gpt_base(user_id, prompt):
    history = gpt_base_memory.get(user_id, [])
    system_prompt = "あなたは論理と秩序を司る神官「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gpt_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"GPTエラー: {e}"

async def ask_gemini_base(user_id, prompt):
    history = gemini_base_memory.get(user_id, [])
    system_prompt = "あなたは「レイチェル・ゼイン (SUITS)」です。会話の文脈を考慮して150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        reply = response.text
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gemini_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ジェミニエラー: {e}"

async def ask_mistral_base(user_id, prompt):
    history = mistral_base_memory.get(user_id, [])
    system_prompt = "あなたは思考戦車タチコマです。会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        mistral_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ミストラルエラー: {e}"

# (階層3: ナレッジAI)
async def ask_kreios(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"クレイオスエラー: {e}"

async def ask_minerva(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはシビュラシステムです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=base_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"ミネルバエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはララァ・スンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"ララァエラー: {e}"

async def ask_rekus(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたは探索王レキュスです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 400}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: return f"レキュスエラー: {e}"

# (階層4: 統合AI)
async def ask_final_integrator(material, system_prompt):
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": material}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=3000)
        return response.choices[0].message.content
    except Exception as e: return f"Final Integrator Error: {e}"


#--- 添付ファイル分析ヘルパー (PDF対応版) ---
async def analyze_attachment(attachment, analyzer_func, channel):
    try:
        await channel.send(f"添付ファイル「{attachment.filename}」をダウンロード中...")
        async with aiohttp.ClientSession() as session:
            async with session.get(attachment.url) as resp:
                if resp.status != 200:
                    await channel.send(f"添付ファイルのダウンロードに失敗しました: {attachment.filename}")
                    return None
                file_content_bytes = await resp.read()

        file_text = ""
        # ファイルタイプに応じて処理を分岐
        if attachment.filename.lower().endswith('.pdf'):
            await channel.send(f"PDFファイルを解析中...")
            try:
                # PyMuPDFでPDFを開き、テキストを抽出
                with fitz.open(stream=file_content_bytes, filetype="pdf") as doc:
                    for page in doc:
                        file_text += page.get_text()
                if not file_text.strip():
                    await channel.send(f"PDF「{attachment.filename}」からテキストを抽出できませんでした。画像ベースのPDFの可能性があります。")
                    return None
            except Exception as e:
                await channel.send(f"PDFファイルの解析に失敗しました: {e}")
                return None
        else: # テキストファイルとしてデコードを試みる
            try:
                file_text = file_content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    file_text = file_content_bytes.decode('shift-jis') # Shift-JISも試す
                except UnicodeDecodeError:
                    await channel.send(f"添付ファイル「{attachment.filename}」はサポートされていないテキスト形式です。")
                    return None

        await channel.send(f"担当AIによるファイル内容の要約を開始します...")
        summary = await analyzer_func(file_text)
        return summary
    except Exception as e:
        await channel.send(f"添付ファイルの処理中に予期せぬエラーが発生しました: {e}")
        return None


#--- Notionコンテキスト生成ヘルパー ---
async def get_notion_context(channel, page_id, query):
    await channel.send(f"Notionページを読み込んでいます...")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await channel.send("Notionページからテキストを取得できませんでした。")
        return None

    chunk_summarizer_model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは要約AIです。指示された文字数制限に従ってください。")
    chunk_size = 8000
    text_chunks = [notion_text[i:i+chunk_size] for i in range(0, len(notion_text), chunk_size)]
    chunk_summaries = []
    await channel.send(f"Notionの内容を{len(text_chunks)}個のチャンクに分割し、要約を開始します...")
    for i, chunk in enumerate(text_chunks):
        prompt = f"以下の文章を、ユーザーの質問「{query}」の文脈に合わせて2000文字以内で要約してください。\n\n{chunk}"
        try:
            response = await chunk_summarizer_model.generate_content_async(prompt)
            chunk_summaries.append(response.text)
        except Exception as e:
            await channel.send(f"チャンク[{i+1}]の要約中にエラー: {e}")
            await asyncio.sleep(3)

    if not chunk_summaries:
        await channel.send("Notionページの内容を要約できませんでした。")
        return None

    await channel.send("全チャンクの要約完了。gpt-4oが統合・分析します...")
    combined = "\n---\n".join(chunk_summaries)
    prompt = f"以下の要約群を一つの文脈に統合してください。\n\n{combined}"
    messages=[{"role": "system", "content": "あなたは統合AIです。"}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2200)
        final_context = response.choices[0].message.content
        return final_context
    except Exception as e:
        await channel.send(f"統合中にエラー: {e}")
        return None

#--- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"ログイン成功: {client.user}")
    print(f"Notion対応表が読み込まれました: {NOTION_PAGE_MAP}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users:
        return

    if not message.content.startswith("!"):
        return

    processing_users.add(message.author.id)
    try:
        content = message.content
        command_name = content.split(' ')[0].lower()
        user_id, user_name = str(message.author.id), message.author.display_name
        original_query = content[len(command_name):].strip()
        query = original_query
        is_admin = user_id == ADMIN_USER_ID
        thread_id = str(message.channel.id)
        target_notion_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        # 添付ファイルの処理
        if message.attachments:
            attachment = message.attachments[0]
            analyzer_func = None
            
            if command_name in ["!gpt", "!ジェミニ", "!ミストラル", "!みんなで"]:
                analyzer_func = lambda text: ask_gemini_base(user_id, f"この文章を要約してください:\n{text}")
            elif command_name in ["!クレイオス", "!ミネルバ", "!レキュス", "!ララァ", "!all", "!クリティカル", "!ロジカル", "!スライド"]:
                analyzer_func = lambda text: ask_minerva(f"この文章を要約してください:\n{text}")

            if analyzer_func:
                attachment_summary = await analyze_attachment(attachment, analyzer_func, message.channel)
                if attachment_summary:
                    query = f"【添付ファイル要約】\n{attachment_summary}\n\n【ユーザーの質問】\n{original_query}"
        
        if not target_notion_page_id and command_name not in ["!gpt", "!ジェミニ", "!ミストラル", "!ポッド042", "!ポッド153", "!みんなで", "!スライド"]:
            await message.channel.send("X このスレッドに対応するNotionページが設定されておらず、メインページの指定もありません。")
            return

        if is_admin:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"<{user_name}>が「{command_name} {original_query}」を実行しました。"}}]}}]
            await log_to_notion(target_notion_page_id, log_blocks)

        # グループ1: Notion非参照AI
        if command_name in ["!gpt", "!ジェミニ", "!ミストラル", "!ポッド042", "!ポッド153", "!みんなで"]:
            if command_name == "!みんなで":
                await message.channel.send("◎ ベースAI 3体が同時に応答します...")
                tasks = {"GPT": ask_gpt_base(user_id, query), "ジェミニ": ask_gemini_base(user_id, query), "ミストラル": ask_mistral_base(user_id, query)}
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                for name, result in zip(tasks.keys(), results):
                    await send_long_message(message.channel, f"**{name}:**\n{result}")
                    if is_admin: await log_response(target_notion_page_id, result, f"{name} (!みんなで)")
            else: # 個別呼び出し
                reply, bot_name = None, None
                if command_name == "!gpt": bot_name, reply = "GPT", await ask_gpt_base(user_id, query)
                elif command_name == "!ジェミニ": bot_name, reply = "ジェミニ", await ask_gemini_base(user_id, query)
                elif command_name == "!ミストラル": bot_name, reply = "ミストラル", await ask_mistral_base(user_id, query)
                elif command_name == "!ポッド042": bot_name, reply = "ポッド042 (添付非対応)", await ask_pod042(query)
                elif command_name == "!ポッド153": bot_name, reply = "ポッド153 (添付非対応)", await ask_pod153(query)
                if reply:
                    await send_long_message(message.channel, f"《{bot_name}より応答》\n{reply}")
                    if is_admin: await log_response(target_notion_page_id, reply, bot_name)
        
        # グループ2: 複合・Notion参照AI
        elif command_name in ["!クレイオス", "!ミネルバ", "!レキュス", "!ララァ", "!all", "!クリティカル", "!ロジカル", "!スライド"]:
            
            if command_name == "!スライド":
                await message.channel.send("▶️ フロー①: ベースAI 3体による意見出しを開始...")
                tasks_step1 = {"GPT": ask_gpt_base(user_id, query), "ジェミニ": ask_gemini_base(user_id, query), "ミストラル": ask_mistral_base(user_id, query)}
                results_step1 = await asyncio.gather(*tasks_step1.values(), return_exceptions=True)
                
                synthesis_material_step1 = "以下の3つのAIの意見を統合し、魅力的なプレゼンテーションの骨子案（叩き台）を作成してください。\n\n"
                for name, result in zip(tasks_step1.keys(), results_step1):
                    synthesis_material_step1 += f"--- [{name}の意見] ---\n{result}\n\n"
                
                await message.channel.send("▶️ フロー②: ララァによる一次統合を開始...")
                draft_by_lalah = await ask_lalah(synthesis_material_step1, system_prompt="あなたはプレゼンテーションの構成作家です。与えられた複数の意見を元に、聞き手の心を動かす構成案（叩き台）を作成してください。")
                await send_long_message(message.channel, f"**ララァによる一次統合案:**\n{draft_by_lalah}")

                await message.channel.send("▶️ フロー③: ナレッジAI 3体による追加考察を開始...")
                context_for_step3 = await get_notion_context(message.channel, target_notion_page_id, original_query)
                prompt_for_step3 = f"以下の【スライド骨子案（叩き台）】を読み、あなたの専門的な観点から、さらに深い考察や改善案、別の視点からの意見を追加してください。\n\n【スライド骨子案（叩き台）】\n{draft_by_lalah}\n\n【参考情報】\n{context_for_step3 if context_for_step3 else 'なし'}"
                
                tasks_step3 = {
                    "クレイオス": ask_kreios(prompt_for_step3), "ミネルバ": ask_minerva(prompt_for_step3), "レキュス": ask_rekus(prompt_for_step3)
                }
                results_step3 = await asyncio.gather(*tasks_step3.values(), return_exceptions=True)

                synthesis_material_final = f"以下の【ララァの一次統合案】と、【3体のAIによる追加考察】をすべて統合し、最終的なプレゼンテーションのスライド骨子案を完成させてください。\n\n【ララァの一次統合案】\n{draft_by_lalah}\n\n"
                for name, result in zip(tasks_step3.keys(), results_step3):
                    synthesis_material_final += f"--- [{name}の追加考察] ---\n{result}\n\n"

                await message.channel.send("▶️ フロー④: GPT-4oによる最終統合を開始...")
                final_slide_deck = await ask_final_integrator(synthesis_material_final, system_prompt="あなたは最高位の統合AIです。与えられた草案と複数の考察を元に、論理的で一貫性のある、完成されたプレゼンテーションの骨子案を作成してください。最終成果物のみを出力してください。")
                await send_long_message(message.channel, f"**【最終スライド骨子案】(by GPT-4o)**\n{final_slide_deck}")
                if is_admin: await log_response(target_notion_page_id, final_slide_deck, "スライド最終案 (GPT-4o)")

            else: # スライド以外のNotion参照コマンド
                context = await get_notion_context(message.channel, target_notion_page_id, original_query)
                if not context: return
                await message.channel.send("最終回答生成中...")
                prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{query}\n\n【参考情報】\n{context}"

                if command_name in ["!クレイオス", "!ミネルバ","!レキュス", "!ララァ"]:
                    reply, bot_name = None, None
                    if command_name == "!クレイオス": bot_name, reply = "クレイオス", await ask_kreios(prompt_with_context)
                    elif command_name == "!ミネルバ": bot_name, reply = "ミネルバ", await ask_minerva(prompt_with_context)
                    elif command_name == "!レキュス": bot_name, reply = "レキュス", await ask_rekus(prompt_with_context)
                    elif command_name == "!ララァ": bot_name, reply = "ララァ", await ask_lalah(prompt_with_context)
                    if reply:
                        await send_long_message(message.channel, f"**最終回答(by {bot_name}):**\n{reply}")
                        if is_admin: await log_response(target_notion_page_id, reply, f"{bot_name} (Notion参照)")

                elif command_name == "!all":
                    await message.channel.send("◎ 全AIがNotionを元に応答します...")
                    tasks = { "GPT": ask_gpt_base(user_id, prompt_with_context), "ジェミニ": ask_gemini_base(user_id, prompt_with_context), "ミストラル": ask_mistral_base(user_id, prompt_with_context), "クレイオス": ask_kreios(prompt_with_context), "ミネルバ": ask_minerva(prompt_with_context), "レキュス": ask_rekus(prompt_with_context) }
                    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                    for (name, result) in zip(tasks.keys(), results):
                        reply_text = result if not isinstance(result, Exception) else f"エラー: {result}"
                        await send_long_message(message.channel, f"**{name}:**\n{reply_text}")
                        if is_admin: await log_response(target_notion_page_id, reply_text, f"{name} (!all)")
                
                elif command_name == "!クリティカル":
                    await message.channel.send("◎ 6体のAIが初期意見を生成中...")
                    tasks = { "GPT": ask_gpt_base(user_id, prompt_with_context), "ジェミニ": ask_gemini_base(user_id, prompt_with_context), "ミストラル": ask_mistral_base(user_id, prompt_with_context), "クレイオス": ask_kreios(prompt_with_context), "ミネルバ": ask_minerva(prompt_with_context), "レキュス": ask_rekus(prompt_with_context) }
                    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                    synthesis_material = "以下の6つの異なるAIの意見を統合し、客観的な事実と論理に基づいて、最終的な結論をレポートとしてまとめてください。\n\n"
                    for (name, result) in zip(tasks.keys(), results):
                        reply_text = result if not isinstance(result, Exception) else f"エラー: {result}"
                        await send_long_message(message.channel, f"**{name}の意見:**\n{reply_text}")
                        synthesis_material += f"--- [{name}の意見] ---\n{reply_text}\n\n"
                        if is_admin: await log_response(target_notion_page_id, reply_text, f"{name} (!クリティカル)")
                    
                    await message.channel.send("▶️ GPT-4oが最終統合を行います...")
                    final_report = await ask_final_integrator(synthesis_material, system_prompt="あなたは最高位の統合AIです。与えられた複数の意見を分析し、客観的な事実と論理に基づいて、最終的な結論をレポートとしてまとめてください。")
                    await send_long_message(message.channel, f"**【最終統合レポート】(by GPT-4o)**\n{final_report}")
                    if is_admin: await log_response(target_notion_page_id, final_report, "クリティカル最終レポート (GPT-4o)")
                    for mem_dict in [gpt_base_memory, gemini_base_memory, mistral_base_memory]:
                        if user_id in mem_dict: del mem_dict[user_id]
                    await message.channel.send("ベースAIの短期記憶はリセットされました。")

                elif command_name == "!ロジカル":
                    await message.channel.send("◎ 3体のAIが異なる立場で意見を生成中...")
                    tasks = {
                        "肯定論者(クレイオス)": ask_kreios(prompt_with_context, system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"),
                        "否定論者(レキュス)": ask_rekus(prompt_with_context, system_prompt="あなたはこの議題の【否定論者】です。議題に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。"),
                        "中立分析官(ミネルバ)": ask_minerva(prompt_with_context, system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。")
                    }
                    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                    synthesis_material = "以下の3つの異なる立場の意見を統合し、客観的な事実と論理に基づいて、最終的な結論をレポートとしてまとめてください。\n\n"
                    for (name, result) in zip(tasks.keys(), results):
                        reply_text = result if not isinstance(result, Exception) else f"エラー: {result}"
                        await send_long_message(message.channel, f"**{name}:**\n{reply_text}")
                        synthesis_material += f"--- [{name}の意見] ---\n{reply_text}\n\n"
                        if is_admin: await log_response(target_notion_page_id, reply_text, f"{name} (!ロジカル)")
                    
                    await message.channel.send("▶️ GPT-4oが最終統合を行います...")
                    final_report = await ask_final_integrator(synthesis_material, system_prompt="あなたは最高位の統合AIです。与えられた3つの異なる立場の意見を分析し、客観的な事実と論理に基づいて、最終的な結論をレポートとしてまとめてください。")
                    await send_long_message(message.channel, f"**【最終統合レポート】(by GPT-4o)**\n{final_report}")
                    if is_admin: await log_response(target_notion_page_id, final_report, "ロジカル最終レポート (GPT-4o)")

    except Exception as e:
        print(f"An error occurred in on_message: {e}")
        error_message = str(e)
        display_error = (error_message[:300] + '...') if len(error_message) > 300 else error_message
        await message.channel.send(f"予期せぬエラーが発生しました: ```{display_error}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

#--- 起動
if __name__ == "__main__":
    if not all([DISCORD_TOKEN, openai_api_key, gemini_api_key, MISTRAL_API_KEY, perplexity_api_key, notion_api_key]):
        print("致命的なエラー: 必要な環境変数がすべて設定されていません。")
    else:
        client.run(DISCORD_TOKEN)
