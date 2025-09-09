import discord
from discord.ext import commands
import asyncio
import traceback

# --- 必要なモジュールをインポート ---
from notion_utils import NOTION_PAGE_MAP
from utils import safe_log
# channel_tasks.py から、実行したいタスク関数をすべてインポートします
from channel_tasks import (
    run_genius_task,
    run_gpt4o_task,
    run_gpt5_task,
    run_gemini_task,
    run_perplexity_task,
    run_claude_task,
    run_mistral_large_task  # 👈【追加】mistral-largeタスクをインポート
)

class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.content.startswith("/"):
            return

        if message.content.startswith("!"):
            await message.channel.send("💡 `!`コマンドは廃止されました。スラッシュコマンドをご利用ください。")
            return

        channel_name = message.channel.name.lower()
        
        try:
            if channel_name.startswith("genius"):
                if str(message.channel.id) in self.bot.processing_channels:
                    await message.channel.send("⏳ 処理中です...", delete_after=10)
                    return
                self.bot.processing_channels.add(str(message.channel.id))
                asyncio.create_task(run_genius_task(self.bot, message))

            elif channel_name.startswith("claude"):
                await run_claude_task(self.bot, message)

            elif channel_name.startswith("gpt4o"):
                await run_gpt4o_task(self.bot, message)

            elif channel_name.startswith("gpt"):
                await run_gpt5_task(self.bot, message)

            elif channel_name.startswith("gemini"):
                await run_gemini_task(self.bot, message)

            elif channel_name.startswith("perplexity"):
                await run_perplexity_task(self.bot, message)
            
            # ▼▼▼【ここから追加】▼▼▼
            elif channel_name.startswith("mistral-large"):
                await run_mistral_large_task(self.bot, message)
            # ▲▲▲【ここまで追加】▲▲▲

        except Exception as e:
            safe_log(f"🚨 on_message ルーティングエラー:", e)
            traceback.print_exc()
            await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")

async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))