# Copyright 2024 PeppyMeter for Volumio by 2aCD
# 
# This file is part of PeppyMeter for Volumio
# 

import pygame as pg
import time
import ctypes
# import pygame as pg
import socketio
from threading import Thread

from configfileparser import METER, RANDOM_METER_INTERVAL, UI_REFRESH_PERIOD
from volumio_configfileparser import METER_BKP, RANDOM_TITLE, METER_VISIBLE
  
class RandomControl(Thread):
    """ Provides show albumart in a separate thread """
    
    def __init__(self, util, meter_config_volumio, meter):
        """ Initializer
        """
        Thread.__init__(self)

        self.meter = meter
        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_volumio = meter_config_volumio

        self.run_flag = True
        self.first_run = True
        self.position_mem = ""
        self.random_meter = False
        self.list_meter = False
        
        # config values
        self.random_meter_interval = int(self.meter_config[RANDOM_METER_INTERVAL])
        if self.meter_config_volumio[METER_BKP] == "random":
            self.random_meter = True
        elif "," in self.meter_config_volumio[METER_BKP]:
            self.list_meter = True
        self.random_title = (self.random_meter or self.list_meter) and self.meter_config_volumio[RANDOM_TITLE]
        self.seconds = 0
        # python-socketio v5.x compatible client
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=5)
        
    def run(self):
        """ Thread method. Restart meters on random mode. """
                
        # only for random on title change
        @self.sio.on ('pushState')
        def on_push_state(*args):
            if self.random_title:            
                if args[0]['status'] == 'play' and args[0]['position'] != self.position_mem:
                    # print (args[0]['status'] + ' ' + str(args[0]['position']) + ' + ' + str(self.position_mem))
                    self.position_mem = args[0]['position']
                    
                    # no restart on initialization
                    if not self.first_run:
                        #self.meter.meter.set_volume(0.0)
                        self.meter.restart() # vumeter restart
                    self.first_run = False
                
        @self.sio.on ('connect')
        def on_connect():
            # print('connect')
            # run once only on initialization to save current position
            if self.random_title:
                self.sio.emit('getState')

        if self.random_meter or self.list_meter:
            try:
                self.sio.connect('http://localhost:3000', transports=['websocket', 'polling'])
            except Exception as e:
                print(f"socketio connect error: {e}")
                return

            # wait until disconnect            
            if self.random_title:
                while self.sio.connected:
                    self.sio.wait()

            
            # wait while run_flag            
            else: 
                while self.run_flag:
                    # start random with random interval
                    if self.seconds == self.random_meter_interval:
                        self.seconds = 0
                        self.meter.restart() # vumeter restart
                    self.seconds += 1
                    self.sio.sleep(1)

                # on exit
                self.sio.disconnect()
                    
        # cleanup memory
        del self.meter
        del self.util
        del self.meter_config
        del self.meter_config_volumio
        del self.sio
        self.trim_memory()
        #print('exit -->')
        
    def stop_thread(self):
        """ Stop thread """
        
        if self.random_title:
            if hasattr(self, 'sio') and self.sio is not None:
                self.sio.disconnect()
        else:
            self.run_flag = False


    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)
            
# ===================================================================================================================	