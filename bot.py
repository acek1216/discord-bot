import os
import sys
import threading
import asyncio
from flask import Flask, request, abort

# LINE Bot SDKのライブラリ
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# 各APIのライブラリ
import openai
import discord

# --- 環境変数の読み込み ---
# 全てのキーが存在するか最初に確認
required_keys = ['LINE_CHANNEL_SECRET', 'LINE_CHANNEL_ACCESS_TOKEN', 'DISCORD_BOT_TOKEN', 'CLAUDE_API_KEY', 'CLAUDE_BASE_URL']
if not all(key in os.environ for key in required_keys):
    print(f"FATAL ERROR: 必要な環境変数が不足しています。{required_keys} を確認してください。")
    sys.exit(1)

LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
DISCORD_BOT_TOKEN = os.environ['DISCORD_BOT_TOKEN']
CLAUDE_API_KEY = os.environ['CLAUDE_API_KEY']
CLAUDE_BASE_URL = os.environ['CLAUDE_BASE_URL']

# --- Discord Bot クライアントの初期化 ---
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

@discord_client.event
async def on_ready():
    print(f'✅ Discord Bot logged in as {discord_client.user}')

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user:
        return
    if message.content.startswith('!hello'):
        await message.channel.send('Hello! こちらは統合サーバーから応答しています。')
    # (ここにあなたの他のDiscordコマンドを追加してください)


# --- LINE Bot用Webサーバー（Flask）の初期化と処理 ---
app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
claude_client = openai.OpenAI(api_key=CLAUDE_API_KEY, base_url=CLAUDE_BASE_URL)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=False)
    try:
        handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        print("🛑 ERROR: Signature verification failed.")
        abort(400)
    return 'OK'

def call_claude_api(user_message):
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。"
    try:
        chat_completion = claude_client.chat.completions.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}]
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"🛑 ERROR: Claude API Error: {e}")
        return "申し訳ございません、ご主人様。わたくしの思考回路に少し問題が生じたようです…"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        reply_text = call_claude_api(event.message.text)
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
        )

# --- Discord Botをバックグラウンドで起動する設定 ---
def run_discord_bot_in_background():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(discord_client.start(DISCORD_BOT_TOKEN))
    except Exception as e:
        print(f"🛑 ERROR: Discord bot thread failed: {e}")

if DISCORD_BOT_TOKEN:
    discord_thread = threading.Thread(target=run_discord_bot_in_background)
    discord_thread.daemon = True
    discord_thread.start()

# --- サーバー起動 (ローカルテスト用) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
