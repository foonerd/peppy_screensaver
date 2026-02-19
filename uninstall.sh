#!/bin/bash
echo "Uninstalling PeppyMeter Screensaver plugin"

PLUGIN_DIR="/data/plugins/user_interface/peppy_screensaver"

# Unmount MPD template if mounted
MPD="/volumio/app/plugins/music_service/mpd/mpd.conf.tmpl"
if df "$MPD" 2>/dev/null | grep -q "$MPD"; then
  echo "Unmounting MPD template..."
  sudo umount "$MPD"
fi

# Remove MPD custom config
rm -f /data/configuration/music_service/mpd/mpd_custom.conf

# Unmount Airplay template if mounted
AIR="/volumio/app/plugins/music_service/airplay_emulation/shairport-sync.conf.tmpl"
if df "$AIR" 2>/dev/null | grep -q "$AIR"; then
  echo "Unmounting Airplay template..."
  sudo umount "$AIR"
fi

# Run createConf.js if it exists (for config restoration)
if [ -f "$PLUGIN_DIR/createConf.js" ]; then
  node "$PLUGIN_DIR/createConf.js"
fi

# =============================================================================
# CLEANUP: Plugin-installed components
# =============================================================================
DATA_DIR="/data/INTERNAL/peppy_screensaver"

# Remove x64 X session script if present
if [ -f /etc/X11/Xsession.d/50-peppy-xhost ]; then
  echo "Removing x64 X11 access script..."
  rm -f /etc/X11/Xsession.d/50-peppy-xhost
fi

# Remove library symlink
if [ -L "$PLUGIN_DIR/lib/libpeppyalsa.so" ]; then
  echo "Removing library symlink..."
  rm -f "$PLUGIN_DIR/lib/libpeppyalsa.so"
fi

# Remove arch-specific binaries and libraries
echo "Removing binaries and libraries..."
rm -rf "$PLUGIN_DIR/bin"
rm -rf "$PLUGIN_DIR/lib"

# Remove Python packages
echo "Removing Python packages..."
rm -rf "$PLUGIN_DIR/packages"

# Remove PeppyMeter
if [ -d "$PLUGIN_DIR/screensaver/peppymeter" ]; then
  echo "Removing PeppyMeter..."
  rm -rf "$PLUGIN_DIR/screensaver/peppymeter"
fi

# Remove PeppySpectrum
if [ -d "$PLUGIN_DIR/screensaver/spectrum" ]; then
  echo "Removing PeppySpectrum..."
  rm -rf "$PLUGIN_DIR/screensaver/spectrum"
fi

# Remove Volumio integration files
if [ -d "$PLUGIN_DIR/screensaver" ]; then
  echo "Removing screensaver integration..."
  rm -rf "$PLUGIN_DIR/screensaver"
fi

# Remove templates and data (unless user chose to preserve themes)
if [ -d "$DATA_DIR" ]; then
  if [ -f "$DATA_DIR/.preserve" ]; then
    echo "Preserving themes (user setting)..."
  else
    echo "Removing templates..."
    rm -rf "$DATA_DIR"
  fi
fi

# Remove system packages if not needed by other software
echo "Removing system dependencies if unused..."
for pkg in libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libfftw3-double3; do
  if dpkg -s "$pkg" &> /dev/null; then
    apt-get remove -y "$pkg" 2>/dev/null || echo "$pkg in use by other software, skipped"
  fi
done
apt-get autoremove -y 2>/dev/null || true

echo "Uninstall complete"
echo "pluginuninstallend"
