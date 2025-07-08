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

# 必要に応じてジェミニ・パープレ関数も残す

@client.event
async def on_ready():
    print(f"✅ Discordログイン: {client.user}")

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
        await post_to_notion(user_name, query, reply)  # ← 公式SDK経由で絶対書き込まれる！

client.run(DISCORD_TOKEN)
