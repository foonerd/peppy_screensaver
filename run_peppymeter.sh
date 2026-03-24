#!/bin/bash
# run_peppymeter.sh - Launch PeppyMeter with plugin-local libraries

PLUGIN_DIR="/data/plugins/user_interface/peppy_screensaver"

# PeppyMeter Screensaver release (must match package.json) — used for remote client compatibility
if [ -f "$PLUGIN_DIR/package.json" ]; then
  PEPPY_PLUGIN_VERSION=$(grep -m1 '"version"' "$PLUGIN_DIR/package.json" | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/')
  export PEPPY_PLUGIN_VERSION
fi

# Get Volumio architecture
ARCH=$(cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d 'VOLUMIO_ARCH="')

if [ -z "$ARCH" ]; then
  echo "ERROR: Could not detect Volumio architecture"
  exit 1
fi

# Set library paths for plugin-local dependencies
# Include pygame.libs and pillow.libs for bundled libs from manylinux wheels
export LD_LIBRARY_PATH="$PLUGIN_DIR/lib/$ARCH:$PLUGIN_DIR/lib/$ARCH/python/pygame.libs:$PLUGIN_DIR/lib/$ARCH/python/pillow.libs:$LD_LIBRARY_PATH"
export PYTHONPATH="$PLUGIN_DIR/lib/$ARCH/python:$PYTHONPATH"
export DISPLAY=:0

# x64-specific fixes
if [ "$ARCH" = "x64" ]; then
  # Disable software rendering to avoid swrast/llvmpipe crashes
  export LIBGL_ALWAYS_SOFTWARE=0
  export SDL_RENDER_DRIVER=x11
  export SDL_FRAMEBUFFER_ACCELERATION=0
  
  # Disable MIT-SHM (shared memory) - causes BadValue errors in VMs
  export QT_X11_NO_MITSHM=1
  export _X11_NO_MITSHM=1
fi

cd "$PLUGIN_DIR"
python3 ./screensaver/volumio_peppymeter.py
