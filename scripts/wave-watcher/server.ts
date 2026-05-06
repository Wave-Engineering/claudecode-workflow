// HTTP/SSE server. Bun.serve on localhost:7777 by default.
//
// Routes:
//   GET /              — HTML dashboard
//   GET /events        — Server-Sent Events stream of transitions
//   GET /api/projects  — Aggregated state JSON
//   GET /api/project/:root_hash — Per-project drilldown
//   GET /statusline    — Single-glyph status with ANSI color
//   GET /health        — {ok, uptime_s}

import { Aggregator } from "./aggregator";
import type { AggregatedState, Health, Transition } from "./types";

export interface ServerOptions {
	port: number;
	host?: string;
}

export function createServer(
	agg: Aggregator,
	opts: ServerOptions,
) {
	const sseClients = new Set<WritableStreamDefaultWriter<Uint8Array>>();
	const encoder = new TextEncoder();

	agg.on((t) => {
		const payload = encoder.encode(`data: ${JSON.stringify(t)}\n\n`);
		for (const client of sseClients) {
			void client.write(payload).catch(() => {
				sseClients.delete(client);
			});
		}
	});

	return Bun.serve({
		port: opts.port,
		hostname: opts.host ?? "127.0.0.1",
		async fetch(req) {
			const url = new URL(req.url);
			if (url.pathname === "/health") {
				return Response.json({
					ok: true,
					uptime_s: agg.uptimeSeconds(),
					last_poll_ms: agg.lastPoll(),
				});
			}
			if (url.pathname === "/api/projects") {
				return Response.json({ projects: agg.getAll() });
			}
			if (url.pathname.startsWith("/api/project/")) {
				const id = url.pathname.slice("/api/project/".length);
				const state = agg.get(id);
				if (!state) {
					return Response.json({ error: "not found" }, { status: 404 });
				}
				return Response.json(state);
			}
			if (url.pathname === "/statusline") {
				return new Response(statuslineFor(agg.getAll()), {
					headers: { "content-type": "text/plain; charset=utf-8" },
				});
			}
			if (url.pathname === "/events") {
				const { readable, writable } = new TransformStream<
					Uint8Array,
					Uint8Array
				>();
				const writer = writable.getWriter();
				sseClients.add(writer);
				// Initial comment to flush headers immediately.
				void writer.write(encoder.encode(": hello\n\n"));
				// Send a snapshot frame so clients connecting mid-flight
				// don't sit empty until the next transition.
				void writer.write(
					encoder.encode(
						`event: snapshot\ndata: ${JSON.stringify({ projects: agg.getAll() })}\n\n`,
					),
				);
				req.signal.addEventListener("abort", () => {
					sseClients.delete(writer);
					void writer.close().catch(() => {});
				});
				return new Response(readable, {
					headers: {
						"content-type": "text/event-stream",
						"cache-control": "no-cache",
						connection: "keep-alive",
					},
				});
			}
			if (url.pathname === "/" || url.pathname === "/index.html") {
				return new Response(renderDashboard(agg.getAll()), {
					headers: { "content-type": "text/html; charset=utf-8" },
				});
			}
			return new Response("not found", { status: 404 });
		},
	});
}

const COLOR = {
	green: "\x1b[32m",
	yellow: "\x1b[33m",
	red: "\x1b[31m",
	reset: "\x1b[0m",
} as const;

export function statuslineFor(states: AggregatedState[]): string {
	if (states.length === 0) return `${COLOR.yellow}O${COLOR.reset}`;
	const worst = worstHealth(states);
	switch (worst) {
		case "ok":
			return `${COLOR.green}V${COLOR.reset}`;
		case "blocked":
		case "unhealthy":
			return `${COLOR.red}X${COLOR.reset}`;
		case "unknown":
		default:
			return `${COLOR.yellow}O${COLOR.reset}`;
	}
}

export function worstHealth(states: AggregatedState[]): Health {
	let worst: Health = "ok";
	const rank: Record<Health, number> = {
		ok: 0,
		unknown: 1,
		blocked: 2,
		unhealthy: 3,
	};
	for (const s of states) {
		if (rank[s.health] > rank[worst]) worst = s.health;
	}
	return worst;
}

const TRANSITION_KINDS: Transition["kind"][] = [
	"wave-completion",
	"flight-start",
	"action-change",
	"health-degrade",
];

function escapeHtml(s: string): string {
	return s
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");
}

function freshnessBadge(mtime: number): string {
	const ageS = Math.max(0, Math.floor((Date.now() - mtime) / 1000));
	let cls = "fresh";
	if (ageS > 300) cls = "stale";
	else if (ageS > 60) cls = "warm";
	const label = ageS < 60 ? `${ageS}s` : ageS < 3600 ? `${Math.floor(ageS / 60)}m` : `${Math.floor(ageS / 3600)}h`;
	return `<span class="badge ${cls}">${label}</span>`;
}

export function renderDashboard(states: AggregatedState[]): string {
	const rows = states
		.map((s) => {
			const wavesSummary = s.waves
				.slice(0, 5)
				.map(
					(w) =>
						`<code class="wave wave-${escapeHtml(w.status)}">${escapeHtml(w.id)}:${escapeHtml(w.status)}</code>`,
				)
				.join(" ");
			return `
<tr class="health-${escapeHtml(s.health)}" data-root="${escapeHtml(s.root)}">
  <td>${freshnessBadge(s.last_mtime)}</td>
  <td><code>${escapeHtml(s.root)}</code></td>
  <td>${escapeHtml(s.platform)}</td>
  <td>${escapeHtml(s.current_wave ?? "—")}</td>
  <td>${escapeHtml(s.current_action.label || s.current_action.action)}</td>
  <td><span class="health">${escapeHtml(s.health)}</span></td>
  <td>${wavesSummary || "—"}</td>
</tr>`;
		})
		.join("");

	return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>wave-watcher</title>
<meta http-equiv="refresh" content="10">
<style>
  body { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 1em; background: #0e1116; color: #e6edf3; }
  h1 { font-size: 1.1em; margin: 0 0 1em 0; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #21262d; vertical-align: top; }
  th { background: #161b22; cursor: pointer; user-select: none; }
  tr.health-ok { }
  tr.health-blocked { background: rgba(187, 128, 9, 0.10); }
  tr.health-unhealthy { background: rgba(248, 81, 73, 0.12); }
  tr.health-unknown { color: #8b949e; }
  code { font-family: inherit; }
  code.wave { padding: 1px 4px; border: 1px solid #30363d; border-radius: 3px; margin-right: 2px; }
  code.wave-completed { color: #3fb950; border-color: #2ea043; }
  code.wave-pending { color: #8b949e; }
  code.wave-active, code.wave-in_progress { color: #58a6ff; border-color: #1f6feb; }
  code.wave-failed, code.wave-blocked { color: #f85149; border-color: #f85149; }
  .badge { padding: 1px 6px; border-radius: 8px; font-size: 11px; }
  .badge.fresh { background: #1f6feb33; color: #58a6ff; }
  .badge.warm { background: #bb800933; color: #d29922; }
  .badge.stale { background: #f8514933; color: #f85149; }
  .health { text-transform: uppercase; font-weight: 600; font-size: 11px; }
  .empty { color: #8b949e; padding: 2em; text-align: center; }
  #log { margin-top: 1em; max-height: 200px; overflow-y: auto; background: #161b22; padding: 8px; font-size: 11px; }
  #log .entry { padding: 2px 0; }
</style>
</head>
<body>
<h1>wave-watcher — ${states.length} project(s) — kinds: ${TRANSITION_KINDS.join(", ")}</h1>
${
	states.length === 0
		? `<div class="empty">No active wave-pattern projects discovered. Configure scan roots in <code>~/.config/wave-watcher.json</code>.</div>`
		: `<table>
<thead>
  <tr>
    <th>fresh</th><th>root</th><th>platform</th><th>wave</th><th>action</th><th>health</th><th>waves</th>
  </tr>
</thead>
<tbody>${rows}</tbody>
</table>`
}
<div id="log"><strong>events</strong></div>
<script>
(function() {
  var log = document.getElementById('log');
  function append(kind, payload) {
    var div = document.createElement('div');
    div.className = 'entry';
    div.textContent = '[' + new Date().toLocaleTimeString() + '] ' + kind + ' ' + JSON.stringify(payload);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }
  try {
    var es = new EventSource('/events');
    es.onmessage = function(e) {
      try { var t = JSON.parse(e.data); append(t.kind || 'event', t); } catch(_){}
    };
    es.addEventListener('snapshot', function() { /* noop — page refreshes itself */ });
  } catch (e) { /* SSE unsupported — meta refresh covers it */ }
})();
</script>
</body>
</html>`;
}
