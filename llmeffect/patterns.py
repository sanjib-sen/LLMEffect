import ast


# (attr1, attr2, ...) suffix tuples that identify LLM call sites on
# native SDKs (OpenAI, Anthropic) or thin wrappers (litellm).
LLM_CALL_SUFFIXES = [
    ("chat", "completions", "create"),
    ("chat", "completions", "acreate"),
    ("completions", "create"),
    ("messages", "create"),
    ("messages", "stream"),
    ("responses", "create"),
    ("responses", "stream"),
    # litellm: litellm.completion(...), litellm.acompletion(...)
    ("litellm", "completion"),
    ("litellm", "acompletion"),
]

# Runtime helper that wraps an LLM call with role separation and labelled inputs.
LLM_HELPER_NAMES = {"safe_llm_call"}

# Plain function names that, when called as completion(...) / acompletion(...),
# are treated as LLM calls (e.g. `from litellm import completion`).
LLM_FUNCTION_NAMES = {"completion", "acompletion"}

# When .invoke() / .generate() / .ainvoke() / .agenerate() is called on a
# receiver whose lowercase name matches one of these, treat it as an LLM call.
# Covers LangChain (`llm.invoke(...)`, `chat.invoke(...)`), LlamaIndex
# (`llm.complete(...)`, `llm.chat(...)`), and common conventions.
LLM_RECEIVER_NAMES = {"llm", "chat", "chat_model", "chatmodel", "model", "client",
                       "agent", "chain", "runnable"}
LLM_METHOD_NAMES = {"invoke", "ainvoke", "generate", "agenerate",
                     "complete", "acomplete", "chat", "achat",
                     "predict", "apredict", "call", "acall"}


# Dangerous sinks: method-name -> sink kind.
METHOD_SINKS = {
    "execute": "db",
    "executemany": "db",
    "executescript": "db",
    "raw": "db",
}

# Function-name + module sinks.
SHELL_FUNCS = {"system", "popen", "run", "call", "Popen", "check_output", "check_call"}
EVAL_FUNCS = {"eval", "exec", "compile"}
URL_FUNCS = {"get", "post", "put", "delete", "patch", "request", "urlopen"}

# Built-in validator class names.
VALIDATOR_CLASSES = {"DatabaseCall", "ShellExec", "URLFetch"}
VALIDATE_METHOD = "validate"


def attr_chain(node: ast.AST) -> list[str]:
    chain: list[str] = []
    while isinstance(node, ast.Attribute):
        chain.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        chain.append(node.id)
    elif isinstance(node, ast.Call):
        chain.append("<call>")
    return list(reversed(chain))


def is_llm_call(node: ast.Call) -> bool:
    chain = attr_chain(node.func)
    if not chain:
        return False
    if chain[-1] in LLM_HELPER_NAMES:
        return True
    for suffix in LLM_CALL_SUFFIXES:
        if len(chain) >= len(suffix) and tuple(chain[-len(suffix):]) == suffix:
            return True
    # Bare-name LLM functions: completion(...), acompletion(...) from litellm.
    if len(chain) == 1 and chain[0] in LLM_FUNCTION_NAMES:
        return True
    # Heuristic: <receiver>.<method>() where the receiver name strongly
    # suggests an LLM/chat-model object (LangChain, LlamaIndex conventions).
    if (
        len(chain) >= 2
        and chain[-1] in LLM_METHOD_NAMES
        and chain[-2].lower() in LLM_RECEIVER_NAMES
    ):
        return True
    return False


def classify_sink(node: ast.Call) -> tuple[str, str] | None:
    chain = attr_chain(node.func)
    if not chain:
        return None
    last = chain[-1]
    if last in METHOD_SINKS:
        return (METHOD_SINKS[last], ".".join(chain))
    # subprocess.* / os.system / os.popen
    if len(chain) >= 2:
        head, tail = chain[0], chain[-1]
        if head == "subprocess" and tail in SHELL_FUNCS:
            return ("shell", ".".join(chain))
        if head == "os" and tail in SHELL_FUNCS:
            return ("shell", ".".join(chain))
        if head == "requests" and tail in URL_FUNCS:
            return ("url", ".".join(chain))
        if head == "urllib" and tail in URL_FUNCS:
            return ("url", ".".join(chain))
    if len(chain) == 1 and last in EVAL_FUNCS:
        return ("eval", last)
    return None


def is_validator_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute) and node.func.attr == VALIDATE_METHOD:
        return True
    chain = attr_chain(node.func)
    return bool(chain) and chain[-1] in VALIDATOR_CLASSES
