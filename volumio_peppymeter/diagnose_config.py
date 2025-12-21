#!/usr/bin/env python3
# diagnose_config.py - PeppyMeter configuration diagnostic tool
#
# Usage:
#   cd /data/plugins/user_interface/peppy_screensaver/screensaver
#   python3 diagnose_config.py
#
# This script dumps the meter configuration structure to help diagnose
# issues with backgrounds, overlays, and meter settings.

import os
import sys

# Try to auto-detect and add pygame path
plugin_base = '/data/plugins/user_interface/peppy_screensaver'
arch_dirs = ['armv7', 'armv8', 'arm', 'x64']
for arch in arch_dirs:
    py_path = os.path.join(plugin_base, 'lib', arch, 'python')
    if os.path.exists(py_path):
        sys.path.insert(0, py_path)
        break

# Find screensaver directory
script_dir = os.path.dirname(os.path.abspath(__file__))
peppymeter_dir = os.path.join(script_dir, 'peppymeter')

if not os.path.isdir(peppymeter_dir):
    print(f"ERROR: Cannot find peppymeter directory at {peppymeter_dir}")
    print(f"  Place this script in the screensaver/ directory")
    sys.exit(1)

# Change to peppymeter directory (required for internal imports)
os.chdir(peppymeter_dir)
sys.path.insert(0, peppymeter_dir)

try:
    from peppymeter import Peppymeter
    from configfileparser import *
except ImportError as e:
    print(f"ERROR: Failed to import peppymeter")
    print(f"Import error: {e}")
    sys.exit(1)

print("Initializing Peppymeter (this may take a moment)...")

try:
    pm = Peppymeter(standalone=True, timer_controlled_random_meter=False, quit_pygame_on_stop=False)
    cfg = pm.util.meter_config
except Exception as e:
    print(f"ERROR: Failed to initialize Peppymeter: {e}")
    sys.exit(1)

print("=" * 70)
print("PEPPYMETER CONFIGURATION DIAGNOSTIC")
print("=" * 70)

# Get current meter name
meter_name = cfg.get(METER, cfg.get('meter', 'unknown'))
print(f"\nCurrent METER: {meter_name}")

# Print top-level keys
print("\n--- Top-level config keys ---")
for k in sorted(cfg.keys(), key=str):
    v = cfg[k]
    if isinstance(v, dict):
        print(f"  {k}: <dict with {len(v)} keys>")
    else:
        print(f"  {k}: {type(v).__name__} = {repr(v)[:50]}")

# Check if meter section exists
print("\n" + "=" * 70)
if meter_name in cfg:
    mc = cfg[meter_name]
    print(f"METER SECTION: [{meter_name}]")
    print("=" * 70)
    for k in sorted(mc.keys(), key=str):
        v = mc[k]
        print(f"  {repr(k)}: {repr(v)[:60]}")
else:
    print(f"WARNING: [{meter_name}] section not found in config!")
    print("\nAvailable sections that look like meters:")
    for k in cfg.keys():
        if isinstance(cfg[k], dict) and len(cfg[k]) > 5:
            print(f"  {k}")

# Look for background-related keys
print("\n" + "=" * 70)
print("BACKGROUND-RELATED KEYS")
print("=" * 70)

if meter_name in cfg:
    mc = cfg[meter_name]
    found = False
    for k in mc.keys():
        k_lower = str(k).lower()
        if 'bgr' in k_lower or 'background' in k_lower or 'screen' in k_lower or 'fgr' in k_lower:
            print(f"  {repr(k)}: {repr(mc[k])}")
            found = True
    if not found:
        print("  (none found)")

# Check screen info
print("\n" + "=" * 70)
print("SCREEN INFO")
print("=" * 70)

if SCREEN_INFO in cfg:
    si = cfg[SCREEN_INFO]
    for k in sorted(si.keys(), key=str):
        print(f"  {k}: {repr(si[k])}")
else:
    print("  SCREEN_INFO not found")

# Check meter folder path
print("\n" + "=" * 70)
print("PATHS")
print("=" * 70)

base_path = cfg.get(BASE_PATH, "not set")
print(f"  BASE_PATH: {base_path}")

if SCREEN_INFO in cfg:
    meter_folder = cfg[SCREEN_INFO].get(METER_FOLDER, "not set")
    print(f"  METER_FOLDER: {meter_folder}")
    full_path = os.path.join(str(base_path), str(meter_folder))
    print(f"  Full meter path: {full_path}")
    if os.path.exists(full_path):
        print(f"  Path exists: YES")
        # List image files
        images = [f for f in os.listdir(full_path) if f.endswith(('.png', '.jpg', '.jpeg'))]
        if images:
            print(f"  Image files ({len(images)}):")
            for img in sorted(images)[:10]:
                print(f"    {img}")
            if len(images) > 10:
                print(f"    ... and {len(images) - 10} more")
    else:
        print(f"  Path exists: NO")

print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
