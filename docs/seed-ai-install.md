# Seed: Installing the Claude Code Workflow Kit

You are a Claude Code agent. A human has asked you to install the **cc-workflow** kit (Claude Code workflow environment by Wave-Engineering). Follow every step below in order. Do not skip steps. Do not ask the human for input unless explicitly told to below.

---

## 0. Pre-flight: Detect Environment

```bash
uname -s   # Linux or Darwin
uname -m   # x86_64 or arm64
echo $SHELL
```

Record the OS and architecture. You will need them for dependency installation.

Check if this is a corporate/restricted environment:

```bash
# Self-signed cert check — if this fails with SSL error, you're behind a corporate proxy
curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/main/README.md > /dev/null 2>&1 || echo "CERT_ISSUE"
```

If `CERT_ISSUE` is detected, see [Troubleshooting: Corporate Environments](#troubleshooting-corporate-environments) before proceeding.

---

## 1. Clone the Repository

```bash
git clone https://github.com/Wave-Engineering/claudecode-workflow.git ~/.local/share/claudecode-workflow
```

If the directory already exists, pull instead:

```bash
cd ~/.local/share/claudecode-workflow && git pull --ff-only
```

Set a variable for convenience in subsequent steps:

```bash
CCWORK_DIR="$HOME/.local/share/claudecode-workflow"
```

---

## 2. Install Dependencies

The kit requires these CLI tools. Check which are missing, then install them.

### Required

| Tool | Check | Purpose |
|------|-------|---------|
| `jq` | `command -v jq` | Settings merge, MCP install |
| `curl` | `command -v curl` | MCP install scripts, remote fetch |
| `bun` | `command -v bun` | MCP server builds (discord-watcher, etc.) |
| `gh` | `command -v gh` | GitHub CLI (issues, PRs, releases) |
| `python3` | `command -v python3` | Package builds (zipapp) |
| `shellcheck` | `command -v shellcheck` | Script validation |
| `shfmt` | `command -v shfmt` | Script formatting |

### Optional

| Tool | Check | Purpose |
|------|-------|---------|
| `glab` | `command -v glab` | GitLab CLI (only needed for GitLab projects) |
| `trivy` | `command -v trivy` | Dependency vulnerability scan in precheck |

### Install commands by platform

Run ONLY the commands for tools that are missing.

**Ubuntu/Debian (apt):**

```bash
sudo apt update && sudo apt install -y jq curl shellcheck python3
```

**macOS (Homebrew):**

```bash
brew install jq curl shellcheck shfmt gh python3
```

**Fedora/RHEL (dnf):**

```bash
sudo dnf install -y jq curl ShellCheck python3
```

**Arch (pacman):**

```bash
sudo pacman -S --noconfirm jq curl shellcheck shfmt python3
```

### Tools with special install procedures

**bun** (all platforms):

```bash
curl -fsSL https://bun.sh/install | bash
# Reload PATH
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"
```

**gh** (GitHub CLI):

```bash
# Ubuntu/Debian
(type -p wget >/dev/null || sudo apt install wget -y) \
  && sudo mkdir -p -m 755 /etc/apt/keyrings \
  && out=$(mktemp) && wget -nv -O$out https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  && cat $out | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null \
  && sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
  && sudo apt update \
  && sudo apt install gh -y

# macOS
brew install gh
```

**shfmt:**

```bash
# Via go install (requires go)
go install mvdan.cc/sh/v3/cmd/shfmt@latest

# Or via brew (macOS)
brew install shfmt

# Or download binary directly (Linux amd64)
curl -fsSL "https://github.com/mvdan/sh/releases/latest/download/shfmt_$(uname -s)_$(uname -m)" -o ~/.local/bin/shfmt && chmod +x ~/.local/bin/shfmt
```

**glab** (if GitLab projects are needed):

```bash
# Ubuntu/Debian
curl -fsSL "https://gitlab.com/gitlab-org/cli/-/releases/permalink/latest/downloads/glab_$(uname -s)_$(uname -m).deb" -o /tmp/glab.deb && sudo dpkg -i /tmp/glab.deb

# macOS
brew install glab
```

**trivy** (optional):

```bash
# Ubuntu/Debian
sudo apt install -y wget apt-transport-https gnupg lsb-release \
  && wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add - \
  && echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee /etc/apt/sources.list.d/trivy.list \
  && sudo apt update && sudo apt install trivy -y

# macOS
brew install trivy
```

---

## 3. Ensure PATH Includes ~/.local/bin

The kit installs scripts to `~/.local/bin`. Verify it is on PATH:

```bash
echo "$PATH" | grep -q "$HOME/.local/bin" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
```

For zsh users:

```bash
echo "$PATH" | grep -q "$HOME/.local/bin" || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Reload after adding:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

---

## 4. Run the Installer

```bash
cd "$CCWORK_DIR" && ./install
```

This installs:
- Skills to `~/.claude/skills/`
- Scripts to `~/.claude/scripts/` (Cellar) with symlinks in `~/.local/bin/`
- Config (statusline, settings.json smart-merge) to `~/.claude/`
- MCP servers from the `mcps.json` manifest

If this is a **re-install** (updating an existing installation), the installer automatically:
- Backs up changed files to `.bak`
- Skips unchanged files
- Removes deprecated components
- Smart-merges new settings without overwriting customizations

---

## 5. Authenticate CLI Tools

### GitHub CLI

```bash
gh auth status || gh auth login
```

If `gh auth login` is needed, the human will need to complete the browser OAuth flow.

### GitLab CLI (if needed)

```bash
glab auth status || glab auth login
```

---

## 6. Verify Installation

Run the built-in check:

```bash
cd "$CCWORK_DIR" && ./install --check
```

This reports:
- Skill sync status
- Script sync status (Cellar + symlink farm)
- Settings completeness (hooks, plugins, permissions)
- MCP server registration
- Dependency availability
- Package build status

**Success criteria:** Zero items "out of sync" or "NOT INSTALLED" for required components. Optional items (trivy, glab, secrets) may show as missing without blocking success.

---

## 7. Display Success

If step 6 shows all required items in sync, display the logo from `$CCWORK_DIR/assets/logo.txt` and report to the human:

```
            ___________________________
           /                           \
          /   | |                 | |   \
         /     \|                 |/     \
        |       \                 /       |
        |        --------+--------        |
        |                |                |
        |      | |       |       | |      |
        |       \|       |       |/       |
        |        \       |       /        |
        |         -------+-------         |
        |                |                |
        |         | |    |    | |         |
        |          \|    |    |/          |
        |           \    |    /           |
        |            ----+----            |
        |                |                |
        |                |                |
        |                |                |
        |                |                |
        |  _.-~-._       |       _.-~-._ |
        |  ~     ~-._    |    _.-~   *~  |
         \     ~   ~----~~~----~   ~    /
          \           ~~~~~~~          /
           \___________________________/

            O A K    &    W A V E

cc-workflow installed successfully.

Installed:
  - Skills:  ~/.claude/skills/ (N skills)
  - Scripts: ~/.claude/scripts/ (Cellar) + ~/.local/bin/ (symlinks)
  - Config:  ~/.claude/settings.json (smart-merged)
  - MCPs:    wtf-server, discord-watcher, nerf-server, disc-server, sdlc-server

Next steps:
  1. Start a new Claude Code session in any project
  2. Run /engage to load the kit and confirm rules
  3. See docs/getting-started.md for a 15-minute walkthrough
```

---

## Troubleshooting: Corporate Environments

### Self-signed certificates / corporate proxy

If `curl` fails with SSL/certificate errors:

```bash
# Option 1: Tell curl to skip certificate verification (use only if you trust the network)
curl -kfsSL <url> | bash

# Option 2: Set NODE_EXTRA_CA_CERTS for bun/node operations
export NODE_EXTRA_CA_CERTS=/path/to/corporate-ca-bundle.crt

# Option 3: Tell git to use the corporate CA bundle
git config --global http.sslCAInfo /path/to/corporate-ca-bundle.crt
```

Common CA bundle locations:
- Ubuntu/Debian: `/etc/ssl/certs/ca-certificates.crt`
- RHEL/Fedora: `/etc/pki/tls/certs/ca-bundle.crt`
- macOS: `/etc/ssl/cert.pem` (or export from Keychain Access)

To find the corporate cert if you don't know the path:

```bash
# Check if the system trust store has been modified
ls -la /usr/local/share/ca-certificates/
# Or check environment
echo "$SSL_CERT_FILE" "$CURL_CA_BUNDLE" "$REQUESTS_CA_BUNDLE"
```

### MCP server install failures behind proxy

The MCP install scripts use `curl`. If they fail:

```bash
# Re-run installer with curl -k via environment
# (each MCP's install-remote.sh respects this)
export CURL_OPTS="-k"
cd "$CCWORK_DIR" && ./install --mcps
```

If that does not work, install MCPs manually by cloning their repos:

```bash
git clone https://github.com/Wave-Engineering/mcp-server-wtf.git /tmp/mcp-wtf && cd /tmp/mcp-wtf && ./scripts/install-local.sh
git clone https://github.com/Wave-Engineering/mcp-server-discord-watcher.git /tmp/mcp-dw && cd /tmp/mcp-dw && ./scripts/install-local.sh
git clone https://github.com/Wave-Engineering/mcp-server-nerf.git /tmp/mcp-nerf && cd /tmp/mcp-nerf && ./scripts/install-local.sh
git clone https://github.com/Wave-Engineering/mcp-server-discord.git /tmp/mcp-disc && cd /tmp/mcp-disc && ./scripts/install-local.sh
git clone https://github.com/Wave-Engineering/mcp-server-sdlc.git /tmp/mcp-sdlc && cd /tmp/mcp-sdlc && ./scripts/install-local.sh
```

---

## Troubleshooting: PEP 668 (Externally Managed Environment)

On modern Ubuntu (23.04+), Debian 12+, and Fedora 38+, `pip install` outside a venv is blocked:

```
error: externally-managed-environment
```

**Solution:** Use `pipx` for any Python tool installs:

```bash
# Install pipx if missing
sudo apt install pipx   # or: brew install pipx
pipx ensurepath

# Then install Python-based tools via pipx, not pip
pipx install <tool-name>
```

For the cc-workflow kit itself, Python packages are built as zipapps (self-contained executables via `scripts/ci/build.sh`). They do NOT require pip install. If you see a pip-related error during install, it is likely from:

1. **The commutativity-probe** — see the next section.
2. **A dependency of an MCP server** — use `bun install` (not pip) for MCP servers.

---

## Troubleshooting: commutativity-probe pip install failure

The `commutativity-probe` is a Python tool used by the SDLC server. If its installation fails with PEP 668 or permission errors:

```bash
# The probe is distributed as a zipapp — it should NOT need pip install.
# If something triggered a pip install attempt, the workaround is:

# 1. Check if the zipapp already exists in the Cellar
ls ~/.claude/scripts/commutativity-probe

# 2. If missing, build it from source
cd "$CCWORK_DIR" && ./scripts/ci/build.sh

# 3. Verify it runs
~/.claude/scripts/commutativity-probe --version
```

If build.sh itself fails due to missing Python dependencies:

```bash
# Create a temporary venv for the build
python3 -m venv /tmp/ccwork-build-venv
source /tmp/ccwork-build-venv/bin/activate
pip install -r "$CCWORK_DIR/src/commutativity_probe/requirements.txt" 2>/dev/null || true
cd "$CCWORK_DIR" && ./scripts/ci/build.sh
deactivate
```

---

## Troubleshooting: Permission Issues

### ~/.local/bin not writable

```bash
mkdir -p ~/.local/bin
chmod 755 ~/.local/bin
```

### ~/.claude not writable

```bash
mkdir -p ~/.claude/skills ~/.claude/scripts ~/.claude/logs
chmod -R 755 ~/.claude
```

### sudo not available (for apt/dnf installs)

If the user cannot sudo, they need to install dependencies via:
- Their package manager with user-level access
- Homebrew (which does not need root): https://brew.sh
- Direct binary downloads to `~/.local/bin/`

Report to the human which dependencies could not be installed and why.

---

## Troubleshooting: Bun Install Failures

If `bun install` (used by MCP servers) fails:

```bash
# Clear bun cache
rm -rf ~/.bun/install/cache

# If bun itself won't install (curl fails)
# Try the npm fallback:
npm install -g bun

# If on a system where the bun binary doesn't work (old glibc, musl, etc.)
# MCP servers can fall back to node — check each server's README for node support
```

---

## Troubleshooting: shfmt Binary Not Found After Install

`go install` puts binaries in `$GOPATH/bin` (default `~/go/bin`). Ensure it is on PATH:

```bash
echo "$PATH" | grep -q "$HOME/go/bin" || export PATH="$HOME/go/bin:$PATH"
```

Add to shell rc if needed:

```bash
echo 'export PATH="$HOME/go/bin:$PATH"' >> ~/.bashrc  # or ~/.zshrc
```

---

## Troubleshooting: MCP Servers Not Registering

If `./install --check` shows MCP servers as "NOT REGISTERED":

```bash
# Verify claude CLI is available
command -v claude

# List registered MCPs
claude mcp list

# Manual registration (if install-remote.sh failed)
claude mcp add wtf-server -- bun run ~/.local/share/mcp-server-wtf/src/index.ts
claude mcp add discord-watcher -- bun run ~/.local/share/mcp-server-discord-watcher/src/index.ts
claude mcp add nerf-server -- bun run ~/.local/share/mcp-server-nerf/src/index.ts
claude mcp add disc-server -- bun run ~/.local/share/mcp-server-discord/src/index.ts
claude mcp add sdlc-server -- bun run ~/.local/share/mcp-server-sdlc/src/index.ts
```

---

## Notes for Future Troubleshooting Additions

This document is designed to be extended. When a new installation failure mode is encountered:

1. Add a new `## Troubleshooting: <Issue Name>` section at the end (before this Notes section)
2. Include: symptom description, detection command, fix commands
3. Keep each section self-contained (no dependencies on other troubleshooting sections)
