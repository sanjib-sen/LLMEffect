# Agent retries forever on error. Expect LLM020.
import openai


def agent_loop(task, db):
    history = [{"role": "user", "content": task}]
    while True:
        resp = openai.chat.completions.create(model="gpt-4", messages=history)
        out = resp.choices[0].message.content
        try:
            return db.execute(out)
        except Exception as e:
            history.append({"role": "user", "content": f"Error: {e}. Try again."})
