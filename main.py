import os
from flask import Flask, request

app = Flask(__name__)

@app.route("/callback", methods=['POST'])
def callback():
    # リクエストのヘッダーとボディを取得
    sig = request.headers.get("X-Line-Signature")
    body = request.get_data() # bytes

    # 署名の有無とボディのサイズをログに出力する
    app.logger.info(f"[PING] sig_present={bool(sig)} bytes={len(body)}")

    # 署名検証などを行わず、必ず200 OKを返す
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
