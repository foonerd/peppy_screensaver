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
| x64 | Excellent | Spotify requires config change - see Troubleshooting |

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
- Playback state indicators (volume, mute, shuffle, repeat, play/pause, progress)
- Cassette deck skins with rotating reel animation
- Track info overlay with scrolling text
- Display persistence during pause/track changes (eliminates flicker)
- Random meter rotation
- Touch to exit
- Configurable frame rate and update interval for CPU tuning
- Meter window positioning (centered or manual coordinates)
- Configurable text scrolling speeds
- **Remote display server** - Stream visualization to other devices on your network

## Plugin Settings

The plugin settings are organized into sections:

### Global Settings

| Setting | Description |
|---------|-------------|
| ALSA Device | Audio input source for visualization |
| DSP | Enable DSP processing |
| Use Spotify | Include Spotify playback (x64: see Troubleshooting for config) |
| Use USB DAC | Include USB DAC playback |
| Use Airplay | Include Airplay playback |
| Timeout | Idle timeout before screensaver activates |
| Meter | Select active meter skin |
| Meter Position | Window position: centered or manual coordinates |
| Position X/Y | Manual position coordinates (when not centered) |
| Start/Stop Animation | Enable fade animation on start/stop |
| Smooth Buffer | Audio smoothing buffer size |
| Needle Cache | Cache rotated needle images (reduces CPU, uses more RAM) |

### VU-Meter Settings

Template/meter selection and randomization options.

| Setting | Description |
|---------|-------------|
| Meter Selection | Select specific meter or use random/list mode |
| Random Selection | Comma-separated list of meters for list mode |
| Random Mode | Trigger: on title change or at interval |
| Random Interval | Seconds between random meter changes (15-1000) |

### Performance Settings

Frame rate, update intervals, and CPU tuning.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Frame Rate | 10-60 | 30 | Display refresh rate (FPS). Lower = less CPU |
| Update Interval | 1-10 | 2 | Spectrum/needle updates per N frames. Higher = less CPU |
| Meter Timing Delay | 0-20 | 10 | Render loop delay in milliseconds. See below for details |

**Meter Timing Delay:** Controls the pause between render frames. This setting balances CPU usage and meter responsiveness:

- **10ms (default)**: Good balance of CPU and responsive meters
- **15-20ms**: Lower CPU usage, meters may feel slightly sluggish  
- **0-5ms**: Higher CPU usage, more responsive meters

**Warning:** Values below 10ms can significantly increase CPU usage. Not recommended for Pi 3 or systems with thermal constraints.

**Spectrum Template Performance:** Spectrum analyzer templates have higher CPU usage than VU meter templates due to rendering ~57 animated bars per frame. CPU scales directly with frame rate:

| Frame Rate | Approximate CPU (Pi 5) |
|------------|------------------------|
| 30 fps | ~75-80% |
| 25 fps | ~70-75% |
| 20 fps | ~60-65% |
| 15 fps | ~45-50% |
| 10 fps | ~25-30% |

**Recommendation:** Use 15-20 fps for spectrum templates to keep CPU under 60%.

### Rotation Settings

Album art and cassette spool rotation speed and quality.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Rotation Quality | Low/Medium/High/Custom | Medium | Rotation smoothness vs CPU usage |
| Rotation FPS | 4-30 | 8 | Custom rotation update rate |
| Vinyl Rotation Speed | 0.1-5.0 | 1.0 | Album art rotation multiplier |
| Left Spool Speed | 0.1-5.0 | 1.0 | Left cassette reel multiplier |
| Right Spool Speed | 0.1-5.0 | 1.0 | Right cassette reel multiplier |
| Adaptive Spool Speeds | On/Off | Off | Dynamic speed based on playback progress |
| Reel Rotation Direction | CCW/CW | CCW | Cassette reel rotation direction |

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

### Playback Behavior

Controls display persistence during pause and track changes.

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Keep display active | Disabled/5s/15s/30s/1min/2min/5min | 30s | Delay before display turns off after pause/stop |
| Time display during persist | Freeze/Countdown | Freeze | What to show in time area when paused |
| Queue progress mode | Single Track/Full Queue | Single Track | How cassette/turntable animations track progress |

**Keep display active:** Prevents screen flicker during track changes by keeping the display running briefly after playback stops. Volumio sends stop-play sequence on next/prev, causing visible restart without this delay.

**Time display modes:**
- **Freeze**: Shows track time at moment of pause (default)
- **Countdown**: Shows time until display turns off (orange color)

**Queue progress mode:** Determines how cassette reels and turntable tonearm track playback progress:
- **Single Track**: Animations based on current track duration (default)
- **Full Queue**: Animations span the entire playlist - reels/tonearm move across all queued tracks

Queue mode automatically falls back to single track for webstreams or when the queue is empty.

### Debug Settings

Diagnostic logging for troubleshooting.

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Debug Level | Off/Basic/Verbose/Trace | Off | Logging verbosity |

**Debug levels:**
- **Off**: No logging (recommended for normal use)
- **Basic**: Startup, errors, key state changes
- **Verbose**: Configuration details (includes Basic)
- **Trace**: Component-specific logging (includes Verbose)

When **Trace** is selected, additional switches appear to enable logging for specific components:

| Switch | Description |
|--------|-------------|
| Meters/Needles | Audio levels, needle positions, render decisions |
| Spectrum | Spectrum analyzer updates and throttling |
| Vinyl rotation | Rotation state, angle, FPS gating |
| Reel left | Left cassette spool state and render decisions |
| Reel right | Right cassette spool state and render decisions |
| Tonearm | State machine, angles, DROP/LIFT/TRACKING transitions, backing restore |
| Album art | URL changes, rotation, cache |
| Text scrolling | Scroll position, offset changes, backing restore |
| Volume indicator | Value changes, position calculations |
| Mute indicator | 3-state logic (off, muted, volume=0) |
| Shuffle indicator | Shuffle/infinity state changes |
| Repeat indicator | Repeat state changes (off, all, single) |
| Playstate indicator | Play/pause/stop transitions |
| Progress bar | Progress percentage, seek input |
| Metadata (pushState) | Every pushState event from Volumio |
| Seek interpolation | Raw vs interpolated seek calculations |
| Time remaining | Time calculations and display updates |
| Initialization | Meter init, backing captures, renderer creation |
| Fade transitions | Fade timing, lock states, skip reasons |
| Frame timing | Render loop timing, status changes |

All trace switches default to OFF and persist independently.

### Profiling

Performance analysis tools for developers and advanced users.

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Timing Profiling | On/Off | Off | Log render loop timing to debug log |
| Timing Interval | 1-1000 | 30 | Frames between timing reports |
| cProfile Profiling | On/Off | Off | Enable Python cProfile for detailed analysis |
| cProfile Duration | 0-3600 | 60 | Seconds to run profiler before writing results |

**Timing Profiling:** Logs frame timing statistics (min/max/avg render time) to the debug log at the specified interval. Useful for identifying performance issues.

**cProfile Profiling:** Runs Python's cProfile module for detailed function-level timing. Results are written to `/tmp/peppy_profile.txt` after the specified duration. Use for deep performance analysis.

**Note:** Both profiling options add overhead. Disable after troubleshooting.

### Remote Display Settings

Stream visualization data to remote displays on your network.

| Setting | Options | Default | Description |
|---------|---------|---------|-------------|
| Enable Remote Server | On/Off | Off | Enable network streaming of visualization data |
| Server Mode | Server Only / Server + Local | Server + Local | Display mode when server is enabled |
| Level Port | 1024-65535 | 5580 | UDP port for audio level data |
| Discovery Port | 1024-65535 | 5579 | UDP port for server discovery broadcasts |

**Server modes:**
- **Server Only**: Headless mode - streams data but shows no local display (for dedicated servers)
- **Server + Local**: Streams data AND shows visualization locally (default)

**How it works:**
1. Server broadcasts discovery packets on UDP (default port 5579)
2. Clients discover server automatically or connect by hostname/IP
3. Audio level data streams via UDP (default port 5580)
4. Clients fetch configuration and templates from server
5. Metadata comes from Volumio's socket.io interface

See [Remote Client](#remote-display-client) section for client installation.

## Performance Tuning

### Tuning Guide

**Pi 4/5 (recommended settings):**
- Frame rate: 30 FPS
- Update interval: 2
- Meter timing delay: 10ms
- Expected CPU: 15-25% (basic), 80-85% (turntable)

**Pi 3B (conservative settings):**
- Frame rate: 20 FPS
- Update interval: 3
- Meter timing delay: 15ms
- Expected CPU: 25-35%

**High CPU / thermal issues:**
- Reduce frame rate to 15-20
- Increase update interval to 3-4
- Increase meter timing delay to 15-20ms
- Use 800x480 resolution templates
- Avoid turntable templates with rotation

### Optimization Details

v3.2.0+ includes several CPU optimizations:

- **Dirty rectangle rendering**: Spectrum analyzer only redraws bars that changed
- **Skip-if-unchanged**: Needle animation skips frames when volume is static
- **Configurable throttling**: UI-adjustable frame rate and update intervals

v3.2.1+ adds turntable-specific optimizations:

- **Vinyl + album art composite**: Album art is composited onto vinyl surface once per track change, then rotated as a single unit (like a real LP). Reduces per-frame blits by ~50%
- **Precomputed rotation frames**: Tonearm rotation frames are precomputed at load time, eliminating per-frame rotation calculations
- **Configurable meter timing delay**: Adjustable render loop delay (0-20ms) balances CPU usage and meter responsiveness

These optimizations reduce turntable template CPU usage from 100%+ to 80-85% on Pi 5.

### Expected CPU Usage

At default settings (30 FPS, update interval 2, meter delay 10ms):

**Basic/Spectrum templates:**

| Resolution | Pi 5 | Pi 4 | Pi 3B | x64 |
|------------|------|------|-------|-----|
| 800x480 | 8-12% | 12-18% | 20-30% | 1-2% |
| 1024x600 | 12-18% | 18-25% | 30-40% | 1-2% |
| 1280x720 | 20-30% | 30-40% | Not recommended | 1-2% |
| 1920x1080 | 30-40% | 40-55% | Not recommended | 2-3% |

**Turntable templates (with vinyl/art rotation):**

| Resolution | Pi 5 | Pi 4 | Pi 3B | x64 |
|------------|------|------|-------|-----|
| 800x480 | 50-60% | 60-70% | Not recommended | 5-10% |
| 1280x720 | 80-85% | 85-95% | Not recommended | 10-15% |

Turntable templates are more CPU-intensive due to continuous rotation rendering.
Use basic templates on Pi 3 or systems with thermal constraints.

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

### Time display (elapsed and total)

Optional elapsed and total time labels use the same style as time remaining and apply to basic, cassette, and turntable when set in the meter config. In `meters.txt` (per meter): `time.elapsed.pos`, `time.elapsed.color`, `time.total.pos`, `time.total.color`. See the wiki meters.txt reference for details.

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

# Adaptive spool speeds (optional - overrides global setting)
spool.adaptive = true
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
| `spool.adaptive` | Adaptive spool speeds: `true` or `false` (optional, overrides global setting) |

The reel graphics should be PNG files with transparency. The center point
defines the rotation axis and should be the visual center of the reel hub.

Reel rotation direction can be set per-meter in meters.txt (`reel.direction = cw` or `ccw`),
or globally via plugin settings (Rotation Settings > Reel Rotation Direction).
Per-meter setting takes priority over global setting.

**Adaptive spool speeds:** When enabled, spool speeds dynamically adjust based on playback
progress to simulate realistic cassette physics. Tape speed over the head is constant, so
angular velocity is inversely proportional to spool radius (larger spool = slower spin).

For **CCW** (tape path at bottom, standard orientation):
- Start: Left spool full (slow), right spool empty (fast)
- End: Left spool empty (fast), right spool full (slow)

For **CW** (tape path at top): Reversed - left is take-up, right is supply.

Uses queue progress when Queue Mode is set to Full Queue, otherwise uses single track progress.
Can be set globally (Rotation Settings > Adaptive Spool Speeds) or per-meter in meters.txt.

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

### Playback Indicators

Skins can display playback control states including volume level, mute,
shuffle, repeat mode, play/pause status, and track progress bar.

Indicators support two display modes:
- **LED mode**: Colored shapes (circle/rectangle) with optional glow effects
- **Icon mode**: PNG images per state with optional glow frame/edge

Volume display supports multiple styles: numeric text, horizontal bar,
image-based fader/slider, rotary knob, or arc gauge.

#### Progress Indicator Styles

Progress bar supports the same styles as volume indicator:

**Horizontal slider (default):**
```ini
progress.pos = 100,680
progress.dim = 500,10
progress.color = 0,200,255
progress.bg.color = 40,40,40
```

**Vertical slider:**
```ini
progress.pos = 50,200
progress.dim = 10,400
progress.slider.orientation = vertical
progress.color = 0,200,255
progress.bg.color = 40,40,40
```

**Arc gauge:**
```ini
progress.pos = 100,100
progress.dim = 100,100
progress.style = arc
progress.arc.width = 8
progress.arc.angle.start = 180
progress.arc.angle.end = 0
progress.color = 0,255,0
progress.bg.color = 40,40,40
```

**Rotary knob:**
```ini
progress.pos = 100,100
progress.dim = 80,80
progress.style = knob
progress.knob.image = progress_knob.png
progress.knob.angle.start = 225
progress.knob.angle.end = -45
```

**Image-based slider:**
```ini
progress.pos = 50,600
progress.dim = 500,30
progress.style = slider
progress.slider.track = progress_track.png
progress.slider.tip = progress_tip.png
progress.slider.orientation = horizontal
progress.slider.travel = 0,470
progress.slider.tip.offset = 0,0
```

| Option | Description |
|--------|-------------|
| `progress.style` | Display style: slider, arc, knob, numeric (default: slider) |
| `progress.slider.orientation` | Slider direction: horizontal, vertical (default: horizontal) |
| `progress.slider.track` | PNG image for slider track/groove (optional) |
| `progress.slider.tip` | PNG image for slider handle/tip (required for image slider) |
| `progress.slider.travel` | Pixel range for tip movement: start,end |
| `progress.slider.tip.offset` | Tip anchor offset: x,y (default: 0,0) |
| `progress.knob.image` | PNG image for rotary knob (required for knob style) |
| `progress.knob.angle.start` | Knob start angle in degrees (default: 225) |
| `progress.knob.angle.end` | Knob end angle in degrees (default: -45) |
| `progress.arc.width` | Arc stroke width in pixels (default: 6) |
| `progress.arc.angle.start` | Arc start angle in degrees (default: 225) |
| `progress.arc.angle.end` | Arc end angle in degrees (default: -45) |
| `progress.font.size` | Font size for numeric style (default: 24) |

**Progress bar markers (optional):** Add fixed signs or buttons along the bar (e.g. chapter marks). Up to 5 markers per section. Each marker has a position (0–100% along the bar) and either an image filename or a text label. Use keys `progress.marker.1.pos`, `progress.marker.1.image` or `progress.marker.1.label`, then `progress.marker.2.*`, etc. Images are loaded from the meter folder. Markers are visual only (no click/touch).

**Progress bar head icon (optional):** One icon that moves with the current progress (e.g. a forward arrow at the “head” of the bar). Use `progress.head.image` = filename (from meter folder). Position matches bar orientation: horizontal bars move the icon left-to-right, vertical bars bottom-to-top. Optional `progress.head.offset` = x,y (pixels) to nudge the icon.

Example (fixed markers + head icon):
```ini
progress.marker.1.pos = 0
progress.marker.1.label = |
progress.marker.2.pos = 100
progress.marker.2.label = |
progress.head.image = progress_head_arrow.png
progress.head.offset = 0,0
```

See the wiki for detailed configuration reference and examples.

## Troubleshooting

### Debug Logging

Enable debug logging via plugin settings:

1. Settings > Plugins > PeppyMeter Screensaver > Settings
2. Debug Settings > Debug Level
3. Select level: Basic, Verbose, or Trace
4. If Trace selected, enable specific component switches as needed
5. Apply settings
6. Check `/tmp/peppy_debug.log` for diagnostic output

Log levels:
- **Off**: No logging (recommended for normal use)
- **Basic**: Startup, errors, key state changes
- **Verbose**: Configuration details (includes Basic)
- **Trace**: Component-specific logging (use switches to select components)

**Trace mode:** When debugging specific issues (e.g., tonearm behavior), select Trace level and enable only the relevant component switch(es). This avoids flooding the log with unrelated data.

**Note:** Disable after troubleshooting - the log file can fill /tmp (volatile RAM disk).

#### ALSA Config Logging

The debug level also controls ALSA configuration logging in the Node.js plugin (output to Volumio log, not `/tmp/peppy_debug.log`). This logs what happens when the ALSA pipeline is built or rebuilt (e.g., on startup, bridge toggle, output device change).

| Level | What is logged | When |
|-------|---------------|------|
| **Off** | Nothing | — |
| **Basic** | Peppyalsa mode selected (inline-meter / multi-duplicate / DSD-passthrough), config file written, bridge toggle direction, ALSA rebuild trigger, output device/mixer changes | On every ALSA config rebuild |
| **Verbose** | All Basic entries plus: full input parameters (useDSP, alsaConf, isX64, plugType, useSpotify), template and output file paths | On every ALSA config rebuild |
| **Trace** | All Verbose entries plus: full generated ALSA config content | On every ALSA config rebuild |

**To view:** Check Volumio log with `journalctl -u volumio` or `cat /var/log/volumio.log` and search for `peppy_screensaver: ALSA:`.

**Example output at Basic level:**
```
peppy_screensaver: ALSA: Peppyalsa mode: inline-meter (bridge on)
peppy_screensaver: ALSA: config written: /data/plugins/.../asound/Peppyalsa.postPeppyalsa.5.conf
```

**Example output at Verbose level:**
```
peppy_screensaver: ALSA: writeAsoundConfigModular: alsaConf=0 useDSP=true isX64=false plugType=empty useSpot=false
peppy_screensaver: ALSA: writeAsoundConfigModular: template=/data/plugins/.../Peppyalsa.postPeppyalsa.5.conf.tmpl output=/data/plugins/.../asound/Peppyalsa.postPeppyalsa.5.conf
peppy_screensaver: ALSA: Peppyalsa mode: inline-meter (bridge on)
peppy_screensaver: ALSA: config written: /data/plugins/.../asound/Peppyalsa.postPeppyalsa.5.conf
```

**Trace level** adds the full generated config content (can be large).

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

### x64 Spotify Configuration

On x64 systems, Spotify playback with PeppyMeter requires a reduced audio buffer time.
Without this change, playback may fail on pause/resume with ALSA buffer negotiation errors.

**Symptoms:**
- Spotify plays initially but fails after pause/resume
- Log shows: `ALSA error at snd_pcm_hw_params_set_buffer_time_near: Invalid argument`
- Playback becomes unstable or stops working

**Solution:**

1. Go to Plugins > Installed Plugins
2. Click Settings on the Spotify plugin
3. Change **Audio Buffer Time** from 500000 to **100000**
4. Click Save

**Technical background:** The default 500ms buffer is too large for the ALSA multi plugin
to negotiate compatible parameters between the main audio output and the meter capture path.
Reducing to 100ms (100000 microseconds) allows successful buffer negotiation on x64 hardware.

This issue does not affect Raspberry Pi systems.

### High CPU usage on Pi

If CPU usage is higher than expected:

1. **Adjust Performance Settings** (Settings > Plugins > PeppyMeter > Performance):
   - Reduce frame rate to 20 FPS
   - Increase update interval to 3 or 4
   - Increase meter timing delay to 15-20ms
2. Verify NEON is enabled (see above)
3. Use a lower resolution meter template (800x480 recommended for Pi 3)
4. Use basic templates instead of turntable templates (no rotation overhead)
5. Disable spectrum visualization if not needed
6. Disable album art rotation if enabled

## Remote Display Client

Display PeppyMeter visualizations on any Debian-based system (Ubuntu, Raspberry Pi OS, etc.) by connecting to a Volumio server running PeppyMeter with Remote Display Server enabled.

The remote client uses the **same rendering code** as the Volumio plugin - all skins work identically.

### Quick Install

```bash
curl -sSL https://raw.githubusercontent.com/foonerd/peppy_remote/main/install.sh | bash
```

### Usage

```bash
# Auto-discover server on network
~/peppy_remote/peppy_remote

# Connect to specific server
~/peppy_remote/peppy_remote --server volumio

# Interactive configuration wizard
~/peppy_remote/peppy_remote --config
```

### Features

- Auto-discovery of PeppyMeter servers via UDP broadcast
- Full meter rendering (turntable, cassette, spectrum, indicators)
- Album art and metadata from Volumio
- Windowed, frameless, or fullscreen display modes
- Interactive configuration wizard
- Templates loaded via SMB from server

### Server Setup

1. Install PeppyMeter plugin on Volumio
2. Enable "Remote Display Server" in plugin settings
3. Choose mode: Server Only (headless) or Server + Local
4. Save settings

### Documentation

For detailed documentation, troubleshooting, and configuration options, see the separate repository:
**https://github.com/foonerd/peppy_remote**

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
    volumio_peppymeter.py        - Main coordinator and entry point
    volumio_basic.py             - Basic skin handler (meters, static art)
    volumio_turntable.py         - Turntable skin handler (vinyl, tonearm)
    volumio_cassette.py          - Cassette skin handler (rotating reels)
    volumio_spectrum.py          - Spectrum analyzer integration
    volumio_configfileparser.py  - Volumio config extensions
    volumio_indicators.py        - Playback indicator support
    diagnose_config.py           - Configuration diagnostic tool
  volumio_peppymeter/            - Volumio integration (before install)
  asound/                        - ALSA configuration
  i18n/                          - Translations (en, de, fr)
  UIConfig.json                  - Plugin settings UI definition
  index.js                       - Volumio plugin controller
```

## Architecture Overview

The plugin uses a coordinator pattern with specialized handlers for different skin types.
The main coordinator (`volumio_peppymeter.py`) detects the skin type and delegates
rendering to the appropriate handler.

### Skin Type Detection

Skin type is automatically detected from the meter configuration:

| Skin Type | Detection Criteria | Handler |
|-----------|-------------------|---------|
| **Cassette** | Has `reel.left.center` OR `reel.right.center`, WITHOUT tonearm or vinyl | `volumio_cassette.py` |
| **Turntable** | Has `vinyl.center` OR `tonearm.*` OR `albumart.rotation = True` | `volumio_turntable.py` |
| **Basic** | Everything else (meters only, static album art) | `volumio_basic.py` |

### Handler Responsibilities

Each handler is self-contained and manages its own render loop:

**BasicHandler** - Simplest rendering path, no backing buffer conflicts:
- Static album art
- Scrolling text fields
- Playback indicators
- No animated mechanical elements

**TurntableHandler** - Vinyl turntable skins:
- Rotating vinyl disc
- Rotating album art (coupled to vinyl)
- Animated tonearm with drop/lift/tracking states
- Backing buffer management for overlapping elements

**CassetteHandler** - Cassette deck skins:
- Left and right rotating reels
- Backing buffer management for reel overlap zones
- Force-redraw logic for text in reel areas

### Render Z-Order

All handlers follow a layered render order:

1. Background (static, already on screen)
2. Backing restoration (for animated elements)
3. Meters (needle animation)
4. Animated elements (vinyl, reels, tonearm)
5. Album art
6. Text fields (artist, title, album)
7. Indicators (volume, mute, shuffle, repeat, progress)
8. Time remaining (and optional elapsed/total when `time.elapsed.pos` / `time.total.pos` are set in the meter config)
9. Sample rate / format icon
10. Foreground mask

### Performance Implications

| Skin Type | Relative CPU | Notes |
|-----------|-------------|-------|
| Basic | Lowest | No rotation calculations or backing management |
| Turntable | Medium | Pre-computed rotation frames, FPS-gated updates |
| Cassette | Medium-High | Dual reel rotation, force-redraw for overlap zones |

Template authors can reduce CPU usage by choosing simpler skin types when
animated mechanical elements are not needed.

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
- Volumio 4 Python development: [Wheaten](https://github.com/WheatenSudo)
- Plugin Q&A testing: Wheaten
