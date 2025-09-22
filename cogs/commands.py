import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os

# --- 各モジュールから必要な関数をインポート ---
from ai_clients import (
    ask_gpt_base, ask_gemini_base, ask_mistral_base, ask_claude, ask_llama, ask_grok,
    ask_gpt4o, ask_minerva, ask_rekus, ask_gpt5, ask_gpt5_mini, ask_gemini_2_5_pro,
    ask_lalah, ask_o1_pro
)
from notion_utils import NOTION_PAGE_MAP, log_to_notion, log_response, log_user_message, find_latest_section_id, append_summary_to_kb
from utils import (
    safe_log, send_long_message, analyze_attachment_for_gemini,
    get_full_response_and_summary, get_notion_context
)

# ----------------------------------------------------------------
# コマンドから利用されるヘルパー関数群
# ----------------------------------------------------------------
async def simple_ai_command_runner(bot: commands.Bot, interaction: discord.Interaction, prompt: str, ai_function, bot_name: str):
    await interaction.response.defer()
    user_id = str(interaction.user.id)
    
    memory_map = {
        "GPT": bot.gpt_base_memory, "Gemini": bot.gemini_base_memory,
        "Mistral": bot.mistral_base_memory, "Claude": bot.claude_base_memory,
        "Llama": bot.llama_base_memory, "Grok": bot.grok_base_memory
    }
    
    clean_bot_name = bot_name.split("-")[0].split(" ")[0]
    memory = memory_map.get(clean_bot_name)
    history = memory.get(user_id, []) if memory is not None else []

    try:
        # この呼び出しで 'history' というキーワード引数を使っている
        reply = await ai_function(user_id, prompt, history=history)

        if memory is not None and "エラー" not in str(reply):
            new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
            memory[user_id] = new_history[-10:]
        
        await send_long_message(bot.openai_client, interaction, reply, is_followup=True)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

async def advanced_ai_simple_runner(bot: commands.Bot, interaction: discord.Interaction, prompt: str, ai_function, bot_name: str):
    await interaction.response.defer()
    try:
        reply = await ai_function(prompt)
        await send_long_message(bot.openai_client, interaction, reply, is_followup=True)
    except Exception as e:
        await interaction.followup.send(f"🤖 {bot_name} の処理中にエラーが発生しました: {e}")

# ----------------------------------------------------------------
# Cogクラスの定義
# ----------------------------------------------------------------
class CommandCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # ▼▼▼【修正箇所】lambdaの引数名を 'h' から 'history' に変更 ▼▼▼
        self.BASE_MODELS_FOR_ALL = {
            "GPT": lambda user_id, prompt, history=None: ask_gpt_base(self.bot.openai_client, user_id, prompt, history),
            "Gemini": lambda user_id, prompt, history=None: ask_gemini_base(user_id, prompt, history),
            "Claude": lambda user_id, prompt, history=None: ask_claude(self.bot.openrouter_api_key, user_id, prompt, history),
            "Llama": lambda user_id, prompt, history=None: ask_llama(self.bot.llama_model, user_id, prompt, history),
            "Grok": lambda user_id, prompt, history=None: ask_grok(self.bot.grok_api_key, user_id, prompt, history)
        }
        async def get_gpt4o_response(p, **kwargs):
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            if not ai_manager.initialized:
                ai_manager.initialize(self.bot)
            return await ai_manager.ask_ai("gpt4o", p, **kwargs)

        async def get_gpt5_response(p, **kwargs):
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            if not ai_manager.initialized:
                ai_manager.initialize(self.bot)
            return await ai_manager.ask_ai("gpt5", p, **kwargs)

        self.ADVANCED_MODELS_FOR_ALL = {
            "gpt-4o": (get_gpt4o_response,
                       lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Gemini 2.5 Flash": (ask_minerva,
                                 lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Perplexity": (lambda p, **kwargs: ask_rekus(self.bot.perplexity_api_key, p, **kwargs),
                           lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Gemini 2.5 Pro": (ask_gemini_2_5_pro,
                               lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "gpt-5": (get_gpt5_response,
                      lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs))
        }

    # (以降のコマンド定義は変更ありません)
# 🗑️ /gpt コマンド削除: 専用チャンネル #gpt-chat で代替

# 🗑️ /gemini コマンド削除: 専用チャンネル #gemini-room で代替

# 🗑️ /claude コマンド削除: 専用チャンネル #claude-discussion で代替

# 🗑️ /llama コマンド削除: 専用チャンネル #llama-chat で代替

# 🗑️ /grok コマンド削除: 専用チャンネル #grok-ai で代替

# 🗑️ /gpt-4o コマンド削除: 専用チャンネル #gpt4o-chat で代替

# 🗑️ /gemini-2-5-flash コマンド削除: 専用チャンネル #gemini-flash で代替

# 🗑️ /perplexity コマンド削除: コマンドのみの呼び出しは非推奨、/all で代替

# 🗑️ /gpt5 コマンド削除: 専用チャンネル #gpt-premium で代替

# 🗑️ /gemini-2-5-pro コマンド削除: 専用チャンネル #gemini-pro で代替

# 🗑️ /gemini-1-5-pro コマンド削除: 専用チャンネル #gemini1.5pro-chat で代替

    @app_commands.command(name="notion", description="現在のNotionページの内容について質問します（全文高精度処理）")
    @app_commands.describe(query="Notionページに関する質問")
    async def notion_command(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        try:
            # Geniusチャンネルでの使用をチェック（genius-proは除外）
            channel_name = interaction.channel.name.lower()
            if "genius" in channel_name and "genius-pro" not in channel_name and "geniuspro" not in channel_name:
                await interaction.edit_original_response(content="❌ `/notion`コマンドはGenius部屋では使用できません。\n💡 Genius部屋では普通にメッセージを送るだけで自動応答します。")
                return

            page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not page_ids:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return

            target_page_id = page_ids[0]
            user_name = interaction.user.display_name
            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} (via /notion):\n{query}"}}]}}])
            
            # 全文取得（4000文字制限なし）
            await interaction.edit_original_response(content="📖 Notionページ全文を読み込み中...")
            from notion_utils import get_notion_page_text
            full_text = await get_notion_page_text([target_page_id])
            
            if full_text.startswith("ERROR:") or not full_text.strip():
                await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
                return
            
            # チャンク処理：GPT5miniで各チャンクを要約
            await interaction.edit_original_response(content="⚙️ GPT-5miniでチャンク処理中...")
            chunk_summaries = []
            chunk_size = 4000
            for i in range(0, len(full_text), chunk_size):
                chunk = full_text[i:i+chunk_size]
                chunk_prompt = f"以下のテキストから「{query}」に関連する情報を抽出し要約してください。関連情報がない場合は「関連情報なし」と回答。\n\n{chunk}"
                from ai_manager import get_ai_manager
                ai_manager = get_ai_manager()
                if not ai_manager.initialized:
                    ai_manager.initialize(self.bot)
                summary = await ai_manager.ask_ai("gpt5mini", chunk_prompt)
                if "関連情報なし" not in summary:
                    chunk_summaries.append(summary)
            
            if not chunk_summaries:
                await interaction.edit_original_response(content="❌ 質問に関連する情報が見つかりませんでした。")
                return
            
            # O1-Proで統合
            await interaction.edit_original_response(content="🧠 O1-Proで情報を統合中...")
            integration_material = "\n\n---\n\n".join(chunk_summaries)
            integration_prompt = f"以下の複数の情報を統合し、「{query}」に対する一貫した回答を作成してください。\n\n{integration_material}"
            integrated_answer = await ask_o1_pro(self.bot.o1_api_key, integration_prompt)
            
            # Gemini 2.5 Proで最終回答
            await interaction.edit_original_response(content="✨ Gemini 2.5 Proで最終回答を生成中...")
            final_prompt = f"【統合済み情報】\n{integrated_answer}\n\n【ユーザーの質問】\n{query}\n\n上記の統合情報を基に、質問に対する最終的で完全な回答を提供してください。"
            final_answer = await ask_gemini_2_5_pro(final_prompt)
            
            await log_response(target_page_id, final_answer, "Notion高精度処理 (/notionコマンド)")
            await send_long_message(self.bot.openai_client, interaction, f"**🎯 高精度処理による最終回答:**\n{final_answer}", is_followup=False, primary_ai="gpt5mini")

        except Exception as e:
            safe_log("🚨 /notion コマンドでエラー:", e)
            if not interaction.response.is_done():
                await interaction.edit_original_response(content=f"❌ エラーが発生しました: {e}")

    @app_commands.command(name="minna", description="6体のベースAIが議題に同時に意見を出します。")
    @app_commands.describe(prompt="AIに尋ねる議題")
    async def minna_command(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        user_id = str(interaction.user.id)

        # Notionログ記録
        page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
        if page_ids:
            await log_user_message(page_ids[0], interaction.user.display_name, f"/minna {prompt}")

        await interaction.followup.send("🔬 6体のベースAIが意見を生成中…")
        tasks = {name: func(user_id, prompt, history=[]) for name, func in self.BASE_MODELS_FOR_ALL.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        all_responses = ""
        for (name, result) in zip(tasks.keys(), results):
            display_text = f"エラー: {result}" if isinstance(result, Exception) else result
            all_responses += f"🔹 {name}の意見:\n{display_text}\n\n"
            await send_long_message(self.bot.openai_client, interaction, f"**🔹 {name}の意見:**\n{display_text}", is_followup=True)

        # AI回答をNotionに記録
        if page_ids:
            await log_response(page_ids[0], all_responses, "6体ベースAI (/minnaコマンド)")

    @app_commands.command(name="all", description="9体のAI（ベース6体+高機能3体）が議題に同時に意見を出します。")
    @app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
    async def all_command(self, interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
        await interaction.response.defer()

        # Notionログ記録
        page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
        attachment_info = f" (添付: {attachment.filename})" if attachment else ""
        if page_ids:
            await log_user_message(page_ids[0], interaction.user.display_name, f"/all {prompt}{attachment_info}")

        final_query = prompt
        if attachment:
            await interaction.edit_original_response(content="📎 添付ファイルを解析しています…")
            final_query += await analyze_attachment_for_gemini(attachment)

        user_id = str(interaction.user.id)
        await interaction.edit_original_response(content="🔬 9体のAIが初期意見を生成中…")

        tasks = {name: func(user_id, final_query, history=[]) for name, func in self.BASE_MODELS_FOR_ALL.items()}
        adv_models_to_run = {
            "gpt-4o": self.ADVANCED_MODELS_FOR_ALL["gpt-4o"][0],
            "Gemini 2.5 Flash": self.ADVANCED_MODELS_FOR_ALL["Gemini 2.5 Flash"][0],
            "Perplexity": self.ADVANCED_MODELS_FOR_ALL["Perplexity"][0]
        }
        for name, func in adv_models_to_run.items():
            tasks[name] = func(final_query)

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        first_name = list(tasks.keys())[0]
        first_result = results[0]
        first_display_text = f"**🔹 {first_name}の意見:**\n{first_result if not isinstance(first_result, Exception) else f'エラー: {first_result}'}"
        await interaction.edit_original_response(content=first_display_text[:1900])

        all_responses = first_display_text + "\n\n"
        for name, result in list(zip(tasks.keys(), results))[1:]:
            display_text = f"**🔹 {name}の意見:**\n{result if not isinstance(result, Exception) else f'エラー: {result}'}"
            all_responses += display_text + "\n\n"
            await send_long_message(self.bot.openai_client, interaction, display_text, is_followup=True)

        # AI回答をNotionに記録
        if page_ids:
            await log_response(page_ids[0], all_responses, "9体AI (/allコマンド)")

    @app_commands.command(name="chain", description="複数AIがリレー形式で意見を継続していきます")
    @app_commands.describe(topic="連鎖させたい議題")
    async def chain_command(self, interaction: discord.Interaction, topic: str):
        await interaction.response.defer()

        # Notionログ記録
        page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
        if page_ids:
            await log_user_message(page_ids[0], interaction.user.display_name, f"/chain {topic}")

        ai_order = [
            ("GPT", self.BASE_MODELS_FOR_ALL["GPT"]),
            ("Gemini", self.BASE_MODELS_FOR_ALL["Gemini"]),
            ("Claude", self.BASE_MODELS_FOR_ALL["Claude"]),
            ("Llama", self.BASE_MODELS_FOR_ALL["Llama"]),
            ("Grok", self.BASE_MODELS_FOR_ALL["Grok"])
        ]
        user_id = str(interaction.user.id)
        previous_opinion = f"【議題】\n{topic}"
        chain_results = []
        for name, ai_func in ai_order:
            prompt = f"{previous_opinion}\n\nあなたは{name}です。前のAIの意見を参考に、さらに深めてください。"
            try:
                opinion = await ai_func(user_id, prompt, history=[])
            except Exception as e:
                opinion = f"{name}エラー: {e}"
            chain_results.append(f"◆ {name}の意見:\n{opinion}")
            previous_opinion = opinion

        all_chain_results = "\n\n".join(chain_results)
        await send_long_message(self.bot.openai_client, interaction, all_chain_results, is_followup=True)

        # AI回答をNotionに記録
        if page_ids:
            await log_response(page_ids[0], all_chain_results, "5体AIリレー (/chainコマンド)")

            # KB用要約保存 (2つ目のページがあれば)
            if len(page_ids) >= 2:
                try:
                    from ai_manager import get_ai_manager
                    ai_manager = get_ai_manager()
                    if not ai_manager.initialized:
                        ai_manager.initialize(self.bot)

                    summary_prompt = f"以下の5体AIリレー結果を150字以内で要約してください。\n\n{all_chain_results}"
                    kb_summary = await ai_manager.ask_ai("gpt5mini", summary_prompt)

                    new_section_id = await find_latest_section_id(page_ids[1])
                    await append_summary_to_kb(page_ids[1], new_section_id, kb_summary)
                    safe_log("📝 /chain KB要約保存完了: ", new_section_id)
                except Exception as e:
                    safe_log("🚨 /chain KB要約エラー: ", e)

    @app_commands.command(name="critical", description="Notion情報を元に全AIで議論し、多角的な結論を導きます。")
    @app_commands.describe(topic="議論したい議題")
    async def critical_command(self, interaction: discord.Interaction, topic: str):
        await interaction.response.defer()
        try:
            page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not page_ids:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return
            target_page_id = page_ids[0]

            # ユーザー質問をNotionに記録
            await log_user_message(target_page_id, interaction.user.display_name, f"/critical {topic}")

            context = await get_notion_context(self.bot, interaction, target_page_id, topic, model_choice="gpt5mini")
            if not context: return

            prompt_with_context = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}"
            user_id = str(interaction.user.id)
            tasks = {name: func(user_id, prompt_with_context, history=[]) for name, func in self.BASE_MODELS_FOR_ALL.items()}
            for name, (func, wrapper) in self.ADVANCED_MODELS_FOR_ALL.items():
                if name == "Perplexity": tasks[name] = wrapper(func, topic, notion_context=context)
                else: tasks[name] = wrapper(func, prompt_with_context)

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            synthesis_material = "以下のAI群の意見を統合してください。\n\n"
            full_text_results = ""
            for (name, result) in zip(tasks.keys(), results):
                full_response, summary = (result if isinstance(result, tuple) else (result, None))
                display_text = f"エラー: {result}" if isinstance(result, Exception) else (summary or full_response or result)
                full_text_results += f"**🔹 {name}の意見:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response or display_text}\n\n"

            # 並列処理: AI議論表示と統合レポート生成を同時実行

            # AI議論結果を表示（バックグラウンド）
            display_task = asyncio.create_task(
                send_long_message(self.bot.openai_client, interaction, full_text_results, is_followup=False, primary_ai="gpt5")
            )

            # 統合レポート生成（並列）
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            if not ai_manager.initialized:
                ai_manager.initialize(self.bot)

            # 中間レポートと最終レポートを並列生成
            intermediate_task = asyncio.create_task(
                ai_manager.ask_ai("gpt5", synthesis_material, system_prompt="以下の意見の要点だけを抽出し、短い中間レポートを作成してください。")
            )

            # 表示完了を待機
            await display_task

            # 中間レポート完了を待機し、最終レポート生成
            intermediate_report = await intermediate_task
            final_report = await ask_lalah(self.bot.mistral_client, intermediate_report, system_prompt="あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。")
            await interaction.followup.send(f"**Mistral Large (最終統合レポート):**\n{final_report}")

            # 全AI議論結果をNotionに記録
            all_results = full_text_results + f"最終統合レポート:\n{final_report}"
            await log_response(target_page_id, all_results, "AI議論+統合レポート (/criticalコマンド)")

            # KB用要約保存 (2つ目のページがあれば)
            if len(page_ids) >= 2:
                try:
                    summary_prompt = f"以下のAI議論統合レポートを150字以内で要約してください。\n\n{final_report}"
                    kb_summary = await ai_manager.ask_ai("gpt5mini", summary_prompt)

                    new_section_id = await find_latest_section_id(page_ids[1])
                    await append_summary_to_kb(page_ids[1], new_section_id, kb_summary)
                    safe_log("📝 /critical KB要約保存完了: ", new_section_id)
                except Exception as e:
                    safe_log("🚨 /critical KB要約エラー: ", e)

        except Exception as e:
            safe_log("🚨 /critical コマンドでエラー:", e)
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

    @app_commands.command(name="logical", description="Notion情報を元にAIが討論し、論理的な結論を導きます。")
    @app_commands.describe(topic="討論したい議題")
    async def logical_command(self, interaction: discord.Interaction, topic: str):
        await interaction.response.defer()
        try:
            page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not page_ids:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return
            target_page_id = page_ids[0]

            # ユーザー質問をNotionに記録
            await log_user_message(target_page_id, interaction.user.display_name, f"/logical {topic}")

            context = await get_notion_context(self.bot, interaction, target_page_id, topic, model_choice="gpt5mini")
            if not context: return

            prompt_with_context = (f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}")
            user_id = str(interaction.user.id)

            tasks = {
                "肯定論者(gpt-4o)": self.ADVANCED_MODELS_FOR_ALL["gpt-4o"][1](
                    self.ADVANCED_MODELS_FOR_ALL["gpt-4o"][0], prompt_with_context,
                    system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"
                ),
                "否定論者(Perplexity)": self.ADVANCED_MODELS_FOR_ALL["Perplexity"][1](
                    self.ADVANCED_MODELS_FOR_ALL["Perplexity"][0], f"{topic} - 否定的な視点で外部情報を統合し、反対論を提示", notion_context=context
                ),
                "中立分析官(Gemini 2.5 Flash)": self.ADVANCED_MODELS_FOR_ALL["Gemini 2.5 Flash"][1](
                    self.ADVANCED_MODELS_FOR_ALL["Gemini 2.5 Flash"][0], prompt_with_context,
                    system_prompt="あなたはこの議題に関する【中立的な分析官】です。関連する社会的・倫理的な論点を、感情を排して提示してください。"
                ),
                "外部調査(Perplexity)": self.ADVANCED_MODELS_FOR_ALL["Perplexity"][1](
                    self.ADVANCED_MODELS_FOR_ALL["Perplexity"][0], topic, notion_context=context
                )
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)

            synthesis_material = "以下の情報を統合し、最終的な結論を導き出してください。\n\n"
            results_text = ""
            for (name, result) in zip(tasks.keys(), results):
                if isinstance(result, Exception):
                    display_text, full_response = (f"エラー: {result}", f"エラー: {result}")
                elif name == "否定論者(Perplexity)":
                    full_response, summary = result if isinstance(result, tuple) else (result, None)
                    display_text = summary or full_response
                else:
                    full_response, summary = result if isinstance(result, tuple) else (result, None)
                    display_text = summary or full_response
                results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"

            # 並列処理: AI討論表示と統合レポート生成を同時実行

            # AI討論結果を表示（バックグラウンド）
            display_task = asyncio.create_task(
                send_long_message(self.bot.openai_client, interaction, results_text, is_followup=False, primary_ai="gpt5mini")
            )

            # 統合レポート生成（並列）
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            if not ai_manager.initialized:
                ai_manager.initialize(self.bot)

            report_task = asyncio.create_task(
                ai_manager.ask_ai(
                    "gpt5mini", synthesis_material,
                    system_prompt="あなたは統合専用AIです。渡された情報を客観的に統合し、最終的な結論をレポートとしてまとめてください。"
                )
            )

            # 両方の完了を待機
            await display_task
            final_report = await report_task
            await interaction.followup.send(f"** GPT-5mini (最終統合レポート):**\n{final_report}")

            # AI討論結果をNotionに記録
            all_results = results_text + f"最終統合レポート:\n{final_report}"
            await log_response(target_page_id, all_results, "AI討論+統合レポート (/logicalコマンド)")

            # KB用要約保存 (2つ目のページがあれば)
            if len(page_ids) >= 2:
                try:
                    summary_prompt = f"以下のAI討論統合レポートを150字以内で要約してください。\n\n{final_report}"
                    kb_summary = await ai_manager.ask_ai("gpt5mini", summary_prompt)

                    new_section_id = await find_latest_section_id(page_ids[1])
                    await append_summary_to_kb(page_ids[1], new_section_id, kb_summary)
                    safe_log("📝 /logical KB要約保存完了: ", new_section_id)
                except Exception as e:
                    safe_log("🚨 /logical KB要約エラー: ", e)

        except Exception as e:
            safe_log("🚨 /logical コマンドでエラー:", e)
            if not interaction.response.is_done():
                await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)

    @app_commands.command(name="sync", description="管理者専用：スラッシュコマンドをサーバーに同期します。")
    async def sync_command(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.bot.ADMIN_USER_ID:
            await interaction.response.send_message("この操作を実行する権限がありません。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        if not self.bot.GUILD_ID:
            await interaction.followup.send("❌ GUILD_IDが設定されていません。同期できません。", ephemeral=True)
            return
        try:
            guild_obj = discord.Object(id=int(self.bot.GUILD_ID))
            synced_commands = await self.bot.tree.sync(guild=guild_obj)
            await interaction.followup.send(f"✅ コマンドの同期が完了しました。同期数: {len(synced_commands)}件", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 同期中にエラーが発生しました:\n```{e}```", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CommandCog(bot))