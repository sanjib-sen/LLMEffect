# LangChain-style single bound: only max_iterations. Expect LLM021.
import openai


def agent_loop(task, db, max_iterations=10):
    history = [{"role": "user", "content": task}]
    for _ in range(max_iterations):
        resp = openai.chat.completions.create(model="gpt-4", messages=history)
        out = resp.choices[0].message.content
        try:
            return db.execute(out)
        except Exception as e:
            history.append({"role": "user", "content": f"Error: {e}"})
    return None
