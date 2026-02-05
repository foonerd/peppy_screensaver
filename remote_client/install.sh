#!/bin/bash
#
# PeppyMeter Remote Client Installer
#
# One-liner installation from GitHub:
#   curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash
#
# Or with server pre-configured:
#   curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash -s -- --server hanger
#
# This installs PeppyMeter Remote Client to ~/peppy_remote/
# Everything is self-contained in that folder.
#

set -e

# =============================================================================
# Configuration
# =============================================================================
REPO_URL="https://github.com/foonerd/peppy_screensaver"
REPO_BRANCH="experimental-refactor"
PEPPYMETER_REPO="https://github.com/project-owner/PeppyMeter"
INSTALL_DIR="${PEPPY_REMOTE_DIR:-$HOME/peppy_remote}"
SERVER_HOST=""

# =============================================================================
# Parse arguments
# =============================================================================
while [[ $# -gt 0 ]]; do
    case $1 in
        --server|-s)
            SERVER_HOST="$2"
            shift 2
            ;;
        --dir|-d)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --help|-h)
            echo "PeppyMeter Remote Client Installer"
            echo ""
            echo "Usage:"
            echo "  curl -sSL <url>/install.sh | bash"
            echo "  curl -sSL <url>/install.sh | bash -s -- [options]"
            echo ""
            echo "Options:"
            echo "  --server, -s <host>   Pre-configure server hostname/IP"
            echo "  --dir, -d <path>      Install directory (default: ~/peppy_remote)"
            echo "  --help, -h            Show this help"
            echo ""
            echo "Environment variables:"
            echo "  PEPPY_REMOTE_DIR      Override install directory"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# =============================================================================
# Banner
# =============================================================================
echo ""
echo "========================================"
echo " PeppyMeter Remote Client Installer"
echo "========================================"
echo ""
echo "Install directory: $INSTALL_DIR"
if [ -n "$SERVER_HOST" ]; then
    echo "Server: $SERVER_HOST"
fi
echo ""

# =============================================================================
# Check for existing installation
# =============================================================================
if [ -d "$INSTALL_DIR" ]; then
    echo "Existing installation found at $INSTALL_DIR"
    read -p "Remove and reinstall? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing installation..."
        # Unmount if mounted
        if mountpoint -q "$INSTALL_DIR/mnt" 2>/dev/null; then
            sudo umount "$INSTALL_DIR/mnt" 2>/dev/null || true
        fi
        rm -rf "$INSTALL_DIR"
    else
        echo "Cancelled."
        exit 0
    fi
fi

# =============================================================================
# Detect system
# =============================================================================
echo "Detecting system..."

if ! command -v dpkg &> /dev/null; then
    echo "ERROR: This installer requires a Debian-based system (dpkg not found)"
    exit 1
fi

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
echo "  Architecture: $ARCH"

# =============================================================================
# Install system dependencies
# =============================================================================
echo ""
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

# =============================================================================
# Create install directory
# =============================================================================
echo ""
echo "Creating installation directory..."

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/mnt"
cd "$INSTALL_DIR"

# =============================================================================
# Download client scripts from repo
# =============================================================================
echo ""
echo "Downloading client scripts..."

# Download main client script
curl -sSL "$REPO_URL/raw/$REPO_BRANCH/remote_client/peppy_remote.py" -o "$INSTALL_DIR/peppy_remote.py"
chmod +x "$INSTALL_DIR/peppy_remote.py"

# Download uninstall script
curl -sSL "$REPO_URL/raw/$REPO_BRANCH/remote_client/uninstall.sh" -o "$INSTALL_DIR/uninstall.sh"
chmod +x "$INSTALL_DIR/uninstall.sh"

echo "  Downloaded: peppy_remote.py"
echo "  Downloaded: uninstall.sh"

# =============================================================================
# Create screensaver directory structure (mirrors Volumio plugin layout)
# =============================================================================
echo ""
echo "Creating screensaver directory structure..."

mkdir -p "$INSTALL_DIR/screensaver"

# =============================================================================
# Clone PeppyMeter (base rendering engine)
# =============================================================================
echo ""
echo "Cloning PeppyMeter (base engine)..."

PEPPYMETER_DIR="$INSTALL_DIR/screensaver/peppymeter"

if [ -d "$PEPPYMETER_DIR" ]; then
    echo "  Updating existing PeppyMeter..."
    cd "$PEPPYMETER_DIR"
    git pull --ff-only 2>/dev/null || echo "  (Update failed, using existing)"
    cd "$INSTALL_DIR"
else
    git clone --depth 1 "$PEPPYMETER_REPO" "$PEPPYMETER_DIR"
fi

# =============================================================================
# Clone PeppySpectrum (spectrum analyzer engine)
# =============================================================================
echo ""
echo "Cloning PeppySpectrum (spectrum engine)..."

SPECTRUM_REPO="https://github.com/project-owner/PeppySpectrum"
SPECTRUM_DIR="$INSTALL_DIR/screensaver/spectrum"

if [ -d "$SPECTRUM_DIR" ]; then
    echo "  Updating existing PeppySpectrum..."
    cd "$SPECTRUM_DIR"
    git pull --ff-only 2>/dev/null || echo "  (Update failed, using existing)"
    cd "$INSTALL_DIR"
else
    git clone --depth 1 "$SPECTRUM_REPO" "$SPECTRUM_DIR"
fi

# =============================================================================
# Download Volumio custom handlers (turntable, cassette, compositor, etc.)
# =============================================================================
echo ""
echo "Downloading Volumio custom handlers..."

VOLUMIO_FILES=(
    "volumio_peppymeter.py"
    "volumio_configfileparser.py"
    "volumio_turntable.py"
    "volumio_cassette.py"
    "volumio_compositor.py"
    "volumio_indicators.py"
    "volumio_spectrum.py"
    "volumio_basic.py"
    "screensaverspectrum.py"
)

for file in "${VOLUMIO_FILES[@]}"; do
    echo "  Downloading: $file"
    curl -sSL "$REPO_URL/raw/$REPO_BRANCH/volumio_peppymeter/$file" -o "$INSTALL_DIR/screensaver/$file"
done

# Download fonts directory
echo "  Downloading fonts..."
mkdir -p "$INSTALL_DIR/screensaver/fonts"
for font in DSEG7Classic-Bold.ttf DSEG7Classic-BoldItalic.ttf DSEG7Classic-Italic.ttf DSEG7Classic-Regular.ttf; do
    curl -sSL "$REPO_URL/raw/$REPO_BRANCH/volumio_peppymeter/fonts/$font" -o "$INSTALL_DIR/screensaver/fonts/$font"
done

# Download format-icons directory
echo "  Downloading format icons..."
mkdir -p "$INSTALL_DIR/screensaver/format-icons"
for icon in cd.svg dab.svg fm.svg qobuz.svg radio.svg tidal.svg; do
    curl -sSL "$REPO_URL/raw/$REPO_BRANCH/volumio_peppymeter/format-icons/$icon" -o "$INSTALL_DIR/screensaver/format-icons/$icon"
done

echo "  All Volumio handlers downloaded"

# Note: No symlink at root level - imports use screensaver/peppymeter path directly

# =============================================================================
# Create Python virtual environment
# =============================================================================
echo ""
echo "Setting up Python environment..."

if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi

source "$INSTALL_DIR/venv/bin/activate"

echo "  Installing Python packages..."
pip install --upgrade pip wheel > /dev/null 2>&1
# Install all packages matching Volumio plugin's bundled Python packages
pip install \
    pillow \
    pygame \
    cairosvg \
    cssselect2 \
    tinycss2 \
    defusedxml \
    webencodings \
    python-socketio[client] \
    python-engineio \
    bidict \
    requests \
    certifi \
    charset-normalizer \
    idna \
    urllib3 \
    websocket-client \
    mss \
    pyscreenshot \
    easyprocess \
    entrypoint2 \
    > /dev/null 2>&1

deactivate

# =============================================================================
# Create launcher script
# =============================================================================
echo ""
echo "Creating launcher..."

cat > "$INSTALL_DIR/peppy_remote" << 'LAUNCHER_EOF'
#!/bin/bash
# PeppyMeter Remote Client Launcher

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Set PYTHONPATH to include:
# 1. screensaver/ - for volumio_*.py modules
# 2. screensaver/peppymeter/ - for base PeppyMeter modules (configfileparser, etc.)
# 3. screensaver/spectrum/ - for PeppySpectrum modules (spectrum.py, spectrumutil.py, etc.)
export PYTHONPATH="$SCRIPT_DIR/screensaver:$SCRIPT_DIR/screensaver/peppymeter:$SCRIPT_DIR/screensaver/spectrum:$PYTHONPATH"

# SDL environment for desktop display (not framebuffer)
# Must be set BEFORE pygame import - unset lets SDL auto-detect (x11, wayland)
unset SDL_VIDEODRIVER
unset SDL_FBDEV
unset SDL_MOUSEDEV
unset SDL_MOUSEDRV
unset SDL_NOMOUSE

# Ensure DISPLAY is set for X11
if [ -z "$DISPLAY" ]; then
    export DISPLAY=:0
fi

# Run client
python3 "$SCRIPT_DIR/peppy_remote.py" "$@"
LAUNCHER_EOF

chmod +x "$INSTALL_DIR/peppy_remote"

# =============================================================================
# Create client config
# =============================================================================
echo ""
echo "Creating configuration..."

if [ -n "$SERVER_HOST" ]; then
    cat > "$INSTALL_DIR/config.json" << EOF
{
  "server": {
    "host": "$SERVER_HOST",
    "level_port": 5580,
    "volumio_port": 3000,
    "discovery_port": 5579,
    "discovery_timeout": 10
  },
  "display": {
    "windowed": true,
    "position": null,
    "fullscreen": false,
    "monitor": 0
  },
  "templates": {
    "use_smb": true,
    "local_path": null
  }
}
EOF
    echo "  Server pre-configured: $SERVER_HOST"
else
    cat > "$INSTALL_DIR/config.json" << EOF
{
  "server": {
    "host": null,
    "level_port": 5580,
    "volumio_port": 3000,
    "discovery_port": 5579,
    "discovery_timeout": 10
  },
  "display": {
    "windowed": true,
    "position": null,
    "fullscreen": false,
    "monitor": 0
  },
  "templates": {
    "use_smb": true,
    "local_path": null
  }
}
EOF
    echo "  Auto-discovery enabled (default: windowed mode)"
fi

# =============================================================================
# Setup sudoers for mount (optional)
# =============================================================================
echo ""
echo "Setting up passwordless mount..."

SUDOERS_FILE="/etc/sudoers.d/peppy_remote"
SUDOERS_LINE="$USER ALL=(ALL) NOPASSWD: /bin/mount, /bin/umount"

if [ -f "$SUDOERS_FILE" ]; then
    echo "  Sudoers entry already exists"
else
    echo "  Creating sudoers entry for mount/umount..."
    echo "$SUDOERS_LINE" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    echo "  Created: $SUDOERS_FILE"
fi

# =============================================================================
# Create desktop shortcut (if on desktop system)
# =============================================================================
if [ -d "$HOME/Desktop" ] || [ -d "$HOME/.local/share/applications" ]; then
    echo ""
    echo "Creating desktop shortcut..."
    
    DESKTOP_FILE="[Desktop Entry]
Type=Application
Name=PeppyMeter Remote
Comment=Remote VU meter display
Exec=$INSTALL_DIR/peppy_remote
Icon=audio-x-generic
Terminal=true
Categories=AudioVideo;Audio;
"
    
    if [ -d "$HOME/.local/share/applications" ]; then
        echo "$DESKTOP_FILE" > "$HOME/.local/share/applications/peppy-remote.desktop"
        echo "  Created: ~/.local/share/applications/peppy-remote.desktop"
    fi
fi

# =============================================================================
# Done
# =============================================================================
echo ""
echo "========================================"
echo " Installation complete!"
echo "========================================"
echo ""
echo "To run PeppyMeter Remote Client:"
echo ""
echo "  $INSTALL_DIR/peppy_remote                    # Auto-discover server"
echo "  $INSTALL_DIR/peppy_remote --server hanger    # Connect to specific server"
echo "  $INSTALL_DIR/peppy_remote --config           # Interactive configuration"
echo "  $INSTALL_DIR/peppy_remote --test             # Simple test display"
echo ""
echo "Display options:"
echo "  --windowed     Movable window with title bar (default)"
echo "  --fullscreen   Fullscreen mode"
echo ""
echo "To configure settings interactively:"
echo "  $INSTALL_DIR/peppy_remote --config"
echo ""
echo "To uninstall:"
echo "  $INSTALL_DIR/uninstall.sh"
echo ""
