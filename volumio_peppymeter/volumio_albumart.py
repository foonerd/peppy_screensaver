# Copyright 2021 PeppyMeter for Volumio by 2aCD
# Refactored 2024 for Volumio 4 (Python 3.11, python-socketio 5.x)
# 
# This file is part of PeppyMeter for Volumio
# 

import time
import os
import pygame as pg
import requests
import io
import ctypes
import socketio

if not pg.version.ver.startswith("2"):
    try:
        import cairosvg
    except:
        pass # if it not properly installed
                
from PIL import Image, ImageOps
from threading import Thread, Timer

from configfileparser import METER, BASE_PATH, METER_FOLDER, UI_REFRESH_PERIOD 
from volumio_configfileparser import *
  
class AlbumartAnimator(Thread):
    """ Provides show albumart in a separate thread """
    
    def __init__(self, util, meter_config_volumio):
        """ Initializer

        :param util: utility class
        :param meter_config_volumio: VolumioConfig class
        """
        Thread.__init__(self)
        
        self.screen = util.PYGAME_SCREEN		
        self.run_flag = True
        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_volumio = meter_config_volumio
        self.meter_section = self.meter_config_volumio[self.meter_config[METER]]
        self.random_title = (self.meter_config_volumio[METER_BKP] == "random" or "," in self.meter_config_volumio[METER_BKP]) and self.meter_config_volumio[RANDOM_TITLE]
        # python-socketio v5.x compatible client
        self.sio = socketio.Client(reconnection=True, reconnection_attempts=5)
        # print ('<-- init')
        
    def run(self):
        """ Thread method. show all title infos and albumart. """
 		
        @self.sio.on ('pushState')
        def on_push_state(*args):

            if args[0]['status'] == 'play':

                if self.meter_section[EXTENDED_CONF] == True:                        
                    # for random/list mode with 'change on title' start only on initializiation (first run)
                    if self.random_title == False or self.first_run == True:
                        # print ('play')

                        # draw albumart
                        if args[0]['albumart'] != self.albumart_mem:
                            self.albumart_mem = args[0]['albumart']
                            title_factory.init_aa()
                            #title_factory.get_albumart_data(self.albumart_mem)
                            #title_factory.render_aa()
                            
                            # as thread to speedup start
                            try:
                                if hasattr(self, 'AA_Thread'):
                                    del self.AA_Thread
                                self.AA_Thread = Thread(target = albumart_thread, args=(title_factory, self.albumart_mem, ))
                                self.AA_Thread.start()
                            except:
                                pass
                                
                        # draw title info
                        if args[0]['title'] + args[0]['artist'] != self.position_mem:                        
                            self.position_mem = args[0]['title'] + args[0]['artist']
                            #title_factory.get_title_data(args[0])
                            #title_factory.render_text()
                        
                            # as thread to speedup start
                            try:
                                if hasattr(self, 'TI_Thread'):
                                    del self.TI_Thread
                                TI_Thread = Thread(target = titleinfo_thread, args=(title_factory, args[0], ))
                                TI_Thread.start()
                            except:
                                pass
                                
                        self.first_run = False
                        
                    # draw reamining time, timer is started for countdown  
                    if self.meter_section[TIME_REMAINING_POS]:
                        duration = int(args[0]['duration']) if 'duration' in args[0] else 0
                        seek = int(args[0]['seek']) if 'seek' in args[0] and args[0]['seek'] is not None else 0
                        service = args[0]['service'] if 'service' in args[0] else ''					
                        if seek != self.seek_mem:
                            self.seek_mem = seek
                            self.time_args = [duration, seek, service]
                            # repeat timer start, initial with duration and seek -> remaining_time 
                            try:
                                self.timer_initial = True
                                self.timer_part = 0
                                timer.start()
                                time.sleep(0.1)
                            except:
                                pass


        def albumart_thread(*args):
            """ render albumart as thread """
            tf = args[0]
            tf.get_albumart_data(args[1])
            tf.render_aa()

        def titleinfo_thread(*args):
            """ render titleinfo as thread """
            tf = args[0]
            tf.get_title_data(args[1])
            tf.render_text()
            
        def remaining_time():
            if self.timer_part == 0:
                title_factory.get_time_data(self.time_args, self.timer_initial)
                title_factory.render_time()
                self.timer_initial = False # countdown without new input values
            
            self.timer_part += 1
            if self.timer_part == 10:
                self.timer_part = 0
		
        @self.sio.on ('connect')
        def on_connect():
            # print('connect')
            if hasattr(self, 'sio') and self.sio is not None and self.run_flag == True:
                self.sio.emit('getState')
                # print('emit')
            
        # @self.sio.on ('disconnect')            
        # def on_disconnect():
        #    while self.sio.connected:
        #        self.sio.wait()
        
        # ---> start run ---->
        self.albumart_mem = ''
        self.position_mem = ''
        self.seek_mem = -1
        self.first_run = True
        # print ('start')

        if self.meter_section[EXTENDED_CONF] == True:		
            title_factory = ImageTitleFactory(self.util, self.meter_config_volumio)
            title_factory.load_fonts() # load fonts for title info
            title_factory.init_surfaces() # copy clean surfaces to backup

        else:
            title_factory = None

        self.timer_part = 0
        timer = RepeatTimer(0.1, remaining_time)
        try:
            self.sio.connect('http://localhost:3000', transports=['websocket', 'polling'])
        except Exception as e:
            print(f"socketio connect error: {e}")
            timer.cancel()
            return
        
        # wait until disconnect
        while self.run_flag:
            self.sio.sleep(0.1)
        self.sio.disconnect()
        # print('disconnect')		
        # <---- wait run <----
        
        # ----> on exit
        timer.cancel()
        del timer
        
        if self.meter_section[EXTENDED_CONF] == True:
            title_factory.stop_text_animator()
            title_factory.stop_AA_FadeIn()
        
        time.sleep(0.1)
        
        # cleanup memory
        if hasattr(self, 'AA_Thread'):
            del self.AA_Thread
        if hasattr(self, 'TI_Thread'):
            del self.TI_Thread
        del title_factory
        del self.screen		
        del self.util
        del self.meter_config
        del self.meter_config_volumio
        del self.sio
        self.trim_memory()
        # print ('exit -->')
        # <---- exit <----

    def stop_thread(self):
        """ Stop thread """
            
        self.run_flag = False
        # wait for threads finshed (timer, text animator) 
        # time.sleep(0.12)
        
    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)
            
# ===================================================================================================================			
class ImageTitleFactory():
    """ Provides show albumart in a separate thread """
    
    def __init__(self, util, meter_config_volumio):
        """ Initializer

        :param util: utility class
        :param ui_refresh_period
        """

        self.run_flag = True
        self.screen = util.PYGAME_SCREEN		
        self.util = util
        self.meter_config = self.util.meter_config
        self.meter_config_volumio = meter_config_volumio
        self.meter_section_meter = self.meter_config[self.meter_config[METER]]        
        self.ui_refresh = self.meter_section_meter[UI_REFRESH_PERIOD]
        self.meter_section = self.meter_config_volumio[self.meter_config[METER]]
        self.titleMem = ""
        self.file_path = os.path.dirname(os.path.realpath(__file__))
        
    def init_surfaces(self):
        """ create clean surfaces as backup """
        #self.init_aa()
        self.init_text()
        self.init_time()
    
    def load_fonts(self):
        """ load fonts for titleinfo """
        FontPath = self.meter_config_volumio[FONT_PATH]
        FontPathDigi = os.path.join(self.file_path, 'fonts', 'DSEG7Classic-Italic.ttf')

        # font style light
        self.fontL = None
        if os.path.exists(FontPath + self.meter_config_volumio[FONT_LIGHT]):
            self.fontL = pg.font.Font(FontPath + self.meter_config_volumio[FONT_LIGHT], self.meter_section[FONTSIZE_LIGHT])
        else:
            self.fontL = pg.font.SysFont(None, 50)
       
        # font style regular
        self.fontR = None
        if os.path.exists(FontPath + self.meter_config_volumio[FONT_REGULAR]):
            self.fontR = pg.font.Font(FontPath + self.meter_config_volumio[FONT_REGULAR], self.meter_section[FONTSIZE_REGULAR])
        else:
            self.fontR = pg.font.SysFont(None, 50)
        
        # font style bold
        self.fontB = None
        if os.path.exists(FontPath + self.meter_config_volumio[FONT_BOLD]):		
            self.fontB = pg.font.Font(FontPath + self.meter_config_volumio[FONT_BOLD], self.meter_section[FONTSIZE_BOLD])
        else:
            self.fontB = pg.font.SysFont(None, 70, bold=True)
        
        # digital font for remaining time
        self.FontDigi = None
        if os.path.exists(FontPathDigi) and self.meter_section[FONTSIZE_DIGI]:
            self.fontDigi = pg.font.Font(FontPathDigi, self.meter_section[FONTSIZE_DIGI])
        else:
            self.fontDigi = pg.font.SysFont(None, 40)
	
        self.fontcolor = self.meter_section[FONTCOLOR]
        #green = (84, 198, 136)

    # get data functions
    # ----------------------------------	
    def get_title_data(self, play_info):
        """ get title infos from argument """
        #print(play_info)			
        if hasattr(self, 'playinfo_title'):
            self.titleMem = self.playinfo_title
        self.playinfo_title = play_info['title'] if play_info['title'] is not None else ''
        self.playinfo_artist = play_info['artist'] if play_info['artist'] is not None else ''
        self.playinfo_album = play_info['album'] if play_info['album'] is not None else ''
        self.playinfo_trackT = play_info['trackType'] if play_info['trackType'] is not None else ''
        self.playinfo_sample = play_info['samplerate'] if 'samplerate' in play_info and play_info['samplerate'] is not None else ''
        self.playinfo_depth = play_info['bitdepth'] if 'bitdepth' in play_info and play_info['bitdepth'] is not None else ''
        playinfo_rate = play_info['bitrate'] if 'bitrate' in play_info and play_info['bitrate'] is not None else '' 
        
        self.playinfo_sample = str(self.playinfo_sample) # some tidal samples are float
        if self.playinfo_sample =='':
            self.playinfo_sample = playinfo_rate # for webradio
        if not self.meter_section[PLAY_ALBUM_POS] and self.playinfo_album != '':
            self.playinfo_artist = self.playinfo_artist + " - " + self.playinfo_album
        if self.playinfo_trackT == 'dsf':
            self.playinfo_trackT = 'dsd'		

    def get_albumart_data(self, play_info):
        """ get albumart infos from argument """	
                
        albumart = play_info
        if len(albumart) == 0:
            albumart = 'http://localhost:3000/albumart'			
        if 'http' not in albumart:
            albumart = 'http://localhost:3000' + play_info

        #print (albumart)
        stream = io.BytesIO(requests.get(albumart).content) 
        self.aa_img = None
        
        # if png mask available use PIL for image 
        if self.meter_section[ALBUMART_MSK]:
            self.aa_img = Image.open(stream).convert("RGBA")
            if self.meter_section[ALBUMART_DIM]:    
                self.aa_img = self.aa_img.resize(self.meter_section[ALBUMART_DIM])
        # otherwise surface
        else:    
            self.aa_img = pg.image.load(stream)        
            if self.meter_section[ALBUMART_DIM]:
                self.aa_img = pg.transform.scale(self.aa_img, self.meter_section[ALBUMART_DIM])
        stream.close()
        
    def get_time_data(self, time_args, timer_init):
        """ get time data """

        self.NoTime = False
        seek_current = int(float(time_args[1])/1000)
        # set initial to current and then count automatcally
        self.seek_new = seek_current if timer_init else self.seek_new + 1

        # webradio has no time info
        if time_args[2] == 'webradio':
            self.remain = time_args[0] 		
            if time_args[0] == 0:
                self.NoTime = True
        else:
            self.remain = 0 if time_args[0] - self.seek_new <= 0 else time_args[0] - self.seek_new			
        self.timecolor = self.meter_section[TIMECOLOR] if self.remain > 10 else (242,0,0) # red for last 10 seconds
        self.remain = '{:02d}:{:02d}'.format( self.remain // 60, self.remain %60)

    # render data functions
    # ----------------------------------
            
    def init_aa(self):
        """ create clean album art surface as backup """
    
        if self.meter_section[ALBUMART_POS]:
            self.aa_rect = pg.Rect(self.meter_section[ALBUMART_POS][0], self.meter_section[ALBUMART_POS][1], self.meter_section[ALBUMART_DIM][0], self.meter_section[ALBUMART_DIM][1])
            self.AABackup = None
            self.AABackup = self.screen.subsurface(self.aa_rect).copy()
    
    def render_aa(self):
        """ render albumart """

        def updateFade(img, a):
            img.set_alpha(a)
            self.screen.blit(img, self.aa_rect)
            pg.display.update(self.aa_rect)
            
        if self.meter_section[ALBUMART_POS]:
            # copy clean surface from backup
            self.screen.blit(self.AABackup, self.aa_rect)

            # mask image if png mask set
            if self.meter_section[ALBUMART_MSK]:
                # load mask image
                path = os.path.join(self.meter_config[BASE_PATH], self.meter_config[SCREEN_INFO][METER_FOLDER], self.meter_section[ALBUMART_MSK])
                mask_image = Image.open(path).convert('L')                
                # scale mask if needed
                if mask_image.size != self.aa_img.size:
                    mask_image = mask_image.resize(self.aa_img.size)
                # image composite
                self.aa_img.putalpha(ImageOps.invert(mask_image))
                #empty_image = Image.new('RGBA', self.aa_img.size, 0)
                #self.aa_img = Image.composite(empty_image, self.aa_img, mask_image)
                # put albumart image to surface
                self.aa_img = pg.image.fromstring(self.aa_img.tobytes(), self.aa_img.size, self.aa_img.mode)
                
                
            # fadeIn album art
            alpha = 20
            while alpha < 120 and self.run_flag:
                updateFade(self.aa_img, alpha)
                time.sleep(self.ui_refresh)
                alpha += 4
        
            if self.run_flag:
                updateFade(self.aa_img, 255) 
                        
            # draw border
            if self.meter_section[ALBUMBORDER]:
                pg.draw.rect(self.screen, self.fontcolor, self.aa_rect, self.meter_section[ALBUMBORDER])
                pg.display.update(self.aa_rect)
                           
    def stop_AA_FadeIn(self):
        self.run_flag = False
    
    def init_time(self): 
        """ create clean time surface as backup """

        self.imgTimeBackup = None
        if self.meter_section[TIME_REMAINING_POS]:
            self.time_rect = pg.Rect(self.meter_section[TIME_REMAINING_POS], self.fontDigi.size('00:00'))
            self.imgTimeBackup = self.screen.subsurface(self.time_rect).copy()
            
    def render_time(self):
        """ render time info """

        # copy clean surface from backup
        self.screen.blit(self.imgTimeBackup, self.time_rect)
        
        imgDigi = self.fontDigi.render(self.remain, True, self.timecolor)			
        # webradio has no time info
        if self.NoTime == False:
            self.screen.blit(imgDigi, self.time_rect)
        # update time rectangle
        pg.display.update(self.time_rect)
        
    def init_text(self):
        """ create clean text surfaces as backup """
        
        def set_txt_max(txtmax):
            if (txtmax):
                return txtmax
            else:
                return self.meter_section[PLAY_MAX]

        def size_txt(rendertxt, fontstyle):
            if fontstyle == FONT_STYLE_L:
                ret = self.fontL.size(rendertxt)
            elif fontstyle == FONT_STYLE_R:
                ret = self.fontR.size(rendertxt)
            else:
                ret = self.fontB.size(rendertxt)
            return ret
        
        # track type
        if self.meter_section[PLAY_TYPE_POS] and self.meter_section[PLAY_TYPE_DIM]:
            self.type_rect = pg.Rect(self.meter_section[PLAY_TYPE_POS], self.meter_section[PLAY_TYPE_DIM])
            self.imgFormatBackup = None
            self.imgFormatBackup = self.screen.subsurface(self.type_rect).copy()
        # title info
        if self.meter_section[PLAY_TITLE_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_TITLE_MAX]):
            txt_size = size_txt('A', self.meter_section[PLAY_TITLE_STYLE]) # for height
            self.title_rect = pg.Rect(self.meter_section[PLAY_TITLE_POS], (set_txt_max(self.meter_section[PLAY_TITLE_MAX]), txt_size[1]))
            self.imgTitleBackup = None
            self.imgTitleBackup = self.screen.subsurface(self.title_rect).copy()
        # artist info
        if self.meter_section[PLAY_ARTIST_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_ARTIST_MAX]):
            txt_size = size_txt('A', self.meter_section[PLAY_ARTIST_STYLE]) # for height
            self.artist_rect = pg.Rect(self.meter_section[PLAY_ARTIST_POS], (set_txt_max(self.meter_section[PLAY_ARTIST_MAX]), txt_size[1]))
            self.imgArtistBackup = None
            self.imgArtistBackup = self.screen.subsurface(self.artist_rect).copy()
        # album info			
        if self.meter_section[PLAY_ALBUM_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_ALBUM_MAX]):
            txt_size = size_txt('A', self.meter_section[PLAY_ALBUM_STYLE]) # for height
            self.album_rect = pg.Rect(self.meter_section[PLAY_ALBUM_POS], (set_txt_max(self.meter_section[PLAY_ALBUM_MAX]), txt_size[1]))
            self.imgAlbumBackup = None
            self.imgAlbumBackup = self.screen.subsurface(self.album_rect).copy()
        # frame rate info                
        if self.meter_section[PLAY_SAMPLE_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_SAMPLE_MAX]): 
            txt_size = size_txt('-44.1 kHz 24 bit-', self.meter_section[PLAY_SAMPLE_STYLE]) # max widht to create rectangle for clear area            
            if self.meter_section[PLAY_SAMPLE_MAX]:
                self.sample_rect = pg.Rect(self.meter_section[PLAY_SAMPLE_POS], (set_txt_max(self.meter_section[PLAY_SAMPLE_MAX]), txt_size[1]))
            else:
                sample_pos_x = self.meter_section[PLAY_SAMPLE_POS][0]
                # center sample position
                if self.meter_section[PLAY_CENTER] == True:
                    sample_pos_x += int((self.meter_section[PLAY_MAX] - txt_size[0])/2)
                self.sample_rect = pg.Rect((sample_pos_x, self.meter_section[PLAY_SAMPLE_POS][1]), txt_size)
            
            self.imgSampleBackup = None
            self.imgSampleBackup = self.screen.subsurface(self.sample_rect).copy()
        
    def render_text(self):
        """ render text objects """

        format_icons = ['tidal','cd','qobuz']
        if self.playinfo_trackT in format_icons:
            formatIcon = os.path.join(self.file_path, 'format-icons', self.playinfo_trackT + '.svg')
        else:
            formatIcon = os.path.join('/volumio/http/www3/app/assets-common/format-icons', self.playinfo_trackT + '.svg')
        
        def set_color(img, color):
            for x in range(img.get_width()):
                for y in range(img.get_height()):
                    color.a = img.get_at((x, y)).a  # Preserve the alpha value.
                    img.set_at((x, y), color)  # Set the color of the pixel.

        def set_txt_center(txtcenter):
            if(txtcenter != None):
                return txtcenter
            else:
                return self.meter_section[PLAY_CENTER]
        
        def set_txt_color(txtcolor):
            if (txtcolor):
                return txtcolor
            else:
                return self.fontcolor
                
        def render_txt(rendertxt, fontstyle, color):
            if fontstyle == FONT_STYLE_L:
                ret = self.fontL.render(rendertxt, True, color )
            elif fontstyle == FONT_STYLE_R:
                ret = self.fontR.render(rendertxt, True, color )
            else:
                ret = self.fontB.render(rendertxt, True, color )
            return ret

        def update_txt(imgtxt, rect):
            if set_txt_center(self.meter_section[PLAY_TXT_CENTER]) == True: # center title position
                self.screen.blit(imgtxt, (rect.centerx - int(imgtxt.get_width()/2), rect.y))
            else:
                self.screen.blit(imgtxt, rect)

            pg.display.update(rect)
                    
        # title, artist, album
        imgTitle_long = render_txt(self.playinfo_title, self.meter_section[PLAY_TITLE_STYLE], set_txt_color(self.meter_section[PLAY_TITLE_COLOR]))
        imgArtist_long = render_txt(self.playinfo_artist, self.meter_section[PLAY_ARTIST_STYLE], set_txt_color(self.meter_section[PLAY_ARTIST_COLOR]))            
        imgAlbum_long = render_txt(self.playinfo_album, self.meter_section[PLAY_ALBUM_STYLE], set_txt_color(self.meter_section[PLAY_ALBUM_COLOR]))
        # samplerate + bitdepth
        imgSample_long = render_txt((self.playinfo_sample + " " + self.playinfo_depth).rstrip(), self.meter_section[PLAY_SAMPLE_STYLE], self.meter_section[PLAY_TYPE_COLOR])
            
        if self.titleMem != self.playinfo_title: # only if title changed
        
            # trackType
            if self.meter_section[PLAY_TYPE_POS] and self.meter_section[PLAY_TYPE_DIM]:
                # copy clean surface from backup
                self.screen.blit(self.imgFormatBackup, self.type_rect)

                if os.path.exists(formatIcon):
                    # for pygame > 2.0 use internal svg functions 
                    if pg.version.ver.startswith("2"):
                        format_img = pg.image.load(formatIcon)
                        h = format_img.get_height()
                        w = format_img.get_width()
                    
                        # scale aspect ratio to dimension
                        sc = self.type_rect.height/h if h >= w else self.type_rect.width/w
                        format_img = pg.transform.smoothscale_by(format_img, sc)

                        set_color(format_img, pg.Color(self.meter_section[PLAY_TYPE_COLOR][0], self.meter_section[PLAY_TYPE_COLOR][1], self.meter_section[PLAY_TYPE_COLOR][2])) 

                        # center horizontal
                        if h >= w:
                            PlayTypePos = self.meter_section[PLAY_TYPE_POS] 
                        else:				
                            PlayTypePos = (self.meter_section[PLAY_TYPE_POS][0], int(self.meter_section[PLAY_TYPE_POS][1] + self.meter_section[PLAY_TYPE_DIM][1]/2 - format_img.get_height()/2))
                        self.screen.blit(format_img, PlayTypePos)
                    
                    # pygame 1.9 have no svg, use cairosvg
                    else:                    
                        try:
                            # convert to png with scaling
                            new_bites = cairosvg.svg2png(url = formatIcon, output_width = self.type_rect.width, output_height = self.type_rect.height)
                            imgType = Image.open(io.BytesIO(new_bites))
 
                            # create pygame image surface
                            format_img = pg.image.fromstring(imgType.tobytes(), imgType.size, imgType.mode)			
                            set_color(format_img, pg.Color(self.meter_section[PLAY_TYPE_COLOR][0], self.meter_section[PLAY_TYPE_COLOR][1], self.meter_section[PLAY_TYPE_COLOR][2])) 
			
                            # center type icon in surface
                            if imgType.height >= imgType.width:
                                PlayTypePos = self.meter_section[PLAY_TYPE_POS] 
                            else:				
                                PlayTypePos = (self.meter_section[PLAY_TYPE_POS][0], int(self.meter_section[PLAY_TYPE_POS][1] + self.meter_section[PLAY_TYPE_DIM][0]/2 - imgType.height/2))
                            self.screen.blit(format_img, PlayTypePos)
                    
                        # if cairosvg not properly installed use text instead
                        except:
                            if self.meter_section[PLAY_SAMPLE_POS]:
                                if self.meter_section[PLAY_CENTER] == True:
                                    typePos_Y = self.meter_section[PLAY_TYPE_POS][1]
                                    typeStr = self.playinfo_trackT
                                else:
                                    typePos_Y = self.meter_section[PLAY_SAMPLE_POS][1]
                                    typeStr = self.playinfo_trackT[:4]                            
                            
                                if self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_R:
                                    imgTrackT = self.fontR.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])
                                elif self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_B:
                                    imgTrackT = self.fontB.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])
                                else:
                                    imgTrackT = self.fontL.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])

                                self.type_rect = pg.Rect((self.meter_section[PLAY_TYPE_POS][0], typePos_Y), imgTrackT.get_size())                           
                                self.screen.blit(imgTrackT, self.type_rect)
 
                else:
                    # clear area, webradio has no type
                    self.screen.blit(self.imgFormatBackup, self.type_rect)
                
                # update tracktype rectangle
                pg.display.update(self.type_rect)

						
            # stop all ticker if title info changed
            self.stop_text_animator()
            
            # title info			
            if self.meter_section[PLAY_TITLE_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_TITLE_MAX]):
                # copy clean surface from backup
                self.screen.blit(self.imgTitleBackup, self.title_rect)

                if imgTitle_long.get_width() - 5 <= self.title_rect.width: 
                    update_txt(imgTitle_long, self.title_rect)
                else: # start ticker daemon title
                    self.text_animator_title = None
                    self.text_animator_title = self.start_text_animator(self.imgTitleBackup, imgTitle_long, self.title_rect)

            # artist info
            if self.meter_section[PLAY_ARTIST_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_ARTIST_MAX]):		
                # copy clean surface from backup
                self.screen.blit(self.imgArtistBackup, self.artist_rect)

                if imgArtist_long.get_width() - 5 <= self.artist_rect.width:
                    update_txt(imgArtist_long, self.artist_rect)
                else: # start ticker daemon artist
                    self.text_animator_artist = None
                    self.text_animator_artist = self.start_text_animator(self.imgArtistBackup, imgArtist_long, self.artist_rect)

            # album info			
            if self.meter_section[PLAY_ALBUM_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_ALBUM_MAX]):
                # copy clean surface from backup
                self.screen.blit(self.imgAlbumBackup, self.album_rect)

                if imgAlbum_long.get_width() - 5 <= self.album_rect.width:
                    update_txt(imgAlbum_long, self.album_rect)
                else: # start ticker daemon album
                    self.text_animator_album = None
                    self.text_animator_album = self.start_text_animator(self.imgAlbumBackup, imgAlbum_long, self.album_rect)

            # frame rate info                
            if self.meter_section[PLAY_SAMPLE_POS] and (self.meter_section[PLAY_MAX] or self.meter_section[PLAY_SAMPLE_MAX]): 
                # copy clean surface from backup
                self.screen.blit(self.imgSampleBackup, self.sample_rect)
                
                sample_pos_x = self.sample_rect.x
                if self.meter_section[PLAY_CENTER] == True and self.meter_section[PLAY_SAMPLE_MAX]:
                    # center sample position
                    sample_pos_x = self.sample_rect.centerx - int(imgSample_long.get_width()/2)

                # sample rate
                self.screen.blit(imgSample_long, (sample_pos_x, self.sample_rect.y))
                # update sample rectangle
                pg.display.update(self.sample_rect)

                
    # text animator functions
    # ----------------------------------
    def start_text_animator(self, imgBackup, imgTxt, imgRect):
        """ start daemon for text animation""" 
		
        a = TextAnimator(self.util, self.ui_refresh, imgBackup, imgTxt, imgRect)
        a.start()        
        return a
		
    def stop_text_animator(self):
        """ stop daemons for text animation """

        if hasattr(self, 'text_animator_title') and self.text_animator_title is not None:
            self.text_animator_title.stop_thread()			
            del self.text_animator_title
        if hasattr(self, 'text_animator_artist') and self.text_animator_artist is not None:
            self.text_animator_artist.stop_thread()			
            del self.text_animator_artist
        if hasattr(self, 'text_animator_album') and self.text_animator_album is not None:
            self.text_animator_album.stop_thread()
            del self.text_animator_album

        time.sleep(self.ui_refresh * 2)
        self.trim_memory()

    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)
        
# ===================================================================================================================		
class TextAnimator(Thread):
    """ Provides show ticker in a separate thread """
    
    def __init__(self, util, ui_refresh, imgBackup, imgTxt, imgRect):
        """ Initializer

        :param util: utility class
        :param ui_refresh_period
        :param imgBackup: backup surface for clean
        :param imTxt: txt surface
        :param imgRect: rectangle for update
        """
        Thread.__init__(self)
        
        self.util = util
        self.ui_refresh = ui_refresh
        self.screen = self.util.PYGAME_SCREEN		
        self.backup = imgBackup
        self.txt = imgTxt
        self.rct = imgRect
        self.run_flag = True
        
    def run(self):
        """ Thread method. draw ticker """
	
        x = 0
        while self.run_flag:
            
            self.screen.blit(self.backup, self.rct)
            #pg.draw.rect(self.screen, (200,200,200), self.rct)
            self.screen.blit(self.txt, (self.rct.x, self.rct.y), ((x, 0), self.rct.size))                        
            if self.rct.width + x >= self.txt.get_width():
                xd = -1 # backward
            elif x <= 0:
                xd = 1  # forward
            x += xd
            
            pg.display.update(self.rct)
            time.sleep(self.ui_refresh)


        # cleanup memory
        del self.screen		
        del self.backup
        del self.txt
        del self.rct
        self.trim_memory()
        
    def stop_thread(self):
        """ Stop thread """

        self.run_flag = False


    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)
            
# RepeatTimer for remaining time
class RepeatTimer(Timer):
    def run(self):
        self.function(*self.args, **self.kwargs)
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)
