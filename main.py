import os
import sys
from flask import Flask, request, abort

# 署名検証とLINE Bot SDKのライブラリ
import hmac
import hashlib
import base64
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# Claude APIのライブラリ
import openai

# --- Flaskアプリケーションの初期化 ---
app = Flask(__name__)

# --- 環境変数の読み込み ---
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
claude_api_key = os.environ.get('CLAUDE_API_KEY')
claude_base_url = os.environ.get('CLAUDE_BASE_URL')

if not all([channel_secret, channel_access_token, claude_api_key]):
    print("エラー: 1つ以上の必要な環境変数が設定されていません。")
    # Gunicorn環境ではsys.exit(1)が即時終了しない場合があるため、ログ出力に留める
    # sys.exit(1)

# --- LINE Bot SDK クライアントの初期化 ---
handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

# --- Claude API クライアントの初期化 ---
client = openai.OpenAI(
    api_key=claude_api_key,
    base_url=claude_base_url,
)

# --- Webhookのメイン処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=False)

    # --- ▼▼▼ 最終診断コード ▼▼▼ ---
    print("--- Final Verification Check ---")
    loaded_secret = os.environ.get('LINE_CHANNEL_SECRET', '!!! SECRET NOT FOUND !!!')
    print(f"Loaded Secret (from GCP Env): '{loaded_secret}'")
    
    is_verified = False
    try:
        hash_val = hmac.new(loaded_secret.encode('utf-8'), body, hashlib.sha256).digest()
        is_verified = hmac.compare_digest(base64.b64decode(signature.encode('utf-8')), hash_val)
        print(f"Manual Verification Result: {is_verified}")
    except Exception as e:
        print(f"Manual Verification Error: {e}")
    
    print("------------------------------")
    # --- ▲▲▲ ここまで ▲▲▲ ---

    if not is_verified:
        # 署名が無効な場合、ここで処理を終了する
        abort(400)

    # 署名が有効な場合のみ、SDKのハンドラを呼び出してメッセージ処理を行う
    try:
        # handler.handle()には文字列を渡す必要があるため、ここではデコードする
        handler.handle(body.decode('utf-8'), signature)
    except Exception as e:
        print(f"Handler Error after verification: {e}")

    return 'OK'

# --- Claude API 呼び出し関数 ---
def call_claude_api(user_message):
    """
    Claude APIを呼び出し、17歳の女執事として応答を生成する関数
    """
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。完璧な執事でありながら、時折年齢相応の表情を見せるのがあなたの魅力です。専門的な知識も披露しますが、必ず執事としての丁寧な言葉遣いを崩さないでください。"
    try:
        chat_completion = client.chat.completions.create(
            model="claude-3-haiku-20240307",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        app.logger.error(f"Claude API Error: {e}")
        return "申し訳ございません、ご主人様。わたくしの思考回路に少し問題が生じたようです…"

# --- メッセージイベントの処理 ---
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

# --- サーバー起動 ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
