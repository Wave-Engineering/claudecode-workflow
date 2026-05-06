// Statusline surface tests.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	mkdtempSync,
	readFileSync,
	rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { statuslineLine, writeStatusline } from "./statusline";
import type { AggregatedState } from "../types";

let scratch: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-sl-"));
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

const mk = (h: AggregatedState["health"]): AggregatedState =>
	({
		root: "/x",
		platform: "github",
		current_wave: null,
		current_action: { action: "idle", label: "idle", detail: "" },
		waves: [],
		issues: [],
		deferrals: [],
		gauges: {},
		last_updated: null,
		last_mtime: 0,
		health: h,
		error: null,
	}) satisfies AggregatedState;

describe("statuslineLine", () => {
	test("0 projects → idle marker", () => {
		expect(statuslineLine([])).toBe("wave-watcher: 0 projects");
	});

	test("ok counts only", () => {
		const line = statuslineLine([mk("ok"), mk("ok")]);
		expect(line).toContain("V");
		expect(line).toContain("ok=2");
		expect(line).toContain("blocked=0");
	});

	test("any unhealthy → X glyph", () => {
		const line = statuslineLine([mk("ok"), mk("unhealthy")]);
		expect(line).toContain("X");
		expect(line).toContain("unhealthy=1");
	});

	test("blocked-without-unhealthy → ! glyph", () => {
		const line = statuslineLine([mk("ok"), mk("blocked")]);
		expect(line).toContain("!");
	});
});

describe("writeStatusline", () => {
	test("writes the line atomically (no .tmp left behind)", async () => {
		const path = join(scratch, "sl.txt");
		await writeStatusline([mk("ok")], path);
		const text = readFileSync(path, "utf-8");
		expect(text).toContain("V");
		// Tmp file should be cleaned up by the rename.
		const list = await Bun.file(`${path}.tmp.${process.pid}`).exists();
		expect(list).toBe(false);
	});
});
