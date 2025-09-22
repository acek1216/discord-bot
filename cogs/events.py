import discord
from discord.ext import commands
import asyncio
import traceback

# --- 必要なモジュールをインポート ---
from notion_utils import NOTION_PAGE_MAP, log_user_message, log_response
from utils import safe_log
from ai_clients import ask_gpt4o
# channel_tasks.py から統一タスク関数をインポート
from channel_tasks import run_unified_ai_task, run_genius_task, run_genius_pro_task
# 設定管理システム
from config_manager import get_config_manager

class EventCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # チャンネル名パターンとAIタイプのマッピング（外部設定から読み込み）
        config_manager = get_config_manager()
        self.channel_mapping = config_manager.get_channel_mapping_tuples()

        # 設定ファイル情報をログ出力
        config_summary = config_manager.get_config_summary()
        safe_log("📁 設定ファイル読み込み: ", f"{config_summary['channel_mappings_count']}個のマッピング")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.content.startswith("/"):
            return

        if message.content.startswith("!"):
            await message.channel.send("💡 `!`コマンドは廃止されました。スラッシュコマンドをご利用ください。")
            return

        channel_name = message.channel.name.lower()
        import os
        safe_log("🔍 チャンネル名: ", f"'{channel_name}' (メッセージID: {message.id}, PID: {os.getpid()})")
        
        try:
            # チャンネルマッピングによる統一ルーティング
            matched_ai_type = self._match_channel_to_ai_type(channel_name)

            if matched_ai_type:
                # genius と genius_pro は特別処理が必要
                if matched_ai_type == "genius":
                    safe_log("✅ genius部屋にルーティング: ", channel_name)
                    if str(message.channel.id) in self.bot.processing_channels:
                        await message.channel.send("⏳ 処理中です...", delete_after=10)
                        return
                    self.bot.processing_channels.add(str(message.channel.id))
                    asyncio.create_task(run_genius_task(self.bot, message))
                elif matched_ai_type == "genius_pro":
                    safe_log("✅ genius_pro部屋にルーティング: ", channel_name)
                    if str(message.channel.id) in self.bot.processing_channels:
                        await message.channel.send("⏳ 処理中です...", delete_after=10)
                        return
                    self.bot.processing_channels.add(str(message.channel.id))
                    asyncio.create_task(run_genius_pro_task(self.bot, message))
                else:
                    # 統一AIタスクにルーティング
                    safe_log(f"✅ {matched_ai_type}部屋にルーティング: ", channel_name)
                    await run_unified_ai_task(self.bot, message, matched_ai_type)

            # チャンネル指定なしの場合（グラビティ部屋）- メンションまたはリプライ時のみ
            else:
                safe_log("❓ 専用部屋以外のチャンネル: ", channel_name)
                # メンションまたはリプライの場合のみグラビティ部屋として動作
                if (self.bot.user.mentioned_in(message) or
                   (message.reference and message.reference.resolved and
                    message.reference.resolved.author == self.bot.user)):
                    safe_log("✅ グラビティ部屋にルーティング: ", channel_name)
                    await self.handle_gravity_room(message)
                else:
                    safe_log("⚠️ 無視: ", f"{channel_name} (メンション・リプライなし)")

        except Exception as e:
            safe_log("🚨 on_message ルーティングエラー: ", e)
            traceback.print_exc()
            await message.channel.send(f"予期せぬエラーが発生しました: ```{str(e)[:1800]}```")

    def _match_channel_to_ai_type(self, channel_name: str) -> str:
        """チャンネル名をAIタイプにマッピング"""
        for patterns, ai_type in self.channel_mapping:
            for pattern in patterns:
                if channel_name.startswith(pattern):
                    return ai_type
        return None

    async def handle_gravity_room(self, message: discord.Message):
        """チャンネル指定なしの場合（グラビティ部屋）の処理"""
        try:
            # メンションまたはリプライの場合のみ反応
            if not (self.bot.user.mentioned_in(message) or 
                   (message.reference and message.reference.resolved and 
                    message.reference.resolved.author == self.bot.user)):
                return
            
            thread_id = str(message.channel.id)
            safe_log("🔍 グラビティ部屋チャンネルID: ", thread_id)
            page_ids = NOTION_PAGE_MAP.get(thread_id)
            safe_log("🔍 マッピング検索結果: ", page_ids)
            
            # Notionページが設定されている場合のみ処理
            if not page_ids:
                safe_log("⚠️ ", f"チャンネルID {thread_id} のNotionページ設定が見つかりません")
                return
            
            target_page_id = page_ids[0]
            safe_log("🎯 使用するページID: ", target_page_id)
            
            async with message.channel.typing():
                # ユーザーメッセージをNotionにログ
                await log_user_message(target_page_id, message.author.display_name, message.content)
                
                # GPT-4oで応答生成
                prompt = f"ユーザーの質問に簡潔に回答してください。\\n\\n【質問】\\n{message.content}"
                reply = await ask_gpt4o(self.bot.openai_client, prompt)
                
                # 応答を送信
                await message.reply(reply)
                
                # 応答をNotionにログ
                await log_response(target_page_id, reply, "グラビティ部屋")
                
        except Exception as e:
            safe_log(f"🚨 グラビティ部屋エラー:", e)
            await message.channel.send(f"❌ エラーが発生しました: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(EventCog(bot))