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
    argv = jg.review_argv("claude-opus-5-5", Path("/r/sys.md"), Path("/d"))
    assert argv[:4] == ["claude", "-p", "--model", "claude-opus-5-5"]
    assert argv[argv.index("--tools") + 1] == "Read,Grep,Glob"
    joined = " ".join(argv)
    assert "WebFetch" not in joined and "WebSearch" not in joined and "Bash" not in joined
    assert argv[argv.index("--system-prompt-file") + 1] == "/r/sys.md"
    assert argv[argv.index("--add-dir") + 1] == "/d"
    assert "--bare" not in argv


def test_arms_differ_only_by_model():
    a = jg.review_argv("claude-sonnet-5-5", Path("/r/sys.md"), Path("/d"))
    b = jg.review_argv("claude-opus-5-5", Path("/r/sys.md"), Path("/d"))
    assert [x for x in a if x != "claude-sonnet-5-5"] == [x for x in b if x != "claude-opus-5-5"]


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
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw["env"])
        raise SystemExit("stop after the spawn")

    d = tmp_path / "prs" / "o__r__1"
    (d / "tree").mkdir(parents=True)
    (d / "pr.json").write_text(json.dumps({"diff_lines": 1, "diff_parts": [str(d / "p.diff")]}))
    monkeypatch.setattr(jg, "PRS", tmp_path / "prs")
    monkeypatch.setattr(jg, "agent_system_prompt", lambda: ("body", "/a.md", "0" * 64))
    monkeypatch.setattr(jg.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        jg.review("https://github.com/o/r/pull/1", "claude-opus-5-5", tmp_path / "run")
    assert seen["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert seen["OTEL_RESOURCE_ATTRIBUTES"].startswith("precheck_variant=claude-opus-5-5,")


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


def _review(run: Path, url: str, model: str, text: str) -> None:
    (run / "reviews").mkdir(parents=True, exist_ok=True)
    rec = {"golden_url": url, "tool": jg.tool_name(model), "model": model, "review": text,
           "agent_sha256": "a" * 64, "total_cost_usd": 1.0, "wall_s": 60.0, "usage": {}}
    (run / "reviews" / f"{jg.slug(url)}__{jg.tool_name(model)}.json").write_text(json.dumps(rec))


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


def test_assemble_refuses_a_pr_outside_the_benchmark(tmp_path):
    upstream = tmp_path / "benchmark_data.json"
    upstream.write_text("{}")
    run = tmp_path / "run"
    _review(run, "https://github.com/o/r/pull/9", "claude-opus-5-5", "x")
    with pytest.raises(SystemExit):
        jg.assemble(run, upstream)
