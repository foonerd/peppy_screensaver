# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Rewritten 2025 for Volumio 4 / Bookworm (Python 3.11, pygame 2.5)
# Optimized 2025 - dirty rectangle updates, reduced per-frame overhead
#
# This file is part of PeppyMeter for Volumio
#
# Volumio 4 architecture:
# - Main-thread rendering (pygame/X11 requirement)
# - Socket.io for metadata (pushState events - no HTTP polling)
# - HTTP only for album art image fetching
# - ScrollingLabel for text animation (replaces TextAnimator threads)
# - Backing surface capture for clean redraws
# - Random meter support with overlay reinit
# - OPTIMIZED: Dirty rectangle updates instead of full screen flip
# - OPTIMIZED: Conditional redraw based on actual changes

import os
import sys
import time
import ctypes
import resource
import io
import math
import json
import hashlib
import requests
import socket
import struct
import pygame as pg
import socketio
import cProfile
import pstats

# SDL2 window positioning support (pygame 2.x with SDL2)
use_sdl2 = False
if pg.version.ver.startswith("2"):
    try:
        from pygame._sdl2 import Window
        import pyscreenshot
        use_sdl2 = True
    except ImportError:
        pass

from pathlib import Path
from threading import Thread
from pygame.time import Clock

from peppymeter.peppymeter import Peppymeter
from configfileparser import (
    SCREEN_INFO, WIDTH, HEIGHT, DEPTH, FRAME_RATE, METER, METER_NAMES,
    SDL_ENV, FRAMEBUFFER_DEVICE, MOUSE_ENABLED, MOUSE_DEVICE, MOUSE_DRIVER,
    VIDEO_DRIVER, VIDEO_DISPLAY, DOUBLE_BUFFER, SCREEN_RECT, BASE_PATH,
    METER_FOLDER, UI_REFRESH_PERIOD, BGR_FILENAME, FGR_FILENAME,
    EXIT_ON_TOUCH, STOP_DISPLAY_ON_TOUCH, RANDOM_METER_INTERVAL
)

from volumio_configfileparser import (
    Volumio_ConfigFileParser, EXTENDED_CONF, METER_VISIBLE, SPECTRUM_VISIBLE,
    COLOR_DEPTH, POSITION_TYPE, POS_X, POS_Y, START_ANIMATION, UPDATE_INTERVAL,
    FRAME_RATE_VOLUMIO,
    TRANSITION_TYPE, TRANSITION_DURATION, TRANSITION_COLOR, TRANSITION_OPACITY,
    DEBUG_LEVEL, DEBUG_TRACE_SWITCHES,
    DEBUG_TRACE_METERS, DEBUG_TRACE_SPECTRUM, DEBUG_TRACE_VINYL, DEBUG_TRACE_REEL_LEFT, DEBUG_TRACE_REEL_RIGHT,
    DEBUG_TRACE_TONEARM, DEBUG_TRACE_ALBUMART, DEBUG_TRACE_SCROLLING,
    DEBUG_TRACE_VOLUME, DEBUG_TRACE_MUTE, DEBUG_TRACE_SHUFFLE, DEBUG_TRACE_REPEAT,
    DEBUG_TRACE_PLAYSTATE, DEBUG_TRACE_PROGRESS,
    DEBUG_TRACE_METADATA, DEBUG_TRACE_SEEK, DEBUG_TRACE_TIME,
    QUEUE_MODE,
    DEBUG_TRACE_INIT, DEBUG_TRACE_FADE, DEBUG_TRACE_FRAME,
    PROFILING_TIMING, PROFILING_INTERVAL, PROFILING_CPROFILE, PROFILING_DURATION,
    ROTATION_QUALITY, ROTATION_FPS, ROTATION_SPEED,
    REEL_DIRECTION, SPOOL_LEFT_SPEED, SPOOL_RIGHT_SPEED,
    FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD,
    ALBUMART_POS, ALBUMART_DIM, ALBUMART_MSK, ALBUMBORDER,
    ALBUMART_ROT, ALBUMART_ROT_SPEED,
    PLAY_TXT_CENTER, PLAY_CENTER, PLAY_MAX,
    SCROLLING_SPEED, SCROLLING_SPEED_ARTIST, SCROLLING_SPEED_TITLE, SCROLLING_SPEED_ALBUM,
    PLAY_TITLE_POS, PLAY_TITLE_COLOR, PLAY_TITLE_MAX, PLAY_TITLE_STYLE,
    PLAY_ARTIST_POS, PLAY_ARTIST_COLOR, PLAY_ARTIST_MAX, PLAY_ARTIST_STYLE,
    PLAY_ALBUM_POS, PLAY_ALBUM_COLOR, PLAY_ALBUM_MAX, PLAY_ALBUM_STYLE,
    PLAY_TYPE_POS, PLAY_TYPE_COLOR, PLAY_TYPE_DIM,
    PLAY_SAMPLE_POS, PLAY_SAMPLE_STYLE, PLAY_SAMPLE_MAX,
    TIME_REMAINING_POS, TIMECOLOR,
    FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_DIGI, FONTCOLOR,
    FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_L,
    METER_BKP, RANDOM_TITLE, SPECTRUM, SPECTRUM_SIZE,
    REMOTE_SERVER_ENABLED, REMOTE_SERVER_MODE, REMOTE_SERVER_PORT, REMOTE_DISCOVERY_PORT,
    REMOTE_SPECTRUM_PORT
)

# Indicator configuration constants - import with fallback for backward compatibility
try:
    from volumio_configfileparser import (
        VOLUME_POS, VOLUME_STYLE, VOLUME_DIM, VOLUME_COLOR, VOLUME_BG_COLOR, VOLUME_FONT_SIZE,
        MUTE_POS, MUTE_ICON, MUTE_LED, MUTE_LED_SHAPE, MUTE_LED_COLOR,
        MUTE_LED_GLOW, MUTE_LED_GLOW_INTENSITY, MUTE_LED_GLOW_COLOR,
        MUTE_ICON_GLOW, MUTE_ICON_GLOW_INTENSITY, MUTE_ICON_GLOW_COLOR,
        SHUFFLE_POS, SHUFFLE_ICON, SHUFFLE_LED, SHUFFLE_LED_SHAPE, SHUFFLE_LED_COLOR,
        SHUFFLE_LED_GLOW, SHUFFLE_LED_GLOW_INTENSITY, SHUFFLE_LED_GLOW_COLOR,
        SHUFFLE_ICON_GLOW, SHUFFLE_ICON_GLOW_INTENSITY, SHUFFLE_ICON_GLOW_COLOR,
        REPEAT_POS, REPEAT_ICON, REPEAT_LED, REPEAT_LED_SHAPE, REPEAT_LED_COLOR,
        REPEAT_LED_GLOW, REPEAT_LED_GLOW_INTENSITY, REPEAT_LED_GLOW_COLOR,
        REPEAT_ICON_GLOW, REPEAT_ICON_GLOW_INTENSITY, REPEAT_ICON_GLOW_COLOR,
        PLAYSTATE_POS, PLAYSTATE_ICON, PLAYSTATE_LED, PLAYSTATE_LED_SHAPE, PLAYSTATE_LED_COLOR,
        PLAYSTATE_LED_GLOW, PLAYSTATE_LED_GLOW_INTENSITY, PLAYSTATE_LED_GLOW_COLOR,
        PLAYSTATE_ICON_GLOW, PLAYSTATE_ICON_GLOW_INTENSITY, PLAYSTATE_ICON_GLOW_COLOR,
        PROGRESS_POS, PROGRESS_DIM, PROGRESS_COLOR, PROGRESS_BG_COLOR,
        PROGRESS_BORDER, PROGRESS_BORDER_COLOR
    )
except ImportError:
    # Fallback if volumio_configfileparser not updated yet
    VOLUME_POS = "volume.pos"
    VOLUME_STYLE = "volume.style"
    VOLUME_DIM = "volume.dim"
    VOLUME_COLOR = "volume.color"
    VOLUME_BG_COLOR = "volume.bg.color"
    VOLUME_FONT_SIZE = "volume.font.size"
    MUTE_POS = "mute.pos"
    MUTE_ICON = "mute.icon"
    MUTE_LED = "mute.led"
    MUTE_LED_SHAPE = "mute.led.shape"
    MUTE_LED_COLOR = "mute.led.color"
    MUTE_LED_GLOW = "mute.led.glow"
    MUTE_LED_GLOW_INTENSITY = "mute.led.glow.intensity"
    MUTE_LED_GLOW_COLOR = "mute.led.glow.color"
    MUTE_ICON_GLOW = "mute.icon.glow"
    MUTE_ICON_GLOW_INTENSITY = "mute.icon.glow.intensity"
    MUTE_ICON_GLOW_COLOR = "mute.icon.glow.color"
    SHUFFLE_POS = "shuffle.pos"
    SHUFFLE_ICON = "shuffle.icon"
    SHUFFLE_LED = "shuffle.led"
    SHUFFLE_LED_SHAPE = "shuffle.led.shape"
    SHUFFLE_LED_COLOR = "shuffle.led.color"
    SHUFFLE_LED_GLOW = "shuffle.led.glow"
    SHUFFLE_LED_GLOW_INTENSITY = "shuffle.led.glow.intensity"
    SHUFFLE_LED_GLOW_COLOR = "shuffle.led.glow.color"
    SHUFFLE_ICON_GLOW = "shuffle.icon.glow"
    SHUFFLE_ICON_GLOW_INTENSITY = "shuffle.icon.glow.intensity"
    SHUFFLE_ICON_GLOW_COLOR = "shuffle.icon.glow.color"
    REPEAT_POS = "repeat.pos"
    REPEAT_ICON = "repeat.icon"
    REPEAT_LED = "repeat.led"
    REPEAT_LED_SHAPE = "repeat.led.shape"
    REPEAT_LED_COLOR = "repeat.led.color"
    REPEAT_LED_GLOW = "repeat.led.glow"
    REPEAT_LED_GLOW_INTENSITY = "repeat.led.glow.intensity"
    REPEAT_LED_GLOW_COLOR = "repeat.led.glow.color"
    REPEAT_ICON_GLOW = "repeat.icon.glow"
    REPEAT_ICON_GLOW_INTENSITY = "repeat.icon.glow.intensity"
    REPEAT_ICON_GLOW_COLOR = "repeat.icon.glow.color"
    PLAYSTATE_POS = "playstate.pos"
    PLAYSTATE_ICON = "playstate.icon"
    PLAYSTATE_LED = "playstate.led"
    PLAYSTATE_LED_SHAPE = "playstate.led.shape"
    PLAYSTATE_LED_COLOR = "playstate.led.color"
    PLAYSTATE_LED_GLOW = "playstate.led.glow"
    PLAYSTATE_LED_GLOW_INTENSITY = "playstate.led.glow.intensity"
    PLAYSTATE_LED_GLOW_COLOR = "playstate.led.glow.color"
    PLAYSTATE_ICON_GLOW = "playstate.icon.glow"
    PLAYSTATE_ICON_GLOW_INTENSITY = "playstate.icon.glow.intensity"
    PLAYSTATE_ICON_GLOW_COLOR = "playstate.icon.glow.color"
    PROGRESS_POS = "progress.pos"
    PROGRESS_DIM = "progress.dim"
    PROGRESS_COLOR = "progress.color"
    PROGRESS_BG_COLOR = "progress.bg.color"
    PROGRESS_BORDER = "progress.border"
    PROGRESS_BORDER_COLOR = "progress.border.color"

# Reel configuration constants - import with fallback for backward compatibility
try:
    from volumio_configfileparser import (
        REEL_LEFT_FILE, REEL_LEFT_POS, REEL_LEFT_CENTER,
        REEL_RIGHT_FILE, REEL_RIGHT_POS, REEL_RIGHT_CENTER,
        REEL_ROTATION_SPEED
    )
except ImportError:
    # Fallback if volumio_configfileparser not updated yet
    REEL_LEFT_FILE = "reel.left.filename"
    REEL_LEFT_POS = "reel.left.pos"
    REEL_LEFT_CENTER = "reel.left.center"
    REEL_RIGHT_FILE = "reel.right.filename"
    REEL_RIGHT_POS = "reel.right.pos"
    REEL_RIGHT_CENTER = "reel.right.center"
    REEL_ROTATION_SPEED = "reel.rotation.speed"

# Vinyl configuration constants - import with fallback for backward compatibility
try:
    from volumio_configfileparser import (
        VINYL_FILE, VINYL_POS, VINYL_CENTER, VINYL_DIRECTION
    )
except ImportError:
    # Fallback if volumio_configfileparser not updated yet
    VINYL_FILE = "vinyl.filename"
    VINYL_POS = "vinyl.pos"
    VINYL_CENTER = "vinyl.center"
    VINYL_DIRECTION = "vinyl.direction"


# =============================================================================
# Foreground Region Detection - OPTIMIZATION for selective blitting
# =============================================================================
def compute_foreground_regions(surface, min_gap=50, padding=2):
    """
    Analyze a foreground surface and return list of opaque region rects.
    
    This enables selective blitting - only blit foreground portions that
    overlap with dirty rectangles, rather than the entire surface.
    Typically reduces foreground blit area by 80-90%.
    
    :param surface: pygame surface with alpha channel
    :param min_gap: minimum horizontal gap (pixels) to consider regions separate
    :param padding: pixels to add around detected regions
    :return: list of pygame.Rect objects covering opaque regions
    """
    if surface is None:
        return []
    
    try:
        # Get surface dimensions
        w, h = surface.get_size()
        
        # Find columns that have any opaque pixels
        opaque_columns = {}
        for x in range(w):
            for y in range(h):
                try:
                    pixel = surface.get_at((x, y))
                    if len(pixel) >= 4 and pixel[3] > 0:  # Has alpha and is opaque
                        if x not in opaque_columns:
                            opaque_columns[x] = []
                        opaque_columns[x].append(y)
                except Exception:
                    continue
        
        if not opaque_columns:
            return []
        
        # Group columns into horizontal regions based on gaps
        x_sorted = sorted(opaque_columns.keys())
        regions = []
        region_start = x_sorted[0]
        region_end = x_sorted[0]
        
        for i in range(1, len(x_sorted)):
            if x_sorted[i] - x_sorted[i-1] > min_gap:
                # Gap detected - save current region
                min_y = min(min(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
                max_y = max(max(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
                regions.append(pg.Rect(
                    max(0, region_start - padding),
                    max(0, min_y - padding),
                    min(w - max(0, region_start - padding), region_end - region_start + 1 + 2 * padding),
                    min(h - max(0, min_y - padding), max_y - min_y + 1 + 2 * padding)
                ))
                region_start = x_sorted[i]
            region_end = x_sorted[i]
        
        # Save final region
        min_y = min(min(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
        max_y = max(max(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
        regions.append(pg.Rect(
            max(0, region_start - padding),
            max(0, min_y - padding),
            min(w - max(0, region_start - padding), region_end - region_start + 1 + 2 * padding),
            min(h - max(0, min_y - padding), max_y - min_y + 1 + 2 * padding)
        ))
        
        return regions
        
    except Exception as e:
        # Fallback: return empty list, full blit will be used
        return []

# Tonearm configuration constants - import with fallback for backward compatibility
try:
    from volumio_configfileparser import (
        TONEARM_FILE, TONEARM_PIVOT_SCREEN, TONEARM_PIVOT_IMAGE,
        TONEARM_ANGLE_REST, TONEARM_ANGLE_START, TONEARM_ANGLE_END,
        TONEARM_DROP_DURATION, TONEARM_LIFT_DURATION
    )
except ImportError:
    # Fallback if volumio_configfileparser not updated yet
    TONEARM_FILE = "tonearm.filename"
    TONEARM_PIVOT_SCREEN = "tonearm.pivot.screen"
    TONEARM_PIVOT_IMAGE = "tonearm.pivot.image"
    TONEARM_ANGLE_REST = "tonearm.angle.rest"
    TONEARM_ANGLE_START = "tonearm.angle.start"
    TONEARM_ANGLE_END = "tonearm.angle.end"
    TONEARM_DROP_DURATION = "tonearm.drop.duration"
    TONEARM_LIFT_DURATION = "tonearm.lift.duration"

from volumio_spectrum import SpectrumOutput, init_spectrum_debug

# Optional SVG support for pygame < 2
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except Exception:
    CAIROSVG_AVAILABLE = False

try:
    from PIL import Image, ImageOps, ImageDraw
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Debug logging - controlled by config debug.level setting
# Levels: off, basic, verbose, trace
# When trace enabled, individual component switches control what gets logged
# Writes to /tmp/peppy_debug.log
DEBUG_LOG_FILE = '/tmp/peppy_debug.log'

# Global debug level - will be set from config after parsing
# Default to off until config is loaded
DEBUG_LEVEL_CURRENT = "off"

# Debug trace switches - dict mapping component name to enabled state
# Keys match the config key suffix (e.g., "meters" for debug.trace.meters)
DEBUG_TRACE = {
    "meters": False,
    "spectrum": False,
    "vinyl": False,
    "reel.left": False,
    "reel.right": False,
    "tonearm": False,
    "albumart": False,
    "scrolling": False,
    "volume": False,
    "mute": False,
    "shuffle": False,
    "repeat": False,
    "playstate": False,
    "progress": False,
    "metadata": False,
    "seek": False,
    "time": False,
    "init": False,
    "fade": False,
    "frame": False,
}

# Profiling settings - controlled by config profiling.* settings
# Per-frame timing logs component breakdown to debug log
# cProfile creates /tmp/peppy_profile.prof and /tmp/peppy_profile_summary.txt
PROFILING_TIMING_ENABLED = False
PROFILING_INTERVAL_VALUE = 30
PROFILING_CPROFILE_ENABLED = False
PROFILING_DURATION_VALUE = 60
PROFILING_START_TIME = 0
PROFILING_FRAME_COUNTER = 0
PROFILER = None

def log_debug(msg, level="basic", component=None):
    """Write debug message to log file based on debug level and component switches.
    
    Debug Levels:
    - off: No logging
    - basic: Startup, errors, key state changes
    - verbose: Configuration details (includes basic)
    - trace: Component-specific logging (includes verbose, requires component switch)
    
    :param msg: Message to log
    :param level: Required level - 'basic', 'verbose', or 'trace'
    :param component: For trace level, which component (e.g., 'tonearm', 'meters')
                     Must match a key in DEBUG_TRACE dict
    """
    if DEBUG_LEVEL_CURRENT == "off":
        return
    
    if level == "basic":
        # basic logs at basic, verbose, or trace
        pass
    elif level == "verbose":
        # verbose logs at verbose or trace only
        if DEBUG_LEVEL_CURRENT == "basic":
            return
    elif level == "trace":
        # trace logs only at trace level AND component switch must be on
        if DEBUG_LEVEL_CURRENT != "trace":
            return
        if component and not DEBUG_TRACE.get(component, False):
            return
    
    try:
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def init_debug_config(meter_config_volumio):
    """Initialize debug settings from config. Called after config is parsed."""
    global DEBUG_LEVEL_CURRENT, DEBUG_TRACE
    
    DEBUG_LEVEL_CURRENT = meter_config_volumio.get(DEBUG_LEVEL, "off")
    
    # Load trace switches from config
    trace_key_map = {
        DEBUG_TRACE_METERS: "meters",
        DEBUG_TRACE_SPECTRUM: "spectrum",
        DEBUG_TRACE_VINYL: "vinyl",
        DEBUG_TRACE_REEL_LEFT: "reel.left",
        DEBUG_TRACE_REEL_RIGHT: "reel.right",
        DEBUG_TRACE_TONEARM: "tonearm",
        DEBUG_TRACE_ALBUMART: "albumart",
        DEBUG_TRACE_SCROLLING: "scrolling",
        DEBUG_TRACE_VOLUME: "volume",
        DEBUG_TRACE_MUTE: "mute",
        DEBUG_TRACE_SHUFFLE: "shuffle",
        DEBUG_TRACE_REPEAT: "repeat",
        DEBUG_TRACE_PLAYSTATE: "playstate",
        DEBUG_TRACE_PROGRESS: "progress",
        DEBUG_TRACE_METADATA: "metadata",
        DEBUG_TRACE_SEEK: "seek",
        DEBUG_TRACE_TIME: "time",
        DEBUG_TRACE_INIT: "init",
        DEBUG_TRACE_FADE: "fade",
        DEBUG_TRACE_FRAME: "frame",
    }
    
    for config_key, trace_key in trace_key_map.items():
        DEBUG_TRACE[trace_key] = meter_config_volumio.get(config_key, False)


def init_profiling_config(meter_config_volumio):
    """Initialize profiling settings from config. Called after config is parsed."""
    global PROFILING_TIMING_ENABLED, PROFILING_INTERVAL_VALUE
    global PROFILING_CPROFILE_ENABLED, PROFILING_DURATION_VALUE
    global PROFILING_START_TIME, PROFILER
    
    PROFILING_TIMING_ENABLED = meter_config_volumio.get(PROFILING_TIMING, False)
    PROFILING_INTERVAL_VALUE = meter_config_volumio.get(PROFILING_INTERVAL, 30)
    PROFILING_CPROFILE_ENABLED = meter_config_volumio.get(PROFILING_CPROFILE, False)
    PROFILING_DURATION_VALUE = meter_config_volumio.get(PROFILING_DURATION, 60)
    
    if PROFILING_TIMING_ENABLED:
        log_debug(f"[Profiling] Per-frame timing ENABLED, interval={PROFILING_INTERVAL_VALUE} frames", "basic")
    
    if PROFILING_CPROFILE_ENABLED:
        log_debug(f"[Profiling] cProfile ENABLED, duration={PROFILING_DURATION_VALUE}s", "basic")
        log_debug("[Profiling] WARNING: cProfile adds 10-30% CPU overhead", "basic")
        PROFILER = cProfile.Profile()
        PROFILER.enable()
        PROFILING_START_TIME = time.time()


def stop_profiling():
    """Stop cProfile and save results. Called on exit or after duration expires."""
    global PROFILER, PROFILING_CPROFILE_ENABLED
    
    if PROFILER and PROFILING_CPROFILE_ENABLED:
        PROFILER.disable()
        
        # Save binary profile
        profile_path = '/tmp/peppy_profile.prof'
        PROFILER.dump_stats(profile_path)
        log_debug(f"[Profiling] Profile saved to {profile_path}", "basic")
        
        # Save human-readable summary
        summary_path = '/tmp/peppy_profile_summary.txt'
        try:
            with open(summary_path, 'w') as f:
                f.write("PeppyMeter cProfile Summary\n")
                f.write("=" * 60 + "\n\n")
                f.write("Top 50 functions by cumulative time:\n\n")
                stats = pstats.Stats(PROFILER, stream=f)
                stats.sort_stats('cumulative')
                stats.print_stats(50)
                f.write("\n\nTop 50 functions by total time:\n\n")
                stats.sort_stats('tottime')
                stats.print_stats(50)
            log_debug(f"[Profiling] Summary saved to {summary_path}", "basic")
        except Exception as e:
            log_debug(f"[Profiling] Error saving summary: {e}", "basic")
        
        PROFILER = None
        PROFILING_CPROFILE_ENABLED = False


def check_profiling_duration():
    """Check if cProfile duration has expired. Call each frame."""
    global PROFILING_CPROFILE_ENABLED
    
    if PROFILING_CPROFILE_ENABLED and PROFILING_DURATION_VALUE > 0:
        elapsed = time.time() - PROFILING_START_TIME
        if elapsed >= PROFILING_DURATION_VALUE:
            log_debug(f"[Profiling] Duration limit reached ({PROFILING_DURATION_VALUE}s), stopping cProfile", "basic")
            stop_profiling()


def log_frame_timing(frame_num, t_start, t_meter=None, t_rotation=None, t_blit=None, t_scroll=None, t_end=None):
    """Log per-frame timing breakdown.
    
    If per-component timings are not available (None), only total time is logged.
    For detailed component timing, handlers must be instrumented.
    """
    global PROFILING_FRAME_COUNTER
    
    if not PROFILING_TIMING_ENABLED:
        return
    
    PROFILING_FRAME_COUNTER += 1
    if PROFILING_FRAME_COUNTER % PROFILING_INTERVAL_VALUE != 0:
        return
    
    if t_end is None:
        return
    
    total_ms = (t_end - t_start) * 1000
    
    # Check if we have per-component timing
    if t_meter is not None and t_rotation is not None and t_blit is not None and t_scroll is not None:
        meter_ms = (t_meter - t_start) * 1000
        rot_ms = (t_rotation - t_meter) * 1000
        blit_ms = (t_blit - t_rotation) * 1000
        scroll_ms = (t_scroll - t_blit) * 1000
        other_ms = (t_end - t_scroll) * 1000
        
        log_debug(
            f"[Perf] Frame #{frame_num}: total={total_ms:.1f}ms | "
            f"meter={meter_ms:.1f}ms | rot={rot_ms:.1f}ms | blit={blit_ms:.1f}ms | "
            f"scroll={scroll_ms:.1f}ms | other={other_ms:.1f}ms",
            "basic"
        )
    else:
        # Only total time available
        log_debug(
            f"[Perf] Frame #{frame_num}: total={total_ms:.1f}ms",
            "basic"
        )


# Runtime paths
PeppyRunning = '/tmp/peppyrunning'
CurDir = os.getcwd()
PeppyPath = CurDir + '/screensaver/peppymeter'

# Skin type constants for handler delegation
SKIN_TYPE_CASSETTE = "cassette"
SKIN_TYPE_TURNTABLE = "turntable"
SKIN_TYPE_BASIC = "basic"


def detect_skin_type(mc_vol):
    """
    Detect skin type from meter config for handler delegation.
    
    Priority order:
    1. CASSETTE: Has reels (reel.left.center OR reel.right.center) WITHOUT tonearm
    2. TURNTABLE: Has vinyl.center OR tonearm OR rotating album art, OR single reel + tonearm
    3. BASIC: Everything else (meters only)
    
    :param mc_vol: Volumio meter config dict for current meter
    :return: SKIN_TYPE_CASSETTE, SKIN_TYPE_TURNTABLE, or SKIN_TYPE_BASIC
    """
    has_reel_left = bool(mc_vol.get(REEL_LEFT_CENTER))
    has_reel_right = bool(mc_vol.get(REEL_RIGHT_CENTER))
    has_reels = has_reel_left or has_reel_right
    has_vinyl = bool(mc_vol.get(VINYL_CENTER))
    has_tonearm = bool(mc_vol.get(TONEARM_FILE) and 
                       mc_vol.get(TONEARM_PIVOT_SCREEN) and 
                       mc_vol.get(TONEARM_PIVOT_IMAGE))
    has_rotating_albumart = bool(mc_vol.get(ALBUMART_ROT, False))
    
    # CASSETTE: reels without tonearm or vinyl
    if has_reels and not has_tonearm and not has_vinyl:
        return SKIN_TYPE_CASSETTE
    
    # TURNTABLE: vinyl or tonearm or rotating album art (including edge case: single reel + tonearm)
    if has_vinyl or has_tonearm or has_rotating_albumart:
        return SKIN_TYPE_TURNTABLE
    
    # BASIC: everything else
    return SKIN_TYPE_BASIC


# =============================================================================
# MetadataWatcher - Socket.io listener for pushState events
# =============================================================================
class MetadataWatcher:
    """
    Watches Volumio pushState events via socket.io.
    Updates shared metadata dict and signals title changes for random meter mode.
    Eliminates HTTP polling - state updates are event-driven.
    """
    
    def __init__(self, metadata_dict, title_changed_callback=None, volumio_host='localhost', volumio_port=3000):
        self.metadata = metadata_dict
        self.title_callback = title_changed_callback
        self.volumio_url = f'http://{volumio_host}:{volumio_port}'
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.run_flag = True
        self.thread = None
        self.last_title = None
        self.first_run = True
        
        # Time tracking for countdown (moved here from main loop)
        self.time_remain_sec = -1
        self.time_last_update = 0
        self.time_service = ""
        
        # Queue tracking
        self.queue_array = []  # Full queue array from pushQueue
        self.queue_duration = 0.0  # Cached total queue duration
        self.queue_position = 0  # Current track position in queue
        self._queue_hash = None  # Hash to detect queue changes
        
        # Initialize infinity state (separate from random/shuffle)
        self.metadata["infinity"] = False
    
    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def _run(self):
        # DEBUG: Track previous values for change detection
        _prev_status = ""
        _prev_volatile = False
        _prev_title = ""
        _prev_seek = 0
        _pushstate_count = 0
        
        @self.sio.on('pushState')
        def on_push_state(data):
            nonlocal _prev_status, _prev_volatile, _prev_title, _prev_seek, _pushstate_count
            if not self.run_flag:
                return
            
            # Extract ALL key values
            status = data.get("status", "") or ""
            volatile = data.get("volatile", False) or False
            title = data.get("title", "") or ""
            seek = data.get("seek", 0) or 0
            duration = data.get("duration", 0) or 0
            service = data.get("service", "") or ""
            
            # TRACE: Log EVERY pushState with sequence number and ALL data
            _pushstate_count += 1
            log_debug(f"[pushState #{_pushstate_count}] status={status}, seek={seek}ms ({seek/1000:.1f}s), dur={duration}s, volatile={volatile}, svc={service}, title='{title[:30]}'", "trace", "metadata")
            
            # TRACE: Log when values CHANGE
            if status != _prev_status:
                log_debug(f"[pushState] STATUS CHANGE: '{_prev_status}' -> '{status}'", "trace", "metadata")
                _prev_status = status
            if volatile != _prev_volatile:
                log_debug(f"[pushState] VOLATILE CHANGE: {_prev_volatile} -> {volatile}", "trace", "metadata")
                _prev_volatile = volatile
            if title != _prev_title:
                log_debug(f"[pushState] TITLE CHANGE: '{_prev_title[:20]}' -> '{title[:20]}'", "trace", "metadata")
                _prev_title = title
            if abs(seek - _prev_seek) > 1000:  # >1s seek change
                log_debug(f"[pushState] SEEK CHANGE: {_prev_seek}ms -> {seek}ms (delta={seek - _prev_seek}ms)", "trace", "metadata")
                _prev_seek = seek
            
            # Extract metadata
            self.metadata["artist"] = data.get("artist", "") or ""
            self.metadata["title"] = title
            self.metadata["album"] = data.get("album", "") or ""
            
            # Handle albumart URL - convert relative paths to absolute for remote clients
            albumart = data.get("albumart", "") or ""
            if albumart and not albumart.startswith(('http://', 'https://')):
                # Relative path - prepend Volumio URL for remote access
                albumart = f"{self.volumio_url}{albumart}" if albumart.startswith('/') else f"{self.volumio_url}/{albumart}"
            self.metadata["albumart"] = albumart
            self.metadata["samplerate"] = str(data.get("samplerate", "") or "")
            self.metadata["bitdepth"] = str(data.get("bitdepth", "") or "")
            self.metadata["trackType"] = data.get("trackType", "") or ""
            self.metadata["bitrate"] = str(data.get("bitrate", "") or "")
            self.metadata["service"] = data.get("service", "") or ""
            self.metadata["status"] = status
            self.metadata["volatile"] = volatile
            
            # Update queue position if available
            position = data.get("position")
            if position is not None:
                self.queue_position = int(position)
                self.metadata["queue_position"] = self.queue_position
            
            # Playback control states (for indicators)
            self.metadata["volume"] = data.get("volume", 0) or 0
            self.metadata["mute"] = data.get("mute", False) or False
            self.metadata["random"] = data.get("random", False) or False
            self.metadata["repeat"] = data.get("repeat", False) or False
            self.metadata["repeatSingle"] = data.get("repeatSingle", False) or False
            
            # Update time tracking
            import time
            service = data.get("service", "")
            
            # Store duration and seek for progress calculation (tonearm, etc)
            self.metadata["duration"] = duration
            self.metadata["seek"] = seek
            self.metadata["_seek_raw"] = seek  # Original value, never modified by render loop
            self.metadata["_seek_update"] = time.time()  # Track when seek was received
            
            # Always update time remaining from actual seek position
            # This ensures pause/stop shows correct frozen time
            if duration > 0:
                self.time_remain_sec = max(0, duration - (seek // 1000))
                self.time_last_update = time.time()
                self.time_service = service
            elif service != self.time_service:
                # Service changed to one without duration (webradio)
                self.time_remain_sec = -1
                self.time_last_update = time.time()
                self.time_service = service
            
            self.metadata["_time_remain"] = self.time_remain_sec
            self.metadata["_time_update"] = self.time_last_update
            
            # Store queue calculations in metadata
            queue_mode = self.metadata.get("_queue_mode", "track")  # Will be set by main loop
            if queue_mode == "queue":
                queue_info = self.calculate_queue_progress(
                    seek, 
                    duration, 
                    volatile=volatile
                )
                if queue_info:
                    self.metadata["queue_progress_pct"] = queue_info['progress_pct']
                    self.metadata["queue_duration"] = queue_info['duration']
                    self.metadata["queue_time_remaining"] = queue_info['time_remaining']
                else:
                    # Fall back to track mode
                    self.metadata["queue_progress_pct"] = None
                    self.metadata["queue_duration"] = None
                    self.metadata["queue_time_remaining"] = None
            else:
                self.metadata["queue_progress_pct"] = None
                self.metadata["queue_duration"] = None
                self.metadata["queue_time_remaining"] = None
            
            # Check for title change (for random meter mode)
            current_title = self.metadata["title"]
            if self.title_callback and current_title != self.last_title:
                self.last_title = current_title
                if not self.first_run:
                    self.title_callback()
                self.first_run = False
        
        @self.sio.on('pushInfinityPlayback')
        def on_push_infinity(data):
            """Handle infinity playback state updates."""
            if not self.run_flag:
                return
            if data and isinstance(data, dict):
                self.metadata["infinity"] = data.get("enabled", False)
        
        @self.sio.on('pushQueue')
        def on_push_queue(queue_data):
            """Handle queue updates from Volumio."""
            nonlocal _pushstate_count
            
            if not isinstance(queue_data, list):
                return
            
            # Calculate hash to detect changes
            queue_str = json.dumps(queue_data, sort_keys=True)
            queue_hash = hashlib.md5(queue_str.encode()).hexdigest()
            
            # Only recalculate if queue actually changed
            if queue_hash != self._queue_hash:
                self._queue_hash = queue_hash
                self.queue_array = queue_data
                
                # Calculate total queue duration (sum of all track durations)
                self.queue_duration = sum(
                    float(track.get('duration', 0) or 0) 
                    for track in queue_data
                )
                
                log_debug(f"[pushQueue] Updated: {len(queue_data)} tracks, total_duration={self.queue_duration:.1f}s", "trace", "metadata")
        
        @self.sio.on('connect')
        def on_connect():
            if self.run_flag:
                self.sio.emit('getState')
                self.sio.emit('getInfinityPlayback')
                self.sio.emit('getQueue')
        
        # Socket connection loop - must be at end of _run() method
        while self.run_flag:
            try:
                self.sio.connect(self.volumio_url, transports=['websocket'])
                while self.run_flag and self.sio.connected:
                    self.sio.sleep(0.5)
            except Exception as e:
                print(f"MetadataWatcher connect error: {e}")
                import time
                time.sleep(1)  # Retry delay
            finally:
                if self.sio.connected:
                    try:
                        self.sio.disconnect()
                    except Exception:
                        pass
    
    def calculate_queue_progress(self, current_seek_ms, current_duration, volatile=False):
        """Calculate queue progress percentage.
        
        :param current_seek_ms: Current track seek position in milliseconds
        :param current_duration: Current track duration in seconds
        :param volatile: Whether current source is volatile (webstream)
        :return: dict with progress_pct, duration, time_remaining or None if not applicable
        """
        # If queue is empty or invalid, return None (will fall back to track mode)
        if not self.queue_array or len(self.queue_array) == 0:
            return None
        
        # For volatile sources (webstreams), use track mode even if queue exists
        if volatile:
            return None
        
        # If queue duration is 0 (all tracks have no duration), fall back to track mode
        if self.queue_duration <= 0:
            return None
        
        # If current track has no duration, only valid for volatile (already handled above)
        # But double-check: if current track missing duration and not volatile, can't calculate
        if current_duration <= 0:
            return None
        
        # Calculate completed duration (sum of durations before current position)
        completed_duration = 0.0
        for i in range(self.queue_position):
            if i < len(self.queue_array):
                track_dur = float(self.queue_array[i].get('duration', 0) or 0)
                completed_duration += track_dur
        
        # Add current track progress
        current_progress_sec = current_seek_ms / 1000.0
        total_progress_sec = completed_duration + current_progress_sec
        
        # Calculate percentage
        queue_progress_pct = min(100.0, (total_progress_sec / self.queue_duration) * 100.0)
        
        # Calculate time remaining in queue
        queue_time_remaining = max(0.0, self.queue_duration - total_progress_sec)
        
        return {
            'progress_pct': queue_progress_pct,
            'duration': self.queue_duration,
            'time_remaining': queue_time_remaining
        }
    
    def stop(self):
        self.run_flag = False
        if self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass


# =============================================================================
# NetworkLevelServer - Broadcasts audio levels over UDP for remote displays
# =============================================================================
class NetworkLevelServer:
    """
    Broadcasts audio level data over UDP for remote display clients.
    
    Packet format (16 bytes, little-endian):
        - seq (uint32): Sequence number for loss detection
        - left (float32): Left channel level (0-100)
        - right (float32): Right channel level (0-100)
        - mono (float32): Mono level (0-100)
    
    Modes:
        - 'local': Server disabled, normal local display only
        - 'server': Server enabled, no local display (headless)
        - 'server_local': Server enabled AND local display
    """
    
    def __init__(self, port=5580, enabled=True):
        """Initialize the level server.
        
        :param port: UDP port to broadcast on (default 5580)
        :param enabled: Whether broadcasting is enabled
        """
        self.port = port
        self.enabled = enabled
        self.seq = 0
        self.sock = None
        self._last_error_time = 0
        
        if self.enabled:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                # Set non-blocking to avoid stalling the render loop
                self.sock.setblocking(False)
                log_debug(f"[NetworkLevelServer] Started on UDP port {port}", "basic")
            except Exception as e:
                log_debug(f"[NetworkLevelServer] Failed to create socket: {e}", "basic")
                self.sock = None
                self.enabled = False
    
    def broadcast(self, left, right, mono):
        """Broadcast current level data to all clients.
        
        :param left: Left channel level (0-100)
        :param right: Right channel level (0-100)
        :param mono: Mono level (0-100)
        """
        if not self.enabled or not self.sock:
            return
        
        # Guard against None values (can occur during meter transitions or when data source has no data)
        if left is None or right is None or mono is None:
            return
        
        try:
            # Pack as: sequence (uint32) + 3 floats (left, right, mono)
            data = struct.pack('<Ifff', self.seq, float(left), float(right), float(mono))
            self.sock.sendto(data, ('<broadcast>', self.port))
            self.seq = (self.seq + 1) & 0xFFFFFFFF  # Wrap at 32-bit
        except BlockingIOError:
            # Non-blocking socket would block - skip this frame
            pass
        except Exception as e:
            # Rate-limit error logging
            now = time.time()
            if now - self._last_error_time > 10:
                log_debug(f"[NetworkLevelServer] Broadcast error: {e}", "basic")
                self._last_error_time = now
    
    def stop(self):
        """Stop the server and close the socket."""
        self.enabled = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        log_debug("[NetworkLevelServer] Stopped", "basic")


# =============================================================================
# NetworkSpectrumServer - Broadcasts spectrum FFT data for remote displays
# =============================================================================
class NetworkSpectrumServer:
    """
    Broadcasts spectrum analyzer data over UDP for remote display clients.
    
    Supports two modes:
    - Standalone (read_pipe=True): Reads FFT data directly from the spectrum pipe.
      Use this in 'server' mode where there's no local display.
    - Injected (read_pipe=False): Receives data via set_bins() from SpectrumOutput.
      Use this in 'server_local' mode to avoid pipe contention with local Spectrum.
    
    Packet format (variable size, little-endian):
        - seq (uint32): Sequence number for loss detection
        - size (uint16): Number of frequency bins
        - bins (float32 * size): Frequency bin values (0-100)
    
    Default spectrum_size is 20 bins (matching peppyalsa default).
    """
    
    SPECTRUM_PIPE_PATH = '/tmp/myfifosa'
    
    def __init__(self, port=5581, enabled=True, spectrum_size=20, read_pipe=True):
        """Initialize the spectrum server.
        
        :param port: UDP port to broadcast on (default 5581)
        :param enabled: Whether broadcasting is enabled
        :param spectrum_size: Number of frequency bins (default 20)
        :param read_pipe: If True, read from pipe directly; if False, use set_bins()
        """
        self.port = port
        self.enabled = enabled
        self.spectrum_size = spectrum_size
        self.read_pipe = read_pipe
        self.seq = 0
        self.sock = None
        self.pipe = None
        self._last_error_time = 0
        self._first_broadcast_logged = False
        self._pipe_size = 4 * spectrum_size  # 4 bytes per bin (int32)
        self._injected_bins = None  # For injected mode
        self._switched_to_pipe = False  # Track if we switched from injected to pipe mode
        
        if self.enabled:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.sock.setblocking(False)
                mode_str = "pipe" if read_pipe else "injected"
                log_debug(f"[NetworkSpectrumServer] Started on UDP port {port}, size={spectrum_size}, mode={mode_str}", "basic")
            except Exception as e:
                log_debug(f"[NetworkSpectrumServer] Failed to create socket: {e}", "basic")
                self.sock = None
                self.enabled = False
            
            # Only open pipe in standalone mode
            if read_pipe:
                self._open_pipe()
    
    def _open_pipe(self):
        """Open the spectrum pipe for reading."""
        try:
            if os.path.exists(self.SPECTRUM_PIPE_PATH):
                self.pipe = os.open(self.SPECTRUM_PIPE_PATH, os.O_RDONLY | os.O_NONBLOCK)
                log_debug(f"[NetworkSpectrumServer] Opened pipe: {self.SPECTRUM_PIPE_PATH}", "basic")
            else:
                log_debug(f"[NetworkSpectrumServer] Pipe not found: {self.SPECTRUM_PIPE_PATH}", "basic")
        except Exception as e:
            log_debug(f"[NetworkSpectrumServer] Failed to open pipe: {e}", "basic")
            self.pipe = None
    
    def _read_pipe_data(self):
        """Read latest FFT data from the spectrum pipe.
        
        :return: List of frequency bin values, or None if no data
        """
        if self.pipe is None:
            # Try to open pipe if it wasn't available at startup
            if os.path.exists(self.SPECTRUM_PIPE_PATH):
                self._open_pipe()
            if self.pipe is None:
                return None
        
        try:
            # Read all available data, keep only the latest frame
            data = None
            while True:
                try:
                    tmp_data = os.read(self.pipe, self._pipe_size)
                    if len(tmp_data) == self._pipe_size:
                        data = tmp_data
                    else:
                        break
                except BlockingIOError:
                    break
            
            if data is None:
                return None
            
            # Unpack as int32 values (same format peppyalsa writes)
            # Each bin is a 4-byte little-endian integer
            bins = []
            for i in range(self.spectrum_size):
                offset = i * 4
                val = data[offset] + (data[offset + 1] << 8) + (data[offset + 2] << 16) + (data[offset + 3] << 24)
                bins.append(float(val))
            
            return bins
            
        except Exception as e:
            now = time.time()
            if now - self._last_error_time > 10:
                log_debug(f"[NetworkSpectrumServer] Pipe read error: {e}", "basic")
                self._last_error_time = now
            return None
    
    def set_bins(self, bins):
        """Set spectrum bins for injected mode (called by SpectrumOutput).
        
        :param bins: List of frequency bin values
        """
        self._injected_bins = bins
    
    def broadcast(self):
        """Broadcast spectrum data to all clients.
        
        In pipe mode, reads from pipe. In injected mode, uses set_bins() data.
        """
        if not self.enabled or not self.sock:
            return
        
        # Get bins based on mode
        if self.read_pipe:
            bins = self._read_pipe_data()
        else:
            # In injected mode, keep broadcasting last known data
            # Don't clear - this ensures consistent data even if set_bins()
            # isn't called every frame
            bins = self._injected_bins
        
        if bins is None:
            return
        
        try:
            # Pack as: sequence (uint32) + size (uint16) + bins (float32 * size)
            num_bins = len(bins)
            fmt = '<IH' + str(num_bins) + 'f'
            data = struct.pack(fmt, self.seq, num_bins, *bins)
            self.sock.sendto(data, ('<broadcast>', self.port))
            self.seq = (self.seq + 1) & 0xFFFFFFFF
            
            # Log first successful broadcast
            if not self._first_broadcast_logged:
                log_debug(f"[NetworkSpectrumServer] First broadcast: {num_bins} bins", "basic")
                self._first_broadcast_logged = True
                
        except BlockingIOError:
            pass
        except Exception as e:
            now = time.time()
            if now - self._last_error_time > 10:
                log_debug(f"[NetworkSpectrumServer] Broadcast error: {e}", "basic")
                self._last_error_time = now
    
    def stop(self):
        """Stop the server and close resources."""
        self.enabled = False
        if self.pipe is not None:
            try:
                os.close(self.pipe)
            except Exception:
                pass
            self.pipe = None
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        log_debug("[NetworkSpectrumServer] Stopped", "basic")


# =============================================================================
# DiscoveryAnnouncer - Broadcasts server presence for client discovery
# =============================================================================
class DiscoveryAnnouncer:
    """
    Periodically broadcasts server presence for client auto-discovery.
    
    Announcement format (JSON):
        {
            "service": "peppy_level_server",
            "version": 1,
            "level_port": 5580,
            "spectrum_port": 5581,
            "volumio_port": 3000,
            "hostname": "volumio",
            "config_version": "a1b2c3d4"
        }
    
    Clients can listen on the discovery port to find available servers
    without needing to know the IP address in advance. The config_version
    field changes when server configuration changes, allowing clients to
    detect and re-fetch updated config.
    """
    
    def __init__(self, discovery_port=5579, level_port=5580, spectrum_port=5581,
                 volumio_port=3000, interval=5.0, enabled=True, config_path=None):
        """Initialize the discovery announcer.
        
        :param discovery_port: UDP port for discovery broadcasts (default 5579)
        :param level_port: Level data port to advertise (default 5580)
        :param spectrum_port: Spectrum data port to advertise (default 5581)
        :param volumio_port: Volumio socket.io port to advertise (default 3000)
        :param interval: Seconds between announcements (default 5.0)
        :param enabled: Whether announcements are enabled
        :param config_path: Path to config.txt for version hashing
        """
        self.discovery_port = discovery_port
        self.level_port = level_port
        self.spectrum_port = spectrum_port
        self.volumio_port = volumio_port
        self.interval = interval
        self.enabled = enabled
        self.config_path = config_path
        self.run_flag = False
        self.thread = None
        self.sock = None
        self._config_version = ""
        self._last_config_check = 0
        self._config_check_interval = 5.0  # Check config every 5 seconds
        
        # Get hostname
        try:
            self.hostname = socket.gethostname()
        except Exception:
            self.hostname = "volumio"
        
        # Calculate initial config version
        self._update_config_version()
    
    def _update_config_version(self):
        """Calculate MD5 hash of config file for version tracking."""
        if not self.config_path:
            return
        
        try:
            import hashlib
            with open(self.config_path, 'rb') as f:
                content = f.read()
            new_hash = hashlib.md5(content).hexdigest()[:8]
            if new_hash != self._config_version:
                self._config_version = new_hash
                log_debug(f"[DiscoveryAnnouncer] Config version: {self._config_version}", "verbose")
        except Exception as e:
            log_debug(f"[DiscoveryAnnouncer] Config hash error: {e}", "verbose")
    
    def _build_announcement(self):
        """Build the announcement payload with current config version."""
        return json.dumps({
            "service": "peppy_level_server",
            "version": 1,
            "level_port": self.level_port,
            "spectrum_port": self.spectrum_port,
            "volumio_port": self.volumio_port,
            "hostname": self.hostname,
            "config_version": self._config_version
        }).encode('utf-8')
    
    def start(self):
        """Start the announcer thread."""
        if not self.enabled:
            return
        
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.run_flag = True
            self.thread = Thread(target=self._run, daemon=True)
            self.thread.start()
            log_debug(f"[DiscoveryAnnouncer] Started on UDP port {self.discovery_port}, "
                     f"announcing level_port={self.level_port}", "basic")
        except Exception as e:
            log_debug(f"[DiscoveryAnnouncer] Failed to start: {e}", "basic")
            self.enabled = False
    
    def _run(self):
        """Thread loop - broadcast announcements periodically."""
        while self.run_flag:
            # Periodically re-check config version
            now = time.time()
            if now - self._last_config_check > self._config_check_interval:
                self._update_config_version()
                self._last_config_check = now
            
            try:
                announcement = self._build_announcement()
                self.sock.sendto(announcement, ('<broadcast>', self.discovery_port))
            except Exception as e:
                log_debug(f"[DiscoveryAnnouncer] Send error: {e}", "verbose")
            
            # Sleep in small increments to allow faster shutdown
            sleep_remaining = self.interval
            while sleep_remaining > 0 and self.run_flag:
                time.sleep(min(0.5, sleep_remaining))
                sleep_remaining -= 0.5
    
    def stop(self):
        """Stop the announcer thread."""
        self.run_flag = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        log_debug("[DiscoveryAnnouncer] Stopped", "basic")


# =============================================================================
# ScrollingLabel - Replaces TextAnimator threads
# =============================================================================
class ScrollingLabel:
    """Single-threaded scrolling text label with bidirectional scroll and self-backing."""
    
    def __init__(self, font, color, pos, box_width, center=False,
                 speed_px_per_sec=40, pause_ms=400):
        self.font = font
        self.color = color
        self.pos = pos
        self.box_width = int(box_width or 0)
        self.center = bool(center)
        self.speed = float(speed_px_per_sec)
        self.pause_ms = int(pause_ms)
        self.text = ""
        self.surf = None
        self.text_w = 0
        self.text_h = 0
        self.offset = 0.0
        self.direction = 1
        self._last_time = pg.time.get_ticks()
        self._pause_until = 0
        self._backing = None
        self._backing_rect = None
        # OPTIMIZATION: Track if redraw needed
        self._needs_redraw = True
        self._last_draw_offset = -1

    def capture_backing(self, surface):
        """Capture backing surface for this label's area."""
        if not self.pos or self.box_width <= 0:
            return
        x, y = self.pos
        # Use linesize for full height including descenders
        height = self.font.get_linesize()
        self._backing_rect = pg.Rect(x, y, self.box_width, height)
        try:
            self._backing = surface.subsurface(self._backing_rect).copy()
        except Exception:
            self._backing = pg.Surface((self._backing_rect.width, self._backing_rect.height))
            self._backing.fill((0, 0, 0))
        
        # TRACE: Log backing capture
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] CAPTURE: pos={self.pos}, box_w={self.box_width}, backing_rect={self._backing_rect}", "trace", "scrolling")

    def update_text(self, new_text):
        """Update text content, reset scroll position if changed."""
        new_text = new_text or ""
        if new_text == self.text and self.surf is not None:
            return False  # No change
        old_text = self.text
        self.text = new_text
        self.surf = self.font.render(self.text, True, self.color)
        self.text_w, self.text_h = self.surf.get_size()
        self.offset = 0.0
        self.direction = 1
        self._pause_until = 0
        self._last_time = pg.time.get_ticks()
        self._needs_redraw = True
        self._last_draw_offset = -1
        
        # TRACE: Log text update
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] UPDATE: text='{new_text[:30]}', text_w={self.text_w}, box_w={self.box_width}, scrolls={self.text_w > self.box_width}", "trace", "scrolling")
        
        return True  # Changed

    def force_redraw(self):
        """Force redraw on next draw() call."""
        self._needs_redraw = True
        self._last_draw_offset = -1
        
        # TRACE: Log force redraw
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] FORCE: text='{self.text[:20]}...', pos={self.pos}", "trace", "scrolling")

    def draw(self, surface):
        """Draw label, handling scroll animation with self-backing.
        Returns dirty rect if drawn, None if skipped."""
        if not self.surf or not self.pos or self.box_width <= 0:
            return None
        
        x, y = self.pos
        box_rect = pg.Rect(x, y, self.box_width, self.text_h)
        
        # Text fits - no scrolling needed
        if self.text_w <= self.box_width:
            # OPTIMIZATION: Only redraw if text changed
            if not self._needs_redraw:
                return None
            
            # TRACE: Log static text draw
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
                log_debug(f"[Scrolling] STATIC: text='{self.text[:20]}...', pos={self.pos}, box_w={self.box_width}, text_w={self.text_w}", "trace", "scrolling")
            
            # Restore backing before drawing (prevents artifacts)
            if self._backing and self._backing_rect:
                surface.blit(self._backing, self._backing_rect.topleft)
            
            if self.center and self.box_width > 0:
                left = box_rect.x + (self.box_width - self.text_w) // 2
                surface.blit(self.surf, (left, box_rect.y))
            else:
                surface.blit(self.surf, (box_rect.x, box_rect.y))
            self._needs_redraw = False
            
            dirty = self._backing_rect.copy() if self._backing_rect else box_rect.copy()
            
            # TRACE: Log static draw output
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
                log_debug(f"[Scrolling] OUTPUT: static, dirty_rect={dirty}", "trace", "scrolling")
            
            return dirty
        
        # Scrolling text - check if offset changed enough to warrant redraw
        now = pg.time.get_ticks()
        dt = (now - self._last_time) / 1000.0
        self._last_time = now
        
        # Calculate new offset
        if now >= self._pause_until:
            limit = max(0, self.text_w - self.box_width)
            self.offset += self.direction * self.speed * dt
            
            if self.offset <= 0:
                self.offset = 0
                self.direction = 1
                self._pause_until = now + self.pause_ms
            elif self.offset >= limit:
                self.offset = float(limit)
                self.direction = -1
                self._pause_until = now + self.pause_ms
        
        # OPTIMIZATION: Only redraw if offset changed by at least 1 pixel
        current_offset_int = int(self.offset)
        if current_offset_int == self._last_draw_offset and not self._needs_redraw:
            return None
        
        # TRACE: Log scrolling text draw
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] SCROLL: text='{self.text[:20]}...', offset={current_offset_int}, forced={self._needs_redraw}, backing={self._backing_rect}", "trace", "scrolling")
        
        # Restore backing before drawing (prevents artifacts)
        if self._backing and self._backing_rect:
            surface.blit(self._backing, self._backing_rect.topleft)
        
        # Draw scrolling text
        prev_clip = surface.get_clip()
        surface.set_clip(box_rect)
        draw_x = box_rect.x - current_offset_int
        surface.blit(self.surf, (draw_x, box_rect.y))
        surface.set_clip(prev_clip)
        
        self._last_draw_offset = current_offset_int
        self._needs_redraw = False
        
        dirty = self._backing_rect.copy() if self._backing_rect else box_rect.copy()
        
        # TRACE: Log draw output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] OUTPUT: dirty_rect={dirty}", "trace", "scrolling")
        
        return dirty


# =============================================================================
# Album Art Renderer (round cover + optional LP rotation)
# =============================================================================
# Rotation quality presets (FPS, step_degrees):
#   low:    4 FPS, 12 deg step (30 frames, choppy, lowest CPU)
#   medium: 8 FPS, 6 deg step (60 frames, balanced) - default
#   high:   15 FPS, 3 deg step (120 frames, smooth, higher CPU)
#   custom: uses rotation.fps from config
ROTATION_PRESETS = {
    "low":    (4, 12),
    "medium": (8, 6),
    "high":   (15, 3),
}

# Default values (will be overridden by config)
ROTATE_TARGET_FPS = 8
ROTATE_STEP_DEG = 6
USE_PRECOMPUTED_FRAMES = True

def get_rotation_params(quality, custom_fps=8):
    """Get rotation FPS and step degrees based on quality setting.
    
    :param quality: 'low', 'medium', 'high', or 'custom'
    :param custom_fps: FPS to use when quality is 'custom'
    :return: (fps, step_degrees)
    """
    if quality == "custom":
        # Higher FPS needs smaller step for smooth rotation
        # Maintain roughly constant fps*step product (~45) like presets:
        #   low:    4 fps * 12 step = 48
        #   medium: 8 fps *  6 step = 48
        #   high:  15 fps *  3 step = 45
        # So step = 45 / fps, clamped to reasonable range
        step = max(1, min(12, int(45 / max(1, custom_fps))))
        return (custom_fps, step)
    return ROTATION_PRESETS.get(quality, ROTATION_PRESETS["medium"])

class AlbumArtRenderer:
    """
    Handles album art loading, optional file mask or circular crop,
    scaling, rotation (LP-style), and drawing with optional circular border.
    Rotation is optional and disabled if config params are missing.
    
    OPTIMIZATION: Pre-computes rotation frames and uses FPS gating for CPU reduction.
    """

    def __init__(self, base_path, meter_folder, art_pos, art_dim, screen_size,
                 font_color=(255, 255, 255), border_width=0,
                 mask_filename=None, rotate_enabled=False, rotate_rpm=0.0,
                 angle_step_deg=0.5, spindle_radius=5, ring_radius=None,
                 circle=True, rotation_fps=8, rotation_step=6, speed_multiplier=1.0,
                 vinyl_renderer=None):
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.art_pos = art_pos
        self.art_dim = art_dim
        self.screen_size = screen_size
        self.font_color = font_color
        self.border_width = border_width
        self.mask_filename = mask_filename
        self.rotate_enabled = bool(rotate_enabled)
        self.rotate_rpm = float(rotate_rpm) * float(speed_multiplier)  # Apply speed multiplier
        self.angle_step_deg = float(angle_step_deg)
        self.spindle_radius = max(1, int(spindle_radius))
        self.ring_radius = ring_radius or max(3, min(art_dim[0], art_dim[1]) // 10)
        self.circle = bool(circle)
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)

        # Vinyl coupling (for turntable skins)
        self.vinyl_renderer = vinyl_renderer

        # Derived center
        self.art_center = (int(art_pos[0] + art_dim[0] // 2),
                           int(art_pos[1] + art_dim[1] // 2)) if (art_pos and art_dim) else None

        # Runtime cache
        self._requests = requests.Session()
        self._current_url = None
        self._scaled_surf = None
        self._rot_frames = None  # OPTIMIZATION: Pre-computed rotation frames
        self._current_angle = 0.0
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        # OPTIMIZATION: Track if redraw needed
        self._needs_redraw = True
        self._need_first_blit = False

        # Mask path (if provided)
        self._mask_path = None
        if self.mask_filename:
            self._mask_path = os.path.join(self.base_path, self.meter_folder, self.mask_filename)

        # Compute backing rect (extended for rotation)
        self._backing_rect = None
        self._backing_surf = None

    def _apply_mask_with_pil(self, img_bytes):
        """Load via PIL, apply file mask or circular mask; return pygame surface."""
        try:
            pil_img = Image.open(img_bytes).convert("RGBA")
            pil_img = pil_img.resize(self.art_dim)

            # Provided mask file takes precedence
            if self._mask_path and os.path.exists(self._mask_path):
                mask = Image.open(self._mask_path).convert('L')
                if mask.size != pil_img.size:
                    mask = mask.resize(pil_img.size)
                pil_img.putalpha(ImageOps.invert(mask))
            # Otherwise circular crop if enabled
            elif self.circle:
                mask = Image.new('L', pil_img.size, 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, pil_img.size[0], pil_img.size[1]), fill=255)
                pil_img.putalpha(mask)

            return pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
        except Exception:
            return None

    def _load_surface_from_bytes(self, img_bytes):
        """Load pygame surface directly from bytes (no mask)."""
        try:
            surf = pg.image.load(img_bytes).convert_alpha()
        except Exception:
            try:
                img_bytes.seek(0)
                surf = pg.image.load(img_bytes).convert()
            except Exception:
                surf = None
        return surf

    def load_from_url(self, url):
        """Fetch image from URL, build scaled surface, pre-compute rotation frames."""
        self._current_url = url
        self._scaled_surf = None
        self._rot_frames = None
        self._current_angle = 0.0
        self._needs_redraw = True
        self._need_first_blit = False

        if not url:
            return

        try:
            real_url = url if not url.startswith("/") else f"http://localhost:3000{url}"
            resp = self._requests.get(real_url, timeout=3)
            if not (resp.ok and "image" in resp.headers.get("Content-Type", "").lower()):
                return

            img_bytes = io.BytesIO(resp.content)

            # Prefer PIL to handle mask/circle
            surf = None
            if PIL_AVAILABLE:
                surf = self._apply_mask_with_pil(img_bytes)

            # Fallback when PIL not available
            if surf is None:
                surf = self._load_surface_from_bytes(img_bytes)

            if surf:
                try:
                    scaled = pg.transform.smoothscale(surf, self.art_dim)
                except Exception:
                    scaled = pg.transform.scale(surf, self.art_dim)
                
                # Ensure scaled surface has proper alpha channel
                try:
                    self._scaled_surf = scaled.convert_alpha()
                except Exception:
                    self._scaled_surf = scaled
                
                # OPTIMIZATION: Pre-compute all rotation frames on load
                if USE_PRECOMPUTED_FRAMES and self.rotate_enabled and self.rotate_rpm > 0.0 and self._scaled_surf:
                    try:
                        self._rot_frames = [
                            pg.transform.rotate(self._scaled_surf, -a)
                            for a in range(0, 360, self.rotation_step)
                        ]
                    except Exception:
                        self._rot_frames = None
                
                self._need_first_blit = True

        except Exception:
            pass  # Silent fail
    
    def check_pending_load(self):
        """Compatibility stub - sync loading has no pending loads."""
        return False

    def _update_angle(self, status, now_ticks, volatile=False):
        """Update rotation angle based on RPM and playback status.
        
        OPTIMIZATION: Only updates at target FPS rate.
        
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        # Ignore stop/pause during volatile transitions (track skip)
        if volatile and status in ("stop", "pause"):
            status = "play"
        if status == "play":
            # degrees per second = rpm * 6
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0

    def will_blit(self, now_ticks):
        """Check if rotation blit is needed (FPS gating)."""
        if self._scaled_surf is None:
            return False
        if self._need_first_blit:
            # TRACE: Log first blit decision
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
                log_debug(f"[AlbumArt] DECISION: will_blit=True (first_blit)", "trace", "albumart")
            return True
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        
        result = (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        # TRACE: Log will_blit decision (only when true to reduce noise)
        if result and DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
            log_debug(f"[AlbumArt] DECISION: will_blit=True, angle={self._current_angle:.1f}, rotate_enabled={self.rotate_enabled}", "trace", "albumart")
        
        return result

    def get_backing_rect(self):
        """Get backing rect for this renderer, extended for rotation if needed."""
        if not self.art_pos or not self.art_dim:
            return None
        
        if self.rotate_enabled and self.rotate_rpm > 0.0:
            # Rotated bounding box = diagonal = side * sqrt(2), clamped to screen
            diag = int(max(self.art_dim[0], self.art_dim[1]) * math.sqrt(2)) + 2
            center_x = self.art_pos[0] + self.art_dim[0] // 2
            center_y = self.art_pos[1] + self.art_dim[1] // 2
            ext_x = max(0, center_x - diag // 2)
            ext_y = max(0, center_y - diag // 2)
            # Clamp to screen bounds
            ext_w = min(diag, self.screen_size[0] - ext_x)
            ext_h = min(diag, self.screen_size[1] - ext_y)
            return pg.Rect(ext_x, ext_y, ext_w, ext_h)
        else:
            return pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

    def render(self, screen, status, now_ticks, advance_angle=True, volatile=False):
        """Render album art (rotated if enabled) plus border and LP center markers.
        
        OPTIMIZATION: FPS gating limits rotation updates to reduce CPU.
        Returns dirty rect if drawn, None if skipped.
        
        :param screen: pygame screen surface
        :param status: playback status ("play", "pause", "stop")
        :param now_ticks: pygame.time.get_ticks() value
        :param advance_angle: if False, render at current angle without advancing rotation
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if not self.art_pos or not self.art_dim or not self._scaled_surf:
            return None

        # FPS gating: skip if not time to blit yet (unless advance_angle=False which forces render)
        if advance_angle and not self.will_blit(now_ticks):
            return None

        # TRACE: Log render input
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
            coupled = "vinyl-coupled" if self.vinyl_renderer else "independent"
            log_debug(f"[AlbumArt] INPUT: status={status}, angle={self._current_angle:.1f}, advance={advance_angle}, {coupled}", "trace", "albumart")

        dirty_rect = None
        # Only update timing when advancing (so tonearm redraws don't reset album art's FPS schedule)
        if advance_angle:
            self._last_blit_tick = now_ticks

        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0:
            # Update angle based on playback status (only if advancing)
            if advance_angle:
                # If coupled to vinyl, use vinyl's angle
                if self.vinyl_renderer:
                    self._current_angle = self.vinyl_renderer.get_current_angle()
                else:
                    self._update_angle(status, now_ticks, volatile=volatile)
            
            # OPTIMIZATION: Use pre-computed frame lookup if available
            if self._rot_frames:
                idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
                rot = self._rot_frames[idx]
            else:
                # Fallback: real-time rotation
                try:
                    rot = pg.transform.rotate(self._scaled_surf, -self._current_angle)
                except Exception:
                    rot = pg.transform.rotate(self._scaled_surf, int(-self._current_angle))
            
            if rot:
                rot_rect = rot.get_rect(center=self.art_center)
                screen.blit(rot, rot_rect.topleft)
                dirty_rect = self.get_backing_rect()
            else:
                screen.blit(self._scaled_surf, self.art_pos)
                dirty_rect = pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])
        else:
            # Rotation disabled or parameters missing - static
            screen.blit(self._scaled_surf, self.art_pos)
            dirty_rect = pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

        self._needs_redraw = False
        self._need_first_blit = False

        # Border: circle if cover is round; else rect
        if self.border_width and dirty_rect:
            try:
                if self.circle and self.art_center:
                    rad = min(self.art_dim[0], self.art_dim[1]) // 2
                    pg.draw.circle(screen, self.font_color, self.art_center, rad, self.border_width)
                else:
                    pg.draw.rect(screen, self.font_color, pg.Rect(self.art_pos, self.art_dim), self.border_width)
            except Exception:
                pass

        # LP center markers (spindle + inner thin ring)
        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0 and dirty_rect:
            try:
                pg.draw.circle(screen, self.font_color, self.art_center, self.spindle_radius, 0)
                pg.draw.circle(screen, self.font_color, self.art_center, self.ring_radius, 1)
            except Exception:
                pass

        # TRACE: Log render output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
            mode = "rotating" if (self.rotate_enabled and self.rotate_rpm > 0.0) else "static"
            frame_info = f"frame_idx={idx}" if (self.rotate_enabled and self._rot_frames) else ""
            log_debug(f"[AlbumArt] OUTPUT: {mode}, angle={self._current_angle:.1f}, {frame_info}, rect={dirty_rect}", "trace", "albumart")

        return dirty_rect


# =============================================================================
# Reel Renderer (for cassette skins with rotating reels)
# =============================================================================
class ReelRenderer:
    """
    Handles file-based reel graphics with rotation for cassette-style skins.
    Simpler than AlbumArtRenderer - no URL fetching, masks, or borders.
    Loads PNG file once and rotates based on playback status.
    
    OPTIMIZATION: Pre-computes rotation frames and uses FPS gating for CPU reduction.
    """

    def __init__(self, base_path, meter_folder, filename, pos, center, 
                 rotate_rpm=1.5, angle_step_deg=1.0, rotation_fps=8, rotation_step=6,
                 speed_multiplier=1.0, direction="ccw", name="reel"):
        """
        Initialize reel renderer.
        
        :param base_path: Base path for meter assets
        :param meter_folder: Meter folder name
        :param filename: PNG filename for the reel graphic
        :param pos: Top-left position tuple (x, y) for drawing
        :param center: Center point tuple (x, y) for rotation pivot
        :param rotate_rpm: Rotation speed in RPM
        :param angle_step_deg: Minimum angle change to trigger re-render (legacy)
        :param rotation_fps: Target FPS for rotation updates
        :param rotation_step: Degrees per pre-computed frame
        :param speed_multiplier: Multiplier for rotation speed (from config)
        :param direction: Rotation direction - "ccw" (counter-clockwise) or "cw" (clockwise)
        :param name: Identifier for trace logging ("reel_left" or "reel_right")
        """
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pos = pos
        self.center = center
        self.rotate_rpm = abs(float(rotate_rpm) * float(speed_multiplier))  # abs() - direction via UI
        self.angle_step_deg = float(angle_step_deg)
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)
        self.direction_mult = 1 if direction == "cw" else -1  # CCW = negative angle change
        
        # Trace identification
        self._trace_name = name.replace("_", " ").title()  # "reel_left" -> "Reel Left"
        self._trace_component = name.replace("_", ".")  # "reel_left" -> "reel.left"
        
        # Runtime state
        self._original_surf = None
        self._rot_frames = None  # OPTIMIZATION: Pre-computed rotation frames
        self._current_angle = 0.0
        self._loaded = False
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._need_first_blit = False
        
        # Load the reel image
        self._load_image()
    
    def _load_image(self):
        """Load the reel PNG file and pre-compute rotation frames."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if os.path.exists(img_path):
                self._original_surf = pg.image.load(img_path).convert_alpha()
                self._loaded = True
                self._need_first_blit = True
                
                # OPTIMIZATION: Pre-compute all rotation frames
                if USE_PRECOMPUTED_FRAMES and self.center and self.rotate_rpm > 0.0:
                    try:
                        self._rot_frames = [
                            pg.transform.rotate(self._original_surf, -a)
                            for a in range(0, 360, self.rotation_step)
                        ]
                    except Exception:
                        self._rot_frames = None
            else:
                print(f"[ReelRenderer] File not found: {img_path}")
        except Exception as e:
            print(f"[ReelRenderer] Failed to load '{self.filename}': {e}")
    
    def _update_angle(self, status, now_ticks, volatile=False):
        """Update rotation angle based on RPM, direction, and playback status.
        
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        # Ignore stop/pause during volatile transitions (track skip)
        if volatile and status in ("stop", "pause"):
            status = "play"
        if status == "play":
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating)."""
        if not self._loaded or not self._original_surf:
            return False
        if self._need_first_blit:
            # TRACE: Log first blit decision
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
                log_debug(f"[{self._trace_name}] DECISION: will_blit=True (first_blit)", "trace", self._trace_component)
            return True
        if not self.center or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        
        result = (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        # TRACE: Log will_blit decision (only when true to reduce noise)
        if result and DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            log_debug(f"[{self._trace_name}] DECISION: will_blit=True, angle={self._current_angle:.1f}", "trace", self._trace_component)
        
        return result
    
    def get_backing_rect(self):
        """Get bounding rectangle for backing surface (extended for rotation)."""
        if not self._original_surf or not self.center:
            return None
        
        w = self._original_surf.get_width()
        h = self._original_surf.get_height()
        
        # Rotated bounding box is larger (diagonal)
        diag = int(max(w, h) * math.sqrt(2)) + 4
        
        ext_x = self.center[0] - diag // 2
        ext_y = self.center[1] - diag // 2
        
        return pg.Rect(ext_x, ext_y, diag, diag)
    
    def render(self, screen, status, now_ticks, volatile=False):
        """Render the reel (rotated if playing).
        
        OPTIMIZATION: Uses pre-computed frames and FPS gating.
        Returns dirty rect if drawn, None if skipped.
        
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if not self._loaded or not self._original_surf:
            return None
        
        # FPS gating
        if not self.will_blit(now_ticks):
            return None
        
        # TRACE: Log render input
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            log_debug(f"[{self._trace_name}] INPUT: status={status}, angle={self._current_angle:.1f}, volatile={volatile}", "trace", self._trace_component)
        
        self._last_blit_tick = now_ticks
        
        if not self.center:
            # No rotation - just blit at position
            screen.blit(self._original_surf, self.pos)
            self._needs_redraw = False
            self._need_first_blit = False
            rect = pg.Rect(self.pos[0], self.pos[1], 
                         self._original_surf.get_width(), 
                         self._original_surf.get_height())
            # TRACE: Log static render output
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
                log_debug(f"[{self._trace_name}] OUTPUT: static, rect={rect}", "trace", self._trace_component)
            return rect
        
        # Update angle based on playback status
        self._update_angle(status, now_ticks, volatile=volatile)
        
        # OPTIMIZATION: Use pre-computed frame lookup if available
        if self._rot_frames:
            idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
            rot = self._rot_frames[idx]
        else:
            # Fallback: real-time rotation
            try:
                rot = pg.transform.rotate(self._original_surf, -self._current_angle)
            except Exception:
                rot = pg.transform.rotate(self._original_surf, int(-self._current_angle))
        
        # Get rect centered on rotation center
        rot_rect = rot.get_rect(center=self.center)
        screen.blit(rot, rot_rect.topleft)
        self._needs_redraw = False
        self._need_first_blit = False
        
        backing_rect = self.get_backing_rect()
        
        # TRACE: Log rotated render output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            frame_info = f"frame_idx={idx}" if self._rot_frames else "realtime"
            log_debug(f"[{self._trace_name}] OUTPUT: {frame_info}, angle={self._current_angle:.1f}, rect={backing_rect}", "trace", self._trace_component)
        
        return backing_rect


# =============================================================================
# Vinyl Renderer (for turntable skins with spinning vinyl under album art)
# =============================================================================
class VinylRenderer:
    """
    Handles vinyl disc graphics with rotation for turntable-style skins.
    Renders UNDER album art. When albumart.rotation=true, album art locks
    to vinyl's rotation angle for unified spinning.
    
    Uses albumart.rotation.speed for rotation speed (unified with album art).
    """

    def __init__(self, base_path, meter_folder, filename, pos, center,
                 rotate_rpm=0.0, rotation_fps=8, rotation_step=6,
                 speed_multiplier=1.0, direction="cw"):
        """
        Initialize vinyl renderer.
        
        :param base_path: Base path for meter assets
        :param meter_folder: Meter folder name
        :param filename: PNG filename for the vinyl graphic
        :param pos: Top-left position tuple (x, y) for drawing
        :param center: Center point tuple (x, y) for rotation pivot
        :param rotate_rpm: Rotation speed in RPM (from albumart.rotation.speed)
        :param rotation_fps: Target FPS for rotation updates
        :param rotation_step: Degrees per pre-computed frame
        :param speed_multiplier: Multiplier for rotation speed (from config)
        :param direction: Rotation direction - "ccw" (counter-clockwise) or "cw" (clockwise)
        """
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pos = pos
        self.center = center
        self.rotate_rpm = abs(float(rotate_rpm) * float(speed_multiplier))
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)
        self.direction_mult = 1 if direction == "cw" else -1
        
        # Runtime state
        self._original_surf = None
        self._rot_frames = None
        self._current_angle = 0.0
        self._loaded = False
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._need_first_blit = False
        
        # Load the vinyl image
        self._load_image()
    
    def _load_image(self):
        """Load the vinyl PNG file and pre-compute rotation frames."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if os.path.exists(img_path):
                self._original_surf = pg.image.load(img_path).convert_alpha()
                self._loaded = True
                self._need_first_blit = True
                
                # Pre-compute all rotation frames
                if USE_PRECOMPUTED_FRAMES and self.center and self.rotate_rpm > 0.0:
                    try:
                        self._rot_frames = [
                            pg.transform.rotate(self._original_surf, -a)
                            for a in range(0, 360, self.rotation_step)
                        ]
                    except Exception:
                        self._rot_frames = None
            else:
                print(f"[VinylRenderer] File not found: {img_path}")
        except Exception as e:
            print(f"[VinylRenderer] Failed to load '{self.filename}': {e}")
    
    def _update_angle(self, status, now_ticks, volatile=False):
        """Update rotation angle based on RPM, direction, and playback status.
        
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        # Ignore stop/pause during volatile transitions (track skip)
        if volatile and status in ("stop", "pause"):
            status = "play"
        if status == "play":
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
    
    def get_current_angle(self):
        """Return current rotation angle (for album art coupling)."""
        return self._current_angle
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating)."""
        if not self._loaded or not self._original_surf:
            return False
        if self._need_first_blit:
            # TRACE: Log first blit decision
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("vinyl", False):
                log_debug(f"[Vinyl] DECISION: will_blit=True (first_blit)", "trace", "vinyl")
            return True
        if not self.center or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        
        result = (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        # TRACE: Log will_blit decision (only when true to reduce noise)
        if result and DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("vinyl", False):
            log_debug(f"[Vinyl] DECISION: will_blit=True, angle={self._current_angle:.1f}, interval={self._blit_interval_ms}ms", "trace", "vinyl")
        
        return result
    
    def get_backing_rect(self):
        """Get bounding rectangle for backing surface (extended for rotation)."""
        if not self._original_surf or not self.center:
            return None
        
        w = self._original_surf.get_width()
        h = self._original_surf.get_height()
        
        # Rotated bounding box is larger (diagonal)
        diag = int(max(w, h) * math.sqrt(2)) + 4
        
        ext_x = self.center[0] - diag // 2
        ext_y = self.center[1] - diag // 2
        
        return pg.Rect(ext_x, ext_y, diag, diag)
    
    def render(self, screen, status, now_ticks, volatile=False):
        """Render the vinyl disc (rotated if playing).
        
        Returns dirty rect if drawn, None if skipped.
        
        :param volatile: if True, ignore stop/pause (track transition in progress)
        """
        if not self._loaded or not self._original_surf:
            return None
        
        # FPS gating
        if not self.will_blit(now_ticks):
            return None
        
        # TRACE: Log render input
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("vinyl", False):
            log_debug(f"[Vinyl] INPUT: status={status}, angle={self._current_angle:.1f}, volatile={volatile}", "trace", "vinyl")
        
        self._last_blit_tick = now_ticks
        
        if not self.center:
            # No rotation - just blit at position
            screen.blit(self._original_surf, self.pos)
            self._needs_redraw = False
            self._need_first_blit = False
            rect = pg.Rect(self.pos[0], self.pos[1],
                         self._original_surf.get_width(),
                         self._original_surf.get_height())
            # TRACE: Log static render output
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("vinyl", False):
                log_debug(f"[Vinyl] OUTPUT: static (no rotation), rect={rect}", "trace", "vinyl")
            return rect
        
        # Update angle based on playback status
        self._update_angle(status, now_ticks, volatile=volatile)
        
        # Use pre-computed frame lookup if available
        if self._rot_frames:
            idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
            rot = self._rot_frames[idx]
        else:
            # Fallback: real-time rotation
            try:
                rot = pg.transform.rotate(self._original_surf, -self._current_angle)
            except Exception:
                rot = pg.transform.rotate(self._original_surf, int(-self._current_angle))
        
        # Get rect centered on rotation center
        rot_rect = rot.get_rect(center=self.center)
        screen.blit(rot, rot_rect.topleft)
        self._needs_redraw = False
        self._need_first_blit = False
        
        backing_rect = self.get_backing_rect()
        
        # TRACE: Log rotated render output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("vinyl", False):
            frame_info = f"frame_idx={idx}" if self._rot_frames else "realtime"
            log_debug(f"[Vinyl] OUTPUT: {frame_info}, angle={self._current_angle:.1f}, backing={backing_rect}", "trace", "vinyl")
        
        return backing_rect


# =============================================================================
# TonearmRenderer - Turntable tonearm animation based on track progress
# =============================================================================

# Tonearm state constants
TONEARM_STATE_REST = "rest"
TONEARM_STATE_DROP = "drop"
TONEARM_STATE_TRACKING = "tracking"
TONEARM_STATE_LIFT = "lift"


class TonearmRenderer:
    """
    Renders a tonearm that tracks playback progress.
    
    The tonearm pivots around a fixed point and sweeps from an outer groove
    position (start) to an inner groove position (end) based on track progress.
    
    Drop and lift animations provide realistic arm movement when playback
    starts and stops.
    """
    
    def __init__(self, base_path, meter_folder, filename,
                 pivot_screen, pivot_image,
                 angle_rest, angle_start, angle_end,
                 drop_duration=1.5, lift_duration=1.0,
                 rotation_fps=30):
        """
        Initialize tonearm renderer.
        
        :param base_path: Base path for meter assets
        :param meter_folder: Meter folder name
        :param filename: PNG filename for the tonearm graphic
        :param pivot_screen: Screen coordinates (x, y) where pivot point is drawn
        :param pivot_image: Coordinates (x, y) within the PNG where pivot is located
        :param angle_rest: Angle in degrees when arm is parked (off record)
        :param angle_start: Angle at outer groove (0% progress)
        :param angle_end: Angle at inner groove (100% progress)
        :param drop_duration: Seconds for drop animation (rest -> start)
        :param lift_duration: Seconds for lift animation (current -> rest)
        :param rotation_fps: Target FPS for animation updates
        """
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pivot_screen = pivot_screen
        self.pivot_image = pivot_image
        self.angle_rest = float(angle_rest)
        self.angle_start = float(angle_start)
        self.angle_end = float(angle_end)
        self.drop_duration = float(drop_duration)
        self.lift_duration = float(lift_duration)
        self.rotation_fps = int(rotation_fps)
        
        # Runtime state
        self._original_surf = None
        self._loaded = False
        self._state = TONEARM_STATE_REST
        self._current_angle = self.angle_rest
        self._animation_start_time = 0
        self._animation_start_angle = 0
        self._animation_end_angle = 0
        self._animation_duration = 0
        self._last_status = ""
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._last_drawn_angle = None
        self._pending_drop_target = None  # For track change lift->drop sequence
        self._last_update_time = 0  # For freeze detection
        self._early_lift = False  # Flag for end-of-track early lift
        
        # Per-frame backing for clean restore (only covers actual tonearm draw area)
        self._last_blit_rect = None
        self._last_backing = None
        
        # Exclusion zones - areas where tonearm backing should not restore
        # (scrollers manage these areas with their own backings)
        self._exclusion_zones = []
        self._exclusion_min_x = 9999  # Pre-calculated for fast early-exit check
        
        # Arm geometry for backing rect calculation
        self._arm_length = 0
        
        # Load the tonearm image
        self._load_image()
    
    def set_exclusion_zones(self, zones):
        """Set rectangles that should be excluded from backing restore.
        These are typically scroller areas that manage their own backings.
        
        :param zones: List of pygame.Rect objects to exclude
        """
        self._exclusion_zones = zones if zones else []
        # Pre-calculate min x for fast early-exit check
        if self._exclusion_zones:
            self._exclusion_min_x = min(z.left for z in self._exclusion_zones)
        else:
            self._exclusion_min_x = 9999
    
    def get_last_blit_rect(self):
        """Return the last blit rect for overlap checking."""
        return self._last_blit_rect
    
    def is_animating(self):
        """Return True if tonearm is in DROP or LIFT animation."""
        return self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT)
    
    def _load_image(self):
        """Load the tonearm PNG file."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if os.path.exists(img_path):
                self._original_surf = pg.image.load(img_path).convert_alpha()
                self._loaded = True
                self._needs_redraw = True
                
                # Calculate arm length as distance from pivot to furthest corner
                w = self._original_surf.get_width()
                h = self._original_surf.get_height()
                px, py = self.pivot_image
                
                # Check all four corners, find max distance from pivot
                corners = [(0, 0), (w, 0), (0, h), (w, h)]
                self._arm_length = max(
                    math.sqrt((cx - px)**2 + (cy - py)**2)
                    for cx, cy in corners
                )
                
                log_debug(f"[TonearmRenderer] Loaded '{self.filename}', arm_length={self._arm_length:.1f}")
            else:
                print(f"[TonearmRenderer] File not found: {img_path}")
        except Exception as e:
            print(f"[TonearmRenderer] Failed to load '{self.filename}': {e}")
    
    def _start_animation(self, target_angle, duration):
        """Start an animation from current angle to target angle."""
        self._animation_start_time = time.time()
        self._animation_start_angle = self._current_angle
        self._animation_end_angle = target_angle
        self._animation_duration = duration
    
    def _update_animation(self):
        """Update animation progress, return True if animation complete."""
        if self._animation_duration <= 0:
            self._current_angle = self._animation_end_angle
            return True
        
        elapsed = time.time() - self._animation_start_time
        progress = min(1.0, elapsed / self._animation_duration)
        
        # Ease-out for natural arm movement (decelerate at end)
        eased = 1 - (1 - progress) ** 2
        
        self._current_angle = (
            self._animation_start_angle + 
            (self._animation_end_angle - self._animation_start_angle) * eased
        )
        
        return progress >= 1.0
    
    def update(self, status, progress_pct, time_remaining_sec=None):
        """
        Update tonearm state based on playback status and progress.
        
        :param status: Playback status ("play", "pause", "stop")
        :param progress_pct: Track progress as percentage (0.0 to 100.0)
        :param time_remaining_sec: Seconds remaining in track (for early lift)
        :return: True if redraw needed
        """
        if not self._loaded:
            return False
        
        now = time.time()
        
        # Freeze detection: if we're in animation and haven't been updated for >300ms,
        # the animation timing has drifted due to blocking operations (e.g., album art download).
        # Reset animation to continue smoothly from current angle.
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._last_update_time > 0:
                gap_sec = now - self._last_update_time
                if gap_sec > 0.3:  # 300ms freeze
                    # Restart animation from current position
                    remaining_angle = abs(self._animation_end_angle - self._current_angle)
                    total_angle = abs(self._animation_end_angle - self._animation_start_angle)
                    if total_angle > 0.1:
                        remaining_pct = remaining_angle / total_angle
                        remaining_duration = self._animation_duration * remaining_pct
                        if remaining_duration > 0.05:  # At least 50ms remaining
                            self._animation_start_time = now
                            self._animation_start_angle = self._current_angle
                            self._animation_duration = remaining_duration
                            log_debug(f"[Tonearm] Update freeze ({gap_sec*1000:.0f}ms), restart animation", "trace", "tonearm")
        
        self._last_update_time = now
        
        status = (status or "").lower()
        self._last_status = status
        
        # State machine
        if self._state == TONEARM_STATE_REST:
            if status == "play":
                # If early_lift flag is set, wait for new track (progress near start)
                progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                if self._early_lift and progress_pct > 10.0:
                    # Still on old track ending - stay at REST
                    return self._needs_redraw
                
                # New track started or normal playback - clear flag and DROP
                self._early_lift = False
                target_angle = (
                    self.angle_start + 
                    (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                )
                log_debug(f"[Tonearm] REST->DROP: progress={progress_pct:.1f}%, target={target_angle:.1f}", "trace", "tonearm")
                self._state = TONEARM_STATE_DROP
                self._start_animation(target_angle, self.drop_duration)
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_DROP:
            if status != "play":
                # Playback stopped during drop - lift back
                log_debug(f"[Tonearm] DROP->LIFT: playback stopped (status={status})", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._early_lift = False  # Clear flag - this is a normal stop
                self._start_animation(self.angle_rest, self.lift_duration)
            else:
                # Continue drop animation
                if self._update_animation():
                    # Drop complete - sync to current progress before entering TRACKING
                    # This prevents jump detection from triggering immediately
                    progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                    sync_angle = (
                        self.angle_start + 
                        (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                    )
                    log_debug(f"[Tonearm] DROP->TRACKING: progress={progress_pct:.1f}%, sync_angle={sync_angle:.1f}, drop_target={self._animation_end_angle:.1f}", "trace", "tonearm")
                    self._current_angle = sync_angle
                    self._state = TONEARM_STATE_TRACKING
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_TRACKING:
            # Early lift: when track is about to end, lift tonearm preemptively
            # This hides the freeze during track change - looks like natural LP change
            if time_remaining_sec is not None and time_remaining_sec < 1.5 and time_remaining_sec > 0:
                log_debug(f"[Tonearm] TRACKING->LIFT: early lift, track ending in {time_remaining_sec:.1f}s", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._pending_drop_target = None  # Will get new position from next track
                self._early_lift = True  # Flag to stay at REST after lift completes
                self._start_animation(self.angle_rest, self.lift_duration)
                self._needs_redraw = True
                self._last_blit_tick = 0
            elif status != "play":
                # Playback stopped - start lift (not early lift)
                log_debug(f"[Tonearm] TRACKING->LIFT: playback stopped (status={status})", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._pending_drop_target = None
                self._early_lift = False  # Clear flag - this is a normal stop
                self._start_animation(self.angle_rest, self.lift_duration)
                self._needs_redraw = True
                self._last_blit_tick = 0  # Reset to allow immediate render
            else:
                # Calculate angle from progress
                # Clamp progress to 0-100
                progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                target_angle = (
                    self.angle_start + 
                    (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                )
                
                # Detect large jump (track change, seek forward, or seek backward)
                # Any sudden movement > 2 degrees triggers lift/drop animation
                if abs(target_angle - self._current_angle) > 2.0:
                    # Large jump - lift and drop to new position
                    log_debug(f"[Tonearm] TRACKING->LIFT: jump detected, current={self._current_angle:.1f}, target={target_angle:.1f}, progress={progress_pct:.1f}%", "trace", "tonearm")
                    self._state = TONEARM_STATE_LIFT
                    self._pending_drop_target = target_angle
                    self._early_lift = False  # Clear flag - this is a seek/jump
                    self._start_animation(self.angle_rest, self.lift_duration)
                    self._needs_redraw = True
                    self._last_blit_tick = 0  # Reset to allow immediate render
                # Only update if angle changed significantly (0.2 degree threshold)
                elif abs(target_angle - self._current_angle) > 0.2:
                    self._current_angle = target_angle
                    self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_LIFT:
            if self._update_animation():
                # Lift animation complete
                if self._early_lift:
                    # Early lift for track change - stay at REST until new track
                    log_debug("[Tonearm] LIFT->REST: early lift complete, waiting for new track", "trace", "tonearm")
                    self._state = TONEARM_STATE_REST
                    self._pending_drop_target = None
                    # Keep _early_lift=True - will be cleared when DROP starts
                elif self._pending_drop_target is not None:
                    # Seek/jump - drop to pending target
                    log_debug(f"[Tonearm] LIFT->DROP: pending target={self._pending_drop_target:.1f}", "trace", "tonearm")
                    self._state = TONEARM_STATE_DROP
                    self._start_animation(self._pending_drop_target, self.drop_duration)
                    self._pending_drop_target = None
                elif status == "play":
                    # Drop to current progress position (most up-to-date)
                    progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                    target_angle = (
                        self.angle_start + 
                        (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                    )
                    log_debug(f"[Tonearm] LIFT->DROP: no pending, using progress={progress_pct:.1f}%, target={target_angle:.1f}", "trace", "tonearm")
                    self._state = TONEARM_STATE_DROP
                    self._start_animation(target_angle, self.drop_duration)
                else:
                    # Lift complete, not playing - back to rest
                    log_debug(f"[Tonearm] LIFT->REST: not playing (status={status})", "trace", "tonearm")
                    self._state = TONEARM_STATE_REST
                    self._pending_drop_target = None
            self._needs_redraw = True
        
        return self._needs_redraw
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating + state check)."""
        if not self._loaded or not self._original_surf:
            return False
        
        # During animations (DROP/LIFT), always render if needed for smooth motion
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._needs_redraw:
                return True
            return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        # TRACKING state - arm moves very slowly, use slower updates
        # But always allow immediate render when _needs_redraw is True
        # (e.g., when jump detection triggers state change)
        if self._state == TONEARM_STATE_TRACKING:
            if self._needs_redraw:
                return True  # Allow immediate render for state changes
            # Throttle routine position updates
            tracking_interval = 500  # ms
            return (now_ticks - self._last_blit_tick) >= tracking_interval
        
        # REST state - always blit if needed
        if self._needs_redraw:
            return True
        
        return False
    
    def get_backing_rect(self):
        """
        Get bounding rectangle for backing surface.
        
        Must cover the full sweep area from rest angle to end angle.
        """
        if not self._original_surf or not self.pivot_screen:
            return None
        
        # Calculate the sweep area
        # The arm tip traces an arc - we need a rect that covers the full arc
        px, py = self.pivot_screen
        arm_len = self._arm_length + 4  # Small padding
        
        # Find min/max angles for full sweep range
        min_angle = min(self.angle_rest, self.angle_start, self.angle_end)
        max_angle = max(self.angle_rest, self.angle_start, self.angle_end)
        
        # Calculate bounding box of arc sweep
        # Sample points along the arc to find extents
        points = []
        for angle in range(int(min_angle), int(max_angle) + 1, 5):
            rad = math.radians(angle)
            x = px + arm_len * math.cos(rad)
            y = py - arm_len * math.sin(rad)  # Pygame Y is inverted
            points.append((x, y))
        
        # Also add the pivot point itself
        points.append((px, py))
        
        if not points:
            return None
        
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        
        # Add padding for arm parts not covered by arc sampling:
        # - Counterweight side (distance from pivot to left edge of image)
        # - Arm thickness (distance from pivot to top/bottom of image)
        px, py = self.pivot_image
        img_h = self._original_surf.get_height()
        counterweight_len = px  # pivot distance from left edge
        arm_thickness = max(py, img_h - py)  # max perpendicular extent
        padding = max(counterweight_len, arm_thickness) + 5
        
        return pg.Rect(
            int(min_x - padding),
            int(min_y - padding),
            int(max_x - min_x + 2 * padding),
            int(max_y - min_y + 2 * padding)
        )
    
    def restore_backing(self, screen):
        """
        Restore backing from previous frame's tonearm position.
        Call this BEFORE meter.run() to avoid wiping meters.
        
        Excludes any configured exclusion zones (scroller areas) to prevent
        restoring stale content in those areas. Uses efficient chunk-based
        blitting to avoid per-row overhead.
        
        :param screen: Pygame screen surface
        :return: Dirty rect if restored, None if nothing to restore
        """
        if self._last_backing is None or self._last_blit_rect is None:
            return None
        
        # TRACE: Log backing restore
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("tonearm", False):
            log_debug(f"[Tonearm] RESTORE: rect={self._last_blit_rect}, state={self._state}, exclusions={len(self._exclusion_zones)}", "trace", "tonearm")
        
        # If no exclusion zones or not animating, restore entire backing
        if not self._exclusion_zones or self._state == TONEARM_STATE_TRACKING:
            screen.blit(self._last_backing, self._last_blit_rect.topleft)
            return self._last_blit_rect.copy()
        
        # Find exclusion zones that actually overlap with current backing rect
        br = self._last_blit_rect
        overlaps = []
        for zone in self._exclusion_zones:
            if br.colliderect(zone):
                overlaps.append(br.clip(zone))
        
        # If no actual overlap, restore entire backing
        if not overlaps:
            screen.blit(self._last_backing, self._last_blit_rect.topleft)
            return self._last_blit_rect.copy()
        
        # Efficient chunk-based restore: split into up to 4 regions around exclusions
        # Find bounding box of all overlapping exclusion zones
        ex_left = min(o.left for o in overlaps)
        ex_right = max(o.right for o in overlaps)
        ex_top = min(o.top for o in overlaps)
        ex_bottom = max(o.bottom for o in overlaps)
        
        bx, by = br.topleft
        bw, bh = br.size
        
        # Region 1: Full width strip ABOVE exclusion zones
        if ex_top > by:
            h = ex_top - by
            src_rect = pg.Rect(0, 0, bw, h)
            screen.blit(self._last_backing, (bx, by), src_rect)
        
        # Region 2: Full width strip BELOW exclusion zones
        if ex_bottom < by + bh:
            h = (by + bh) - ex_bottom
            local_y = ex_bottom - by
            src_rect = pg.Rect(0, local_y, bw, h)
            screen.blit(self._last_backing, (bx, ex_bottom), src_rect)
        
        # Region 3: Strip to LEFT of exclusion zones (between top and bottom of exclusions)
        if ex_left > bx:
            w = ex_left - bx
            h = ex_bottom - ex_top
            local_y = ex_top - by
            src_rect = pg.Rect(0, local_y, w, h)
            screen.blit(self._last_backing, (bx, ex_top), src_rect)
        
        # Region 4: Strip to RIGHT of exclusion zones (between top and bottom of exclusions)
        if ex_right < bx + bw:
            w = (bx + bw) - ex_right
            h = ex_bottom - ex_top
            local_x = ex_right - bx
            local_y = ex_top - by
            src_rect = pg.Rect(local_x, local_y, w, h)
            screen.blit(self._last_backing, (ex_right, ex_top), src_rect)
        
        return self._last_blit_rect.copy()
    
    def has_scroller_overlap(self):
        """Check if current tonearm position overlaps with scroller exclusion zones.
        Used to determine if scrollers need force_redraw during animation.
        
        :return: True if tonearm backing overlaps any exclusion zone
        """
        if not self._last_blit_rect or not self._exclusion_zones:
            return False
        # Fast check using pre-calculated min_x
        return self._last_blit_rect.right >= self._exclusion_min_x
    
    def render(self, screen, now_ticks, force=False):
        """
        Render the tonearm at current angle.
        NOTE: Call restore_backing() separately BEFORE this and BEFORE meter.run()
        to properly handle overlapping elements.
        
        :param screen: Pygame screen surface
        :param now_ticks: Current tick count (for FPS gating)
        :param force: If True, bypass FPS gating (used when album art redraws)
        :return: Dirty rect if drawn, None if skipped
        """
        if not self._loaded or not self._original_surf:
            return None
        
        # FPS gating (bypass if force)
        if not force and not self.will_blit(now_ticks):
            return None
        
        # Detect render freeze (e.g., during album art download)
        # Use fresh timestamp since now_ticks may have been captured before blocking ops
        actual_now = pg.time.get_ticks()
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._last_blit_tick > 0:
                gap_ms = actual_now - self._last_blit_tick
                if gap_ms > 300:  # More than 300ms since last render = freeze
                    # Restart animation from current angle position
                    remaining_angle = abs(self._animation_end_angle - self._current_angle)
                    total_angle = abs(self._animation_end_angle - self._animation_start_angle)
                    if total_angle > 0.1:  # Avoid division issues
                        remaining_pct = remaining_angle / total_angle
                        remaining_duration = self._animation_duration * remaining_pct
                        if remaining_duration > 0.1:  # Only reset if significant animation remains
                            self._animation_start_time = time.time()
                            self._animation_start_angle = self._current_angle
                            self._animation_duration = remaining_duration
                            log_debug(f"[Tonearm] Freeze detected ({gap_ms}ms), restarting animation", "trace", "tonearm")
        
        self._last_blit_tick = actual_now  # Use fresh timestamp
        
        # Skip if angle hasn't changed (optimization for TRACKING state only)
        # During DROP/LIFT animations, always render for smooth movement
        # Also always render if _needs_redraw is True (state just changed)
        if not force and not self._needs_redraw and self._state == TONEARM_STATE_TRACKING:
            if self._last_drawn_angle is not None:
                if abs(self._current_angle - self._last_drawn_angle) < 0.1:
                    return None
        
        # Rotate the image around the pivot point
        # pygame.transform.rotate rotates around center, so we need to compensate
        
        # 1. Rotate the surface
        rotated = pg.transform.rotate(self._original_surf, self._current_angle)
        
        # 2. Calculate where the pivot point ended up after rotation
        # Original pivot in image coordinates
        px, py = self.pivot_image
        img_w = self._original_surf.get_width()
        img_h = self._original_surf.get_height()
        
        # Pivot relative to image center
        cx, cy = img_w / 2, img_h / 2
        dx, dy = px - cx, py - cy
        
        # Rotate pivot point
        rad = math.radians(-self._current_angle)  # Negative because pygame rotates CCW
        new_dx = dx * math.cos(rad) - dy * math.sin(rad)
        new_dy = dx * math.sin(rad) + dy * math.cos(rad)
        
        # New pivot position in rotated image
        rot_w = rotated.get_width()
        rot_h = rotated.get_height()
        rot_cx, rot_cy = rot_w / 2, rot_h / 2
        rot_px = rot_cx + new_dx
        rot_py = rot_cy + new_dy
        
        # 3. Position the rotated image so pivot aligns with screen position
        scr_px, scr_py = self.pivot_screen
        blit_x = int(scr_px - rot_px)
        blit_y = int(scr_py - rot_py)
        blit_rect = pg.Rect(blit_x, blit_y, rot_w, rot_h)
        
        # Capture backing for THIS frame's position BEFORE drawing tonearm
        # (backing must NOT contain the tonearm itself to avoid ghosting)
        screen_rect = screen.get_rect()
        clipped_rect = blit_rect.clip(screen_rect)
        if clipped_rect.width > 0 and clipped_rect.height > 0:
            try:
                self._last_backing = screen.subsurface(clipped_rect).copy()
                self._last_blit_rect = clipped_rect
                # TRACE: Log backing capture
                if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("tonearm", False):
                    log_debug(f"[Tonearm] CAPTURE: rect={clipped_rect}, angle={self._current_angle:.1f}, state={self._state}", "trace", "tonearm")
            except Exception:
                self._last_backing = None
                self._last_blit_rect = None
        
        # Blit tonearm to screen
        screen.blit(rotated, (blit_x, blit_y))
        
        # TRACE: Log render output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("tonearm", False):
            log_debug(f"[Tonearm] RENDER: angle={self._current_angle:.1f}, blit_rect={blit_rect}", "trace", "tonearm")
        
        self._needs_redraw = False
        self._last_drawn_angle = self._current_angle
        
        return blit_rect
    
    def get_state(self):
        """Return current state for debugging."""
        return self._state
    
    def get_angle(self):
        """Return current angle for debugging."""
        return self._current_angle


# =============================================================================
# CallBack - Interface for upstream Peppymeter
# =============================================================================
class CallBack:
    """Callback functions for Peppymeter start/stop/update."""
    
    def __init__(self, util, meter_config_volumio, meter=None):
        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_volumio = meter_config_volumio
        self.first_run = True
        self.meter = meter
        self.pending_restart = False
        self.spectrum_output = None
        self.last_fade_time = 0  # Cooldown to prevent multiple fade-ins
        self.did_fade_in = False  # Track if this instance did fade-in
        
    def vol_FadeIn_thread(self, meter):
        """Volume fade-in thread."""
        for i in range(0, 100, 10):
            meter.set_volume(i)
            time.sleep(0.07)
        meter.set_volume(100)

    def screen_fade_in(self, screen, duration=0.5):
        """Fade in the screen from configured background color.
        
        :param screen: pygame screen surface
        :param duration: fade duration in seconds
        """
        log_debug(f"screen_fade_in called, duration={duration}", "trace", "fade")
        
        transition_type = self.meter_config_volumio.get(TRANSITION_TYPE, "fade")
        if transition_type == "none":
            log_debug("-> skipped (transition_type=none)", "trace", "fade")
            return
            
        clock = Clock()
        frame_rate = self.meter_config.get(FRAME_RATE, 30)
        
        # Get configured fade color
        fade_color = self.meter_config_volumio.get(TRANSITION_COLOR, "black")
        if fade_color == "white":
            overlay_color = (255, 255, 255)
        else:
            overlay_color = (0, 0, 0)
        
        # Get opacity (0-100, default 100 for solid fade)
        opacity = self.meter_config_volumio.get(TRANSITION_OPACITY, 100)
        max_alpha = int(255 * opacity / 100)
        log_debug(f"-> fade_in with opacity={opacity}%, max_alpha={max_alpha}", "trace", "fade")
        
        # Capture current screen content
        screen_copy = screen.copy()
        
        # Create overlay surface
        overlay = pg.Surface(screen.get_size())
        overlay.fill(overlay_color)
        
        # Calculate steps based on duration and frame rate
        total_frames = max(int(duration * frame_rate), 1)
        alpha_step = max_alpha / total_frames
        
        # Start with overlay at max_alpha, decrease to 0
        for i in range(total_frames + 1):
            alpha = max_alpha - int(i * alpha_step)
            if alpha < 0:
                alpha = 0
            screen.blit(screen_copy, (0, 0))
            overlay.set_alpha(alpha)
            screen.blit(overlay, (0, 0))
            pg.display.update()
            clock.tick(frame_rate)
        
        # Ensure clean finish - content only, no overlay
        screen.blit(screen_copy, (0, 0))
        pg.display.update()

    def screen_fade_out(self, screen, duration=0.5):
        """Fade out the screen to configured color.
        
        :param screen: pygame screen surface
        :param duration: fade duration in seconds
        """
        log_debug(f"screen_fade_out called, duration={duration}", "trace", "fade")
        
        transition_type = self.meter_config_volumio.get(TRANSITION_TYPE, "fade")
        if transition_type == "none":
            log_debug("-> skipped (transition_type=none)", "trace", "fade")
            return
            
        clock = Clock()
        frame_rate = self.meter_config.get(FRAME_RATE, 30)
        
        # Get configured fade color
        fade_color = self.meter_config_volumio.get(TRANSITION_COLOR, "black")
        if fade_color == "white":
            overlay_color = (255, 255, 255)
        else:
            overlay_color = (0, 0, 0)
        
        # Get opacity (0-100, default 100 for solid fade)
        opacity = self.meter_config_volumio.get(TRANSITION_OPACITY, 100)
        max_alpha = int(255 * opacity / 100)
        log_debug(f"-> fade_out with opacity={opacity}%, max_alpha={max_alpha}", "trace", "fade")
        
        # Create overlay
        overlay = pg.Surface(screen.get_size())
        overlay.fill(overlay_color)
        
        # Calculate steps based on duration and frame rate
        total_frames = max(int(duration * frame_rate), 1)
        alpha_step = max_alpha / total_frames
        
        # Capture current screen
        screen_copy = screen.copy()
        
        # Start with overlay at 0, increase to max_alpha
        for i in range(total_frames + 1):
            alpha = int(i * alpha_step)
            if alpha > max_alpha:
                alpha = max_alpha
            screen.blit(screen_copy, (0, 0))
            overlay.set_alpha(alpha)
            screen.blit(overlay, (0, 0))
            pg.display.update()
            clock.tick(frame_rate)

    def peppy_meter_start(self, meter):
        """Called when meter starts - initialize spectrum and albumart overlay."""
        meter_section = self.meter_config[self.meter_config[METER]]
        meter_section_volumio = self.meter_config_volumio[self.meter_config[METER]]
        
        # Screen fade-in transition (before restoring screen)
        # Use cooldown to prevent multiple fade-ins on rapid meter changes
        current_time = time.time()
        duration = self.meter_config_volumio.get(TRANSITION_DURATION, 0.5)
        animation = self.meter_config_volumio.get(START_ANIMATION, False)
        cooldown = duration + 1.0  # cooldown is fade duration + 1 second
        
        # TRACE: track calls
        time_since_last = current_time - self.last_fade_time
        log_debug(f"peppy_meter_start: first_run={self.first_run}, animation={animation}, duration={duration}s, cooldown={cooldown}s", "trace", "fade")
        
        # Use file-based cooldown that persists across process restarts
        # This prevents double fade when skin change triggers multiple restarts
        fade_lockfile = '/tmp/peppy_fade_lock'
        should_fade = False
        
        try:
            if os.path.exists(fade_lockfile):
                lock_mtime = os.path.getmtime(fade_lockfile)
                lock_age = current_time - lock_mtime
                log_debug(f"-> fade lock exists, age={lock_age:.2f}s", "trace", "fade")
                if lock_age > cooldown:
                    # Lock expired, allow fade
                    should_fade = True
                else:
                    log_debug(f"-> skipped (lock active: {lock_age:.2f}s < {cooldown}s)", "trace", "fade")
            else:
                # No lock, allow fade
                should_fade = True
        except Exception as e:
            log_debug(f"-> lock check error: {e}", "trace", "fade")
            should_fade = True
        
        # Only fade on first run with animation, or meter change
        if should_fade:
            if self.first_run and animation:
                log_debug("-> will fade (first_run + animation)", "trace", "fade")
                # Touch lock file
                Path(fade_lockfile).touch()
                self.did_fade_in = True
                self.screen_fade_in(meter.util.PYGAME_SCREEN, duration)
            elif not self.first_run:
                log_debug("-> will fade (meter change)", "trace", "fade")
                Path(fade_lockfile).touch()
                self.did_fade_in = True
                self.screen_fade_in(meter.util.PYGAME_SCREEN, duration)
            else:
                log_debug("-> no fade (first_run but no animation)", "trace", "fade")
        
        # Restore screen reference
        meter.util.PYGAME_SCREEN = meter.util.screen_copy
        for comp in meter.components:
            comp.screen = meter.util.screen_copy
        
        if meter_section_volumio[EXTENDED_CONF]:
            # Stop meters if not visible
            if not meter_section_volumio[METER_VISIBLE]:
                meter.stop()
            
            # Start spectrum if visible (but not if already set by remote client)
            if meter_section_volumio[SPECTRUM_VISIBLE]:
                # Check if spectrum_output was pre-injected (e.g., RemoteSpectrumOutput)
                # If so, don't create a new SpectrumOutput - use the injected one
                if self.spectrum_output is None:
                    init_spectrum_debug(DEBUG_LEVEL_CURRENT, DEBUG_TRACE)
                    self.spectrum_output = SpectrumOutput(self.util, self.meter_config_volumio, CurDir)
                    self.spectrum_output.start()
        
        # Volume fade-in
        meter.set_volume(0.0)
        self.FadeIn = Thread(target=self.vol_FadeIn_thread, args=(meter,))
        self.FadeIn.start()
        self.first_run = False
        
    def peppy_meter_stop(self, meter):
        """Called when meter stops - cleanup spectrum."""
        # Save screen reference
        meter.util.screen_copy = meter.util.PYGAME_SCREEN
        meter.util.PYGAME_SCREEN = meter.util.PYGAME_SCREEN.copy()
        
        # Stop spectrum
        if self.spectrum_output is not None:
            self.spectrum_output.stop_thread()
            self.spectrum_output = None
            
        if hasattr(self, 'FadeIn'):
            del self.FadeIn
            
    def peppy_meter_update(self):
        """Called each frame - update spectrum."""
        # Handle pending random restart
        if self.pending_restart:
            self.pending_restart = False
            if self.meter:
                self.meter.restart()
            return
        
        # Update spectrum
        if self.spectrum_output is not None:
            self.spectrum_output.update()
    
    def trim_memory(self):
        """Trim memory allocation."""
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)
    
    def exit_trim_memory(self):
        """Cleanup on exit."""
        if os.path.exists(PeppyRunning):
            os.remove(PeppyRunning)
        if self.spectrum_output is not None:
            self.spectrum_output.stop_thread()
        self.trim_memory()


# =============================================================================
# Helper Functions
# =============================================================================
def sanitize_color(val, default=(255, 255, 255)):
    """Convert various color formats to RGB tuple, clamped to 0-255."""
    def clamp(v):
        return max(0, min(255, int(v)))
    
    try:
        if isinstance(val, pg.Color):
            return (clamp(val.r), clamp(val.g), clamp(val.b))
        if isinstance(val, (tuple, list)) and len(val) >= 3:
            return (clamp(val[0]), clamp(val[1]), clamp(val[2]))
        if isinstance(val, str):
            parts = [p.strip() for p in val.split(",")]
            if len(parts) >= 3:
                return (clamp(parts[0]), clamp(parts[1]), clamp(parts[2]))
    except Exception:
        pass
    return default


def as_int(val, default=0):
    """Safely convert value to integer."""
    if val is None:
        return default
    try:
        if isinstance(val, (int, float)):
            return int(val)
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return default
            return int(float(val))
        return int(val)
    except Exception:
        return default


def as_float(val, default=0.0):
    """Safely convert value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except Exception:
        return default


def set_color(surface, color):
    """Colorize a surface with given color (preserving alpha). Modifies surface in place."""
    # Check if numpy is available (required for surfarray)
    numpy_available = False
    try:
        import numpy
        numpy_available = True
    except ImportError:
        pass
    
    if numpy_available:
        try:
            r, g, b = color.r, color.g, color.b
            # Get pixel array for direct manipulation (requires numpy)
            arr = pg.surfarray.pixels3d(surface)
            alpha = pg.surfarray.pixels_alpha(surface)
            # Replace all non-transparent pixel colors with target color
            mask = alpha > 0
            arr[mask] = [r, g, b]
            del arr
            del alpha
            return
        except Exception:
            pass
    
    # Fallback: pixel-by-pixel (slow but works without numpy)
    try:
        r, g, b = color.r, color.g, color.b
        w, h = surface.get_size()
        for x in range(w):
            for y in range(h):
                px = surface.get_at((x, y))
                if px.a > 0:
                    surface.set_at((x, y), (r, g, b, px.a))
    except Exception:
        pass


def get_memory():
    """Get available memory in KB."""
    with open('/proc/meminfo', 'r') as mem:
        free_memory = 0
        for line in mem:
            sline = line.split()
            if str(sline[0]) == 'MemAvailable:':
                free_memory += int(sline[1])
    return free_memory


def memory_limit():
    """Limit maximum memory usage."""
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    free_memory = get_memory() * 1024
    resource.setrlimit(resource.RLIMIT_AS, (free_memory + 90000000, hard))


def trim_memory():
    """Trim memory allocation."""
    libc = ctypes.CDLL("libc.so.6")
    return libc.malloc_trim(0)


# =============================================================================
# Display Initialization
# =============================================================================
def init_display(pm, meter_config_volumio, screen_w, screen_h, hide=False):
    """Initialize pygame display.
    
    :param pm: Peppymeter instance
    :param meter_config_volumio: Volumio meter configuration
    :param screen_w: Screen width
    :param screen_h: Screen height
    :param hide: If True, create hidden window (for SDL2 positioning)
    """
    depth = meter_config_volumio[COLOR_DEPTH]
    pm.util.meter_config[SCREEN_INFO][DEPTH] = depth
    
    os.environ["SDL_FBDEV"] = pm.util.meter_config[SDL_ENV][FRAMEBUFFER_DEVICE]
    
    if pm.util.meter_config[SDL_ENV][MOUSE_ENABLED]:
        os.environ["SDL_MOUSEDEV"] = pm.util.meter_config[SDL_ENV][MOUSE_DEVICE]
        os.environ["SDL_MOUSEDRV"] = pm.util.meter_config[SDL_ENV][MOUSE_DRIVER]
    else:
        os.environ["SDL_NOMOUSE"] = "1"
    
    if pm.util.meter_config[SDL_ENV][VIDEO_DRIVER] != "dummy":
        os.environ["SDL_VIDEODRIVER"] = pm.util.meter_config[SDL_ENV][VIDEO_DRIVER]
        os.environ["DISPLAY"] = pm.util.meter_config[SDL_ENV][VIDEO_DISPLAY]
    
    pg.display.init()
    pg.mouse.set_visible(False)
    pg.font.init()
    
    flags = pg.NOFRAME
    if pm.util.meter_config[SDL_ENV][DOUBLE_BUFFER]:
        flags |= pg.DOUBLEBUF
    if hide and use_sdl2:
        flags |= pg.HIDDEN
    
    screen = pg.display.set_mode((screen_w, screen_h), flags, depth)
    pm.util.meter_config[SCREEN_RECT] = pg.Rect(0, 0, screen_w, screen_h)
    
    return screen


# =============================================================================
# Stop Watcher Thread
# =============================================================================
def stop_watcher():
    """Watch for PeppyRunning file deletion to trigger stop."""
    while os.path.exists(PeppyRunning):
        time.sleep(1)
    # File deleted - send quit event
    pg.event.post(pg.event.Event(pg.MOUSEBUTTONUP))


# =============================================================================
# Main Display Output with Overlay - OPTIMIZED
# =============================================================================
def start_display_output(pm, callback, meter_config_volumio, volumio_host='localhost', volumio_port=3000, check_reload_callback=None):
    """Main display loop with integrated overlay rendering.
    OPTIMIZED: Uses dirty rectangle updates instead of full screen flip.
    
    :param pm: Peppymeter instance
    :param callback: CallBack instance
    :param meter_config_volumio: Volumio meter configuration dict
    :param volumio_host: Volumio host for socket.io metadata (default: localhost)
    :param volumio_port: Volumio port for socket.io (default: 3000)
    :param check_reload_callback: Optional callable(); if it returns True, loop exits for config reload (remote client).
    """
    
    pg.event.clear()
    screen = pm.util.PYGAME_SCREEN
    SCREEN_WIDTH, SCREEN_HEIGHT = screen.get_size()
    cfg = pm.util.meter_config
    file_path = os.path.dirname(os.path.realpath(__file__))
    
    # Runtime state for overlay
    overlay_state = {}
    active_meter_name = None
    last_cover_url = None
    cover_img = None
    scaled_cover_img = None  # Cached scaled cover to avoid per-frame scaling
    
    # OPTIMIZATION: Cache for static overlay elements
    last_time_str = ""
    last_time_surf = None
    last_sample_text = ""
    last_sample_surf = None
    last_track_type = ""
    last_format_icon_surf = None
    
    # Shared metadata dict - updated by MetadataWatcher via socket.io
    last_metadata = {
        "artist": "", "title": "", "album": "", "albumart": "",
        "samplerate": "", "bitdepth": "", "trackType": "", "bitrate": "",
        "service": "", "status": "", "_time_remain": -1, "_time_update": 0
    }
    
    # Random meter tracking
    random_mode = meter_config_volumio[METER_BKP] == "random" or "," in meter_config_volumio[METER_BKP]
    random_title = random_mode and meter_config_volumio[RANDOM_TITLE]
    random_interval_mode = random_mode and not random_title
    random_interval = cfg.get(RANDOM_METER_INTERVAL, 60)
    random_timer = 0
    
    # Title change flag for random-on-title mode
    title_changed_flag = [False]  # Mutable for closure
    
    def on_title_change():
        title_changed_flag[0] = True
    
    # Start MetadataWatcher - handles both metadata updates and title change detection
    metadata_watcher = MetadataWatcher(
        last_metadata,
        title_changed_callback=on_title_change if random_title else None,
        volumio_host=volumio_host,
        volumio_port=volumio_port
    )
    metadata_watcher.start()
    
    # -------------------------------------------------------------------------
    # Remote Display Server - broadcasts level data for remote clients
    # -------------------------------------------------------------------------
    remote_enabled = meter_config_volumio.get(REMOTE_SERVER_ENABLED, False)
    remote_mode = meter_config_volumio.get(REMOTE_SERVER_MODE, "server_local")
    level_server = None
    discovery_announcer = None
    
    spectrum_server = None
    
    if remote_enabled:
        level_port = meter_config_volumio.get(REMOTE_SERVER_PORT, 5580)
        discovery_port = meter_config_volumio.get(REMOTE_DISCOVERY_PORT, 5579)
        spectrum_port = meter_config_volumio.get(REMOTE_SPECTRUM_PORT, 5581)
        
        # Start level server
        level_server = NetworkLevelServer(port=level_port, enabled=True)
        
        # Start spectrum server
        # In server mode (headless): read from pipe directly (no local display to conflict)
        # In server_local mode: use injected mode initially, will get data from SpectrumOutput
        #                       if no local spectrum is active, will switch to pipe mode dynamically
        read_pipe_mode = (remote_mode == "server")
        spectrum_server = NetworkSpectrumServer(port=spectrum_port, enabled=True, read_pipe=read_pipe_mode)
        
        # Start discovery announcer (includes config version for change detection)
        config_path = os.path.join(PeppyPath, 'config.txt')
        discovery_announcer = DiscoveryAnnouncer(
            discovery_port=discovery_port,
            level_port=level_port,
            spectrum_port=spectrum_port,
            volumio_port=3000,
            interval=5.0,
            enabled=True,
            config_path=config_path
        )
        discovery_announcer.start()
        
        log_debug(f"Remote display server enabled, mode: {remote_mode}", "basic")
    
    # -------------------------------------------------------------------------
    # Resolve active meter name
    # -------------------------------------------------------------------------
    def resolve_active_meter_name():
        names = cfg.get(METER_NAMES) or []
        # Check Vumeter attributes
        for attr in ("current_meter_name", "meter_name", "name"):
            try:
                v = getattr(pm.meter, attr, None)
                if isinstance(v, str) and (not names or v in names):
                    return v
            except Exception:
                pass
        # Fallback to config
        val = (cfg.get(METER) or "").strip()
        if val:
            first = val.split(",")[0].strip()
            if not names or first in names:
                return first
        return names[0] if names else None
    
    # -------------------------------------------------------------------------
    # Load fonts for a meter section
    # -------------------------------------------------------------------------
    def load_fonts(mc_vol):
        font_path = meter_config_volumio.get(FONT_PATH) or ""
        size_light = mc_vol.get(FONTSIZE_LIGHT, 30)
        size_regular = mc_vol.get(FONTSIZE_REGULAR, 35)
        size_bold = mc_vol.get(FONTSIZE_BOLD, 40)
        size_digi = mc_vol.get(FONTSIZE_DIGI, 40)
        
        log_debug("--- Font Config ---", "verbose")
        log_debug(f"  font.path = {font_path}", "verbose")
        log_debug(f"  font.size.light = {size_light}", "verbose")
        log_debug(f"  font.size.regular = {size_regular}", "verbose")
        log_debug(f"  font.size.bold = {size_bold}", "verbose")
        log_debug(f"  font.size.digi = {size_digi}", "verbose")
        
        fontL = None
        fontR = None
        fontB = None
        fontDigi = None
        
        # Light font
        light_file = meter_config_volumio.get(FONT_LIGHT)
        if light_file and os.path.exists(font_path + light_file):
            fontL = pg.font.Font(font_path + light_file, size_light)
            log_debug(f"  Font light: loaded {font_path + light_file}", "verbose")
        else:
            fontL = pg.font.SysFont("DejaVuSans", size_light)
        
        # Regular font
        regular_file = meter_config_volumio.get(FONT_REGULAR)
        if regular_file and os.path.exists(font_path + regular_file):
            fontR = pg.font.Font(font_path + regular_file, size_regular)
            log_debug(f"  Font regular: loaded {font_path + regular_file}", "verbose")
        else:
            fontR = pg.font.SysFont("DejaVuSans", size_regular)
        
        # Bold font
        bold_file = meter_config_volumio.get(FONT_BOLD)
        if bold_file and os.path.exists(font_path + bold_file):
            fontB = pg.font.Font(font_path + bold_file, size_bold)
            log_debug(f"  Font bold: loaded {font_path + bold_file}", "verbose")
        else:
            fontB = pg.font.SysFont("DejaVuSans", size_bold, bold=True)
        
        # Digital font for time
        digi_path = os.path.join(file_path, 'fonts', 'DSEG7Classic-Italic.ttf')
        if os.path.exists(digi_path):
            fontDigi = pg.font.Font(digi_path, size_digi)
            log_debug(f"  Font digi: loaded {digi_path}", "verbose")
        else:
            fontDigi = pg.font.SysFont("DejaVuSans", size_digi)
        
        return fontL, fontR, fontB, fontDigi
    
    # -------------------------------------------------------------------------
    # Get font by style
    # -------------------------------------------------------------------------
    def font_for_style(style, fontL, fontR, fontB):
        if style == FONT_STYLE_B:
            return fontB
        if style == FONT_STYLE_R:
            return fontR
        return fontL
    
    # -------------------------------------------------------------------------
    # Draw static assets (background only - fgr drawn at render loop end)
    # -------------------------------------------------------------------------
    def draw_static_assets(mc):
        base_path = cfg.get(BASE_PATH)
        meter_dir = cfg.get(SCREEN_INFO)[METER_FOLDER]
        meter_path = os.path.join(base_path, meter_dir)
        
        screen_bgr_name = mc.get('screen.bgr')
        bgr_name = mc.get(BGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        
        # Draw full screen background
        if screen_bgr_name:
            try:
                img_path = os.path.join(meter_path, screen_bgr_name)
                img = pg.image.load(img_path).convert()
                screen.blit(img, (0, 0))
            except Exception as e:
                print(f"[draw_static_assets] Failed to load screen.bgr '{screen_bgr_name}': {e}")
        
        # Draw meter background at meter position (convert_alpha for PNG transparency)
        if bgr_name:
            try:
                img_path = os.path.join(meter_path, bgr_name)
                img = pg.image.load(img_path).convert_alpha()
                screen.blit(img, (meter_x, meter_y))
            except Exception as e:
                print(f"[draw_static_assets] Failed to load bgr '{bgr_name}': {e}")
        
        # NOTE: fgr (foreground mask) is NOT drawn here
        # It is drawn ONCE at the end of each render frame as the top layer
    
    # -------------------------------------------------------------------------
    # Initialize overlay for a meter
    # -------------------------------------------------------------------------
    def overlay_init_for_meter(meter_name):
        nonlocal active_meter_name, overlay_state, last_cover_url, cover_img
        nonlocal last_time_str, last_time_surf, last_sample_text, last_sample_surf
        nonlocal last_track_type, last_format_icon_surf
        
        mc = cfg.get(meter_name, {}) if meter_name else {}
        mc_vol = meter_config_volumio.get(meter_name, {}) if meter_name else {}
        active_meter_name = meter_name
        
        log_debug(f"=== Initializing meter: {meter_name} ===", "basic")
        log_debug(f"  config.extend = {mc_vol.get(EXTENDED_CONF, False)}", "verbose")
        
        # CLEANUP: Release resources from previous handler before creating new one
        # This prevents zombie handlers when switching between template types
        old_handler = overlay_state.get("handler") if overlay_state else None
        if old_handler:
            log_debug(f"  Cleaning up previous handler", "verbose")
            try:
                old_handler.cleanup()
            except Exception as e:
                log_debug(f"  Handler cleanup error (non-fatal): {e}", "verbose")
        
        # Reset caches
        last_time_str = ""
        last_time_surf = None
        last_sample_text = ""
        last_sample_surf = None
        last_track_type = ""
        last_format_icon_surf = None
        
        # Fill screen black before drawing anything (prevents white background if assets fail to load)
        screen.fill((0, 0, 0))
        
        # Check if extended config enabled
        if not mc_vol.get(EXTENDED_CONF, False):
            overlay_state = {"enabled": False}
            draw_static_assets(mc)
            pm.meter.run()
            pg.display.update()
            return
        
        # Detect skin type and load handler
        skin_type = detect_skin_type(mc_vol)
        log_debug(f"  Skin type detected: {skin_type}", "verbose")
        
        if skin_type == SKIN_TYPE_CASSETTE:
            from volumio_cassette import CassetteHandler, init_cassette_debug
            init_cassette_debug(DEBUG_LEVEL_CURRENT, DEBUG_TRACE)
            handler = CassetteHandler(screen, pm.meter, cfg, mc_vol, meter_config_volumio)
        elif skin_type == SKIN_TYPE_TURNTABLE:
            from volumio_turntable import TurntableHandler, init_turntable_debug
            init_turntable_debug(DEBUG_LEVEL_CURRENT, DEBUG_TRACE)
            handler = TurntableHandler(screen, pm.meter, cfg, mc_vol, meter_config_volumio)
        else:
            from volumio_basic import BasicHandler, init_basic_debug
            init_basic_debug(DEBUG_LEVEL_CURRENT, DEBUG_TRACE)
            handler = BasicHandler(screen, pm.meter, cfg, mc_vol, meter_config_volumio)
        
        log_debug(f"  Handler loaded: {skin_type}", "verbose")
        
        # Initialize handler for this meter
        handler.init_for_meter(meter_name)
        
        # Draw static assets and initial meter state
        draw_static_assets(mc)
        pm.meter.run()  # Just runs meter animation, does NOT trigger callbacks
        pg.display.update()
        
        # Note: SpectrumOutput is created by pm.meter.start() -> callback_start -> peppy_meter_start()
        # which happens BEFORE overlay_init_for_meter() is called (see line 3577).
        # We tap into callback.spectrum_output for network broadcast.
        
        # Store handler in overlay state
        overlay_state = {
            "enabled": True,
            "handler": handler,
            "mc_vol": mc_vol,
        }
        log_debug(f"  Handler initialized successfully", "verbose")
        return
    
    # -------------------------------------------------------------------------
    # Render format icon - OPTIMIZED with caching
    # -------------------------------------------------------------------------
    def render_format_icon(track_type, type_rect, type_color, force_redraw=False):
        nonlocal last_track_type, last_format_icon_surf
        
        if not type_rect:
            return None
        
        fmt = (track_type or "").strip().lower().replace(" ", "_")
        if fmt == "dsf":
            fmt = "dsd"
        
        # OPTIMIZATION: Return cached surface if format unchanged (unless forced)
        if not force_redraw and fmt == last_track_type and last_format_icon_surf is not None:
            return None  # No redraw needed
        
        last_track_type = fmt
        
        # Restore backing for type area
        bd = overlay_state.get("backing_dict", {})
        if "type" in bd:
            r, b = bd["type"]
            screen.blit(b, r.topleft)
        
        # Check local icons first
        local_icons = {'tidal', 'cd', 'qobuz'}
        if fmt in local_icons:
            icon_path = os.path.join(file_path, 'format-icons', f"{fmt}.svg")
        else:
            icon_path = f"/volumio/http/www3/app/assets-common/format-icons/{fmt}.svg"
        
        if not os.path.exists(icon_path):
            # Render text fallback
            if overlay_state.get("sample_font"):
                txt_surf = overlay_state["sample_font"].render(fmt[:4], True, type_color)
                screen.blit(txt_surf, (type_rect.x, type_rect.y))
                last_format_icon_surf = txt_surf
            return type_rect.copy()
        
        try:
            if pg.version.ver.startswith("2"):
                # Pygame 2 native SVG
                img = pg.image.load(icon_path)
                w, h = img.get_width(), img.get_height()
                sc = min(type_rect.width / float(w), type_rect.height / float(h))
                new_size = (max(1, int(w * sc)), max(1, int(h * sc)))
                try:
                    img = pg.transform.smoothscale(img, new_size)
                except Exception:
                    img = pg.transform.scale(img, new_size)
                # Convert to format suitable for pixel manipulation
                img = img.convert_alpha()
                set_color(img, pg.Color(type_color[0], type_color[1], type_color[2]))
                dx = type_rect.x + (type_rect.width - img.get_width()) // 2
                dy = type_rect.y + (type_rect.height - img.get_height()) // 2
                screen.blit(img, (dx, dy))
                last_format_icon_surf = img
            elif CAIROSVG_AVAILABLE and PIL_AVAILABLE:
                # Pygame 1.x with cairosvg
                png_bytes = cairosvg.svg2png(url=icon_path, 
                                              output_width=type_rect.width,
                                              output_height=type_rect.height)
                pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                img = img.convert_alpha()
                set_color(img, pg.Color(type_color[0], type_color[1], type_color[2]))
                dx = type_rect.x + (type_rect.width - img.get_width()) // 2
                dy = type_rect.y + (type_rect.height - img.get_height()) // 2
                screen.blit(img, (dx, dy))
                last_format_icon_surf = img
            return type_rect.copy()
        except Exception as e:
            print(f"[FormatIcon] error: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Main loop - OPTIMIZED with dirty rectangle updates
    # -------------------------------------------------------------------------
    clock = Clock()
    pm.meter.start()
    
    # Read frame.rate from config (set via UI), default to 30
    # This overrides the peppymeter [screen] section value
    MAIN_LOOP_FRAME_RATE = meter_config_volumio.get(FRAME_RATE_VOLUMIO, 30)
    log_debug(f"Main loop frame.rate = {MAIN_LOOP_FRAME_RATE} (from config.txt [current] section via UI)", "basic")
    
    # Initialize overlay for first meter
    overlay_init_for_meter(resolve_active_meter_name())
    
    running = True
    exit_events = [pg.MOUSEBUTTONUP]
    if pg.version.ver.startswith("2"):
        exit_events.append(pg.FINGERUP)
    
    # OPTIMIZATION: Frame counter for spectrum throttling
    frame_counter = 0
    # Read update.interval from config (set via UI), default to 2
    SPECTRUM_UPDATE_INTERVAL = meter_config_volumio.get(UPDATE_INTERVAL, 2)
    
    # OPTIMIZATION: Idle detection - skip work when playback stopped
    last_status = ""
    idle_frame_skip = 0
    
    # DEBUG: Track previous values for change detection logging
    _dbg_last_status = ""
    _dbg_last_volatile = False
    _dbg_last_seek_raw = 0
    _dbg_last_seek_interp = 0
    _dbg_last_progress = 0.0
    _dbg_frame_count = 0
    _dbg_log_time = 0  # Throttle periodic logging
    last_reload_check = 0.0  # For check_reload_callback throttling
    
    while running:
        # CHECK PROFILING DURATION: Auto-stop cProfile if duration exceeded
        check_profiling_duration()
        
        # CHECK STOP SIGNAL: Exit if plugin removed runFlag
        # This is separate from touch/mouse exit handling to ensure
        # clean shutdown when plugin requests stop
        if not os.path.exists(PeppyRunning):
            log_debug("runFlag removed - initiating shutdown", "basic")
            running = False
            break
        
        current_time = time.time()
        # CHECK RELOAD (remote client): exit so client can re-fetch config and restart
        if check_reload_callback and (current_time - last_reload_check) >= 1.0:
            last_reload_check = current_time
            try:
                if check_reload_callback():
                    log_debug("Config reload requested - exiting display loop", "basic")
                    running = False
                    break
            except Exception:
                pass
        now_ticks = pg.time.get_ticks()  # OPTIMIZATION: For FPS-gated rendering
        dirty_rects = []  # OPTIMIZATION: Collect dirty rectangles
        frame_counter += 1
        
        # OPTIMIZATION: Idle detection - reduce frame rate when stopped/paused
        current_status = last_metadata.get("status", "")
        if current_status != last_status:
            last_status = current_status
            idle_frame_skip = 0
        
        if current_status in ("stop", "pause", ""):
            # When idle, skip every other frame to reduce CPU
            idle_frame_skip += 1
            if idle_frame_skip % 2 == 0:
                # Still handle events even when skipping
                for event in pg.event.get():
                    if event.type == pg.QUIT:
                        running = False
                    elif event.type in exit_events:
                        if cfg.get(EXIT_ON_TOUCH, False) or cfg.get(STOP_DISPLAY_ON_TOUCH, False):
                            running = False
                clock.tick(MAIN_LOOP_FRAME_RATE)
                continue
        
        # Check for random meter change
        nm = resolve_active_meter_name()
        if nm != active_meter_name:
            overlay_init_for_meter(nm)
        
        # Handle title-change random restart
        # Only restart if there are multiple meters to choose from
        if title_changed_flag[0]:
            title_changed_flag[0] = False
            meter_names = cfg.get(METER_NAMES) or []
            if len(meter_names) > 1:
                callback.pending_restart = True
        
        # Handle interval-based random restart
        # Only restart if there are multiple meters
        if random_interval_mode:
            random_timer += clock.get_time() / 1000.0
            if random_timer >= random_interval:
                random_timer = 0
                meter_names = cfg.get(METER_NAMES) or []
                if len(meter_names) > 1:
                    callback.pending_restart = True
        
        # Get overlay state
        ov = overlay_state
        
        if not ov.get("enabled", False):
            # No extended config - just run meter with dirty rect updates
            meter_rects = pm.meter.run()
            callback.peppy_meter_update()
            # OPTIMIZATION: Use dirty rectangle update
            if meter_rects:
                pg.display.update(meter_rects)
            else:
                pg.display.update()
        else:
            # Check for handler delegation
            handler = ov.get("handler")
            if handler:
                # PROFILING: Time the handler render
                t_render_start = time.perf_counter() if PROFILING_TIMING_ENABLED else 0
                
                # Get queue mode from config
                queue_mode = meter_config_volumio.get(QUEUE_MODE, "track")
                
                # Pass queue mode to metadata (for MetadataWatcher calculations)
                last_metadata["_queue_mode"] = queue_mode
                
                # Handler-based rendering (handler calls meter.run() internally)
                dirty_rects = handler.render(last_metadata, now_ticks)
                
                # PROFILING: Log frame timing
                if PROFILING_TIMING_ENABLED:
                    t_render_end = time.perf_counter()
                    # Note: Per-component timing requires handler instrumentation
                    # Here we just log total render time
                    log_frame_timing(
                        frame_counter,
                        t_render_start,
                        None,  # t_meter - not available at this level
                        None,  # t_rotation - not available at this level
                        None,  # t_blit - not available at this level
                        None,  # t_scroll - not available at this level
                        t_render_end  # t_end - total render time
                    )
                
                # TRACE: Log meter activity (meter.run() called by handler)
                if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("meters", False):
                    try:
                        ds = pm.data_source
                        if ds:
                            left = ds.get_current_left_channel_data()
                            right = ds.get_current_right_channel_data()
                            mono = ds.get_current_mono_channel_data()
                            log_debug(f"[Meter] INPUT: left={left}, right={right}, mono={mono}", "trace", "meters")
                    except Exception:
                        pass
                
                callback.peppy_meter_update()
                
                # Display update
                if dirty_rects:
                    pg.display.update(dirty_rects)
                else:
                    pg.display.update()
                
                # Handle events
                for event in pg.event.get():
                    if event.type == pg.QUIT:
                        running = False
                    elif event.type in exit_events:
                        if cfg.get(EXIT_ON_TOUCH, False) or cfg.get(STOP_DISPLAY_ON_TOUCH, False):
                            running = False
                
                clock.tick(MAIN_LOOP_FRAME_RATE)
                
                # Frame timing trace (handler path)
                if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("frame", False):
                    frame_time_ms = clock.get_time()
                    fps_actual = clock.get_fps()
                    log_debug(f"[Frame] #{frame_counter}: time={frame_time_ms}ms, fps={fps_actual:.1f}, dirty_rects={len(dirty_rects)}", "trace", "frame")
                
                # Broadcast level data to remote clients (handler path)
                if level_server and level_server.enabled:
                    try:
                        ds = pm.data_source
                        if ds:
                            left = ds.get_current_left_channel_data()
                            right = ds.get_current_right_channel_data()
                            mono = ds.get_current_mono_channel_data()
                            level_server.broadcast(left, right, mono)
                            # Log first successful broadcast
                            if not hasattr(level_server, '_logged_first'):
                                log_debug(f"[NetworkLevelServer] First broadcast: L={left}, R={right}, M={mono}", "basic")
                                level_server._logged_first = True
                        else:
                            if not hasattr(level_server, '_logged_no_ds'):
                                log_debug("[NetworkLevelServer] No data_source available", "basic")
                                level_server._logged_no_ds = True
                    except Exception as e:
                        # Log first error only to avoid spam
                        if not hasattr(level_server, '_logged_error'):
                            log_debug(f"[NetworkLevelServer] Broadcast exception: {e}", "basic")
                            level_server._logged_error = True
                
                # Broadcast spectrum data to remote clients (handler path)
                if spectrum_server and spectrum_server.enabled:
                    # In injected mode, get bins from SpectrumOutput (which reads the pipe)
                    if not spectrum_server.read_pipe:
                        bins = None
                        source = "none"
                        
                        # First try: SpectrumOutput (for handler-based meters with spectrum overlay)
                        if callback.spectrum_output:
                            bins = callback.spectrum_output.get_current_bins()
                            source = "spectrum_output"
                        
                        # Second try: Direct from pm.meter if it IS a Spectrum (spectrum-only meters)
                        # This avoids pipe contention when the meter itself is the spectrum renderer
                        if not bins or all(b == 0 for b in bins):
                            if hasattr(pm.meter, '_prev_bar_heights') and pm.meter._prev_bar_heights:
                                meter_bins = list(pm.meter._prev_bar_heights)
                                if any(b > 0 for b in meter_bins):
                                    bins = meter_bins
                                    source = "pm.meter"
                                    if not hasattr(spectrum_server, '_logged_meter_fallback'):
                                        log_debug("[NetworkSpectrumServer] Using pm.meter._prev_bar_heights as source", "basic")
                                        spectrum_server._logged_meter_fallback = True
                        
                        if bins:
                            spectrum_server.set_bins(bins)
                        elif not callback.spectrum_output:
                            # No local spectrum active - switch to pipe mode
                            if not spectrum_server._switched_to_pipe:
                                log_debug("[NetworkSpectrumServer] No local spectrum, switching to pipe mode", "basic")
                                spectrum_server.read_pipe = True
                                spectrum_server._open_pipe()
                                spectrum_server._switched_to_pipe = True
                    spectrum_server.broadcast()
                
                continue
        
        # Handle events
        for event in pg.event.get():
            if event.type == pg.QUIT:
                running = False
            elif event.type in (pg.KEYDOWN, pg.KEYUP):
                keys = pg.key.get_pressed()
                if (keys[pg.K_LCTRL] or keys[pg.K_RCTRL]) and event.key == pg.K_c:
                    running = False
            elif event.type in exit_events:
                if cfg.get(EXIT_ON_TOUCH, False) or cfg.get(STOP_DISPLAY_ON_TOUCH, False):
                    running = False
        
        # Broadcast level data to remote clients (if server mode enabled)
        if level_server and level_server.enabled:
            try:
                ds = pm.data_source
                if ds:
                    left = ds.get_current_left_channel_data()
                    right = ds.get_current_right_channel_data()
                    mono = ds.get_current_mono_channel_data()
                    level_server.broadcast(left, right, mono)
                    # Log first successful broadcast
                    if not hasattr(level_server, '_logged_first'):
                        log_debug(f"[NetworkLevelServer] First broadcast: L={left}, R={right}, M={mono}", "basic")
                        level_server._logged_first = True
                else:
                    if not hasattr(level_server, '_logged_no_ds'):
                        log_debug("[NetworkLevelServer] No data_source available", "basic")
                        level_server._logged_no_ds = True
            except Exception as e:
                # Log first error only to avoid spam
                if not hasattr(level_server, '_logged_error'):
                    log_debug(f"[NetworkLevelServer] Broadcast exception: {e}", "basic")
                    level_server._logged_error = True
        
        # Broadcast spectrum data to remote clients (if server mode enabled)
        # NOTE: This is the NON-HANDLER path - only runs when no handler is active
        if spectrum_server and spectrum_server.enabled:
            # In injected mode, get bins from SpectrumOutput (which reads the pipe)
            if not spectrum_server.read_pipe:
                bins = None
                
                # First try: SpectrumOutput (for handler-based meters with spectrum overlay)
                if callback.spectrum_output:
                    bins = callback.spectrum_output.get_current_bins()
                
                # Second try: Direct from pm.meter if it IS a Spectrum (spectrum-only meters)
                # This avoids pipe contention when the meter itself is the spectrum renderer
                if not bins or all(b == 0 for b in bins):
                    if hasattr(pm.meter, '_prev_bar_heights') and pm.meter._prev_bar_heights:
                        meter_bins = list(pm.meter._prev_bar_heights)
                        if any(b > 0 for b in meter_bins):
                            bins = meter_bins
                            if not hasattr(spectrum_server, '_logged_meter_fallback'):
                                log_debug("[NetworkSpectrumServer] Using pm.meter._prev_bar_heights as source", "basic")
                                spectrum_server._logged_meter_fallback = True
                
                if bins:
                    spectrum_server.set_bins(bins)
                elif not callback.spectrum_output:
                    # No local spectrum active - switch to pipe mode
                    if not spectrum_server._switched_to_pipe:
                        log_debug("[NetworkSpectrumServer] No local spectrum, switching to pipe mode", "basic")
                        spectrum_server.read_pipe = True
                        spectrum_server._open_pipe()
                        spectrum_server._switched_to_pipe = True
            spectrum_server.broadcast()
        
        clock.tick(MAIN_LOOP_FRAME_RATE)
        
        # Frame timing trace
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("frame", False):
            frame_time_ms = clock.get_time()
            fps_actual = clock.get_fps()
            log_debug(f"[Frame] #{frame_counter}: time={frame_time_ms}ms, fps={fps_actual:.1f}, dirty_rects={len(dirty_rects)}", "trace", "frame")
    
    # Exiting for config reload (remote client): stop watchers but keep display alive for restart
    if check_reload_callback:
        try:
            if check_reload_callback():
                log_debug("Exiting for config reload - stopping watchers only", "basic")
                if level_server:
                    level_server.stop()
                if spectrum_server:
                    spectrum_server.stop()
                if discovery_announcer:
                    discovery_announcer.stop()
                final_handler = overlay_state.get("handler") if overlay_state else None
                if final_handler:
                    try:
                        final_handler.cleanup()
                    except Exception:
                        pass
                metadata_watcher.stop()
                return
        except Exception:
            pass
    
    # Fade-out transition before cleanup (only if we did fade-in)
    if callback.did_fade_in:
        # Recreate runFlag to prevent new instance starting during our fade_out
        # index.js checks this flag before starting peppymeter
        Path(PeppyRunning).touch()
        log_debug("runFlag recreated for fade_out protection", "trace", "fade")
        
        duration = meter_config_volumio.get(TRANSITION_DURATION, 0.5)
        callback.screen_fade_out(screen, duration)
        
        # Remove runFlag after fade_out complete
        if os.path.exists(PeppyRunning):
            os.remove(PeppyRunning)
            log_debug("runFlag removed after fade_out", "trace", "fade")
    else:
        log_debug("screen_fade_out skipped (no fade_in was done)", "trace", "fade")
    
    # Cleanup
    log_debug("=== Shutting down ===", "basic")
    
    # Stop remote display server components
    if level_server:
        log_debug("  Stopping level server", "verbose")
        level_server.stop()
    if spectrum_server:
        log_debug("  Stopping spectrum server", "verbose")
        spectrum_server.stop()
    if discovery_announcer:
        log_debug("  Stopping discovery announcer", "verbose")
        discovery_announcer.stop()
    
    # Cleanup handler resources
    final_handler = overlay_state.get("handler") if overlay_state else None
    if final_handler:
        log_debug("  Cleaning up handler", "verbose")
        try:
            final_handler.cleanup()
        except Exception as e:
            log_debug(f"  Handler cleanup error (non-fatal): {e}", "verbose")
    
    metadata_watcher.stop()
    
    # Stop profiling and save results
    stop_profiling()
    
    pm.exit()


# =============================================================================
# Main Entry Point
# =============================================================================
if __name__ == "__main__":
    """Called by Volumio to start PeppyMeter."""
    
    # Enable X11 threading
    ctypes.CDLL('libX11.so.6').XInitThreads()
    
    # Get peppymeter object
    os.chdir(PeppyPath)
    pm = Peppymeter(standalone=True, timer_controlled_random_meter=False, quit_pygame_on_stop=False)
    
    # Parse Volumio configuration
    parser = Volumio_ConfigFileParser(pm.util)
    meter_config_volumio = parser.meter_config_volumio
    
    # Initialize debug settings from config (sets level and trace switches)
    init_debug_config(meter_config_volumio)
    
    # Clear debug log on fresh start (after config is loaded)
    if DEBUG_LEVEL_CURRENT != "off":
        try:
            with open(DEBUG_LOG_FILE, 'w') as f:
                f.write("")
        except Exception:
            pass
    log_debug(f"Debug level set to: {DEBUG_LEVEL_CURRENT}", "basic")
    
    # Initialize profiling settings (must be after debug init to use log_debug)
    init_profiling_config(meter_config_volumio)
    
    # Log enabled trace components (AFTER file clearing)
    if DEBUG_LEVEL_CURRENT == "trace":
        enabled = [k for k, v in DEBUG_TRACE.items() if v]
        if enabled:
            log_debug(f"Trace components enabled: {', '.join(enabled)}", "basic")
    
    log_debug("=== PeppyMeter starting ===", "basic")
    log_debug(f"Config file: {os.path.join(os.getcwd(), 'config.txt')}", "basic")
    log_debug(f"Meters file: {parser.meter_config_path}", "basic")
    log_debug("--- Global Config (config.txt) ---", "verbose")
    log_debug(f"  rotation.quality = {meter_config_volumio.get(ROTATION_QUALITY, 'medium')}", "verbose")
    log_debug(f"  rotation.fps = {meter_config_volumio.get(ROTATION_FPS, 8)}", "verbose")
    log_debug(f"  rotation.speed = {meter_config_volumio.get(ROTATION_SPEED, 1.0)}", "verbose")
    log_debug(f"  spool.left.speed = {meter_config_volumio.get(SPOOL_LEFT_SPEED, 1.0)}", "verbose")
    log_debug(f"  spool.right.speed = {meter_config_volumio.get(SPOOL_RIGHT_SPEED, 1.0)}", "verbose")
    log_debug(f"  reel.direction = {meter_config_volumio.get(REEL_DIRECTION, 'ccw')}", "verbose")
    log_debug(f"  scrolling.mode = {meter_config_volumio.get('scrolling.mode', 'skin')}", "verbose")
    log_debug(f"  scrolling.speed.artist = {meter_config_volumio.get('scrolling.speed.artist', 40)}", "verbose")
    log_debug(f"  scrolling.speed.title = {meter_config_volumio.get('scrolling.speed.title', 40)}", "verbose")
    log_debug(f"  scrolling.speed.album = {meter_config_volumio.get('scrolling.speed.album', 40)}", "verbose")
    log_debug(f"  color.depth = {meter_config_volumio.get(COLOR_DEPTH, 32)}", "verbose")
    log_debug(f"  position.type = {meter_config_volumio.get(POSITION_TYPE, 'center')}", "verbose")
    log_debug(f"  position.x = {meter_config_volumio.get(POS_X, 0)}", "verbose")
    log_debug(f"  position.y = {meter_config_volumio.get(POS_Y, 0)}", "verbose")
    log_debug(f"  transition.type = {meter_config_volumio.get(TRANSITION_TYPE, 'fade')}", "verbose")
    log_debug(f"  transition.duration = {meter_config_volumio.get(TRANSITION_DURATION, 0.5)}", "verbose")
    log_debug(f"  transition.color = {meter_config_volumio.get(TRANSITION_COLOR, 'black')}", "verbose")
    log_debug(f"  transition.opacity = {meter_config_volumio.get(TRANSITION_OPACITY, 100)}", "verbose")
    log_debug(f"  start.animation = {meter_config_volumio.get(START_ANIMATION, False)}", "verbose")
    log_debug(f"  update.interval = {meter_config_volumio.get(UPDATE_INTERVAL, 2)}", "verbose")
    log_debug(f"  font.path = {meter_config_volumio.get(FONT_PATH, '')}", "verbose")
    log_debug("--- End Global Config ---", "verbose")
    
    # Create callback handler
    callback = CallBack(pm.util, meter_config_volumio, pm.meter)
    pm.meter.callback_start = callback.peppy_meter_start
    pm.meter.callback_stop = callback.peppy_meter_stop
    pm.dependent = callback.peppy_meter_update
    pm.meter.malloc_trim = callback.trim_memory
    pm.malloc_trim = callback.exit_trim_memory
    
    # Initialize display
    screen_w = pm.util.meter_config[SCREEN_INFO][WIDTH]
    screen_h = pm.util.meter_config[SCREEN_INFO][HEIGHT]
    
    memory_limit()
    
    try:
        Path(PeppyRunning).touch()
        Path(PeppyRunning).chmod(0o0777)
        
        # Start stop watcher
        watcher = Thread(target=stop_watcher, daemon=True)
        watcher.start()
        
        # Initialize display with SDL2 positioning support
        if use_sdl2:
            # Grab screenshot to get full display dimensions
            try:
                screenshot_img = pyscreenshot.grab()
                display_w = screenshot_img.size[0]
                display_h = screenshot_img.size[1]
            except Exception as e:
                log_debug(f"pyscreenshot failed: {e}, using meter size")
                display_w = screen_w
                display_h = screen_h
            
            # Calculate position
            if meter_config_volumio.get(POSITION_TYPE) == "center":
                screen_x = int((display_w - screen_w) / 2)
                screen_y = int((display_h - screen_h) / 2)
            else:
                screen_x = meter_config_volumio.get(POS_X, 0)
                screen_y = meter_config_volumio.get(POS_Y, 0)
            
            log_debug(f"SDL2 positioning: display={display_w}x{display_h}, meter={screen_w}x{screen_h}, pos=({screen_x},{screen_y})")
            
            # Initialize hidden display
            pm.util.PYGAME_SCREEN = init_display(pm, meter_config_volumio, screen_w, screen_h, hide=True)
            pm.util.screen_copy = pm.util.PYGAME_SCREEN
            
            # Position and show window
            try:
                win = Window.from_display_module()
                win.position = (screen_x, screen_y)
                Window.show(win)
                log_debug("SDL2 window positioned and shown")
            except Exception as e:
                log_debug(f"Window positioning failed: {e}")
        else:
            # Non-SDL2 fallback
            pm.util.PYGAME_SCREEN = init_display(pm, meter_config_volumio, screen_w, screen_h)
            pm.util.screen_copy = pm.util.PYGAME_SCREEN
        
        # Run main display loop
        start_display_output(pm, callback, meter_config_volumio)
        
    except MemoryError:
        print('ERROR: Memory Exception')
        callback.exit_trim_memory()
        del pm
        del callback
        trim_memory()
        if os.path.exists(PeppyRunning):
            os.remove(PeppyRunning)
        os._exit(1)
