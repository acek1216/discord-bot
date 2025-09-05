from openai import AsyncOpenAI # OpenAIライブラリをインポート
openai_client: AsyncOpenAI = None # クライアントを格納する変数を準備

def set_openai_client(client: AsyncOpenAI):
    """bot.pyからOpenAIクライアントを受け取るための関数"""
    global openai_client
    openai_client = client

import json
import discord
import io

def safe_log(prefix: str, obj) -> None:
    """絵文字/日本語/巨大オブジェクトでもクラッシュしない安全なログ出力"""
    try:
        if isinstance(obj, (dict, list, tuple)):
            s = json.dumps(obj, ensure_ascii=False, indent=2)[:2000]
        else:
            s = str(obj)
        print(f"{prefix}{s}")
    except Exception as e:
        try:
            print(f"{prefix}(log skipped: {e})")
        except Exception:
            pass

# utils.py の send_long_message をこれに置き換え

async def send_long_message(interaction_or_channel, text: str, is_followup: bool = True, mention: str = ""):
    """
    Discordにメッセージを送信する。
    2000文字を超える場合はgpt-4oで要約して送信する。
    """
    if not text:
        text = "（応答が空でした）"
    
    full_text = f"{mention}\n{text}" if mention and mention not in text else text

    # 文字数がDiscordの制限を超えているかチェック
    if len(full_text) > 2000:
        # 要約処理
        summary_prompt = f"以下の文章はDiscordの文字数制限を超えています。内容の要点を最も重要視し、1800文字以内で簡潔に要約してください。\n\n---\n\n{text}"
        
        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=1800,
                temperature=0.2
            )
            summary = response.choices[0].message.content
            warning_message = "⚠️ 元の回答が2000文字を超えたため、gpt-4oが要約しました：\n\n"
            final_content = f"{mention}\n{warning_message}{summary}" if mention else f"{warning_message}{summary}"
        except Exception as e:
            safe_log("🚨 要約中にエラーが発生しました:", e)
            error_msg = "元の回答は長すぎましたが、要約中にエラーが発生しました。"
            final_content = f"{mention}\n{error_msg}" if mention else error_msg
    else:
        # 2000文字以下の場合はそのまま
        final_content = full_text

    # --- あなたの優れた送信ロジックをそのまま利用 ---
    if isinstance(interaction_or_channel, discord.Interaction):
        try:
            if is_followup:
                await interaction_or_channel.followup.send(final_content)
            else:
                await interaction_or_channel.edit_original_response(content=final_content)
        except (discord.errors.InteractionResponded, discord.errors.NotFound):
            await interaction_or_channel.channel.send(final_content)
    else: 
        await interaction_or_channel.send(final_content)
