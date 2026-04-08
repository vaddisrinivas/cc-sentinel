#!/usr/bin/env bash
set -euo pipefail

# cc-retrospect installer
# Run from the plugin directory after cloning:
#   git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
#   ~/.claude/plugins/cc-retrospect/install.sh

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

echo "cc-retrospect installer"
echo "======================"
echo ""

# 1. Detect package manager
if command -v uv &>/dev/null; then
    PKG="uv pip"
    echo -e "${GREEN}Found uv${NC}"
elif command -v pip3 &>/dev/null; then
    PKG="pip3"
    echo -e "${YELLOW}uv not found, using pip3${NC}"
elif command -v pip &>/dev/null; then
    PKG="pip"
    echo -e "${YELLOW}uv not found, using pip${NC}"
else
    echo "Error: no package manager found. Install uv (recommended) or pip."
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 2. Install dependencies
echo ""
echo "Installing dependencies..."
$PKG install -e "$PLUGIN_DIR" 2>&1 | tail -3

# 3. Verify install
echo ""
echo "Verifying..."
if python3 "$PLUGIN_DIR/scripts/dispatch.py" status 2>&1 | head -8; then
    echo ""
    echo -e "${GREEN}Install successful.${NC}"
else
    echo ""
    echo -e "${YELLOW}Warning: dispatch.py status failed. Check the output above.${NC}"
fi

# 4. Backfill trends from existing data
echo ""
read -p "Backfill weekly trends from existing session data? [Y/n] " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    python3 "$PLUGIN_DIR/scripts/dispatch.py" trends --backfill 2>&1
fi

# 5. Done
echo ""
echo "======================"
echo -e "${GREEN}cc-retrospect is ready.${NC}"
echo ""
echo "Commands:  /cc-retrospect:cost, /cc-retrospect:savings, /cc-retrospect:analyze"
echo "Docs:      $PLUGIN_DIR/docs/"
echo ""
echo "Hooks fire automatically on your next Claude Code session."
