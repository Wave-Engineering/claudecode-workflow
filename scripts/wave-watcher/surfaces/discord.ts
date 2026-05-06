// Discord surface: posts a message to a webhook URL when a project becomes
// unhealthy or blocked. Opt-in via `surfaces: ["discord"]` in config and
// `discord_webhook` URL.
//
// We deliberately keep this dumb and dependency-free (POST to a webhook URL
// the user supplies). Failures are logged-and-swallowed — a busted webhook
// must never take down the daemon.

import type { Transition, WaveWatcherConfig } from "../types";

export interface DiscordPoster {
	post(payload: { content: string }): Promise<boolean>;
}

export class WebhookDiscordPoster implements DiscordPoster {
	constructor(private url: string) {}
	async post(payload: { content: string }): Promise<boolean> {
		try {
			const res = await fetch(this.url, {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(payload),
			});
			if (!res.ok) {
				process.stderr.write(
					`wave-watcher: discord post failed ${res.status} ${res.statusText}\n`,
				);
				return false;
			}
			return true;
		} catch (err) {
			process.stderr.write(
				`wave-watcher: discord post threw: ${(err as Error).message}\n`,
			);
			return false;
		}
	}
}

export function shouldNotifyDiscord(t: Transition): boolean {
	if (t.kind === "health-degrade") {
		return t.to === "blocked" || t.to === "unhealthy";
	}
	return false;
}

export function formatDiscordMessage(t: Transition): string {
	if (t.kind === "health-degrade") {
		return `:warning: \`${t.project}\` health: ${t.from} → **${t.to}** at ${t.at}`;
	}
	if (t.kind === "wave-completion") {
		return `:white_check_mark: \`${t.project}\` wave **${t.wave_id}** completed at ${t.at}`;
	}
	if (t.kind === "flight-start") {
		return `:airplane: \`${t.project}\` flight start (wave ${t.wave_id}) at ${t.at}`;
	}
	return `:bell: \`${t.project}\` action ${t.from} → ${t.to} at ${t.at}`;
}

export function makeDiscordHandler(
	config: WaveWatcherConfig,
	poster?: DiscordPoster,
): ((t: Transition) => void) | null {
	if (!config.surfaces.includes("discord")) return null;
	if (!config.discord_webhook && !poster) {
		process.stderr.write(
			"wave-watcher: discord surface enabled but no discord_webhook configured\n",
		);
		return null;
	}
	const sender =
		poster ??
		(config.discord_webhook
			? new WebhookDiscordPoster(config.discord_webhook)
			: null);
	if (!sender) return null;
	return (t: Transition) => {
		if (!shouldNotifyDiscord(t)) return;
		void sender.post({ content: formatDiscordMessage(t) });
	};
}
