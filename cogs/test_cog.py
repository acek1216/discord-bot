import discord
from discord.ext import commands
from discord import app_commands

# 1. Cogクラスを定義
class TestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 2. 最小限のテストコマンドを定義
    @app_commands.command(name="minimum_test", description="最小構成での疎通テスト")
    async def minimum_test_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("最小テスト成功！Cogは読み込まれています。")

# 3. Cogを登録するための必須関数
async def setup(bot):
    await bot.add_cog(TestCog(bot))