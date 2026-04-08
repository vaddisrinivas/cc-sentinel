#!/usr/bin/env bash
set -euo pipefail

# cc-retrospect installer
# Run from the plugin directory after cloning:
#   git clone https://github.com/vaddisrinivas/cc-retrospect ~/.claude/plugins/cc-retrospect
#   ~/.claude/plugins/cc-retrospect/install.sh

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

# Parse flags
DRY_RUN=0
UNINSTALL=0
UPGRADE=0
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        --upgrade) UPGRADE=1; shift ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

if [ $UNINSTALL -eq 1 ]; then
    echo "Uninstalling cc-retrospect..."
    python3 "$PLUGIN_DIR/scripts/dispatch.py" uninstall
    echo -e "${GREEN}Uninstall complete.${NC}"
    exit 0
fi

echo "cc-retrospect installer"
echo "======================"
echo ""
[ $DRY_RUN -eq 1 ] && echo -e "${YELLOW}[DRY RUN]${NC}"
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
if [ $DRY_RUN -eq 0 ]; then
    $PKG install -e "$PLUGIN_DIR" 2>&1 | tail -3
else
    echo "[DRY RUN] Would run: $PKG install -e $PLUGIN_DIR"
fi

# 3. Health check
echo ""
echo "Health check..."
if [ $DRY_RUN -eq 0 ]; then
    if python3 "$PLUGIN_DIR/scripts/dispatch.py" status 2>&1 | head -8; then
        echo ""
        echo -e "${GREEN}Install successful.${NC}"
    else
        echo ""
        echo -e "${RED}Error: health check failed. See output above.${NC}"
        exit 1
    fi
else
    echo "[DRY RUN] Would verify: python3 dispatch.py status"
fi

# 4. Backfill trends from existing data
echo ""
if [ $DRY_RUN -eq 0 ]; then
    read -p "Backfill weekly trends from existing session data? [Y/n] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        python3 "$PLUGIN_DIR/scripts/dispatch.py" trends --backfill 2>&1
    fi
else
    echo "[DRY RUN] Would ask about backfilling trends"
fi

# 5. Done
echo ""
echo "======================"
if [ $DRY_RUN -eq 0 ]; then
    echo -e "${GREEN}cc-retrospect is ready.${NC}"
else
    echo -e "${YELLOW}[DRY RUN] Installation preview complete.${NC}"
fi
echo ""
echo "Commands:  /cc-retrospect:cost, /cc-retrospect:savings, /cc-retrospect:analyze"
echo "Docs:      $PLUGIN_DIR/docs/"
echo ""
if [ $DRY_RUN -eq 0 ]; then
    echo "Hooks fire automatically on your next Claude Code session."
fi
