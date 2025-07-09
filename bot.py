import discord
import os
from dotenv import load_dotenv

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# --- Discordクライアントの初期化 ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print("✅--- FINAL DEBUG BOT ---")
    print(f"✅ Logged in as: {client.user}")
    print("✅ Ready to receive !test command.")
    print("--------------------------")

@client.event
async def on_message(message):
    # ボット自身のメッセージは無視
    if message.author.bot:
        return

    # デバッグログ1：メッセージ受信を記録
    print(f"Received message: '{message.content}' from {message.author.name}")

    # !test コマンドにのみ反応
    if message.content == "!test":
        # デバッグログ2：コマンド認識を記録
        print("✅ Command '!test' recognized.")
        
        try:
            # Discordに応答
            await message.channel.send("✅ Test command received. Check Render logs.")
            # デバッグログ3：応答成功を記録
            print("✅ Sent response to Discord channel.")
            
        except Exception as e:
            # デバッグログ4：エラーを記録
            print(f"❌ An error occurred: {e}")
    else:
        # デバッグログ5：コマンド不一致を記録
        print("-> Command not '!test'. Ignoring.")

# --- 起動 ---
print("🚀 Starting final debug bot...")
client.run(DISCORD_TOKEN)
