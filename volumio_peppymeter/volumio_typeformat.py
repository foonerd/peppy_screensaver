# Copyright 2025-2026 PeppyMeter for Volumio
# Shared format/type display helper (icon / text / both)
#
# Used by volumio_basic, volumio_cassette, and volumio_turntable.
# Handlers keep clear/dirty/force orchestration; this module builds surfaces.

import io
import os
import re

import pygame as pg

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
except Exception:
    CAIROSVG_AVAILABLE = False

VALID_TYPE_MODES = ("icon", "text", "both")
DEFAULT_TYPE_MODE = "icon"
VALID_TYPE_ALIGNS = ("left", "center", "right")
DEFAULT_TYPE_ALIGN = "center"
BOTH_GAP_PX = 3
VOLUMIO_STOCK_ICONS = "/volumio/http/www3/app/assets-common/format-icons"

# Normalize Volumio trackType variants to icon file keys (lowercase).
FORMAT_KEY_ALIASES = {
    "dab_radio": "dab",
    "dab_": "dab",
    "dab": "dab",
    "rtlsdr": "dab",
    "rtlsdr_radio": "dab",
    "fm_radio": "fm",
    "fm_": "fm",
    "fm": "fm",
    "webradio": "radio",
    "web_radio": "radio",
    "internet_radio": "radio",
    "tidal_connect": "tidal",
    "qobuz_connect": "qobuz",
    "spotify": "spotify",
    "spotify_connect": "spotify",
    "airplay": "airplay",
    "bluetooth": "bluetooth",
    "upnp": "upnp",
    "dlna": "upnp",
}

# Proper-case labels for services / sources. Codecs use UPPERCASE via fallback.
SERVICE_LABELS = {
    "tidal": "Tidal",
    "qobuz": "Qobuz",
    "spotify": "Spotify",
    "radio": "Webradio",
    "airplay": "AirPlay",
    "bluetooth": "Bluetooth",
    "upnp": "UPnP",
    "dab": "DAB",
    "fm": "FM",
    "cd": "CD",
}


def _set_color(surface, color):
    """Tint opaque pixels to color while preserving alpha (SVG icons)."""
    numpy_available = False
    try:
        import numpy  # noqa: F401
        numpy_available = True
    except ImportError:
        pass

    if numpy_available:
        try:
            r, g, b = color.r, color.g, color.b
            arr = pg.surfarray.pixels3d(surface)
            alpha = pg.surfarray.pixels_alpha(surface)
            mask = alpha > 0
            arr[mask] = [r, g, b]
            del arr
            del alpha
            return
        except Exception:
            pass

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


def normalize_format_key(track_type):
    """Normalize raw trackType to a lowercase icon/label key."""
    fmt = (track_type or "").strip().lower().replace(" ", "_")
    if fmt == "dsf":
        fmt = "dsd"

    # Strip signal-strength / non-alnum suffixes (e.g. dab_●◦◦◦◦ -> dab)
    fmt_clean = re.sub(r"[^a-z0-9_].*", "", fmt)
    if fmt_clean:
        fmt = fmt_clean

    return FORMAT_KEY_ALIASES.get(fmt, fmt)


def display_label_for_key(fmt_key):
    """Human label: UPPERCASE for codecs, proper case for known services."""
    if not fmt_key:
        return ""
    if fmt_key in SERVICE_LABELS:
        return SERVICE_LABELS[fmt_key]
    return fmt_key.upper()


def resolve_type_mode(mc_vol, global_config):
    """
    Precedence: valid meters.txt playinfo.type.mode ->
    valid config.txt [current] playinfo.type.mode -> icon.
    """
    mc_vol = mc_vol or {}
    global_config = global_config or {}
    for source in (mc_vol, global_config):
        raw = source.get("playinfo.type.mode")
        if raw is None:
            continue
        mode = str(raw).strip().lower()
        if mode in VALID_TYPE_MODES:
            return mode
    return DEFAULT_TYPE_MODE


def resolve_type_align(mc_vol):
    """
    meters.txt playinfo.type.align = left|center|right.

    Default center (wiki / current boxed behaviour). Does not inherit
    playinfo.align or playinfo.center. Meaningful only with a real type box;
    callers ignore align when type_has_real_dim is false.
    """
    mc_vol = mc_vol or {}
    raw = mc_vol.get("playinfo.type.align")
    if raw is None:
        return DEFAULT_TYPE_ALIGN
    align = str(raw).strip().lower()
    if align in VALID_TYPE_ALIGNS:
        return align
    return DEFAULT_TYPE_ALIGN


def align_blit_pos(type_rect, surf, align=DEFAULT_TYPE_ALIGN):
    """
    Blit origin for a surface already clipped to fit inside type_rect.

    left:   dx = type_rect.x
    center: dx = type_rect.x + (W - sw) // 2
    right:  dx = type_rect.x + max(0, W - sw)
    dy always vertically centered in the box.
    """
    if type_rect is None or surf is None:
        return None
    sw = surf.get_width()
    sh = surf.get_height()
    w = int(type_rect.width)
    h = int(type_rect.height)
    align = (align or DEFAULT_TYPE_ALIGN).strip().lower()
    if align not in VALID_TYPE_ALIGNS:
        align = DEFAULT_TYPE_ALIGN
    if align == "left":
        dx = type_rect.x
    elif align == "right":
        dx = type_rect.x + max(0, w - sw)
    else:
        dx = type_rect.x + (w - sw) // 2
    dy = type_rect.y + (h - sh) // 2
    return (dx, dy)


def is_real_type_dimension(dim):
    """
    True when playinfo.type.dimension is a usable box.

    False if omitted, non-positive, or the legacy 1,1 "no box" placeholder.
    """
    if dim is None:
        return False
    try:
        w, h = int(dim[0]), int(dim[1])
    except (TypeError, ValueError, IndexError):
        return False
    if w <= 0 or h <= 0:
        return False
    if w == 1 and h == 1:
        return False
    return True


def resolve_type_rect(pos, dim, mode, font=None):
    """
    Build the type clear/blit Rect, or None if type should not draw.

    icon / both: require a real dimension (missing or 1,1 -> no draw).
    text: real dimension keeps a fixed box (caller centers). Omitted or 1,1
    synthesizes a provisional rect at pos from font metrics (like time
    fields); callers update it from the rendered surface on draw.
    """
    if not pos:
        return None
    mode = (mode or DEFAULT_TYPE_MODE).strip().lower()
    if mode not in VALID_TYPE_MODES:
        mode = DEFAULT_TYPE_MODE

    try:
        x, y = int(pos[0]), int(pos[1])
    except (TypeError, ValueError, IndexError):
        return None

    if is_real_type_dimension(dim):
        return pg.Rect(x, y, int(dim[0]), int(dim[1]))

    if mode != "text":
        return None

    if font is not None:
        try:
            w = font.size("WEBRADIO")[0] + 4
            h = font.get_linesize()
            return pg.Rect(x, y, max(1, int(w)), max(1, int(h)))
        except Exception:
            pass
    return pg.Rect(x, y, 1, 1)


def type_clear_rect_for_surface(pos, surf):
    """Dirty/clear Rect at pos matching surface size (text without box)."""
    if not pos or surf is None:
        return None
    try:
        return pg.Rect(int(pos[0]), int(pos[1]), surf.get_width(), surf.get_height())
    except (TypeError, ValueError, IndexError):
        return None


def default_type_fontsize(samplerate_style_size, type_rect_height):
    """
    Font size when playinfo.type.fontsize is unset.

    With a real type box height: min(style size, max(10, 0.45 * height)).
    Without (None / non-positive / height 1 from 1,1): samplerate style size.
    """
    try:
        style_size = int(samplerate_style_size)
    except (TypeError, ValueError):
        style_size = 20
    style_size = max(1, style_size)
    if type_rect_height is None:
        return style_size
    try:
        rect_h = int(type_rect_height)
    except (TypeError, ValueError):
        return style_size
    if rect_h <= 1:
        return style_size
    return min(style_size, max(10, int(0.45 * rect_h)))


def resolve_type_fontsize(configured, samplerate_style_size, type_rect_height):
    """Return configured fontsize if valid, else default heuristic."""
    if configured is not None:
        try:
            value = int(configured)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return default_type_fontsize(samplerate_style_size, type_rect_height)


def load_sized_font(font_path, font_filename, size, bold=False):
    """Load the same face as samplerate text at a specific point size."""
    size = max(1, int(size))
    path = ""
    if font_path and font_filename:
        path = os.path.join(font_path.rstrip(os.sep), font_filename.lstrip(os.sep))
        if not os.path.exists(path):
            path = (font_path or "") + (font_filename or "")
    if path and os.path.exists(path):
        try:
            return pg.font.Font(path, size)
        except Exception:
            pass
    return pg.font.SysFont("DejaVuSans", size, bold=bool(bold))


def match_icon_name(names, basename):
    """Exact filename first, then the same name with different case.

    Volumio ships YouTube.svg. Linux will not open that as youtube.svg.
    """
    if not basename:
        return None
    if basename in names:
        return basename
    target = basename.lower()
    for name in names:
        if name.lower() == target:
            return name
    return None


def fit_icon_size(src_w, src_h, box_w, box_h):
    """Pixel size that fits src inside the box, keeping aspect ratio.

    Returns None when either side is not a positive size. A source smaller
    than the box is enlarged to meet the nearer edge, which is the existing
    icon behaviour.
    """
    try:
        src_w = int(src_w)
        src_h = int(src_h)
        box_w = int(box_w)
        box_h = int(box_h)
    except (TypeError, ValueError):
        return None
    if src_w <= 0 or src_h <= 0 or box_w <= 0 or box_h <= 0:
        return None
    scale = min(float(box_w) / float(src_w), float(box_h) / float(src_h))
    return (max(1, int(src_w * scale)), max(1, int(src_h * scale)))


def existing_icon_file(directory, basename):
    """Path to basename in directory, allowing YouTube.svg to satisfy youtube.svg."""
    if not directory or not basename:
        return None
    exact = os.path.join(directory, basename)
    if os.path.isfile(exact):
        return exact
    try:
        match = match_icon_name(os.listdir(directory), basename)
    except OSError:
        return None
    if not match:
        return None
    found = os.path.join(directory, match)
    if os.path.isfile(found):
        return found
    return None


def resolve_icon_path(fmt_key, skin_icons_dir, plugin_dir):
    """
    Resolution order:
      1. skin format-icons/{key}.png then .svg
      2. plugin-local format-icons/{key}.svg (all keys)
      3. Volumio stock SVG
    Filename match is case-insensitive. Returns a path that exists, or the
    stock path even when it is missing so the caller can fall back to text.
    """
    if not fmt_key:
        return None

    if skin_icons_dir:
        for ext in (".png", ".svg"):
            found = existing_icon_file(skin_icons_dir, fmt_key + ext)
            if found:
                return found

    if plugin_dir:
        found = existing_icon_file(
            os.path.join(plugin_dir, "format-icons"), fmt_key + ".svg"
        )
        if found:
            return found

    stock_dir = VOLUMIO_STOCK_ICONS
    found = existing_icon_file(stock_dir, fmt_key + ".svg")
    if found:
        return found
    return os.path.join(stock_dir, fmt_key + ".svg")


def _scale_to_box(img, box_w, box_h):
    """Scale surface to fit inside box; keep aspect ratio."""
    if img is None:
        return img
    new_size = fit_icon_size(img.get_width(), img.get_height(), box_w, box_h)
    if not new_size:
        return img
    if new_size == (img.get_width(), img.get_height()):
        return img
    try:
        return pg.transform.smoothscale(img, new_size)
    except Exception:
        return pg.transform.scale(img, new_size)


def _load_icon_surface(icon_path, box_w, box_h, type_color):
    """Load PNG/SVG icon into a pygame surface sized for box_w x box_h."""
    if not icon_path or not os.path.exists(icon_path):
        return None
    try:
        img = None
        is_svg = icon_path.lower().endswith(".svg")
        if is_svg and CAIROSVG_AVAILABLE and PIL_AVAILABLE:
            png_bytes = cairosvg.svg2png(
                url=icon_path, output_width=box_w, output_height=box_h
            )
            pil_img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
            img = pg.image.fromstring(pil_img.tobytes(), pil_img.size, "RGBA")
            img = img.convert_alpha()
            # svg2png can ignore output size on a large pt-based file such as
            # YouTube.svg (900 x 336). Fit again so the blit cannot exceed the box.
            img = _scale_to_box(img, box_w, box_h)
        elif is_svg and pg.version.ver.startswith("2"):
            img = pg.image.load(icon_path)
            img = _scale_to_box(img, box_w, box_h)
            img = img.convert_alpha()
        elif not is_svg:
            # Skin PNG: preserve authored colours (no tint)
            img = pg.image.load(icon_path).convert_alpha()
            img = _scale_to_box(img, box_w, box_h)
        if img and is_svg:
            _set_color(
                img, pg.Color(type_color[0], type_color[1], type_color[2])
            )
        return img
    except Exception as e:
        print(f"[TypeFormat] icon load error: {e}")
        return None


def _render_label(font, label, color):
    if not font or not label:
        return None
    try:
        return font.render(label, True, color)
    except Exception:
        return None


def _clip_text_surface(txt_surf, max_w):
    if txt_surf is None or max_w <= 0:
        return None
    if txt_surf.get_width() <= max_w:
        return txt_surf
    clipped = pg.Surface((max_w, txt_surf.get_height()), pg.SRCALPHA)
    clipped.blit(txt_surf, (0, 0))
    return clipped


def _clip_surface_to_box(surf, max_w, max_h):
    """Clip surface to max_w x max_h so paint stays inside the clear box."""
    if surf is None or max_w <= 0 or max_h <= 0:
        return None
    surf = _clip_text_surface(surf, max_w)
    if surf is None:
        return None
    if surf.get_height() <= max_h:
        return surf
    clipped = pg.Surface((surf.get_width(), max_h), pg.SRCALPHA)
    clipped.blit(surf, (0, 0))
    return clipped


def build_type_surface(
    track_type,
    mode,
    type_rect,
    type_color,
    font,
    skin_icons_dir,
    plugin_dir,
    clip_to_box=False,
):
    """
    Build a surface for the type area.

    Modes:
      icon  - icon (or full-label text fallback if missing)
      text  - label only
      both  - icon left, text right, 3px gap, text clipped

    Returns (surface, fmt_key) or (None, fmt_key).

    When clip_to_box is True (real type dimension), text / missing-icon text
    is clipped to type_rect so paint ⊆ clear. Callers then use
    align_blit_pos() inside the box. Mode both already builds a full-box
    surface. Text mode without a real box blits at type pos (top-left) and
    sizes the clear rect from the surface; leave clip_to_box False there.
    """
    fmt_key = normalize_format_key(track_type)
    if not fmt_key or not type_rect:
        return None, fmt_key

    mode = (mode or DEFAULT_TYPE_MODE).strip().lower()
    if mode not in VALID_TYPE_MODES:
        mode = DEFAULT_TYPE_MODE

    label = display_label_for_key(fmt_key)
    tw, th = int(type_rect.width), int(type_rect.height)

    if mode == "text":
        txt = _render_label(font, label, type_color)
        if clip_to_box and txt is not None:
            txt = _clip_surface_to_box(txt, tw, th)
        return txt, fmt_key

    if tw <= 0 or th <= 0:
        return None, fmt_key

    icon_path = resolve_icon_path(fmt_key, skin_icons_dir, plugin_dir)

    if mode == "icon":
        img = _load_icon_surface(icon_path, tw, th, type_color)
        if img is not None:
            return img, fmt_key
        # Missing icon: full label, sized by type font (caller aligns in box)
        txt = _render_label(font, label, type_color)
        if clip_to_box and txt is not None:
            txt = _clip_surface_to_box(txt, tw, th)
        return txt, fmt_key

    # mode == "both": icon left, text right inside type_rect
    icon_box = max(1, min(tw, th))
    img = _load_icon_surface(icon_path, icon_box, icon_box, type_color)
    txt = _render_label(font, label, type_color)

    if img is None and txt is None:
        return None, fmt_key
    if img is None:
        if clip_to_box and txt is not None:
            txt = _clip_surface_to_box(txt, tw, th)
        return txt, fmt_key
    if txt is None:
        return img, fmt_key

    out = pg.Surface((tw, th), pg.SRCALPHA)
    iy = (th - img.get_height()) // 2
    out.blit(img, (0, iy))
    text_x = img.get_width() + BOTH_GAP_PX
    max_text_w = tw - text_x
    txt = _clip_text_surface(txt, max_text_w)
    if txt is not None and max_text_w > 0:
        # Keep text inside box height (same paint ⊆ clear invariant)
        if txt.get_height() > th:
            txt = _clip_surface_to_box(txt, max_text_w, th)
        if txt is not None:
            ty = (th - txt.get_height()) // 2
            out.blit(txt, (text_x, ty))
    return out, fmt_key


def skin_format_icons_dir(config, base_path_key, screen_info_key, meter_folder_key):
    """Build <meter>/format-icons path from Peppy config dict; None on failure."""
    try:
        return os.path.join(
            config.get(base_path_key),
            config.get(screen_info_key)[meter_folder_key],
            "format-icons",
        )
    except Exception:
        return None


def make_type_font(global_config, mc_vol, sample_style, type_rect_height):
    """
    Build a pygame Font for type text using the samplerate style face and
    playinfo.type.fontsize (or the default heuristic when unset).

    Pass type_rect_height=None when there is no real type dimension so the
    default size is the samplerate style size (not 0.45 * 1).
    """
    from volumio_configfileparser import (
        FONT_PATH, FONT_LIGHT, FONT_REGULAR, FONT_BOLD, FONT_ITALIC,
        FONTSIZE_LIGHT, FONTSIZE_REGULAR, FONTSIZE_BOLD, FONTSIZE_ITALIC,
        FONT_STYLE_B, FONT_STYLE_R, FONT_STYLE_I,
        PLAY_TYPE_FONTSIZE,
    )

    global_config = global_config or {}
    mc_vol = mc_vol or {}
    style = (sample_style or "").strip().lower()

    if style == FONT_STYLE_B:
        samp_size = mc_vol.get(FONTSIZE_BOLD, 40)
        face = global_config.get(FONT_BOLD)
        bold = True
    elif style == FONT_STYLE_R:
        samp_size = mc_vol.get(FONTSIZE_REGULAR, 35)
        face = global_config.get(FONT_REGULAR)
        bold = False
    elif style == FONT_STYLE_I:
        samp_size = mc_vol.get(FONTSIZE_ITALIC, mc_vol.get(FONTSIZE_REGULAR, 35))
        face = global_config.get(FONT_ITALIC) or global_config.get(FONT_REGULAR)
        bold = False
    else:
        samp_size = mc_vol.get(FONTSIZE_LIGHT, 30)
        face = global_config.get(FONT_LIGHT)
        bold = False

    size = resolve_type_fontsize(
        mc_vol.get(PLAY_TYPE_FONTSIZE), samp_size, type_rect_height
    )
    font_path = global_config.get(FONT_PATH) or ""
    return load_sized_font(font_path, face, size, bold=bold)
