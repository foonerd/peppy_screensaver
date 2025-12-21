# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Rewritten 2025 for Volumio 4 / Bookworm (Python 3.11, pygame 2.5)
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

import os
import sys
import time
import ctypes
import resource
import io
import requests
import pygame as pg
import socketio

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
    COLOR_DEPTH, POSITION_TYPE, POS_X, POS_Y, START_ANIMATION,
    FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD,
    ALBUMART_POS, ALBUMART_DIM, ALBUMART_MSK, ALBUMBORDER,
    PLAY_TXT_CENTER, PLAY_CENTER, PLAY_MAX,
    PLAY_TITLE_POS, PLAY_TITLE_COLOR, PLAY_TITLE_MAX, PLAY_TITLE_STYLE,
    PLAY_ARTIST_POS, PLAY_ARTIST_COLOR, PLAY_ARTIST_MAX, PLAY_ARTIST_STYLE,
    PLAY_ALBUM_POS, PLAY_ALBUM_COLOR, PLAY_ALBUM_MAX, PLAY_ALBUM_STYLE,
    PLAY_TYPE_POS, PLAY_TYPE_COLOR, PLAY_TYPE_DIM,
    PLAY_SAMPLE_POS, PLAY_SAMPLE_STYLE, PLAY_SAMPLE_MAX,
    TIME_REMAINING_POS, TIMECOLOR,
    FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_DIGI, FONTCOLOR,
    FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_L,
    METER_BKP, RANDOM_TITLE, SPECTRUM, SPECTRUM_SIZE, SPECTRUM_POS
)

from volumio_spectrum import SpectrumOutput

# Optional SVG support for pygame < 2
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except Exception:
    CAIROSVG_AVAILABLE = False

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# Runtime paths
PeppyRunning = '/tmp/peppyrunning'
CurDir = os.getcwd()
PeppyPath = CurDir + '/screensaver/peppymeter'

# SDL2 disabled for Volumio 4 compatibility
use_sdl2 = False


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

    def capture_backing(self, surface):
        """Capture backing surface for this label's area."""
        if not self.pos or self.box_width <= 0:
            return
        x, y = self.pos
        height = self.font.get_height()
        self._backing_rect = pg.Rect(x, y, self.box_width, height)
        try:
            self._backing = surface.subsurface(self._backing_rect).copy()
        except Exception:
            self._backing = pg.Surface((self._backing_rect.width, self._backing_rect.height))
            self._backing.fill((0, 0, 0))

    def update_text(self, new_text):
        """Update text content, reset scroll position if changed."""
        new_text = new_text or ""
        if new_text == self.text and self.surf is not None:
            return
        self.text = new_text
        self.surf = self.font.render(self.text, True, self.color)
        self.text_w, self.text_h = self.surf.get_size()
        self.offset = 0.0
        self.direction = 1
        self._pause_until = 0
        self._last_time = pg.time.get_ticks()

    def draw(self, surface):
        """Draw label, handling scroll animation with self-backing."""
        if not self.surf or not self.pos or self.box_width <= 0:
            return
        x, y = self.pos
        box_rect = pg.Rect(x, y, self.box_width, self.text_h)
        
        # Restore backing before drawing (prevents artifacts)
        if self._backing and self._backing_rect:
            surface.blit(self._backing, self._backing_rect.topleft)
        
        # Text fits - no scrolling needed
        if self.text_w <= self.box_width:
            if self.center and self.box_width > 0:
                left = box_rect.x + (self.box_width - self.text_w) // 2
                surface.blit(self.surf, (left, box_rect.y))
            else:
                surface.blit(self.surf, (box_rect.x, box_rect.y))
            return
        
        # Scrolling text
        prev_clip = surface.get_clip()
        surface.set_clip(box_rect)
        draw_x = box_rect.x - int(self.offset)
        surface.blit(self.surf, (draw_x, box_rect.y))
        surface.set_clip(prev_clip)
        
        # Advance scroll position
        now = pg.time.get_ticks()
        dt = (now - self._last_time) / 1000.0
        self._last_time = now
        
        if now < self._pause_until:
            return
            
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
        
    def vol_FadeIn_thread(self, meter):
        """Volume fade-in thread."""
        for i in range(0, 100, 10):
            meter.set_volume(i)
            time.sleep(0.07)
        meter.set_volume(100)

    def peppy_meter_start(self, meter):
        """Called when meter starts - initialize spectrum and albumart overlay."""
        meter_section = self.meter_config[self.meter_config[METER]]
        meter_section_volumio = self.meter_config_volumio[self.meter_config[METER]]
        
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
    """Convert various color formats to RGB tuple."""
    try:
        if isinstance(val, pg.Color):
            return (val.r, val.g, val.b)
        if isinstance(val, (tuple, list)) and len(val) >= 3:
            return (int(val[0]), int(val[1]), int(val[2]))
        if isinstance(val, str):
            parts = [p.strip() for p in val.split(",")]
            if len(parts) >= 3:
                return (int(parts[0]), int(parts[1]), int(parts[2]))
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


def set_color(surface, color):
    """Tint a surface with given color (preserving alpha)."""
    try:
        r, g, b = color
        surface.fill((r, g, b, 255), special_flags=pg.BLEND_RGBA_MULT)
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
def init_display(pm, meter_config_volumio, screen_w, screen_h):
    """Initialize pygame display."""
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
# Main Display Output with Overlay
# =============================================================================
def start_display_output(pm, callback, meter_config_volumio):
    """Main display loop with integrated overlay rendering."""
    
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
        
        # Draw meter background at meter position
        if bgr_name:
            try:
                img_path = os.path.join(meter_path, bgr_name)
                img = pg.image.load(img_path).convert()
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
        
        mc = cfg.get(meter_name, {}) if meter_name else {}
        mc_vol = meter_config_volumio.get(meter_name, {}) if meter_name else {}
        active_meter_name = meter_name
        
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
            if global_max:
                return global_max
            if field_max:
                return field_max
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
        
        def capture_rect(pos, width, height):
            if pos and width and height:
                r = pg.Rect(pos[0], pos[1], int(width), int(height))
                try:
                    backing.append((r, screen.subsurface(r).copy()))
                except Exception:
                    backing.append((r, pg.Surface((r.width, r.height)).convert()))
        
        if artist_pos:
            capture_rect(artist_pos, artist_box, artist_font.get_height())
        if title_pos:
            capture_rect(title_pos, title_box, title_font.get_height())
        if album_pos:
            capture_rect(album_pos, album_box, album_font.get_height())
        if time_pos:
            capture_rect(time_pos, fontDigi.size('00:00')[0] + 10, fontDigi.get_height())
        if sample_pos and sample_box:
            capture_rect(sample_pos, sample_box, sample_font.get_height())
        if type_pos and type_dim:
            capture_rect(type_pos, type_dim[0], type_dim[1])
        if art_pos and art_dim:
            capture_rect(art_pos, art_dim[0], art_dim[1])
        
        # Create scrollers
        artist_scroller = ScrollingLabel(artist_font, artist_color, artist_pos, artist_box, center=center_flag) if artist_pos else None
        title_scroller = ScrollingLabel(title_font, title_color, title_pos, title_box, center=center_flag) if title_pos else None
        album_scroller = ScrollingLabel(album_font, album_color, album_pos, album_box, center=center_flag) if album_pos else None
        
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
        
        # Store state
        overlay_state = {
            "enabled": True,
            "mc_vol": mc_vol,
            "center_flag": center_flag,
            "backing": backing,
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
            "art_pos": art_pos,
            "art_dim": art_dim,
            "sample_font": sample_font,
            "sample_box": sample_box,
            "font_color": font_color,
            "time_color": time_color,
            "type_color": type_color,
            "art_mask": mc_vol.get(ALBUMART_MSK),
            "art_border": mc_vol.get(ALBUMBORDER),
            "spectrum_backing": None,
            "spectrum_rect": None
        }
        
        # Capture spectrum backing if spectrum visible
        if mc_vol.get(SPECTRUM_VISIBLE) and mc_vol.get(SPECTRUM_SIZE):
            spec_size = mc_vol.get(SPECTRUM_SIZE)
            spec_pos = mc_vol.get(SPECTRUM_POS, (0, 0))
            if spec_pos is None:
                spec_pos = (0, 0)
            spec_rect = pg.Rect(spec_pos[0], spec_pos[1], spec_size[0], spec_size[1])
            try:
                overlay_state["spectrum_backing"] = screen.subsurface(spec_rect).copy()
                overlay_state["spectrum_rect"] = spec_rect
            except Exception:
                pass
    
    # -------------------------------------------------------------------------
    # Render format icon
    # -------------------------------------------------------------------------
    def render_format_icon(track_type, type_rect, type_color):
        if not type_rect:
            return
        
        fmt = (track_type or "").strip().lower().replace(" ", "_")
        if fmt == "dsf":
            fmt = "dsd"
        
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
            return
        
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
                set_color(img, pg.Color(type_color[0], type_color[1], type_color[2]))
                dx = type_rect.x + (type_rect.width - img.get_width()) // 2
                dy = type_rect.y + (type_rect.height - img.get_height()) // 2
                screen.blit(img, (dx, dy))
            elif CAIROSVG_AVAILABLE and PIL_AVAILABLE:
                # Pygame 1.x with cairosvg
                png_bytes = cairosvg.svg2png(url=icon_path, 
                                              output_width=type_rect.width,
                                              output_height=type_rect.height)
                pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                set_color(img, pg.Color(type_color[0], type_color[1], type_color[2]))
                dx = type_rect.x + (type_rect.width - img.get_width()) // 2
                dy = type_rect.y + (type_rect.height - img.get_height()) // 2
                screen.blit(img, (dx, dy))
        except Exception as e:
            print(f"[FormatIcon] error: {e}")
    
    # -------------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------------
    clock = Clock()
    pm.meter.start()
    
    # Initialize overlay for first meter
    overlay_init_for_meter(resolve_active_meter_name())
    
    running = True
    exit_events = [pg.MOUSEBUTTONUP]
    if pg.version.ver.startswith("2"):
        exit_events.append(pg.FINGERUP)
    
    while running:
        current_time = time.time()
        
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
            # No extended config - just run meter
            pm.meter.run()
            callback.peppy_meter_update()
            pg.display.flip()
        else:
            # Restore backing surfaces
            for r, b in ov["backing"]:
                screen.blit(b, r.topleft)
            
            # Run meter animation
            pm.meter.run()
            
            # Read metadata from socket.io watcher (no polling needed)
            meta = last_metadata
            artist = meta.get("artist", "")
            title = meta.get("title", "")
            album = meta.get("album", "")
            albumart = meta.get("albumart", "")
            samplerate = meta.get("samplerate", "")
            bitdepth = meta.get("bitdepth", "")
            track_type = meta.get("trackType", "")
            bitrate = meta.get("bitrate", "")
            
            # Album art
            if ov["art_pos"] and ov["art_dim"]:
                if albumart != last_cover_url:
                    last_cover_url = albumart
                    cover_img = None
                    scaled_cover_img = None  # Reset cached scaled image
                    try:
                        if albumart:
                            url = albumart if not albumart.startswith("/") else f"http://localhost:3000{albumart}"
                            resp = requests.get(url, timeout=3)
                            if resp.ok and "image" in resp.headers.get("Content-Type", "").lower():
                                img_bytes = io.BytesIO(resp.content)
                                
                                if ov["art_mask"] and PIL_AVAILABLE:
                                    # Use PIL for masked albumart
                                    pil_img = Image.open(img_bytes).convert("RGBA")
                                    pil_img = pil_img.resize(ov["art_dim"])
                                    
                                    # Load and apply mask
                                    mask_path = os.path.join(cfg.get(BASE_PATH), cfg.get(SCREEN_INFO)[METER_FOLDER], ov["art_mask"])
                                    if os.path.exists(mask_path):
                                        mask = Image.open(mask_path).convert('L')
                                        if mask.size != pil_img.size:
                                            mask = mask.resize(pil_img.size)
                                        pil_img.putalpha(ImageOps.invert(mask))
                                    
                                    cover_img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                                else:
                                    # Standard pygame loading
                                    try:
                                        cover_img = pg.image.load(img_bytes).convert_alpha()
                                    except Exception:
                                        img_bytes.seek(0)
                                        cover_img = pg.image.load(img_bytes).convert()
                                
                                # Scale ONCE on load, not every frame
                                if cover_img:
                                    try:
                                        scaled_cover_img = pg.transform.smoothscale(cover_img, ov["art_dim"])
                                    except Exception:
                                        scaled_cover_img = cover_img
                    except Exception:
                        pass
                
                # Blit cached scaled image (no per-frame scaling)
                if scaled_cover_img:
                    screen.blit(scaled_cover_img, ov["art_pos"])
                    
                    # Border
                    if ov["art_border"]:
                        pg.draw.rect(screen, ov["font_color"], 
                                    pg.Rect(ov["art_pos"], ov["art_dim"]), 
                                    ov["art_border"])
            
            # Text scrollers
            if ov["artist_scroller"]:
                # Combine artist + album if no album position
                display_artist = artist
                if not ov["album_pos"] and album:
                    display_artist = f"{artist} - {album}" if artist else album
                ov["artist_scroller"].update_text(display_artist)
                ov["artist_scroller"].draw(screen)
            
            if ov["title_scroller"]:
                ov["title_scroller"].update_text(title)
                ov["title_scroller"].draw(screen)
            
            if ov["album_scroller"]:
                ov["album_scroller"].update_text(album)
                ov["album_scroller"].draw(screen)
            
            # Time remaining
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
                    
                    # Color - red for last 10 seconds
                    t_color = (242, 0, 0) if 0 < time_remain_sec <= 10 else ov["time_color"]
                    
                    time_surf = ov["fontDigi"].render(time_str, True, t_color)
                    screen.blit(time_surf, ov["time_pos"])
            
            # Sample rate / bitdepth
            if ov["sample_pos"] and ov["sample_box"]:
                # Match original: concatenate sample + depth, fallback to bitrate
                sample_text = f"{samplerate} {bitdepth}".strip()
                if not sample_text:
                    sample_text = bitrate.strip() if bitrate else ""
                
                if sample_text:
                    sample_surf = ov["sample_font"].render(sample_text, True, ov["type_color"])
                    
                    # Center if configured
                    if ov["center_flag"] and ov["sample_box"]:
                        sx = ov["sample_pos"][0] + (ov["sample_box"] - sample_surf.get_width()) // 2
                    else:
                        sx = ov["sample_pos"][0]
                    screen.blit(sample_surf, (sx, ov["sample_pos"][1]))
            
            # Format icon
            render_format_icon(track_type, ov["type_rect"], ov["type_color"])
            
            # Restore spectrum backing before update (prevents double-draw artifacts)
            if ov.get("spectrum_backing") and ov.get("spectrum_rect"):
                screen.blit(ov["spectrum_backing"], ov["spectrum_rect"].topleft)
            
            # Spectrum and callbacks
            callback.peppy_meter_update()
            
            # Update display
            pg.display.flip()
        
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
        
        # Initialize display
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
