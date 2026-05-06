// Configuration loader.
//
// Reads ~/.config/wave-watcher.json (overridable via WAVE_WATCHER_CONFIG env)
// and merges over DEFAULT_CONFIG. Missing or invalid file → defaults silently
// (the daemon must run on a fresh machine without ceremony).

import { homedir } from "node:os";
import { join } from "node:path";
import { DEFAULT_CONFIG, type WaveWatcherConfig } from "./types";

export function configPath(): string {
	if (process.env.WAVE_WATCHER_CONFIG) {
		return process.env.WAVE_WATCHER_CONFIG;
	}
	return join(homedir(), ".config", "wave-watcher.json");
}

export function expandHome(p: string): string {
	if (p.startsWith("~")) {
		return join(homedir(), p.slice(1).replace(/^[/\\]/, ""));
	}
	return p;
}

export async function loadConfig(
	path: string = configPath(),
): Promise<WaveWatcherConfig> {
	const file = Bun.file(path);
	if (!(await file.exists())) {
		return {
			...DEFAULT_CONFIG,
			scan_roots: DEFAULT_CONFIG.scan_roots.map(expandHome),
		};
	}
	let parsed: Partial<WaveWatcherConfig> = {};
	try {
		parsed = (await file.json()) as Partial<WaveWatcherConfig>;
	} catch (err) {
		// Malformed JSON: fall back to defaults rather than crash. A daemon
		// that won't start because someone left a trailing comma in their
		// config is a worse failure than running with defaults.
		process.stderr.write(
			`wave-watcher: config at ${path} is invalid JSON (${(err as Error).message}); using defaults\n`,
		);
		return {
			...DEFAULT_CONFIG,
			scan_roots: DEFAULT_CONFIG.scan_roots.map(expandHome),
		};
	}
	const merged: WaveWatcherConfig = {
		...DEFAULT_CONFIG,
		...parsed,
	};
	merged.scan_roots = (merged.scan_roots ?? DEFAULT_CONFIG.scan_roots).map(
		expandHome,
	);
	merged.surfaces = merged.surfaces ?? [];
	return merged;
}
