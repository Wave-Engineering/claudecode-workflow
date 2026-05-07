// Vox surface tests: announces on wave-completion only.

import { describe, expect, test } from "bun:test";
import { makeVoxHandler, shouldAnnounceVox } from "./vox";
import type { Transition, WaveWatcherConfig } from "../types";

const cfg = (overrides: Partial<WaveWatcherConfig> = {}): WaveWatcherConfig => ({
	scan_roots: [],
	poll_interval_ms: 1000,
	port: 7777,
	max_depth: 4,
	surfaces: ["vox"],
	vox_command: "echo",
	...overrides,
});

describe("shouldAnnounceVox", () => {
	test("yes only for wave-completion", () => {
		expect(
			shouldAnnounceVox({
				kind: "wave-completion",
				project: "/x",
				wave_id: "1a",
				at: "now",
			}),
		).toBe(true);
		expect(
			shouldAnnounceVox({
				kind: "health-degrade",
				project: "/x",
				from: "ok",
				to: "blocked",
				at: "now",
			}),
		).toBe(false);
	});
});

describe("makeVoxHandler", () => {
	test("returns null when surface not enabled", () => {
		expect(makeVoxHandler(cfg({ surfaces: [] }))).toBeNull();
	});

	test("invokes spawn on wave-completion", () => {
		const calls: { cmd: string; args: string[] }[] = [];
		const h = makeVoxHandler(cfg(), (cmd, args) => {
			calls.push({ cmd, args });
		});
		const t: Transition = {
			kind: "wave-completion",
			project: "/x",
			wave_id: "1a",
			at: "now",
		};
		h!(t);
		expect(calls).toHaveLength(1);
		expect(calls[0]?.cmd).toBe("echo");
		expect(calls[0]?.args[0]).toContain("1a");
	});

	test("does not invoke spawn for non-completion transitions", () => {
		const calls: unknown[] = [];
		const h = makeVoxHandler(cfg(), () => {
			calls.push(1);
		});
		h!({
			kind: "action-change",
			project: "/x",
			from: "idle",
			to: "planning",
			at: "now",
		});
		expect(calls).toHaveLength(0);
	});
});
