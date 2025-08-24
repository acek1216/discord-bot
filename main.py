# --- Webhookのメイン処理 ---
@app.route("/callback", methods=['POST'])
def callback():
    # --- ▼▼▼ 最終デバッグコードを追加 ▼▼▼ ---
    print("--- Verification Check ---")
    loaded_secret = os.environ.get('LINE_CHANNEL_SECRET', '!!! SECRET NOT FOUND IN ENVIRONMENT !!!')
    print(f"Loaded LINE_CHANNEL_SECRET: '{loaded_secret}'")
    print("--------------------------")
    # --- ▲▲▲ ここまで追加 ▲▲▲ ---

    # リクエストヘッダーから署名検証のための値を取得
    signature = request.headers.get('X-Line-Signature')

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
