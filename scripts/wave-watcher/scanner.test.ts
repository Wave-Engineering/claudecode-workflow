// Scanner tests: discovery + depth limit + symlink/dot-dir avoidance.
//
// Real fs (mkdtempSync) — these tests exercise the real walker, not a
// mocked one. The wave-watcher scanner is a thin wrapper over readdir/stat;
// stubbing those would test nothing.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	mkdirSync,
	mkdtempSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { scanProjects } from "./scanner";

let scratch: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-scanner-"));
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

function makeProject(root: string, useSdlc = false): string {
	mkdirSync(root, { recursive: true });
	const statusDir = useSdlc
		? join(root, ".sdlc", "waves")
		: join(root, ".claude", "status");
	mkdirSync(statusDir, { recursive: true });
	writeFileSync(
		join(statusDir, "state.json"),
		JSON.stringify({ schema_version: 3, current_wave: "1a", waves: {} }),
	);
	mkdirSync(join(root, ".git"), { recursive: true });
	writeFileSync(
		join(root, ".git", "config"),
		"[remote \"origin\"]\n\turl = https://github.com/foo/bar.git\n",
	);
	return root;
}

describe("scanProjects", () => {
	test("finds a project at the scan root itself (depth 0)", async () => {
		makeProject(scratch);
		const out = await scanProjects([scratch], 4);
		expect(out).toHaveLength(1);
		expect(out[0]?.root).toBe(scratch);
		expect(out[0]?.platform).toBe("github");
	});

	test("finds projects nested 2 deep", async () => {
		makeProject(join(scratch, "owner1", "repo1"));
		makeProject(join(scratch, "owner2", "repo2"));
		const out = await scanProjects([scratch], 4);
		const roots = out.map((m) => m.root).sort();
		expect(roots).toEqual([
			join(scratch, "owner1", "repo1"),
			join(scratch, "owner2", "repo2"),
		]);
	});

	test("respects max depth — projects deeper than limit are not found", async () => {
		// scratch/a/b/c/d/repo — that's 5 levels deep
		const deep = join(scratch, "a", "b", "c", "d", "repo");
		makeProject(deep);
		const found = await scanProjects([scratch], 3);
		expect(found).toHaveLength(0);
		const found4 = await scanProjects([scratch], 4);
		// At depth 4 we still don't reach a 5-deep path; sanity check.
		expect(found4).toHaveLength(0);
		const found5 = await scanProjects([scratch], 5);
		expect(found5).toHaveLength(1);
	});

	test("does not descend into a project once found (no .git/modules false-positives)", async () => {
		const proj = join(scratch, "owner", "repo");
		makeProject(proj);
		// Plant a fake nested project (e.g. a submodule's status dir).
		const nested = join(proj, "submodules", "nested");
		makeProject(nested);
		const out = await scanProjects([scratch], 6);
		expect(out.map((m) => m.root)).toEqual([proj]);
	});

	test("skips dot-dirs and node_modules", async () => {
		makeProject(join(scratch, "real"));
		makeProject(join(scratch, ".hidden", "repo"));
		makeProject(join(scratch, "node_modules", "evil"));
		const out = await scanProjects([scratch], 4);
		expect(out.map((m) => m.root)).toEqual([join(scratch, "real")]);
	});

	test("supports both .claude/status and .sdlc/waves layouts", async () => {
		makeProject(join(scratch, "claude-style"), false);
		makeProject(join(scratch, "sdlc-style"), true);
		const out = await scanProjects([scratch], 4);
		expect(out).toHaveLength(2);
	});

	test("detects gitlab platform", async () => {
		const root = join(scratch, "gl");
		makeProject(root);
		writeFileSync(
			join(root, ".git", "config"),
			"[remote \"origin\"]\n\turl = git@gitlab.com:foo/bar.git\n",
		);
		const out = await scanProjects([scratch], 4);
		expect(out[0]?.platform).toBe("gitlab");
	});

	test("returns last_mtime from the actual file", async () => {
		const root = join(scratch, "p");
		makeProject(root);
		const out = await scanProjects([scratch], 4);
		expect(out[0]?.last_mtime).toBeGreaterThan(0);
		expect(typeof out[0]?.last_mtime).toBe("number");
	});

	test("non-existent scan root is silently skipped", async () => {
		const out = await scanProjects(
			[join(scratch, "nope"), scratch],
			4,
		);
		// scratch alone — empty — so 0 projects, but no throw.
		expect(out).toHaveLength(0);
	});
});
