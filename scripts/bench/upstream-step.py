#!/usr/bin/env python3
"""upstream-step.py — run one of upstream's judge steps for jobd-golden.py, fail-closed (#1406).

Usage:
    upstream-step.py <module> <workers> <call_timeout_s> [step args...]

Upstream runs unmodified but for two things, both set here before the step's main() runs.

Deadlines. Each step sends BATCH_SIZE calls at once, and the shim serves only <workers> of them,
so a call can wait ceil(BATCH_SIZE / workers) - 1 rounds before its own. Both client-side
deadlines are set to that worst case plus the call itself: upstream's LLM_CALL_TIMEOUT, where the
step has one, and the openai SDK's own (600 s by default). The judge's cap on a whole review is
switched off, since each call in it is bounded. The SDK's retries are switched off. A
request the SDK drops stays queued in the shim, which cannot see the hang-up, so a retry would
queue behind its own orphan. Upstream's own loops already retry three times.

Failures. Upstream turns a failed call into an answer and exits 0: an extract with no candidates,
a dedup of all singletons, a judge match counted in `errors`. This counts them and exits 3, so
`jobd-golden.py judge` stops at the step that failed. A rerun redoes what failed:
  - extract saves nothing for a failed review, so a rerun retries it;
  - the judge's resume counts an evaluation with errors as not done, so a rerun retries it;
  - dedup saves its fallback, and a rerun skips every arm it has, so on any failure its whole
    output is removed (one call per arm, a few minutes to redo).
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import math
import sys
from typing import Any, Callable

FAILED = 3


def deadline(batch_size: int, workers: int, call_timeout: int) -> int:
    """The worst case for one call: every round of the batch ahead of it, then its own."""
    return math.ceil(batch_size / workers) * call_timeout


def _errored(result: Any) -> bool:
    return isinstance(result, dict) and bool(result.get("error"))


# The per-call method of each step, and how its result says the call failed.
CALLS: tuple[tuple[str, str, Callable[[Any], bool]], ...] = (
    ("CandidateExtractor", "call_llm", _errored),
    ("DedupLLM", "dedup_candidates", lambda result: result is None),
    ("LLMJudge", "call_llm", _errored),
)


def count_failures(m: Any) -> list[str]:
    """Wrap the step's per-call methods, so each failed call is recorded in the returned list."""
    failures: list[str] = []
    for cls_name, name, failed in CALLS:
        cls = getattr(m, cls_name, None)
        if cls is None:
            continue
        orig = getattr(cls, name)

        @functools.wraps(orig)
        async def wrapped(self: Any, *args: Any, _orig: Any = orig, _failed: Any = failed,
                          **kwargs: Any) -> Any:
            try:
                result = await _orig(self, *args, **kwargs)
            except Exception as e:  # upstream's gather turns this into a fallback, so count it
                failures.append(repr(e))
                raise
            if _failed(result):
                failures.append(str(result)[:200])
            return result

        setattr(cls, name, wrapped)
    return failures


def main(argv: list[str]) -> int:
    step, workers, call_timeout = argv[1], int(argv[2]), int(argv[3])
    sys.argv = [argv[0], *argv[4:]]  # the step's own argparse sees only its arguments
    m = importlib.import_module(step)
    limit = deadline(m.BATCH_SIZE, workers, call_timeout)
    if hasattr(m, "LLM_CALL_TIMEOUT"):
        m.LLM_CALL_TIMEOUT = limit
    if hasattr(m, "REVIEW_TIMEOUT"):
        # The judge also caps a whole review (1800 s). A review runs its batches one after
        # another, each call with up to 3 attempts, so a review can legitimately outlast the cap
        # at any worker count. Its cancel drops the calls in flight, which the shim still runs,
        # and step 3 skips the review and exits 0. Every call inside is already bounded, so the
        # cap is switched off.
        m.REVIEW_TIMEOUT = None
    # Upstream constructs the client by its module-level name, so this reaches every instance.
    m.AsyncOpenAI = functools.partial(m.AsyncOpenAI, timeout=limit, max_retries=0)
    failures = count_failures(m)
    asyncio.run(m.main())
    if not failures:
        return 0
    if hasattr(m, "DedupLLM"):
        (m.get_model_dir() / "dedup_groups.json").unlink(missing_ok=True)
    print(f"upstream-step: {step}: {len(failures)} call(s) failed, first: {failures[0]}",
          file=sys.stderr)
    return FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv))
