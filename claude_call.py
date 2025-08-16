import vertexai
from vertexai.language_models import ChatModel

# Claude対応リージョンに設定
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "us-central1"

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

#【重要】モデルの呼び出し方を「ChatModel.from_pretrained」に変更
model = ChatModel.from_pretrained("claude-opus-4-1@20250805")

def call_claude_opus(prompt_text: str) -> str:
    """
    指定されたClaudeモデルにプロンプトを送信し、応答を返す関数
    """
    try:
        # ChatModelに合わせた呼び出し方に変更
        chat = model.start_chat()
        response = chat.send_message(prompt_text)
        return response.text
    
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"
