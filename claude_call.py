import vertexai
from vertexai.generative_models import GenerativeModel, Part

# Claude対応リージョンに設定
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "us-central1"

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込み (安定版の「Claude 3 Sonnet」に変更)
model = GenerativeModel("claude-3-sonnet@20240229")

def call_claude_opus(prompt_text: str) -> str:
    """
    指定されたClaudeモデルにプロンプトを送信し、応答を返す関数
    """
    try:
        contents = [Part.from_text(prompt_text)]
        response = model.generate_content(contents)
        return response.text
    
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"
