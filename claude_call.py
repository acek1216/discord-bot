import vertexai
from vertexai.generative_models import GenerativeModel, Part

# あなたのGoogle CloudプロジェクトIDなどを設定
PROJECT_ID = "stunning-agency-469102-b5"
LOCATION = "asia-northeast1"

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込み (ご指定いただいた最終的なモデル名)
model = GenerativeModel("publishers/anthropic/models/claude-opus-4-1")

def call_claude_opus(prompt_text: str) -> str:
    """
    指定されたClaudeモデルにプロンプトを送信し、応答を返す関数
    """

    try:
        # モデルへのリクエストを作成
        contents = [Part.from_text(prompt_text)]

        # テキスト生成を実行
        response = model.generate_content(contents)

        return response.text
    
    except Exception as e:
        print(f"Vertex AI 呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"

# --- テスト用 ---
if __name__ == '__main__':
    test_prompt = "こんにちは！自己紹介をしてください。"
    response_text = call_claude_opus(test_prompt)
    print("--- Claudeからの応答 ---")
    print(response_text)
