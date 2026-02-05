# PeppyMeter Remote Client

Display PeppyMeter visualizations on any Debian-based system by connecting to a Volumio server running the PeppyMeter plugin.

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

# Simple test display (no PeppyMeter, just VU bars)
~/peppy_remote/peppy_remote --test
```

## Requirements

- Debian-based Linux (Ubuntu, Raspberry Pi OS, etc.)
- Network access to Volumio box
- Volumio must have PeppyMeter plugin with "Remote Display Server" enabled

## How It Works

1. **Discovery**: Client listens for UDP broadcasts from PeppyMeter server (port 5579)
2. **Config**: Fetches `config.txt` from server via SMB (Internal Storage share)
3. **Templates**: Mounts template skins from server via SMB
4. **Audio Levels**: Receives real-time level data via UDP (port 5580)
5. **Metadata**: Connects to Volumio socket.io for track info
6. **Rendering**: Uses PeppyMeter to render the visualization

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

**SMB mount fails:**
- Ensure cifs-utils is installed
- Check Volumio SMB is accessible: `smbclient -L //hanger.local -N`
- Verify sudoers entry exists: `cat /etc/sudoers.d/peppy_remote`

**No audio levels:**
- Check server is broadcasting: `nc -ul 5580`
- Verify music is playing on Volumio
- Check firewall allows UDP 5580

**PeppyMeter import error:**
- Verify PeppyMeter was cloned: `ls ~/peppy_remote/peppymeter`
- Check Python packages: `~/peppy_remote/venv/bin/pip list`
