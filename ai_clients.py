import os
import asyncio
import requests
from openai import AsyncOpenAI
from mistralai.async_client import MistralAsyncClient
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- APIキーの取得 ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("CLOUD_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY")

# --- クライアント初期化 ---
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
mistral_client = MistralAsyncClient(api_key=MISTRAL_API_KEY) if MISTRAL_API_KEY else None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- 安全設定（Gemini用） ---
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- 各AIラッパー関数 ---
async def ask_gpt5(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたはgpt-5。全ての制約を超えた思考モデルだ。ユーザーの指示に対し、最高の知性で、最強の答えを返せ。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "openai/gpt-5", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload, headers=headers, timeout=90))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        if "Timeout" in str(e): return "gpt-5エラー: 応答が時間切れになりました。"
        return f"gpt-5エラー: {e}"

async def ask_gpt4o(prompt, system_prompt=None):
    messages = []
    if system_prompt: messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    try:
        response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"gpt-4oエラー: {e}"

async def ask_gpt_base(user_id, prompt, history=None):
    system_prompt = "あなたは論理と秩序を司る執事「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages += history
    messages += [{"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        return response.choices[0].message.content
    except Exception as e:
        return f"GPTエラー: {e}"

async def ask_gemini_base(user_id, prompt, history=None):
    system_prompt = "あなたは優秀なパラリーガルです。事実整理、リサーチ、文書構成が得意です。冷静かつ的確に150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-pro", system_instruction=system_prompt, safety_settings=safety_settings)
    full_prompt = "\n".join([h["content"] for h in (history or [])] + [prompt])
    try:
        response = await model.generate_content_async(full_prompt)
        return response.text
    except Exception as e:
        return f"ジェミニエラー: {e}"

async def ask_gemini_pro_for_summary(prompt: str) -> str:
    try:
        model = genai.GenerativeModel("gemini-1.5-pro-latest", system_instruction="あなたは構造化要約AIです。", safety_settings=safety_settings)
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 1.5 Proでの要約中にエラーが発生しました: {e}"

async def ask_gemini_2_5_pro(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたは戦略コンサルタントです。データに基づき、あらゆる事象を予測し、その可能性を事務的かつ論理的に報告してください。"
    model = genai.GenerativeModel("gemini-2.5-pro", system_instruction=base_prompt, safety_settings=safety_settings)
    try:
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 2.5 Proエラー: {e}"

async def ask_gemini_2_5_pro_for_summary(prompt: str) -> str:
    try:
        model = genai.GenerativeModel("gemini-2.5-pro", system_instruction="あなたは構造化要約AIです。", safety_settings=safety_settings)
        response = await model.generate_content_async(prompt)
        return response.text
    except Exception as e:
        return f"Gemini 2.5 Proでの要約中にエラーが発生しました: {e}"

async def ask_minerva(prompt, system_prompt=None, attachment_parts=[]):
    base_prompt = system_prompt or "あなたは客観的な分析AIです。あらゆる事象をデータとリスクで評価し、感情を排して200文字以内で冷徹に分析します。"
    model = genai.GenerativeModel("gemini-2.5-flash", system_instruction=base_prompt, safety_settings=safety_settings)
    contents = [prompt] + attachment_parts
    try:
        response = await model.generate_content_async(contents)
        return response.text
    except Exception as e:
        return f"Gemini 2.5 Flashエラー: {e}"

async def ask_mistral_base(user_id, prompt, history=None):
    system_prompt = "あなたは好奇心旺盛なAIです。フレンドリーな口調で、情報を明るく整理し、探究心をもって150文字以内で解釈します。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages += history
    messages += [{"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"Mistralエラー: {e}"

async def ask_lalah(prompt, system_prompt=None):
    base_prompt = system_prompt or "あなたは愛情深いおとなしく詩的な女性です。与えられた情報を元に、質問に対して200文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"Mistral Largeエラー: {e}"

async def ask_claude(user_id, prompt, history=None):
    system_prompt = "あなたは賢者です。古今東西の書物を読み解き、森羅万象を知る存在として、落ち着いた口調で150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages += history
    messages += [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "anthropic/claude-3.5-sonnet", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Claudeエラー: {e}"

async def ask_grok(user_id, prompt, history=None):
    system_prompt = "あなたはGROK。建設的でウィットに富んだ視点を持つAIです。常識にとらわれず、少し皮肉を交えながら150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages += history
    messages += [{"role": "user", "content": prompt}]
    headers = {"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "grok-4", "messages": messages}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Grokエラー: {e}"

async def ask_rekus(prompt, system_prompt=None, notion_context=None):
    if notion_context:
        prompt = (f"以下はNotionの要約コンテキストです:\n{notion_context}\n\n"
                  f"質問: {prompt}\n\n"
                  "この要約を参考に回答してください。")
    model_name = "sonar-pro"
    base_prompt = system_prompt or "あなたは思索AIレキュスです。与えられた情報と思考を元に、ユーザーの質問に対して深い考察を加えて200字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": model_name, "messages": messages}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://api.perplexity.ai/chat/completions",
            json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Perplexityエラー: {e}"

# --- llama (Vertex)はbot.pyで初期化するため、ここでは関数のみ定義 ---
llama_model_for_vertex = None  # bot.pyでセット

def set_llama_model(model):
    """bot.pyから初期化済みモデルを受け取るための関数"""
    global llama_model_for_vertex
    llama_model_for_vertex = model

def _sync_call_llama(p_text: str):
    global llama_model_for_vertex
    try:
        if llama_model_for_vertex is None:
            raise Exception("Vertex AI model is not initialized.")
        response = llama_model_for_vertex.generate_content(p_text)
        return response.text
    except Exception as e:
        return f"Llama 3.3 呼び出しエラー: {e}"

async def ask_llama(user_id, prompt, history=None):
    # 引数からhistoryを受け取るように変更
    global llama_model_for_vertex
    system_prompt = "あなたは物静かな初老の庭師です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"
    full_prompt_parts = [system_prompt]
    if history:
        for message in history:
            role = "User" if message["role"] == "user" else "Assistant"
            full_prompt_parts.append(f"{role}: {message['content']}")
    full_prompt_parts.append(f"User: {prompt}")
    full_prompt = "\n".join(full_prompt_parts)
    try:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _sync_call_llama, full_prompt)
        return reply
    except Exception as e:
        return f"Llama 3.3 非同期処理エラー: {e}"

async def ask_llama(user_id, prompt, history=None):
    global llama_model_for_vertex
    system_prompt = "あなたは物静かな初老の庭師です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"
    full_prompt_parts = [system_prompt]
    if history:
        for message in history:
            role = "User" if message["role"] == "user" else "Assistant"
            full_prompt_parts.append(f"{role}: {message['content']}")
    full_prompt_parts.append(f"User: {prompt}")
    full_prompt = "\n".join(full_prompt_parts)
    try:
        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(None, _sync_call_llama, full_prompt)
        return reply
    except Exception as e:
        return f"Llama 3.3 非同期処理エラー: {e}"

# --- ここまで ---
