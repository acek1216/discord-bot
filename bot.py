import discord
from openai import AsyncOpenAI
import google.generativeai as genai
import asyncio
import requests
import os
from dotenv import load_dotenv
from notion_client import Client  # 公式SDK

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
notion_page_id = os.getenv("NOTION_PAGE_ID")

openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
gemini_model = genai.GenerativeModel("gemini-1.5-pro")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# Notion公式クライアント
notion = Client(auth=notion_api_key)

philipo_memory = {}
gemini_memory = {}
perplexity_memory = {}

# Notionに「テキストブロックを追加」する関数
async def post_to_notion(user_name, question, answer):
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
                        {"type": "text", "text": {"content": f"🤖 フィリポ: {answer}"}}
                    ]
                }
            }
        ]
        # ページIDに子ブロックを追加（公式推奨）
        resp = notion.blocks.children.append(block_id=notion_page_id, children=children)
        print("✅ Notionレスポンス:", resp)
    except Exception as e:
        print("❌ Notionエラー:", e)

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
    full_prompt = history + f"\nユーザー: {prompt}\n先生:"
    response = await loop.run_in_executor(None, gemini_model.generate_content, full_prompt)
    reply = response.text
    gemini_memory[user_id] = full_prompt + reply
    return reply

async def ask_perplexity(user_id, prompt):
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
    reply = response.json()["choices"][0]["message"]["content"]
    perplexity_memory[user_id] = history + "\n" + prompt + "\n" + reply
    return reply

# ✅ 起動ログ
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

# ✅ メイン処理
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)
    # ファイル処理（省略可）

    # フィリポ
    if content.startswith("!フィリポ "):
        query = content[len("!フィリポ "):]
        await message.channel.send("🎩 フィリポに伺わせますので、しばしお待ちくださいませ。")
        reply = await ask_philipo(user_id, query)
        await message.channel.send(reply)

    # ジェミニ
    elif content.startswith("!ジェミニ "):
        query = content[len("!ジェミニ "):]
        await message.channel.send("🎓 ジェミニ先生に尋ねてみますね。")
        reply = await ask_gemini(user_id, query)
        await message.channel.send(reply)

    # パープレ
    elif content.startswith("!パープレ "):
        query = content[len("!パープレ "):]
        await message.channel.send("🔎 パープレさんが検索中です…")
        reply = await ask_perplexity(user_id, query)
        await message.channel.send(reply)

    # みんなに
    elif content.startswith("!みんなで "):
        query = content[len("!みんなで "):]
        await message.channel.send("🧠 みんなに質問を送ります…")

        philipo_reply = await ask_philipo(user_id, query)
        await message.channel.send(f"🧤 **フィリポ** より:\n{philipo_reply}")

        gemini_reply = await ask_gemini(user_id, query)
        await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")

        perplexity_reply = await ask_perplexity(user_id, query)
        await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")

    # 三連モード（順番引き継ぎ風）
    
    elif content.startswith("!三連 "):
        query = content[len("!三連 "):]
        await message.channel.send("🎩 フィリポに伺わせますので、しばしお待ちくださいませ。")
        philipo_reply = await ask_philipo(user_id, query)
        await message.channel.send(f"🧤 **フィリポ** より:\n{philipo_reply}")

        try:
            await message.channel.send("🎓 ジェミニ先生に引き継ぎます…")
            gemini_reply = await ask_gemini(user_id, philipo_reply)
            await message.channel.send(f"🎓 **ジェミニ先生** より:\n{gemini_reply}")
        except Exception as e:
            await message.channel.send("⚠️ ジェミニ先生は現在ご多忙のようです。スキップします。")
            gemini_reply = philipo_reply  # フィリポの返答を次に渡す

        await message.channel.send("🔎 パープレさんに情報確認を依頼します…")
        perplexity_reply = await ask_perplexity(user_id, gemini_reply)
        await message.channel.send(f"🔎 **パープレさん** より:\n{perplexity_reply}")

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
            await message.channel.send("⚠️ ジェミニ先生は現在ご多忙のようです。スキップします。")
            gemini_reply = perplexity_reply

        await message.channel.send("🎩 フィリポが最終まとめを行います…")
        philipo_reply = await ask_philipo(user_id, gemini_reply)
        await message.channel.send(f"🎩 **フィリポ** より:\n{philipo_reply}")

        # ✅ Notion記録（フィリポの最終回答のみ）
        await post_to_notion(user_name, query, philipo_reply)


# ✅ 起動
client.run(DISCORD_TOKEN)
