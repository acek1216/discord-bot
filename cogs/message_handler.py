# cogs/message_handler.py

import discord
from discord.ext import commands
import asyncio
import os

from notion_utils import NOTION_PAGE_MAP, get_notion_page_text, log_to_notion, log_response, get_memory_flag_from_notion
from ai_clients import ask_claude, ask_gemini_2_5_pro, ask_rekus
from utils import safe_log, send_long_message, get_notion_context_for_message, analyze_attachment_for_gpt5
import state
from channel_tasks import run_genius_channel_task, run_long_gpt5_task, run_gpt4o_room_task

ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()

class MessageHandlerCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("--- MessageHandlerCog Initialized ---") # 起動確認用

    # ▼▼▼【重要】リアクションテスト用のリスナーを追加 ▼▼▼
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot:
            return
        
        print(f"[診断] リアクション検知: {reaction.emoji} by {user.name}")
        try:
            # チャンネルにメッセージを送信して応答テスト
            await reaction.message.channel.send(f"リアクション検知成功！ {user.mention}さん、Botは生きています。")
        except Exception as e:
            print(f"🚨 [診断] リアクション応答エラー: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.content.startswith("/"):
            return

        if message.content.startswith("!"):
            await message.channel.send("💡 `!`コマンドは廃止されました。今後は`/`で始まるスラッシュコマンドをご利用ください。")
            return

        channel_name = message.channel.name.lower()
        
        # --- "genius" 部屋の処理 ---
        if channel_name.startswith("genius"):
            thread_id = str(message.channel.id)
            if thread_id in state.processing_channels:
                await message.channel.send("⏳ 現在、前の処理を実行中です。完了までしばらくお待ちください。", delete_after=10)
                return
            
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            if not page_ids:
                await message.channel.send("❌ このスレッドは Notion ページに紐づいていません（MAP未設定）。")
                return

            try:
                state.processing_channels.add(thread_id)
                prompt = message.content
                if message.attachments:
                    await message.channel.send("📎 添付ファイルを解析しています…")
                    prompt += "\n\n" + await analyze_attachment_for_gpt5(message.attachments[0])
                
                if str(message.author.id) == ADMIN_USER_ID:
                    await log_to_notion(page_ids[0], [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
                
                asyncio.create_task(run_genius_channel_task(message, prompt, page_ids[0]))
            except Exception as e:
                safe_log("🚨 on_message (genius)でエラー:", e)
                await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
            return

        # --- "claude" 部屋の処理 ---
        if channel_name.startswith("claude"):
            try:
                # (元のコードから変更なし)
                prompt = message.content
                thread_id = str(message.channel.id)
                is_admin = str(message.author.id) == ADMIN_USER_ID
                page_ids = NOTION_PAGE_MAP.get(thread_id)
                if not page_ids:
                    await message.channel.send("❌ このスレッドは Notion ページに紐づいていません（MAP未設定）。")
                    return
                target_page_id = page_ids[0]
                notion_raw_text = await get_notion_page_text([target_page_id])
                if notion_raw_text.startswith("ERROR:") or not notion_raw_text.strip():
                    await message.channel.send("❌ Notionページからテキストを取得できませんでした。")
                    return
                if is_admin and target_page_id:
                    await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
                full_prompt = (f"以下の【参考情報】を元に、会話のみで【ユーザーの質問】に回答してください。\n\n"
                               f"【参考情報】\n{notion_raw_text}\n\n"
                               f"【ユーザーの質問】\n{prompt}")
                async with message.channel.typing():
                    reply = await ask_claude("claude_user", full_prompt, history=[])
                    await send_long_message(message.channel, reply)
                if is_admin and target_page_id:
                    await log_response(target_page_id, reply, "Claude (専用部屋)")
            except Exception as e:
                safe_log("🚨 on_message (claude)でエラー:", e)
                await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")
            return

        # --- "gpt4o" 部屋の処理 ---
        if channel_name.startswith("gpt4o"):
            page_ids = NOTION_PAGE_MAP.get(str(message.channel.id))
            if not page_ids or len(page_ids) < 2:
                await message.channel.send("⚠️ この部屋にはログ用とKB用の2つのNotionページが必要です。")
                return
            await run_gpt4o_room_task(message, message.content, log_page_id=page_ids[0], kb_page_id=page_ids[1])
            return

        # --- gpt, gemini, perplexity 部屋の共通処理 ---
        if any(channel_name.startswith(p) for p in ["gpt", "gemini", "perplexity"]):
            try:
                prompt = message.content
                thread_id = str(message.channel.id)
                page_ids = NOTION_PAGE_MAP.get(thread_id)
                if not page_ids:
                    await message.channel.send("❌ このスレッドは Notion ページに紐づいていません。")
                    return
                
                target_page_id = page_ids[0]
                is_admin = str(message.author.id) == ADMIN_USER_ID
                is_memory_on = await get_memory_flag_from_notion(thread_id)
                
                attachment_text = ""
                if message.attachments:
                    attachment_text = await analyze_attachment_for_gpt5(message.attachments[0])

                summary_model_map = {"gpt": "perplexity", "gemini": "gpt"}
                summary_model = summary_model_map.get(channel_name.split('-')[0], "gemini_2_5_pro")
                
                notion_context = await get_notion_context_for_message(message, target_page_id, prompt, model_choice=summary_model)
                if notion_context is None:
                    await message.channel.send("⚠️ Notionの参照に失敗したため、会話履歴のみで応答します。")

                full_prompt_parts = []
                if attachment_text: full_prompt_parts.append(f"【添付ファイルの解析結果】\n{attachment_text}")
                if notion_context: full_prompt_parts.append(f"【Notionページの要約】\n{notion_context}")
                
                if channel_name.startswith("gpt"):
                    history = state.gpt_thread_memory.get(thread_id, []) if is_memory_on else []
                    history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                    if history_text: full_prompt_parts.append(f"【これまでの会話】\n{history_text}")
                    full_prompt_parts.append(f"【今回の質問】\n{prompt}")
                    full_prompt = "\n\n".join(full_prompt_parts)
                    await message.channel.send("🤖 受付完了。gpt-5が思考を開始します。")
                    asyncio.create_task(run_long_gpt5_task(message, prompt, full_prompt, target_page_id, thread_id))

                else: # gemini, perplexity の同期処理
                    async with message.channel.typing():
                        if is_admin:
                            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {message.author.display_name}:\n{prompt}"}}]}}])
                        
                        reply = ""
                        if channel_name.startswith("gemini"):
                            history = state.gemini_thread_memory.get(thread_id, []) if is_memory_on else []
                            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                            if history_text: full_prompt_parts.append(f"【これまでの会話】\n{history_text}")
                            full_prompt_parts.append(f"【今回の質問】\nuser: {prompt}")
                            full_prompt = "\n\n".join(full_prompt_parts)
                            reply = await ask_gemini_2_5_pro(full_prompt)
                            if is_memory_on and "エラー" not in reply:
                                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                                state.gemini_thread_memory[thread_id] = history[-10:]

                        elif channel_name.startswith("perplexity"):
                            history = state.perplexity_thread_memory.get(thread_id, []) if is_memory_on else []
                            history_text = "\n".join([f"{m['role']}: {m['content']}" for m in history])
                            if history_text: full_prompt_parts.append(f"【これまでの会話】\n{history_text}")
                            full_prompt_parts.append(f"【今回の質問】\n{prompt}")
                            rekus_prompt = "\n\n".join(full_prompt_parts)
                            reply = await ask_rekus(rekus_prompt, notion_context=notion_context)
                            if is_memory_on and "エラー" not in str(reply):
                                history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}])
                                state.perplexity_thread_memory[thread_id] = history[-10:]

                        await send_long_message(message.channel, reply)
                        if is_admin:
                            model_name = "Gemini 2.5 Pro" if channel_name.startswith("gemini") else "Perplexity Sonar"
                            await log_response(target_page_id, reply, model_name)

            except Exception as e:
                safe_log("🚨 on_messageでエラー:", e)
                await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")

# この関数はCogsを読み込むために必須
async def setup(bot):

    await bot.add_cog(MessageHandlerCog(bot))


