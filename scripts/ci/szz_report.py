#!/usr/bin/env python3
"""Aggregate szz-oracle edges into a summary, or emit a calibration worksheet.

Driven by szz-oracle.sh; not a standalone entry point. Reads three files the
caller has already produced (edges, commit universe, fix list) so that the git
plumbing stays in one place and this stays a pure function of its inputs --
which is what makes it testable against a fixture repo.
"""

import collections
import re
import statistics
import subprocess
import sys


def load(edges_path, univ_path, fixes_path):
    edges = [
        line.split("\t")
        for line in open(edges_path).read().splitlines()
        if line.strip()
    ]
    universe = {}
    for line in open(univ_path).read().splitlines():
        if not line.strip():
            continue
        sha, ctime, subject = line.split(" ", 2)
        universe[sha] = (int(ctime), subject)
    fixes = [line for line in open(fixes_path).read().splitlines() if line.strip()]
    return edges, universe, fixes


def top_culprit(edges):
    """Highest-weight culprit per fix. Ties break on sha for determinism."""
    best = {}
    for fix, culprit, weight in edges:
        weight = int(weight)
        current = best.get(fix)
        if current is None or (weight, culprit) > (current[1], current[0]):
            best[fix] = (culprit, weight)
    return best


def lifetimes(best, universe):
    out = []
    for fix, (culprit, _weight) in best.items():
        if fix in universe and culprit in universe:
            out.append((universe[fix][0] - universe[culprit][0]) / 86400.0)
    out.sort()
    return out


def summary(edges, universe, fixes):
    best = top_culprit(edges)
    attributed = set(best)
    n_universe = len(universe)
    all_culprits = {e[1] for e in edges} & set(universe)
    top_culprits = {c for c, _ in best.values()} & set(universe)

    print("SZZ ORACLE — SELF-REPORT")
    print("=" * 62)
    print(f"commit universe (non-merge, in window) : {n_universe}")
    print(f"bug-fix commits (by subject) in window  : {len(fixes)}")
    print()
    print("YIELD — the share of fixes SZZ can attribute at all")
    unattributed = len(fixes) - len(attributed)
    pct = 100.0 * len(attributed) / len(fixes) if fixes else 0.0
    print(f"  attributed   : {len(attributed)}/{len(fixes)} = {pct:.1f}%")
    print(f"  unattributed : {unattributed}  (no blame trail. The fix only")
    print("                 ADDED lines; or its deletions all landed in excluded")
    print("                 files; or its deletions were whole-file removals or")
    print("                 renames, which --diff-filter=M does not consider)")
    print()
    print("BASE RATE — the share of changesets that ever introduced a defect.")
    print("  This is the number that sizes a study: sampling changesets at")
    print("  random draws positives at this rate, and a paired test needs")
    print("  DISCORDANT pairs, which are rarer still.")
    if n_universe:
        print(
            f"  any-blame : {len(all_culprits)}/{n_universe} = "
            f"{100.0 * len(all_culprits) / n_universe:.1f}%"
        )
        print(
            f"  top-1     : {len(top_culprits)}/{n_universe} = "
            f"{100.0 * len(top_culprits) / n_universe:.1f}%"
        )
    print()
    life = lifetimes(best, universe)
    if life:
        within = lambda d: sum(1 for x in life if x <= d)  # noqa: E731
        print("DEFECT LIFETIME (top-1 culprit -> fix), days")
        print(
            f"  n={len(life)}  median={statistics.median(life):.1f}  "
            f"p25={life[len(life) // 4]:.1f}  "
            f"p75={life[3 * len(life) // 4]:.1f}  max={life[-1]:.0f}"
        )
        print(
            f"  <=1d: {within(1)} ({100.0 * within(1) / len(life):.0f}%)   "
            f"<=7d: {within(7)} ({100.0 * within(7) / len(life):.0f}%)"
        )
        print("  Short lifetimes are the cleanest fixtures: the defect was")
        print("  visible in the changeset rather than emerging from later context.")
    print()
    counts = collections.Counter(c for c, _ in best.values())
    repeat = sum(1 for _c, n in counts.items() if n > 1)
    print(f"culprits blamed by more than one distinct fix : {repeat}")
    print()
    print("MOST-BLAMED CHANGESETS (these dominate an unstratified sample)")
    for culprit, n in counts.most_common(8):
        subject = universe.get(culprit, (0, "<outside window>"))[1]
        print(f"  {n}x {culprit[:9]} {subject[:64]}")


# A changeset that bundles a whole wave, or a bulk sync, was never reviewed as a
# unit by any single /precheck — so it cannot serve as a bench fixture no matter
# how correct the blame is. This keys on the wave pattern's DECLARED emission
# convention (`plan(#N): PxWy — … to main`, `promote(…)`), not on an inferred
# property like size: the convention is a contract this repo emits on purpose,
# which is what makes the rule derived rather than maintained.
COMPOUND_RE = re.compile(r"^(plan\(|promote\(|chore\(wave-impl\)|chore: sync)")


def is_compound(subject):
    return bool(COMPOUND_RE.match(subject)) or "cutover" in subject


def fixtures(edges, universe, _fixes):
    """Emit the (fix, culprit) pairs a bench can actually use.

    `edges` is the raw primitive and stays policy-free; this is where policy
    lives, in one place. Every exclusion is COUNTED and printed to stderr --
    a filter that quietly shrinks its output reads as "nothing to exclude",
    which is the same indistinguishable-from-success failure the oracle exists
    to remove.
    """
    best = top_culprit(edges)
    kept = 0
    dropped_compound = 0
    dropped_missing = 0
    for fix in sorted(best):
        culprit, weight = best[fix]
        if culprit not in universe or fix not in universe:
            dropped_missing += 1
            continue
        if is_compound(universe[culprit][1]) or is_compound(universe[fix][1]):
            dropped_compound += 1
            continue
        days = (universe[fix][0] - universe[culprit][0]) / 86400.0
        print(f"{fix}\t{culprit}\t{weight}\t{days:.1f}")
        kept += 1
    print(
        f"szz-oracle fixtures: kept {kept}; dropped {dropped_compound} compound, "
        f"{dropped_missing} outside window",
        file=sys.stderr,
    )


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True
    ).stdout.rstrip("\n")


def worksheet(edges, universe, fixes, limit, stride):
    """Emit adjudication evidence for a deterministic, lifetime-stratified sample.

    Stratified rather than uniform because oracle precision is not expected to
    be constant in defect age -- a long-lived defect gives blame more chances to
    be stolen by an intervening edit. Reporting one blended accuracy would hide
    exactly the gradient a consumer needs in order to choose a sampling frame.
    """
    best = top_culprit(edges)
    rows = []
    for fix, (culprit, weight) in best.items():
        if fix not in universe or culprit not in universe:
            continue
        days = (universe[fix][0] - universe[culprit][0]) / 86400.0
        rows.append((fix, culprit, weight, days))

    fresh = sorted([r for r in rows if r[3] <= 7], key=lambda r: r[0])
    stale = sorted([r for r in rows if r[3] > 7], key=lambda r: r[0])
    per = max(1, (limit or 20) // 2)
    sample = fresh[::stride][:per] + stale[::stride][:per]

    print("# SZZ oracle calibration worksheet")
    print("#")
    print("# Adjudicate each pair: did CULPRIT actually introduce what FIX fixed?")
    print("# Verdicts: YES (introduced it) | NO (wrong commit) | PARTIAL (one of")
    print("# several, or the fix is a redesign rather than a defect repair).")
    print(f"# stratum sizes available: fresh(<=7d)={len(fresh)} stale(>7d)={len(stale)}")
    print()
    for fix, culprit, weight, days in sample:
        stratum = "fresh" if days <= 7 else "stale"
        print(f"## {fix[:9]} -> {culprit[:9]}   [{stratum}] {days:.1f}d "
              f"blamed_lines={weight}")
        print(f"   FIX     {git('log', '-1', '--format=%s', fix)}")
        print(f"   CULPRIT {git('log', '-1', '--format=%s', culprit)}")
        body = git("log", "-1", "--format=%b", fix).strip()
        if body:
            first = [ln for ln in body.splitlines() if ln.strip()][:3]
            for ln in first:
                print(f"   why> {ln[:96]}")
        print("   --- lines the fix DELETED (the alleged defect) ---")
        # Per-file, and only inside hunks -- the same reason szz-oracle.sh parses
        # per-file. Skipping lines that merely START with "---" silently drops a
        # deleted line whose own content begins "-- ", and this block is the
        # evidence a human adjudicates the calibration verdicts from, so a
        # silently-missing line is a verdict formed on incomplete evidence.
        shown = 0
        names = git("show", "--format=", "--name-only", "--diff-filter=M", fix).split()
        for path in names:
            if shown >= 8:
                break
            body = git("show", "--unified=0", "--format=", "--diff-filter=M", fix, "--", path)
            in_hunk = False
            for ln in body.splitlines():
                if ln.startswith("@@"):
                    in_hunk = True
                    continue
                if in_hunk and ln.startswith("-") and shown < 8:
                    print(f"   {ln[:110]}")
                    shown += 1
        print("   VERDICT: ____")
        print()


if __name__ == "__main__":
    mode, edges_path, univ_path, fixes_path, limit, stride = sys.argv[1:7]
    e, u, f = load(edges_path, univ_path, fixes_path)
    if mode == "summary":
        summary(e, u, f)
    elif mode == "fixtures":
        fixtures(e, u, f)
    else:
        worksheet(e, u, f, int(limit), max(1, int(stride)))
