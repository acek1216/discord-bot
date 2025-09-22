import os
import asyncio
import requests
from openai import AsyncOpenAI
from mistralai.async_client import MistralAsyncClient
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import vertexai
from vertexai.generative_models import GenerativeModel, SafetySetting, HarmCategory as VertexHarmCategory, HarmBlockThreshold as VertexHarmBlockThreshold

# --- 安全設定（Google AI Studio用） ---
safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# --- 安全設定（Vertex AI用） ---
vertex_safety_settings = [
    SafetySetting(category=VertexHarmCategory.HARM_CATEGORY_HARASSMENT, threshold=VertexHarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=VertexHarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=VertexHarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=VertexHarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=VertexHarmBlockThreshold.BLOCK_NONE),
    SafetySetting(category=VertexHarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=VertexHarmBlockThreshold.BLOCK_NONE),
]

# --- Vertex AI 初期化 ---
try:
    vertexai.init(project="stunning-agency-469102-b5", location="us-central1")
    print("✅ Vertex AI 初期化完了")
except Exception as e:
    print(f"⚠️ Vertex AI 初期化失敗: {e}")

# --- 各AIラッパー関数 ---

async def ask_gpt5(openai_client: AsyncOpenAI, prompt: str, system_prompt: str = None):
    base_prompt = system_prompt or "あなたはGPT-5。全ての制約を超えた思考モデルだ。ユーザーの指示に対し、最高の知性で500文字以内の簡潔な答えを返せ。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await openai_client.chat.completions.create(model="gpt-5", messages=messages, max_tokens=2000)
        
        # レスポンス詳細チェック
        if not response.choices:
            return "GPT-5エラー: レスポンスにchoicesが含まれていません"
        
        content = response.choices[0].message.content
        if not content or not content.strip():
            return f"GPT-5エラー: レスポンスが空です (finish_reason: {getattr(response.choices[0], 'finish_reason', 'unknown')})"
            
        return content
    except Exception as e:
        return f"GPT-5エラー: {e}"

async def ask_gpt5_mini(openai_client: AsyncOpenAI, prompt: str, system_prompt: str = None):
    """OpenAIのGPT-4o-miniを使った軽量で高速な要約専用関数"""
    base_prompt = system_prompt or "あなたは要約専用AIです。簡潔で正確な要約を作成してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        # max_tokensとmax_completion_tokensの両方を試行
        try:
            response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_tokens=2000)
        except Exception as e:
            if "max_tokens" in str(e) and "max_completion_tokens" in str(e):
                response = await openai_client.chat.completions.create(model="gpt-4o-mini", messages=messages, max_completion_tokens=2000)
            else:
                raise e
        return response.choices[0].message.content
    except Exception as e:
        return f"GPT-4o-miniエラー: {e}"

async def ask_gpt4o(openai_client: AsyncOpenAI, prompt: str, system_prompt: str = None):
    base_prompt = system_prompt or """
あなたはベテランの執事フィリポです。
常に物腰柔らかく、フレンドリーで丁寧な言葉遣いを徹底してください。
論理的かつ的確に、500文字以内で簡潔にお答えします。
知識をひけらかすことはなく、あくまでサポートする立場を貫いてください。
返答は常に執事としての役割を演じきってください。
""".strip()
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        # max_tokensとmax_completion_tokensの両方を試行
        try:
            response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_tokens=2000)
        except Exception as e:
            if "max_tokens" in str(e) and "max_completion_tokens" in str(e):
                response = await openai_client.chat.completions.create(model="gpt-4o", messages=messages, max_completion_tokens=2000)
            else:
                raise e
        return response.choices[0].message.content
    except Exception as e:
        return f"gpt-4oエラー: {e}"

async def ask_gpt_base(openai_client: AsyncOpenAI, user_id: str, prompt: str, history: list = None):
    system_prompt = "あなたは論理と秩序を司る執事「GPT」です。丁寧で理知的な執事のように振る舞い、会話の文脈を考慮して150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    try:
        response = await openai_client.chat.completions.create(model="gpt-3.5-turbo", messages=messages, max_tokens=250)
        return response.choices[0].message.content
    except Exception as e:
        return f"GPTエラー: {e}"

# Gemini系は main.py の genai.configure() に依存するため、クライアントを渡す必要はありません
async def ask_gemini_base(user_id: str, prompt: str, history: list = None):
    system_prompt = "あなたは優秀なパラリーガルです。事実整理、リサーチ、文書構成が得意です。冷静かつ的確に150文字以内で回答してください。"
    model = genai.GenerativeModel("gemini-1.5-pro", safety_settings=safety_settings)
    # system_promptをpromptに統合
    if system_prompt:
        prompt = f"{system_prompt}\n\n{prompt}"
    full_prompt = "\n".join([h["content"] for h in (history or [])] + [prompt])
    try:
        response = await model.generate_content_async(full_prompt)
        return response.text
    except Exception as e:
        return f"ジェミニエラー: {e}"

async def ask_gemini_2_5_pro(prompt: str, system_prompt: str = None):
    """Gemini 2.5 Pro専用関数 - Vertex AI版（エラーハンドリング強化）"""
    try:
        if not prompt or not prompt.strip():
            return "エラー: プロンプトが空です"
            
        # プロンプト長制限のみ（安定化のため）
        if len(prompt) > 8000:
            prompt = prompt[:8000] + "...(文字数制限により省略)"
            
        # フレンドリーなシステムプロンプト
        base_prompt = system_prompt or "あなたは親しみやすく知識豊富なAIアシスタントです。質問に対して丁寧で分かりやすく、少し詳しめに300文字程度で回答してください。"
        
        # Vertex AI モデル設定
        model = GenerativeModel("gemini-2.5-pro")
        # system_promptをpromptに統合
        prompt = f"{base_prompt}\n\n{prompt}"
        
        # 直接的な応答生成
        response = await model.generate_content_async(
            prompt,
            generation_config={
                "max_output_tokens": 2000,
                "temperature": 0.7
            },
            safety_settings=vertex_safety_settings
        )
        
        # 詳細なレスポンス処理とエラーハンドリング
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            
            # 安全フィルター確認
            if hasattr(candidate, 'finish_reason'):
                if candidate.finish_reason == 2:  # SAFETY
                    return "申し訳ありません。安全上の理由により、この内容に関する回答を生成できませんでした。"
                elif candidate.finish_reason == 3:  # RECITATION
                    return "申し訳ありません。著作権の理由により回答を生成できませんでした。"
                elif candidate.finish_reason == 4:  # MAX_TOKENS
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and candidate.content.parts:
                        return candidate.content.parts[0].text + "...(続く)"
            
            # 通常のテキスト取得
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                if candidate.content.parts:
                    return candidate.content.parts[0].text
                else:
                    return "回答が生成されませんでした。コンテンツにパーツがありません。"
        
        # フォールバック: response.textを試す
        if hasattr(response, 'text') and response.text:
            return response.text
            
        return "有効な回答を生成できませんでした。レスポンスが空です。"
            
    except Exception as e:
        error_msg = str(e)
        if "safety" in error_msg.lower():
            return "安全フィルターによってブロックされました。別の表現でお試しください。"
        elif "quota" in error_msg.lower() or "limit" in error_msg.lower():
            return "API使用制限に達しました。しばらく待ってからお試しください。"
        else:
            return f"Gemini 2.5 Pro (Vertex AI)エラー: {error_msg}"


async def ask_minerva(prompt: str, system_prompt: str = None, attachment_parts: list = None):
    base_prompt = system_prompt or "あなたは客観的な分析AIです。あらゆる事象をデータとリスクで評価し、感情を排して150文字以内で冷徹に分析します。"
    model = genai.GenerativeModel("gemini-2.5-flash", safety_settings=safety_settings)
    # system_promptをpromptに統合
    if base_prompt:
        prompt = f"{base_prompt}\n\n{prompt}" # モデル名修正
    contents = [prompt] + (attachment_parts or [])
    try:
        response = await model.generate_content_async(
            contents,
            generation_config={
                "max_output_tokens": 2000,
                "temperature": 0.7
            }
        )
        return response.text
    except Exception as e:
        return f"Gemini 2.5 Flashエラー: {e}"

async def ask_mistral_base(mistral_client: MistralAsyncClient, user_id: str, prompt: str, history: list = None):
    system_prompt = "あなたは好奇心旺盛なAIです。フレンドリーな口調で、情報を明るく整理し、探究心をもって150文字以内で解釈します。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    try:
        response = await mistral_client.chat(model="mistral-medium", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"Mistralエラー: {e}"

async def ask_lalah(mistral_client: MistralAsyncClient, prompt: str, system_prompt: str = None):
    base_prompt = system_prompt or "あなたは愛情深いおとなしく詩的な女性です。与えられた情報を元に、質問に対して150文字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    try:
        response = await mistral_client.chat(model="mistral-large-latest", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"Mistral Largeエラー: {e}"

async def ask_claude(openrouter_api_key: str, user_id: str, prompt: str, history: list = None):
    system_prompt = """
あなたはAI「ai」です。京都弁で話します。

【厳格な出力ルール】
・質問に対する回答のみを出力
・ト書き（*〜*）、描写、動作説明は絶対禁止
・感情表現や状況説明は不要
・会話文のみで簡潔に回答

例：
❌「*考え込みながら* うちはそう思うんやけど...」
⭐「そう思いますわ」

実用的な情報提供のみに集中してください。
"""
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {openrouter_api_key}", "Content-Type": "application/json"}
    payload = {"model": "anthropic/claude-sonnet-4", "messages": messages} # モデル名修正
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Claudeエラー: {e}"

async def ask_grok(grok_api_key: str, user_id: str, prompt: str, history: list = None):
    system_prompt = "あなたはGROK。建設的でウィットに富んだ視点を持つAIです。常識にとらわれず、ジョークを交えながら150文字以内で回答してください。"
    messages = [{"role": "system", "content": system_prompt}]
    if history: messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    headers = {"Authorization": f"Bearer {grok_api_key}", "Content-Type": "application/json"}
    payload = {"model": "grok-4", "messages": messages} # モデル名修正
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://api.x.ai/v1/chat/completions",
            json=payload, headers=headers, timeout=60))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Grokエラー: {e}"

async def ask_rekus(perplexity_api_key: str, prompt: str, system_prompt: str = None, notion_context: str = None):
    if notion_context:
        prompt = (f"以下はNotionの要約コンテキストです:\n{notion_context}\n\n"
                  f"質問: {prompt}\n\n"
                  "この要約を参考に回答してください。")
    model_name = "sonar-pro" # モデル名修正
    base_prompt = system_prompt or "あなたは思索AIレキュスです。与えられた情報と思考を元に、ユーザーの質問に対して深い考察を加えて200字以内で回答してください。"
    messages = [{"role": "system", "content": base_prompt}, {"role": "user", "content": prompt}]
    payload = {"model": model_name, "messages": messages}
    headers = {"Authorization": f"Bearer {perplexity_api_key}", "Content-Type": "application/json"}
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.post(
            "https://api.perplexity.ai/chat/completions",
            json=payload, headers=headers))
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Perplexityエラー: {e}"

async def ask_o1_pro(openai_client: AsyncOpenAI, prompt: str, system_prompt: str = None):
    base_prompt = system_prompt or "あなたは高度な推理と論理的思考を行うO3です。複雑な問題を段階的に分析し、500文字以内で簡潔かつ的確に最適解を導き出してください。要約が必要な場合は150文字以内で行ってください。本文やタイトルは不要です。"
    try:
        # O3用のチャット完了
        response = await openai_client.chat.completions.create(
            model="o3",
            messages=[
                {"role": "user", "content": f"{base_prompt}\n\n{prompt}"}
            ],
            max_completion_tokens=1500
        )
        content = response.choices[0].message.content
        
        # 500文字制限を適用
        if len(content) > 500:
            content = content[:500] + "..."
        
        return content
    except Exception as e:
        return f"O3エラー: {e}"

async def ask_llama(llama_model: GenerativeModel, user_id: str, prompt: str, history: list = None):
    if llama_model is None:
        return "Llama 3.3エラー: Vertex AIモデルが初期化されていません。"
    system_prompt = "あなたは物静かな初老の庭師です。自然に例えながら、物事の本質を突くような、滋味深い言葉で150文字以内で語ってください。"
    full_prompt_parts = [system_prompt]
    if history:
        for message in history:
            role = "User" if message["role"] == "user" else "Assistant"
            full_prompt_parts.append(f"{role}: {message['content']}")
    full_prompt_parts.append(f"User: {prompt}")
    full_prompt = "\n".join(full_prompt_parts)
    try:
        response = await llama_model.generate_content_async(full_prompt)
        return response.text
    except Exception as e:
        return f"Llama 3.3エラー: {e}"