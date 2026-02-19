# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Cassette Handler - Self-contained module for cassette skin rendering
#
# This file is part of PeppyMeter for Volumio
#
# SKIN TYPE: CASSETTE
# - HAS: reel_left, reel_right, static album art
# - NO: vinyl, tonearm
# - ARCHITECTURE: Layer composition (no backing restore collisions)
#
# This module is intentionally self-contained with duplicated components
# to eliminate dead code paths and reduce CPU overhead.

import os
import io
import math
import time
import time as time_module
import requests
import pygame as pg

# Layer composition system
from volumio_compositor import LayerCompositor

try:
    from PIL import Image, ImageOps, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except ImportError:
    CAIROSVG_AVAILABLE = False

# =============================================================================
# Configuration Constants (cassette-specific subset)
# =============================================================================
from configfileparser import (
    SCREEN_INFO, WIDTH, HEIGHT, FRAME_RATE, BASE_PATH, METER_FOLDER,
    BGR_FILENAME, FGR_FILENAME
)

from volumio_configfileparser import (
    EXTENDED_CONF, METER_DELAY,
    ROTATION_QUALITY, ROTATION_FPS, ROTATION_SPEED, SMOOTH_ROTATION,  # SMOOTH_ROTATION: rollback remove from import
    REEL_DIRECTION, SPOOL_LEFT_SPEED, SPOOL_RIGHT_SPEED, SPOOL_ADAPTIVE, QUEUE_MODE,
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
    TIME_ELAPSED_POS, TIME_ELAPSED_COLOR, TIME_TOTAL_POS, TIME_TOTAL_COLOR,
    FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_DIGI, FONTCOLOR,
    FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_L
)

# Reel configuration constants
try:
    from volumio_configfileparser import (
        REEL_LEFT_FILE, REEL_LEFT_POS, REEL_LEFT_CENTER,
        REEL_RIGHT_FILE, REEL_RIGHT_POS, REEL_RIGHT_CENTER,
        REEL_ROTATION_SPEED
    )
except ImportError:
    REEL_LEFT_FILE = "reel.left.filename"
    REEL_LEFT_POS = "reel.left.pos"
    REEL_LEFT_CENTER = "reel.left.center"
    REEL_RIGHT_FILE = "reel.right.filename"
    REEL_RIGHT_POS = "reel.right.pos"
    REEL_RIGHT_CENTER = "reel.right.center"
    REEL_ROTATION_SPEED = "reel.rotation.speed"

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
# Keys use DOT notation to match config key suffix (e.g., "reel.left" for debug.trace.reel.left)
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


def init_cassette_debug(level, trace_dict):
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


# Rotation quality presets (FPS, step_degrees)
ROTATION_PRESETS = {
    "low":    (4, 12),
    "medium": (8, 6),
    "high":   (15, 3),
}

USE_PRECOMPUTED_FRAMES = True


def get_rotation_params(quality, custom_fps=8):
    """Get rotation FPS and step degrees based on quality setting."""
    if quality == "custom":
        step = max(1, min(12, int(45 / max(1, custom_fps))))
        return (custom_fps, step)
    return ROTATION_PRESETS.get(quality, ROTATION_PRESETS["medium"])


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
        self._needs_redraw = True
        self._last_draw_offset = -1
    
    def set_background_surface(self, bgr_surface):
        """Set background surface for layer composition clearing.
        
        When set, draw() will clear from this surface instead of captured backing.
        This eliminates backing collision artifacts.
        """
        self._bgr_surface = bgr_surface

    def capture_backing(self, surface):
        """Capture backing surface for this label's area.
        
        NOTE: With layer composition, this is only used as fallback.
        Prefer set_background_surface() for proper z-order handling.
        """
        if not self.pos or self.box_width <= 0:
            return
        x, y = self.pos
        height = self.font.get_linesize()
        self._backing_rect = pg.Rect(x, y, self.box_width, height)
        try:
            self._backing = surface.subsurface(self._backing_rect).copy()
        except Exception:
            self._backing = pg.Surface((self._backing_rect.width, self._backing_rect.height))
            self._backing.fill((0, 0, 0))
        
        # TRACE: Log backing capture
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] CAPTURE: pos={self.pos}, box_w={self.box_width}, rect={self._backing_rect}", "trace", "scrolling")

    def update_text(self, new_text):
        """Update text content, reset scroll position if changed."""
        new_text = new_text or ""
        if new_text == self.text and self.surf is not None:
            return False
        
        # TRACE: Log text update
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] UPDATE: old='{self.text[:20]}', new='{new_text[:20]}'", "trace", "scrolling")
        
        self.text = new_text
        self.surf = self.font.render(self.text, True, self.color)
        self.text_w, self.text_h = self.surf.get_size()
        self.offset = 0.0
        self.direction = 1
        self._pause_until = 0
        self._last_time = pg.time.get_ticks()
        self._needs_redraw = True
        self._last_draw_offset = -1
        return True

    def force_redraw(self):
        """Force redraw on next draw() call."""
        self._needs_redraw = True
        self._last_draw_offset = -1
        
        # TRACE: Log force redraw
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] FORCE: text='{self.text[:20]}...'", "trace", "scrolling")

    def draw(self, surface):
        """Draw label, handling scroll animation with self-backing.
        Returns dirty rect if drawn, None if skipped.
        
        LAYER COMPOSITION: When _bgr_surface is set, clears from background
        instead of captured backing. This prevents collision artifacts when
        text overlaps other dynamic content.
        """
        if not self.surf or not self.pos or self.box_width <= 0:
            return None
        
        x, y = self.pos
        box_rect = pg.Rect(x, y, self.box_width, self.text_h)
        
        # Text fits - no scrolling needed
        if self.text_w <= self.box_width:
            if not self._needs_redraw:
                return None
            
            # TRACE: Log static text draw
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
                log_debug(f"[Scrolling] STATIC: text='{self.text[:20]}...', forced={self._needs_redraw}", "trace", "scrolling")
            
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
# AlbumArtRenderer - CASSETTE VERSION (static only, no rotation)
# =============================================================================
class AlbumArtRenderer:
    """
    Handles album art loading with optional file mask or circular crop.
    CASSETTE VERSION: Static only - no rotation support.
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
        
        # Backing surface tracking (for compatibility)
        self._backing_rect = None
        self._backing_surf = None

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

    def check_pending_load(self):
        """Compatibility stub - sync loading has no pending loads."""
        return False

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
# ReelRenderer - Rotating reel graphics for cassette skins
# =============================================================================
class ReelRenderer:
    """
    Handles file-based reel graphics with rotation for cassette-style skins.
    Pre-computes rotation frames and uses FPS gating for CPU reduction.
    """

    def __init__(self, base_path, meter_folder, filename, pos, center, 
                 rotate_rpm=1.5, angle_step_deg=1.0, rotation_fps=8, rotation_step=6,
                 speed_multiplier=1.0, direction="ccw", name="reel", smooth_rotation=False):  # SMOOTH_ROTATION: rollback remove param
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pos = pos
        self.center = center
        self._base_rpm = abs(float(rotate_rpm))  # Base RPM from config
        self.speed_multiplier = float(speed_multiplier)  # Can be changed at runtime
        self.rotate_rpm = self._base_rpm * self.speed_multiplier  # Effective RPM
        self.angle_step_deg = float(angle_step_deg)
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)
        self.direction_mult = 1 if direction == "cw" else -1
        
        # Trace component name uses DOT notation to match DEBUG_TRACE keys
        self._trace_name = name.replace("_", " ").title()
        self._trace_component = name.replace("_", ".")  # "reel_left" -> "reel.left"
        
        self._original_surf = None
        self._rot_frames = None
        self._current_angle = 0.0
        self._loaded = False
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._need_first_blit = False
        # SMOOTH_ROTATION: rollback remove next 2 lines
        self._smooth_rotation = str(smooth_rotation).strip().lower() in ('1', 'true', 'yes') if isinstance(smooth_rotation, str) else bool(smooth_rotation)
        
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
        """Update rotation angle based on RPM, direction, and playback status."""
        # Calculate effective RPM from base RPM and current speed multiplier
        effective_rpm = self._base_rpm * self.speed_multiplier
        if effective_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if volatile and status in ("stop", "pause"):
            status = "play"
        if status == "play":
            # SMOOTH_ROTATION: rollback replace block with: dt = self._blit_interval_ms / 1000.0
            if getattr(self, '_smooth_rotation', False) and self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                dt = min(max(dt, 0.0), 0.5)
            else:
                dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + effective_rpm * 6.0 * dt * self.direction_mult) % 360.0
            if getattr(self, '_smooth_rotation', False):
                self._last_blit_tick = now_ticks
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating)."""
        if not self._loaded or not self._original_surf:
            return False
        
        # TRACE: Log first blit check
        if self._need_first_blit:
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
                log_debug(f"[{self._trace_name}] FIRST_BLIT: will return True", "trace", self._trace_component)
            return True
        
        effective_rpm = self._base_rpm * self.speed_multiplier
        if not self.center or effective_rpm <= 0.0:
            return self._needs_redraw
        # SMOOTH_ROTATION: rollback remove next 2 lines
        if getattr(self, '_smooth_rotation', False) and effective_rpm > 0.0:
            return True
        
        result = (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        # TRACE: Log will_blit decision (only when true to reduce noise)
        if result and DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            log_debug(f"[{self._trace_name}] DECISION: will_blit=True, angle={self._current_angle:.1f}, interval={self._blit_interval_ms}ms", "trace", self._trace_component)
        
        return result
    
    def get_backing_rect(self):
        """Get bounding rectangle for backing surface (extended for rotation)."""
        if not self._original_surf or not self.center:
            return None
        
        w = self._original_surf.get_width()
        h = self._original_surf.get_height()
        diag = int(max(w, h) * math.sqrt(2)) + 4
        
        ext_x = self.center[0] - diag // 2
        ext_y = self.center[1] - diag // 2
        
        return pg.Rect(ext_x, ext_y, diag, diag)
    
    def get_visual_rect(self):
        """Get visual bounding rectangle (actual image extent, not rotation-safe).
        
        Used to calculate meter exclusion zones - the visual rect shows where
        the reel image actually appears (before rotation extends it).
        """
        if not self._original_surf or not self.center:
            return None
        
        w = self._original_surf.get_width()
        h = self._original_surf.get_height()
        
        # Visual rect centered on rotation pivot
        x = self.center[0] - w // 2
        y = self.center[1] - h // 2
        
        return pg.Rect(x, y, w, h)
    
    def render(self, screen, status, now_ticks, volatile=False):
        """Render the reel (rotated if playing).
        Returns dirty rect if drawn, None if skipped."""
        if not self._loaded or not self._original_surf:
            return None
        
        if not self.will_blit(now_ticks):
            return None
        
        # TRACE: Log render input
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            log_debug(f"[{self._trace_name}] INPUT: status={status}, angle={self._current_angle:.1f}, volatile={volatile}", "trace", self._trace_component)
        
        # SMOOTH_ROTATION: skip when smooth (set in _update_angle); rollback remove this condition
        if not getattr(self, '_smooth_rotation', False):
            self._last_blit_tick = now_ticks
        
        if not self.center:
            screen.blit(self._original_surf, self.pos)
            self._needs_redraw = False
            self._need_first_blit = False
            rect = pg.Rect(self.pos[0], self.pos[1], 
                          self._original_surf.get_width(), 
                          self._original_surf.get_height())
            # TRACE: Log static render output
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
                log_debug(f"[{self._trace_name}] OUTPUT: static (no rotation), rect={rect}", "trace", self._trace_component)
            return rect
        
        self._update_angle(status, now_ticks, volatile=volatile)
        
        if self._rot_frames:
            idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
            rot = self._rot_frames[idx]
        else:
            try:
                rot = pg.transform.rotate(self._original_surf, -self._current_angle)
            except Exception:
                rot = pg.transform.rotate(self._original_surf, int(-self._current_angle))
        
        rot_rect = rot.get_rect(center=self.center)
        screen.blit(rot, rot_rect.topleft)
        self._needs_redraw = False
        self._need_first_blit = False
        
        backing_rect = self.get_backing_rect()
        
        # TRACE: Log rotated render output
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get(self._trace_component, False):
            frame_info = f"frame_idx={idx}" if self._rot_frames else "realtime"
            log_debug(f"[{self._trace_name}] OUTPUT: {frame_info}, angle={self._current_angle:.1f}, backing={backing_rect}", "trace", self._trace_component)
        
        return backing_rect


# =============================================================================
# CassetteHandler - Main handler class for cassette skins
# =============================================================================
class CassetteHandler:
    """
    Handler for cassette skin type.
    
    LAYER COMPOSITION ARCHITECTURE:
    Layers (bottom to top):
      Z0: Background (static, drawn to screen at init)
      Z1: Reels layer (animated rotation)
      Z2: Art layer (changes on track)
      --: Meters (draws to screen via meter.run())
      Z4: Text layer (scrollers)
      Z5: Indicators layer (volume, mute, shuffle, repeat, playstate, progress)
      Z6: Meta layer (time, type icon, sample rate)
      Z7: Foreground mask (static, drawn to screen at init)
    
    Each component renders to its own layer surface (transparent).
    Compositor blits layers to screen in z-order.
    No backing restore needed - no collision possible.
    
    COMPOSITE SEQUENCE:
    1. Reels render to reels layer (if animating)
    2. Art renders to art layer (if changed)
    3. Compositor blits Z1-Z2 to screen
    4. Meters draw to screen (meter.run())
    5. Text renders to text layer
    6. Indicators render to indicators layer
    7. Meta renders to meta layer (time/type/sample)
    8. Compositor blits Z4-Z6 to screen
    9. Foreground mask drawn to screen (selective)
    """
    
    def __init__(self, screen, meter, config, meter_config, meter_config_volumio):
        """
        Initialize cassette handler.
        
        :param screen: pygame screen surface
        :param meter: PeppyMeter meter instance
        :param config: Parsed config (cfg dict from main)
        :param meter_config: Meter-specific config (mc_vol dict)
        :param meter_config_volumio: Global volumio config (from config.txt)
        """
        self.screen = screen
        self.meter = meter
        self.config = config
        self.mc_vol = meter_config
        self.meter_config_volumio = meter_config_volumio  # Renamed for clarity
        
        self.SCREEN_WIDTH = config[SCREEN_INFO][WIDTH]
        self.SCREEN_HEIGHT = config[SCREEN_INFO][HEIGHT]
        
        # State tracking
        self.enabled = False
        self.dirty_rects = []
        
        # Layer compositor (replaces backing_dict)
        self.compositor = None
        
        # Renderers (cassette-specific)
        self.reel_left = None
        self.reel_right = None
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
        self.time_rect = None
        self.sample_rect = None
        self.sample_box = 0
        self.center_flag = False
        
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
        
        # Background surface for layer composition clearing
        self.bgr_surface = None
        
        # Caches
        self.last_time_str = ""
        self.last_elapsed_str = ""
        self.last_total_str = ""
        self.last_time_surf = None
        self.last_sample_text = ""
        self.last_sample_surf = None
        self.last_track_type = ""
        self.last_format_icon_surf = None
        
        log_debug("CassetteHandler initialized", "basic")
        
        # Performance: meter timing delay (configurable, affects CPU usage)
        # Higher values = lower CPU but meters may feel sluggish
        # Lower values = higher CPU but more responsive meters
        self.meter_delay_ms = max(0, min(20, meter_config_volumio.get(METER_DELAY, 10)))
        self.meter_delay_sec = self.meter_delay_ms / 1000.0
    
    def init_for_meter(self, meter_name):
        """Initialize handler for a specific meter."""
        mc = self.config.get(meter_name, {}) if meter_name else {}
        mc_vol = self.meter_config_volumio.get(meter_name, {}) if meter_name else {}
        self.mc_vol = mc_vol
        
        log_debug(f"=== CassetteHandler: Initializing meter: {meter_name} ===", "basic")
        log_debug(f"  config.extend = {mc_vol.get(EXTENDED_CONF, False)}", "verbose")
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("init", False):
            log_debug(f"[Init] CassetteHandler: meter={meter_name}, extended={mc_vol.get(EXTENDED_CONF, False)}", "trace", "init")
        
        # Reset caches
        self.last_time_str = ""
        self.last_elapsed_str = ""
        self.last_total_str = ""
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
        
        # Load fonts
        self._load_fonts(mc_vol)
        
        # Draw static assets (background)
        self._draw_static_assets(mc)
        
        # Positions and colors
        self.center_flag = bool(mc_vol.get(PLAY_CENTER, mc_vol.get(PLAY_TXT_CENTER, False)))
        global_max = as_int(mc_vol.get(PLAY_MAX), 0)
        
        # Scrolling speed logic based on mode (from global config)
        scrolling_mode = self.meter_config_volumio.get("scrolling.mode", "skin")
        if scrolling_mode == "default":
            # System default: always 40
            scroll_speed_artist = 40
            scroll_speed_title = 40
            scroll_speed_album = 40
        elif scrolling_mode == "custom":
            # Custom: use UI-specified values from global config
            scroll_speed_artist = self.meter_config_volumio.get("scrolling.speed.artist", 40)
            scroll_speed_title = self.meter_config_volumio.get("scrolling.speed.title", 40)
            scroll_speed_album = self.meter_config_volumio.get("scrolling.speed.album", 40)
        else:
            # Skin mode: per-field from skin -> global from skin -> 40
            scroll_speed_artist = mc_vol.get(SCROLLING_SPEED_ARTIST, 40)
            scroll_speed_title = mc_vol.get(SCROLLING_SPEED_TITLE, 40)
            scroll_speed_album = mc_vol.get(SCROLLING_SPEED_ALBUM, 40)
        
        log_debug(f"Scrolling: mode={scrolling_mode}, artist={scroll_speed_artist}, title={scroll_speed_title}, album={scroll_speed_album}")
        
        artist_pos = mc_vol.get(PLAY_ARTIST_POS)
        title_pos = mc_vol.get(PLAY_TITLE_POS)
        album_pos = mc_vol.get(PLAY_ALBUM_POS)
        self.time_pos = mc_vol.get(TIME_REMAINING_POS)
        self.time_elapsed_pos = mc_vol.get(TIME_ELAPSED_POS)
        self.time_total_pos = mc_vol.get(TIME_TOTAL_POS)
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
        self.time_elapsed_color = sanitize_color(mc_vol.get(TIME_ELAPSED_COLOR), self.time_color)
        self.time_total_color = sanitize_color(mc_vol.get(TIME_TOTAL_COLOR), self.time_color)
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
        
        # =================================================================
        # LAYER COMPOSITION SETUP
        # =================================================================
        # Create compositor and layers (replaces backing captures)
        screen_size = (self.SCREEN_WIDTH, self.SCREEN_HEIGHT)
        self.compositor = LayerCompositor(self.screen, screen_size)
        
        # Determine art region for layer optimization
        art_region = None
        if art_pos and art_dim:
            art_region = pg.Rect(art_pos[0], art_pos[1], art_dim[0], art_dim[1])
        
        log_debug("--- Layer Composition Setup ---", "verbose")
        
        # Z1: Reels layer (will be sized after reel renderers created)
        # Created later once we know reel backing rects
        
        # Z2: Art layer (region-optimized)
        if art_region:
            self.compositor.add_layer("art", z_index=2, region=art_region)
            log_debug(f"  Layer 'art': z=2, region={art_region}", "verbose")
        else:
            self.compositor.add_layer("art", z_index=2)
            log_debug(f"  Layer 'art': z=2, fullscreen", "verbose")
        
        # Z4: Text layer (fullscreen for flexible positioning)
        self.compositor.add_layer("text", z_index=4)
        log_debug(f"  Layer 'text': z=4, fullscreen", "verbose")
        
        # Z5: Indicators layer
        self.compositor.add_layer("indicators", z_index=5)
        log_debug(f"  Layer 'indicators': z=5, fullscreen", "verbose")
        
        # Z6: Meta layer (time, type, sample)
        self.compositor.add_layer("meta", z_index=6)
        log_debug(f"  Layer 'meta': z=6, fullscreen", "verbose")
        
        # Store art position for layer-local coordinates
        self.art_layer_offset = art_pos if art_pos else (0, 0)
        
        # =================================================================
        # COMPONENT INITIALIZATION
        # =================================================================
        
        # Create album art renderer (static for cassette)
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
                circle=False  # Cassette typically uses rectangular art
            )
            log_debug("  AlbumArtRenderer created (static)", "verbose")
        
        # Create reel renderers
        self.reel_left = None
        self.reel_right = None
        
        reel_left_file = mc_vol.get(REEL_LEFT_FILE)
        reel_left_pos = mc_vol.get(REEL_LEFT_POS)
        reel_left_center = mc_vol.get(REEL_LEFT_CENTER)
        reel_right_file = mc_vol.get(REEL_RIGHT_FILE)
        reel_right_pos = mc_vol.get(REEL_RIGHT_POS)
        reel_right_center = mc_vol.get(REEL_RIGHT_CENTER)
        reel_rpm = as_float(mc_vol.get(REEL_ROTATION_SPEED), 0.0)
        
        rot_quality = self.meter_config_volumio.get(ROTATION_QUALITY, "medium")
        rot_custom_fps = self.meter_config_volumio.get(ROTATION_FPS, 8)
        rot_fps, rot_step = get_rotation_params(rot_quality, rot_custom_fps)
        spool_left_mult = self.meter_config_volumio.get(SPOOL_LEFT_SPEED, 1.0)
        spool_right_mult = self.meter_config_volumio.get(SPOOL_RIGHT_SPEED, 1.0)
        reel_direction = mc_vol.get(REEL_DIRECTION) or self.meter_config_volumio.get(REEL_DIRECTION, "ccw")
        # SMOOTH_ROTATION: rollback remove next 2 lines
        smooth_rot_raw = self.meter_config_volumio.get(SMOOTH_ROTATION, False)
        smooth_rot = str(smooth_rot_raw).strip().lower() in ('1', 'true', 'yes') if smooth_rot_raw is not None else False
        
        log_debug("--- Reel Config ---", "verbose")
        log_debug(f"  reel.left.filename = {reel_left_file}", "verbose")
        log_debug(f"  reel.left.pos = {reel_left_pos}", "verbose")
        log_debug(f"  reel.left.center = {reel_left_center}", "verbose")
        log_debug(f"  reel.right.filename = {reel_right_file}", "verbose")
        log_debug(f"  reel.right.pos = {reel_right_pos}", "verbose")
        log_debug(f"  reel.right.center = {reel_right_center}", "verbose")
        log_debug(f"  reel.rotation.speed = {reel_rpm}", "verbose")
        log_debug(f"  reel.direction = {reel_direction} (per-meter: {mc_vol.get(REEL_DIRECTION)}, global: {self.meter_config_volumio.get(REEL_DIRECTION, 'ccw')})", "verbose")
        log_debug(f"  Computed: rot_quality={rot_quality}, rot_custom_fps={rot_custom_fps} -> rot_fps={rot_fps}, rot_step={rot_step}", "verbose")
        log_debug(f"  Computed: spool_left_mult={spool_left_mult}, spool_right_mult={spool_right_mult}", "verbose")
        
        if reel_left_file and reel_left_center:
            self.reel_left = ReelRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                filename=reel_left_file,
                pos=reel_left_pos,
                center=reel_left_center,
                rotate_rpm=reel_rpm,
                angle_step_deg=1.0,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=spool_left_mult,
                direction=reel_direction,
                name="reel_left",
                smooth_rotation=smooth_rot  # SMOOTH_ROTATION: rollback remove this kwarg
            )
            backing_rect = self.reel_left.get_backing_rect()
            visual_rect = self.reel_left.get_visual_rect()
            log_debug(f"  ReelRenderer LEFT created, backing_rect: x={backing_rect.x}, y={backing_rect.y}, w={backing_rect.width}, h={backing_rect.height}" if backing_rect else "  ReelRenderer LEFT created (no backing_rect)", "verbose")
            log_debug(f"  ReelRenderer LEFT visual_rect: x={visual_rect.x}, y={visual_rect.y}, w={visual_rect.width}, h={visual_rect.height}" if visual_rect else "  ReelRenderer LEFT visual_rect: None", "verbose")
        
        if reel_right_file and reel_right_center:
            self.reel_right = ReelRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                filename=reel_right_file,
                pos=reel_right_pos,
                center=reel_right_center,
                rotate_rpm=reel_rpm,
                angle_step_deg=1.0,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=spool_right_mult,
                direction=reel_direction,
                name="reel_right",
                smooth_rotation=smooth_rot  # SMOOTH_ROTATION: rollback remove this kwarg
            )
            backing_rect = self.reel_right.get_backing_rect()
            visual_rect = self.reel_right.get_visual_rect()
            log_debug(f"  ReelRenderer RIGHT created, backing_rect: x={backing_rect.x}, y={backing_rect.y}, w={backing_rect.width}, h={backing_rect.height}" if backing_rect else "  ReelRenderer RIGHT created (no backing_rect)", "verbose")
            log_debug(f"  ReelRenderer RIGHT visual_rect: x={visual_rect.x}, y={visual_rect.y}, w={visual_rect.width}, h={visual_rect.height}" if visual_rect else "  ReelRenderer RIGHT visual_rect: None", "verbose")
        
        # Create reels layer (Z1) based on actual reel bounding rects
        reel_left_rect = self.reel_left.get_backing_rect() if self.reel_left else None
        reel_right_rect = self.reel_right.get_backing_rect() if self.reel_right else None
        
        if reel_left_rect or reel_right_rect:
            if reel_left_rect and reel_right_rect:
                reels_region = reel_left_rect.union(reel_right_rect)
            else:
                reels_region = reel_left_rect or reel_right_rect
            self.compositor.add_layer("reels", z_index=1, region=reels_region)
            log_debug(f"  Layer 'reels': z=1, region={reels_region}", "verbose")
        else:
            self.compositor.add_layer("reels", z_index=1)
            log_debug(f"  Layer 'reels': z=1, fullscreen (no reels defined)", "verbose")
        
        # Store reel layer offset for coordinate conversion
        reels_layer = self.compositor.get_layer("reels")
        self.reels_layer_offset = reels_layer.pos if reels_layer else (0, 0)
        
        # NOTE: Meter exclusion zone no longer needed with layer composition
        # Layers prevent backing restore collisions entirely
        
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
                    meter_config=self.meter_config_volumio,
                    base_path=self.config.get(BASE_PATH),
                    meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                    fonts=fonts_dict
                )
                log_debug(f"[CassetteHandler] IndicatorRenderer created: has_indicators={self.indicator_renderer.has_indicators()}", "trace", "init")
                # Set background surface for proper transparent icon restore
                if self.bgr_surface and self.indicator_renderer.has_indicators():
                    self.indicator_renderer.set_background_surfaces(self.bgr_surface)
                    self.indicator_renderer.capture_backings(self.bgr_surface)
        except ImportError as e:
            log_debug(f"[CassetteHandler] IndicatorRenderer not available: {e}", "trace", "init")
        except Exception as e:
            print(f"[CassetteHandler] Failed to create IndicatorRenderer: {e}")
        
        # Create scrollers (no backing capture needed - layer composition handles overlaps)
        self.artist_scroller = ScrollingLabel(artist_font, artist_color, artist_pos, artist_box, center=self.center_flag, speed_px_per_sec=scroll_speed_artist) if artist_pos else None
        self.title_scroller = ScrollingLabel(title_font, title_color, title_pos, title_box, center=self.center_flag, speed_px_per_sec=scroll_speed_title) if title_pos else None
        self.album_scroller = ScrollingLabel(album_font, album_color, album_pos, album_box, center=self.center_flag, speed_px_per_sec=scroll_speed_album) if album_pos else None
        
        # LAYER COMPOSITION: Set background surface on scrollers for proper clearing
        # This eliminates backing collision artifacts when text overlaps other content
        if self.bgr_surface:
            if self.artist_scroller:
                self.artist_scroller.set_background_surface(self.bgr_surface)
                self.artist_scroller.capture_backing(self.screen)  # Still capture rect for clearing bounds
            if self.title_scroller:
                self.title_scroller.set_background_surface(self.bgr_surface)
                self.title_scroller.capture_backing(self.screen)
            if self.album_scroller:
                self.album_scroller.set_background_surface(self.bgr_surface)
                self.album_scroller.capture_backing(self.screen)
        
        # NOTE: No backing captures needed for scrollers/indicators
        # Layer composition prevents all backing restore collisions
        
        # Now run meter to show initial needle positions
        self.meter.run()
        pg.display.update()
        
        # LAYER COMPOSITION: Create rects for clearing time/type/sample areas
        # Type rect
        self.type_rect = pg.Rect(self.type_pos[0], self.type_pos[1], type_dim[0], type_dim[1]) if (self.type_pos and type_dim) else None
        
        # Time rect (for clearing from bgr_surface)
        if self.time_pos and self.fontDigi:
            time_width = self.fontDigi.size('00:00')[0] + 10
            time_height = self.fontDigi.get_linesize()
            self.time_rect = pg.Rect(self.time_pos[0], self.time_pos[1], time_width, time_height)
        else:
            self.time_rect = None
        if self.time_elapsed_pos and self.fontDigi:
            time_width = self.fontDigi.size('00:00')[0] + 10
            time_height = self.fontDigi.get_linesize()
            self.time_elapsed_rect = pg.Rect(self.time_elapsed_pos[0], self.time_elapsed_pos[1], time_width, time_height)
        else:
            self.time_elapsed_rect = None
        if self.time_total_pos and self.fontDigi:
            time_width = self.fontDigi.size('00:00')[0] + 10
            time_height = self.fontDigi.get_linesize()
            self.time_total_rect = pg.Rect(self.time_total_pos[0], self.time_total_pos[1], time_width, time_height)
        else:
            self.time_total_rect = None

        # Sample rect (for clearing from bgr_surface)
        if self.sample_pos and self.sample_box and self.sample_font:
            sample_height = self.sample_font.get_linesize()
            self.sample_rect = pg.Rect(self.sample_pos[0], self.sample_pos[1], self.sample_box, sample_height)
        else:
            self.sample_rect = None
        
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
                    log_debug(f"Foreground has {len(self.fgr_regions)} opaque regions for selective blit")
                    for i, r in enumerate(self.fgr_regions):
                        log_debug(f"  fgr region {i}: x={r.x}, y={r.y}, w={r.width}, h={r.height}")
        except Exception as e:
            print(f"[CassetteHandler] Failed to load fgr '{fgr_name}': {e}")
        
        # Store album position for artist combination logic
        self.album_pos = album_pos
        
        log_debug("--- Initialization Complete ---", "verbose")
        log_debug(f"  Renderers: album_art={'YES' if self.album_renderer else 'NO'}, reel_left={'YES' if self.reel_left else 'NO'}, reel_right={'YES' if self.reel_right else 'NO'}, indicators={'YES' if self.indicator_renderer and self.indicator_renderer.has_indicators() else 'NO'}", "verbose")
        log_debug(f"  Layers: {len(self.compositor.layers)} ({', '.join(self.compositor.layers.keys())})", "verbose")
        log_debug(f"  Foreground: {'YES' if self.fgr_surf else 'NO'} ({len(self.fgr_regions) if self.fgr_regions else 0} regions)", "verbose")
    
    def _load_fonts(self, mc_vol):
        """Load fonts from config."""
        font_path = self.meter_config_volumio.get(FONT_PATH) or ""
        
        # FIXED: Defaults match original - 30/35/40/40 not 24/24/24/24
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
        light_file = self.meter_config_volumio.get(FONT_LIGHT)
        if light_file and os.path.exists(font_path + light_file):
            self.fontL = pg.font.Font(font_path + light_file, size_light)
            log_debug(f"  Font light: loaded {font_path + light_file}", "verbose")
        else:
            self.fontL = pg.font.SysFont("DejaVuSans", size_light)
        
        # Regular font
        regular_file = self.meter_config_volumio.get(FONT_REGULAR)
        if regular_file and os.path.exists(font_path + regular_file):
            self.fontR = pg.font.Font(font_path + regular_file, size_regular)
            log_debug(f"  Font regular: loaded {font_path + regular_file}", "verbose")
        else:
            self.fontR = pg.font.SysFont("DejaVuSans", size_regular)
        
        # Bold font
        bold_file = self.meter_config_volumio.get(FONT_BOLD)
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
        base_path = self.config.get(BASE_PATH)
        meter_dir = self.config.get(SCREEN_INFO)[METER_FOLDER]
        meter_path = os.path.join(base_path, meter_dir)
        
        # FIXED: Support screen.bgr (full screen background)
        screen_bgr_name = mc.get('screen.bgr')
        bgr_name = mc.get(BGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        
        # Draw full screen background first
        if screen_bgr_name:
            try:
                img_path = os.path.join(meter_path, screen_bgr_name)
                img = pg.image.load(img_path).convert()
                self.screen.blit(img, (0, 0))
            except Exception as e:
                print(f"[CassetteHandler] Failed to load screen.bgr '{screen_bgr_name}': {e}")
        
        # Draw meter background at meter position (FIXED: convert_alpha for PNG transparency)
        if bgr_name:
            try:
                bgr_path = os.path.join(meter_path, bgr_name)
                bgr_surf = pg.image.load(bgr_path).convert_alpha()
                self.screen.blit(bgr_surf, (meter_x, meter_y))
            except Exception as e:
                print(f"[CassetteHandler] Failed to load bgr: {e}")
        
        # LAYER COMPOSITION: Store background surface for clearing
        # This is the composited background AFTER screen.bgr + bgr are drawn
        self.bgr_surface = self.screen.copy()
        log_debug("  Background surface captured for layer composition", "verbose")
    
    def render(self, meta, now_ticks):
        """
        Render one frame using layer composition.
        
        LAYER COMPOSITION ARCHITECTURE:
        1. Components render to layer surfaces (transparent)
        2. Compositor clears dirty areas from background
        3. Compositor blits layer surfaces in z-order
        4. No backing restore = no collision possible
        
        RENDER Z-ORDER:
        Z0: Background (static on screen, used for clearing)
        Z1: Reels layer
        Z2: Art layer
        --: Meters (direct to screen via meter.run())
        Z4: Text layer
        Z5: Indicators layer
        Z6: Meta layer (time/type/sample)
        Z7: Foreground mask (direct to screen)
        
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
        
        # Get queue mode from config
        queue_mode = self.meter_config_volumio.get(QUEUE_MODE, "track")
        
        # Determine which duration/progress to use
        use_queue = (queue_mode == "queue" and not volatile and 
                     meta.get("queue_progress_pct") is not None)
        
        if use_queue:
            effective_duration = meta.get("queue_duration", 0) or 0
            effective_progress_pct = meta.get("queue_progress_pct", 0.0)
            effective_time_remaining = meta.get("queue_time_remaining", 0.0)
        else:
            # Track mode (default or fallback)
            effective_duration = duration
            if duration > 0:
                seek = meta.get("seek", 0) or 0
                effective_progress_pct = (seek / 1000.0 / duration) * 100.0
                effective_time_remaining = duration - (seek / 1000.0)
            else:
                effective_progress_pct = 0.0
                effective_time_remaining = None
        
        # Pass effective progress to indicators via metadata
        # This allows progress bar to reflect queue progress when queue mode is active
        meta["_effective_progress_pct"] = effective_progress_pct
        
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
        
        # Adaptive spool speeds: dynamically adjust based on progress
        # Left spool slows down (less tape), right spool speeds up (more tape accumulated)
        spool_adaptive = self.mc_vol.get(SPOOL_ADAPTIVE)
        if spool_adaptive is None:
            spool_adaptive = self.meter_config_volumio.get(SPOOL_ADAPTIVE, False)
        
        if spool_adaptive and effective_progress_pct is not None and self.reel_left and self.reel_right:
            progress_factor = effective_progress_pct / 100.0  # 0.0 to 1.0
            base_left = self.meter_config_volumio.get(SPOOL_LEFT_SPEED, 1.0)
            base_right = self.meter_config_volumio.get(SPOOL_RIGHT_SPEED, 1.0)
            
            # Get reel direction (per-meter or global)
            reel_direction = self.mc_vol.get(REEL_DIRECTION)
            if reel_direction is None:
                reel_direction = self.meter_config_volumio.get(REEL_DIRECTION, "ccw")
            
            # Real cassette physics: tape speed over head is constant.
            # Angular velocity is inversely proportional to spool radius.
            # Larger spool (more tape) = slower spin, smaller spool = faster spin.
            #
            # CCW (tape at bottom): Left=supply (full→empty), Right=take-up (empty→full)
            #   Start (0%): left FULL (slow), right EMPTY (fast)
            #   End (100%): left EMPTY (fast), right FULL (slow)
            #
            # CW (tape at top): Reverse - left is take-up, right is supply
            #   Start (0%): left EMPTY (fast), right FULL (slow)
            #   End (100%): left FULL (slow), right EMPTY (fast)
            
            if reel_direction == "ccw":
                # CCW: left starts slow (full), ends fast (empty)
                #      right starts fast (empty), ends slow (full)
                self.reel_left.speed_multiplier = base_left * (0.5 + progress_factor)
                self.reel_right.speed_multiplier = base_right * (1.5 - progress_factor)
            else:
                # CW: left starts fast (empty), ends slow (full)
                #     right starts slow (full), ends fast (empty)
                self.reel_left.speed_multiplier = base_left * (1.5 - progress_factor)
                self.reel_right.speed_multiplier = base_right * (0.5 + progress_factor)
        
        # Pre-calculate reel state
        reel_should_spin = is_playing or volatile
        left_will_blit = self.reel_left and reel_should_spin and self.reel_left.will_blit(now_ticks)
        right_will_blit = self.reel_right and reel_should_spin and self.reel_right.will_blit(now_ticks)
        
        # CASSETTE FORCING: Force redraw when reels animate
        force_flag = left_will_blit or right_will_blit
        
        # Pre-calculate album art state
        album_url_changed = False
        if self.album_renderer:
            album_url_changed = albumart != self.album_renderer._current_url
        
        # =================================================================
        # LAYER COMPOSITION: Clear and render in z-order
        # =================================================================
        # Instead of backing restore (which causes collisions), we:
        # 1. Clear dirty regions from background surface
        # 2. Render ALL overlapping content in z-order
        # This eliminates backing collision artifacts
        
        # Collect regions that need clearing
        clear_regions = []
        
        # Reel regions need clearing when they animate
        # Use visual_rect (actual image bounds) instead of backing_rect (rotation-extended)
        # visual_rect is smaller and likely doesn't overlap meter area in center
        # Trade-off: minor rotation artifacts at corners vs meter flicker
        if left_will_blit and self.reel_left:
            rect = self.reel_left.get_visual_rect()
            if rect:
                clear_regions.append(rect)
        
        if right_will_blit and self.reel_right:
            rect = self.reel_right.get_visual_rect()
            if rect:
                clear_regions.append(rect)
        
        # Art region needs clearing when URL changes or reels force redraw
        if (force_flag or album_url_changed) and self.album_renderer:
            rect = self.album_renderer.get_backing_rect()
            if rect:
                clear_regions.append(rect)
        
        # Clear all dirty regions from background
        if clear_regions and self.bgr_surface:
            for region in clear_regions:
                # Blit from background surface to clear this region
                self.screen.blit(self.bgr_surface, region.topleft, region)
        
        # PERFORMANCE: Helper to check if component overlaps any cleared region
        # Only force redraw components that actually need it
        def overlaps_cleared(component_rect):
            if not component_rect or not clear_regions:
                return False
            for region in clear_regions:
                if region and component_rect.colliderect(region):
                    return True
            return False
        
        # =================================================================
        # RENDER ALL LAYERS IN Z-ORDER
        # =================================================================
        # After clearing, render everything that overlaps in proper z-order
        # This ensures no content is wiped by stale backing
        
        # Z1: Reels (draw BEFORE meters so meters appear on top)
        if self.reel_left and left_will_blit:
            rect = self.reel_left.render(self.screen, status, now_ticks, volatile=volatile)
            if rect:
                dirty_rects.append(rect)
        
        if self.reel_right and right_will_blit:
            rect = self.reel_right.render(self.screen, status, now_ticks, volatile=volatile)
            if rect:
                dirty_rects.append(rect)
        
        # LAYER 3: Album art (draw BEFORE meters so meters appear on top)
        if self.album_renderer:
            if album_url_changed:
                self.album_renderer.load_from_url(albumart)
            if force_flag:
                self.album_renderer.force_redraw()
            if album_url_changed or force_flag:
                rect = self.album_renderer.render(self.screen)
                if rect:
                    dirty_rects.append(rect)
        
        # LAYER 4: Meters (draw AFTER reels/art so needles are visible)
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
        
        # LAYER 5: Text fields - smart forcing based on overlap with cleared regions
        # PERFORMANCE FIX: Only force scrollers that actually overlap reel areas
        if self.artist_scroller:
            if overlaps_cleared(self.artist_scroller._backing_rect):
                self.artist_scroller.force_redraw()
        if self.title_scroller:
            if overlaps_cleared(self.title_scroller._backing_rect):
                self.title_scroller.force_redraw()
        if self.album_scroller:
            if overlaps_cleared(self.album_scroller._backing_rect):
                self.album_scroller.force_redraw()
        
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
        
        # LAYER 6: Indicators (FORCE when reels animate)
        # NOTE: skip_restore=False to properly clear transparent icons
        # - bgr_surface provides clean background for transparent icon restore
        # - Without this, transparent areas show previous icon state (ghosting)
        if self.indicator_renderer and self.indicator_renderer.has_indicators():
            self.indicator_renderer.render(self.screen, meta, dirty_rects, force=force_flag, skip_restore=False)
        
        # LAYER 7: Time remaining (FORCE when reels animate)
        if self.time_pos:
            current_time = time_module.time()
            
            # Check for persist file (countdown mode for external control)
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
                
                needs_redraw = time_str != self.last_time_str or force_flag
                
                if needs_redraw:
                    self.last_time_str = time_str
                    
                    # LAYER COMPOSITION: Clear from bgr_surface
                    if self.bgr_surface and self.time_rect:
                        self.screen.blit(self.bgr_surface, self.time_rect.topleft, self.time_rect)
                        dirty_rects.append(self.time_rect.copy())
                    
                    # Color: orange for persist countdown, red for <10s, else skin color
                    if show_persist_countdown:
                        t_color = (242, 165, 0)  # Orange
                    elif 0 < display_sec <= 10:
                        t_color = (242, 0, 0)  # Red
                    else:
                        t_color = self.time_color
                    
                    self.last_time_surf = self.fontDigi.render(time_str, True, t_color)
                    self.screen.blit(self.last_time_surf, self.time_pos)
                    
                    if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("time", False):
                        log_debug(f"[Time] OUTPUT: rendered '{time_str}' at {self.time_pos}, color={t_color}", "trace", "time")

        # LAYER 7b: Elapsed time (when time.elapsed.pos set, anti-collision: force redraw when reels overlap)
        if self.time_elapsed_pos and self.fontDigi:
            seek_ms = meta.get("seek") or 0
            elapsed_sec = max(0, int(seek_ms) // 1000)
            elapsed_str = f"{elapsed_sec // 60:02d}:{elapsed_sec % 60:02d}"
            needs_redraw = (
                elapsed_str != self.last_elapsed_str or force_flag or
                (self.time_elapsed_rect and overlaps_cleared(self.time_elapsed_rect))
            )
            if needs_redraw:
                self.last_elapsed_str = elapsed_str
                if self.bgr_surface and self.time_elapsed_rect:
                    self.screen.blit(self.bgr_surface, self.time_elapsed_rect.topleft, self.time_elapsed_rect)
                    dirty_rects.append(self.time_elapsed_rect.copy())
                surf = self.fontDigi.render(elapsed_str, True, self.time_elapsed_color)
                self.screen.blit(surf, self.time_elapsed_pos)

        # LAYER 7c: Total time (when time.total.pos set, anti-collision: force redraw when reels overlap)
        if self.time_total_pos and self.fontDigi:
            duration_sec = max(0, int(meta.get("duration") or 0))
            total_str = f"{duration_sec // 60:02d}:{duration_sec % 60:02d}"
            needs_redraw = (
                total_str != self.last_total_str or force_flag or
                (self.time_total_rect and overlaps_cleared(self.time_total_rect))
            )
            if needs_redraw:
                self.last_total_str = total_str
                if self.bgr_surface and self.time_total_rect:
                    self.screen.blit(self.bgr_surface, self.time_total_rect.topleft, self.time_total_rect)
                    dirty_rects.append(self.time_total_rect.copy())
                surf = self.fontDigi.render(total_str, True, self.time_total_color)
                self.screen.blit(surf, self.time_total_pos)

        # LAYER 8: Sample rate / format icon
        # PERFORMANCE FIX: Separate format CHANGE (expensive) from force BLIT (cheap)
        # Profiler showed 46% CPU wasted reloading/scaling/colorizing icon every frame
        if self.type_rect:
            fmt = (track_type or "").strip().lower().replace(" ", "_")
            if fmt == "dsf":
                fmt = "dsd"
            
            # Strip signal strength indicators and other suffixes
            # DAB sends "DAB ●◦◦◦◦" -> "dab_●◦◦◦◦", need just "dab"
            # FM sends "FM ◦◦◦◦◦" -> "fm_◦◦◦◦◦", need just "fm"
            import re
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
            
            # Only reload icon when format actually changes (once per track)
            format_changed = fmt != self.last_track_type
            
            if format_changed:
                self.last_track_type = fmt
                self.last_format_icon_surf = None  # Clear cache
                
                # Check for icon file
                file_path = os.path.dirname(__file__)
                local_icons = {'tidal', 'cd', 'qobuz', 'dab', 'fm', 'radio'}
                if fmt in local_icons:
                    icon_path = os.path.join(file_path, 'format-icons', f"{fmt}.svg")
                else:
                    icon_path = f"/volumio/http/www3/app/assets-common/format-icons/{fmt}.svg"
                
                if not os.path.exists(icon_path):
                    # Render text fallback
                    if self.sample_font and fmt:
                        self.last_format_icon_surf = self.sample_font.render(fmt[:4], True, self.type_color)
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
                            img = img.convert_alpha()
                            set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                            self.last_format_icon_surf = img
                        elif CAIROSVG_AVAILABLE and PIL_AVAILABLE:
                            png_bytes = cairosvg.svg2png(url=icon_path, 
                                                          output_width=self.type_rect.width,
                                                          output_height=self.type_rect.height)
                            pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                            img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                            img = img.convert_alpha()
                            set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                            self.last_format_icon_surf = img
                    except Exception as e:
                        print(f"[FormatIcon] error: {e}")
            
            # Blit cached icon when format changed OR when force_flag (reel overlap)
            if (format_changed or force_flag) and self.last_format_icon_surf:
                # Clear from bgr_surface
                if self.bgr_surface:
                    self.screen.blit(self.bgr_surface, self.type_rect.topleft, self.type_rect)
                
                # Center and blit cached icon
                dx = self.type_rect.x + (self.type_rect.width - self.last_format_icon_surf.get_width()) // 2
                dy = self.type_rect.y + (self.type_rect.height - self.last_format_icon_surf.get_height()) // 2
                self.screen.blit(self.last_format_icon_surf, (dx, dy))
                dirty_rects.append(self.type_rect.copy())
        
        # Sample rate
        if self.sample_pos and self.sample_box:
            sample_text = f"{samplerate} {bitdepth}".strip()
            if not sample_text:
                sample_text = bitrate.strip() if bitrate else ""
            
            needs_redraw = sample_text and (sample_text != self.last_sample_text or force_flag)
            
            if needs_redraw:
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
        
        # LAYER 9: Foreground mask
        if self.fgr_surf and dirty_rects:
            fgr_x, fgr_y = self.fgr_pos
            if self.fgr_regions:
                for region in self.fgr_regions:
                    screen_rect = region.move(fgr_x, fgr_y)
                    for dirty in dirty_rects:
                        if screen_rect.colliderect(dirty):
                            self.screen.blit(self.fgr_surf, screen_rect.topleft, region)
                            break
            else:
                self.screen.blit(self.fgr_surf, self.fgr_pos)
        
        # Performance: meter timing delay for audio buffer accumulation
        # Prevents render loop from spinning too fast when reels animate
        if self.meter_delay_sec > 0:
            time_module.sleep(self.meter_delay_sec)
        
        return dirty_rects
    
    def cleanup(self):
        """Release resources on shutdown."""
        log_debug("CassetteHandler cleanup", "basic")
        self.reel_left = None
        self.reel_right = None
        self.album_renderer = None
        self.indicator_renderer = None
        self.artist_scroller = None
        self.title_scroller = None
        self.album_scroller = None
        self.bgr_surface = None
        if self.compositor:
            self.compositor.cleanup()
            self.compositor = None
