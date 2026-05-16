from llmeffect import analyze_source


def find(violations, code):
    return [v for v in violations if v.code == code]


def test_unvalidated_output_to_db_execute():
    src = """
import openai
def f(db):
    resp = openai.chat.completions.create(model="gpt-4", messages=[])
    sql = resp.choices[0].message.content
    db.execute(sql)
"""
    assert find(analyze_source(src), "LLM010")


def test_validated_output_to_db_execute_is_clean():
    src = """
import openai
def f(db, client):
    result = safe_llm_call(client, model="gpt-4", instructions=Trusted("..."))
    validated = result.validate(DatabaseCall(allowed_operations=["SELECT"]))
    if validated:
        db.execute(validated.value)
"""
    assert find(analyze_source(src), "LLM010") == []


def test_unvalidated_output_to_subprocess_run():
    src = """
import openai, subprocess
def f():
    resp = openai.chat.completions.create(model="gpt-4", messages=[])
    cmd = resp.choices[0].message.content
    subprocess.run(cmd, shell=True)
"""
    assert find(analyze_source(src), "LLM010")
