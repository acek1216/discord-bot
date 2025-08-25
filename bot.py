# (ファイル上部のimport文などはそのまま)
# ...

# --- 環境変数の読み込み ---
# Claude関連のキーを削除
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
# (あなたのDiscord Botで必要な他のAPIキー)
# ...

# --- Discord Botの既存コード ---
# (あなたの800行のコードの大部分がここに入ります)
# ...

# --- LINE Bot用Webサーバー（Flask）の初期化と処理 ---
app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

@app.route("/callback", methods=['POST'])
def callback():
    """LINEからのWebhookを受け取るエンドポイント"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=False)
    try:
        handler.handle(body.decode('utf-8'), signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

def create_line_reply(user_message):
    """LINE用のシンプルなオウム返し応答を作成する関数"""
    return f"メッセージ「{user_message}」を受け取りました。"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """LINEのメッセージイベントを処理する関数"""
    with ApiClient(configuration) as api_client:
        reply_text = create_line_reply(event.message.text) # Claude呼び出しをシンプルな関数に変更
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
        )

# --- サーバー起動部分 (Gunicorn + Discordスレッド) ---
# (変更なし)
# ...
