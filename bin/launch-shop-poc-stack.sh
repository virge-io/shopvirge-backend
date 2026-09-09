#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# Config (defaults — override via .env)
# -----------------------------------------------------------------------------

PROJECTS_DIR="${PROJECTS_DIR:-$HOME/Projects}"

SHOP_POC_DIR="${SHOP_POC_DIR:-$PROJECTS_DIR/shop-poc}"
SHOP_EDIT_DIR="${SHOP_EDIT_DIR:-$PROJECTS_DIR/shop}"

SHOP_BACKEND_DIR="${SHOP_BACKEND_DIR:-$PROJECTS_DIR/shop-backend}"

WFO_FORMATICS_DIR="${WFO_FORMATICS_DIR:-$PROJECTS_DIR/wfo-backend-formatics}"
WFO_UI_DIR="${WFO_UI_DIR:-$PROJECTS_DIR/orchestrator-ui-library}"

SESSION="${SESSION:-shop-poc-stack}"

# -----------------------------------------------------------------------------
# Default Flags
# -----------------------------------------------------------------------------
EDIT_MODE=false
RUN_WFO_UI=false
FORCE_LOCAL=false

# -----------------------------------------------------------------------------
# Load optional global .env
# -----------------------------------------------------------------------------
ENV_FILE="${ENV_FILE:-$HOME/Projects/.Launch/.env}"
if [[ -f "$ENV_FILE" ]]; then
    echo "Loading config from $ENV_FILE"
    set -o allexport
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +o allexport
fi

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --edit|-e)
            EDIT_MODE=true
            shift
            ;;
        --orchestrator-ui|-ou|--wfo-ui)
            RUN_WFO_UI=true
            shift
            ;;
        --force-local|-fl|--force-local-stack)
            FORCE_LOCAL=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--edit|-e] [--orchestrator-ui|-ou|--wfo-ui] [--force-local|-fl]"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Detect environment
# -----------------------------------------------------------------------------
ENVIRONMENT_NAME="unknown"
SHOP_POC_ENV_FILE="$SHOP_POC_DIR/.env"

if [[ -f "$SHOP_POC_ENV_FILE" ]]; then
    ENVIRONMENT_NAME=$(grep -E '^NEXT_PUBLIC_ENVIRONMENT_NAME=' "$SHOP_POC_ENV_FILE" | cut -d '=' -f2 | tr -d '"')
fi

echo "Detected NEXT_PUBLIC_ENVIRONMENT_NAME=$ENVIRONMENT_NAME"

RUN_LOCAL_STACK=true
if [[ "$ENVIRONMENT_NAME" != "development" && "$FORCE_LOCAL" = false ]]; then
    RUN_LOCAL_STACK=false
    echo "Non-development environment detected → skipping shop-edit & shop-backend"
    echo "Use --force-local to override"
fi

# -----------------------------------------------------------------------------
# Validate WFO dependencies
# -----------------------------------------------------------------------------
if [[ ! -d "$WFO_FORMATICS_DIR" ]]; then
    echo "Warning: WFO formatics dir not found at $WFO_FORMATICS_DIR → skipping"
    RUN_WFO_FORMATICS=false
    if $RUN_WFO_UI; then
        echo "Warning: WFO UI requires formatics → disabling WFO UI"
        RUN_WFO_UI=false
    fi
else
    RUN_WFO_FORMATICS=true
fi

# -----------------------------------------------------------------------------
# Preconditions
# -----------------------------------------------------------------------------
if ! command -v tmux &>/dev/null; then
    echo "Error: tmux is not installed."
    exit 1
fi

# -----------------------------------------------------------------------------
# Reset session
# -----------------------------------------------------------------------------
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Killing existing session '$SESSION'..."
    tmux kill-session -t "$SESSION"
fi

echo "Starting stack..."
$EDIT_MODE && echo "→ Edit mode enabled"
$RUN_WFO_UI && echo "→ WFO UI enabled ($WFO_UI_DIR)"
$FORCE_LOCAL && echo "→ Force local stack enabled"

# -----------------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------------
create_window() {
    local name="$1"
    local cmd="$2"

    tmux new-window -t "$SESSION" -n "$name"
    tmux send-keys -t "$SESSION:$name" "$cmd" Enter
}

# -----------------------------------------------------------------------------
# 1. Always create session with correct FIRST window
# -----------------------------------------------------------------------------
if $EDIT_MODE && $RUN_LOCAL_STACK; then
    # shop-edit MUST be first → owns port 3000
    tmux new-session -d -s "$SESSION" -n "shop-edit"
    tmux send-keys -t "$SESSION:shop-edit" \
        "cd $SHOP_EDIT_DIR && yarn turbo dev --filter pricelist-shop" Enter

    SHOP_POC_CMD="npm run dev -- -p 3001"
else
    tmux new-session -d -s "$SESSION" -n "shop-poc"
    SHOP_POC_CMD="npm run dev"
fi

# -----------------------------------------------------------------------------
# 2. shop-poc
# -----------------------------------------------------------------------------
if $EDIT_MODE && $RUN_LOCAL_STACK; then
    create_window "shop-poc" "cd $SHOP_POC_DIR && $SHOP_POC_CMD"
else
    tmux send-keys -t "$SESSION:shop-poc" \
        "cd $SHOP_POC_DIR && $SHOP_POC_CMD" Enter
fi

# -----------------------------------------------------------------------------
# 3. wfo-backend-formatics (optional now)
# -----------------------------------------------------------------------------
if $RUN_WFO_FORMATICS; then
    create_window "wfo-formatics" \
        "cd $WFO_FORMATICS_DIR && ./start.sh dev"
fi

# -----------------------------------------------------------------------------
# 4. shop backend (gated)
# -----------------------------------------------------------------------------
if $RUN_LOCAL_STACK; then
    create_window "shop-backend" \
        "cd $SHOP_BACKEND_DIR && ./start.sh dev"
fi

# -----------------------------------------------------------------------------
# 5. WFO UI (optional + dependency-aware)
# -----------------------------------------------------------------------------
if $RUN_WFO_UI; then
    #echo "Waiting for shop-edit to initialize (port 3000)..."
    #sleep 2
    create_window "wfo-ui" \
        "cd $WFO_UI_DIR && npx turbo run dev --filter=wfo-ui -- --port 3002"
fi

# -----------------------------------------------------------------------------
# Attach
# -----------------------------------------------------------------------------
tmux attach-session -t "$SESSION" \; choose-window
