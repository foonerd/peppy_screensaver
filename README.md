# PeppyMeter Screensaver for Volumio 4

VU meter and spectrum analyzer screensaver plugin for Volumio 4.x (Bookworm).

Based on [PeppyMeter](https://github.com/project-owner/PeppyMeter) and [PeppySpectrum](https://github.com/project-owner/PeppySpectrum) by project-owner.
Uses optimized forks: [foonerd/PeppyMeter](https://github.com/foonerd/PeppyMeter) and [foonerd/PeppySpectrum](https://github.com/foonerd/PeppySpectrum).

Original Volumio plugin by [2aCD](https://github.com/2aCD-creator/volumio-plugins).

## Requirements

- Volumio 4.x (Bookworm-based)
- Minimum: Raspberry Pi 3B or equivalent
- Recommended: Raspberry Pi 4 or Pi 5
- Supported architectures: armv7 (Pi 3/4/5 32-bit), armv8 (Pi 3/4/5 64-bit), x64

### Hardware Compatibility

| Device | Status | Notes |
|--------|--------|-------|
| Pi 5 | Excellent | Best performance |
| Pi 4 | Good | Recommended |
| Pi 3B/3B+ | Minimum | Use 800x480, avoid heavy skins |
| Pi Zero 2 W | Marginal | Thermal throttling, 512MB RAM limit - not recommended |
| Pi 2 | Marginal | Weak cores - not recommended |
| Pi Zero/1 | Unsupported | Single core ARMv6, no NEON - will not run adequately |

Real-time 30fps rendering with ALSA audio capture and metadata updates requires
multi-core ARM with NEON SIMD. Single-core Pi Zero/1 cannot sustain this workload.

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
- Album art display with optional LP rotation effect
- Vinyl turntable animation (spinning disc under album art)
- Animated tonearm for turntable skins (tracks playback progress)
- Cassette deck skins with rotating reel animation
- Track info overlay with scrolling text
- Random meter rotation
- Touch to exit
- Configurable frame rate and update interval for CPU tuning
- Meter window positioning (centered or manual coordinates)
- Configurable text scrolling speeds

## Plugin Settings

The plugin settings are organized into sections:

### Global Settings

| Setting | Description |
|---------|-------------|
| ALSA Device | Audio input source for visualization |
| DSP | Enable DSP processing |
| Use Spotify | Include Spotify playback |
| Use USB DAC | Include USB DAC playback |
| Use Airplay | Include Airplay playback |
| Timeout | Idle timeout before screensaver activates |
| Meter | Select active meter skin |
| Meter Position | Window position: centered or manual coordinates |
| Position X/Y | Manual position coordinates (when not centered) |
| Start/Stop Animation | Enable fade animation on start/stop |
| Smooth Buffer | Audio smoothing buffer size |
| Needle Cache | Cache rotated needle images (reduces CPU, uses more RAM) |

### Performance Settings

Frame rate, update intervals, and debug logging.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Frame Rate | 10-60 | 30 | Display refresh rate (FPS). Lower = less CPU |
| Update Interval | 1-10 | 2 | Spectrum/needle updates per N frames. Higher = less CPU |
| Debug Logging | Off/Basic/Verbose | Off | Enable logging to /tmp/peppy_debug.log |

### Scrolling Settings

Text scrolling speed for artist, title, and album display.

| Setting | Description |
|---------|-------------|
| Scrolling Mode | Use skin value / System default (40) / Custom |
| Artist Scrolling Speed | Custom speed for artist text (5-200 pixels/sec) |
| Title Scrolling Speed | Custom speed for title text (5-200 pixels/sec) |
| Album Scrolling Speed | Custom speed for album text (5-200 pixels/sec) |

Scrolling modes:
- **Use skin value**: Reads speed from skin configuration, falls back to 40 if not set
- **System default**: Always uses 40 pixels/second
- **Custom**: Uses the individual speed values specified below

### Animation Settings

Fade transitions between meters and playback states.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Transition Effect | None/Fade | Fade | Visual transition type |
| Transition Duration | 0.1-5.0 | 0.5 | Fade duration in seconds |
| Transition Color | Black/White | Black | Fade overlay color |
| Transition Opacity | 0-100 | 100 | Fade overlay opacity percentage |

### Rotation Settings

Album art and cassette spool rotation speed and quality.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Rotation Quality | Low/Medium/High/Custom | Medium | Rotation smoothness vs CPU usage |
| Rotation FPS | 4-30 | 8 | Custom rotation update rate |
| Vinyl Rotation Speed | 0.1-5.0 | 1.0 | Album art rotation multiplier |
| Left Spool Speed | 0.1-5.0 | 1.0 | Left cassette reel multiplier |
| Right Spool Speed | 0.1-5.0 | 1.0 | Right cassette reel multiplier |
| Reel Rotation Direction | CCW/CW | CCW | Cassette reel rotation direction |

## Performance Tuning

### Tuning Guide

**Pi 4/5 (recommended settings):**
- Frame rate: 30 FPS
- Update interval: 2
- Expected CPU: 15-25%

**Pi 3B (conservative settings):**
- Frame rate: 20 FPS
- Update interval: 3
- Expected CPU: 25-35%

**High CPU / thermal issues:**
- Reduce frame rate to 15-20
- Increase update interval to 3-4
- Use 800x480 resolution templates

### Optimization Details

v3.0.7+ includes several CPU optimizations:

- **Dirty rectangle rendering**: Spectrum analyzer only redraws bars that changed
- **Skip-if-unchanged**: Needle animation skips frames when volume is static
- **Configurable throttling**: UI-adjustable frame rate and update intervals

These optimizations reduce CPU usage by 30-50% compared to earlier versions.

### Expected CPU Usage

At default settings (30 FPS, update interval 2):

| Resolution | Pi 5 | Pi 4 | Pi 3B | x64 |
|------------|------|------|-------|-----|
| 800x480 | 8-12% | 12-18% | 20-30% | 1-2% |
| 1024x600 | 12-18% | 18-25% | 30-40% | 1-2% |
| 1280x720 | 20-30% | 30-40% | Not recommended | 1-2% |
| 1920x1080 | 30-40% | 40-55% | Not recommended | 2-3% |

CPU usage can be reduced further by lowering frame rate and increasing update interval.

### NEON Optimization (ARM)

The bundled pygame package for ARM (armv7/armv8) is built with NEON SIMD
optimization enabled, providing significantly better performance on Pi 3/4/5.

To verify NEON is enabled:
```bash
PYTHONPATH=/data/plugins/user_interface/peppy_screensaver/lib/arm/python \
  python3 -c "import pygame; pygame.init()"
```

If you see "neon capable but pygame was not built with support" warning,
the package needs to be rebuilt with NEON support. See Build Information below.

## Skin Configuration

Skins are configured via `meters.txt` in the meter folder. Extended features
require `config.extend = True` in the meter section.

### Text Scrolling Speed

Control how fast text scrolls when it exceeds the display area:

```ini
# Global scrolling speed (applies to all text fields)
playinfo.scrolling.speed = 20

# Per-field scrolling speeds (override global)
playinfo.scrolling.speed.artist = 15
playinfo.scrolling.speed.title = 25
playinfo.scrolling.speed.album = 20
```

Values are in pixels per second. Lower = slower scrolling. Default is 40.

Priority when using "Use skin value" mode:
1. Per-field speed (e.g., `playinfo.scrolling.speed.title`)
2. Global speed (`playinfo.scrolling.speed`)
3. Default (40)

### Cassette Reel Animation

Cassette-style skins can display rotating tape reels that spin during playback.
Reels pause when playback is paused and maintain their position.

```ini
[MyCassetteSkin]
meter.type = linear
config.extend = True
screen.bgr = cassette_background.png
bgr.filename = cassette_bgr.png

# Left reel (supply reel)
reel.left.filename = reel_left.png
reel.left.pos = 100,150
reel.left.center = 137,187

# Right reel (take-up reel)
reel.right.filename = reel_right.png
reel.right.pos = 300,150
reel.right.center = 355,187

# Rotation speed in RPM (revolutions per minute)
reel.rotation.speed = 1.5

# Rotation direction (optional - overrides global setting)
reel.direction = ccw
```

| Option | Description |
|--------|-------------|
| `reel.left.filename` | PNG file for left reel graphic |
| `reel.left.pos` | Top-left position (x,y) for drawing |
| `reel.left.center` | Center point (x,y) for rotation pivot |
| `reel.right.filename` | PNG file for right reel graphic |
| `reel.right.pos` | Top-left position (x,y) for drawing |
| `reel.right.center` | Center point (x,y) for rotation pivot |
| `reel.rotation.speed` | Rotation speed in RPM (default: 0) |
| `reel.direction` | Rotation direction: `cw` or `ccw` (optional, overrides global setting) |

The reel graphics should be PNG files with transparency. The center point
defines the rotation axis and should be the visual center of the reel hub.

Reel rotation direction can be set per-meter in meters.txt (`reel.direction = cw` or `ccw`),
or globally via plugin settings (Rotation Settings > Reel Rotation Direction).
Per-meter setting takes priority over global setting.

### Album Art Rotation

Album art can rotate like a vinyl record during playback:

```ini
albumart.pos = 500,100
albumart.dimension = 200,200
albumart.rotation = True
albumart.rotation.speed = 8
```

### Vinyl Turntable Animation

Turntable-style skins can display a spinning vinyl disc image beneath the album art.
This provides a more realistic turntable effect where the vinyl record rotates and
the album art (as a record label) can either spin with it or remain static.

```ini
[MyTurntableSkin]
meter.type = circular
config.extend = True

# Vinyl disc configuration
vinyl.filename = vinyl_disc.png
vinyl.pos = 100,50
vinyl.center = 300,250
vinyl.direction = cw

# Album art positioned as record label on the vinyl
albumart.pos = 200,150
albumart.dimension = 200,200
albumart.rotation = True
albumart.rotation.speed = 1.5
```

| Option | Description |
|--------|-------------|
| `vinyl.filename` | PNG file for vinyl disc graphic (transparent background) |
| `vinyl.pos` | Top-left position (x,y) for drawing |
| `vinyl.center` | Center point (x,y) for rotation pivot |
| `vinyl.direction` | Rotation direction: `cw` or `ccw` (optional, defaults to global reel.direction) |

**Rotation coupling:**

- When `albumart.rotation = True`: Album art rotates WITH the vinyl at the same speed (locked together like a real record label)
- When `albumart.rotation = False`: Vinyl spins but album art stays static (useful for certain visual effects)

The rotation speed is controlled by `albumart.rotation.speed` which applies to both vinyl and album art when coupled. This unified speed ensures realistic turntable behavior.

**Vinyl vs Reel:**

- Use **vinyl** for turntable skins where a single disc rotates under album art
- Use **reel** for cassette skins where two independent reels rotate

Both systems can coexist in the same installation but typically a skin uses one or the other.

### Tonearm Animation

Turntable-style skins can display an animated tonearm that follows track progress.
The arm drops onto the record when playback starts, tracks across the record
surface following the seek position, and lifts off when playback stops.

```ini
[MyTurntableSkin]
meter.type = circular
config.extend = True
screen.bgr = turntable_background.png

# Album art as rotating vinyl
albumart.pos = 100,80
albumart.dimension = 300,300
albumart.rotation = True
albumart.rotation.speed = 33.3

# Tonearm configuration
tonearm.filename = tonearm.png
tonearm.pivot.screen = 450,120
tonearm.pivot.image = 45,36
tonearm.angle.rest = -70
tonearm.angle.start = -45
tonearm.angle.end = -15
tonearm.drop.duration = 1.5
tonearm.lift.duration = 1.0
```

| Option | Description |
|--------|-------------|
| `tonearm.filename` | PNG file for tonearm graphic (transparent background) |
| `tonearm.pivot.screen` | Screen coordinates (x,y) where pivot point is drawn |
| `tonearm.pivot.image` | Coordinates (x,y) within PNG where pivot/rotation center is located |
| `tonearm.angle.rest` | Angle in degrees when arm is parked off the record |
| `tonearm.angle.start` | Angle at outer groove (0% track progress) |
| `tonearm.angle.end` | Angle at inner groove (100% track progress) |
| `tonearm.drop.duration` | Duration in seconds for drop animation (default: 1.5) |
| `tonearm.lift.duration` | Duration in seconds for lift animation (default: 1.0) |

**Angle convention:** 0 degrees points RIGHT, negative angles rotate clockwise
(so -45 points down-right, -90 points straight down).

**State machine:**
- **REST**: Arm parked at rest angle, waiting for playback
- **DROP**: Animated descent onto record (ease-out curve)
- **TRACKING**: Following track progress across the record surface
- **LIFT**: Animated lift off record back to rest position

**Tonearm graphic tips:**
- Use PNG with transparent background
- Pivot point can be anywhere in the image (for counterweight designs)
- For S-curved arms, set pivot.image to the bearing housing location
- Arm length from pivot determines sweep radius

## Troubleshooting

### Debug Logging

Enable debug logging via plugin settings:

1. Settings > Plugins > PeppyMeter Screensaver > Settings
2. Performance Settings > Debug Logging
3. Select "Basic" or "Verbose"
4. Apply settings
5. Check `/tmp/peppy_debug.log` for diagnostic output

Log levels:
- **Off**: No logging (recommended for normal use)
- **Basic**: Essential events and errors
- **Verbose**: Detailed information for troubleshooting

**Note:** Disable after troubleshooting - the log file can fill /tmp (volatile RAM disk).

### Configuration Diagnostic

To dump the current meter configuration (useful for diagnosing missing backgrounds, wrong paths, etc.):

```bash
cd /data/plugins/user_interface/peppy_screensaver/screensaver
python3 diagnose_config.py
```

This shows:
- Current meter name and settings
- Background image keys (screen.bgr, bgr.filename, fgr.filename)
- Meter folder paths
- Available image files

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
sudo apt-get install -y libsdl2-ttf-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libfftw3-double3
```

### Permission errors on uninstall

```bash
sudo chown -R volumio:volumio /data/plugins/user_interface/peppy_screensaver
```

### High CPU usage on Pi

If CPU usage is higher than expected:

1. **Adjust Performance Settings** (Settings > Plugins > PeppyMeter > Performance):
   - Reduce frame rate to 20 FPS
   - Increase update interval to 3 or 4
2. Verify NEON is enabled (see above)
3. Use a lower resolution meter template (800x480 recommended for Pi 3)
4. Disable spectrum visualization if not needed
5. Disable album art rotation if enabled

## Directory Structure

```
peppy_screensaver/
  bin/{arch}/                    - peppyalsa-client binary
  lib/{arch}/                    - libpeppyalsa.so library
  lib/{arch}/python/             - Python packages (pygame, socketio, etc.)
  packages/{arch}/               - Python packages archive (extracted on install)
  screensaver/                   - PeppyMeter runtime (after install)
    peppymeter/                  - PeppyMeter module
    spectrum/                    - PeppySpectrum module
    volumio_peppymeter.py        - Main screensaver script
    volumio_spectrum.py          - Spectrum analyzer integration
    volumio_configfileparser.py  - Volumio config extensions
    diagnose_config.py           - Configuration diagnostic tool
  volumio_peppymeter/            - Volumio integration (before install)
  asound/                        - ALSA configuration
  i18n/                          - Translations (en, de, fr)
  UIConfig.json                  - Plugin settings UI definition
  index.js                       - Volumio plugin controller
```

## Build Information

Pre-built binaries included for all supported architectures. No compilation required on target system.

- peppyalsa: Native ALSA scope plugin for audio data capture
- Python packages: pygame 2.5.2 (NEON-optimized), python-socketio 5.x, Pillow, pyscreenshot, etc.

### ARM Python Packages (NEON Build)

The ARM python packages must be built natively on a Raspberry Pi to get
NEON-optimized pygame. Docker/QEMU cross-compilation produces non-NEON builds.

For build instructions and native Pi build scripts, see the separate build repository:

**https://github.com/foonerd/peppy_builds**

### Architecture Package Mapping

| Plugin Path | Target Devices | NEON |
|-------------|----------------|------|
| armv7 | Pi 3/4/5 32-bit (ARMv7+) | Yes |
| armv8 | Pi 3/4/5 64-bit (ARMv8) | Yes |
| x64 | x86_64 PCs | N/A (SSE/AVX) |

Note: ARMv6 (Pi Zero/1) is not supported due to insufficient CPU performance.

## Deprecation Notices

### meters.txt Configuration

The following configuration options are deprecated and will be removed in a future version:

- `playinfo.maxwidth` - Use field-specific settings instead:
  - `playinfo.title.maxwidth`
  - `playinfo.artist.maxwidth`
  - `playinfo.album.maxwidth`
  - `playinfo.samplerate.maxwidth`

## License

MIT

## Credits

- PeppyMeter/PeppySpectrum: [project-owner](https://github.com/project-owner)
- Original Volumio plugin: [2aCD](https://github.com/2aCD-creator)
- Volumio 4 refactoring: [foonerd](https://github.com/foonerd)
- Volumio 4 pythonising: [Wheaten](https://github.com/WheatenSudo)
- Plugin Q&A testing: Wheaten
