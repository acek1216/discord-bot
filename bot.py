import discord
from openai import AsyncOpenAI
import google.generativeai as genai
import asyncio
import requests
import os
from dotenv import load_dotenv
from notion_client import Client

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
notion_page_id = os.getenv("NOTION_PAGE_ID")

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
gemini_model = genai.GenerativeModel("gemini-1.5-pro")
notion = Client(auth=notion_api_key) # Notion公式クライアント

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- メモリ管理 ---
philipo_memory = {}
gemini_memory = {}
perplexity_memory = {}

# --- Notion書き込み関数 ---
# (変更なし)
async def post_to_notion(user_name, question, answer, bot_name="フィリポ"):
    try:
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"👤 {user_name}: {question}"}}
                    ]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🤖 {bot_name}: {answer}"}}
                    ]
                }
            }
        ]
        resp = notion.blocks.children.append(block_id=notion_page_id, children=children)
        print("✅ Notionへの書き込み成功")
    except Exception as e:
        print(f"❌ Notionエラー: {e}")

# --- 各AIモデル呼び出し関数 ---
# (変更なし、ask_philipo, ask_gemini, ask_perplexity)
async def ask_philipo(user_id, prompt):
    history = philipo_memory.get(user_id, [])
    messages = [{"role": "system", "content": "あなたは執事フィリポです。礼儀正しく対応してください。"}] + history + [{"role": "user", "content": prompt}]
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages)
    reply = response.choices[0].message.content
    philipo_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
    return reply

async def ask_gemini(user_id, prompt):
    loop = asyncio.get_event_loop()
    history = gemini_memory.get(user_id, "")
     full_prompt = (
        "あなたは論理と感情の架け橋となるAI教師です。"
        "哲学・構造・言語表現に長けており、質問には冷静かつ丁寧に答えてください。\n\n"
        + history + f"\nユーザー: {prompt}\n先生:"
    )
    response = await loop.run_in_executor(None, gemini_model.generate_content, full_prompt)
    reply = response.text
    gemini_memory[user_id] = full_prompt + reply
    return reply

async def ask_perplexity(user_id, prompt):
    # Perplexity APIは同期的であるため、非同期で実行するためにrun_in_executorを使用
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _sync_ask_perplexity, user_id, prompt
    )

def _sync_ask_perplexity(user_id, prompt):
    history = perplexity_memory.get(user_id, "")
    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "あなたは探索神パープレです。情報収集と構造整理を得意とし、簡潔にお答えします。"},
            {"role": "user", "content": prompt}
        ],
        "stream": False
    }
    headers = {
        "Authorization": f"Bearer {perplexity_api_key}",
        "Content-Type": "application/json"
    }
    response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
    response.raise_for_status() # エラーチェック
    reply = response.json()["choices"][0]["message"]["content"]
    perplexity_memory[user_id] = history + "\n" + prompt + "\n" + reply
    return reply


# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)
    
    # ▼▼▼▼▼【修正点1】ここでuser_nameを定義する ▼▼▼▼▼
    user_name = message.author.display_name
    # ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲

    # フィリポ
    if content.startswith("!フィリポ "):
        query = content[len("!フィリポ "):]
        await message.channel.send("🎩 フィリポに伺わせますので、しばしお待ちくださいませ。")
        reply = await ask_philipo(user_id, query)
        await message.channel.send(reply)
        # ▼▼▼▼▼【修正点2】Notion書き込み処理を追加 ▼▼▼▼▼
        await post_to_notion(user_name, query, reply, bot_name="フィリポ")

    # ジェミニ
    elif content.startswith("!ジェミニ "):
        query = content[len("!ジェミニ "):]
        await message.channel.send("🎓 ジェミニ先生に尋ねてみますね。")
        reply = await ask_gemini(user_id, query)
        await message.channel.send(reply)
        # ▼▼▼▼▼【修正点2】Notion書き込み処理を追加 ▼▼▼▼▼
        await post_to_notion(user_name, query, reply, bot_name="ジェミニ先生")

    # パープレ
    elif content.startswith("!パープレ "):
        query = content[len("!パープレ "):]
        await message.channel.send("🔎 パープレさんが検索中です…")
        reply = await ask_perplexity(user_id, query)
        await message.channel.send(reply)
        # ▼▼▼▼▼【修正点2】Notion書き込み処理を追加 ▼▼▼▼▼
        await post_to_notion(user_name, query, reply, bot_name="パープレさん")
    
    # (三連、逆三連などの他のコマンドは、必要に応じて同様に修正してください)
    elif content.startswith("!逆三連 "):
        query = content[len("!逆三連 "):]
        await message.channel.send("🔎 パープレさんが先陣を切ります…")
        perplexity_reply = await ask_perplexity(user_id, query)
        await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")

        try:
            await message.channel.send("🎓 ジェミニ先生に引き継ぎます…")
            gemini_reply = await ask_gemini(user_id, perplexity_reply)
            await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")
        except Exception as e:
            await message.channel.send(f"⚠️ ジェミニ先生は現在ご多忙のようです。スキップします。({e})")
            gemini_reply = perplexity_reply

        await message.channel.send("🎩 フィリポが最終まとめを行います…")
        philipo_reply = await ask_philipo(user_id, gemini_reply)
        await message.channel.send(f"🎩 **フィリポ** より:\n{philipo_reply}")

        # ✅ Notion記録（フィリポの最終回答のみ）
        await post_to_notion(user_name, query, philipo_reply, bot_name="逆三連(フィリポ)")


# --- 起動 ---
client.run(DISCORD_TOKEN)
