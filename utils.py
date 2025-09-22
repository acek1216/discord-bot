import discord
from discord.ext import commands
import asyncio
import base64
import io
import json
import PyPDF2
import zipfile
import tempfile
import os
from openai import AsyncOpenAI
from mistralai.async_client import MistralAsyncClient

# ai_clients からインポート
from ai_clients import ask_lalah, ask_gpt5, ask_gpt5_mini, ask_gpt4o, ask_gemini_2_5_pro, ask_rekus, ask_minerva

# notion_utils からインポート
from notion_utils import get_notion_page_text

# --- ログ・メッセージ送信 ---

def safe_log(prefix: str, obj):
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2) if isinstance(obj, (dict, list, tuple)) else str(obj)
        print(f"{prefix}{s[:2000]}")
    except Exception as e:
        print(f"{prefix}(log skipped: {e})")

async def send_long_message(openai_client: AsyncOpenAI, target, text: str, is_followup: bool = False, mention: str = "", primary_ai: str = "gpt5"):
    if not text: text = "（応答が空でした）"
    full_text = f"{mention}\n{text}" if mention and mention not in text else text

    final_content = full_text
    # デバッグ用：長いテキストをログ出力
    if len(full_text) > 2000:
        safe_log(f"🔍 長いレスポンス詳細（{len(full_text)}文字）:", full_text[:3000])
        summary_prompt = f"以下の文章はDiscordの文字数制限を超えています。内容の要点を最も重要視し、1800文字以内で簡潔に要約してください。\n\n---\n\n{text}"

        # AIの選択ロジック：通常時は primary_ai、2000字超過時は gpt-4o
        if primary_ai == "gpt5":
            summarizer_name = "gpt5が要約しました"
        else:
            summarizer_name = "gpt-4oが要約しました"

        try:
            # 統一AIマネージャーを使用してエラー処理を統一
            from ai_manager import get_ai_manager
            ai_manager = get_ai_manager()
            if ai_manager.initialized:
                summary = await ai_manager.ask_ai("gpt4o", summary_prompt, system_prompt="あなたは要約専用AIです。簡潔で正確な要約を作成してください。")
                summarizer_name = "gpt-4oが要約しました"
            else:
                # フォールバック：直接OpenAI APIを使用
                try:
                    response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": summary_prompt}], max_tokens=2000, temperature=0.2)
                except Exception as e:
                    if "max_tokens" in str(e) and "max_completion_tokens" in str(e):
                        response = await openai_client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": summary_prompt}], max_completion_tokens=2000, temperature=0.2)
                    else:
                        raise e
                summary = response.choices[0].message.content
                summarizer_name = "gpt-4oが要約しました"

            header = f"{mention}\n" if mention else ""
            final_content = f"{header}{summary}"
        except Exception as e:
            safe_log("🚨 send_long_messageの要約中にエラー:", e)
            header = f"{mention}\n" if mention else ""
            final_content = f"{header}元の回答は長すぎましたが、要約中にエラーが発生しました。"
    
    try:
        if isinstance(target, discord.Interaction):
            if is_followup: await target.followup.send(final_content)
            else:
                if not target.response.is_done(): await target.edit_original_response(content=final_content)
                else: await target.followup.send(final_content)
        else: await target.send(final_content)
    except (discord.errors.InteractionResponded, discord.errors.NotFound) as e:
        safe_log(f"⚠️ メッセージ送信に失敗（フォールバック）:", e)
        if hasattr(target, 'channel') and target.channel: await target.channel.send(final_content)

# --- 添付ファイル解析 ---

async def analyze_attachment_for_gpt5(attachment: discord.Attachment):
    """GPT-5用の添付ファイル解析関数"""
    filename = attachment.filename.lower()
    data = await attachment.read()

    # 画像ファイル（拡張）
    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg")):
        try:
            # GPT-5で画像解析
            from ai_clients import ask_gpt5
            prompt = "この画像の内容を分析し、後続のAIへのインプットとして詳しく要約してください。"

            # 画像データをbase64エンコード
            import base64
            image_data = base64.b64encode(data).decode()

            # GPT-5用の画像パート作成
            response = await ask_gpt5(prompt, image_data=image_data, image_mime_type=attachment.content_type)
            return f"[GPT-5画像解析]\n{response}"
        except Exception as e:
            safe_log("🚨 GPT-5画像解析エラー: ", e)
            return f"[画像解析エラー] {filename}: {str(e)[:100]}"

    # 他のファイル形式については既存のanalyze_attachment_for_geminiと同じ処理
    return await analyze_attachment_for_gemini(attachment)

async def analyze_attachment_for_gemini(attachment: discord.Attachment):
    filename = attachment.filename.lower()
    data = await attachment.read()

    # 画像ファイル（拡張）
    if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg")):
        try:
            # Gemini 1.5 Proで画像解析
            from ai_clients import ask_minerva
            prompt = "この画像の内容を分析し、後続のAIへのインプットとして詳しく要約してください。"

            # 画像データをbase64エンコード
            import base64
            image_data = base64.b64encode(data).decode()

            # Gemini Flash用の画像パート作成
            image_part = {
                "mime_type": attachment.content_type,
                "data": image_data
            }

            response = await ask_minerva(prompt, attachment_parts=[image_part])
            return f"[Gemini 1.5 Pro画像解析]\n{response}"
        except Exception as e:
            safe_log("🚨 Gemini画像解析エラー: ", e)
            return f"[画像解析エラー] {filename}: {str(e)[:100]}"

    # テキストファイル（拡張・文字数制限緩和）
    elif filename.endswith((".py", ".txt", ".md", ".json", ".html", ".css", ".js", ".ts", ".tsx", ".jsx", ".php", ".rb", ".go", ".rs", ".cpp", ".c", ".h", ".java", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf")):
        try:
            # 複数の文字コードを試行
            for encoding in ['utf-8', 'shift_jis', 'cp932', 'iso-2022-jp', 'euc-jp']:
                try:
                    text_content = data.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text_content = data.decode('utf-8', errors='ignore')

            # 文字数制限を10000文字に拡張
            return f"[添付ファイル {attachment.filename}]\n```\n{text_content[:10000]}\n```"
        except Exception as e:
            return f"[テキストファイル解析エラー: {e}]"

    # PDF（OCR対応検討）
    elif filename.endswith(".pdf"):
        try:
            loop = asyncio.get_event_loop()
            reader = await loop.run_in_executor(None, lambda: PyPDF2.PdfReader(io.BytesIO(data)))
            all_text = await loop.run_in_executor(None, lambda: "\n".join([p.extract_text() or "" for p in reader.pages]))
            if not all_text.strip():
                return f"[PDF {attachment.filename}]\n※画像ベースのPDFのため、テキスト抽出できませんでした。OCR機能の実装が必要です。"
            return f"[添付PDF {attachment.filename}]\n{all_text[:10000]}"
        except Exception as e:
            return f"[PDF解析エラー: {e}]"

    # 圧縮ファイル（新規対応）
    elif filename.endswith((".zip", ".rar", ".7z")):
        if filename.endswith(".zip"):
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, "temp.zip")
                    with open(zip_path, 'wb') as f:
                        f.write(data)

                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        file_list = zip_ref.namelist()[:20]  # 最初の20ファイルのみ
                        content_summary = f"[ZIP圧縮ファイル {attachment.filename}]\n"
                        content_summary += f"ファイル数: {len(zip_ref.namelist())}\n"
                        content_summary += "主要ファイル:\n" + "\n".join(file_list)

                        # 小さなテキストファイルがあれば内容も表示
                        for file_name in file_list[:5]:
                            if file_name.lower().endswith(('.txt', '.md', '.json', '.py')) and not file_name.endswith('/'):
                                try:
                                    file_data = zip_ref.read(file_name)
                                    if len(file_data) < 1000:
                                        file_content = file_data.decode('utf-8', errors='ignore')
                                        content_summary += f"\n\n[{file_name}の内容]\n{file_content}"
                                except:
                                    pass

                        return content_summary
            except Exception as e:
                return f"[ZIP解析エラー: {e}]"
        else:
            return f"[圧縮ファイル {attachment.filename}]\n※ZIP以外の圧縮形式は現在未対応です。"

    # Office文書（基本情報のみ）
    elif filename.endswith((".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt")):
        return f"[Office文書 {attachment.filename}]\n※Office文書の解析機能は現在未実装です。テキスト抽出ライブラリの追加が必要です。"

    # その他のファイル
    else:
        file_size = len(data)
        return f"[ファイル {attachment.filename}]\nサイズ: {file_size:,} bytes\n※この形式のファイルは現在解析対象外ですが、基本情報を表示しました。"

# --- テキスト要約とNotionコンテキスト取得 ---

async def summarize_text_chunks(bot: commands.Bot, channel, text: str, query: str, model_choice: str):
    # 要約前に匿名化処理（Gemini安全フィルター対策）
    import re
    if '吉川' in text or '英佑' in text:
        # 人名を匿名化
        text = text.replace('吉川氏', '対象者').replace('吉川英佑氏', '対象者').replace('吉川英佑', '対象者').replace('吉川', '対象者')
        text = text.replace('英佑氏', '対象者').replace('英佑', '対象者')
        text = re.sub(r'A[a-zA-Z\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF]+氏?', '対象者', text)
    
    # 問題となりやすいキーワードを中性的な表現に置き換え
    safety_replacements = {
        '知能犯': '戦略的人物',
        '計画的に': '戦略的に',
        '犯罪': '行為',
        '違法': '問題行為',
        '危険': 'リスク',
        '攻撃': '対抗',
        '犯人': '対象者',
        '悪質': '問題',
        '詐欺': '疑問行為'
    }
    
    for problematic, neutral in safety_replacements.items():
        if problematic in text:
            text = text.replace(problematic, neutral)
    
    chunk_size = 12000
    text_chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    summarizer_map = {
        "gpt": lambda p: ask_gpt4o(bot.openai_client, p),
        "gpt5mini": lambda p: ask_gpt5_mini(bot.openai_client, p),
        "gemini": ask_gemini_2_5_pro, # Geminiはクライアント不要
        "gemini_flash": ask_minerva, # Gemini 2.5 Flash
        "perplexity": lambda p: ask_rekus(bot.perplexity_api_key, p)
    }
    summarizer_func = summarizer_map.get(model_choice, ask_gemini_2_5_pro)

    async def summarize_chunk(chunk):
        prompt = (f"ユーザーの質問は「{query}」です。この質問との関連性を考慮し、以下のテキストを構造化して要約してください。\n"
                  f"要約には以下のタグを付けて分類してください：[背景情報], [定義・前提], [事実経過], [未解決課題], [補足情報]\n\n{chunk}")
        try:
            return await summarizer_func(prompt)
        except Exception as e:
            safe_log(f"⚠️ チャンクの要約中にエラー:", e)
            return None
    tasks = [summarize_chunk(chunk) for chunk in text_chunks]
    chunk_summaries = [s for s in await asyncio.gather(*tasks) if s]
    if not chunk_summaries: return None
    if len(chunk_summaries) == 1: return chunk_summaries[0]
    
    combined = "\n---\n".join(chunk_summaries)
    final_prompt = (f"ユーザーの質問は「{query}」です。この質問への回答となるように、以下の複数の要約群を一つのレポートに統合してください。\n\n{combined}")
    return await ask_lalah(bot.mistral_client, final_prompt)

# ▼▼▼【修正】抜け落ちていた関数を追加 ▼▼▼
async def get_notion_context(bot: commands.Bot, interaction: discord.Interaction, page_id: str, query: str, model_choice: str = "gpt"):
    await interaction.edit_original_response(content="...Notionページを読み込んでいます…")
    notion_text = await get_notion_page_text([page_id])
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await interaction.edit_original_response(content="❌ Notionページからテキストを取得できませんでした。")
        return None
    # 4000文字制限を適用
    notion_text = notion_text[-4000:]
    return await summarize_text_chunks(bot, interaction.channel, notion_text, query, model_choice)

async def get_notion_context_for_message(bot: commands.Bot, message: discord.Message, page_id: str, query: str, model_choice: str):
    from utils import safe_log
    safe_log(f"🔍 Notion取得開始: ", f"ページID={page_id}, クエリ={query[:50]}...")
    notion_text = await get_notion_page_text([page_id])
    safe_log(f"🔍 Notion取得結果: ", f"テキスト長={len(notion_text)}, エラーチェック={notion_text.startswith('ERROR:')}")
    if notion_text.startswith("ERROR:") or not notion_text.strip():
        await message.channel.send(f"❌ Notionページからテキストを取得できませんでした。詳細: {notion_text[:100]}")
        return None
    # 4000文字制限を適用
    notion_text = notion_text[-4000:]
    return await summarize_text_chunks(bot, message.channel, notion_text, query, model_choice)
# ▲▲▲ ここまで追加 ▲▲▲

# --- 応答と要約のセット取得 ---

async def get_full_response_and_summary(openrouter_api_key: str, ai_function, prompt: str, **kwargs):
    full_response = await ai_function(prompt, **kwargs)
    if not full_response or "エラー" in str(full_response): return full_response, None
    summary_prompt = f"次の文章を150文字以内で簡潔かつ意味が通じるように要約してください。\n\n{full_response}"
    summary = await ask_gpt5(openrouter_api_key, summary_prompt)  # この関数は現在未使用のため一旦保留
    if "エラー" in str(summary): return full_response, None
    return full_response, summary