import discord
from discord.ext import commands
import asyncio
import base64
import io
import json
import PyPDF2
from openai import AsyncOpenAI
from mistralai.async_client import MistralAsyncClient

# ai_clients からインポート
from ai_clients import ask_lalah, ask_gpt5, ask_gpt4o, ask_gemini_2_5_pro, ask_rekus

# notion_utils からインポート
from notion_utils import get_notion_page_text

# --- ログ・メッセージ送信 ---

def safe_log(prefix: str, obj):
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list, tuple)) else str(obj)
        print(f"{prefix}{s[:2000]}")
    except Exception as e:
        print(f"{prefix}(log skipped: {e})")

async def send_long_message(openai_client: AsyncOpenAI, target, text: str, is_followup: bool = False, mention: str = ""):
    if not text: text = "（応答が空でした）"
    full_text = f"{mention}\n{text}" if mention and mention not in text else text

    final_content = full_text
    if len(full_text) > 2000:
        summary_prompt = f"以下の文章はDiscordの文字数制限を超えています。内容の要点を最も重要視し、1800文字以内で簡潔に要約してください。\n\n---\n\n{text}"
        try:
            response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": summary_prompt}], max_tokens=1800, temperature=0.2)
            summary = response.choices[0].message.content
            header = f"{mention}\n" if mention else ""
            final_content = f"{header}⚠️ 元の回答が2000文字を超えたため、gpt-4oが要約しました：\n\n{summary}"
        except Exception as e:
            safe_log("🚨 send_long_messageの要約中にエラー:", e)
            header = f"{mention}\n" if mention else ""
            final_content = f"{header}元の回答は長すぎましたが、要約中にエラーが発生しました。"
    
    try:
        if isinstance(target, discord.Interaction):
            if is_followup: await target.followup.send(final_content)
            else:
                if not target.response.is_done(): await target.edit_original_response(content=final_content)
                else: await target.followup.send(final_content)
        else: await target.send(final_content)
    except (discord.errors.InteractionResponded, discord.errors.NotFound) as e:
        safe_log(f"⚠️ メッセージ送信に失敗（フォールバック）:", e)
        if hasattr(target, 'channel') and target.channel: await target.channel.send(final_content)

# --- 添付ファイル解析 ---

async def analyze_attachment_for_gpt5(openai_client: AsyncOpenAI, attachment: discord.Attachment):
    filename = attachment.filename.lower()
    data = await attachment.read()
    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        content = [{"type": "text", "text": "この画像の内容を分析し、後続のAIへのインプットとして要約してください。"}, {"type": "image_url", "image_url": {"url": f"data:{attachment.content_type};base64,{base64.b64encode(data).decode()}"}}]
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": content}], max_tokens=1500)
        return f"[gpt-4o画像解析]\n{response.choices[0].message.content}"
    elif filename.endswith((".py", ".txt", ".md", ".json", ".html", ".css", ".js")):
        return f"[添付コード {attachment.filename}]\n```\n{data.decode('utf-8', errors='ignore')[:3500]}\n```"
    elif filename.endswith(".pdf"):
        try:
            loop = asyncio.get_event_loop()
            reader = await loop.run_in_executor(None, lambda: PyPDF2.PdfReader(io.BytesIO(data)))
            all_text = await loop.run_in_executor(None, lambda: "\n".join([p.extract_text() or "" for p in reader.pages]))
            return f"[添付PDF {attachment.filename} 抜粋]\n{all_text[:3500]}"
        except Exception as e: return f"[PDF解析エラー: {e}]"
    else: return f"[未対応の添付ファイル形式: {attachment.filename}]"

# --- テキスト要約とNotionコンテキスト取得 ---

async def summarize_text_chunks(bot: commands.Bot, channel, text: str, query: str, model_choice: str):
    chunk_size = 12000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    summarizer_map = {
        "gpt": lambda p: ask_gpt4o(bot.openai_client, p),
        "gemini": ask_gemini_2_5_pro, # Geminiはクライアント不要
        "perplexity": lambda p: ask_rekus(bot.perplexity_api_key, p)
    }
    summarizer_func = summarizer_map.get(model_choice, ask_gemini_2_5_pro)

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
    return await ask_lalah(bot.mistral_client, final_prompt)

# ▼▼▼【修正】抜け落ちていた関数を追加 ▼▼▼
async def get_notion_context(bot: commands.Bot, interaction: discord.Interaction, page_id: str, query: str, model_choice: str = "gpt"):
    await interaction.edit_original_response(content="...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text([page_id])
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks(bot, interaction.channel, notion_text, query, model_choice)

async def get_notion_context_for_message(bot: commands.Bot, message: discord.Message, page_id: str, query: str, model_choice: str):
    notion_text = await get_notion_page_text([page_id])
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None
    return await summarize_text_chunks(bot, message.channel, notion_text, query, model_choice)
# ▲▲▲ ここまで追加 ▲▲▲

# --- 応答と要約のセット取得 ---

async def get_full_response_and_summary(openrouter_api_key: str, ai_function, prompt: str, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if not full_response or "エラー" in str(full_response): return full_response, None
    summary_prompt = f"次の文章を200文字以内で簡潔かつ意味が通じるように要約してください。\n\n{full_response}"
    summary = await ask_gpt5(openrouter_api_key, summary_prompt)
    if "エラー" in str(summary): return full_response, None
    return full_response, summary