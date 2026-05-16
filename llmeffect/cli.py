import argparse
import sys
from pathlib import Path

from .analyzer import analyze_file
from .violations import Severity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llmeffect", description="Static analyzer for LLM-integrated Python programs.")
    parser.add_argument("paths", nargs="+", help="Files or directories to analyze.")
    parser.add_argument("--no-warnings", action="store_true", help="Suppress warning-level findings.")
    parser.add_argument("--summary", action="store_true", help="Print a summary line at the end.")
    args = parser.parse_args(argv)

    files: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.py")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"warn: {raw} does not exist", file=sys.stderr)

    total_errors = 0
    total_warnings = 0
    total_files = 0

    for f in files:
        total_files += 1
        try:
            violations = analyze_file(f)
        except SyntaxError as e:
            print(f"{f}: syntax error: {e}", file=sys.stderr)
            continue
        for v in violations:
            if v.severity == Severity.WARNING and args.no_warnings:
                continue
            print(v.render())
            if v.severity == Severity.ERROR:
                total_errors += 1
            else:
                total_warnings += 1

    if args.summary:
        print(f"\nscanned {total_files} file(s): {total_errors} error(s), {total_warnings} warning(s)")

    return 1 if total_errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
