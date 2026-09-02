#!/bin/bash
# siesta.sh — Entry point for Siesta 💤
# Usage: ./factory/bin/siesta.sh "Build me a CLI pomodoro timer in Python"
#
# What it does:
#   1. Takes your idea
#   2. Interviews you (human interactive)
#   3. You leave. Go take a siesta. 💤
#   4. The planner (GLM-5.2) generates spec + plan
#   5. The worker (Qwen 2.5, local) executes issues autonomously
#   6. If stuck → the consultant resolves → if 3 fails → deep diagnosis
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
echo "║  Models:   GLM-5.2 (planner/consultant) via pi             ║"
echo "║  Worker:    Qwen 2.5 Coder — local (Ollama), writes code   ║"
echo "║  Guard:     Degenerate-output guard + regression gating     ║"
echo "║  Fallback:    Deep diagnosis + skip (from Ralph)           ║"
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
IDEA="${@: -1}"  # flags may come first; show the idea, not "--auto"
echo -e "${BLUE}Idea:${NC} $IDEA"
echo ""

if echo "$@" | grep -q -- "--auto"; then
  echo -e "${CYAN}Auto mode: skipping interview. Using idea as intent directly.${NC}"
  echo ""
else
  echo -e "${YELLOW}The agent will ask you questions first. Then you can leave.${NC}"
  echo ""
fi

# Run the pipeline (Python port lives in $FACTORY_DIR/pipeline/)
exec env PYTHONPATH="$FACTORY_DIR" python3 -m pipeline "$@"