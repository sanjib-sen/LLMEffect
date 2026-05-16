import ast
from dataclasses import dataclass, field
from pathlib import Path

from .labels import Label, WRAPPER_LABELS, heuristic_label_for_name
from .patterns import (
    attr_chain,
    is_llm_call,
    classify_sink,
    is_validator_call,
)
from .violations import Violation, make


@dataclass
class VarState:
    label: Label = Label.TRUSTED
    # typestate: "normal" | "unvalidated" | "validated"
    typestate: str = "normal"
    # Where the LLM call that produced this value was located.
    origin_line: int | None = None
    # Distinct labels that contributed to this value. Join loses information
    # (e.g. PII | Tainted -> PII); keeping the set lets each be reported.
    contributing: frozenset = frozenset()


@dataclass
class FunctionContext:
    file: str
    source_lines: list[str]
    vars: dict[str, VarState] = field(default_factory=dict)
    violations: list[Violation] = field(default_factory=list)


# ---------- label inference ----------

def infer_label(node: ast.AST, ctx: FunctionContext) -> Label:
    if isinstance(node, ast.Constant):
        return Label.TRUSTED

    if isinstance(node, ast.Name):
        if node.id in ctx.vars:
            return ctx.vars[node.id].label
        # Unknown name -> heuristic from identifier.
        h = heuristic_label_for_name(node.id)
        return h if h is not None else Label.TRUSTED

    if isinstance(node, ast.JoinedStr):  # f-string
        labels = [infer_label(v.value, ctx) for v in node.values if isinstance(v, ast.FormattedValue)]
        labels.append(Label.TRUSTED)
        return _join(labels)

    if isinstance(node, ast.BinOp):
        return infer_label(node.left, ctx).join(infer_label(node.right, ctx))

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return _join([infer_label(e, ctx) for e in node.elts] or [Label.TRUSTED])

    if isinstance(node, ast.Dict):
        items = [infer_label(v, ctx) for v in node.values if v is not None]
        return _join(items or [Label.TRUSTED])

    if isinstance(node, ast.Subscript):
        return _label_from_subscript(node, ctx)

    if isinstance(node, ast.Attribute):
        return _label_from_attribute(node, ctx)

    if isinstance(node, ast.Call):
        return _label_from_call(node, ctx)

    if isinstance(node, ast.IfExp):
        return infer_label(node.body, ctx).join(infer_label(node.orelse, ctx))

    return Label.TRUSTED


def _join(labels: list[Label]) -> Label:
    out = Label.TRUSTED
    for l in labels:
        out = out.join(l)
    return out


def contributing_labels(node: ast.AST, ctx: FunctionContext) -> frozenset:
    """Return the set of distinct labels that flow into this expression."""
    if isinstance(node, ast.Constant):
        return frozenset({Label.TRUSTED})
    if isinstance(node, ast.Name):
        if node.id in ctx.vars:
            s = ctx.vars[node.id]
            return s.contributing if s.contributing else frozenset({s.label})
        h = heuristic_label_for_name(node.id)
        return frozenset({h if h is not None else Label.TRUSTED})
    if isinstance(node, ast.JoinedStr):
        out = set()
        for v in node.values:
            if isinstance(v, ast.FormattedValue):
                out |= contributing_labels(v.value, ctx)
        return frozenset(out) or frozenset({Label.TRUSTED})
    if isinstance(node, ast.BinOp):
        return contributing_labels(node.left, ctx) | contributing_labels(node.right, ctx)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out = set()
        for e in node.elts:
            out |= contributing_labels(e, ctx)
        return frozenset(out) or frozenset({Label.TRUSTED})
    if isinstance(node, ast.Dict):
        out = set()
        for v in node.values:
            if v is not None:
                out |= contributing_labels(v, ctx)
        return frozenset(out) or frozenset({Label.TRUSTED})
    # Fall back to the join-level inference for Subscript / Attribute / Call.
    return frozenset({infer_label(node, ctx)})


def _label_from_subscript(node: ast.Subscript, ctx: FunctionContext) -> Label:
    chain = attr_chain(node.value)
    # request.body[...], request.json[...], request.args[...] -> Tainted
    if chain and chain[0] in {"request", "req"} and len(chain) >= 2:
        return Label.TAINTED
    if chain and len(chain) >= 2 and chain[-2] == "request":
        return Label.TAINTED
    if chain and chain[0] == "os" and len(chain) >= 2 and chain[1] == "environ":
        return Label.SECRET
    return infer_label(node.value, ctx)


def _label_from_attribute(node: ast.Attribute, ctx: FunctionContext) -> Label:
    chain = attr_chain(node)
    if chain and chain[0] in {"request", "req"} and len(chain) >= 2:
        return Label.TAINTED
    if len(chain) >= 2 and chain[-2] == "request":
        return Label.TAINTED
    h = heuristic_label_for_name(chain[-1]) if chain else None
    if h is not None:
        return h
    return Label.TRUSTED


def _label_from_call(node: ast.Call, ctx: FunctionContext) -> Label:
    chain = attr_chain(node.func)
    if not chain:
        return Label.TRUSTED

    # Wrapper constructors: Tainted(x), PII(x), Secret(x), ...
    head = chain[-1]
    if head in WRAPPER_LABELS:
        explicit = WRAPPER_LABELS[head]
        # The wrapper at least raises the label to the wrapper's level.
        inner = _join([infer_label(a, ctx) for a in node.args] or [Label.TRUSTED])
        return explicit.join(inner)

    # os.getenv / os.environ.get
    if chain[:2] == ["os", "getenv"] or chain[-2:] == ["environ", "get"]:
        return Label.SECRET

    # Common DB read patterns -> PII (sample row reads).
    if head in {"query", "fetchall", "fetchone", "execute"} and len(chain) >= 2:
        return Label.PII

    # Vector DB / search -> Internal by default.
    if head in {"search", "similarity_search", "retrieve"}:
        return Label.INTERNAL

    return Label.TRUSTED


# ---------- prompt inspection (phase 1) ----------

def _prompt_data_args(call: ast.Call) -> list[ast.AST]:
    """Return the argument expressions that constitute the prompt payload."""
    out: list[ast.AST] = []
    for kw in call.keywords:
        if kw.arg in {"messages", "input", "prompt", "context", "system", "instructions"}:
            out.append(kw.value)
    return out


def _check_role_separation(call: ast.Call) -> bool:
    """True if developer/user role separation is structurally present."""
    # safe_llm_call wrapper guarantees separation by design (instructions/context split).
    chain = attr_chain(call.func)
    if chain and chain[-1] == "safe_llm_call":
        return True
    for kw in call.keywords:
        if kw.arg == "messages" and isinstance(kw.value, ast.List):
            roles = []
            for elt in kw.value.elts:
                if isinstance(elt, ast.Dict):
                    for k, v in zip(elt.keys, elt.values):
                        if isinstance(k, ast.Constant) and k.value == "role" and isinstance(v, ast.Constant):
                            roles.append(v.value)
            if "developer" in roles or "system" in roles:
                return True
    return False


# Nodes considered "value leaves" for prompt-input checking. Containers like
# List/Dict/JoinedStr are skipped because their children are visited instead.
_LEAF_TYPES = (ast.Name, ast.Attribute, ast.Subscript, ast.Call)


def analyze_call_inputs(call: ast.Call, ctx: FunctionContext) -> None:
    role_sep = _check_role_separation(call)
    for arg in _prompt_data_args(call):
        for sub in ast.walk(arg):
            if not isinstance(sub, _LEAF_TYPES):
                continue
            if isinstance(sub, ast.Call) and is_llm_call(sub):
                continue
            labels = contributing_labels(sub, ctx)
            if Label.SECRET in labels:
                ctx.violations.append(make("LLM001", ctx.file, sub.lineno, sub.col_offset,
                                           _describe(sub)))
            if Label.PII in labels:
                ctx.violations.append(make("LLM002", ctx.file, sub.lineno, sub.col_offset,
                                           _describe(sub)))
            if Label.TAINTED in labels and not role_sep:
                ctx.violations.append(make("LLM003", ctx.file, sub.lineno, sub.col_offset,
                                           _describe(sub)))


def _describe(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ".".join(attr_chain(node))
    if isinstance(node, ast.Subscript):
        return f"{_describe(node.value)}[...]"
    return type(node).__name__


# ---------- typestate (phase 2) ----------

def update_typestate_from_assign(target_name: str, value: ast.AST, ctx: FunctionContext) -> None:
    if isinstance(value, ast.Call):
        if is_llm_call(value):
            ctx.vars[target_name] = VarState(
                label=Label.TRUSTED, typestate="unvalidated", origin_line=value.lineno
            )
            return
        if is_validator_call(value):
            # x = something.validate(...) -> validated if base is unvalidated.
            if isinstance(value.func, ast.Attribute):
                base = value.func.value
                if isinstance(base, ast.Name) and base.id in ctx.vars:
                    base_state = ctx.vars[base.id]
                    if base_state.typestate == "unvalidated":
                        ctx.vars[target_name] = VarState(
                            label=base_state.label, typestate="validated",
                            origin_line=base_state.origin_line,
                        )
                        return
        # x = y.value extracts a validated value -> safe.
        if isinstance(value.func, ast.Attribute) and value.func.attr in {"parsed", "value"}:
            pass

    # Pass-through for simple aliasing: x = y
    if isinstance(value, ast.Name) and value.id in ctx.vars:
        ctx.vars[target_name] = VarState(**ctx.vars[value.id].__dict__)
        return

    # Anything derived from an unvalidated value stays unvalidated, including
    # complex expressions like `resp.choices[0].message.content`.
    for sub in ast.walk(value):
        if isinstance(sub, ast.Name) and sub.id in ctx.vars:
            s = ctx.vars[sub.id]
            if s.typestate == "unvalidated":
                ctx.vars[target_name] = VarState(
                    label=s.label, typestate="unvalidated", origin_line=s.origin_line
                )
                return

    # Default: fresh variable, inferred label + contributing source set.
    contrib = contributing_labels(value, ctx)
    ctx.vars[target_name] = VarState(
        label=infer_label(value, ctx),
        contributing=contrib,
    )


def check_sink_for_unvalidated(call: ast.Call, ctx: FunctionContext) -> None:
    sink = classify_sink(call)
    if sink is None:
        return
    kind, name = sink
    for arg in [*call.args, *(kw.value for kw in call.keywords)]:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Name) and sub.id in ctx.vars:
                state = ctx.vars[sub.id]
                if state.typestate == "unvalidated":
                    detail = f"`{sub.id}` -> {name} ({kind})"
                    ctx.violations.append(make("LLM010", ctx.file, call.lineno, call.col_offset, detail))
            if isinstance(sub, ast.Attribute):
                chain = attr_chain(sub)
                if chain and chain[0] in ctx.vars and ctx.vars[chain[0]].typestate == "unvalidated":
                    detail = f"`{chain[0]}.{chain[-1]}` -> {name} ({kind})"
                    ctx.violations.append(make("LLM010", ctx.file, call.lineno, call.col_offset, detail))


# ---------- loops (phase 3) ----------

def _loop_contains_llm_call(loop: ast.AST) -> ast.Call | None:
    # Only the loop body counts. `for x in llm.invoke(...)` and
    # `while client.poll(): ...` are stream/condition expressions, not retries.
    bodies: list = []
    if isinstance(loop, ast.For):
        bodies = list(loop.body) + list(loop.orelse)
    elif isinstance(loop, ast.While):
        bodies = list(loop.body) + list(loop.orelse)
    for stmt in bodies:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call) and is_llm_call(node):
                return node
    return None


def _agent_loop_config_in_scope(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return the number of keyword bounds used in an AgentLoopConfig(...) within the function."""
    best = 0
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            chain = attr_chain(node.func)
            if chain and chain[-1] == "AgentLoopConfig":
                bounds = sum(1 for kw in node.keywords if kw.arg and kw.arg.startswith("max_"))
                if bounds > best:
                    best = bounds
    return best


def _loop_has_explicit_bound(loop: ast.AST) -> bool:
    if isinstance(loop, ast.For):
        # for ... in range(N): / for ... in iterable: -> bounded by iterable length.
        return True
    if isinstance(loop, ast.While):
        # while True: with no counter is unbounded; treat any non-True condition as a bound.
        if isinstance(loop.test, ast.Constant) and loop.test.value is True:
            # Look for a break inside (very rough).
            for n in ast.walk(loop):
                if isinstance(n, ast.Break):
                    return True
            return False
        return True
    return False


def analyze_loops(func_node: ast.FunctionDef | ast.AsyncFunctionDef, ctx: FunctionContext) -> None:
    config_bounds = _agent_loop_config_in_scope(func_node)
    for node in ast.walk(func_node):
        if isinstance(node, (ast.For, ast.While)):
            llm_call = _loop_contains_llm_call(node)
            if llm_call is None:
                continue
            if config_bounds >= 2:
                continue  # dual-bound satisfied
            if not _loop_has_explicit_bound(node):
                ctx.violations.append(make(
                    "LLM020", ctx.file, node.lineno, node.col_offset,
                    "no termination condition and no AgentLoopConfig",
                ))
            else:
                ctx.violations.append(make(
                    "LLM021", ctx.file, node.lineno, node.col_offset,
                    f"only one bound found (AgentLoopConfig fields used: {config_bounds})",
                ))


# ---------- driver ----------

class _FunctionAnalyzer(ast.NodeVisitor):
    def __init__(self, ctx: FunctionContext) -> None:
        self.ctx = ctx

    def visit_Assign(self, node: ast.Assign) -> None:
        # Process the RHS first to catch LLM-call inputs and sink-arg violations.
        self.visit(node.value)
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                update_typestate_from_assign(tgt.id, node.value, self.ctx)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        if is_llm_call(node):
            analyze_call_inputs(node, self.ctx)
        check_sink_for_unvalidated(node, self.ctx)
        self.generic_visit(node)


def _analyze_function(func: ast.FunctionDef | ast.AsyncFunctionDef, ctx: FunctionContext) -> None:
    # Seed: function parameters get heuristic labels.
    for arg in func.args.args:
        h = heuristic_label_for_name(arg.arg)
        ctx.vars[arg.arg] = VarState(label=h if h is not None else Label.TRUSTED)

    _FunctionAnalyzer(ctx).visit(func)
    analyze_loops(func, ctx)


def analyze_source(source: str, filename: str = "<string>") -> list[Violation]:
    tree = ast.parse(source, filename=filename)
    source_lines = source.splitlines()
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ctx = FunctionContext(file=filename, source_lines=source_lines)
            _analyze_function(node, ctx)
            violations.extend(ctx.violations)
    # Also analyze the module body as an implicit function.
    mod_ctx = FunctionContext(file=filename, source_lines=source_lines)
    _ModuleAnalyzer(mod_ctx).visit(tree)
    analyze_loops_module(tree, mod_ctx)
    violations.extend(mod_ctx.violations)

    # Dedupe by (file, line, col, code).
    seen = set()
    unique: list[Violation] = []
    for v in violations:
        key = (v.file, v.line, v.col, v.code, v.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(v)
    unique.sort(key=lambda v: (v.line, v.col, v.code))
    return unique


class _ModuleAnalyzer(_FunctionAnalyzer):
    """Same as function analyzer but only looks at top-level statements."""

    def __init__(self, ctx: FunctionContext) -> None:
        super().__init__(ctx)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # skip; functions are analyzed separately

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return


def analyze_loops_module(tree: ast.Module, ctx: FunctionContext) -> None:
    # Treat the module body as if it were a function for loop detection.
    fake = ast.FunctionDef(
        name="<module>",
        args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=tree.body,
        decorator_list=[],
    )
    analyze_loops(fake, ctx)


def analyze_file(path: str | Path) -> list[Violation]:
    p = Path(path)
    return analyze_source(p.read_text(), filename=str(p))
