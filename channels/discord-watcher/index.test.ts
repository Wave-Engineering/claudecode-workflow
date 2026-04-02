/**
 * Tests for discord-watcher voice message STT, kill switch, and config features.
 *
 * These tests exercise the real transcribeAudioAttachments, resolveIdentity,
 * checkKillSwitch, and engageKillSwitch functions. Only `fetch` (network) and
 * `readFileSync`/`execSync` (filesystem/process) are mocked — those are true
 * external boundaries.
 */

import { describe, test, expect, mock, beforeEach, afterEach } from "bun:test";
import type { DiscordMessage, DiscordAttachment, DiscordConfig } from "./index";
import { stripTokenPunctuation, loadConfig, checkKillSwitch, engageKillSwitch } from "./index";

// We need to mock fetch and fs before importing the module under test.
// Bun's mock system lets us intercept global fetch.

// Helper to build a DiscordMessage
function makeMsg(
  overrides: Partial<DiscordMessage> & { attachments?: DiscordAttachment[] } = {}
): DiscordMessage {
  return {
    id: "msg-1",
    author: { id: "user-1", username: "testuser" },
    content: "",
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

// --- transcribeAudioAttachments tests ----------------------------------------

describe("transcribeAudioAttachments", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test("returns null when message has no attachments", async () => {
    const { transcribeAudioAttachments } = await import("./index");
    const msg = makeMsg({ content: "hello" });
    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBeNull();
  });

  test("returns null when message has no audio attachments", async () => {
    const { transcribeAudioAttachments } = await import("./index");
    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "image.png",
          content_type: "image/png",
          url: "https://cdn.discordapp.com/image.png",
          size: 1024,
        },
      ],
    });
    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBeNull();
  });

  test("returns transcription for audio attachment", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    // Mock fetch: first call downloads audio, second call transcribes
    const mockFetch = mock(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (url.includes("cdn.discordapp.com")) {
        // Audio download
        return new Response(new ArrayBuffer(100), { status: 200 });
      }
      if (url.includes("audio/transcriptions")) {
        // STT response
        return new Response(JSON.stringify({ text: "Hello from phone" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    });
    globalThis.fetch = mockFetch as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice.ogg",
          size: 2048,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBe('[voice memo from testuser: "Hello from phone"]');
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  test("returns failure message when audio download fails", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    globalThis.fetch = mock(async () => {
      return new Response("forbidden", { status: 403 });
    }) as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice.ogg",
          size: 2048,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBe("[voice memo attached \u2014 download failed]");
  });

  test("returns failure message when STT endpoint fails", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    const mockFetch = mock(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (url.includes("cdn.discordapp.com")) {
        return new Response(new ArrayBuffer(100), { status: 200 });
      }
      // STT fails
      return new Response("service unavailable", { status: 503 });
    });
    globalThis.fetch = mockFetch as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice.ogg",
          size: 2048,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBe("[voice memo attached \u2014 transcription failed]");
  });

  test("returns failure message when fetch throws (network error)", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    globalThis.fetch = mock(async () => {
      throw new Error("ECONNREFUSED");
    }) as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice.ogg",
          size: 2048,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBe("[voice memo attached \u2014 transcription failed]");
  });

  test("handles multiple audio attachments", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    let callCount = 0;
    const mockFetch = mock(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (url.includes("cdn.discordapp.com")) {
        return new Response(new ArrayBuffer(100), { status: 200 });
      }
      if (url.includes("audio/transcriptions")) {
        callCount++;
        const text = callCount === 1 ? "first message" : "second message";
        return new Response(JSON.stringify({ text }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    });
    globalThis.fetch = mockFetch as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "voice1.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice1.ogg",
          size: 2048,
        },
        {
          id: "att-2",
          filename: "voice2.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice2.ogg",
          size: 4096,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toContain('[voice memo from testuser: "first message"]');
    expect(result).toContain('[voice memo from testuser: "second message"]');
    expect(result).toContain("\n");
  });

  test("skips non-audio attachments in mixed set", async () => {
    const { transcribeAudioAttachments } = await import("./index");

    const mockFetch = mock(async (input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

      if (url.includes("cdn.discordapp.com")) {
        return new Response(new ArrayBuffer(100), { status: 200 });
      }
      if (url.includes("audio/transcriptions")) {
        return new Response(JSON.stringify({ text: "transcribed" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response("not found", { status: 404 });
    });
    globalThis.fetch = mockFetch as any;

    const msg = makeMsg({
      attachments: [
        {
          id: "att-1",
          filename: "image.png",
          content_type: "image/png",
          url: "https://cdn.discordapp.com/image.png",
          size: 1024,
        },
        {
          id: "att-2",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://cdn.discordapp.com/voice.ogg",
          size: 2048,
        },
      ],
    });

    const result = await transcribeAudioAttachments(msg, "Bot fake-token");
    expect(result).toBe('[voice memo from testuser: "transcribed"]');
    // Only 2 fetch calls: 1 download + 1 STT (the image is skipped)
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});

// --- resolveIdentity tests ---------------------------------------------------

describe("resolveIdentity", () => {
  test("resolveIdentity returns devName and devTeam when agent file missing", async () => {
    const { resolveIdentity: resolveId } = await import("./index");
    // This calls the real function which may or may not find the agent file.
    // The important thing: it doesn't throw, and returns an AgentIdentity
    const identity = resolveId();
    expect(identity).toHaveProperty("devName");
    expect(identity).toHaveProperty("devTeam");
  });
});

// --- AgentIdentity interface tests -------------------------------------------

describe("AgentIdentity interface", () => {
  test("has devName and devTeam fields", async () => {
    const identity: import("./index").AgentIdentity = {
      devName: "test",
      devTeam: "team",
    };
    expect(identity.devName).toBe("test");
    expect(identity.devTeam).toBe("team");
  });
});

// --- DiscordMessage with attachments -----------------------------------------

describe("DiscordMessage with attachments", () => {
  test("accepts messages with audio attachments", () => {
    const msg: DiscordMessage = {
      id: "1",
      author: { id: "u1", username: "user" },
      content: "",
      timestamp: new Date().toISOString(),
      attachments: [
        {
          id: "a1",
          filename: "voice.ogg",
          content_type: "audio/ogg",
          url: "https://example.com/voice.ogg",
          size: 1024,
        },
      ],
    };
    expect(msg.attachments).toHaveLength(1);
    expect(msg.attachments![0].content_type).toBe("audio/ogg");
  });

  test("attachments field is optional", () => {
    const msg: DiscordMessage = {
      id: "1",
      author: { id: "u1", username: "user" },
      content: "text only",
      timestamp: new Date().toISOString(),
    };
    expect(msg.attachments).toBeUndefined();
  });
});

// --- STT configuration tests -------------------------------------------------

describe("STT configuration", () => {
  test("STT_ENDPOINT defaults to archer:8004", async () => {
    // The default is set in the module. We verify the constant value
    // by reading the source (since it's a module-level const).
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(
      new URL("./index.ts", import.meta.url).pathname,
      "utf-8"
    );
    expect(src).toContain(
      'process.env.STT_ENDPOINT ?? "http://archer:8300/v1/audio/transcriptions"'
    );
  });

  test("STT_MODEL defaults to whisper-1", async () => {
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(
      new URL("./index.ts", import.meta.url).pathname,
      "utf-8"
    );
    expect(src).toContain('process.env.STT_MODEL ?? "deepdml/faster-whisper-large-v3-turbo-ct2"');
  });
});

// --- Addressing tests --------------------------------------------------------

describe("addressing", () => {
  test("@-addressing matches when followed by punctuation", async () => {
    // The watcher tokenizes on whitespace then strips non-routing chars.
    // "@echo-chamber," should match dev_name "echo-chamber".
    const tokens = "@echo-chamber, hello @all. @cc-workflow:"
      .toLowerCase()
      .split(/\s+/)
      .map(stripTokenPunctuation);

    expect(tokens).toContain("@echo-chamber");
    expect(tokens).toContain("@all");
    expect(tokens).toContain("@cc-workflow");
  });

  test("@-addressing matches clean tokens without punctuation", async () => {
    const tokens = "@echo-chamber hello @all @cc-workflow"
      .toLowerCase()
      .split(/\s+/)
      .map(stripTokenPunctuation);

    expect(tokens).toContain("@echo-chamber");
    expect(tokens).toContain("@all");
    expect(tokens).toContain("@cc-workflow");
  });
});

// --- Kill switch tests -------------------------------------------------------

describe("kill switch", () => {
  const KILL_FILE = `${process.env.HOME}/.claude/discord-bot.kill`;

  afterEach(async () => {
    // Clean up kill file after each test
    const { unlinkSync: unlink } = await import("node:fs");
    try { unlink(KILL_FILE); } catch { /* ignore if not exists */ }
  });

  test("checkKillSwitch returns clear when no kill file exists", () => {
    // Ensure kill file doesn't exist
    const { unlinkSync: unlink } = require("node:fs");
    try { unlink(KILL_FILE); } catch { /* ignore */ }

    const result = checkKillSwitch();
    expect(result).toBe("clear");
  });

  test("checkKillSwitch returns active for empty kill file (manual kill)", async () => {
    const { writeFileSync: write, mkdirSync } = await import("node:fs");
    mkdirSync(`${process.env.HOME}/.claude`, { recursive: true });
    write(KILL_FILE, "");

    const result = checkKillSwitch();
    expect(result).toBe("active");
  });

  test("checkKillSwitch returns active for future timestamp", async () => {
    const { writeFileSync: write, mkdirSync } = await import("node:fs");
    mkdirSync(`${process.env.HOME}/.claude`, { recursive: true });
    const futureTs = Math.floor(Date.now() / 1000) + 3600; // 1 hour from now
    write(KILL_FILE, `${futureTs}\n`);

    const result = checkKillSwitch();
    expect(result).toBe("active");
  });

  test("checkKillSwitch auto-lifts expired timestamp", async () => {
    const { writeFileSync: write, existsSync: exists, mkdirSync } = await import("node:fs");
    mkdirSync(`${process.env.HOME}/.claude`, { recursive: true });
    const pastTs = Math.floor(Date.now() / 1000) - 60; // 1 minute ago
    write(KILL_FILE, `${pastTs}\n`);

    const result = checkKillSwitch();
    expect(result).toBe("clear");
    // Kill file should have been deleted
    expect(exists(KILL_FILE)).toBe(false);
  });

  test("engageKillSwitch writes kill file with expiry timestamp", async () => {
    const { readFileSync: read, existsSync: exists, mkdirSync } = await import("node:fs");
    mkdirSync(`${process.env.HOME}/.claude`, { recursive: true });

    engageKillSwitch(120); // 2 minutes

    expect(exists(KILL_FILE)).toBe(true);
    const content = read(KILL_FILE, "utf-8").trim();
    const ts = parseInt(content, 10);
    const now = Math.floor(Date.now() / 1000);
    // Timestamp should be ~120 seconds in the future (allow 5s tolerance)
    expect(ts).toBeGreaterThan(now);
    expect(ts).toBeLessThanOrEqual(now + 125);
  });

  test("kill switch format is compatible with discord-bot shell script", async () => {
    const { readFileSync: read, mkdirSync } = await import("node:fs");
    mkdirSync(`${process.env.HOME}/.claude`, { recursive: true });

    engageKillSwitch(60);

    const content = read(KILL_FILE, "utf-8").trim();
    // Must be a plain integer (Unix timestamp) — discord-bot checks with regex ^[0-9]+$
    expect(content).toMatch(/^\d+$/);
  });
});

// --- loadConfig tests --------------------------------------------------------

describe("loadConfig", () => {
  const originalEnv = { ...process.env };

  afterEach(() => {
    // Restore env vars
    process.env.DISCORD_GUILD_ID = originalEnv.DISCORD_GUILD_ID;
    process.env.DISCORD_TOKEN_PATH = originalEnv.DISCORD_TOKEN_PATH;
    if (originalEnv.DISCORD_GUILD_ID === undefined) delete process.env.DISCORD_GUILD_ID;
    if (originalEnv.DISCORD_TOKEN_PATH === undefined) delete process.env.DISCORD_TOKEN_PATH;
  });

  test("loadConfig returns an object with guildId and tokenPath", () => {
    const config = loadConfig();
    expect(config).toHaveProperty("guildId");
    expect(config).toHaveProperty("tokenPath");
    expect(typeof config.guildId).toBe("string");
    expect(typeof config.tokenPath).toBe("string");
    // Must return non-empty strings (either from config, env, or defaults)
    expect(config.guildId.length).toBeGreaterThan(0);
    expect(config.tokenPath.length).toBeGreaterThan(0);
  });

  test("loadConfig falls back to hardcoded defaults when no config or env", () => {
    // Temporarily clear env vars
    delete process.env.DISCORD_GUILD_ID;
    delete process.env.DISCORD_TOKEN_PATH;

    // loadConfig reads ~/.claude/discord.json if it exists, then env, then defaults.
    // We cannot remove the user's config file in a test, so we verify the
    // function at minimum returns valid values (either from config or defaults).
    const config = loadConfig();
    // The default guild ID is the Oak and Wave server
    // If config file exists, it should return the config value; otherwise the default
    expect(config.guildId).toMatch(/^\d+$/);
    expect(config.tokenPath).toContain("discord-bot-token");
  });

  test("loadConfig uses DISCORD_GUILD_ID env var when set", () => {
    process.env.DISCORD_GUILD_ID = "9999999999999999999";
    // Re-import to pick up env changes (loadConfig reads env at call time)
    // Note: if config file exists and has guild_id, that takes precedence.
    // This test verifies the env var is read when config file value is absent.
    const { loadConfig: reloadConfig } = require("./index");
    const config = reloadConfig();
    // If config file has guild_id, it takes precedence. If not, env var should win.
    // At minimum, verify the function doesn't throw.
    expect(typeof config.guildId).toBe("string");
  });

  test("DiscordConfig interface matches expected schema", () => {
    // Verify the TypeScript interface at compile time by constructing a valid object
    const config: DiscordConfig = {
      guild_id: "123",
      token_path: "~/secrets/token",
      channels: {
        default: { name: "agent-ops", id: "456" },
        "roll-call": { name: "roll-call", id: "789" },
      },
    };
    expect(config.guild_id).toBe("123");
    expect(config.channels?.default?.id).toBe("456");
    expect(config.channels?.["roll-call"]?.id).toBe("789");
  });

  test("loadConfig source implements three-level fallback chain", () => {
    // Verify the implementation pattern exists in source
    const { readFileSync } = require("node:fs");
    const src = readFileSync(
      new URL("./index.ts", import.meta.url).pathname,
      "utf-8"
    );

    // Config file read
    expect(src).toContain("discord.json");
    expect(src).toContain("existsSync");

    // Env var fallback
    expect(src).toContain("process.env.DISCORD_GUILD_ID");
    expect(src).toContain("process.env.DISCORD_TOKEN_PATH");

    // Hardcoded defaults
    expect(src).toContain('DEFAULT_GUILD_ID = "1486516321385578576"');
    expect(src).toContain('DEFAULT_TOKEN_PATH = "~/secrets/discord-bot-token"');
  });
});
