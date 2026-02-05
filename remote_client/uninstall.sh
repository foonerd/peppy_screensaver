#!/bin/bash
#
# PeppyMeter Remote Client Uninstaller
#
# Removes the PeppyMeter Remote Client installation.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "========================================"
echo " PeppyMeter Remote Client Uninstaller"
echo "========================================"
echo ""
echo "This will remove: $SCRIPT_DIR"
echo ""

# Confirm
read -p "Are you sure you want to uninstall? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Uninstalling..."

# =============================================================================
# Unmount SMB if mounted
# =============================================================================
if mountpoint -q "$SCRIPT_DIR/mnt" 2>/dev/null; then
    echo "  Unmounting SMB share..."
    sudo umount "$SCRIPT_DIR/mnt" 2>/dev/null || true
fi

# =============================================================================
# Remove sudoers entry
# =============================================================================
SUDOERS_FILE="/etc/sudoers.d/peppy_remote"
if [ -f "$SUDOERS_FILE" ]; then
    echo "  Removing sudoers entry..."
    sudo rm -f "$SUDOERS_FILE"
fi

# =============================================================================
# Remove desktop shortcut
# =============================================================================
DESKTOP_FILE="$HOME/.local/share/applications/peppy-remote.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    echo "  Removing desktop shortcut..."
    rm -f "$DESKTOP_FILE"
fi

# =============================================================================
# Remove installation directory
# =============================================================================
echo "  Removing installation directory..."

# We need to be careful here - don't delete if we're not in the install dir
if [ -f "$SCRIPT_DIR/peppy_remote.py" ] && [ -f "$SCRIPT_DIR/peppy_remote" ]; then
    cd "$HOME"  # Move out of the directory first
    rm -rf "$SCRIPT_DIR"
    echo "  Removed: $SCRIPT_DIR"
else
    echo "  ERROR: This doesn't look like a valid installation directory"
    echo "  Refusing to delete for safety"
    exit 1
fi

echo ""
echo "========================================"
echo " Uninstall complete!"
echo "========================================"
echo ""
echo "System packages (python3, SDL2, etc.) were NOT removed."
echo "Remove them manually if no longer needed:"
echo "  sudo apt remove python3-venv libsdl2-2.0-0 cifs-utils"
echo ""
