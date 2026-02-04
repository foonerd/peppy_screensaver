# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Basic Handler - Self-contained module for basic skin rendering
#
# This file is part of PeppyMeter for Volumio
#
# SKIN TYPE: BASIC
# - HAS: meters, static album art, text fields, indicators
# - NO: vinyl, reels, tonearm (no animated mechanical elements)
# - FORCING: None needed (no animated elements to conflict)
#
# This is the simplest handler - no rotation, no backing conflicts.
# This module is intentionally self-contained with duplicated components
# to eliminate dead code paths and reduce CPU overhead.

import os
import io
import time
import requests
import pygame as pg
import re
import time as time_module

try:
    from PIL import Image, ImageOps, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# Optional SVG support for pygame < 2
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except Exception:
    CAIROSVG_AVAILABLE = False

# =============================================================================
# Configuration Constants (basic-specific subset)
# =============================================================================
from configfileparser import (
    SCREEN_INFO, WIDTH, HEIGHT, FRAME_RATE, BASE_PATH, METER_FOLDER,
    BGR_FILENAME, FGR_FILENAME
)

from volumio_configfileparser import (
    EXTENDED_CONF, METER_DELAY,
    FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD,
    ALBUMART_POS, ALBUMART_DIM, ALBUMART_MSK, ALBUMBORDER,
    PLAY_TXT_CENTER, PLAY_CENTER, PLAY_MAX,
    SCROLLING_SPEED_ARTIST, SCROLLING_SPEED_TITLE, SCROLLING_SPEED_ALBUM,
    PLAY_TITLE_POS, PLAY_TITLE_COLOR, PLAY_TITLE_MAX, PLAY_TITLE_STYLE,
    PLAY_ARTIST_POS, PLAY_ARTIST_COLOR, PLAY_ARTIST_MAX, PLAY_ARTIST_STYLE,
    PLAY_ALBUM_POS, PLAY_ALBUM_COLOR, PLAY_ALBUM_MAX, PLAY_ALBUM_STYLE,
    PLAY_TYPE_POS, PLAY_TYPE_COLOR, PLAY_TYPE_DIM,
    PLAY_SAMPLE_POS, PLAY_SAMPLE_STYLE, PLAY_SAMPLE_MAX,
    TIME_REMAINING_POS, TIMECOLOR,
    FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_DIGI, FONTCOLOR,
    FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_L
)

# Indicator configuration constants
try:
    from volumio_configfileparser import (
        VOLUME_POS, MUTE_POS, SHUFFLE_POS, REPEAT_POS, PLAYSTATE_POS, PROGRESS_POS
    )
except ImportError:
    VOLUME_POS = "volume.pos"
    MUTE_POS = "mute.pos"
    SHUFFLE_POS = "shuffle.pos"
    REPEAT_POS = "repeat.pos"
    PLAYSTATE_POS = "playstate.pos"
    PROGRESS_POS = "progress.pos"


# =============================================================================
# Debug Logging (self-contained)
# =============================================================================
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
    "reel_left": False,
    "reel_right": False,
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


def init_basic_debug(level, trace_dict):
    """Initialize debug settings from main module."""
    global DEBUG_LEVEL_CURRENT, DEBUG_TRACE
    DEBUG_LEVEL_CURRENT = level
    # Copy all values from main module's trace dict
    for key, value in trace_dict.items():
        DEBUG_TRACE[key] = value


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


# =============================================================================
# Helper Functions (self-contained)
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


def compute_foreground_regions(surface, min_gap=50, padding=2):
    """Analyze foreground surface and return list of opaque region rects."""
    if surface is None:
        return []
    
    try:
        w, h = surface.get_size()
        opaque_columns = {}
        for x in range(w):
            for y in range(h):
                try:
                    pixel = surface.get_at((x, y))
                    if len(pixel) >= 4 and pixel[3] > 0:
                        if x not in opaque_columns:
                            opaque_columns[x] = []
                        opaque_columns[x].append(y)
                except Exception:
                    continue
        
        if not opaque_columns:
            return []
        
        x_sorted = sorted(opaque_columns.keys())
        regions = []
        region_start = x_sorted[0]
        region_end = x_sorted[0]
        
        for i in range(1, len(x_sorted)):
            if x_sorted[i] - x_sorted[i-1] > min_gap:
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
        
        min_y = min(min(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
        max_y = max(max(opaque_columns[x]) for x in range(region_start, region_end + 1) if x in opaque_columns)
        regions.append(pg.Rect(
            max(0, region_start - padding),
            max(0, min_y - padding),
            min(w - max(0, region_start - padding), region_end - region_start + 1 + 2 * padding),
            min(h - max(0, min_y - padding), max_y - min_y + 1 + 2 * padding)
        ))
        
        return regions
    except Exception:
        return []


# =============================================================================
# ScrollingLabel - Text animation with self-backing
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
        self._bgr_surface = None  # Layer composition: use bgr for clearing
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

    def set_background_surface(self, bgr_surface):
        """Set background surface for layer composition clearing.
        
        When set, draw() will clear from this surface instead of captured backing.
        This eliminates backing collision artifacts.
        """
        self._bgr_surface = bgr_surface

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
            
            # LAYER COMPOSITION: Clear from bgr_surface if available
            if self._bgr_surface and self._backing_rect:
                surface.blit(self._bgr_surface, self._backing_rect.topleft, self._backing_rect)
            elif self._backing and self._backing_rect:
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
        
        # LAYER COMPOSITION: Clear from bgr_surface if available
        if self._bgr_surface and self._backing_rect:
            surface.blit(self._bgr_surface, self._backing_rect.topleft, self._backing_rect)
        elif self._backing and self._backing_rect:
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
# AlbumArtRenderer - BASIC VERSION (static only, no rotation)
# =============================================================================
class AlbumArtRenderer:
    """
    Handles album art loading with optional file mask or circular crop.
    BASIC VERSION: Static only - no rotation support.
    """

    def __init__(self, base_path, meter_folder, art_pos, art_dim, screen_size,
                 font_color=(255, 255, 255), border_width=0,
                 mask_filename=None, circle=False):
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.art_pos = art_pos
        self.art_dim = art_dim
        self.screen_size = screen_size
        self.font_color = font_color
        self.border_width = border_width
        self.mask_filename = mask_filename
        self.circle = bool(circle)

        # Runtime cache
        self._requests = requests.Session()
        self._current_url = None
        self._scaled_surf = None
        self._needs_redraw = True
        self._need_first_blit = False

        # Mask path
        self._mask_path = None
        if self.mask_filename:
            self._mask_path = os.path.join(self.base_path, self.meter_folder, self.mask_filename)

    def _apply_mask_with_pil(self, img_bytes):
        """Load via PIL, apply file mask or circular mask; return pygame surface."""
        try:
            pil_img = Image.open(img_bytes).convert("RGBA")
            pil_img = pil_img.resize(self.art_dim)

            if self._mask_path and os.path.exists(self._mask_path):
                mask = Image.open(self._mask_path).convert('L')
                if mask.size != pil_img.size:
                    mask = mask.resize(pil_img.size)
                pil_img.putalpha(ImageOps.invert(mask))
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
        """Fetch image from URL, build scaled surface."""
        self._current_url = url
        self._scaled_surf = None
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

            surf = None
            if PIL_AVAILABLE:
                surf = self._apply_mask_with_pil(img_bytes)

            if surf is None:
                surf = self._load_surface_from_bytes(img_bytes)

            if surf:
                try:
                    scaled = pg.transform.smoothscale(surf, self.art_dim)
                except Exception:
                    scaled = pg.transform.scale(surf, self.art_dim)
                
                try:
                    self._scaled_surf = scaled.convert_alpha()
                except Exception:
                    self._scaled_surf = scaled
                
                self._need_first_blit = True

        except Exception:
            pass

    def get_backing_rect(self):
        """Get backing rect for this renderer."""
        if not self.art_pos or not self.art_dim:
            return None
        return pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

    def render(self, screen):
        """Render album art (static). Returns dirty rect if drawn, None if skipped."""
        if not self.art_pos or not self.art_dim or not self._scaled_surf:
            return None

        if not self._needs_redraw and not self._need_first_blit:
            return None

        screen.blit(self._scaled_surf, self.art_pos)
        dirty_rect = pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

        self._needs_redraw = False
        self._need_first_blit = False

        # Border
        if self.border_width and dirty_rect:
            try:
                if self.circle:
                    center = (self.art_pos[0] + self.art_dim[0] // 2,
                              self.art_pos[1] + self.art_dim[1] // 2)
                    rad = min(self.art_dim[0], self.art_dim[1]) // 2
                    pg.draw.circle(screen, self.font_color, center, rad, self.border_width)
                else:
                    pg.draw.rect(screen, self.font_color, pg.Rect(self.art_pos, self.art_dim), self.border_width)
            except Exception:
                pass

        return dirty_rect

    def force_redraw(self):
        """Force redraw on next render() call."""
        self._needs_redraw = True


# =============================================================================
# BasicHandler - Main handler class for basic skins
# =============================================================================
class BasicHandler:
    """
    Handler for basic skin type (meters only, no animated elements).
    
    RENDER Z-ORDER:
    1. bgr (static background - already on screen)
    2. album art (static)
    3. meters (meter.run())
    4. text fields
    5. indicators
    6. time remaining
    7. sample/icon
    8. fgr (foreground mask)
    
    FORCING BEHAVIOR:
    - NO forcing needed (no animated elements)
    
    This is the simplest and most CPU-efficient handler.
    """
    
    def __init__(self, screen, meter, config, meter_config, meter_config_volumio):
        """
        Initialize basic handler.
        
        :param screen: pygame screen surface
        :param meter: PeppyMeter meter instance
        :param config: Parsed config (cfg dict from main)
        :param meter_config: Meter-specific config (mc_vol dict)
        :param meter_config_volumio: Global volumio config
        """
        self.screen = screen
        self.meter = meter
        self.config = config
        self.mc_vol = meter_config
        self.global_config = meter_config_volumio
        
        self.SCREEN_WIDTH = config[SCREEN_INFO][WIDTH]
        self.SCREEN_HEIGHT = config[SCREEN_INFO][HEIGHT]
        
        # State tracking
        self.enabled = False
        self.bgr_surface = None  # Layer composition: static background
        self.dirty_rects = []
        
        # Meter timing delay
        self.meter_delay_ms = 10
        self.meter_delay_sec = 0.010
        
        # Renderers
        self.album_renderer = None
        self.indicator_renderer = None
        
        # Scrollers
        self.artist_scroller = None
        self.title_scroller = None
        self.album_scroller = None
        
        # Positions and fonts
        self.time_pos = None
        self.sample_pos = None
        self.type_pos = None
        self.type_rect = None
        self.sample_box = 0
        self.center_flag = False
        
        # Rects for layer composition clearing
        self.time_rect = None
        self.sample_rect = None
        self.art_rect = None
        
        # Fonts
        self.fontL = None
        self.fontR = None
        self.fontB = None
        self.fontDigi = None
        self.sample_font = None
        
        # Colors
        self.font_color = (255, 255, 255)
        self.time_color = (255, 255, 255)
        self.type_color = (255, 255, 255)
        
        # Foreground
        self.fgr_surf = None
        self.fgr_pos = (0, 0)
        self.fgr_regions = []
        
        # Caches
        self.last_time_str = ""
        self.last_time_surf = None
        self.last_sample_text = ""
        self.last_sample_surf = None
        self.last_track_type = ""
        self.last_format_icon_surf = None
        
        log_debug("BasicHandler initialized", "basic")
    
    def init_for_meter(self, meter_name):
        """Initialize handler for a specific meter."""
        mc = self.config.get(meter_name, {}) if meter_name else {}
        mc_vol = self.global_config.get(meter_name, {}) if meter_name else {}
        self.mc_vol = mc_vol
        
        log_debug(f"=== BasicHandler: Initializing meter: {meter_name} ===", "basic")
        log_debug(f"  config.extend = {mc_vol.get(EXTENDED_CONF, False)}", "verbose")
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("init", False):
            log_debug(f"[Init] BasicHandler: meter={meter_name}, extended={mc_vol.get(EXTENDED_CONF, False)}", "trace", "init")
        
        # Reset caches
        self.last_time_str = ""
        self.last_time_surf = None
        self.last_sample_text = ""
        self.last_sample_surf = None
        self.last_track_type = ""
        self.last_format_icon_surf = None
        
        # Fill screen black
        self.screen.fill((0, 0, 0))
        
        # Check if extended config enabled
        if not mc_vol.get(EXTENDED_CONF, False):
            self.enabled = False
            self._draw_static_assets(mc)
            self.meter.run()
            pg.display.update()
            return
        
        self.enabled = True
        
        # Meter timing delay (configurable, 0-20ms, default 10ms)
        self.meter_delay_ms = max(0, min(20, self.global_config.get(METER_DELAY, 10)))
        self.meter_delay_sec = self.meter_delay_ms / 1000.0
        
        # Load fonts
        self._load_fonts(mc_vol)
        
        # Draw static assets (background)
        self._draw_static_assets(mc)
        
        # Positions and colors
        self.center_flag = bool(mc_vol.get(PLAY_CENTER, mc_vol.get(PLAY_TXT_CENTER, False)))
        global_max = as_int(mc_vol.get(PLAY_MAX), 0)
        
        # Scrolling speed logic based on mode
        scrolling_mode = self.global_config.get("scrolling.mode", "skin")
        if scrolling_mode == "default":
            # System default: always 40
            scroll_speed_artist = 40
            scroll_speed_title = 40
            scroll_speed_album = 40
        elif scrolling_mode == "custom":
            # Custom: use UI-specified values
            scroll_speed_artist = self.global_config.get("scrolling.speed.artist", 40)
            scroll_speed_title = self.global_config.get("scrolling.speed.title", 40)
            scroll_speed_album = self.global_config.get("scrolling.speed.album", 40)
        else:
            # Skin mode: per-field from skin config
            scroll_speed_artist = mc_vol.get(SCROLLING_SPEED_ARTIST, 40)
            scroll_speed_title = mc_vol.get(SCROLLING_SPEED_TITLE, 40)
            scroll_speed_album = mc_vol.get(SCROLLING_SPEED_ALBUM, 40)
        
        log_debug(f"Scrolling: mode={scrolling_mode}, artist={scroll_speed_artist}, title={scroll_speed_title}, album={scroll_speed_album}", "verbose")
        
        artist_pos = mc_vol.get(PLAY_ARTIST_POS)
        title_pos = mc_vol.get(PLAY_TITLE_POS)
        album_pos = mc_vol.get(PLAY_ALBUM_POS)
        self.time_pos = mc_vol.get(TIME_REMAINING_POS)
        self.sample_pos = mc_vol.get(PLAY_SAMPLE_POS)
        self.type_pos = mc_vol.get(PLAY_TYPE_POS)
        type_dim = mc_vol.get(PLAY_TYPE_DIM)
        art_pos = mc_vol.get(ALBUMART_POS)
        art_dim = mc_vol.get(ALBUMART_DIM)
        
        log_debug("--- Playinfo Config ---", "verbose")
        log_debug(f"  playinfo.artist.pos = {artist_pos}", "verbose")
        log_debug(f"  playinfo.title.pos = {title_pos}", "verbose")
        log_debug(f"  playinfo.album.pos = {album_pos}", "verbose")
        log_debug(f"  time.remaining.pos = {self.time_pos}", "verbose")
        log_debug(f"  playinfo.samplerate.pos = {self.sample_pos}", "verbose")
        log_debug(f"  playinfo.type.pos = {self.type_pos}", "verbose")
        log_debug(f"  playinfo.type.dimension = {type_dim}", "verbose")
        log_debug(f"  albumart.pos = {art_pos}", "verbose")
        log_debug(f"  albumart.dimension = {art_dim}", "verbose")
        
        # Styles
        artist_style = mc_vol.get(PLAY_ARTIST_STYLE, FONT_STYLE_L)
        title_style = mc_vol.get(PLAY_TITLE_STYLE, FONT_STYLE_B)
        album_style = mc_vol.get(PLAY_ALBUM_STYLE, FONT_STYLE_L)
        sample_style = mc_vol.get(PLAY_SAMPLE_STYLE, FONT_STYLE_L)
        
        # Fonts per field
        artist_font = self._font_for_style(artist_style)
        title_font = self._font_for_style(title_style)
        album_font = self._font_for_style(album_style)
        self.sample_font = self._font_for_style(sample_style)
        
        # Colors
        self.font_color = sanitize_color(mc_vol.get(FONTCOLOR), (255, 255, 255))
        artist_color = sanitize_color(mc_vol.get(PLAY_ARTIST_COLOR), self.font_color)
        title_color = sanitize_color(mc_vol.get(PLAY_TITLE_COLOR), self.font_color)
        album_color = sanitize_color(mc_vol.get(PLAY_ALBUM_COLOR), self.font_color)
        self.time_color = sanitize_color(mc_vol.get(TIMECOLOR), self.font_color)
        self.type_color = sanitize_color(mc_vol.get(PLAY_TYPE_COLOR), self.font_color)
        
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
            if self.center_flag:
                return int(self.SCREEN_WIDTH * 0.6)
            return max(0, self.SCREEN_WIDTH - pos[0] - RIGHT_MARGIN)
        
        def get_box_width(pos, field_max):
            if field_max:
                return field_max
            if global_max:
                return global_max
            return auto_box_width(pos)
        
        artist_box = get_box_width(artist_pos, artist_max)
        title_box = get_box_width(title_pos, title_max)
        album_box = get_box_width(album_pos, album_max)
        
        if self.sample_pos and (global_max or sample_max):
            if sample_max:
                self.sample_box = sample_max
            else:
                self.sample_box = self.sample_font.size('-44.1 kHz 24 bit-')[0]
        else:
            self.sample_box = 0
        
        # LAYER COMPOSITION: Store background surface for clearing
        # This is captured AFTER background is drawn but BEFORE dynamic content
        self.bgr_surface = self.screen.copy()
        log_debug("  Background surface captured for layer composition", "verbose")
        
        # Store rects for layer composition clearing
        if self.time_pos:
            time_w = self.fontDigi.size('00:00')[0] + 10
            time_h = self.fontDigi.get_linesize()
            self.time_rect = pg.Rect(self.time_pos[0], self.time_pos[1], time_w, time_h)
            log_debug(f"  time_rect: x={self.time_rect.x}, y={self.time_rect.y}, w={self.time_rect.width}, h={self.time_rect.height}", "verbose")
        
        if self.sample_pos and self.sample_box:
            sample_h = self.sample_font.get_linesize()
            self.sample_rect = pg.Rect(self.sample_pos[0], self.sample_pos[1], self.sample_box, sample_h)
            log_debug(f"  sample_rect: x={self.sample_rect.x}, y={self.sample_rect.y}, w={self.sample_rect.width}, h={self.sample_rect.height}", "verbose")
        
        if art_pos and art_dim:
            self.art_rect = pg.Rect(art_pos[0], art_pos[1], art_dim[0], art_dim[1])
            log_debug(f"  art_rect: x={self.art_rect.x}, y={self.art_rect.y}, w={self.art_rect.width}, h={self.art_rect.height}", "verbose")
        
        # Create album art renderer (static for basic)
        self.album_renderer = None
        if art_pos and art_dim:
            screen_size = (self.SCREEN_WIDTH, self.SCREEN_HEIGHT)
            
            log_debug("--- Album Art Config ---", "verbose")
            log_debug(f"  albumart.pos = {art_pos}", "verbose")
            log_debug(f"  albumart.dimension = {art_dim}", "verbose")
            log_debug(f"  albumart.mask = {mc_vol.get(ALBUMART_MSK)}", "verbose")
            log_debug(f"  albumart.border = {mc_vol.get(ALBUMBORDER)}", "verbose")
            
            self.album_renderer = AlbumArtRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                art_pos=art_pos,
                art_dim=art_dim,
                screen_size=screen_size,
                font_color=self.font_color,
                border_width=mc_vol.get(ALBUMBORDER) or 0,
                mask_filename=mc_vol.get(ALBUMART_MSK),
                circle=False
            )
            log_debug("  AlbumArtRenderer created (static)", "verbose")
        
        # Create indicator renderer
        self.indicator_renderer = None
        try:
            from volumio_indicators import IndicatorRenderer, init_indicator_debug
            init_indicator_debug(DEBUG_LEVEL_CURRENT, DEBUG_TRACE)
            has_indicators = (
                mc_vol.get(VOLUME_POS) or mc_vol.get(MUTE_POS) or
                mc_vol.get(SHUFFLE_POS) or mc_vol.get(REPEAT_POS) or
                mc_vol.get(PLAYSTATE_POS) or mc_vol.get(PROGRESS_POS)
            )
            if has_indicators:
                fonts_dict = {
                    "light": self.fontL,
                    "regular": self.fontR,
                    "bold": self.fontB,
                    "digi": self.fontDigi
                }
                self.indicator_renderer = IndicatorRenderer(
                    config=mc_vol,
                    meter_config=self.global_config,
                    base_path=self.config.get(BASE_PATH),
                    meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                    fonts=fonts_dict
                )
                log_debug(f"  IndicatorRenderer created", "verbose")
        except ImportError as e:
            log_debug(f"  IndicatorRenderer not available: {e}", "verbose")
        except Exception as e:
            print(f"[BasicHandler] Failed to create IndicatorRenderer: {e}")
        
        # Create scrollers
        self.artist_scroller = ScrollingLabel(artist_font, artist_color, artist_pos, artist_box, center=self.center_flag, speed_px_per_sec=scroll_speed_artist) if artist_pos else None
        self.title_scroller = ScrollingLabel(title_font, title_color, title_pos, title_box, center=self.center_flag, speed_px_per_sec=scroll_speed_title) if title_pos else None
        self.album_scroller = ScrollingLabel(album_font, album_color, album_pos, album_box, center=self.center_flag, speed_px_per_sec=scroll_speed_album) if album_pos else None
        
        # LAYER COMPOSITION: Set background surface for scrollers
        if self.bgr_surface:
            if self.artist_scroller:
                self.artist_scroller.capture_backing(self.screen)  # For rect calculation
                self.artist_scroller.set_background_surface(self.bgr_surface)
            if self.title_scroller:
                self.title_scroller.capture_backing(self.screen)
                self.title_scroller.set_background_surface(self.bgr_surface)
            if self.album_scroller:
                self.album_scroller.capture_backing(self.screen)
                self.album_scroller.set_background_surface(self.bgr_surface)
        
        # Capture backing for indicators (indicators use skip_restore=True in basic handler,
        # but set_background_surfaces is still needed for proper transparent icon handling)
        if self.indicator_renderer and self.indicator_renderer.has_indicators():
            if self.bgr_surface:
                self.indicator_renderer.set_background_surfaces(self.bgr_surface)
            self.indicator_renderer.capture_backings(self.screen)
        
        # Now run meter to show initial needle positions
        self.meter.run()
        pg.display.update()
        
        # Type rect
        self.type_rect = pg.Rect(self.type_pos[0], self.type_pos[1], type_dim[0], type_dim[1]) if (self.type_pos and type_dim) else None
        
        # Load foreground
        self.fgr_surf = None
        self.fgr_regions = []
        fgr_name = mc.get(FGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        try:
            if fgr_name:
                meter_path = os.path.join(self.config.get(BASE_PATH), self.config.get(SCREEN_INFO)[METER_FOLDER])
                fgr_path = os.path.join(meter_path, fgr_name)
                self.fgr_surf = pg.image.load(fgr_path).convert_alpha()
                self.fgr_regions = compute_foreground_regions(self.fgr_surf)
                self.fgr_pos = (meter_x, meter_y)
                if self.fgr_regions:
                    log_debug(f"Foreground has {len(self.fgr_regions)} opaque regions for selective blit", "verbose")
        except Exception as e:
            print(f"[BasicHandler] Failed to load fgr '{fgr_name}': {e}")
        
        # Store album position for artist combination logic
        self.album_pos = album_pos
        
        log_debug("--- Initialization Complete ---", "verbose")
        log_debug(f"  Renderers: album_art={'YES' if self.album_renderer else 'NO'}, indicators={'YES' if self.indicator_renderer and self.indicator_renderer.has_indicators() else 'NO'}", "verbose")
        log_debug(f"  Layer composition: bgr_surface={'YES' if self.bgr_surface else 'NO'}", "verbose")
        log_debug(f"  Foreground: {'YES' if self.fgr_surf else 'NO'} ({len(self.fgr_regions) if self.fgr_regions else 0} regions)", "verbose")
    
    def _load_fonts(self, mc_vol):
        """Load fonts from config."""
        font_path = self.global_config.get(FONT_PATH) or ""
        
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
        
        # Light font
        light_file = self.global_config.get(FONT_LIGHT)
        if light_file and os.path.exists(font_path + light_file):
            self.fontL = pg.font.Font(font_path + light_file, size_light)
            log_debug(f"  Font light: loaded {font_path + light_file}", "verbose")
        else:
            self.fontL = pg.font.SysFont("DejaVuSans", size_light)
        
        # Regular font
        regular_file = self.global_config.get(FONT_REGULAR)
        if regular_file and os.path.exists(font_path + regular_file):
            self.fontR = pg.font.Font(font_path + regular_file, size_regular)
            log_debug(f"  Font regular: loaded {font_path + regular_file}", "verbose")
        else:
            self.fontR = pg.font.SysFont("DejaVuSans", size_regular)
        
        # Bold font
        bold_file = self.global_config.get(FONT_BOLD)
        if bold_file and os.path.exists(font_path + bold_file):
            self.fontB = pg.font.Font(font_path + bold_file, size_bold)
            log_debug(f"  Font bold: loaded {font_path + bold_file}", "verbose")
        else:
            self.fontB = pg.font.SysFont("DejaVuSans", size_bold, bold=True)
        
        # Digital font for time
        digi_path = os.path.join(os.path.dirname(__file__), 'fonts', 'DSEG7Classic-Italic.ttf')
        if os.path.exists(digi_path):
            self.fontDigi = pg.font.Font(digi_path, size_digi)
            log_debug(f"  Font digi: loaded {digi_path}", "verbose")
        else:
            self.fontDigi = pg.font.SysFont("DejaVuSans", size_digi)
    
    def _font_for_style(self, style):
        """Get font for style."""
        if style == FONT_STYLE_B:
            return self.fontB
        elif style == FONT_STYLE_R:
            return self.fontR
        else:
            return self.fontL
    
    def _draw_static_assets(self, mc):
        """Draw static background."""
        meter_path = os.path.join(self.config.get(BASE_PATH), self.config.get(SCREEN_INFO)[METER_FOLDER])
        
        # Draw full screen background first (if configured)
        screen_bgr_name = mc.get('screen.bgr')
        if screen_bgr_name:
            try:
                img_path = os.path.join(meter_path, screen_bgr_name)
                img = pg.image.load(img_path).convert()
                self.screen.blit(img, (0, 0))
            except Exception as e:
                print(f"[BasicHandler] Failed to load screen.bgr '{screen_bgr_name}': {e}")
        
        # Draw meter background at meter position (convert_alpha for PNG transparency)
        bgr_name = mc.get(BGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        if bgr_name:
            try:
                bgr_path = os.path.join(meter_path, bgr_name)
                bgr_surf = pg.image.load(bgr_path).convert_alpha()
                self.screen.blit(bgr_surf, (meter_x, meter_y))
            except Exception as e:
                print(f"[BasicHandler] Failed to load bgr '{bgr_name}': {e}")
    
    def render(self, meta, now_ticks):
        """
        Render one frame.
        
        BASIC RENDER Z-ORDER (simplest - no backing conflicts):
        1. Render album art (if URL changed)
        2. meter.run() - draws needles ON TOP of art
        3. Render text
        4. Render indicators
        5. Render time
        6. Render sample/icon
        7. Render fgr (topmost layer)
        
        :param meta: Metadata dict
        :param now_ticks: pygame.time.get_ticks() value
        :return: List of dirty rects
        """
        if not self.enabled:
            meter_rects = self.meter.run()
            if meter_rects:
                return meter_rects if isinstance(meter_rects, list) else [meter_rects]
            return []
        
        dirty_rects = []
        
        # Extract metadata
        artist = meta.get("artist", "")
        title = meta.get("title", "")
        album = meta.get("album", "")
        albumart = meta.get("albumart", "")
        samplerate = meta.get("samplerate", "")
        bitdepth = meta.get("bitdepth", "")
        track_type = meta.get("trackType", "")
        bitrate = meta.get("bitrate", "")
        status = meta.get("status", "")
        volatile = meta.get("volatile", False)
        is_playing = status == "play"
        duration = meta.get("duration", 0) or 0
        
        # Seek interpolation - calculate current position based on elapsed time
        # CRITICAL: Don't use 'or' fallback - 0 is a valid seek position!
        seek_raw = meta.get("_seek_raw")
        if seek_raw is None:
            seek_raw = meta.get("seek", 0) or 0
        seek = seek_raw
        seek_update_time = meta.get("_seek_update", 0)
        
        # Interpolate seek based on elapsed time when playing
        # Use _seek_raw to avoid accumulation error from previous frames
        # Webradio excluded by duration=0 check
        if is_playing and duration > 0:
            if seek_update_time > 0:
                elapsed_ms = (time.time() - seek_update_time) * 1000
                seek = min(duration * 1000, seek_raw + elapsed_ms)
                meta["seek"] = seek  # Update for indicators (progress bar)
        
        # Pre-calculate album art state
        album_url_changed = False
        if self.album_renderer:
            album_url_changed = albumart != self.album_renderer._current_url
        
        # =================================================================
        # RENDER LAYERS (no backing restore needed - no animated elements)
        # =================================================================
        
        # LAYER: Album art (only redraw on URL change) - BEFORE meters
        if self.album_renderer and album_url_changed:
            # LAYER COMPOSITION: Clear from bgr_surface
            if self.bgr_surface and self.art_rect:
                self.screen.blit(self.bgr_surface, self.art_rect.topleft, self.art_rect)
            
            self.album_renderer.load_from_url(albumart)
            rect = self.album_renderer.render(self.screen)
            if rect:
                dirty_rects.append(rect)
        
        # LAYER: Meters (draw AFTER art so needles are visible)
        meter_rects = self.meter.run()
        if meter_rects:
            if isinstance(meter_rects, list):
                for item in meter_rects:
                    if item:
                        if isinstance(item, tuple) and len(item) >= 2:
                            rect = item[1]
                            if rect:
                                dirty_rects.append(rect)
                        elif hasattr(item, 'x'):
                            dirty_rects.append(item)
            elif isinstance(meter_rects, tuple) and len(meter_rects) >= 2:
                rect = meter_rects[1]
                if rect:
                    dirty_rects.append(rect)
            elif hasattr(meter_rects, 'x'):
                dirty_rects.append(meter_rects)
        
        # LAYER: Text fields (NO forcing needed)
        if self.artist_scroller:
            display_artist = artist
            if not self.album_pos and album:
                display_artist = f"{artist} - {album}" if artist else album
            self.artist_scroller.update_text(display_artist)
            rect = self.artist_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)
        
        if self.title_scroller:
            self.title_scroller.update_text(title)
            rect = self.title_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)
        
        if self.album_scroller:
            self.album_scroller.update_text(album)
            rect = self.album_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)
        
        # LAYER: Indicators (skip_restore=True - meters redraw every frame, procedural indicators self-clear)
        if self.indicator_renderer and self.indicator_renderer.has_indicators():
            self.indicator_renderer.render(self.screen, meta, dirty_rects, force=False, skip_restore=True)
        
        # LAYER: Time remaining (with persist countdown support)
        if self.time_pos:
            current_time = time_module.time()
            
            # Check for persist countdown
            persist_countdown_sec = None
            persist_display_mode = "freeze"
            persist_file = '/tmp/peppy_persist'
            if not is_playing and os.path.exists(persist_file):
                try:
                    with open(persist_file, 'r') as f:
                        parts = f.read().strip().split(':')
                        if len(parts) >= 2:
                            p_duration = int(parts[0])
                            start_ts = int(parts[1]) / 1000.0
                            elapsed_persist = current_time - start_ts
                            persist_countdown_sec = max(0, p_duration - int(elapsed_persist))
                        if len(parts) >= 3:
                            persist_display_mode = parts[2]
                except Exception:
                    pass
            
            time_remain_sec = meta.get("_time_remain", -1)
            time_last_update = meta.get("_time_update", 0)
            
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("time", False):
                log_debug(f"[Time] INPUT: remain={time_remain_sec}s, playing={is_playing}, persist_mode={persist_display_mode}, persist_sec={persist_countdown_sec}", "trace", "time")
            
            show_persist_countdown = (
                persist_display_mode == "countdown" and
                persist_countdown_sec is not None and
                persist_countdown_sec >= 0
            )
            
            if show_persist_countdown:
                display_sec = persist_countdown_sec
            elif time_remain_sec >= 0:
                if is_playing:
                    elapsed = current_time - time_last_update
                    if elapsed >= 1.0:
                        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("seek", False):
                            log_debug(f"[Seek] INTERPOLATE: raw={time_remain_sec}s, elapsed={elapsed:.1f}s, result={max(0, time_remain_sec - int(elapsed))}s", "trace", "seek")
                        time_remain_sec = max(0, time_remain_sec - int(elapsed))
                display_sec = time_remain_sec
            else:
                display_sec = -1
            
            if display_sec >= 0:
                mins = display_sec // 60
                secs = display_sec % 60
                time_str = f"{mins:02d}:{secs:02d}"
                
                if time_str != self.last_time_str:
                    self.last_time_str = time_str
                    
                    # LAYER COMPOSITION: Clear from bgr_surface
                    if self.bgr_surface and self.time_rect:
                        self.screen.blit(self.bgr_surface, self.time_rect.topleft, self.time_rect)
                        dirty_rects.append(self.time_rect.copy())
                    
                    if show_persist_countdown:
                        t_color = (242, 165, 0)  # Orange for persist countdown
                    elif 0 < display_sec <= 10:
                        t_color = (242, 0, 0)  # Red for final 10 seconds
                    else:
                        t_color = self.time_color
                    
                    self.last_time_surf = self.fontDigi.render(time_str, True, t_color)
                    self.screen.blit(self.last_time_surf, self.time_pos)
                    
                    if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("time", False):
                        log_debug(f"[Time] OUTPUT: rendered '{time_str}' at {self.time_pos}, color={t_color}", "trace", "time")
        
        # LAYER: Sample rate / format icon
        # Format icon
        if self.type_rect:
            fmt = (track_type or "").strip().lower().replace(" ", "_")
            if fmt == "dsf":
                fmt = "dsd"
            
            # Strip signal strength indicators and other suffixes
            # DAB sends "DAB ●◦◦◦◦" -> "dab_●◦◦◦◦", need just "dab"
            # FM sends "FM ◦◦◦◦◦" -> "fm_◦◦◦◦◦", need just "fm"
            fmt_clean = re.sub(r'[^a-z0-9_].*', '', fmt)  # Keep only alphanumeric prefix
            if fmt_clean:
                fmt = fmt_clean
            
            # Normalize common trackType variants to icon names
            format_map = {
                'dab_radio': 'dab',
                'dab_': 'dab',
                'dab': 'dab',
                'rtlsdr': 'dab',
                'rtlsdr_radio': 'dab',
                'fm_radio': 'fm',
                'fm_': 'fm',
                'fm': 'fm',
                'webradio': 'radio',
                'web_radio': 'radio',
                'internet_radio': 'radio',
                'tidal_connect': 'tidal',
                'qobuz_connect': 'qobuz',
                'spotify': 'spotify',
                'spotify_connect': 'spotify',
                'airplay': 'airplay',
                'bluetooth': 'bluetooth',
                'upnp': 'upnp',
                'dlna': 'upnp',
            }
            fmt_before = fmt
            fmt = format_map.get(fmt, fmt)
            
            # TRACE: Log format icon processing
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("metadata", False):
                log_debug(f"[FormatIcon] INPUT: track_type='{track_type}', fmt_normalized='{fmt_before}', fmt_mapped='{fmt}'", "trace", "metadata")
            
            if fmt != self.last_track_type:
                self.last_track_type = fmt
                
                # LAYER COMPOSITION: Clear from bgr_surface
                if self.bgr_surface and self.type_rect:
                    self.screen.blit(self.bgr_surface, self.type_rect.topleft, self.type_rect)
                
                file_path = os.path.dirname(__file__)
                local_icons = {'tidal', 'cd', 'qobuz', 'dab', 'fm', 'radio'}
                if fmt in local_icons:
                    icon_path = os.path.join(file_path, 'format-icons', f"{fmt}.svg")
                else:
                    icon_path = f"/volumio/http/www3/app/assets-common/format-icons/{fmt}.svg"
                
                if not os.path.exists(icon_path):
                    # Render text fallback
                    if self.sample_font:
                        txt_surf = self.sample_font.render(fmt[:4], True, self.type_color)
                        self.screen.blit(txt_surf, (self.type_rect.x, self.type_rect.y))
                        self.last_format_icon_surf = txt_surf
                    dirty_rects.append(self.type_rect.copy())
                else:
                    try:
                        if pg.version.ver.startswith("2"):
                            # Pygame 2 native SVG
                            img = pg.image.load(icon_path)
                            w, h = img.get_width(), img.get_height()
                            sc = min(self.type_rect.width / float(w), self.type_rect.height / float(h))
                            new_size = (max(1, int(w * sc)), max(1, int(h * sc)))
                            try:
                                img = pg.transform.smoothscale(img, new_size)
                            except Exception:
                                img = pg.transform.scale(img, new_size)
                            # Convert to format suitable for pixel manipulation
                            img = img.convert_alpha()
                            set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                            dx = self.type_rect.x + (self.type_rect.width - img.get_width()) // 2
                            dy = self.type_rect.y + (self.type_rect.height - img.get_height()) // 2
                            self.screen.blit(img, (dx, dy))
                            self.last_format_icon_surf = img
                        elif CAIROSVG_AVAILABLE and PIL_AVAILABLE:
                            # Pygame 1.x with cairosvg
                            png_bytes = cairosvg.svg2png(url=icon_path,
                                                          output_width=self.type_rect.width,
                                                          output_height=self.type_rect.height)
                            pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                            img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                            img = img.convert_alpha()
                            set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                            dx = self.type_rect.x + (self.type_rect.width - img.get_width()) // 2
                            dy = self.type_rect.y + (self.type_rect.height - img.get_height()) // 2
                            self.screen.blit(img, (dx, dy))
                            self.last_format_icon_surf = img
                        dirty_rects.append(self.type_rect.copy())
                    except Exception as e:
                        print(f"[BasicHandler] FormatIcon error: {e}")
        
        # Sample rate
        if self.sample_pos and self.sample_box:
            sample_text = f"{samplerate} {bitdepth}".strip()
            if not sample_text:
                sample_text = bitrate.strip() if bitrate else ""
            
            if sample_text and sample_text != self.last_sample_text:
                self.last_sample_text = sample_text
                
                # LAYER COMPOSITION: Clear from bgr_surface
                if self.bgr_surface and self.sample_rect:
                    self.screen.blit(self.bgr_surface, self.sample_rect.topleft, self.sample_rect)
                    dirty_rects.append(self.sample_rect.copy())
                
                self.last_sample_surf = self.sample_font.render(sample_text, True, self.type_color)
                
                if self.center_flag and self.sample_box:
                    sx = self.sample_pos[0] + (self.sample_box - self.last_sample_surf.get_width()) // 2
                else:
                    sx = self.sample_pos[0]
                self.screen.blit(self.last_sample_surf, (sx, self.sample_pos[1]))
        
        # LAYER: Foreground mask
        if self.fgr_surf and dirty_rects:
            fgr_x, fgr_y = self.fgr_pos
            if self.fgr_regions:
                # Selective blit - only regions overlapping dirty rects
                for region in self.fgr_regions:
                    # Translate region to screen coordinates
                    screen_rect = region.move(fgr_x, fgr_y)
                    # Check if any dirty rect overlaps this region
                    for dirty in dirty_rects:
                        if screen_rect.colliderect(dirty):
                            # Blit just this region from foreground surface
                            self.screen.blit(self.fgr_surf, screen_rect.topleft, region)
                            break
            else:
                # Fallback: no regions computed, blit entire foreground
                self.screen.blit(self.fgr_surf, self.fgr_pos)
        
        # METER TIMING: Delay to allow audio buffer to accumulate samples
        # Without this, fast render loops can outpace audio data source
        if self.meter_delay_sec > 0:
            time_module.sleep(self.meter_delay_sec)
        
        return dirty_rects
    
    def cleanup(self):
        """Release resources on shutdown."""
        log_debug("BasicHandler cleanup", "basic")
        self.bgr_surface = None
        self.album_renderer = None
        self.indicator_renderer = None
        self.artist_scroller = None
        self.title_scroller = None
        self.album_scroller = None
