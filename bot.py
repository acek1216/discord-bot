# -*- coding: utf-8 -*-
"""Discord Bot Final Version (Refactored for Stable Slash Command Operation - Final Fix)
"""

import discord
from discord import app_commands
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
import vertexai
from vertexai.generative_models import GenerativeModel
from flask import Flask
import threading
import time

# --- 環境変数の読み込みと必須チェック ---
def get_env_variable(var_name: str, is_secret: bool = True) -> str:
    """環境変数を読み込む。存在しない場合はエラーを発生させる。"""
    value = os.getenv(var_name)
    if not value:
        print(f"🚨 致命的なエラー: 環境変数 '{var_name}' が設定されていません。")
        exit(1) # プログラムを終了
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

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)
notion = Client(auth=NOTION_API_KEY)

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
gemini_2_5_pro_thread_memory = {}
processing_users = set()

# --- ヘルパー関数 ---

async def send_long_message(channel, text):
    """Discordの2000文字制限を超えたメッセージを分割して送信する"""
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

async def process_attachment(attachment: discord.Attachment, channel: discord.TextChannel) -> str:
    """添付ファイルを処理し、要約テキストを返す"""
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
    """同期的にLlamaを呼び出す内部関数"""
    try:
        vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
        model = GenerativeModel("publishers/meta/models/llama-3.3-70b-instruct-maas")
        response = model.generate_content(p_text)
        return response.text
    except Exception as e:
        error_message = f"🛑 Llama 3.3 呼び出しエラー: {e}"
        print(error_message)
        return error_message

async def ask_llama(user_id, prompt):
    """Vertex AI経由でLlama 3.3を呼び出し、短期記憶を持つ。"""
    history = llama_base_memory.get(user_id, [])
    system_prompt = "あなたは物静かな庭師の老人です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"

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
    """OpenRouter経由でClaude 3.5 Haikuを呼び出し、短期記憶を持つ。"""
    history = claude_base_memory.get(user_id, [])
    system_prompt = "あなたは図書館の賢者です。古今東西の書物を読み解き、森羅万象を知る存在として、落ち着いた口調で150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "anthropic/claude-3.5-haiku",
        "messages": messages
    }

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers
            )
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"]

        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        claude_base_memory[user_id] = new_history

        return reply

    except requests.exceptions.RequestException as e:
        error_message = f"🛑 OpenRouter経由 Claude 呼び出しエラー (requests): {e}"
        print(error_message)
        return error_message
    except Exception as e:
        error_message = f"🛑 OpenRouter経由 Claude 呼び出しエラー (その他): {e}"
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

async def ask_kreios(prompt, system_prompt=None): # gpt-4o
    base_prompt = system_prompt or "あなたはハマーン・カーンです。与えられた情報を元に、質問に対して回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=4000)
        return response.choices[0].message.content
    except Exception as e: return f"gpt-4oエラー: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]): # gemini-1.5-pro
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
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e: return f"Perplexityエラー: {e}"

async def ask_pod042(prompt): # Mistral Small に変更
    """
    POD042として、Mistral Smallモデルで応答を生成する。
    """
    system_prompt = """あなたは「ポッド042」という名前の、分析支援AIです。
ユーザーの要求に対し、「報告：」または「提案：」から始めて200文字以内で簡潔に応答してください。"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    try:
        # Mistralクライアントを使用してAPIを呼び出す
        response = await mistral_client.chat(
            model="mistral-small-latest",  # モデルをMistral Smallに変更
            messages=messages,
            max_tokens=300  # 応答が長くなりすぎないように制限
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"ポッド042(Mistral)エラー: {e}"

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

async def get_full_response_and_summary(ai_function, prompt, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if not full_response or "エラー" in str(full_response):
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
    prompt = f"以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n【ユーザーの質問】\n{query}\n\n【タグ付き要약群】\n{combined}"
    try:
        final_context = await ask_lalah(prompt, system_prompt="あなたは構造化統合AIです。")
        return final_context
    except Exception as e:
        await channel.send(f"⚠️ 統合中にエラー: {e}")
        return None

async def run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id):
    """
    gpt-5の長時間実行タスクをバックグラウンドで処理する関数
    """
    try:
        if is_admin and target_page_id:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}]
            await log_to_notion(target_page_id, log_blocks)

        reply = await ask_gpt5(full_prompt)

        user_mention = message.author.mention
        await send_long_message(message.channel, f"{user_mention}\nお待たせしました。gpt-5の回答です。\n\n{reply}")

        is_memory_on = await get_memory_flag_from_notion(thread_id)
        if is_memory_on:
            history = gpt_thread_memory.get(thread_id, [])
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": reply})
            gpt_thread_memory[thread_id] = history[-10:]

        if is_admin and target_page_id:
            await log_response(target_page_id, reply, "gpt-5 (専用スレッド)")

    except Exception as e:
        error_message = f"gpt-5の処理中に予期せぬエラーが発生しました: {e}"
        print(f"❌ {error_message}")
        try:
            await message.channel.send(f"{message.author.mention} {error_message}")
        except discord.errors.Forbidden:
            pass


# --- スラッシュコマンド定義 ---

async def simple_ai_command_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str, use_memory: bool = True):
    """単一のAIを呼び出すスラッシュコマンドの共通処理（最終修正版）"""
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id), NOTION_MAIN_PAGE_ID)
    is_admin = user_id == ADMIN_USER_ID

    try:
        if is_admin and target_page_id:
            log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {interaction.user.display_name} が `/{interaction.command.name} {prompt}` を実行しました。"}}]}}]
            await log_to_notion(target_page_id, log_blocks)

        if use_memory:
            reply = await ai_function(user_id, prompt)
        else:
            reply = await ai_function(prompt)

        print(f"[{bot_name}] Raw API Reply: {reply}")

        if reply and isinstance(reply, str) and reply.strip():
            await interaction.followup.send(reply)
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, bot_name)
        else:
            error_msg = f"🤖 {bot_name}からの応答が空、または無効でした。"
            print(f"エラー: {error_msg} (元の応答: {reply})")
            await interaction.followup.send(error_msg)

    except Exception as e:
        print(f"🚨 simple_ai_command_runnerの実行中にエラーが発生 ({bot_name}): {e}")
        await interaction.followup.send(f"🤖 {bot_name} の処理中に予期せぬエラーが発生しました。詳細はログを確認してください。")


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

# --- Notion連携・高機能コマンド群 ---
@tree.command(name="notion", description="現在のNotionページの内容について質問します")
@app_commands.describe(query="Notionページに関する質問", attachment="補足資料として画像を添付")
async def notion_command(interaction: discord.Interaction, query: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    
    final_query = query
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
    if not target_page_id:
        await interaction.followup.send("❌ このチャンネルはNotionページにリンクされていません。")
        return
        
    context = await get_notion_context(interaction.channel, target_page_id, final_query)
    if not context:
        await interaction.followup.send("❌ Notionからコンテキストを取得できませんでした。")
        return

    prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"
    
    await interaction.followup.send("⏳ gpt-5が最終回答を生成中です...")
    reply = await ask_gpt5(prompt_with_context)

    await send_long_message(interaction.channel, f"**🤖 最終回答 (by gpt-5):**\n{reply}")

    if str(interaction.user.id) == ADMIN_USER_ID:
        await log_response(target_page_id, reply, "gpt-5 (Notion参照)")

# --- 複雑な処理・マルチAI連携コマンド群 ---
BASE_MODELS_FOR_ALL = {
    "GPT": ask_gpt_base,
    "ジェミニ": ask_gemini_base,
    "ミストラル": ask_mistral_base,
    "Claude": ask_claude,
    "Llama": ask_llama,
}
ADVANCED_MODELS_FOR_ALL = {
    "gpt-4o": (ask_kreios, get_full_response_and_summary),
    "Gemini Pro": (ask_minerva, get_full_response_and_summary),
    "Perplexity": (ask_rekus, get_full_response_and_summary),
    "Gemini 2.5 Pro": (ask_gemini_2_5_pro, get_full_response_and_summary),
}

@tree.command(name="minna", description="5体のベースAIが議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
async def minna_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()

    final_query = prompt
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    user_id = str(interaction.user.id)
    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id), NOTION_MAIN_PAGE_ID)
    is_admin = user_id == ADMIN_USER_ID

    await interaction.followup.send("🔬 5体のベースAIが意見を生成中…")

    tasks = {}
    # ベースAIのタスクのみを追加
    for name, func in BASE_MODELS_FOR_ALL.items():
        tasks[name] = func(user_id, final_query)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    for (name, result) in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            display_text = f"エラー: {result}"
        else:
            display_text = result
        
        await send_long_message(interaction.channel, f"**🔹 {name}の意見:**\n{display_text}")

        if is_admin and target_page_id:
            await log_response(target_page_id, display_text, f"{name} (/minna)")


@tree.command(name="all", description="8体のAI（ベース5体+高機能3体）が議題に同時に意見を出します。")
@app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
async def all_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    
    final_query = prompt
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    user_id = str(interaction.user.id)
    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id), NOTION_MAIN_PAGE_ID)
    is_admin = user_id == ADMIN_USER_ID

    await interaction.followup.send("🔬 8体のAIが初期意見を生成中…")
    
    tasks = {}
    # ベースAIのタスクを追加
    for name, func in BASE_MODELS_FOR_ALL.items():
        tasks[name] = func(user_id, final_query)
    
    # 高機能AIのタスクを追加（ユーザーの定義に合わせて3体に限定）
    advanced_models_to_use = {
        "gpt-4o": ADVANCED_MODELS_FOR_ALL["gpt-4o"],
        "Gemini Pro": ADVANCED_MODELS_FOR_ALL["Gemini Pro"],
        "Perplexity": ADVANCED_MODELS_FOR_ALL["Perplexity"],
    }
    for name, (func, wrapper) in advanced_models_to_use.items():
        tasks[name] = wrapper(func, final_query)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    for (name, result) in zip(tasks.keys(), results):
        full_response, summary = None, None
        if isinstance(result, Exception): display_text = f"エラー: {result}"
        elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
        else: display_text = result
        
        await send_long_message(interaction.channel, f"**🔹 {name}の意見:**\n{display_text}")
        
        if is_admin and target_page_id:
            log_text = full_response if full_response else display_text
            await log_response(target_page_id, log_text, f"{name} (/all)")


@tree.command(name="slide", description="Notionの情報を元に、プレゼンテーションのスライド骨子案を作成します。")
@app_commands.describe(theme="スライドのテーマや議題", attachment="補足資料として画像を添付")
async def slide_command(interaction: discord.Interaction, theme: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    
    final_query = theme
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
    if not target_page_id:
        await interaction.followup.send("❌ このチャンネルはNotionページにリンクされていません。")
        return

    context = await get_notion_context(interaction.channel, target_page_id, final_query)
    if not context: return

    await interaction.followup.send("📝 gpt-5がスライド骨子案を作成します…")
    
    prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に対するプレゼンテーションのスライド骨子案を作成してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"
    slide_prompt = "あなたはプレゼンテーションの構成作家です。与えられた情報を元に、聞き手の心を動かす構成案を以下の形式で提案してください。\n・タイトル\n・スライド1: [タイトル] - [内容]\n・スライド2: [タイトル] - [内容]\n..."
    slide_draft = await ask_gpt5(prompt_with_context, system_prompt=slide_prompt)
    
    await send_long_message(interaction.channel, f"✨ **gpt-5 (スライド骨子案):**\n{slide_draft}")
    
    if str(interaction.user.id) == ADMIN_USER_ID:
        await log_response(target_page_id, slide_draft, "gpt-5 (スライド)")


@tree.command(name="critical", description="Notion情報を元に全AIで議論し、多角的な結論を導きます。")
@app_commands.describe(topic="議論したい議題", attachment="補足資料として画像を添付")
async def critical_command(interaction: discord.Interaction, topic: str, attachment: discord.Attachment = None):
    await interaction.response.defer()

    final_query = topic
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
    if not target_page_id:
        await interaction.followup.send("❌ このチャンネルはNotionページにリンクされていません。")
        return
    
    context = await get_notion_context(interaction.channel, target_page_id, final_query)
    if not context: return
    
    await interaction.followup.send("🔬 9体のAIが初期意見を生成中…")
    
    prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"
    user_id = str(interaction.user.id)
    is_admin = user_id == ADMIN_USER_ID

    tasks = {}
    for name, func in BASE_MODELS_FOR_ALL.items():
        tasks[name] = func(user_id, prompt_with_context)
    for name, (func, wrapper) in ADVANCED_MODELS_FOR_ALL.items():
        if name == "Perplexity":
            tasks[name] = wrapper(func, final_query, notion_context=context)
        else:
            tasks[name] = wrapper(func, prompt_with_context)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    synthesis_material = "以下の9つの異なるAIの意見を統合してください。\n\n"
    for (name, result) in zip(tasks.keys(), results):
        full_response, summary = None, None
        if isinstance(result, Exception): display_text = f"エラー: {result}"
        elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
        else: display_text = result
        
        await send_long_message(interaction.channel, f"**🔹 {name}の意見:**\n{display_text}")
        
        log_text = full_response if full_response else display_text
        synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
        if is_admin: await log_response(target_page_id, log_text, f"{name} (/critical)")

    await send_long_message(interaction.channel, "✨ gpt-5が中間レポートを作成します…")
    intermediate_prompt = "以下の9つの意見の要点だけを抽出し、短い中間レポートを作成してください。"
    intermediate_report = await ask_gpt5(synthesis_material, system_prompt=intermediate_prompt)

    await send_long_message(interaction.channel, "✨ Mistral Largeが最終統合を行います…")
    lalah_prompt = "あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。"
    final_report = await ask_lalah(intermediate_report, system_prompt=lalah_prompt)
    
    await send_long_message(interaction.channel, f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
    if is_admin: await log_response(target_page_id, final_report, "Mistral Large (統合)")


@tree.command(name="logical", description="Notion情報を元にAIが討論し、論理的な結論を導きます。")
@app_commands.describe(topic="討論したい議題", attachment="補足資料として画像を添付")
async def logical_command(interaction: discord.Interaction, topic: str, attachment: discord.Attachment = None):
    await interaction.response.defer()

    final_query = topic
    if attachment:
        final_query += await process_attachment(attachment, interaction.channel)

    target_page_id = NOTION_PAGE_MAP.get(str(interaction.channel.id))
    if not target_page_id:
        await interaction.followup.send("❌ このチャンネルはNotionページにリンクされていません。")
        return

    context = await get_notion_context(interaction.channel, target_page_id, final_query)
    if not context: return

    await interaction.followup.send("⚖️ 内部討論と外部調査を並列で開始します…")
    prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{final_query}\n\n【参考情報】\n{context}"
    is_admin = str(interaction.user.id) == ADMIN_USER_ID

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
    
    await send_long_message(interaction.channel, "--- 内部討論の結果 ---")
    for (name, result) in zip(tasks_internal.keys(), results_internal):
        full_response, summary = None, None
        if isinstance(result, Exception): display_text = f"エラー: {result}"
        elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
        else: display_text = result
        await send_long_message(interaction.channel, f"**{name}:**\n{display_text}")
        log_text = full_response if full_response else display_text
        synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
        if is_admin: await log_response(target_page_id, log_text, name)

    await send_long_message(interaction.channel, "--- 外部調査の結果 ---")
    for (name, result) in zip(tasks_external.keys(), results_external):
        full_response, summary = None, None
        if isinstance(result, Exception): display_text = f"エラー: {result}"
        elif isinstance(result, tuple): full_response, summary = result; display_text = summary if summary else full_response
        else: display_text = result
        await send_long_message(interaction.channel, f"**{name}:**\n{display_text}")
        log_text = full_response if full_response else display_text
        synthesis_material += f"--- [{name}の意見] ---\n{log_text}\n\n"
        if is_admin: await log_response(target_page_id, log_text, name)

    await send_long_message(interaction.channel, "✨ Mistral Largeが最終統合を行います…")
    lalah_prompt = "あなたは統合専用AIです。あなた自身のペルソナも、渡される意見のペルソナも全て無視し、純粋な情報として客観的に統合し、最終的な結論をレポートとしてまとめてください。"
    final_report = await ask_lalah(synthesis_material, system_prompt=lalah_prompt)
    
    await send_long_message(interaction.channel, f"✨ **Mistral Large (最終統合レポート):**\n{final_report}")
    if is_admin: await log_response(target_page_id, final_report, "Mistral Large (ロジカル統合)")


# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ ログイン成功: {client.user}")
    print(f"📖 Notion対応表: {NOTION_PAGE_MAP}")
    print(f"🚀 {len(await tree.fetch_commands())}個のスラッシュコマンドを同期しました。")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users:
        return

    if message.content.startswith("!"):
        await message.channel.send("💡 `!`コマンドは廃止されました。今後は`/`で始まるスラッシュコマンドをご利用ください。")
        return

    channel_name = message.channel.name.lower()
    if not (channel_name.startswith("gpt") or channel_name.startswith("gemini2.5pro")):
        return

    processing_users.add(message.author.id)
    try:
        prompt = message.content
        thread_id = str(message.channel.id)
        is_admin = str(message.author.id) == ADMIN_USER_ID
        target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        if message.attachments:
            prompt += await process_attachment(message.attachments[0], message.channel)

        is_memory_on = await get_memory_flag_from_notion(thread_id)
        
        if channel_name.startswith("gpt"):
            history = gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            messages_for_api = history + [{"role": "user", "content": prompt}]
            full_prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages_for_api])
            
            await message.channel.send("✅ 受付完了。gpt-5が思考を開始します。完了次第、このチャンネルでお知らせします。")
            asyncio.create_task(run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id))

        elif channel_name.startswith("gemini2.5pro"):
            history = gemini_2_5_pro_thread_memory.get(thread_id, []) if is_memory_on else []
            full_prompt_parts = [f"{m['role']}: {m['content']}" for m in history]
            full_prompt_parts.append(f"user: {prompt}")
            full_prompt = "\n".join(full_prompt_parts)

            await message.channel.send("⏳ Gemini 2.5 Proが思考を開始します…")
            reply = await ask_gemini_2_5_pro(full_prompt)
            await send_long_message(message.channel, reply)

            if is_memory_on:
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                gemini_2_5_pro_thread_memory[thread_id] = history[-10:]

            if is_admin and target_page_id:
                log_blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}]
                await log_to_notion(target_page_id, log_blocks)
                await log_response(target_page_id, reply, "Gemini 2.5 Pro (専用スレッド)")

    except Exception as e:
        print(f"on_messageでエラーが発生しました: {e}")
        await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動処理 ---
app = Flask(__name__)
@app.route("/")
def index():
    return "ボットは正常に動作中です！"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    try:
        print("🤖 Discordボットを起動します...")
        client.run(DISCORD_TOKEN)
    except Exception as e:
        print(f"🚨 ボットの起動に失敗しました: {e}")
