# utils.py

import discord
import asyncio
import base64
import io
import json
import PyPDF2
from openai import AsyncOpenAI

# ai_clients.py から必要な関数をインポート
from ai_clients import (
    ask_gpt_base, ask_gemini_base, ask_mistral_base, ask_claude,
    ask_llama, ask_grok, ask_gpt5, ask_gpt4o, ask_minerva, ask_rekus,
    ask_gemini_pro_for_summary, ask_rekus_for_summary, ask_lalah,
    ask_gemini_2_5_pro
)
# notion_utils.py からもインポート
from notion_utils import get_notion_page_text

# --- グローバル変数 ---
openai_client: AsyncOpenAI = None

# --- クライアント設定関数 ---
def set_openai_client(client: AsyncOpenAI):
    global openai_client
    openai_client = client

# --- ログ・メッセージ送信 ---
def safe_log(prefix: str, obj):
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list, tuple)) else str(obj)
        print(f"{prefix}{s[:2000]}")
    except Exception as e:
        print(f"{prefix}(log skipped: {e})")

async def send_long_message(target, text: str, is_followup: bool = False, mention: str = ""):
    if not text: text = "（応答が空でした）"
    full_text = f"{mention}\n{text}" if mention and mention not in text else text

    if len(full_text) > 2000:
        summary_prompt = f"以下の文章はDiscordの文字数制限を超えています。内容の要点を最も重要視し、1800文字以内で簡潔に要約してください。\n\n---\n\n{text}"
        try:
            response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": summary_prompt}], max_tokens=1800, temperature=0.2)
            summary = response.choices[0].message.content
            final_content = f"{mention}\n⚠️ 元の回答が2000文字を超えたため、gpt-4oが要約しました：\n\n{summary}" if mention else f"⚠️ 元の回答が2000文字を超えたため、gpt-4oが要約しました：\n\n{summary}"
        except Exception as e:
            safe_log("🚨 要約中にエラー:", e)
            final_content = f"{mention}\n元の回答は長すぎましたが、要約中にエラーが発生しました。" if mention else "元の回答は長すぎましたが、要約中にエラーが発生しました。"
    else:
        final_content = full_text

    if isinstance(target, discord.Interaction):
        try:
            if is_followup: await target.followup.send(final_content)
            else: await target.edit_original_response(content=final_content)
        except (discord.errors.InteractionResponded, discord.errors.NotFound):
            if target.channel: await target.channel.send(final_content)
    else: # channel object
        await target.send(final_content)

# --- スラッシュコマンド用ヘルパー ---
async def simple_ai_command_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str, memory_map: dict):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    clean_bot_name = bot_name.split("-")[0].split(" ")[0]
    memory = memory_map.get(clean_bot_name)
    history = memory.get(user_id, []) if memory is not None else []
    try:
        reply = await ai_function(user_id, prompt, history=history)
        if memory is not None and "エラー" not in str(reply):
            new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
            memory[user_id] = new_history[-10:]
        await interaction.followup.send(reply)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラー: {e}")

async def advanced_ai_simple_runner(interaction: discord.Interaction, prompt: str, ai_function, bot_name: str):
    await interaction.response.defer()
    try:
        reply = await ai_function(prompt)
        await send_long_message(interaction, reply, is_followup=True)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラー: {e}")

async def get_full_response_and_summary(ai_function, prompt, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if not full_response or "エラー" in str(full_response): return full_response, None
    summary_prompt = f"次の文章を200文字以内で簡潔に要約してください。\n\n{full_response}"
    summary = await ask_gpt5(summary_prompt)
    if "エラー" in str(summary): return full_response, None
    return full_response, summary

# --- 添付ファイル解析 ---
async def analyze_attachment_for_gpt5(attachment: discord.Attachment):
    filename = attachment.filename.lower()
    data = await attachment.read()
    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        content = [{"type": "text", "text": "この画像の内容を分析し、後続のAIへのインプットとして要約してください。"},
                   {"type": "image_url", "image_url": {"url": f"data:{attachment.content_type};base64,{base64.b64encode(data).decode()}"}}]
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": content}], max_tokens=1500)
        return f"[gpt-4o画像解析]\n{response.choices[0].message.content}"
    elif filename.endswith((".py", ".txt", ".md", ".json", ".html", ".css", ".js")):
        return f"[添付コード {attachment.filename}]\n```\n{data.decode('utf-8', errors='ignore')[:3500]}\n```"
    elif filename.endswith(".pdf"):
        try:
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            return f"[添付PDF {attachment.filename} 抜粋]\n{'\n'.join([p.extract_text() or '' for p in reader.pages])[:3500]}"
        except Exception as e: return f"[PDF解析エラー: {e}]"
    else: return f"[未対応の添付ファイル形式: {attachment.filename}]"

# --- テキスト要約 ---
async def summarize_text_chunks_for_message(channel, text: str, query: str, summarizer_func):
    chunk_size = 12000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    async def summarize_chunk(chunk):
        prompt = (f"ユーザーの質問は「{query}」です。この質問との関連性を考慮し、以下のテキストを構造化して要約してください。\n"
                  "要約には以下のタグを付けて分類してください：[背景情報], [定義・前提], [事実経過], [未解決課題], [補足情報]\n\n{chunk}")
        try:
            return await summarizer_func(prompt)
        except Exception as e:
            safe_log(f"⚠️ チャンクの要約中にエラー:", e)
            return None
    tasks = [summarize_chunk(chunk) for chunk in text_chunks]
    chunk_summaries = [s for s in await asyncio.gather(*tasks) if s]
    if not chunk_summaries: return None
    if len(chunk_summaries) == 1: return chunk_summaries[0]
    combined = "\n---\n".join(chunk_summaries)
    final_prompt = (f"ユーザーの質問は「{query}」です。この質問への回答となるように、以下の複数の要約群を一つのレポートに統合してください。\n\n{combined}")
    return await ask_lalah(final_prompt) # 最終統合はMistral Large (lalah)

async def get_notion_context_for_message(message: discord.Message, page_id: str, query: str, model_choice: str):
    notion_text = await get_notion_page_text([page_id])
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None
    summarizer_map = {"gpt": ask_gpt4o, "gemini": ask_gemini_pro_for_summary, "perplexity": ask_rekus_for_summary}
    summarizer = summarizer_map.get(model_choice, ask_gemini_2_5_pro)
    return await summarize_text_chunks_for_message(message.channel, notion_text, query, summarizer)

async def get_notion_context(interaction: discord.Interaction, page_id: str, query: str, model_choice: str = "gpt"):
    await interaction.edit_original_response(content="...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text([page_id])
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    summarizer_map = {"gpt": ask_gpt4o, "gemini": ask_gemini_pro_for_summary}
    summarizer = summarizer_map.get(model_choice, ask_gpt4o)
    return await summarize_text_chunks_for_message(interaction.channel, notion_text, query, summarizer)

# --- AIモデル定義 (共通) ---
BASE_MODELS_FOR_ALL = {"GPT": ask_gpt_base, "Gemini": ask_gemini_base, "Mistral": ask_mistral_base, "Claude": ask_claude, "Llama": ask_llama, "Grok": ask_grok}
ADVANCED_MODELS_FOR_ALL = {"gpt-4o": (ask_gpt4o, get_full_response_and_summary), "Gemini 2.5 Pro": (ask_gemini_2_5_pro, get_full_response_and_summary), "Perplexity": (ask_rekus, get_full_response_and_summary)}
