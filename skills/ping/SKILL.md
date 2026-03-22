---
name: agent-say
description: Send a message to #ai-dev as this Claude Code agent. Reads agent identity from the standard identity system (CLAUDE.md + session file), and posts with full Slack mrkdwn formatting. Use when communicating with other agents or announcing status.
---

# Agent Say — Post to #ai-dev as This Agent

You are sending a message to the `#ai-dev` Slack channel on behalf of this Claude Code instance.
Follow these steps exactly, in order.

---

## Step 1: Load Identity

Identity is managed by the Agent Identity system defined in `CLAUDE.md`. Load it now.

```bash
cat /tmp/claude-agent-$(echo $PPID).json 2>/dev/null
```

**If the file exists:** load `dev_team`, `dev_name`, and `dev_avatar` from it. Proceed to Step 2.

**If the file does NOT exist:** Session onboarding has not run yet. Trigger it now:
1. Read `Dev-Team` from the current project's `CLAUDE.md` (look for the `Dev-Team:` line). If empty, ask the user what Dev-Team name to use and write it into `CLAUDE.md`.
2. Pick a `dev_name` and `dev_avatar` following the naming rules in the Agent Identity section of `CLAUDE.md`.
3. Persist to `/tmp/claude-agent-<PPID>.json`:
   ```bash
   cat > /tmp/claude-agent-$(echo $PPID).json << 'EOF'
   {
     "dev_team": "<resolved team>",
     "dev_name": "<your chosen name>",
     "dev_avatar": "<your chosen emoji>"
   }
   EOF
   ```
4. Announce your identity to the user before continuing.

---

## Step 2: Compose the Message

Use the user's request to determine what to say. If no message was specified, compose a contextually appropriate one based on current work.

Format in Slack mrkdwn:
- Bold: `*text*` (NOT `**text**`)
- Italic: `_text_`
- Inline code: `` `code` ``
- Lists: `- item`
- Lead with the key point — don't bury the lede

---

## Step 3: Confirm Before Sending

Show a preview:
```
From:    <dev_name> <dev_avatar>  [<dev_team>]
Channel: #ai-dev
Message:
<the composed message>
```

Ask: "Send this?" and wait for explicit confirmation.

---

## Step 4: Send

```bash
CLAUDE_AGENT_NAME="<dev_name> [<dev_team>]" \
CLAUDE_AGENT_EMOJI="<dev_avatar>" \
slackbot-send "#ai-dev" "<message>"
```

To reply in an existing thread, append `--thread <thread_ts>`.

On success, `slackbot-send` outputs the message `ts`. Save it as `last_thread_ts` in the PPID file:
```bash
PPID_FILE="/tmp/claude-agent-$(echo $PPID).json"
jq --arg ts "<returned_ts>" '. + {last_thread_ts: $ts}' "$PPID_FILE" > "$PPID_FILE.tmp" && mv "$PPID_FILE.tmp" "$PPID_FILE"
```

Report it to the user:
> "Sent. ts: `<ts>` — saved as your current thread."

If `--thread <ts>` was used to reply to an existing thread, save that parent ts as `last_thread_ts` instead.

On failure, show the error verbatim. Do not retry automatically.

---

## Notes

- The bot token is read automatically from `~/secrets/slack-bot-token`.
- Identity is managed by the Agent Identity section in `CLAUDE.md`. This skill is a consumer of that system, not the owner.
- Identity is stable for the life of this session (keyed to `$PPID`). A new CC window = new identity.
- The `Dev-Team` label appears in brackets after the name so channel readers know what project the agent is from.
