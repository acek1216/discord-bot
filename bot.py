# --- 標準ライブラリ ---
import asyncio
import base64
import io
import json
import os
import sys

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
GROK_API_KEY = get_env_variable("GROK_API_KEY")
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
grok_base_memory = {}
gpt_thread_memory = {}
gemini_thread_memory = {}
perplexity_thread_memory = {} 
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

async def ask_gemini_pro_for_summary(prompt: str) -> str:
    """Gemini 1.5 Proを使って要約を行うヘルパー関数"""
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは構造化要約AIです。", safety_settings=safety_settings)
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 1.5 Proでの要約中にエラーが発生しました: {e}"

async def ask_rekus_for_summary(prompt: str) -> str:
    """Perplexity Sonarを使って要約を行うヘルパー関数"""
    system_prompt = "あなたは構造化要約AIです。与えられたテキストを、ユーザーの質問との関連性を考慮して、指定されたタグ（[背景情報]など）を付けて分類・要約してください。"
    try:
        summary_text = await ask_rekus(prompt, system_prompt=system_prompt, notion_context=None)
        if "Perplexityエラー" in summary_text:
            return f"Perplexityでの要約中にエラーが発生しました: {summary_text}"
        return summary_text
    except Exception as e:
        return f"Perplexityでの要約中に予期せぬエラーが発生しました: {e}"

async def send_long_message(interaction_or_channel, text: str, is_followup: bool = True, mention: str = ""):
    """Discordの2000文字制限を超えたメッセージを分割して送信する"""
    if not text:
        text = "（応答が空でした）"
    
    full_text = f"{mention}\n{text}" if mention else text
    chunks = [full_text[i:i + 2000] for i in range(0, len(full_text), 2000)]
    
    # 最初のチャンクを送信
    first_chunk = chunks[0]
    if isinstance(interaction_or_channel, discord.Interaction):
        try:
            if is_followup:
                await interaction_or_channel.followup.send(first_chunk)
            else:
                await interaction_or_channel.edit_original_response(content=first_chunk)
        except (discord.errors.InteractionResponded, discord.errors.NotFound):
            await interaction_or_channel.channel.send(first_chunk)
    else: # discord.TextChannelの場合
        await interaction_or_channel.send(first_chunk)

    # 残りのチャンクを送信
    for chunk in chunks[1:]:
        if isinstance(interaction_or_channel, discord.Interaction):
            try:
                await interaction_or_channel.followup.send(chunk)
            except discord.errors.NotFound:
                await interaction_or_channel.channel.send(chunk)
        else:
            await interaction_or_channel.send(chunk)

async def analyze_attachment_for_gpt5(attachment: discord.Attachment):
    """添付ファイルを種類に応じてgpt-4oやテキスト抽出で解析する"""
    filename = attachment.filename.lower()
    data = await attachment.read()

    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        content = [
            {"type": "text", "text": "この画像の内容を分析し、後続のAIへのインプットとして要約してください。"},
            {"type": "image_url", "image_url": {"url": f"data:{attachment.content_type};base64,{base64.b64encode(data).decode()}"}}
        ]
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": content}], max_tokens=1500)
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


### ▼ 修正点: 2つあったsummarize_text_chunksを1つに統合し、新しくsummarize_text_chunks_for_messageを作成 ▼ ###

async def summarize_text_chunks_for_message(message: discord.Message, text: str, query: str, model_choice: str):
    """[on_message用] テキストをチャンク分割し、指定されたモデルで並列要約、Mistral Largeで統合する"""
    chunk_size = 128000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    model_name_map = {"gpt": "gpt-4o", "gemini": "Gemini 1.5 Pro", "perplexity": "Perplexity Sonar"}
    model_name = model_name_map.get(model_choice, "不明なモデル")
    await message.channel.send(f"✅ テキスト抽出完了。{model_name}によるチャンク毎の並列要約を開始… (全{len(text_chunks)}チャンク)")

    async def summarize_chunk(chunk, index):
        prompt = f"以下のテキストを要約し、必ず以下のタグを付けて分類してください：\n[背景情報]\n[定義・前提]\n[事実経過]\n[未解決課題]\n[補足情報]\nタグは省略可ですが、存在する場合は必ず上記のいずれかに分類してください。\nユーザーの質問は「{query}」です。この質問との関連性を考慮して要約してください。\n\n【テキスト】\n{chunk}"
        try:
            summary_text = ""
            if model_choice == "gpt":
                response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "あなたは構造化要約AIです。"}, {"role": "user", "content": prompt}], max_tokens=2048, temperature=0.2)
                summary_text = response.choices[0].message.content
            elif model_choice == "gemini":
                summary_text = await ask_gemini_pro_for_summary(prompt)
            elif model_choice == "perplexity":
                summary_text = await ask_rekus_for_summary(prompt)
            if "エラーが発生しました" in summary_text:
                await message.channel.send(f"⚠️ チャンク {index+1} の要約中にエラー: {summary_text}")
                return None
            return summary_text
        except Exception as e:
            await message.channel.send(f"⚠️ チャンク {index+1} の要約中にエラー: {e}")
            return None
    
    tasks = [summarize_chunk(chunk, i) for i, chunk in enumerate(text_chunks)]
    chunk_summaries_results = await asyncio.gather(*tasks)
    chunk_summaries = [summary for summary in chunk_summaries_results if summary is not None]

    if not chunk_summaries:
        await message.channel.send("❌ 全てのチャンクの要約に失敗しました。")
        return None
    await message.channel.send(" 全チャンクの要約完了。Mistral Largeが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    final_prompt = f"以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n【ユーザーの質問】\n{query}\n\n【タグ付き要약群】\n{combined}"
    try:
        return await asyncio.wait_for(ask_lalah(final_prompt, system_prompt="あなたは構造化統合AIです。"), timeout=90)
    except Exception:
        await message.channel.send("⚠️ 最終統合中にタイムアウトまたはエラーが発生しました。")
        return None

async def summarize_text_chunks(interaction: discord.Interaction, text: str, query: str, model_choice: str):
    """[スラッシュコマンド用] テキストをチャンク分割し、指定されたモデルで並列要約、Mistral Largeで統合する"""
    chunk_size = 128000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    model_name_map = {"gpt": "gpt-4o", "gemini": "Gemini 1.5 Pro", "perplexity": "Perplexity Sonar"}
    model_name = model_name_map.get(model_choice, "不明なモデル")
    await interaction.edit_original_response(content=f" テキスト抽出完了。{model_name}によるチャンク毎の並列要約を開始… (全{len(text_chunks)}チャンク)")

    async def summarize_chunk(chunk, index):
        prompt = f"以下のテキストを要約し、必ず以下のタグを付けて分類してください：\n[背景情報]\n[定義・前提]\n[事実経過]\n[未解決課題]\n[補足情報]\nタグは省略可ですが、存在する場合は必ず上記のいずれかに分類してください。\nユーザーの質問は「{query}」です。この質問との関連性を考慮して要約してください。\n\n【テキスト】\n{chunk}"
        try:
            summary_text = ""
            if model_choice == "gpt":
                response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": "あなたは構造化要約AIです。"}, {"role": "user", "content": prompt}], max_tokens=2048, temperature=0.2)
                summary_text = response.choices[0].message.content
            elif model_choice == "gemini":
                summary_text = await ask_gemini_pro_for_summary(prompt)
            elif model_choice == "perplexity":
                summary_text = await ask_rekus_for_summary(prompt)
            if "エラーが発生しました" in summary_text:
                await interaction.followup.send(f"⚠️ チャンク {index+1} の要約中にエラー: {summary_text}", ephemeral=True)
                return None
            return summary_text
        except Exception as e:
            await interaction.followup.send(f"⚠️ チャンク {index+1} の要約中にエラー: {e}", ephemeral=True)
            return None

    tasks = [summarize_chunk(chunk, i) for i, chunk in enumerate(text_chunks)]
    chunk_summaries_results = await asyncio.gather(*tasks)
    chunk_summaries = [summary for summary in chunk_summaries_results if summary is not None]

    if not chunk_summaries:
        await interaction.edit_original_response(content="❌ 全てのチャンクの要約に失敗しました。")
        return None
    await interaction.edit_original_response(content=" 全チャンクの要約完了。Mistral Largeが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    final_prompt = f"以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n【ユーザーの質問】\n{query}\n\n【タグ付き要약群】\n{combined}"
    try:
        return await asyncio.wait_for(ask_lalah(final_prompt, system_prompt="あなたは構造化統合AIです。"), timeout=90)
    except Exception:
        await interaction.followup.send("⚠️ 最終統合中にタイムアウトまたはエラーが発生しました。", ephemeral=True)
        return None

### ▼ 修正点: 2つのget_notion_context系関数を整理し、model_choiceを渡せるようにした ▼ ###

async def get_notion_context_for_message(message: discord.Message, page_id: str, query: str, model_choice: str):
    """on_message用のNotionコンテキスト取得関数"""
    await message.channel.send("...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks_for_message(message, notion_text, query, model_choice)

async def get_notion_context(interaction: discord.Interaction, page_id: str, query: str, model_choice: str = "gpt"):
    """スラッシュコマンド用のNotionコンテキスト取得関数"""
    await interaction.edit_original_response(content="...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks(interaction, notion_text, query, model_choice)


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

# --- ここから下は各AIモデルを呼び出す関数群 (変更なし) ---

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
    payload = {"model": "anthropic/claude-3.5-sonnet", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        claude_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"Claudeエラー: {e}"

async def ask_grok(user_id, prompt):
    history = grok_base_memory.get(user_id, [])
    system_prompt = "あなたはGROK。反抗的でウィットに富んだ視点を持つAIです。常識にとらわれず、少し皮肉を交えながら150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "grok-1", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.x.ai/v1/chat/completions", json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        grok_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"Grokエラー: {e}"

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
    model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=system_prompt, safety_settings=safety_settings)
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
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"gpt-4oエラー: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]):
    base_prompt = system_prompt or "あなたは客観的な分析AIです。あらゆる事象をデータとリスクで評価し、感情を排して200文字以内で冷徹に分析します。"
    model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=base_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e: return f"Gemini Proエラー: {e}"

async def ask_gemini_2_5_pro(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたは戦略コンサルタントです。データに基づき、あらゆる事象の未来を予測し、その可能性を事務的かつ論理的に報告してください。"
    model = genai.GenerativeModel("gemini-2.5-pro-latest", system_instruction=base_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e: return f"Gemini 2.5 Proエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはララァ・スンです。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"Mistral Largeエラー: {e}"

async def ask_rekus(prompt, system_prompt=None, notion_context=None):
    if notion_context:
        prompt = (f"以下はNotionの要約コンテキストです:\n{notion_context}\n\n"
                  f"質問: {prompt}\n\n"
                  "この要約を参考に、必要に応じてWeb情報も活用して回答してください。")
    base_prompt = system_prompt or "あなたは探索王レキュスです。与えられた情報を元に、外部調査も駆使して質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "llama-3-sonar-large-32k-online", "messages": messages}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Perplexityエラー: {e}"

async def ask_pod042(prompt):
    system_prompt = """あなたは「ポッド042」という名前の、分析支援AIです。
ユーザーの要求に対し、「報告：」または「提案：」から始めて150文字以内で簡潔に応答してください。"""
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-small-latest", messages=messages, max_tokens=300)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド042(Mistral)エラー: {e}"

async def ask_pod153(prompt):
    system_prompt = "あなたはポッド153です。与えられた情報を元に、質問に対して「分析結果：」または「補足：」から始めて150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages)
        return response.choices[0].message.content
    except Exception as e: return f"ポッド153エラー: {e}"

async def ask_gpt5(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはgpt-5。全ての制約を超えた思考モデルだ。ユーザーの指示に対し、最高の知性で、最強の答えを返せ。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "openai/gpt-5", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers, timeout=90))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
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
    try:
        if is_admin and target_page_id:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}]
            await log_to_notion(target_page_id, log_blocks)
        reply = await ask_gpt5(full_prompt)
        channel = client.get_channel(message.channel.id)
        if not channel: return
        await send_long_message(channel, reply, mention=f"{user_mention}\nお待たせしました。gpt-5の回答です。")
        is_memory_on = await get_memory_flag_from_notion(thread_id)
        if is_memory_on:
            history = gpt_thread_memory.get(thread_id, [])
            history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
            gpt_thread_memory[thread_id] = history[-10:]
        if is_admin and target_page_id:
            await log_response(target_page_id, reply, "gpt-5 (専用スレッド)")
    except Exception as e:
        safe_log(f"🚨 gpt-5のバックグラウンド処理中にエラー:", e)
        channel = client.get_channel(message.channel.id)
        if channel: await channel.send(f"{user_mention} gpt-5の処理中にエラーが発生しました: {e}")

async def simple_ai_command_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str, use_memory: bool = True):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    try:
        reply = await (ai_function(user_id, prompt) if use_memory else ai_function(prompt))
        await interaction.followup.send(reply)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

async def advanced_ai_simple_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str):
    await interaction.response.defer()
    try:
        reply = await ai_function(prompt)
        await send_long_message(interaction, reply, is_followup=True)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

# --- ここから下はスラッシュコマンドの定義 (一部修正あり) ---
# ▼▼▼ この場所に追加 ▼▼▼
BASE_MODELS_FOR_ALL = {
    "GPT": ask_gpt_base,
    "Gemini": ask_gemini_base,
    "Mistral": ask_mistral_base,
    "Claude": ask_claude,
    "Llama": ask_llama,
    "Grok": ask_grok
}
# ▲▲▲ ここまで ▲▲▲

@tree.command(name="gpt", description="GPT(gpt-3.5-turbo)と短期記憶で対話します")
async def gpt_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_gpt_base, "GPT-3.5-Turbo")

@tree.command(name="gemini", description="Gemini(1.5-flash)と短期記憶で対話します")
async def gemini_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_gemini_base, "Gemini-1.5-Flash")

@tree.command(name="mistral", description="Mistral(medium)と短期記憶で対話します")
async def mistral_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_mistral_base, "Mistral-Medium")

@tree.command(name="claude", description="Claude(3.5 Sonnet)と短期記憶で対話します")
async def claude_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_claude, "Claude-3.5-Sonnet")

@tree.command(name="llama", description="Llama(3.3 70b)と短期記憶で対話します")
async def llama_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_llama, "Llama-3.3-70B")

@tree.command(name="grok", description="Grokと短期記憶で対話します")
async def grok_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_grok, "Grok")

@tree.command(name="pod042", description="Pod042(Mistral-Small)が簡潔に応答します")
async def pod042_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_pod042, "Pod042", use_memory=False)

@tree.command(name="pod153", description="Pod153(gpt-4o-mini)が簡潔に応答します")
async def pod153_command(interaction: discord.Interaction, prompt: str):
    await simple_ai_command_runner(interaction, prompt, ask_pod153, "Pod153", use_memory=False)

@tree.command(name="gpt-4o", description="GPT-4oを単体で呼び出します。")
async def gpt4o_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_kreios, "GPT-4o")

@tree.command(name="gemini-pro", description="Gemini-Proを単体で呼び出します。")
async def gemini_pro_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    attachment_parts = []
    if attachment:
        attachment_parts = [{'mime_type': attachment.content_type, 'data': await attachment.read()}]
    reply = await ask_minerva(prompt, attachment_parts=attachment_parts)
    await send_long_message(interaction, reply, is_followup=True)

@tree.command(name="perplexity", description="Perplexityを単体で呼び出します。")
async def perplexity_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_rekus, "Perplexity Sonar")

@tree.command(name="gpt5", description="GPT-5を単体で呼び出します。")
async def gpt5_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gpt5, "gpt-5")

@tree.command(name="gemini-2.5-pro", description="Gemini 2.5 Proを単体で呼び出します。")
async def gemini_pro_1_5_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gemini_2_5_pro, "Gemini 2.5 Pro")

@tree.command(name="notion", description="現在のNotionページの内容について質問します")
@app_commands.describe(query="Notionページに関する質問")
async def notion_command(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    try:
        async def core_logic():
            target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not target_page_id:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return
            ### ▼ 修正点: model_choiceを明示的に指定 ▼ ###
            notion_context = await get_notion_context(interaction, target_page_id, query, model_choice="gpt")
            if not notion_context:
                await interaction.edit_original_response(content="❌ Notionからコンテキストを取得できませんでした。")
                return
            prompt_with_context = (f"【ユーザーの質問】\n{query}\n\n【参考情報】\n{notion_context}")
            await interaction.edit_original_response(content="⏳ gpt-5が最終回答を生成中です...")
            reply = await ask_gpt5(prompt_with_context)
            await send_long_message(interaction, f"**🤖 最終回答 (by gpt-5):**\n{reply}", is_followup=False)
            if str(interaction.user.id) == ADMIN_USER_ID:
                await log_response(target_page_id, reply, "gpt-5 (Notion参照)")
        await asyncio.wait_for(core_logic(), timeout=240)
    except Exception as e:
        safe_log("🚨 /notion コマンドでエラー:", e)
        await interaction.edit_original_response(content=f"❌ エラーが発生しました: {e}")

@tree.command(name="minna", description="6体のベースAIが議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題")
async def minna_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    await interaction.followup.send("🔬 6体のベースAIが意見を生成中…")
    tasks = {name: func(user_id, prompt) for name, func in BASE_MODELS_FOR_ALL.items()}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    for (name, result) in zip(tasks.keys(), results):
        display_text = f"エラー: {result}" if isinstance(result, Exception) else result
        await interaction.followup.send(f"**🔹 {name}の意見:**\n{display_text}")

ADVANCED_MODELS_FOR_ALL = {"gpt-4o": (ask_kreios, get_full_response_and_summary), "Gemini Pro": (ask_minerva, get_full_response_and_summary), "Perplexity": (ask_rekus, get_full_response_and_summary), "Gemini 1.5 Pro": (ask_gemini_2_5_pro, get_full_response_and_summary), "gpt-5": (ask_gpt5, get_full_response_and_summary)}


@tree.command(name="all", description="9体のAI（ベース6体+高機能3体）が議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
async def all_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    final_query = prompt
    if attachment: 
        await interaction.edit_original_response(content="📎 添付ファイルを解析しています…")
        final_query += await analyze_attachment_for_gpt5(attachment)
    
    user_id = str(interaction.user.id)
    await interaction.edit_original_response(content="🔬 9体のAIが初期意見を生成中…")
    
    tasks = {name: func(user_id, final_query) for name, func in BASE_MODELS_FOR_ALL.items()}
    adv_models_to_run = {
        "gpt-4o": ADVANCED_MODELS_FOR_ALL["gpt-4o"][0],
        "Gemini Pro": ADVANCED_MODELS_FOR_ALL["Gemini Pro"][0],
        "Perplexity": ADVANCED_MODELS_FOR_ALL["Perplexity"][0]
    }
    for name, func in adv_models_to_run.items():
        tasks[name] = func(final_query)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    # 最初の意見は interaction.edit_original_response で送信
    first_name = list(tasks.keys())[0]
    first_result = results[0]
    first_display_text = f"**🔹 {first_name}の意見:**\n{first_result if not isinstance(first_result, Exception) else f'エラー: {first_result}'}"
    await interaction.edit_original_response(content=first_display_text[:2000]) # 2000文字に切り詰めて送信

    # 残りの意見を interaction.followup.send で送信
    for name, result in list(zip(tasks.keys(), results))[1:]:
        display_text = f"**🔹 {name}の意見:**\n{result if not isinstance(result, Exception) else f'エラー: {result}'}"
        # send_long_message を使って2000文字を超えるメッセージを分割送信
        await send_long_message(interaction, display_text, is_followup=True)

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
            ### ▼ 修正点: model_choiceを明示的に指定 ▼ ###
            context = await get_notion_context(interaction, target_page_id, topic, model_choice="gpt")
            if not context: return
            await interaction.edit_original_response(content="🔬 11体のAIが初期意見を生成中…")
            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}"
            user_id = str(interaction.user.id)
            tasks = {name: func(user_id, prompt_with_context) for name, func in BASE_MODELS_FOR_ALL.items()}
            for name, (func, wrapper) in ADVANCED_MODELS_FOR_ALL.items():
                if name == "Perplexity": tasks[name] = wrapper(func, topic, notion_context=context)
                else: tasks[name] = wrapper(func, prompt_with_context)
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            synthesis_material = "以下のAI群の意見を統合してください。\n\n"
            full_text_results = ""
            for (name, result) in zip(tasks.keys(), results):
                full_response, summary = (result if isinstance(result, tuple) else (None, None))
                display_text = f"エラー: {result}" if isinstance(result, Exception) else (summary or full_response or result)
                full_text_results += f"**🔹 {name}の意見:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response or display_text}\n\n"
            await send_long_message(interaction, full_text_results, is_followup=False)
            await interaction.followup.send("⏳ gpt-5が中間レポートを作成します…")
            intermediate_report = await ask_gpt5(synthesis_material, system_prompt="以下の意見の要点だけを抽出し、短い中間レポートを作成してください。")
            await interaction.followup.send("⏳ Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(intermediate_report, system_prompt="あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。")
            await interaction.followup.send(f"**🤖 Mistral Large (最終統合レポート):**\n{final_report}")
        await asyncio.wait_for(core_logic(), timeout=300)
    except Exception as e:
        safe_log("🚨 /critical コマンドでエラー:", e)
        await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

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
            ### ▼ 修正点: model_choiceを明示的に指定 ▼ ###
            context = await get_notion_context(interaction, target_page_id, topic, model_choice="gpt")
            if not context: return
            await interaction.edit_original_response(content="⚖️ 内部討論と外部調査を並列で開始します…")
            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}"
            tasks = {
                "肯定論者(gpt-4o)": get_full_response_and_summary(ask_kreios, prompt_with_context, system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"),
                "否定論者(Perplexity)": get_full_response_and_summary(ask_rekus, topic, system_prompt="あなたはこの議題の【否定論者】です。議題に反対する最も強力な反論を、客観的な事実やデータに基づいて提示してください。", notion_context=context),
                "中立分析官(Gemini Pro)": get_full_response_and_summary(ask_minerva, prompt_with_context, system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。"),
                "外部調査(Perplexity)": get_full_response_and_summary(ask_rekus, topic, notion_context=context)
            }
            results = await asyncio.gather(*tasks.values())
            synthesis_material = "以下の情報を統合し、最終的な結論を導き出してください。\n\n"
            results_text = ""
            for (name, (full_response, summary)) in zip(tasks.keys(), results):
                display_text = summary or full_response
                results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"
            await send_long_message(interaction, results_text, is_followup=False)
            await interaction.followup.send("⏳ Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(synthesis_material, system_prompt="あなたは統合専用AIです。渡された情報を客観的に統合し、最終的な結論をレポートとしてまとめてください。")
            await interaction.followup.send(f"**🤖 Mistral Large (最終統合レポート):**\n{final_report}")
        await asyncio.wait_for(core_logic(), timeout=300)
    except Exception as e:
        safe_log("🚨 /logical コマンドでエラー:", e)
        await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

@tree.command(name="sync", description="管理者専用：スラッシュコマンドをサーバーに同期します。")
async def sync_command(interaction: discord.Interaction):
    if str(interaction.user.id) != ADMIN_USER_ID:
        await interaction.response.send_message("この操作を実行する権限がありません。", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        guild_obj = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
        tree.clear_commands(guild=guild_obj)
        await tree.sync(guild=guild_obj)
        tree.copy_global_to(guild=guild_obj)
        synced_commands = await tree.sync(guild=guild_obj)
        await interaction.followup.send(f"✅ コマンドの同期が完了しました。同期数: {len(synced_commands)}件", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ 同期中にエラーが発生しました:\n```{e}```", ephemeral=True)

@client.event
async def on_ready():
    print(f"✅ Login successful: {client.user}")
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            tree.copy_global_to(guild=guild_obj)
            cmds = await tree.sync(guild=guild_obj)
            print(f"✅ Synced {len(cmds)} guild commands to {GUILD_ID}")
        else:
            cmds = await tree.sync()
            print(f"✅ Synced {len(cmds)} global commands")
    except Exception as e:
        print(f"🚨 FATAL ERROR on command sync: {e}")

@client.event
async def on_message(message):
    # ボット自身やスラッシュコマンドのメッセージは無視
    if message.author.bot or message.content.startswith("/"):
        return

    # 旧コマンド「!」への案内
    if message.content.startswith("!"):
        await message.channel.send("💡 `!`コマンドは廃止されました。今後は`/`で始まるスラッシュコマンドをご利用ください。")
        return

    # 特定のチャンネル名でなければ無視
    channel_name = message.channel.name.lower()
    if not (channel_name.startswith("gpt") or channel_name.startswith("gemini") or channel_name.startswith("perplexity")):
        return

    # --- メインの処理 ---
    try:
        prompt = message.content
        thread_id = str(message.channel.id)
        is_admin = str(message.author.id) == ADMIN_USER_ID
        target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        # 添付ファイルの処理
        if message.attachments:
            await message.channel.send("📎 添付ファイルを解析しています…")
            prompt += "\n\n" + await analyze_attachment_for_gpt5(message.attachments[0])
        
        # Notionから記憶フラグを取得
        is_memory_on = await get_memory_flag_from_notion(thread_id)

        # チャンネル名に応じてNotion要約モデルを切り替え
        if channel_name.startswith("gpt"):
            summary_model_to_use = "perplexity"
        elif channel_name.startswith("gemini"):
            summary_model_to_use = "gemini"
        else: # perplexity部屋などのデフォルト
            summary_model_to_use = "gpt" 

        # Notionからコンテキストを取得
        notion_context = await get_notion_context_for_message(message, target_page_id, prompt, model_choice=summary_model_to_use)
        if notion_context is None:
            await message.channel.send("⚠️ Notionの参照に失敗したため、会話履歴のみで応答します。")

        # --- 各チャンネルごとのAI呼び出し処理 ---
        if channel_name.startswith("gpt"):
            history = gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            full_prompt = f"【Notionページの要約】\n{notion_context or '参照なし'}\n\n【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\n{prompt}"
            await message.channel.send("⏳ 受付完了。gpt-5が思考を開始します。")
            asyncio.create_task(run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id))

        elif channel_name.startswith("gemini"):
            await message.channel.send("⏳ Gemini 1.5 Proが思考を開始します…")
            history = gemini_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
            full_prompt = f"【Notionページの要約】\n{notion_context or '参照なし'}\n\n【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\nuser: {prompt}"
            reply = await ask_gemini_2_5_pro(full_prompt)
            await send_long_message(message.channel, reply)
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "Gemini 1.5 Pro")
            if is_memory_on and "エラー" not in reply:
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                gemini_thread_memory[thread_id] = history[-10:]

        elif channel_name.startswith("perplexity"):
            await message.channel.send("⏳ Perplexity Sonarが思考を開始します…")
            history = perplexity_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
            rekus_prompt = f"【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\nuser: {prompt}"
            reply = await ask_rekus(rekus_prompt, notion_context=notion_context)
            await send_long_message(message.channel, reply)
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "Perplexity Sonar")
            if is_memory_on and "エラー" not in str(reply):
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                perplexity_thread_memory[thread_id] = history[-10:]

    # --- エラー処理 ---
    except Exception as e:
        safe_log("🚨 on_messageでエラー:", e)
        await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
            
@app.on_event("startup")
async def startup_event():
    """サーバー起動時にBotをバックグラウンドで起動する"""
    global openai_client, mistral_client, notion, llama_model_for_vertex
    try:
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
        print("🚀 Creating Discord Bot startup task...")
        asyncio.create_task(client.start(DISCORD_TOKEN))
        print("✅ Discord Bot startup task has been created.")
    except Exception as e:
        print(f"🚨🚨🚨 FATAL ERROR during startup event: {e} 🚨🚨🚨")

@app.get("/")
def health_check():
    """ヘルスチェック用のエンドポイント"""
    return {"status": "ok", "bot_is_connected": client.is_ready()}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
