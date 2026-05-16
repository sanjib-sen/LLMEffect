"""Evaluation driver: shallow-clone corpus, run analyzer, dump per-repo logs."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus"
LOGS = ROOT / "logs"
REPOS_FILE = ROOT / "repos.json"


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check, text=True,
                          capture_output=True, timeout=timeout)


def clone(repo: dict) -> Path:
    target = CORPUS / repo["name"]
    if target.exists():
        return target
    print(f"  cloning {repo['repo']} ...", flush=True)
    try:
        sh(["git", "clone", "--depth", "1", "--filter=blob:none", repo["repo"], str(target)],
           check=True, timeout=180)
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT cloning {repo['name']}", file=sys.stderr)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    except subprocess.CalledProcessError as e:
        print(f"  FAIL cloning {repo['name']}: {e.stderr.strip()[:200]}", file=sys.stderr)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    return target


# Skip noise: vendored deps, generated code, tests we don't want to count.
SKIP_DIR_PARTS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "site-packages", "dist", "build", ".tox", ".pytest_cache",
}


def python_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIR_PARTS for part in p.parts):
            continue
        out.append(p)
    return out


def analyze_repo(name: str, path: Path) -> dict:
    from llmeffect import analyze_file

    files = python_files(path)
    violations: list = []
    syntax_errors = 0
    for f in files:
        try:
            violations.extend(analyze_file(f))
        except SyntaxError:
            syntax_errors += 1
        except Exception as e:  # be defensive on third-party code
            print(f"  warn: {f}: {type(e).__name__}: {e}", file=sys.stderr)
    counts = Counter(v.code for v in violations)
    return {
        "name": name,
        "files_scanned": len(files),
        "syntax_errors": syntax_errors,
        "total_violations": len(violations),
        "by_rule": dict(counts),
        "violations": [
            {"file": str(Path(v.file).relative_to(path)), "line": v.line, "col": v.col,
             "code": v.code, "severity": v.severity.value, "message": v.message}
            for v in violations
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="only run on a single repo name")
    p.add_argument("--skip-clone", action="store_true")
    args = p.parse_args(argv)

    CORPUS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    repos = json.loads(REPOS_FILE.read_text())
    if args.only:
        repos = [r for r in repos if r["name"] == args.only]
        if not repos:
            print(f"unknown repo: {args.only}", file=sys.stderr)
            return 2

    summary: list[dict] = []
    for repo in repos:
        print(f"\n[{repo['name']}] ({repo['category']})")
        path = CORPUS / repo["name"]
        if not args.skip_clone:
            path = clone(repo)
        if not path.exists():
            print(f"  skipped (no clone)")
            continue
        result = analyze_repo(repo["name"], path)
        result["category"] = repo["category"]
        (LOGS / f"{repo['name']}.json").write_text(json.dumps(result, indent=2))
        print(f"  files={result['files_scanned']}  syntax_err={result['syntax_errors']}  "
              f"violations={result['total_violations']}  by_rule={result['by_rule']}")
        summary.append({k: result[k] for k in ("name", "category", "files_scanned",
                                                "syntax_errors", "total_violations", "by_rule")})

    (LOGS / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n== summary ==")
    for s in summary:
        print(f"  {s['name']:24s} files={s['files_scanned']:>5}  vio={s['total_violations']:>4}  {s['by_rule']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
