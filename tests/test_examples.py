from pathlib import Path

from llmeffect import analyze_file


EXAMPLES = Path(__file__).parent.parent / "examples"


def codes(path: Path) -> set[str]:
    return {v.code for v in analyze_file(path)}


def test_unsafe_text_to_sql():
    found = codes(EXAMPLES / "unsafe_text_to_sql.py")
    # PII from db.query, Tainted user_question without role separation, unvalidated sql -> execute.
    assert "LLM002" in found
    assert "LLM003" in found
    assert "LLM010" in found


def test_safe_text_to_sql_is_clean():
    assert codes(EXAMPLES / "safe_text_to_sql.py") == set()


def test_secret_in_prompt():
    assert "LLM001" in codes(EXAMPLES / "secret_in_prompt.py")


def test_pii_in_prompt():
    assert "LLM002" in codes(EXAMPLES / "pii_in_prompt.py")


def test_unvalidated_shell_execution():
    assert "LLM010" in codes(EXAMPLES / "unvalidated_shell.py")


def test_unbounded_agent_loop():
    assert "LLM020" in codes(EXAMPLES / "unbounded_agent_loop.py")


def test_single_bound_agent_loop():
    assert "LLM021" in codes(EXAMPLES / "single_bound_agent_loop.py")


def test_safe_agent_loop_is_clean_for_loop_rules():
    found = codes(EXAMPLES / "safe_agent_loop.py")
    assert "LLM020" not in found
    assert "LLM021" not in found
