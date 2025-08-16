from vertexai.preview.language_models import ChatModel
import vertexai

def call_claude_opus(prompt: str) -> str:
    vertexai.init(project="stunning-agency-469102-b5", location="asia-northeast1")

    chat_model = ChatModel.from_pretrained(
        "publishers/anthropic/models/claude-opus-4-1@20250805"
    )
    chat = chat_model.start_chat()
    response = chat.send_message(prompt, temperature=0.7, max_tokens=1024)
    return response.text
