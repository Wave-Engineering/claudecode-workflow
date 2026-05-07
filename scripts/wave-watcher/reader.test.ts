// Reader tests: schema_version 3 parse + missing phases-waves.json
// graceful + health derivation.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	mkdirSync,
	mkdtempSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readState } from "./reader";
import type { ProjectMatch } from "./types";

let scratch: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-reader-"));
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

function writeState(content: object, options: { withPhases?: boolean } = {}) {
	const dir = join(scratch, ".claude", "status");
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "state.json"), JSON.stringify(content));
	if (options.withPhases) {
		writeFileSync(
			join(dir, "phases-waves.json"),
			JSON.stringify({ phases: [] }),
		);
	}
	return {
		root: scratch,
		platform: "github" as const,
		last_mtime: Date.now(),
		state_path: join(dir, "state.json"),
		phases_path: options.withPhases ? join(dir, "phases-waves.json") : null,
	} satisfies ProjectMatch;
}

describe("readState", () => {
	test("parses a v3 state.json into AggregatedState", async () => {
		const match = writeState({
			schema_version: 3,
			current_wave: "1a",
			current_action: { action: "planning", label: "Planning", detail: "" },
			waves: {
				"1a": { status: "in_progress", mr_urls: { "owner/repo#1": "https://x" } },
				"1b": { status: "pending", mr_urls: {} },
			},
			issues: {
				"123": { status: "open" },
				"124": { status: "closed" },
			},
			deferrals: [],
			gauges: { quality: 0.9 },
			last_updated: "2026-05-06T18:00:00Z",
		});
		const agg = await readState(match);
		expect(agg.current_wave).toBe("1a");
		expect(agg.current_action.action).toBe("planning");
		expect(agg.waves).toHaveLength(2);
		const wa = agg.waves.find((w) => w.id === "1a");
		expect(wa?.status).toBe("in_progress");
		expect(wa?.mr_urls).toEqual({ "owner/repo#1": "https://x" });
		expect(agg.issues).toHaveLength(2);
		expect(agg.gauges).toEqual({ quality: 0.9 });
		expect(agg.last_updated).toBe("2026-05-06T18:00:00Z");
		expect(agg.health).toBe("ok");
		expect(agg.error).toBeNull();
	});

	test("treats unreadable JSON as unhealthy + error set", async () => {
		const dir = join(scratch, ".claude", "status");
		mkdirSync(dir, { recursive: true });
		writeFileSync(join(dir, "state.json"), "not json {{{");
		const match: ProjectMatch = {
			root: scratch,
			platform: "github",
			last_mtime: Date.now(),
			state_path: join(dir, "state.json"),
			phases_path: null,
		};
		const agg = await readState(match);
		expect(agg.health).toBe("unhealthy");
		expect(agg.error).toContain("state.json unreadable");
	});

	test("missing phases-waves.json does not block parsing of state.json", async () => {
		const match = writeState(
			{
				schema_version: 3,
				current_wave: "1a",
				waves: { "1a": { status: "completed", mr_urls: {} } },
				issues: {},
				deferrals: [],
			},
			{ withPhases: false },
		);
		expect(match.phases_path).toBeNull();
		const agg = await readState(match);
		expect(agg.error).toBeNull();
		expect(agg.waves[0]?.status).toBe("completed");
	});

	test("health: pending deferrals → blocked", async () => {
		const match = writeState({
			schema_version: 3,
			current_wave: "1a",
			waves: {},
			issues: {},
			deferrals: [{ issue: 99, status: "pending" }],
		});
		const agg = await readState(match);
		expect(agg.health).toBe("blocked");
	});

	test("health: failed wave → blocked", async () => {
		const match = writeState({
			schema_version: 3,
			current_wave: "1a",
			waves: { "1a": { status: "failed", mr_urls: {} } },
			issues: {},
			deferrals: [],
		});
		const agg = await readState(match);
		expect(agg.health).toBe("blocked");
	});

	test("health: schema_version > 3 → unhealthy", async () => {
		const match = writeState({
			schema_version: 99,
			current_wave: "1a",
			waves: {},
			issues: {},
			deferrals: [],
		});
		const agg = await readState(match);
		expect(agg.health).toBe("unhealthy");
	});

	test("missing optional fields default cleanly", async () => {
		const match = writeState({ schema_version: 3 });
		const agg = await readState(match);
		expect(agg.waves).toEqual([]);
		expect(agg.issues).toEqual([]);
		expect(agg.deferrals).toEqual([]);
		expect(agg.gauges).toEqual({});
		expect(agg.current_action.action).toBe("idle");
	});
});
