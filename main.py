from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "Claude Bot is running!"

if __name__ == "__main__":
    t = threading.Thread(target=client.run, args=(DISCORD_TOKEN,))
    t.start()

    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
