// Aggregator tests: pollOnce diff, transition listeners, hashRoot stable.
//
// Uses real scanner + reader against an on-disk fixture tree to exercise
// the integration end-to-end. Mocks are limited to *not* mocking — we
// just write JSON to a tmpdir and let the real code path read it.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	mkdirSync,
	mkdtempSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Aggregator, diff, hashRoot } from "./aggregator";
import type { AggregatedState, Transition, WaveWatcherConfig } from "./types";

let scratch: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-agg-"));
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

function makeFixture(name: string, state: object) {
	const root = join(scratch, name);
	const dir = join(root, ".claude", "status");
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "state.json"), JSON.stringify(state));
	mkdirSync(join(root, ".git"), { recursive: true });
	writeFileSync(
		join(root, ".git", "config"),
		"[remote \"origin\"]\n\turl = https://github.com/x/y.git\n",
	);
	return root;
}

const cfg = (overrides: Partial<WaveWatcherConfig> = {}): WaveWatcherConfig => ({
	scan_roots: [scratch],
	poll_interval_ms: 50,
	port: 0,
	max_depth: 4,
	surfaces: [],
	...overrides,
});

describe("hashRoot", () => {
	test("is stable and 16 chars", () => {
		const a = hashRoot("/tmp/foo");
		const b = hashRoot("/tmp/foo");
		expect(a).toBe(b);
		expect(a).toHaveLength(16);
		expect(hashRoot("/tmp/bar")).not.toBe(a);
	});
});

describe("diff", () => {
	const base: AggregatedState = {
		root: "/x",
		platform: "github",
		current_wave: "1a",
		current_action: { action: "idle", label: "idle", detail: "" },
		waves: [{ id: "1a", status: "pending", mr_urls: {} }],
		issues: [],
		deferrals: [],
		gauges: {},
		last_updated: null,
		last_mtime: 0,
		health: "ok",
		error: null,
	};

	test("emits action-change on action transition", () => {
		const next = { ...base, current_action: { action: "planning", label: "p", detail: "" } };
		const ts = diff(base, next, "now");
		expect(ts.find((t) => t.kind === "action-change")).toBeDefined();
	});

	test("emits flight-start when entering a flight action", () => {
		const next = { ...base, current_action: { action: "flight-1", label: "f", detail: "" } };
		const ts = diff(base, next, "now");
		expect(ts.find((t) => t.kind === "flight-start")).toBeDefined();
		expect(ts.find((t) => t.kind === "action-change")).toBeDefined();
	});

	test("emits wave-completion when a wave moves to completed", () => {
		const next = {
			...base,
			waves: [{ id: "1a", status: "completed", mr_urls: {} }],
		};
		const ts = diff(base, next, "now");
		const wc = ts.find((t) => t.kind === "wave-completion");
		expect(wc).toBeDefined();
		if (wc?.kind === "wave-completion") expect(wc.wave_id).toBe("1a");
	});

	test("emits health-degrade on ok → blocked", () => {
		const next = { ...base, health: "blocked" as const };
		const ts = diff(base, next, "now");
		const hd = ts.find((t) => t.kind === "health-degrade");
		expect(hd).toBeDefined();
	});

	test("does not emit health-degrade for blocked → blocked (no change)", () => {
		const prev = { ...base, health: "blocked" as const };
		const ts = diff(prev, prev, "now");
		expect(ts.find((t) => t.kind === "health-degrade")).toBeUndefined();
	});
});

describe("Aggregator.pollOnce", () => {
	test("populates state on first poll without emitting transitions", async () => {
		makeFixture("p1", {
			schema_version: 3,
			current_wave: "1a",
			current_action: { action: "idle", label: "idle", detail: "" },
			waves: { "1a": { status: "pending", mr_urls: {} } },
			issues: {},
			deferrals: [],
		});
		const agg = new Aggregator(cfg());
		const events: Transition[] = [];
		agg.on((t) => events.push(t));
		const ts = await agg.pollOnce();
		expect(ts).toEqual([]);
		expect(events).toEqual([]);
		expect(agg.getAll()).toHaveLength(1);
	});

	test("detects wave-completion across two polls", async () => {
		const root = makeFixture("p1", {
			schema_version: 3,
			current_wave: "1a",
			current_action: { action: "idle", label: "idle", detail: "" },
			waves: { "1a": { status: "in_progress", mr_urls: {} } },
			issues: {},
			deferrals: [],
		});
		const agg = new Aggregator(cfg());
		const events: Transition[] = [];
		agg.on((t) => events.push(t));
		await agg.pollOnce();
		// Mutate state.json — wave moves to completed.
		writeFileSync(
			join(root, ".claude", "status", "state.json"),
			JSON.stringify({
				schema_version: 3,
				current_wave: "1a",
				current_action: { action: "idle", label: "idle", detail: "" },
				waves: { "1a": { status: "completed", mr_urls: {} } },
				issues: {},
				deferrals: [],
			}),
		);
		const ts = await agg.pollOnce();
		expect(ts.find((t) => t.kind === "wave-completion")).toBeDefined();
		expect(events.find((t) => t.kind === "wave-completion")).toBeDefined();
	});

	test("detects health-degrade ok → blocked across polls", async () => {
		const root = makeFixture("p1", {
			schema_version: 3,
			current_wave: "1a",
			current_action: { action: "idle", label: "idle", detail: "" },
			waves: { "1a": { status: "pending", mr_urls: {} } },
			issues: {},
			deferrals: [],
		});
		const agg = new Aggregator(cfg());
		await agg.pollOnce(); // ok
		// Inject a pending deferral → blocked.
		writeFileSync(
			join(root, ".claude", "status", "state.json"),
			JSON.stringify({
				schema_version: 3,
				current_wave: "1a",
				current_action: { action: "idle", label: "idle", detail: "" },
				waves: { "1a": { status: "pending", mr_urls: {} } },
				issues: {},
				deferrals: [{ issue: 99, status: "pending" }],
			}),
		);
		const ts = await agg.pollOnce();
		const hd = ts.find((t) => t.kind === "health-degrade");
		expect(hd).toBeDefined();
		if (hd?.kind === "health-degrade") {
			expect(hd.from).toBe("ok");
			expect(hd.to).toBe("blocked");
		}
	});

	test("get(rootHash) returns the project keyed by hashRoot", async () => {
		const root = makeFixture("p1", {
			schema_version: 3,
			current_wave: null,
			waves: {},
			issues: {},
		});
		const agg = new Aggregator(cfg());
		await agg.pollOnce();
		const found = agg.get(hashRoot(root));
		expect(found?.root).toBe(root);
		expect(agg.get("nonsense")).toBeNull();
	});

	test("onPoll fires every poll, even when no transitions", async () => {
		makeFixture("p1", {
			schema_version: 3,
			waves: { "1a": { status: "in_progress", mr_urls: {} } },
		});
		const agg = new Aggregator(cfg());
		const polls: number[] = [];
		agg.onPoll((s) => polls.push(s.length));
		await agg.pollOnce();
		await agg.pollOnce();
		expect(polls).toEqual([1, 1]);
	});

	test("listener exception does not crash the poll loop", async () => {
		makeFixture("p1", {
			schema_version: 3,
			waves: { "1a": { status: "in_progress", mr_urls: {} } },
		});
		const agg = new Aggregator(cfg());
		await agg.pollOnce();
		agg.on(() => {
			throw new Error("boom");
		});
		// Mutate the state to provoke a transition.
		writeFileSync(
			join(scratch, "p1", ".claude", "status", "state.json"),
			JSON.stringify({
				schema_version: 3,
				waves: { "1a": { status: "completed", mr_urls: {} } },
			}),
		);
		// Should not throw.
		const ts = await agg.pollOnce();
		expect(ts.length).toBeGreaterThan(0);
	});
});
