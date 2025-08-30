# web.py

from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "Web service is running."

if __name__ == "__main__":
    # Cloud RunがPORT環境変数を設定するので、それに従う
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
