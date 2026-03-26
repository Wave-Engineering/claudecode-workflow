#!/usr/bin/env bash
# Claude Code status line — mirrors ~/.bashrc __build_prompt

input=$(cat)

cwd=$(echo "$input" | jq -r '.cwd // .workspace.current_dir // ""')
model=$(echo "$input" | jq -r '.model.display_name // ""')
remaining_pct=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

# ANSI colors
c_purple='\033[38;5;97m'
c_green='\033[01;32m'
c_blue='\033[01;34m'
c_cyan='\033[36m'
c_red='\033[31m'
c_yellow='\033[33m'
c_reset='\033[00m'

# Shorten path: replace $HOME with ~
short_cwd="${cwd/#$HOME/\~}"

# Git info
git_line=""
if git_output=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" status --porcelain -b 2>/dev/null); then
	branch_line="${git_output%%$'\n'*}"

	branch="${branch_line#\#\# }"
	branch="${branch%%...*}"
	branch="${branch%% \[*}"

	if [[ "$branch" == "HEAD (no branch)"* ]]; then
		branch="detached:$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --short HEAD 2>/dev/null)"
	fi

	repo=$(basename "$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)")

	ahead=0
	behind=0
	if [[ "$branch_line" =~ \[ahead\ ([0-9]+) ]]; then ahead="${BASH_REMATCH[1]}"; fi
	if [[ "$branch_line" =~ behind\ ([0-9]+) ]]; then behind="${BASH_REMATCH[1]}"; fi

	staged=0
	dirty=0
	if [[ "$git_output" == *$'\n'* ]]; then
		status_lines="${git_output#*$'\n'}"
		while IFS= read -r line; do
			[[ "${line:0:1}" =~ [MADRC] ]] && ((staged++))
			[[ "${line:1:1}" =~ [MADRC\?] ]] && ((dirty++))
		done <<<"$status_lines"
	fi

	git_line="  $(printf '%b' "${c_cyan}")${repo} @ ${branch}$(printf '%b' "${c_reset}")"

	if ((dirty > 0)); then
		git_line+=" $(printf '%b' "${c_red}")✗$(printf '%b' "${c_reset}")"
	else
		git_line+=" $(printf '%b' "${c_green}")✓$(printf '%b' "${c_reset}")"
	fi

	if ((staged > 0)); then
		git_line+=" $(printf '%b' "${c_yellow}")+${staged}$(printf '%b' "${c_reset}")"
	fi

	if ((ahead > 0)); then
		git_line+=" $(printf '%b' "${c_yellow}")↑${ahead}$(printf '%b' "${c_reset}")"
	fi

	if ((behind > 0)); then
		git_line+=" $(printf '%b' "${c_yellow}")↓${behind}$(printf '%b' "${c_reset}")"
	fi
fi

# Context remaining indicator (always shown when available)
ctx_str=""
if [ -n "$remaining_pct" ]; then
	remaining_int=${remaining_pct%.*}
	if ((remaining_int <= 13)); then
		ctx_color="$c_red"
	elif ((remaining_int <= 25)); then
		ctx_color="$c_yellow"
	else
		ctx_color="$c_cyan"
	fi
	ctx_str="  $(printf '%b' "${ctx_color}")ctx remaining: ${remaining_int}%$(printf '%b' "${c_reset}")"
fi

# Model indicator
model_str=""
if [ -n "$model" ]; then
	model_str="  $(printf '%b' "${c_purple}")${model}$(printf '%b' "${c_reset}")"
fi

# Agent dev-name (from CLAUDE.md agent identity)
# Identity files are keyed by md5 of the project root so the statusline
# resolves the correct agent regardless of process ancestry.
agent_str=""
if [ -n "$cwd" ]; then
	project_root=$(GIT_OPTIONAL_LOCKS=0 git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || echo "$cwd")
	dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
	agent_file="/tmp/claude-agent-${dir_hash}.json"
	if [ -f "$agent_file" ]; then
		dev_name=$(jq -r '.dev_name // empty' "$agent_file" 2>/dev/null)
		dev_avatar=$(jq -r '.dev_avatar // empty' "$agent_file" 2>/dev/null)
		if [ -n "$dev_name" ]; then
			agent_str="  $(printf '%b' "${c_green}")${dev_name}$(printf '%b' "${c_reset}")"
			if [ -n "$dev_avatar" ]; then
				agent_str="${agent_str} ${dev_avatar}"
			fi
		fi
	fi
fi

# Assemble output
printf '%b' "${c_blue}${short_cwd}${c_reset}"
printf "%s" "$agent_str"
if [ -n "$git_line" ]; then
	printf "%s" "$git_line"
fi
printf "%s" "$ctx_str"
printf "%s" "$model_str"
printf "\n"
