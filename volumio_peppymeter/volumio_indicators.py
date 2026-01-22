# Copyright 2025 PeppyMeter for Volumio by Just a Nerd
# Indicator renderers for playback state display
#
# This file is part of PeppyMeter for Volumio
#
# Provides visual indicators for:
# - Volume level (numeric, slider, knob, arc)
# - Mute state (LED or icon with glow)
# - Shuffle state (LED or icon with glow)
# - Repeat state (LED or icon with glow, 3 states)
# - Play/Pause/Stop state (LED or icon with glow, 3 states)
# - Track progress bar

import os
import math
import pygame as pg

try:
    from PIL import Image, ImageFilter, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# =============================================================================
# GlowEffect - Utility class for glow effect generation
# =============================================================================
class GlowEffect:
    """Utility class for generating glow effects using PIL blur."""
    
    @staticmethod
    def create_led_glow_surface(size, shape, color, radius, intensity):
        """Create a glow surface for LED indicator using PIL blur.
        
        :param size: (width, height) of the LED element
        :param shape: 'circle' or 'rect'
        :param color: RGB tuple for glow color
        :param radius: blur radius in pixels
        :param intensity: 0.0-1.0 glow opacity
        :return: pygame surface with alpha, or None if PIL unavailable
        """
        if not PIL_AVAILABLE or radius <= 0 or intensity <= 0:
            return None
        
        try:
            # Create surface larger than LED to accommodate glow
            padding = radius * 2
            glow_w = size[0] + padding * 2
            glow_h = size[1] + padding * 2
            
            # Create PIL image with alpha channel
            pil_img = Image.new('RGBA', (glow_w, glow_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(pil_img)
            
            # Calculate alpha from intensity
            alpha = int(255 * min(1.0, max(0.0, intensity)))
            glow_color = (color[0], color[1], color[2], alpha)
            
            # Draw shape at center
            if shape == 'circle':
                # Draw filled ellipse
                left = padding
                top = padding
                right = padding + size[0]
                bottom = padding + size[1]
                draw.ellipse([left, top, right, bottom], fill=glow_color)
            else:
                # Draw filled rectangle
                left = padding
                top = padding
                right = padding + size[0]
                bottom = padding + size[1]
                draw.rectangle([left, top, right, bottom], fill=glow_color)
            
            # Apply gaussian blur for glow effect
            pil_img = pil_img.filter(ImageFilter.GaussianBlur(radius=radius))
            
            # Convert to pygame surface
            mode = pil_img.mode
            size_tuple = pil_img.size
            data = pil_img.tobytes()
            
            pg_surface = pg.image.fromstring(data, size_tuple, mode)
            return pg_surface.convert_alpha()
            
        except Exception as e:
            print(f"[GlowEffect] Failed to create LED glow: {e}")
            return None
    
    @staticmethod
    def create_icon_glow_surface(icon_surface, radius, intensity, color=None):
        """Create glow effect around an icon's opaque pixels.
        
        :param icon_surface: pygame surface of the icon
        :param radius: blur radius in pixels
        :param intensity: 0.0-1.0 glow opacity
        :param color: RGB tuple for glow color (None = use white/neutral)
        :return: pygame surface with glow (larger than original), or None
        """
        if not PIL_AVAILABLE or radius <= 0 or intensity <= 0:
            return None
        
        if icon_surface is None:
            return None
        
        try:
            # Get icon dimensions
            icon_w = icon_surface.get_width()
            icon_h = icon_surface.get_height()
            
            # Create surface larger than icon to accommodate glow
            padding = radius * 2
            glow_w = icon_w + padding * 2
            glow_h = icon_h + padding * 2
            
            # Convert pygame surface to PIL for processing
            icon_string = pg.image.tostring(icon_surface, 'RGBA')
            pil_icon = Image.frombytes('RGBA', (icon_w, icon_h), icon_string)
            
            # Extract alpha channel as mask
            alpha_channel = pil_icon.split()[3]
            
            # Create glow image - solid color with icon's alpha mask
            if color:
                glow_color = (color[0], color[1], color[2])
            else:
                glow_color = (255, 255, 255)  # White glow by default
            
            # Create base glow image
            pil_glow = Image.new('RGBA', (glow_w, glow_h), (0, 0, 0, 0))
            
            # Create colored version of alpha mask
            glow_base = Image.new('RGBA', (icon_w, icon_h), (0, 0, 0, 0))
            glow_alpha = int(255 * min(1.0, max(0.0, intensity)))
            
            # For each pixel with alpha > 0, set glow color
            pixels = glow_base.load()
            alpha_pixels = alpha_channel.load()
            for y in range(icon_h):
                for x in range(icon_w):
                    a = alpha_pixels[x, y]
                    if a > 0:
                        # Scale alpha by original alpha and intensity
                        final_alpha = int((a / 255.0) * glow_alpha)
                        pixels[x, y] = (glow_color[0], glow_color[1], glow_color[2], final_alpha)
            
            # Paste glow base at center of larger surface
            pil_glow.paste(glow_base, (padding, padding))
            
            # Apply gaussian blur for glow effect
            pil_glow = pil_glow.filter(ImageFilter.GaussianBlur(radius=radius))
            
            # Convert to pygame surface
            pg_surface = pg.image.fromstring(pil_glow.tobytes(), pil_glow.size, 'RGBA')
            return pg_surface.convert_alpha()
            
        except Exception as e:
            print(f"[GlowEffect] Failed to create icon glow: {e}")
            return None


# =============================================================================
# LEDIndicator - Renders LED-style indicators with optional glow
# =============================================================================
class LEDIndicator:
    """Renders an LED-style indicator with optional glow effect.
    
    Supports circle or rectangle shapes with multiple color states.
    Glow effect is pre-rendered for each state to minimize per-frame overhead.
    """
    
    def __init__(self, pos, size, shape, colors, glow_radius=0,
                 glow_intensity=0.5, glow_colors=None):
        """Initialize LED indicator.
        
        :param pos: (x, y) screen position (top-left of LED area including glow)
        :param size: (width, height) of LED element itself
        :param shape: 'circle' or 'rect'
        :param colors: list of RGB tuples for each state
        :param glow_radius: pixels for glow blur (0 = no glow)
        :param glow_intensity: 0.0-1.0 opacity of glow
        :param glow_colors: list of RGB tuples per state (None = use colors)
        """
        self.pos = pos
        self.size = size
        self.shape = shape.lower() if shape else "circle"
        self.colors = colors if colors else [(255, 0, 0), (64, 64, 64)]
        self.glow_radius = max(0, int(glow_radius))
        self.glow_intensity = max(0.0, min(1.0, float(glow_intensity)))
        self.glow_colors = glow_colors if glow_colors else self.colors
        
        # Ensure glow_colors has same length as colors
        while len(self.glow_colors) < len(self.colors):
            self.glow_colors.append(self.glow_colors[-1] if self.glow_colors else (255, 255, 255))
        
        # Calculate total render area (LED + glow padding)
        if self.glow_radius > 0:
            self.padding = self.glow_radius * 2
        else:
            self.padding = 0
        
        self.total_size = (size[0] + self.padding * 2, size[1] + self.padding * 2)
        
        # Pre-render LED and glow surfaces for each state
        self._surfaces = []
        self._pre_render_states()
        
        # Track current state for change detection
        self._current_state = -1
        self._needs_redraw = True
        
        # Backing surface for clean restore
        self._backing = None
        self._backing_rect = None
    
    def _pre_render_states(self):
        """Pre-render combined LED + glow surface for each state."""
        self._surfaces = []
        
        for i, color in enumerate(self.colors):
            # Create surface for this state
            surf = pg.Surface(self.total_size, pg.SRCALPHA)
            surf.fill((0, 0, 0, 0))
            
            # Render glow first (behind LED)
            if self.glow_radius > 0 and self.glow_intensity > 0:
                glow_color = self.glow_colors[i] if i < len(self.glow_colors) else color
                glow_surf = GlowEffect.create_led_glow_surface(
                    self.size, self.shape, glow_color,
                    self.glow_radius, self.glow_intensity
                )
                if glow_surf:
                    surf.blit(glow_surf, (0, 0))
            
            # Render LED on top
            led_x = self.padding
            led_y = self.padding
            
            if self.shape == 'circle':
                center = (led_x + self.size[0] // 2, led_y + self.size[1] // 2)
                radius = min(self.size[0], self.size[1]) // 2
                pg.draw.circle(surf, color, center, radius)
            else:
                rect = pg.Rect(led_x, led_y, self.size[0], self.size[1])
                pg.draw.rect(surf, color, rect)
            
            self._surfaces.append(surf)
    
    def get_rect(self):
        """Get bounding rectangle for this indicator (including glow)."""
        if not self.pos:
            return None
        return pg.Rect(self.pos[0], self.pos[1], self.total_size[0], self.total_size[1])
    
    def capture_backing(self, screen):
        """Capture backing surface under indicator area."""
        rect = self.get_rect()
        if not rect:
            return
        
        self._backing_rect = rect.copy()
        try:
            self._backing = screen.subsurface(rect).copy()
        except Exception:
            self._backing = pg.Surface((rect.width, rect.height))
            self._backing.fill((0, 0, 0))
    
    def restore_backing(self, screen):
        """Restore backing surface to screen."""
        if self._backing and self._backing_rect:
            screen.blit(self._backing, self._backing_rect.topleft)
            return self._backing_rect.copy()
        return None
    
    def render(self, screen, state_index):
        """Render LED at specified state.
        
        :param screen: pygame screen surface
        :param state_index: integer index into colors list
        :return: dirty rect if drawn, None if skipped
        """
        if not self.pos or not self._surfaces:
            return None
        
        # Clamp state index
        state_index = max(0, min(len(self._surfaces) - 1, int(state_index)))
        
        # Check if state changed
        if state_index == self._current_state and not self._needs_redraw:
            return None
        
        self._current_state = state_index
        self._needs_redraw = False
        
        # Blit pre-rendered surface
        screen.blit(self._surfaces[state_index], self.pos)
        
        return self.get_rect()
    
    def force_redraw(self):
        """Force redraw on next render call."""
        self._needs_redraw = True


# =============================================================================
# IconIndicator - Renders icon-based indicators with optional glow
# =============================================================================
class IconIndicator:
    """Renders icon-based indicator with optional glow effect.
    
    Loads PNG icons for each state. Glow is pre-rendered per state.
    """
    
    def __init__(self, base_path, meter_folder, pos, icon_filenames,
                 glow_radius=0, glow_intensity=0.5, glow_colors=None):
        """Initialize icon indicator.
        
        :param base_path: base asset path
        :param meter_folder: meter folder name
        :param pos: (x, y) screen position
        :param icon_filenames: comma-separated PNG filenames or list
        :param glow_radius: pixels for glow blur (0 = no glow)
        :param glow_intensity: 0.0-1.0 opacity of glow
        :param glow_colors: list of RGB tuples per state (None = derive from icon)
        """
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.pos = pos
        self.glow_radius = max(0, int(glow_radius))
        self.glow_intensity = max(0.0, min(1.0, float(glow_intensity)))
        self.glow_colors = glow_colors
        
        # Parse icon filenames
        if isinstance(icon_filenames, str):
            self.icon_filenames = [f.strip() for f in icon_filenames.split(',')]
        else:
            self.icon_filenames = list(icon_filenames) if icon_filenames else []
        
        # Load icons and create surfaces
        self._icons = []
        self._surfaces = []
        self._icon_sizes = []
        self._max_size = (0, 0)
        self._padding = self.glow_radius * 2 if self.glow_radius > 0 else 0
        
        self._load_icons()
        self._pre_render_states()
        
        # Track state
        self._current_state = -1
        self._needs_redraw = True
        
        # Backing
        self._backing = None
        self._backing_rect = None
    
    def _load_icons(self):
        """Load icon PNG files."""
        self._icons = []
        self._icon_sizes = []
        max_w, max_h = 0, 0
        
        for filename in self.icon_filenames:
            icon_path = os.path.join(self.base_path, self.meter_folder, filename)
            try:
                if os.path.exists(icon_path):
                    icon = pg.image.load(icon_path).convert_alpha()
                    self._icons.append(icon)
                    w, h = icon.get_size()
                    self._icon_sizes.append((w, h))
                    max_w = max(max_w, w)
                    max_h = max(max_h, h)
                else:
                    print(f"[IconIndicator] File not found: {icon_path}")
                    self._icons.append(None)
                    self._icon_sizes.append((0, 0))
            except Exception as e:
                print(f"[IconIndicator] Failed to load '{filename}': {e}")
                self._icons.append(None)
                self._icon_sizes.append((0, 0))
        
        self._max_size = (max_w, max_h)
    
    def _pre_render_states(self):
        """Pre-render icon + glow surface for each state."""
        self._surfaces = []
        
        total_w = self._max_size[0] + self._padding * 2
        total_h = self._max_size[1] + self._padding * 2
        
        for i, icon in enumerate(self._icons):
            if icon is None:
                self._surfaces.append(None)
                continue
            
            # Create surface for this state
            surf = pg.Surface((total_w, total_h), pg.SRCALPHA)
            surf.fill((0, 0, 0, 0))
            
            # Render glow first (behind icon)
            if self.glow_radius > 0 and self.glow_intensity > 0:
                glow_color = None
                if self.glow_colors and i < len(self.glow_colors):
                    glow_color = self.glow_colors[i]
                
                glow_surf = GlowEffect.create_icon_glow_surface(
                    icon, self.glow_radius, self.glow_intensity, glow_color
                )
                if glow_surf:
                    # Center glow in surface
                    gx = (total_w - glow_surf.get_width()) // 2
                    gy = (total_h - glow_surf.get_height()) // 2
                    surf.blit(glow_surf, (gx, gy))
            
            # Render icon centered
            icon_w, icon_h = icon.get_size()
            ix = (total_w - icon_w) // 2
            iy = (total_h - icon_h) // 2
            surf.blit(icon, (ix, iy))
            
            self._surfaces.append(surf)
    
    def get_rect(self):
        """Get bounding rectangle for this indicator."""
        if not self.pos or self._max_size == (0, 0):
            return None
        total_w = self._max_size[0] + self._padding * 2
        total_h = self._max_size[1] + self._padding * 2
        return pg.Rect(self.pos[0], self.pos[1], total_w, total_h)
    
    def capture_backing(self, screen):
        """Capture backing surface under indicator area."""
        rect = self.get_rect()
        if not rect:
            return
        
        self._backing_rect = rect.copy()
        try:
            self._backing = screen.subsurface(rect).copy()
        except Exception:
            self._backing = pg.Surface((rect.width, rect.height))
            self._backing.fill((0, 0, 0))
    
    def restore_backing(self, screen):
        """Restore backing surface to screen."""
        if self._backing and self._backing_rect:
            screen.blit(self._backing, self._backing_rect.topleft)
            return self._backing_rect.copy()
        return None
    
    def render(self, screen, state_index):
        """Render icon at specified state.
        
        :param screen: pygame screen surface
        :param state_index: integer index into icons list
        :return: dirty rect if drawn, None if skipped
        """
        if not self.pos or not self._surfaces:
            return None
        
        # Clamp state index
        state_index = max(0, min(len(self._surfaces) - 1, int(state_index)))
        
        # Check if state changed
        if state_index == self._current_state and not self._needs_redraw:
            return None
        
        self._current_state = state_index
        self._needs_redraw = False
        
        # Get surface for this state
        surf = self._surfaces[state_index]
        if surf is None:
            return None
        
        # Blit pre-rendered surface
        screen.blit(surf, self.pos)
        
        return self.get_rect()
    
    def force_redraw(self):
        """Force redraw on next render call."""
        self._needs_redraw = True


# =============================================================================
# VolumeIndicator - Renders volume display in various styles
# =============================================================================
class VolumeIndicator:
    """Renders volume level display.
    
    Styles:
    - numeric: text display "75%"
    - slider: horizontal bar
    - knob: rotary graphic (requires knob image)
    - arc: gauge/arc style
    """
    
    STYLE_NUMERIC = "numeric"
    STYLE_SLIDER = "slider"
    STYLE_KNOB = "knob"
    STYLE_ARC = "arc"
    
    def __init__(self, pos, dim, style, color, bg_color=None,
                 font=None, font_size=24, base_path=None, meter_folder=None,
                 knob_image=None, knob_angle_start=225.0, knob_angle_end=-45.0,
                 arc_width=6, arc_angle_start=225.0, arc_angle_end=-45.0):
        """Initialize volume indicator.
        
        :param pos: (x, y) screen position
        :param dim: (width, height) for slider/knob/arc
        :param style: 'numeric', 'slider', 'knob', 'arc'
        :param color: RGB tuple for foreground
        :param bg_color: RGB tuple for background (slider/arc)
        :param font: pygame font object (for numeric)
        :param font_size: font size if font not provided
        :param base_path: base path for knob image
        :param meter_folder: meter folder for knob image
        :param knob_image: filename for knob image (default: volume_knob.png)
        :param knob_angle_start: start angle in degrees (default: 225)
        :param knob_angle_end: end angle in degrees (default: -45)
        :param arc_width: arc stroke width in pixels (default: 6)
        :param arc_angle_start: arc start angle in degrees (default: 225)
        :param arc_angle_end: arc end angle in degrees (default: -45)
        """
        self.pos = pos
        self.dim = dim if dim else (100, 20)
        self.style = (style or self.STYLE_NUMERIC).lower()
        self.color = color if color else (255, 255, 255)
        self.bg_color = bg_color if bg_color else (40, 40, 40)
        self.font_size = font_size
        self.base_path = base_path
        self.meter_folder = meter_folder
        
        # Knob parameters
        self.knob_image_filename = knob_image if knob_image else "volume_knob.png"
        self.knob_angle_start = float(knob_angle_start)
        self.knob_angle_end = float(knob_angle_end)
        self.knob_angle_sweep = self.knob_angle_start - self.knob_angle_end
        
        # Arc parameters
        self.arc_width = max(1, int(arc_width))
        self.arc_angle_start = float(arc_angle_start)
        self.arc_angle_end = float(arc_angle_end)
        self.arc_angle_sweep = self.arc_angle_start - self.arc_angle_end
        
        # Font for numeric display
        if font:
            self.font = font
        else:
            try:
                self.font = pg.font.Font(None, font_size)
            except Exception:
                self.font = pg.font.SysFont(None, font_size)
        
        # Knob image (loaded if style is knob)
        self._knob_image = None
        self._knob_frames = None
        if self.style == self.STYLE_KNOB:
            self._load_knob_image()
        
        # State tracking
        self._current_volume = -1
        self._needs_redraw = True
        
        # Backing
        self._backing = None
        self._backing_rect = None
    
    def _load_knob_image(self):
        """Load knob image for rotary style."""
        if not self.base_path or not self.meter_folder:
            return
        
        knob_path = os.path.join(self.base_path, self.meter_folder, self.knob_image_filename)
        try:
            if os.path.exists(knob_path):
                self._knob_image = pg.image.load(knob_path).convert_alpha()
                # Pre-compute rotated frames (0-100 maps to angle sweep)
                self._knob_frames = []
                # Calculate the offset to center the knob rotation
                # knob_angle_start is where volume=0, knob_angle_end is where volume=100
                for v in range(101):
                    # Map 0-100 to angle_start to angle_end
                    angle = self.knob_angle_start - (v / 100.0) * self.knob_angle_sweep
                    # pygame rotation is CCW positive, 0=right
                    # Adjust so pointer points correctly
                    rotated = pg.transform.rotate(self._knob_image, angle)
                    self._knob_frames.append(rotated)
                print(f"[VolumeIndicator] Knob loaded: {self.knob_image_filename}, {len(self._knob_frames)} frames, sweep={self.knob_angle_sweep}")
            else:
                print(f"[VolumeIndicator] Knob image not found: {knob_path}")
        except Exception as e:
            print(f"[VolumeIndicator] Failed to load knob image: {e}")
    
    def get_rect(self):
        """Get bounding rectangle for this indicator."""
        if not self.pos:
            return None
        
        if self.style == self.STYLE_NUMERIC:
            # Estimate text size
            return pg.Rect(self.pos[0], self.pos[1], self.dim[0], self.font_size)
        else:
            return pg.Rect(self.pos[0], self.pos[1], self.dim[0], self.dim[1])
    
    def capture_backing(self, screen):
        """Capture backing surface under indicator area."""
        rect = self.get_rect()
        if not rect:
            return
        
        self._backing_rect = rect.copy()
        try:
            self._backing = screen.subsurface(rect).copy()
        except Exception:
            self._backing = pg.Surface((rect.width, rect.height))
            self._backing.fill((0, 0, 0))
    
    def restore_backing(self, screen):
        """Restore backing surface to screen."""
        if self._backing and self._backing_rect:
            screen.blit(self._backing, self._backing_rect.topleft)
            return self._backing_rect.copy()
        return None
    
    def render(self, screen, volume):
        """Render volume indicator.
        
        :param screen: pygame screen surface
        :param volume: 0-100 integer
        :return: dirty rect if drawn, None if skipped
        """
        if not self.pos:
            return None
        
        # Clamp volume
        volume = max(0, min(100, int(volume)))
        
        # Check if changed
        if volume == self._current_volume and not self._needs_redraw:
            return None
        
        self._current_volume = volume
        self._needs_redraw = False
        
        if self.style == self.STYLE_NUMERIC:
            return self._render_numeric(screen, volume)
        elif self.style == self.STYLE_SLIDER:
            return self._render_slider(screen, volume)
        elif self.style == self.STYLE_KNOB:
            return self._render_knob(screen, volume)
        elif self.style == self.STYLE_ARC:
            return self._render_arc(screen, volume)
        
        return None
    
    def _render_numeric(self, screen, volume):
        """Render numeric volume display."""
        text = f"{volume}%"
        surf = self.font.render(text, True, self.color)
        screen.blit(surf, self.pos)
        return pg.Rect(self.pos[0], self.pos[1], surf.get_width(), surf.get_height())
    
    def _render_slider(self, screen, volume):
        """Render horizontal slider bar."""
        x, y = self.pos
        w, h = self.dim
        
        # Background
        if self.bg_color:
            pg.draw.rect(screen, self.bg_color, (x, y, w, h))
        
        # Foreground fill based on volume
        fill_w = int((volume / 100.0) * w)
        if fill_w > 0:
            pg.draw.rect(screen, self.color, (x, y, fill_w, h))
        
        return pg.Rect(x, y, w, h)
    
    def _render_knob(self, screen, volume):
        """Render rotary knob."""
        if self._knob_frames and 0 <= volume <= 100:
            frame = self._knob_frames[volume]
            # Center knob in dim area
            fx = self.pos[0] + (self.dim[0] - frame.get_width()) // 2
            fy = self.pos[1] + (self.dim[1] - frame.get_height()) // 2
            screen.blit(frame, (fx, fy))
        else:
            # Fallback: draw simple arc
            return self._render_arc(screen, volume)
        
        return pg.Rect(self.pos[0], self.pos[1], self.dim[0], self.dim[1])
    
    def _render_arc(self, screen, volume):
        """Render arc/gauge style volume."""
        x, y = self.pos
        w, h = self.dim
        
        # Draw background arc (full sweep)
        rect = pg.Rect(x, y, w, h)
        if self.bg_color:
            pg.draw.arc(screen, self.bg_color, rect, 
                       math.radians(self.arc_angle_end), 
                       math.radians(self.arc_angle_start), 
                       self.arc_width)
        
        # Draw foreground arc based on volume
        # volume 0% = arc_angle_start, volume 100% = arc_angle_end
        if volume > 0:
            # Calculate end angle for current volume
            current_angle = self.arc_angle_start - (volume / 100.0) * self.arc_angle_sweep
            pg.draw.arc(screen, self.color, rect,
                       math.radians(current_angle), 
                       math.radians(self.arc_angle_start), 
                       self.arc_width)
        
        return rect
    
    def force_redraw(self):
        """Force redraw on next render call."""
        self._needs_redraw = True


# =============================================================================
# ProgressBar - Renders track progress bar
# =============================================================================
class ProgressBar:
    """Renders horizontal track progress bar."""
    
    def __init__(self, pos, dim, color, bg_color=None,
                 border_width=0, border_color=None):
        """Initialize progress bar.
        
        :param pos: (x, y) screen position
        :param dim: (width, height)
        :param color: RGB tuple for fill
        :param bg_color: RGB tuple for background
        :param border_width: pixels (0 = no border)
        :param border_color: RGB tuple for border
        """
        self.pos = pos
        self.dim = dim if dim else (200, 8)
        self.color = color if color else (0, 200, 255)
        self.bg_color = bg_color if bg_color else (40, 40, 40)
        self.border_width = max(0, int(border_width))
        self.border_color = border_color if border_color else (100, 100, 100)
        
        # State tracking
        self._current_progress = -1
        self._needs_redraw = True
        
        # Backing
        self._backing = None
        self._backing_rect = None
    
    def get_rect(self):
        """Get bounding rectangle for this indicator."""
        if not self.pos or not self.dim:
            return None
        return pg.Rect(self.pos[0], self.pos[1], self.dim[0], self.dim[1])
    
    def capture_backing(self, screen):
        """Capture backing surface under progress bar area."""
        rect = self.get_rect()
        if not rect:
            return
        
        self._backing_rect = rect.copy()
        try:
            self._backing = screen.subsurface(rect).copy()
        except Exception:
            self._backing = pg.Surface((rect.width, rect.height))
            self._backing.fill((0, 0, 0))
    
    def restore_backing(self, screen):
        """Restore backing surface to screen."""
        if self._backing and self._backing_rect:
            screen.blit(self._backing, self._backing_rect.topleft)
            return self._backing_rect.copy()
        return None
    
    def render(self, screen, progress_pct):
        """Render progress bar.
        
        :param screen: pygame screen surface
        :param progress_pct: 0.0-100.0 percentage
        :return: dirty rect if drawn, None if skipped
        """
        if not self.pos or not self.dim:
            return None
        
        # Quantize to 1% steps to reduce redraws
        progress_int = max(0, min(100, int(progress_pct)))
        
        # Check if changed
        if progress_int == self._current_progress and not self._needs_redraw:
            return None
        
        self._current_progress = progress_int
        self._needs_redraw = False
        
        x, y = self.pos
        w, h = self.dim
        
        # Background
        if self.bg_color:
            pg.draw.rect(screen, self.bg_color, (x, y, w, h))
        
        # Foreground fill based on progress
        fill_w = int((progress_pct / 100.0) * w)
        if fill_w > 0:
            pg.draw.rect(screen, self.color, (x, y, fill_w, h))
        
        # Border
        if self.border_width > 0 and self.border_color:
            pg.draw.rect(screen, self.border_color, (x, y, w, h), self.border_width)
        
        return self.get_rect()
    
    def force_redraw(self):
        """Force redraw on next render call."""
        self._needs_redraw = True


# =============================================================================
# IndicatorRenderer - Coordinator for all indicator elements
# =============================================================================
class IndicatorRenderer:
    """Main coordinator for all indicator elements.
    
    Manages volume, mute, shuffle, repeat, playstate, and progress indicators.
    Handles state change detection, backing capture/restore, and rendering.
    """
    
    def __init__(self, config, meter_config, base_path, meter_folder, fonts=None):
        """Initialize indicator renderer.
        
        :param config: parsed meter config dict (from meters.txt)
        :param meter_config: global volumio config dict
        :param base_path: base asset path
        :param meter_folder: current meter folder name
        :param fonts: dict of loaded pygame fonts (optional)
        """
        self.config = config
        self.meter_config = meter_config
        self.base_path = base_path
        self.meter_folder = meter_folder
        self.fonts = fonts if fonts else {}
        
        # Initialize individual indicators (None if not configured)
        self._volume = None
        self._mute = None
        self._shuffle = None
        self._repeat = None
        self._playstate = None
        self._progress = None
        
        # State tracking for change detection
        self._prev_volume = None
        self._prev_mute = None
        self._prev_shuffle = None
        self._prev_infinity = None
        self._prev_repeat = None
        self._prev_repeat_single = None
        self._prev_status = None
        self._prev_progress = None
        
        # Initialize indicators from config
        self._init_volume()
        self._init_mute()
        self._init_shuffle()
        self._init_repeat()
        self._init_playstate()
        self._init_progress()
    
    def _init_volume(self):
        """Initialize volume indicator from config."""
        pos = self.config.get("volume.pos")
        if not pos:
            return
        
        style = self.config.get("volume.style", "numeric")
        dim = self.config.get("volume.dim", (100, 20))
        color = self.config.get("volume.color", (255, 255, 255))
        bg_color = self.config.get("volume.bg.color")
        font_size = self.config.get("volume.font.size", 24)
        
        # Knob parameters
        knob_image = self.config.get("volume.knob.image")
        knob_angle_start = self.config.get("volume.knob.angle.start", 225.0)
        knob_angle_end = self.config.get("volume.knob.angle.end", -45.0)
        
        # Arc parameters
        arc_width = self.config.get("volume.arc.width", 6)
        arc_angle_start = self.config.get("volume.arc.angle.start", 225.0)
        arc_angle_end = self.config.get("volume.arc.angle.end", -45.0)
        
        # Get font from fonts dict if available
        font = self.fonts.get("regular") if self.fonts else None
        
        self._volume = VolumeIndicator(
            pos=pos,
            dim=dim,
            style=style,
            color=color,
            bg_color=bg_color,
            font=font,
            font_size=font_size,
            base_path=self.base_path,
            meter_folder=self.meter_folder,
            knob_image=knob_image,
            knob_angle_start=knob_angle_start,
            knob_angle_end=knob_angle_end,
            arc_width=arc_width,
            arc_angle_start=arc_angle_start,
            arc_angle_end=arc_angle_end
        )
    
    def _init_mute(self):
        """Initialize mute indicator from config."""
        pos = self.config.get("mute.pos")
        if not pos:
            return
        
        # Check for LED mode
        led_size = self.config.get("mute.led")
        if led_size:
            self._mute = LEDIndicator(
                pos=pos,
                size=led_size,
                shape=self.config.get("mute.led.shape", "circle"),
                colors=self.config.get("mute.led.color", [(255, 0, 0), (64, 64, 64)]),
                glow_radius=self.config.get("mute.led.glow", 0),
                glow_intensity=self.config.get("mute.led.glow.intensity", 0.5),
                glow_colors=self.config.get("mute.led.glow.color")
            )
            return
        
        # Check for icon mode
        icon_files = self.config.get("mute.icon")
        if icon_files:
            self._mute = IconIndicator(
                base_path=self.base_path,
                meter_folder=self.meter_folder,
                pos=pos,
                icon_filenames=icon_files,
                glow_radius=self.config.get("mute.icon.glow", 0),
                glow_intensity=self.config.get("mute.icon.glow.intensity", 0.5),
                glow_colors=self.config.get("mute.icon.glow.color")
            )
    
    def _init_shuffle(self):
        """Initialize shuffle indicator from config."""
        pos = self.config.get("shuffle.pos")
        if not pos:
            return
        
        # Check for LED mode
        led_size = self.config.get("shuffle.led")
        if led_size:
            self._shuffle = LEDIndicator(
                pos=pos,
                size=led_size,
                shape=self.config.get("shuffle.led.shape", "circle"),
                colors=self.config.get("shuffle.led.color", [(0, 200, 255), (64, 64, 64)]),
                glow_radius=self.config.get("shuffle.led.glow", 0),
                glow_intensity=self.config.get("shuffle.led.glow.intensity", 0.5),
                glow_colors=self.config.get("shuffle.led.glow.color")
            )
            return
        
        # Check for icon mode
        icon_files = self.config.get("shuffle.icon")
        if icon_files:
            self._shuffle = IconIndicator(
                base_path=self.base_path,
                meter_folder=self.meter_folder,
                pos=pos,
                icon_filenames=icon_files,
                glow_radius=self.config.get("shuffle.icon.glow", 0),
                glow_intensity=self.config.get("shuffle.icon.glow.intensity", 0.5),
                glow_colors=self.config.get("shuffle.icon.glow.color")
            )
    
    def _init_repeat(self):
        """Initialize repeat indicator from config (3 states)."""
        pos = self.config.get("repeat.pos")
        if not pos:
            return
        
        # Check for LED mode
        led_size = self.config.get("repeat.led")
        if led_size:
            self._repeat = LEDIndicator(
                pos=pos,
                size=led_size,
                shape=self.config.get("repeat.led.shape", "circle"),
                colors=self.config.get("repeat.led.color", [(64, 64, 64), (0, 255, 0), (255, 200, 0)]),
                glow_radius=self.config.get("repeat.led.glow", 0),
                glow_intensity=self.config.get("repeat.led.glow.intensity", 0.5),
                glow_colors=self.config.get("repeat.led.glow.color")
            )
            return
        
        # Check for icon mode
        icon_files = self.config.get("repeat.icon")
        if icon_files:
            self._repeat = IconIndicator(
                base_path=self.base_path,
                meter_folder=self.meter_folder,
                pos=pos,
                icon_filenames=icon_files,
                glow_radius=self.config.get("repeat.icon.glow", 0),
                glow_intensity=self.config.get("repeat.icon.glow.intensity", 0.5),
                glow_colors=self.config.get("repeat.icon.glow.color")
            )
    
    def _init_playstate(self):
        """Initialize play/pause/stop indicator from config (3 states)."""
        pos = self.config.get("playstate.pos")
        if not pos:
            return
        
        # Check for LED mode
        led_size = self.config.get("playstate.led")
        if led_size:
            self._playstate = LEDIndicator(
                pos=pos,
                size=led_size,
                shape=self.config.get("playstate.led.shape", "circle"),
                colors=self.config.get("playstate.led.color", [(64, 64, 64), (255, 200, 0), (0, 255, 0)]),
                glow_radius=self.config.get("playstate.led.glow", 0),
                glow_intensity=self.config.get("playstate.led.glow.intensity", 0.5),
                glow_colors=self.config.get("playstate.led.glow.color")
            )
            return
        
        # Check for icon mode
        icon_files = self.config.get("playstate.icon")
        if icon_files:
            self._playstate = IconIndicator(
                base_path=self.base_path,
                meter_folder=self.meter_folder,
                pos=pos,
                icon_filenames=icon_files,
                glow_radius=self.config.get("playstate.icon.glow", 0),
                glow_intensity=self.config.get("playstate.icon.glow.intensity", 0.5),
                glow_colors=self.config.get("playstate.icon.glow.color")
            )
    
    def _init_progress(self):
        """Initialize progress bar from config."""
        pos = self.config.get("progress.pos")
        dim = self.config.get("progress.dim")
        if not pos or not dim:
            return
        
        self._progress = ProgressBar(
            pos=pos,
            dim=dim,
            color=self.config.get("progress.color", (0, 200, 255)),
            bg_color=self.config.get("progress.bg.color", (40, 40, 40)),
            border_width=self.config.get("progress.border", 0),
            border_color=self.config.get("progress.border.color", (100, 100, 100))
        )
    
    def has_indicators(self):
        """Return True if any indicators are configured."""
        return any([
            self._volume, self._mute, self._shuffle,
            self._repeat, self._playstate, self._progress
        ])
    
    def capture_backings(self, screen):
        """Capture backing surfaces for all configured indicators."""
        if self._volume:
            self._volume.capture_backing(screen)
        if self._mute:
            self._mute.capture_backing(screen)
        if self._shuffle:
            self._shuffle.capture_backing(screen)
        if self._repeat:
            self._repeat.capture_backing(screen)
        if self._playstate:
            self._playstate.capture_backing(screen)
        if self._progress:
            self._progress.capture_backing(screen)
    
    def force_redraw_all(self):
        """Force redraw of all indicators."""
        if self._volume:
            self._volume.force_redraw()
        if self._mute:
            self._mute.force_redraw()
        if self._shuffle:
            self._shuffle.force_redraw()
        if self._repeat:
            self._repeat.force_redraw()
        if self._playstate:
            self._playstate.force_redraw()
        if self._progress:
            self._progress.force_redraw()
    
    def render(self, screen, metadata, dirty_rects):
        """Render all configured indicators.
        
        :param screen: pygame screen surface
        :param metadata: dict with volume, mute, random, repeat,
                         repeatSingle, status, seek, duration
        :param dirty_rects: list to append dirty rects
        """
        # Volume
        if self._volume:
            volume = metadata.get("volume", 0)
            if volume != self._prev_volume:
                self._volume.restore_backing(screen)
                rect = self._volume.render(screen, volume)
                if rect:
                    dirty_rects.append(rect)
                self._prev_volume = volume
        
        # Mute (2 states: off=0, on=1)
        if self._mute:
            mute = metadata.get("mute", False)
            if mute != self._prev_mute:
                self._mute.restore_backing(screen)
                state_idx = 1 if mute else 0
                rect = self._mute.render(screen, state_idx)
                if rect:
                    dirty_rects.append(rect)
                self._prev_mute = mute
        
        # Shuffle (3 states: off=0, shuffle=1, infinity=2)
        if self._shuffle:
            shuffle = metadata.get("random", False)
            infinity = metadata.get("infinity", False)
            if shuffle != self._prev_shuffle or infinity != self._prev_infinity:
                self._shuffle.restore_backing(screen)
                # State logic: infinity takes priority over shuffle
                if infinity:
                    state_idx = 2
                elif shuffle:
                    state_idx = 1
                else:
                    state_idx = 0
                rect = self._shuffle.render(screen, state_idx)
                if rect:
                    dirty_rects.append(rect)
                self._prev_shuffle = shuffle
                self._prev_infinity = infinity
        
        # Repeat (3 states: off=0, all=1, single=2)
        if self._repeat:
            repeat = metadata.get("repeat", False)
            repeat_single = metadata.get("repeatSingle", False)
            if repeat != self._prev_repeat or repeat_single != self._prev_repeat_single:
                self._repeat.restore_backing(screen)
                if repeat_single:
                    state_idx = 2
                elif repeat:
                    state_idx = 1
                else:
                    state_idx = 0
                rect = self._repeat.render(screen, state_idx)
                if rect:
                    dirty_rects.append(rect)
                self._prev_repeat = repeat
                self._prev_repeat_single = repeat_single
        
        # Play/Pause/Stop (3 states: stop=0, pause=1, play=2)
        if self._playstate:
            status = metadata.get("status", "stop")
            if status != self._prev_status:
                self._playstate.restore_backing(screen)
                if status == "play":
                    state_idx = 2
                elif status == "pause":
                    state_idx = 1
                else:
                    state_idx = 0
                rect = self._playstate.render(screen, state_idx)
                if rect:
                    dirty_rects.append(rect)
                self._prev_status = status
        
        # Progress bar
        if self._progress:
            duration = metadata.get("duration", 0) or 0
            seek = metadata.get("seek", 0) or 0
            if duration > 0:
                progress_pct = min(100.0, (seek / 1000.0 / duration) * 100.0)
            else:
                progress_pct = 0.0
            
            # Quantize to 1% steps to reduce redraws
            progress_quantized = int(progress_pct)
            if progress_quantized != self._prev_progress:
                self._progress.restore_backing(screen)
                rect = self._progress.render(screen, progress_pct)
                if rect:
                    dirty_rects.append(rect)
                self._prev_progress = progress_quantized
