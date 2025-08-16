# claude_call.py

import vertexai
from vertexai.generative_models import GenerativeModel, Part

# あなたのGoogle CloudプロジェクトIDなどを設定
PROJECT_ID = "your-gcp-project-id"  # 👈 ここにあなたのプロジェクトIDを設定
LOCATION = "us-central1"  # 👈 利用可能なリージョンを設定 (例: us-central1)

# Vertex AIを初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込む (画像に表示されているモデル名を指定)
model = GenerativeModel("claude-opus-4-1")

def call_claude_opus(prompt_text: str) -> str:
    """
    Claude Opus 4.1モデルにプロンプトを送信し、応答を返す関数
    """
    try:
        # モデルへのリクエストを作成
        contents = [Part.from_text(prompt_text)]
        
        # テキスト生成を実行
        response = model.generate_content(contents)
        
        return response.text
    except Exception as e:
        print(f"Vertex AI呼び出し中にエラーが発生しました: {e}")
        return f"エラー: Claudeモデルの呼び出しに失敗しました。詳細: {e}"

# --- テスト用 ---
if __name__ == '__main__':
    test_prompt = "こんにちは！自己紹介をしてください。"
    response_text = call_claude_opus(test_prompt)
    print("--- Claudeからの応答 ---")
    print(response_text)
