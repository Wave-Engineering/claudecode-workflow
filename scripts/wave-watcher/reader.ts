// State reader: parses `.claude/status/state.json` (or `.sdlc/waves/state.json`)
// and the optional sibling `phases-waves.json` directly. Does NOT shell out
// to wave_show — wave-watcher must work even when sdlc-server is offline.
//
// Schema reference: cc-workflow `src/wave_status/state.py` — schema_version 3.
// Earlier versions are tolerated (degraded view) but never modified by us.

import { stat } from "node:fs/promises";
import type {
	AggregatedState,
	Deferral,
	Gauges,
	Health,
	IssueStatus,
	Platform,
	ProjectMatch,
	WaveStatus,
} from "./types";

interface RawState {
	schema_version?: number;
	current_wave?: string | null;
	current_action?: { action?: string; label?: string; detail?: string };
	waves?: Record<string, { status?: string; mr_urls?: Record<string, string> }>;
	issues?: Record<string, { status?: string }>;
	deferrals?: Deferral[];
	gauges?: Gauges;
	last_updated?: string;
	wavemachine_active?: boolean;
}

export async function readState(
	match: ProjectMatch,
): Promise<AggregatedState> {
	const base: AggregatedState = {
		root: match.root,
		platform: match.platform,
		current_wave: null,
		current_action: { action: "idle", label: "idle", detail: "" },
		waves: [],
		issues: [],
		deferrals: [],
		gauges: {},
		last_updated: null,
		last_mtime: match.last_mtime,
		health: "unknown",
		error: null,
	};

	let raw: RawState;
	try {
		raw = (await Bun.file(match.state_path).json()) as RawState;
	} catch (err) {
		base.error = `state.json unreadable: ${(err as Error).message}`;
		base.health = "unhealthy";
		return base;
	}

	// Refresh mtime — match.last_mtime is from scan time, but the file
	// could have rotated since. We want the freshness badge to reflect
	// "what we just read", not "what we found".
	try {
		const s = await stat(match.state_path);
		base.last_mtime = s.mtimeMs;
	} catch {
		// keep scan-time mtime
	}

	base.current_wave = raw.current_wave ?? null;
	if (raw.current_action) {
		base.current_action = {
			action: raw.current_action.action ?? "idle",
			label: raw.current_action.label ?? "idle",
			detail: raw.current_action.detail ?? "",
		};
	}

	const waves: WaveStatus[] = [];
	for (const [id, w] of Object.entries(raw.waves ?? {})) {
		waves.push({
			id,
			status: w.status ?? "unknown",
			mr_urls: w.mr_urls ?? {},
		});
	}
	base.waves = waves;

	const issues: IssueStatus[] = [];
	for (const [key, i] of Object.entries(raw.issues ?? {})) {
		issues.push({ key, status: i.status ?? "open" });
	}
	base.issues = issues;

	base.deferrals = Array.isArray(raw.deferrals) ? raw.deferrals : [];
	base.gauges = raw.gauges ?? {};
	base.last_updated = raw.last_updated ?? null;

	base.health = computeHealth(raw, base);

	return base;
}

function computeHealth(raw: RawState, agg: AggregatedState): Health {
	if (raw.schema_version && raw.schema_version > 3) return "unhealthy";
	const pendingDeferrals = agg.deferrals.filter(
		(d) => d.status === "pending",
	).length;
	if (pendingDeferrals > 0) return "blocked";
	const failed = agg.waves.filter(
		(w) => w.status === "failed" || w.status === "blocked",
	).length;
	if (failed > 0) return "blocked";
	const action = agg.current_action.action.toLowerCase();
	if (action.includes("error") || action.includes("fail")) return "unhealthy";
	if (action === "idle" || action === "complete") return "ok";
	return "ok";
}

export function platformFromAggregated(agg: AggregatedState): Platform {
	return agg.platform;
}
