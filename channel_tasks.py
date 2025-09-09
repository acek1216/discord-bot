import discord
from discord.ext import commands
import asyncio
import traceback

from notion_utils import (
    NOTION_PAGE_MAP, get_notion_page_text, log_to_notion,
    log_response, get_memory_flag_from_notion,
    find_latest_section_id, append_summary_to_kb
)
from ai_clients import (
    ask_gpt5, ask_gemini_2_5_pro, ask_rekus, ask_claude, ask_lalah, ask_gpt4o
)
from utils import (
    safe_log, send_long_message, analyze_attachment_for_gpt5, get_notion_context_for_message
)

# --- geniusチャンネルタスク ---
async def run_genius_task(bot: commands.Bot, message: discord.Message):
    thread_id = str(message.channel.id)
    prompt = message.content
    try:
        page_ids = NOTION_PAGE_MAP.get(thread_id)
        if not page_ids:
            await message.channel.send("❌ Notion未連携"); return

        initial_summary = await get_notion_context_for_message(bot, message, page_ids[0], prompt, "gpt")
        if not initial_summary:
            await message.channel.send(f"❌ 初回要約に失敗"); return

        await send_long_message(bot.openai_client, message.channel, f"**📝 論点サマリー:**\n{initial_summary}")
        await message.channel.send("🤖 AI評議会 分析開始...")

        council_prompt = f"【論点】\n{initial_summary}\n\n上記を踏まえ議題「{prompt}」を分析せよ。"
        tasks = {
            "GPT-5": ask_gpt5(bot.openrouter_api_key, council_prompt, system_prompt="研究者として先進的な視点で分析せよ。"),
            "Perplexity": ask_rekus(bot.perplexity_api_key, council_prompt, system_prompt="外部調査専門家として客観的事実を報告せよ。"),
            "Gemini 2.5 Pro": ask_gemini_2_5_pro(council_prompt, system_prompt="リスクアナリストとして批判的に分析せよ。")
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        council_reports = {name: (f"エラー: {res}" if isinstance(res, Exception) else res) for name, res in zip(tasks.keys(), results)}

        for name, report in council_reports.items():
            await send_long_message(bot.openai_client, message.channel, f"**📄 分析 by {name}:**\n{report}")

        synthesis_material = "以下のレポートを統合し結論を導け。\n\n" + "\n\n".join(f"--- [{name}] ---\n{report}" for name, report in council_reports.items())
        await message.channel.send("🤖 統合AI Claude 最終結論 生成中...")

        final_report = await ask_claude(bot.openrouter_api_key, "genius_user", synthesis_material)
        await send_long_message(bot.openai_client, message.channel, f"**👑 最終統合レポート:**\n{final_report}")

    except Exception as e:
        safe_log("🚨 geniusタスクエラー:", e); await message.channel.send(f"分析シーケンスエラー: {e}")
    finally:
        bot.processing_channels.discard(thread_id)

# --- gpt4oチャンネルタスク ---
async def run_gpt4o_task(bot: commands.Bot, message: discord.Message):
    try:
        page_ids = NOTION_PAGE_MAP.get(str(message.channel.id))
        if not page_ids or len(page_ids) < 2:
            await message.channel.send("⚠️ ログ用とKB用のNotion設定が必要です。"); return

        log_page_id, kb_page_id = page_ids[0], page_ids[1]
        async with message.channel.typing():
            kb_context, log_context = await asyncio.gather(get_notion_page_text([kb_page_id]), get_notion_page_text([log_page_id]))
            current_convo = (f"{log_context[-4000:]}\n\n👤 {message.author.display_name}: {message.content}").strip()
            attach_text = await analyze_attachment_for_gpt5(bot.openai_client, message.attachments[0]) if message.attachments else ""

            prompt = (f"KBと会話履歴を元に応答する執事AIです。\n"
                      f"【KB】\n{kb_context or 'なし'}\n【会話履歴】\n{current_convo}\n【添付】\n{attach_text or 'なし'}\n\n"
                      f"【質問】\n{message.content}")

            primary_answer = await ask_gpt4o(bot.openai_client, prompt)
            await log_to_notion(log_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{message.content}"}}]}}])
            await log_response(log_page_id, primary_answer, "gpt-4o")

            summary_prompt = f"以下のテキストをNotion KB用に「タイトル\\n本文」形式で200字で要約せよ。\n\n{primary_answer}"
            official_summary = await ask_gpt4o(bot.openai_client, summary_prompt)
            new_section_id = await find_latest_section_id(kb_page_id)
            await append_summary_to_kb(kb_page_id, new_section_id, official_summary)

            final_message = f"{primary_answer}\n\n---\n*{message.author.mention} この回答はKBに **{new_section_id}** として記録されました。*"
            await send_long_message(bot.openai_client, message.channel, final_message)
    except Exception as e:
        await message.channel.send(f"❌ gpt-4o部屋エラー: {e}"); traceback.print_exc()

# --- claudeチャンネルタスク ---
async def run_claude_task(bot: commands.Bot, message: discord.Message):
    try:
        prompt = message.content
        thread_id = str(message.channel.id)
        is_admin = str(message.author.id) == bot.ADMIN_USER_ID
        page_ids = NOTION_PAGE_MAP.get(thread_id)
        if not page_ids:
            await message.channel.send("❌ このスレッドは Notion ページに紐づいていません。")
            return

        target_page_id = page_ids[0]

        async with message.channel.typing():
            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:") or not notion_raw_text.strip():
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                return

            if is_admin:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])

            full_prompt = (f"以下の【参考情報】を元に、会話のみで【ユーザーの質問】に回答してください。\n\n"
                           f"【参考情報】\n{notion_raw_text}\n\n"
                           f"【ユーザーの質問】\n{prompt}")

            reply = await ask_claude(bot.openrouter_api_key, "claude_user", full_prompt, history=[])
            await send_long_message(bot.openai_client, message.channel, reply)

            if is_admin:
                await log_response(target_page_id, reply, "Claude (専用部屋)")

    except Exception as e:
        safe_log("🚨 on_message (claude)でエラー:", e)
        await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")

# --- gpt5チャンネルタスク ---
async def run_gpt5_task(bot: commands.Bot, message: discord.Message):
    async with message.channel.typing():
        try:
            thread_id = str(message.channel.id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ Notion未連携")
                return

            target_page_id = page_ids[0]

            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:"):
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                notion_raw_text = ""

            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{message.content}"}}]}}])
            attach_text = await analyze_attachment_for_gpt5(bot.openai_client, message.attachments[0]) if message.attachments else ""

            is_memory_on = await get_memory_flag_from_notion(thread_id)
            history = bot.gpt_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history]) if history else "なし"

            full_prompt = (
                f"以下の【参考情報】と【会話履歴】を元に、ユーザーの質問に回答してください。\n\n"
                f"【参考情報】\n{notion_raw_text or 'なし'}\n\n"
                f"【添付】\n{attach_text or 'なし'}\n\n"
                f"【会話履歴】\n{history_text}\n\n"
                f"【ユーザーの質問】\n{message.content}"
            )

            reply = await ask_gpt5(bot.openrouter_api_key, full_prompt)
            await send_long_message(bot.openai_client, message.channel, reply, mention=f"{message.author.mention} gpt-5より:")
            await log_response(target_page_id, reply, "gpt-5")

            if is_memory_on:
                history.extend([{"role": "user", "content": message.content}, {"role": "assistant", "content": reply}])
                bot.gpt_thread_memory[thread_id] = history[-10:]

        except Exception as e:
            safe_log("🚨 gpt5タスクエラー:", e)
            await message.channel.send(f"❌ gpt-5部屋エラー: {e}")
            traceback.print_exc()

# --- geminiチャンネルタスク ---
async def run_gemini_task(bot: commands.Bot, message: discord.Message):
    async with message.channel.typing():
        try:
            thread_id = str(message.channel.id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ Notion未連携")
                return

            target_page_id = page_ids[0]

            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:"):
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                notion_raw_text = ""

            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{message.content}"}}]}}])
            attach_text = await analyze_attachment_for_gpt5(bot.openai_client, message.attachments[0]) if message.attachments else ""

            is_memory_on = await get_memory_flag_from_notion(thread_id)
            history = bot.gemini_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history]) if history else "なし"

            full_prompt = (
                f"以下の【参考情報】と【会話履歴】を元に、ユーザーの質問に回答してください。\n\n"
                f"【参考情報】\n{notion_raw_text or 'なし'}\n\n"
                f"【添付】\n{attach_text or 'なし'}\n\n"
                f"【会話履歴】\n{history_text}\n\n"
                f"【ユーザーの質問】\n{message.content}"
            )

            reply = await ask_gemini_2_5_pro(full_prompt)
            await send_long_message(bot.openai_client, message.channel, reply)
            await log_response(target_page_id, reply, "Gemini 2.5 Pro")

            if is_memory_on and "エラー" not in reply:
                history.extend([{"role": "user", "content": message.content}, {"role": "assistant", "content": reply}])
                bot.gemini_thread_memory[thread_id] = history[-10:]

        except Exception as e:
            safe_log("🚨 geminiタスクエラー:", e)
            await message.channel.send(f"❌ Gemini部屋エラー: {e}")
            traceback.print_exc()

# --- perplexityチャンネルタスク ---
async def run_perplexity_task(bot: commands.Bot, message: discord.Message):
    # ▼▼▼【ここからが修正箇所】▼▼▼
    async with message.channel.typing():
        try:
            thread_id = str(message.channel.id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ Notion未連携")
                return

            target_page_id = page_ids[0]

            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:"):
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                notion_raw_text = ""

            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{message.content}"}}]}}])
            attach_text = await analyze_attachment_for_gpt5(bot.openai_client, message.attachments[0]) if message.attachments else ""

            is_memory_on = await get_memory_flag_from_notion(thread_id)
            history = bot.perplexity_thread_memory.get(thread_id, []) if is_memory_on else []
            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history]) if history else "なし"

            full_prompt = (
                f"【添付】\n{attach_text or 'なし'}\n\n"
                f"【会話履歴】\n{history_text}\n\n"
                f"【ユーザーの質問】\n{message.content}"
            )

            # Perplexityのask_rekusはnotion_contextを特別に受け取る
            reply = await ask_rekus(bot.perplexity_api_key, full_prompt, notion_context=notion_raw_text)
            await send_long_message(bot.openai_client, message.channel, reply)
            await log_response(target_page_id, reply, "Perplexity")

            if is_memory_on and "エラー" not in str(reply):
                history.extend([{"role": "user", "content": message.content}, {"role": "assistant", "content": reply}])
                bot.perplexity_thread_memory[thread_id] = history[-10:]

        except Exception as e:
            safe_log("🚨 perplexityタスクエラー:", e)
            await message.channel.send(f"❌ Perplexity部屋エラー: {e}")
            traceback.print_exc()
    # ▲▲▲【ここまでが修正箇所】▲▲▲

# --- mistral-largeチャンネルタスク ---
async def run_mistral_large_task(bot: commands.Bot, message: discord.Message):
    # ▼▼▼【ここからが追加箇所】▼▼▼
    async with message.channel.typing():
        try:
            thread_id = str(message.channel.id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ Notion未連携")
                return

            target_page_id = page_ids[0]

            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:"):
                await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                notion_raw_text = ""

            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{message.content}"}}]}}])

            # Mistral Largeは短期記憶をサポートしていないため、履歴は含めない
            full_prompt = (
                f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n"
                f"【参考情報】\n{notion_raw_text or 'なし'}\n\n"
                f"【ユーザーの質問】\n{message.content}"
            )

            reply = await ask_lalah(bot.mistral_client, full_prompt)
            await send_long_message(bot.openai_client, message.channel, reply)
            await log_response(target_page_id, reply, "Mistral Large")

        except Exception as e:
            safe_log("🚨 mistral-largeタスクエラー:", e)
            await message.channel.send(f"❌ Mistral Large部屋エラー: {e}")
            traceback.print_exc()
    # ▲▲▲【ここまでが追加箇所】▲▲▲