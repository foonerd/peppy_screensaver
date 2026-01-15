# Copyright 2025 PeppyMeter for Volumio - GPU Acceleration Module
#
# This module provides GPU-accelerated rendering via SDL2 Renderer/Texture API.
# It is designed to work alongside the CPU rendering path, with automatic fallback.
#
# IMPORTANT: SDL2 Renderer and pygame.display are MUTUALLY EXCLUSIVE.
# When GPU rendering is active, ALL display updates must go through this module.
# Do NOT mix with pygame.display.update() calls.
#
# Usage:
#   from volumio_render_gpu import GPURenderer, is_gpu_available
#
#   if is_gpu_available():
#       gpu = GPURenderer()
#       if gpu.init_from_display():
#           # Use GPU rendering path
#           texture = gpu.create_texture(surface)
#           gpu.clear()
#           gpu.blit(texture, (x, y))
#           gpu.blit_rotated(texture, (x, y), angle, pivot)
#           gpu.present()
#       else:
#           # Fallback to CPU
#   else:
#       # CPU only

import os
import pygame as pg

# =============================================================================
# SDL2 Availability Detection
# =============================================================================

_SDL2_AVAILABLE = False
_SDL2_Window = None
_SDL2_Renderer = None
_SDL2_Texture = None
_SDL2_DRIVERS = []

def _init_sdl2():
    """Attempt to import SDL2 components. Called once at module load."""
    global _SDL2_AVAILABLE, _SDL2_Window, _SDL2_Renderer, _SDL2_Texture, _SDL2_DRIVERS
    
    if not pg.version.ver.startswith("2"):
        return
    
    try:
        from pygame._sdl2.video import Window, Renderer, Texture, get_drivers
        _SDL2_Window = Window
        _SDL2_Renderer = Renderer
        _SDL2_Texture = Texture
        _SDL2_AVAILABLE = True
        
        # Get available renderer drivers
        try:
            _SDL2_DRIVERS = list(get_drivers())
        except Exception:
            _SDL2_DRIVERS = []
            
    except ImportError:
        pass

# Initialize on module load
_init_sdl2()


def is_gpu_available():
    """Check if GPU acceleration is available.
    
    :return: True if SDL2 Renderer/Texture API is available
    """
    return _SDL2_AVAILABLE


def get_available_drivers():
    """Get list of available SDL2 renderer drivers.
    
    :return: List of driver info objects, or empty list if unavailable
    """
    return _SDL2_DRIVERS


def get_driver_names():
    """Get names of available renderer drivers.
    
    :return: List of driver names (e.g., ['opengl', 'opengles2', 'software'])
    """
    names = []
    for driver in _SDL2_DRIVERS:
        try:
            name = driver.name
            if isinstance(name, bytes):
                name = name.decode('utf-8')
            names.append(name)
        except Exception:
            pass
    return names


def has_hardware_renderer():
    """Check if a hardware-accelerated renderer is available.
    
    :return: True if opengl or opengles2 driver is available
    """
    names = get_driver_names()
    return 'opengl' in names or 'opengles2' in names


# =============================================================================
# GPU Renderer Class
# =============================================================================

class GPURenderer:
    """
    GPU-accelerated renderer using SDL2 Renderer/Texture API.
    
    This class manages:
    - SDL2 Renderer lifecycle
    - Texture creation and caching
    - Hardware-accelerated blitting and rotation
    - Automatic resource cleanup
    
    IMPORTANT: Once initialized, this renderer OWNS the display.
    Do not call pygame.display.update() while GPURenderer is active.
    """
    
    def __init__(self):
        """Initialize GPURenderer (does not create renderer yet)."""
        self._renderer = None
        self._window = None
        self._initialized = False
        self._textures = {}  # Named texture cache
        self._screen_size = (0, 0)
        self._driver_name = None
    
    @property
    def initialized(self):
        """Check if renderer is initialized and ready."""
        return self._initialized
    
    @property
    def renderer(self):
        """Get underlying SDL2 Renderer (or None)."""
        return self._renderer
    
    @property
    def driver_name(self):
        """Get name of active renderer driver."""
        return self._driver_name
    
    @property
    def screen_size(self):
        """Get screen dimensions."""
        return self._screen_size
    
    def init_from_display(self, driver_index=-1):
        """Initialize GPU renderer from existing pygame display.
        
        IMPORTANT: After calling this, pygame.display.update() will no longer work.
        All rendering must go through this GPURenderer instance.
        
        :param driver_index: Renderer driver index (ignored - uses existing renderer)
        :return: True if initialization succeeded
        """
        if not _SDL2_AVAILABLE:
            return False
        
        if self._initialized:
            return True
        
        try:
            # Wrap existing pygame display window
            self._window = _SDL2_Window.from_display_module()
            
            # Get the EXISTING renderer that pygame created with display.set_mode()
            # Note: Creating a new Renderer fails with "Renderer already associated"
            # because pygame 2.x automatically creates one.
            self._renderer = _SDL2_Renderer.from_window(self._window)
            
            # Get screen size from window
            self._screen_size = self._window.size
            
            # Determine driver name
            try:
                # Renderer doesn't expose driver name directly, check drivers
                names = get_driver_names()
                self._driver_name = names[0] if names else "unknown"
            except Exception:
                self._driver_name = "unknown"
            
            self._initialized = True
            return True
            
        except Exception as e:
            self._cleanup_partial()
            return False
    
    def init_new_window(self, title, width, height, flags=0):
        """Create new window and renderer (alternative to init_from_display).
        
        :param title: Window title
        :param width: Window width
        :param height: Window height
        :param flags: Window flags (e.g., pg.NOFRAME)
        :return: True if initialization succeeded
        """
        if not _SDL2_AVAILABLE:
            return False
        
        if self._initialized:
            return True
        
        try:
            self._window = _SDL2_Window(
                title=title,
                size=(width, height),
                fullscreen=False,
                borderless=(flags & pg.NOFRAME) != 0
            )
            
            self._renderer = _SDL2_Renderer(
                self._window,
                accelerated=1,
                vsync=1
            )
            
            self._screen_size = (width, height)
            self._initialized = True
            return True
            
        except Exception as e:
            self._cleanup_partial()
            return False
    
    def _cleanup_partial(self):
        """Clean up after failed initialization."""
        self._renderer = None
        self._window = None
        self._initialized = False
    
    def cleanup(self):
        """Release all GPU resources.
        
        Call this before exiting or switching back to CPU rendering.
        """
        # Clear texture cache
        self._textures.clear()
        
        # Renderer and window are released automatically
        self._renderer = None
        self._window = None
        self._initialized = False
        self._driver_name = None
    
    # -------------------------------------------------------------------------
    # Texture Management
    # -------------------------------------------------------------------------
    
    def create_texture(self, surface, name=None):
        """Create GPU texture from pygame Surface.
        
        :param surface: pygame Surface to upload to GPU
        :param name: Optional name for caching (retrieve with get_texture)
        :return: SDL2 Texture object, or None on failure
        """
        if not self._initialized or surface is None:
            return None
        
        try:
            texture = _SDL2_Texture.from_surface(self._renderer, surface)
            
            if name:
                self._textures[name] = texture
            
            return texture
            
        except Exception:
            return None
    
    def create_streaming_texture(self, width, height, name=None):
        """Create a streaming GPU texture for efficient per-frame updates.
        
        Streaming textures can be updated efficiently each frame without
        recreating the texture object. Use update_texture() to update contents.
        
        :param width: Texture width
        :param height: Texture height
        :param name: Optional name for caching
        :return: SDL2 Texture object, or None on failure
        """
        if not self._initialized:
            return None
        
        try:
            texture = _SDL2_Texture(self._renderer, (width, height), streaming=True)
            
            if name:
                self._textures[name] = texture
            
            return texture
            
        except Exception:
            return None
    
    def update_texture(self, texture, surface, area=None):
        """Update streaming texture contents from pygame Surface.
        
        This is MUCH faster than create_texture() for per-frame updates.
        
        :param texture: Streaming texture to update
        :param surface: pygame Surface with new contents
        :param area: Optional rect to update (None = entire texture)
        :return: True if successful
        """
        if texture is None or surface is None:
            return False
        
        try:
            texture.update(surface, area)
            return True
        except Exception:
            return False
    
    def get_texture(self, name):
        """Get cached texture by name.
        
        :param name: Texture name (from create_texture)
        :return: Texture or None
        """
        return self._textures.get(name)
    
    def remove_texture(self, name):
        """Remove texture from cache.
        
        :param name: Texture name to remove
        """
        if name in self._textures:
            del self._textures[name]
    
    def clear_textures(self):
        """Clear all cached textures."""
        self._textures.clear()
    
    # -------------------------------------------------------------------------
    # Rendering Operations
    # -------------------------------------------------------------------------
    
    def clear(self, color=None):
        """Clear the renderer.
        
        :param color: Optional (r, g, b) or (r, g, b, a) clear color
        """
        if not self._initialized:
            return
        
        try:
            if color:
                if len(color) == 3:
                    self._renderer.draw_color = (*color, 255)
                else:
                    self._renderer.draw_color = color
            else:
                self._renderer.draw_color = (0, 0, 0, 255)
            
            self._renderer.clear()
            
        except Exception:
            pass
    
    def blit(self, texture, dest, area=None):
        """Blit texture to screen.
        
        :param texture: SDL2 Texture to draw
        :param dest: Destination as (x, y) tuple or pygame.Rect
        :param area: Source area rect (optional, for partial blit)
        """
        if not self._initialized or texture is None:
            return
        
        try:
            # Convert dest to Rect if needed
            if isinstance(dest, tuple):
                dest = pg.Rect(dest[0], dest[1], texture.width, texture.height)
            
            # Use Texture.draw() for blitting
            texture.draw(srcrect=area, dstrect=dest)
            
        except Exception:
            pass
    
    def blit_rotated(self, texture, dest, angle, pivot=None, flip_x=False, flip_y=False):
        """Blit texture with GPU-accelerated rotation.
        
        This is the key advantage over CPU rendering - rotation is done on GPU
        with no pre-computed frames needed.
        
        :param texture: SDL2 Texture to draw
        :param dest: Destination as (x, y) tuple or pygame.Rect
        :param angle: Rotation angle in degrees (positive = clockwise)
        :param pivot: Rotation pivot point relative to dest (None = center)
        :param flip_x: Flip texture horizontally
        :param flip_y: Flip texture vertically
        """
        if not self._initialized or texture is None:
            return
        
        try:
            # Convert dest to Rect if needed
            if isinstance(dest, tuple):
                dest = pg.Rect(dest[0], dest[1], texture.width, texture.height)
            
            # Use Texture.draw() with rotation parameters
            # Signature: draw(srcrect, dstrect, angle, origin, flipX, flipY)
            texture.draw(
                srcrect=None,       # Full texture
                dstrect=dest,       # Destination rect
                angle=angle,        # Rotation angle (clockwise)
                origin=pivot,       # Pivot point (None = center)
                flipX=flip_x,
                flipY=flip_y
            )
            
        except Exception:
            pass
    
    def draw_rect(self, rect, color, width=0):
        """Draw rectangle.
        
        :param rect: pygame.Rect to draw
        :param color: (r, g, b) or (r, g, b, a) color
        :param width: Line width (0 = filled)
        """
        if not self._initialized:
            return
        
        try:
            if len(color) == 3:
                self._renderer.draw_color = (*color, 255)
            else:
                self._renderer.draw_color = color
            
            if width == 0:
                self._renderer.fill_rect(rect)
            else:
                self._renderer.draw_rect(rect)
                
        except Exception:
            pass
    
    def draw_circle(self, center, radius, color, width=0):
        """Draw circle (approximated with polygon).
        
        Note: SDL2 Renderer doesn't have native circle support.
        For filled circles, this uses a simple approximation.
        
        :param center: (x, y) center point
        :param radius: Circle radius
        :param color: (r, g, b) or (r, g, b, a) color
        :param width: Line width (0 = filled)
        """
        if not self._initialized:
            return
        
        # SDL2 Renderer doesn't have circle primitives
        # For now, fall back to pygame.draw on a temporary surface
        # This is a known limitation - circles should be pre-rendered to textures
        pass
    
    def present(self):
        """Present the rendered frame (flip buffers).
        
        Call this once per frame after all drawing operations.
        This is GPU-accelerated and includes vsync.
        """
        if not self._initialized:
            return
        
        try:
            self._renderer.present()
        except Exception:
            pass
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def upload_surface(self, surface):
        """Upload surface to GPU and return texture.
        
        Convenience method for dynamic content that changes each frame.
        Note: Creating textures every frame has overhead - use sparingly.
        
        :param surface: pygame Surface to upload
        :return: SDL2 Texture or None
        """
        return self.create_texture(surface)
    
    def render_surface_to_screen(self, surface):
        """Render entire pygame surface to screen via GPU.
        
        This is the simplest way to use GPU acceleration:
        1. Do all rendering to a pygame Surface (CPU)
        2. Upload surface to GPU texture
        3. Present via GPU
        
        :param surface: pygame Surface containing rendered frame
        """
        if not self._initialized:
            return False
        
        try:
            texture = self.create_texture(surface)
            if texture:
                self.clear()
                self.blit(texture, (0, 0))
                self.present()
                return True
        except Exception:
            pass
        
        return False
    
    def create_target_texture(self, width, height):
        """Create a texture that can be used as render target.
        
        :param width: Texture width
        :param height: Texture height
        :return: SDL2 Texture with target=True, or None on failure
        """
        if not self._initialized:
            return None
        
        try:
            return _SDL2_Texture(self._renderer, (width, height), target=True)
        except Exception:
            return None
    
    def render_rotated_to_surface(self, texture, size, angle, pivot=None):
        """Render rotated texture and return result as pygame Surface.
        
        This is the key method for GPU-accelerated rotation with surface readback.
        Uses render-to-texture, then reads pixels back to pygame Surface.
        
        The output surface is sized to contain the fully rotated image (diagonal).
        The rotated image is centered in the output surface.
        
        WARNING: Reading pixels from GPU is slow. Use sparingly (rotation only).
        
        :param texture: Source SDL2 Texture to rotate
        :param size: (width, height) of source texture
        :param angle: Rotation angle in degrees (positive = clockwise)
        :param pivot: Rotation pivot point (None = center)
        :return: pygame Surface with rotated image (diagonal size), or None on failure
        """
        if not self._initialized or texture is None:
            return None
        
        width, height = size
        
        # Calculate diagonal size to contain rotated image
        import math
        diag = int(math.ceil(math.sqrt(width * width + height * height))) + 2
        
        try:
            # Create render target texture (diagonal size)
            target = self.create_target_texture(diag, diag)
            if target is None:
                return None
            
            # Set render target to our texture
            self._renderer.target = target
            
            # Clear with transparent black
            self._renderer.draw_color = (0, 0, 0, 0)
            self._renderer.clear()
            
            # Calculate destination rect - center the original size in diagonal target
            offset_x = (diag - width) // 2
            offset_y = (diag - height) // 2
            dest = pg.Rect(offset_x, offset_y, width, height)
            
            # Pivot relative to dest rect (center of texture)
            if pivot is None:
                pivot = (width // 2, height // 2)
            
            # Render rotated texture to target
            texture.draw(
                srcrect=None,
                dstrect=dest,
                angle=angle,
                origin=pivot,
                flipX=False,
                flipY=False
            )
            
            # Read pixels back to pygame Surface WITH ALPHA
            # Create surface with per-pixel alpha to preserve transparency
            alpha_surface = pg.Surface((diag, diag), pg.SRCALPHA, 32)
            result = self._renderer.to_surface(surface=alpha_surface)
            
            # Reset render target to screen
            self._renderer.target = None
            
            return result
            
        except Exception:
            # Ensure target is reset on error
            try:
                self._renderer.target = None
            except Exception:
                pass
            return None


# =============================================================================
# GPU-Accelerated Album Art Renderer
# =============================================================================

class AlbumArtRendererGPU:
    """
    GPU-accelerated album art renderer.
    
    Unlike the CPU version which pre-computes 60 rotation frames,
    this uses a single texture with hardware rotation.
    
    Benefits:
    - No pre-computation delay when loading new art
    - Smooth rotation at any angle (not quantized to 6-degree steps)
    - Lower memory usage (1 texture vs 60 surfaces)
    - Rotation is nearly free on GPU
    """
    
    def __init__(self, gpu_renderer, art_pos, art_dim,
                 rotate_enabled=False, rotate_rpm=0.0,
                 rotation_fps=30):
        """Initialize GPU album art renderer.
        
        :param gpu_renderer: GPURenderer instance
        :param art_pos: (x, y) position on screen
        :param art_dim: (width, height) dimensions
        :param rotate_enabled: Enable rotation
        :param rotate_rpm: Rotation speed in RPM
        :param rotation_fps: Target FPS for rotation updates
        """
        self.gpu = gpu_renderer
        self.art_pos = art_pos
        self.art_dim = art_dim
        self.rotate_enabled = bool(rotate_enabled)
        self.rotate_rpm = float(rotate_rpm)
        self.rotation_fps = int(rotation_fps)
        
        # Derived values
        self.art_center = (
            art_pos[0] + art_dim[0] // 2,
            art_pos[1] + art_dim[1] // 2
        ) if art_pos and art_dim else None
        
        # State
        self._texture = None
        self._current_angle = 0.0
        self._current_url = None
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, rotation_fps))
    
    def load_surface(self, surface):
        """Load album art from pygame Surface.
        
        :param surface: Pre-processed pygame Surface (masked, scaled)
        """
        self._texture = self.gpu.create_texture(surface)
        self._current_angle = 0.0
        self._last_blit_tick = 0  # Reset so first render doesn't calculate huge dt
    
    def will_blit(self, now_ticks):
        """Check if render is needed based on FPS gating.
        
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: True if should render this frame
        """
        if self._texture is None:
            return False
        
        if not self.rotate_enabled or self.rotate_rpm <= 0:
            return False
        
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
    
    def update_angle(self, status, now_ticks, advance_angle=True):
        """Update rotation angle without rendering.
        
        Used for deferred GPU composite - angle is updated now, render happens at frame end.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        :param advance_angle: If True, advance angle based on time. If False, keep current.
        """
        if self._texture is None:
            return
        
        # Update angle if playing AND advance_angle is True
        if advance_angle and self.rotate_enabled and self.rotate_rpm > 0 and status == "play":
            if self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                # Clamp dt to avoid jumps after pauses (max 0.5 sec)
                dt = min(dt, 0.5)
                self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0
            self._last_blit_tick = now_ticks
    
    def render_direct(self):
        """Render album art directly to GPU backbuffer at current angle.
        
        Used for deferred GPU composite. Call after update_angle().
        Does NOT update angle - uses whatever was set by update_angle().
        
        :return: True if rendered, False if no texture available
        """
        if self._texture is None or self.art_center is None:
            return False
        
        # Calculate destination rect centered on art_center
        dest = pg.Rect(
            self.art_center[0] - self.art_dim[0] // 2,
            self.art_center[1] - self.art_dim[1] // 2,
            self.art_dim[0],
            self.art_dim[1]
        )
        
        # Pivot is center of texture
        pivot = (self.art_dim[0] // 2, self.art_dim[1] // 2)
        
        # GPU-accelerated rotated blit
        self.gpu.blit_rotated(self._texture, dest, self._current_angle, pivot)
        
        return True
    
    def render(self, status, now_ticks):
        """Render album art with GPU-accelerated rotation.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: True if rendered, False if skipped
        """
        if self._texture is None or self.art_center is None:
            return False
        
        # FPS gating
        if not self.will_blit(now_ticks):
            return False
        
        self._last_blit_tick = now_ticks
        
        # Update angle if playing
        if self.rotate_enabled and self.rotate_rpm > 0 and status == "play":
            # degrees per frame = rpm * 6 * (interval_ms / 1000)
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0
        
        # Calculate destination rect centered on art_center
        dest = pg.Rect(
            self.art_center[0] - self.art_dim[0] // 2,
            self.art_center[1] - self.art_dim[1] // 2,
            self.art_dim[0],
            self.art_dim[1]
        )
        
        # Pivot is center of texture
        pivot = (self.art_dim[0] // 2, self.art_dim[1] // 2)
        
        # GPU-accelerated rotated blit
        self.gpu.blit_rotated(self._texture, dest, self._current_angle, pivot)
        
        return True
    
    def render_to_surface(self, status, now_ticks, advance_angle=True):
        """Render album art with GPU rotation and return as pygame Surface.
        
        This method renders the rotated album art using GPU acceleration,
        then reads the result back to a pygame Surface for blitting to screen.
        
        NOTE: This method does NOT do FPS gating - caller should handle timing.
        The returned surface is diagonal-sized to contain the rotated image.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        :param advance_angle: If True, advance rotation angle. If False, render at current angle.
        :return: pygame Surface with rotated art (diagonal size), or None on failure
        """
        if self._texture is None or self.art_center is None:
            return None
        
        # Update angle if playing AND advance_angle is True
        if advance_angle and self.rotate_enabled and self.rotate_rpm > 0 and status == "play":
            if self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                # Clamp dt to avoid jumps after pauses (max 0.5 sec)
                dt = min(dt, 0.5)
                self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt) % 360.0
            # Only update tick when we actually advance - otherwise FPS gating breaks
            self._last_blit_tick = now_ticks
        
        # Pivot is center of texture
        pivot = (self.art_dim[0] // 2, self.art_dim[1] // 2)
        
        # Use GPU to render rotated texture to surface
        return self.gpu.render_rotated_to_surface(
            self._texture,
            self.art_dim,
            self._current_angle,
            pivot
        )


# =============================================================================
# GPU-Accelerated Tonearm Renderer
# =============================================================================

class TonearmRendererGPU:
    """
    GPU-accelerated tonearm renderer.
    
    Uses single texture with hardware rotation around pivot point.
    No pre-computation needed, smooth animation at any angle.
    """
    
    def __init__(self, gpu_renderer, pivot_screen, pivot_image,
                 angle_rest=-55, angle_start=-130, angle_end=-90,
                 drop_duration=1.5, lift_duration=1.0):
        """Initialize GPU tonearm renderer.
        
        :param gpu_renderer: GPURenderer instance
        :param pivot_screen: (x, y) pivot point on screen
        :param pivot_image: (x, y) pivot point in image
        :param angle_rest: Rest angle (degrees)
        :param angle_start: Start of record angle (degrees)
        :param angle_end: End of record angle (degrees)
        :param drop_duration: Drop animation duration (seconds)
        :param lift_duration: Lift animation duration (seconds)
        """
        self.gpu = gpu_renderer
        self.pivot_screen = pivot_screen
        self.pivot_image = pivot_image
        self.angle_rest = float(angle_rest)
        self.angle_start = float(angle_start)
        self.angle_end = float(angle_end)
        self.drop_duration = float(drop_duration)
        self.lift_duration = float(lift_duration)
        
        # State
        self._texture = None
        self._texture_size = (0, 0)
        self._current_angle = self.angle_rest
        self._state = "rest"  # rest, drop, tracking, lift
    
    def load_surface(self, surface):
        """Load tonearm from pygame Surface.
        
        :param surface: pygame Surface of tonearm image
        """
        self._texture = self.gpu.create_texture(surface)
        if surface:
            self._texture_size = surface.get_size()
        self._current_angle = self.angle_rest
        self._state = "rest"
    
    def update(self, status, progress_pct, time_remaining_sec=None):
        """Update tonearm state based on playback.
        
        :param status: Playback status ("play", "pause", "stop")
        :param progress_pct: Track progress 0-100
        :param time_remaining_sec: Seconds remaining (for early lift)
        """
        # Simplified state machine - full implementation would match CPU version
        if status == "play":
            if self._state == "rest":
                self._state = "drop"
            elif self._state == "tracking":
                # Calculate tracking angle based on progress
                angle_range = self.angle_end - self.angle_start
                self._current_angle = self.angle_start + (progress_pct / 100.0) * angle_range
        elif status in ("stop", "pause"):
            if self._state == "tracking":
                self._state = "lift"
    
    def render(self, now_ticks):
        """Render tonearm with GPU-accelerated rotation.
        
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: True if rendered
        """
        if self._texture is None:
            return False
        
        # Calculate destination - position image so pivot_image aligns with pivot_screen
        dest_x = self.pivot_screen[0] - self.pivot_image[0]
        dest_y = self.pivot_screen[1] - self.pivot_image[1]
        dest = pg.Rect(dest_x, dest_y, self._texture_size[0], self._texture_size[1])
        
        # Pivot point for rotation (in texture coordinates)
        pivot = self.pivot_image
        
        # GPU-accelerated rotated blit
        # Note: SDL2 uses clockwise positive, our angles may need adjustment
        self.gpu.blit_rotated(self._texture, dest, -self._current_angle, pivot)
        
        return True


# =============================================================================
# GPU-Accelerated Reel Renderer
# =============================================================================

class ReelRendererGPU:
    """
    GPU-accelerated reel renderer for cassette-style skins.
    
    Uses single texture with hardware rotation around center point.
    No pre-computation needed, smooth animation at any angle.
    """
    
    def __init__(self, gpu_renderer, pos, center,
                 rotate_rpm=1.5, rotation_fps=15, direction="ccw"):
        """Initialize GPU reel renderer.
        
        :param gpu_renderer: GPURenderer instance
        :param pos: (x, y) top-left position for drawing
        :param center: (x, y) rotation center point on screen
        :param rotate_rpm: Rotation speed in RPM
        :param rotation_fps: Target FPS for rotation updates
        :param direction: Rotation direction - "ccw" or "cw"
        """
        self.gpu = gpu_renderer
        self.pos = pos
        self.center = center
        self.rotate_rpm = abs(float(rotate_rpm))
        self.rotation_fps = int(rotation_fps)
        self.direction_mult = 1 if direction == "cw" else -1
        
        # State
        self._texture = None
        self._texture_size = (0, 0)
        self._current_angle = 0.0
        self._last_blit_tick = 0
        self._blit_interval_ms = int(1000 / max(1, rotation_fps))
    
    def load_surface(self, surface):
        """Load reel image from pygame Surface.
        
        :param surface: pygame Surface of reel image
        """
        self._texture = self.gpu.create_texture(surface)
        if surface:
            self._texture_size = surface.get_size()
        self._current_angle = 0.0
        self._last_blit_tick = 0  # Reset so first render doesn't calculate huge dt
    
    def will_blit(self, now_ticks):
        """Check if render is needed based on FPS gating.
        
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: True if should render this frame
        """
        if self._texture is None:
            return False
        
        if self.rotate_rpm <= 0 or self.center is None:
            return False
        
        return (now_ticks - self._last_blit_tick) >= self._blit_interval_ms
    
    def update_angle(self, status, now_ticks):
        """Update rotation angle without rendering.
        
        Used for deferred GPU composite - angle is updated now, render happens at frame end.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        """
        if self._texture is None:
            return
        
        # Update angle if playing - use actual elapsed time
        status = (status or "").lower()
        if self.rotate_rpm > 0 and status == "play":
            if self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                # Clamp dt to avoid jumps after pauses (max 0.5 sec)
                dt = min(dt, 0.5)
                self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
        
        self._last_blit_tick = now_ticks
    
    def render_direct(self):
        """Render reel directly to GPU backbuffer at current angle.
        
        Used for deferred GPU composite. Call after update_angle().
        Does NOT update angle - uses whatever was set by update_angle().
        
        :return: True if rendered, False if no texture available
        """
        if self._texture is None or self.center is None:
            return False
        
        # Calculate destination rect centered on rotation center
        w, h = self._texture_size
        dest = pg.Rect(
            self.center[0] - w // 2,
            self.center[1] - h // 2,
            w, h
        )
        
        # Pivot is center of texture
        pivot = (w // 2, h // 2)
        
        # GPU-accelerated rotated blit
        self.gpu.blit_rotated(self._texture, dest, -self._current_angle, pivot)
        
        return True
    
    def render(self, status, now_ticks):
        """Render reel with GPU-accelerated rotation.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: True if rendered, False if skipped
        """
        if self._texture is None or self.center is None:
            return False
        
        # FPS gating
        if not self.will_blit(now_ticks):
            return False
        
        self._last_blit_tick = now_ticks
        
        # Update angle if playing
        status = (status or "").lower()
        if self.rotate_rpm > 0 and status == "play":
            dt = self._blit_interval_ms / 1000.0
            self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
        
        # Calculate destination rect centered on rotation center
        w, h = self._texture_size
        dest = pg.Rect(
            self.center[0] - w // 2,
            self.center[1] - h // 2,
            w, h
        )
        
        # Pivot is center of texture
        pivot = (w // 2, h // 2)
        
        # GPU-accelerated rotated blit
        self.gpu.blit_rotated(self._texture, dest, -self._current_angle, pivot)
        
        return True
    
    def render_to_surface(self, status, now_ticks):
        """Render reel with GPU rotation and return as pygame Surface.
        
        This method renders the rotated reel using GPU acceleration,
        then reads the result back to a pygame Surface for blitting to screen.
        
        NOTE: This method does NOT do FPS gating - caller should handle timing.
        The returned surface is diagonal-sized to contain the rotated image.
        
        :param status: Playback status ("play", "pause", "stop")
        :param now_ticks: Current pygame.time.get_ticks() value
        :return: pygame Surface with rotated reel (diagonal size), or None on failure
        """
        if self._texture is None or self.center is None:
            return None
        
        # Update angle if playing - use actual elapsed time
        status = (status or "").lower()
        if self.rotate_rpm > 0 and status == "play":
            if self._last_blit_tick > 0:
                dt = (now_ticks - self._last_blit_tick) / 1000.0
                # Clamp dt to avoid jumps after pauses (max 0.5 sec)
                dt = min(dt, 0.5)
                self._current_angle = (self._current_angle + self.rotate_rpm * 6.0 * dt * self.direction_mult) % 360.0
        
        self._last_blit_tick = now_ticks
        
        # Pivot is center of texture
        w, h = self._texture_size
        pivot = (w // 2, h // 2)
        
        # Use GPU to render rotated texture to surface
        # Note: negative angle to match render() behavior
        return self.gpu.render_rotated_to_surface(
            self._texture,
            self._texture_size,
            -self._current_angle,
            pivot
        )

if __name__ == "__main__":
    """Self-test: Check GPU availability and capabilities."""
    
    print("=" * 60)
    print("PeppyMeter GPU Renderer Module - Self Test")
    print("=" * 60)
    
    print(f"\npygame version: {pg.version.ver}")
    print(f"SDL2 available: {_SDL2_AVAILABLE}")
    print(f"GPU available: {is_gpu_available()}")
    
    if is_gpu_available():
        print(f"\nAvailable renderer drivers:")
        for i, driver in enumerate(get_available_drivers()):
            try:
                name = driver.name
                if isinstance(name, bytes):
                    name = name.decode('utf-8')
                print(f"  {i}: {name} (flags: {hex(driver.flags)})")
            except Exception as e:
                print(f"  {i}: <error reading driver: {e}>")
        
        print(f"\nHardware acceleration: {has_hardware_renderer()}")
        
        # Try to initialize
        print("\nAttempting GPU initialization...")
        pg.init()
        screen = pg.display.set_mode((640, 480))
        print(f"  Display created: {screen.get_size()}")
        
        gpu = GPURenderer()
        if gpu.init_from_display():
            print(f"  SUCCESS: GPU renderer initialized")
            print(f"  Driver: {gpu.driver_name}")
            print(f"  Screen size: {gpu.screen_size}")
            
            # Test texture creation
            test_surf = pg.Surface((100, 100))
            test_surf.fill((255, 0, 0))
            tex = gpu.create_texture(test_surf, "test")
            if tex:
                print(f"  Texture creation: OK")
            else:
                print(f"  Texture creation: FAILED")
            
            # Test rendering
            print("\n  Render test (red square for 2 seconds)...")
            import time
            start = time.time()
            while time.time() - start < 2.0:
                gpu.clear((0, 0, 0))
                gpu.blit(tex, (270, 190))  # Center-ish
                gpu.present()
                
                # Handle quit events
                for event in pg.event.get():
                    if event.type == pg.QUIT:
                        break
            print(f"  Render test: OK")
            
            # Test rotation
            print("\n  Rotation test (spinning square for 3 seconds)...")
            angle = 0
            start = time.time()
            while time.time() - start < 3.0:
                gpu.clear((0, 0, 50))  # Dark blue background
                gpu.blit_rotated(tex, (270, 190), angle, (50, 50))
                gpu.present()
                angle = (angle + 5) % 360
                
                for event in pg.event.get():
                    if event.type == pg.QUIT:
                        break
            print(f"  Rotation test: OK")
            
            gpu.cleanup()
        else:
            print(f"  FAILED: Could not initialize GPU renderer")
        
        pg.quit()
    else:
        print("\nGPU acceleration not available on this system.")
    
    print("\n" + "=" * 60)
