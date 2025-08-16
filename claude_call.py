from vertexai.preview.language_models import ChatModel
import vertexai

def call_claude_opus(prompt: str) -> str:
    vertexai.init(project="your-project-id", location="us-central1")

    # Claude 4.1 Opus（Vertex AIでのAnthropic提供モデル）の正しい指定方法
    chat_model = ChatModel.from_pretrained("claude-opus-4-1")

    chat = chat_model.start_chat()
    response = chat.send_message(prompt, temperature=0.7, max_tokens=1024)
    return response.text
