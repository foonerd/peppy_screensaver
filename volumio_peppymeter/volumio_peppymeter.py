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
import requests
import pygame as pg
import socketio

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
    TRANSITION_TYPE, TRANSITION_DURATION, TRANSITION_COLOR, TRANSITION_OPACITY,
    DEBUG_LEVEL, ROTATION_QUALITY, ROTATION_FPS, ROTATION_SPEED,
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
    METER_BKP, RANDOM_TITLE, SPECTRUM, SPECTRUM_SIZE
)

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

# Import CPU rendering components (extracted for GPU/CPU switching)
from volumio_render_cpu import (
    compute_foreground_regions,
    get_rotation_params,
    ScrollingLabel,
    AlbumArtRenderer,
    ReelRenderer,
    TonearmRenderer,
    ROTATION_PRESETS,
    USE_PRECOMPUTED_FRAMES,
    TONEARM_STATE_REST,
    TONEARM_STATE_DROP,
    TONEARM_STATE_TRACKING,
    TONEARM_STATE_LIFT,
    set_log_debug as set_cpu_log_debug,
)

# Import GPU rendering components (optional - with fallback)
try:
    from volumio_render_gpu import (
        is_gpu_available,
        GPURenderer,
        AlbumArtRendererGPU,
        TonearmRendererGPU,
        ReelRendererGPU,
    )
    GPU_MODULE_AVAILABLE = True
except ImportError:
    GPU_MODULE_AVAILABLE = False
    
    def is_gpu_available():
        return False



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

from volumio_spectrum import SpectrumOutput

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
# Levels: off, basic, verbose
# When enabled, writes to /tmp/peppy_debug.log
DEBUG_LOG_FILE = '/tmp/peppy_debug.log'

# Global debug level - will be set from config after parsing
# Default to off until config is loaded
DEBUG_LEVEL_CURRENT = "off"

def log_debug(msg, level="basic"):
    """Write debug message to log file based on debug level.
    
    :param msg: Message to log
    :param level: Required level - 'basic' or 'verbose'
    """
    if DEBUG_LEVEL_CURRENT == "off":
        return
    if DEBUG_LEVEL_CURRENT == "basic" and level == "verbose":
        return
    # verbose level logs everything
    try:
        import datetime
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# Wire up log_debug to CPU render module
set_cpu_log_debug(log_debug)

# Runtime paths
PeppyRunning = '/tmp/peppyrunning'
CurDir = os.getcwd()
PeppyPath = CurDir + '/screensaver/peppymeter'


# =============================================================================
# MetadataWatcher - Socket.io listener for pushState events
# =============================================================================
class MetadataWatcher:
    """
    Watches Volumio pushState events via socket.io.
    Updates shared metadata dict and signals title changes for random meter mode.
    Eliminates HTTP polling - state updates are event-driven.
    """
    
    def __init__(self, metadata_dict, title_changed_callback=None):
        self.metadata = metadata_dict
        self.title_callback = title_changed_callback
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.run_flag = True
        self.thread = None
        self.last_title = None
        self.first_run = True
        
        # Time tracking for countdown (moved here from main loop)
        self.time_remain_sec = -1
        self.time_last_update = 0
        self.time_service = ""
    
    def start(self):
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
    
    def _run(self):
        @self.sio.on('pushState')
        def on_push_state(data):
            if not self.run_flag:
                return
            
            # Extract metadata
            self.metadata["artist"] = data.get("artist", "") or ""
            self.metadata["title"] = data.get("title", "") or ""
            self.metadata["album"] = data.get("album", "") or ""
            self.metadata["albumart"] = data.get("albumart", "") or ""
            self.metadata["samplerate"] = str(data.get("samplerate", "") or "")
            self.metadata["bitdepth"] = str(data.get("bitdepth", "") or "")
            self.metadata["trackType"] = data.get("trackType", "") or ""
            self.metadata["bitrate"] = str(data.get("bitrate", "") or "")
            self.metadata["service"] = data.get("service", "") or ""
            self.metadata["status"] = data.get("status", "") or ""
            
            # Update time tracking
            import time
            duration = data.get("duration", 0) or 0
            seek = data.get("seek", 0) or 0
            service = data.get("service", "")
            
            # Store duration and seek for progress calculation (tonearm, etc)
            self.metadata["duration"] = duration
            self.metadata["seek"] = seek
            self.metadata["_seek_update"] = time.time()  # Track when seek was received
            
            if service != self.time_service or abs(seek / 1000 - (duration - self.time_remain_sec)) > 3:
                # Reset time on track change or significant seek
                if duration > 0:
                    self.time_remain_sec = max(0, duration - (seek // 1000))
                else:
                    self.time_remain_sec = -1  # No time to display for webradio
                self.time_last_update = time.time()
                self.time_service = service
            
            self.metadata["_time_remain"] = self.time_remain_sec
            self.metadata["_time_update"] = self.time_last_update
            
            # Check for title change (for random meter mode)
            current_title = self.metadata["title"]
            if self.title_callback and current_title != self.last_title:
                self.last_title = current_title
                if not self.first_run:
                    self.title_callback()
                self.first_run = False
        
        @self.sio.on('connect')
        def on_connect():
            if self.run_flag:
                self.sio.emit('getState')
        
        while self.run_flag:
            try:
                self.sio.connect('http://localhost:3000', transports=['websocket'])
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
    
    def stop(self):
        self.run_flag = False
        if self.sio.connected:
            try:
                self.sio.disconnect()
            except Exception:
                pass


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
        log_debug(f"screen_fade_in called, duration={duration}")
        
        transition_type = self.meter_config_volumio.get(TRANSITION_TYPE, "fade")
        if transition_type == "none":
            log_debug("-> skipped (transition_type=none)")
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
        log_debug(f"-> fade_in with opacity={opacity}%, max_alpha={max_alpha}")
        
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
        log_debug(f"screen_fade_out called, duration={duration}")
        
        transition_type = self.meter_config_volumio.get(TRANSITION_TYPE, "fade")
        if transition_type == "none":
            log_debug("-> skipped (transition_type=none)")
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
        log_debug(f"-> fade_out with opacity={opacity}%, max_alpha={max_alpha}")
        
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
        
        # Debug: track calls
        time_since_last = current_time - self.last_fade_time
        log_debug(f"peppy_meter_start: first_run={self.first_run}, animation={animation}, duration={duration}s, cooldown={cooldown}s")
        
        # Use file-based cooldown that persists across process restarts
        # This prevents double fade when skin change triggers multiple restarts
        fade_lockfile = '/tmp/peppy_fade_lock'
        should_fade = False
        
        try:
            if os.path.exists(fade_lockfile):
                lock_mtime = os.path.getmtime(fade_lockfile)
                lock_age = current_time - lock_mtime
                log_debug(f"-> fade lock exists, age={lock_age:.2f}s")
                if lock_age > cooldown:
                    # Lock expired, allow fade
                    should_fade = True
                else:
                    log_debug(f"-> skipped (lock active: {lock_age:.2f}s < {cooldown}s)")
            else:
                # No lock, allow fade
                should_fade = True
        except Exception as e:
            log_debug(f"-> lock check error: {e}")
            should_fade = True
        
        # Only fade on first run with animation, or meter change
        if should_fade:
            if self.first_run and animation:
                log_debug("-> will fade (first_run + animation)")
                # Touch lock file
                Path(fade_lockfile).touch()
                self.did_fade_in = True
                self.screen_fade_in(meter.util.PYGAME_SCREEN, duration)
            elif not self.first_run:
                log_debug("-> will fade (meter change)")
                Path(fade_lockfile).touch()
                self.did_fade_in = True
                self.screen_fade_in(meter.util.PYGAME_SCREEN, duration)
            else:
                log_debug("-> no fade (first_run but no animation)")
        
        # Restore screen reference
        meter.util.PYGAME_SCREEN = meter.util.screen_copy
        for comp in meter.components:
            comp.screen = meter.util.screen_copy
        
        if meter_section_volumio[EXTENDED_CONF]:
            # Stop meters if not visible
            if not meter_section_volumio[METER_VISIBLE]:
                meter.stop()
            
            # Start spectrum if visible
            if meter_section_volumio[SPECTRUM_VISIBLE]:
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
def start_display_output(pm, callback, meter_config_volumio):
    """Main display loop with integrated overlay rendering.
    OPTIMIZED: Uses dirty rectangle updates instead of full screen flip.
    GPU: Uses hardware acceleration for rotation when available."""
    
    pg.event.clear()
    screen = pm.util.PYGAME_SCREEN
    SCREEN_WIDTH, SCREEN_HEIGHT = screen.get_size()
    cfg = pm.util.meter_config
    file_path = os.path.dirname(os.path.realpath(__file__))
    
    # -------------------------------------------------------------------------
    # GPU Initialization
    # -------------------------------------------------------------------------
    gpu_renderer = None
    use_gpu = False
    
    # Config option to control GPU (auto/on/off from UI)
    # auto = enable if available (default)
    # on = force GPU rendering
    # off = force CPU rendering
    gpu_config_value = meter_config_volumio.get("gpu.acceleration", "auto")
    if isinstance(gpu_config_value, str):
        gpu_config_value = gpu_config_value.lower().strip()
    else:
        gpu_config_value = "auto"
    log_debug(f"[GPU] Config value: '{gpu_config_value}'", "verbose")
    
    # Determine if GPU should be enabled based on config
    if gpu_config_value == "off":
        gpu_config_enabled = False
    elif gpu_config_value == "on":
        gpu_config_enabled = True
    else:  # "auto" or any other value
        gpu_config_enabled = True  # Will be checked against availability below
    
    if gpu_config_enabled and GPU_MODULE_AVAILABLE and is_gpu_available():
        try:
            gpu_renderer = GPURenderer()
            if gpu_renderer.init_from_display():
                use_gpu = True
                log_debug(f"[GPU] Initialized: driver={gpu_renderer.driver_name}", "basic")
            else:
                log_debug("[GPU] Failed to initialize, falling back to CPU", "basic")
                gpu_renderer = None
        except Exception as e:
            log_debug(f"[GPU] Initialization error: {e}, falling back to CPU", "basic")
            gpu_renderer = None
    elif gpu_config_value == "off":
        log_debug("[GPU] Disabled by config (gpu.acceleration = off)", "basic")
    elif not GPU_MODULE_AVAILABLE or not is_gpu_available():
        if gpu_config_value == "on":
            log_debug("[GPU] Forced on but not available, falling back to CPU", "basic")
        else:
            log_debug("[GPU] Not available, using CPU rendering", "basic")
    else:
        log_debug("[GPU] Not available, using CPU rendering", "basic")
    
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
        title_changed_callback=on_title_change if random_title else None
    )
    metadata_watcher.start()
    
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
        
        fontL = None
        fontR = None
        fontB = None
        fontDigi = None
        
        # Light font
        light_file = meter_config_volumio.get(FONT_LIGHT)
        if light_file and os.path.exists(font_path + light_file):
            fontL = pg.font.Font(font_path + light_file, size_light)
        else:
            fontL = pg.font.SysFont("DejaVuSans", size_light)
        
        # Regular font
        regular_file = meter_config_volumio.get(FONT_REGULAR)
        if regular_file and os.path.exists(font_path + regular_file):
            fontR = pg.font.Font(font_path + regular_file, size_regular)
        else:
            fontR = pg.font.SysFont("DejaVuSans", size_regular)
        
        # Bold font
        bold_file = meter_config_volumio.get(FONT_BOLD)
        if bold_file and os.path.exists(font_path + bold_file):
            fontB = pg.font.Font(font_path + bold_file, size_bold)
        else:
            fontB = pg.font.SysFont("DejaVuSans", size_bold, bold=True)
        
        # Digital font for time
        digi_path = os.path.join(file_path, 'fonts', 'DSEG7Classic-Italic.ttf')
        if os.path.exists(digi_path):
            fontDigi = pg.font.Font(digi_path, size_digi)
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
    # Draw static assets (background, meter graphics)
    # -------------------------------------------------------------------------
    def draw_static_assets(mc):
        base_path = cfg.get(BASE_PATH)
        meter_dir = cfg.get(SCREEN_INFO)[METER_FOLDER]
        meter_path = os.path.join(base_path, meter_dir)
        
        screen_bgr_name = mc.get('screen.bgr')
        bgr_name = mc.get(BGR_FILENAME)
        fgr_name = mc.get(FGR_FILENAME)
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
        
        # Draw meter foreground at meter position
        if fgr_name:
            try:
                img_path = os.path.join(meter_path, fgr_name)
                img = pg.image.load(img_path).convert_alpha()
                screen.blit(img, (meter_x, meter_y))
            except Exception as e:
                print(f"[draw_static_assets] Failed to load fgr '{fgr_name}': {e}")
    
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
        
        # Load fonts
        fontL, fontR, fontB, fontDigi = load_fonts(mc_vol)
        
        # Draw static assets
        draw_static_assets(mc)
        
        # Run meter once to show needles before capture
        pm.meter.run()
        pg.display.update()
        
        # Positions and colors
        center_flag = bool(mc_vol.get(PLAY_CENTER, mc_vol.get(PLAY_TXT_CENTER, False)))
        global_max = as_int(mc_vol.get(PLAY_MAX), 0)
        
        # Scrolling speed logic based on mode
        scrolling_mode = meter_config_volumio.get("scrolling.mode", "skin")
        if scrolling_mode == "default":
            # System default: always 40
            scroll_speed_artist = 40
            scroll_speed_title = 40
            scroll_speed_album = 40
        elif scrolling_mode == "custom":
            # Custom: use UI-specified values
            scroll_speed_artist = meter_config_volumio.get("scrolling.speed.artist", 40)
            scroll_speed_title = meter_config_volumio.get("scrolling.speed.title", 40)
            scroll_speed_album = meter_config_volumio.get("scrolling.speed.album", 40)
        else:
            # Skin mode: per-field from skin -> global from skin -> 40
            scroll_speed_artist = mc_vol.get(SCROLLING_SPEED_ARTIST, 40)
            scroll_speed_title = mc_vol.get(SCROLLING_SPEED_TITLE, 40)
            scroll_speed_album = mc_vol.get(SCROLLING_SPEED_ALBUM, 40)
        
        log_debug(f"Scrolling: mode={scrolling_mode}, artist={scroll_speed_artist}, title={scroll_speed_title}, album={scroll_speed_album}")
        
        artist_pos = mc_vol.get(PLAY_ARTIST_POS)
        title_pos = mc_vol.get(PLAY_TITLE_POS)
        album_pos = mc_vol.get(PLAY_ALBUM_POS)
        time_pos = mc_vol.get(TIME_REMAINING_POS)
        sample_pos = mc_vol.get(PLAY_SAMPLE_POS)
        type_pos = mc_vol.get(PLAY_TYPE_POS)
        type_dim = mc_vol.get(PLAY_TYPE_DIM)
        art_pos = mc_vol.get(ALBUMART_POS)
        art_dim = mc_vol.get(ALBUMART_DIM)
        
        # Styles
        artist_style = mc_vol.get(PLAY_ARTIST_STYLE, FONT_STYLE_L)
        title_style = mc_vol.get(PLAY_TITLE_STYLE, FONT_STYLE_B)
        album_style = mc_vol.get(PLAY_ALBUM_STYLE, FONT_STYLE_L)
        sample_style = mc_vol.get(PLAY_SAMPLE_STYLE, FONT_STYLE_L)
        
        # Fonts per field
        artist_font = font_for_style(artist_style, fontL, fontR, fontB)
        title_font = font_for_style(title_style, fontL, fontR, fontB)
        album_font = font_for_style(album_style, fontL, fontR, fontB)
        sample_font = font_for_style(sample_style, fontL, fontR, fontB)
        
        # Colors
        font_color = sanitize_color(mc_vol.get(FONTCOLOR), (255, 255, 255))
        artist_color = sanitize_color(mc_vol.get(PLAY_ARTIST_COLOR), font_color)
        title_color = sanitize_color(mc_vol.get(PLAY_TITLE_COLOR), font_color)
        album_color = sanitize_color(mc_vol.get(PLAY_ALBUM_COLOR), font_color)
        time_color = sanitize_color(mc_vol.get(TIMECOLOR), font_color)
        type_color = sanitize_color(mc_vol.get(PLAY_TYPE_COLOR), font_color)
        
        # Max widths
        artist_max = as_int(mc_vol.get(PLAY_ARTIST_MAX), 0)
        title_max = as_int(mc_vol.get(PLAY_TITLE_MAX), 0)
        album_max = as_int(mc_vol.get(PLAY_ALBUM_MAX), 0)
        sample_max = as_int(mc_vol.get(PLAY_SAMPLE_MAX), 0)
        
        # Calculate box widths
        RIGHT_MARGIN = 20
        
        def auto_box_width(pos):
            if not pos:
                return 0
            if center_flag:
                return int(SCREEN_WIDTH * 0.6)
            return max(0, SCREEN_WIDTH - pos[0] - RIGHT_MARGIN)
        
        def get_box_width(pos, field_max):
            if field_max:
                return field_max
            if global_max:
                return global_max
            return auto_box_width(pos)
        
        artist_box = get_box_width(artist_pos, artist_max)
        title_box = get_box_width(title_pos, title_max)
        album_box = get_box_width(album_pos, album_max)
        # Sample box: use sample_max if set, else calculate from text width (NOT global_max)
        # Original code uses rendered text width for "-44.1 kHz 24 bit-"
        if sample_pos and (global_max or sample_max):
            if sample_max:
                sample_box = sample_max
            else:
                # Calculate from typical sample rate text
                sample_box = sample_font.size('-44.1 kHz 24 bit-')[0]
        else:
            sample_box = 0
        
        # Capture backing surfaces
        backing = []
        backing_dict = {}  # OPTIMIZATION: Dict for quick lookup
        screen_rect = screen.get_rect()  # Screen bounds for clipping
        
        def capture_rect(name, pos, width, height):
            if pos and width and height:
                r = pg.Rect(pos[0], pos[1], int(width), int(height))
                # Clip to screen bounds to avoid subsurface failure
                clipped = r.clip(screen_rect)
                if clipped.width > 0 and clipped.height > 0:
                    try:
                        surf = screen.subsurface(clipped).copy()
                        backing.append((clipped, surf))
                        backing_dict[name] = (clipped, surf)
                    except Exception:
                        # Fallback: create black surface
                        s = pg.Surface((clipped.width, clipped.height))
                        s.fill((0, 0, 0))
                        backing.append((clipped, s))
                        backing_dict[name] = (clipped, s)
        
        if artist_pos:
            capture_rect("artist", artist_pos, artist_box, artist_font.get_linesize())
        if title_pos:
            capture_rect("title", title_pos, title_box, title_font.get_linesize())
        if album_pos:
            capture_rect("album", album_pos, album_box, album_font.get_linesize())
        if time_pos:
            capture_rect("time", time_pos, fontDigi.size('00:00')[0] + 10, fontDigi.get_linesize())
        if sample_pos and sample_box:
            capture_rect("sample", sample_pos, sample_box, sample_font.get_linesize())
        if type_pos and type_dim:
            capture_rect("type", type_pos, type_dim[0], type_dim[1])
        if art_pos and art_dim:
            capture_rect("art", art_pos, art_dim[0], art_dim[1])
        
        # Create album art renderer (handles rotation if enabled)
        album_renderer = None
        album_renderer_gpu = None
        if art_pos and art_dim:
            rotate_enabled = mc_vol.get(ALBUMART_ROT, False)
            rotate_rpm = as_float(mc_vol.get(ALBUMART_ROT_SPEED), 0.0)
            screen_size = (cfg[SCREEN_INFO][WIDTH], cfg[SCREEN_INFO][HEIGHT])
            
            # Get rotation quality settings from global config
            rot_quality = meter_config_volumio.get(ROTATION_QUALITY, "medium")
            rot_custom_fps = meter_config_volumio.get(ROTATION_FPS, 8)
            rot_fps, rot_step = get_rotation_params(rot_quality, rot_custom_fps)
            rot_speed_mult = meter_config_volumio.get(ROTATION_SPEED, 1.0)
            
            # CPU renderer (always created - handles image loading/masking)
            album_renderer = AlbumArtRenderer(
                base_path=cfg.get(BASE_PATH),
                meter_folder=cfg.get(SCREEN_INFO)[METER_FOLDER],
                art_pos=art_pos,
                art_dim=art_dim,
                screen_size=screen_size,
                font_color=font_color,
                border_width=mc_vol.get(ALBUMBORDER) or 0,
                mask_filename=mc_vol.get(ALBUMART_MSK),
                rotate_enabled=rotate_enabled,
                rotate_rpm=rotate_rpm,
                angle_step_deg=0.5,
                spindle_radius=5,
                ring_radius=max(3, min(art_dim[0], art_dim[1]) // 10),
                circle=rotate_enabled,  # Only circular when rotation enabled
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=rot_speed_mult
            )
            
            # GPU renderer (if available and rotation enabled)
            if use_gpu and gpu_renderer and rotate_enabled and rotate_rpm > 0:
                album_renderer_gpu = AlbumArtRendererGPU(
                    gpu_renderer=gpu_renderer,
                    art_pos=art_pos,
                    art_dim=art_dim,
                    rotate_enabled=True,
                    rotate_rpm=rotate_rpm * rot_speed_mult,
                    rotation_fps=rot_fps
                )
                log_debug(f"[GPU] AlbumArtRendererGPU created", "basic")
        
        # Create reel renderers (for cassette skins)
        reel_left_renderer = None
        reel_right_renderer = None
        reel_left_renderer_gpu = None
        reel_right_renderer_gpu = None
        
        reel_left_file = mc_vol.get(REEL_LEFT_FILE)
        reel_left_pos = mc_vol.get(REEL_LEFT_POS)
        reel_left_center = mc_vol.get(REEL_LEFT_CENTER)
        reel_right_file = mc_vol.get(REEL_RIGHT_FILE)
        reel_right_pos = mc_vol.get(REEL_RIGHT_POS)
        reel_right_center = mc_vol.get(REEL_RIGHT_CENTER)
        reel_rpm = as_float(mc_vol.get(REEL_ROTATION_SPEED), 0.0)
        
        # Get rotation quality settings from global config (shared with album art)
        rot_quality = meter_config_volumio.get(ROTATION_QUALITY, "medium")
        rot_custom_fps = meter_config_volumio.get(ROTATION_FPS, 8)
        rot_fps, rot_step = get_rotation_params(rot_quality, rot_custom_fps)
        spool_left_mult = meter_config_volumio.get(SPOOL_LEFT_SPEED, 1.0)
        spool_right_mult = meter_config_volumio.get(SPOOL_RIGHT_SPEED, 1.0)
        # Per-meter reel direction (meters.txt) takes priority over global config
        reel_direction = mc_vol.get(REEL_DIRECTION) or meter_config_volumio.get(REEL_DIRECTION, "ccw")
        
        if reel_left_file and reel_left_center:
            reel_left_renderer = ReelRenderer(
                base_path=cfg.get(BASE_PATH),
                meter_folder=cfg.get(SCREEN_INFO)[METER_FOLDER],
                filename=reel_left_file,
                pos=reel_left_pos,
                center=reel_left_center,
                rotate_rpm=reel_rpm,
                angle_step_deg=1.0,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=spool_left_mult,
                direction=reel_direction
            )
            # Capture backing for left reel
            backing_rect = reel_left_renderer.get_backing_rect()
            if backing_rect:
                capture_rect("reel_left", (backing_rect.x, backing_rect.y), backing_rect.width, backing_rect.height)
            
            # GPU reel renderer (if available)
            if use_gpu and gpu_renderer and reel_rpm > 0 and reel_left_renderer._original_surf:
                reel_left_renderer_gpu = ReelRendererGPU(
                    gpu_renderer=gpu_renderer,
                    pos=reel_left_pos,
                    center=reel_left_center,
                    rotate_rpm=reel_rpm * spool_left_mult,
                    rotation_fps=rot_fps,
                    direction=reel_direction
                )
                reel_left_renderer_gpu.load_surface(reel_left_renderer._original_surf)
                log_debug(f"[GPU] ReelRendererGPU (left) created", "basic")
        
        if reel_right_file and reel_right_center:
            reel_right_renderer = ReelRenderer(
                base_path=cfg.get(BASE_PATH),
                meter_folder=cfg.get(SCREEN_INFO)[METER_FOLDER],
                filename=reel_right_file,
                pos=reel_right_pos,
                center=reel_right_center,
                rotate_rpm=reel_rpm,
                angle_step_deg=1.0,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=spool_right_mult,
                direction=reel_direction
            )
            # Capture backing for right reel
            backing_rect = reel_right_renderer.get_backing_rect()
            if backing_rect:
                capture_rect("reel_right", (backing_rect.x, backing_rect.y), backing_rect.width, backing_rect.height)
            
            # GPU reel renderer (if available)
            if use_gpu and gpu_renderer and reel_rpm > 0 and reel_right_renderer._original_surf:
                reel_right_renderer_gpu = ReelRendererGPU(
                    gpu_renderer=gpu_renderer,
                    pos=reel_right_pos,
                    center=reel_right_center,
                    rotate_rpm=reel_rpm * spool_right_mult,
                    rotation_fps=rot_fps,
                    direction=reel_direction
                )
                reel_right_renderer_gpu.load_surface(reel_right_renderer._original_surf)
                log_debug(f"[GPU] ReelRendererGPU (right) created", "basic")
        
        # Create tonearm renderer (for turntable skins)
        tonearm_renderer = None
        
        tonearm_file = mc_vol.get(TONEARM_FILE)
        tonearm_pivot_screen = mc_vol.get(TONEARM_PIVOT_SCREEN)
        tonearm_pivot_image = mc_vol.get(TONEARM_PIVOT_IMAGE)
        
        if tonearm_file and tonearm_pivot_screen and tonearm_pivot_image:
            tonearm_renderer = TonearmRenderer(
                base_path=cfg.get(BASE_PATH),
                meter_folder=cfg.get(SCREEN_INFO)[METER_FOLDER],
                filename=tonearm_file,
                pivot_screen=tonearm_pivot_screen,
                pivot_image=tonearm_pivot_image,
                angle_rest=mc_vol.get(TONEARM_ANGLE_REST, -30.0),
                angle_start=mc_vol.get(TONEARM_ANGLE_START, 0.0),
                angle_end=mc_vol.get(TONEARM_ANGLE_END, 25.0),
                drop_duration=mc_vol.get(TONEARM_DROP_DURATION, 1.5),
                lift_duration=mc_vol.get(TONEARM_LIFT_DURATION, 1.0),
                rotation_fps=rot_fps
            )
            # Capture backing for tonearm sweep area
            backing_rect = tonearm_renderer.get_backing_rect()
            if backing_rect:
                capture_rect("tonearm", (backing_rect.x, backing_rect.y), backing_rect.width, backing_rect.height)
            log_debug(f"[overlay_init] TonearmRenderer created: {tonearm_file}")
        
        # Create scrollers with per-field speeds
        artist_scroller = ScrollingLabel(artist_font, artist_color, artist_pos, artist_box, center=center_flag, speed_px_per_sec=scroll_speed_artist) if artist_pos else None
        title_scroller = ScrollingLabel(title_font, title_color, title_pos, title_box, center=center_flag, speed_px_per_sec=scroll_speed_title) if title_pos else None
        album_scroller = ScrollingLabel(album_font, album_color, album_pos, album_box, center=center_flag, speed_px_per_sec=scroll_speed_album) if album_pos else None
        
        # Capture backing for scrollers (after static assets drawn)
        if artist_scroller:
            artist_scroller.capture_backing(screen)
        if title_scroller:
            title_scroller.capture_backing(screen)
        if album_scroller:
            album_scroller.capture_backing(screen)
        
        # Type rect
        type_rect = pg.Rect(type_pos[0], type_pos[1], type_dim[0], type_dim[1]) if (type_pos and type_dim) else None
        
        # Reset cover
        last_cover_url = None
        cover_img = None

        # Load meter foreground (fgr) to draw last, above rotating cover
        fgr_surf = None
        fgr_regions = []  # OPTIMIZATION: Pre-computed opaque regions for selective blitting
        fgr_name = mc.get(FGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        try:
            if fgr_name:
                meter_path = os.path.join(cfg.get(BASE_PATH), cfg.get(SCREEN_INFO)[METER_FOLDER])
                fgr_path = os.path.join(meter_path, fgr_name)
                fgr_surf = pg.image.load(fgr_path).convert_alpha()
                # OPTIMIZATION: Compute opaque regions for selective blitting
                # This typically reduces foreground blit area by 80-90%
                fgr_regions = compute_foreground_regions(fgr_surf)
                if fgr_regions:
                    log_debug(f"Foreground has {len(fgr_regions)} opaque regions for selective blit")
                    for i, r in enumerate(fgr_regions):
                        log_debug(f"  fgr region {i}: x={r.x}, y={r.y}, w={r.width}, h={r.height}")
        except Exception as e:
            print(f"[overlay_init] Failed to load fgr '{fgr_name}': {e}")
        
        # Store state
        overlay_state = {
            "enabled": True,
            "mc_vol": mc_vol,
            "center_flag": center_flag,
            "backing": backing,
            "backing_dict": backing_dict,
            "fontL": fontL,
            "fontR": fontR,
            "fontB": fontB,
            "fontDigi": fontDigi,
            "artist_scroller": artist_scroller,
            "title_scroller": title_scroller,
            "album_scroller": album_scroller,
            "artist_pos": artist_pos,
            "title_pos": title_pos,
            "album_pos": album_pos,
            "time_pos": time_pos,
            "sample_pos": sample_pos,
            "type_pos": type_pos,
            "type_rect": type_rect,
            "sample_font": sample_font,
            "sample_box": sample_box,
            "font_color": font_color,
            "time_color": time_color,
            "type_color": type_color,
            "album_renderer": album_renderer,
            "album_renderer_gpu": album_renderer_gpu,
            "reel_left_renderer": reel_left_renderer,
            "reel_left_renderer_gpu": reel_left_renderer_gpu,
            "reel_right_renderer": reel_right_renderer,
            "reel_right_renderer_gpu": reel_right_renderer_gpu,
            "tonearm_renderer": tonearm_renderer,
            "fgr_surf": fgr_surf,
            "fgr_pos": (meter_x, meter_y),
            "fgr_regions": fgr_regions,  # OPTIMIZATION: Opaque regions for selective blitting
            "use_gpu": use_gpu,
            "gpu_renderer": gpu_renderer,
            # GPU deferred render state
            "_gpu_fgr_texture": None,  # Foreground texture (uploaded once)
            "_gpu_tonearm_texture": None,  # Tonearm texture (uploaded once)
            "_gpu_base_texture": None,  # Streaming base texture (reused each frame)
            "_gpu_needs_composite": False,  # Flag for GPU frame composite
            "_gpu_reel_left_dirty": False,
            "_gpu_reel_right_dirty": False,
            "_gpu_album_dirty": False,
            "_gpu_tonearm_dirty": False,
        }
        
        # Upload foreground texture for GPU path (once at init)
        if use_gpu and gpu_renderer and fgr_surf:
            overlay_state["_gpu_fgr_texture"] = gpu_renderer.create_texture(fgr_surf)
            if overlay_state["_gpu_fgr_texture"]:
                log_debug("[GPU] Foreground texture uploaded", "basic")
        
        # Create streaming base texture for efficient per-frame updates
        if use_gpu and gpu_renderer:
            screen_w = cfg[SCREEN_INFO][WIDTH]
            screen_h = cfg[SCREEN_INFO][HEIGHT]
            overlay_state["_gpu_base_texture"] = gpu_renderer.create_streaming_texture(screen_w, screen_h)
            if overlay_state["_gpu_base_texture"]:
                log_debug("[GPU] Streaming base texture created", "basic")
    
    # -------------------------------------------------------------------------
    # Render format icon - OPTIMIZED with caching
    # -------------------------------------------------------------------------
    def render_format_icon(track_type, type_rect, type_color):
        nonlocal last_track_type, last_format_icon_surf
        
        if not type_rect:
            return None
        
        fmt = (track_type or "").strip().lower().replace(" ", "_")
        if fmt == "dsf":
            fmt = "dsd"
        
        # OPTIMIZATION: Return cached surface if format unchanged
        if fmt == last_track_type and last_format_icon_surf is not None:
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
    
    while running:
        current_time = time.time()
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
                clock.tick(cfg[FRAME_RATE])
                continue
        
        # Check for random meter change
        nm = resolve_active_meter_name()
        if nm != active_meter_name:
            overlay_init_for_meter(nm)
        
        # Handle title-change random restart
        if title_changed_flag[0]:
            title_changed_flag[0] = False
            callback.pending_restart = True
        
        # Handle interval-based random restart
        if random_interval_mode:
            random_timer += clock.get_time() / 1000.0
            if random_timer >= random_interval:
                random_timer = 0
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
            # Read metadata FIRST (needed for tonearm backing restore before meter.run)
            meta = last_metadata
            artist = meta.get("artist", "")
            title = meta.get("title", "")
            album = meta.get("album", "")
            albumart = meta.get("albumart", "")
            samplerate = meta.get("samplerate", "")
            bitdepth = meta.get("bitdepth", "")
            track_type = meta.get("trackType", "")
            bitrate = meta.get("bitrate", "")
            status = meta.get("status", "")
            is_playing = status == "play"
            bd = ov.get("backing_dict", {})
            
            # Pre-calculate tonearm state BEFORE meter.run()
            # This allows backing restore before meters draw
            tonearm = ov.get("tonearm_renderer")
            tonearm_will_render = False
            if tonearm:
                duration = meta.get("duration", 0) or 0
                seek = meta.get("seek", 0) or 0
                
                # Interpolate seek based on elapsed time when playing
                if is_playing and duration > 0:
                    seek_update_time = meta.get("_seek_update", 0)
                    if seek_update_time > 0:
                        elapsed_ms = (current_time - seek_update_time) * 1000
                        seek = min(duration * 1000, seek + elapsed_ms)
                
                if duration > 0:
                    progress_pct = min(100.0, (seek / 1000.0 / duration) * 100.0)
                    # Calculate time remaining for early lift feature
                    time_remaining_sec = duration - (seek / 1000.0)
                else:
                    progress_pct = 0.0
                    time_remaining_sec = None  # Unknown duration (webradio etc)
                
                tonearm.update(status, progress_pct, time_remaining_sec)
                tonearm_will_render = tonearm.will_blit(now_ticks)
            
            # Pre-calculate album art state
            album_renderer = ov.get("album_renderer")
            album_renderer_gpu = ov.get("album_renderer_gpu")
            use_gpu_render = ov.get("use_gpu", False)
            tonearm_active = tonearm and tonearm.get_state() != "rest"
            album_will_render = False
            if album_renderer:
                url_changed = albumart != getattr(album_renderer, "_current_url", None)
                if url_changed:
                    album_will_render = True
                elif album_renderer.rotate_enabled and album_renderer.rotate_rpm > 0.0:
                    # Use GPU timing when GPU is active, otherwise CPU timing
                    if use_gpu_render and album_renderer_gpu:
                        album_will_render = is_playing and album_renderer_gpu.will_blit(now_ticks)
                    else:
                        album_will_render = is_playing and album_renderer.will_blit(now_ticks)
            
            # RESTORE TONEARM BACKING BEFORE meter.run() so meters draw on top
            tonearm_backing_restored = False
            if (tonearm_will_render or (album_will_render and tonearm_active)) and "tonearm" in bd:
                r, b = bd["tonearm"]
                screen.blit(b, r.topleft)
                tonearm_backing_restored = True
            
            # Run meter animation - collect dirty rects
            # Meters now draw on top of restored backing
            meter_rects = pm.meter.run()
            if meter_rects:
                # meter.run() returns list of tuples: [(index, rect), (index, rect)]
                # Extract just the rects for display update
                if isinstance(meter_rects, list):
                    for item in meter_rects:
                        if item:
                            # Handle tuple (index, rect) from circular/linear animator
                            if isinstance(item, tuple) and len(item) >= 2:
                                rect = item[1]  # Second element is the rect
                                if rect:
                                    dirty_rects.append(rect)
                            elif hasattr(item, 'x'):  # It's a Rect object
                                dirty_rects.append(item)
                elif isinstance(meter_rects, tuple) and len(meter_rects) >= 2:
                    rect = meter_rects[1]
                    if rect:
                        dirty_rects.append(rect)
                elif hasattr(meter_rects, 'x'):  # It's a Rect object
                    dirty_rects.append(meter_rects)
            
            # Render cassette reels
            reel_left = ov.get("reel_left_renderer")
            reel_right = ov.get("reel_right_renderer")
            reel_left_gpu = ov.get("reel_left_renderer_gpu")
            reel_right_gpu = ov.get("reel_right_renderer_gpu")
            
            # Restore BOTH backings first to avoid overlap clobbering
            # Use GPU timing when GPU is active for proper FPS gating
            if use_gpu_render and reel_left_gpu:
                left_will_blit = reel_left and is_playing and reel_left_gpu.will_blit(now_ticks)
            else:
                left_will_blit = reel_left and is_playing and reel_left.will_blit(now_ticks)
            
            if use_gpu_render and reel_right_gpu:
                right_will_blit = reel_right and is_playing and reel_right_gpu.will_blit(now_ticks)
            else:
                right_will_blit = reel_right and is_playing and reel_right.will_blit(now_ticks)
            
            # Always restore backings (needed for both CPU and GPU paths)
            if left_will_blit and "reel_left" in bd:
                r, b = bd["reel_left"]
                screen.blit(b, r.topleft)
            if right_will_blit and "reel_right" in bd:
                r, b = bd["reel_right"]
                screen.blit(b, r.topleft)
            
            # Now render both reels
            # GPU path: update angle only, defer actual render to GPU composite
            # CPU path: render directly to pygame screen
            if left_will_blit:
                if use_gpu_render and reel_left_gpu:
                    # GPU: update angle, mark for deferred composite
                    reel_left_gpu.update_angle(status, now_ticks)
                    ov["_gpu_reel_left_dirty"] = True
                    ov["_gpu_needs_composite"] = True
                else:
                    # CPU: render directly
                    rect = reel_left.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)
            
            if right_will_blit:
                if use_gpu_render and reel_right_gpu:
                    # GPU: update angle, mark for deferred composite
                    reel_right_gpu.update_angle(status, now_ticks)
                    ov["_gpu_reel_right_dirty"] = True
                    ov["_gpu_needs_composite"] = True
                else:
                    # CPU: render directly
                    rect = reel_right.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)
            
            # STEP 2: Album art (restore backing + draw)
            # This covers any overlap area that tonearm backing cleared
            album_rendered = False
            album_renderer_gpu = ov.get("album_renderer_gpu")
            
            if album_renderer:
                url_changed = albumart != getattr(album_renderer, "_current_url", None)
                if url_changed:
                    if "art" in bd:
                        r, b = bd["art"]
                        screen.blit(b, r.topleft)
                    album_renderer.load_from_url(albumart)
                    
                    # Upload new image to GPU renderer if available
                    if use_gpu_render and album_renderer_gpu and album_renderer._scaled_surf:
                        album_renderer_gpu.load_surface(album_renderer._scaled_surf)
                        # GPU: update angle, mark for deferred composite
                        album_renderer_gpu.update_angle(status, now_ticks, advance_angle=False)
                        ov["_gpu_album_dirty"] = True
                        ov["_gpu_needs_composite"] = True
                        album_rendered = True
                    else:
                        # CPU fallback
                        rect = album_renderer.render(screen, status, now_ticks)
                        if rect:
                            dirty_rects.append(rect)
                            album_rendered = True
                elif album_renderer.rotate_enabled and album_renderer.rotate_rpm > 0.0:
                    # Normal rotation rendering - GPU or CPU path
                    if album_will_render or tonearm_will_render:
                        if "art" in bd:
                            r, b = bd["art"]
                            screen.blit(b, r.topleft)
                        
                        # Only stop rotation during early lift (track ending) after 0.5s delay
                        # During seek (lift without early_lift flag), keep rotating
                        tonearm_allows_rotation = (tonearm is None or 
                                                   not tonearm.should_stop_rotation(now_ticks, delay_ms=500))
                        should_advance = album_will_render and tonearm_allows_rotation
                        
                        if use_gpu_render and album_renderer_gpu:
                            # GPU: update angle, mark for deferred composite
                            album_renderer_gpu.update_angle(status, now_ticks, advance_angle=should_advance)
                            album_renderer._need_first_blit = False
                            ov["_gpu_album_dirty"] = True
                            ov["_gpu_needs_composite"] = True
                            album_rendered = True
                        else:
                            # CPU: render directly
                            rect = album_renderer.render(screen, status, now_ticks, advance_angle=should_advance)
                            if rect:
                                dirty_rects.append(rect)
                                album_rendered = True
                else:
                    # Static artwork - redraw when tonearm renders
                    if tonearm_will_render:
                        if "art" in bd:
                            r, b = bd["art"]
                            screen.blit(b, r.topleft)
                        rect = album_renderer.render(screen, status, now_ticks, advance_angle=False)
                        if rect:
                            dirty_rects.append(rect)
                            album_rendered = True
                    else:
                        rect = album_renderer.render(screen, status, now_ticks)
                        if rect:
                            dirty_rects.append(rect)
                            album_rendered = True
                        if rect:
                            dirty_rects.append(rect)
                            album_rendered = True
            
            # STEP 3: Tonearm draws on top of album art
            # Must render if: tonearm needs update OR album art just rendered (to stay on top)
            # GPU path: update state but skip pygame blit, render via GPU composite after album art
            if tonearm and (tonearm_will_render or (album_rendered and tonearm.get_state() != "rest")):
                # Force render if album art just rendered (to stay on top)
                force = album_rendered and not tonearm_will_render
                
                if use_gpu_render and ov.get("_gpu_needs_composite"):
                    # GPU path: track that tonearm needs GPU render, but let CPU update its state
                    # The tonearm.update() was already called earlier, angle is current
                    ov["_gpu_tonearm_dirty"] = True
                    # Still need to mark dirty rect for foreground selective blit
                    backing_rect = tonearm.get_backing_rect()
                    if backing_rect:
                        dirty_rects.append(backing_rect)
                else:
                    # CPU path: render directly to pygame screen
                    rect = tonearm.render(screen, now_ticks, force=force)
                    if rect:
                        dirty_rects.append(rect)
            
            # Text scrollers - render AFTER tonearm so labels aren't wiped by backing restore
            # Force redraw if tonearm backing was restored (it may have wiped text areas)
            if tonearm_backing_restored:
                if ov["artist_scroller"]:
                    ov["artist_scroller"]._needs_redraw = True
                if ov["title_scroller"]:
                    ov["title_scroller"]._needs_redraw = True
                if ov["album_scroller"]:
                    ov["album_scroller"]._needs_redraw = True
                # Also force time/sample/icon redraw
                last_time_str = ""
                last_sample_text = ""
                last_track_type = ""
            
            if ov["artist_scroller"]:
                # Combine artist + album if no album position
                display_artist = artist
                if not ov["album_pos"] and album:
                    display_artist = f"{artist} - {album}" if artist else album
                ov["artist_scroller"].update_text(display_artist)
                rect = ov["artist_scroller"].draw(screen)
                if rect:
                    dirty_rects.append(rect)
            
            if ov["title_scroller"]:
                ov["title_scroller"].update_text(title)
                rect = ov["title_scroller"].draw(screen)
                if rect:
                    dirty_rects.append(rect)
            
            if ov["album_scroller"]:
                ov["album_scroller"].update_text(album)
                rect = ov["album_scroller"].draw(screen)
                if rect:
                    dirty_rects.append(rect)
            
            # Time remaining - OPTIMIZED with caching
            if ov["time_pos"]:
                # Read time from socket.io metadata watcher
                time_remain_sec = meta.get("_time_remain", -1)
                time_last_update = meta.get("_time_update", 0)
                
                # Update countdown (only if we have valid time)
                if time_remain_sec >= 0:
                    elapsed = current_time - time_last_update
                    if elapsed >= 1.0:
                        # Calculate updated remaining time
                        time_remain_sec = max(0, time_remain_sec - int(elapsed))
                
                # Format time (skip if no valid time, e.g. webradio)
                if time_remain_sec >= 0:
                    mins = time_remain_sec // 60
                    secs = time_remain_sec % 60
                    time_str = f"{mins:02d}:{secs:02d}"
                    
                    # OPTIMIZATION: Only redraw if time string changed
                    if time_str != last_time_str:
                        last_time_str = time_str
                        
                        # Restore backing for time area
                        if "time" in bd:
                            r, b = bd["time"]
                            screen.blit(b, r.topleft)
                            dirty_rects.append(r.copy())
                        
                        # Color - red for last 10 seconds
                        t_color = (242, 0, 0) if 0 < time_remain_sec <= 10 else ov["time_color"]
                        
                        last_time_surf = ov["fontDigi"].render(time_str, True, t_color)
                        screen.blit(last_time_surf, ov["time_pos"])
            
            # Sample rate / bitdepth - OPTIMIZED with caching
            if ov["sample_pos"] and ov["sample_box"]:
                # Match original: concatenate sample + depth, fallback to bitrate
                sample_text = f"{samplerate} {bitdepth}".strip()
                if not sample_text:
                    sample_text = bitrate.strip() if bitrate else ""
                
                # OPTIMIZATION: Only redraw if sample text changed
                if sample_text and sample_text != last_sample_text:
                    last_sample_text = sample_text
                    
                    # Restore backing for sample area
                    if "sample" in bd:
                        r, b = bd["sample"]
                        screen.blit(b, r.topleft)
                        dirty_rects.append(r.copy())
                    
                    last_sample_surf = ov["sample_font"].render(sample_text, True, ov["type_color"])
                    
                    # Center if configured
                    if ov["center_flag"] and ov["sample_box"]:
                        sx = ov["sample_pos"][0] + (ov["sample_box"] - last_sample_surf.get_width()) // 2
                    else:
                        sx = ov["sample_pos"][0]
                    screen.blit(last_sample_surf, (sx, ov["sample_pos"][1]))
            
            # Format icon - OPTIMIZED with caching
            icon_rect = render_format_icon(track_type, ov["type_rect"], ov["type_color"])
            if icon_rect:
                dirty_rects.append(icon_rect)

            # Draw the meter foreground above everything (needles + rotating cover)
            # GPU path: skip CPU foreground blit, will be done in GPU composite
            # CPU path: selective blit - only regions overlapping dirty areas
            fgr_surf = ov.get("fgr_surf")
            fgr_regions = ov.get("fgr_regions", [])
            if fgr_surf and dirty_rects and not ov.get("_gpu_needs_composite"):
                # CPU path only - GPU path renders foreground in composite
                fgr_x, fgr_y = ov["fgr_pos"]
                if fgr_regions:
                    # Selective blit - only regions overlapping dirty rects
                    for region in fgr_regions:
                        # Translate region to screen coordinates
                        screen_rect = region.move(fgr_x, fgr_y)
                        # Check if any dirty rect overlaps this region
                        for dirty in dirty_rects:
                            if screen_rect.colliderect(dirty):
                                # Blit just this region from foreground surface
                                screen.blit(fgr_surf, screen_rect.topleft, region)
                                break
                else:
                    # Fallback: no regions computed, blit entire foreground
                    screen.blit(fgr_surf, ov["fgr_pos"])
            
            # Spectrum and callbacks - OPTIMIZED: throttle spectrum updates
            if callback.spectrum_output is not None:
                # Only update spectrum every N frames to reduce CPU load
                if frame_counter % SPECTRUM_UPDATE_INTERVAL == 0:
                    callback.peppy_meter_update()
            else:
                callback.peppy_meter_update()
            
            # OPTIMIZATION: Update only dirty rectangles
            # GPU path: composite all rotating elements via renderer, then present
            if use_gpu_render and gpu_renderer and ov.get("_gpu_needs_composite"):
                # Use streaming base texture for efficient per-frame updates
                base_texture = ov.get("_gpu_base_texture")
                texture_ready = False
                
                if base_texture:
                    # Update texture contents from pygame screen (much faster than create_texture)
                    texture_ready = gpu_renderer.update_texture(base_texture, screen)
                
                if not texture_ready:
                    # Fallback: create new texture (slower but works)
                    base_texture = gpu_renderer.create_texture(screen)
                    texture_ready = base_texture is not None
                
                if texture_ready and base_texture:
                    
                    # Clear GPU backbuffer and draw base (everything pygame rendered)
                    gpu_renderer.clear()
                    gpu_renderer.blit(base_texture, (0, 0))
                    
                    # Layer order for GPU composite:
                    # 1. Base (already blitted above - meters, spectrum, text)
                    # 2. Reels (left, right)
                    # 3. Album art
                    # 4. Tonearm (on top of album art)
                    # 5. Foreground (topmost)
                    
                    # Render reels via GPU (if marked dirty)
                    reel_left_gpu = ov.get("reel_left_renderer_gpu")
                    reel_right_gpu = ov.get("reel_right_renderer_gpu")
                    
                    if ov.get("_gpu_reel_left_dirty") and reel_left_gpu:
                        reel_left_gpu.render_direct()
                    
                    if ov.get("_gpu_reel_right_dirty") and reel_right_gpu:
                        reel_right_gpu.render_direct()
                    
                    # Render album art via GPU (if marked dirty)
                    album_renderer_gpu = ov.get("album_renderer_gpu")
                    if ov.get("_gpu_album_dirty") and album_renderer_gpu and album_renderer_gpu._texture:
                        album_renderer_gpu.render_direct()
                    
                    # Render tonearm via GPU (if marked dirty)
                    # Use CPU renderer's state (angle, surface) with GPU rotation
                    if ov.get("_gpu_tonearm_dirty"):
                        tonearm_cpu = ov.get("tonearm_renderer")
                        if tonearm_cpu and tonearm_cpu._original_surf:
                            # Get or create tonearm texture
                            tonearm_texture = ov.get("_gpu_tonearm_texture")
                            if tonearm_texture is None:
                                tonearm_texture = gpu_renderer.create_texture(tonearm_cpu._original_surf)
                                ov["_gpu_tonearm_texture"] = tonearm_texture
                            
                            if tonearm_texture:
                                # Calculate blit position (pivot point alignment)
                                px, py = tonearm_cpu.pivot_image
                                sx, sy = tonearm_cpu.pivot_screen
                                tw, th = tonearm_cpu._original_surf.get_size()
                                dest = pg.Rect(sx - px, sy - py, tw, th)
                                
                                # Blit with GPU rotation using CPU's current angle
                                gpu_renderer.blit_rotated(
                                    tonearm_texture, dest,
                                    -tonearm_cpu._current_angle,  # Negative for correct direction
                                    tonearm_cpu.pivot_image
                                )
                    
                    # Render foreground via GPU (always on top)
                    fgr_texture = ov.get("_gpu_fgr_texture")
                    if fgr_texture:
                        fgr_x, fgr_y = ov.get("fgr_pos", (0, 0))
                        gpu_renderer.blit(fgr_texture, (fgr_x, fgr_y))
                    
                    # Present the composited frame
                    gpu_renderer.present()
                    
                    # Debug log (only first time)
                    if not getattr(gpu_renderer, "_logged_composite", False):
                        log_debug("[GPU] Deferred composite with streaming texture - no readback", "basic")
                        gpu_renderer._logged_composite = True
                else:
                    # Fallback if streaming texture not available
                    log_debug("[GPU] Base texture not available, fallback to display.update", "basic")
                    if dirty_rects:
                        pg.display.update(dirty_rects)
                
                # Reset all GPU dirty flags for next frame
                ov["_gpu_needs_composite"] = False
                ov["_gpu_reel_left_dirty"] = False
                ov["_gpu_reel_right_dirty"] = False
                ov["_gpu_album_dirty"] = False
                ov["_gpu_tonearm_dirty"] = False
            elif dirty_rects:
                pg.display.update(dirty_rects)
            # If nothing changed, skip display update entirely
        
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
        
        clock.tick(cfg[FRAME_RATE])
    
    # Fade-out transition before cleanup (only if we did fade-in)
    if callback.did_fade_in:
        # Recreate runFlag to prevent new instance starting during our fade_out
        # index.js checks this flag before starting peppymeter
        Path(PeppyRunning).touch()
        log_debug("runFlag recreated for fade_out protection")
        
        duration = meter_config_volumio.get(TRANSITION_DURATION, 0.5)
        callback.screen_fade_out(screen, duration)
        
        # Remove runFlag after fade_out complete
        if os.path.exists(PeppyRunning):
            os.remove(PeppyRunning)
            log_debug("runFlag removed after fade_out")
    else:
        log_debug("screen_fade_out skipped (no fade_in was done)")
    
    # Cleanup
    metadata_watcher.stop()
    
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
    
    # Set debug level from config early so logging works
    DEBUG_LEVEL_CURRENT = meter_config_volumio.get(DEBUG_LEVEL, "off")
    
    # Clear debug log on fresh start (after config is loaded)
    if DEBUG_LEVEL_CURRENT != "off":
        try:
            with open(DEBUG_LOG_FILE, 'w') as f:
                f.write("")
        except Exception:
            pass
    log_debug(f"Debug level set to: {DEBUG_LEVEL_CURRENT}", "basic")
    log_debug("=== PeppyMeter starting ===", "basic")
    
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
