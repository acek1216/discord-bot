import vertexai
from vertexai.language_models import ChatModel

# プロジェクトIDとリージョンの設定はここで行う
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "us-central1"

# ★★★ ここでは初期化もモデル読み込みも行わない ★★★

def call_claude_opus(prompt_text: str) -> str:
    """
    指定されたClaudeモデルにプロンプトを送信し、応答を返す関数
    """
    try:
        # ★★★ 関数が呼ばれた時に初めて初期化とモデル読み込みを行う ★★★
        vertexai.init(project=PROJECT_ID, location=LOCATION)
        model = ChatModel.from_pretrained("claude-3-5-sonnet@20240620")
        
        chat = model.start_chat()
        response = chat.send_message(prompt_text)
        return response.text
    
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"
