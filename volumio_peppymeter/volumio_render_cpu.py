# Copyright 2025 PeppyMeter for Volumio - CPU Rendering Module
#
# This module provides CPU-based rendering for album art, reels, tonearm,
# scrolling labels, and foreground optimization.
#
# Extracted from volumio_peppymeter.py to allow clean separation between
# CPU and GPU rendering paths.
#
# Usage:
#   from volumio_render_cpu import (
#       AlbumArtRenderer, ReelRenderer, TonearmRenderer,
#       ScrollingLabel, compute_foreground_regions,
#       get_rotation_params, ROTATION_PRESETS
#   )

import os
import io
import math
import time
import requests
import pygame as pg

# Optional PIL support for masking and circular crops
try:
    from PIL import Image, ImageOps, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# =============================================================================
# Debug Logging - Passthrough to main module or no-op
# =============================================================================

# Default no-op logger - will be replaced if main module provides one
_log_debug_func = None

def set_log_debug(func):
    """Set the debug logging function from main module."""
    global _log_debug_func
    _log_debug_func = func

def log_debug(msg, level="basic"):
    """Log debug message if logger is set."""
    if _log_debug_func:
        _log_debug_func(msg, level)


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


# =============================================================================
# Rotation Quality Presets
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


# =============================================================================
# ScrollingLabel - Single-threaded scrolling text
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
    
    def check_pending_load(self):
        """Compatibility stub - sync loading has no pending loads."""
        return False

    def has_art(self):
        """Check if album art is loaded."""
        return self._scaled_surf is not None

    def _update_angle(self, status, now_ticks):
        """Update rotation angle based on RPM and playback status."""
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if status == "play":
            # Calculate angle increment
            # RPM * 6 = degrees per second (360 / 60 = 6)
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0

    def will_blit(self, now_ticks):
        """Check if blit is needed (FPS gating for rotating covers)."""
        if not self._scaled_surf:
            return False
        if self._need_first_blit:
            return True
        if not self.rotate_enabled or self.rotate_rpm <= 0.0:
            # Static art - only blit when needed
            return self._needs_redraw
        # Rotating - check interval
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms

    def get_backing_rect(self):
        """Get the rectangle needed for backing (accounts for rotation)."""
        if not self.art_pos or not self.art_dim:
            return None
        
        if self.rotate_enabled and self.rotate_rpm > 0.0 and self.art_center:
            # Rotating - need larger rect to cover rotation
            diag = int(max(self.art_dim[0], self.art_dim[1]) * math.sqrt(2)) + 4
            center_x, center_y = self.art_center
            ext_x = max(0, center_x - diag // 2)
            ext_y = max(0, center_y - diag // 2)
            # Clamp to screen bounds
            ext_w = min(diag, self.screen_size[0] - ext_x)
            ext_h = min(diag, self.screen_size[1] - ext_y)
            return pg.Rect(ext_x, ext_y, ext_w, ext_h)
        else:
            return pg.Rect(self.art_pos[0], self.art_pos[1], self.art_dim[0], self.art_dim[1])

    def render(self, screen, status, now_ticks, advance_angle=True):
        """Render album art (rotated if enabled) plus border and LP center markers.
        
        OPTIMIZATION: FPS gating limits rotation updates to reduce CPU.
        Returns dirty rect if drawn, None if skipped.
        
        :param screen: pygame screen surface
        :param status: playback status ("play", "pause", "stop")
        :param now_ticks: pygame.time.get_ticks() value
        :param advance_angle: if False, render at current angle without advancing rotation
        """
        if not self.art_pos or not self.art_dim or not self._scaled_surf:
            return None

        # FPS gating: skip if not time to blit yet (unless advance_angle=False which forces render)
        if advance_angle and not self.will_blit(now_ticks):
            return None

        dirty_rect = None
        # Only update timing when advancing (so tonearm redraws don't reset album art's FPS schedule)
        if advance_angle:
            self._last_blit_tick = now_ticks

        if self.rotate_enabled and self.art_center and self.rotate_rpm > 0.0:
            # Update angle based on playback status (only if advancing)
            if advance_angle:
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
                 speed_multiplier=1.0, direction="ccw"):
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
                log_debug(f"[ReelRenderer] File not found: {img_path}", "basic")
        except Exception as e:
            log_debug(f"[ReelRenderer] Failed to load '{self.filename}': {e}", "basic")
    
    def _update_angle(self, status, now_ticks):
        """Update rotation angle based on RPM, direction, and playback status."""
        if self.rotate_rpm <= 0.0:
            return
        
        status = (status or "").lower()
        if status == "play":
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
    
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
        return self.get_backing_rect()


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
        self._early_lift_start_tick = 0  # Timestamp when early lift started
        
        # Arm geometry for backing rect calculation
        self._arm_length = 0
        
        # Load the tonearm image
        self._load_image()
    
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
                log_debug(f"[TonearmRenderer] File not found: {img_path}", "basic")
        except Exception as e:
            log_debug(f"[TonearmRenderer] Failed to load '{self.filename}': {e}", "basic")
    
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
                            log_debug(f"[Tonearm] Update freeze ({gap_sec*1000:.0f}ms), restart animation")
        
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
                self._early_lift_start_tick = 0
                target_angle = (
                    self.angle_start + 
                    (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                )
                self._state = TONEARM_STATE_DROP
                self._start_animation(target_angle, self.drop_duration)
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_DROP:
            if status != "play":
                # Playback stopped during drop - lift back
                self._state = TONEARM_STATE_LIFT
                self._early_lift = False  # Clear flag - this is a normal stop
                self._start_animation(self.angle_rest, self.lift_duration)
            else:
                # Continue drop animation
                if self._update_animation():
                    # Drop complete - sync to current progress before entering TRACKING
                    # This prevents jump detection from triggering immediately
                    progress_pct = max(0.0, min(100.0, progress_pct or 0.0))
                    self._current_angle = (
                        self.angle_start + 
                        (self.angle_end - self.angle_start) * (progress_pct / 100.0)
                    )
                    self._state = TONEARM_STATE_TRACKING
                self._needs_redraw = True
        
        elif self._state == TONEARM_STATE_TRACKING:
            # Early lift: when track is about to end, lift tonearm preemptively
            # This hides the freeze during track change - looks like natural LP change
            if time_remaining_sec is not None and time_remaining_sec < 1.5 and time_remaining_sec > 0:
                log_debug(f"[Tonearm] Early lift - track ending in {time_remaining_sec:.1f}s")
                self._state = TONEARM_STATE_LIFT
                self._pending_drop_target = None  # Will get new position from next track
                self._early_lift = True  # Flag to stay at REST after lift completes
                self._early_lift_start_tick = pg.time.get_ticks()  # Record start time
                self._start_animation(self.angle_rest, self.lift_duration)
                self._needs_redraw = True
                self._last_blit_tick = 0
            elif status != "play":
                # Playback stopped - start lift (not early lift)
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
                    log_debug(f"[Tonearm] Large jump detected: {self._current_angle:.1f} -> {target_angle:.1f}, lifting")
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
                    log_debug("[Tonearm] Early lift complete - staying at REST")
                    self._state = TONEARM_STATE_REST
                    self._pending_drop_target = None
                    # Keep _early_lift=True - will be cleared when DROP starts
                elif self._pending_drop_target is not None:
                    # Seek/jump - drop to pending target
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
                    self._state = TONEARM_STATE_DROP
                    self._start_animation(target_angle, self.drop_duration)
                else:
                    # Lift complete, not playing - back to rest
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
    
    def render(self, screen, now_ticks, force=False):
        """
        Render the tonearm at current angle.
        
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
                            log_debug(f"[Tonearm] Freeze detected ({gap_ms}ms), restarting animation")
        
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
        blit_x = scr_px - rot_px
        blit_y = scr_py - rot_py
        
        # 4. Blit to screen
        screen.blit(rotated, (int(blit_x), int(blit_y)))
        
        self._needs_redraw = False
        self._last_drawn_angle = self._current_angle
        
        return self.get_backing_rect()
    
    def get_state(self):
        """Return current state for debugging."""
        return self._state
    
    def get_angle(self):
        """Return current angle for debugging."""
        return self._current_angle
    
    def is_early_lift(self):
        """Return True if tonearm is doing early lift for track ending."""
        return self._early_lift
    
    def should_stop_rotation(self, now_ticks, delay_ms=500):
        """Return True if rotation should stop due to early lift (after delay).
        
        :param now_ticks: Current pygame.time.get_ticks() value
        :param delay_ms: Delay in ms before stopping rotation (default 500ms)
        :return: True if early lift is active AND delay has passed
        """
        if not self._early_lift:
            return False
        return (now_ticks - self._early_lift_start_tick) >= delay_ms


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Functions
    'compute_foreground_regions',
    'get_rotation_params',
    'set_log_debug',
    
    # Constants
    'ROTATION_PRESETS',
    'USE_PRECOMPUTED_FRAMES',
    'PIL_AVAILABLE',
    'TONEARM_STATE_REST',
    'TONEARM_STATE_DROP',
    'TONEARM_STATE_TRACKING',
    'TONEARM_STATE_LIFT',
    
    # Classes
    'ScrollingLabel',
    'AlbumArtRenderer',
    'ReelRenderer',
    'TonearmRenderer',
]
