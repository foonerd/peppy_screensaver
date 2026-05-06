#!/bin/bash
# run_peppymeter.sh - Launch PeppyMeter with plugin-local libraries

PLUGIN_DIR="/data/plugins/user_interface/peppy_screensaver"
log() {
  echo "peppy-launcher: $*"
}

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

# Try to discover X authority cookie from running X server command line.
if [ -z "$XAUTHORITY" ] || [ ! -f "$XAUTHORITY" ]; then
  X_PID=$(pgrep -xo Xorg 2>/dev/null || true)
  if [ -z "$X_PID" ]; then
    X_PID=$(pgrep -xo X 2>/dev/null || true)
  fi
  if [ -n "$X_PID" ] && [ -r "/proc/$X_PID/cmdline" ]; then
    X_CMDLINE=$(tr '\0' ' ' < "/proc/$X_PID/cmdline")
    AUTH_FROM_X=$(echo "$X_CMDLINE" | sed -n 's/.*-auth[[:space:]]\([^[:space:]]\+\).*/\1/p')
    if [ -n "$AUTH_FROM_X" ] && [ -f "$AUTH_FROM_X" ]; then
      export XAUTHORITY="$AUTH_FROM_X"
    fi
  fi
fi

if [ -z "$XAUTHORITY" ] || [ ! -f "$XAUTHORITY" ]; then
  LATEST_AUTH=$(ls -1t /tmp/serverauth.* 2>/dev/null | head -n1)
  if [ -n "$LATEST_AUTH" ] && [ -f "$LATEST_AUTH" ]; then
    export XAUTHORITY="$LATEST_AUTH"
  fi
fi

# Prefer X11 when an X socket is available.
DISPLAY_NUM="${DISPLAY#:}"
if [ -S "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
  export SDL_VIDEODRIVER=x11
  if [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
    log "backend=x11 display=$DISPLAY xauth=$XAUTHORITY"
  else
    log "backend=x11 display=$DISPLAY xauth=missing (relying on xhost ACL)"
  fi
elif [ -n "$WAYLAND_DISPLAY" ]; then
  export SDL_VIDEODRIVER=wayland
  log "backend=wayland display=$WAYLAND_DISPLAY"
else
  log "backend=unknown (no X11 socket and no WAYLAND_DISPLAY)"
fi

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

# If render node exists but is not accessible, force software rendering.
if [ -e /dev/dri/renderD128 ] && { [ ! -r /dev/dri/renderD128 ] || [ ! -w /dev/dri/renderD128 ]; }; then
  export LIBGL_ALWAYS_SOFTWARE=1
  export SDL_RENDER_DRIVER=software
  export MESA_LOADER_DRIVER_OVERRIDE=llvmpipe
  log "render-node inaccessible (/dev/dri/renderD128); forcing software rendering"
fi

cd "$PLUGIN_DIR" || exit 1
python3 ./screensaver/volumio_peppymeter.py
