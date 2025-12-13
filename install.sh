#!/bin/bash
echo "Installing PeppyMeter Screensaver plugin"

# Get Volumio architecture - direct match to bin/lib/packages folders
ARCH=$(cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d 'VOLUMIO_ARCH="')

if [ -z "$ARCH" ]; then
  echo "ERROR: Could not detect Volumio architecture"
  exit 1
fi

echo "Detected architecture: $ARCH"

PLUGIN_DIR="/data/plugins/user_interface/peppy_screensaver"
DATA_DIR="/data/INTERNAL/peppy_screensaver"
BIN_SOURCE="$PLUGIN_DIR/bin/$ARCH"
LIB_SOURCE="$PLUGIN_DIR/lib/$ARCH"
PKG_SOURCE="$PLUGIN_DIR/packages/$ARCH"

# Verify architecture is supported
if [ ! -d "$BIN_SOURCE" ]; then
  echo "ERROR: Architecture $ARCH not supported"
  echo "Available: arm, armv7, armv8, x64"
  exit 1
fi

echo "Using binaries from: $BIN_SOURCE"
echo "Using libraries from: $LIB_SOURCE"
echo "Using packages from: $PKG_SOURCE"

# =============================================================================
# INSTALL: System dependencies
# =============================================================================
echo ""
echo "Installing system dependencies..."

# Check and install runtime dependencies
NEEDED_PKGS=""
for pkg in libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libfftw3-double3; do
  if ! dpkg -s "$pkg" &> /dev/null; then
    NEEDED_PKGS="$NEEDED_PKGS $pkg"
  else
    echo "$pkg already installed"
  fi
done

if [ -n "$NEEDED_PKGS" ]; then
  echo "Installing:$NEEDED_PKGS"
  apt-get update
  apt-get install -y $NEEDED_PKGS
else
  echo "All runtime dependencies already present"
fi

echo "System dependencies installed"

# =============================================================================
# INSTALL: peppyalsa library
# =============================================================================
echo ""
echo "Installing peppyalsa library..."

if [ ! -f "$LIB_SOURCE/libpeppyalsa.so" ]; then
  echo "ERROR: libpeppyalsa.so not found in $LIB_SOURCE"
  exit 1
fi

# Create symlink for ALSA to find the library
# ALSA config points to lib/libpeppyalsa.so, symlink to arch-specific location
ln -sf "$LIB_SOURCE/libpeppyalsa.so" "$PLUGIN_DIR/lib/libpeppyalsa.so"
echo "Created symlink: $PLUGIN_DIR/lib/libpeppyalsa.so -> $LIB_SOURCE/libpeppyalsa.so"

# =============================================================================
# INSTALL: peppyalsa-client
# =============================================================================
echo ""
echo "Installing peppyalsa-client..."

if [ ! -f "$BIN_SOURCE/peppyalsa-client" ]; then
  echo "ERROR: peppyalsa-client not found in $BIN_SOURCE"
  exit 1
fi

chmod +x "$BIN_SOURCE/peppyalsa-client"
echo "peppyalsa-client ready in: $BIN_SOURCE"

# =============================================================================
# INSTALL: Python packages
# =============================================================================
echo ""
echo "Installing Python packages..."

PYTHON_DIR="$LIB_SOURCE/python"
mkdir -p "$PYTHON_DIR"

if [ -f "$PKG_SOURCE/peppy-python-packages.tar.gz" ]; then
  tar -xzf "$PKG_SOURCE/peppy-python-packages.tar.gz" -C "$PYTHON_DIR/"
  chown -R volumio:volumio "$PYTHON_DIR"
  echo "Python packages installed to: $PYTHON_DIR"
else
  echo "ERROR: peppy-python-packages.tar.gz not found in $PKG_SOURCE"
  exit 1
fi

# =============================================================================
# INSTALL: PeppyMeter from GitHub
# =============================================================================
echo ""
echo "Installing PeppyMeter..."

PEPPYMETER_DIR="$PLUGIN_DIR/screensaver/peppymeter"

if [ ! -d "$PEPPYMETER_DIR" ]; then
  mkdir -p "$PLUGIN_DIR/screensaver"
  git clone --depth 1 https://github.com/project-owner/PeppyMeter.git "$PEPPYMETER_DIR"
else
  echo "PeppyMeter already installed"
fi

# =============================================================================
# INSTALL: PeppySpectrum from GitHub
# =============================================================================
echo ""
echo "Installing PeppySpectrum..."

PEPPYSPECTRUM_DIR="$PLUGIN_DIR/screensaver/spectrum"

if [ ! -d "$PEPPYSPECTRUM_DIR" ]; then
  git clone --depth 1 https://github.com/project-owner/PeppySpectrum.git "$PEPPYSPECTRUM_DIR"
else
  echo "PeppySpectrum already installed"
fi

# =============================================================================
# SETUP: Volumio integration files
# =============================================================================
echo ""
echo "Setting up Volumio integration..."

cp -rf "$PLUGIN_DIR/volumio_peppymeter/"* "$PLUGIN_DIR/screensaver/"
rm -rf "$PLUGIN_DIR/volumio_peppymeter"
chmod +x "$PLUGIN_DIR/run_peppymeter.sh"

# =============================================================================
# SETUP: Templates
# =============================================================================
echo ""
echo "Setting up templates..."

mkdir -p "$DATA_DIR"

# PeppyMeter templates
if [ -d "$PLUGIN_DIR/templates" ]; then
  cp -rf "$PLUGIN_DIR/templates" "$DATA_DIR/"
  rm -rf "$PLUGIN_DIR/templates"
fi
cp -rf "$PEPPYMETER_DIR"/*0x* "$DATA_DIR/templates/" 2>/dev/null || true
rm -rf "$PEPPYMETER_DIR"/*0x* 2>/dev/null || true

# PeppySpectrum templates
if [ -d "$PLUGIN_DIR/templates_spectrum" ]; then
  cp -rf "$PLUGIN_DIR/templates_spectrum" "$DATA_DIR/"
  rm -rf "$PLUGIN_DIR/templates_spectrum"
fi
cp -rf "$PEPPYSPECTRUM_DIR"/*0x* "$DATA_DIR/templates_spectrum/" 2>/dev/null || true
rm -rf "$PEPPYSPECTRUM_DIR"/*0x* 2>/dev/null || true

# Permissions
chmod -R 755 "$DATA_DIR"
chown -R volumio:volumio "$DATA_DIR"
chmod -R 755 "$PLUGIN_DIR/screensaver"
chown -R volumio:volumio "$PLUGIN_DIR/screensaver"
chmod -R 755 "$PLUGIN_DIR/lib"
chown -R volumio:volumio "$PLUGIN_DIR/lib"
chmod -R 755 "$PLUGIN_DIR/bin"
chown -R volumio:volumio "$PLUGIN_DIR/bin"

# =============================================================================
# SETUP: Prevent segmentation fault on Pi (arm/armv7)
# =============================================================================
if [ "$ARCH" = "arm" ] || [ "$ARCH" = "armv7" ]; then
  echo ""
  echo "Applying Pi-specific meter.x fixes..."
  
  changeSection() {
    ret=$(sed -nr "/^\[$1\]/ { :l /^meter.x[ ]*=/ { s/[^=]*=[ ]*//; p; q;}; n; b l;}" $2)
    if [ ! $ret ]; then 
      sed -i "/^\[$1\]/a\meter.x = 1" $2
    fi
  }
  
  changeINI() {
    sed -i 's|meter.x.*|meter.x = 1|g' $1
    sect=$(grep "^\[" $1 | sed 's,^\[,,' | sed 's,\],,')
    for i in $sect; do
      changeSection "$i" "$1"
    done
  }
  
  for ini in "$DATA_DIR/templates/320x240/meters.txt" "$DATA_DIR/templates/480x320/meters.txt"; do
    if [ -f "$ini" ]; then
      changeINI "$ini"
    fi
  done
fi

# =============================================================================
# CONFIGURE: PeppyMeter
# =============================================================================
echo ""
echo "Configuring PeppyMeter for Volumio..."

CFG="$PEPPYMETER_DIR/config.txt"
TOTAL_MEM=$(free -m | grep Mem: | awk '{print $2}')

if [ -f "$CFG" ]; then
  # Section current
  sed -i 's|random.meter.interval.*|random.meter.interval = 60|g' $CFG
  sed -i 's|exit.on.touch.*|exit.on.touch = True|g' $CFG
  sed -i 's|stop.display.on.touch.*|stop.display.on.touch = True|g' $CFG
  sed -i "s|base.folder.*|base.folder = $DATA_DIR/templates|g" $CFG
  
  if [ $TOTAL_MEM -lt 3000 ]; then
    sed -i 's|use.cache.*|use.cache = False|g' $CFG
  else
    sed -i 's|use.cache.*|use.cache = True|g' $CFG
  fi

  # Add volumio entries if not present
  if ! grep -q 'volumio entries' $CFG; then
    sed -i '/\[sdl.env\]/i\
# --- volumio entries -------\
random.change.title = True\
color.depth = 24\
position.type = center\
position.x = 0\
position.y = 0\
start.animation = True\
font.path = /volumio/http/www3/app/themes/volumio3/assets/variants/volumio/fonts\
font.light = /Lato-Light.ttf\
font.regular = /Lato-Regular.ttf\
font.bold = /Lato-Bold.ttf\
' $CFG
  fi

  # Section sdl.env
  sed -i 's|framebuffer.device.*|framebuffer.device = /dev/fb0|g' $CFG
  sed -i 's|mouse.device.*|mouse.device = /dev/input/event0|g' $CFG
  sed -i 's|double.buffer.*|double.buffer = True|g' $CFG
  sed -i 's|no.frame.*|no.frame = True|g' $CFG
  
  # Section data.source
  sed -i 's|pipe.name.*|pipe.name = /tmp/myfifo|g' $CFG
  sed -i 's|smooth.buffer.size.*|smooth.buffer.size = 8|g' $CFG
fi

# =============================================================================
# CONFIGURE: PeppySpectrum
# =============================================================================
echo ""
echo "Configuring PeppySpectrum for Volumio..."

CFG="$PEPPYSPECTRUM_DIR/config.txt"

if [ -f "$CFG" ]; then
  sed -i "s|base.folder.*|base.folder = $DATA_DIR/templates_spectrum|g" $CFG
  sed -i 's|exit.on.touch.*|exit.on.touch = True|g' $CFG
  sed -i 's|pipe.name.*|pipe.name = /tmp/myfifosa|g' $CFG
  sed -i 's|size.*|size = 20|g' $CFG
  sed -i 's|update.ui.interval.*|update.ui.interval = 0.04|g' $CFG
  sed -i 's|framebuffer.device.*|framebuffer.device = /dev/fb0|g' $CFG
  sed -i 's|mouse.device.*|mouse.device = /dev/input/event0|g' $CFG
  sed -i 's|double.buffer.*|double.buffer = False|g' $CFG
  sed -i 's|no.frame.*|no.frame = True|g' $CFG
fi

# =============================================================================
# CLEANUP
# =============================================================================
echo ""
echo "Cleaning up..."

# Remove packages directory after extraction
rm -rf "$PLUGIN_DIR/packages"

echo ""
echo "=========================================="
echo "PeppyMeter Screensaver installation complete"
echo "=========================================="
echo "Architecture: $ARCH"
echo ""
echo "Library: $PLUGIN_DIR/lib/libpeppyalsa.so"
echo "Python packages: $LIB_SOURCE/python"
echo "Templates: $DATA_DIR"
echo "=========================================="
echo ""

echo "plugininstallend"
