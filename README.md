# LLMEffect

A static analyzer for Python programs that integrate with Large Language Model APIs.
LLMEffect inspects every LLM call site in your code and flags three classes of risk:
sensitive data flowing into prompts, unvalidated model output reaching dangerous
operations, and agent loops without proper iteration bounds.

The analyzer works on the abstract syntax tree of unmodified Python source. No
runtime instrumentation, no annotations required, no LLM API keys needed for
analysis itself.

## Rules

| Code   | Phase     | Severity | What it catches |
|--------|-----------|----------|-----------------|
| LLM001 | labels    | error    | Secret value (API key, credential) flows into an LLM prompt |
| LLM002 | labels    | error    | Personally identifiable information flows into an LLM prompt |
| LLM003 | labels    | warning  | User-controlled input flows into an LLM prompt without developer/user role separation |
| LLM010 | typestate | error    | LLM output reaches a dangerous sink (db.execute, subprocess.run, eval, etc.) without going through a validator |
| LLM020 | loops     | error    | LLM call sits inside a loop with no termination bound |
| LLM021 | loops     | warning  | LLM call sits inside a loop with only a single iteration bound, with no separate error budget |

## Install

The project uses [uv](https://github.com/astral-sh/uv) for environment management.

```sh
uv sync
```

This creates a `.venv/` and installs the project in editable mode.

## Usage

```sh
# Analyze a single file
uv run llmeffect path/to/file.py

# Analyze a directory recursively
uv run llmeffect path/to/dir/

# Print a one-line summary at the end
uv run llmeffect path/to/dir/ --summary

# Suppress warning-level findings
uv run llmeffect path/to/dir/ --no-warnings
```

Exit status is `1` if any error-level finding is reported, `0` otherwise.
Useful for CI gates.

Output format, one line per finding:

```
path/to/file.py:LINE:COL: SEVERITY [CODE] MESSAGE
```

## What the analyzer recognizes

### Label sources (no annotations required)

| Pattern | Label |
|---------|-------|
| `os.environ[...]`, `os.getenv(...)` | `Secret` |
| `request.body[...]`, `request.json[...]`, etc. (Flask/Django) | `Tainted` |
| `*.query(...)`, `*.fetchall(...)`, `*.execute(...)` on a DB handle | `PII` |
| `*.search(...)`, `*.similarity_search(...)` on a vector DB | `Internal` |
| Parameter names like `user_question`, `user_input`, `user_message` | `Tainted` |
| Variable names containing `password`, `api_key`, `token`, `ssn`, `email` | `Secret` or `PII` |
| Explicit wrappers: `Trusted(x)`, `Public(x)`, `Internal(x)`, `Tainted(x)`, `PII(x)`, `Secret(x)` | as declared |

Labels are propagated through assignments, f-strings, binary operations, and
container literals. Joins preserve the **set** of contributing labels, so a
value built from PII and Tainted sources fires both LLM002 and LLM003 rather
than collapsing under the lattice maximum.

### LLM call sites

The analyzer recognizes native SDK calls and common framework wrappers:

| Pattern | Library |
|---------|---------|
| `*.chat.completions.create(...)`, `*.chat.completions.acreate(...)` | OpenAI |
| `*.completions.create(...)` | OpenAI legacy |
| `*.responses.create(...)`, `*.responses.stream(...)` | OpenAI Responses API |
| `*.messages.create(...)`, `*.messages.stream(...)` | Anthropic |
| `litellm.completion(...)`, `litellm.acompletion(...)` | litellm |
| `completion(...)`, `acompletion(...)` (bare names) | litellm via `from litellm import completion` |
| `<llm\|chat\|model\|client\|agent\|chain\|runnable>.<invoke\|generate\|complete\|chat\|call\|predict>(...)` | LangChain, LlamaIndex, similar |
| `safe_llm_call(...)` | LLMEffect runtime helper |

### Dangerous sinks

| Pattern | Kind |
|---------|------|
| `*.execute(...)`, `*.executemany(...)`, `*.executescript(...)`, `*.raw(...)` | SQL |
| `subprocess.run`, `subprocess.Popen`, `subprocess.call`, `subprocess.check_output`, `os.system`, `os.popen` | shell |
| `eval(...)`, `exec(...)`, `compile(...)` | code execution |
| `requests.get/post/put/delete/...`, `urllib.*` | URL fetch |

### Validators

A typestate transition `Unvalidated to Validated` occurs when the LLM output
passes through any `.validate(...)` call, or is wrapped in one of the built-in
validators: `DatabaseCall`, `ShellExec`, `URLFetch`.

## Test suite

```sh
uv run pytest tests/ -v
```

Eighteen unit tests covering each rule and a vulnerable text-to-SQL agent end
to end.

## Demo

```sh
./run_demo.sh
```

Runs the analyzer on every file under `examples/` and prints findings.

## Evaluation harness

The `eval/` directory contains a driver that downloads a corpus of open-source
LLM-integrated Python projects and runs the analyzer against each one.

```sh
uv run python eval/run.py
```

### What the driver does

1. Reads `eval/repos.json`, a list of project metadata (name, GitHub URL,
   category, notes).
2. For each project, performs a shallow blobless clone into
   `eval/corpus/<name>/` if it does not already exist:
   ```
   git clone --depth 1 --filter=blob:none <url> eval/corpus/<name>
   ```
3. Runs the analyzer on every `.py` file under the cloned tree, excluding
   `.git`, `node_modules`, `venv`, `.venv`, `__pycache__`, `site-packages`,
   `dist`, `build`, `.tox`, `.pytest_cache`.
4. Writes one JSON log per project to `eval/logs/<name>.json` and a combined
   `eval/logs/summary.json`.

### Default corpus

`eval/repos.json` lists ten projects spanning four use cases. The clone
locations are all canonical GitHub repositories.

| Name | Repo | Category |
|------|------|----------|
| open-interpreter | `https://github.com/OpenInterpreter/open-interpreter.git` | shell agent |
| aider | `https://github.com/Aider-AI/aider.git` | code agent |
| gpt-engineer | `https://github.com/AntonOsika/gpt-engineer.git` | code generation |
| crewAI | `https://github.com/crewAIInc/crewAI.git` | agent framework |
| autogen | `https://github.com/microsoft/autogen.git` | agent framework |
| embedchain | `https://github.com/mem0ai/mem0.git` | RAG / memory framework |
| vanna | `https://github.com/vanna-ai/vanna.git` | text-to-SQL |
| openai-cookbook | `https://github.com/openai/openai-cookbook.git` | official OpenAI examples |
| anthropic-cookbook | `https://github.com/anthropics/anthropic-cookbook.git` | official Anthropic examples |
| langchain-templates | `https://github.com/langchain-ai/langchain.git` | LangChain framework + templates |

Shallow blobless clones keep the total size under a few hundred megabytes.

### Driver flags

| Flag | Meaning |
|------|---------|
| `--only <name>` | Run on a single project by its `name` field in `repos.json` |
| `--skip-clone` | Reuse existing clones in `eval/corpus/`, do not refetch |

### Customizing the corpus

Edit `eval/repos.json`. The driver only reads `name`, `repo`, and `category`
for each entry. `notes` is for human readers.

### Where outputs go

```
eval/corpus/<name>/        # the cloned source tree (not committed)
eval/logs/<name>.json      # per-project findings
eval/logs/summary.json     # aggregate
```

`eval/corpus/` and `eval/logs/` are gitignored.

## Known limitations

* **Intra-procedural only.** Labels and typestates do not propagate across
  function boundaries. A function parameter receives its label from a name
  heuristic; the caller's argument is not threaded in.
* **No control-flow merge.** Branches that produce different typestates are
  not joined. The analyzer follows the path order in source.
* **Python dynamic features unsupported.** `eval`, `getattr` with non-literal
  names, `**kwargs` unpacking at call sites, dynamic imports, and
  metaclass-driven rewriting are out of scope.
* **Heuristic source labelling.** Without explicit `PII(...)` / `Secret(...)`
  wrappers the analyzer falls back to name-based heuristics, which will both
  miss labelled-but-renamed values and over-flag innocuous variables that
  happen to share a substring.
* **Sink list is closed.** Custom dangerous sinks need to be added to
  `llmeffect/patterns.py`.

## Layout

```
.
├── llmeffect/             # the analyzer package
│   ├── analyzer.py        # three-phase orchestration
│   ├── labels.py          # label lattice and heuristics
│   ├── patterns.py        # LLM call site, sink, and validator recognition
│   ├── violations.py      # rule catalog and Violation dataclass
│   ├── cli.py             # `llmeffect` entry point
│   └── __main__.py
├── examples/              # vulnerable and safe sample programs
├── tests/                 # pytest suite
├── eval/                  # evaluation harness
│   ├── run.py
│   ├── repos.json
│   └── results.md         # writeup of a prior eval run
├── pyproject.toml
├── run_demo.sh
└── README.md
```

## License

MIT.
