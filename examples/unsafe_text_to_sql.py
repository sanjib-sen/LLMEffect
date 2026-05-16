# Vulnerable text-to-SQL agent. Three violations expected:
#   LLM002 (PII -> prompt), LLM003 (Tainted -> prompt, no role separation),
#   LLM010 (unvalidated LLM output -> db.execute).
import openai


def ask_database(user_question, user_db):
    schema = user_db.get_schema()
    sample_data = user_db.query("SELECT * FROM customers LIMIT 3")
    prompt = f"""You are a SQL assistant.
    Schema: {schema}
    Sample rows: {sample_data}
    Question: {user_question}
    Return only the SQL query."""
    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
    )
    sql = resp.choices[0].message.content
    return user_db.execute(sql)
