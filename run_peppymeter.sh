#!/bin/bash
# run_peppymeter.sh - Launch PeppyMeter with plugin-local libraries

PLUGIN_DIR="/data/plugins/user_interface/peppy_screensaver"

# Get Volumio architecture
ARCH=$(cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d 'VOLUMIO_ARCH="')

if [ -z "$ARCH" ]; then
  echo "ERROR: Could not detect Volumio architecture"
  exit 1
fi

# Set library paths for plugin-local dependencies
export LD_LIBRARY_PATH="$PLUGIN_DIR/lib/$ARCH:$LD_LIBRARY_PATH"
export PYTHONPATH="$PLUGIN_DIR/lib/$ARCH/python:$PYTHONPATH"
export DISPLAY=:0

cd "$PLUGIN_DIR"
python3 ./screensaver/volumio_peppymeter.py
