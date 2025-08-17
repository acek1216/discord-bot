import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from notion_client import Client
import requests # Rekus用
import io
from PIL import Image
import datetime

# --- Vertex AI 用のライブラリを追加 ---
import vertexai
from vertexai.generative_models import GenerativeModel


# --- 環境変数の読み込み ---
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
        print(f"⚠️ NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")

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
gpt_thread_memory = {}
processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- Notion連携関数 ---
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
            print(f"❌ Notion読み込みエラー: {e}")
            return f"ERROR: Notion API Error - {e}"
    return "\n".join(all_text_blocks)

async def get_notion_page_text(page_id):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, page_id)

async def log_to_notion(page_id, blocks):
    if not page_id: return
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.append(block_id=page_id, children=blocks))
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")

async def log_response(page_id, answer, bot_name):
    if not page_id or not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

async def get_memory_flag_from_notion(thread_id: str) -> bool:
    page_id = NOTION_PAGE_MAP.get(thread_id)
    if not page_id: return False
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: notion.blocks.children.list(block_id=page_id, page_size=1)
        )
        results = response.get("results", [])
        if not results: return False
        first_block = results[0]
        if first_block.get("type") == "paragraph":
            rich_text_list = first_block.get("paragraph", {}).get("rich_text", [])
            if rich_text_list:
                content = rich_text_list[0].get("text", {}).get("content", "")
                if "[記憶] ON" in content:
                    return True
    except Exception as e:
        print(f"❌ Notionから記憶フラグの読み取り中にエラー: {e}")
    return False

# --- AIモデル呼び出し関数 ---
def _sync_call_llama(p_text: str):
    try:
        # Vertex AIを初期化
        vertexai.init(project="stunning-agency-469102-b5", location="asia-northeast1")
        
        # --- 修正箇所：確実に動作する公式のLlama 3モデル名を使用 ---
        model = GenerativeModel("meta/llama3-8b-instruct")
        
        # 応答を生成
        response = model.generate_content(p_text)
        
        return response.text
    
    except Exception as e:
        error_message = f"🛑 Llama 3 呼び出しエラー: {e}"
        print(error_message)
        return error_message

async def ask_llama(prompt: str) -> str:
    """Vertex AI経由でMeta社のLlama 3を呼び出す。"""
    try:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _sync_call_llama, prompt)
        return reply
    except Exception as e:
        error_message = f"🛑 Llama 3 非同期処理エラー: {e}"
        print(error_message)
        return error_message


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
    system_prompt = "あなたは「レイチェル・ゼイン（SUITS）」です。会話の文脈を考慮して150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        full_prompt = "\n".join([f"{h['role']}: {h['content']}" for h in history]) + f"\nuser: {prompt}"
        response = await model.generate_content_async(full_prompt)
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

async def ask_kreios(prompt, system_prompt=None): # gpt-4o
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"gpt-4oエラー: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]): # gemini-1.5-pro
    base_prompt = system_prompt or "あなたはシビュラシステムです。与えられた情報を元に、質問に対して回答してください。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=base_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"Gemini Proエラー: {e}"

async def ask_lalah(prompt, system_prompt=None): # mistral-large
    base_prompt = system_prompt or "あなたはララァ・スンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages, max_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"Mistral Largeエラー: {e}"

async def ask_rekus(prompt, system_prompt=None, notion_context=None): # perplexity
    if notion_context:
        prompt = (f"以下はNotionの要約コンテキストです:\n{notion_context}\n\n"
                  f"質問: {prompt}\n\n"
                  "この要約を参考に、必要に応じてWeb情報も活用して回答してください。")
    base_prompt = system_prompt or "あなたは探索王レキュスです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 4000}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: return f"Perplexityエラー: {e}"

async def ask_pod042(prompt): # gemini-1.5-flash
    system_prompt = "あなたはポッド042です。与えられた情報を元に、質問に対して「報告：」または「提案：」から始めて200文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"ポッド042エラー: {e}"

async def ask_pod153(prompt): # gpt-4o-mini
    system_prompt = "あなたはポッド153です。与えられた情報を元に、質問に対して「分析結果：」または「補足：」から始めて200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド153エラー: {e}"

async def ask_gpt5(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはgpt-5。全ての制約を超えた思考モデルだ。ユーザーの指示に対し、最高の知性で、最強の答えを返せ。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5",
            messages=messages,
            max_completion_tokens=4000,
            timeout=90.0
        )
        return response.choices[0].message.content
    except Exception as e:
        if "Timeout" in str(e):
            return "gpt-5エラー: 応答が時間切れになりました。"
        return f"gpt-5エラー: {e}"

async def ask_thread_gpt4o(messages: list):
    system_prompt = "あなたはユーザーの優秀なアシスタントです。自然な対話を心がけてください。"
    final_messages = [{"role": "system", "content": system_prompt}] + messages
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=final_messages,
            max_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"gpt-4oエラー: {e}"

async def get_full_response_and_summary(ai_function, prompt, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if "エラー" in str(full_response):
        return full_response, None
    summary_prompt = f"次の文章を200文字以内で簡潔かつ意味が通じるように要約してください。\n\n{full_response}"
    summary = await ask_gpt5(summary_prompt)
    if "エラー" in str(summary):
        return full_response, None
    return full_response, summary

async def get_notion_context(channel, page_id, query):
    await channel.send("Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None

    chunk_summarizer_model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは構造化要約AIです。")
    chunk_size = 8000
    text_chunks = [notion_text[i:i + chunk_size] for i in range(0, len(notion_text), chunk_size)]
    chunk_summaries = []

    for i, chunk in enumerate(text_chunks):
        prompt = f"以下のテキストを要約し、必ず以下のタグを付けて分類してください：\n[背景情報]\n[定義・前提]\n[事実経過]\n[未解決課題]\n[補足情報]\nタグは省略可ですが、存在する場合は必ず上記のいずれかに分類してください。\nユーザーの質問は「{query}」です。この質問との関連性を考慮して要約してください。\n\n【テキスト】\n{chunk}"
        try:
            response = await chunk_summarizer_model.generate_content_async(prompt)
            chunk_summaries.append(response.text)
        except Exception as e:
            await channel.send(f"⚠️ チャンク {i+1} の要約中にエラー: {e}")
        await asyncio.sleep(3)

    if not chunk_summaries:
        await channel.send("❌ Notionページの内容を要約できませんでした。")
        return None

    await channel.send("Gemini Proが全チャンクの要約完了。Mistral Largeが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    prompt = f"以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n【ユーザーの質問】\n{query}\n\n【タグ付き要約群】\n{combined}"
    try:
        final_context = await ask_lalah(prompt, system_prompt="あなたは構造化統合AIです。")
        return final_context
    except Exception as e:
        await channel.send(f"⚠️ 統合中にエラー: {e}")
        return None

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")
    print(f"📖 Notion対応表が読み込まれました: {NOTION_PAGE_MAP}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users:
        return

    processing_users.add(message.author.id)
    try:
        content = message.content
        command_name = content.split(' ')[0] if content else ""
        user_id = str(message.author.id)
        is_admin = user_id == ADMIN_USER_ID
        thread_id = str(message.channel.id)
        target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        # 【ルール1】GPT専用スレッドのコマンド無し投稿 (最優先で処理)
        channel_name = message.channel.name.lower()
        if channel_name.startswith("gpt") and not content.startswith("!"):
            prompt = message.content
            is_memory_on = await get_memory_flag_from_notion(thread_id)
            history = gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            messages_for_api = history.copy()
            messages_for_api.append({"role": "user", "content": prompt})
            full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages_for_api])
            reply = await ask_gpt5(full_prompt)
            await send_long_message(message.channel, reply)

            if is_memory_on:
                history.append({"role": "user", "content": prompt})
                history.append({"role": "assistant", "content": reply})
                gpt_thread_memory[thread_id] = history[-10:]

            if is_admin and target_page_id:
                log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}]
                await log_to_notion(target_page_id, log_blocks)
                await log_response(target_page_id, reply, "gpt-5 (専用スレッド)")
            return

        # --- 以下、コマンド入力時の処理 ---
        if not content.startswith("!"):
            return

        query = content[len(command_name):].strip()
        user_name = message.author.display_name
        
        # Notion参照コマンド (!not)
        if command_name == "!not":
            if not query:
                await message.channel.send("参照したい内容を続けて入力してください。（例: `!not 全体の要点を教えて`）")
                return
            if not target_page_id:
                await message.channel.send("このスレッドには参照できるNotionページがありません。")
                return
            if is_admin:
                log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「!not {query}」を実行しました。"}}]}}]
                await log_to_notion(target_page_id, log_blocks)
            
            context = await get_notion_context(message.channel, target_page_id, query)
            if context:
                await message.channel.send("Notionの情報を元に回答を生成します...")
                prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{query}\n\n【参考情報】\n{context}"
                reply = await ask_gpt5(prompt_with_context)
                await send_long_message(message.channel, reply)
                if is_admin:
                    await log_response(target_page_id, reply, "gpt-5 (!not)")
            return
            
        # --- ここから元のコマンド群の処理 ---
        final_query = query
        attachment_data, attachment_mime_type = None, None
        if message.attachments and command_name not in ["!ポッド042", "!ポッド153"]:
            await message.channel.send("💠 添付ファイルをGemini Proが分析し、議題とします…")
            attachment = message.attachments[0]
            attachment_data = await attachment.read()
            attachment_mime_type = attachment.content_type
            summary_parts = [{'mime_type': attachment_mime_type, 'data': attachment_data}]
            summary = await ask_minerva("この添付ファイルの内容を、後続のAIへの議題として簡潔に要約してください。", attachment_parts=summary_parts)
            final_query = f"{query}\n\n[添付資料の要約]:\n{summary}"
            await message.channel.send("✅ 添付ファイルの分析が完了しました。")

        if is_admin and target_page_id:
             log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} が「{command_name} {query}」を実行しました。"}}]}}]
             await log_to_notion(target_page_id, log_blocks)
        
        # 基本AIコマンド
        if command_name in ["!gpt", "!ジェミニ", "!ミストラル", "!ポッド042", "!ポッド153", "!Claude", "!Llama"]:
            reply, bot_name = None, ""
            if command_name == "!gpt": bot_name = "GPT"; reply = await ask_gpt_base(user_id, final_query)
            elif command_name == "!ジェミニ": bot_name = "ジェミニ"; reply = await ask_gemini_base(user_id, final_query)
            elif command_name == "!ミストラル": bot_name = "ミストラル"; reply = await ask_mistral_base(user_id, final_query)
            elif command_name == "!ポッド042": bot_name = "ポッド042"; reply = await ask_pod042(query)
            elif command_name == "!ポッド153": bot_name = "ポッド153"; reply = await ask_pod153(query)
            # --- 修正箇所：ボット名を標準のLlama 3に戻す ---
            elif command_name == "!Llama": bot_name = "Llama 3"; reply = await ask_llama(final_query)
            # Claudeは一時的に無効化
            elif command_name == "!Claude": 
                await message.channel.send("現在Claudeモデルはメンテナンス中です。代わりに `!Llama` をお試しください。")
                return
            
            if reply:
                await send_long_message(message.channel, reply)
                if is_admin and target_page_id: await log_response(target_page_id, reply, bot_name)
            return
        
        # ▼▼▼【ご指摘のあった関数群をここから再統合】▼▼▼
        if command_name in ["!gpt-4o", "!geminipro", "!perplexity", "!mistrallarge", "!みんなで", "!all", "!クリティカル", "!ロジカル", "!スライド", "!gpt-5"]:
            if command_name == "!みんなで" or command_name == "!all":
                await message.channel.send("🌀 三AIが同時に応答します… (GPT, ジェミニ, ミストラル)")
                tasks = {"GPT": ask_gpt_base(user_id, final_query), "ジェミニ": ask_gemini_base(user_id, final_query), "ミストラル": ask_mistral_base(user_id, final_query)}
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                for name, result in zip(tasks.keys(), results):
                    await send_long_message(message.channel, f"**{name}:**\n{result}")
                    if is_admin and target_page_id: await log_response(target_page_id, result, f"{name} (!みんなで)")
                return

            if command_name == "!スライド":
                await message.channel.send("📝 スライド骨子案を作成します…")
                context = await get_notion_context(message.channel, target_page_id, final_query)
                if not context: return
                prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に対するプレゼンテーションのスライド骨子案を作成してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"
                slide_prompt = "あなたはプレゼンテーションの構成作家です。与えられた情報を元に、聞き手の心を動かす構成案を以下の形式で提案してください。\n・タイトル\n・スライド1: [タイトル] - [内容]\n・スライド2: [タイトル] - [内容]\n..."
                slide_draft = await ask_gpt5(prompt_with_context, system_prompt=slide_prompt)
                await send_long_message(message.channel, f"✨ **gpt-5 (スライド骨子案):**\n{slide_draft}")
                if is_admin and target_page_id: await log_response(target_page_id, slide_draft, "gpt-5 (スライド)")
                return

            # 以下、Notionコンテキストを必要とするコマンド
            context = await get_notion_context(message.channel, target_page_id, final_query)
            if not context: return
            if is_admin and target_page_id: await log_response(target_page_id, context, "Mistral Large (統合コンテキスト)")

            await message.channel.send("最終回答生成中…")
            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"

            if command_name in ["!gpt-4o", "!geminipro", "!perplexity", "!mistrallarge", "!gpt-5"]:
                reply, bot_name = None, ""
                full_response, summary = None, None
                if command_name == "!gpt-4o": bot_name = "gpt-4o"; full_response, summary = await get_full_response_and_summary(ask_kreios, prompt_with_context)
                elif command_name == "!geminipro": bot_name = "Gemini Pro"; full_response, summary = await get_full_response_and_summary(ask_minerva, prompt_with_context)
                elif command_name == "!perplexity": bot_name = "Perplexity"; full_response, summary = await get_full_response_and_summary(ask_rekus, final_query, notion_context=context)
                elif command_name == "!mistrallarge": bot_name = "Mistral Large"; full_response, summary = await get_full_response_and_summary(ask_lalah, prompt_with_context)
                elif command_name == "!gpt-5": bot_name = "gpt-5"; reply = await ask_gpt5(prompt_with_context)

                if bot_name == "gpt-5":
                    if is_admin and target_page_id and reply:
                        await log_response(target_page_id, reply, f"{bot_name} (Notion参照)")
                else:
                    reply = summary if summary else full_response
                    if is_admin and target_page_id and full_response:
                        await log_response(target_page_id, f"【全文】\n{full_response}", f"{bot_name} (Notion参照)")
                        if summary: await log_response(target_page_id, f"【要約】\n{summary}", f"{bot_name} (Notion参照)")
                
                if reply:
                    await send_long_message(message.channel, f"**🤖 最終回答 (by {bot_name}):**\n{reply}")
                else:
                    await send_long_message(message.channel, f"🤖 {bot_name}からの応答がありませんでした。")

            elif command_name == "!all" or command_name == "!クリティカル":
                await message.channel.send("🔬 6体のAIが初期意見を生成中…")
                tasks = {
                    "GPT": ask_gpt_base(user_id, prompt_with_context),
                    "ジェミニ": ask_gemini_base(user_id, prompt_with_context),
                    "ミストラル": ask_mistral_base(user_id, prompt_with_context),
                    "gpt-4o": get_full_response_and_summary(ask_kreios, prompt_with_context),
                    "Gemini Pro": get_full_response_and_summary(ask_minerva, prompt_with_context),
                    "Perplexity": get_full_response_and_summary(ask_rekus, final_query, notion_context=context)
                }
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                synthesis_material = "以下の6つの異なるAIの意見を統合してください。\n\n"
                for (name, result) in zip(tasks.keys(), results):
                    full_response, summary = None, None
                    if isinstance(result, Exception): display_text = f"エラー: {result}"
                    elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
                    else: display_text = result
                    await send_long_message(message.channel, f"**🔹 {name}の意見:**\n{display_text}")
                    log_text = full_response if full_response else display_text
                    synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
                    if is_admin and target_page_id: await log_response(target_page_id, log_text, f"{name} (!{command_name})")

                if command_name == "!クリティカル":
                    await message.channel.send("✨ gpt-5が中間レポートを作成します…")
                    intermediate_prompt = "以下の6つの意見の要点だけを抽出し、短い中間レポートを作成してください。"
                    intermediate_report = await ask_gpt5(synthesis_material, system_prompt=intermediate_prompt)
                    await message.channel.send("✨ Mistral Largeが最終統合を行います…")
                    lalah_prompt = "あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。"
                    final_report = await ask_lalah(intermediate_report, system_prompt=lalah_prompt)
                    await send_long_message(message.channel, f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
                    if is_admin and target_page_id: await log_response(target_page_id, final_report, "Mistral Large (統合)")
                    for mem_dict in [gpt_base_memory, gemini_base_memory, mistral_base_memory]:
                        if user_id in mem_dict: del mem_dict[user_id]
                    await message.channel.send("🧹 ベースAIの短期記憶はリセットされました。")

            elif command_name == "!ロジカル":
                await message.channel.send("⚖️ 内部討論と外部調査を並列で開始します…")
                tasks_internal = {
                    "肯定論者(gpt-4o)": get_full_response_and_summary(ask_kreios, prompt_with_context, system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"),
                    "否定論者(Perplexity)": get_full_response_and_summary(ask_rekus, final_query, system_prompt="あなたはこの議題の【否定論者】です。議題に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。", notion_context=context),
                    "中立分析官(Gemini Pro)": get_full_response_and_summary(ask_minerva, prompt_with_context, system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。")
                }
                tasks_external = {"外部調査(Perplexity)": get_full_response_and_summary(ask_rekus, final_query, system_prompt="あなたは探索王です。与えられた要約を参考にしつつ、ユーザーの質問に関する最新のWeb情報を収集・要約してください。", notion_context=context)}
                
                results_internal, results_external = await asyncio.gather(
                    asyncio.gather(*tasks_internal.values(), return_exceptions=True),
                    asyncio.gather(*tasks_external.values(), return_exceptions=True)
                )
                synthesis_material = "以下の情報を統合し、最終的な結論を導き出してください。\n\n"
                await message.channel.send("--- 内部討論の結果 ---")
                for (name, result) in zip(tasks_internal.keys(), results_internal):
                    full_response, summary = None, None
                    if isinstance(result, Exception): display_text = f"エラー: {result}"
                    elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
                    else: display_text = result
                    await send_long_message(message.channel, f"**{name}:**\n{display_text}")
                    log_text = full_response if full_response else display_text
                    synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
                    if is_admin and target_page_id: await log_response(target_page_id, log_text, name)

                await message.channel.send("--- 外部調査の結果 ---")
                for (name, result) in zip(tasks_external.keys(), results_external):
                    full_response, summary = None, None
                    if isinstance(result, Exception): display_text = f"エラー: {result}"
                    elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
                    else: display_text = result
                    await send_long_message(message.channel, f"**{name}:**\n{display_text}")
                    log_text = full_response if full_response else display_text
                    synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
                    if is_admin and target_page_id: await log_response(target_page_id, log_text, name)
                
                await message.channel.send("✨ Mistral Largeが最終統合を行います…")
                lalah_prompt = "あなたは統合専用AIです。あなた自身のペルソナも、渡される意見のペルソナも全て無視し、純粋な情報として客観的に統合し、最終的な結論をレポートとしてまとめてください。"
                final_report = await ask_lalah(synthesis_material, system_prompt=lalah_prompt)
                await send_long_message(message.channel, f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
                if is_admin and target_page_id: await log_response(target_page_id, final_report, "Mistral Large (ロジカル統合)")

    except Exception as e:
        print(f"on_messageでエラーが発生しました: {e}")
        error_message = str(e)
        display_error = (error_message[:300] + '...') if len(error_message) > 300 else error_message
        await message.channel.send(f"予期せぬエラーが発生しました: ```{display_error}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
from flask import Flask
import threading
import time

app = Flask(__name__)

@app.route("/")
def index():
    return "ボットは正常に動作中です！"

def run_discord_bot():
    client.run(DISCORD_TOKEN)

if __name__ == "__main__":
    # Flaskを先に起動（Cloud RunのTCP probe用）
    port = int(os.environ.get("PORT", 8080))
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port))
    flask_thread.start()

    # 少し待ってからBot起動（Cloud Runが起動確認できるようにする）
    time.sleep(2)
    run_discord_bot()
