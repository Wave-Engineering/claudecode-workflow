// Discord surface tests: posts on unhealthy/blocked transitions, no-ops on
// other kinds, swallows post failures.

import { describe, expect, test } from "bun:test";
import {
	formatDiscordMessage,
	makeDiscordHandler,
	shouldNotifyDiscord,
} from "./discord";
import type { DiscordPoster } from "./discord";
import type { Transition, WaveWatcherConfig } from "../types";

const cfg = (overrides: Partial<WaveWatcherConfig> = {}): WaveWatcherConfig => ({
	scan_roots: [],
	poll_interval_ms: 1000,
	port: 7777,
	max_depth: 4,
	surfaces: ["discord"],
	discord_webhook: "https://example.invalid/webhook",
	...overrides,
});

class CapturePoster implements DiscordPoster {
	posts: { content: string }[] = [];
	failNext = false;
	async post(payload: { content: string }) {
		if (this.failNext) {
			this.failNext = false;
			return false;
		}
		this.posts.push(payload);
		return true;
	}
}

describe("shouldNotifyDiscord", () => {
	test("yes for health-degrade → blocked", () => {
		expect(
			shouldNotifyDiscord({
				kind: "health-degrade",
				project: "/x",
				from: "ok",
				to: "blocked",
				at: "now",
			}),
		).toBe(true);
	});

	test("yes for health-degrade → unhealthy", () => {
		expect(
			shouldNotifyDiscord({
				kind: "health-degrade",
				project: "/x",
				from: "ok",
				to: "unhealthy",
				at: "now",
			}),
		).toBe(true);
	});

	test("no for action-change", () => {
		expect(
			shouldNotifyDiscord({
				kind: "action-change",
				project: "/x",
				from: "idle",
				to: "planning",
				at: "now",
			}),
		).toBe(false);
	});

	test("no for wave-completion", () => {
		expect(
			shouldNotifyDiscord({
				kind: "wave-completion",
				project: "/x",
				wave_id: "1a",
				at: "now",
			}),
		).toBe(false);
	});
});

describe("formatDiscordMessage", () => {
	test("includes project, transition, and timestamp", () => {
		const msg = formatDiscordMessage({
			kind: "health-degrade",
			project: "/repo",
			from: "ok",
			to: "blocked",
			at: "2026-05-06T18:00:00Z",
		});
		expect(msg).toContain("/repo");
		expect(msg).toContain("blocked");
		expect(msg).toContain("2026-05-06T18:00:00Z");
	});
});

describe("makeDiscordHandler", () => {
	test("returns null when surface not enabled", () => {
		expect(makeDiscordHandler(cfg({ surfaces: [] }))).toBeNull();
	});

	test("returns null when webhook missing and no poster", () => {
		expect(
			makeDiscordHandler({
				...cfg(),
				discord_webhook: undefined,
			}),
		).toBeNull();
	});

	test("posts on health-degrade to blocked", async () => {
		const poster = new CapturePoster();
		const h = makeDiscordHandler(cfg(), poster);
		expect(h).not.toBeNull();
		const t: Transition = {
			kind: "health-degrade",
			project: "/x",
			from: "ok",
			to: "blocked",
			at: "now",
		};
		h!(t);
		// post() is async — yield once to let the floating promise resolve.
		await Promise.resolve();
		await Promise.resolve();
		expect(poster.posts).toHaveLength(1);
		expect(poster.posts[0]?.content).toContain("blocked");
	});

	test("does not post on wave-completion", async () => {
		const poster = new CapturePoster();
		const h = makeDiscordHandler(cfg(), poster);
		h!({
			kind: "wave-completion",
			project: "/x",
			wave_id: "1a",
			at: "now",
		});
		await Promise.resolve();
		expect(poster.posts).toHaveLength(0);
	});

	test("post failure is swallowed (handler does not throw)", () => {
		const poster = new CapturePoster();
		poster.failNext = true;
		const h = makeDiscordHandler(cfg(), poster);
		expect(() =>
			h!({
				kind: "health-degrade",
				project: "/x",
				from: "ok",
				to: "unhealthy",
				at: "now",
			}),
		).not.toThrow();
	});
});
