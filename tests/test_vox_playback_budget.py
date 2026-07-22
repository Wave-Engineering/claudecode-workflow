"""
tests/test_vox_playback_budget.py — a caller timeout must bound synth, not playback.

Covers cc-workflow#952. `vox` synthesized the whole wav (body + the appended
". This is <name>." sign-off) and then played it, under ONE caller timeout. Synth
runs ~1x realtime, so a long body ate the timeout budget during synthesis and a
FOREGROUND player was then SIGTERM'd partway through playback — and the sign-off,
being the tail, was the first thing cut. The fix makes playback DETACHED by
default, so the caller's timeout bounds synthesis only.

HOW THIS IS TESTED WITHOUT REAL AUDIO (the assertion-liveness AC)
----------------------------------------------------------------
vox resolves its provider and player from $VOX_PROVIDER / $VOX_PLAYER. We inject:

  - a fake PROVIDER that sleeps `SYNTH_SECS` (simulating ~1x-realtime synthesis)
    then writes a tiny valid WAV, and
  - a fake PLAYER that sleeps `PLAY_SECS` (simulating playback) and, only on
    reaching the end, writes a "DONE" marker file.

Wrap vox in `timeout WRAP`. The marker is the observable that stands in for "the
sign-off was heard": it is written ONLY if the player ran to completion.

  foreground, WRAP < SYNTH+PLAY  -> player SIGTERM'd mid-playback -> NO marker
  detached,   WRAP < SYNTH+PLAY  -> vox returns after synth+fork  -> marker
                                    (player finishes in the background)

A fix not shown to survive the failing case is not known to work, so the
foreground case must genuinely lose the marker.
"""

import os
import stat
import subprocess
import tempfile
import textwrap
import unittest

VOX = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'scripts', 'vox'))


def _make_exec(path, body):
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class VoxBudgetHarness(unittest.TestCase):
    """Builds an injectable fake provider + player around a temp dir."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='vox952-')
        self.marker = os.path.join(self.dir, 'played-to-end')
        self.provider = os.path.join(self.dir, 'provider.sh')
        self.player = os.path.join(self.dir, 'player.sh')

        # Provider: sleep SYNTH_SECS, then write a minimal valid WAV to
        # $VOX_OUTPUT_FILE (44-byte RIFF header, zero samples — enough for the
        # wake-noise python step to open it).
        _make_exec(self.provider, textwrap.dedent(r'''
            #!/usr/bin/env bash
            sleep "${SYNTH_SECS:-0}"
            python3 - "$VOX_OUTPUT_FILE" <<'PY'
            import sys, wave
            with wave.open(sys.argv[1], 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b'')
            PY
        ''').lstrip())

        # Player: last arg is the wav path (ignored). Sleep PLAY_SECS, then —
        # only on reaching the end — touch the marker. A SIGTERM mid-sleep skips
        # the touch, which is exactly "the tail was cut".
        _make_exec(self.player, textwrap.dedent(r'''
            #!/usr/bin/env bash
            sleep "${PLAY_SECS:-0}"
            touch "%s"
        ''' % self.marker).lstrip())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_vox(self, *args, synth, play, wrap):
        env = dict(os.environ)
        env.update({
            'VOX_PROVIDER': self.provider,
            'VOX_PLAYER': self.player,
            'SYNTH_SECS': str(synth),
            'PLAY_SECS': str(play),
            'VOX_NO_SIGNOFF': '0',
            # keep the fake fast + hermetic
            'VOX_NO_LOG': '1',
            # Neutralize the two ambient vars that would invert what we test:
            # VOX_FOREGROUND=1 would make the no-flag "default detached" case run
            # foreground and fail spuriously; VOX_DISABLED=1 would no-op vox
            # before it ever synthesizes or plays. Both are plausible per-session
            # settings, so pin them regardless of the inherited environment.
            'VOX_FOREGROUND': '0',
            'VOX_DISABLED': '0',
        })
        # A dedicated flock path per test avoids cross-test serialization stalls.
        env['VOX_LOCK'] = os.path.join(self.dir, 'lock')
        r = subprocess.run(
            ['timeout', str(wrap), 'bash', VOX, *args, 'a moderately long body of words'],
            capture_output=True, text=True, env=env, timeout=wrap + 20)
        return r

    def wait_for_marker(self, timeout):
        """Poll for the detached player to finish (bounded)."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(self.marker):
                return True
            time.sleep(0.1)
        return os.path.exists(self.marker)


class TestForegroundTruncatesUnderTightTimeout(VoxBudgetHarness):
    def test_foreground_loses_the_tail(self):
        """Characterization of the NEW --fg opt-in: it genuinely blocks, so a
        tight wrap still truncates it. This proves --fg was not accidentally made
        detached — it is NOT the red-first proof of the fix (that is
        test_default_detached_completes_playback below). Against pre-fix vox this
        test also fails, but for an unrelated reason (--fg did not exist → unknown
        option), so it is not evidence about truncation on its own.

        WRAP=2, synth=1, play=3 → foreground reaches the player ~1s in, then the
        wrap kills vox (and the player with it) at 2s, 2s into a 3s playback. The
        marker is never written — the tail was cut.
        """
        r = self.run_vox('--fg', synth=1, play=3, wrap=2)
        self.assertEqual(r.returncode, 124,
                         "expected the wrapping timeout to SIGTERM foreground vox")
        # Give any stray process a moment; the marker must NOT appear.
        self.assertFalse(self.wait_for_marker(1.0),
                         "foreground playback was not truncated by the caller timeout")


class TestDetachedSurvivesTightTimeout(VoxBudgetHarness):
    def test_default_detached_completes_playback(self):
        """The fix: default playback is detached, so the same tight wrap that cut
        foreground lets synth finish, vox return, and the player run to the end.

        Same timings (synth=1, play=3, wrap=2). vox returns ~1s after synth+fork,
        under the 2s wrap; the detached player finishes ~3s later and writes the
        marker.
        """
        r = self.run_vox(synth=1, play=3, wrap=2)
        self.assertEqual(r.returncode, 0,
                         "detached vox should return cleanly within the wrap "
                         "(caller timeout bounds synth, not playback)")
        self.assertTrue(self.wait_for_marker(6.0),
                        "detached playback did not run to completion")

    def test_explicit_bg_flag_also_detaches(self):
        """--bg is retained and behaves as the default detached mode."""
        r = self.run_vox('--bg', synth=1, play=3, wrap=2)
        self.assertEqual(r.returncode, 0)
        self.assertTrue(self.wait_for_marker(6.0))

    def test_synth_exceeding_the_wrap_still_fails(self):
        """Honesty guard: detaching bounds the caller timeout to SYNTH.

        If SYNTH alone exceeds the wrap, vox is still killed — the fix does not
        (and should not) claim to bound synthesis. synth=3, wrap=2 → rc 124.
        """
        r = self.run_vox(synth=3, play=1, wrap=2)
        self.assertEqual(r.returncode, 124,
                         "a synth longer than the wrap must still time out")


class TestDetachedPlaysWithoutTimeoutBinary(VoxBudgetHarness):
    """macOS regression guard — Linux CI cannot see this without simulating it.

    `timeout(1)` is GNU coreutils / BusyBox and is absent on stock macOS. The
    detached path prefixes the player with `timeout -k 5 60`; unguarded, that is
    `command not found` on macOS, swallowed by `|| true`, so the now-DEFAULT
    detached path would play NO audio. Raised by review as critical #1.

    Simulate a no-`timeout` host by symlinking the real PATH into a temp bin dir
    with `timeout`/`gtimeout` removed, then assert default vox still plays.
    """

    def _no_timeout_path(self):
        binroot = os.path.join(self.dir, 'nobin')
        os.makedirs(binroot, exist_ok=True)
        for d in ('/usr/bin', '/bin', '/usr/local/bin'):
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                link = os.path.join(binroot, name)
                if not os.path.exists(link):
                    try:
                        os.symlink(os.path.join(d, name), link)
                    except OSError:
                        pass
        for t in ('timeout', 'gtimeout'):
            p = os.path.join(binroot, t)
            if os.path.lexists(p):
                os.unlink(p)
        return binroot

    def test_default_plays_when_timeout_is_absent(self):
        binroot = self._no_timeout_path()
        # The simulation is only meaningful if `timeout` is genuinely gone.
        probe = subprocess.run(['bash', '-c', 'command -v timeout'],
                               env={'PATH': binroot}, capture_output=True, text=True)
        if probe.returncode == 0:
            self.skipTest("could not hide `timeout` from PATH on this host")

        # Inherit the ambient env (HOME, TMPDIR, …) and override ONLY PATH so the
        # no-`timeout` condition is the single variable — a bare env breaks vox's
        # own HOME-dependent lookups and would fail for the wrong reason.
        env = dict(os.environ)
        env.update({
            'PATH': binroot,
            'VOX_PROVIDER': self.provider, 'VOX_PLAYER': self.player,
            'SYNTH_SECS': '0', 'PLAY_SECS': '0',
            'VOX_NO_LOG': '1', 'VOX_NO_SIGNOFF': '0',
            'VOX_FOREGROUND': '0', 'VOX_DISABLED': '0',
            'VOX_LOCK': os.path.join(self.dir, 'lock-nt'),
        })
        subprocess.run(['bash', VOX, 'a body'], env=env,
                       capture_output=True, text=True, timeout=30)
        self.assertTrue(self.wait_for_marker(6.0),
                        "detached vox played nothing when `timeout` was absent "
                        "(the macOS silence regression)")


if __name__ == '__main__':
    unittest.main()
