from vertexai.generative_models import GenerativeModel

def call_claude_opus(prompt: str) -> str:
    model = GenerativeModel(
        model_name="claude-4-opus-20240805", 
        publisher="anthropic"
    )

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.7,
            "max_output_tokens": 1024
        }
    )
    return response.text
