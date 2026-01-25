# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Rewritten 2025 for Volumio 4 / Bookworm (Python 3.11)
#
# This file is part of PeppyMeter for Volumio 

import os
from configparser import ConfigParser
from configfileparser import BASE_PATH, SCREEN_INFO, METER_FOLDER, FILE_CONFIG, FILE_METER_CONFIG, CURRENT, METER

METER_BKP = "meter"
FILE_CONFIG = "config.txt"
FILE_METER_CONFIG = "meters.txt"

RANDOM_TITLE = "random.change.title"
COLOR_DEPTH = "color.depth"
START_ANIMATION = "start.animation"
FONT_PATH = "font.path"
FONT_LIGHT = "font.light"
FONT_REGULAR = "font.regular"
FONT_BOLD = "font.bold"

POSITION_TYPE = "position.type"
POS_X = "position.x"
POS_Y = "position.y"

UPDATE_INTERVAL = "update.interval"

# Debug settings
DEBUG_LEVEL = "debug.level"

# Debug trace switches (only active when level=trace)
DEBUG_TRACE_METERS = "debug.trace.meters"
DEBUG_TRACE_SPECTRUM = "debug.trace.spectrum"
DEBUG_TRACE_VINYL = "debug.trace.vinyl"
DEBUG_TRACE_REEL_LEFT = "debug.trace.reel.left"
DEBUG_TRACE_REEL_RIGHT = "debug.trace.reel.right"
DEBUG_TRACE_TONEARM = "debug.trace.tonearm"
DEBUG_TRACE_ALBUMART = "debug.trace.albumart"
DEBUG_TRACE_SCROLLING = "debug.trace.scrolling"
DEBUG_TRACE_VOLUME = "debug.trace.volume"
DEBUG_TRACE_MUTE = "debug.trace.mute"
DEBUG_TRACE_SHUFFLE = "debug.trace.shuffle"
DEBUG_TRACE_REPEAT = "debug.trace.repeat"
DEBUG_TRACE_PLAYSTATE = "debug.trace.playstate"
DEBUG_TRACE_PROGRESS = "debug.trace.progress"
DEBUG_TRACE_METADATA = "debug.trace.metadata"
DEBUG_TRACE_SEEK = "debug.trace.seek"
DEBUG_TRACE_TIME = "debug.trace.time"
DEBUG_TRACE_INIT = "debug.trace.init"
DEBUG_TRACE_FADE = "debug.trace.fade"
DEBUG_TRACE_FRAME = "debug.trace.frame"

# List of all trace switch keys for iteration
DEBUG_TRACE_SWITCHES = [
    DEBUG_TRACE_METERS, DEBUG_TRACE_SPECTRUM, DEBUG_TRACE_VINYL, DEBUG_TRACE_REEL_LEFT, DEBUG_TRACE_REEL_RIGHT,
    DEBUG_TRACE_TONEARM, DEBUG_TRACE_ALBUMART, DEBUG_TRACE_SCROLLING,
    DEBUG_TRACE_VOLUME, DEBUG_TRACE_MUTE, DEBUG_TRACE_SHUFFLE, DEBUG_TRACE_REPEAT,
    DEBUG_TRACE_PLAYSTATE, DEBUG_TRACE_PROGRESS,
    DEBUG_TRACE_METADATA, DEBUG_TRACE_SEEK, DEBUG_TRACE_TIME,
    DEBUG_TRACE_INIT, DEBUG_TRACE_FADE, DEBUG_TRACE_FRAME
]

TRANSITION_TYPE = "transition.type"
TRANSITION_DURATION = "transition.duration"
TRANSITION_COLOR = "transition.color"
TRANSITION_OPACITY = "transition.opacity"

# Rotation settings (global)
ROTATION_QUALITY = "rotation.quality"
ROTATION_FPS = "rotation.fps"
ROTATION_SPEED = "rotation.speed"
REEL_DIRECTION = "reel.direction"
SPOOL_LEFT_SPEED = "spool.left.speed"
SPOOL_RIGHT_SPEED = "spool.right.speed"

EXTENDED_CONF = "config.extend"
METER_VISIBLE = "meter.visible"
ALBUMART_POS = "albumart.pos"
ALBUMART_DIM = "albumart.dimension"
ALBUMART_MSK = "albumart.mask"
ALBUMBORDER = "albumart.border"
ALBUMART_ROT = "albumart.rotation"
ALBUMART_ROT_SPEED = "albumart.rotation.speed"

# Reel configuration constants (for cassette skins)
REEL_LEFT_FILE = "reel.left.filename"
REEL_LEFT_POS = "reel.left.pos"
REEL_LEFT_CENTER = "reel.left.center"
REEL_RIGHT_FILE = "reel.right.filename"
REEL_RIGHT_POS = "reel.right.pos"
REEL_RIGHT_CENTER = "reel.right.center"
REEL_ROTATION_SPEED = "reel.rotation.speed"

# Vinyl configuration constants (for turntable skins)
VINYL_FILE = "vinyl.filename"
VINYL_POS = "vinyl.pos"
VINYL_CENTER = "vinyl.center"
VINYL_DIRECTION = "vinyl.direction"

# Tonearm configuration constants (for turntable skins)
TONEARM_FILE = "tonearm.filename"
TONEARM_PIVOT_SCREEN = "tonearm.pivot.screen"
TONEARM_PIVOT_IMAGE = "tonearm.pivot.image"
TONEARM_ANGLE_REST = "tonearm.angle.rest"
TONEARM_ANGLE_START = "tonearm.angle.start"
TONEARM_ANGLE_END = "tonearm.angle.end"
TONEARM_DROP_DURATION = "tonearm.drop.duration"
TONEARM_LIFT_DURATION = "tonearm.lift.duration"

# Indicator configuration constants (state display elements)
# Volume indicator
VOLUME_POS = "volume.pos"
VOLUME_STYLE = "volume.style"
VOLUME_DIM = "volume.dim"
VOLUME_COLOR = "volume.color"
VOLUME_BG_COLOR = "volume.bg.color"
VOLUME_FONT_SIZE = "volume.font.size"
# Volume knob style parameters
VOLUME_KNOB_IMAGE = "volume.knob.image"
VOLUME_KNOB_ANGLE_START = "volume.knob.angle.start"
VOLUME_KNOB_ANGLE_END = "volume.knob.angle.end"
# Volume arc style parameters
VOLUME_ARC_WIDTH = "volume.arc.width"
VOLUME_ARC_ANGLE_START = "volume.arc.angle.start"
VOLUME_ARC_ANGLE_END = "volume.arc.angle.end"
# Volume slider style parameters (image-based)
VOLUME_SLIDER_TRACK = "volume.slider.track"
VOLUME_SLIDER_TIP = "volume.slider.tip"
VOLUME_SLIDER_ORIENTATION = "volume.slider.orientation"
VOLUME_SLIDER_TRAVEL = "volume.slider.travel"
VOLUME_SLIDER_TIP_OFFSET = "volume.slider.tip.offset"

# Mute indicator
MUTE_POS = "mute.pos"
MUTE_ICON = "mute.icon"
MUTE_LED = "mute.led"
MUTE_LED_SHAPE = "mute.led.shape"
MUTE_LED_COLOR = "mute.led.color"
MUTE_LED_GLOW = "mute.led.glow"
MUTE_LED_GLOW_INTENSITY = "mute.led.glow.intensity"
MUTE_LED_GLOW_COLOR = "mute.led.glow.color"
MUTE_ICON_GLOW = "mute.icon.glow"
MUTE_ICON_GLOW_INTENSITY = "mute.icon.glow.intensity"
MUTE_ICON_GLOW_COLOR = "mute.icon.glow.color"

# Shuffle indicator
SHUFFLE_POS = "shuffle.pos"
SHUFFLE_ICON = "shuffle.icon"
SHUFFLE_LED = "shuffle.led"
SHUFFLE_LED_SHAPE = "shuffle.led.shape"
SHUFFLE_LED_COLOR = "shuffle.led.color"
SHUFFLE_LED_GLOW = "shuffle.led.glow"
SHUFFLE_LED_GLOW_INTENSITY = "shuffle.led.glow.intensity"
SHUFFLE_LED_GLOW_COLOR = "shuffle.led.glow.color"
SHUFFLE_ICON_GLOW = "shuffle.icon.glow"
SHUFFLE_ICON_GLOW_INTENSITY = "shuffle.icon.glow.intensity"
SHUFFLE_ICON_GLOW_COLOR = "shuffle.icon.glow.color"

# Repeat indicator
REPEAT_POS = "repeat.pos"
REPEAT_ICON = "repeat.icon"
REPEAT_LED = "repeat.led"
REPEAT_LED_SHAPE = "repeat.led.shape"
REPEAT_LED_COLOR = "repeat.led.color"
REPEAT_LED_GLOW = "repeat.led.glow"
REPEAT_LED_GLOW_INTENSITY = "repeat.led.glow.intensity"
REPEAT_LED_GLOW_COLOR = "repeat.led.glow.color"
REPEAT_ICON_GLOW = "repeat.icon.glow"
REPEAT_ICON_GLOW_INTENSITY = "repeat.icon.glow.intensity"
REPEAT_ICON_GLOW_COLOR = "repeat.icon.glow.color"

# Play/Pause/Stop indicator
PLAYSTATE_POS = "playstate.pos"
PLAYSTATE_ICON = "playstate.icon"
PLAYSTATE_LED = "playstate.led"
PLAYSTATE_LED_SHAPE = "playstate.led.shape"
PLAYSTATE_LED_COLOR = "playstate.led.color"
PLAYSTATE_LED_GLOW = "playstate.led.glow"
PLAYSTATE_LED_GLOW_INTENSITY = "playstate.led.glow.intensity"
PLAYSTATE_LED_GLOW_COLOR = "playstate.led.glow.color"
PLAYSTATE_ICON_GLOW = "playstate.icon.glow"
PLAYSTATE_ICON_GLOW_INTENSITY = "playstate.icon.glow.intensity"
PLAYSTATE_ICON_GLOW_COLOR = "playstate.icon.glow.color"

# Progress bar
PROGRESS_POS = "progress.pos"
PROGRESS_DIM = "progress.dim"
PROGRESS_COLOR = "progress.color"
PROGRESS_BG_COLOR = "progress.bg.color"
PROGRESS_BORDER = "progress.border"
PROGRESS_BORDER_COLOR = "progress.border.color"

PLAY_TXT_CENTER = "playinfo.text.center"
PLAY_TITLE_POS = "playinfo.title.pos"
PLAY_TITLE_COLOR = "playinfo.title.color"
PLAY_TITLE_MAX = "playinfo.title.maxwidth"
PLAY_ARTIST_POS = "playinfo.artist.pos"
PLAY_ARTIST_COLOR = "playinfo.artist.color"
PLAY_ARTIST_MAX = "playinfo.artist.maxwidth"
PLAY_ALBUM_POS = "playinfo.album.pos"
PLAY_ALBUM_COLOR = "playinfo.album.color"
PLAY_ALBUM_MAX = "playinfo.album.maxwidth"
PLAY_TITLE_STYLE = "PLAY_TITLE_STYLE"
PLAY_ARTIST_STYLE = "PLAY_ARTIST_STYLE"
PLAY_ALBUM_STYLE = "PLAY_ALBUM_STYLE"
PLAY_CENTER = "playinfo.center"
PLAY_MAX = "playinfo.maxwidth"
SCROLLING_SPEED = "playinfo.scrolling.speed"
SCROLLING_SPEED_ARTIST = "playinfo.scrolling.speed.artist"
SCROLLING_SPEED_TITLE = "playinfo.scrolling.speed.title"
SCROLLING_SPEED_ALBUM = "playinfo.scrolling.speed.album"
PLAY_TYPE_POS = "playinfo.type.pos"
PLAY_TYPE_COLOR = "playinfo.type.color"
PLAY_TYPE_DIM = "playinfo.type.dimension"
PLAY_SAMPLE_POS = "playinfo.samplerate.pos"
PLAY_SAMPLE_STYLE = "PLAY_SAMPLE_STYLE"
PLAY_SAMPLE_MAX = "playinfo.samplerate.maxwidth"
TIME_REMAINING_POS = "time.remaining.pos"
TIMECOLOR = "time.remaining.color" 
FONT_STYLE_B = "bold"
FONT_STYLE_R = "regular"
FONT_STYLE_L = "light"
FONTSIZE_LIGHT = "font.size.light"
FONTSIZE_REGULAR = "font.size.regular"
FONTSIZE_BOLD = "font.size.bold"
FONTSIZE_DIGI = "font.size.digi"
FONTCOLOR = "font.color"

SPECTRUM_VISIBLE = "spectrum.visible"
SPECTRUM = "spectrum.name"
SPECTRUM_SIZE = "spectrum.size"
SPECTRUM_POS = "spectrum.pos"

class Volumio_ConfigFileParser(object):
    """ Configuration file parser """
    
    def __init__(self, util):
        """ Initializer """  

        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_path = os.path.join(self.meter_config[BASE_PATH], self.meter_config[SCREEN_INFO][METER_FOLDER], FILE_METER_CONFIG)              
        self.meter_config_volumio = {}
        c = ConfigParser()

        peppy_meter_path = os.path.join(os.getcwd(), FILE_CONFIG)        
        c.read(peppy_meter_path)

        try:    
            self.meter_config_volumio[RANDOM_TITLE] = c.getboolean(CURRENT, RANDOM_TITLE)
        except:
            self.meter_config_volumio[RANDOM_TITLE] = False                
        try:
            self.meter_config_volumio[COLOR_DEPTH] = c.getint(CURRENT, COLOR_DEPTH)
        except:
            self.meter_config_volumio[COLOR_DEPTH] = 32
        try:    
            self.meter_config_volumio[START_ANIMATION] = c.getboolean(CURRENT, START_ANIMATION)
        except:
            self.meter_config_volumio[START_ANIMATION] = False
        try:
            self.meter_config_volumio[POSITION_TYPE] = c.get(CURRENT, POSITION_TYPE)
        except:
            self.meter_config_volumio[POSITION_TYPE] = "center"
        try:
            self.meter_config_volumio[POS_X] = c.getint(CURRENT, POS_X)
        except:
            self.meter_config_volumio[POS_X] = 0
        try:
            self.meter_config_volumio[POS_Y] = c.getint(CURRENT, POS_Y)
        except:
            self.meter_config_volumio[POS_Y] = 0

        try:
            self.meter_config_volumio[UPDATE_INTERVAL] = c.getint(CURRENT, UPDATE_INTERVAL)
        except:
            self.meter_config_volumio[UPDATE_INTERVAL] = 2

        try:
            self.meter_config_volumio[TRANSITION_TYPE] = c.get(CURRENT, TRANSITION_TYPE)
        except:
            self.meter_config_volumio[TRANSITION_TYPE] = "fade"
        try:
            self.meter_config_volumio[TRANSITION_DURATION] = c.getfloat(CURRENT, TRANSITION_DURATION)
        except:
            self.meter_config_volumio[TRANSITION_DURATION] = 0.5
        try:
            self.meter_config_volumio[TRANSITION_COLOR] = c.get(CURRENT, TRANSITION_COLOR)
        except:
            self.meter_config_volumio[TRANSITION_COLOR] = "black"
        try:
            self.meter_config_volumio[TRANSITION_OPACITY] = c.getint(CURRENT, TRANSITION_OPACITY)
        except:
            self.meter_config_volumio[TRANSITION_OPACITY] = 100

        # Debug settings
        try:
            self.meter_config_volumio[DEBUG_LEVEL] = c.get(CURRENT, DEBUG_LEVEL)
        except:
            self.meter_config_volumio[DEBUG_LEVEL] = "off"

        # Debug trace switches (all default to False)
        for trace_key in DEBUG_TRACE_SWITCHES:
            try:
                self.meter_config_volumio[trace_key] = c.getboolean(CURRENT, trace_key)
            except:
                self.meter_config_volumio[trace_key] = False

        # Rotation settings (global)
        try:
            self.meter_config_volumio[ROTATION_QUALITY] = c.get(CURRENT, ROTATION_QUALITY)
        except:
            self.meter_config_volumio[ROTATION_QUALITY] = "medium"
        try:
            self.meter_config_volumio[ROTATION_FPS] = c.getint(CURRENT, ROTATION_FPS)
        except:
            self.meter_config_volumio[ROTATION_FPS] = 8
        try:
            self.meter_config_volumio[ROTATION_SPEED] = c.getfloat(CURRENT, ROTATION_SPEED)
        except:
            self.meter_config_volumio[ROTATION_SPEED] = 1.0
        try:
            self.meter_config_volumio[REEL_DIRECTION] = c.get(CURRENT, REEL_DIRECTION)
        except:
            self.meter_config_volumio[REEL_DIRECTION] = "ccw"
        try:
            self.meter_config_volumio[SPOOL_LEFT_SPEED] = c.getfloat(CURRENT, SPOOL_LEFT_SPEED)
        except:
            self.meter_config_volumio[SPOOL_LEFT_SPEED] = 1.0
        try:
            self.meter_config_volumio[SPOOL_RIGHT_SPEED] = c.getfloat(CURRENT, SPOOL_RIGHT_SPEED)
        except:
            self.meter_config_volumio[SPOOL_RIGHT_SPEED] = 1.0

        # Scrolling settings (global)
        try:
            self.meter_config_volumio["scrolling.mode"] = c.get(CURRENT, "scrolling.mode")
        except:
            self.meter_config_volumio["scrolling.mode"] = "skin"
        try:
            self.meter_config_volumio["scrolling.speed.artist"] = c.getint(CURRENT, "scrolling.speed.artist")
        except:
            self.meter_config_volumio["scrolling.speed.artist"] = 40
        try:
            self.meter_config_volumio["scrolling.speed.title"] = c.getint(CURRENT, "scrolling.speed.title")
        except:
            self.meter_config_volumio["scrolling.speed.title"] = 40
        try:
            self.meter_config_volumio["scrolling.speed.album"] = c.getint(CURRENT, "scrolling.speed.album")
        except:
            self.meter_config_volumio["scrolling.speed.album"] = 40

        try:
            self.meter_config_volumio[FONT_PATH] = c.get(CURRENT, FONT_PATH)
        except:
            self.meter_config_volumio[FONT_PATH] = None
        try:
            self.meter_config_volumio[FONT_LIGHT] = c.get(CURRENT, FONT_LIGHT)
        except:
            self.meter_config_volumio[FONT_LIGHT] = None
        try:
            self.meter_config_volumio[FONT_REGULAR] = c.get(CURRENT, FONT_REGULAR)
        except:
            self.meter_config_volumio[FONT_REGULAR] = None
        try:    
            self.meter_config_volumio[FONT_BOLD] = c.get(CURRENT, FONT_BOLD)
        except:
            self.meter_config_volumio[FONT_BOLD] = None
        try:
            self.meter_config_volumio[METER_BKP] = self.meter_config[METER]
        except:
            self.meter_config_volumio[METER_BKP] = None
            

        c = ConfigParser()
        c.read(self.meter_config_path)
        
        for section in c.sections():
            self.meter_config_volumio[section] = self.get_common_options(c, section)
        
        
    def get_common_options(self, config_file, section):
        """ Parser for the common section of the configuration file
        
        :param config_file: configuration file
        :param section: section name
        """
        d = {}
        try:
            d[EXTENDED_CONF] = config_file.getboolean(section, EXTENDED_CONF)
        except:
            d[EXTENDED_CONF] = False
        try:
            d[METER_VISIBLE] = config_file.getboolean(section, METER_VISIBLE)
        except:
            d[METER_VISIBLE] = True
        try:
            spl = config_file.get(section, ALBUMART_POS).split(',')
            d[ALBUMART_POS] =  (int(spl[0]), int(spl[1]))
        except:
            d[ALBUMART_POS] = None
        try:
            spl = config_file.get(section, ALBUMART_DIM).split(',')
            d[ALBUMART_DIM] =  (int(spl[0]), int(spl[1]))
        except:
            d[ALBUMART_DIM] = None
        try:
            d[ALBUMART_MSK] = config_file.get(section, ALBUMART_MSK)
        except:
            d[ALBUMART_MSK] = None            
        try:
            d[ALBUMBORDER] = config_file.getint(section, ALBUMBORDER)
        except:
            d[ALBUMBORDER] = None

        try:
            d[ALBUMART_ROT] = config_file.getboolean(section, ALBUMART_ROT)
        except:
            d[ALBUMART_ROT] = False  # default: rotation disabled

        try:
            d[ALBUMART_ROT_SPEED] = config_file.getfloat(section, ALBUMART_ROT_SPEED)
        except:
            d[ALBUMART_ROT_SPEED] = 0.0  # default: no rotation

        # --- Reel configuration (for cassette skins) ---
        try:
            d[REEL_LEFT_FILE] = config_file.get(section, REEL_LEFT_FILE)
        except:
            d[REEL_LEFT_FILE] = None
        try:
            spl = config_file.get(section, REEL_LEFT_POS).split(',')
            d[REEL_LEFT_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[REEL_LEFT_POS] = None
        try:
            spl = config_file.get(section, REEL_LEFT_CENTER).split(',')
            d[REEL_LEFT_CENTER] = (int(spl[0]), int(spl[1]))
        except:
            d[REEL_LEFT_CENTER] = None
        try:
            d[REEL_RIGHT_FILE] = config_file.get(section, REEL_RIGHT_FILE)
        except:
            d[REEL_RIGHT_FILE] = None
        try:
            spl = config_file.get(section, REEL_RIGHT_POS).split(',')
            d[REEL_RIGHT_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[REEL_RIGHT_POS] = None
        try:
            spl = config_file.get(section, REEL_RIGHT_CENTER).split(',')
            d[REEL_RIGHT_CENTER] = (int(spl[0]), int(spl[1]))
        except:
            d[REEL_RIGHT_CENTER] = None
        try:
            d[REEL_ROTATION_SPEED] = config_file.getfloat(section, REEL_ROTATION_SPEED)
        except:
            d[REEL_ROTATION_SPEED] = 0.0
        try:
            d[REEL_DIRECTION] = config_file.get(section, REEL_DIRECTION)
        except:
            d[REEL_DIRECTION] = None  # None = use global config

        # --- Vinyl configuration (for turntable skins) ---
        try:
            d[VINYL_FILE] = config_file.get(section, VINYL_FILE)
        except:
            d[VINYL_FILE] = None
        try:
            spl = config_file.get(section, VINYL_POS).split(',')
            d[VINYL_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[VINYL_POS] = None
        try:
            spl = config_file.get(section, VINYL_CENTER).split(',')
            d[VINYL_CENTER] = (int(spl[0]), int(spl[1]))
        except:
            d[VINYL_CENTER] = None
        try:
            d[VINYL_DIRECTION] = config_file.get(section, VINYL_DIRECTION)
        except:
            d[VINYL_DIRECTION] = None  # None = use global config (reel.direction)

        # --- Tonearm configuration (for turntable skins) ---
        try:
            d[TONEARM_FILE] = config_file.get(section, TONEARM_FILE)
        except:
            d[TONEARM_FILE] = None
        try:
            spl = config_file.get(section, TONEARM_PIVOT_SCREEN).split(',')
            d[TONEARM_PIVOT_SCREEN] = (int(spl[0]), int(spl[1]))
        except:
            d[TONEARM_PIVOT_SCREEN] = None
        try:
            spl = config_file.get(section, TONEARM_PIVOT_IMAGE).split(',')
            d[TONEARM_PIVOT_IMAGE] = (int(spl[0]), int(spl[1]))
        except:
            d[TONEARM_PIVOT_IMAGE] = None
        try:
            d[TONEARM_ANGLE_REST] = config_file.getfloat(section, TONEARM_ANGLE_REST)
        except:
            d[TONEARM_ANGLE_REST] = -30.0  # default: parked at -30 degrees
        try:
            d[TONEARM_ANGLE_START] = config_file.getfloat(section, TONEARM_ANGLE_START)
        except:
            d[TONEARM_ANGLE_START] = 0.0  # default: outer groove at 0 degrees
        try:
            d[TONEARM_ANGLE_END] = config_file.getfloat(section, TONEARM_ANGLE_END)
        except:
            d[TONEARM_ANGLE_END] = 25.0  # default: inner groove at 25 degrees
        try:
            d[TONEARM_DROP_DURATION] = config_file.getfloat(section, TONEARM_DROP_DURATION)
        except:
            d[TONEARM_DROP_DURATION] = 1.5  # default: 1.5 second drop animation
        try:
            d[TONEARM_LIFT_DURATION] = config_file.getfloat(section, TONEARM_LIFT_DURATION)
        except:
            d[TONEARM_LIFT_DURATION] = 1.0  # default: 1.0 second lift animation

        # --- Indicator configuration (state display elements) ---
        # Volume indicator
        try:
            spl = config_file.get(section, VOLUME_POS).split(',')
            d[VOLUME_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[VOLUME_POS] = None
        try:
            d[VOLUME_STYLE] = config_file.get(section, VOLUME_STYLE)
        except:
            d[VOLUME_STYLE] = "numeric"
        try:
            spl = config_file.get(section, VOLUME_DIM).split(',')
            d[VOLUME_DIM] = (int(spl[0]), int(spl[1]))
        except:
            d[VOLUME_DIM] = None
        try:
            spl = config_file.get(section, VOLUME_COLOR).split(',')
            d[VOLUME_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[VOLUME_COLOR] = (255, 255, 255)
        try:
            spl = config_file.get(section, VOLUME_BG_COLOR).split(',')
            d[VOLUME_BG_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[VOLUME_BG_COLOR] = None
        try:
            d[VOLUME_FONT_SIZE] = config_file.getint(section, VOLUME_FONT_SIZE)
        except:
            d[VOLUME_FONT_SIZE] = 24
        # Volume knob parameters
        try:
            d[VOLUME_KNOB_IMAGE] = config_file.get(section, VOLUME_KNOB_IMAGE)
        except:
            d[VOLUME_KNOB_IMAGE] = None
        try:
            d[VOLUME_KNOB_ANGLE_START] = config_file.getfloat(section, VOLUME_KNOB_ANGLE_START)
        except:
            d[VOLUME_KNOB_ANGLE_START] = 225.0
        try:
            d[VOLUME_KNOB_ANGLE_END] = config_file.getfloat(section, VOLUME_KNOB_ANGLE_END)
        except:
            d[VOLUME_KNOB_ANGLE_END] = -45.0
        # Volume arc parameters
        try:
            d[VOLUME_ARC_WIDTH] = config_file.getint(section, VOLUME_ARC_WIDTH)
        except:
            d[VOLUME_ARC_WIDTH] = 6
        try:
            d[VOLUME_ARC_ANGLE_START] = config_file.getfloat(section, VOLUME_ARC_ANGLE_START)
        except:
            d[VOLUME_ARC_ANGLE_START] = 225.0
        try:
            d[VOLUME_ARC_ANGLE_END] = config_file.getfloat(section, VOLUME_ARC_ANGLE_END)
        except:
            d[VOLUME_ARC_ANGLE_END] = -45.0
        # Volume slider parameters (image-based)
        try:
            d[VOLUME_SLIDER_TRACK] = config_file.get(section, VOLUME_SLIDER_TRACK)
        except:
            d[VOLUME_SLIDER_TRACK] = None
        try:
            d[VOLUME_SLIDER_TIP] = config_file.get(section, VOLUME_SLIDER_TIP)
        except:
            d[VOLUME_SLIDER_TIP] = None
        try:
            d[VOLUME_SLIDER_ORIENTATION] = config_file.get(section, VOLUME_SLIDER_ORIENTATION)
        except:
            d[VOLUME_SLIDER_ORIENTATION] = "vertical"
        try:
            spl = config_file.get(section, VOLUME_SLIDER_TRAVEL).split(',')
            d[VOLUME_SLIDER_TRAVEL] = (int(spl[0]), int(spl[1]))
        except:
            d[VOLUME_SLIDER_TRAVEL] = None
        try:
            spl = config_file.get(section, VOLUME_SLIDER_TIP_OFFSET).split(',')
            d[VOLUME_SLIDER_TIP_OFFSET] = (int(spl[0]), int(spl[1]))
        except:
            d[VOLUME_SLIDER_TIP_OFFSET] = (0, 0)

        # Mute indicator
        try:
            spl = config_file.get(section, MUTE_POS).split(',')
            d[MUTE_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[MUTE_POS] = None
        try:
            d[MUTE_ICON] = config_file.get(section, MUTE_ICON)
        except:
            d[MUTE_ICON] = None
        try:
            spl = config_file.get(section, MUTE_LED).split(',')
            d[MUTE_LED] = (int(spl[0]), int(spl[1]))
        except:
            d[MUTE_LED] = None
        try:
            d[MUTE_LED_SHAPE] = config_file.get(section, MUTE_LED_SHAPE)
        except:
            d[MUTE_LED_SHAPE] = "circle"
        try:
            spl = config_file.get(section, MUTE_LED_COLOR).split(',')
            # 6 values: on_r,on_g,on_b,off_r,off_g,off_b
            d[MUTE_LED_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                 (int(spl[3]), int(spl[4]), int(spl[5]))]
        except:
            d[MUTE_LED_COLOR] = [(255, 0, 0), (64, 64, 64)]
        try:
            d[MUTE_LED_GLOW] = config_file.getint(section, MUTE_LED_GLOW)
        except:
            d[MUTE_LED_GLOW] = 0
        try:
            d[MUTE_LED_GLOW_INTENSITY] = config_file.getfloat(section, MUTE_LED_GLOW_INTENSITY)
        except:
            d[MUTE_LED_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, MUTE_LED_GLOW_COLOR).split(',')
            d[MUTE_LED_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                      (int(spl[3]), int(spl[4]), int(spl[5]))]
        except:
            d[MUTE_LED_GLOW_COLOR] = None
        try:
            d[MUTE_ICON_GLOW] = config_file.getint(section, MUTE_ICON_GLOW)
        except:
            d[MUTE_ICON_GLOW] = 0
        try:
            d[MUTE_ICON_GLOW_INTENSITY] = config_file.getfloat(section, MUTE_ICON_GLOW_INTENSITY)
        except:
            d[MUTE_ICON_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, MUTE_ICON_GLOW_COLOR).split(',')
            d[MUTE_ICON_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                       (int(spl[3]), int(spl[4]), int(spl[5]))]
        except:
            d[MUTE_ICON_GLOW_COLOR] = None

        # Shuffle indicator
        try:
            spl = config_file.get(section, SHUFFLE_POS).split(',')
            d[SHUFFLE_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[SHUFFLE_POS] = None
        try:
            d[SHUFFLE_ICON] = config_file.get(section, SHUFFLE_ICON)
        except:
            d[SHUFFLE_ICON] = None
        try:
            spl = config_file.get(section, SHUFFLE_LED).split(',')
            d[SHUFFLE_LED] = (int(spl[0]), int(spl[1]))
        except:
            d[SHUFFLE_LED] = None
        try:
            d[SHUFFLE_LED_SHAPE] = config_file.get(section, SHUFFLE_LED_SHAPE)
        except:
            d[SHUFFLE_LED_SHAPE] = "circle"
        try:
            spl = config_file.get(section, SHUFFLE_LED_COLOR).split(',')
            # Support 3 states (9 values): off, shuffle, infinity
            # Or backwards compatible 2 states (6 values): shuffle, off
            if len(spl) >= 9:
                d[SHUFFLE_LED_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                        (int(spl[3]), int(spl[4]), int(spl[5])),
                                        (int(spl[6]), int(spl[7]), int(spl[8]))]
            else:
                # Backwards compatible: 6 values = [on, off] -> [off, shuffle, shuffle]
                d[SHUFFLE_LED_COLOR] = [(int(spl[3]), int(spl[4]), int(spl[5])),
                                        (int(spl[0]), int(spl[1]), int(spl[2])),
                                        (int(spl[0]), int(spl[1]), int(spl[2]))]
        except:
            # Default: off=gray, shuffle=cyan, infinity=magenta
            d[SHUFFLE_LED_COLOR] = [(64, 64, 64), (0, 200, 255), (200, 0, 200)]
        try:
            d[SHUFFLE_LED_GLOW] = config_file.getint(section, SHUFFLE_LED_GLOW)
        except:
            d[SHUFFLE_LED_GLOW] = 0
        try:
            d[SHUFFLE_LED_GLOW_INTENSITY] = config_file.getfloat(section, SHUFFLE_LED_GLOW_INTENSITY)
        except:
            d[SHUFFLE_LED_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, SHUFFLE_LED_GLOW_COLOR).split(',')
            # Support 3 states or 2 states
            if len(spl) >= 9:
                d[SHUFFLE_LED_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                             (int(spl[3]), int(spl[4]), int(spl[5])),
                                             (int(spl[6]), int(spl[7]), int(spl[8]))]
            else:
                d[SHUFFLE_LED_GLOW_COLOR] = [(int(spl[3]), int(spl[4]), int(spl[5])),
                                             (int(spl[0]), int(spl[1]), int(spl[2])),
                                             (int(spl[0]), int(spl[1]), int(spl[2]))]
        except:
            d[SHUFFLE_LED_GLOW_COLOR] = None
        try:
            d[SHUFFLE_ICON_GLOW] = config_file.getint(section, SHUFFLE_ICON_GLOW)
        except:
            d[SHUFFLE_ICON_GLOW] = 0
        try:
            d[SHUFFLE_ICON_GLOW_INTENSITY] = config_file.getfloat(section, SHUFFLE_ICON_GLOW_INTENSITY)
        except:
            d[SHUFFLE_ICON_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, SHUFFLE_ICON_GLOW_COLOR).split(',')
            # Support 3 states or 2 states
            if len(spl) >= 9:
                d[SHUFFLE_ICON_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                              (int(spl[3]), int(spl[4]), int(spl[5])),
                                              (int(spl[6]), int(spl[7]), int(spl[8]))]
            else:
                d[SHUFFLE_ICON_GLOW_COLOR] = [(int(spl[3]), int(spl[4]), int(spl[5])),
                                              (int(spl[0]), int(spl[1]), int(spl[2])),
                                              (int(spl[0]), int(spl[1]), int(spl[2]))]
        except:
            d[SHUFFLE_ICON_GLOW_COLOR] = None

        # Repeat indicator (3 states: off, all, single)
        try:
            spl = config_file.get(section, REPEAT_POS).split(',')
            d[REPEAT_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[REPEAT_POS] = None
        try:
            d[REPEAT_ICON] = config_file.get(section, REPEAT_ICON)
        except:
            d[REPEAT_ICON] = None
        try:
            spl = config_file.get(section, REPEAT_LED).split(',')
            d[REPEAT_LED] = (int(spl[0]), int(spl[1]))
        except:
            d[REPEAT_LED] = None
        try:
            d[REPEAT_LED_SHAPE] = config_file.get(section, REPEAT_LED_SHAPE)
        except:
            d[REPEAT_LED_SHAPE] = "circle"
        try:
            spl = config_file.get(section, REPEAT_LED_COLOR).split(',')
            # 9 values: off_r,off_g,off_b,on_r,on_g,on_b,single_r,single_g,single_b
            d[REPEAT_LED_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                   (int(spl[3]), int(spl[4]), int(spl[5])),
                                   (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[REPEAT_LED_COLOR] = [(64, 64, 64), (0, 255, 0), (255, 200, 0)]
        try:
            d[REPEAT_LED_GLOW] = config_file.getint(section, REPEAT_LED_GLOW)
        except:
            d[REPEAT_LED_GLOW] = 0
        try:
            d[REPEAT_LED_GLOW_INTENSITY] = config_file.getfloat(section, REPEAT_LED_GLOW_INTENSITY)
        except:
            d[REPEAT_LED_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, REPEAT_LED_GLOW_COLOR).split(',')
            d[REPEAT_LED_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                        (int(spl[3]), int(spl[4]), int(spl[5])),
                                        (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[REPEAT_LED_GLOW_COLOR] = None
        try:
            d[REPEAT_ICON_GLOW] = config_file.getint(section, REPEAT_ICON_GLOW)
        except:
            d[REPEAT_ICON_GLOW] = 0
        try:
            d[REPEAT_ICON_GLOW_INTENSITY] = config_file.getfloat(section, REPEAT_ICON_GLOW_INTENSITY)
        except:
            d[REPEAT_ICON_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, REPEAT_ICON_GLOW_COLOR).split(',')
            d[REPEAT_ICON_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                         (int(spl[3]), int(spl[4]), int(spl[5])),
                                         (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[REPEAT_ICON_GLOW_COLOR] = None

        # Play/Pause/Stop indicator (3 states: stop, pause, play)
        try:
            spl = config_file.get(section, PLAYSTATE_POS).split(',')
            d[PLAYSTATE_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[PLAYSTATE_POS] = None
        try:
            d[PLAYSTATE_ICON] = config_file.get(section, PLAYSTATE_ICON)
        except:
            d[PLAYSTATE_ICON] = None
        try:
            spl = config_file.get(section, PLAYSTATE_LED).split(',')
            d[PLAYSTATE_LED] = (int(spl[0]), int(spl[1]))
        except:
            d[PLAYSTATE_LED] = None
        try:
            d[PLAYSTATE_LED_SHAPE] = config_file.get(section, PLAYSTATE_LED_SHAPE)
        except:
            d[PLAYSTATE_LED_SHAPE] = "circle"
        try:
            spl = config_file.get(section, PLAYSTATE_LED_COLOR).split(',')
            # 9 values: stop_r,stop_g,stop_b,pause_r,pause_g,pause_b,play_r,play_g,play_b
            d[PLAYSTATE_LED_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                      (int(spl[3]), int(spl[4]), int(spl[5])),
                                      (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[PLAYSTATE_LED_COLOR] = [(64, 64, 64), (255, 200, 0), (0, 255, 0)]
        try:
            d[PLAYSTATE_LED_GLOW] = config_file.getint(section, PLAYSTATE_LED_GLOW)
        except:
            d[PLAYSTATE_LED_GLOW] = 0
        try:
            d[PLAYSTATE_LED_GLOW_INTENSITY] = config_file.getfloat(section, PLAYSTATE_LED_GLOW_INTENSITY)
        except:
            d[PLAYSTATE_LED_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, PLAYSTATE_LED_GLOW_COLOR).split(',')
            d[PLAYSTATE_LED_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                           (int(spl[3]), int(spl[4]), int(spl[5])),
                                           (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[PLAYSTATE_LED_GLOW_COLOR] = None
        try:
            d[PLAYSTATE_ICON_GLOW] = config_file.getint(section, PLAYSTATE_ICON_GLOW)
        except:
            d[PLAYSTATE_ICON_GLOW] = 0
        try:
            d[PLAYSTATE_ICON_GLOW_INTENSITY] = config_file.getfloat(section, PLAYSTATE_ICON_GLOW_INTENSITY)
        except:
            d[PLAYSTATE_ICON_GLOW_INTENSITY] = 0.5
        try:
            spl = config_file.get(section, PLAYSTATE_ICON_GLOW_COLOR).split(',')
            d[PLAYSTATE_ICON_GLOW_COLOR] = [(int(spl[0]), int(spl[1]), int(spl[2])),
                                            (int(spl[3]), int(spl[4]), int(spl[5])),
                                            (int(spl[6]), int(spl[7]), int(spl[8]))]
        except:
            d[PLAYSTATE_ICON_GLOW_COLOR] = None

        # Progress bar
        try:
            spl = config_file.get(section, PROGRESS_POS).split(',')
            d[PROGRESS_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[PROGRESS_POS] = None
        try:
            spl = config_file.get(section, PROGRESS_DIM).split(',')
            d[PROGRESS_DIM] = (int(spl[0]), int(spl[1]))
        except:
            d[PROGRESS_DIM] = None
        try:
            spl = config_file.get(section, PROGRESS_COLOR).split(',')
            d[PROGRESS_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PROGRESS_COLOR] = (0, 200, 255)
        try:
            spl = config_file.get(section, PROGRESS_BG_COLOR).split(',')
            d[PROGRESS_BG_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PROGRESS_BG_COLOR] = (40, 40, 40)
        try:
            d[PROGRESS_BORDER] = config_file.getint(section, PROGRESS_BORDER)
        except:
            d[PROGRESS_BORDER] = 0
        try:
            spl = config_file.get(section, PROGRESS_BORDER_COLOR).split(',')
            d[PROGRESS_BORDER_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PROGRESS_BORDER_COLOR] = (100, 100, 100)

        try:
            d[PLAY_TXT_CENTER] = config_file.getboolean(section, PLAY_TXT_CENTER)
        except:
            d[PLAY_TXT_CENTER] = None
        try:
            spl = config_file.get(section, PLAY_TITLE_POS).split(',')		
            d[PLAY_TITLE_POS] = (int(spl[0]), int(spl[1]))
            d[PLAY_TITLE_STYLE] = spl[2]
        except:
            d[PLAY_TITLE_POS] = None
            d[PLAY_TITLE_STYLE] = FONT_STYLE_B
        try:
            spl = config_file.get(section, PLAY_TITLE_COLOR).split(',')
            d[PLAY_TITLE_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PLAY_TITLE_COLOR] = None
        try:
            d[PLAY_TITLE_MAX] = config_file.getint(section, PLAY_TITLE_MAX)
        except:
            d[PLAY_TITLE_MAX] = None
            
        try:
            spl = config_file.get(section, PLAY_ARTIST_POS).split(',')
            d[PLAY_ARTIST_POS] = (int(spl[0]), int(spl[1]))
            d[PLAY_ARTIST_STYLE] = spl[2]
        except:
            d[PLAY_ARTIST_POS] = None
            d[PLAY_ARTIST_STYLE] = FONT_STYLE_L
        try:
            spl = config_file.get(section, PLAY_ARTIST_COLOR).split(',')
            d[PLAY_ARTIST_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PLAY_ARTIST_COLOR] = None
        try:
            d[PLAY_ARTIST_MAX] = config_file.getint(section, PLAY_ARTIST_MAX)
        except:
            d[PLAY_ARTIST_MAX] = None
            
        try:
            spl = config_file.get(section, PLAY_ALBUM_POS).split(',')
            d[PLAY_ALBUM_POS] = (int(spl[0]), int(spl[1]))
            d[PLAY_ALBUM_STYLE] = spl[2]
        except:
            d[PLAY_ALBUM_POS] = None
            d[PLAY_ALBUM_STYLE] = FONT_STYLE_L
        try:
            spl = config_file.get(section, PLAY_ALBUM_COLOR).split(',')
            d[PLAY_ALBUM_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PLAY_ALBUM_COLOR] = None
        try:
            d[PLAY_ALBUM_MAX] = config_file.getint(section, PLAY_ALBUM_MAX)
        except:
            d[PLAY_ALBUM_MAX] = None
            
        try:
            d[PLAY_CENTER] = config_file.getboolean(section, PLAY_CENTER)
        except:
            d[PLAY_CENTER] = False
        try:
            d[PLAY_MAX] = config_file.getint(section, PLAY_MAX)
        except:
            d[PLAY_MAX] = None
        try:
            d[SCROLLING_SPEED] = config_file.getint(section, SCROLLING_SPEED)
        except:
            d[SCROLLING_SPEED] = 40  # default pixels per second
        # Per-field scrolling speeds (fallback to global, then default)
        global_speed = d[SCROLLING_SPEED]
        try:
            d[SCROLLING_SPEED_ARTIST] = config_file.getint(section, SCROLLING_SPEED_ARTIST)
        except:
            d[SCROLLING_SPEED_ARTIST] = global_speed
        try:
            d[SCROLLING_SPEED_TITLE] = config_file.getint(section, SCROLLING_SPEED_TITLE)
        except:
            d[SCROLLING_SPEED_TITLE] = global_speed
        try:
            d[SCROLLING_SPEED_ALBUM] = config_file.getint(section, SCROLLING_SPEED_ALBUM)
        except:
            d[SCROLLING_SPEED_ALBUM] = global_speed

        try:
            spl = config_file.get(section, PLAY_TYPE_POS).split(',')		
            d[PLAY_TYPE_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[PLAY_TYPE_POS] = None
        try:
            spl = config_file.get(section, PLAY_TYPE_COLOR).split(',')
            d[PLAY_TYPE_COLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[PLAY_TYPE_COLOR] = (255,255,255)			
        try:
            spl = config_file.get(section, PLAY_TYPE_DIM).split(',')
            d[PLAY_TYPE_DIM] =  (int(spl[0]), int(spl[1]))
        except:
            d[PLAY_TYPE_DIM] = None
        try:
            spl = config_file.get(section, PLAY_SAMPLE_POS).split(',')		
            d[PLAY_SAMPLE_POS] = (int(spl[0]), int(spl[1]))
            d[PLAY_SAMPLE_STYLE] = spl[2]
        except:
            d[PLAY_SAMPLE_POS] = None
            d[PLAY_SAMPLE_STYLE] = FONT_STYLE_B
        try:
            d[PLAY_SAMPLE_MAX] = config_file.getint(section, PLAY_SAMPLE_MAX)
        except:
            d[PLAY_SAMPLE_MAX] = None

        try:
            spl = config_file.get(section, TIME_REMAINING_POS).split(',')		
            d[TIME_REMAINING_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[TIME_REMAINING_POS] = None
        try:
            d[FONTSIZE_LIGHT] = config_file.getint(section, FONTSIZE_LIGHT)
        except:
            d[FONTSIZE_LIGHT] = 30			
        try:
            d[FONTSIZE_REGULAR] = config_file.getint(section, FONTSIZE_REGULAR)
        except:
            d[FONTSIZE_REGULAR] = 35
        try:
            d[FONTSIZE_BOLD] = config_file.getint(section, FONTSIZE_BOLD)
        except:
            d[FONTSIZE_BOLD] = 40	
        try:
            d[FONTSIZE_DIGI] = config_file.getint(section, FONTSIZE_DIGI)
        except:
            d[FONTSIZE_DIGI] = 40
        try:
            spl = config_file.get(section, FONTCOLOR).split(',')
            d[FONTCOLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[FONTCOLOR] = (255,255,255)	
        try:
            spl = config_file.get(section, TIMECOLOR).split(',')
            d[TIMECOLOR] = (int(spl[0]), int(spl[1]), int(spl[2]))
        except:
            d[TIMECOLOR] = (255,255,255)

        try:
            d[SPECTRUM_VISIBLE] = config_file.getboolean(section, SPECTRUM_VISIBLE)
        except:
            d[SPECTRUM_VISIBLE] = False
        try:
            d[SPECTRUM] = config_file.get(section, SPECTRUM)
        except:
            d[SPECTRUM] = None             
        try:
            spl = config_file.get(section, SPECTRUM_SIZE).split(',')		
            d[SPECTRUM_SIZE] = (int(spl[0]), int(spl[1]))
        except:
            d[SPECTRUM_SIZE] = None
        try:
            spl = config_file.get(section, SPECTRUM_POS).split(',')		
            d[SPECTRUM_POS] = (int(spl[0]), int(spl[1]))
        except:
            d[SPECTRUM_POS] = None
        return d
