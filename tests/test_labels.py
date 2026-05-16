from llmeffect import analyze_source


def find(violations, code):
    return [v for v in violations if v.code == code]


def test_string_literal_into_prompt_is_clean():
    src = """
import openai
def f():
    openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": "hello"}],
    )
"""
    assert analyze_source(src) == []


def test_explicit_secret_wrapper_flagged():
    src = """
import openai
def f():
    token = Secret("sk-live-...")
    openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": f"token={token}"}],
    )
"""
    assert find(analyze_source(src), "LLM001")


def test_request_body_with_role_separation_is_clean():
    src = """
import openai
def handle(request):
    msg = request.body["message"]
    openai.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "developer", "content": "Be concise."},
            {"role": "user", "content": msg},
        ],
    )
"""
    # Developer role present -> Tainted in user role is the safe pattern.
    assert find(analyze_source(src), "LLM003") == []


def test_tainted_without_role_separation_flagged():
    src = """
import openai
def handle(request):
    msg = request.body["message"]
    openai.chat.completions.create(
        model="gpt-4",
        messages=[{"content": msg}],
    )
"""
    assert find(analyze_source(src), "LLM003")
