# --- Webサーバー(Flask) & 起動設定 ---
# LINE Botのコールバック処理
@app.post("/callback")
def cb():
    sig = request.headers.get("X-Line-Signature","")
    body = request.get_data()

    # --- ▼▼▼ デバッグ用コードを追加 ▼▼▼ ---
    print("--- LINE Webhook Received ---")
    print(f"Signature Header: {sig}")
    print(f"Request Body: {body.decode('utf-8', 'ignore')}") # UTF-8でデコードして見やすくする
    is_verified = verify_signature(body, sig)
    print(f"Verification Result: {is_verified}")
    print("-----------------------------")
    # --- ▲▲▲ デバッグ用コードはここまで ▲▲▲ ---

    if not is_verified:
        print("署名が無効です。")
        abort(400)
    
    evs = (request.get_json(silent=True) or {}).get("events", [])
    for ev in evs:
        if ev.get("type")=="message" and ev.get("message", {}).get("type")=="text":
            user_text = ev["message"]["text"]
            reply = handle_claude(user_text)
            line_reply(ev.get("replyToken"), [{"type":"text","text": reply}])
    return "OK"
