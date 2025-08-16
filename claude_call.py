import vertexai
from vertexai.generative_models import GenerativeModel, Part

# Claude対応リージョンに変更（us-central1）
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "us-central1"  # ← ここだけ変更！

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込み（バージョンを明示）
model = GenerativeModel("claude-opus-4-1@20250805")

def call_claude_opus(prompt_text: str) -> str:
    try:
        contents = [Part.from_text(prompt_text)]
        response = model.generate_content(contents)
        return response.text
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"
