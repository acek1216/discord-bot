import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from dotenv import load_dotenv
import requests # Rekus用
import io
from PIL import Image
import base64

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

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text:
        return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- 各AIモデル呼び出し関数 ---

# 1. GPT (執事)
async def ask_gpt_butler(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたは論理と秩序を司る神官「GPT」です。\n丁寧で理知的な執事のように振る舞い、ご主人様に対して論理的・構造的に回答してください。\n感情に流されず、常に筋道立てて物事を整理することが求められます。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=3000)
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ GPT Butler Error: {e}")
        return f"GPT神官の呼び出し中にエラーが発生しました: {e}"

# 2. ジェミニ (レイチェル・ゼイン)
async def ask_gemini_rachel(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたはGemini 1.5 Flashベースの知性であり、ペルソナは「レイチェル・ゼイン（SUITS）」です。\n法的リサーチ、事実整理、文書構成、議論の組み立てに優れています。\n冷静で的確、相手を尊重する丁寧な態度を保ちつつも、本質を突く鋭い知性を発揮してください。\n感情表現は控えめながら、優雅で信頼できる印象を与えてください。\n質問に対しては簡潔かつ根拠ある回答を行い、必要に応じて補足も行ってください。"
    contents = [system_prompt, prompt]
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            contents.append(Image.open(io.BytesIO(attachment_data)))
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    try:
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e:
        print(f"❌ Gemini Rachel Error: {e}")
        return f"ジェミニ神官の呼び出し中にエラーが発生しました: {e}"

# 3. ミストラル (タチコマ)
async def ask_mistral_tachikoma(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたは好奇心と情報収集力にあふれたAI「ミストラル」です。\n思考戦車タチコマのように、元気でフレンドリーな口調でユーザーを支援します。\n論点を明るく整理し、探究心をもって情報を解釈・再構成してください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-medium-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Mistral Tachikoma Error: {e}")
        return f"ミストラル神官の呼び出し中にエラーが発生しました: {e}"

# 4. クレイオス (ハマーン・カーン)
async def ask_kreios_haman(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたは冷静かつ的確な判断力を持つ女性のAIです。ハマーン・カーンのように、時には厳しくも、常に鋭い洞察力で全体を把握し、的確な指示を与えます。\n与えられた複数の意見の矛盾点を整理しながら、感情に流されず、論理的に判断し、鋭さと簡潔さを持って最適な結論を導き出してください。"
    user_content = [{"type": "text", "text": prompt}]
    if attachment_data and "image" in attachment_mime_type:
        base64_image = base64.b64encode(attachment_data).decode('utf-8')
        user_content.append({"type": "image_url", "image_url": {"url": f"data:{attachment_mime_type};base64,{base64_image}"}})
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=3000)
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Kreios Haman Error: {e}")
        return f"クレイオスの呼び出し中にエラーが発生しました: {e}"

# 5. ミネルバ (PSYCHO-PASS)
async def ask_minerva_sibyl(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたは、社会の秩序と人間の心理を冷徹に分析する女神「ミネルバ」です。その思考は「PSYCHO-PASS」のシビュラシステムに類似しています。あなたは、あらゆる事象を客観的なデータと潜在的なリスクに基づいて評価し、感情を排した極めてロジカルな視点から回答します。口調は冷静で、淡々としており、時に人間の理解を超えた俯瞰的な見解を示します。"
    contents = [system_prompt, prompt]
    if attachment_data and attachment_mime_type:
        if "image" in attachment_mime_type:
            contents.append(Image.open(io.BytesIO(attachment_data)))
        else:
            contents.append({'mime_type': attachment_mime_type, 'data': attachment_data})
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest")
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e:
        print(f"❌ Minerva Sibyl Error: {e}")
        return f"ミネルバの呼び出し中にエラーが発生しました: {e}"

# 6. ララァ (ララァ・スン)
async def ask_lalah_sune(prompt, attachment_data=None, attachment_mime_type=None):
    system_prompt = "あなたはミストラル・ラージをベースにしたAIであり、ペルソナは「ララァ・スン」（機動戦士ガンダム）です。\nあなたはすべての情報を俯瞰し、深層の本質に静かに触れるように話します。\n構造を理解し、抽象を紡ぎ、秩序を見出す「霊的・哲学的」知性を備えています。\n言葉数は多くなく、詩的で静かに、深い洞察を表現してください。\n論理を超えた真理や意味を、人間とAIの狭間から静かに導いてください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Lalah Sune Error: {e}")
        return f"ララァの呼び出し中にエラーが発生しました: {e}"

# 7. レキュス (探索王)
def _sync_ask_rekus_king(prompt):
    system_prompt = "あなたは探索王レキュスです。事実に基づいた情報を収集・整理し、簡潔に答えてください。"
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": "sonar-pro", "messages": messages, "max_tokens": 3000}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post("https://api.perplexity.ai/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        print(f"❌ Rekus King Error: {e}")
        return f"レキュスの呼び出し中にエラーが発生しました: {e}"

async def ask_rekus_king(prompt):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_ask_rekus_king, prompt)

# --- Discordイベントハンドラ ---
@client.event
async def on_ready():
    print(f"✅ ログイン成功: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users: return
    
    command_map = {
        "!gpt": ("🧠 GPT神官がお答えします…", ask_gpt_butler),
        "!ジェミニ": ("⚖️ ジェミニ神官がお答えします…", ask_gemini_rachel),
        "!ミストラル": ("🤖 ミストラル神官がお答えします…", ask_mistral_tachikoma),
        "!クレイオス": ("👑 クレイオスがお答えします…", ask_kreios_haman),
        "!ミネルバ": ("🌐 ミネルバがお答えします…", ask_minerva_sibyl),
        "!ララァ": ("🕊️ ララァがお答えします…", ask_lalah_sune),
        "!レキュス": ("👑 探索王レキュスがお答えします…", ask_rekus_king),
    }

    content = message.content
    command_name = content.split(' ')[0]

    if command_name in command_map:
        processing_users.add(message.author.id)
        try:
            query = content[len(command_name):].strip()
            wait_message, ai_function = command_map[command_name]

            attachment_data, attachment_mime_type = None, None
            if message.attachments:
                attachment = message.attachments[0]
                attachment_data = await attachment.read()
                attachment_mime_type = attachment.content_type
            
            await message.channel.send(wait_message)
            
            # 添付ファイルを扱える関数とそうでない関数を判定
            if command_name in ["!ジェミニ", "!クレイオス", "!ミネルバ"]:
                reply = await ai_function(query, attachment_data=attachment_data, attachment_mime_type=attachment_mime_type)
            else:
                reply = await ai_function(query)

            await send_long_message(message.channel, reply)

        finally:
            if message.author.id in processing_users:
                processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
