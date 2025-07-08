import discord
from openai import AsyncOpenAI
import google.generativeai as genai
import asyncio
import requests
import os
from dotenv import load_dotenv
import json

# ✅ .env 読み込み（Renderでは自動的に環境変数使用）
load_dotenv()

# ✅ 各種キー取得
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
notion_page_id = os.getenv("NOTION_PAGE_ID")

# ✅ 初期化
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
gemini_model = genai.GenerativeModel("gemini-1.5-pro")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ✅ メモリ管理
philipo_memory = {}
gemini_memory = {}
perplexity_memory = {}

# ✅ Notion投稿関数
async def post_to_notion(user_name, question, answer):
    notion_url = f"https://api.notion.com/v1/blocks/{notion_page_id}/children"
    headers = {
        "Authorization": f"Bearer {notion_api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    data = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"👤 {user_name}:\n{question}"}}
                    ]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🤖 フィリポ:\n{answer}"}}
                    ]
                }
            }
        ]
    }

    # ✅ レスポンスを確認してエラー内容を出力
    response = requests.patch(notion_url, headers=headers, json=data)
    print("📦 Notion投稿レスポンス:", response.status_code, response.text)

# ✅ 各AIへの問い
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

# ✅ 起動確認
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

# ✅ メイン応答処理
@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)
    user_name = message.author.display_name

    if content.startswith("!フィリポ "):
        query = content[len("!フィリポ "):]
        await message.channel.send("🎩 フィリポに伺わせますので、しばしお待ちくださいませ。")
        reply = await ask_philipo(user_id, query)
        await message.channel.send(reply)
        await post_to_notion(user_name, query, reply)

    elif content.startswith("!ジェミニ "):
        query = content[len("!ジェミニ "):]
        await message.channel.send("🎓 ジェミニ先生に尋ねてみますね。")
        reply = await ask_gemini(user_id, query)
        await message.channel.send(reply)

    elif content.startswith("!パープレ "):
        query = content[len("!パープレ "):]
        await message.channel.send("🔎 パープレさんが検索中です…")
        reply = await ask_perplexity(user_id, query)
        await message.channel.send(reply)

# ✅ 実行
client.run(DISCORD_TOKEN)
