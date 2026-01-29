# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Layer Composition System
#
# Eliminates backing restore collisions by rendering each component
# to its own layer surface. Compositor blits layers in z-order.
#
# LAYER ARCHITECTURE:
#   Z0: Background (static, on screen)
#   Z1: Reels (animated rotation)
#   Z2: Album art (changes on track)
#   Z3: [Meters - special, draws to screen via meter.run()]
#   Z4: Text (scrollers)
#   Z5: Indicators (volume, mute, shuffle, repeat, playstate, progress)
#   Z6: Meta (time, type icon, sample rate)
#   Z7: Foreground mask (static, on screen)
#
# Benefits:
#   - No backing restore needed (no collision possible)
#   - Explicit z-order control
#   - Only dirty layers re-composite
#   - Simpler render logic

import pygame as pg


# =============================================================================
# Layer - Individual render surface with dirty tracking
# =============================================================================
class Layer:
    """
    Single compositing layer with its own surface.
    
    Each layer:
    - Has transparent background (SRCALPHA)
    - Tracks dirty state
    - Can have restricted region (optimization)
    """
    
    def __init__(self, name, size, z_index, region=None):
        """
        Initialize layer.
        
        :param name: Layer identifier
        :param size: (width, height) tuple
        :param z_index: Compositing order (lower = behind)
        :param region: Optional pg.Rect limiting this layer's area
        """
        self.name = name
        self.z_index = z_index
        self.region = region  # If set, only this area is used
        
        # Create transparent surface
        if region:
            self.surface = pg.Surface((region.width, region.height), pg.SRCALPHA)
            self.pos = (region.x, region.y)
        else:
            self.surface = pg.Surface(size, pg.SRCALPHA)
            self.pos = (0, 0)
        
        # State
        self.dirty = True
        self.visible = True
        self._last_dirty_rect = None
    
    def clear(self, rect=None):
        """
        Clear layer to transparent.
        
        :param rect: Optional rect to clear (None = entire surface)
        """
        if rect:
            # Clear specific region
            self.surface.fill((0, 0, 0, 0), rect)
        else:
            # Clear entire surface
            self.surface.fill((0, 0, 0, 0))
        self.dirty = True
    
    def mark_dirty(self, rect=None):
        """Mark layer as needing re-composite."""
        self.dirty = True
        self._last_dirty_rect = rect
    
    def get_surface(self):
        """Get the layer surface for drawing."""
        return self.surface
    
    def get_rect(self):
        """Get layer bounding rect in screen coordinates."""
        if self.region:
            return self.region.copy()
        return pg.Rect(self.pos[0], self.pos[1], 
                       self.surface.get_width(), self.surface.get_height())


# =============================================================================
# LayerCompositor - Manages and composites all layers
# =============================================================================
class LayerCompositor:
    """
    Manages multiple layers and composites them to screen.
    
    Usage:
        compositor = LayerCompositor(screen, (1280, 720))
        compositor.add_layer("art", z_index=2, region=pg.Rect(100, 100, 200, 200))
        compositor.add_layer("overlay", z_index=5)
        
        # In render loop:
        art_surf = compositor.get_surface("art")
        art_surf.blit(album_image, (0, 0))
        compositor.mark_dirty("art")
        
        dirty_rects = compositor.composite()
    """
    
    def __init__(self, screen, size):
        """
        Initialize compositor.
        
        :param screen: Target pygame screen surface
        :param size: (width, height) of screen
        """
        self.screen = screen
        self.size = size
        self.layers = {}  # name -> Layer
        self._sorted_layers = []  # Sorted by z_index
        self._needs_full_composite = True
    
    def add_layer(self, name, z_index, region=None):
        """
        Add a new layer.
        
        :param name: Layer identifier
        :param z_index: Compositing order (lower = behind)
        :param region: Optional pg.Rect limiting layer area
        :return: The created Layer
        """
        layer = Layer(name, self.size, z_index, region)
        self.layers[name] = layer
        self._sorted_layers = sorted(self.layers.values(), key=lambda l: l.z_index)
        return layer
    
    def get_layer(self, name):
        """Get layer by name."""
        return self.layers.get(name)
    
    def get_surface(self, name):
        """Get layer's drawing surface."""
        layer = self.layers.get(name)
        return layer.surface if layer else None
    
    def clear_layer(self, name, rect=None):
        """Clear a layer to transparent."""
        layer = self.layers.get(name)
        if layer:
            layer.clear(rect)
    
    def mark_dirty(self, name, rect=None):
        """Mark a layer as needing re-composite."""
        layer = self.layers.get(name)
        if layer:
            layer.mark_dirty(rect)
    
    def mark_all_dirty(self):
        """Mark all layers as dirty (force full re-composite)."""
        for layer in self.layers.values():
            layer.dirty = True
        self._needs_full_composite = True
    
    def set_visible(self, name, visible):
        """Set layer visibility."""
        layer = self.layers.get(name)
        if layer:
            if layer.visible != visible:
                layer.visible = visible
                layer.dirty = True
    
    def composite(self, force=False):
        """
        Composite all dirty layers to screen.
        
        :param force: If True, composite all layers regardless of dirty state
        :return: List of dirty rects for display.update()
        """
        dirty_rects = []
        
        if force or self._needs_full_composite:
            # Full composite - blit all visible layers
            for layer in self._sorted_layers:
                if layer.visible:
                    self.screen.blit(layer.surface, layer.pos)
                    dirty_rects.append(layer.get_rect())
                layer.dirty = False
            self._needs_full_composite = False
        else:
            # Incremental composite - only dirty layers
            for layer in self._sorted_layers:
                if layer.visible and layer.dirty:
                    self.screen.blit(layer.surface, layer.pos)
                    dirty_rects.append(layer.get_rect())
                    layer.dirty = False
        
        return dirty_rects
    
    def composite_region(self, rect):
        """
        Composite all layers within a specific region.
        
        Useful when only part of screen needs update.
        
        :param rect: Region to composite
        :return: The rect for display.update()
        """
        for layer in self._sorted_layers:
            if not layer.visible:
                continue
            
            layer_rect = layer.get_rect()
            if not layer_rect.colliderect(rect):
                continue
            
            # Calculate overlap
            overlap = layer_rect.clip(rect)
            
            # Source rect in layer coordinates
            src_x = overlap.x - layer.pos[0]
            src_y = overlap.y - layer.pos[1]
            src_rect = pg.Rect(src_x, src_y, overlap.width, overlap.height)
            
            # Blit overlapping portion
            self.screen.blit(layer.surface, overlap.topleft, src_rect)
        
        return rect
    
    def cleanup(self):
        """Release all layer surfaces."""
        for layer in self.layers.values():
            layer.surface = None
        self.layers.clear()
        self._sorted_layers.clear()


# =============================================================================
# Helper functions for common patterns
# =============================================================================

def create_cassette_layers(compositor, screen_size, art_rect=None, 
                           reel_left_rect=None, reel_right_rect=None):
    """
    Create standard layer set for cassette handler.
    
    :param compositor: LayerCompositor instance
    :param screen_size: (width, height)
    :param art_rect: Album art region (optional optimization)
    :param reel_left_rect: Left reel region
    :param reel_right_rect: Right reel region
    """
    # Z1: Reels (can be region-optimized)
    if reel_left_rect or reel_right_rect:
        # Combined reel layer covering both
        if reel_left_rect and reel_right_rect:
            combined = reel_left_rect.union(reel_right_rect)
            compositor.add_layer("reels", z_index=1, region=combined)
        elif reel_left_rect:
            compositor.add_layer("reels", z_index=1, region=reel_left_rect)
        else:
            compositor.add_layer("reels", z_index=1, region=reel_right_rect)
    else:
        compositor.add_layer("reels", z_index=1)
    
    # Z2: Album art (region-optimized if known)
    compositor.add_layer("art", z_index=2, region=art_rect)
    
    # Z4: Text overlays (full screen for flexibility)
    compositor.add_layer("text", z_index=4)
    
    # Z5: Indicators
    compositor.add_layer("indicators", z_index=5)
    
    # Z6: Meta (time, type, sample)
    compositor.add_layer("meta", z_index=6)


# =============================================================================
# Debug utilities
# =============================================================================

_DEBUG_COMPOSITOR = False

def enable_compositor_debug(enabled=True):
    """Enable/disable compositor debug logging."""
    global _DEBUG_COMPOSITOR
    _DEBUG_COMPOSITOR = enabled

def _log_compositor(msg):
    """Log compositor debug message."""
    if _DEBUG_COMPOSITOR:
        print(f"[Compositor] {msg}")
