# PeppyMeter Screensaver for Volumio 4

VU meter and spectrum analyzer screensaver plugin for Volumio 4.x (Bookworm).

Based on [PeppyMeter](https://github.com/project-owner/PeppyMeter) and [PeppySpectrum](https://github.com/project-owner/PeppySpectrum) by project-owner.

Original Volumio plugin by [2aCD](https://github.com/2aCD-creator/volumio-plugins).

## Requirements

- Volumio 4.x (Bookworm-based)
- Supported architectures: arm (Pi Zero/1), armv7 (Pi 2/3/4 32-bit), armv8 (Pi 3/4/5 64-bit), x64

## Installation

```bash
git clone --depth=1 https://github.com/foonerd/peppy_screensaver.git
cd peppy_screensaver
volumio plugin install
```

## Manual Installation

If the above method fails:

```bash
git clone --depth=1 https://github.com/foonerd/peppy_screensaver.git
cd peppy_screensaver
zip -r peppy_screensaver.zip .
minidlna -d &
```

Then install via Volumio UI: Settings > Plugins > Install from local file

## Configuration

After installation, enable and configure the plugin:

1. Settings > Plugins > Installed Plugins
2. Enable "PeppyMeter Screensaver"
3. Click Settings to configure meter style, display options, etc.

## Features

- Multiple VU meter skins
- Spectrum analyzer mode
- Album art display
- Track info overlay
- Random meter rotation
- Touch to exit

## Troubleshooting

### Plugin won't start

Check logs:
```bash
journalctl -u volumio -f | grep -i peppy
```

### Manual test

```bash
cd /data/plugins/user_interface/peppy_screensaver
./run_peppymeter.sh
```

### Missing libraries

If you see SDL2 errors:
```bash
sudo apt-get install -y libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0
```

### Permission errors on uninstall

```bash
sudo chown -R volumio:volumio /data/plugins/user_interface/peppy_screensaver
```

## Directory Structure

```
peppy_screensaver/
  bin/{arch}/           - peppyalsa-client binary
  lib/{arch}/           - libpeppyalsa.so library
  lib/{arch}/python/    - Python packages (pygame, socketio, etc.)
  packages/{arch}/      - Python packages archive (extracted on install)
  screensaver/          - PeppyMeter and PeppySpectrum (cloned on install)
  asound/               - ALSA configuration
  i18n/                 - Translations
```

## Build Information

Pre-built binaries included for all supported architectures. No compilation required on target system.

- peppyalsa: Native ALSA scope plugin for audio data capture
- Python packages: pygame 2.5.2, python-socketio 5.x, Pillow, etc.

## License

ISC

## Credits

- PeppyMeter/PeppySpectrum: [project-owner](https://github.com/project-owner)
- Original Volumio plugin: [2aCD](https://github.com/2aCD-creator)
- Volumio 4 refactoring: foonerd
