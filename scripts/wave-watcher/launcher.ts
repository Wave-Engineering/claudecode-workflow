#!/usr/bin/env bun
// Launcher / lifecycle manager for wave-watcher.
//
// Subcommands:
//   start   — daemonize (setsid + fork), pid in ~/.local/state/wave-watcher.pid
//   stop    — SIGTERM, escalate SIGKILL after 5s
//   status  — print state, port, projects, last poll
//   run     — run in foreground (used by daemonized child + systemd unit)
//
// Idempotency: `start` checks the pidfile + signal-0 liveness; if the daemon
// is already running it prints status and exits 0.

import { spawn } from "node:child_process";
import {
	existsSync,
	mkdirSync,
	readFileSync,
	unlinkSync,
	writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Aggregator } from "./aggregator";
import { loadConfig } from "./config";
import { createServer } from "./server";
import { makeDiscordHandler } from "./surfaces/discord";
import { writeStatusline } from "./surfaces/statusline";
import { makeVoxHandler } from "./surfaces/vox";

export const PID_PATH = join(
	process.env.WAVE_WATCHER_STATE_DIR || join(homedir(), ".local", "state"),
	"wave-watcher.pid",
);

export function pidIsAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch (err) {
		return (err as NodeJS.ErrnoException).code === "EPERM";
	}
}

export function readPidFile(path: string = PID_PATH): number | null {
	if (!existsSync(path)) return null;
	try {
		const raw = readFileSync(path, "utf-8").trim();
		const n = Number.parseInt(raw, 10);
		if (!Number.isFinite(n) || n <= 0) return null;
		return n;
	} catch {
		return null;
	}
}

export function writePidFile(pid: number, path: string = PID_PATH): void {
	mkdirSync(join(path, ".."), { recursive: true });
	writeFileSync(path, String(pid), "utf-8");
}

export function clearPidFile(path: string = PID_PATH): void {
	try {
		unlinkSync(path);
	} catch {
		// ignore
	}
}

export interface StartResult {
	status: "started" | "already-running";
	pid: number;
}

/** Daemonize via setsid + detached spawn. The child re-execs `run`. */
export function daemonize(): StartResult {
	const existing = readPidFile();
	if (existing && pidIsAlive(existing)) {
		return { status: "already-running", pid: existing };
	}
	if (existing) clearPidFile();

	// Re-exec ourselves under `setsid` with the `run` subcommand. This both
	// detaches the child from the controlling terminal and makes it the
	// session leader so closing the parent's terminal doesn't SIGHUP it.
	const exe = process.execPath;
	const script = process.argv[1] ?? "";
	const child = spawn("setsid", [exe, script, "run"], {
		stdio: ["ignore", "ignore", "ignore"],
		detached: true,
		env: process.env,
	});
	child.unref();
	if (typeof child.pid !== "number") {
		throw new Error("daemonize: spawn returned no pid");
	}
	writePidFile(child.pid);
	return { status: "started", pid: child.pid };
}

export async function stopDaemon(timeoutMs = 5000): Promise<{
	stopped: boolean;
	used_kill: boolean;
}> {
	const pid = readPidFile();
	if (!pid) return { stopped: false, used_kill: false };
	if (!pidIsAlive(pid)) {
		clearPidFile();
		return { stopped: true, used_kill: false };
	}
	try {
		process.kill(pid, "SIGTERM");
	} catch {
		// already gone
	}
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		if (!pidIsAlive(pid)) {
			clearPidFile();
			return { stopped: true, used_kill: false };
		}
		await new Promise((r) => setTimeout(r, 100));
	}
	try {
		process.kill(pid, "SIGKILL");
	} catch {
		// ignore
	}
	await new Promise((r) => setTimeout(r, 200));
	clearPidFile();
	return { stopped: true, used_kill: true };
}

export async function runForeground(): Promise<void> {
	const config = await loadConfig();
	const agg = new Aggregator(config);
	const server = createServer(agg, { port: config.port });

	// Wire active surfaces.
	const discord = makeDiscordHandler(config);
	if (discord) agg.on(discord);
	const vox = makeVoxHandler(config);
	if (vox) agg.on(vox);
	if (config.surfaces.includes("statusline")) {
		// Re-emit the statusline file on every successful poll. The file
		// must reflect "last known truth" continuously, not only at
		// transition moments.
		agg.onPoll((states) => void writeStatusline(states));
	}

	agg.start();
	process.stderr.write(
		`wave-watcher: serving on http://${server.hostname}:${server.port} pid=${process.pid}\n`,
	);

	const shutdown = (sig: string) => {
		process.stderr.write(`wave-watcher: ${sig} — shutting down\n`);
		agg.stop();
		server.stop(true);
		clearPidFile();
		process.exit(0);
	};
	process.on("SIGTERM", () => shutdown("SIGTERM"));
	process.on("SIGINT", () => shutdown("SIGINT"));

	// Update pidfile to *our* pid (the daemonized child); when invoked
	// via `run` directly (e.g. systemd), the parent never wrote one.
	writePidFile(process.pid);
}

export interface StatusReport {
	running: boolean;
	pid: number | null;
	port: number;
	projects: number;
	last_poll: number;
}

export async function statusReport(): Promise<StatusReport> {
	const config = await loadConfig();
	const pid = readPidFile();
	const running = pid !== null && pidIsAlive(pid);
	let projects = 0;
	let lastPoll = 0;
	if (running) {
		try {
			const res = await fetch(`http://127.0.0.1:${config.port}/api/projects`);
			if (res.ok) {
				const body = (await res.json()) as { projects: unknown[] };
				projects = body.projects.length;
			}
			const h = await fetch(`http://127.0.0.1:${config.port}/health`);
			if (h.ok) {
				const hb = (await h.json()) as { last_poll_ms?: number };
				lastPoll = hb.last_poll_ms ?? 0;
			}
		} catch {
			// daemon claims to be alive but can't be queried — surface that
			// via running:false in the caller's eyes. We'll keep running:true
			// here because the pid IS alive; the HTTP failure may be transient.
		}
	}
	return {
		running,
		pid: pid ?? null,
		port: config.port,
		projects,
		last_poll: lastPoll,
	};
}

async function main(argv: string[]): Promise<number> {
	const cmd = argv[2] ?? "status";
	switch (cmd) {
		case "start": {
			const r = daemonize();
			if (r.status === "already-running") {
				process.stdout.write(`wave-watcher already running pid=${r.pid}\n`);
				return 0;
			}
			process.stdout.write(`wave-watcher started pid=${r.pid}\n`);
			return 0;
		}
		case "stop": {
			const r = await stopDaemon();
			if (!r.stopped) {
				process.stdout.write("wave-watcher not running\n");
				return 0;
			}
			process.stdout.write(
				`wave-watcher stopped${r.used_kill ? " (SIGKILL)" : ""}\n`,
			);
			return 0;
		}
		case "status": {
			const r = await statusReport();
			process.stdout.write(JSON.stringify(r, null, 2) + "\n");
			return r.running ? 0 : 1;
		}
		case "run": {
			await runForeground();
			// runForeground returns once setup completes, but the process
			// must stay alive — Bun.serve and the polling interval timer
			// hold the loop open, but only as long as someone is awaiting.
			// Park here until a SIGTERM/SIGINT handler calls process.exit.
			await new Promise<never>(() => {
				/* never resolves */
			});
			return 0;
		}
		case "--help":
		case "-h":
		case "help": {
			process.stdout.write(
				"usage: wave-watcher {start|stop|status|run}\n" +
					"  start  — daemonize and write pidfile\n" +
					"  stop   — SIGTERM (escalate SIGKILL after 5s)\n" +
					"  status — print pid/port/projects/last_poll JSON\n" +
					"  run    — run in foreground (used by daemonized child + systemd)\n",
			);
			return 0;
		}
		default:
			process.stderr.write(`unknown subcommand: ${cmd}\n`);
			return 2;
	}
}

if (import.meta.main) {
	main(process.argv).then(
		(code) => process.exit(code),
		(err) => {
			process.stderr.write(`wave-watcher: ${err?.stack ?? err}\n`);
			process.exit(1);
		},
	);
}
