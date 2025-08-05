import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from dotenv import load_dotenv
import requests # Rekus用
import io
from PIL import Image

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY)

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    """2000文字を超えるメッセージを分割して送信する"""
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- 各AIモデル呼び出し関数 ---

# ▼▼▼ クレイオスは gpt-4-turbo で固定 ▼▼▼
async def ask_kreios(prompt):
    """クレイオス(GPT-4 Turbo)を呼び出す"""
    system_prompt = "あなたは冷静かつ的確な判断力を持つAI、クレイオスです。与えられたテーマについて論理的に回答してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4-turbo",  # 指示通りgpt-4-turboに固定
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"クレイオス(gpt-4-turbo) Error: {e}"

# ▼▼▼ Notion要約専用のgpt-4o関数を新規作成 ▼▼▼
async def ask_gpt4o_summarizer(chunk_text):
    """Notionのチャンク(断片)を要約するためのgpt-4o専用関数"""
    system_prompt = "あなたは、与えられた文章の要点を抽出する専門家です。以下の文章から最も重要な情報を300文字程度で簡潔に要約してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": chunk_text}]
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"GPT-4o Summarizer Error: {e}"

async def ask_minerva(prompt, attachment_parts=[]):
    """ミネルバ(Gemini 1.5 Pro)を呼び出す"""
    system_prompt = "あなたは、社会の秩序と人間の心理を冷徹に分析する女神「ミネルバ」です。あらゆる事象を客観的なデータと潜在的なリスクに基づいて評価し、感情を排した極めてロジカルな視点から回答します。"
    model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction=system_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e:
        return f"ミネルバ(Gemini Pro) Error: {e}"

async def _sync_ask_rekus_sonar(prompt):
    """レキュス(Perplexity Sonar)を呼び出す（同期処理）"""
    system_prompt = "あなたは探索王レキュスです。与えられた情報のみを根拠として、ユーザーの質問に簡潔に答えてください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        return f"レキュス(Sonar Pro) Error: {e}"

async def ask_rekus(prompt):
    """レキュスの非同期ラッパー"""
    return await asyncio.get_event_loop().run_in_executor(None, _sync_ask_rekus_sonar, prompt)


# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users:
        return
    
    # ▼▼▼ !askコマンドのロジックを全面的に刷新 ▼▼▼
    if message.content.startswith("!ask"):
        query = message.content[len("!ask"):].strip()
        if not query:
            await message.channel.send("質問内容を`!ask`に続けて入力してください。")
            return
        
        if not message.attachments:
            await message.channel.send("Notionページのテキストファイルを添付してください。")
            return

        processing_users.add(message.author.id)
        try:
            attachment = message.attachments[0]
            if not attachment.filename.endswith('.txt'):
                await message.channel.send("`.txt`形式のファイルを添付してください。")
                return

            notion_text_bytes = await attachment.read()
            notion_text = notion_text_bytes.decode('utf-8')
            
            await message.channel.send(f"📄 Notionテキスト読み込み完了。")

            # --- ステップ1: gpt-4oによるチャンク毎の個別要約 ---
            await message.channel.send("【ステップ1/3】`gpt-4o`がチャンク毎の要約を開始します...")
            
            chunk_size = 8000  # 1チャンクあたりの文字数
            text_chunks = [notion_text[i:i + chunk_size] for i in range(0, len(notion_text), chunk_size)]
            
            chunk_summaries = []
            summary_tasks = [ask_gpt4o_summarizer(chunk) for chunk in text_chunks]
            
            results = await asyncio.gather(*summary_tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception) or "Error" in result:
                    await message.channel.send(f"⚠️ チャンク {i+1} の要約中にエラーが発生しました。スキップします。")
                    continue
                chunk_summaries.append(result)

            if not chunk_summaries:
                await message.channel.send("❌ 全てのチャンクの要約に失敗しました。処理を中断します。")
                return

            await message.channel.send("✅ `gpt-4o`による個別要約が完了しました。")

            # --- ステップ2: ミネルバによる統合・分析 ---
            await message.channel.send("【ステップ2/3】`ミネルバ`が全要約を統合・分析します...")
            
            combined_summaries_text = "\n\n---\n\n".join(chunk_summaries)
            
            integration_prompt = (
                "あなたは、複数の要約レポートを統合し、一つの首尾一貫したコンテキストにまとめる専門家です。"
                "以下のバラバラな要約レポート群を統合し、分析して、最終的な回答の土台となる一つの背景情報を作成してください。"
                "文字数制限は2000文字です。\n\n"
                "--- 以下、要約レポート群 ---\n"
                f"{combined_summaries_text}"
            )

            final_context = await ask_minerva(integration_prompt)
            if "Error" in final_context:
                await message.channel.send(f"❌ ミネルバによる統合中にエラーが発生しました。処理を中断します。\n`{final_context}`")
                return
            
            await message.channel.send("✅ `ミネルバ`による統合・分析が完了しました。")


            # --- ステップ3: レキュスによる最終回答 ---
            await message.channel.send("【ステップ3/3】`レキュス`が最終回答を生成します...")

            final_answer_prompt = (
                "以下の【背景情報】のみを根拠として、ユーザーからの【質問】に答えてください。\n\n"
                "--- 【背景情報】 ---\n"
                f"{final_context}\n\n"
                "--- 【ユーザーからの質問】 ---\n"
                f"{query}"
            )

            final_answer = await ask_rekus(final_answer_prompt)
            if "Error" in final_answer:
                 await message.channel.send(f"❌ レキュスによる最終回答生成中にエラーが発生しました。\n`{final_answer}`")
                 return

            await send_long_message(message.channel, f"**🤖 レキュスの最終回答:**\n{final_answer}")

        except Exception as e:
            await message.channel.send(f"予期せぬエラーが発生しました: {e}")
        finally:
            if message.author.id in processing_users:
                processing_users.remove(message.author.id)
    
    # ▼▼▼ !kreiosコマンドは gpt-4-turbo で応答 ▼▼▼
    elif message.content.startswith("!kreios"):
        query = message.content[len("!kreios"):].strip()
        if not query:
            await message.channel.send("質問内容を`!kreios`に続けて入力してください。")
            return
        
        processing_users.add(message.author.id)
        try:
            await message.channel.send("🧠 `クレイオス(gpt-4-turbo)`が応答します...")
            reply = await ask_kreios(query)
            await send_long_message(message.channel, reply)
        except Exception as e:
             await message.channel.send(f"予期せぬエラーが発生しました: {e}")
        finally:
            if message.author.id in processing_users:
                processing_users.remove(message.author.id)


# --- 起動 ---
client.run(DISCORD_TOKEN)
