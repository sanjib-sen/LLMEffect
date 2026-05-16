# LLMEffect evaluation on real LLM-integrated Python applications

This file records the result of running the analyzer on a corpus of
open-source LLM-integrated Python projects, and a manual triage of every
finding.

## Corpus

Ten open-source LLM-integrated Python projects, selected to cover four use
cases: shell and code agents, code-generation tools, RAG and memory
frameworks, and text-to-SQL. All clones are shallow (`--depth 1
--filter=blob:none`). Tests, build artifacts, vendored dependencies, and
`__pycache__` directories are excluded from analysis when they live under
standard skip-paths.

| # | Repo | Category | Files scanned |
|---|------|----------|---------------|
| 1 | OpenInterpreter/open-interpreter | shell-agent     |   144 |
| 2 | Aider-AI/aider                   | code-agent      |   147 |
| 3 | AntonOsika/gpt-engineer          | code-gen        |    84 |
| 4 | crewAIInc/crewAI                 | agent-framework | 1,179 |
| 5 | microsoft/autogen                | agent-framework |   546 |
| 6 | mem0ai/mem0                      | rag             |   620 |
| 7 | vanna-ai/vanna                   | text-to-sql     |   301 |
| 8 | openai/openai-cookbook           | examples        |   190 |
| 9 | anthropics/anthropic-cookbook    | examples        |    91 |
| 10 | langchain-ai/langchain          | framework       | 2,478 |
|    | **Total**                       |                 | **5,780** |


## Method

For each repo, the driver runs `git clone --depth 1 --filter=blob:none`,
recursively analyzes all `.py` files outside skip directories, and records
per-rule violation counts. The analyzer was run in two configurations:

* **Baseline.** Stock patterns covering only direct OpenAI and Anthropic SDK
  calls (`*.chat.completions.create`, `*.messages.create`, etc.).
* **Extended.** Baseline plus `litellm.completion` and `litellm.acompletion`,
  plus a receiver-name heuristic that treats
  `<llm|chat|model|client|agent|chain>.<invoke|generate|complete|chat|call|predict>(...)`
  as an LLM call. This covers LangChain and LlamaIndex idioms.

After the extended run, one analyzer fix was applied to a clear false-positive
class: `for x in llm.invoke(...)` (consuming a streaming response) was being
treated as a loop containing an LLM call. The fix restricts the phase-3 check
to the loop body, not the iterator expression. After-fix numbers are reported
below.


## Headline numbers

|                            | Baseline | Extended (post-FP fix) |
|----------------------------|---------:|-----------------------:|
| Total violations           |        9 |                     23 |
| Repos with any finding     |     4/10 |                   7/10 |
| LLM001 (Secret to prompt)  |        0 |                      0 |
| LLM002 (PII to prompt)     |        0 |                      0 |
| LLM003 (Tainted to prompt) |        1 |                      1 |
| LLM010 (Unvalidated sink)  |        0 |                      0 |
| LLM020 (Unbounded loop)    |        1 |                      2 |
| LLM021 (Single-bound loop) |        7 |                     20 |


## Per-repo breakdown (extended run)

| Repo                | Files | LLM020 | LLM021 | LLM003 | Total |
|---------------------|------:|-------:|-------:|-------:|------:|
| open-interpreter    |   144 |      1 |      2 |        |     3 |
| aider               |   147 |        |      1 |        |     1 |
| gpt-engineer        |    84 |        |        |        |     0 |
| crewAI              | 1,179 |        |      3 |        |     3 |
| autogen             |   546 |        |        |        |     0 |
| mem0                |   620 |        |      1 |      1 |     2 |
| vanna               |   301 |        |        |        |     0 |
| openai-cookbook     |   190 |      1 |      4 |        |     5 |
| anthropic-cookbook  |    91 |        |      1 |        |     1 |
| langchain           | 2,478 |        |      8 |        |     8 |


## Triage

Each finding was inspected manually.

### LLM020, unbounded LLM loop (2 of 2 true positives)

1. `open-interpreter/interpreter/core/computer/terminal/languages/jupyter_language.py:136`.
   A `while True:` polling loop that calls `litellm.completion(...)` whenever
   a Jupyter kernel has been silent past a patience threshold. Exit is by an
   externally-set `finish_flag` and `return` statements. There is no
   iteration cap on LLM calls. A long-running stuck kernel can produce
   unbounded LLM traffic.

2. `openai-cookbook/examples/partners/model_selection_guide/agent_utils.py:206`.
   A `while True:` tool-calling agent. Exit is only via `return` when the
   model produces no more tool calls. No iteration cap. A model that keeps
   requesting tool calls loops indefinitely. Notable because this is published
   as guidance.

LLM020 precision in the corpus: 100% (2 of 2).

### LLM021, single-bound agent loop

All 20 hits were directly inspected. Every one of them matches the rule's
syntactic specification: an LLM call inside a single-bound loop with no
`AgentLoopConfig` in scope. So by rule letter, precision is 20 of 20 = 100%.

The more interesting precision question is whether the *underlying concern*
applies: a snowball error pattern in which error context is re-prompted to
the model across iterations, degrading subsequent responses.

**Intent true positives (4), where error feedback flows into a growing
message history:**

| Site | Pattern |
|------|---------|
| `anthropic-cookbook/tool_use/memory_demo/code_review_demo.py:124` | `while True:` conversation. `self.messages.append(assistant_content)` and `self.messages.append(tool_results)` each turn |
| `crewAI/lib/crewai/src/crewai/agents/step_executor.py:290` | `for _ in range(max_step_iterations):`. `messages.append(assistant)` and `messages.append(_build_observation_message(tool_result))` each iter |
| `crewAI/lib/crewai/src/crewai/agents/step_executor.py:491` | Same shape. `_execute_native_tool_calls(answer, messages, ...)` mutates messages |
| `open-interpreter/interpreter/computer_use/loop.py:137` | `while True:` computer-use loop. `messages.append({"role": "assistant", "content": ...})` and tool-result blocks each turn |

**Intent false positives (16), where the analyzer fires correctly per rule
letter but the snowball mechanism does not apply:**

Retry-on-exception with a fixed prompt (no error appended to messages):

* `aider/aider/coders/base_coder.py:1358`. Cache-warming worker with fixed
  `cacheable_messages()`.
* `embedchain/evaluation/src/rag.py:41`. `while retries <= max_retries:`
  retry, fixed prompt.
* `open-interpreter/interpreter/core/llm/llm.py:444`. `for attempt in
  range(attempts):` adjusts `params` (api_key, temperature), not messages.
* `openai-cookbook/.../gen_baseline.py:37`, `gen_optimized.py:34`,
  `llm_judge.py:133`, `llm_judge.py:276`. Identical
  `for attempt in range(max_retries): try: client.responses.create(...)`
  shape with fixed payload.

Collection iteration (each iteration processes a different input):

* `crewAI/lib/crewai/src/crewai/utilities/agent_utils.py:966`.
  `for idx, chunk in enumerate(chunks, 1):` per-chunk summarization.
* `langchain/.../langchain_classic/memory/entity.py:613`.
  `for entity in self.entity_cache:` per-entity summarization.
* `langchain/.../langchain_classic/chains/sequential.py:113`.
  `for _i, chain in enumerate(self.chains):` chain dispatch.
* `langchain/.../core/langchain_core/runnables/branch.py:212, 260`.
  `for idx, branch in enumerate(self.branches):` branch dispatch.

Test and benchmark code:

* `langchain/.../tests/.../test_benchmark.py:15`.
  `for _ in range(1_000): model.invoke("foo")` on `GenericFakeChatModel`.
* `langchain/.../tests/.../test_rate_limiting.py:203, 265`.
  `for _ in range(2):` rate-limiter cache tests.
* `langchain/.../tests/agents/test_responses_spec.py:125`.
  `for assertion in case.assertions_by_invocation:` test fixture iteration.

Precision by intent: 4 of 20 = 20%.

The 100% letter precision versus 20% intent precision gap means the rule as
written is a syntactic check. Closing the rule under the snowball-error
intent requires recognising a specific pattern in the loop body: an exception
or success branch that appends to a message history that is re-sent on the
next iteration. All four intent true positives have that. None of the
sixteen intent false positives do. A tightened rule that demands this
evidence would discriminate cleanly.

### LLM003, tainted input without role separation (1 of 1 true positive)

* `mem0/embedchain/examples/misc/movie_recommendation_grok3.py:55`. The user
  query is interpolated into a prompt and sent as a single `user`-role
  message with no `developer` or `system` role anywhere. Classic
  prompt-injection setup.


## The zero-hit rules: a structural finding

The most informative number in the table is **LLM001 = 0, LLM002 = 0,
LLM010 = 0** across 5,780 files. These are not cases of an analyzer that
over-reports nothing. They reflect a real architectural blind spot.

* **LLM001 (Secret to prompt).** Real apps pass API credentials to SDK
  constructors (`OpenAI(api_key=os.getenv(...))`), not to prompts. Direct
  interpolation of secrets into a prompt, the pattern the rule catches, is
  rare in mature code.
* **LLM002 (PII to prompt).** Cookbook code uses synthetic data, and
  production apps typically wrap user records in ORM models. The current
  heuristic (DB `query` and `fetchall` calls return PII) misses ORM-mediated
  data flows entirely.
* **LLM010 (Unvalidated to sink).** This is the most consequential miss.
  Apps such as open-interpreter and crewAI absolutely do execute LLM-generated
  code, but the LLM call and the execution sink live in different methods,
  often different files. The analyzer is intra-procedural and cannot follow
  `self.last_response` from a `call()` method through a hand-off to an
  `_execute()` method elsewhere.

In other words, the corpus did not contain zero unvalidated-output sinks.
The analyzer cannot see them with intra-procedural analysis. Cross-procedural
data-flow propagation is the single highest-value extension.


## Pattern coverage is a precondition

Before extending `patterns.py`, the analyzer detected zero LLM calls in
aider, crewAI, autogen, vanna, and langchain. Five of the most LLM-heavy
projects in the corpus, because they all dispatch through `litellm` or
LangChain-style `.invoke()`. After extension, total findings rose 2.6 times
(from 9 to 23). The pattern-recognition surface is a first-order concern for
any practical adoption. An analyzer that does not know the SDK wrappers in
use produces silent zero output, the worst kind of result.


## Summary observations

1. The analyzer detects real, published anti-patterns. Both LLM020 hits, one
   in the official OpenAI cookbook, match the rule's target exactly. The
   crewAI LLM021 hits are clean matches for the single-bound retry pattern.
2. The phase-1 rules (labels) need cross-procedural propagation to be useful
   on real apps. Heuristic source labelling at the call site is not enough.
   Values originate elsewhere and pass through wrappers.
3. The phase-2 rule (typestate) has the same dependency, and the cost is
   severe. LLM010 found nothing across the corpus despite shell-executing
   agents being present. Cross-procedural typestate would change this number
   drastically.
4. LLM021 is precision-limited as a static rule. Letter precision is 100%
   (20 of 20). Intent precision is 20% (4 of 20). The gap is the distance
   between a syntactic shape and a semantic pattern. Closing it requires
   detecting error-feedback propagation in the loop body.
5. The extended patterns list is reusable evidence. The 2.6 times recall
   improvement after adding `litellm` and the LangChain `.invoke()` heuristic
   is a concrete demonstration that the analyzer architecture is extensible,
   and that pattern coverage is the gate to everything else.
