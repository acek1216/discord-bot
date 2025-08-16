from vertexai.preview.language_models import ChatModel
import vertexai

vertexai.init(project="genius-bot-514855808739", location="us-central1")

def call_claude_opus(prompt: str) -> str:
    chat_model = ChatModel.from_pretrained("claude-3-opus")
    chat = chat_model.start_chat()
    response = chat.send_message(prompt, temperature=0.7, max_tokens=1024)
    return response.text
