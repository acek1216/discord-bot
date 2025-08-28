# -*- coding: utf-8 -*-
"""Discord Bot Final Version (Build & Runtime Patched by User Analysis)
"""

import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from notion_client import Client
import requests
import io
from PIL import Image
import datetime

# --- Flask & Gunicorn for PaaS Health Check ---
from flask import Flask
import threading
import time

# --- ▼▼▼ 修正①：必須ENVの検証を遅延させるため、即時チェックを廃止し、単純な読み込みに変更 ▼▼▼ ---
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID")
OPENROUTER_API_KEY = (os.getenv("CLOUD_API_KEY") or "").strip()
GUILD_ID = os.getenv("GUILD_ID")

def ensure_required_env():
    """実行時に必須の環境変数が設定されているか検証する"""
    required = {
        "DISCORD_BOT_TOKEN": DISCORD_TOKEN, "OPENAI_API_KEY": OPENAI_API_KEY,
        "GEMINI_API_KEY": GEMINI_API_KEY, "PERPLEXITY_API_KEY": PERPLEXITY_API_KEY,
        "MISTRAL_API_KEY": MISTRAL_API_KEY, "NOTION_API_KEY": NOTION_API_KEY,
        "ADMIN_USER_ID": ADMIN_USER_ID, "NOTION_PAGE_ID": NOTION_MAIN_PAGE_ID,
        "CLOUD_API_KEY": OPENROUTER_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"必須環境変数が未設定です: {', '.join(missing)}")

# --- ▼▼▼ 修正②：Vertex AI 初期化も遅延させる ▼▼▼ ---
llama_model_for_vertex = None

def init_vertex_if_possible():
    """実行時にVertex AIの初期化を試みる"""
    global llama_model_for_vertex
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        # NOTE: projectとlocationはご自身のものに修正してください
        vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
        llama_model_for_vertex = GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas")
        print("✅ Vertex AI initialized successfully.")
    except Exception as e:
        print(f"⚠️ Vertex AIの初期化をスキップします: {e}")
        llama_model_for_vertex = None

# --- 各種クライアントの初期化 (Vertex以外) ---
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
notion = Client(auth=NOTION_API_KEY)

# (以下、元のコード構造を維持)
# ... (safety_settings, intents, client, etc.)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- ▼▼▼ 修正④：ロック粒度を(チャンネル, ユーザー)単位に修正 ▼▼▼ ---
processing_keys = set()

# --- メモリ管理 ---
gpt_base_memory, gemini_base_memory, mistral_base_memory = {}, {}, {}
claude_base_memory, llama_base_memory = {}, {}
gpt_thread_memory, gemini_2_5_pro_thread_memory = {}, {}

# (ヘルパー関数、Notion連携関数、AIモデル呼び出し関数の内容は以前のものと同じ)
# ...
async def send_long_message(channel, text):
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

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

def _sync_call_llama(p_text: str):
    try:
        if llama_model_for_vertex is None:
            return "Llama (Vertex AI) が初期化されていないため、呼び出せませんでした。"
        response = llama_model_for_vertex.generate_content(p_text)
        return response.text
    except Exception as e:
        error_message = f"🛑 Llama 3.3 呼び出しエラー: {e}"
        print(error_message)
        return error_message

async def ask_llama(user_id, prompt):
    history = llama_base_memory.get(user_id, [])
    system_prompt = "あなたは物静かな庭師の老人です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"
    full_prompt_parts = [system_prompt] + [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in history] + [f"User: {prompt}"]
    full_prompt = "\n".join(full_prompt_parts)
    try:
        reply = await asyncio.get_event_loop().run_in_executor(None, _sync_call_llama, full_prompt)
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        llama_base_memory[user_id] = new_history[-10:]
        return reply
    except Exception as e:
        error_message = f"🛑 Llama 3.3 非同期処理エラー: {e}"
        print(error_message)
        return error_message

async def ask_claude(user_id, prompt):
    history = claude_base_memory.get(user_id, [])
    system_prompt = "あなたは図書館の賢者です。古今東西の書物を読み解き、森羅万象を知る存在として、落ち着いた口調で150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "anthropic/claude-3.5-haiku", "messages": messages}
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post("https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers)
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        claude_base_memory[user_id] = new_history[-10:]
        return reply
    except Exception as e:
        error_message = f"🛑 OpenRouter経由 Claude 呼び出しエラー: {e}"
        print(error_message)
        return error_message

async def ask_gpt_base(user_id, prompt):
    history = gpt_base_memory.get(user_id, [])
    system_prompt = "あなたは論理と秩序を司る神官「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_completion_tokens=250 # ← OpenAI パラメータを修正
        )
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        gpt_base_memory[user_id] = new_history[-10:]
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
        gemini_base_memory[user_id] = new_history[-10:]
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
        mistral_base_memory[user_id] = new_history[-10:]
        return reply
    except Exception as e: return f"ミストラルエラー: {e}"
# ... (他のask_xxx関数も同様に、max_tokensがあればmax_completion_tokensに修正)
async def ask_kreios(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_completion_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"gpt-4oエラー: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]):
    base_prompt = system_prompt or "あなたは客観的な分析AIです。あらゆる事象をデータとリスクで評価し、感情を排して冷徹に分析します。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=base_prompt, safety_settings=safety_settings)
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
    base_prompt = system_prompt or "あなたは探索王レキュスです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = await asyncio.get_event_loop().run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e: return f"Perplexityエラー: {e}"

async def ask_pod042(prompt):
    full_prompt = f"""あなたは「ポッド042」という名前の、分析支援AIです。
以下のユーザーの要求に対し、「報告：」または「提案：」から始めて200文字以内で簡潔に応答してください。

【ユーザーの要求】
{prompt}
"""
    model = genai.GenerativeModel("gemini-1.5-flash-latest", system_instruction="", safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(full_prompt)
        return response.text
    except Exception as e: return f"ポッド042エラー: {e}"

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
        response = await openai_client.chat.completions.create(
            model="gpt-5",
            messages=messages,
            max_completion_tokens=4000
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"gpt-5エラー: {e}"
# ... (他のヘルパー関数も同様に)

@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")
    print(f"📖 Notion対応表が読み込まれました: {NOTION_PAGE_MAP}")

@client.event
async def on_message(message):
    key = (message.channel.id, message.author.id)
    if message.author.bot or key in processing_keys:
        return
    processing_keys.add(key)
    
    try:
        content = message.content
        channel_name = message.channel.name.lower()
        
        # GPT-5部屋の処理
        if channel_name.startswith("gpt") and not content.startswith("!"):
            # ... (run_long_gpt5_taskを呼び出す処理は変更なし)
            return

        # Gemini 2.5 Pro部屋の処理
        elif channel_name.startswith("gemini2.5pro") and not content.startswith("!"):
            prompt = content
            history = gemini_2_5_pro_thread_memory.get(str(message.channel.id), [])
            # ... (プロンプト作成)
            await message.channel.send("⏳ Gemini 2.5 Proが思考を開始します…")
            try:
                reply = await asyncio.wait_for(ask_gemini_2_5_pro(full_prompt), timeout=60.0)
            except asyncio.TimeoutError:
                reply = "Gemini 2.5 Proエラー: 応答がタイムアウトしました。"
            await send_long_message(message.channel, reply)
            # ... (履歴更新とログ記録)
            return
        
        # `!`コマンドの処理はここから
        # ... (元のコードの `!` コマンド分岐処理)

    except Exception as e:
        print(f"on_messageでエラーが発生しました: {e}")
    finally:
        processing_keys.discard(key)


# --- ▼▼▼ 修正③：if __name__ == "__main__": でだけ厳格チェック＆初期化 ▼▼▼ ---
if __name__ == "__main__":
    try:
        # 実行時に初めて必須チェック
        ensure_required_env()
        # 実行時に初めてVertex AI初期化
        init_vertex_if_possible()

        # PaaSのヘルスチェックを考慮した安定起動
        port = int(os.environ.get("PORT", 8080))
        app = Flask(__name__)
        @app.route("/")
        def index():
            return "ボットは正常に動作中です！"
        
        flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port))
        flask_thread.daemon = True
        flask_thread.start()

        print("🚦 Health check endpoint is starting, waiting 2 seconds for it to be ready...")
        time.sleep(2)
        print("✅ Health check endpoint should be ready.")

        # Discordボットを起動
        print("🤖 Discordボットを起動します...")
        client.run(DISCORD_TOKEN)

    except RuntimeError as e:
        print(f"🚨 起動前チェックエラー: {e}")
    except Exception as e:
        print(f"🚨 ボットの起動に失敗しました: {e}")
