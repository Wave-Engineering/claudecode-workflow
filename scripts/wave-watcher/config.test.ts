// Config loader tests: defaults + override + tilde expansion.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expandHome, loadConfig } from "./config";

let scratch: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-config-"));
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

describe("expandHome", () => {
	test("replaces leading ~ with $HOME", () => {
		const out = expandHome("~/foo/bar");
		expect(out).not.toContain("~");
		expect(out.endsWith("foo/bar")).toBe(true);
	});

	test("leaves absolute paths alone", () => {
		expect(expandHome("/absolute/path")).toBe("/absolute/path");
	});
});

describe("loadConfig", () => {
	test("returns defaults when file is missing", async () => {
		const path = join(scratch, "missing.json");
		const cfg = await loadConfig(path);
		expect(cfg.port).toBe(7777);
		expect(cfg.poll_interval_ms).toBe(5000);
		expect(cfg.max_depth).toBe(4);
		expect(cfg.surfaces).toEqual([]);
		// scan_roots should have ~ expanded.
		for (const r of cfg.scan_roots) {
			expect(r.startsWith("~")).toBe(false);
		}
	});

	test("merges user overrides over defaults", async () => {
		const path = join(scratch, "config.json");
		writeFileSync(
			path,
			JSON.stringify({
				port: 9999,
				poll_interval_ms: 1500,
				surfaces: ["discord"],
			}),
		);
		const cfg = await loadConfig(path);
		expect(cfg.port).toBe(9999);
		expect(cfg.poll_interval_ms).toBe(1500);
		expect(cfg.surfaces).toEqual(["discord"]);
		// max_depth was not overridden, stays at default.
		expect(cfg.max_depth).toBe(4);
	});

	test("malformed JSON falls back to defaults (does not throw)", async () => {
		const path = join(scratch, "bad.json");
		writeFileSync(path, "{this is not json");
		const cfg = await loadConfig(path);
		expect(cfg.port).toBe(7777);
	});

	test("scan_roots from config are also tilde-expanded", async () => {
		const path = join(scratch, "config.json");
		writeFileSync(
			path,
			JSON.stringify({ scan_roots: ["~/projects", "/abs"] }),
		);
		const cfg = await loadConfig(path);
		expect(cfg.scan_roots[0]?.startsWith("~")).toBe(false);
		expect(cfg.scan_roots[1]).toBe("/abs");
	});
});
