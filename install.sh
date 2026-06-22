#!/usr/bin/env bash
# ============================================================
# EnviroPulse V2.0
# File: install.sh
# Role: Install Entrypoint
# ============================================================
#
# Purpose:
#   Provide the top-level EnviroPulse installer entrypoint.
#
# Supports:
#   - Node install path
#   - Future server install path
#   - Future GUI install path
#
# Does:
#   - Resolves the EnviroPulse repository root.
#   - Verifies Linux package manager availability.
#   - Installs required apt packages for node runtime.
#   - Creates the Python virtual environment.
#   - Installs Python requirements.
#   - Calls the node install wizard when available.
#
# Does NOT:
#   - Own runtime subsystem logic.
#   - Modify production Python source files.
#   - Start EnviroPulse runtime services yet.
#   - Configure systemd services yet.
#   - Rewrite boot overlays yet.
#
# Architecture Notes:
#   - install.sh is deployment tooling only.
#   - Runtime Main starts subsystems and gets out of the way.
#   - Dispatchers own workflow.
#   - Managers do work.
#   - Event services connect subsystems to the event bus only.
#
# ============================================================

set -euo pipefail

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
VENV_DIR="$REPO_ROOT/.venv"

NODE_REQUIREMENTS_FILE="$REPO_ROOT/requirements_node_beta_v2.txt"
NODE_WIZARD="$REPO_ROOT/tools/install/install_node.py"

# ------------------------------------------------------------
# Display Helpers
# ------------------------------------------------------------

print_header() {
    echo
    echo "============================================================"
    echo "$1"
    echo "============================================================"
    echo
}

print_step() {
    echo
    echo "[INSTALL] $1"
}

print_warn() {
    echo
    echo "[WARN] $1"
}

print_error() {
    echo
    echo "[ERROR] $1" >&2
}

pause_for_enter() {
    echo
    read -r -p "Press Enter to continue..."
}

# ------------------------------------------------------------
# Safety Checks
# ------------------------------------------------------------

require_repo_root() {
    if [[ ! -f "$REPO_ROOT/install.sh" ]]; then
        print_error "install.sh could not verify the repository root."
        exit 1
    fi

    if [[ ! -d "$REPO_ROOT/node" ]]; then
        print_error "Expected node/ directory was not found."
        print_error "Run this installer from the EnviroPulse EP_V2 repository."
        exit 1
    fi
}

require_linux() {
    if [[ "$(uname -s)" != "Linux" ]]; then
        print_error "This installer is intended to run on Linux nodes."
        print_error "Edit and commit it from your PC, but run it on the Raspberry Pi."
        exit 1
    fi
}

require_apt() {
    if ! command -v apt-get >/dev/null 2>&1; then
        print_error "apt-get was not found. This installer currently supports Debian/Raspberry Pi OS style systems."
        exit 1
    fi
}

confirm_action() {
    local prompt="$1"
    local answer=""

    read -r -p "$prompt [y/N]: " answer

    case "$answer" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# ------------------------------------------------------------
# Apt Packages
# ------------------------------------------------------------

install_node_apt_packages() {
    print_step "Installing node apt packages"

    local packages=(
        python3
        python3-venv
        python3-pip
        git
        curl
        ffmpeg
        libsndfile1
        portaudio19-dev
        libopenblas-dev
        liblapack-dev
        i2c-tools
        alsa-utils
        pps-tools
        gpiod
    )

    echo "Packages:"
    printf '  - %s\n' "${packages[@]}"

    if confirm_action "Install/update apt packages now?"; then
        sudo apt-get update
        sudo apt-get install -y "${packages[@]}"
    else
        print_warn "Skipped apt package installation."
    fi
}

# ------------------------------------------------------------
# Python Environment
# ------------------------------------------------------------

create_venv() {
    print_step "Preparing Python virtual environment"

    if [[ -d "$VENV_DIR" ]]; then
        echo "Virtual environment already exists:"
        echo "  $VENV_DIR"
        return
    fi

    python3 -m venv "$VENV_DIR"

    echo "Created virtual environment:"
    echo "  $VENV_DIR"
}

upgrade_pip_tools() {
    print_step "Upgrading pip, setuptools, and wheel"

    "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
}

install_node_requirements() {
    print_step "Installing node Python requirements"

    if [[ ! -f "$NODE_REQUIREMENTS_FILE" ]]; then
        print_warn "Requirements file not found:"
        print_warn "$NODE_REQUIREMENTS_FILE"
        return
    fi

    "$VENV_DIR/bin/python" -m pip install -r "$NODE_REQUIREMENTS_FILE"

    print_step "Installing explicit current node runtime packages"

    # Current working BirdNET path uses birdnetlib.
    # This stays explicit until node 04 requirements are rebuilt cleanly.
    "$VENV_DIR/bin/python" -m pip install birdnetlib
}

# ------------------------------------------------------------
# Node Wizard
# ------------------------------------------------------------

run_node_wizard_if_available() {
    print_step "Checking for node install wizard"

    if [[ -f "$NODE_WIZARD" ]]; then
        "$VENV_DIR/bin/python" "$NODE_WIZARD"
    else
        print_warn "Node wizard does not exist yet:"
        print_warn "$NODE_WIZARD"
        print_warn "This is expected for the first installer checkpoint."
    fi
}

# ------------------------------------------------------------
# Install Paths
# ------------------------------------------------------------

install_node() {
    print_header "EnviroPulse Node Install"

    echo "Repository root:"
    echo "  $REPO_ROOT"
    echo
    echo "Virtual environment:"
    echo "  $VENV_DIR"
    echo
    echo "Requirements:"
    echo "  $NODE_REQUIREMENTS_FILE"
    echo

    pause_for_enter

    require_linux
    require_apt

    install_node_apt_packages
    create_venv
    upgrade_pip_tools
    install_node_requirements
    run_node_wizard_if_available

    print_header "Node Install Checkpoint Complete"

    echo "Next likely commands:"
    echo
    echo "  cd $REPO_ROOT"
    echo "  source .venv/bin/activate"
    echo "  python3 node/node_main.py"
    echo
}

install_server() {
    print_header "EnviroPulse Server Install"

    print_warn "Server installer is not implemented yet."
    print_warn "Today we are building the node path first."
}

install_gui() {
    print_header "EnviroPulse GUI Install"

    print_warn "GUI installer is not implemented yet."
    print_warn "Today we are building the node path first."
}

# ------------------------------------------------------------
# Menu
# ------------------------------------------------------------

show_menu() {
    print_header "EnviroPulse V2 Installer"

    echo "Choose install type:"
    echo
    echo "  1) Node"
    echo "  2) Server"
    echo "  3) GUI"
    echo "  q) Quit"
    echo
}

main() {
    require_repo_root

    cd "$REPO_ROOT"

    while true; do
        show_menu

        local choice=""
        read -r -p "Selection: " choice

        case "$choice" in
            1|node|Node|NODE)
                install_node
                break
                ;;
            2|server|Server|SERVER)
                install_server
                break
                ;;
            3|gui|GUI|Gui)
                install_gui
                break
                ;;
            q|Q|quit|Quit|QUIT)
                echo "Installer exited."
                exit 0
                ;;
            *)
                print_warn "Unknown selection: $choice"
                ;;
        esac
    done
}

main "$@"