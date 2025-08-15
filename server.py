from flask import Flask
import threading
from bot import run_bot  # ← Discord bot 起動関数

app = Flask(__name__)

@app.route("/")
def health_check():
    return "Bot is alive!", 200

if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    app.run(host="0.0.0.0", port=8080)
