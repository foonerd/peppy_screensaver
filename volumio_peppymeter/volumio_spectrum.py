# Copyright 2024 PeppyMeter for Volumio by 2aCD
# 
# This file is part of PeppyMeter for Volumio
#

import os
import time
# import pygame as pg
from threading import Thread

from spectrum.spectrum import Spectrum
from spectrumutil import SpectrumUtil
from configfileparser import METER
from volumio_configfileparser import SPECTRUM, SPECTRUM_SIZE
# from volumio_spectrumconfigwriter import Volumio_SpectrumConfigWriter
from spectrumconfigparser import SCREEN_WIDTH, SCREEN_HEIGHT, AVAILABLE_SPECTRUM_NAMES 

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


    def update(self):
        """ Update method, called from meters display output """
        
        if hasattr(self, 'sp') and self.sp is not None:
            # if background is ready
            if self.sp.components[0].content is not None:
                self.sp.clean_draw_update()

    
    def stop_thread(self):
        """ Stop thread """

        if hasattr(self, 'sp') and self.sp is not None:
            self.sp.stop()
        if hasattr(self, 'FadeIn'):
            del self.FadeIn

        