"""scripts/notify-bj.sh: a page goes through `crewchat-send` first, Discord second (#1348).

`crewchat-send` and `vox` are stubs on a sandboxed PATH that record their argv and STDIN.
Discord is a local HTTP server (`NOTIFY_BJ_DISCORD_API`) that records each post and answers
with a chosen status. The script must:
- deliver through crewchat-send when it exits 0, and make no Discord request;
- fall back to Discord when crewchat-send exits non-zero or is not on PATH, saying so;
- exit non-zero only when both paths fail, so a page never goes quiet.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "notify-bj.sh"
_CALL_4_BJ = "1518536836673310800"

_CREWCHAT_SEND_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$@" >"$STUB_DIR/crewchat-send.argv"
cat >"$STUB_DIR/crewchat-send.stdin"
[[ "${STUB_SEND_RC:-0}" == 0 ]] && echo "pppppppppppppppppppppppppp"
exit "${STUB_SEND_RC:-0}"
"""
_VOX_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_DIR/vox.calls"
"""


class FakeDiscord:
    """Records each POST; answers `status`."""

    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []
        self.status = 200
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 (the stdlib's name)
                body = self.rfile.read(int(self.headers["Content-Length"]))
                fake.posts.append(
                    {
                        "path": self.path,
                        "auth": self.headers["Authorization"],
                        "body": json.loads(body),
                    }
                )
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args: Any) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def discord() -> Iterator[FakeDiscord]:
    fake = FakeDiscord()
    yield fake
    fake.close()


@pytest.fixture
def stubs(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "stubs"
    (stub_dir / "bin").mkdir(parents=True)
    _write_exec(stub_dir / "bin" / "crewchat-send", _CREWCHAT_SEND_STUB)
    _write_exec(stub_dir / "bin" / "vox", _VOX_STUB)
    (tmp_path / "token").write_text("test-token\n")
    return stub_dir


def _run(stubs: Path, discord: FakeDiscord, **env: str) -> subprocess.CompletedProcess[str]:
    # A runner's CI mutes the script; a proxy would intercept the local fake.
    drop = {"CI", "DISCORD_BOT_TOKEN", "NOTIFY_BJ_REPO_ROOT"}
    base = {k: v for k, v in os.environ.items() if k not in drop and "proxy" not in k.lower()}
    base.update(
        PATH=f"{stubs / 'bin'}:/usr/bin:/bin",
        STUB_DIR=str(stubs),
        HOME=str(stubs.parent),
        DISCORD_TOKEN_PATH=str(stubs.parent / "token"),
        NOTIFY_BJ_DISCORD_API=discord.api,
        NOTIFY_BJ_DISABLED="0",
    )
    base.update(env)
    page = "⚠️ **Reseed auto-revive FAILED** — pane `%3`: run `/reseed revive` and $(not this)"
    return subprocess.run(
        [str(_SCRIPT), "Hey BJ", page],
        env=base,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_notify_bj_prefers_crewchat_send(stubs: Path, discord: FakeDiscord) -> None:
    result = _run(stubs, discord, NOTIFY_BJ_REPO_ROOT="/work/checkout")
    assert result.returncode == 0, result.stderr
    assert "delivered via crewchat" in result.stderr
    assert discord.posts == []
    argv = (stubs / "crewchat-send.argv").read_text().splitlines()
    assert argv == ["call-4-bj", "--repo-root", "/work/checkout"]
    # The text arrives on STDIN, verbatim: backticks and $( ) never met a shell.
    sent = (stubs / "crewchat-send.stdin").read_text()
    assert sent == (
        "⚠️ **Reseed auto-revive FAILED** — pane `%3`: run `/reseed revive` and $(not this)"
    )
    assert (stubs / "vox.calls").read_text() == "Hey BJ\n"


def test_notify_bj_without_repo_root_lets_crewchat_send_find_it(
    stubs: Path, discord: FakeDiscord
) -> None:
    assert _run(stubs, discord).returncode == 0
    assert (stubs / "crewchat-send.argv").read_text().splitlines() == ["call-4-bj"]


@pytest.mark.parametrize("absent", [False, True], ids=["exits-4", "not-on-path"])
def test_notify_bj_falls_back_to_discord(
    stubs: Path, discord: FakeDiscord, absent: bool
) -> None:
    if absent:
        (stubs / "bin" / "crewchat-send").unlink()
    result = _run(stubs, discord, STUB_SEND_RC="4")
    assert result.returncode == 0, result.stderr
    if absent:
        assert "no crewchat-send on PATH; falling back to Discord" in result.stderr
    else:
        assert "crewchat-send exited 4; falling back to Discord" in result.stderr
    assert "delivered via discord" in result.stderr
    (post,) = discord.posts
    assert post["path"] == f"/channels/{_CALL_4_BJ}/messages"
    assert post["auth"] == "Bot test-token"
    assert post["body"]["content"].startswith("⚠️ **Reseed auto-revive FAILED**")
    assert "test-token" not in result.stderr


def test_notify_bj_fails_loud_when_both_fail(stubs: Path, discord: FakeDiscord) -> None:
    discord.status = 500
    result = _run(stubs, discord, STUB_SEND_RC="5")
    assert result.returncode == 1
    assert "crewchat-send exited 5" in result.stderr
    assert "Discord post failed" in result.stderr
    assert "delivered" not in result.stderr


def test_notify_bj_fails_loud_with_no_token(stubs: Path, discord: FakeDiscord) -> None:
    result = _run(stubs, discord, STUB_SEND_RC="5", DISCORD_TOKEN_PATH=str(stubs / "absent"))
    assert result.returncode == 1
    assert "no Discord token" in result.stderr
    assert discord.posts == []


@pytest.mark.parametrize("mute", [{"CI": "true"}, {"NOTIFY_BJ_DISABLED": "1"}])
def test_notify_bj_muted_sends_nothing(
    stubs: Path, discord: FakeDiscord, mute: dict[str, str]
) -> None:
    assert _run(stubs, discord, **mute).returncode == 0
    assert not (stubs / "crewchat-send.argv").exists()
    assert not (stubs / "vox.calls").exists()
    assert discord.posts == []
