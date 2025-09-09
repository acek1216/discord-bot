import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import os

# --- 各モジュールから必要な関数をインポート ---
from ai_clients import (
    ask_gpt_base, ask_gemini_base, ask_mistral_base, ask_claude, ask_llama, ask_grok,
    ask_gpt4o, ask_minerva, ask_rekus, ask_gpt5, ask_gemini_2_5_pro,
    ask_lalah
)
from notion_utils import NOTION_PAGE_MAP, log_to_notion, log_response
from utils import (
    safe_log, send_long_message, analyze_attachment_for_gpt5,
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
            "Gemini": ask_gemini_base, # ask_gemini_baseは元から'history'なので修正不要
            "Mistral": lambda user_id, prompt, history=None: ask_mistral_base(self.bot.mistral_client, user_id, prompt, history),
            "Claude": lambda user_id, prompt, history=None: ask_claude(self.bot.openrouter_api_key, user_id, prompt, history),
            "Llama": lambda user_id, prompt, history=None: ask_llama(self.bot.llama_model, user_id, prompt, history),
            "Grok": lambda user_id, prompt, history=None: ask_grok(self.bot.grok_api_key, user_id, prompt, history)
        }
        self.ADVANCED_MODELS_FOR_ALL = {
            "gpt-4o": (lambda p, **kwargs: ask_gpt4o(self.bot.openai_client, p, **kwargs),
                       lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Gemini 2.5 Flash": (ask_minerva,
                                 lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Perplexity": (lambda p, **kwargs: ask_rekus(self.bot.perplexity_api_key, p, **kwargs),
                           lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "Gemini 2.5 Pro": (ask_gemini_2_5_pro,
                               lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs)),
            "gpt-5": (lambda p, **kwargs: ask_gpt5(self.bot.openrouter_api_key, p, **kwargs),
                      lambda af, p, **kwargs: get_full_response_and_summary(self.bot.openrouter_api_key, af, p, **kwargs))
        }

    # (以降のコマンド定義は変更ありません)
    @app_commands.command(name="gpt", description="GPT(gpt-3.5-turbo)と短期記憶で対話します")
    async def gpt_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["GPT"], "GPT-3.5-Turbo")

    @app_commands.command(name="gemini", description="Gemini(1.5-flash)と短期記憶で対話します")
    async def gemini_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["Gemini"], "Gemini-1.5-Flash")

    @app_commands.command(name="mistral", description="Mistral(medium)と短期記憶で対話します")
    async def mistral_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["Mistral"], "Mistral-Medium")

    @app_commands.command(name="claude", description="Claude(3.5 Sonnet)と短期記憶で対話します")
    async def claude_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["Claude"], "Claude-3.5-Sonnet")

    @app_commands.command(name="llama", description="Llama(3.3 70b)と短期記憶で対話します")
    async def llama_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["Llama"], "Llama-3.3-70B")

    @app_commands.command(name="grok", description="Grokと短期記憶で対話します")
    async def grok_command(self, interaction: discord.Interaction, prompt: str):
        await simple_ai_command_runner(self.bot, interaction, prompt, self.BASE_MODELS_FOR_ALL["Grok"], "Grok")

    @app_commands.command(name="gpt-4o", description="GPT-4oを単体で呼び出します。")
    async def gpt4o_command(self, interaction: discord.Interaction, prompt: str):
        func = lambda p: ask_gpt4o(self.bot.openai_client, p)
        await advanced_ai_simple_runner(self.bot, interaction, prompt, func, "GPT-4o")

    @app_commands.command(name="gemini-2-5-flash", description="Gemini 2.5 Flashを単体で呼び出します。")
    async def gemini_2_5_flash_command(self, interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
        await interaction.response.defer()
        attachment_parts = []
        if attachment:
            attachment_parts = [{'mime_type': attachment.content_type, 'data': await attachment.read()}]
        reply = await ask_minerva(prompt, attachment_parts=attachment_parts)
        await send_long_message(self.bot.openai_client, interaction, reply, is_followup=True)

    @app_commands.command(name="perplexity", description="Perplexityを単体で呼び出します。")
    async def perplexity_command(self, interaction: discord.Interaction, prompt: str):
        func = lambda p: ask_rekus(self.bot.perplexity_api_key, p)
        await advanced_ai_simple_runner(self.bot, interaction, prompt, func, "Perplexity")

    @app_commands.command(name="gpt5", description="GPT-5を単体で呼び出します。")
    async def gpt5_command(self, interaction: discord.Interaction, prompt: str):
        func = lambda p: ask_gpt5(self.bot.openrouter_api_key, p)
        await advanced_ai_simple_runner(self.bot, interaction, prompt, func, "gpt-5")

    @app_commands.command(name="gemini-2-5-pro", description="Gemini 2.5 Proを単体で呼び出します。")
    async def gemini_pro_1_5_command(self, interaction: discord.Interaction, prompt: str):
        await advanced_ai_simple_runner(self.bot, interaction, prompt, ask_gemini_2_5_pro, "Gemini 2.5 Pro")

    @app_commands.command(name="mistrallarge", description="Mistral Largeと単体で対話します。")
    async def mistrallarge_command(self, interaction: discord.Interaction, prompt: str):
        func = lambda p: ask_lalah(self.bot.mistral_client, p)
        await advanced_ai_simple_runner(self.bot, interaction, prompt, func, "Mistral Large")

    @app_commands.command(name="notion", description="現在のNotionページの内容について質問します")
    @app_commands.describe(query="Notionページに関する質問")
    async def notion_command(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        try:
            page_ids = NOTION_PAGE_MAP.get(str(interaction.channel.id))
            if not page_ids:
                await interaction.edit_original_response(content="❌ このチャンネルはNotionページにリンクされていません。")
                return

            target_page_id = page_ids[0]
            user_name = interaction.user.display_name
            await log_to_notion(target_page_id, [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"👤 {user_name} (via /notion):\n{query}"}}]}}])
            
            notion_context = await get_notion_context(self.bot, interaction, target_page_id, query, model_choice="gpt")
            if not notion_context:
                return

            prompt_with_context = (f"【ユーザーの質問】\n{query}\n\n【参考情報】\n{notion_context}")
            await interaction.edit_original_response(content="⏳ gpt-5が最終回答を生成中です...")
            reply = await ask_gpt5(self.bot.openrouter_api_key, prompt_with_context)

            await log_response(target_page_id, reply, "gpt-5 (/notionコマンド)")
            await send_long_message(self.bot.openai_client, interaction, f"** 最終回答 (by gpt-5):**\n{reply}", is_followup=False)

        except Exception as e:
            safe_log("🚨 /notion コマンドでエラー:", e)
            if not interaction.response.is_done():
                await interaction.edit_original_response(content=f"❌ エラーが発生しました: {e}")

    @app_commands.command(name="minna", description="6体のベースAIが議題に同時に意見を出します。")
    @app_commands.describe(prompt="AIに尋ねる議題")
    async def minna_command(self, interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        user_id = str(interaction.user.id)
        await interaction.followup.send("🔬 6体のベースAIが意見を生成中…")
        tasks = {name: func(user_id, prompt, history=[]) for name, func in self.BASE_MODELS_FOR_ALL.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for (name, result) in zip(tasks.keys(), results):
            display_text = f"エラー: {result}" if isinstance(result, Exception) else result
            await send_long_message(self.bot.openai_client, interaction, f"**🔹 {name}の意見:**\n{display_text}", is_followup=True)

    @app_commands.command(name="all", description="9体のAI（ベース6体+高機能3体）が議題に同時に意見を出します。")
    @app_commands.describe(prompt="AIに尋ねる議題", attachment="補足資料として画像を添付")
    async def all_command(self, interaction: discord.Interaction, prompt: str, attachment: discord.Attachment = None):
        await interaction.response.defer()
        final_query = prompt
        if attachment: 
            await interaction.edit_original_response(content="📎 添付ファイルを解析しています…")
            final_query += await analyze_attachment_for_gpt5(self.bot.openai_client, attachment)
        
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

        for name, result in list(zip(tasks.keys(), results))[1:]:
            display_text = f"**🔹 {name}の意見:**\n{result if not isinstance(result, Exception) else f'エラー: {result}'}"
            await send_long_message(self.bot.openai_client, interaction, display_text, is_followup=True)

    @app_commands.command(name="chain", description="複数AIがリレー形式で意見を継続していきます")
    @app_commands.describe(topic="連鎖させたい議題")
    async def chain_command(self, interaction: discord.Interaction, topic: str):
        await interaction.response.defer()
        ai_order = [
            ("GPT", self.BASE_MODELS_FOR_ALL["GPT"]),
            ("Gemini", self.BASE_MODELS_FOR_ALL["Gemini"]),
            ("Mistral", self.BASE_MODELS_FOR_ALL["Mistral"]),
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
        await send_long_message(self.bot.openai_client, interaction, "\n\n".join(chain_results), is_followup=True)

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
            
            context = await get_notion_context(self.bot, interaction, target_page_id, topic, model_choice="gemini")
            if not context: return

            await interaction.edit_original_response(content=" 11体のAIが初期意見を生成中…")
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
            
            await send_long_message(self.bot.openai_client, interaction, full_text_results, is_followup=False)
            await interaction.followup.send(" gpt-5が中間レポートを作成します…")
            intermediate_report = await ask_gpt5(self.bot.openrouter_api_key, synthesis_material, system_prompt="以下の意見の要点だけを抽出し、短い中間レポートを作成してください。")
            await interaction.followup.send(" Mistral Largeが最終統合を行います…")
            final_report = await ask_lalah(self.bot.mistral_client, intermediate_report, system_prompt="あなたは統合専用AIです。渡された中間レポートを元に、最終的な結論を500文字以内でレポートしてください。")
            await interaction.followup.send(f"** Mistral Large (最終統合レポート):**\n{final_report}")
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

            context = await get_notion_context(self.bot, interaction, target_page_id, topic, model_choice="gemini")
            if not context: return

            await interaction.edit_original_response(content="⚖️ 内部討論と外部調査を並列で開始します…")
            prompt_with_context = (f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{topic}\n\n【参考情報】\n{context}")
            user_id = str(interaction.user.id)
            
            tasks = {
                "肯定論者(gpt-4o)": self.ADVANCED_MODELS_FOR_ALL["gpt-4o"][1](
                    self.ADVANCED_MODELS_FOR_ALL["gpt-4o"][0], prompt_with_context,
                    system_prompt="あなたはこの議題の【肯定論者】です。議題を推進する最も強力な論拠を提示してください。"
                ),
                "否定論者(Grok)": self.BASE_MODELS_FOR_ALL["Grok"](
                    user_id, f"{prompt_with_context}\n\n上記を踏まえ、あなたはこの議題の【否定論者】として、議題に反対する最も強力な反論を、常識にとらわれず提示してください。", history=[]
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
                elif name == "否定論者(Grok)":
                    display_text, full_response = (result, result)
                else:
                    full_response, summary = result if isinstance(result, tuple) else (result, None)
                    display_text = summary or full_response
                results_text += f"**{name}:**\n{display_text}\n\n"
                synthesis_material += f"--- [{name}の意見] ---\n{full_response}\n\n"

            await send_long_message(self.bot.openai_client, interaction, results_text, is_followup=False)
            await interaction.followup.send(" gpt-5が最終統合を行います…")
            final_report = await ask_gpt5(
                self.bot.openrouter_api_key, synthesis_material,
                system_prompt="あなたは統合専用AIです。渡された情報を客観的に統合し、最終的な結論をレポートとしてまとめてください。"
            )
            await interaction.followup.send(f"** gpt-5 (最終統合レポート):**\n{final_report}")
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