#!/usr/bin/env python3
"""jobd-golden.py — run /precheck Job D on the golden-comment benchmark, one model per arm (#1195).

The question: what does Job D's reviewer catch, and at what cost per pass, under each model?
The yardstick is withmartian/code-review-benchmark's `offline/` set (pinned by
fetch-code-review-benchmark.sh). It holds 50 public PRs with human-verified golden comments,
and an upstream pipeline that extracts, de-duplicates and judges candidates against them.

What is held constant across arms, so the only difference is `--model`:
  - the prompt: Job D-full as `skills/precheck/SKILL.md` states it (`jobd_prompt`; the drift
    test pins its wording to the skill's);
  - the system prompt: `feature-dev:code-reviewer`'s agent body, read from the installed plugin
    and recorded with its sha256. `claude -p` cannot select a subagent type, so the persona is
    passed explicitly (the lesson in scripts/ci/pmr-bench-arm.sh's header);
  - the tools: Read, Grep and Glob. The agent's WebFetch and WebSearch are left out on purpose:
    the PRs are public, and a reviewer that could fetch a PR's real review thread would be
    reading the answers;
  - the tree: the PR's head commit, shallow-fetched, with the diff from its base on disk.

Steps, each its own subcommand:
  prepare  <golden_url>                      fetch the PR's diff and head tree into .bench/prs/
  review   <golden_url> --model M --run DIR  one Job D pass; writes DIR/reviews/, DIR/ledger.jsonl
  assemble --run DIR                         DIR/results/benchmark_data.json, holding only
                                             the PRs and arms this run reviewed
  judge    --run DIR --judge-model J         upstream steps 2, 2.5 and 3, through the shim
  report   --run DIR --judge-model J         per-arm precision, recall and cost, as JSON

Upstream runs unmodified, from DIR: its paths are relative to the working directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / ".bench"
OFFLINE = BENCH / "code-review-benchmark" / "offline"
PRS = BENCH / "prs"
AGENT_GLOB = "plugins/cache/claude-plugins-official/feature-dev/*/agents/code-reviewer.md"
REVIEW_TOOLS = "Read,Grep,Glob"
EFFORTS = ("medium", "high", "xhigh")  # the range a /precheck session runs Job D at (#1394)
SPLIT_LINES = 1500  # under Read's 2000-line page, as precheck-review-scope.sh gather splits
REVIEW_FLAGS = [
    "--setting-sources", "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--output-format", "json",
]
# `--setting-sources ""` does not stop CLAUDE.md discovery, which walks up from the cwd. The PR
# trees live under this checkout's .bench/, so without this every pass loaded this repo's
# CLAUDE.md (~9k tokens of rules foreign to the reviewed repo; measured 2026-10-31). It also
# drops a reviewed repo's own CLAUDE.md; `prepare` notes when a tree has one.
ISOLATION_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}


TELEMETRY_KEY = re.compile(r"^(OTEL_|CLAUDE_CODE_ENABLE_TELEMETRY$)")


def telemetry_env(variant: str, case: str, settings: Path = Path.home() / ".claude" / "settings.json") -> dict[str, str]:
    """The fleet's telemetry env for one run, labelled for the A/B capture.

    `--setting-sources ""` keeps user settings, and so hooks, out of every `claude -p`, but that
    also drops the settings' `env` block, which carries the OTEL exporter keys. They are copied
    here, and `OTEL_RESOURCE_ATTRIBUTES` labels the run `precheck_variant=<variant>` and
    `bench_case=<case>` (no spaces; low cardinality: arms × cases).
    """
    env: dict[str, str] = {}
    if settings.exists():
        for k, v in (json.loads(settings.read_text()).get("env") or {}).items():
            if TELEMETRY_KEY.match(k):
                env[k] = str(v)
    for label, value in (("precheck_variant", variant), ("bench_case", case)):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise SystemExit(f"jobd-golden: {label} must be a short token, not {value!r}")
    env["OTEL_RESOURCE_ATTRIBUTES"] = f"precheck_variant={variant},bench_case={case}"
    return env


def case_id(golden_url: str) -> str:
    """A short bench_case label: `<repo>-<number>`."""
    _, repo, num = slug(golden_url).split("__")
    return f"{repo}-{num}"


def tool_name(model: str) -> str:
    """The benchmark's tool key for an arm: `jobd-<model>`."""
    return "jobd-" + re.sub(r"[^A-Za-z0-9.-]+", "-", model)


def slug(golden_url: str) -> str:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)$", golden_url)
    if not m:
        raise SystemExit(f"jobd-golden: not a GitHub PR URL: {golden_url}")
    return f"{m[1]}__{m[2]}__{m[3]}"


def gh_pr(golden_url: str) -> dict[str, Any]:
    owner, repo, _, num = golden_url.removeprefix("https://github.com/").split("/")
    out = subprocess.run(["gh", "api", f"repos/{owner}/{repo}/pulls/{num}"],
                         capture_output=True, text=True, check=True).stdout
    pr = json.loads(out)
    return {"owner": owner, "repo": repo, "number": int(num), "title": pr["title"],
            "base_sha": pr["base"]["sha"], "head_sha": pr["head"]["sha"]}


def jobd_prompt(repo_root: str, total_lines: int, diff_paths: list[str]) -> str:
    """Job D-full, first pass of a cycle, as skills/precheck/SKILL.md states it.

    No untracked files (a benchmark PR is a commit range) and no prior findings (the first pass
    omits that section).
    """
    paths = "\n".join(diff_paths)
    return (
        f"Review this changeset in {repo_root}.\n\n"
        f"### Diff — {total_lines} lines total, read ALL of these files before reviewing\n"
        f"{paths}\n\n"
        "### Untracked files — NOT in the diff above, read each IN FULL\n"
        "(none)\n\n"
        "The diff is given so you do not have to reconstruct it. You still have\n"
        "Read/Grep/Glob — use them freely to pull in whatever context you need to\n"
        "judge these changes: callers, callees, tests, sibling implementations,\n"
        "project rules. Do not restrict yourself to the lines above.\n\n"
        "Use confidence-based filtering — report only issues you are genuinely confident matter.\n"
        "Categorize findings as: critical / important / minor.\n"
        "Return a structured list; if none, say 'No findings'."
    )


def agent_system_prompt(claude_home: Path = Path.home() / ".claude") -> tuple[str, str, str]:
    """The installed code-reviewer agent's body (frontmatter removed), its path and sha256."""
    installed = claude_home / "plugins" / "installed_plugins.json"
    path: Path | None = None
    if installed.exists():
        for key, entries in json.loads(installed.read_text()).get("plugins", {}).items():
            if key.startswith("feature-dev"):
                for e in entries:
                    cand = Path(e["installPath"]) / "agents" / "code-reviewer.md"
                    if cand.exists():
                        path = cand
    if path is None:
        found = sorted(claude_home.glob(AGENT_GLOB))
        if not found:
            raise SystemExit("jobd-golden: feature-dev:code-reviewer is not installed")
        path = found[-1]
    text = path.read_text()
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S).strip()
    return body, str(path), hashlib.sha256(body.encode()).hexdigest()


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def prepare(golden_url: str) -> Path:
    """Fetch the PR's head tree (shallow) and its diff from base, split for Read."""
    pr = gh_pr(golden_url)
    d = PRS / slug(golden_url)
    tree = d / "tree"
    if not (tree / ".git").exists():
        tree.mkdir(parents=True, exist_ok=True)
        git("init", "-q", cwd=tree)
        git("remote", "add", "origin", f"https://github.com/{pr['owner']}/{pr['repo']}.git", cwd=tree)
    have = subprocess.run(["git", "rev-parse", "-q", "--verify", "HEAD"], cwd=tree,
                          capture_output=True, text=True)
    if (have.stdout.strip() if have.returncode == 0 else "") != pr["head_sha"]:
        git("fetch", "-q", "--depth", "1", "origin", pr["head_sha"], cwd=tree)
        git("-c", "advice.detachedHead=false", "checkout", "-q", pr["head_sha"], cwd=tree)
    diff = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github.diff",
                           f"repos/{pr['owner']}/{pr['repo']}/pulls/{pr['number']}"],
                          capture_output=True, text=True, check=True).stdout
    ddir = d / "diff"
    if ddir.exists():
        shutil.rmtree(ddir)
    ddir.mkdir()
    lines = diff.splitlines(keepends=True)
    parts = []
    for i in range(0, max(len(lines), 1), SPLIT_LINES):
        p = ddir / f"part-{i // SPLIT_LINES:03d}.diff"
        p.write_text("".join(lines[i:i + SPLIT_LINES]))
        parts.append(str(p))
    (d / "pr.json").write_text(json.dumps({**pr, "golden_url": golden_url, "diff_lines": len(lines),
                                           "diff_parts": parts, "memory_files": memory_files(tree)},
                                          indent=1))
    return d


MEMORY_NAMES = {"claude.md", "claude.local.md", "agents.md"}


def memory_files(tree: Path) -> list[str]:
    """The tree's own agent-memory files, which ISOLATION_ENV keeps out of the review."""
    return sorted(str(p.relative_to(tree)) for p in tree.rglob("*")
                  if p.name.lower() in MEMORY_NAMES and ".git" not in p.relative_to(tree).parts)


def review_argv(model: str, effort: str, system_file: Path, diff_dir: Path) -> list[str]:
    return ["claude", "-p", "--model", model, "--effort", effort, *REVIEW_FLAGS, "--tools", REVIEW_TOOLS,
            "--allowedTools", REVIEW_TOOLS, "--system-prompt-file", str(system_file),
            "--add-dir", str(diff_dir)]


def arm(model: str, effort: str) -> str:
    """One arm is a model at an effort level. Effort is explicit because `--setting-sources ""`
    drops `effortLevel`, and in /precheck the reviewer inherits the session's level (measured
    2026-10-31, #1394), so no single default stands for production."""
    if effort not in EFFORTS:
        raise SystemExit(f"jobd-golden: effort must be one of {', '.join(EFFORTS)}, not {effort!r}")
    return f"{model}.{effort}"


EFFORT_PAIRS = tuple((a, b) for i, a in enumerate(EFFORTS) for b in EFFORTS[i + 1:])


def plan(urls: list[str], models: list[str], design: str) -> list[tuple[str, str, str]]:
    """The sweep's passes, as (url, model, effort), every model run at each (PR, effort).

    rotate2: each PR at two of the three levels, the pair rotating by PR index. That is a
      balanced incomplete block design, so every pair of levels is compared within the same
      PRs, and PR difficulty cancels out of the effort comparison. Cost: 2 passes per PR per model.
    round-robin: each PR at one level, rotating. 1 pass per PR per model. The effort comparison
      is between PRs, so it detects only a large effect.
    """
    levels = {"rotate2": lambda i: EFFORT_PAIRS[i % len(EFFORT_PAIRS)],
              "round-robin": lambda i: (EFFORTS[i % len(EFFORTS)],)}[design]
    return [(url, m, e) for i, url in enumerate(urls) for e in levels(i) for m in models]


def review(golden_url: str, model: str, run: Path, effort: str) -> dict[str, Any]:
    variant = arm(model, effort)
    run = run.resolve()  # claude -p runs with cwd=<tree>, so every path handed to it must be absolute
    d = PRS / slug(golden_url)
    pr = json.loads((d / "pr.json").read_text())
    body, agent_path, agent_sha = agent_system_prompt()
    run.mkdir(parents=True, exist_ok=True)
    system_file = run / "code-reviewer.system.md"
    if system_file.exists() and hashlib.sha256(system_file.read_text().encode()).hexdigest() != agent_sha:
        raise SystemExit("jobd-golden: the agent definition changed mid-run; start a new run dir")
    system_file.write_text(body)
    prompt = jobd_prompt(str(d / "tree"), pr["diff_lines"], pr["diff_parts"])
    start = time.monotonic()
    env = {**os.environ, **ISOLATION_ENV, **telemetry_env(variant, case_id(golden_url))}
    proc = subprocess.run(review_argv(model, effort, system_file, d / "diff"), input=prompt, cwd=d / "tree",
                          env=env, capture_output=True, text=True, timeout=3600)
    wall = round(time.monotonic() - start, 1)
    if proc.returncode != 0:
        raise SystemExit(f"jobd-golden: claude -p exited {proc.returncode}: {proc.stderr[:500]}")
    out = json.loads(proc.stdout)
    if out.get("is_error") or not isinstance(out.get("result"), str):
        raise SystemExit(f"jobd-golden: the review failed: {str(out.get('result'))[:500]}")
    rec = {
        "golden_url": golden_url, "tool": tool_name(variant), "model": model, "effort": effort,
        "head_sha": pr["head_sha"], "agent_path": agent_path, "agent_sha256": agent_sha,
        "tools": REVIEW_TOOLS, "wall_s": wall, "total_cost_usd": out.get("total_cost_usd"),
        "usage": out.get("usage"), "model_usage": out.get("modelUsage"),
        "num_turns": out.get("num_turns"), "review": out["result"],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    rdir = run / "reviews"
    rdir.mkdir(exist_ok=True)
    (rdir / f"{slug(golden_url)}__{tool_name(variant)}.json").write_text(json.dumps(rec, indent=1))
    with open(run / "ledger.jsonl", "a") as f:
        f.write(json.dumps({k: v for k, v in rec.items() if k != "review"} | {"kind": "review"}) + "\n")
    return rec


def assemble(run: Path, upstream: Path = OFFLINE / "results" / "benchmark_data.json") -> Path:
    """The run's own benchmark_data.json: the reviewed PRs, holding only this run's arms."""
    data = json.loads(upstream.read_text())
    mine: dict[str, Any] = {}
    for f in sorted((run / "reviews").glob("*.json")):
        rec = json.loads(f.read_text())
        url = rec["golden_url"]
        if url not in data:
            raise SystemExit(f"jobd-golden: {url} is not in the benchmark")
        entry = mine.setdefault(url, {**data[url], "reviews": []})
        entry["reviews"].append({"tool": rec["tool"], "repo_name": slug(url), "pr_url": url,
                                 "review_comments": [{"path": None, "line": None, "body": rec["review"]}]})
    out = run / "results" / "benchmark_data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mine, indent=1))
    return out


def judge_env(base_url: str, judge_model: str) -> dict[str, str]:
    """The environment for upstream's steps: the shim as the endpoint, and upstream's package
    importable. `uv run --project` syncs the project's venv but, run from the run dir, does not
    put the project itself on sys.path, so `python -m code_review_benchmark...` would not resolve.
    """
    pythonpath = os.pathsep.join(p for p in (str(OFFLINE), os.environ.get("PYTHONPATH", "")) if p)
    return {**os.environ, "MARTIAN_BASE_URL": base_url, "MARTIAN_API_KEY": "unused",
            "MARTIAN_MODEL": judge_model, "PYTHONPATH": pythonpath}


def judge(run: Path, judge_model: str, workers: int) -> None:
    """Upstream steps 2, 2.5 and 3 from the run dir, the judge served by the shim."""
    run = run.resolve()  # the steps run with cwd=run, so every path handed to them must be absolute
    ledger = run / "judge-ledger.jsonl"
    shim = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "bench" / "claude-openai-shim.py"),
                             "--model", judge_model, "--workers", str(workers), "--ledger", str(ledger)],
                            stdout=subprocess.PIPE, text=True,
                            env={**os.environ, **telemetry_env("judge", run.name)})
    try:
        line = shim.stdout.readline().strip()
        if not line.startswith("listening "):
            raise SystemExit(f"jobd-golden: the shim did not start: {line!r}")
        env = judge_env(line.split(" ", 1)[1], judge_model)
        model_dir = run / "results" / judge_model.replace("/", "_")
        uv = ["uv", "run", "--project", str(OFFLINE), "python", "-m"]
        for step in (["code_review_benchmark.step2_extract_comments"],
                     ["code_review_benchmark.step2_5_dedup_candidates"],
                     ["code_review_benchmark.step3_judge_comments", "--dedup-groups",
                      str(model_dir / "dedup_groups.json")]):
            subprocess.run(uv + step, cwd=run, env=env, check=True)
    finally:
        shim.terminate()
        shim.wait(timeout=30)


def rec_missing(evals: dict[str, Any], url: str, tool: str) -> bool:
    return not isinstance(evals.get(url, {}).get(tool), dict)


def report(run: Path, judge_model: str) -> dict[str, Any]:
    evals = json.loads((run / "results" / judge_model.replace("/", "_") / "evaluations.json").read_text())
    reviews = [json.loads(f.read_text()) for f in sorted((run / "reviews").glob("*.json"))]
    judge_cost = sum((json.loads(x).get("total_cost_usd") or 0)
                     for x in (run / "judge-ledger.jsonl").read_text().splitlines() if x.strip())
    arms: dict[str, Any] = {}
    unjudged = [f"{r['golden_url']} {r['tool']}" for r in reviews
                if rec_missing(evals, r["golden_url"], r["tool"])]
    if unjudged:  # a partial judge run would otherwise read as zero TP, with the pass's cost counted
        raise SystemExit("jobd-golden: no evaluation for: " + "; ".join(unjudged))
    for rec in reviews:
        e = evals[rec["golden_url"]][rec["tool"]]
        a = arms.setdefault(rec["tool"], {"model": rec["model"], "effort": rec.get("effort"),
                                          "passes": [], "tp": 0, "fp": 0, "fn": 0,
                                          "by_severity": {}})
        for key, hits in (("tp", e.get("true_positives") or []), ("fn", e.get("false_negatives") or [])):
            for g in hits:
                s = a["by_severity"].setdefault(g.get("severity") or "unrated", {"tp": 0, "fn": 0})
                s[key] += 1
        a["passes"].append({"golden_url": rec["golden_url"], "cost_usd": rec["total_cost_usd"],
                            "wall_s": rec["wall_s"], "usage": rec["usage"],
                            "precision": e.get("precision"), "recall": e.get("recall")})
        for k in ("tp", "fp", "fn"):
            a[k] += int(e.get(k) or e.get(k.upper()) or 0)
    for a in arms.values():
        a["precision"] = a["tp"] / (a["tp"] + a["fp"]) if a["tp"] + a["fp"] else None
        a["recall"] = a["tp"] / (a["tp"] + a["fn"]) if a["tp"] + a["fn"] else None
        for s in a["by_severity"].values():  # recall per golden severity: High and Critical apart
            s["recall"] = s["tp"] / (s["tp"] + s["fn"])
        a["cost_usd_per_pass"] = sum(p["cost_usd"] or 0 for p in a["passes"]) / len(a["passes"])
        a["wall_s_per_pass"] = sum(p["wall_s"] for p in a["passes"]) / len(a["passes"])
    agent_shas = sorted({r["agent_sha256"] for r in reviews})
    return {"judge_model": judge_model, "judge_cost_usd": round(judge_cost, 4),
            "agent_sha256": agent_shas, "tools": REVIEW_TOOLS, "arms": arms}


def models_arg(value: str) -> list[str]:
    """`plan --models`: an empty entry would plan a pass that fails at `claude -p`, and a
    repeated one would run every pass of that arm twice."""
    models = value.split(",")
    if any(not m.strip() for m in models) or len(set(models)) != len(models):
        raise argparse.ArgumentTypeError(f"want distinct, non-empty models: {value!r}")
    return models


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("prepare")
    sp.add_argument("golden_url")
    sr = sub.add_parser("review")
    sr.add_argument("golden_url")
    sr.add_argument("--model", required=True)
    sr.add_argument("--effort", required=True, choices=EFFORTS)
    sr.add_argument("--run", required=True, type=Path)
    spl = sub.add_parser("plan")
    spl.add_argument("--design", required=True, choices=("rotate2", "round-robin"))
    spl.add_argument("--models", required=True, type=models_arg, help="comma-separated")
    spl.add_argument("urls", nargs="+")
    sa = sub.add_parser("assemble")
    sa.add_argument("--run", required=True, type=Path)
    sj = sub.add_parser("judge")
    sj.add_argument("--run", required=True, type=Path)
    sj.add_argument("--judge-model", required=True)
    sj.add_argument("--workers", type=int, default=6)
    so = sub.add_parser("report")
    so.add_argument("--run", required=True, type=Path)
    so.add_argument("--judge-model", required=True)
    a = p.parse_args(argv)
    if a.cmd == "prepare":
        print(prepare(a.golden_url))
    elif a.cmd == "review":
        rec = review(a.golden_url, a.model, a.run, a.effort)
        print(json.dumps({k: rec[k] for k in ("tool", "wall_s", "total_cost_usd", "num_turns")}))
    elif a.cmd == "plan":
        for url, model, effort in plan(a.urls, a.models, a.design):
            print(f"{url}\t{model}\t{effort}")
    elif a.cmd == "assemble":
        print(assemble(a.run))
    elif a.cmd == "judge":
        judge(a.run, a.judge_model, a.workers)
    else:
        print(json.dumps(report(a.run, a.judge_model), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
