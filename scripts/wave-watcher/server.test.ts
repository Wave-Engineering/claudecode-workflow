// Server tests: /api/projects, /events, /statusline, /health, /api/project/:hash.
//
// Boots a real Bun.serve on an ephemeral port (port: 0) so the route
// behavior — including SSE — is exercised. No mocks of Bun.serve.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	mkdirSync,
	mkdtempSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Aggregator, hashRoot } from "./aggregator";
import { createServer, renderDashboard, statuslineFor, worstHealth } from "./server";
import type { AggregatedState, WaveWatcherConfig } from "./types";

let scratch: string;
let server: ReturnType<typeof createServer> | null = null;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-server-"));
});

afterEach(() => {
	if (server) {
		server.stop(true);
		server = null;
	}
	rmSync(scratch, { recursive: true, force: true });
});

function makeFixture(name: string, state: object) {
	const root = join(scratch, name);
	const dir = join(root, ".claude", "status");
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "state.json"), JSON.stringify(state));
	return root;
}

const cfg: WaveWatcherConfig = {
	scan_roots: [],
	poll_interval_ms: 1000,
	port: 0,
	max_depth: 4,
	surfaces: [],
};

async function bootWithFixture(name = "p1"): Promise<{
	agg: Aggregator;
	root: string;
	url: string;
}> {
	const root = makeFixture(name, {
		schema_version: 3,
		current_wave: "1a",
		current_action: { action: "idle", label: "idle", detail: "" },
		waves: { "1a": { status: "in_progress", mr_urls: {} } },
		issues: {},
		deferrals: [],
	});
	const agg = new Aggregator({ ...cfg, scan_roots: [scratch] });
	await agg.pollOnce();
	server = createServer(agg, { port: 0 });
	const url = `http://${server.hostname}:${server.port}`;
	return { agg, root, url };
}

describe("statuslineFor + worstHealth", () => {
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

	test("empty list → yellow O", () => {
		expect(statuslineFor([])).toContain("O");
	});

	test("all ok → green V", () => {
		const s = statuslineFor([mk("ok"), mk("ok")]);
		expect(s).toContain("V");
		expect(s).toContain("\x1b[32m");
	});

	test("any unhealthy → red X", () => {
		expect(statuslineFor([mk("ok"), mk("unhealthy")])).toContain("X");
		expect(statuslineFor([mk("ok"), mk("blocked")])).toContain("X");
	});

	test("worstHealth ranks unhealthy > blocked > unknown > ok", () => {
		expect(worstHealth([mk("ok"), mk("blocked")])).toBe("blocked");
		expect(worstHealth([mk("blocked"), mk("unhealthy")])).toBe("unhealthy");
		expect(worstHealth([mk("ok"), mk("ok")])).toBe("ok");
	});
});

describe("renderDashboard", () => {
	test("escapes HTML in project root paths", () => {
		const html = renderDashboard([
			{
				root: "/x<script>",
				platform: "github",
				current_wave: null,
				current_action: { action: "idle", label: "idle", detail: "" },
				waves: [],
				issues: [],
				deferrals: [],
				gauges: {},
				last_updated: null,
				last_mtime: Date.now(),
				health: "ok",
				error: null,
			},
		]);
		// User input is escaped; the literal "<script>" from /x<script>
		// must not appear inside the project-root cell.
		expect(html).toContain("&lt;script&gt;");
		expect(html).toContain("/x&lt;script&gt;");
		// And it must not be rendered as a real tag in that context.
		expect(html).not.toContain("/x<script>");
	});

	test("emits empty-state message when no projects", () => {
		const html = renderDashboard([]);
		expect(html).toContain("No active wave-pattern projects");
	});
});

describe("HTTP routes", () => {
	test("/health returns ok + uptime", async () => {
		const { url } = await bootWithFixture();
		const res = await fetch(`${url}/health`);
		expect(res.status).toBe(200);
		const body = (await res.json()) as { ok: boolean; uptime_s: number };
		expect(body.ok).toBe(true);
		expect(body.uptime_s).toBeGreaterThanOrEqual(0);
	});

	test("/api/projects returns aggregated state", async () => {
		const { root, url } = await bootWithFixture("apiproj");
		const res = await fetch(`${url}/api/projects`);
		const body = (await res.json()) as { projects: AggregatedState[] };
		expect(body.projects).toHaveLength(1);
		expect(body.projects[0]?.root).toBe(root);
		expect(body.projects[0]?.waves[0]?.status).toBe("in_progress");
	});

	test("/api/project/:hash returns the matching project", async () => {
		const { root, url } = await bootWithFixture();
		const h = hashRoot(root);
		const res = await fetch(`${url}/api/project/${h}`);
		expect(res.status).toBe(200);
		const body = (await res.json()) as AggregatedState;
		expect(body.root).toBe(root);
	});

	test("/api/project/:hash 404s for unknown hash", async () => {
		const { url } = await bootWithFixture();
		const res = await fetch(`${url}/api/project/deadbeef`);
		expect(res.status).toBe(404);
	});

	test("/statusline returns ANSI-coloured glyph", async () => {
		const { url } = await bootWithFixture();
		const res = await fetch(`${url}/statusline`);
		const text = await res.text();
		expect(text).toMatch(/[VXO]/);
		expect(text).toContain("\x1b[");
	});

	test("/ returns HTML", async () => {
		const { url } = await bootWithFixture();
		const res = await fetch(`${url}/`);
		expect(res.headers.get("content-type")).toContain("text/html");
		const text = await res.text();
		expect(text).toContain("wave-watcher");
	});

	test("/events streams SSE and emits initial snapshot frame", async () => {
		const { url } = await bootWithFixture();
		const ctrl = new AbortController();
		const res = await fetch(`${url}/events`, { signal: ctrl.signal });
		expect(res.headers.get("content-type")).toContain("text/event-stream");
		const reader = res.body!.getReader();
		const dec = new TextDecoder();
		let buf = "";
		// Read until we have at least the "snapshot" event.
		const deadline = Date.now() + 2000;
		while (Date.now() < deadline) {
			const { value, done } = await reader.read();
			if (done) break;
			buf += dec.decode(value);
			if (buf.includes("event: snapshot")) break;
		}
		ctrl.abort();
		expect(buf).toContain("event: snapshot");
		expect(buf).toContain("projects");
	});

	test("unknown path 404s", async () => {
		const { url } = await bootWithFixture();
		const res = await fetch(`${url}/nope`);
		expect(res.status).toBe(404);
	});
});
