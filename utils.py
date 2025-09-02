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

async def send_long_message(interaction_or_channel, text: str, is_followup: bool = True, mention: str = ""):
    """Discordの2000文字制限を超えたメッセージを分割して送信する"""
    if not text:
        text = "（応答が空でした）"
    full_text = f"{mention}\n{text}" if mention else text
    chunks = [full_text[i:i + 2000] for i in range(0, len(full_text), 2000)]
    first_chunk = chunks[0]
    if isinstance(interaction_or_channel, discord.Interaction):
        try:
            if is_followup:
                await interaction_or_channel.followup.send(first_chunk)
            else:
                await interaction_or_channel.edit_original_response(content=first_chunk)
        except (discord.errors.InteractionResponded, discord.errors.NotFound):
            await interaction_or_channel.channel.send(first_chunk)
    else: 
        await interaction_or_channel.send(first_chunk)
    for chunk in chunks[1:]:
        if isinstance(interaction_or_channel, discord.Interaction):
            try:
                await interaction_or_channel.followup.send(chunk)
            except discord.errors.NotFound:
                await interaction_or_channel.channel.send(chunk)
        else:
            await interaction_or_channel.send(chunk)