# Copyright 2024 PeppyMeter for Volumio by 2aCD
# Copyright 2025 Volumio 4 adaptation by Just a Nerd
# Rewritten 2025 for Volumio 4 / Bookworm (Python 3.11)
#
# This file is part of PeppyMeter for Volumio

import os
import time
from datetime import datetime
from threading import Thread

from spectrum.spectrum import Spectrum
from spectrumutil import SpectrumUtil
from configfileparser import METER
from volumio_configfileparser import SPECTRUM, SPECTRUM_SIZE
# from volumio_spectrumconfigwriter import Volumio_SpectrumConfigWriter
from spectrumconfigparser import SCREEN_WIDTH, SCREEN_HEIGHT, AVAILABLE_SPECTRUM_NAMES 


# =============================================================================
# Debug logging support (shared from main module)
# =============================================================================
DEBUG_LOG_FILE = '/tmp/peppy_debug.log'

_DEBUG_LEVEL = "off"
_DEBUG_TRACE = {}

def init_spectrum_debug(level, trace_dict):
    """Initialize debug settings from main module.
    
    :param level: Debug level string ("off", "basic", "verbose", "trace")
    :param trace_dict: Dictionary of trace component switches
    """
    global _DEBUG_LEVEL, _DEBUG_TRACE
    _DEBUG_LEVEL = level
    _DEBUG_TRACE = trace_dict

def _log_debug(msg, level="basic", component=None):
    """Log debug message to file if level is enabled.
    
    :param msg: Message to log
    :param level: Required level ("basic", "verbose", "trace")
    :param component: For trace level, the component name to check
    """
    if _DEBUG_LEVEL == "off":
        return
    
    level_order = {"off": 0, "basic": 1, "verbose": 2, "trace": 3}
    current_level = level_order.get(_DEBUG_LEVEL, 0)
    required_level = level_order.get(level, 1)
    
    if current_level < required_level:
        return
    
    # For trace level, check component switch
    if level == "trace" and component:
        if not _DEBUG_TRACE.get(component, False):
            return
    
    try:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


class SpectrumOutput(Thread):
    """ Provides show spectrum in a separate thread """
    
    def __init__(self, util, meter_config_volumio, CurDir):
        """ Initializer

        :param util: utility class
        :param meter_config_volumio: VolumioConfig class
        :param CurDir: current dir on start moment

        """
        Thread.__init__(self)		
        self.CurDir = CurDir        
        self.SpectrumPath = self.CurDir + '/screensaver/spectrum'
        
        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_volumio = meter_config_volumio
        self.meter_section = self.meter_config_volumio[self.meter_config[METER]]

        self.w = self.meter_section[SPECTRUM_SIZE][0]
        self.h = self.meter_section[SPECTRUM_SIZE][1]
        self.s = self.meter_section[SPECTRUM]
        
        # TRACE: Log init
        if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
            _log_debug(f"[Spectrum] INIT: size={self.w}x{self.h}, spectrum={self.s}", "trace", "spectrum")

    def VolumeFadeIn(self, spectrum):
        """ callback methode to fade in volume for spectrum bars """
        self.FadeIn = Thread(target = self.FadeIn_thread, args=(spectrum, ))
        self.FadeIn.start()

    def FadeIn_thread(self, arg):
        spc = arg
        vol = 0.0
        while vol <= 1.0: 
            spc.height_adjuster = vol
            vol += 0.1
            time.sleep(0.07)
        
    def run(self):
        """ Thread method start peppySpectrum """
    
        # TRACE: Log run start
        if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
            _log_debug(f"[Spectrum] INPUT: starting thread, path={self.SpectrumPath}", "trace", "spectrum")
    
        # write new spectrum config
        # writer_SP = Volumio_SpectrumConfigWriter(self.SpectrumPath)
        # writer_SP.set_config(self.meter_section[SPECTRUM], w, h) #not more needed
    
        # parse spectrum config values for X and X
        # os.chdir(self.SpectrumPath) # needed for spectrumparser
        # parser_SP = SpectrumConfigParser(standalone=False)
        # spectrum_configs = parser_SP.spectrum_configs
    
        # make meter.util compatible with spectrum.util
        # self.util.screen_rect = pg.Rect(spectrum_configs[0][SPECTRUM_X], spectrum_configs[0][SPECTRUM_Y], w, h)
        self.util.spectrum_size = (self.w, self.h, self.s)
        self.util.pygame_screen = self.util.PYGAME_SCREEN
        self.util.image_util = SpectrumUtil()
     
        # get the peppy spectrum object
        os.chdir(self.SpectrumPath) # to find the config file
        self.sp = None
        self.sp = Spectrum(self.util, standalone=False)
        # overwrite from folder calculated spectrum dimensions
        self.sp.config[SCREEN_WIDTH] = self.w
        self.sp.config[SCREEN_HEIGHT] = self.h
        # set current spectrum and re-read config
        self.sp.config[AVAILABLE_SPECTRUM_NAMES] = [self.s]
        self.sp.spectrum_configs = self.sp.config_parser.get_spectrum_configs()
        self.sp.init_spectrums()
        # start spectrum without UI refresh loop
        # self.sp.callback_start = lambda x: x # <-- dummy function to prevent update_ui on start
        self.sp.callback_start = self.VolumeFadeIn
        self.sp.start()
        
        # TRACE: Log run complete
        if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
            _log_debug(f"[Spectrum] OUTPUT: thread started, spectrum={self.s}", "trace", "spectrum")


    def update(self):
        """ Update method, called from meters display output 
        
        IMPORTANT: We call spectrum.draw() directly instead of dirty_draw_update()
        because dirty_draw_update() calls pygame.display.update() internally,
        which conflicts with the parent's display update cycle and causes flicker.
        The parent (volumio_peppymeter) handles display updates.
        """
        
        if hasattr(self, 'sp') and self.sp is not None:
            # if background is ready
            if self.sp.components[0].content is not None:
                # Clip drawing to spectrum rect (constrains reflections)
                prev_clip = self.util.pygame_screen.get_clip()
                self.util.pygame_screen.set_clip(self.util.screen_rect)
                
                # Clean dirty areas and draw WITHOUT calling display.update()
                # This prevents double display updates that cause flicker
                if hasattr(self.sp, '_dirty_rects') and self.sp._dirty_rects:
                    for rect in self.sp._dirty_rects:
                        self.sp.draw_area(rect)
                    self.sp._dirty_rects = []
                self.sp.draw()
                
                # Restore previous clip
                self.util.pygame_screen.set_clip(prev_clip)
                
                # TRACE: Log update (only occasionally to reduce noise)
                if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
                    _log_debug(f"[Spectrum] OUTPUT: draw (no display.update), clip={self.util.screen_rect}", "trace", "spectrum")
    
    def get_current_bins(self):
        """Get current spectrum bin values for network broadcast.
        
        Returns the bar heights which represent the processed FFT values.
        These are scaled/normalized values suitable for remote display.
        
        :return: List of bin values, or None if not available
        """
        if not hasattr(self, 'sp') or self.sp is None:
            _log_debug("[Spectrum] get_current_bins: sp is None", "verbose")
            return None
        
        # Read from components directly - this is the most reliable source
        # as it reflects the actual visual state being rendered
        if hasattr(self.sp, 'components') and hasattr(self.sp, 'config'):
            try:
                size = self.sp.config.get('size', 30)
                heights = []
                for i in range(size):
                    idx = i + 1  # Components are 1-indexed (0 is background)
                    if idx < len(self.sp.components):
                        comp = self.sp.components[idx]
                        if comp and comp.bounding_box:
                            heights.append(float(comp.bounding_box.h))
                        else:
                            heights.append(0.0)
                    else:
                        heights.append(0.0)
                
                # Only log first successful retrieval
                if not hasattr(self, '_logged_first_bins'):
                    _log_debug(f"[Spectrum] get_current_bins: returning {len(heights)} bins from components", "basic")
                    self._logged_first_bins = True
                return heights
            except Exception as e:
                _log_debug(f"[Spectrum] get_current_bins: error reading components: {e}", "verbose")
        
        # Fallback to _prev_bar_heights if components not available
        if hasattr(self.sp, '_prev_bar_heights') and self.sp._prev_bar_heights:
            heights = list(self.sp._prev_bar_heights)
            if not hasattr(self, '_logged_first_bins'):
                _log_debug(f"[Spectrum] get_current_bins: returning {len(heights)} bins from _prev_bar_heights", "basic")
                self._logged_first_bins = True
            return heights
        
        _log_debug("[Spectrum] get_current_bins: no data source available", "verbose")
        return None

    
    def stop_thread(self):
        """ Stop thread """
        
        # TRACE: Log stop
        if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
            _log_debug(f"[Spectrum] INPUT: stopping thread", "trace", "spectrum")

        if hasattr(self, 'sp') and self.sp is not None:
            self.sp.stop()
        if hasattr(self, 'FadeIn'):
            del self.FadeIn
        
        # TRACE: Log stop complete
        if _DEBUG_LEVEL == "trace" and _DEBUG_TRACE.get("spectrum", False):
            _log_debug(f"[Spectrum] OUTPUT: thread stopped", "trace", "spectrum")
