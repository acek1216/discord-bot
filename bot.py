import discord
from openai import AsyncOpenAI
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from mistralai.async_client import MistralAsyncClient
import asyncio
import os
from dotenv import load_dotenv
from notion_client import Client
import requests # Rekus用

# --- 環境変数の読み込み ---
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
perplexity_api_key = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
notion_api_key = os.getenv("NOTION_API_KEY")
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
NOTION_MAIN_PAGE_ID = os.getenv("NOTION_PAGE_ID") 

# Renderの環境変数から対応表を読み込み、辞書を作成
NOTION_PAGE_MAP_STRING = os.getenv("NOTION_PAGE_MAP_STRING", "")
NOTION_PAGE_MAP = {}
if NOTION_PAGE_MAP_STRING:
    try:
        pairs = NOTION_PAGE_MAP_STRING.split(',')
        for pair in pairs:
            if ':' in pair:
                thread_id, page_id = pair.split(':', 1)
                NOTION_PAGE_MAP[thread_id.strip()] = page_id.strip()
    except Exception as e:
        print(f"⚠️ NOTION_PAGE_MAP_STRINGの解析に失敗しました: {e}")

# --- 各種クライアントの初期化 ---
openai_client = AsyncOpenAI(api_key=openai_api_key)
genai.configure(api_key=gemini_api_key)
notion = Client(auth=notion_api_key)
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# --- メモリ管理 ---
gpt_base_memory = {}
gemini_base_memory = {}
mistral_base_memory = {}
processing_users = set()

# --- ヘルパー関数 ---
async def send_long_message(channel, text):
    if not text: return
    if len(text) <= 2000:
        await channel.send(text)
    else:
        for i in range(0, len(text), 2000):
            await channel.send(text[i:i+2000])

# --- Notion連携関数 ---
def _sync_get_notion_page_text(page_id):
    all_text_blocks = []
    next_cursor = None
    while True:
        try:
            response = notion.blocks.children.list(block_id=page_id, start_cursor=next_cursor, page_size=100)
            results = response.get("results", [])
            for block in results:
                if block.get("type") == "paragraph":
                    for rich_text in block.get("paragraph", {}).get("rich_text", []):
                        all_text_blocks.append(rich_text.get("text", {}).get("content", ""))
            if response.get("has_more"):
                next_cursor = response.get("next_cursor")
            else:
                break
        except Exception as e:
            print(f"❌ Notion読み込みエラー: {e}")
            return f"ERROR: Notion API Error - {e}"
    return "\n".join(all_text_blocks)

async def get_notion_page_text(page_id):
    return await asyncio.get_event_loop().run_in_executor(None, _sync_get_notion_page_text, page_id)

async def log_to_notion(page_id, blocks):
    if not page_id: return
    try:
        await asyncio.get_event_loop().run_in_executor(None, lambda: notion.blocks.children.append(block_id=page_id, children=blocks))
    except Exception as e:
        print(f"❌ Notion書き込みエラー: {e}")

async def log_response(page_id, answer, bot_name):
    if not page_id or not answer or isinstance(answer, Exception): return
    chunks = [answer[i:i + 1900] for i in range(0, len(answer), 1900)] if len(answer) > 1900 else [answer]
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"🤖 {bot_name}:\n{chunks[0]}"}}]}}]
    for chunk in chunks[1:]:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk}}]}})
    await log_to_notion(page_id, blocks)

# --- AIモデル呼び出し関数 ---

# グループA：短期記憶型
async def ask_gpt_base(user_id, prompt):
    history = gpt_base_memory.get(user_id, [])
    system_prompt = "あなたは論理と秩序を司る神官「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        reply = response.choices[0].message.content
        new_history = history + [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        if len(new_history) > 10: new_history = new_history[-10:]
        gpt_base_memory[user_id] = new_history
        return reply
    except Exception as e: return f"GPTエラー: {e}"

# (他のグループA, グループBのAI呼び出し関数も同様に定義)
# ... ask_gemini_base, ask_mistral_base ...
# ... ask_kreios, ask_minerva, ask_lalah, ask_rekus ...
# ... ask_pod042, ask_pod153 ...

# Notionコンテキスト生成ヘルパー
async def get_notion_context(channel, page_id, query):
    await channel.send(f"🧠 Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text(page_id)
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await channel.send("❌ Notionページからテキストを取得できませんでした。")
        return None

    await channel.send(f"📄 ミネルバが内容を分割・要約します…")
    chunk_size = 8000
    text_chunks = [notion_text[i:i + chunk_size] for i in range(0, len(notion_text), chunk_size)]
    chunk_summaries = []
    for i, chunk in enumerate(text_chunks):
        await channel.send(f"🔄 チャンク {i+1}/{len(text_chunks)} をミネルバが要約中…")
        # ask_minervaを呼び出す (ここでは簡略化のため直接実装)
        prompt = f"以下の文章を、ユーザーの質問「{query}」の文脈に合わせて2000文字以内で要約してください。\n\n{chunk}"
        # この部分は実際のask_minerva_chunk_summarizerに置き換える
        model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは要約AIです。")
        response = await model.generate_content_async(prompt)
        summary = response.text
        chunk_summaries.append(summary)
        await asyncio.sleep(3)
    
    await channel.send("✅ gpt-4oが統合・分析します…")
    combined = "\n---\n".join(chunk_summaries)
    # ask_gpt4oを呼び出す (簡略化)
    prompt = f"以下の要約群を一つの文脈に統合してください。\n\n{combined}"
    # この部分は実際のask_gpt4o_final_summarizerに置き換える
    model = "gpt-4o"
    response = await openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=2200)
    final_context = response.choices[0].message.content
    return final_context


# --- Discordイベントハンドラ ---
@client.event
async def on_ready(): 
    print(f"✅ ログイン成功: {client.user}")
    print(f"📖 Notion対応表が読み込まれました: {NOTION_PAGE_MAP}")

@client.event
async def on_message(message):
    if message.author.bot or message.author.id in processing_users: return
    
    processing_users.add(message.author.id)
    try:
        content = message.content
        command_name = content.split(' ')[0]
        user_id, user_name = str(message.author.id), message.author.display_name
        query = content[len(command_name):].strip()
        is_admin = user_id == ADMIN_USER_ID
        
        thread_id = str(message.channel.id)
        target_notion_page_id = NOTION_PAGE_MAP.get(thread_id, NOTION_MAIN_PAGE_ID)

        if not target_notion_page_id:
            if command_name.startswith("!"):
                 await message.channel.send("❌ このスレッドに対応するNotionページが設定されておらず、メインページの指定もありません。")
            return

        # グループA：短期記憶型チャットAI
        if command_name in ["!gpt", "!ジェミニ", "!ミストラル", "!ポッド042", "!ポッド153"]:
            reply = None
            bot_name = ""
            if command_name == "!gpt":
                bot_name = "GPT"
                await message.channel.send(f"🤵‍♂️ {bot_name}を呼び出しています…")
                reply = await ask_gpt_base(user_id, query) # 短期記憶を使用
            # ... 他のグループAのAIも同様に実装 ...

            if reply:
                await send_long_message(message.channel, reply)
                if is_admin: await log_response(target_notion_page_id, reply, bot_name)

        # グループB：Notion参照型ナレッジAI
        elif command_name in ["!ask", "!クレイオス", "!ミネルバ", "!レキュス", "!ララァ", "!all", "!クリティカル", "!ロジカル", "!スライド"]:
            # Notionからコンテキストを生成
            final_context = await get_notion_context(message.channel, target_notion_page_id, query)
            if not final_context:
                return # エラーメッセージはget_notion_context内で送信済み
            
            await message.channel.send("✅ コンテキスト生成完了。最終回答を生成します…")
            
            final_prompt = f"以下の【参考情報】を元に、【ユーザーの質問】に回答してください。\n\n【ユーザーの質問】\n{query}\n\n【参考情報】\n{final_context}"
            
            # 各コマンドの最終回答役をここで指定
            final_reply = None
            bot_name = ""
            if command_name in ["!ask", "!クレイオス", "!ミネルバ", "!レキュス", "!ララァ"]: # 単独コマンドの場合
                # ... 各コマンドに応じた最終回答役で final_reply を生成 ...
                # 例: !クレイオスなら ask_kreios(final_prompt)
                bot_name = command_name[1:].capitalize()
                # final_reply = await ask_rekus_final_answerer(final_prompt) # 仮
            
            # ... !all, !クリティカルなどの連携コマンドの処理 ...

            if final_reply:
                await send_long_message(message.channel, f"**🤖 最終回答 (by {bot_name}):**\n{final_reply}")
                if is_admin: await log_response(target_notion_page_id, final_reply, f"{bot_name} (最終回答)")

    except Exception as e:
        print(f"An error occurred in on_message: {e}")
        error_message = str(e)
        display_error = (error_message[:300] + '...') if len(error_message) > 300 else error_message
        await message.channel.send(f"予期せぬエラーが発生しました: ```{display_error}```")
    finally:
        if message.author.id in processing_users:
            processing_users.remove(message.author.id)

# --- 起動 ---
client.run(DISCORD_TOKEN)
