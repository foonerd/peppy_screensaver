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

echo "Uninstall complete"
echo "pluginuninstallend"
