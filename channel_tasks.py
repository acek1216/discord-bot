# channel_tasks.py

import asyncio
import discord
from notion_utils import (
    get_notion_page_text, log_to_notion, log_response,
    find_latest_section_id, append_summary_to_kb, get_memory_flag_from_notion
)
from ai_clients import (
    ask_gpt5, ask_rekus, ask_gemini_2_5_pro, ask_claude, ask_lalah
)
from utils import (
    safe_log, send_long_message, summarize_text_chunks_for_message,
    extract_attachments_as_text
)
import state # state.py からメモリをインポート
import os

# --- 環境変数の読み込み ---
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

# --- "genius" チャンネル専用タスク ---
async def run_genius_channel_task(message: discord.Message, prompt: str, target_page_id: str):
    thread_id = str(message.channel.id)
    try:
        initial_summary = None
        async with message.channel.typing():
            notion_raw_text = await get_notion_page_text([target_page_id])
            if notion_raw_text.startswith("ERROR:") or not notion_raw_text.strip():
                await message.channel.send("⚠️ Notionページからテキストを取得できませんでした。議題のみで進行します。")
                notion_raw_text = "参照なし"

            # Mistral Large (lalah) で初回要約
            initial_summary = await summarize_text_chunks_for_message(
                channel=message.channel,
                text=notion_raw_text,
                query=prompt,
                summarizer_func=ask_lalah
            )

        if not initial_summary or "エラー" in str(initial_summary):
            await message.channel.send(f"❌ 初回要約の生成に失敗しました: {initial_summary}")
            return

        await send_long_message(message.channel, f"**📝 Mistral Largeによる論点サマリー:**\n{initial_summary}")
        await message.channel.send("🤖 AI評議会（GPT-5, Perplexity, Gemini 2.5 Pro）が並列で分析を開始...")

        full_prompt_for_council = f"【論点サマリー】\n{initial_summary}\n\n上記のサマリーを踏まえ、ユーザーの最初の議題「{prompt}」について、あなたの役割に基づいた分析レポートを作成してください。"
        tasks = {
            "GPT-5": ask_gpt5(full_prompt_for_council, system_prompt="あなたはこの議題に関する第一線の研究者です。最も先進的で鋭い視点から、要点を800字程度で分析してください。"),
            "Perplexity": ask_rekus(full_prompt_for_council, system_prompt="あなたは外部調査の専門家です。関連情報や動向を調査し、客観的な事実に基づき800字程度で報告してください。"),
            "Gemini 2.5 Pro": ask_gemini_2_5_pro(full_prompt_for_council, system_prompt="あなたはこの議題に関するリスクアナリストです。潜在的な問題点や倫理的課題を中心に、批判的な視点から800字程度で分析してください。")
        }
        
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        
        council_reports = {name: (f"エラー: {res}" if isinstance(res, Exception) else res) for name, res in zip(tasks.keys(), results)}
        
        for name, report in council_reports.items():
            await send_long_message(message.channel, f"**📄 分析レポート by {name}:**\n{report}")

        synthesis_material = "以下の3つの専門家レポートを統合し、最終的な結論を導き出してください。\n\n" + "\n\n".join(f"--- [{name}のレポート] ---\n{report}" for name, report in council_reports.items())
        
        await message.channel.send("🤖 統合AI（Claude 3.5 Sonnet）が全レポートを統合し、最終結論を生成します...")
        
        async with message.channel.typing():
            final_report = await ask_claude("genius_user", synthesis_material, history=[])
        
        await send_long_message(message.channel, f"**👑 最終統合レポート by Claude 3.5 Sonnet:**\n{final_report}")

        if str(message.author.id) == ADMIN_USER_ID:
            await log_response(target_page_id, initial_summary, "Mistral Large (初回要約)")
            for name, report in council_reports.items():
                await log_response(target_page_id, report, f"{name} (評議会)")
            await log_response(target_page_id, final_report, "Claude 3.5 Sonnet (最終統合)")

    except Exception as e:
        safe_log("🚨 geniusチャンネルのタスク実行中にエラー:", e)
        await message.channel.send(f"分析シーケンス中にエラーが発生しました: {e}")
    finally:
        state.processing_channels.discard(thread_id)
        print(f"✅ geniusチャンネルの処理が完了し、ロックを解除しました (Channel ID: {thread_id})")

# --- "gpt" チャンネル専用タスク ---
async def run_long_gpt5_task(message: discord.Message, prompt: str, full_prompt: str, target_page_id: str, thread_id: str):
    user_mention = message.author.mention
    channel = message.channel
    is_admin = str(message.author.id) == ADMIN_USER_ID

    try:
        async with channel.typing():
            if is_admin and target_page_id:
                await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
            
            reply = await ask_gpt5(full_prompt)
            await send_long_message(channel, reply, mention=f"{user_mention}\nお待たせしました。gpt-5の回答です。")
            
            is_memory_on = await get_memory_flag_from_notion(thread_id)
            if is_memory_on:
                history = state.gpt_thread_memory.get(thread_id, [])
                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                state.gpt_thread_memory[thread_id] = history[-10:]
            
            if is_admin and target_page_id:
                await log_response(target_page_id, reply, "gpt-5 (専用スレッド)")

    except Exception as e:
        safe_log(f"🚨 gpt-5のバックグラウンド処理中にエラー:", e)
        await channel.send(f"{user_mention} gpt-5の処理中にエラーが発生しました: {e}")

# --- "gpt4o" チャンネル専用タスク ---
async def run_gpt4o_room_task(message: discord.Message, user_prompt: str, log_page_id: str, kb_page_id: str):
    channel = message.channel
    is_admin = str(message.author.id) == ADMIN_USER_ID

    async with channel.typing():
        try:
            kb_context_task = get_notion_page_text([kb_page_id])
            log_context_task = get_notion_page_text([log_page_id])
            kb_context, log_context = await asyncio.gather(kb_context_task, log_context_task)

            log_context_summary = log_context[-4000:]
            current_conversation = (f"{log_context_summary}\n\n"
                                    f"👤 {message.author.display_name} (最新の発言):\n{user_prompt}").strip()
            
            attach_text = await extract_attachments_as_text(message)
            
            prompt_for_answer = (
                f"あなたはナレッジベースと会話履歴を元に応答する執事AIです。\n"
                f"以下の【ナレッジベース】、【直近の会話履歴】、【添付情報】を元に、【ユーザーの質問】に回答してください。\n"
                f"ナレッジベース内の§IDを参照する場合は、必ずそのIDを文中に含めてください（例: §001によると...）。\n\n"
                f"--- 参考情報 ---\n"
                f"【ナレッジベース】\n{kb_context or '（まだありません）'}\n\n"
                f"【直近の会話履歴】\n{current_conversation or '（これが最初の会話です）'}\n\n"
                f"【添付情報】\n{attach_text or '（なし）'}\n\n"
                f"--- ここまで ---\n\n"
                f"【ユーザーの質問】\n{user_prompt}"
            )
            
            primary_answer = await ai_clients.ask_gpt4o(prompt_for_answer)

            if is_admin:
                await log_to_notion(log_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{user_prompt}"}}]}}])
                await log_response(log_page_id, primary_answer, "gpt-4o (一次回答)")

            prompt_for_summary = (f"以下のテキストを、Notionナレッジベースに登録するための「正規要約」にしてください。\n"
                                f"1行目にタイトル、2行目以降に本文という形式で、200字程度の簡潔な要約を作成してください。\n\n"
                                f"【元のテキスト】\n{primary_answer}")
            
            official_summary = await ai_clients.ask_gpt4o(prompt_for_summary)
            
            new_section_id = await find_latest_section_id(kb_page_id)
            await append_summary_to_kb(kb_page_id, new_section_id, official_summary)

            final_message = (f"{primary_answer}\n\n"
                             f"--- \n"
                             f"*{message.author.mention} この回答の要約はナレッジベースに **{new_section_id}** として記録されました。*")
            await send_long_message(channel, final_message)

        except Exception as e:
            await channel.send(f"❌ gpt-4o部屋でエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()