import vertexai
from vertexai.language_models import ChatModel

# Claude 3.5 Sonnetが利用可能なリージョンに設定
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "us-central1"

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込み (お客様が特定した正しいモデル名を指定)
model = ChatModel.from_pretrained("claude-3-5-sonnet@20240620")

def call_claude_opus(prompt_text: str) -> str:
    """
    指定されたClaudeモデルにプロンプトを送信し、応答を返す関数
    """
    try:
        chat = model.start_chat()
        response = chat.send_message(prompt_text)
        return response.text
    
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"
