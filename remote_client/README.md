# PeppyMeter Remote Client

Display PeppyMeter visualizations on any Debian-based system by connecting to a Volumio server running the PeppyMeter plugin.

This client uses the **same rendering code** as the Volumio plugin (turntable, cassette, meters) but receives audio data over the network.

## Quick Install

One-liner installation:

```bash
curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash
```

With server pre-configured:

```bash
curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash -s -- --server hanger
```

## Usage

After installation, run:

```bash
# Auto-discover server on network
~/peppy_remote/peppy_remote

# Connect to specific server
~/peppy_remote/peppy_remote --server hanger
~/peppy_remote/peppy_remote --server 192.168.1.100

# Simple test display (VU bars only, no full PeppyMeter)
~/peppy_remote/peppy_remote --test

# Interactive configuration wizard
~/peppy_remote/peppy_remote --config
```

## Configuration

### Interactive Wizard (Recommended)

Run the configuration wizard for easy setup:

```bash
~/peppy_remote/peppy_remote --config
```

This opens an interactive menu where you can configure:
- Server connection (auto-discover or manual)
- Display mode (windowed, frameless, fullscreen)
- Window position
- Template source (SMB or local)

Settings are saved to `~/peppy_remote/config.json` and persist between runs.

### Display Modes

| Mode | Description | Use Case |
|------|-------------|----------|
| **Windowed** | Normal window with title bar, movable/resizable | Desktop use, testing |
| **Frameless** | No window decorations, fixed position | Kiosk displays, embedded |
| **Fullscreen** | Full screen on selected monitor | Dedicated displays |

Command-line overrides:
```bash
~/peppy_remote/peppy_remote --windowed      # Movable window
~/peppy_remote/peppy_remote --fullscreen    # Full screen
```

### Configuration File

Settings are stored in `~/peppy_remote/config.json`:

```json
{
  "server": {
    "host": null,           // null = auto-discover
    "level_port": 5580,
    "volumio_port": 3000,
    "discovery_port": 5579,
    "discovery_timeout": 10
  },
  "display": {
    "windowed": true,       // true = movable window
    "position": null,       // null = centered, or [x, y]
    "fullscreen": false,
    "monitor": 0
  },
  "templates": {
    "use_smb": true,
    "local_path": null
  }
}
```

Command-line arguments override config file settings.

## Requirements

- Debian-based Linux (Ubuntu, Raspberry Pi OS, etc.)
- Network access to Volumio box
- Volumio must have PeppyMeter plugin with "Remote Display Server" enabled

## How It Works

1. **Discovery**: Client listens for UDP broadcasts from PeppyMeter server (port 5579)
   - Discovery packets include `config_version` for detecting config changes
2. **Config**: Fetches `config.txt` from server via HTTP (Volumio plugin API)
   - Uses direct IP address from discovery for reliable connectivity
   - Endpoint: `/api/v1/pluginEndpoint?endpoint=peppy_screensaver&method=getRemoteConfig`
3. **Templates**: Mounts template skins from server via SMB
4. **Audio Levels**: Receives real-time level data via UDP (port 5580)
5. **Rendering**: Uses full Volumio PeppyMeter code (turntable, cassette, meters, indicators)

## Installation Structure

```
~/peppy_remote/
├── peppy_remote          # Launcher script
├── peppy_remote.py       # Main client
├── screensaver/          # Mirrors Volumio plugin structure
│   ├── peppymeter/       # PeppyMeter base engine (git clone)
│   │   ├── peppymeter.py
│   │   ├── configfileparser.py
│   │   ├── meter.py, needle.py, etc.
│   │   └── ...
│   ├── spectrum/         # PeppySpectrum engine (git clone)
│   │   ├── spectrum.py
│   │   ├── spectrumutil.py
│   │   ├── spectrumconfigparser.py
│   │   └── ...
│   ├── volumio_peppymeter.py   # Volumio main handler
│   ├── volumio_turntable.py    # Turntable/vinyl animations
│   ├── volumio_cassette.py     # Cassette deck animations
│   ├── volumio_compositor.py   # Layer compositing
│   ├── volumio_indicators.py   # Volume/mute/shuffle icons
│   ├── volumio_spectrum.py     # Spectrum integration
│   ├── volumio_configfileparser.py
│   ├── fonts/
│   └── format-icons/
├── mnt/                  # SMB mount for templates
├── venv/                 # Python virtual environment
└── config.json           # Client configuration
```

## Server Setup

On your Volumio box:

1. Go to plugin settings for PeppyMeter
2. Enable "Remote Display Server"
3. Choose server mode:
   - **Server Only**: Headless, only streams data (no local display)
   - **Server + Local**: Streams data AND shows local display
4. Save settings

## Uninstall

```bash
~/peppy_remote/uninstall.sh
```

This removes:
- Installation directory (`~/peppy_remote`)
- Sudoers entry for mount
- Desktop shortcut

System packages are NOT removed (python3, SDL2, etc.).

## Troubleshooting

**No servers found:**
- Check that PeppyMeter is running on Volumio
- Check that "Remote Display Server" is enabled
- Verify network connectivity: `ping hanger.local`
- Try manual server: `peppy_remote --server <ip_address>`

**SMB mount fails (templates):**
- Ensure cifs-utils is installed
- Check Volumio SMB is accessible: `smbclient -L //hanger.local -N`
- Verify sudoers entry exists: `cat /etc/sudoers.d/peppy_remote`
- Note: Config is fetched via HTTP, only templates use SMB

**Config fetch fails:**
- Ensure Volumio plugin is installed and running
- Test endpoint manually: `curl "http://<server_ip>:3000/api/v1/pluginEndpoint?endpoint=peppy_screensaver&method=getRemoteConfig"`
- Check Volumio logs for plugin errors

**No audio levels:**
- Check server is broadcasting: `nc -ul 5580`
- Verify music is playing on Volumio
- Check firewall allows UDP 5580

**Import errors:**
- Verify screensaver directory exists: `ls ~/peppy_remote/screensaver/`
- Check volumio_*.py files downloaded: `ls ~/peppy_remote/screensaver/volumio_*.py`
- Check PeppyMeter cloned: `ls ~/peppy_remote/screensaver/peppymeter/`

**Display issues ("windows not available"):**
- Ensure DISPLAY environment variable is set: `echo $DISPLAY`
- Check X11 is running: `xdpyinfo`
- Try: `export DISPLAY=:0` before running
