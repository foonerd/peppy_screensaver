#!/bin/bash
#
# PeppyMeter Remote Client Installer
#
# Installs dependencies and sets up PeppyMeter as a remote display client.
# Can run on any Debian-based system (Ubuntu, Raspberry Pi OS, Volumio, etc.)
#
# PORTABLE: Everything is installed in the current directory.
# Just copy this folder to another system and run install_client.sh again.
#
# Usage:
#   ./install_client.sh                    # Interactive install
#   ./install_client.sh --server hanger    # Pre-configure server
#

set -e

echo "========================================"
echo "PeppyMeter Remote Client Installer"
echo "========================================"
echo ""

# =============================================================================
# Parse arguments
# =============================================================================
SERVER_HOST=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --server|-s)
            SERVER_HOST="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--server <hostname_or_ip>]"
            echo ""
            echo "Options:"
            echo "  --server, -s    Pre-configure the PeppyMeter server hostname/IP"
            echo "  --help, -h      Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Detect system
# =============================================================================
echo "Detecting system..."

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
echo "  Detected architecture: $ARCH"

# Map architectures
case "$ARCH" in
    amd64|x86_64|x64)
        ARCH_NORMALIZED="x64"
        ;;
    arm64|aarch64|armv8)
        ARCH_NORMALIZED="armv8"
        ;;
    armhf|armv7l|armv7)
        ARCH_NORMALIZED="armv7"
        ;;
    armel|arm)
        ARCH_NORMALIZED="arm"
        ;;
    *)
        echo "WARNING: Unknown architecture '$ARCH', assuming x64"
        ARCH_NORMALIZED="x64"
        ;;
esac

echo "  Normalized: $ARCH_NORMALIZED"

# =============================================================================
# Set paths - EVERYTHING in current directory (portable)
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR"
DATA_DIR="$SCRIPT_DIR/data"
RUN_USER="$USER"

echo "  Install directory: $INSTALL_DIR"
echo "  Data directory: $DATA_DIR"
echo ""

# =============================================================================
# Install system dependencies
# =============================================================================
echo "Installing system dependencies..."
echo "(You may be prompted for sudo password)"
echo ""

NEEDED_PKGS=""

# Check each package
for pkg in python3 python3-pip python3-venv git cifs-utils \
           libsdl2-2.0-0 libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0; do
    if ! dpkg -s "$pkg" &> /dev/null; then
        NEEDED_PKGS="$NEEDED_PKGS $pkg"
    fi
done

if [ -n "$NEEDED_PKGS" ]; then
    echo "Installing:$NEEDED_PKGS"
    sudo apt-get update
    sudo apt-get install -y $NEEDED_PKGS
else
    echo "All system dependencies already installed"
fi

echo ""

# =============================================================================
# Create directories
# =============================================================================
echo "Creating directories..."

mkdir -p "$DATA_DIR/templates"
mkdir -p "$INSTALL_DIR/screensaver"
mkdir -p "$INSTALL_DIR/mnt"  # Local mount point (portable)

echo ""

# =============================================================================
# Clone/update PeppyMeter
# =============================================================================
echo "Installing PeppyMeter..."

PEPPYMETER_DIR="$INSTALL_DIR/screensaver/peppymeter"

if [ -d "$PEPPYMETER_DIR/.git" ]; then
    echo "  Updating existing PeppyMeter installation..."
    cd "$PEPPYMETER_DIR"
    git pull --ff-only || echo "  (Update failed, using existing version)"
    cd - > /dev/null
else
    echo "  Cloning PeppyMeter repository..."
    rm -rf "$PEPPYMETER_DIR"
    git clone --depth 1 https://github.com/foonerd/PeppyMeter.git "$PEPPYMETER_DIR"
fi

echo ""

# =============================================================================
# Install Python dependencies
# =============================================================================
echo "Installing Python dependencies..."

# Create virtual environment if it doesn't exist
VENV_DIR="$INSTALL_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install packages
source "$VENV_DIR/bin/activate"

echo "  Installing Python packages..."
pip install --upgrade pip wheel > /dev/null
pip install pygame python-socketio[client] websocket-client > /dev/null

deactivate

echo ""

# =============================================================================
# Verify client scripts exist
# =============================================================================
echo "Checking client scripts..."

if [ -f "$INSTALL_DIR/run_peppy_remote.py" ]; then
    chmod +x "$INSTALL_DIR/run_peppy_remote.py"
    echo "  Found: run_peppy_remote.py"
else
    echo "  WARNING: run_peppy_remote.py not found in $INSTALL_DIR"
    echo "           Make sure it's in the same folder as install_client.sh"
fi

echo ""

# =============================================================================
# Create launcher script
# =============================================================================
echo "Creating launcher script..."

LAUNCHER="$INSTALL_DIR/peppy_remote"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/bin/bash
# PeppyMeter Remote Client Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Set PYTHONPATH to include PeppyMeter
export PYTHONPATH="$SCRIPT_DIR/screensaver/peppymeter:$SCRIPT_DIR/screensaver:$PYTHONPATH"

# Run the client
python3 "$SCRIPT_DIR/run_peppy_remote.py" "$@"
LAUNCHER_EOF

chmod +x "$LAUNCHER"

echo ""

# =============================================================================
# Create client config
# =============================================================================
echo "Creating client configuration..."

CLIENT_CONFIG="$INSTALL_DIR/client_config.json"

if [ -n "$SERVER_HOST" ]; then
    cat > "$CLIENT_CONFIG" << EOF
{
    "server": "$SERVER_HOST",
    "level_port": 5580,
    "volumio_port": 3000,
    "auto_discover": false,
    "mount_smb": true,
    "smb_mount_point": "$INSTALL_DIR/mnt"
}
EOF
    echo "  Server pre-configured: $SERVER_HOST"
else
    cat > "$CLIENT_CONFIG" << EOF
{
    "server": null,
    "level_port": 5580,
    "volumio_port": 3000,
    "auto_discover": true,
    "mount_smb": true,
    "smb_mount_point": "$INSTALL_DIR/mnt"
}
EOF
    echo "  Auto-discovery enabled (no server specified)"
fi

echo ""

# =============================================================================
# Done
# =============================================================================
echo "========================================"
echo "Installation complete!"
echo "========================================"
echo ""
echo "This folder is now PORTABLE - copy it to any system and run:"
echo "  ./install_client.sh    # to set up dependencies on new system"
echo ""
echo "To run PeppyMeter Remote Client:"
echo ""
echo "  ./peppy_remote                    # Auto-discover server"
echo "  ./peppy_remote --server hanger    # Connect to specific server"
echo "  ./peppy_remote --test             # Simple test display"
echo ""
echo "The client will:"
echo "  1. Discover or connect to PeppyMeter server"
echo "  2. Mount templates via SMB from server"
echo "  3. Receive audio levels and metadata"
echo "  4. Display the visualization"
echo ""

if [ -z "$SERVER_HOST" ]; then
    echo "TIP: Run the installer with --server to pre-configure:"
    echo "  ./install_client.sh --server <hostname_or_ip>"
    echo ""
fi

echo "For SMB mounting, you may need to add your user to sudoers for mount:"
echo "  echo '$USER ALL=(ALL) NOPASSWD: /bin/mount, /bin/umount' | sudo tee /etc/sudoers.d/peppy_mount"
echo ""
