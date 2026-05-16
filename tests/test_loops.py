from llmeffect import analyze_source


def find(violations, code):
    return [v for v in violations if v.code == code]


def test_while_true_loop_around_llm_call_is_unbounded():
    src = """
import openai
def f():
    while True:
        openai.chat.completions.create(model="gpt-4", messages=[])
"""
    assert find(analyze_source(src), "LLM020")


def test_for_range_loop_is_single_bound():
    src = """
import openai
def f():
    for _ in range(10):
        openai.chat.completions.create(model="gpt-4", messages=[])
"""
    assert find(analyze_source(src), "LLM021")


def test_dual_bound_agent_loop_config_is_clean():
    src = """
def step(): pass
def f():
    config = AgentLoopConfig(max_consecutive_errors=3, max_total_errors=8, max_successful_steps=30)
    for _ in range(100):
        import openai
        openai.chat.completions.create(model="gpt-4", messages=[])
"""
    out = analyze_source(src)
    assert find(out, "LLM020") == []
    assert find(out, "LLM021") == []
