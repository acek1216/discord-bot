import google.auth
from google.auth.transport.requests import Request
import requests
import json

def call_claude(prompt: str) -> str:
    project_id = "stunning-agency-469102-b5"
    location = "asia-northeast1"
    model = "claude-opus-4-1"

    # 認証情報の取得と更新
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    token = credentials.token

    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/anthropic/models/{model}:generateContent"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024
        }
    }

    response = requests.post(url, headers=headers, json=body)

    if response.status_code != 200:
        raise Exception(f"🛑 Claude呼び出しエラー: {response.status_code} {response.text}")

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]
