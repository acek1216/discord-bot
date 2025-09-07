# cogs/commands.py (最小テスト用)

import discord
from discord.ext import commands
from discord import app_commands

# ▼▼▼ 他のファイルからのインポートをすべて削除（テストのため） ▼▼▼
# from ai_clients import ...
# from notion_utils import ...
# from utils import ...

class SlashCommands(commands.Cog):
    def __init__(self, client):
        self.client = client
        print("--- [DEBUG] Minimal commands.py Cog Initialized ---")

    # ▼▼▼ テスト用の最小コマンド ▼▼▼
    @app_commands.command(name="command_ping", description="commands.pyの読み込みテスト")
    async def command_ping(self, interaction: discord.Interaction):
        await interaction.response.send_message("Pong from commands.py!")

async def setup(bot):
    await bot.add_cog(SlashCommands(bot))
