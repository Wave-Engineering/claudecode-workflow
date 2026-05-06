// Statusline surface: writes a one-line digest of project health to a
// well-known file (`/tmp/wave-watcher-statusline.txt`) that
// `config/statusline-command.sh` can read on every prompt redraw.
//
// The file is written atomically (tmp + rename) so a half-written file is
// never observed by the statusline reader.

import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import type { AggregatedState } from "../types";

export const STATUSLINE_PATH = join(tmpdir(), "wave-watcher-statusline.txt");

export function statuslineLine(states: AggregatedState[]): string {
	if (states.length === 0) return "wave-watcher: 0 projects";
	let ok = 0,
		blocked = 0,
		unhealthy = 0;
	for (const s of states) {
		if (s.health === "ok") ok++;
		else if (s.health === "blocked") blocked++;
		else if (s.health === "unhealthy") unhealthy++;
	}
	const glyph =
		unhealthy > 0 ? "X" : blocked > 0 ? "!" : ok > 0 ? "V" : "O";
	return `wave-watcher: ${glyph} ok=${ok} blocked=${blocked} unhealthy=${unhealthy} (${states.length} total)`;
}

export async function writeStatusline(
	states: AggregatedState[],
	path: string = STATUSLINE_PATH,
): Promise<void> {
	const dir = dirname(path);
	await mkdir(dir, { recursive: true });
	const tmp = `${path}.tmp.${process.pid}`;
	await writeFile(tmp, statuslineLine(states) + "\n", "utf-8");
	await rename(tmp, path);
}
