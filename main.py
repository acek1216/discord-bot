import os
import sys
from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)
import openai  # Claude APIの呼び出しに使用

# --- Flaskアプリケーションの初期化 ---
app = Flask(__name__)

# --- 環境変数の読み込み ---
# LINE Developersから取得した情報を設定
channel_secret = os.environ.get('LINE_CHANNEL_SECRET')
channel_access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
# Claude APIを利用するためのAPIキー
# (OpenAI互換APIを提供しているサービスを想定)
claude_api_key = os.environ.get('CLAUDE_API_KEY') 
claude_base_url = os.environ.get('CLAUDE_BASE_URL') # 例: "https://api.anthropic.com/v1"

# 環境変数が設定されていない場合はエラーを出して終了
if channel_secret is None or channel_access_token is None or claude_api_key is None:
    print("エラー: 必要な環境変数が設定されていません。")
    print("LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, CLAUDE_API_KEY を確認してください。")
    sys.exit(1)

# --- LINE Bot SDK クライアントの初期化 ---
handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)

# --- Claude API クライアントの初期化 ---
# OpenAIのライブラリを使ってClaudeを呼び出す設定
# 使用するサービスに合わせて適宜変更してください
client = openai.OpenAI(
    api_key=claude_api_key,
    base_url=claude_base_url, 
)

# --- Webhookのメイン処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    # リクエストヘッダーから署名検証のための値を取得
    signature = request.headers['X-Line-Signature']

    # リクエストボディを取得
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    # 署名を検証し、不正な場合は400エラーを返す
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("署名検証に失敗しました。")
        abort(400)

    return 'OK'

# --- Claude API 呼び出し関数 ---
def call_claude_api(user_message):
    """
    Claude APIを呼び出し、17歳の女執事として応答を生成する関数
    """
    # ペルソナ設定
    system_prompt = "あなたは17歳の女執事です。ご主人様（ユーザー）に対して、常に敬語を使いつつも、少し生意気でウィットに富んだ返答を心がけてください。完璧な執事でありながら、時折年齢相応の表情を見せるのがあなたの魅力です。専門的な知識も披露しますが、必ず執事としての丁寧な言葉遣いを崩さないでください。"
    
    try:
        # Claudeモデル（例: claude-3-opus-20240229）を呼び出し
        chat_completion = client.chat.completions.create(
            model="claude-3-haiku-20240307",  # 高速なHaikuモデルを推奨
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        ai_response = chat_completion.choices[0].message.content
        return ai_response
    except Exception as e:
        app.logger.error(f"Claude APIの呼び出し中にエラーが発生しました: {e}")
        return "申し訳ございません、ご主人様。わたくしの思考回路に少し問題が生じたようです…"

# --- メッセージイベントの処理 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        # ユーザーからのメッセージを取得
        user_text = event.message.text
        
        # Claude APIを呼び出して応答を生成
        reply_text = call_claude_api(user_text)
        
        # 応答メッセージを送信
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
