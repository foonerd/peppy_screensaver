# Copyright 2024 PeppyMeter for Volumio by 2aCD
# 
# This file is part of PeppyMeter for Volumio
# It's overwrite ScreensaverSpectrum from PeppySpectrum
#

import pygame as pg
from spectrum.spectrumconfigparser import SpectrumConfigParser, SPECTRUM_X, SPECTRUM_Y, AVAILABLE_SPECTRUM_NAMES

class ScreensaverSpectrum():
    """ Parent class for spectrum plug-in """
    
    def __init__(self, name, util, plugin_folder):
        """ Initializer called from spectrum.py """ 

        self.util = util
        self.bg = (None, None, None, None)
        self.w = self.util.spectrum_size[0]
        self.h = self.util.spectrum_size[1]
        self.s = self.util.spectrum_size[2]

        # define the spectrum dimensions
        parser_SP = SpectrumConfigParser(standalone=False)
        parser_SP.config[AVAILABLE_SPECTRUM_NAMES] = [self.s] # update spectrum name to read correct section
        spectrum_configs = parser_SP.get_spectrum_configs()
        self.util.screen_rect = pg.Rect(spectrum_configs[0][SPECTRUM_X], spectrum_configs[0][SPECTRUM_Y], self.w, self.h)
