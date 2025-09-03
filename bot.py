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

# --- utilsのimportをここに追加 ---
from utils import safe_log, send_long_message

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
processing_channels = set()

# --- ヘルパー関数 ---
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

async def run_genius_channel_task(message, prompt, target_page_id):
    """ "genius" チャンネル専用のAI評議会タスクを実行 """
    thread_id = str(message.channel.id)
    try:
        # 1. Notionコンテキストの取得（共通チャンク要約ロジックに統一）
        await message.channel.send("📜 Notionページを要約しています...")

        notion_raw_text = await get_notion_page_text(target_page_id)
        if notion_raw_text.startswith("ERROR:") or not notion_raw_text.strip():
            await message.channel.send("⚠️ Notionページからテキストを取得できませんでした。議題のみで進行します。")
            notion_raw_text = "参照なし"

        # 共通チャンク要約関数を呼び出し（全ルーム統一）
        initial_summary = await summarize_text_chunks_for_message(
            channel=message.channel,
            text=notion_raw_text,
            query=prompt,
            model_choice="gpt"   # ← ここは好みで "gemini" や "perplexity" に切替可能
        )

        if not initial_summary:
            await message.channel.send("❌ 初回要約の生成に失敗しました。")
            return

        await send_long_message(message.channel, f"** 初回要約:**\n{initial_summary}")

        if "エラー" in str(initial_summary):
            await message.channel.send(f"⚠️ 初回要約中にエラーが発生しました: {initial_summary}")
            return

        await send_long_message(message.channel, f"** Mistral Largeによる論点サマリー:**\n{initial_summary}")
        
        # 2. AI評議会による並列分析
        await message.channel.send(" AI評議会（GPT-5, Perplexity, Gemini 2.5 Pro）が並列で分析を開始...")

        full_prompt_for_council = f"【論点サマリー】\n{initial_summary}\n\n上記のサマリーを踏まえ、ユーザーの最初の議題「{prompt}」について、あなたの役割に基づいた分析レポートを作成してください。"

        # 各AIのシステムプロンプトに文字数制限を追加
        tasks = {
            "GPT-5": ask_gpt5(full_prompt_for_council, system_prompt="あなたはこの議題に関する第一線の研究者です。最も先進的で鋭い視点から、要点を800字程度に絞って分析レポートを作成してください。"),
            "Perplexity": ask_rekus(full_prompt_for_council, system_prompt="あなたは外部調査の専門家です。関連情報や最新の動向を調査し、客観的な事実に基づいたレポートを800字程度で作成してください。"),
            "Gemini 2.5 Pro": ask_gemini_2_5_pro(full_prompt_for_council, system_prompt="あなたはこの議題に関するリスクアナリストです。潜在的な問題点や倫理的課題を中心に、批判的な視点からの分析レポートを800字程度で作成してください。")
        }
        
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        
        # 3. 各レポートを投稿
        synthesis_material = "以下の3つの専門家レポートを統合し、最終的な結論を導き出してください。\n\n"
        council_reports = {}
        for (name, result) in zip(tasks.keys(), results):
            report_text = f"エラー: {result}" if isinstance(result, Exception) else result
            await send_long_message(message.channel, f"**分析レポート by {name}:**\n{report_text}")
            synthesis_material += f"--- [{name}のレポート] ---\n{report_text}\n\n"
            council_reports[name] = report_text
    
        # 4. 統合AI (Claude 3.5) による最終レポート作成
        await message.channel.send(" 統合AI（Claude 3.5 Sonnet）が全レポートを統合し、最終結論を生成します...")
        final_report = await ask_claude("genius_user", synthesis_material, history=[])
        
        await send_long_message(message.channel, f"** 最終統合レポート by Claude 3.5 Sonnet:**\n{final_report}")

        # 5. Notionへの全ログ書き込み
        is_admin = str(message.author.id) == ADMIN_USER_ID
        if is_admin and target_page_id:
            await log_response(target_page_id, initial_summary, "Mistral Large (初回要約)")
            if not isinstance(council_reports.get("GPT-5"), Exception):
                await log_response(target_page_id, council_reports.get("GPT-5"), "GPT-5 (評議会)")
            if not isinstance(council_reports.get("Perplexity"), Exception):
                await log_response(target_page_id, council_reports.get("Perplexity"), "Perplexity (評議会)")
            if not isinstance(council_reports.get("Gemini 2.5 Pro"), Exception):
                await log_response(target_page_id, council_reports.get("Gemini 2.5 Pro"), "Gemini 2.5 Pro (評議会)")
            if not isinstance(final_report, Exception):
                await log_response(target_page_id, final_report, "Claude 3.5 Sonnet (最終統合)")

    except Exception as e:
        safe_log("🚨 geniusチャンネルのタスク実行中にエラー:", e)
        await message.channel.send(f"分析シーケンス中にエラーが発生しました: {e}")
    finally:
        # 処理が成功しても失敗しても、必ず最後にロックを解除する
        if thread_id in processing_channels:
            processing_channels.remove(thread_id)
        print(f"✅ geniusチャンネルの処理が完了し、ロックを解除しました (Channel ID: {thread_id})")

async def summarize_text_chunks_for_message(channel, text: str, query: str, model_choice: str):
    """[on_message/interaction用] テキストをチャンク分割し、指定モデルで並列要約し、必要ならMistral Largeで統合する"""
    chunk_size = 12000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    model_name_map = {
        "gpt": "gpt-4o",
        "gemini": "Gemini 1.5 Pro",
        "perplexity": "Perplexity Sonar",
        "gemini_2_5_pro": "Gemini 2.5 Pro",
        "gemini-2.5-pro": "Gemini 2.5 Pro",
    }
    model_name = model_name_map.get(model_choice, "不明なモデル")
    await channel.send(f" テキスト抽出完了。{model_name}によるチャンク毎の並列要約を開始… (全{len(text_chunks)}チャンク)")

    async def summarize_chunk(chunk, index):
        prompt = (
            "以下のテキストを要約し、必ず以下のタグを付けて分類してください：\n"
            "[背景情報]\n[定義・前提]\n[事実経過]\n[未解決課題]\n[補足情報]\n"
            "タグは省略可ですが、存在する場合は必ず上記のいずれかに分類してください。\n"
            f"ユーザーの質問は「{query}」です。この質問との関連性を考慮して要約してください。\n\n"
            f"【テキスト】\n{chunk}"
        )
        try:
            if model_choice == "gpt":
                resp = await openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": "あなたは構造化要約AIです。"},
                              {"role": "user", "content": prompt}],
                    max_tokens=2048,
                    temperature=0.2
                )
                summary_text = resp.choices[0].message.content
            elif model_choice == "gemini":
                summary_text = await ask_gemini_pro_for_summary(prompt)
            elif model_choice in ("gemini_2_5_pro", "gemini-2.5-pro"):
                summary_text = await ask_gemini_2_5_pro(prompt)  # ← 名称を実在関数に統一
            elif model_choice == "perplexity":
                summary_text = await ask_rekus_for_summary(prompt)
            else:
                summary_text = ""

            if not summary_text or "エラー" in str(summary_text):
                await channel.send(f"⚠️ チャンク {index+1} の要約中にエラーまたは空結果。")
                return None
            return summary_text
        except Exception as e:
            await channel.send(f"⚠️ チャンク {index+1} の要約中にエラー: {e}")
            return None

    tasks = [summarize_chunk(chunk, i) for i, chunk in enumerate(text_chunks)]
    chunk_summaries_results = await asyncio.gather(*tasks)
    chunk_summaries = [s for s in chunk_summaries_results if s is not None]

    if not chunk_summaries:
        await channel.send("❌ 全てのチャンクの要約に失敗しました。")
        return None

    # ✅ 1チャンクなら二重圧縮を避けて即採用（全ルーム共通）
    if len(chunk_summaries) == 1:
        await channel.send(" 1チャンクだけだったので、Mistral統合をスキップして要約を採用します。")
        return chunk_summaries[0]

    # 2チャンク以上のみ Mistral Large で統合
    await channel.send(" 全チャンクの要約完了。Mistral Largeが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    final_prompt = (
        "以下の、タグ付けされた複数の要約群を、一つの構造化されたレポートに統合してください。\n"
        "各タグ（[背景情報]、[事実経過]など）ごとに内容をまとめ直し、最終的なコンテキストとして出力してください。\n\n"
        f"【ユーザーの質問】\n{query}\n\n【タグ付き要約群】\n{combined}"
    )
    try:
        final_summary = await ask_lalah(final_prompt)
        if "エラー" in str(final_summary):
            await channel.send(f"⚠️ Mistral Largeによる最終統合中にエラーが発生しました: {final_summary}")
            return None
        return final_summary
    except Exception as e:
        await channel.send(f"❌ Mistral Largeによる最終統合中に予期せぬエラーが発生しました: {e}")
        return None

    
async def get_notion_context_for_message(message: discord.Message, page_id: str, query: str, model_choice: str):
    """on_message用のNotionコンテキスト取得関数"""
    await message.channel.send("...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks_for_message(message.channel, notion_text, query, model_choice)

async def get_notion_context(interaction: discord.Interaction, page_id: str, query: str, model_choice: str = "gpt"):
    """スラッシュコマンド用のNotionコンテキスト取得関数"""
    await interaction.edit_original_response(content="...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks_for_message(interaction.channel, notion_text, query, model_choice)

# bot.py ファイルの _sync_get_notion_page_text 関数を以下に差し替えてください

def _sync_get_notion_page_text(page_id):
    """
    Notionページからテキストを抽出する関数。
    複数のブロックタイプに対応し、デバッグログも出力する改良版。
    """
    all_text_blocks = []
    next_cursor = None
    print(f" Notionページ(ID: {page_id})の読み込みを開始します...")
    while True:
        try:
            response = notion.blocks.children.list(
                block_id=page_id,
                start_cursor=next_cursor,
                page_size=100
            )
            results = response.get("results", [])
            if not results and not all_text_blocks:
                print("⚠️ Notionからブロックが1件も返されませんでした。ページの権限やIDを確認してください。")

            for block in results:
                block_type = block.get("type")
                text_content = ""
                
                # 対応するブロックタイプを大幅に増やす
                if block_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item", "quote", "callout"]:
                    rich_text_list = block.get(block_type, {}).get("rich_text", [])
                    if rich_text_list:
                        text_content = "".join([rich_text.get("plain_text", "") for rich_text in rich_text_list])

                if text_content:
                    all_text_blocks.append(text_content)

            if response.get("has_more"):
                next_cursor = response.get("next_cursor")
            else:
                break
        except Exception as e:
            print(f"❌ Notion APIからの読み込み中に致命的なエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
            return f"ERROR: Notion API Error - {e}"

    print(f" Notionページの読み込み完了。合計 {len(all_text_blocks)} ブロック分のテキストを抽出しました。")
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

from ai_clients import (
    ask_gpt5, ask_gpt4o, ask_gemini_base, ask_minerva, ask_claude, 
    ask_mistral_base, ask_grok, ask_gemini_2_5_pro, ask_rekus, ask_llama,
    ask_gpt_base, ask_lalah, set_llama_model
)

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
    
    # メモリ管理オブジェクトを名前から動的に選択
    memory_map = {
        "GPT": gpt_base_memory,
        "Gemini": gemini_base_memory,
        "Mistral": mistral_base_memory,
        "Claude": claude_base_memory,
        "Llama": llama_base_memory,
        "Grok": grok_base_memory
    }
    # bot_nameからハイフンなどを取り除いて一致させる
    clean_bot_name = bot_name.split("-")[0].split(" ")[0]
    memory = memory_map.get(clean_bot_name)

    history = None
    if use_memory and memory is not None:
        history = memory.get(user_id, [])

    try:
        # historyを引数として渡す
        reply = await ai_function(user_id, prompt, history=history)

        if use_memory and memory is not None and "エラー" not in str(reply):
            new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
            if len(new_history) > 10: new_history = new_history[-10:]
            memory[user_id] = new_history

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

@tree.command(name="gpt-4o", description="GPT-4oを単体で呼び出します。")
async def gpt4o_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gpt4o, "GPT-4o")

@tree.command(name="gemini-2-5-flash", description="Gemini 2.5 Flashを単体で呼び出します。")
async def gemini_2_5_flash_command(interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
    await interaction.response.defer()
    attachment_parts = []
    if attachment:
        attachment_parts = [{'mime_type': attachment.content_type, 'data': await attachment.read()}]
    reply = await ask_minerva(prompt, attachment_parts=attachment_parts)
    await send_long_message(interaction, reply, is_followup=True)

@tree.command(name="perplexity", description="Perplexityを単体で呼び出します。")
async def perplexity_command(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    try:
        reply = await ask_rekus(prompt)
        await send_long_message(interaction, reply, is_followup=True)
    except Exception as e:
        await interaction.followup.send(f" Perplexity Sonar の処理中にエラーが発生しました: {e}")

@tree.command(name="gpt5", description="GPT-5を単体で呼び出します。")
async def gpt5_command(interaction: discord.Interaction, prompt: str):
    await advanced_ai_simple_runner(interaction, prompt, ask_gpt5, "gpt-5")

@tree.command(name="gemini-2-5-pro", description="Gemini 2.5 Proを単体で呼び出します。")
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
            
            notion_context = await get_notion_context(interaction, target_page_id, query, model_choice="gpt")
            if not notion_context:
                await interaction.edit_original_response(content="❌ Notionからコンテキストを取得できませんでした。")
                return
            prompt_with_context = (f"【ユーザーの質問】\n{query}\n\n【参考情報】\n{notion_context}")
            await interaction.edit_original_response(content="⏳ gpt-5が最終回答を生成中です...")
            reply = await ask_gpt5(prompt_with_context)
            await send_long_message(interaction, f"** 最終回答 (by gpt-5):**\n{reply}", is_followup=False)
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

ADVANCED_MODELS_FOR_ALL = {"gpt-4o": (ask_gpt4o, get_full_response_and_summary), "Gemini 2.5 Flash": (ask_minerva, get_full_response_and_summary), "Perplexity": (ask_rekus, get_full_response_and_summary), "Gemini 2.5 Pro": (ask_gemini_2_5_pro, get_full_response_and_summary), "gpt-5": (ask_gpt5, get_full_response_and_summary)}


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
        "Gemini 2.5 Flash": ADVANCED_MODELS_FOR_ALL["Gemini 2.5 Flash"][0],
        "Perplexity": ADVANCED_MODELS_FOR_ALL["Perplexity"][0]
    }
    for name, func in adv_models_to_run.items():
        tasks[name] = func(final_query)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    
    first_name = list(tasks.keys())[0]
    first_result = results[0]
    first_display_text = f"**🔹 {first_name}の意見:**\n{first_result if not isinstance(first_result, Exception) else f'エラー: {first_result}'}"
    await interaction.edit_original_response(content=first_display_text[:2000]) 

    for name, result in list(zip(tasks.keys(), results))[1:]:
        display_text = f"**🔹 {name}の意見:**\n{result if not isinstance(result, Exception) else f'エラー: {result}'}"
        await send_long_message(interaction, display_text, is_followup=True)

@tree.command(name="chain", description="複数AIがリレー形式で意見を継続していきます")
@app_commands.describe(topic="連鎖させたい議題")
async def chain_command(interaction: discord.Interaction, topic: str):
    await interaction.response.defer()
    ai_order = [
        ("GPT", ask_gpt_base),
        ("Gemini", ask_gemini_base),
        ("Mistral", ask_mistral_base),
        ("Claude", ask_claude),
        ("Llama", ask_llama),
        ("Grok", ask_grok)
    ]
    user_id = str(interaction.user.id)
    previous_opinion = f"【議題】\n{topic}"
    chain_results = []
    for name, ai_func in ai_order:
        prompt = f"{previous_opinion}\n\nあなたは{name}です。前のAIの意見を参考に、さらに深めてください。"
        try:
            opinion = await ai_func(user_id, prompt)
        except Exception as e:
            opinion = f"{name}エラー: {e}"
        chain_results.append(f"◆ {name}の意見:\n{opinion}")
        previous_opinion = opinion  
    await send_long_message(interaction, "\n\n".join(chain_results), is_followup=True)

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
            
            context = await get_notion_context(interaction, target_page_id, topic, model_choice="gemini")

            if not context: return
            await interaction.edit_original_response(content=" 11体のAIが初期意見を生成中…")
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
            await interaction.followup.send(" gpt-5が中間レポートを作成します…")
            intermediate_report = await ask_gpt5(synthesis_material, system_prompt="以下の意見の要点だけを抽出し、短い中間レポートを作成してください。")
            await interaction.followup.send(" Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(intermediate_report, system_prompt="あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。")
            await interaction.followup.send(f"** Mistral Large (最終統合レポート):**\n{final_report}")
        await asyncio.wait_for(core_logic(), timeout=600)
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

            context = await get_notion_context(interaction, target_page_id, topic, model_choice="gemini")
            if not context:
                # get_notion_context内でエラーメッセージは送信済み
                return

            await interaction.edit_original_response(content="⚖️ 内部討論と外部調査を並列で開始します…")
            prompt_with_context = (f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n"
                                   f"【ユーザーの質問】\n{topic}\n\n"
                                   f"【参考情報】\n{context}")

            user_id = str(interaction.user.id)
            tasks = {
                "肯定論者(gpt-4o)": get_full_response_and_summary(
                    ask_gpt4o,
                    prompt_with_context,
                    system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"
                ),
                "否定論者(Grok)": ask_grok(
                    user_id,
                    f"{prompt_with_context}\n\n上記を踏まえ、あなたはこの議題の【否定論者】として、議題に反対する最も強力な反論を、常識にとらわれず提示してください。"
                ),
                "中立分析官(Gemini 2.5 Flash)": get_full_response_and_summary(
                    ask_minerva,
                    prompt_with_context,
                    system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。"
                ),
                "外部調査(Perplexity)": get_full_response_and_summary(
                    ask_rekus,
                    topic,
                    notion_context=context
                )
            }

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            synthesis_material = "以下の情報を統合し、最終的な結論を導き出してください。\n\n"
            results_text = ""
            for (name, result) in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    display_text = f"エラー: {result}"
                    full_response = display_text
                
                elif name == "否定論者(Grok)":
                    display_text = result
                    full_response = result
                
                else:
                    full_response, summary = result
                    display_text = summary or full_response

                results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"

            await send_long_message(interaction, results_text, is_followup=False)

            await interaction.followup.send(" gpt-5が最終統合を行います…")
            final_report = await ask_gpt5(
                synthesis_material,
                system_prompt="あなたは統合専用AIです。渡された情報を客観的に統合し、最終的な結論をレポートとしてまとめてください。"
            )
            await interaction.followup.send(f"** gpt-5 (最終統合レポート):**\n{final_report}")

        await asyncio.wait_for(core_logic(), timeout=600)

    except Exception as e:
        safe_log("🚨 /logical コマンドでエラー:", e)
        try:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)
        except discord.errors.InteractionResponded:
            pass

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
    if message.author.bot or message.content.startswith("/"):
        return

    if message.content.startswith("!"):
        await message.channel.send("💡 `!`コマンドは廃止されました。今後は`/`で始まるスラッシュコマンドをご利用ください。")
        return

    channel_name = message.channel.name.lower()
    
    # "genius" チャンネルの処理
    if channel_name.startswith("genius"):
        thread_id = str(message.channel.id)

        if thread_id in processing_channels:
            await message.channel.send("⏳ 現在、前の処理を実行中です。完了までしばらくお待ちください。", delete_after=10)
            return

        try:
            prompt = message.content
            is_admin = str(message.author.id) == ADMIN_USER_ID
            target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

            if message.attachments:
                await message.channel.send(" 添付ファイルを解析しています…")
                prompt += "\n\n" + await analyze_attachment_for_gpt5(message.attachments[0])

            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])

            # 処理を開始する直前にチャンネルをロック
            processing_channels.add(thread_id)
            asyncio.create_task(run_genius_channel_task(message, prompt, target_page_id))
            return
            
            
            if not initial_summary:
                await channel.send("❌ 初回要約の生成に失敗しました。")
                return


        except Exception as e:
            safe_log("🚨 on_message (genius)でエラー:", e)
            await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
            # エラーが発生した場合もロックを解除
            if thread_id in processing_channels:
                processing_channels.remove(thread_id)
            return

    # "claude部屋" を含む各専用部屋の処理
    if not (channel_name.startswith("gpt") or channel_name.startswith("gemini") or channel_name.startswith("perplexity") or channel_name.startswith("claude")):
        return
        
    try:
        prompt = message.content
        thread_id = str(message.channel.id)
        is_admin = str(message.author.id) == ADMIN_USER_ID
        target_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        if message.attachments:
            # 添付ファイルはClaude部屋では一旦無視するか、別途処理を定義
            if not channel_name.startswith("claude"):
                 await message.channel.send("📎 添付ファイルを解析しています…")
                 prompt += "\n\n" + await analyze_attachment_for_gpt5(message.attachments[0])

        # --- "Claude部屋" の専用ロジック ---
        if channel_name.startswith("claude"):
            # 進捗を出さずにNotionを読み込む
            notion_raw_text = await get_notion_page_text(target_page_id)
            if notion_raw_text.startswith("ERROR:") or not notion_raw_text.strip():
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                return
            
            # 管理者の場合、ユーザーの発言をNotionに記録
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])

            full_prompt = (
                f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n"
                f"【参考情報】\n{notion_raw_text}\n\n"
                f"【ユーザーの質問】\n{prompt}"
            )
            
            # Botに「考え中」のステータスを表示させる
            async with message.channel.typing():
                reply = await ask_claude("claude_user", full_prompt, history=[])
                await send_long_message(message.channel, reply)

            # 管理者の場合、Botの返答をNotionに記録
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "Claude (専用部屋)")
            return
        
        # --- ここまでがClaude部屋の処理 ---

        # 以下、既存のgpt, gemini, perplexity部屋の処理
        is_memory_on = await get_memory_flag_from_notion(thread_id)

        if channel_name.startswith("gpt"):
            summary_model_to_use = "perplexity"
        elif channel_name.startswith("gemini"):
            summary_model_to_use = "gpt"
        else: # perplexity
            summary_model_to_use = "gemini_2_5_pro"

        notion_context = await get_notion_context_for_message(message, target_page_id, prompt, model_choice=summary_model_to_use)
        if notion_context is None:
            await message.channel.send("⚠️ Notionの参照に失敗したため、会話履歴のみで応答します。")

        if channel_name.startswith("gpt"):
            history = gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            full_prompt = f"【Notionページの要約】\n{notion_context or '参照なし'}\n\n【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\n{prompt}"
            await message.channel.send(" 受付完了。gpt-5が思考を開始します。")
            asyncio.create_task(run_long_gpt5_task(message, prompt, full_prompt, is_admin, target_page_id, thread_id))

        elif channel_name.startswith("gemini"):
            await message.channel.send(" Gemini 2.5 Proが思考を開始します…")
            history = gemini_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
            full_prompt = f"【Notionページの要約】\n{notion_context or '参照なし'}\n\n【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\nuser: {prompt}"
            
            reply = await ask_gemini_2_5_pro(full_prompt)
            
            await send_long_message(message.channel, reply)
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "Gemini 2.5 Pro")
            if is_memory_on and "エラー" not in reply:
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                gemini_thread_memory[thread_id] = history[-10:]

        elif channel_name.startswith("perplexity"):
            await message.channel.send(" Perplexity Sonarが思考を開始します…")
            history = perplexity_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
            
            rekus_prompt = f"【これまでの会話】\n{history_text or 'なし'}\n\n【今回の質問】\n{prompt}"
            
            reply = await ask_rekus(rekus_prompt, notion_context=notion_context)
            
            await send_long_message(message.channel, reply)
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "Perplexity Sonar")
            if is_memory_on and "エラー" not in str(reply):
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                perplexity_thread_memory[thread_id] = history[-10:]

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
            
            # ▼▼▼【追加】ここから ▼▼▼
            # 初期化したモデルをai_clients.pyに渡す
            set_llama_model(llama_model_for_vertex)
            print("✅ Vertex AI initialized successfully and passed to clients.")
            # ▲▲▲【追加】ここまで ▲▲▲

        except Exception as e:
            print(f"🚨 Vertex AI init failed (continue without it): {e}")
        
        async def start_bot():
            await client.login(DISCORD_TOKEN)
            await client.connect()

        asyncio.create_task(start_bot())

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
