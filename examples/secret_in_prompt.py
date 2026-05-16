# Sends API credential into prompt. Expect LLM001.
import os
import openai


def summarize_account():
    api_token = os.environ["STRIPE_SECRET_KEY"]
    return openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": f"Use this token to fetch data: {api_token}"}],
    )
