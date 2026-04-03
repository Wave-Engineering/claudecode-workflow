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
    
    # Get most recent MAIN AGENT message with usage
    # CRITICAL: Filter for REAL model messages (claude-*), not synthetic placeholders
    # Synthetic messages have model:"<synthetic>" with all-zero usage data
    local USAGE_LINE USAGE
    USAGE_LINE=$(tac "$TRANSCRIPT" 2>/dev/null | grep -m1 '"model":"claude-[^"]*".*"usage"' || echo "")
    
    USAGE=$(echo "$USAGE_LINE" | jq -c '.message.usage // empty' 2>/dev/null || echo "")
    
    if [[ -z "$USAGE" ]]; then
        echo '{"error": "no usage data", "tokens": 0, "percent": 0, "action": "none"}'
        return 0
    fi
    
    local INPUT CACHE_CREATE CACHE_READ OUTPUT TOTAL PERCENT ACTION
    INPUT=$(echo "$USAGE" | jq -r '.input_tokens // 0')
    CACHE_CREATE=$(echo "$USAGE" | jq -r '.cache_creation_input_tokens // 0')
    CACHE_READ=$(echo "$USAGE" | jq -r '.cache_read_input_tokens // 0')
    OUTPUT=$(echo "$USAGE" | jq -r '.output_tokens // 0')
    
    TOTAL=$((INPUT + CACHE_CREATE + CACHE_READ))
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
