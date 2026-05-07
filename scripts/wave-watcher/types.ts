// Shared types for wave-watcher.
//
// The reader treats schema_version 3 as canonical. Unknown fields are
// preserved in the raw state but ignored at the typed surface.

export type Platform = "github" | "gitlab" | "unknown";

export type Health = "ok" | "blocked" | "unhealthy" | "unknown";

export interface ProjectMatch {
	root: string;
	platform: Platform;
	last_mtime: number; // ms since epoch
	state_path: string;
	phases_path: string | null;
}

export interface WaveStatus {
	id: string;
	status: string;
	mr_urls: Record<string, string>;
}

export interface IssueStatus {
	key: string;
	status: string;
}

export interface CurrentAction {
	action: string;
	label: string;
	detail: string;
}

export interface Deferral {
	issue?: string | number;
	status?: string;
	[k: string]: unknown;
}

export interface Gauges {
	[name: string]: number | string | boolean | null;
}

export interface AggregatedState {
	root: string;
	platform: Platform;
	current_wave: string | null;
	current_action: CurrentAction;
	waves: WaveStatus[];
	issues: IssueStatus[];
	deferrals: Deferral[];
	gauges: Gauges;
	last_updated: string | null;
	last_mtime: number;
	health: Health;
	error: string | null;
}

export interface WaveWatcherConfig {
	scan_roots: string[];
	poll_interval_ms: number;
	port: number;
	max_depth: number;
	surfaces: string[];
	discord_webhook?: string;
	vox_command?: string;
}

export const DEFAULT_CONFIG: WaveWatcherConfig = {
	scan_roots: ["~/sandbox/github", "~/sandbox/gitlab"],
	poll_interval_ms: 5000,
	port: 7777,
	max_depth: 4,
	surfaces: [],
};

export type Transition =
	| {
			kind: "wave-completion";
			project: string;
			wave_id: string;
			at: string;
	  }
	| {
			kind: "flight-start";
			project: string;
			wave_id: string;
			at: string;
	  }
	| {
			kind: "action-change";
			project: string;
			from: string;
			to: string;
			at: string;
	  }
	| {
			kind: "health-degrade";
			project: string;
			from: Health;
			to: Health;
			at: string;
	  };
