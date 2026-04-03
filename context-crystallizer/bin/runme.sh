# Find your transcript
TRANSCRIPT=$(find ~/.claude/projects -name "*.jsonl" -type f -mmin -5 | head -1)

# See if there are ANY lines with "type":"assistant" and "usage"
echo "=== Lines matching our pattern ==="
grep '"type":"assistant"' "$TRANSCRIPT" | grep '"usage"' | tail -3

echo ""
echo "=== Lines matching WITHOUT progress filter ==="
grep '"type":"assistant".*"usage"' "$TRANSCRIPT" | tail -3

echo ""
echo "=== What tac + grep finds ==="
tac "$TRANSCRIPT" | grep -m1 '"type":"assistant".*"usage"'

echo ""
echo "=== What tac + grep + progress filter finds ==="
tac "$TRANSCRIPT" | grep -m1 '"type":"assistant".*"usage"' | grep -v '"type":"progress"'
