#!/usr/bin/env bash
# context-analyzer.sh - Core library for context analysis
# Returns: JSON with context stats and recommended action

analyze_context() {
    local TRANSCRIPT="$1"
    local CONTEXT_LIMIT="${2:-200000}"
    local WARN_THRESHOLD="${3:-70}"
    local DANGER_THRESHOLD="${4:-85}"
    local CRITICAL_THRESHOLD="${5:-92}"
    # Calibration: Our token count appears ~15% lower than Claude Code's native meter
    local CALIBRATION_OFFSET="${6:-15}"
    
    if [[ ! -f "$TRANSCRIPT" ]]; then
        echo '{"error": "transcript not found"}'
        return 1
    fi

    # --- Compact boundary handling ----------------------------------------
    # Claude Code writes a `{"type":"system","subtype":"compact_boundary", ...}`
    # entry to the transcript every time the session is compacted. Entries
    # before the boundary describe context that is no longer live, so using
    # their usage numbers overstates the current window.
    #
    # Strategy:
    #   1. Find the line number of the LAST compact_boundary (if any).
    #   2. Scan only entries AFTER that line for the most recent claude-*
    #      usage — this is the authoritative post-compact total.
    #   3. If no post-boundary claude-* usage exists yet (the first turn
    #      after a compact hasn't completed), fall back to the boundary's
    #      `compactMetadata.postTokens` as the effective TOTAL.
    #   4. If no boundary entry exists, behaviour is unchanged: full-file
    #      scan for the most recent claude-* usage.
    # ---------------------------------------------------------------------
    local BOUNDARY_LINE USAGE_LINE USAGE
    BOUNDARY_LINE=$(grep -n '"subtype":"compact_boundary"' "$TRANSCRIPT" 2>/dev/null | tail -n1 | cut -d: -f1)

    if [[ -n "$BOUNDARY_LINE" ]]; then
        # Scan post-boundary entries, newest-first, for the latest claude-* usage.
        # Fall back to postTokens from the boundary if none exists yet.
        USAGE_LINE=$(tail -n +$((BOUNDARY_LINE + 1)) "$TRANSCRIPT" 2>/dev/null | tac | grep -m1 '"model":"claude-[^"]*".*"usage"' || echo "")
    else
        USAGE_LINE=$(tac "$TRANSCRIPT" 2>/dev/null | grep -m1 '"model":"claude-[^"]*".*"usage"' || echo "")
    fi

    USAGE=$(echo "$USAGE_LINE" | jq -c '.message.usage // empty' 2>/dev/null || echo "")

    local INPUT CACHE_CREATE CACHE_READ OUTPUT TOTAL PERCENT ACTION
    if [[ -n "$USAGE" ]]; then
        INPUT=$(echo "$USAGE" | jq -r '.input_tokens // 0')
        CACHE_CREATE=$(echo "$USAGE" | jq -r '.cache_creation_input_tokens // 0')
        CACHE_READ=$(echo "$USAGE" | jq -r '.cache_read_input_tokens // 0')
        OUTPUT=$(echo "$USAGE" | jq -r '.output_tokens // 0')
        TOTAL=$((INPUT + CACHE_CREATE + CACHE_READ))
    elif [[ -n "$BOUNDARY_LINE" ]]; then
        # No post-boundary assistant turn yet — use the boundary's postTokens.
        # Synthetic breakdown: the post-compact context is a fresh summary (not
        # a cache-hit), so attribute the whole total to INPUT rather than
        # CACHE_READ. The per-field breakdown is approximate; only TOTAL is
        # load-bearing for downstream callers.
        local POST_TOKENS
        POST_TOKENS=$(sed -n "${BOUNDARY_LINE}p" "$TRANSCRIPT" 2>/dev/null | jq -r '.compactMetadata.postTokens // 0' 2>/dev/null)
        if [[ -n "$POST_TOKENS" && "$POST_TOKENS" != "0" && "$POST_TOKENS" != "null" ]]; then
            INPUT="$POST_TOKENS"
            CACHE_CREATE=0
            CACHE_READ=0
            OUTPUT=0
            TOTAL="$POST_TOKENS"
        else
            echo '{"error": "no usage data", "tokens": 0, "percent": 0, "action": "none"}'
            return 0
        fi
    else
        echo '{"error": "no usage data", "tokens": 0, "percent": 0, "action": "none"}'
        return 0
    fi
    RAW_PERCENT=$(echo "scale=1; ($TOTAL * 100) / $CONTEXT_LIMIT" | bc)
    # Apply calibration offset to align with Claude Code's native meter
    PERCENT=$(echo "scale=1; $RAW_PERCENT + $CALIBRATION_OFFSET" | bc)
    
    # Determine action
    if (( $(echo "$PERCENT >= $CRITICAL_THRESHOLD" | bc -l) )); then
        ACTION="critical"
    elif (( $(echo "$PERCENT >= $DANGER_THRESHOLD" | bc -l) )); then
        ACTION="crystallize"
    elif (( $(echo "$PERCENT >= $WARN_THRESHOLD" | bc -l) )); then
        ACTION="warn"
    else
        ACTION="none"
    fi
    
    # Output JSON
    jq -n \
        --argjson input "$INPUT" \
        --argjson cache_create "$CACHE_CREATE" \
        --argjson cache_read "$CACHE_READ" \
        --argjson output "$OUTPUT" \
        --argjson total "$TOTAL" \
        --argjson limit "$CONTEXT_LIMIT" \
        --arg percent "$PERCENT" \
        --arg action "$ACTION" \
        '{
            tokens: {
                input: $input,
                cache_create: $cache_create,
                cache_read: $cache_read,
                output: $output,
                total: $total
            },
            limit: $limit,
            percent: ($percent | tonumber),
            action: $action
        }'
}

# Allow sourcing or direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    analyze_context "$@"
fi
