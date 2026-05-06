// Aggregator: in-memory map { project_root: AggregatedState }, polled at
// `poll_interval_ms`. Detects transitions (wave-completion / flight-start /
// action-change / health-degrade) by diffing successive snapshots.
//
// Single-instance per process; the launcher owns the lifecycle.

import { scanProjects } from "./scanner";
import { readState } from "./reader";
import type {
	AggregatedState,
	Health,
	Transition,
	WaveWatcherConfig,
} from "./types";

export type TransitionListener = (t: Transition) => void;
export type PollListener = (states: AggregatedState[]) => void;

export class Aggregator {
	private state = new Map<string, AggregatedState>();
	private listeners = new Set<TransitionListener>();
	private pollListeners = new Set<PollListener>();
	private timer: ReturnType<typeof setInterval> | null = null;
	private startedAt = Date.now();
	private lastPollAt = 0;

	constructor(private config: WaveWatcherConfig) {}

	on(listener: TransitionListener): () => void {
		this.listeners.add(listener);
		return () => this.listeners.delete(listener);
	}

	onPoll(listener: PollListener): () => void {
		this.pollListeners.add(listener);
		return () => this.pollListeners.delete(listener);
	}

	getAll(): AggregatedState[] {
		return [...this.state.values()].sort(
			(a, b) => b.last_mtime - a.last_mtime,
		);
	}

	get(rootHash: string): AggregatedState | null {
		for (const s of this.state.values()) {
			if (hashRoot(s.root) === rootHash) return s;
		}
		return null;
	}

	uptimeSeconds(): number {
		return Math.floor((Date.now() - this.startedAt) / 1000);
	}

	lastPoll(): number {
		return this.lastPollAt;
	}

	/** Run one poll pass. Public so tests can drive it deterministically. */
	async pollOnce(): Promise<Transition[]> {
		const matches = await scanProjects(
			this.config.scan_roots,
			this.config.max_depth,
		);
		const next = new Map<string, AggregatedState>();
		const transitions: Transition[] = [];
		const now = new Date().toISOString();

		for (const m of matches) {
			const agg = await readState(m);
			next.set(m.root, agg);
			const prev = this.state.get(m.root);
			if (prev) {
				transitions.push(...diff(prev, agg, now));
			}
		}

		// Handle disappearance: a project that was being tracked is gone.
		// We don't emit a transition for it, just drop it from state.

		this.state = next;
		this.lastPollAt = Date.now();
		for (const t of transitions) {
			for (const l of this.listeners) {
				try {
					l(t);
				} catch (err) {
					process.stderr.write(
						`wave-watcher: transition listener threw: ${(err as Error).message}\n`,
					);
				}
			}
		}
		const snapshot = this.getAll();
		for (const l of this.pollListeners) {
			try {
				l(snapshot);
			} catch (err) {
				process.stderr.write(
					`wave-watcher: poll listener threw: ${(err as Error).message}\n`,
				);
			}
		}
		return transitions;
	}

	start(): void {
		if (this.timer) return;
		// Kick off an immediate poll so the dashboard isn't empty for
		// poll_interval_ms after start.
		void this.pollOnce();
		this.timer = setInterval(() => {
			void this.pollOnce();
		}, this.config.poll_interval_ms);
	}

	stop(): void {
		if (this.timer) {
			clearInterval(this.timer);
			this.timer = null;
		}
	}
}

export function diff(
	prev: AggregatedState,
	next: AggregatedState,
	at: string,
): Transition[] {
	const out: Transition[] = [];

	if (prev.current_action.action !== next.current_action.action) {
		out.push({
			kind: "action-change",
			project: next.root,
			from: prev.current_action.action,
			to: next.current_action.action,
			at,
		});
		// Treat any move into a *flight* action as flight-start.
		if (
			next.current_action.action.toLowerCase().includes("flight") &&
			!prev.current_action.action.toLowerCase().includes("flight")
		) {
			out.push({
				kind: "flight-start",
				project: next.root,
				wave_id: next.current_wave ?? "",
				at,
			});
		}
	}

	const prevWaves = new Map(prev.waves.map((w) => [w.id, w.status]));
	for (const w of next.waves) {
		const prior = prevWaves.get(w.id);
		if (prior !== "completed" && w.status === "completed") {
			out.push({
				kind: "wave-completion",
				project: next.root,
				wave_id: w.id,
				at,
			});
		}
	}

	if (
		healthRank(next.health) > healthRank(prev.health) &&
		prev.health !== "unknown"
	) {
		out.push({
			kind: "health-degrade",
			project: next.root,
			from: prev.health,
			to: next.health,
			at,
		});
	}

	return out;
}

function healthRank(h: Health): number {
	switch (h) {
		case "ok":
			return 0;
		case "unknown":
			return 1;
		case "blocked":
			return 2;
		case "unhealthy":
			return 3;
	}
}

export function hashRoot(root: string): string {
	// Stable, short, filename-safe. We're not using crypto for security,
	// just to map root paths to URL slugs.
	const hasher = new Bun.CryptoHasher("sha256");
	hasher.update(root);
	return hasher.digest("hex").slice(0, 16);
}
