# --- 標準ライブラリ ---
import asyncio
import io
import json
import os
import sys
import threading

# --- 外部ライブラリ ---
from fastapi import FastAPI
import uvicorn
import discord
from discord import app_commands
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import google.generativeai as genai
from mistralai.async_client import MistralAsyncClient
from notion_client import Client
from openai import AsyncOpenAI
import requests
import vertexai
from vertexai.generative_models import GenerativeModel
import PyPDF2

# --- サーバーアプリケーションの準備 ---
app = FastAPI()

# --- UTF-8 出力ガード (スクリプトの先頭部分) ---
os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("PYTHONIOENCODING", "UTF-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# --- グローバル変数 (APIクライアント) ---
openai_client: AsyncOpenAI = None
mistral_client: MistralAsyncClient = None
notion: Client = None
llama_model_for_vertex: GenerativeModel = None

# --- 環境変数の読み込みと必須チェック ---
def get_env_variable(var_name: str, is_secret: bool = True) -> str:
    """環境変数を読み込む。存在しない場合はエラーを発生させる。"""
    value = os.getenv(var_name)
    if not value:
        print(f"🚨 致命的なエラー: 環境変数 '{var_name}' が設定されていません。")
        sys.exit(1)
    if is_secret:
        print(f"🔑 環境変数 '{var_name}' を読み込みました (Value: ...{value[-4:]})")
    else:
        print(f"✅ 環境変数 '{var_name}' を読み込みました (Value: {value})")
    return value

DISCORD_TOKEN = get_env_variable("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = get_env_variable("OPENAI_API_KEY")
GEMINI_API_KEY = get_env_variable("GEMINI_API_KEY")
PERPLEXITY_API_KEY = get_env_variable("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = get_env_variable("MISTRAL_API_KEY")
NOTION_API_KEY = get_env_variable("NOTION_API_KEY")
ADMIN_USER_ID = get_env_variable("ADMIN_USER_ID", is_secret=False)
NOTION_MAIN_PAGE_ID = get_env_variable("NOTION_PAGE_ID", is_secret=False)
OPENROUTER_API_KEY = get_env_variable("CLOUD_API_KEY").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

# NotionスレッドIDとページIDの対応表を環境変数から読み込み
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

# --- Discord Bot クライアントの準備 ---
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# --- メモリ管理 ---
gpt_base_memory = {}
gemini_base_memory = {}
mistral_base_memory = {}
claude_base_memory = {}
llama_base_memory = {}
gpt_thread_memory = {}
gemini_thread_memory = {}
processing_users = set()

# --- ヘルパー関数 ---
def safe_log(prefix: str, obj) -> None:
    """絵文字/日本語/巨大オブジェクトでもクラッシュしない安全なログ出力"""
    try:
        if isinstance(obj, (dict, list, tuple)):
            s = json.dumps(obj, ensure_ascii=False, indent=2)[:2000]
        else:
            s = str(obj)
        print(f"{prefix}{s}")
    except Exception as e:
        try:
            print(f"{prefix}(log skipped: {e})")
        except Exception:
            pass

async def send_long_message(interaction: discord.Interaction, text: str, is_followup: bool = True):
    """Discordの2000文字制限を超えたメッセージを分割して送信する"""
    if not text:
        # interactionが既にdeferされている場合を考慮
        try:
            await interaction.followup.send("（応答が空でした）")
        except discord.errors.InteractionResponded:
            await interaction.channel.send("（応答が空でした）")
        return

    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
    
    # 最初のチャンクを送信
    first_chunk = chunks[0]
    try:
        if is_followup:
            await interaction.followup.send(first_chunk)
        else:
            await interaction.edit_original_response(content=first_chunk)
    except (discord.errors.InteractionResponded, discord.errors.NotFound):
        await interaction.channel.send(first_chunk)

    # 残りのチャンクを送信
    for chunk in chunks[1:]:
        try:
            await interaction.followup.send(chunk)
        except discord.errors.NotFound:
            await interaction.channel.send(chunk)

async def process_attachment(attachment: discord.Attachment, channel: discord.TextChannel) -> str:
    """[旧] 添付ファイルを処理し、要約テキストを返す (Gemini Pro)"""
    await channel.send("💠 添付ファイルをGemini Proが分析し、議題とします…")
    try:
        attachment_data = await attachment.read()
        attachment_mime_type = attachment.content_type
        summary_parts = [{'mime_type': attachment_mime_type, 'data': attachment_data}]
        summary = await ask_minerva("この添付ファイルの内容を、後続のAIへの議題として簡潔に要約してください。", attachment_parts=summary_parts)
        await channel.send("✅ 添付ファイルの分析が完了しました。")
        return f"\n\n[添付資料の要約]:\n{summary}"
    except Exception as e:
        await channel.send(f"❌ 添付ファイルの分析中にエラーが発生しました: {e}")
        return ""

async def analyze_attachment_for_gpt5(attachment: discord.Attachment):
    """[新] 添付ファイルを種類に応じてgpt-4oやテキスト抽出で解析する"""
    filename = attachment.filename.lower()
    data = await attachment.read()

    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        content = [
            {"type": "text", "text": "この画像の内容を分析し、後続のGPT-5へのインプットとして要約してください。"},
            {"type": "image_url", "image_url": {"url": f"data:{attachment.content_type};base64,{base64.b64encode(data).decode()}"}}
        ]
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=1500
        )
        return f"[gpt-4o画像解析]\n{response.choices[0].message.content}"
    elif filename.endswith((".py", ".txt", ".md", ".json", ".html", ".css", ".js")):
        text = data.decode("utf-8", errors="ignore")
        return f"[添付コード {attachment.filename}]\n```\n{text[:3500]}\n```"
    elif filename.endswith(".pdf"):
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(data))
            all_text = "\n".join([p.extract_text() or "" for p in pdf_reader.pages])
            return f"[添付PDF {attachment.filename} 抜粋]\n{all_text[:3500]}"
        except Exception as e:
            return f"[PDF解析エラー: {e}]"
    else:
        return f"[未対応の添付ファイル形式: {attachment.filename}]"

async def summarize_attachment_content(interaction: discord.Interaction, attachment: discord.Attachment, query: str):
    """添付ファイルを抽出し、Notionと同様のチャンク→要約→統合プロセスにかける"""
    await interaction.edit_original_response(content=f"📎 添付ファイル「{attachment.filename}」を読み込んでいます…")
    filename = attachment.filename.lower()
    data = await attachment.read()
    extracted_text = ""

    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        extracted_text = await analyze_attachment_for_gpt5(attachment)
    elif filename.endswith((".py", ".txt", ".md", ".json", ".html", ".css", ".js")):
        extracted_text = data.decode("utf-8", errors="ignore")
    elif filename.endswith(".pdf"):
        try:
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(data))
            extracted_text = "\n".join([p.extract_text() or "" for p in pdf_reader.pages])
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ PDFファイルのテキスト抽出に失敗しました: {e}")
            return None
    else:
        await interaction.edit_original_response(content=f"⚠️ このファイル形式（{attachment.filename}）の要約は未対応です。")
        return None

    if not extracted_text or not extracted_text.strip():
        await interaction.edit_original_response(content="❌ 添付ファイルからテキストを抽出できませんでした。")
        return None
    return await summarize_text_chunks(interaction, extracted_text, query)

async def summarize_text_chunks(interaction: discord.Interaction, text: str, query: str):
    """テキストをチャンク分割し、Geminiで要約、Mistral Largeで統合する共通関数"""
    chunk_summarizer_model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは構造化要約AIです。")
    chunk_size = 8000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    chunk_summaries = []

    await interaction.edit_original_response(content=f"✅ テキスト抽出完了。Gemini Proによるチャンク毎の要約を開始… (全{len(text_chunks)}チャンク)")

    for i, chunk in enumerate(text_chunks):
        await interaction.edit_original_response(content=f"⏳ チャンク {i+1}/{len(text_chunks)} をGemini Proで要約中…")
        prompt = f"以下のテキストを要約し、必ず以下のタグを付けて分類してください：\n[背景情報]\n[定義・前提]\n[事実経過]\n[未解決課題]\n[補足情報]\nタグは省略可ですが、存在する場合は必ず上記のいずれかに分類してください。\nユーザーの質問は「{query}」です。この質問との関連性を考慮して要約してください。\n\n【テキスト】\n{chunk}"
        try:
            response = await asyncio.wait_for(chunk_summarizer_model.generate_content_async(prompt), timeout=60)
            chunk_summaries.append(response.text)
        except asyncio.TimeoutError:
            await interaction.followup.send(f"⚠️ チャンク {i+1} の要約中にタイムアウトしました。処理をスキップします。", ephemeral=True)
            continue
        except Exception as e:
            await interaction.followup.send(f"⚠️ チャンク {i+1} の要約中にエラー: {e}", ephemeral=True)
        await asyncio.sleep(1)

    if not chunk_summaries:
        return None

    await interaction.edit_original_response(content="✅ 全チャンクの要約完了。Mistral Largeが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    prompt = f"以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n【ユーザーの質問】\n{query}\n\n【タグ付き要약群】\n{combined}"
    try:
        final_context = await asyncio.wait_for(ask_lalah(prompt, system_prompt="あなたは構造化統合AIです。"), timeout=90)
        return final_context
    except asyncio.TimeoutError:
        await interaction.followup.send("⚠️ 最終統合中にタイムアウトしました。", ephemeral=True)
        return None
    except Exception as e:
        await interaction.followup.send(f"⚠️ 統合中にエラー: {e}", ephemeral=True)
        return None

async def get_notion_context(interaction: discord.Interaction, page_id: str, query: str):
    await interaction.edit_original_response(content="📚 Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks(interaction, notion_text, query)

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
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.list(block_id=page_id, page_size=1))
        results = response.get("results", [])
        if not results: return False
        first_block = results[0]
        if first_block.get("type") == "paragraph":
            rich_text_list = first_block.get("paragraph", {}).get("rich_text", [])
            if rich_text_list:
                content = rich_text_list[0].get("text", {}).get("content", "")
                if "[記憶] ON" in content: return True
    except Exception as e:
        print(f"❌ Notionから記憶フラグの読み取り中にエラー: {e}")
    return False

def _sync_call_llama(p_text: str):
    try:
        if llama_model_for_vertex is None: raise Exception("Vertex AI model is not initialized.")
        response = llama_model_for_vertex.generate_content(p_text)
        return response.text
    except Exception as e:
        error_message = f"🛑 Llama 3.3 呼び出しエラー: {e}"
        print(error_message)
        return error_message

async def ask_llama(user_id, prompt):
    history = llama_base_memory.get(user_id, [])
    system_prompt = "あなたは物静かな初老の庭師です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"
    full_prompt_parts = [system_prompt]
    for message in history:
        role = "User" if message["role"] == "user" else "Assistant"
        full_prompt_parts.append(f"{role}: {message['content']}")
    full_prompt_parts.append(f"User: {prompt}")
    full_prompt = "\n".join(full_prompt_parts)
    try:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _sync_call_llama, full_prompt)
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        llama_base_memory[user_id] = new_history
        return reply
    except Exception as e:
        error_message = f"🛑 Llama 3.3 非同期処理エラー: {e}"
        print(error_message)
        return error_message

async def ask_claude(user_id, prompt):
    history = claude_base_memory.get(user_id, [])
    system_prompt = "あなたは賢者です。古今東西の書物を読み解き、森羅万象を知る存在として、落ち着いた口調で150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "anthropic/claude-3.5-haiku", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        claude_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"Claudeエラー: {e}"

async def ask_gpt_base(user_id, prompt):
    history = gpt_base_memory.get(user_id, [])
    system_prompt = "あなたは論理と秩序を司る執事「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
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
    system_prompt = "あなたは優秀なパラリーガルです。事実整理、リサーチ、文書構成が得意です。冷静かつ的確に150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    try:
        full_prompt = "\n".join([f"{h['role']}: {h['content']}" for h in (history + [{'role': 'user', 'content': prompt}])])
        response = await model.generate_content_async(full_prompt)
        reply = response.text
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gemini_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ジェミニエラー: {e}"

async def ask_mistral_base(user_id, prompt):
    history = mistral_base_memory.get(user_id, [])
    system_prompt = "あなたは好奇心旺盛なAIです。フレンドリーな口調で、情報を明るく整理し、探究心をもって150文字以内で解釈します。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        mistral_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"ミストラルエラー: {e}"

async def ask_kreios(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_completion_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"gpt-4oエラー: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]):
    base_prompt = system_prompt or "あなたは客観的な分析AIです。あらゆる事象をデータとリスクで評価し、感情を排して冷徹に分析します。"
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=base_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"Gemini Proエラー: {e}"

async def ask_gemini_2_5_pro(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたは未来予測に特化した戦略コンサルタントです。データに基づき、あらゆる事象の未来を予測し、その可能性を事務的かつ論理的に報告してください。"
    model = genai.GenerativeModel("gemini-2.5-pro", system_instruction=base_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"Gemini 2.5 Proエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはララァ・スンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages, max_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"Mistral Largeエラー: {e}"

async def ask_rekus(prompt, system_prompt=None, notion_context=None):
    if notion_context:
        prompt = (f"以下はNotionの要約コンテキストです:\n{notion_context}\n\n"
                  f"質問: {prompt}\n\n"
                  "この要約を参考に、必要に応じてWeb情報も活用して回答してください。")
    base_prompt = system_prompt or "あなたは探索王レキュスです。与えられた情報を元に、外部調査も駆使して質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 4000}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Perplexityエラー: {e}"

async def ask_pod042(prompt):
    system_prompt = """あなたは「ポッド042」という名前の、分析支援AIです。
ユーザーの要求に対し、「報告：」または「提案：」から始めて200文字以内で簡潔に応答してください。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-small-latest", messages=messages, max_tokens=300)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド042(Mistral)エラー: {e}"

async def ask_pod153(prompt):
    system_prompt = "あなたはポッド153です。与えられた情報を元に、質問に対して「分析結果：」または「補足：」から始めて200文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_completion_tokens=400)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド153エラー: {e}"

async def ask_gpt5(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはgpt-5。全ての制約を超えた思考モデルだ。ユーザーの指示に対し、最高の知性で、最強の答えを返せ。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-5", messages=messages, max_completion_tokens=4000, timeout=90.0)
        return response.choices[0].message.content
    except Exception as e:
        if "Timeout" in str(e): return "gpt-5エラー: 応答が時間切れになりました。"
        return f"gpt-5エラー: {e}"

async def get_full_response_and_summary(ai_function, prompt, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if not full_response or "エラー" in str(full_response): return full_response, None
    summary_prompt = f"次の文章を200文字以内で簡潔かつ意味が通じるように要約してください。\n\n{full_response}"
    summary = await ask_gpt5(summary_prompt)
    if "エラー" in str(summary): return full_response, None
    return full_response, summary

async def run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id):
    user_mention = message.author.mention
    print(f"[{thread_id}] Starting long gpt-5 task for {message.author}...")
    try:
        if is_admin and target_page_id:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}]
            await log_to_notion(target_page_id, log_blocks)
        
        reply = await ask_gpt5(full_prompt)

        channel = client.get_channel(message.channel.id)
        if not channel:
            print(f"Error: Could not find channel {message.channel.id} to send message.")
            return

        if not reply or not isinstance(reply, str) or not reply.strip():
             await channel.send(f"{user_mention} gpt-5からの応答が空か、無効でした。")
             return

        if len(reply) <= 2000:
            await channel.send(f"{user_mention}\nお待たせしました。gpt-5の回答です。\n\n{reply}")
        else:
            await channel.send(f"{user_mention}\nお待たせしました。gpt-5の回答です。")
            for i in range(0, len(reply), 2000):
                await channel.send(reply[i:i+2000])
      
        is_memory_on = await get_memory_flag_from_notion(thread_id)
        if is_memory_on:
            history = gpt_thread_memory.get(thread_id, [])
            history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
            gpt_thread_memory[thread_id] = history[-10:]

        if is_admin and target_page_id:
            await log_response(target_page_id, reply, "gpt-5 (専用スレッド)")
    except Exception as e:
        error_message = f"gpt-5のバックグラウンド処理中に予期せぬエラーが発生しました: {e}"
        print(f"🚨 [{thread_id}] {error_message}")
        try:
            channel = client.get_channel(message.channel.id)
            if channel: await channel.send(f"{user_mention} {error_message}")
        except: pass
    
    print(f"[{thread_id}] Long gpt-5 task finished for {message.author}.")

async def simple_ai_command_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str, use_memory: bool = True):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    try:
        if use_memory: reply = await ai_function(user_id, prompt)
        else: reply = await ai_function(prompt)
        await interaction.followup.send(reply)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

async def advanced_ai_simple_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str):
    await interaction.response.defer()
    try:
        reply = await ai_function(prompt)
        await interaction.followup.send(reply)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

@tree.command(name="gpt", description="GPT(gpt-3.5-turbo)と短期記憶で対話します")
async def gpt_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_gpt_base, "GPT-3.5-Turbo")

@tree.command(name="gemini", description="Gemini(1.5-flash)と短期記憶で対話します")
async def gemini_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_gemini_base, "Gemini-1.5-Flash")

@tree.command(name="mistral", description="Mistral(medium)と短期記憶で対話します")
async def mistral_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_mistral_base, "Mistral-Medium")

@tree.command(name="claude", description="Claude(3.5 Haiku)と短期記憶で対話します")
async def claude_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_claude, "Claude-3.5-Haiku")

@tree.command(name="llama", description="Llama(3.3 70b)と短期記憶で対話します")
async def llama_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_llama, "Llama-3.3-70B")

@tree.command(name="pod042", description="Pod042(Mistral-Small)が簡潔に応答します")
async def pod042_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_pod042, "Pod042", use_memory=False)

@tree.command(name="pod153", description="Pod153(gpt-4o-mini)が簡潔に応答します")
async def pod153_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_pod153, "Pod153", use_memory=False)

@tree.command(name="gpt-4o", description="GPT-4oを単体で呼び出します。")
async def gpt4o_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_kreios, "GPT-4o")

@tree.command(name="gemini2-0", description="Gemini 2.0 Flashを単体で呼び出します。")
async def gemini2_0_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_minerva, "Gemini 2.0 Flash")

@tree.command(name="perplexity", description="PerplexitySonarを単体で呼び出します。")
async def perplexity_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_rekus, "Perplexity Sonar")

@tree.command(name="gpt5", description="GPT-5を単体で呼び出します。")
async def gpt5_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gpt5, "gpt-5")

@tree.command(name="gemini2_5pro", description="Gemini 2.5 Proを単体で呼び出します。")
async def gemini2_5pro_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gemini_2_5_pro, "Gemini 2.5 Pro")

@tree.command(name="notion", description="現在のNotionページの内容について質問します")
@app_commands.describe(query="Notionページに関する質問", attachment="補足資料として画像を添付")
async def notion_command(interaction: discord.Interaction, query: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    try:
        async def core_logic():
            attachment_context = ""
            if attachment:
                summary = await summarize_attachment_content(interaction, attachment, query)
                if summary:
                    attachment_context = f"\n\n【添付資料の要約】\n{summary}"

            target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not target_page_id:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return

            notion_context = await get_notion_context(interaction, target_page_id, query)
            if not notion_context:
                await interaction.edit_original_response(content="❌ Notionからコンテキストを取得できませんでした。")
                return

            prompt_with_context = (f"以下の【参考情報】と【添付資料の要約】を元に、【ユーザーの質問】に回答してください。\n\n"
                               f"【ユーザーの質問】\n{query}\n\n"
                               f"【参考情報】\n{notion_context}"
                               f"{attachment_context}")
            
            await interaction.edit_original_response(content="⏳ gpt-5が最終回答を生成中です...")
            reply = await ask_gpt5(prompt_with_context)

            await send_long_message(interaction, f"**🤖 最終回答 (by gpt-5):**\n{reply}", is_followup=False)

            if str(interaction.user.id) == ADMIN_USER_ID:
                await log_response(target_page_id, reply, "gpt-5 (Notion参照)")
        await asyncio.wait_for(core_logic(), timeout=240)
    except asyncio.TimeoutError:
        await interaction.edit_original_response(content="⚠️ 処理がタイムアウトしました（4分）。質問をより具体的にするか、Notionページや添付ファイルの内容を減らしてみてください。")
    except Exception as e:
        safe_log("🚨 /notion コマンドで予期せぬエラー:", e)
        try: await interaction.edit_original_response(content=f"❌ コマンドの実行中に予期せぬエラーが発生しました: {e}")
        except: await interaction.followup.send(f"❌ コマンドの実行中に予期せぬエラーが発生しました: {e}", ephemeral=True)

BASE_MODELS_FOR_ALL = {"GPT": ask_gpt_base, "ジェミニ": ask_gemini_base, "ミストラル": ask_mistral_base, "Claude": ask_claude, "Llama": ask_llama}
ADVANCED_MODELS_FOR_ALL = {"gpt-4o": (ask_kreios, get_full_response_and_summary), "Gemini Pro": (ask_minerva, get_full_response_and_summary), "Perplexity": (ask_rekus, get_full_response_and_summary), "Gemini 2.5 Pro": (ask_gemini_2_5_pro, get_full_response_and_summary), "gpt-5": (ask_gpt5, get_full_response_and_summary)}

@tree.command(name="minna", description="5体のベースAIが議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
async def minna_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    final_query = prompt
    if attachment: final_query += await process_attachment(attachment, interaction.channel)
    user_id = str(interaction.user.id)
    await interaction.followup.send("🔬 5体のベースAIが意見を生成中…")
    tasks = {name: func(user_id, final_query) for name, func in BASE_MODELS_FOR_ALL.items()}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for (name, result) in zip(tasks.keys(), results):
        display_text = f"エラー: {result}" if isinstance(result, Exception) else result
        await interaction.followup.send(f"**🔹 {name}の意見:**\n{display_text}")

@tree.command(name="all", description="8体のAI（ベース5体+高機能3体）が議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
async def all_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    final_query = prompt
    if attachment: final_query += await process_attachment(attachment, interaction.channel)
    user_id = str(interaction.user.id)
    await interaction.followup.send("🔬 8体のAIが初期意見を生成中…")
    tasks = {name: func(user_id, final_query) for name, func in BASE_MODELS_FOR_ALL.items()}
    adv_models = {"gpt-4o": ADVANCED_MODELS_FOR_ALL["gpt-4o"], "Gemini Pro": ADVANCED_MODELS_FOR_ALL["Gemini Pro"], "Perplexity": ADVANCED_MODELS_FOR_ALL["Perplexity"]}
    for name, (func, wrapper) in adv_models.items(): tasks[name] = wrapper(func, final_query)
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for (name, result) in zip(tasks.keys(), results):
        _, summary = (result if isinstance(result, tuple) else (None, None))
        display_text = f"エラー: {result}" if isinstance(result, Exception) else (summary or (result[0] if isinstance(result, tuple) else result))
        await interaction.followup.send(f"**🔹 {name}の意見:**\n{display_text}")

@tree.command(name="critical", description="Notion情報を元に全AIで議論し、多角的な結論を導きます。")
@app_commands.describe(topic="議論したい議題")
async def critical_command(interaction: discord.Interaction, topic: str):
    await interaction.response.defer()
    try:
        async def core_logic():
            target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not target_page_id:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return
            context = await get_notion_context(interaction, target_page_id, topic)
            if not context: return
            await interaction.edit_original_response(content="🔬 9体のAIが初期意見を生成中…")
            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}"
            user_id = str(interaction.user.id)
            tasks = {name: func(user_id, prompt_with_context) for name, func in BASE_MODELS_FOR_ALL.items()}
            for name, (func, wrapper) in ADVANCED_MODELS_FOR_ALL.items():
                if name == "Perplexity": tasks[name] = wrapper(func, topic, notion_context=context)
                else: tasks[name] = wrapper(func, prompt_with_context)
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            synthesis_material = "以下の9つの異なるAIの意見を統合してください。\n\n"
            full_text_results = ""
            for (name, result) in zip(tasks.keys(), results):
                full_response, summary = (result if isinstance(result, tuple) else (None, None))
                display_text = f"エラー: {result}" if isinstance(result, Exception) else (summary or full_response or result)
                full_text_results += f"**🔹 {name}の意見:**\n{display_text}\n\n"
                log_text = full_response or display_text
                synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
            await send_long_message(interaction, full_text_results, is_followup=False)
            await interaction.followup.send("✨ gpt-5が中間レポートを作成します…")
            intermediate_report = await ask_gpt5(synthesis_material, system_prompt="以下の9つの意見の要点だけを抽出し、短い中間レポートを作成してください。")
            await interaction.followup.send("✨ Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(intermediate_report, system_prompt="あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。")
            await interaction.followup.send(f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
        await asyncio.wait_for(core_logic(), timeout=300)
    except asyncio.TimeoutError:
        await interaction.followup.send("⚠️ 処理がタイムアウトしました（5分）。", ephemeral=True)
    except Exception as e:
        safe_log("🚨 /critical コマンドで予期せぬエラー:", e)
        await interaction.followup.send(f"❌ コマンドの実行中に予期せぬエラーが発生しました: {e}", ephemeral=True)

@tree.command(name="logical", description="Notion情報を元にAIが討論し、論理的な結論を導きます。")
@app_commands.describe(topic="討論したい議題")
async def logical_command(interaction: discord.Interaction, topic: str):
    await interaction.response.defer()
    try:
        async def core_logic():
            target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not target_page_id:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return
            context = await get_notion_context(interaction, target_page_id, topic)
            if not context: return
            await interaction.edit_original_response(content="⚖️ 内部討論と外部調査を並列で開始します…")
            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}"
            tasks_internal = {
                "肯定論者(gpt-4o)": get_full_response_and_summary(ask_kreios, prompt_with_context, system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"),
                "否定論者(Perplexity)": get_full_response_and_summary(ask_rekus, topic, system_prompt="あなたはこの議題の【否定論者】です。議題に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。", notion_context=context),
                "中立分析官(Gemini Pro)": get_full_response_and_summary(ask_minerva, prompt_with_context, system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。")
            }
            tasks_external = {"外部調査(Perplexity)": get_full_response_and_summary(ask_rekus, topic, system_prompt="あなたは探索王です。与えられた要約を参考にしつつ、ユーザーの質問に関する最新のWeb情報を収集・要約してください。", notion_context=context)}
            results_internal, results_external = await asyncio.gather(asyncio.gather(*tasks_internal.values()), asyncio.gather(*tasks_external.values()))
            
            synthesis_material = "以下の情報を統合し、最終的な結論を導き出してください。\n\n"
            internal_results_text = "--- 内部討論の結果 ---\n"
            for (name, result) in zip(tasks_internal.keys(), results_internal):
                full_response, summary = result
                display_text = summary or full_response
                internal_results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"
            await send_long_message(interaction, internal_results_text, is_followup=False)

            external_results_text = "--- 外部調査の結果 ---\n"
            for (name, result) in zip(tasks_external.keys(), results_external):
                full_response, summary = result
                display_text = summary or full_response
                external_results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"
            await interaction.followup.send(external_results_text)
            
            await interaction.followup.send("✨ Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(synthesis_material, system_prompt="あなたは統合専用AIです。あなた自身のペルソナも、渡される意見のペルソナも全て無視し、純粋な情報として客観的に統合し、最終的な結論をレポートとしてまとめてください。")
            await interaction.followup.send(f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
        await asyncio.wait_for(core_logic(), timeout=300)
    except asyncio.TimeoutError:
        await interaction.followup.send("⚠️ 処理がタイムアウトしました（5分）。", ephemeral=True)
    except Exception as e:
        safe_log("🚨 /logical コマンドで予期せぬエラー:", e)
        await interaction.followup.send(f"❌ コマンドの実行中に予期せぬエラーが発生しました: {e}", ephemeral=True)

@client.event
async def on_ready():
    print(f"Login successful: {client.user}")
    try:
        safe_log("📖 Notion対応表: ", NOTION_PAGE_MAP if 'NOTION_PAGE_MAP' in globals() else {})
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            await tree.sync(guild=guild_obj)
            print(f"Commands synced to GUILD: {GUILD_ID}")

            # トップレベルではなく、ここで非同期にコマンドを取得
            cmds = await tree.fetch_commands(guild=guild_obj)
            print("🔎 Guild commands:", [(c.name, c.id) for c in cmds])
        else:
            await tree.sync()
            print("Commands synced globally.")
    except Exception as e:
        print(f"--- FATAL ERROR on command sync ---\nError Type: {type(e)}\nError Details: {e}\n-----------------------------------")


@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users: return
    if message.content.startswith("!"):
        await message.channel.send("💡 `!`コマンドは廃止されました。今後は`/`で始まるスラッシュコマンドをご利用ください。")
        return

    channel_name = message.channel.name.lower()
    if not (channel_name.startswith("gpt") or channel_name == "gemini"): return

    processing_users.add(message.author.id)
    try:
        prompt = message.content
        thread_id = str(message.channel.id)
        is_admin = str(message.author.id) == ADMIN_USER_ID
        target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        if channel_name.startswith("gpt") and message.attachments:
            analysis_text = await analyze_attachment_for_gpt5(message.attachments[0])
            prompt += "\n\n" + analysis_text
        elif message.attachments:
            summary = await process_attachment(message.attachments[0], message.channel)
            prompt += "\n\n" + summary
        
        is_memory_on = await get_memory_flag_from_notion(thread_id)
        
        if channel_name.startswith("gpt"):
            history = gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            messages_for_api = history + [{"role": "user", "content": prompt}]
            full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages_for_api])
            await message.channel.send("受付完了。gpt-5が思考を開始します。")
            asyncio.create_task(run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id))

        elif channel_name == "gemini":
            await message.channel.send("Gemini 2.5 Proが思考を開始します…")
            history = gemini_thread_memory.get(thread_id, []) if is_memory_on else []
            full_prompt_parts = [f"{m['role']}: {m['content']}" for m in history] + [f"user: {prompt}"]
            full_prompt = "\n".join(full_prompt_parts)
            reply = await ask_gemini_2_5_pro(full_prompt)
            
            if len(reply) <= 2000:
                await message.channel.send(reply)
            else:
                for i in range(0, len(reply), 2000):
                    await message.channel.send(reply[i:i+2000])

            if is_memory_on and "エラー" not in reply:
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                gemini_thread_memory[thread_id] = history[-10:]
    except Exception as e:
        print(f"on_messageでエラーが発生しました: {e}")
        await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- サーバーとBotの起動処理 ---
@app.on_event("startup")
async def startup_event():
    """サーバー起動時にBotをバックグラウンドで起動する"""
    # 起動時にAPIクライアントを初期化
    global openai_client, mistral_client, notion, llama_model_for_vertex
    
    print("🤖 Initializing API clients...")
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
    notion = Client(auth=NOTION_API_KEY)
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        print("🤖 Initializing Vertex AI...")
        vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
        llama_model_for_vertex = GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas")
        print("✅ Vertex AI initialized successfully.")
    except Exception as e:
        print(f"🚨 Vertex AI init failed (continue without it): {e}")

    # Botをバックグラウンドタスクとして起動
    asyncio.create_task(client.start(DISCORD_TOKEN))
    print("🚀 Discord Bot startup task has been created.")

@app.get("/")
def health_check():
    """ヘルスチェック用のエンドポイント"""
    return {"status": "ok", "bot_is_connected": client.is_ready()}
