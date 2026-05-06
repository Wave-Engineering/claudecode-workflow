// Launcher tests: pidfile read/write, idempotency, pidIsAlive.

import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import {
	existsSync,
	mkdtempSync,
	readFileSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
	clearPidFile,
	pidIsAlive,
	readPidFile,
	writePidFile,
} from "./launcher";

let scratch: string;
let pidPath: string;

beforeEach(() => {
	scratch = mkdtempSync(join(tmpdir(), "ww-launcher-"));
	pidPath = join(scratch, "wave-watcher.pid");
});

afterEach(() => {
	rmSync(scratch, { recursive: true, force: true });
});

describe("pidfile primitives", () => {
	test("readPidFile returns null when file is missing", () => {
		expect(readPidFile(pidPath)).toBeNull();
	});

	test("writePidFile + readPidFile roundtrip", () => {
		writePidFile(12345, pidPath);
		expect(readFileSync(pidPath, "utf-8").trim()).toBe("12345");
		expect(readPidFile(pidPath)).toBe(12345);
	});

	test("readPidFile returns null on corrupt content", () => {
		writeFileSync(pidPath, "not a pid", "utf-8");
		expect(readPidFile(pidPath)).toBeNull();
	});

	test("readPidFile returns null on negative/zero pid", () => {
		writeFileSync(pidPath, "-5", "utf-8");
		expect(readPidFile(pidPath)).toBeNull();
		writeFileSync(pidPath, "0", "utf-8");
		expect(readPidFile(pidPath)).toBeNull();
	});

	test("clearPidFile removes the file silently when present", () => {
		writePidFile(1, pidPath);
		expect(existsSync(pidPath)).toBe(true);
		clearPidFile(pidPath);
		expect(existsSync(pidPath)).toBe(false);
	});

	test("clearPidFile is a no-op when file is missing (no throw)", () => {
		clearPidFile(pidPath);
		expect(existsSync(pidPath)).toBe(false);
	});
});

describe("pidIsAlive", () => {
	test("returns true for our own pid", () => {
		expect(pidIsAlive(process.pid)).toBe(true);
	});

	test("returns false for a definitely-dead pid", () => {
		// 2^31 - 1 is the upper bound of Linux pids by default; this is
		// virtually guaranteed to be unallocated.
		expect(pidIsAlive(2_147_483_646)).toBe(false);
	});
});

describe("idempotency-shape contract", () => {
	test("a stale pidfile pointing to a dead pid is treated as not-running", () => {
		writePidFile(2_147_483_646, pidPath);
		expect(readPidFile(pidPath)).toBe(2_147_483_646);
		expect(pidIsAlive(readPidFile(pidPath)!)).toBe(false);
	});

	test("a live pid in the pidfile is treated as running", () => {
		writePidFile(process.pid, pidPath);
		expect(pidIsAlive(readPidFile(pidPath)!)).toBe(true);
	});
});
