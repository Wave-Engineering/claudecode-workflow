#!/usr/bin/env bun
/**
 * discord-watcher — MCP channel server for Claude Code
 *
 * Watches all text channels on the Oak and Wave Discord server and pushes
 * wake-up notifications into the Claude Code session when new messages arrive.
 *
 * This is a "doorbell, not a mailroom" — it notifies the agent that something
 * new appeared, then the agent uses discord-bot read/send to interact.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { readFileSync, writeFileSync, renameSync, existsSync, unlinkSync } from "node:fs";
import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// --- Build-date query (early exit) ------------------------------------------

const __dirname = dirname(fileURLToPath(import.meta.url));
const BUILDINFO_PATH = join(__dirname, ".buildinfo");

if (process.argv.includes("--builddate")) {
  if (existsSync(BUILDINFO_PATH)) {
    process.stdout.write(readFileSync(BUILDINFO_PATH, "utf-8").trim() + "\n");
  } else {
    process.stdout.write("unknown\n");
  }
  process.exit(0);
}

// --- Configuration -----------------------------------------------------------

// Hardcoded defaults (Oak and Wave — last-resort fallback)
const DEFAULT_GUILD_ID = "1486516321385578576";
const DEFAULT_TOKEN_PATH = "~/secrets/discord-bot-token";

/** Discord configuration schema as stored in ~/.claude/discord.json */
export interface DiscordConfig {
  guild_id?: string;
  token_path?: string;
  channels?: {
    [role: string]: { name: string; id: string };
  };
}

/**
 * Load Discord config using the fallback chain:
 * 1. ~/.claude/discord.json
 * 2. Environment variables
 * 3. Hardcoded defaults
 */
export function loadConfig(): { guildId: string; tokenPath: string } {
  let config: DiscordConfig = {};
  const configPath = join(homedir(), ".claude", "discord.json");

  // 1. Try config file
  if (existsSync(configPath)) {
    try {
      config = JSON.parse(readFileSync(configPath, "utf-8"));
    } catch {
      console.error(`[discord-watcher] Warning: ${configPath} contains invalid JSON, falling back to defaults`);
    }
  }

  // 2. Guild ID: config → env → default
  const guildId =
    config.guild_id ||
    process.env.DISCORD_GUILD_ID ||
    DEFAULT_GUILD_ID;

  // 3. Token path: config → env → default
  const tokenPath =
    config.token_path ||
    process.env.DISCORD_TOKEN_PATH ||
    DEFAULT_TOKEN_PATH;

  return { guildId, tokenPath };
}

const { guildId: GUILD_ID, tokenPath: CONFIGURED_TOKEN_PATH } = loadConfig();

const API_BASE = "https://discord.com/api/v10";
const POLL_INTERVAL_MS = 15_000;
const CHANNEL_REFRESH_MS = 5 * 60_000;
const MESSAGES_PER_PAGE = 50;
const VERBOSE = process.env.DISCORD_WATCHER_VERBOSE === "1";

// --- Kill switch -------------------------------------------------------------

const KILL_FILE = join(homedir(), ".claude", "discord-bot.kill");

/**
 * Check the kill switch file (~/.claude/discord-bot.kill).
 *
 * Returns:
 *   "active"  — kill switch is active, skip the poll cycle
 *   "clear"   — no kill switch or it was auto-lifted, proceed normally
 *
 * Kill file format (compatible with discord-bot shell script):
 *   - Empty file: manual kill, no expiry — always active
 *   - File containing a Unix timestamp: active until that time, auto-lifted when expired
 */
export function checkKillSwitch(): "active" | "clear" {
  if (!existsSync(KILL_FILE)) return "clear";

  const content = readFileSync(KILL_FILE, "utf-8").trim();

  if (!content || !/^\d+$/.test(content)) {
    // Manual kill — no expiry
    console.error("[discord-watcher] Kill switch active (manual). Skipping poll cycle.");
    return "active";
  }

  const expiryTimestamp = parseInt(content, 10);
  const nowSeconds = Math.floor(Date.now() / 1000);

  if (nowSeconds >= expiryTimestamp) {
    // Ban expired — auto-lift
    try {
      unlinkSync(KILL_FILE);
      console.error("[discord-watcher] Kill switch expired, auto-lifted.");
    } catch {
      // File may have been removed by another process
    }
    return "clear";
  }

  const remaining = expiryTimestamp - nowSeconds;
  console.error(
    `[discord-watcher] Kill switch active (expires in ~${remaining}s). Skipping poll cycle.`
  );
  return "active";
}

/**
 * Engage the kill switch with an expiry timestamp.
 * Called when a 429 (rate limit) response is received.
 * Uses atomic write (write to temp + rename) to prevent empty kill files.
 */
export function engageKillSwitch(retryAfterSeconds: number): void {
  const expiry = Math.floor(Date.now() / 1000) + Math.ceil(retryAfterSeconds);
  const tmpFile = `${KILL_FILE}.${process.pid}`;
  try {
    writeFileSync(tmpFile, `${expiry}\n`);
    renameSync(tmpFile, KILL_FILE);
    console.error(
      `[discord-watcher] 429 received. Kill switch engaged for ~${Math.ceil(retryAfterSeconds)}s.`
    );
  } catch (err) {
    console.error(`[discord-watcher] Failed to write kill switch: ${err}`);
    // Clean up temp file if rename failed
    try { unlinkSync(tmpFile); } catch { /* ignore */ }
  }
}

// --- Auth --------------------------------------------------------------------

function loadToken(): string {
  const envToken = process.env.DISCORD_BOT_TOKEN;
  if (envToken) return envToken.trim();

  // Expand ~ in configured token path
  const tokenPath = CONFIGURED_TOKEN_PATH.replace(/^~/, homedir());
  try {
    return readFileSync(tokenPath, "utf-8").replace(/\r?\n/g, "").trim();
  } catch {
    throw new Error(
      `DISCORD_BOT_TOKEN not set and ${tokenPath} not found. Save your bot token there.`
    );
  }
}

// --- Agent identity (self-echo filtering + targeted routing) -----------------

export interface AgentIdentity {
  devName: string | null;
  devTeam: string | null;
}

let cachedIdentity: AgentIdentity = { devName: null, devTeam: null };

export function resolveIdentity(): AgentIdentity {
  try {
    // Match the agent's identity resolution: git rev-parse, fallback to cwd
    let projectRoot: string;
    try {
      projectRoot = execSync("git rev-parse --show-toplevel", {
        encoding: "utf-8",
        stdio: ["pipe", "pipe", "pipe"],
      }).trim();
    } catch {
      projectRoot = process.cwd();
    }
    const dirHash = createHash("md5").update(projectRoot).digest("hex");
    const agentFile = `/tmp/claude-agent-${dirHash}.json`;
    const data = JSON.parse(readFileSync(agentFile, "utf-8"));
    return {
      devName: data.dev_name || null,
      devTeam: data.dev_team || null,
    };
  } catch {
    return { devName: null, devTeam: null };
  }
}

// --- Discord API helpers -----------------------------------------------------

async function apiGet(
  endpoint: string,
  authHeader: string
): Promise<{ ok: true; data: unknown } | { ok: false; status: number; retryAfter?: number }> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    headers: { Authorization: authHeader },
  });
  if (res.status === 429) {
    const retryAfter = parseFloat(res.headers.get("Retry-After") ?? "5");
    engageKillSwitch(retryAfter);
    return { ok: false, status: 429, retryAfter };
  }
  if (!res.ok) {
    return { ok: false, status: res.status };
  }
  return { ok: true, data: await res.json() };
}

interface DiscordChannel {
  id: string;
  name: string;
  type: number;
}

export interface DiscordAttachment {
  id: string;
  filename: string;
  content_type?: string;
  url: string;
  size: number;
}

export interface DiscordMessage {
  id: string;
  author: { id: string; username: string };
  content: string;
  timestamp: string;
  attachments?: DiscordAttachment[];
}

// --- Voice message STT -------------------------------------------------------

/** Strip punctuation from a lowercased token, keeping only routing-key chars. */
export function stripTokenPunctuation(token: string): string {
  return token.replace(/[^a-z0-9@_-]/g, "");
}

const STT_ENDPOINT = process.env.STT_ENDPOINT ?? "http://archer:8300/v1/audio/transcriptions";
const STT_MODEL = process.env.STT_MODEL ?? "deepdml/faster-whisper-large-v3-turbo-ct2";

export async function transcribeAudioAttachments(
  msg: DiscordMessage,
  _authHeader: string
): Promise<string | null> {
  if (!msg.attachments?.length) return null;

  const audioAttachments = msg.attachments.filter(
    (a) => a.content_type?.startsWith("audio/")
  );
  if (audioAttachments.length === 0) return null;

  const transcriptions: string[] = [];

  for (const attachment of audioAttachments) {
    try {
      // Download audio
      const audioResp = await fetch(attachment.url);
      if (!audioResp.ok) {
        console.error(`[discord-watcher] Failed to download audio: HTTP ${audioResp.status}`);
        transcriptions.push(`[voice memo attached — download failed]`);
        continue;
      }
      const audioBuffer = await audioResp.arrayBuffer();

      // Transcribe via Whisper
      const form = new FormData();
      form.append("file", new Blob([audioBuffer]), attachment.filename);
      form.append("model", STT_MODEL);

      const sttResp = await fetch(STT_ENDPOINT, {
        method: "POST",
        body: form,
      });

      if (!sttResp.ok) {
        console.error(`[discord-watcher] STT failed: HTTP ${sttResp.status}`);
        transcriptions.push(`[voice memo attached — transcription failed]`);
        continue;
      }

      const result = (await sttResp.json()) as { text: string };
      if (result.text?.trim()) {
        transcriptions.push(`[voice memo from ${msg.author.username}: "${result.text.trim()}"]`);
      }
    } catch (err) {
      console.error(`[discord-watcher] STT error: ${err}`);
      transcriptions.push(`[voice memo attached — transcription failed]`);
    }
  }

  return transcriptions.length > 0 ? transcriptions.join("\n") : null;
}

// --- State -------------------------------------------------------------------

let watchedChannels: DiscordChannel[] = [];
const lastSeenMessageId = new Map<string, string>();

// --- Channel discovery -------------------------------------------------------

async function fetchTextChannels(authHeader: string): Promise<DiscordChannel[]> {
  const result = await apiGet(`/guilds/${GUILD_ID}/channels`, authHeader);
  if (!result.ok) {
    throw new Error(`Failed to fetch channels: HTTP ${result.status}`);
  }
  return (result.data as DiscordChannel[]).filter((c) => c.type === 0);
}

async function initializeBaselines(authHeader: string): Promise<void> {
  for (const channel of watchedChannels) {
    try {
      const result = await apiGet(
        `/channels/${channel.id}/messages?limit=1`,
        authHeader
      );
      if (result.ok) {
        const messages = result.data as DiscordMessage[];
        if (messages.length > 0) {
          lastSeenMessageId.set(channel.id, messages[0].id);
        }
      }
    } catch {
      // Channel might not be readable — skip it
    }
  }
}

// --- Polling -----------------------------------------------------------------

async function fetchAllNewMessages(
  channelId: string,
  afterId: string,
  authHeader: string
): Promise<DiscordMessage[]> {
  const allMessages: DiscordMessage[] = [];
  let cursor = afterId;

  // Paginate to collect all new messages (prevents silent drops on bursts)
  while (true) {
    const result = await apiGet(
      `/channels/${channelId}/messages?after=${cursor}&limit=${MESSAGES_PER_PAGE}`,
      authHeader
    );

    if (!result.ok) {
      if (result.status === 429 && result.retryAfter) {
        console.error(
          `[discord-watcher] Rate limited, waiting ${result.retryAfter}s`
        );
        await new Promise((r) => setTimeout(r, result.retryAfter! * 1000));
        continue;
      }
      throw new Error(`Discord API HTTP ${result.status}`);
    }

    const messages = result.data as DiscordMessage[];
    if (messages.length === 0) break;

    allMessages.push(...messages);

    // If we got fewer than the limit, we've consumed everything
    if (messages.length < MESSAGES_PER_PAGE) break;

    // Advance cursor to the newest message (messages are newest-first)
    cursor = messages[0].id;
  }

  return allMessages;
}

async function checkForNewMessages(
  server: Server,
  authHeader: string
): Promise<void> {
  // Check kill switch before polling
  if (checkKillSwitch() === "active") return;

  // Refresh identity each cycle (agent may pick name after server starts)
  cachedIdentity = resolveIdentity();

  for (const channel of watchedChannels) {
    try {
      const lastId = lastSeenMessageId.get(channel.id);

      // First poll for this channel — just set baseline
      if (!lastId) {
        const result = await apiGet(
          `/channels/${channel.id}/messages?limit=1`,
          authHeader
        );
        if (result.ok) {
          const msgs = result.data as DiscordMessage[];
          if (msgs.length > 0) {
            lastSeenMessageId.set(channel.id, msgs[0].id);
          }
        } else if (result.status === 429 && result.retryAfter) {
          console.error(
            `[discord-watcher] Rate limited on #${channel.name}, skipping cycle`
          );
        }
        continue;
      }

      const messages = await fetchAllNewMessages(channel.id, lastId, authHeader);
      if (messages.length === 0) continue;

      // Update baseline to the newest message (messages are newest-first)
      lastSeenMessageId.set(channel.id, messages[0].id);

      // Push a wake-up notification for each new message (oldest first)
      for (const msg of messages.reverse()) {
        // Skip messages with no text and no attachments (e.g. bot embeds)
        if (!msg.content.trim() && !msg.attachments?.length) {
          continue;
        }

        // Self-echo filter: skip messages containing our own signature (case-insensitive)
        if (cachedIdentity.devName &&
            msg.content.toLowerCase().includes(`— **${cachedIdentity.devName.toLowerCase()}**`)) {
          continue;
        }

        // Targeted filtering (unless VERBOSE mode bypasses it)
        if (!VERBOSE) {
          // If identity hasn't been set yet, fail open — deliver the message
          if (!cachedIdentity.devName && !cachedIdentity.devTeam) {
            // No identity resolved yet — deliver all messages until agent sets up
          } else {
            const contentLower = msg.content.toLowerCase();
            const tokens = contentLower.split(/\s+/).map(stripTokenPunctuation);
            const isAddressedToAll = tokens.includes("@all");
            const isAddressedToTeam = cachedIdentity.devTeam
              ? tokens.includes(`@${cachedIdentity.devTeam.toLowerCase()}`)
              : false;
            const isAddressedToMe = cachedIdentity.devName
              ? tokens.includes(`@${cachedIdentity.devName.toLowerCase()}`)
              : false;

            if (!isAddressedToAll && !isAddressedToTeam && !isAddressedToMe) {
              continue;
            }
          }
        }

        // Transcribe audio attachments if present
        const audioTranscription = await transcribeAudioAttachments(msg, authHeader);
        const fullContent = audioTranscription
          ? audioTranscription + (msg.content.trim() ? "\n" + msg.content : "")
          : msg.content;

        const preview =
          fullContent.length > 100
            ? fullContent.slice(0, 100) + "…"
            : fullContent;

        console.error(
          `[discord-watcher] New message in #${channel.name} from ${msg.author.username}: ${preview}`
        );

        await server.notification({
          method: "notifications/claude/channel" as any,
          params: {
            content: `New message from ${msg.author.username} in #${channel.name}: ${preview}`,
            meta: {
              channel_name: channel.name,
              channel_id: channel.id,
              author: msg.author.username,
              message_id: msg.id,
            },
          },
        });
      }
    } catch (err) {
      console.error(
        `[discord-watcher] Error polling #${channel.name}: ${err}`
      );
    }
  }

}

// --- Main --------------------------------------------------------------------

const INSTRUCTIONS = [
  'Discord messages arrive as <channel source="discord_watcher" channel_name="..." channel_id="..." author="...">.',
  "Messages are pre-filtered: you only receive messages addressed to @all, @<Dev-Team>, or @<Dev-Name>.",
  "When you see a notification:",
  "1. Run: discord-bot read <channel_id> --limit 10",
  "2. Process the message and respond via discord-bot send if action is needed.",
  '3. Sign every message with: — **<dev-name>** <dev-avatar> (<dev-team>). The watcher filters your own echoes by this signature.',
].join("\n");

async function main(): Promise<void> {
  // Load token early — fail fast before MCP transport setup
  const token = loadToken();
  const authHeader = `Bot ${token}`;

  const server = new Server(
    { name: "discord_watcher", version: "0.1.0" },
    {
      capabilities: {
        experimental: { "claude/channel": {} },
      },
      instructions: INSTRUCTIONS,
    }
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Discover channels — fail hard if this fails
  try {
    watchedChannels = await fetchTextChannels(authHeader);
    await initializeBaselines(authHeader);
  } catch (err) {
    console.error(`[discord-watcher] Initialization failed: ${err}`);
    console.error(
      "[discord-watcher] Cannot watch channels without channel list. Exiting."
    );
    process.exit(1);
  }

  console.error(
    `[discord-watcher] Watching ${watchedChannels.length} channels: ${watchedChannels.map((c) => `#${c.name}`).join(", ")}`
  );

  // Poll for new messages
  const pollTimer = setInterval(
    () => checkForNewMessages(server, authHeader),
    POLL_INTERVAL_MS
  );

  // Periodically refresh the channel list
  const refreshTimer = setInterval(async () => {
    try {
      const fresh = await fetchTextChannels(authHeader);
      for (const ch of fresh) {
        if (!lastSeenMessageId.has(ch.id)) {
          try {
            const result = await apiGet(
              `/channels/${ch.id}/messages?limit=1`,
              authHeader
            );
            if (result.ok) {
              const msgs = result.data as DiscordMessage[];
              if (msgs.length > 0) {
                lastSeenMessageId.set(ch.id, msgs[0].id);
              }
            }
          } catch {
            // skip unreadable
          }
        }
      }
      watchedChannels = fresh;
      console.error(
        `[discord-watcher] Refreshed: ${fresh.length} channels`
      );
    } catch (err) {
      console.error(`[discord-watcher] Channel refresh failed: ${err}`);
    }
  }, CHANNEL_REFRESH_MS);

  // Clean up on exit
  process.on("SIGINT", () => {
    clearInterval(pollTimer);
    clearInterval(refreshTimer);
    process.exit(0);
  });

  process.on("SIGTERM", () => {
    clearInterval(pollTimer);
    clearInterval(refreshTimer);
    process.exit(0);
  });
}

main().catch((err) => {
  console.error(`[discord-watcher] Fatal: ${err}`);
  process.exit(1);
});
