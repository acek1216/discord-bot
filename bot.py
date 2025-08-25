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

# Discord Botの既存ライブラリ
import discord
from openai import AsyncOpenAI
# (ここにあなたのbot.pyで使われている他の全てのimport文を記載)
# ...

# --- 環境変数の読み込み ---
# (あなたの既存の環境変数読み込みコード)
# ...
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')
CLAUDE_BASE_URL = os.environ.get('CLAUDE_BASE_URL')
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

# --- Discord Bot クライアントの初期化 ---
# (あなたの既存のDiscord Botのクライアント初期化と、800行以上にわたる全ての処理コード)
# client = discord.Client(...)
# @client.event
# async def on_ready(): ...
# @client.event
# async def on_message(message): ...
# ...

# --- LINE Bot用Webサーバー（Flask）の初期化と処理 ---
app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
claude_client = openai.OpenAI(api_key=CLAUDE_API_KEY, base_url=CLAUDE_BASE_URL)

@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのWebhookを受け取るエンドポイント（あなたの修正案を適用）"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True) # as_text=True に修正
    
    print("✅ [LINE Webhook] Received a request.") # ログ出力強化

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("🛑 ERROR: Signature verification failed. Check LINE_CHANNEL_SECRET.")
        abort(400)
    except Exception as e:
        print(f"🛑 ERROR: An error occurred in the callback handler: {e}")
        abort(500)

    print("✅ [LINE Webhook] Request processed successfully, returning 200 OK.")
    return 'OK'

def call_claude_api(user_message):
    """Claudeを17歳の女執事として呼び出す関数"""
    print(f"🤖 [Claude API] Calling Claude API for user: '{user_message}'") # ログ出力強化
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。完璧な執事でありながら、時折年齢相応の表情を見せるのがあなたの魅力です。専門的な知識も披露しますが、必ず執事としての丁寧な言葉遣いを崩さないでください。"
    try:
        chat_completion = claude_client.chat.completions.create(
            model="claude-3-haiku-20240307",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        response = chat_completion.choices[0].message.content
        print("🤖 [Claude API] Successfully received response from Claude.") # ログ出力強化
        return response
    except Exception as e:
        print(f"🛑 ERROR: Claude API Error: {e}")
        return "申し訳ございません、ご主人様。わたくしの思考回路に少し問題が生じたようです…"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """LINEのメッセージイベントを処理する関数"""
    with ApiClient(configuration) as api_client:
        # メッセージ処理を別スレッドに投げる
        threading.Thread(target=process_line_message, args=(event, api_client)).start()

def process_line_message(event, api_client):
    """実際のメッセージ処理と返信を行う関数（バックグラウンドで実行）"""
    reply_text = call_claude_api(event.message.text)
    line_bot_api = MessagingApi(api_client)
    line_bot_api.reply_message_with_http_info(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply_text)]
        )
    )
    print("✅ [LINE Reply] Sent reply to user.") # ログ出力強化

# --- サーバー起動 ---
if __name__ == "__main__":
    # LINE Botサーバーをバックグラウンドで起動
    port = int(os.environ.get("PORT", 8080))
    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port, debug=False))
    flask_thread.daemon = True
    flask_thread.start()

    # Discord Botをメインで起動
    # clientはあなたのDiscord Botのクライアント変数名に合わせてください
    client.run(DISCORD_BOT_TOKEN)
