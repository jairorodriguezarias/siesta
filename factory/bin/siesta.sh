#!/bin/bash
# siesta.sh — Entry point for Siesta 💤
# Usage: ./factory/bin/siesta.sh "Build me a CLI pomodoro timer in Python"
#
# What it does:
#   1. Takes your idea
#   2. Interviews you (human interactive)
#   3. You leave. Go take a siesta. 💤
#   4. GLM-5.2 generates spec + plan
#   5. Qwen 2.5 executes issues autonomously
#   6. If stuck → GLM-5.2 consults → if 3 fails → deep diagnosis
#   7. Reviews code, verifies it runs, git commits
#   8. Learns from every issue to improve for next time
#   9. You wake up. Working code is ready.
#
# 💤 Go take a siesta. Come back to working code.

set -e

FACTORY_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ─── Colors ───
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║              💤  SIESTA  💤                                ║"
echo "║                                                            ║"
echo "║  \"Give me an idea, go take a siesta, come back to code\"    ║"
echo "║                                                            ║"
echo "║  Planner:     GLM-5.2 (spec + plan + consultant)           ║"
echo "║  Worker:      Qwen 2.5 Coder (execute + review + verify)  ║"
echo "║  Fallback:    Deep diagnosis + skip (from Ralph)          ║"
echo "║  Skills:      10 addyosmani + 5 factory custom            ║"
echo "║  KB:          JSON graph with progressive disclosure      ║"
echo "║  Learning:    Per-issue + project-level (self-improving)  ║"
echo "║  Safety:      stop.md + regression suite + escalation     ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [ -z "$1" ]; then
  echo -e "${YELLOW}Usage:${NC}"
  echo "  ./factory/bin/siesta.sh \"<project idea>\" [--auto]"
  echo ""
  echo -e "${YELLOW}Examples:${NC}"
  echo "  ./factory/bin/siesta.sh \"Build a CLI pomodoro timer in Python\""
  echo "  ./factory/bin/siesta.sh --auto \"Build a CLI pomodoro timer in Python\""
  echo ""
  echo -e "${CYAN}--auto: Skip interview phase, use idea as intent directly.${NC}"
  echo -e "${CYAN}Pass --auto when the idea is already detailed enough.${NC}"
  echo ""
  echo -e "${CYAN}💤 Go take a siesta. Come back to working code.${NC}"
  echo ""
  exit 1
fi

echo -e "${BLUE}━━━ Starting Siesta 💤 ━━━${NC}"
echo -e "${BLUE}Idea:${NC} $1"
echo ""

if echo "$@" | grep -q -- "--auto"; then
  echo -e "${CYAN}Auto mode: skipping interview. Using idea as intent directly.${NC}"
  echo ""
else
  echo -e "${YELLOW}The agent will ask you questions first. Then you can leave.${NC}"
  echo ""
fi

# Run the pipeline
exec "$FACTORY_DIR/scripts/run-pipeline.sh" "$@"