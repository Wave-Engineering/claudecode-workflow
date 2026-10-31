"""scripts/bench/jobd-golden.py: Job D on the golden-comment benchmark (#1195).

Hermetic: nothing here calls gh, git or a model. The prompt-drift test pins the bench's Job D
prompt to the wording in skills/precheck/SKILL.md, so an edit to the skill cannot leave the
bench quietly measuring an old prompt.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = str(ROOT / "scripts" / "bench" / "jobd-golden.py")
_loader = importlib.machinery.SourceFileLoader("jobd_golden", _SCRIPT)
_spec = importlib.util.spec_from_file_location("jobd_golden", _SCRIPT, loader=_loader)
jg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jg)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _skill_jobd_full() -> str:
    """The prompt text of the Job D-full block in skills/precheck/SKILL.md."""
    skill = (ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    block = skill.split("**Job D-full**", 1)[1].split("```", 2)[1]
    return block.split('prompt: "', 1)[1].rsplit('"', 1)[0]


# The instruction sentences of the skill's Job D-full prompt: everything but its placeholders
# and the prior-findings section, which a first pass omits.
SKILL_SENTENCES = [
    "The diff is given so you do not have to reconstruct it.",
    "You still have Read/Grep/Glob — use them freely to pull in whatever context you need to "
    "judge these changes: callers, callees, tests, sibling implementations, project rules.",
    "Do not restrict yourself to the lines above.",
    "Use confidence-based filtering — report only issues you are genuinely confident matter.",
    "Categorize findings as: critical / important / minor.",
    "Return a structured list; if none, say 'No findings'.",
]


@pytest.mark.parametrize("sentence", SKILL_SENTENCES)
def test_bench_prompt_matches_the_skills_job_d_full(sentence):
    assert _norm(sentence) in _norm(_skill_jobd_full()), "the skill changed: update jobd_prompt"
    assert _norm(sentence) in _norm(jg.jobd_prompt("/t", 10, ["/d/part-000.diff"]))


def test_prompt_names_the_tree_the_line_count_and_every_diff_part():
    p = jg.jobd_prompt("/bench/tree", 3001, ["/d/part-000.diff", "/d/part-001.diff", "/d/part-002.diff"])
    assert p.startswith("Review this changeset in /bench/tree.")
    assert "3001 lines total" in p
    for part in ("/d/part-000.diff", "/d/part-001.diff", "/d/part-002.diff"):
        assert part in p
    assert "Findings from the previous pass" not in p  # a first pass omits it


def test_review_runs_read_only_tools_and_never_the_web():
    argv = jg.review_argv("claude-opus-5-5", "high", Path("/r/sys.md"), Path("/d"))
    assert argv[:4] == ["claude", "-p", "--model", "claude-opus-5-5"]
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    joined = " ".join(argv)
    assert "WebFetch" not in joined and "WebSearch" not in joined and "Bash" not in joined
    assert argv[argv.index("--system-prompt-file") + 1] == "/r/sys.md"
    assert argv[argv.index("--add-dir") + 1] == "/d"
    assert "--bare" not in argv


def test_arms_differ_only_by_model_and_effort():
    a = jg.review_argv("claude-sonnet-5-5", "medium", Path("/r/sys.md"), Path("/d"))
    b = jg.review_argv("claude-opus-5-5", "xhigh", Path("/r/sys.md"), Path("/d"))
    assert ([x for x in a if x not in ("claude-sonnet-5-5", "medium")]
            == [x for x in b if x not in ("claude-opus-5-5", "xhigh")])


def test_an_arm_is_a_model_at_an_effort_and_refuses_other_levels():
    assert jg.arm("claude-sonnet-5-5", "xhigh") == "claude-sonnet-5-5.xhigh"
    assert jg.tool_name(jg.arm("claude-opus-5-5", "medium")) == "jobd-claude-opus-5-5.medium"
    for bad in ("low", "max", ""):
        with pytest.raises(SystemExit):
            jg.arm("claude-opus-5-5", bad)


def test_rotate2_gives_each_pr_two_levels_and_balances_every_pair():
    urls = [f"https://github.com/o/r/pull/{n}" for n in range(1, 51)]
    passes = jg.plan(urls, ["s", "o"], "rotate2")
    assert len(passes) == 50 * 2 * 2
    by_pr: dict[str, set[str]] = {}
    for url, model, effort in passes:
        by_pr.setdefault(url, set()).add(effort)
    assert all(len(levels) == 2 for levels in by_pr.values())
    counts = {pair: sum(1 for lv in by_pr.values() if lv == set(pair)) for pair in jg.EFFORT_PAIRS}
    assert set(counts) == {("medium", "high"), ("medium", "xhigh"), ("high", "xhigh")}
    assert max(counts.values()) - min(counts.values()) <= 1  # 17/17/16 over 50 PRs
    for url, effort in {(u, e) for u, _, e in passes}:  # both models at every (PR, level): paired
        assert {m for u, m, e in passes if u == url and e == effort} == {"s", "o"}


def test_round_robin_gives_each_pr_one_level_in_rotation():
    urls = [f"https://github.com/o/r/pull/{n}" for n in range(1, 7)]
    passes = jg.plan(urls, ["s", "o"], "round-robin")
    assert len(passes) == 6 * 2
    assert [e for _, m, e in passes if m == "s"] == ["medium", "high", "xhigh"] * 2


def test_telemetry_env_carries_the_fleet_keys_and_the_ab_labels(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"env": {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1", "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317", "UNRELATED": "x"}}))
    env = jg.telemetry_env("claude-opus-5-5", "keycloak-37429", settings)
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://collector:4317"
    assert "UNRELATED" not in env
    assert env["OTEL_RESOURCE_ATTRIBUTES"] == "precheck_variant=claude-opus-5-5,bench_case=keycloak-37429"


@pytest.mark.parametrize("bad", ["has space", "a,b", "k=v", ""])
def test_telemetry_labels_must_be_short_tokens(tmp_path, bad):
    with pytest.raises(SystemExit):
        jg.telemetry_env(bad, "case", tmp_path / "none.json")


def test_case_id_is_repo_and_number():
    assert jg.case_id("https://github.com/keycloak/keycloak/pull/37429") == "keycloak-37429"


def test_tool_names_are_stable_keys():
    assert jg.tool_name("claude-sonnet-5-5") == "jobd-claude-sonnet-5-5"
    assert jg.tool_name("anthropic/claude-opus") == "jobd-anthropic-claude-opus"


def test_slug_refuses_a_non_pr_url():
    assert jg.slug("https://github.com/getsentry/sentry/pull/93824") == "getsentry__sentry__93824"
    with pytest.raises(SystemExit):
        jg.slug("https://github.com/getsentry/sentry/issues/1")


def test_agent_system_prompt_strips_frontmatter_and_hashes_the_body(tmp_path):
    install = tmp_path / "plugins" / "cache" / "x" / "feature-dev" / "1.0.1"
    (install / "agents").mkdir(parents=True)
    (install / "agents" / "code-reviewer.md").write_text(
        "---\nname: code-reviewer\ntools: Read\n---\n\nYou are an expert code reviewer.\n")
    (tmp_path / "plugins" / "installed_plugins.json").write_text(json.dumps(
        {"plugins": {"feature-dev@claude-plugins-official": [{"installPath": str(install)}]}}))
    body, path, sha = jg.agent_system_prompt(tmp_path)
    assert body == "You are an expert code reviewer."
    assert path.endswith("1.0.1/agents/code-reviewer.md")
    assert len(sha) == 64


def test_review_env_keeps_every_claude_md_out(tmp_path, monkeypatch):
    seen, argvs = {}, []

    def fake_run(argv, **kw):
        seen.update(kw["env"])
        argvs.append(argv)
        raise SystemExit("stop after the spawn")

    d = tmp_path / "prs" / "o__r__1"
    (d / "tree").mkdir(parents=True)
    (d / "pr.json").write_text(json.dumps({"diff_lines": 1, "diff_parts": [str(d / "p.diff")]}))
    monkeypatch.setattr(jg, "PRS", tmp_path / "prs")
    monkeypatch.setattr(jg, "agent_system_prompt", lambda: ("body", "/a.md", "0" * 64))
    monkeypatch.setattr(jg.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        jg.review("https://github.com/o/r/pull/1", "claude-opus-5-5", Path("run"), "xhigh")  # relative run
    assert seen["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert seen["OTEL_RESOURCE_ATTRIBUTES"].startswith("precheck_variant=claude-opus-5-5.xhigh,")
    assert argvs[0][argvs[0].index("--effort") + 1] == "xhigh"
    sys_file = argvs[0][argvs[0].index("--system-prompt-file") + 1]
    assert sys_file == str(tmp_path / "run" / "code-reviewer.system.md")  # absolute: cwd is the tree


def test_memory_files_lists_a_trees_own_but_not_gits(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "AGENTS.md").write_text("x")
    (tmp_path / "sub" / "CLAUDE.md").write_text("x")
    (tmp_path / ".git" / "CLAUDE.md").write_text("x")
    (tmp_path / "README.md").write_text("x")
    assert jg.memory_files(tmp_path) == ["AGENTS.md", "sub/CLAUDE.md"]


def test_judge_env_points_upstream_at_the_shim_and_makes_its_package_importable(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/elsewhere")
    env = jg.judge_env("http://127.0.0.1:5555/v1", "claude-sonnet-5-5")
    assert env["MARTIAN_BASE_URL"] == "http://127.0.0.1:5555/v1"
    assert env["MARTIAN_MODEL"] == "claude-sonnet-5-5"
    assert env["MARTIAN_API_KEY"] == "unused"
    assert env["PYTHONPATH"].split(":") == [str(jg.OFFLINE), "/elsewhere"]


def test_review_records_the_effort_in_the_record_its_file_and_the_ledger(tmp_path, monkeypatch):
    def fake_run(argv, **kw):
        out = {"result": "No findings", "total_cost_usd": 0.5, "usage": {}, "num_turns": 3}
        return jg.subprocess.CompletedProcess(argv, 0, stdout=json.dumps(out), stderr="")

    d = tmp_path / "prs" / "o__r__1"
    (d / "tree").mkdir(parents=True)
    (d / "pr.json").write_text(json.dumps({"diff_lines": 1, "diff_parts": [str(d / "p.diff")],
                                           "head_sha": "b" * 40}))
    monkeypatch.setattr(jg, "PRS", tmp_path / "prs")
    monkeypatch.setattr(jg, "agent_system_prompt", lambda: ("body", "/a.md", "0" * 64))
    monkeypatch.setattr(jg.subprocess, "run", fake_run)
    run = tmp_path / "run"
    rec = jg.review("https://github.com/o/r/pull/1", "claude-sonnet-5-5", run, "high")
    assert rec["effort"] == "high" and rec["tool"] == "jobd-claude-sonnet-5-5.high"
    saved = json.loads((run / "reviews" / "o__r__1__jobd-claude-sonnet-5-5.high.json").read_text())
    assert saved["effort"] == "high"
    ledger = json.loads((run / "ledger.jsonl").read_text())
    assert ledger["effort"] == "high" and "review" not in ledger


def test_review_cli_requires_an_effort(tmp_path):
    with pytest.raises(SystemExit) as e:
        jg.main(["review", "https://github.com/o/r/pull/1", "--model", "claude-opus-5-5",
                 "--run", str(tmp_path)])
    assert e.value.code == 2  # argparse's usage error, before any spawn


def test_plan_cli_prints_one_tab_separated_pass_per_line(capsys):
    assert jg.main(["plan", "--design", "round-robin", "--models", "a,b",
                    "https://github.com/o/r/pull/1"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"https://github.com/o/r/pull/1\ta\t{jg.EFFORTS[0]}",
        f"https://github.com/o/r/pull/1\tb\t{jg.EFFORTS[0]}"]


@pytest.mark.parametrize("models", ["a,", "a,,b", ",a", "a,a", "a, a", "a, "])
def test_plan_cli_refuses_an_empty_or_repeated_model(models):
    with pytest.raises(SystemExit) as e:
        jg.main(["plan", "--design", "rotate2", "--models", models, "https://github.com/o/r/pull/1"])
    assert e.value.code == 2


def _review(run: Path, url: str, model: str, text: str, effort: str | None = None) -> None:
    (run / "reviews").mkdir(parents=True, exist_ok=True)
    tool = jg.tool_name(jg.arm(model, effort) if effort else model)
    rec = {"golden_url": url, "tool": tool, "model": model, "effort": effort, "review": text,
           "agent_sha256": "a" * 64, "total_cost_usd": 1.0, "wall_s": 60.0, "usage": {}}
    (run / "reviews" / f"{jg.slug(url)}__{tool}.json").write_text(json.dumps(rec))


def test_assemble_keeps_only_the_reviewed_prs_and_this_runs_arms(tmp_path):
    url, other = "https://github.com/o/r/pull/1", "https://github.com/o/r/pull/2"
    upstream = tmp_path / "benchmark_data.json"
    golden = [{"comment": "a null deref", "severity": "High"}]
    upstream.write_text(json.dumps({
        url: {"pr_title": "t", "golden_comments": golden, "reviews": [{"tool": "coderabbit"}]},
        other: {"pr_title": "u", "golden_comments": [], "reviews": []},
    }))
    run = tmp_path / "run"
    _review(run, url, "claude-sonnet-5-5", "1. critical: a null deref in f()")
    _review(run, url, "claude-opus-5-5", "No findings")
    out = json.loads(jg.assemble(run, upstream).read_text())
    assert list(out) == [url]
    assert out[url]["golden_comments"] == golden
    tools = sorted(r["tool"] for r in out[url]["reviews"])
    assert tools == ["jobd-claude-opus-5-5", "jobd-claude-sonnet-5-5"]
    body = next(r for r in out[url]["reviews"] if r["tool"] == "jobd-claude-sonnet-5-5")
    assert body["review_comments"] == [{"path": None, "line": None, "body": "1. critical: a null deref in f()"}]


def test_report_totals_each_arm_and_splits_recall_by_golden_severity(tmp_path):
    run = tmp_path / "run"
    u1, u2 = "https://github.com/o/r/pull/1", "https://github.com/o/r/pull/2"
    _review(run, u1, "claude-sonnet-5-5", "x")
    _review(run, u2, "claude-sonnet-5-5", "y")
    tool = jg.tool_name("claude-sonnet-5-5")
    evals = {
        u1: {tool: {"tp": 1, "fp": 2, "fn": 1, "precision": 1 / 3, "recall": 0.5,
                    "true_positives": [{"severity": "Critical"}],
                    "false_negatives": [{"severity": "High"}]}},
        u2: {tool: {"tp": 1, "fp": 0, "fn": 0, "precision": 1.0, "recall": 1.0,
                    "true_positives": [{"severity": "High"}], "false_negatives": []}},
    }
    edir = run / "results" / "claude-sonnet-5-5"
    edir.mkdir(parents=True)
    (edir / "evaluations.json").write_text(json.dumps(evals))
    (run / "judge-ledger.jsonl").write_text('{"total_cost_usd": 0.25}\n{"total_cost_usd": 0.5}\n')
    out = jg.report(run, "claude-sonnet-5-5")
    arm = out["arms"][tool]
    assert (arm["tp"], arm["fp"], arm["fn"]) == (2, 2, 1)
    assert arm["precision"] == 0.5 and arm["recall"] == 2 / 3
    assert arm["by_severity"] == {"Critical": {"tp": 1, "fn": 0, "recall": 1.0},
                                  "High": {"tp": 1, "fn": 1, "recall": 0.5}}
    assert arm["cost_usd_per_pass"] == 1.0 and out["judge_cost_usd"] == 0.75
    assert out["judge_model"] == "claude-sonnet-5-5"


def test_report_keeps_one_models_efforts_as_separate_arms(tmp_path):
    run = tmp_path / "run"
    url = "https://github.com/o/r/pull/1"
    _review(run, url, "claude-opus-5-5", "x", "medium")
    _review(run, url, "claude-opus-5-5", "y", "xhigh")
    med, xhi = jg.tool_name("claude-opus-5-5.medium"), jg.tool_name("claude-opus-5-5.xhigh")
    edir = run / "results" / "claude-sonnet-5-5"
    edir.mkdir(parents=True)
    (edir / "evaluations.json").write_text(json.dumps(
        {url: {med: {"tp": 1, "fp": 0, "fn": 1}, xhi: {"tp": 2, "fp": 1, "fn": 0}}}))
    (run / "judge-ledger.jsonl").write_text("")
    arms = jg.report(run, "claude-sonnet-5-5")["arms"]
    assert sorted(arms) == sorted([med, xhi])
    assert (arms[med]["effort"], arms[med]["tp"]) == ("medium", 1)
    assert (arms[xhi]["effort"], arms[xhi]["tp"]) == ("xhigh", 2)
    assert arms[med]["model"] == arms[xhi]["model"] == "claude-opus-5-5"


def test_report_refuses_a_review_the_judge_never_evaluated(tmp_path):
    run = tmp_path / "run"
    url = "https://github.com/o/r/pull/1"
    _review(run, url, "claude-sonnet-5-5", "x")
    _review(run, url, "claude-opus-5-5", "y")
    edir = run / "results" / "claude-sonnet-5-5"
    edir.mkdir(parents=True)
    (edir / "evaluations.json").write_text(json.dumps(
        {url: {jg.tool_name("claude-sonnet-5-5"): {"tp": 0, "fp": 0, "fn": 1}}}))
    (run / "judge-ledger.jsonl").write_text("")
    with pytest.raises(SystemExit) as e:
        jg.report(run, "claude-sonnet-5-5")
    assert "jobd-claude-opus-5-5" in str(e.value)


def test_assemble_refuses_a_pr_outside_the_benchmark(tmp_path):
    upstream = tmp_path / "benchmark_data.json"
    upstream.write_text("{}")
    run = tmp_path / "run"
    _review(run, "https://github.com/o/r/pull/9", "claude-opus-5-5", "x")
    with pytest.raises(SystemExit):
        jg.assemble(run, upstream)


SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"


def _judged_run(tmp_path: Path, cells: dict[tuple[int, str, str], tuple[int, int, float]]) -> Path:
    """A judged run: (pr, model, effort) -> (tp, fp, cost). Each pass misses one golden. Its
    false positives are numbered by PR and level, never named by model, so a test can tell
    whether a worksheet's table leaks the arm."""
    run = tmp_path / "run"
    evals: dict = {}
    for (pr, model, effort), (tp, fp, cost) in cells.items():
        url = f"https://github.com/o/r/pull/{pr}"
        _review(run, url, model, "x", effort)
        tool = jg.tool_name(jg.arm(model, effort))
        f = run / "reviews" / f"{jg.slug(url)}__{tool}.json"
        f.write_text(json.dumps(json.loads(f.read_text()) | {"total_cost_usd": cost, "num_turns": 3}))
        evals.setdefault(url, {})[tool] = {
            "tp": tp, "fp": fp, "fn": 1,
            "false_positives": [{"candidate": f"finding {pr}.{effort}.{len(model)}.{i}"} for i in range(fp)]}
    edir = run / "results" / SONNET
    edir.mkdir(parents=True)
    (edir / "evaluations.json").write_text(json.dumps(evals))
    (run / "judge-ledger.jsonl").write_text("")
    return run


def test_passes_one_record_per_review(tmp_path):
    run = _judged_run(tmp_path, {(1, SONNET, "medium"): (2, 1, 0.2), (1, OPUS, "high"): (3, 0, 0.8)})
    ps = sorted(jg.passes(run, SONNET), key=lambda p: p["model"])
    assert [(p["model"], p["effort"], p["tp"], p["fp"], p["fn"], p["cost_usd"], p["turns"]) for p in ps] == [
        (OPUS, "high", 3, 0, 1, 0.8, 3), (SONNET, "medium", 2, 1, 1, 0.2, 3)]
    assert ps[1]["false_positives"] == [f"finding 1.medium.{len(SONNET)}.0"]
    _review(run, "https://github.com/o/r/pull/9", SONNET, "x", "xhigh")
    with pytest.raises(SystemExit):
        jg.passes(run, SONNET)


def test_compare_model_pairs_by_pr_and_effort(tmp_path):
    run = _judged_run(tmp_path, {
        (1, OPUS, "medium"): (2, 0, 0.5), (1, SONNET, "medium"): (3, 0, 0.1),  # sonnet wins
        (2, OPUS, "medium"): (2, 0, 0.4), (2, SONNET, "medium"): (2, 0, 0.2),  # tie
        (3, OPUS, "medium"): (3, 0, 0.8), (3, SONNET, "medium"): (1, 0, 0.4),  # sonnet loses
        (4, OPUS, "medium"): (1, 0, 0.5),  # no sonnet pass on PR 4: not a pair
    })
    out = jg.compare(run, SONNET)
    cell = out["model"][f"{SONNET} vs {OPUS}"]["medium"]
    assert (cell["n"], cell["tp_wins"], cell["tp_ties"], cell["tp_losses"]) == (3, 1, 1, 1)
    assert (cell["a"]["tp"], cell["b"]["tp"]) == (7, 6)
    assert cell["a"]["recall"] == 7 / 10 and cell["sign_p"] == 1.0
    assert out["model"][f"{SONNET} vs {OPUS}"]["pooled"]["n"] == 3
    assert out["effort"] == {}


def test_compare_effort_pairs_within_pr(tmp_path):
    cells = {}
    for pr, url_levels in enumerate(jg.EFFORT_PAIRS, 1):  # rotate2: PR i at the i-th level pair
        for e in url_levels:
            cells[(pr, OPUS, e)] = (1 + jg.EFFORTS.index(e), 0, 1.0 + jg.EFFORTS.index(e))
    out = jg.compare(run := _judged_run(tmp_path, cells), SONNET)
    assert run.exists() and sorted(out["effort"]) == ["high vs medium", "xhigh vs high", "xhigh vs medium"]
    for key, (lo, hi) in (("high vs medium", ("medium", "high")), ("xhigh vs medium", ("medium", "xhigh")),
                          ("xhigh vs high", ("high", "xhigh"))):
        cell = out["effort"][key][OPUS]
        assert cell["n"] == 1 and cell["tp_wins"] == 1  # the higher level is B, and it caught more
        assert cell["a"]["tp"] == 1 + jg.EFFORTS.index(lo) and cell["b"]["tp"] == 1 + jg.EFFORTS.index(hi)
        assert out["effort"][key]["pooled"]["n"] == 1


@pytest.mark.parametrize("wins,losses,p", [(0, 0, 1.0), (5, 0, 0.0625), (1, 4, 0.375), (3, 3, 1.0)])
def test_sign_test_exact(wins, losses, p):
    assert jg.sign_test(wins, losses) == pytest.approx(p)


def test_cost_ratio_geomean_and_median(tmp_path):
    run = _judged_run(tmp_path, {
        (1, OPUS, "medium"): (1, 0, 1.0), (1, SONNET, "medium"): (1, 0, 0.5),
        (2, OPUS, "medium"): (1, 0, 1.0), (2, SONNET, "medium"): (1, 0, 2.0),
        (3, OPUS, "medium"): (1, 0, 1.0), (3, SONNET, "medium"): (1, 0, 4.0),
    })
    cell = jg.compare(run, SONNET)["model"][f"{SONNET} vs {OPUS}"]["medium"]
    assert cell["cost_ratio_geomean"] == pytest.approx(1.587, abs=1e-3)  # (0.5 * 2 * 4) ** (1/3)
    assert cell["cost_ratio_median"] == 2.0


def test_fp_sample_deterministic_and_stratified(tmp_path):
    run = _judged_run(tmp_path, {(1, OPUS, "medium"): (0, 6, 1.0), (1, SONNET, "medium"): (0, 2, 1.0),
                                 (2, SONNET, "high"): (0, 4, 1.0)})
    a, b = jg.fp_sample(run, SONNET, 6, 1), jg.fp_sample(run, SONNET, 6, 1)
    assert a == b and jg.fp_sample(run, SONNET, 6, 2) != a
    key = a.split("## Key", 1)[1]
    assert key.count(OPUS) == 3 and key.count(SONNET) == 3  # split evenly across models
    table = a.split("## Key", 1)[0]
    assert table.count("| finding ") == 6 and "jobd-" not in table  # blinded: the arm is only in the key
    every = jg.fp_sample(run, SONNET, 99, 1)
    assert "12 of 12 false positives" in every and every.split("## Key", 1)[1].count("| jobd-") == 12
    lopsided = jg.fp_sample(run, SONNET, 10, 1)  # opus has 6: sonnet's quota of 5 plus the spare
    assert lopsided.split("## Key", 1)[1].count(OPUS) == 5 and lopsided.count("10 of 12") == 1
