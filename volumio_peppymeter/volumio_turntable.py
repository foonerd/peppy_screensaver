# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Turntable Handler - Self-contained module for turntable skin rendering
#
# This file is part of PeppyMeter for Volumio
#
# SKIN TYPE: TURNTABLE
# - HAS: vinyl (required), tonearm (optional), rotating album art
# - NO: reel_left, reel_right (cassette elements)
# - ARCHITECTURE: Layer composition (no backing restore collisions)
#
# EDGE CASE: Single reel + tonearm = treat reel as vinyl
# (Early skin developers mistakenly used reel parameters for turntable vinyl)
#
# This module is intentionally self-contained with duplicated components
# to eliminate dead code paths and reduce CPU overhead.

import os
import io
import math
import time
import requests
import pygame as pg

try:
    from PIL import Image, ImageOps, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# =============================================================================
# Configuration Constants (turntable-specific subset)
# =============================================================================
from configfileparser import (
    SCREEN_INFO, WIDTH, HEIGHT, FRAME_RATE, BASE_PATH, METER_FOLDER,
    BGR_FILENAME, FGR_FILENAME
)

from volumio_configfileparser import (
    EXTENDED_CONF,
    ROTATION_QUALITY, ROTATION_FPS, ROTATION_SPEED, SMOOTH_ROTATION,  # SMOOTH_ROTATION: rollback remove from import
    REEL_DIRECTION, QUEUE_MODE,
    FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD,
    ALBUMART_POS, ALBUMART_DIM, ALBUMART_MSK, ALBUMBORDER,
    ALBUMART_ROT, ALBUMART_ROT_SPEED,
    PLAY_TXT_CENTER, PLAY_CENTER, PLAY_MAX,
    SCROLLING_SPEED_ARTIST, SCROLLING_SPEED_TITLE, SCROLLING_SPEED_ALBUM,
    PLAY_TITLE_POS, PLAY_TITLE_COLOR, PLAY_TITLE_MAX, PLAY_TITLE_STYLE,
    PLAY_ARTIST_POS, PLAY_ARTIST_COLOR, PLAY_ARTIST_MAX, PLAY_ARTIST_STYLE,
    PLAY_ALBUM_POS, PLAY_ALBUM_COLOR, PLAY_ALBUM_MAX, PLAY_ALBUM_STYLE,
    PLAY_NEXT_TITLE_POS, PLAY_NEXT_TITLE_COLOR, PLAY_NEXT_TITLE_MAX, PLAY_NEXT_TITLE_STYLE,
    PLAY_NEXT_ARTIST_POS, PLAY_NEXT_ARTIST_COLOR, PLAY_NEXT_ARTIST_MAX, PLAY_NEXT_ARTIST_STYLE,
    PLAY_NEXT_ALBUM_POS, PLAY_NEXT_ALBUM_COLOR, PLAY_NEXT_ALBUM_MAX, PLAY_NEXT_ALBUM_STYLE,
    PLAY_TYPE_POS, PLAY_TYPE_COLOR, PLAY_TYPE_DIM,
    PLAY_SAMPLE_POS, PLAY_SAMPLE_STYLE, PLAY_SAMPLE_MAX,
    TIME_REMAINING_POS, TIMECOLOR,
    TIME_ELAPSED_POS, TIME_ELAPSED_COLOR, TIME_TOTAL_POS, TIME_TOTAL_COLOR,
    FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_DIGI, FONTCOLOR,
    FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_L,
    METER_DELAY
)

# Vinyl configuration constants
try:
    from volumio_configfileparser import (
        VINYL_FILE, VINYL_POS, VINYL_CENTER, VINYL_DIRECTION
    )
except ImportError:
    VINYL_FILE = "vinyl.filename"
    VINYL_POS = "vinyl.pos"
    VINYL_CENTER = "vinyl.center"
    VINYL_DIRECTION = "vinyl.direction"

# Reel configuration constants (for edge case: single reel + tonearm)
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

# Tonearm configuration constants
try:
    from volumio_configfileparser import (
        TONEARM_FILE, TONEARM_PIVOT_SCREEN, TONEARM_PIVOT_IMAGE,
        TONEARM_ANGLE_REST, TONEARM_ANGLE_START, TONEARM_ANGLE_END,
        TONEARM_DROP_DURATION, TONEARM_LIFT_DURATION
    )
except ImportError:
    TONEARM_FILE = "tonearm.filename"
    TONEARM_PIVOT_SCREEN = "tonearm.pivot.screen"
    TONEARM_PIVOT_IMAGE = "tonearm.pivot.image"
    TONEARM_ANGLE_REST = "tonearm.angle.rest"
    TONEARM_ANGLE_START = "tonearm.angle.start"
    TONEARM_ANGLE_END = "tonearm.angle.end"
    TONEARM_DROP_DURATION = "tonearm.drop.duration"
    TONEARM_LIFT_DURATION = "tonearm.lift.duration"

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


def init_turntable_debug(level, trace_dict):
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
    """Recolor a surface to the specified color while preserving alpha.
    
    Used for format icons which are white SVGs that need to match skin color.
    Attempts fast numpy method first, falls back to per-pixel if needed.
    
    :param surface: pygame.Surface with per-pixel alpha
    :param color: pygame.Color or RGB tuple
    """
    try:
        # Try numpy-accelerated method first (much faster)
        import numpy as np
        arr = pg.surfarray.pixels3d(surface)
        arr[:, :, 0] = color.r
        arr[:, :, 1] = color.g
        arr[:, :, 2] = color.b
        del arr  # Release surface lock
        return
    except Exception:
        pass
    
    # Fallback to per-pixel method (slower but always works)
    try:
        width, height = surface.get_size()
        for x in range(width):
            for y in range(height):
                pixel = surface.get_at((x, y))
                if len(pixel) >= 4 and pixel[3] > 0:  # Has alpha and is visible
                    surface.set_at((x, y), (color.r, color.g, color.b, pixel[3]))
    except Exception as e:
        print(f"[set_color] Failed: {e}")


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
        """Set background surface for layer composition clearing."""
        self._bgr_surface = bgr_surface

    def capture_backing(self, surface):
        """Capture backing surface for this label's area.
        
        OPTIMIZED: When _bgr_surface is set, captures from it instead of screen.
        This ensures backing contains only static background for fast clearing
        without collision artifacts.
        """
        if not self.pos or self.box_width <= 0:
            return
        x, y = self.pos
        height = self.font.get_linesize()
        self._backing_rect = pg.Rect(x, y, self.box_width, height)
        
        # Use bgr_surface if available (pure static bg), otherwise use passed surface
        source = self._bgr_surface if self._bgr_surface else surface
        
        try:
            self._backing = source.subsurface(self._backing_rect).copy()
        except Exception:
            self._backing = pg.Surface((self._backing_rect.width, self._backing_rect.height))
            self._backing.fill((0, 0, 0))
        
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] CAPTURE: pos={self.pos}, box_w={self.box_width}, backing_rect={self._backing_rect}", "trace", "scrolling")

    def update_text(self, new_text):
        """Update text content, reset scroll position if changed."""
        new_text = new_text or ""
        if new_text == self.text and self.surf is not None:
            return False
        self.text = new_text
        self.surf = self.font.render(self.text, True, self.color)
        self.text_w, self.text_h = self.surf.get_size()
        self.offset = 0.0
        self.direction = 1
        self._pause_until = 0
        self._last_time = pg.time.get_ticks()
        self._needs_redraw = True
        self._last_draw_offset = -1
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] UPDATE: text='{new_text[:30]}', text_w={self.text_w}, box_w={self.box_width}, scrolls={self.text_w > self.box_width}", "trace", "scrolling")
        return True

    def force_redraw(self):
        """Force redraw on next draw() call."""
        self._needs_redraw = True
        self._last_draw_offset = -1
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] FORCE: text='{self.text[:20]}...', pos={self.pos}", "trace", "scrolling")

    def get_rect(self):
        """Get bounding rectangle for this scroller.
        
        Used for overlap detection in surgical force logic.
        Returns the backing rect if captured, otherwise computes from position.
        """
        if self._backing_rect:
            return self._backing_rect
        if self.pos and self.box_width > 0 and self.font:
            height = self.font.get_linesize()
            return pg.Rect(self.pos[0], self.pos[1], self.box_width, height)
        return None

    def draw(self, surface):
        """Draw label, handling scroll animation with self-backing.
        Returns dirty rect if drawn, None if skipped.
        
        OPTIMIZED: Backing is captured from bgr_surface (pure static bg),
        so we just use the small backing for fast clearing without collision.
        """
        if not self.surf or not self.pos or self.box_width <= 0:
            return None
        
        x, y = self.pos
        box_rect = pg.Rect(x, y, self.box_width, self.text_h)
        
        # Text fits - no scrolling needed
        if self.text_w <= self.box_width:
            if not self._needs_redraw:
                return None
            
            # OPTIMIZED: Use small backing (captured from bgr_surface = pure static bg)
            if self._backing and self._backing_rect:
                surface.blit(self._backing, self._backing_rect.topleft)
            
            if self.center and self.box_width > 0:
                left = box_rect.x + (self.box_width - self.text_w) // 2
                surface.blit(self.surf, (left, box_rect.y))
            else:
                surface.blit(self.surf, (box_rect.x, box_rect.y))
            self._needs_redraw = False
            
            dirty = self._backing_rect.copy() if self._backing_rect else box_rect.copy()
            if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
                log_debug(f"[Scrolling] OUTPUT: static, dirty_rect={dirty}", "trace", "scrolling")
            return dirty
        
        # Scrolling text
        now = pg.time.get_ticks()
        dt = (now - self._last_time) / 1000.0
        self._last_time = now
        
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
        
        current_offset_int = int(self.offset)
        if current_offset_int == self._last_draw_offset and not self._needs_redraw:
            return None
        
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] SCROLL: text='{self.text[:20]}...', offset={current_offset_int}, forced={self._needs_redraw}, backing={self._backing_rect}", "trace", "scrolling")
        
        # OPTIMIZED: Use small backing (captured from bgr_surface = pure static bg)
        if self._backing and self._backing_rect:
            surface.blit(self._backing, self._backing_rect.topleft)
        
        prev_clip = surface.get_clip()
        surface.set_clip(box_rect)
        draw_x = box_rect.x - current_offset_int
        surface.blit(self.surf, (draw_x, box_rect.y))
        surface.set_clip(prev_clip)
        
        self._last_draw_offset = current_offset_int
        self._needs_redraw = False
        
        dirty = self._backing_rect.copy() if self._backing_rect else box_rect.copy()
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("scrolling", False):
            log_debug(f"[Scrolling] OUTPUT: dirty_rect={dirty}", "trace", "scrolling")
        return dirty


# =============================================================================
# AlbumArtRenderer - TURNTABLE VERSION (with rotation support)
# =============================================================================
class AlbumArtRenderer:
    """
    Handles album art loading with optional mask, scaling, and rotation.
    TURNTABLE VERSION: Supports rotation for LP-style spinning effect.
    Can be coupled to VinylRenderer for unified rotation angle.
    
    COMPOSITE MODE: When coupled to vinyl with rotation enabled, art is
    composited directly onto vinyl surface. They rotate as one unit (like
    a real LP with label), halving per-frame blit count.
    """

    def __init__(self, base_path, meter_folder, art_pos, art_dim, screen_size,
                 font_color=(255, 255, 255), border_width=0,
                 mask_filename=None, rotate_enabled=False, rotate_rpm=0.0,
                 angle_step_deg=0.5, spindle_radius=5, ring_radius=None,
                 circle=True, rotation_fps=8, rotation_step=6, speed_multiplier=1.0,
                 vinyl_renderer=None, smooth_rotation=False):  # SMOOTH_ROTATION: rollback remove param
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.art_pos = art_pos
        self.art_dim = art_dim
        self.screen_size = screen_size
        self.font_color = font_color
        self.border_width = border_width
        self.mask_filename = mask_filename
        self.rotate_enabled = bool(rotate_enabled)
        self.rotate_rpm = float(rotate_rpm) * float(speed_multiplier)
        self.angle_step_deg = float(angle_step_deg)
        self.spindle_radius = max(1, int(spindle_radius))
        self.ring_radius = ring_radius or max(3, min(art_dim[0], art_dim[1]) // 10)
        self.circle = bool(circle)
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)

        # Vinyl coupling (for unified rotation)
        self.vinyl_renderer = vinyl_renderer
        self._is_composited = False  # True when art is baked into vinyl surface

        # Derived center
        self.art_center = (int(art_pos[0] + art_dim[0] // 2),
                           int(art_pos[1] + art_dim[1] // 2)) if (art_pos and art_dim) else None

        # Runtime cache
        self._requests = requests.Session()
        self._current_url = None
        self._scaled_surf = None
        self._rot_frames = None
        self._current_angle = 0.0
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._need_first_blit = False
        # SMOOTH_ROTATION: rollback remove next 2 lines
        self._smooth_rotation = str(smooth_rotation).strip().lower() in ('1', 'true', 'yes') if isinstance(smooth_rotation, str) else bool(smooth_rotation)

        # Mask path
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
        """Fetch image from URL, build scaled surface, pre-compute rotation frames.
        
        COMPOSITE MODE: If coupled to vinyl with rotation enabled, composites
        art directly onto vinyl surface instead of precomputing separate frames.
        """
        self._current_url = url
        self._scaled_surf = None
        self._rot_frames = None
        self._current_angle = 0.0
        self._needs_redraw = True
        self._need_first_blit = False
        self._is_composited = False

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
                
                # COMPOSITE MODE: If coupled to vinyl and rotation enabled,
                # composite art onto vinyl surface (like real LP with label)
                if self.vinyl_renderer and self.rotate_enabled and self.rotate_rpm > 0.0:
                    if self.vinyl_renderer.composite_album_art(self._scaled_surf, self.art_dim):
                        self._is_composited = True
                        self._rot_frames = None  # Don't need separate frames
                        log_debug("[AlbumArt] Composited onto vinyl - will skip separate blit", "basic")
                    else:
                        # Fallback to separate rotation frames
                        self._is_composited = False
                        if USE_PRECOMPUTED_FRAMES and self._scaled_surf:
                            try:
                                self._rot_frames = [
                                    pg.transform.rotate(self._scaled_surf, -a)
                                    for a in range(0, 360, self.rotation_step)
                                ]
                            except Exception:
                                self._rot_frames = None
                else:
                    # Not coupled or not rotating - use separate frames
                    self._is_composited = False
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
            pass

    def _update_angle(self, status, now_ticks, volatile=False):
        """Update rotation angle based on RPM and playback status."""
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
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
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0
            if getattr(self, '_smooth_rotation', False):
                self._last_blit_tick = now_ticks

    def check_pending_load(self):
        """Compatibility stub - sync loading has no pending loads."""
        return False

    def will_blit(self, now_ticks):
        """Check if rotation blit is needed (FPS gating)."""
        if self._scaled_surf is None:
            return False
        if self._need_first_blit:
            return True
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        # SMOOTH_ROTATION: rollback remove next 2 lines
        if getattr(self, '_smooth_rotation', False) and self.rotate_enabled and self.rotate_rpm > 0.0:
            return True

        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms

    def get_backing_rect(self):
        """Get backing rect for this renderer, extended for rotation if needed."""
        if not self.art_pos or not self.art_dim:
            return None
        
        if self.rotate_enabled and self.rotate_rpm > 0.0:
            diag = int(max(self.art_dim[0], self.art_dim[1]) * math.sqrt(2)) + 2
            center_x = self.art_pos[0] + self.art_dim[0] // 2
            center_y = self.art_pos[1] + self.art_dim[1] // 2
            ext_x = max(0, center_x - diag // 2)
            ext_y = max(0, center_y - diag // 2)
            ext_w = min(diag, self.screen_size[0] - ext_x)
            ext_h = min(diag, self.screen_size[1] - ext_y)
            return pg.Rect(ext_x, ext_y, ext_w, ext_h)
        else:
            return pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

    def get_visual_rect(self):
        """Get visual bounding rectangle (actual image extent, not rotation-extended).
        
        LAYER COMPOSITION: Used for clearing - returns actual art dimensions
        regardless of rotation state.
        """
        if not self.art_pos or not self.art_dim:
            return None
        return pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

    def render(self, screen, status, now_ticks, advance_angle=True, volatile=False):
        """Render album art (rotated if enabled) plus border and LP center markers.
        
        :param advance_angle: if False, render at current angle without advancing rotation
        :param volatile: if True, ignore stop/pause (track transition in progress)
        
        COMPOSITE MODE: If art is composited onto vinyl, skip the main blit
        (vinyl already has art baked in). Still draw border and spindle markers.
        """
        if not self.art_pos or not self.art_dim or not self._scaled_surf:
            return None

        # COMPOSITE MODE: Art is already baked into vinyl surface
        # Skip blitting art, but still draw decorations (border, spindle)
        if self._is_composited:
            dirty_rect = pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])
            
            # Border
            if self.border_width:
                try:
                    if self.circle and self.art_center:
                        rad = min(self.art_dim[0], self.art_dim[1]) // 2
                        pg.draw.circle(screen, self.font_color, self.art_center, rad, self.border_width)
                    else:
                        pg.draw.rect(screen, self.font_color, pg.Rect(self.art_pos, self.art_dim), self.border_width)
                except Exception:
                    pass
            
            # LP center markers (spindle + inner ring)
            if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0:
                try:
                    pg.draw.circle(screen, self.font_color, self.art_center, self.spindle_radius, 0)
                    pg.draw.circle(screen, self.font_color, self.art_center, self.ring_radius, 1)
                except Exception:
                    pass
            
            return dirty_rect

        # NORMAL MODE: Render art separately
        if advance_angle and not self.will_blit(now_ticks):
            return None

        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
            coupled = f"coupled_to_vinyl={self.vinyl_renderer is not None}" if self.rotate_enabled else "static"
            log_debug(f"[AlbumArt] INPUT: status={status}, angle={self._current_angle:.1f}, advance={advance_angle}, {coupled}", "trace", "albumart")

        dirty_rect = None
        if advance_angle:
            self._last_blit_tick = now_ticks

        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0:
            if advance_angle:
                # If coupled to vinyl, use vinyl's angle
                if self.vinyl_renderer:
                    self._current_angle = self.vinyl_renderer.get_current_angle()
                else:
                    self._update_angle(status, now_ticks, volatile=volatile)
            
            # Use pre-computed frame lookup if available
            if self._rot_frames:
                idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
                rot = self._rot_frames[idx]
            else:
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
            screen.blit(self._scaled_surf, self.art_pos)
            dirty_rect = pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

        self._needs_redraw = False
        self._need_first_blit = False

        # Border
        if self.border_width and dirty_rect:
            try:
                if self.circle and self.art_center:
                    rad = min(self.art_dim[0], self.art_dim[1]) // 2
                    pg.draw.circle(screen, self.font_color, self.art_center, rad, self.border_width)
                else:
                    pg.draw.rect(screen, self.font_color, pg.Rect(self.art_pos, self.art_dim), self.border_width)
            except Exception:
                pass

        # LP center markers (spindle + inner ring)
        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0 and dirty_rect:
            try:
                pg.draw.circle(screen, self.font_color, self.art_center, self.spindle_radius, 0)
                pg.draw.circle(screen, self.font_color, self.art_center, self.ring_radius, 1)
            except Exception:
                pass

        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("albumart", False):
            mode = "rotating" if (self.rotate_enabled and self.rotate_rpm > 0.0) else "static"
            log_debug(f"[AlbumArt] OUTPUT: {mode}, angle={self._current_angle:.1f}, rect={dirty_rect}", "trace", "albumart")

        return dirty_rect

    def force_redraw(self):
        """Force redraw on next render() call."""
        self._needs_redraw = True
    
    def is_composited(self):
        """Return True if art is composited onto vinyl (no separate blit needed)."""
        return self._is_composited


# =============================================================================
# VinylRenderer - Rotating vinyl disc for turntable skins
# =============================================================================
class VinylRenderer:
    """
    Handles vinyl disc graphics with rotation for turntable-style skins.
    Renders UNDER album art. Album art can lock to vinyl's rotation angle.
    
    COMPOSITE MODE: When album art is coupled, art is composited directly onto
    vinyl surface and they rotate as a single unit (like a real LP with label).
    This halves the blit count per frame.
    """

    def __init__(self, base_path, meter_folder, filename, pos, center,
                 rotate_rpm=0.0, rotation_fps=8, rotation_step=6,
                 speed_multiplier=1.0, direction="cw", smooth_rotation=False):  # SMOOTH_ROTATION: rollback remove param
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pos = pos
        self.center = center
        self.rotate_rpm = abs(float(rotate_rpm) * float(speed_multiplier))
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)
        self.direction_mult = 1 if direction == "cw" else -1
        
        self._base_surf = None      # Original vinyl (without art) - kept for recompositing
        self._original_surf = None  # Current surface (may have art composited)
        self._rot_frames = None
        self._current_angle = 0.0
        self._loaded = False
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, self.rotation_fps))
        self._needs_redraw = True
        self._need_first_blit = False
        self._has_composited_art = False  # True when album art is baked into vinyl
        # SMOOTH_ROTATION: rollback remove next 2 lines
        self._smooth_rotation = str(smooth_rotation).strip().lower() in ('1', 'true', 'yes') if isinstance(smooth_rotation, str) else bool(smooth_rotation)
        
        self._load_image()
    
    def _load_image(self):
        """Load the vinyl PNG file and pre-compute rotation frames."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if os.path.exists(img_path):
                self._base_surf = pg.image.load(img_path).convert_alpha()
                self._original_surf = self._base_surf.copy()  # Start with copy of base
                self._loaded = True
                self._need_first_blit = True
                self._has_composited_art = False
                
                self._regenerate_rotation_frames()
            else:
                print(f"[VinylRenderer] File not found: {img_path}")
        except Exception as e:
            print(f"[VinylRenderer] Failed to load '{self.filename}': {e}")
    
    def _regenerate_rotation_frames(self):
        """Regenerate precomputed rotation frames from current _original_surf."""
        self._rot_frames = None
        if USE_PRECOMPUTED_FRAMES and self.center and self.rotate_rpm > 0.0 and self._original_surf:
            try:
                self._rot_frames = [
                    pg.transform.rotate(self._original_surf, -a)
                    for a in range(0, 360, self.rotation_step)
                ]
                log_debug(f"[VinylRenderer] Regenerated {len(self._rot_frames)} rotation frames", "verbose")
            except Exception as e:
                log_debug(f"[VinylRenderer] Failed to regenerate frames: {e}", "basic")
                self._rot_frames = None
    
    def composite_album_art(self, art_surf, art_dim):
        """Composite album art onto vinyl surface center.
        
        This creates a single surface with vinyl + art that rotates as one unit,
        like a real LP with its label. Halves the per-frame blit count.
        
        :param art_surf: Scaled album art surface (with transparency if circular)
        :param art_dim: (width, height) of the album art
        :return: True if composite successful, False otherwise
        """
        if not self._base_surf or not art_surf:
            return False
        
        try:
            # Start fresh from base vinyl (in case art changed)
            self._original_surf = self._base_surf.copy()
            
            # Calculate position to center art on vinyl
            vinyl_w = self._original_surf.get_width()
            vinyl_h = self._original_surf.get_height()
            art_w, art_h = art_dim
            
            # Art goes in center of vinyl
            art_x = (vinyl_w - art_w) // 2
            art_y = (vinyl_h - art_h) // 2
            
            # Blit art onto vinyl
            self._original_surf.blit(art_surf, (art_x, art_y))
            
            # Regenerate rotation frames with composited surface
            self._regenerate_rotation_frames()
            
            self._has_composited_art = True
            self._needs_redraw = True
            self._need_first_blit = True
            
            log_debug(f"[VinylRenderer] Composited album art ({art_w}x{art_h}) onto vinyl ({vinyl_w}x{vinyl_h})", "basic")
            return True
            
        except Exception as e:
            log_debug(f"[VinylRenderer] Failed to composite album art: {e}", "basic")
            self._has_composited_art = False
            return False
    
    def has_composited_art(self):
        """Return True if album art is composited onto this vinyl."""
        return self._has_composited_art
    
    def _update_angle(self, status, now_ticks, volatile=False, decel_factor=1.0):
        """Update rotation angle based on RPM, direction, and playback status.
        
        :param decel_factor: 1.0 = full speed, 0.0 = stopped (for deceleration)
        """
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if volatile and status in ("stop", "pause"):
            status = "play"
        if status == "play" or decel_factor > 0.0:
            # SMOOTH_ROTATION: rollback replace block with: dt = self._blit_interval_ms / 1000.0
            if getattr(self, '_smooth_rotation', False) and self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                dt = min(max(dt, 0.0), 0.5)
            else:
                dt = self._blit_interval_ms / 1000.0
            effective_rpm = self.rotate_rpm * decel_factor
            self._current_angle = (self._current_angle + effective_rpm * 6.0 * dt * self.direction_mult) % 360.0
            if getattr(self, '_smooth_rotation', False):
                self._last_blit_tick = now_ticks
    
    def get_current_angle(self):
        """Return current rotation angle (for album art coupling)."""
        return self._current_angle
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating)."""
        if not self._loaded or not self._original_surf:
            return False
        if self._need_first_blit:
            return True
        if not self.center or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        # SMOOTH_ROTATION: rollback remove next 2 lines
        if getattr(self, '_smooth_rotation', False) and self.rotate_rpm > 0.0:
            return True
        
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
    
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
        """Get visual bounding rectangle (actual image extent, not rotation-extended).
        
        LAYER COMPOSITION: Used for clearing - smaller than backing_rect,
        avoids wiping meter areas that live between rotating elements.
        """
        if not self._original_surf or not self.center:
            return None
        
        w = self._original_surf.get_width()
        h = self._original_surf.get_height()
        
        # Visual rect centered on rotation pivot
        x = self.center[0] - w // 2
        y = self.center[1] - h // 2
        
        return pg.Rect(x, y, w, h)
    
    def render(self, screen, status, now_ticks, volatile=False, force=False, decel_factor=1.0, advance_angle=True):
        """Render the vinyl disc (rotated if playing).
        
        :param force: If True, bypass will_blit timing check
        :param decel_factor: 1.0 = full speed, 0.0 = stopped (for deceleration)
        :param advance_angle: If True, advance rotation angle. If False, render at current angle.
                             Use False when forced to redraw due to overlapping elements.
        Returns dirty rect if drawn, None if skipped."""
        if not self._loaded or not self._original_surf:
            return None
        
        if not force and not self.will_blit(now_ticks):
            return None
        
        log_debug(f"[Vinyl] RENDER: status={status}, angle={self._current_angle:.1f}, decel={decel_factor:.2f}, advance={advance_angle}", "trace", "vinyl")
        
        # Only update timing when advancing (so forced redraws don't reset FPS schedule). SMOOTH_ROTATION: skip when smooth (set in _update_angle)
        if advance_angle and not getattr(self, '_smooth_rotation', False):
            self._last_blit_tick = now_ticks
        
        if not self.center:
            screen.blit(self._original_surf, self.pos)
            self._needs_redraw = False
            self._need_first_blit = False
            return pg.Rect(self.pos[0], self.pos[1],
                          self._original_surf.get_width(),
                          self._original_surf.get_height())
        
        # Only advance angle when requested (prevents speed increase on forced redraws)
        if advance_angle:
            self._update_angle(status, now_ticks, volatile=volatile, decel_factor=decel_factor)
        
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
        
        return self.get_backing_rect()


# =============================================================================
# TonearmRenderer - Tonearm animation based on track progress
# =============================================================================
TONEARM_STATE_REST = "rest"
TONEARM_STATE_DROP = "drop"
TONEARM_STATE_TRACKING = "tracking"
TONEARM_STATE_LIFT = "lift"


class TonearmRenderer:
    """
    Renders a tonearm that tracks playback progress.
    Pivots around a fixed point and sweeps from outer groove to inner groove.
    Drop and lift animations provide realistic arm movement.
    """
    
    def __init__(self, base_path, meter_folder, filename,
                 pivot_screen, pivot_image,
                 angle_rest, angle_start, angle_end,
                 drop_duration=1.5, lift_duration=1.0,
                 rotation_fps=30):
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
        self._pending_drop_target = None
        self._last_update_time = 0
        self._early_lift = False
        
        self._last_blit_rect = None
        self._last_backing = None
        
        # Layer composition: capture backing from bgr_surface (pure static bg)
        self._bgr_surface = None
        
        self._exclusion_zones = []
        self._exclusion_min_x = 9999
        
        self._arm_length = 0
        
        # Precomputed rotation frames for CPU optimization
        self._rot_frames = {}
        self._rot_step = 0.5  # Degree step for precomputed frames
        
        self._load_image()
    
    def set_exclusion_zones(self, zones):
        """Set rectangles that should be excluded from backing restore."""
        self._exclusion_zones = zones if zones else []
        if self._exclusion_zones:
            self._exclusion_min_x = min(z.left for z in self._exclusion_zones)
        else:
            self._exclusion_min_x = 9999
    
    def set_background_surface(self, bgr_surface):
        """Set background surface for layer composition.
        
        When set, backing is captured from this surface (pure static bg)
        instead of screen, preventing collision with dynamic elements.
        """
        self._bgr_surface = bgr_surface
    
    def get_last_blit_rect(self):
        """Return the last blit rect for overlap checking."""
        return self._last_blit_rect
    
    def is_animating(self):
        """Return True if tonearm is in DROP or LIFT animation."""
        return self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT)
    
    def _load_image(self):
        """Load the tonearm PNG file and precompute rotation frames."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if os.path.exists(img_path):
                self._original_surf = pg.image.load(img_path).convert_alpha()
                self._loaded = True
                self._needs_redraw = True
                
                w = self._original_surf.get_width()
                h = self._original_surf.get_height()
                px, py = self.pivot_image
                
                corners = [(0, 0), (w, 0), (0, h), (w, h)]
                self._arm_length = max(
                    math.sqrt((cx - px)**2 + (cy - py)**2)
                    for cx, cy in corners
                )
                
                # Precompute rotation frames for CPU optimization
                # Range covers: rest -> start -> end (all tonearm positions)
                if USE_PRECOMPUTED_FRAMES:
                    angle_min = min(self.angle_rest, self.angle_start, self.angle_end) - 1.0
                    angle_max = max(self.angle_rest, self.angle_start, self.angle_end) + 1.0
                    
                    angle = angle_min
                    frame_count = 0
                    while angle <= angle_max:
                        key = round(angle / self._rot_step) * self._rot_step
                        if key not in self._rot_frames:
                            try:
                                self._rot_frames[key] = pg.transform.rotate(self._original_surf, angle)
                                frame_count += 1
                            except Exception:
                                pass
                        angle += self._rot_step
                    
                    log_debug(f"[TonearmRenderer] Loaded '{self.filename}', arm_length={self._arm_length:.1f}, precomputed {frame_count} frames")
                else:
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
        
        # Ease-out for natural arm movement
        eased = 1 - (1 - progress) ** 2
        
        self._current_angle = (
            self._animation_start_angle + 
            (self._animation_end_angle - self._animation_start_angle) * eased
        )
        
        return progress >= 1.0
    
    def update(self, status, progress_pct, time_remaining_sec=None):
        """Update tonearm state based on playback status and progress."""
        if not self._loaded:
            return False
        
        now = time.time()
        
        # Freeze detection
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._last_update_time > 0:
                gap_sec = now - self._last_update_time
                if gap_sec > 0.3:
                    remaining_angle = abs(self._animation_end_angle - self._current_angle)
                    total_angle = abs(self._animation_end_angle - self._animation_start_angle)
                    if total_angle > 0.1:
                        remaining_pct = remaining_angle / total_angle
                        remaining_duration = self._animation_duration * remaining_pct
                        if remaining_duration > 0.05:
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
                progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                if self._early_lift and progress_pct > 10.0:
                    return self._needs_redraw
                
                self._early_lift = False
                target_angle = (
                    self.angle_start + 
                    (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                )
                log_debug(f"[Tonearm] REST->DROP: progress={progress_pct:.1f}%", "trace", "tonearm")
                self._state = TONEARM_STATE_DROP
                self._start_animation(target_angle, self.drop_duration)
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_DROP:
            if status != "play":
                log_debug(f"[Tonearm] DROP->LIFT: playback stopped", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._early_lift = False
                self._start_animation(self.angle_rest, self.lift_duration)
            else:
                if self._update_animation():
                    progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                    sync_angle = (
                        self.angle_start + 
                        (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                    )
                    log_debug(f"[Tonearm] DROP->TRACKING: sync_angle={sync_angle:.1f}", "trace", "tonearm")
                    self._current_angle = sync_angle
                    self._state = TONEARM_STATE_TRACKING
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_TRACKING:
            # Early lift for end-of-track
            if time_remaining_sec is not None and time_remaining_sec < 1.5 and time_remaining_sec > 0:
                log_debug(f"[Tonearm] TRACKING->LIFT: early lift", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._pending_drop_target = None
                self._early_lift = True
                self._start_animation(self.angle_rest, self.lift_duration)
                self._needs_redraw = True
                self._last_blit_tick = 0
            elif status != "play":
                log_debug(f"[Tonearm] TRACKING->LIFT: playback stopped", "trace", "tonearm")
                self._state = TONEARM_STATE_LIFT
                self._pending_drop_target = None
                self._early_lift = False
                self._start_animation(self.angle_rest, self.lift_duration)
                self._needs_redraw = True
                self._last_blit_tick = 0
            else:
                progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                target_angle = (
                    self.angle_start + 
                    (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                )
                
                # Detect large jump (track change, seek)
                if abs(target_angle - self._current_angle) > 2.0:
                    log_debug(f"[Tonearm] TRACKING->LIFT: jump detected", "trace", "tonearm")
                    self._state = TONEARM_STATE_LIFT
                    self._pending_drop_target = target_angle
                    self._early_lift = False
                    self._start_animation(self.angle_rest, self.lift_duration)
                    self._needs_redraw = True
                    self._last_blit_tick = 0
                elif abs(target_angle - self._current_angle) > 0.2:
                    self._current_angle = target_angle
                    self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_LIFT:
            if self._update_animation():
                if self._early_lift:
                    log_debug("[Tonearm] LIFT->REST: early lift complete", "trace", "tonearm")
                    self._state = TONEARM_STATE_REST
                    self._pending_drop_target = None
                elif self._pending_drop_target is not None:
                    log_debug(f"[Tonearm] LIFT->DROP: pending target", "trace", "tonearm")
                    self._state = TONEARM_STATE_DROP
                    self._start_animation(self._pending_drop_target, self.drop_duration)
                    self._pending_drop_target = None
                elif status == "play":
                    progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                    target_angle = (
                        self.angle_start + 
                        (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                    )
                    log_debug(f"[Tonearm] LIFT->DROP: using progress", "trace", "tonearm")
                    self._state = TONEARM_STATE_DROP
                    self._start_animation(target_angle, self.drop_duration)
                else:
                    log_debug(f"[Tonearm] LIFT->REST: not playing", "trace", "tonearm")
                    self._state = TONEARM_STATE_REST
                    self._pending_drop_target = None
            self._needs_redraw = True
        
        return self._needs_redraw
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating + state check)."""
        if not self._loaded or not self._original_surf:
            return False
        
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._needs_redraw:
                return True
            return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
        
        if self._state == TONEARM_STATE_TRACKING:
            if self._needs_redraw:
                return True
            tracking_interval = 500
            return (now_ticks - self._last_blit_tick) >= tracking_interval
        
        if self._needs_redraw:
            return True
        
        return False
    
    def get_backing_rect(self):
        """Get bounding rectangle for backing surface (full sweep area)."""
        if not self._original_surf or not self.pivot_screen:
            return None
        
        px, py = self.pivot_screen
        arm_len = self._arm_length + 4
        
        min_angle = min(self.angle_rest, self.angle_start, self.angle_end)
        max_angle = max(self.angle_rest, self.angle_start, self.angle_end)
        
        points = []
        for angle in range(int(min_angle), int(max_angle) + 1, 5):
            rad = math.radians(angle)
            x = px + arm_len * math.cos(rad)
            y = py - arm_len * math.sin(rad)
            points.append((x, y))
        
        points.append((px, py))
        
        if not points:
            return None
        
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        
        px_img, py_img = self.pivot_image
        img_h = self._original_surf.get_height()
        counterweight_len = px_img
        arm_thickness = max(py_img, img_h - py_img)
        padding = max(counterweight_len, arm_thickness) + 5
        
        return pg.Rect(
            int(min_x - padding),
            int(min_y - padding),
            int(max_x - min_x + 2 * padding),
            int(max_y - min_y + 2 * padding)
        )
    
    def restore_backing(self, screen):
        """Restore backing from previous frame's tonearm position."""
        if self._last_backing is None or self._last_blit_rect is None:
            return None
        
        log_debug(f"[Tonearm] RESTORE: rect={self._last_blit_rect}, state={self._state}", "trace", "tonearm")
        
        if not self._exclusion_zones or self._state == TONEARM_STATE_TRACKING:
            screen.blit(self._last_backing, self._last_blit_rect.topleft)
            return self._last_blit_rect.copy()
        
        br = self._last_blit_rect
        overlaps = []
        for zone in self._exclusion_zones:
            if br.colliderect(zone):
                overlaps.append(br.clip(zone))
        
        if not overlaps:
            screen.blit(self._last_backing, self._last_blit_rect.topleft)
            return self._last_blit_rect.copy()
        
        # Chunk-based restore around exclusions
        ex_left = min(o.left for o in overlaps)
        ex_right = max(o.right for o in overlaps)
        ex_top = min(o.top for o in overlaps)
        ex_bottom = max(o.bottom for o in overlaps)
        
        bx, by = br.topleft
        bw, bh = br.size
        
        # Above exclusion zones
        if ex_top > by:
            h = ex_top - by
            src_rect = pg.Rect(0, 0, bw, h)
            screen.blit(self._last_backing, (bx, by), src_rect)
        
        # Below exclusion zones
        if ex_bottom < by + bh:
            h = (by + bh) - ex_bottom
            local_y = ex_bottom - by
            src_rect = pg.Rect(0, local_y, bw, h)
            screen.blit(self._last_backing, (bx, ex_bottom), src_rect)
        
        # Left of exclusion zones
        if ex_left > bx:
            w = ex_left - bx
            h = ex_bottom - ex_top
            local_y = ex_top - by
            src_rect = pg.Rect(0, local_y, w, h)
            screen.blit(self._last_backing, (bx, ex_top), src_rect)
        
        # Right of exclusion zones
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
        """Render the tonearm at current angle."""
        if not self._loaded or not self._original_surf:
            return None
        
        if not force and not self.will_blit(now_ticks):
            return None
        
        # Freeze detection
        actual_now = pg.time.get_ticks()
        if self._state in (TONEARM_STATE_DROP, TONEARM_STATE_LIFT):
            if self._last_blit_tick > 0:
                gap_ms = actual_now - self._last_blit_tick
                if gap_ms > 300:
                    remaining_angle = abs(self._animation_end_angle - self._current_angle)
                    total_angle = abs(self._animation_end_angle - self._animation_start_angle)
                    if total_angle > 0.1:
                        remaining_pct = remaining_angle / total_angle
                        remaining_duration = self._animation_duration * remaining_pct
                        if remaining_duration > 0.1:
                            self._animation_start_time = time.time()
                            self._animation_start_angle = self._current_angle
                            self._animation_duration = remaining_duration
                            log_debug(f"[Tonearm] Freeze detected ({gap_ms}ms)", "trace", "tonearm")
        
        self._last_blit_tick = actual_now
        
        # Skip if angle unchanged (TRACKING state only)
        if not force and not self._needs_redraw and self._state == TONEARM_STATE_TRACKING:
            if self._last_drawn_angle is not None:
                if abs(self._current_angle - self._last_drawn_angle) < 0.1:
                    return None
        
        # Rotate around pivot point - use precomputed frame if available
        frame_key = round(self._current_angle / self._rot_step) * self._rot_step
        if frame_key in self._rot_frames:
            rotated = self._rot_frames[frame_key]
        else:
            # Fallback to real-time rotation
            rotated = pg.transform.rotate(self._original_surf, self._current_angle)
        
        px, py = self.pivot_image
        img_w = self._original_surf.get_width()
        img_h = self._original_surf.get_height()
        
        cx, cy = img_w / 2, img_h / 2
        dx, dy = px - cx, py - cy
        
        rad = math.radians(-self._current_angle)
        new_dx = dx * math.cos(rad) - dy * math.sin(rad)
        new_dy = dx * math.sin(rad) + dy * math.cos(rad)
        
        rot_w = rotated.get_width()
        rot_h = rotated.get_height()
        rot_cx, rot_cy = rot_w / 2, rot_h / 2
        rot_px = rot_cx + new_dx
        rot_py = rot_cy + new_dy
        
        scr_px, scr_py = self.pivot_screen
        blit_x = int(scr_px - rot_px)
        blit_y = int(scr_py - rot_py)
        blit_rect = pg.Rect(blit_x, blit_y, rot_w, rot_h)
        
        # Capture backing BEFORE drawing tonearm
        # LAYER COMPOSITION: Use bgr_surface (pure static bg) to avoid
        # capturing dynamic elements like meter needles
        capture_source = self._bgr_surface if self._bgr_surface else screen
        source_rect = capture_source.get_rect()
        clipped_rect = blit_rect.clip(source_rect)
        if clipped_rect.width > 0 and clipped_rect.height > 0:
            try:
                self._last_backing = capture_source.subsurface(clipped_rect).copy()
                self._last_blit_rect = clipped_rect
            except Exception:
                self._last_backing = None
                self._last_blit_rect = None
        
        screen.blit(rotated, (blit_x, blit_y))
        
        log_debug(f"[Tonearm] RENDER: angle={self._current_angle:.1f}, rect={blit_rect}", "trace", "tonearm")
        
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
# TurntableHandler - Main handler class for turntable skins
# =============================================================================
class TurntableHandler:
    """
    Handler for turntable skin type.
    
    RENDER Z-ORDER:
    1. bgr (static background - already on screen)
    2. Restore vinyl backing (if vinyl will blit)
    3. Restore art backing (if vinyl will blit)
    4. Restore tonearm backing
    5. meters (meter.run())
    6. vinyl (rotating disc)
    7. album art (rotating, on vinyl)
    8. text fields (NO forcing needed)
    9. tonearm (animated, tracks progress)
    10. indicators (NO forcing needed)
    11. time remaining
    12. sample/icon
    13. fgr (foreground mask)
    
    FORCING BEHAVIOR:
    - NO forcing needed (tonearm does not overlap text areas)
    
    EDGE CASE:
    - Single reel + tonearm = treat reel as vinyl
    """
    
    def __init__(self, screen, meter, config, meter_config, meter_config_volumio):
        """
        Initialize turntable handler.
        
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
        self.dirty_rects = []
        
        # Performance: meter timing delay (configurable, affects CPU usage)
        # Higher values = lower CPU but meters may feel sluggish
        # Lower values = higher CPU but more responsive meters
        self.meter_delay_ms = max(0, min(20, self.global_config.get(METER_DELAY, 10)))
        self.meter_delay_sec = self.meter_delay_ms / 1000.0  # Convert to seconds for time.sleep()
        
        # Background surface for layer composition
        self.bgr_surface = None
        
        # Deceleration/spindown state - vinyl slows down during tonearm lift
        self._decel_start = None  # Timestamp when deceleration started (tonearm lift began)
        self._decel_duration = 1.5  # Default - will be set from tonearm lift_duration
        self._was_playing = False  # Track playback state changes
        self._was_tonearm_animating = False  # Track tonearm animation state changes
        
        # Renderers (turntable-specific)
        self.vinyl_renderer = None
        self.tonearm_renderer = None
        self.album_renderer = None
        self.indicator_renderer = None
        
        # Scrollers
        self.artist_scroller = None
        self.title_scroller = None
        self.album_scroller = None
        self.next_title_scroller = None
        self.next_artist_scroller = None
        self.next_album_scroller = None

        # Positions and fonts
        self.time_pos = None
        self.sample_pos = None
        self.type_pos = None
        self.type_rect = None
        self.time_rect = None
        self.sample_rect = None
        self.art_rect = None  # For overlap detection
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
        
        # Caches
        self.last_time_str = ""
        self.last_elapsed_str = ""
        self.last_total_str = ""
        self.last_time_surf = None
        self.last_sample_text = ""
        self.last_sample_surf = None
        self.last_track_type = ""
        self.last_format_icon_surf = None
        
        log_debug("TurntableHandler initialized", "basic")
    
    def init_for_meter(self, meter_name):
        """Initialize handler for a specific meter."""
        mc = self.config.get(meter_name, {}) if meter_name else {}
        mc_vol = self.global_config.get(meter_name, {}) if meter_name else {}
        self.mc_vol = mc_vol
        
        log_debug(f"=== TurntableHandler: Initializing meter: {meter_name} ===", "basic")
        if DEBUG_LEVEL_CURRENT == "trace" and DEBUG_TRACE.get("init", False):
            log_debug(f"[Init] TurntableHandler: meter={meter_name}, extended={mc_vol.get(EXTENDED_CONF, False)}", "trace", "init")
        
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
            # Skin mode: per-field from skin -> global from skin -> 40
            scroll_speed_artist = mc_vol.get(SCROLLING_SPEED_ARTIST, 40)
            scroll_speed_title = mc_vol.get(SCROLLING_SPEED_TITLE, 40)
            scroll_speed_album = mc_vol.get(SCROLLING_SPEED_ALBUM, 40)
        
        log_debug(f"Scrolling: mode={scrolling_mode}, artist={scroll_speed_artist}, title={scroll_speed_title}, album={scroll_speed_album}")
        
        artist_pos = mc_vol.get(PLAY_ARTIST_POS)
        title_pos = mc_vol.get(PLAY_TITLE_POS)
        album_pos = mc_vol.get(PLAY_ALBUM_POS)
        next_title_pos = mc_vol.get(PLAY_NEXT_TITLE_POS)
        next_artist_pos = mc_vol.get(PLAY_NEXT_ARTIST_POS)
        next_album_pos = mc_vol.get(PLAY_NEXT_ALBUM_POS)
        self.time_pos = mc_vol.get(TIME_REMAINING_POS)
        self.time_elapsed_pos = mc_vol.get(TIME_ELAPSED_POS)
        self.time_total_pos = mc_vol.get(TIME_TOTAL_POS)
        self.sample_pos = mc_vol.get(PLAY_SAMPLE_POS)
        self.type_pos = mc_vol.get(PLAY_TYPE_POS)
        type_dim = mc_vol.get(PLAY_TYPE_DIM)
        art_pos = mc_vol.get(ALBUMART_POS)
        art_dim = mc_vol.get(ALBUMART_DIM)
        
        # Styles
        artist_style = mc_vol.get(PLAY_ARTIST_STYLE, FONT_STYLE_L)
        title_style = mc_vol.get(PLAY_TITLE_STYLE, FONT_STYLE_B)
        album_style = mc_vol.get(PLAY_ALBUM_STYLE, FONT_STYLE_L)
        next_title_style = mc_vol.get(PLAY_NEXT_TITLE_STYLE, FONT_STYLE_R)
        next_artist_style = mc_vol.get(PLAY_NEXT_ARTIST_STYLE, FONT_STYLE_R)
        next_album_style = mc_vol.get(PLAY_NEXT_ALBUM_STYLE, FONT_STYLE_R)
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
        next_title_color = sanitize_color(mc_vol.get(PLAY_NEXT_TITLE_COLOR), self.font_color)
        next_artist_color = sanitize_color(mc_vol.get(PLAY_NEXT_ARTIST_COLOR), self.font_color)
        next_album_color = sanitize_color(mc_vol.get(PLAY_NEXT_ALBUM_COLOR), self.font_color)
        self.time_color = sanitize_color(mc_vol.get(TIMECOLOR), self.font_color)
        self.time_elapsed_color = sanitize_color(mc_vol.get(TIME_ELAPSED_COLOR), self.time_color)
        self.time_total_color = sanitize_color(mc_vol.get(TIME_TOTAL_COLOR), self.time_color)
        self.type_color = sanitize_color(mc_vol.get(PLAY_TYPE_COLOR), self.font_color)
        
        # Max widths
        artist_max = as_int(mc_vol.get(PLAY_ARTIST_MAX), 0)
        title_max = as_int(mc_vol.get(PLAY_TITLE_MAX), 0)
        album_max = as_int(mc_vol.get(PLAY_ALBUM_MAX), 0)
        next_title_max = as_int(mc_vol.get(PLAY_NEXT_TITLE_MAX), 0)
        next_artist_max = as_int(mc_vol.get(PLAY_NEXT_ARTIST_MAX), 0)
        next_album_max = as_int(mc_vol.get(PLAY_NEXT_ALBUM_MAX), 0)
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
        next_title_box = get_box_width(next_title_pos, next_title_max)
        next_artist_box = get_box_width(next_artist_pos, next_artist_max)
        next_album_box = get_box_width(next_album_pos, next_album_max)

        if self.sample_pos and (global_max or sample_max):
            if sample_max:
                self.sample_box = sample_max
            else:
                self.sample_box = self.sample_font.size('-44.1 kHz 24 bit-')[0]
        else:
            self.sample_box = 0
        
        # LAYER COMPOSITION: No backing capture needed - all clearing uses bgr_surface
        
        # Store art_rect for reference
        self.art_rect = pg.Rect(art_pos[0], art_pos[1], art_dim[0], art_dim[1]) if (art_pos and art_dim) else None
        
        # Get rotation parameters
        rot_quality = self.global_config.get(ROTATION_QUALITY, "medium")
        rot_custom_fps = self.global_config.get(ROTATION_FPS, 8)
        rot_fps, rot_step = get_rotation_params(rot_quality, rot_custom_fps)
        rot_speed_mult = self.global_config.get(ROTATION_SPEED, 1.0)
        # SMOOTH_ROTATION: rollback remove next 2 lines
        smooth_rot_raw = self.global_config.get(SMOOTH_ROTATION, False)
        smooth_rot = str(smooth_rot_raw).strip().lower() in ('1', 'true', 'yes') if smooth_rot_raw is not None else False
        
        # Vinyl configuration - check for standard vinyl OR single reel edge case
        vinyl_file = mc_vol.get(VINYL_FILE)
        vinyl_pos = mc_vol.get(VINYL_POS)
        vinyl_center = mc_vol.get(VINYL_CENTER)
        vinyl_direction = mc_vol.get(VINYL_DIRECTION) or self.global_config.get(REEL_DIRECTION, "cw")
        vinyl_rpm = as_float(mc_vol.get(ALBUMART_ROT_SPEED), 0.0)
        
        # EDGE CASE: Single reel + tonearm = treat reel as vinyl
        # Check if we have tonearm but no vinyl, and single reel
        tonearm_file = mc_vol.get(TONEARM_FILE)
        has_tonearm = bool(tonearm_file and mc_vol.get(TONEARM_PIVOT_SCREEN) and mc_vol.get(TONEARM_PIVOT_IMAGE))
        
        if not vinyl_file and has_tonearm:
            # Check for single reel config - use as vinyl substitute
            reel_left_file = mc_vol.get(REEL_LEFT_FILE)
            reel_left_center = mc_vol.get(REEL_LEFT_CENTER)
            reel_right_file = mc_vol.get(REEL_RIGHT_FILE)
            reel_right_center = mc_vol.get(REEL_RIGHT_CENTER)
            
            # Use left reel if present, else right reel
            if reel_left_file and reel_left_center:
                vinyl_file = reel_left_file
                vinyl_pos = mc_vol.get(REEL_LEFT_POS)
                vinyl_center = reel_left_center
                log_debug("  EDGE CASE: Using reel.left as vinyl substitute", "verbose")
            elif reel_right_file and reel_right_center:
                vinyl_file = reel_right_file
                vinyl_pos = mc_vol.get(REEL_RIGHT_POS)
                vinyl_center = reel_right_center
                log_debug("  EDGE CASE: Using reel.right as vinyl substitute", "verbose")
            
            # Use reel rotation speed if vinyl speed not set
            if vinyl_rpm <= 0.0:
                reel_rpm = as_float(mc_vol.get(REEL_ROTATION_SPEED), 0.0)
                if reel_rpm > 0.0:
                    vinyl_rpm = reel_rpm
                    log_debug(f"  EDGE CASE: Using reel.rotation.speed={vinyl_rpm} for vinyl", "verbose")
        
        log_debug(f"  Vinyl config: file={vinyl_file}, center={vinyl_center}, rpm={vinyl_rpm}", "verbose")
        
        # Create vinyl renderer
        self.vinyl_renderer = None
        if vinyl_file and vinyl_center:
            self.vinyl_renderer = VinylRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                filename=vinyl_file,
                pos=vinyl_pos,
                center=vinyl_center,
                rotate_rpm=vinyl_rpm,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=rot_speed_mult,
                direction=vinyl_direction,
                smooth_rotation=smooth_rot  # SMOOTH_ROTATION: rollback remove this kwarg
            )
            log_debug(f"  VinylRenderer created", "verbose")
        
        # Create album art renderer (with rotation support)
        self.album_renderer = None
        if art_pos and art_dim:
            rotate_enabled = mc_vol.get(ALBUMART_ROT, False)
            rotate_rpm = as_float(mc_vol.get(ALBUMART_ROT_SPEED), 0.0)
            screen_size = (self.SCREEN_WIDTH, self.SCREEN_HEIGHT)
            
            self.album_renderer = AlbumArtRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
                art_pos=art_pos,
                art_dim=art_dim,
                screen_size=screen_size,
                font_color=self.font_color,
                border_width=mc_vol.get(ALBUMBORDER) or 0,
                mask_filename=mc_vol.get(ALBUMART_MSK),
                rotate_enabled=rotate_enabled,
                rotate_rpm=rotate_rpm,
                angle_step_deg=0.5,
                spindle_radius=5,
                ring_radius=max(3, min(art_dim[0], art_dim[1]) // 10),
                circle=rotate_enabled,
                rotation_fps=rot_fps,
                rotation_step=rot_step,
                speed_multiplier=rot_speed_mult,
                smooth_rotation=smooth_rot  # SMOOTH_ROTATION: rollback remove this kwarg
            )
            
            # Couple album art to vinyl if rotation enabled
            if self.album_renderer.rotate_enabled and self.vinyl_renderer:
                self.album_renderer.vinyl_renderer = self.vinyl_renderer
                log_debug("  Album art coupled to vinyl rotation", "verbose")
            
            log_debug(f"  AlbumArtRenderer created (rotate={rotate_enabled})", "verbose")
        
        # Create tonearm renderer
        self.tonearm_renderer = None
        tonearm_pivot_screen = mc_vol.get(TONEARM_PIVOT_SCREEN)
        tonearm_pivot_image = mc_vol.get(TONEARM_PIVOT_IMAGE)
        
        if tonearm_file and tonearm_pivot_screen and tonearm_pivot_image:
            self.tonearm_renderer = TonearmRenderer(
                base_path=self.config.get(BASE_PATH),
                meter_folder=self.config.get(SCREEN_INFO)[METER_FOLDER],
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
            log_debug(f"  TonearmRenderer created", "verbose")
        
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
            print(f"[TurntableHandler] Failed to create IndicatorRenderer: {e}")
        
        # Create scrollers
        self.artist_scroller = ScrollingLabel(artist_font, artist_color, artist_pos, artist_box, center=self.center_flag, speed_px_per_sec=scroll_speed_artist) if artist_pos else None
        self.title_scroller = ScrollingLabel(title_font, title_color, title_pos, title_box, center=self.center_flag, speed_px_per_sec=scroll_speed_title) if title_pos else None
        self.album_scroller = ScrollingLabel(album_font, album_color, album_pos, album_box, center=self.center_flag, speed_px_per_sec=scroll_speed_album) if album_pos else None
        self.next_title_scroller = ScrollingLabel(self._font_for_style(next_title_style), next_title_color, next_title_pos, next_title_box, center=self.center_flag, speed_px_per_sec=scroll_speed_title) if next_title_pos else None
        self.next_artist_scroller = ScrollingLabel(self._font_for_style(next_artist_style), next_artist_color, next_artist_pos, next_artist_box, center=self.center_flag, speed_px_per_sec=scroll_speed_artist) if next_artist_pos else None
        self.next_album_scroller = ScrollingLabel(self._font_for_style(next_album_style), next_album_color, next_album_pos, next_album_box, center=self.center_flag, speed_px_per_sec=scroll_speed_album) if next_album_pos else None

        # LAYER COMPOSITION: Set background surface on scrollers for proper clearing
        if self.bgr_surface:
            if self.artist_scroller:
                self.artist_scroller.set_background_surface(self.bgr_surface)
                self.artist_scroller.capture_backing(self.screen)
            if self.title_scroller:
                self.title_scroller.set_background_surface(self.bgr_surface)
                self.title_scroller.capture_backing(self.screen)
            if self.album_scroller:
                self.album_scroller.set_background_surface(self.bgr_surface)
                self.album_scroller.capture_backing(self.screen)
            if self.next_title_scroller:
                self.next_title_scroller.set_background_surface(self.bgr_surface)
                self.next_title_scroller.capture_backing(self.screen)
            if self.next_artist_scroller:
                self.next_artist_scroller.set_background_surface(self.bgr_surface)
                self.next_artist_scroller.capture_backing(self.screen)
            if self.next_album_scroller:
                self.next_album_scroller.set_background_surface(self.bgr_surface)
                self.next_album_scroller.capture_backing(self.screen)
            # Tonearm also needs bgr_surface to avoid capturing meter needles
            if self.tonearm_renderer:
                self.tonearm_renderer.set_background_surface(self.bgr_surface)
            # LAYER COMPOSITION: Indicators capture backing from bgr_surface (pure static bg)
            # This ensures restore_backing doesn't restore stale meter/tonearm positions
            if self.indicator_renderer and self.indicator_renderer.has_indicators():
                self.indicator_renderer.set_background_surfaces(self.bgr_surface)
                self.indicator_renderer.capture_backings(self.bgr_surface)
        else:
            # Fallback to old backing capture if no bgr_surface
            if self.artist_scroller:
                self.artist_scroller.capture_backing(self.screen)
            if self.title_scroller:
                self.title_scroller.capture_backing(self.screen)
            if self.album_scroller:
                self.album_scroller.capture_backing(self.screen)
            if self.next_title_scroller:
                self.next_title_scroller.capture_backing(self.screen)
            if self.next_artist_scroller:
                self.next_artist_scroller.capture_backing(self.screen)
            if self.next_album_scroller:
                self.next_album_scroller.capture_backing(self.screen)
            # Indicators fallback
            if self.indicator_renderer and self.indicator_renderer.has_indicators():
                self.indicator_renderer.capture_backings(self.screen)
        
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
        
        # ANTI-COLLISION: No exclusion zones - layer composition handles all overlaps
        # via bgr_surface clearing and z-order rendering
        
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
        except Exception as e:
            print(f"[TurntableHandler] Failed to load fgr '{fgr_name}': {e}")
        
        # Store album position for artist combination logic
        self.album_pos = album_pos
        
        log_debug("=== TurntableHandler: Initialization complete ===", "basic")
    
    def _load_fonts(self, mc_vol):
        """Load fonts from config."""
        font_path = self.global_config.get(FONT_PATH, "")
        
        size_light = as_int(mc_vol.get(FONTSIZE_LIGHT), 30)
        size_regular = as_int(mc_vol.get(FONTSIZE_REGULAR), 35)
        size_bold = as_int(mc_vol.get(FONTSIZE_BOLD), 40)
        size_digi = as_int(mc_vol.get(FONTSIZE_DIGI), 40)
        
        # Light font
        light_file = self.global_config.get(FONT_LIGHT)
        if light_file and os.path.exists(font_path + light_file):
            self.fontL = pg.font.Font(font_path + light_file, size_light)
        else:
            self.fontL = pg.font.SysFont("DejaVuSans", size_light)
        
        # Regular font
        regular_file = self.global_config.get(FONT_REGULAR)
        if regular_file and os.path.exists(font_path + regular_file):
            self.fontR = pg.font.Font(font_path + regular_file, size_regular)
        else:
            self.fontR = pg.font.SysFont("DejaVuSans", size_regular)
        
        # Bold font
        bold_file = self.global_config.get(FONT_BOLD)
        if bold_file and os.path.exists(font_path + bold_file):
            self.fontB = pg.font.Font(font_path + bold_file, size_bold)
        else:
            self.fontB = pg.font.SysFont("DejaVuSans", size_bold, bold=True)
        
        # Digital font for time
        digi_path = os.path.join(os.path.dirname(__file__), 'fonts', 'DSEG7Classic-Italic.ttf')
        if os.path.exists(digi_path):
            self.fontDigi = pg.font.Font(digi_path, size_digi)
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
        """Draw static background assets."""
        base_path = self.config.get(BASE_PATH)
        meter_dir = self.config.get(SCREEN_INFO)[METER_FOLDER]
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
                self.screen.blit(img, (0, 0))
            except Exception as e:
                print(f"[TurntableHandler] Failed to load screen.bgr '{screen_bgr_name}': {e}")
        
        # Draw meter background at meter position (convert_alpha for PNG transparency)
        if bgr_name:
            try:
                img_path = os.path.join(meter_path, bgr_name)
                img = pg.image.load(img_path).convert_alpha()
                self.screen.blit(img, (meter_x, meter_y))
            except Exception as e:
                print(f"[TurntableHandler] Failed to load bgr '{bgr_name}': {e}")
        
        # LAYER COMPOSITION: Store background surface for clearing
        self.bgr_surface = self.screen.copy()
        log_debug("  Background surface captured for layer composition", "verbose")
    
    def render(self, meta, now_ticks):
        """
        Render one frame using LAYER COMPOSITION (anti-collision).
        
        LAYER COMPOSITION PATTERN:
        1. Determine what needs updating (vinyl, art, tonearm, etc.)
        2. Clear dirty regions from bgr_surface (NOT backing restore)
        3. Render ALL components in z-order:
           - Vinyl (bottom)
           - Album art
           - Meters (run by peppymeter library)
           - Text scrollers
           - Tonearm
           - Indicators
           - Time/Sample/Type
           - Foreground (top)
        
        ANTI-COLLISION: Uses visual_rect for clearing (smaller than backing_rect)
        to avoid wiping meter areas. No exclusion zones needed.
        
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
        queue_mode = self.global_config.get(QUEUE_MODE, "track")
        
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
        
        # Pre-calculate tonearm state
        tonearm_will_render = False
        tonearm_is_animating = False
        if self.tonearm_renderer:
            if effective_duration > 0:
                self.tonearm_renderer.update(status, effective_progress_pct, effective_time_remaining)
            else:
                self.tonearm_renderer.update(status, 0.0, None)
            tonearm_will_render = self.tonearm_renderer.will_blit(now_ticks)
            tonearm_is_animating = self.tonearm_renderer.is_animating()
        
        # =================================================================
        # DECELERATION: Vinyl slows down gradually when playback stops
        # =================================================================
        # Detect playback state change
        just_stopped = self._was_playing and not is_playing
        just_started = not self._was_playing and is_playing
        self._was_playing = is_playing
        
        # Start deceleration when playback stops
        if just_stopped:
            self._decel_start = time.time()
            # Get lift duration from tonearm for matching deceleration
            if self.tonearm_renderer:
                self._decel_duration = getattr(self.tonearm_renderer, 'lift_duration', 1.5)
            else:
                self._decel_duration = 1.5
        
        # Clear deceleration when playback resumes
        if just_started:
            self._decel_start = None
        
        # Detect when tonearm transitions from animating to rest (for final clear)
        just_reached_rest = self._was_tonearm_animating and not tonearm_is_animating
        self._was_tonearm_animating = tonearm_is_animating
        
        # Calculate deceleration factor
        decel_factor = 1.0
        in_deceleration = False
        if self._decel_start is not None:
            elapsed = time.time() - self._decel_start
            if elapsed < self._decel_duration:
                # Smooth deceleration curve (ease out)
                progress = elapsed / self._decel_duration
                decel_factor = max(0.0, 1.0 - progress * progress)  # Quadratic ease out
                in_deceleration = True
            else:
                # Deceleration complete
                decel_factor = 0.0
                # Only clear decel_start when tonearm also at rest
                if not tonearm_is_animating:
                    self._decel_start = None
        
        # Pre-calculate vinyl state
        # Spin when: playing, volatile, or in deceleration
        vinyl_should_spin = is_playing or volatile or in_deceleration or tonearm_is_animating
        vinyl_will_blit = self.vinyl_renderer and vinyl_should_spin and self.vinyl_renderer.will_blit(now_ticks)
        
        # Pre-calculate album art state
        album_will_render = False
        album_url_changed = False
        if self.album_renderer:
            album_url_changed = albumart != self.album_renderer._current_url
            if album_url_changed:
                album_will_render = True
            elif self.album_renderer.rotate_enabled and self.album_renderer.rotate_rpm > 0.0:
                # Rotating art follows same deceleration logic as vinyl
                album_should_rotate = is_playing or volatile or in_deceleration or tonearm_is_animating
                album_will_render = album_should_rotate and self.album_renderer.will_blit(now_ticks)
        
        # =================================================================
        # FORCE FLAG: When animated elements change, force overlapping 
        # components to redraw (anti-collision pattern from CassetteHandler)
        # =================================================================
        # Include: tonearm animating, just_reached_rest (transition frame needs final clear)
        force_flag = vinyl_will_blit or album_will_render or tonearm_will_render or tonearm_is_animating or just_reached_rest
        
        # =================================================================
        # PHASE 1: LAYER COMPOSITION - Clear dirty regions from bgr_surface
        # =================================================================
        # ANTI-COLLISION: Use visual_rect (actual image bounds) not backing_rect
        # (diagonal-extended). This prevents wiping meter areas.
        
        clear_regions = []
        
        # Vinyl region - clear when spinning OR when force_flag (will render with force)
        if (vinyl_will_blit or force_flag) and self.vinyl_renderer:
            rect = self.vinyl_renderer.get_visual_rect()
            if rect:
                clear_regions.append(rect)
        
        # Art region - use visual_rect
        if (album_will_render or album_url_changed or force_flag) and self.album_renderer:
            rect = self.album_renderer.get_visual_rect()
            if rect:
                clear_regions.append(rect)
        
        # Tonearm region - clear LAST position from bgr_surface (not restore_backing)
        # This clears to pure static background, then overlapping components redraw
        if self.tonearm_renderer:
            last_rect = getattr(self.tonearm_renderer, '_last_blit_rect', None)
            if last_rect and force_flag:
                clear_regions.append(last_rect)
        
        # Clear all dirty regions from background
        if clear_regions and self.bgr_surface:
            for region in clear_regions:
                self.screen.blit(self.bgr_surface, region.topleft, region)
                dirty_rects.append(region.copy())
        
        # =================================================================
        # PHASE 2: RENDER ALL LAYERS IN Z-ORDER
        # =================================================================
        # After clearing, render everything that overlaps in proper z-order
        # Force overlapping components when animated elements change
        
        # Z1: Vinyl (draw BEFORE meters so meters appear on top)
        # Force render when tonearm is animating (tonearm clearing may overlap vinyl)
        # advance_angle=vinyl_will_blit ensures constant rotation speed (angle only advances
        # when vinyl's own FPS gate is ready, not when forced due to overlapping elements)
        if self.vinyl_renderer and (vinyl_will_blit or force_flag):
            advance = vinyl_will_blit
            rect = self.vinyl_renderer.render(self.screen, status, now_ticks, volatile=volatile, force=force_flag, decel_factor=decel_factor, advance_angle=advance)
            if rect:
                dirty_rects.append(rect)
        
        # Z2: Album art (draw BEFORE meters so meters appear on top)
        if self.album_renderer:
            if album_url_changed:
                self.album_renderer.load_from_url(albumart)
            # Force redraw when vinyl animates (may overlap art area)
            if force_flag and not album_url_changed:
                self.album_renderer._needs_redraw = True
            if album_url_changed or album_will_render or (force_flag and self.album_renderer._scaled_surf):
                advance = album_will_render
                rect = self.album_renderer.render(self.screen, status, now_ticks, advance_angle=advance, volatile=volatile)
                if rect:
                    dirty_rects.append(rect)
        
        # Z3: Meters (draw AFTER vinyl/art so needles are visible)
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
        
        # TIMING FIX: Optimizations (precomputed frames, vinyl+art composite) make
        # the render loop complete very fast. This can cause meter.run() to be called
        # before the audio data source has new samples, resulting in stuck needles.
        # 
        # The meter_delay setting (UI configurable, 0-20ms, default 10ms) controls
        # the balance between CPU usage and meter responsiveness:
        # - Higher values (10-20): Lower CPU, meters may feel slightly sluggish
        # - Lower values (0-5): Higher CPU (up to 95%), more responsive meters
        if self.meter_delay_sec > 0:
            if not getattr(self, '_meter_delay_logged', False):
                log_debug(f"Meter timing delay: {self.meter_delay_ms}ms (configurable in Performance Settings)", "basic")
                self._meter_delay_logged = True
            time.sleep(self.meter_delay_sec)
        
        # =================================================================
        # SURGICAL OVERLAP DETECTION
        # =================================================================
        # Only force components that actually overlap cleared regions.
        # This is anti-collision compliant AND efficient.
        def overlaps_cleared(component_rect):
            """Check if component_rect overlaps any cleared region."""
            if not component_rect or not clear_regions:
                return False
            for region in clear_regions:
                if region and component_rect.colliderect(region):
                    return True
            return False
        
        # Z4: Text fields - only force if they overlap cleared regions
        if self.artist_scroller:
            scroller_rect = self.artist_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.artist_scroller.force_redraw()
        
        if self.title_scroller:
            scroller_rect = self.title_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.title_scroller.force_redraw()
        
        if self.album_scroller:
            scroller_rect = self.album_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.album_scroller.force_redraw()
        if self.next_title_scroller:
            scroller_rect = self.next_title_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.next_title_scroller.force_redraw()
        if self.next_artist_scroller:
            scroller_rect = self.next_artist_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.next_artist_scroller.force_redraw()
        if self.next_album_scroller:
            scroller_rect = self.next_album_scroller.get_rect()
            if overlaps_cleared(scroller_rect):
                self.next_album_scroller.force_redraw()

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

        if self.next_title_scroller:
            self.next_title_scroller.update_text(meta.get("next_title", "") or "")
            rect = self.next_title_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)
        if self.next_artist_scroller:
            self.next_artist_scroller.update_text(meta.get("next_artist", "") or "")
            rect = self.next_artist_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)
        if self.next_album_scroller:
            self.next_album_scroller.update_text(meta.get("next_album", "") or "")
            rect = self.next_album_scroller.draw(self.screen)
            if rect:
                dirty_rects.append(rect)

        # Z5: Tonearm (render AFTER scrollers)
        # Always render when force_flag is set (tonearm is part of animated elements)
        if self.tonearm_renderer and force_flag:
            rect = self.tonearm_renderer.render(self.screen, now_ticks, force=True)
            if rect:
                dirty_rects.append(rect)
        
        # Z6: Indicators - only force if they overlap cleared regions
        if self.indicator_renderer and self.indicator_renderer.has_indicators():
            indicator_force = False
            for ind_rect in self.indicator_renderer.get_all_rects():
                if overlaps_cleared(ind_rect):
                    indicator_force = True
                    break
            self.indicator_renderer.render(self.screen, meta, dirty_rects, force=indicator_force, skip_restore=False)
        
        # Z7: Time remaining (FORCE when animated elements change)
        if self.time_pos:
            import time as time_module
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
                
                # Force redraw when animated elements overlap time area
                # or if time string changed
                time_overlaps = overlaps_cleared(self.time_rect) if self.time_rect else False
                needs_redraw = time_str != self.last_time_str or time_overlaps
                
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

        # Z7b: Elapsed time (when time.elapsed.pos set; anti-collision: force redraw when tonearm/vinyl/art overlap)
        if self.time_elapsed_pos and self.fontDigi:
            seek_ms = meta.get("seek") or 0
            elapsed_sec = max(0, int(seek_ms) // 1000)
            elapsed_str = f"{elapsed_sec // 60:02d}:{elapsed_sec % 60:02d}"
            elapsed_overlaps = overlaps_cleared(self.time_elapsed_rect) if self.time_elapsed_rect else False
            needs_redraw = elapsed_str != self.last_elapsed_str or elapsed_overlaps
            if needs_redraw:
                self.last_elapsed_str = elapsed_str
                if self.bgr_surface and self.time_elapsed_rect:
                    self.screen.blit(self.bgr_surface, self.time_elapsed_rect.topleft, self.time_elapsed_rect)
                    dirty_rects.append(self.time_elapsed_rect.copy())
                surf = self.fontDigi.render(elapsed_str, True, self.time_elapsed_color)
                self.screen.blit(surf, self.time_elapsed_pos)

        # Z7c: Total time (when time.total.pos set; anti-collision: force redraw when tonearm/vinyl/art overlap)
        if self.time_total_pos and self.fontDigi:
            duration_sec = max(0, int(meta.get("duration") or 0))
            total_str = f"{duration_sec // 60:02d}:{duration_sec % 60:02d}"
            total_overlaps = overlaps_cleared(self.time_total_rect) if self.time_total_rect else False
            needs_redraw = total_str != self.last_total_str or total_overlaps
            if needs_redraw:
                self.last_total_str = total_str
                if self.bgr_surface and self.time_total_rect:
                    self.screen.blit(self.bgr_surface, self.time_total_rect.topleft, self.time_total_rect)
                    dirty_rects.append(self.time_total_rect.copy())
                surf = self.fontDigi.render(total_str, True, self.time_total_color)
                self.screen.blit(surf, self.time_total_pos)

        # LAYER: Sample rate / format icon - only force if overlapping cleared regions
        # Format icon
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
            
            type_overlaps = overlaps_cleared(self.type_rect)
            needs_redraw = fmt != self.last_track_type or type_overlaps
            
            if needs_redraw:
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
                    if self.sample_font:
                        txt_surf = self.sample_font.render(fmt[:4], True, self.type_color)
                        self.screen.blit(txt_surf, (self.type_rect.x, self.type_rect.y))
                        self.last_format_icon_surf = txt_surf
                else:
                    try:
                        if pg.version.ver.startswith("2"):
                            # Pygame 2 native SVG
                            img = pg.image.load(icon_path)
                            w, h = img.get_width(), img.get_height()
                            # Preserve aspect ratio
                            sc = min(self.type_rect.width / float(w), self.type_rect.height / float(h))
                            new_size = (max(1, int(w * sc)), max(1, int(h * sc)))
                            try:
                                img = pg.transform.smoothscale(img, new_size)
                            except Exception:
                                img = pg.transform.scale(img, new_size)
                            # Convert to format suitable for pixel manipulation
                            img = img.convert_alpha()
                            # Colorize to match skin color
                            set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                            # Center in type_rect
                            dx = self.type_rect.x + (self.type_rect.width - img.get_width()) // 2
                            dy = self.type_rect.y + (self.type_rect.height - img.get_height()) // 2
                            self.screen.blit(img, (dx, dy))
                            self.last_format_icon_surf = img
                        else:
                            try:
                                import cairosvg
                                png_bytes = cairosvg.svg2png(url=icon_path,
                                                            output_width=self.type_rect.width,
                                                            output_height=self.type_rect.height)
                                pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
                                img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
                                img = img.convert_alpha()
                                # Colorize to match skin color
                                set_color(img, pg.Color(self.type_color[0], self.type_color[1], self.type_color[2]))
                                # Center in type_rect
                                dx = self.type_rect.x + (self.type_rect.width - img.get_width()) // 2
                                dy = self.type_rect.y + (self.type_rect.height - img.get_height()) // 2
                                self.screen.blit(img, (dx, dy))
                                self.last_format_icon_surf = img
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"[FormatIcon] error: {e}")
                
                dirty_rects.append(self.type_rect.copy())
        
        # Sample rate - only force if overlapping cleared regions
        if self.sample_pos and self.sample_box:
            sample_text = f"{samplerate} {bitdepth}".strip()
            if not sample_text:
                sample_text = bitrate.strip() if bitrate else ""
            
            sample_overlaps = overlaps_cleared(self.sample_rect) if self.sample_rect else False
            needs_redraw = (sample_text and sample_text != self.last_sample_text) or sample_overlaps
            
            if needs_redraw and sample_text:
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
        
        # LAYER: Foreground mask (always last)
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
        
        return dirty_rects
    
    def cleanup(self):
        """Release resources on shutdown."""
        log_debug("TurntableHandler cleanup", "basic")
        self.vinyl_renderer = None
        self.tonearm_renderer = None
        self.album_renderer = None
        self.indicator_renderer = None
        self.artist_scroller = None
        self.title_scroller = None
        self.album_scroller = None
        self.next_title_scroller = None
        self.next_artist_scroller = None
        self.next_album_scroller = None
        self.bgr_surface = None

