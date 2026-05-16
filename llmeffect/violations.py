from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class Violation:
    file: str
    line: int
    col: int
    phase: str          # "labels" | "typestate" | "loops"
    code: str           # short rule id, e.g. "LLM001"
    severity: Severity
    message: str

    def render(self) -> str:
        return f"{self.file}:{self.line}:{self.col}: {self.severity.value} [{self.code}] {self.message}"


# Rule catalog. Centralized so the README and CLI output share the same codes.
RULES = {
    "LLM001": ("labels",    Severity.ERROR,   "Secret value flows into LLM prompt"),
    "LLM002": ("labels",    Severity.ERROR,   "PII value flows into LLM prompt"),
    "LLM003": ("labels",    Severity.WARNING, "Tainted user input flows into LLM prompt without role separation"),
    "LLM010": ("typestate", Severity.ERROR,   "Unvalidated LLM output reaches dangerous sink"),
    "LLM020": ("loops",     Severity.ERROR,   "LLM call inside unbounded loop"),
    "LLM021": ("loops",     Severity.WARNING, "LLM agent loop has only a single iteration bound"),
}


def make(code: str, file: str, line: int, col: int, detail: str) -> Violation:
    phase, severity, base_msg = RULES[code]
    return Violation(
        file=file, line=line, col=col, phase=phase,
        code=code, severity=severity,
        message=f"{base_msg}: {detail}" if detail else base_msg,
    )
