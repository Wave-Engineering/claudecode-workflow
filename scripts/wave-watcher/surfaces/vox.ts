// Vox surface: speaks an announcement on wave completion via the project's
// existing `vox` CLI (or a configured equivalent). Opt-in via
// `surfaces: ["vox"]`.
//
// We never block on the vox subprocess — fire-and-forget with a logged-and-
// swallowed failure is the right shape for an active surface.

import { spawn } from "node:child_process";
import type { Transition, WaveWatcherConfig } from "../types";

export type SpawnFn = (cmd: string, args: string[]) => void;

export function defaultSpawn(cmd: string, args: string[]): void {
	try {
		const p = spawn(cmd, args, { stdio: "ignore", detached: true });
		p.on("error", (err) => {
			process.stderr.write(
				`wave-watcher: vox spawn failed: ${err.message}\n`,
			);
		});
		p.unref();
	} catch (err) {
		process.stderr.write(
			`wave-watcher: vox spawn threw: ${(err as Error).message}\n`,
		);
	}
}

export function shouldAnnounceVox(t: Transition): boolean {
	return t.kind === "wave-completion";
}

export function makeVoxHandler(
	config: WaveWatcherConfig,
	spawnFn: SpawnFn = defaultSpawn,
): ((t: Transition) => void) | null {
	if (!config.surfaces.includes("vox")) return null;
	const cmd = config.vox_command || "vox";
	return (t: Transition) => {
		if (!shouldAnnounceVox(t)) return;
		if (t.kind === "wave-completion") {
			spawnFn(cmd, [`Wave ${t.wave_id} complete`]);
		}
	};
}
