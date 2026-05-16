# Sends raw PII into the prompt. Expect LLM002.
import openai


def explain_record(customer):
    ssn = customer.ssn
    email = customer.email
    prompt = f"Explain this account: ssn={ssn} email={email}"
    return openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )
