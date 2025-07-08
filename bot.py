import discord
from openai import AsyncOpenAI
from notion_client import Client as NotionClient
import os
from dotenv import load_dotenv
import asyncio

# ✅ 環境変数読み込み
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
notion_page_id = os.getenv("NOTION_PAGE_ID")

# ✅ 各クライアント初期化
openai_client = AsyncOpenAI(api_key=openai_api_key)
notion = NotionClient(auth=notion_api_key)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

philipo_memory = {}

# ✅ Notionに記録
async def post_to_notion(user_name, question, answer):
    try:
        notion.blocks.children.append(
            block_id=notion_page_id,
            children=[
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": f"👤 {user_name}:\n{question}"}
                        }]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": f"🤖 フィリポ:\n{answer}"}
                        }]
                    }
                }
            ]
        )
        print("✅ Notion記録成功")
    except Exception as e:
        print("❌ Notionエラー:", e)

# ✅ フィリポの回答生成
async def ask_philipo(user_id, prompt):
    history = philipo_memory.get(user_id, [])
    messages = [{"role": "system", "content": "あなたは執事フィリポです。礼儀正しく答えてください。"}] + history + [{"role": "user", "content": prompt}]
    response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages)
    reply = response.choices[0].message.content
    philipo_memory[user_id] = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
    return reply

# ✅ 起動ログ
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

# ✅ メッセージ処理
@client.event
async def on_message(message):
    if message.author.bot:
        return

    content = message.content
    user_id = str(message.author.id)
    user_name = message.author.display_name

    if content.startswith("!フィリポ "):
        query = content[len("!フィリポ "):]
        await message.channel.send("🎩 フィリポに伺わせます。")
        reply = await ask_philipo(user_id, query)
        await message.channel.send(reply)
        await post_to_notion(user_name, query, reply)

# ✅ Bot実行
client.run(DISCORD_TOKEN)
