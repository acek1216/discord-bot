import vertexai
from vertexai.generative_models import GenerativeModel, Part

# あなたのGoogle CloudプロジェクトIDなどを設定
PROJECT_ID = "stunning-agency-469102-b5"  # ここにあなたのプロジェクトIDを設定
LOCATION = "asia-northeast1"              # 利用可能なリージョンを設定 (例: asia-northeast1)

# Vertex AI を初期化
vertexai.init(project=PROJECT_ID, location=LOCATION)

# モデルを読み込み (正式なモデルIDを指定)
model = GenerativeModel("claude-3-opus@20240229")

def call_claude_opus(prompt_text: str) -> str:
    """
    Claude 3 Opusモデルにプロンプトを送信し、応答を返す関数
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
