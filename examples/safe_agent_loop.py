# Safe agent loop using AgentLoopConfig with dual bounds. Expect zero violations.
from llmeffect_runtime import AgentLoopConfig, run_agent_safe


def agent_step(state):
    import openai
    resp = openai.chat.completions.create(model="gpt-4", messages=state["history"])
    return resp.choices[0].message.content


def main(state):
    config = AgentLoopConfig(
        max_consecutive_errors=3,
        max_total_errors=8,
        max_successful_steps=30,
    )
    return run_agent_safe(agent_step, config)
