from flask import Flask
import os
import threading
from bot import run_bot

app = Flask(__name__)

@app.route("/")
def index():
    return "Bot is running"

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
