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
    SPOOL_LEFT_SPEED, SPOOL_RIGHT_SPEED,
    FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD,
    ALBUMART_POS, ALBUMART_DIM, ALBUMART_MSK, ALBUMBORDER,
    ALBUMART_ROT, ALBUMART_ROT_SPEED,
    PLAY_TXT_CENTER, PLAY_CENTER, PLAY_MAX,
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

    def update_text(self, new_text):
        """Update text content, reset scroll position if changed."""
        new_text = new_text or ""
        if new_text == self.text and self.surf is not None:
            return False  # No change
        self.text = new_text
        self.surf = self.font.render(self.text, True, self.color)
        self.text_w, self.text_h = self.surf.get_size()
        self.offset = 0.0
        self.direction = 1
        self._pause_until = 0
        self._last_time = pg.time.get_ticks()
        self._needs_redraw = True
        self._last_draw_offset = -1
        return True  # Changed

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
            
            # Restore backing before drawing (prevents artifacts)
            if self._backing and self._backing_rect:
                surface.blit(self._backing, self._backing_rect.topleft)
            
            if self.center and self.box_width > 0:
                left = box_rect.x + (self.box_width - self.text_w) // 2
                surface.blit(self.surf, (left, box_rect.y))
            else:
                surface.blit(self.surf, (box_rect.x, box_rect.y))
            self._needs_redraw = False
            return self._backing_rect.copy() if self._backing_rect else box_rect.copy()
        
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
        return self._backing_rect.copy() if self._backing_rect else box_rect.copy()


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
        # Calculate step from FPS to maintain smooth rotation
        # Higher FPS = smaller steps
        step = max(2, int(180 / custom_fps))
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
                 circle=True, rotation_fps=8, rotation_step=6, speed_multiplier=1.0):
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

    def _update_angle(self, status, now_ticks):
        """Update rotation angle based on RPM and playback status.
        
        OPTIMIZATION: Only updates at target FPS rate.
        """
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if status == "play":
            # degrees per second = rpm * 6
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0

    def will_blit(self, now_ticks):
        """Check if rotation blit is needed (FPS gating)."""
        if self._scaled_surf is None:
            return False
        if self._need_first_blit:
            return True
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms

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

    def render(self, screen, status, now_ticks):
        """Render album art (rotated if enabled) plus border and LP center markers.
        
        OPTIMIZATION: FPS gating limits rotation updates to reduce CPU.
        Returns dirty rect if drawn, None if skipped.
        
        :param screen: pygame screen surface
        :param status: playback status ("play", "pause", "stop")
        :param now_ticks: pygame.time.get_ticks() value
        """
        if not self.art_pos or not self.art_dim or not self._scaled_surf:
            return None

        # FPS gating: skip if not time to blit yet
        if not self.will_blit(now_ticks):
            return None

        dirty_rect = None
        self._last_blit_tick = now_ticks

        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0:
            # Update angle based on playback status
            self._update_angle(status, now_ticks)
            
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
                 speed_multiplier=1.0):
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
        """
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.filename = filename
        self.pos = pos
        self.center = center
        self.rotate_rpm = float(rotate_rpm) * float(speed_multiplier)  # Apply speed multiplier
        self.angle_step_deg = float(angle_step_deg)
        self.rotation_fps = int(rotation_fps)
        self.rotation_step = int(rotation_step)
        
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
        """Load the reel PNG file, apply circular mask, and pre-compute rotation frames."""
        if not self.filename:
            return
        
        try:
            img_path = os.path.join(self.base_path, self.meter_folder, self.filename)
            if not os.path.exists(img_path):
                print(f"[ReelRenderer] File not found: {img_path}")
                return
            
            # Use PIL for circular masking if available
            if PIL_AVAILABLE:
                try:
                    pil_img = Image.open(img_path).convert('RGBA')
                    
                    # Apply circular mask to ensure proper transparency
                    mask = Image.new('L', pil_img.size, 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, pil_img.size[0], pil_img.size[1]), fill=255)
                    pil_img.putalpha(mask)
                    
                    # Convert PIL image to pygame surface
                    mode = pil_img.mode
                    size = pil_img.size
                    data = pil_img.tobytes()
                    self._original_surf = pg.image.fromstring(data, size, mode).convert_alpha()
                    self._loaded = True
                    self._need_first_blit = True
                except Exception as e:
                    print(f"[ReelRenderer] PIL processing failed, falling back: {e}")
                    self._original_surf = pg.image.load(img_path).convert_alpha()
                    self._loaded = True
                    self._need_first_blit = True
            else:
                # Fallback: load directly without circular mask
                self._original_surf = pg.image.load(img_path).convert_alpha()
                self._loaded = True
                self._need_first_blit = True
            
            # OPTIMIZATION: Pre-compute all rotation frames (CCW direction)
            if USE_PRECOMPUTED_FRAMES and self.center and self.rotate_rpm > 0.0:
                try:
                    self._rot_frames = [
                        pg.transform.rotate(self._original_surf, a)
                        for a in range(0, 360, self.rotation_step)
                    ]
                except Exception:
                    self._rot_frames = None
                    
        except Exception as e:
            print(f"[ReelRenderer] Failed to load '{self.filename}': {e}")
    
    def _update_angle(self, status, now_ticks):
        """Update rotation angle based on RPM and playback status."""
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if status == "play":
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0
    
    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating)."""
        if not self._loaded or not self._original_surf:
            return False
        if self._need_first_blit:
            return True
        if not self.center or self.rotate_rpm <= 0.0:
            return self._needs_redraw
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
    
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
    
    def render(self, screen, status, now_ticks):
        """Render the reel (rotated if playing).
        
        OPTIMIZATION: Uses pre-computed frames and FPS gating.
        Returns dirty rect if drawn, None if skipped.
        """
        if not self._loaded or not self._original_surf:
            return None
        
        # FPS gating
        if not self.will_blit(now_ticks):
            return None
        
        self._last_blit_tick = now_ticks
        
        if not self.center:
            # No rotation - just blit at position
            screen.blit(self._original_surf, self.pos)
            self._needs_redraw = False
            self._need_first_blit = False
            return pg.Rect(self.pos[0], self.pos[1], 
                         self._original_surf.get_width(), 
                         self._original_surf.get_height())
        
        # Update angle based on playback status
        self._update_angle(status, now_ticks)
        
        # OPTIMIZATION: Use pre-computed frame lookup if available
        if self._rot_frames:
            idx = int(self._current_angle // self.rotation_step) % len(self._rot_frames)
            rot = self._rot_frames[idx]
        else:
            # Fallback: real-time rotation (CCW direction)
            try:
                rot = pg.transform.rotate(self._original_surf, self._current_angle)
            except Exception:
                rot = pg.transform.rotate(self._original_surf, int(self._current_angle))
        
        # Get rect centered on rotation center
        rot_rect = rot.get_rect(center=self.center)
        screen.blit(rot, rot_rect.topleft)
        self._needs_redraw = False
        self._need_first_blit = False
        return self.get_backing_rect()


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
# Main Display Output with Overlay - OPTIMIZED
# =============================================================================
def start_display_output(pm, callback, meter_config_volumio):
    """Main display loop with integrated overlay rendering.
    OPTIMIZED: Uses dirty rectangle updates instead of full screen flip."""
    
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
        
        def capture_rect(name, pos, width, height):
            if pos and width and height:
                r = pg.Rect(pos[0], pos[1], int(width), int(height))
                try:
                    surf = screen.subsurface(r).copy()
                    backing.append((r, surf))
                    backing_dict[name] = (r, surf)
                except Exception:
                    # Fallback: create black surface (not undefined .convert() content)
                    s = pg.Surface((r.width, r.height))
                    s.fill((0, 0, 0))
                    backing.append((r, s))
                    backing_dict[name] = (r, s)
        
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
        if art_pos and art_dim:
            rotate_enabled = mc_vol.get(ALBUMART_ROT, False)
            rotate_rpm = as_float(mc_vol.get(ALBUMART_ROT_SPEED), 0.0)
            screen_size = (cfg[SCREEN_INFO][WIDTH], cfg[SCREEN_INFO][HEIGHT])
            
            # Get rotation quality settings from global config
            rot_quality = meter_config_volumio.get(ROTATION_QUALITY, "medium")
            rot_custom_fps = meter_config_volumio.get(ROTATION_FPS, 8)
            rot_fps, rot_step = get_rotation_params(rot_quality, rot_custom_fps)
            rot_speed_mult = meter_config_volumio.get(ROTATION_SPEED, 1.0)
            
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
        
        # Create reel renderers (for cassette skins)
        reel_left_renderer = None
        reel_right_renderer = None
        
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
                speed_multiplier=spool_left_mult
            )
            # Capture backing for left reel
            backing_rect = reel_left_renderer.get_backing_rect()
            if backing_rect:
                capture_rect("reel_left", (backing_rect.x, backing_rect.y), backing_rect.width, backing_rect.height)
        
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
                speed_multiplier=spool_right_mult
            )
            # Capture backing for right reel
            backing_rect = reel_right_renderer.get_backing_rect()
            if backing_rect:
                capture_rect("reel_right", (backing_rect.x, backing_rect.y), backing_rect.width, backing_rect.height)
        
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

        # Load meter foreground (fgr) to draw last, above rotating cover
        fgr_surf = None
        fgr_name = mc.get(FGR_FILENAME)
        meter_x = mc.get('meter.x', 0)
        meter_y = mc.get('meter.y', 0)
        try:
            if fgr_name:
                meter_path = os.path.join(cfg.get(BASE_PATH), cfg.get(SCREEN_INFO)[METER_FOLDER])
                fgr_path = os.path.join(meter_path, fgr_name)
                fgr_surf = pg.image.load(fgr_path).convert_alpha()
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
            "reel_left_renderer": reel_left_renderer,
            "reel_right_renderer": reel_right_renderer,
            "fgr_surf": fgr_surf,
            "fgr_pos": (meter_x, meter_y),
        }
    
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
            # Run meter animation - collect dirty rects
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
            status = meta.get("status", "")
            
            # Text scrollers - OPTIMIZED: only redraws if changed
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
                        bd = ov.get("backing_dict", {})
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
                    bd = ov.get("backing_dict", {})
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
            
            # Render cassette reels (before album art) - returns dirty rect or None
            reel_left = ov.get("reel_left_renderer")
            reel_right = ov.get("reel_right_renderer")
            is_playing = status == "play"
            
            if reel_left:
                # Only animate reels during playback, check FPS gating
                if is_playing and reel_left.will_blit(now_ticks):
                    # Restore backing ONLY when we're about to blit
                    bd = ov.get("backing_dict", {})
                    if "reel_left" in bd:
                        r, b = bd["reel_left"]
                        screen.blit(b, r.topleft)
                    rect = reel_left.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)
            
            if reel_right:
                # Only animate reels during playback, check FPS gating
                if is_playing and reel_right.will_blit(now_ticks):
                    # Restore backing ONLY when we're about to blit
                    bd = ov.get("backing_dict", {})
                    if "reel_right" in bd:
                        r, b = bd["reel_right"]
                        screen.blit(b, r.topleft)
                    rect = reel_right.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)
            
            # Album art (round + optional rotating) - draw LAST to sit on top
            album_renderer = ov.get("album_renderer")
            if album_renderer:
                url_changed = albumart != getattr(album_renderer, "_current_url", None)
                if url_changed:
                    # Restore backing for album art area only when URL changes
                    bd = ov.get("backing_dict", {})
                    if "art" in bd:
                        r, b = bd["art"]
                        screen.blit(b, r.topleft)
                    album_renderer.load_from_url(albumart)
                    # Force blit after load
                    rect = album_renderer.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)
                elif album_renderer.rotate_enabled and album_renderer.rotate_rpm > 0.0:
                    # Check if rotation update is needed (FPS gating + playback)
                    if is_playing and album_renderer.will_blit(now_ticks):
                        # Restore backing ONLY when we're about to blit
                        bd = ov.get("backing_dict", {})
                        if "art" in bd:
                            r, b = bd["art"]
                            screen.blit(b, r.topleft)
                        rect = album_renderer.render(screen, status, now_ticks)
                        if rect:
                            dirty_rects.append(rect)
                else:
                    # Static artwork - render once
                    rect = album_renderer.render(screen, status, now_ticks)
                    if rect:
                        dirty_rects.append(rect)

            # Draw the meter foreground above everything (needles + rotating cover)
            fgr_surf = ov.get("fgr_surf")
            if fgr_surf and dirty_rects:
                # Only draw foreground if something changed
                screen.blit(fgr_surf, ov["fgr_pos"])
            
            # Spectrum and callbacks - OPTIMIZED: throttle spectrum updates
            if callback.spectrum_output is not None:
                # Only update spectrum every N frames to reduce CPU load
                if frame_counter % SPECTRUM_UPDATE_INTERVAL == 0:
                    callback.peppy_meter_update()
            else:
                callback.peppy_meter_update()
            
            # OPTIMIZATION: Update only dirty rectangles
            if dirty_rects:
                # Merge overlapping rectangles for efficiency
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
