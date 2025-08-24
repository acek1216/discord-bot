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
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')
CLAUDE_BASE_URL = os.environ.get('CLAUDE_BASE_URL') # OpenAI互換APIのエンドポイント

# --- クライアントの初期化 ---
app = Flask(__name__)

# LINE Bot
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# Claude (OpenAI互換)
claude_client = openai.OpenAI(
    api_key=CLAUDE_API_KEY,
    base_url=CLAUDE_BASE_URL,
)

# Discord Bot
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)


# --- Discord Bot の処理 ---
@discord_client.event
async def on_ready():
    print(f'✅ Discord Bot logged in as {discord_client.user}')

@discord_client.event
async def on_message(message):
    if message.author == discord_client.user:
        return
    if message.content.startswith('!hello'):
        await message.channel.send('Hello! こちらは統合サーバーから応答しています。')
    # (ここに以前のDiscord Botの全ての機能を貼り付け、clientをdiscord_clientに書き換えてください)


# --- LINE Bot の処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのWebhookを受け取るエンドポイント"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("署名検証に失敗しました。LINE_CHANNEL_SECRETが正しいか確認してください。")
        abort(400)

    return 'OK'

def call_claude_api(user_message):
    """Claudeを17歳の女執事として呼び出す関数"""
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。完璧な執事でありながら、時折年齢相応の表情を見せるのがあなたの魅力です。専門的な知識も披露しますが、必ず執事としての丁寧な言葉遣いを崩さないでください。"
    try:
        chat_completion = claude_client.chat.completions.create(
            model="claude-3-haiku-20240307",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"🛑 Claude API Error: {e}")
        return "申し訳ございません、ご主人様。わたくしの思考回路に少し問題が生じたようです…"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """LINEのメッセージイベントを処理する関数"""
    with ApiClient(configuration) as api_client:
        reply_text = call_claude_api(event.message.text)
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )

# --- Discord Botをバックグラウンドで起動する設定 ---
def run_discord_bot_in_background():
    """Discord Botを別スレッドで安全に実行するための関数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(discord_client.start(DISCORD_BOT_TOKEN))

if DISCORD_BOT_TOKEN:
    discord_thread = threading.Thread(target=run_discord_bot_in_background)
    discord_thread.daemon = True # メインプログラムが終了したらスレッドも終了する
    discord_thread.start()
    print("🤖 Discord Bot thread started.")

# --- サーバー起動 (ローカルテスト用) ---
if __name__ == "__main__":
    print("🚀 Starting Flask server for local testing...")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
