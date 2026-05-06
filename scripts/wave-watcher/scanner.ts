// Project discovery: walk scan_roots looking for `.claude/status/state.json`
// or `.sdlc/waves/state.json` markers. Depth-limited; symlinks not followed
// (cycle protection).
//
// Each match → ProjectMatch{root, platform, last_mtime, state_path, phases_path?}.

import { readdir, stat } from "node:fs/promises";
import { join } from "node:path";
import type { Platform, ProjectMatch } from "./types";

const STATE_RELATIVE = [
	[".claude", "status", "state.json"],
	[".sdlc", "waves", "state.json"],
] as const;

const PHASES_RELATIVE = [
	[".claude", "status", "phases-waves.json"],
	[".sdlc", "waves", "phases-waves.json"],
] as const;

async function tryStat(path: string) {
	try {
		return await stat(path);
	} catch {
		return null;
	}
}

async function detectPlatform(repoRoot: string): Promise<Platform> {
	// Cheap inference from .git/config — no shell-out. We don't fail if
	// .git is missing (could be a worktree pointing elsewhere); caller
	// gets `unknown` and the UI can degrade.
	const gitConfig = Bun.file(join(repoRoot, ".git", "config"));
	if (await gitConfig.exists()) {
		try {
			const text = await gitConfig.text();
			if (/gitlab\.com|gitlab\.[a-z0-9.-]+/i.test(text)) return "gitlab";
			if (/github\.com/i.test(text)) return "github";
		} catch {
			// ignore — fall through to unknown
		}
	}
	return "unknown";
}

async function findMarker(
	dir: string,
): Promise<{ statePath: string; phasesPath: string | null; mtime: number } | null> {
	for (let i = 0; i < STATE_RELATIVE.length; i++) {
		const p = STATE_RELATIVE[i];
		if (!p) continue;
		const candidate = join(dir, ...p);
		const s = await tryStat(candidate);
		if (s && s.isFile()) {
			const phasesParts = PHASES_RELATIVE[i];
			const phasesPath = phasesParts ? join(dir, ...phasesParts) : null;
			let phasesExists: string | null = null;
			if (phasesPath) {
				const ps = await tryStat(phasesPath);
				if (ps && ps.isFile()) phasesExists = phasesPath;
			}
			return {
				statePath: candidate,
				phasesPath: phasesExists,
				mtime: s.mtimeMs,
			};
		}
	}
	return null;
}

async function walk(
	dir: string,
	depth: number,
	maxDepth: number,
	out: ProjectMatch[],
	visited: Set<string>,
): Promise<void> {
	if (depth > maxDepth) return;
	if (visited.has(dir)) return;
	visited.add(dir);

	// Check this dir for a marker first.
	const marker = await findMarker(dir);
	if (marker) {
		out.push({
			root: dir,
			platform: await detectPlatform(dir),
			last_mtime: marker.mtime,
			state_path: marker.statePath,
			phases_path: marker.phasesPath,
		});
		// Don't descend into a project once found — projects don't nest
		// for our purposes, and skipping prevents .git/modules false-positives.
		return;
	}

	if (depth === maxDepth) return;

	let entries;
	try {
		entries = await readdir(dir, { withFileTypes: true });
	} catch {
		return;
	}
	for (const entry of entries) {
		if (!entry.isDirectory()) continue;
		// Skip dot-dirs except known safe ones; .git, node_modules, etc. are
		// noise and can contain symlink loops.
		if (entry.name.startsWith(".")) continue;
		if (entry.name === "node_modules") continue;
		await walk(join(dir, entry.name), depth + 1, maxDepth, out, visited);
	}
}

export async function scanProjects(
	roots: string[],
	maxDepth = 4,
): Promise<ProjectMatch[]> {
	const out: ProjectMatch[] = [];
	const visited = new Set<string>();
	for (const root of roots) {
		const s = await tryStat(root);
		if (!s || !s.isDirectory()) continue;
		await walk(root, 0, maxDepth, out, visited);
	}
	return out;
}
