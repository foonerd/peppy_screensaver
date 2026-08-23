// Copyright 2025 Volumio 4 adaptation by Just a Nerd
// Rewritten 2025 for Volumio 4 / Bookworm
//
// This file is part of PeppyMeter for Volumio
//
// Volumio 4 adaptations:
// - socket.io-client v2.4.0 syntax (compatible with Volumio backend)
// - Promise chain fixes (defer.resolve in all error handlers)

'use strict';

var libQ = require('kew');
var fs=require('fs-extra');
var config = new (require('v-conf'))();
var exec = require('child_process').exec;
var execSync = require('child_process').execSync;
var sizeOf = require('image-size');
var crypto = require('crypto');  // For config version hashing
var use_SDL2 = false;
var lt_4GB = false;

const lineReader = require('line-reader');
const io = require('socket.io-client');
const socket = io.connect('http://localhost:3000');
const path = require('path');
const ini = require('ini');
const peppyPluginVersion = require('./package.json').version;
//---
const id = 'peppy_screensaver: ';      // for logging
const PluginPath = '/data/plugins/user_interface/peppy_screensaver';
const DATA_DIR = '/data/INTERNAL/peppy_screensaver';  // themes (meters, spectrum, cassette, turntable, etc.)
const runFlag = '/tmp/peppyrunning';   // for detection, if peppymeter always running
const persistFile = '/tmp/peppy_persist';  // for persist countdown communication with Python
//---
var PeppyPath = PluginPath + '/screensaver/peppymeter';
var RunPeppyFile = PluginPath + '/run_peppymeter.sh';
var PeppyConf = PeppyPath + '/config.txt';
const meterFolderStr = 'meter.folder'; // entry in config.txt to detect template folder

// Continuity Engine - backup and restore of plugin settings
// Named backups live under DATA_DIR and survive uninstall/reinstall.
const BackupsPath = DATA_DIR + '/backups';
const BackupSchemaVersion = 1;
const BackupNameRegex = /^[A-Za-z0-9 _.\-]{1,64}$/;
const BackupMinFreeBytes = 10 * 1024 * 1024; // 10 MB safety margin
const BackupWarnCount = 20; // warn (not block) beyond this many backups
const BackupManifestName = 'manifest.json';
const PeppyConfBackupName = 'peppymeter_config.txt';
const SpectrumConfBackupName = 'spectrum_config.txt';
const ThemeGalleryDir = PluginPath + '/theme-gallery';
const ThemeGallerySectionPrefix = 'user_interface/peppy_screensaver/theme-gallery/';
// Artist fanart (Item 6): on-disk cache served via /albumart?sectionimage=...
const FanartCacheDir = PluginPath + '/fanart-cache';
const FanartSectionPrefix = 'user_interface/peppy_screensaver/fanart-cache/';
const FanartPersonalArtDir = '/data/albumart/personal/artist'; // Volumio's name-keyed artist art store
const FANART_TV_PROJECT_KEY = '9bb4ee75161ec1245cb377bf2716b90b'; // distributable project key (Peppy Screensaver)
const FANART_TTL_MS = 14 * 24 * 60 * 60 * 1000; // refresh online results every 14 days
const FANART_IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.webp'];
const FANART_MAX_IMAGES = 30; // bound cache/CPU per artist
// Remote handler-manifest contract (server-authoritative runtime sync for peppy_remote).
// api/min_remote_api gate the handler/wire protocol independently of the marketing version.
const REMOTE_API_VERSION = 1;
const REMOTE_MIN_API_VERSION = 1;
// Files the remote client may request. The manifest is generated live from disk, so it can
// never drift from what actually ships; these regexes are the only trust boundary.
const REMOTE_HANDLER_NAME_REGEX = /^(volumio_[A-Za-z0-9_]+\.py|screensaverspectrum\.py)$/;
const REMOTE_FONT_NAME_REGEX = /^[A-Za-z0-9 ._\-]+\.(ttf|otf)$/;
const REMOTE_CAPABILITIES = ['fanart', 'folderlayer', 'italic', 'samplerate_color', 'progress_markers', 'spectrum', 'remote', 'type_display_mode'];
const THEME_PREVIEW_FILES = ['preview.png', 'preview.jpg', 'preview.jpeg', 'art.png', 'art.jpg'];
const THEME_GALLERY_CACHE_EXTS = ['.png', '.jpg', '.jpeg'];
const THEME_GALLERY_COLS = 2;
const THEME_GALLERY_ACTIVE_BORDER = '#54C688';
const THEME_GALLERY_ACTIVE_SHADOW = '#2a6848';
// Gallery preview resolution logging - gated by peppy_config debug.level
// basic: resolved source; verbose: candidates/skips; trace: per-section detail
function galleryLog(logger, level, msg) {
    if (!peppy_config || !peppy_config.current) return;
    var cfgLevel = peppy_config.current['debug.level'] || 'off';
    var levels = { 'off': 0, 'basic': 1, 'verbose': 2, 'trace': 3 };
    if ((levels[cfgLevel] || 0) >= (levels[level] || 0)) {
        logger.info(id + 'GALLERY: ' + msg);
    }
}

const THEME_PREVIEW_METER_KEYS = [
  { key: 'meter.preview', source: 'meter.preview' },
  { key: 'screen.bgr', source: 'screen.bgr' },
  { key: 'bgr.filename', source: 'bgr.filename' }
];

var minmax = new Array(16);
var last_outputdevice, last_softmixer;
var peppy_config, base_folder_P;

const PluginConfiguration = '/data/configuration/plugins.json';
const MPDtmpl = '/volumio/app/plugins/music_service/mpd/mpd.conf.tmpl';
const MPD = '/tmp/mpd.conf.tmpl';
const MPD_include_tmpl = PluginPath + '/mpd_custom.conf';
const MPD_include = '/data/configuration/music_service/mpd/mpd_custom.conf';
const AIRtmpl = '/volumio/app/plugins/music_service/airplay_emulation/shairport-sync.conf.tmpl';
const AIR = '/tmp/shairport-sync.conf.tmpl';
const asound = '/Peppyalsa.postPeppyalsa.5.conf';

// Remote client config serving
var remoteConfigVersion = '';  // MD5 hash of config.txt for change detection

var availMeters = '';
var uiNeedsUpdate;
const spotify_config = '/data/plugins/music_service/spop/config.yml.tmpl';
const soloist_index = '/data/plugins/music_service/soloist_connect/index.js';
const dsp_config = '/data/plugins/audio_interface/fusiondsp/camilladsp.conf.yml';
module.exports = peppyScreensaver;

// for spectrum
var SpectrumPath = PluginPath + '/screensaver/spectrum';
var SpectrumConf = SpectrumPath + '/config.txt';
//const SpectrumTmp = '/tmp/spectrumconfig.txt';
const SpectrumFolderStr = 'spectrum.folder';// entry in config.txt to detect template folder
var spectrum_config, base_folder_S;

// ALSA config logging helper - gated by peppy_config debug.level
// basic: key decisions; verbose: inputs and outputs; trace: full config content
function alsaLog(logger, level, msg) {
    if (!peppy_config || !peppy_config.current) return;
    var cfgLevel = peppy_config.current['debug.level'] || 'off';
    var levels = { 'off': 0, 'basic': 1, 'verbose': 2, 'trace': 3 };
    if ((levels[cfgLevel] || 0) >= (levels[level] || 0)) {
        logger.info(id + 'ALSA: ' + msg);
    }
}

function peppyScreensaver(context) {
	var self = this;

	self.context = context;
	self.commandRouter = self.context.coreCommand;
	self.logger = self.context.logger;
	self.configManager = self.context.configManager;
};


peppyScreensaver.prototype.onVolumioStart = function()
{
	var self = this;
	var configFile = self.commandRouter.pluginManager.getConfigurationFile(self.context,'config.json');
	self.config = new (require('v-conf'))();
	self.config.loadFile(configFile);
	if (self.config.get('useSoloist') === undefined) {
		self.config.addConfigValue('useSoloist', 'boolean', true);
	}
        
    return libQ.resolve();
};

peppyScreensaver.prototype.onStart = function() {
    var self = this;
    var defer=libQ.defer();
    var lastStateIsPlaying = false;
    self.Timeout = null;
    self.persistTimer = null;

    // load language strings here again, otherwise needs restart after installation
    self.commandRouter.loadI18nStrings();
    
    // create fifo pipe for PeppyMeter/PeppySpectrum
    self.install_mkfifo('/tmp/myfifo');
    self.install_mkfifo('/tmp/myfifosa');
    self.holdMeterFifos();
    // load snd dummy for peppymeter output 
    self.install_dummy();

    // remove old flag
    if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}

    // get peppyMeter config and new baseFolder
    if (fs.existsSync(PeppyConf)){
        peppy_config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
        base_folder_P = peppy_config.current['base.folder'] + '/';
        if (base_folder_P == '/') {base_folder_P = PeppyPath + '/';}
        
        // One-time sync: copy remote settings from config.txt into Volumio config so UI state survives restart
        if (self.config.get('remoteServerEnabled') === undefined && peppy_config.current['remote.server.enabled'] !== undefined) {
            self.config.set('remoteServerEnabled', peppy_config.current['remote.server.enabled'] === 'true');
            self.config.set('remoteServerMode', peppy_config.current['remote.server.mode'] || 'server_local');
            self.config.set('remoteServerPort', parseInt(peppy_config.current['remote.server.port'], 10) || 5580);
            self.config.set('remoteDiscoveryPort', parseInt(peppy_config.current['remote.discovery.port'], 10) || 5579);
            self.config.set('remoteSpectrumPort', parseInt(peppy_config.current['remote.spectrum.port'], 10) || 5581);
            if (peppy_config.current['remote.spectrum.always'] !== undefined) {
                self.config.set('remoteSpectrumAlways', peppy_config.current['remote.spectrum.always'] === 'true');
            }
        }
    }

    // get peppySpectrum config and new baseFolder
    if (fs.existsSync(SpectrumConf)){
        spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
        base_folder_S = spectrum_config.current['base.folder'] + '/';
        if (base_folder_S == '/') {base_folder_S = SpectrumPath + '/';}
	}
	
    // copy MPD_include file and set output
    if (!fs.existsSync(MPD_include)) {self.copy_MPD_include(MPD_include_tmpl, MPD_include);}
    // only if it not correct deleted on uninstall
    // x64: ALWAYS enable MPD output - it's the only source for meter data
    var arch_cmd = 'cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'';
    var arch = '';
    try { arch = execSync(arch_cmd).toString().trim(); } catch(e) {}
    var isX64 = (arch === 'x64');
    // MPD output for meter: enable on x64 (always) or Pi DSD mode
    // Disable for Pi modular ALSA - uses inline meter instead
    var enableDSD = parseInt(self.config.get('alsaSelection'),10) == 1 ? true : false;
    var enableMPDOutput = isX64 ? true : enableDSD;
    self.MPD_setOutput(MPD_include, enableMPDOutput);
    
    // Set MPD output state via mpc (config file alone doesn't control live state)
    var mpcCmd = enableMPDOutput ? 'mpc enable 1' : 'mpc disable 1';
    setTimeout(function() {
        exec(mpcCmd, { uid: 1000, gid: 1000 }, function(error, stdout, stderr) {
            if (error) {
                self.logger.warn('peppy_screensaver: Startup - Failed to set MPD output: ' + error);
            } else {
                self.logger.info('peppy_screensaver: Startup - MPD output 1 ' + (enableMPDOutput ? 'enabled' : 'disabled'));
            }
        });
    }, 3000); // Wait for MPD to be ready at startup

    // check pygame 2 installed
    self.get_SDL2_enabled().then(function (SDL) { use_SDL2 = SDL; });
    // check installed Memory
    self.get_lt_4gb().then(function (lt4GB) { lt_4GB = lt4GB; });
              
    // inject additional include entry to mpd.conf, only if not exist, it's removed on stop
      try {
		var MPDdata = fs.readFileSync(MPDtmpl, 'utf8'); 
		if (!MPDdata.includes('include_optional')){
			fs.copySync(MPDtmpl, MPD); // copy orignal template file to /tmp
			self.add_mpd_include (MPD) // change the copy
                .then(self.mount_tmpl.bind(self, MPD, MPDtmpl)) // mount over original template
                .then(self.recreate_mpdconf.bind(self))         // recreate mpd.conf on /etc
                .then(self.restartMpd.bind(self));              // if the plugin starts to late restart mpd needed
		}
      } catch (err) {
        self.logger.error(id + MPDtmpl + 'not found');
      }

      // use spectrum config in /tmp (RAM)
      //fs.copySync(SpectrumConf, SpectrumTmp); // copy orignal template file to /tmp
      //self.mount_tmpl(SpectrumTmp, SpectrumConf) // mount over original template

    
      last_outputdevice = self.getAlsaConfigParam('outputdevice');
      last_softmixer = self.getAlsaConfigParam('softvolume');
      
      // Apply saved ALSA config on startup
      var alsaconf = parseInt(self.config.get('alsaSelection'),10);
      self.switch_alsaConfig(alsaconf);
      if (self.connectProvider() === 'conflict') {
        self.commandRouter.pushToastMessage('warning',
          self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
          self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CONNECT_CONFLICT_DESC'));
      }
      
      // event callback if outputdevice or mixer changed
      self.commandRouter.sharedVars.registerCallback('alsa.outputdevice', self.switch_alsaModular.bind(self));
      
      // synchronize external spotify settings with own configuration  
      if (self.connectProvider() === 'spop'){
        var spotifydata = fs.readFileSync(spotify_config, 'utf8'); 
        //var useSpot = self.config.get('useSpotify');
        //if ((useSpot && spotifydata.includes('volumio')) || (!useSpot && spotifydata.includes('spotify'))) {
        //    self.switch_Spotify(useSpot);
        //}
        var useDSP = fs.existsSync(dsp_config) && self.config.get('useDSP');
        if ((!useDSP && spotifydata.includes('volumio')) || (useDSP && spotifydata.includes('spotify'))) {
            self.switch_Spotify(!useDSP);
        }
      }  

	  // synchronize external airplay settings with own configuration
      if (fs.existsSync(AIRtmpl) && self.getPluginStatus ('music_service', 'airplay_emulation') === 'STARTED'){
		var airplaydata = fs.readFileSync(AIRtmpl, 'utf8'); 
		var useAir = self.config.get('useAirplay');
		if ((useAir && airplaydata.includes('${device}')) || (!useAir && airplaydata.includes('airplay'))) {
			self.switch_Airplay(useAir);
		}
	  }

    // event function on change state, to start PeppyMeter    
    socket.emit('getState', '');
    var lastService = '';
    var lastUri = '';
    
    socket.on('pushState', function (state) {
        // Defensive: reject malformed or missing state
        if (!state || typeof state !== 'object') {
            self.logger.warn(id + 'pushState: invalid state (null/undefined)');
            return;
        }
        var status = state.status;
        if (status === undefined || status === null) {
            self.logger.warn(id + 'pushState: missing status, skipping');
            return;
        }
        self.logger.info('peppy_screensaver: pushState - status=' + status + ' service=' + state.service + ' volatile=' + state.volatile);
        // screensaver only for enabled Spotify/Airplay support, enabled DSP and all other
        var DSP_ON = fs.existsSync(dsp_config) && self.config.get('useDSP');
        var Spotify_ON = fs.existsSync(spotify_config) && self.getPluginStatus ('music_service', 'spop') === 'STARTED' && self.config.get('useSpotify') && state.service === 'spop';
        var Airplay_ON = fs.existsSync(AIRtmpl) && self.getPluginStatus ('music_service', 'airplay_emulation') === 'STARTED' && self.config.get('useAirplay') && state.service === 'airplay_emulation';
        var Other_ON = state.service !== 'spop' && state.service !== 'airplay_emulation';
        
        // Get persist duration from config (0 = disabled, >0 = seconds to wait)
        var persistDuration = parseInt(self.config.get('persist_duration'), 10) || 0;
        var persistDisplay = self.config.get('persist_display') || 'freeze';
        
        // Detect if this is a transitional state (track change, seeking, etc.)
        // volatile=true indicates Volumio is in transition between states
        var isVolatile = state.volatile === true;
        // Volumio's getEmptyState() — called only at end-of-queue or when trackBlock is
        // missing — has status=stop, empty uri/title, and no volatile field (undefined).
        var isGetEmptyState = (status === 'stop' && (state.uri || '') === '' && (state.title || '') === '');
        
        // Detect track change within same service (next/previous)
        var isTrackChange = (state.service === lastService && state.uri && lastUri && state.uri !== lastUri);
        
        if (status === 'play') {
            // Clear any pending persist timer - playback resumed
            if (self.persistTimer) {
                clearTimeout(self.persistTimer);
                self.persistTimer = null;
                self.logger.info('peppy_screensaver: Persist timer cancelled - playback resumed');
            }
            // Cancel any pending transition grace timer - playback resumed
            if (self.transitionGraceTimer) {
                clearTimeout(self.transitionGraceTimer);
                self.transitionGraceTimer = null;
            }
            // Remove persist file
            try {
                if (fs.existsSync(persistFile)) fs.removeSync(persistFile);
            } catch(e) {}
            
            if (DSP_ON || Spotify_ON || Airplay_ON || Other_ON) {
                // Ensure screensaver start interval exists when playing
                // (may have been cleared on previous pause/stop)
                if (!self.Timeout) {
                    lastStateIsPlaying = true;
                    var ScreenTimeout = (parseInt(self.config.get('timeout'),10)) * 1000;
                  
                    if (ScreenTimeout > 0){ // for 0 do nothing
                        self.Timeout = setInterval(function () {
                          if (!fs.existsSync(runFlag)){
                            // Enable mpd_peppyalsa output before starting meter - only for DSD mode or x64
                            // Modular ALSA uses inline meter and output 1 must stay disabled
                            var alsaConf = parseInt(self.config.get('alsaSelection'),10);
                            var arch = '';
                            try { arch = execSync('cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'').toString().trim(); } catch(e) {}
                            if ((alsaConf == 1 || arch === 'x64') && state.service === 'mpd') {
                                exec('mpc enable 1 2>/dev/null', function(err) {});
                            }
                            exec( RunPeppyFile, { uid: 1000, gid: 1000 }, function (error, stdout, stderr) {        
                            if (error !== null) {
                                self.logger.error(id + 'Error start PeppyMeter: ' + error);
                            } else {
                                self.logger.info(id + 'Start PeppyMeter');
                            }    
                          });
                          }        
                        }, ScreenTimeout);
                    }
                }
            }
        } else if (lastStateIsPlaying) {
            // Pause or stop detected.
            //
            // Classification:
            //   status==='pause'  → genuine, including Soloist (Volumio sets volatile:true
            //                        for the whole volatile session, so volatile is not a
            //                        pause/handoff discriminator)
            //   isGetEmptyState   → end-of-queue (Volumio pushEmptyState has no volatile field,
            //                        empty title/uri). Deterministic — always genuine.
            //   status==='stop'   → track-change fall-through OR user stop. Grace timer so a
            //                        following 'play' (track change) can cancel the stop.
            
            if (status === 'pause' || isGetEmptyState) {
                // Pause or end-of-queue: genuine stop, act immediately
                self.logger.info('peppy_screensaver: Genuine stop — ' + (status === 'pause' ? 'paused' : 'end of queue'));
                
                if (self.transitionGraceTimer) {
                    clearTimeout(self.transitionGraceTimer);
                    self.transitionGraceTimer = null;
                }
                
                if (self.Timeout) {
                    clearInterval(self.Timeout);
                    self.Timeout = null;
                }
                
                if (persistDuration > 0 && fs.existsSync(runFlag)) {
                    if (self.persistTimer) {
                        clearTimeout(self.persistTimer);
                    }
                    
                    self.logger.info('peppy_screensaver: Starting persist timer - ' + persistDuration + 's');
                    
                    try {
                        fs.writeFileSync(persistFile, persistDuration + ':' + Date.now() + ':' + persistDisplay);
                    } catch(e) {}
                    
                    self.persistTimer = setTimeout(function() {
                        self.persistTimer = null;
                        try {
                            if (fs.existsSync(persistFile)) fs.removeSync(persistFile);
                        } catch(e) {}
                        if (fs.existsSync(runFlag)) {
                            fs.removeSync(runFlag);
                            self.logger.info('peppy_screensaver: Persist timer expired - stopping PeppyMeter');
                        }
                        lastStateIsPlaying = false;
                    }, persistDuration * 1000);
                    
                } else {
                    if (fs.existsSync(runFlag)) {
                        fs.removeSync(runFlag);
                    }
                    lastStateIsPlaying = false;
                }
            } else if (status === 'stop') {
                // Stop with metadata (volatile===false or undefined, not getEmptyState).
                // Could be track-change (play follows) or user-stop (no play follows).
                // Use a grace timer: if play arrives it cancels; otherwise treat as genuine.
                if (self.transitionGraceTimer) {
                    clearTimeout(self.transitionGraceTimer);
                }
                
                var TRANSITION_GRACE_MS = 5000;
                self.logger.info('peppy_screensaver: Stop with metadata — grace timer ' + TRANSITION_GRACE_MS + 'ms');
                
                self.transitionGraceTimer = setTimeout(function() {
                    self.transitionGraceTimer = null;
                    self.logger.info('peppy_screensaver: Grace timer expired — treating as genuine stop');
                    
                    if (self.Timeout) {
                        clearInterval(self.Timeout);
                        self.Timeout = null;
                    }
                    
                    if (persistDuration > 0 && fs.existsSync(runFlag)) {
                        if (self.persistTimer) {
                            clearTimeout(self.persistTimer);
                        }
                        
                        self.logger.info('peppy_screensaver: Starting persist timer - ' + persistDuration + 's');
                        
                        try {
                            fs.writeFileSync(persistFile, persistDuration + ':' + Date.now() + ':' + persistDisplay);
                        } catch(e) {}
                        
                        self.persistTimer = setTimeout(function() {
                            self.persistTimer = null;
                            try {
                                if (fs.existsSync(persistFile)) fs.removeSync(persistFile);
                            } catch(e) {}
                            if (fs.existsSync(runFlag)) {
                                fs.removeSync(runFlag);
                                self.logger.info('peppy_screensaver: Persist timer expired - stopping PeppyMeter');
                            }
                            lastStateIsPlaying = false;
                        }, persistDuration * 1000);
                        
                    } else {
                        if (fs.existsSync(runFlag)) {
                            fs.removeSync(runFlag);
                        }
                        lastStateIsPlaying = false;
                    }
                }, TRANSITION_GRACE_MS);
            }
            
            // Volatile Soloist/spop pause is genuine persist. Do not delete the
            // persist file on that path — Python only draws the persist countdown
            // while the file exists. Clear it on volatile stop/handoff only.
            if (isVolatile && status !== 'pause' && !isGetEmptyState) {
                try {
                    if (fs.existsSync(persistFile)) {
                        fs.removeSync(persistFile);
                        self.logger.info(id + 'pushState: volatile stop, cleared persist file');
                    }
                } catch (e) {}
            }
        }
        
        // Track state for next event
        lastService = state.service || '';
        lastUri = state.uri || '';
    });
    
    // Register REST endpoint for remote config access
    // This allows remote clients to fetch config.txt via HTTP:
    // GET /api/v1/pluginEndpoint?endpoint=peppy_screensaver&method=getRemoteConfig
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getRemoteConfig'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver');

    // Register REST endpoint for remote font fetch (POST with { endpoint, data: { filename } })
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_font',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getFont'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_font');
    
    // Register REST endpoint for remote vinyl fetch (album-folder vinyl for peppy_remote)
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_vinyl',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getVinylImage'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_vinyl');

    // Theme gallery: select via clickable name links (select.html shim POSTs to REST, then redirects)
    // POST /api/v1/pluginEndpoint  body: { endpoint: 'peppy_screensaver_theme', data: { folder: '1280x720_MyTheme_style' } }
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_theme',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'selectThemeFromGallery'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_theme');

    // Extra folder-image layer (Item 5): fetch a decorative image from the playing
    // track's folder. POST { endpoint: 'peppy_screensaver_folderimage', data: { uri, filenames } }
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_folderimage',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getFolderImage'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_folderimage');

    // Artist fanart slideshow (Item 6): server resolves the cascade (personal folder ->
    // fanart/ subfolder -> fanart.tv -> meta.volumio.org) and returns sectionimage paths.
    // POST { endpoint: 'peppy_screensaver_artistfanart', data: { artist, uri } }
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_artistfanart',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getArtistFanart'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_artistfanart');

    // Server-authoritative handler manifest for peppy_remote: lists the exact handler
    // (.py) and font files this plugin runs, with sha256 + the API contract, so a remote
    // can hydrate byte-identical handlers from the server it connects to (no GitHub branch
    // coupling, no hardcoded file lists). GET/POST { endpoint: 'peppy_screensaver_manifest' }
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_manifest',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getRemoteManifest'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_manifest');

    // Companion file-delivery endpoint: returns a single manifest-listed handler or font
    // as base64. Strictly whitelisted by name regex (no path traversal).
    // POST { endpoint: 'peppy_screensaver_file', data: { kind: 'handler'|'font', name } }
    self.commandRouter.addPluginRestEndpoint({
        endpoint: 'peppy_screensaver_file',
        type: 'user_interface',
        name: 'peppy_screensaver',
        method: 'getRemoteFile'
    });
    self.logger.info(id + 'REST endpoint registered: peppy_screensaver_file');
    
    // Initialize config version on startup
    self.updateConfigVersion();
    
    // Normalize template folder permissions for SMB share access on startup
    if (self.config.get('smbShareAccess') === true) {
        self.normalizeTemplatePermissions(true);
    }
    
    // Once the Plugin has successfull started resolve the promise
	defer.resolve();       
 
    return defer.promise;
}; // end onStart ----------------------------


peppyScreensaver.prototype.onStop = function() {
    var self = this;
    var defer=libQ.defer();

    self.releaseMeterFifos();

    self.commandRouter.stateMachine.stop().then(function () {
        if (fs.existsSync(MPD)){
            //unmount mpd_tmpl file, if mounted
            self.unmount_tmpl(MPDtmpl)
                .then(function() {fs.removeSync(MPD);}
            );
                //.then(function(){                  
                //    self.recreate_mpdconf();
                //        .then(self.restartMpd.bind(self));
                //});
        } else {
            self.logger.info (id + 'mpd template already unmounted');
        }

        //umount spectrum config
        //if (fs.existsSync(SpectrumTmp)){self.unmount_tmpl(SpectrumConf);}
        
        //unmount air_tmpl file, if mounted
        if (fs.existsSync(AIR)){self.unmount_tmpl(AIRtmpl);}
        
        // redirect spotify to volumio
        if (fs.existsSync(spotify_config)){self.switch_Spotify(false);}
		
        // clear timeout interval
        if (self.Timeout) {
            clearInterval(self.Timeout);
            self.Timeout = null;
        }
        
        // clear persist timer
        if (self.persistTimer) {
            clearTimeout(self.persistTimer);
            self.persistTimer = null;
        }
        
        // clear transition grace timer
        if (self.transitionGraceTimer) {
            clearTimeout(self.transitionGraceTimer);
            self.transitionGraceTimer = null;
        }
        
        // remove old flag
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
        
        // Unregister REST endpoint
        self.commandRouter.removePluginRestEndpoint({
            endpoint: 'peppy_screensaver'
        });
        
        defer.resolve();                
          
        // stop events
        socket.off('pushState');
    });
    
    return libQ.resolve();
}; // end onStop ---------------------------------


peppyScreensaver.prototype.onRestart = function() {
    var self = this;
    // Optional, use if you need it
};

peppyScreensaver.prototype.onInstall = function () {
    var self = this;
};

peppyScreensaver.prototype.onUninstall = function () {
  var self = this;
  //Perform your installation tasks here
  
        // remove MPD_include file
        if (fs.existsSync(MPD_include)){fs.removeSync(MPD_include);}
        
        if (fs.existsSync(spotify_config)){
            // redirect spotify to volumio
            self.switch_Spotify(false);
        }
		if (fs.existsSync(AIR)){
            //unmount air_tmpl file, if mounted
            self.unmount_tmpl(AIRtmpl);
        //        .then(function() {fs.removeSync(AIR);});
		}
};

// Configuration Methods -----------------------------------------------------------------------------

peppyScreensaver.prototype.getUIConfig = function() {
    var defer = libQ.defer();
    var self = this;

    var lang_code = self.commandRouter.sharedVars.get('language_code');

    self.commandRouter.i18nJson(__dirname+'/i18n/strings_'+lang_code+'.json',
        __dirname+'/i18n/strings_en.json',
        __dirname + '/UIConfig.json')
        .then(function(uiconf)
        {

        // Resolve a control by its (now unique) id, independent of which section or
        // position it occupies. This keeps getUIConfig correct across settings
        // reorganisation (no hard-coded sections[N].content[M] indices to drift).
        var C = function (controlId) {
            for (var _si = 0; _si < uiconf.sections.length; _si++) {
                var _content = uiconf.sections[_si] && uiconf.sections[_si].content;
                if (!_content) { continue; }
                for (var _ci = 0; _ci < _content.length; _ci++) {
                    if (_content[_ci] && _content[_ci].id === controlId) { return _content[_ci]; }
                }
            }
            self.logger.error(id + 'getUIConfig: control id not found: ' + controlId);
            return { value: {}, options: [], attributes: [{}, {}, {}, {}] };
        };

        // Build the configManager path string ('sections[..].content[..].options') for a
        // control by id, so pushUIConfigParam stays position-independent too.
        var P = function (controlId) {
            for (var _si = 0; _si < uiconf.sections.length; _si++) {
                var _content = uiconf.sections[_si] && uiconf.sections[_si].content;
                if (!_content) { continue; }
                for (var _ci = 0; _ci < _content.length; _ci++) {
                    if (_content[_ci] && _content[_ci].id === controlId) {
                        return 'sections[' + _si + '].content[' + _ci + '].options';
                    }
                }
            }
            self.logger.error(id + 'getUIConfig: option-path id not found: ' + controlId);
            return 'sections[' + 0 + '].content[' + 0 + '].options';
        };

        // section 0 -----------------------------        
        if (fs.existsSync(PeppyConf)){
            // read values from ini
            //var config = ini.parse(fs.readFileSync(config_file, 'utf-8'));
            var meters_file = base_folder_P + peppy_config.current[meterFolderStr] + '/meters.txt';
            var upperc = /\b([^-])/g;
            
            var alsaconf = parseInt(self.config.get('alsaSelection'),10);
                if (self.config.get('useDSP')) {
                    C('alsaSelection').value.value = 0;
                    C('alsaSelection').value.label = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.ALSA_SELECTION_0');
                } else {
                    C('alsaSelection').value.value = alsaconf;
                    C('alsaSelection').value.label = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.ALSA_SELECTION_' + self.config.get('alsaSelection'));
                }
                
                // Dsp integration
                if (fs.existsSync(dsp_config)){
                    var useDSP = self.config.get('useDSP');
                    C('useDSP').value = useDSP;
                    self.checkDSPactive(!useDSP);
                } else {
                    self.config.set('useDSP', false);
                    C('useDSP').hidden = true;
                }
                // Spotify Connect (spop) and Soloist are exclusive. The operator
                // enables one music_service plugin; this UI shows that plugin's
                // meter switch only. useSpotify still rewrites librespot YAML.
                var connectProvider = self.connectProvider();
                C('useSoloist').hidden = true;
                if (connectProvider === 'conflict') {
                    C('useSpotify').hidden = true;
                    C('useUSBDAC').hidden = true;
                    for (var _as = 0; _as < uiconf.sections.length; _as++) {
                        if (uiconf.sections[_as].id === 'audio_source_conf') {
                            uiconf.sections[_as].description = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CONNECT_CONFLICT_DESC');
                            break;
                        }
                    }
                    self.commandRouter.pushToastMessage('warning',
                        self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                        self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CONNECT_CONFLICT_DESC'));
                } else if (connectProvider === 'soloist') {
                    C('useSpotify').hidden = true;
                    C('useUSBDAC').hidden = true;
                    if (self.config.get('useDSP')) {
                        self.config.set('useSoloist', false);
                    } else {
                        C('useSoloist').hidden = false;
                        C('useSoloist').value = self.config.get('useSoloist') === true;
                    }
                } else if (connectProvider === 'spop') {
                    if (self.config.get('useDSP')) {
                        self.config.set('useSpotify', false);
                    } else {
                        C('useSpotify').value = self.config.get('useSpotify');
                        C('useUSBDAC').value = self.config.get('useUSBDAC');
                    }
                } else {
                    self.config.set('useSpotify', false);
                    C('useSpotify').hidden = true;
                    C('useUSBDAC').hidden = true;
                }
                // Airplay integration
                if (self.getPluginStatus ('music_service', 'airplay_emulation') === 'STARTED'){
                    if (self.config.get('useDSP')) {
                        self.config.set('useAirplay', false);
                    } else {
                        C('useAirplay').value = self.config.get('useAirplay');
                    }
                } else {
                    C('useAirplay').hidden = true;
                }
            
            // screensaver timeout
            C('timeout').value = self.config.get('timeout');
            minmax[0] = [C('timeout').attributes[2].min,
                C('timeout').attributes[3].max,
                C('timeout').attributes[0].placeholder];
            
            // Theme-to-remove: empty placeholder first so nothing is pre-selected for deletion
            self.configManager.pushUIConfigParam(uiconf, P('themeToRemove'), {
                value: '',
                label: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_NONE')
            });
            // active folder
            // fill selection list with custom folders
            var files = fs.readdirSync(base_folder_P);
            files.forEach(file => {
                var stat = fs.statSync(base_folder_P + file);
                if (stat.isDirectory() && file.includes ('_')) {
                    var partFile = file.split('_');
                    var str_empty = fs.existsSync(base_folder_P + file + '/meters.txt') ? '' : ' (empty)';
                    var folderLabel = (partFile[1]).replace(upperc, c => c.toUpperCase()) + '-' +  partFile[2] + ' ' + partFile[0] + str_empty;
                    self.configManager.pushUIConfigParam(uiconf, P('activeFolder'), {
                        value: file,
                        label: folderLabel
                    });
                    // Theme gallery section (sections[1]): populate the "theme to remove" dropdown
                    self.configManager.pushUIConfigParam(uiconf, P('themeToRemove'), {
                        value: file,
                        label: folderLabel
                    });
                }
            });
            // Default the remove dropdown to the empty placeholder (no destructive pre-selection)
            C('themeToRemove').value.value = '';
            C('themeToRemove').value.label = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_NONE');
            // Artwork: artist fanart slideshow controls (Item 6)
            C('fanartEnabled').value = self.config.get('fanartEnabled') === true;
            var fanartKeyMode = self.config.get('fanartKeyMode') || 'personal';
            C('fanartKeyMode').value.value = fanartKeyMode;
            C('fanartKeyMode').value.label = self.commandRouter.getI18nString(fanartKeyMode === 'project' ? 'PEPPY_SCREENSAVER.FANART_KEY_MODE_PROJECT' : 'PEPPY_SCREENSAVER.FANART_KEY_MODE_PERSONAL');
            C('fanart_personal_key').value = self.config.get('fanart_personal_key') || '';
            C('fanartInterval').value = parseInt(self.config.get('fanartInterval'), 10) || 0;
            var fanartOrder = self.config.get('fanartOrder') || 'sequential';
            if (['sequential', 'random'].indexOf(fanartOrder) === -1) { fanartOrder = 'sequential'; }
            var fanartOrderLabels = {sequential: 'PEPPY_SCREENSAVER.FANART_ORDER_SEQUENTIAL', random: 'PEPPY_SCREENSAVER.FANART_ORDER_RANDOM'};
            C('fanartOrder').value.value = fanartOrder;
            C('fanartOrder').value.label = self.commandRouter.getI18nString(fanartOrderLabels[fanartOrder] || fanartOrderLabels.sequential);
            var fanartTransition = self.config.get('fanartTransition') || 'none';
            var fanartTransitionLabels = {none: 'PEPPY_SCREENSAVER.FANART_TRANSITION_NONE', fade: 'PEPPY_SCREENSAVER.FANART_TRANSITION_FADE', merge: 'PEPPY_SCREENSAVER.FANART_TRANSITION_MERGE'};
            C('fanartTransition').value.value = fanartTransition;
            C('fanartTransition').value.label = self.commandRouter.getI18nString(fanartTransitionLabels[fanartTransition] || fanartTransitionLabels.none);
            C('fanartTransitionMs').value = parseInt(self.config.get('fanartTransitionMs'), 10) || 600;
            C('fanartUnlimitedImages').value = self.config.get('fanartUnlimitedImages') === true;
            //if (self.config.get('activeFolder') == '') {
            var meterFolder = peppy_config.current[meterFolderStr];
            if (meterFolder.includes ('_')) {
                var partFile = meterFolder.split('_');
                var str_empty = fs.existsSync(base_folder_P + meterFolder + '/meters.txt') ? '' : ' (empty)';
                C('activeFolder').value.value = meterFolder;
                C('activeFolder').value.label = (partFile[1]).replace(upperc, c => c.toUpperCase()) + '-' +  partFile[2] + ' ' + partFile[0] + str_empty;
            } else {
                C('activeFolder').value.value = self.config.get('activeFolder');
                C('activeFolder').value.label = self.config.get('activeFolder_title');
            }

            if (use_SDL2) {
            // position type
                if (peppy_config.current['position.type'] == 'center') { 
                    C('positionType').value.value = 0;
                    C('positionType').value.label = 'centered';
                } else {
                    C('positionType').value.value = 1;
                    C('positionType').value.label = 'manually';
                }
            // position x
                C('position_x').value = parseInt(peppy_config.current['position.x'], 10);
                minmax[1] = [C('position_x').attributes[2].min,
                    C('position_x').attributes[3].max,
                    C('position_x').attributes[0].placeholder];
            // position y
                C('position_y').value = parseInt(peppy_config.current['position.y'], 10);
                minmax[2] = [C('position_y').attributes[2].min,
                    C('position_y').attributes[3].max,
                    C('position_y').attributes[0].placeholder];
            // animation
                var animation = (peppy_config.current['start.animation']).toLowerCase() == 'true' ? true : false;
                C('animation').value = animation;
            } else {
                C('positionType').hidden = true;
                C('positionType').value.value = 0;
                C('positionType').value.label = 'centered';

                C('animation').hidden = true; // animation
                C('animation').value = false;
            }

            // smooth buffer
            C('smoothBuffer').value = parseInt(peppy_config.data.source['smooth.buffer.size'], 10);                                
            minmax[3] = [C('smoothBuffer').attributes[2].min,
                C('smoothBuffer').attributes[3].max,
                C('smoothBuffer').attributes[0].placeholder];

            // for installed memory < 4Gb hide needle cache
            if (lt_4GB) {
                C('needleCache').hidden = true;
                C('needleCache').value = false;
            } else {
            // needle cache
                var needleCache = (peppy_config.current['use.cache']).toLowerCase() == 'true' ? true : false;
                C('needleCache').value = needleCache;

            // cache size
                C('cachesize').value = parseInt(peppy_config.current['cache.size'], 10);                                
                minmax[4] = [C('cachesize').attributes[2].min,
                    C('cachesize').attributes[3].max,
                    C('cachesize').attributes[0].placeholder];
            }

            // meter sensitivity (may be negative; do not use || 0 which would clobber valid 0)
            var meterGainVal = parseInt(peppy_config.data.source['volume.gain.db'], 10);
            C('meterGain').value = Number.isFinite(meterGainVal) ? meterGainVal : 0;
            minmax[15] = [C('meterGain').attributes[2].min,
                C('meterGain').attributes[3].max,
                C('meterGain').attributes[0].placeholder];
            
            // mouse support
            var mouseSupport = (peppy_config.sdl.env['mouse.enabled']).toLowerCase() == 'true' ? true : false;
            C('mouseEnabled').value = mouseSupport;

            // display output
            C('displayOutput').value.value = self.config.get('displayOutput');
            C('displayOutput').value.label = 'Display=' + self.config.get('displayOutput');
            C('doNotDeleteThemes').value = self.config.get('doNotDeleteThemes') === true;

            // format / type display mode (config.txt [current] playinfo.type.mode)
            var formatTypeMode = peppy_config.current['playinfo.type.mode'] || 'icon';
            if (formatTypeMode !== 'icon' && formatTypeMode !== 'text' && formatTypeMode !== 'both') {
                formatTypeMode = 'icon';
            }
            var formatTypeOptions = C('formatTypeMode').options;
            for (var i = 0; i < formatTypeOptions.length; i++) {
                if (formatTypeOptions[i].value === formatTypeMode) {
                    C('formatTypeMode').value = formatTypeOptions[i];
                    break;
                }
            }

            // use system fonts (from config.txt, default false = use PeppyFont)
            var useSystemFonts = false;
            try {
                useSystemFonts = (peppy_config.current['use.system.fonts'] || '').toLowerCase() === 'true';
            } catch (e) {}
            C('useSystemFonts').value = useSystemFonts;

            // SMB share access (from config.json, default false)
            var smbEnabled = self.config.get('smbShareAccess') === true;
            C('smbShareAccess').value = smbEnabled;
            
            // Normalize template permissions on settings page access
            // Reclaims ownership from SMB-created files (nobody:nogroup -> volumio:volumio)
            if (smbEnabled) {
                self.normalizeTemplatePermissions(true);
            }
             
            // section 6 - Playback Behavior -----------------------------
            var persistVal = self.config.get('persist_duration');
            // Handle 0 (Disabled) as valid value - don't use || which treats 0 as falsy
            if (persistVal === undefined || persistVal === null || persistVal === '') {
                persistVal = '30';
            }
            persistVal = String(persistVal);
            var persistLabels = {
                '0': 'PEPPY_SCREENSAVER.PERSIST_DISABLED',
                '5': 'PEPPY_SCREENSAVER.PERSIST_5',
                '15': 'PEPPY_SCREENSAVER.PERSIST_15',
                '30': 'PEPPY_SCREENSAVER.PERSIST_30',
                '60': 'PEPPY_SCREENSAVER.PERSIST_60',
                '120': 'PEPPY_SCREENSAVER.PERSIST_120',
                '300': 'PEPPY_SCREENSAVER.PERSIST_300'
            };
            C('persist_duration').value.value = persistVal;
            C('persist_duration').value.label = self.commandRouter.getI18nString(persistLabels[persistVal] || 'PEPPY_SCREENSAVER.PERSIST_30');

            var persistDisplayVal = self.config.get('persist_display') || 'freeze';
            var persistDisplayLabels = {
                'freeze': 'PEPPY_SCREENSAVER.PERSIST_DISPLAY_FREEZE',
                'countdown': 'PEPPY_SCREENSAVER.PERSIST_DISPLAY_COUNTDOWN'
            };
            C('persist_display').value.value = persistDisplayVal;
            C('persist_display').value.label = self.commandRouter.getI18nString(persistDisplayLabels[persistDisplayVal] || 'PEPPY_SCREENSAVER.PERSIST_DISPLAY_FREEZE');

            // queue mode (read from PeppyConf, fallback to config.json)
            var queueMode = 'track';
            if (fs.existsSync(PeppyConf)) {
                queueMode = peppy_config.current['queue.mode'] || 'track';
            } else {
                queueMode = self.config.get('queue.mode') || 'track';
            }
            
            var queueModeOptions = C('queueMode').options;
            for (var i = 0; i < queueModeOptions.length; i++) {
                if (queueModeOptions[i].value === queueMode) {
                    C('queueMode').value = queueModeOptions[i];
                    break;
                }
            }

            // section 1 - VU-Meter settings -----------------------------
            availMeters = '';
           
            if (fs.existsSync(meters_file)){
                var metersconfig = ini.parse(fs.readFileSync(meters_file, 'utf-8'));

                // current meter
                if ((peppy_config.current.meter).includes(',')) {
                    C('meter').value.value = 'list';
                } else {
                    C('meter').value.value = peppy_config.current.meter;
                }
                C('meter').value.label = (C('meter').value.value).replace(upperc, c => c.toUpperCase());

                // read all sections from active meters.txt and fill selection list
                for (var section in metersconfig) {
                    availMeters += section + ', ';
                    self.configManager.pushUIConfigParam(uiconf, P('meter'), {
                        value: section,
                        label: section.replace(upperc, c => c.toUpperCase())
                    });
                }

                // list selection
                availMeters = availMeters.substring(0, availMeters.length -2);
                if (self.config.get('randomSelection') == '') {
                    C('randomSelection').value = availMeters;
                } else {
                    C('randomSelection').value = self.config.get('randomSelection');
                }
                C('randomSelection').doc = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.RANDOMSELECTION_DOC') + '<b>' + availMeters + '</b>';

                // random mode (visible only for random and list)
                if (C('meter').value.value == 'random' || C('meter').value.value == 'list') {
                    C('randomMode').hidden = false;
                }
                var random_change_title = (peppy_config.current['random.change.title']).toLowerCase() == 'true' ? true : false;
                if (random_change_title) {
                    C('randomMode').value.value = 'titlechange';
                    C('randomMode').value.label = 'On Title Change';
                } else {
                    C('randomMode').value.value = 'interval';
                    C('randomMode').value.label = 'Interval';
                }    
                
                // random intervall
                C('randomInterval').value = parseInt(peppy_config.current['random.meter.interval'], 10);
                minmax[5] = [C('randomInterval').attributes[2].min,
                    C('randomInterval').attributes[3].max,
                    C('randomInterval').attributes[0].placeholder];

            }
            
            // section 2 - Performance settings -----------------------------
            // frame rate
            var frameRate = parseInt(peppy_config.current['frame.rate'], 10) || 30;
            C('frameRate').value = frameRate;
            minmax[6] = [C('frameRate').attributes[2].min,
                C('frameRate').attributes[3].max,
                C('frameRate').attributes[0].placeholder];
            
            // update interval (from peppy config.txt)
            var updateInterval = parseInt(peppy_config.current['update.interval'], 10) || 2;
            C('updateInterval').value = updateInterval;
            minmax[7] = [C('updateInterval').attributes[2].min,
                C('updateInterval').attributes[3].max,
                C('updateInterval').attributes[0].placeholder];
            
            // meter delay (ms)
            var meterDelay = parseInt(peppy_config.current['meter.delay'], 10);
            if (isNaN(meterDelay)) meterDelay = 10;
            C('meterDelay').value = meterDelay;
            minmax[8] = [C('meterDelay').attributes[2].min,
                C('meterDelay').attributes[3].max,
                C('meterDelay').attributes[0].placeholder];
            
            // section 4 - Scrolling settings -----------------------------
            // scrolling mode
            var scrollingMode = peppy_config.current['scrolling.mode'] || 'skin';
            var scrollingOptions = C('scrollingMode').options;
            for (var i = 0; i < scrollingOptions.length; i++) {
                if (scrollingOptions[i].value === scrollingMode) {
                    C('scrollingMode').value = scrollingOptions[i];
                    break;
                }
            }
            
            // scrolling speed artist
            var scrollSpeedArtist = parseInt(peppy_config.current['scrolling.speed.artist'], 10) || 40;
            C('scrollingSpeedArtist').value = scrollSpeedArtist;
            
            // scrolling speed title
            var scrollSpeedTitle = parseInt(peppy_config.current['scrolling.speed.title'], 10) || 40;
            C('scrollingSpeedTitle').value = scrollSpeedTitle;
            
            // scrolling speed album
            var scrollSpeedAlbum = parseInt(peppy_config.current['scrolling.speed.album'], 10) || 40;
            C('scrollingSpeedAlbum').value = scrollSpeedAlbum;
            
            // section 5 - Animation settings -----------------------------
            // transition type
            var transitionType = peppy_config.current['transition.type'] || 'fade';
            var transitionOptions = C('transitionType').options;
            for (var i = 0; i < transitionOptions.length; i++) {
                if (transitionOptions[i].value === transitionType) {
                    C('transitionType').value = transitionOptions[i];
                    break;
                }
            }
            
            // transition duration
            var transitionDuration = parseFloat(peppy_config.current['transition.duration']);
            if (isNaN(transitionDuration)) { transitionDuration = 0.5; }
            C('transitionDuration').value = transitionDuration;
            minmax[9] = [C('transitionDuration').attributes[2].min,
                C('transitionDuration').attributes[3].max,
                C('transitionDuration').attributes[0].placeholder];
            
            // transition color
            var transitionColor = peppy_config.current['transition.color'] || 'black';
            var colorOptions = C('transitionColor').options;
            for (var i = 0; i < colorOptions.length; i++) {
                if (colorOptions[i].value === transitionColor) {
                    C('transitionColor').value = colorOptions[i];
                    break;
                }
            }
            
            // transition opacity
            var transitionOpacity = parseInt(peppy_config.current['transition.opacity'], 10);
            if (isNaN(transitionOpacity)) transitionOpacity = 100;
            C('transitionOpacity').value = transitionOpacity;
            minmax[10] = [C('transitionOpacity').attributes[2].min,
                C('transitionOpacity').attributes[3].max,
                C('transitionOpacity').attributes[0].placeholder];
            
            // section 3 - Rotation settings -----------------------------
            // rotation quality
            var rotationQuality = peppy_config.current['rotation.quality'] || 'medium';
            var qualityOptions = C('rotationQuality').options;
            for (var i = 0; i < qualityOptions.length; i++) {
                if (qualityOptions[i].value === rotationQuality) {
                    C('rotationQuality').value = qualityOptions[i];
                    break;
                }
            }
            
            // rotation FPS (custom)
            var rotationFPS = parseInt(peppy_config.current['rotation.fps'], 10) || 8;
            C('rotationFPS').value = rotationFPS;
            minmax[11] = [C('rotationFPS').attributes[2].min,
                C('rotationFPS').attributes[3].max,
                C('rotationFPS').attributes[0].placeholder];
            
            // rotation speed (vinyl multiplier)
            var rotationSpeed = parseFloat(peppy_config.current['rotation.speed']);
            if (isNaN(rotationSpeed)) { rotationSpeed = 1.0; }
            C('rotationSpeed').value = rotationSpeed;
            minmax[12] = [C('rotationSpeed').attributes[2].min,
                C('rotationSpeed').attributes[3].max,
                C('rotationSpeed').attributes[0].placeholder];
            
            // spool left speed (cassette multiplier)
            var spoolLeftSpeed = parseFloat(peppy_config.current['spool.left.speed']);
            if (isNaN(spoolLeftSpeed)) { spoolLeftSpeed = 1.0; }
            C('spoolLeftSpeed').value = spoolLeftSpeed;
            minmax[13] = [C('spoolLeftSpeed').attributes[2].min,
                C('spoolLeftSpeed').attributes[3].max,
                C('spoolLeftSpeed').attributes[0].placeholder];
            
            // spool right speed (cassette multiplier)
            var spoolRightSpeed = parseFloat(peppy_config.current['spool.right.speed']);
            if (isNaN(spoolRightSpeed)) { spoolRightSpeed = 1.0; }
            C('spoolRightSpeed').value = spoolRightSpeed;
            minmax[14] = [C('spoolRightSpeed').attributes[2].min,
                C('spoolRightSpeed').attributes[3].max,
                C('spoolRightSpeed').attributes[0].placeholder];
            
            // spool adaptive (dynamic speeds based on progress)
            var spoolAdaptive = peppy_config.current['spool.adaptive'] === true || peppy_config.current['spool.adaptive'] === 'true';
            C('spoolAdaptive').value = spoolAdaptive;
            
            // reel direction
            var reelDirection = peppy_config.current['reel.direction'] || 'ccw';
            var directionOptions = C('reelDirection').options;
            for (var i = 0; i < directionOptions.length; i++) {
                if (directionOptions[i].value === reelDirection) {
                    C('reelDirection').value = directionOptions[i];
                    break;
                }
            }
            
            // section 7 - Remote display server settings -----------------------------
            // Read from Volumio config (persists across restart); fallback to config.txt for backward compat
            // server enabled
            var remoteServerEnabled = self.config.get('remoteServerEnabled');
            if (remoteServerEnabled === undefined) {
                remoteServerEnabled = peppy_config && peppy_config.current ? peppy_config.current['remote.server.enabled'] === 'true' : false;
            }
            C('remoteServerEnabled').value = remoteServerEnabled;
            
            // server mode
            var remoteServerMode = self.config.get('remoteServerMode');
            if (remoteServerMode === undefined) {
                remoteServerMode = peppy_config && peppy_config.current ? (peppy_config.current['remote.server.mode'] || 'server_local') : 'server_local';
            }
            var remoteServerModeOptions = C('remoteServerMode').options;
            for (var i = 0; i < remoteServerModeOptions.length; i++) {
                if (remoteServerModeOptions[i].value === remoteServerMode) {
                    C('remoteServerMode').value = remoteServerModeOptions[i];
                    break;
                }
            }
            
            // discovery port
            var remoteDiscoveryPort = self.config.get('remoteDiscoveryPort');
            if (remoteDiscoveryPort === undefined) {
                remoteDiscoveryPort = peppy_config && peppy_config.current ? (parseInt(peppy_config.current['remote.discovery.port'], 10) || 5579) : 5579;
            }
            C('remoteDiscoveryPort').value = remoteDiscoveryPort;
            
            // meters data port
            var remoteServerPort = self.config.get('remoteServerPort');
            if (remoteServerPort === undefined) {
                remoteServerPort = peppy_config && peppy_config.current ? (parseInt(peppy_config.current['remote.server.port'], 10) || 5580) : 5580;
            }
            C('remoteServerPort').value = remoteServerPort;
            
            // spectrum port
            var remoteSpectrumPort = self.config.get('remoteSpectrumPort');
            if (remoteSpectrumPort === undefined) {
                remoteSpectrumPort = peppy_config && peppy_config.current ? (parseInt(peppy_config.current['remote.spectrum.port'], 10) || 5581) : 5581;
            }
            C('remoteSpectrumPort').value = remoteSpectrumPort;

            // always stream spectrum bins when host meter has no spectrum
            var remoteSpectrumAlways = self.config.get('remoteSpectrumAlways');
            if (remoteSpectrumAlways === undefined) {
                remoteSpectrumAlways = peppy_config && peppy_config.current
                    ? peppy_config.current['remote.spectrum.always'] === 'true'
                    : false;
            }
            C('remoteSpectrumAlways').value = !!remoteSpectrumAlways;
            
            // config sync interval
            var configSyncInterval = self.config.get('configSyncInterval');
            if (configSyncInterval === undefined) {
                configSyncInterval = peppy_config && peppy_config.current ? (parseInt(peppy_config.current['remote.config.sync.interval'], 10) || 1) : 1;
            }
            C('configSyncInterval').value = configSyncInterval;
            
            // sections 9-11 - Backup and Restore (Continuity Engine) -------
            // Section 9 (Create Backup) has nothing to populate - only the
            // input field and its saveButton. Sections 10 (Restore) and 11
            // (Delete) share the same backup list dropdown.
            var backupList = self.listSettingsBackups();
            if (backupList.length > 0) {
                var firstLabel = backupList[0].name + ' (' + backupList[0].createdLabel + ', v' + backupList[0].pluginVersion + ')';
                var firstValue = { value: backupList[0].name, label: firstLabel };
                
                // Section 10 - Restore Backup dropdown
                C('selectedBackup').options = [];
                backupList.forEach(function (b) {
                    self.configManager.pushUIConfigParam(uiconf, P('selectedBackup'), {
                        value: b.name,
                        label: b.name + ' (' + b.createdLabel + ', v' + b.pluginVersion + ')'
                    });
                });
                C('selectedBackup').value = firstValue;
                
                // Section 11 - Delete Backup dropdown (same list)
                C('selectedBackupDelete').options = [];
                backupList.forEach(function (b) {
                    self.configManager.pushUIConfigParam(uiconf, P('selectedBackupDelete'), {
                        value: b.name,
                        label: b.name + ' (' + b.createdLabel + ', v' + b.pluginVersion + ')'
                    });
                });
                C('selectedBackupDelete').value = firstValue;
            }
            
            // section 12 - Debug settings -----------------------------
            // debug level
            var debugLevel = peppy_config.current['debug.level'] || 'off';
            var debugLevelOptions = C('debugLevel').options;
            for (var i = 0; i < debugLevelOptions.length; i++) {
                if (debugLevelOptions[i].value === debugLevel) {
                    C('debugLevel').value = debugLevelOptions[i];
                    break;
                }
            }
            
            // trace switches (all default to false)
            var traceKeys = [
                'debug.trace.meters', 'debug.trace.spectrum', 'debug.trace.vinyl', 'debug.trace.reel.left',
                'debug.trace.reel.right', 'debug.trace.tonearm', 'debug.trace.albumart',
                'debug.trace.scrolling', 'debug.trace.volume', 'debug.trace.mute',
                'debug.trace.shuffle', 'debug.trace.repeat', 'debug.trace.playstate',
                'debug.trace.progress', 'debug.trace.metadata', 'debug.trace.seek',
                'debug.trace.time', 'debug.trace.init', 'debug.trace.fade', 'debug.trace.frame',
                'debug.trace.remote', 'debug.trace.remote.packets'
            ];
            // Trace switch control ids, parallel to traceKeys above (debug.* config keys).
            var traceIds = [
                'traceMeters', 'traceSpectrum', 'traceVinyl', 'traceReelLeft',
                'traceReelRight', 'traceTonearm', 'traceAlbumart',
                'traceScrolling', 'traceVolume', 'traceMute',
                'traceShuffle', 'traceRepeat', 'tracePlaystate',
                'traceProgress', 'traceMetadata', 'traceSeek',
                'traceTime', 'traceInit', 'traceFade', 'traceFrame',
                'traceRemote', 'traceRemotePackets'
            ];
            for (var i = 0; i < traceKeys.length; i++) {
                var traceValue = peppy_config.current[traceKeys[i]] === 'true' || peppy_config.current[traceKeys[i]] === true;
                C(traceIds[i]).value = traceValue;
            }
            
            // section 13 - Profiling settings -----------------------------
            // per-frame timing
            var profilingTiming = peppy_config.current['profiling.timing'] === 'true' || peppy_config.current['profiling.timing'] === true;
            C('profilingTiming').value = profilingTiming;
            
            // timing interval
            var profilingInterval = parseInt(peppy_config.current['profiling.interval'], 10) || 30;
            C('profilingInterval').value = profilingInterval;
            
            // cProfile enabled
            var profilingCprofile = peppy_config.current['profiling.cprofile'] === 'true' || peppy_config.current['profiling.cprofile'] === true;
            C('profilingCprofile').value = profilingCprofile;
            
            // profile duration
            var profilingDuration = parseInt(peppy_config.current['profiling.duration'], 10) || 60;
            C('profilingDuration').value = profilingDuration;
            
        } else {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));            
        }
            defer.resolve(uiconf);
        })
        .fail(function()
        {
            defer.reject(new Error());
        });


    
    return defer.promise;
}; // end getUIConfig -----------------------------------

peppyScreensaver.prototype.getConfigurationFiles = function() {
	return ['config.json'];
};

// Audio Source save handler (split out of the old global section). Selects which
// audio stream the meters react to (ALSA capture / DSP / Spotify / AirPlay). All of
// these live in config.json and may trigger an ALSA rebuild; a change reloads the
// meter so it captures from the new source.
//-------------------------------------------------------
peppyScreensaver.prototype.saveAudioSourceConf = function (confData) {
  const self = this;
  let noChanges = true;
  let uiNeedsReboot = false;

  // write DSP
  if (self.config.get('useDSP') != confData.useDSP) {
      alsaLog(self.logger, 'basic', 'saveAudioSourceConf: useDSP toggled ' + self.config.get('useDSP') + ' -> ' + confData.useDSP);
      self.config.set('useDSP', confData.useDSP);
      self.checkDSPactive(!confData.useDSP);
      if (self.connectProvider() === 'spop') {
          self.switch_Spotify(!confData.useDSP);
      }
      noChanges = false;
      uiNeedsReboot = true;
  }

  // write alsa selection
  if (confData.useDSP) {
      self.config.set('alsaSelection', 0);
  } else if (self.config.get('alsaSelection') != confData.alsaSelection.value) {
      self.config.set('alsaSelection', confData.alsaSelection.value);
      noChanges = false;
      uiNeedsReboot = true;
  }

  // write spotify / USB-DAC (spop only) or Soloist metering (soloist only)
  var connectProvider = self.connectProvider();
  if (connectProvider === 'spop') {
      if (confData.useDSP) {
          self.config.set('useSpotify', false);
      } else {
          if (self.config.get('useSpotify') != confData.useSpotify) {
              self.config.set('useSpotify', confData.useSpotify);
              noChanges = false;
              uiNeedsReboot = true;
          }
          if (self.config.get('useUSBDAC') != confData.useUSBDAC) {
              self.config.set('useUSBDAC', confData.useUSBDAC);
              noChanges = false;
              uiNeedsReboot = true;
          }
      }
  } else if (connectProvider === 'soloist') {
      if (confData.useDSP) {
          self.config.set('useSoloist', false);
      } else if (self.config.get('useSoloist') != confData.useSoloist) {
          self.config.set('useSoloist', !!confData.useSoloist);
          noChanges = false;
          uiNeedsReboot = true;
      }
  }

  // write airplay
  if (self.getPluginStatus ('music_service', 'airplay_emulation') === 'STARTED'){
      if (confData.useDSP) {
          self.config.set('useAirplay', false);
          self.switch_Airplay(false);
      } else if (self.config.get('useAirplay') != confData.useAirplay) {
          self.config.set('useAirplay', confData.useAirplay);
          self.switch_Airplay(confData.useAirplay);
          noChanges = false;
      }
  }

  if (!noChanges) {
      // Reload the meter so it captures from the newly selected source
      if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
  }
  if (uiNeedsReboot) {
      alsaLog(self.logger, 'basic', 'saveAudioSourceConf: triggering ALSA rebuild (alsaSelection=' + self.config.get('alsaSelection') + ')');
      self.switch_alsaConfig(parseInt(self.config.get('alsaSelection'),10));
  }

  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveAudioSourceConf ----------------------------

// Display & Activation save handler (split out of the old global section). Covers the
// screensaver activation timeout (config.json), on-screen position + mouse pointer
// (config.txt, SDL2) and the display output (config.json). Any change reloads the
// running meter so it is re-rendered with the new geometry/output.
//-------------------------------------------------------
peppyScreensaver.prototype.saveDisplayConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;

  // write timeout (config.json)
  if (Number.isNaN(parseInt(confData.timeout, 10)) || !isFinite(confData.timeout)) {
      uiNeedsUpdate = true;
      setTimeout(function () {
          self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.TIMEOUT') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
      }, 500);
  } else {
      confData.timeout = self.minmax('TIMEOUT', confData.timeout, minmax[0]);
      if (confData.timeout != self.config.get('timeout')){
          self.config.set('timeout', confData.timeout);
          noChanges = false;
      }
  }

  if (fs.existsSync(PeppyConf)){

    // write position type
    var pos_type = use_SDL2 ? confData.positionType.value == 0? 'center' : 'manual' : 'center';
    if (peppy_config.current['position.type'] !== pos_type) {
        peppy_config.current['position.type'] = pos_type;
        noChanges = false;
    }
    if (use_SDL2) {
        // write position x
        if (Number.isNaN(parseInt(confData.position_x, 10)) || !isFinite(confData.position_x)) {
            uiNeedsUpdate = true;
            setTimeout(function () {
                self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.POS_X') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
            }, 500);
        } else {
            confData.position_x = self.minmax('POS_X', confData.position_x, minmax[1]);
            if (peppy_config.current['position.x'] != confData.position_x) {
                peppy_config.current['position.x'] = confData.position_x;
                noChanges = false;
            }
        }
        // write position y
        if (Number.isNaN(parseInt(confData.position_y, 10)) || !isFinite(confData.position_y)) {
            uiNeedsUpdate = true;
            setTimeout(function () {
                self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.POS_Y') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
            }, 500);
        } else {
            confData.position_y = self.minmax('POS_Y', confData.position_y, minmax[2]);
            if (peppy_config.current['position.y'] != confData.position_y) {
                peppy_config.current['position.y'] = confData.position_y;
                noChanges = false;
            }
        }
    }

    // write mouse support
    var mouseSupport = confData.mouseEnabled? 'True' : 'False';
    if (peppy_config.sdl.env['mouse.enabled'] != mouseSupport) {
        peppy_config.sdl.env['mouse.enabled'] = mouseSupport;
        noChanges = false;
    }

    // write display port (config.json + live switch)
    if (self.config.get('displayOutput') != confData.displayOutput.value) {
        self.config.set('displayOutput', confData.displayOutput.value);
        var DispOut = parseInt(confData.displayOutput.value,10);
        self.switch_DisplayPort(DispOut);
        noChanges = false;
    }

    // write format / type display mode (like scrolling.mode: config.txt [current] only)
    var formatTypeMode = (confData.formatTypeMode && confData.formatTypeMode.value) || 'icon';
    if (formatTypeMode !== 'icon' && formatTypeMode !== 'text' && formatTypeMode !== 'both') {
        formatTypeMode = 'icon';
    }
    if (peppy_config.current['playinfo.type.mode'] != formatTypeMode) {
        peppy_config.current['playinfo.type.mode'] = formatTypeMode;
        noChanges = false;
    }

    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }

  if (uiNeedsUpdate) {self.updateUIConfig();}

  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveDisplayConf ----------------------------

// Template File Sharing (SMB) save handler.
// Only toggles config.json + filesystem permissions used for sharing templates over
// the network share; it has no effect on the running meter, so no reload is needed.
// ---------------------------------------------------------------
peppyScreensaver.prototype.saveSmbShareConf = function (confData) {
  const self = this;
  let noChanges = true;

  var smbShareAccess = confData.smbShareAccess === true;
  if (self.config.get('smbShareAccess') !== smbShareAccess) {
    self.config.set('smbShareAccess', smbShareAccess);
    self.normalizeTemplatePermissions(smbShareAccess);
    noChanges = false;
  }

  setTimeout(function () {
    if (noChanges) {
      self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
      self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveSmbShareConf ----------------------------

// called when 'save' button pressed on Playback Behavior settings
// ---------------------------------------------------------------
peppyScreensaver.prototype.savePlaybackConf = function(data) {
    var self = this;
    var defer = libQ.defer();
    
    // Handle 0 (Disabled) as valid value - check for undefined/null, not truthiness
    var persistDuration = (data['persist_duration'] && data['persist_duration'].value !== undefined) 
        ? String(data['persist_duration'].value)
        : '30';
    
    var persistDisplay = data['persist_display'] && data['persist_display'].value 
        ? data['persist_display'].value 
        : 'freeze';
    
    // Queue mode - save to both config.json and PeppyConf
    var queueMode = data['queueMode'] && data['queueMode'].value 
        ? data['queueMode'].value 
        : 'track';
    
    // Validate queue mode
    if (queueMode !== 'track' && queueMode !== 'queue') {
        queueMode = 'track';  // Default fallback
    }
    
    self.config.set('persist_duration', persistDuration);
    self.config.set('persist_display', persistDisplay);
    
    // Track if queue mode changed (needs restart to apply)
    var queueModeChanged = false;
    
    // Save queue mode to PeppyConf (for Python handlers)
    if (fs.existsSync(PeppyConf)) {
        if (peppy_config.current['queue.mode'] != queueMode) {
            peppy_config.current['queue.mode'] = queueMode;
            fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
            queueModeChanged = true;
        }
    }
    
    // Restart meter to apply new queue mode setting
    if (queueModeChanged && fs.existsSync(runFlag)) {
        fs.removeSync(runFlag);
    }
    
    self.commandRouter.pushToastMessage('success', 
        self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), 
        self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    
    defer.resolve();
    return defer.promise;
};

// called when 'save' button pressed on VU-Meter settings
// ------------------------------------------------------
peppyScreensaver.prototype.saveVUMeterConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;
  
  if (fs.existsSync(PeppyConf)){
    //var config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
    
    // write selected meter
    if ((confData.meter.value !== 'list' && peppy_config.current.meter !== confData.meter.value) || (confData.meter.value == 'list' && peppy_config.current.meter !== confData.randomSelection)) {
        if (confData.meter.value === 'list') {
            if (confData.randomSelection !== ''){
				if (self.checkListMode(confData.randomSelection)) {
                    peppy_config.current.meter = (confData.randomSelection);
                    self.config.set('randomSelection', (confData.randomSelection));
                }
            } else {
                peppy_config.current.meter = availMeters;
                self.config.set('randomSelection', availMeters);
            }
        } else {
            peppy_config.current.meter = confData.meter.value;
        }
        uiNeedsUpdate = true;
        noChanges = false;
    }

    // write random mode
    var random_change_title = (peppy_config.current['random.change.title']).toLowerCase() == 'true' ? true : false;
    if ((confData.randomMode.value == 'titlechange' && !random_change_title) || (confData.randomMode.value == 'interval' && random_change_title)){
        if (confData.randomMode.value == 'titlechange') {
            peppy_config.current['random.change.title'] = 'True';
        } else {
            peppy_config.current['random.change.title'] = 'False';
        }
        uiNeedsUpdate = true;
        noChanges = false;    
    }
    
    // write random interval
    if (Number.isNaN(parseInt(confData.randomInterval, 10)) || !isFinite(confData.randomInterval)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.RANDOMINTERVAL') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.randomInterval = self.minmax('RANDOMINTERVAL', confData.randomInterval, minmax[5]);
        if (peppy_config.current['random.meter.interval'] != confData.randomInterval) {
            peppy_config.current['random.meter.interval'] = confData.randomInterval;
            noChanges = false;
        }
    }

    // smooth buffer (moved here from the global section: meter feel)
    if (Number.isNaN(parseInt(confData.smoothBuffer, 10)) || !isFinite(confData.smoothBuffer)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.SMOOTH_BUFFER') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.smoothBuffer = self.minmax('SMOOTH_BUFFER', confData.smoothBuffer, minmax[3]);
        if (peppy_config.data.source['smooth.buffer.size'] != confData.smoothBuffer) {
            peppy_config.data.source['smooth.buffer.size'] = confData.smoothBuffer;
            noChanges = false;
        }
    }

    // meter sensitivity (gain in dB, consumed by the data source)
    if (Number.isNaN(parseInt(confData.meterGain, 10)) || !isFinite(confData.meterGain)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.METER_SENSITIVITY') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.meterGain = self.minmax('METER_SENSITIVITY', confData.meterGain, minmax[15]);
        if (peppy_config.data.source['volume.gain.db'] != confData.meterGain) {
            peppy_config.data.source['volume.gain.db'] = confData.meterGain;
            noChanges = false;
        }
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        try { self.updateConfigVersion(); } catch (e) {}
        // Restart meter to apply new settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  if (uiNeedsUpdate) {self.updateUIConfig();}
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveVUMeterConf -------------------------------------

// called when 'save' button pressed on Performance settings
// ----------------------------------------------------------
peppyScreensaver.prototype.savePerformanceConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;
  
  if (fs.existsSync(PeppyConf)){
    
    // write frame rate
    if (Number.isNaN(parseInt(confData.frameRate, 10)) || !isFinite(confData.frameRate)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.FRAME_RATE') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.frameRate = self.minmax('FRAME_RATE', confData.frameRate, minmax[6]);
        if (peppy_config.current['frame.rate'] != confData.frameRate) {
            peppy_config.current['frame.rate'] = confData.frameRate;
            noChanges = false;
        }
    }
    
    // write update interval (to peppy config.txt for Python to read)
    if (Number.isNaN(parseInt(confData.updateInterval, 10)) || !isFinite(confData.updateInterval)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.UPDATE_INTERVAL') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.updateInterval = self.minmax('UPDATE_INTERVAL', confData.updateInterval, minmax[7]);
        if (peppy_config.current['update.interval'] != confData.updateInterval) {
            peppy_config.current['update.interval'] = confData.updateInterval;
            noChanges = false;
        }
    }
    
    // write meter delay (ms)
    if (Number.isNaN(parseInt(confData.meterDelay, 10)) || !isFinite(confData.meterDelay)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.METER_DELAY') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.meterDelay = self.minmax('METER_DELAY', confData.meterDelay, minmax[8]);
        if (peppy_config.current['meter.delay'] != confData.meterDelay) {
            peppy_config.current['meter.delay'] = confData.meterDelay;
            noChanges = false;
        }
    }

    // needle cache (moved here from the global section: render/CPU tuning)
    var needleCache = lt_4GB ? 'False' : confData.needleCache? 'True' : 'False';
    if (peppy_config.current['use.cache'] != needleCache) {
        peppy_config.current['use.cache'] = needleCache;
        noChanges = false;
    }

    // cache size (moved here from the global section)
    if (!lt_4GB) {
        if (Number.isNaN(parseInt(confData.cachesize, 10)) || !isFinite(confData.cachesize)) {
            uiNeedsUpdate = true;
            setTimeout(function () {
                self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CACHESIZE') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
            }, 500);
        } else {
            confData.cachesize = self.minmax('CACHESIZE', confData.cachesize, minmax[4]);
            if (peppy_config.current['cache.size'] != confData.cachesize) {
                peppy_config.current['cache.size'] = confData.cachesize;
                noChanges = false;
            }
        }
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  if (uiNeedsUpdate) {self.updateUIConfig();}
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end savePerformanceConf -------------------------------------

// Scrolling settings save handler
//-------------------------------------------------------------
peppyScreensaver.prototype.saveScrollingConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;
  
  if (fs.existsSync(PeppyConf)){
    
    // write scrolling mode
    var scrollingMode = confData.scrollingMode.value || 'skin';
    if (peppy_config.current['scrolling.mode'] != scrollingMode) {
        peppy_config.current['scrolling.mode'] = scrollingMode;
        noChanges = false;
    }
    
    // write scrolling speed artist
    var scrollSpeedArtist = parseInt(confData.scrollingSpeedArtist, 10) || 40;
    if (peppy_config.current['scrolling.speed.artist'] != scrollSpeedArtist) {
        peppy_config.current['scrolling.speed.artist'] = scrollSpeedArtist;
        noChanges = false;
    }
    
    // write scrolling speed title
    var scrollSpeedTitle = parseInt(confData.scrollingSpeedTitle, 10) || 40;
    if (peppy_config.current['scrolling.speed.title'] != scrollSpeedTitle) {
        peppy_config.current['scrolling.speed.title'] = scrollSpeedTitle;
        noChanges = false;
    }
    
    // write scrolling speed album
    var scrollSpeedAlbum = parseInt(confData.scrollingSpeedAlbum, 10) || 40;
    if (peppy_config.current['scrolling.speed.album'] != scrollSpeedAlbum) {
        peppy_config.current['scrolling.speed.album'] = scrollSpeedAlbum;
        noChanges = false;
    }
    
    // save config file and restart meter if changes were made
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new scrolling settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  if (uiNeedsUpdate) {self.updateUIConfig();}
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveScrollingConf -------------------------------------

// Animation settings save handler
//-------------------------------------------------------------
peppyScreensaver.prototype.saveAnimationConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;
  
  if (fs.existsSync(PeppyConf)){

    // start/stop animation on/off (moved here from the global section). start.animation
    // is only meaningful with SDL2, matching the control's visibility in getUIConfig.
    if (use_SDL2) {
        var startAnimation = confData.animation ? 'True' : 'False';
        if (peppy_config.current['start.animation'] != startAnimation) {
            peppy_config.current['start.animation'] = startAnimation;
            noChanges = false;
        }
    }
    
    // write transition type
    var transitionType = confData.transitionType.value || 'fade';
    if (peppy_config.current['transition.type'] != transitionType) {
        peppy_config.current['transition.type'] = transitionType;
        noChanges = false;
    }
    
    // write transition duration
    if (Number.isNaN(parseFloat(confData.transitionDuration)) || !isFinite(confData.transitionDuration)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.TRANSITION_DURATION') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.transitionDuration = self.minmax('TRANSITION_DURATION', confData.transitionDuration, minmax[9], true);
        if (peppy_config.current['transition.duration'] != confData.transitionDuration) {
            peppy_config.current['transition.duration'] = confData.transitionDuration;
            noChanges = false;
        }
    }
    
    // write transition color
    var transitionColor = confData.transitionColor.value || 'black';
    if (peppy_config.current['transition.color'] != transitionColor) {
        peppy_config.current['transition.color'] = transitionColor;
        noChanges = false;
    }
    
    // write transition opacity
    if (Number.isNaN(parseInt(confData.transitionOpacity, 10)) || !isFinite(confData.transitionOpacity)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.TRANSITION_OPACITY') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.transitionOpacity = self.minmax('TRANSITION_OPACITY', confData.transitionOpacity, minmax[10]);
        if (peppy_config.current['transition.opacity'] != confData.transitionOpacity) {
            peppy_config.current['transition.opacity'] = confData.transitionOpacity;
            noChanges = false;
        }
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  if (uiNeedsUpdate) {self.updateUIConfig();}
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveAnimationConf -------------------------------------

// Rotation settings save handler
//-------------------------------------------------------------
peppyScreensaver.prototype.saveRotationConf = function (confData) {
  const self = this;
  let noChanges = true;
  uiNeedsUpdate = false;
  
  if (fs.existsSync(PeppyConf)){
    
    // write rotation quality
    var rotationQuality = confData.rotationQuality.value || 'medium';
    if (peppy_config.current['rotation.quality'] != rotationQuality) {
        peppy_config.current['rotation.quality'] = rotationQuality;
        noChanges = false;
    }
    
    // write reel direction
    var reelDirection = confData.reelDirection.value || 'ccw';
    if (peppy_config.current['reel.direction'] != reelDirection) {
        peppy_config.current['reel.direction'] = reelDirection;
        noChanges = false;
    }
    
    // write rotation FPS (custom mode)
    if (Number.isNaN(parseInt(confData.rotationFPS, 10)) || !isFinite(confData.rotationFPS)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.ROTATION_FPS') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.rotationFPS = self.minmax('ROTATION_FPS', confData.rotationFPS, minmax[11]);
        if (peppy_config.current['rotation.fps'] != confData.rotationFPS) {
            peppy_config.current['rotation.fps'] = confData.rotationFPS;
            noChanges = false;
        }
    }
    
    // write rotation speed (vinyl multiplier)
    if (Number.isNaN(parseFloat(confData.rotationSpeed)) || !isFinite(confData.rotationSpeed)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.ROTATION_SPEED') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.rotationSpeed = self.minmax('ROTATION_SPEED', confData.rotationSpeed, minmax[12], true);
        if (peppy_config.current['rotation.speed'] != confData.rotationSpeed) {
            peppy_config.current['rotation.speed'] = confData.rotationSpeed;
            noChanges = false;
        }
    }
    
    // write spool left speed (cassette multiplier)
    if (Number.isNaN(parseFloat(confData.spoolLeftSpeed)) || !isFinite(confData.spoolLeftSpeed)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.SPOOL_LEFT_SPEED') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.spoolLeftSpeed = self.minmax('SPOOL_LEFT_SPEED', confData.spoolLeftSpeed, minmax[13], true);
        if (peppy_config.current['spool.left.speed'] != confData.spoolLeftSpeed) {
            peppy_config.current['spool.left.speed'] = confData.spoolLeftSpeed;
            noChanges = false;
        }
    }
    
    // write spool right speed (cassette multiplier)
    if (Number.isNaN(parseFloat(confData.spoolRightSpeed)) || !isFinite(confData.spoolRightSpeed)) {
        uiNeedsUpdate = true;
        setTimeout(function () {
            self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.SPOOL_RIGHT_SPEED') + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NAN'));
        }, 500);
    } else {
        confData.spoolRightSpeed = self.minmax('SPOOL_RIGHT_SPEED', confData.spoolRightSpeed, minmax[14], true);
        if (peppy_config.current['spool.right.speed'] != confData.spoolRightSpeed) {
            peppy_config.current['spool.right.speed'] = confData.spoolRightSpeed;
            noChanges = false;
        }
    }
    
    // write spool adaptive (dynamic speeds based on progress)
    var spoolAdaptive = confData.spoolAdaptive || false;
    if (peppy_config.current['spool.adaptive'] != spoolAdaptive) {
        peppy_config.current['spool.adaptive'] = spoolAdaptive;
        noChanges = false;
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  if (uiNeedsUpdate) {self.updateUIConfig();}
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveRotationConf -------------------------------------

// Debug settings save handler
//-------------------------------------------------------------
peppyScreensaver.prototype.saveDebugConf = function (confData) {
  const self = this;
  let noChanges = true;
  
  if (fs.existsSync(PeppyConf)){
    
    // write debug level
    var debugLevel = confData.debugLevel.value || 'off';
    if (peppy_config.current['debug.level'] != debugLevel) {
        peppy_config.current['debug.level'] = debugLevel;
        noChanges = false;
    }
    
    // write trace switches (map UI field names to config keys)
    var traceMap = {
        'traceMeters': 'debug.trace.meters',
        'traceSpectrum': 'debug.trace.spectrum',
        'traceVinyl': 'debug.trace.vinyl',
        'traceReelLeft': 'debug.trace.reel.left',
        'traceReelRight': 'debug.trace.reel.right',
        'traceTonearm': 'debug.trace.tonearm',
        'traceAlbumart': 'debug.trace.albumart',
        'traceScrolling': 'debug.trace.scrolling',
        'traceVolume': 'debug.trace.volume',
        'traceMute': 'debug.trace.mute',
        'traceShuffle': 'debug.trace.shuffle',
        'traceRepeat': 'debug.trace.repeat',
        'tracePlaystate': 'debug.trace.playstate',
        'traceProgress': 'debug.trace.progress',
        'traceMetadata': 'debug.trace.metadata',
        'traceSeek': 'debug.trace.seek',
        'traceTime': 'debug.trace.time',
        'traceInit': 'debug.trace.init',
        'traceFade': 'debug.trace.fade',
        'traceFrame': 'debug.trace.frame',
        'traceRemote': 'debug.trace.remote',
        'traceRemotePackets': 'debug.trace.remote.packets'
    };
    
    for (var uiKey in traceMap) {
        var configKey = traceMap[uiKey];
        var newValue = confData[uiKey] ? 'true' : 'false';
        if (peppy_config.current[configKey] != newValue) {
            peppy_config.current[configKey] = newValue;
            noChanges = false;
        }
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new debug settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveDebugConf -------------------------------------

peppyScreensaver.prototype.saveProfilingConf = function (confData) {
  const self = this;
  let noChanges = true;
  
  if (fs.existsSync(PeppyConf)){
    
    // per-frame timing switch
    var profilingTiming = confData.profilingTiming ? 'true' : 'false';
    if (peppy_config.current['profiling.timing'] != profilingTiming) {
        peppy_config.current['profiling.timing'] = profilingTiming;
        noChanges = false;
    }
    
    // timing interval
    var profilingInterval = self.minmax('profiling_interval', confData.profilingInterval, [1, 1000, 30]);
    if (peppy_config.current['profiling.interval'] != profilingInterval) {
        peppy_config.current['profiling.interval'] = profilingInterval;
        noChanges = false;
    }
    
    // cProfile switch
    var profilingCprofile = confData.profilingCprofile ? 'true' : 'false';
    if (peppy_config.current['profiling.cprofile'] != profilingCprofile) {
        peppy_config.current['profiling.cprofile'] = profilingCprofile;
        noChanges = false;
    }
    
    // profile duration
    var profilingDuration = self.minmax('profiling_duration', confData.profilingDuration, [0, 3600, 60]);
    if (peppy_config.current['profiling.duration'] != profilingDuration) {
        peppy_config.current['profiling.duration'] = profilingDuration;
        noChanges = false;
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new profiling settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
  } else {
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveProfilingConf -------------------------------------

peppyScreensaver.prototype.saveRemoteConf = function (confData) {
  const self = this;
  let noChanges = true;
  
  // Persist to Volumio config (survives restart, UI state aligned with other sections)
  var remoteServerEnabled = !!confData.remoteServerEnabled;
  if (self.config.get('remoteServerEnabled') !== remoteServerEnabled) {
      self.config.set('remoteServerEnabled', remoteServerEnabled);
      noChanges = false;
  }
  
  var remoteServerMode = confData.remoteServerMode.value;
  if (self.config.get('remoteServerMode') !== remoteServerMode) {
      self.config.set('remoteServerMode', remoteServerMode);
      noChanges = false;
  }
  
  var remoteServerPort = self.minmax('remote_server_port', confData.remoteServerPort, [1024, 65535, 5580]);
  if (self.config.get('remoteServerPort') !== remoteServerPort) {
      self.config.set('remoteServerPort', remoteServerPort);
      noChanges = false;
  }
  
  var remoteDiscoveryPort = self.minmax('remote_discovery_port', confData.remoteDiscoveryPort, [1024, 65535, 5579]);
  if (self.config.get('remoteDiscoveryPort') !== remoteDiscoveryPort) {
      self.config.set('remoteDiscoveryPort', remoteDiscoveryPort);
      noChanges = false;
  }
  
  var remoteSpectrumPort = self.minmax('remote_spectrum_port', confData.remoteSpectrumPort, [1024, 65535, 5581]);
  if (self.config.get('remoteSpectrumPort') !== remoteSpectrumPort) {
      self.config.set('remoteSpectrumPort', remoteSpectrumPort);
      noChanges = false;
  }

  var remoteSpectrumAlways = !!confData.remoteSpectrumAlways;
  if (self.config.get('remoteSpectrumAlways') !== remoteSpectrumAlways) {
      self.config.set('remoteSpectrumAlways', remoteSpectrumAlways);
      noChanges = false;
  }
  
  var configSyncInterval = self.minmax('config_sync_interval', confData.configSyncInterval, [1, 60, 1]);
  if (self.config.get('configSyncInterval') !== configSyncInterval) {
      self.config.set('configSyncInterval', configSyncInterval);
      noChanges = false;
  }
  
  // Also update config.txt for Python/runtime
  if (fs.existsSync(PeppyConf)){
    var remoteServerEnabledStr = remoteServerEnabled ? 'true' : 'false';
    if (peppy_config.current['remote.server.enabled'] != remoteServerEnabledStr) {
        peppy_config.current['remote.server.enabled'] = remoteServerEnabledStr;
    }
    if (peppy_config.current['remote.server.mode'] != remoteServerMode) {
        peppy_config.current['remote.server.mode'] = remoteServerMode;
    }
    if (peppy_config.current['remote.server.port'] != remoteServerPort) {
        peppy_config.current['remote.server.port'] = remoteServerPort;
    }
    if (peppy_config.current['remote.discovery.port'] != remoteDiscoveryPort) {
        peppy_config.current['remote.discovery.port'] = remoteDiscoveryPort;
    }
    if (peppy_config.current['remote.spectrum.port'] != remoteSpectrumPort) {
        peppy_config.current['remote.spectrum.port'] = remoteSpectrumPort;
    }
    var remoteSpectrumAlwaysStr = remoteSpectrumAlways ? 'true' : 'false';
    if (peppy_config.current['remote.spectrum.always'] != remoteSpectrumAlwaysStr) {
        peppy_config.current['remote.spectrum.always'] = remoteSpectrumAlwaysStr;
    }
    if (peppy_config.current['remote.config.sync.interval'] != configSyncInterval) {
        peppy_config.current['remote.config.sync.interval'] = configSyncInterval;
    }
    
    if (!noChanges) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, {whitespace: true}));
        // Restart meter to apply new remote settings
        if (fs.existsSync(runFlag)){fs.removeSync(runFlag);}
    }
    
    // Update config version hash for remote clients
    self.updateConfigVersion();
    
  } else {
      noChanges = true;  // Don't show success when config.txt is missing
      self.commandRouter.pushToastMessage('error', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  }
  
  setTimeout(function () {
    if (noChanges) {
        self.commandRouter.pushToastMessage('info', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
    } else {
        self.commandRouter.pushToastMessage('success', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
    }
  }, 500);
}; // end saveRemoteConf -------------------------------------

// Calculate and update config version hash (for remote client change detection)
peppyScreensaver.prototype.updateConfigVersion = function () {
  const self = this;
  
  try {
    if (fs.existsSync(PeppyConf)) {
      var configContent = fs.readFileSync(PeppyConf, 'utf8');
      var newHash = crypto.createHash('md5').update(configContent).digest('hex').substring(0, 8);
      
      if (newHash !== remoteConfigVersion) {
        remoteConfigVersion = newHash;
        self.logger.info(id + 'Config version updated: ' + remoteConfigVersion);
      }
    }
  } catch (err) {
    self.logger.error(id + 'Failed to calculate config version: ' + err.message);
  }
  
  return remoteConfigVersion;
};

// Get current config version hash
peppyScreensaver.prototype.getConfigVersion = function () {
  return remoteConfigVersion;
};

// HTTP endpoint: Return config.txt contents for remote clients
// Called via: GET /api/v1/pluginEndpoint?endpoint=peppy_screensaver&method=getRemoteConfig
peppyScreensaver.prototype.getRemoteConfig = function () {
  const self = this;
  var defer = libQ.defer();
  
  try {
    if (!fs.existsSync(PeppyConf)) {
      defer.resolve({
        success: false,
        error: 'Config file not found'
      });
      return defer.promise;
    }
    
    var configContent = fs.readFileSync(PeppyConf, 'utf8');
    var configVersion = self.updateConfigVersion();
    
    // Include persist settings for remote clients to manage their own persist file
    var persistDuration = parseInt(self.config.get('persist_duration'), 10) || 0;
    var persistDisplay = self.config.get('persist_display') || 'freeze';
    
    defer.resolve({
      success: true,
      version: configVersion,
      plugin_version: peppyPluginVersion,
      config: configContent,
      persist_duration: persistDuration,
      persist_display: persistDisplay
    });
  } catch (err) {
    self.logger.error(id + 'Failed to read config for remote client: ' + err.message);
    defer.resolve({
      success: false,
      error: err.message
    });
  }
  
  return defer.promise;
};

// HTTP endpoint: Return font file as base64 for remote clients (theme + plugin fonts)
// Called via: POST /api/v1/pluginEndpoint with body { endpoint: 'peppy_screensaver_font', data: { filename: 'Lato-Light.ttf' } }
peppyScreensaver.prototype.getFont = function (data) {
  var self = this;
  var defer = libQ.defer();
  var filename = (data && typeof data.filename === 'string') ? data.filename : '';
  if (!filename || filename.indexOf('/') !== -1 || filename.indexOf('..') !== -1) {
    defer.resolve({ success: false, error: 'invalid filename' });
    return defer.promise;
  }
  try {
    var themeFonts = path.join(process.env.VOLUMIO_ACTIVE_UI_PATH || '/volumio/http/www', 'app', 'themes', 'volumio3', 'assets', 'variants', 'volumio', 'fonts', filename);
    var pluginFonts = path.join(PluginPath, 'screensaver', 'fonts', filename);
    var fontPath = null;
    if (fs.existsSync(themeFonts)) {
      fontPath = themeFonts;
    } else if (fs.existsSync(pluginFonts)) {
      fontPath = pluginFonts;
    }
    if (fontPath) {
      var buf = fs.readFileSync(fontPath, { encoding: null });
      defer.resolve({ success: true, data: buf.toString('base64') });
    } else {
      defer.resolve({ success: false, error: 'not found' });
    }
  } catch (err) {
    self.logger.error(id + 'getFont: ' + err.message);
    defer.resolve({ success: false, error: err.message });
  }
  return defer.promise;
};

// Resolve the directory that holds the remote handler (.py) files. On an installed
// plugin these live in screensaver/ (install.sh copies volumio_peppymeter/* there);
// fall back to the repo layout (volumio_peppymeter/) for dev/test.
peppyScreensaver.prototype.remoteHandlersDir = function () {
  var installed = path.join(PluginPath, 'screensaver');
  var devDir = path.join(PluginPath, 'volumio_peppymeter');
  try {
    if (fs.existsSync(installed) &&
        fs.readdirSync(installed).some(function (f) { return REMOTE_HANDLER_NAME_REGEX.test(f); })) {
      return installed;
    }
  } catch (e) {}
  if (fs.existsSync(devDir)) {
    return devDir;
  }
  return installed;
};

peppyScreensaver.prototype.remoteFontsDir = function () {
  return path.join(PluginPath, 'screensaver', 'fonts');
};

// Build the entry list for one directory: [{ name, sha256, size }] for files matching
// nameRegex. Hashing is cheap (handler files are small) and done on demand.
peppyScreensaver.prototype.remoteManifestEntries = function (dir, nameRegex) {
  var entries = [];
  try {
    if (!fs.existsSync(dir)) { return entries; }
    fs.readdirSync(dir).forEach(function (f) {
      if (!nameRegex.test(f)) { return; }
      var fp = path.join(dir, f);
      try {
        var st = fs.statSync(fp);
        if (!st.isFile()) { return; }
        var buf = fs.readFileSync(fp);
        entries.push({
          name: f,
          sha256: crypto.createHash('sha256').update(buf).digest('hex'),
          size: st.size
        });
      } catch (e) {}
    });
  } catch (e) {}
  entries.sort(function (a, b) { return a.name < b.name ? -1 : (a.name > b.name ? 1 : 0); });
  return entries;
};

// HTTP endpoint: server-authoritative manifest of handler + font files this plugin runs.
// Generated live from disk (cannot drift from what ships). Lets peppy_remote pull the exact
// handler set the connected server uses, hash-verified, instead of guessing from a branch.
// POST/GET { endpoint: 'peppy_screensaver_manifest' }
peppyScreensaver.prototype.getRemoteManifest = function (data) {
  var self = this;
  var defer = libQ.defer();
  try {
    var handlers = self.remoteManifestEntries(self.remoteHandlersDir(), REMOTE_HANDLER_NAME_REGEX);
    var fonts = self.remoteManifestEntries(self.remoteFontsDir(), REMOTE_FONT_NAME_REGEX);
    defer.resolve({
      success: true,
      plugin_version: peppyPluginVersion,
      api: REMOTE_API_VERSION,
      min_remote_api: REMOTE_MIN_API_VERSION,
      capabilities: REMOTE_CAPABILITIES,
      handlers: handlers,
      fonts: fonts
    });
  } catch (err) {
    self.logger.error(id + 'getRemoteManifest: ' + err.message);
    defer.resolve({ success: false, error: err.message });
  }
  return defer.promise;
};

// HTTP endpoint: deliver one manifest-listed handler or font as base64, with sha256 so the
// client can verify integrity before use. Strictly whitelisted by name regex.
// POST { endpoint: 'peppy_screensaver_file', data: { kind: 'handler'|'font', name } }
peppyScreensaver.prototype.getRemoteFile = function (data) {
  var self = this;
  var defer = libQ.defer();
  var kind = (data && typeof data.kind === 'string') ? data.kind : 'handler';
  var name = (data && typeof data.name === 'string') ? data.name : '';
  if (!name || name.indexOf('/') !== -1 || name.indexOf('\\') !== -1 || name.indexOf('..') !== -1) {
    defer.resolve({ success: false, error: 'invalid name' });
    return defer.promise;
  }
  try {
    var filePath = null;
    if (kind === 'font') {
      if (!REMOTE_FONT_NAME_REGEX.test(name)) {
        defer.resolve({ success: false, error: 'invalid font name' });
        return defer.promise;
      }
      var themeFonts = path.join(process.env.VOLUMIO_ACTIVE_UI_PATH || '/volumio/http/www', 'app', 'themes', 'volumio3', 'assets', 'variants', 'volumio', 'fonts', name);
      var pluginFonts = path.join(self.remoteFontsDir(), name);
      if (fs.existsSync(themeFonts)) { filePath = themeFonts; }
      else if (fs.existsSync(pluginFonts)) { filePath = pluginFonts; }
    } else {
      if (!REMOTE_HANDLER_NAME_REGEX.test(name)) {
        defer.resolve({ success: false, error: 'invalid handler name' });
        return defer.promise;
      }
      var hp = path.join(self.remoteHandlersDir(), name);
      if (fs.existsSync(hp)) { filePath = hp; }
    }
    if (!filePath) {
      defer.resolve({ success: false, error: 'not found' });
      return defer.promise;
    }
    var buf = fs.readFileSync(filePath, { encoding: null });
    defer.resolve({
      success: true,
      kind: kind,
      name: name,
      sha256: crypto.createHash('sha256').update(buf).digest('hex'),
      data: buf.toString('base64')
    });
  } catch (err) {
    self.logger.error(id + 'getRemoteFile: ' + err.message);
    defer.resolve({ success: false, error: err.message });
  }
  return defer.promise;
};

// HTTP endpoint: Return vinyl image from album folder for remote clients (peppy_remote)
// Called via: POST /api/v1/pluginEndpoint with body { endpoint: 'peppy_screensaver_vinyl', data: { uri: '...', filename: 'vinyl.jpg' } }
peppyScreensaver.prototype.getVinylImage = function (data) {
  var self = this;
  var defer = libQ.defer();
  var uri = (data && typeof data.uri === 'string') ? data.uri.trim() : '';
  var filename = (data && typeof data.filename === 'string') ? data.filename.trim() : '';
  if (!uri || !filename || filename.indexOf('/') !== -1 || filename.indexOf('..') !== -1) {
    defer.resolve({ success: false, error: 'invalid uri or filename' });
    return defer.promise;
  }
  var allowedExt = ['.png', '.jpg', '.jpeg', '.gif', '.webp'];
  var ext = path.extname(filename).toLowerCase();
  if (allowedExt.indexOf(ext) === -1) {
    defer.resolve({ success: false, error: 'invalid file extension' });
    return defer.promise;
  }
  try {
    var san = uri.replace(/^music-library\/?/, '').replace(/^mnt\/?/, '');
    var base = san.startsWith('/') ? '/mnt' + san : '/mnt/' + san;
    var albumFolder = path.dirname(base);
    var vinylPath = path.join(albumFolder, filename);
    var realPath = path.resolve(vinylPath);
    if (realPath.indexOf('/mnt/') !== 0 && realPath.indexOf('/mnt') !== 0) {
      defer.resolve({ success: false, error: 'path outside music library' });
      return defer.promise;
    }
    if (realPath.indexOf('..') !== -1) {
      defer.resolve({ success: false, error: 'path traversal not allowed' });
      return defer.promise;
    }
    if (!fs.existsSync(realPath)) {
      defer.resolve({ success: false, error: 'not found' });
      return defer.promise;
    }
    var buf = fs.readFileSync(realPath, { encoding: null });
    defer.resolve({ success: true, data: buf.toString('base64') });
  } catch (err) {
    self.logger.error(id + 'getVinylImage: ' + err.message);
    defer.resolve({ success: false, error: err.message });
  }
  return defer.promise;
};

// HTTP endpoint: Return the first matching decorative image from the playing track's
// folder, as base64. Generalises getVinylImage for the extra folder layer (Item 5).
// Called via: POST /api/v1/pluginEndpoint with body
//   { endpoint: 'peppy_screensaver_folderimage', data: { uri: '...', filenames: ['back.png','logo.png',...] } }
// Resolution and sandboxing are identical to getVinylImage (confined under /mnt).
// For non-file sources (Spotify, webradio, etc.) the path won't exist -> { success:false }.
peppyScreensaver.prototype.getFolderImage = function (data) {
  var self = this;
  var defer = libQ.defer();
  var uri = (data && typeof data.uri === 'string') ? data.uri.trim() : '';
  var filenames = (data && Array.isArray(data.filenames)) ? data.filenames : [];
  if (typeof filenames === 'string') {
    filenames = filenames.split(',');
  }
  if (!uri || !filenames.length) {
    defer.resolve({ success: false, error: 'invalid uri or filenames' });
    return defer.promise;
  }
  var allowedExt = ['.png', '.jpg', '.jpeg', '.gif', '.webp'];
  try {
    var san = uri.replace(/^music-library\/?/, '').replace(/^mnt\/?/, '');
    var base = san.startsWith('/') ? '/mnt' + san : '/mnt/' + san;
    var albumFolder = path.dirname(base);
    var i;
    for (i = 0; i < filenames.length; i++) {
      var filename = (typeof filenames[i] === 'string') ? filenames[i].trim() : '';
      if (!filename || filename.indexOf('/') !== -1 || filename.indexOf('..') !== -1) {
        continue;
      }
      if (allowedExt.indexOf(path.extname(filename).toLowerCase()) === -1) {
        continue;
      }
      var realPath = path.resolve(path.join(albumFolder, filename));
      if (realPath.indexOf('/mnt/') !== 0 && realPath.indexOf('/mnt') !== 0) {
        continue;
      }
      if (realPath.indexOf('..') !== -1) {
        continue;
      }
      if (fs.existsSync(realPath) && fs.statSync(realPath).isFile()) {
        var buf = fs.readFileSync(realPath, { encoding: null });
        defer.resolve({ success: true, filename: filename, data: buf.toString('base64') });
        return defer.promise;
      }
    }
    defer.resolve({ success: false, error: 'not found' });
  } catch (err) {
    self.logger.error(id + 'getFolderImage: ' + err.message);
    defer.resolve({ success: false, error: err.message });
  }
  return defer.promise;
};

// =============================================================================
// Artist fanart (Item 6) - server-side retrieval + on-disk cache
// =============================================================================
function fanartArtistSlug(artist) {
  var raw = String(artist || '').trim().toLowerCase();
  if (!raw) {
    return '';
  }
  var ascii = raw.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
  if (ascii) {
    return ascii;
  }
  // Non-Latin names (Thai, CJK, Cyrillic, …): ASCII slug would be empty and
  // blocked fanart entirely; use a stable hashed cache directory instead.
  return 'u-' + crypto.createHash('sha256').update(raw, 'utf8').digest('hex').slice(0, 16);
}

function fanartDecodeUriPath(part) {
  if (!part || part.indexOf('%') === -1) {
    return part;
  }
  try {
    return decodeURIComponent(part);
  } catch (e) {
    return part;
  }
}

function fanartHttpsGetText(url, headers, timeoutMs) {
  return new Promise(function (resolve, reject) {
    var lib = url.indexOf('https') === 0 ? require('https') : require('http');
    var req = lib.get(url, { headers: headers || {} }, function (resp) {
      if (resp.statusCode >= 300 && resp.statusCode < 400 && resp.headers.location) {
        resp.resume();
        resolve(fanartHttpsGetText(resp.headers.location, headers, timeoutMs));
        return;
      }
      if (resp.statusCode !== 200) {
        resp.resume();
        reject(new Error('HTTP ' + resp.statusCode));
        return;
      }
      var data = '';
      resp.setEncoding('utf8');
      resp.on('data', function (c) { data += c; });
      resp.on('end', function () { resolve(data); });
    });
    req.on('error', reject);
    req.setTimeout(timeoutMs || 8000, function () { req.destroy(new Error('timeout')); });
  });
}

function fanartDownloadFile(url, dest, timeoutMs) {
  return new Promise(function (resolve, reject) {
    var lib = url.indexOf('https') === 0 ? require('https') : require('http');
    var req = lib.get(url, function (resp) {
      if (resp.statusCode >= 300 && resp.statusCode < 400 && resp.headers.location) {
        resp.resume();
        resolve(fanartDownloadFile(resp.headers.location, dest, timeoutMs));
        return;
      }
      if (resp.statusCode !== 200) {
        resp.resume();
        reject(new Error('HTTP ' + resp.statusCode));
        return;
      }
      var file = fs.createWriteStream(dest);
      resp.pipe(file);
      file.on('finish', function () { file.close(function () { resolve(true); }); });
      file.on('error', reject);
    });
    req.on('error', reject);
    req.setTimeout(timeoutMs || 15000, function () { req.destroy(new Error('timeout')); });
  });
}

peppyScreensaver.prototype.fanartListLocalImages = function (dir) {
  var out = [];
  try {
    if (!dir || !fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) {
      return out;
    }
    fs.readdirSync(dir).forEach(function (f) {
      if (FANART_IMAGE_EXTS.indexOf(path.extname(f).toLowerCase()) !== -1) {
        var p = path.join(dir, f);
        try { if (fs.statSync(p).isFile()) out.push(p); } catch (e) {}
      }
    });
  } catch (e) {}
  out.sort();
  return out;
};

peppyScreensaver.prototype.fanartSourceFingerprint = function (paths) {
  if (!paths || !paths.length) {
    return '';
  }
  return paths.map(function (p) {
    try {
      var st = fs.statSync(p);
      return p + ':' + st.mtimeMs + ':' + st.size;
    } catch (e) {
      return p + ':0:0';
    }
  }).sort().join(',');
};

peppyScreensaver.prototype.fanartResolveLocalSource = function (artist, uri) {
  var self = this;
  if (artist.indexOf('/') === -1 && artist.indexOf('..') === -1) {
    var personalImgs = self.fanartListLocalImages(FanartPersonalArtDir + '/' + artist);
    if (personalImgs.length) {
      return {
        source: 'personal',
        picked: personalImgs.map(function (p) { return { type: 'file', path: p }; }),
        fingerprint: 'personal:' + self.fanartSourceFingerprint(personalImgs)
      };
    }
  }
  if (uri) {
    var artistDir = self.fanartResolveArtistMusicDir(uri);
    if (artistDir) {
      var subImgs = self.fanartListLocalImages(path.join(artistDir, 'fanart'));
      if (subImgs.length) {
        return {
          source: 'local-fanart',
          picked: subImgs.map(function (p) { return { type: 'file', path: p }; }),
          fingerprint: 'local-fanart:' + self.fanartSourceFingerprint(subImgs)
        };
      }
    }
  }
  return null;
};

peppyScreensaver.prototype.fanartShouldUseDiskCache = function (cached, artist, uri) {
  var self = this;
  if (!cached || !cached.images || !cached.images.length) {
    return false;
  }
  var firstFile = PluginPath + '/' + cached.images[0].replace('user_interface/peppy_screensaver/', '');
  if (!fs.existsSync(firstFile)) {
    return false;
  }
  var localNow = self.fanartResolveLocalSource(artist, uri);
  if (localNow) {
    return cached.source === localNow.source && cached.sourceSig === localNow.fingerprint;
  }
  if (cached.source === 'personal' || cached.source === 'local-fanart') {
    return false;
  }
  return (Date.now() - (cached.ts || 0)) < FANART_TTL_MS;
};

peppyScreensaver.prototype.fanartResolveArtistMusicDir = function (uri) {
  try {
    var san = fanartDecodeUriPath(uri.replace(/^music-library\/?/, '').replace(/^mnt\/?/, ''));
    var base = san.startsWith('/') ? '/mnt' + san : '/mnt/' + san;
    var albumDir = path.dirname(path.resolve(base));
    var artistDir = path.dirname(albumDir);
    if (artistDir.indexOf('/mnt/') !== 0 || artistDir.indexOf('..') !== -1) {
      return null;
    }
    return artistDir;
  } catch (e) {
    return null;
  }
};

peppyScreensaver.prototype.fanartReadManifest = function (p) {
  try { if (fs.existsSync(p)) { return JSON.parse(fs.readFileSync(p, 'utf8')); } } catch (e) {}
  return null;
};

peppyScreensaver.prototype.fanartWriteManifest = function (p, obj) {
  try { fs.writeFileSync(p, JSON.stringify(obj)); } catch (e) {}
};

// Resolve artist name -> MusicBrainz MBID, cached (incl. negative results). Never guesses
// on a low-confidence match; transient errors are not cached.
peppyScreensaver.prototype.fanartResolveMBID = async function (artist) {
  var self = this;
  var key = artist.toLowerCase();
  var cacheFile = FanartCacheDir + '/mbid.json';
  var cache = {};
  try { if (fs.existsSync(cacheFile)) { cache = JSON.parse(fs.readFileSync(cacheFile, 'utf8')) || {}; } } catch (e) {}
  if (Object.prototype.hasOwnProperty.call(cache, key)) {
    return cache[key];
  }
  var mbid = null;
  try {
    var url = 'https://musicbrainz.org/ws/2/artist/?query=' + encodeURIComponent('artist:"' + artist + '"') + '&fmt=json&limit=1';
    var ua = 'PeppyScreensaver/' + peppyPluginVersion + ' ( https://github.com/foonerd/peppy_screensaver )';
    var body = await fanartHttpsGetText(url, { 'User-Agent': ua, 'Accept': 'application/json' }, 8000);
    var json = JSON.parse(body);
    if (json && json.artists && json.artists.length && json.artists[0].id) {
      var top = json.artists[0];
      if (top.score === undefined || top.score >= 90) {
        mbid = top.id;
      }
    }
  } catch (e) {
    galleryLog(self.logger, 'verbose', 'fanart MBID lookup failed for ' + artist + ': ' + e.message);
    return null; // do not negative-cache transient failures
  }
  try { fs.ensureDirSync(FanartCacheDir); cache[key] = mbid; fs.writeFileSync(cacheFile, JSON.stringify(cache)); } catch (e) {}
  return mbid;
};

peppyScreensaver.prototype.fanartFetchFanartTv = async function (mbid, apiKey) {
  var url = 'https://webservice.fanart.tv/v3/music/' + encodeURIComponent(mbid) + '?api_key=' + encodeURIComponent(apiKey || FANART_TV_PROJECT_KEY);
  var body = await fanartHttpsGetText(url, { 'Accept': 'application/json' }, 10000);
  var json = JSON.parse(body);
  var urls = [];
  if (json && Array.isArray(json.artistbackground)) {
    json.artistbackground.forEach(function (b) { if (b && b.url) { urls.push(b.url); } });
  }
  return urls;
};

peppyScreensaver.prototype.fanartFetchMetaVolumio = async function (artist) {
  var variant = 'volumio';
  try {
    variant = execSync("cat /etc/os-release | grep ^VOLUMIO_VARIANT | tr -d 'VOLUMIO_VARIANT=\"'").toString().replace('\n', '').trim() || 'volumio';
  } catch (e) {}
  var url = 'https://meta.volumio.org/metas/v1/getDatas?mode=artistArt&artist=' + encodeURIComponent(artist.replace('&', 'and')) + '&variant=' + encodeURIComponent(variant);
  var body = await fanartHttpsGetText(url, { 'Accept': 'application/json' }, 8000);
  var json = JSON.parse(body);
  if (json && json.success && json.data) {
    if (typeof json.data === 'string') { return json.data; }
    if (Array.isArray(json.data) && json.data.length) { return json.data[0]; }
  }
  return null;
};

// HTTP endpoint: artist fanart slideshow source list (Item 6). Returns an ordered list
// of sectionimage paths (served via /albumart?sectionimage=...), populating an on-disk
// cache. Cascade: personal artist folder -> fanart/ subfolder -> fanart.tv (MBID) ->
// meta.volumio.org single. POST { endpoint: 'peppy_screensaver_artistfanart', data: { artist, uri } }
function fanartPlaybackOptions(self) {
  var fanartIntervalMs = (parseInt(self.config.get('fanartInterval'), 10) || 0) * 1000;
  var fanartTransition = self.config.get('fanartTransition') || 'none';
  if (['none', 'fade', 'merge'].indexOf(fanartTransition) === -1) { fanartTransition = 'none'; }
  var fanartTransitionMs = parseInt(self.config.get('fanartTransitionMs'), 10);
  if (isNaN(fanartTransitionMs) || fanartTransitionMs < 50) { fanartTransitionMs = 600; }
  var fanartOrder = self.config.get('fanartOrder') || 'sequential';
  if (['sequential', 'random'].indexOf(fanartOrder) === -1) { fanartOrder = 'sequential'; }
  return {
    interval_ms: fanartIntervalMs,
    transition: fanartTransition,
    transition_ms: fanartTransitionMs,
    order: fanartOrder
  };
}

peppyScreensaver.prototype.getArtistFanart = async function (data) {
  var self = this;
  var artist = (data && typeof data.artist === 'string') ? data.artist.trim() : '';
  var uri = (data && typeof data.uri === 'string') ? data.uri.trim() : '';
  if (!artist) {
    return { success: false, error: 'no artist' };
  }
  // Master switch (Item 6): fanart only renders when globally enabled AND the skin
  // declares fanart slots. When disabled, return an empty set so the renderer clears.
  if (self.config.get('fanartEnabled') !== true) {
    return { success: true, source: 'disabled', images: [], interval_ms: 0, order: 'sequential' };
  }
  var fanartOpts = fanartPlaybackOptions(self);
  var slug = fanartArtistSlug(artist);
  if (!slug) {
    return { success: false, error: 'invalid artist' };
  }
  var artistCacheDir = FanartCacheDir + '/' + slug;
  var manifestPath = artistCacheDir + '/manifest.json';
  try {
    var cached = self.fanartReadManifest(manifestPath);
    if (self.fanartShouldUseDiskCache(cached, artist, uri)) {
      galleryLog(self.logger, 'basic', 'getArtistFanart cache hit ' + slug + ' (' + cached.images.length + ' img, ' + cached.source + ')');
      return { success: true, source: cached.source + ':cached', images: cached.images,
        interval_ms: fanartOpts.interval_ms, transition: fanartOpts.transition,
        transition_ms: fanartOpts.transition_ms, order: fanartOpts.order };
    }
    fs.ensureDirSync(artistCacheDir);

    var source = null;
    var picked = [];
    var sourceSig = null;

    var localSource = self.fanartResolveLocalSource(artist, uri);
    if (localSource) {
      source = localSource.source;
      picked = localSource.picked;
      sourceSig = localSource.fingerprint;
    }

    // Tier 3: fanart.tv full set (MBID via MusicBrainz). Key mode decides which
    // api_key is used: 'project' = built-in key (testing/development only),
    // 'personal' = the listener's own fanart.tv key (required; skipped if blank).
    if (!picked.length) {
      var keyMode = self.config.get('fanartKeyMode') || 'personal';
      var apiKey = '';
      if (keyMode === 'project') {
        apiKey = FANART_TV_PROJECT_KEY;
      } else {
        try { apiKey = (self.config.get('fanart_personal_key') || '').trim(); } catch (e) {}
      }
      if (apiKey) {
        var mbid = await self.fanartResolveMBID(artist);
        if (mbid) {
          var urls = await self.fanartFetchFanartTv(mbid, apiKey);
          if (urls.length) {
            source = 'fanart.tv';
            picked = urls.map(function (u) { return { type: 'url', url: u }; });
          }
        }
      } else {
        galleryLog(self.logger, 'verbose', 'fanart.tv skipped: personal key mode with no key set');
      }
    }

    // Tier 4: meta.volumio.org single image
    if (!picked.length) {
      var metaUrl = await self.fanartFetchMetaVolumio(artist);
      if (metaUrl) {
        source = 'meta.volumio';
        picked = [{ type: 'url', url: metaUrl }];
      }
    }

    if (!picked.length) {
      self.fanartWriteManifest(manifestPath, { ts: Date.now(), source: 'none', images: [] });
      galleryLog(self.logger, 'basic', 'getArtistFanart: no fanart for "' + artist + '"');
      return { success: false, error: 'no fanart' };
    }

    // Default: cap at FANART_MAX_IMAGES. Unlimited mode skips the cap (crash risk).
    if (self.config.get('fanartUnlimitedImages') !== true && picked.length > FANART_MAX_IMAGES) {
      picked = picked.slice(0, FANART_MAX_IMAGES);
    }

    // Clear previous cached images for this artist (keep manifest)
    try {
      fs.readdirSync(artistCacheDir).forEach(function (f) {
        if (f !== 'manifest.json') { fs.removeSync(path.join(artistCacheDir, f)); }
      });
    } catch (e) {}

    var images = [];
    for (var i = 0; i < picked.length; i++) {
      var item = picked[i];
      var ext = '.jpg';
      try {
        if (item.type === 'file') {
          ext = path.extname(item.path).toLowerCase() || '.jpg';
        } else {
          ext = path.extname(item.url.split('?')[0]).toLowerCase();
          if (FANART_IMAGE_EXTS.indexOf(ext) === -1) { ext = '.jpg'; }
        }
        var destName = i + ext;
        var destPath = path.join(artistCacheDir, destName);
        if (item.type === 'file') {
          fs.copySync(item.path, destPath);
        } else {
          await fanartDownloadFile(item.url, destPath, 15000);
        }
        images.push(FanartSectionPrefix + slug + '/' + destName);
      } catch (e) {
        galleryLog(self.logger, 'verbose', 'fanart image ' + i + ' failed: ' + e.message);
      }
    }

    if (!images.length) {
      self.fanartWriteManifest(manifestPath, { ts: Date.now(), source: 'none', images: [] });
      return { success: false, error: 'fetch failed' };
    }

    self.fanartWriteManifest(manifestPath, { ts: Date.now(), source: source, sourceSig: sourceSig, images: images });
    galleryLog(self.logger, 'basic', 'getArtistFanart "' + artist + '" -> ' + images.length + ' image(s) from ' + source);
    return { success: true, source: source, images: images,
      interval_ms: fanartOpts.interval_ms, transition: fanartOpts.transition,
      transition_ms: fanartOpts.transition_ms, order: fanartOpts.order };
  } catch (err) {
    self.logger.error(id + 'getArtistFanart: ' + err.message);
    return { success: false, error: err.message };
  }
};

peppyScreensaver.prototype.clearFanartCache = function () {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');
  self.commandRouter.broadcastMessage('openModal', {
    title: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CLEAR_FANART_CACHE_CONFIRM_TITLE'),
    message: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CLEAR_FANART_CACHE_CONFIRM_MSG'),
    size: 'md',
    buttons: [
      {
        name: self.commandRouter.getI18nString('COMMON.CANCEL'),
        class: 'btn btn-default',
        emit: 'closeModals',
        payload: ''
      },
      {
        name: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CLEAR_FANART_CACHE'),
        class: 'btn btn-warning',
        emit: 'callMethod',
        payload: {
          endpoint: 'user_interface/peppy_screensaver',
          method: 'clearFanartCacheConfirmed',
          data: {}
        }
      }
    ]
  });
  defer.resolve();
  return defer.promise;
};

/** Clear cached fanart images (keep mbid.json). Returns true on success. */
peppyScreensaver.prototype._clearFanartImageCache = function () {
  var self = this;
  if (!fs.existsSync(FanartCacheDir)) {
    return true;
  }
  fs.readdirSync(FanartCacheDir).forEach(function (f) {
    if (f === 'mbid.json') { return; }
    fs.removeSync(path.join(FanartCacheDir, f));
  });
  galleryLog(self.logger, 'basic', 'fanart cache cleared (mbid.json preserved)');
  return true;
};

peppyScreensaver.prototype.clearFanartCacheConfirmed = function () {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');
  try {
    self._clearFanartImageCache();
    if (fs.existsSync(runFlag)) { fs.removeSync(runFlag); }
    self.commandRouter.pushToastMessage('success', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.CLEAR_FANART_CACHE_DONE'));
  } catch (e) {
    self.logger.error(id + 'clearFanartCacheConfirmed: ' + e.message);
    self.commandRouter.pushToastMessage('error', pluginName, e.message);
  }
  defer.resolve();
  return defer.promise;
};

function escapeThemeGalleryHtml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildThemeGalleryActiveFrameOpen() {
  return '<table cellpadding="2" cellspacing="0" bgcolor="' + THEME_GALLERY_ACTIVE_SHADOW + '">' +
    '<tr><td><table cellpadding="2" cellspacing="0" bgcolor="' + THEME_GALLERY_ACTIVE_BORDER + '">' +
    '<tr><td align="center">';
}

function buildThemeGalleryActiveFrameClose() {
  return '</td></tr></table></td></tr></table>';
}

function escapeThemeGalleryJsString(text) {
  return JSON.stringify(String(text));
}

peppyScreensaver.prototype.formatThemeShortLabel = function (folder) {
  var upperc = /\b([^-])/g;
  if (!folder || !folder.includes('_')) {
    return folder || '';
  }
  var parts = folder.split('_');
  if (parts.length >= 3) {
    return parts[1].replace(upperc, function (c) { return c.toUpperCase(); }) + '-' + parts[2];
  }
  return parts[1].replace(upperc, function (c) { return c.toUpperCase(); });
};

peppyScreensaver.prototype.parseThemeResolution = function (folder) {
  if (!folder || folder.indexOf('_') === -1) {
    return '';
  }
  return folder.split('_')[0];
};

peppyScreensaver.prototype.isThemeGalleryAssetName = function (filename) {
  if (!filename) {
    return false;
  }
  var name = String(filename).trim();
  return name.length > 0 && name.indexOf('/') === -1 && name.indexOf('..') === -1;
};

peppyScreensaver.prototype.resolveThemeGalleryAssetPath = function (themePath, filename) {
  if (!this.isThemeGalleryAssetName(filename)) {
    return null;
  }
  var candidatePath = themePath + '/' + String(filename).trim();
  if (fs.existsSync(candidatePath) && fs.statSync(candidatePath).isFile()) {
    return candidatePath;
  }
  return null;
};

peppyScreensaver.prototype.loadThemeMetersTxtSections = function (themeFolder) {
  if (!themeFolder || themeFolder.indexOf('/') !== -1 || themeFolder.indexOf('..') !== -1) {
    return null;
  }
  var themePath = base_folder_P + themeFolder;
  var metersFile = themePath + '/meters.txt';
  if (!fs.existsSync(metersFile)) {
    return null;
  }
  try {
    var metersconfig = ini.parse(fs.readFileSync(metersFile, 'utf-8'));
    var sections = Object.keys(metersconfig);
    var result = [];
    var i;
    var sectionName;
    var section;
    for (i = 0; i < sections.length; i++) {
      sectionName = sections[i];
      section = metersconfig[sectionName];
      if (!section) {
        continue;
      }
      result.push({
        section: sectionName,
        data: section
      });
    }
    return { themePath: themePath, sections: result };
  } catch (e) {
    return null;
  }
};

peppyScreensaver.prototype.resolveThemePreviewFromMetersSection = function (themePath, sectionData, sectionName, contextLabel) {
  var self = this;
  var i;
  var spec;
  var filename;
  var candidatePath;

  for (i = 0; i < THEME_PREVIEW_METER_KEYS.length; i++) {
    spec = THEME_PREVIEW_METER_KEYS[i];
    filename = sectionData[spec.key];
    if (!filename) {
      continue;
    }
    candidatePath = self.resolveThemeGalleryAssetPath(themePath, filename);
    if (candidatePath) {
      galleryLog(self.logger, 'trace', contextLabel + ' section [' + sectionName + '] hit ' + spec.source + ' -> ' + filename);
      return {
        path: candidatePath,
        source: spec.source,
        section: sectionName
      };
    }
    galleryLog(self.logger, 'verbose', contextLabel + ' section [' + sectionName + '] missing file for ' + spec.source + ': ' + String(filename).trim());
  }
  return null;
};

peppyScreensaver.prototype.resolveThemePreviewFromMetersTxt = function (themeFolder, scope, sectionName, contextLabel) {
  var self = this;
  var parsed;
  var themePath;
  var i;
  var entry;
  var resolved;
  var label = contextLabel || ('resolveThemePreviewFromMetersTxt scope=' + scope);

  parsed = self.loadThemeMetersTxtSections(themeFolder);
  if (!parsed) {
    galleryLog(self.logger, 'verbose', label + ' no meters.txt for ' + themeFolder);
    return null;
  }
  themePath = parsed.themePath;

  if (scope === 'section') {
    if (!sectionName) {
      galleryLog(self.logger, 'verbose', label + ' section scope requires sectionName');
      return null;
    }
    for (i = 0; i < parsed.sections.length; i++) {
      entry = parsed.sections[i];
      if (entry.section === sectionName) {
        resolved = self.resolveThemePreviewFromMetersSection(themePath, entry.data, entry.section, label);
        if (resolved) {
          galleryLog(self.logger, 'basic', label + ' [' + themeFolder + '/' + sectionName + '] -> ' + resolved.source + ' (' + path.basename(resolved.path) + ')');
        } else {
          galleryLog(self.logger, 'verbose', label + ' [' + themeFolder + '/' + sectionName + '] no preview asset');
        }
        return resolved;
      }
    }
    galleryLog(self.logger, 'verbose', label + ' section [' + sectionName + '] not found in ' + themeFolder);
    return null;
  }

  // folder scope (tier 1 fallback): first valid across sections, key priority meter.preview -> screen.bgr -> bgr.filename
  for (i = 0; i < THEME_PREVIEW_METER_KEYS.length; i++) {
    var keySpec = THEME_PREVIEW_METER_KEYS[i];
    var s;
    var sectionEntry;
    var value;
    for (s = 0; s < parsed.sections.length; s++) {
      sectionEntry = parsed.sections[s];
      value = sectionEntry.data[keySpec.key];
      if (!value) {
        continue;
      }
      resolved = self.resolveThemeGalleryAssetPath(themePath, value);
      if (resolved) {
        galleryLog(self.logger, 'basic', label + ' [' + themeFolder + '] tier1 fallback -> ' + keySpec.source + ' [' + sectionEntry.section + '] (' + path.basename(resolved) + ')');
        galleryLog(self.logger, 'trace', label + ' [' + themeFolder + '] ' + keySpec.source + ' [' + sectionEntry.section + '] = ' + String(value).trim());
        return {
          path: resolved,
          source: keySpec.source,
          section: sectionEntry.section
        };
      }
      galleryLog(self.logger, 'verbose', label + ' [' + themeFolder + '] missing file for ' + keySpec.source + ' [' + sectionEntry.section + ']: ' + String(value).trim());
    }
  }

  galleryLog(self.logger, 'verbose', label + ' [' + themeFolder + '] no meters.txt preview fallback');
  return null;
};

peppyScreensaver.prototype.resolveThemeFolderPreview = function (themeFolder, contextLabel) {
  var self = this;
  var themePath = base_folder_P + themeFolder;
  var i;
  var candidate;
  var fileName;
  var metersResolved;
  var label = contextLabel || 'resolveThemeFolderPreview';

  if (!themeFolder || themeFolder.indexOf('/') !== -1 || themeFolder.indexOf('..') !== -1) {
    return null;
  }

  for (i = 0; i < THEME_PREVIEW_FILES.length; i++) {
    fileName = THEME_PREVIEW_FILES[i];
    candidate = themePath + '/' + fileName;
    if (fs.existsSync(candidate)) {
      galleryLog(self.logger, 'basic', label + ' [' + themeFolder + '] -> folder ' + fileName);
      return {
        path: candidate,
        source: 'folder:' + fileName,
        section: null
      };
    }
  }

  metersResolved = self.resolveThemePreviewFromMetersTxt(themeFolder, 'folder', null, label);
  return metersResolved;
};

peppyScreensaver.prototype.resolveMeterSectionPreview = function (themeFolder, sectionName, contextLabel) {
  return this.resolveThemePreviewFromMetersTxt(themeFolder, 'section', sectionName, contextLabel || 'resolveMeterSectionPreview');
};

peppyScreensaver.prototype.findThemePreviewFile = function (themeFolder) {
  var resolved = this.resolveThemeFolderPreview(themeFolder, 'findThemePreviewFile');
  return resolved ? resolved.path : null;
};

peppyScreensaver.prototype.removeThemeGalleryCacheSiblings = function (themeFolder, keepExt, cacheKeySuffix) {
  var self = this;
  var i;
  var ext;
  var siblingName;
  var siblingPath;
  var suffix = cacheKeySuffix || '';
  if (!fs.existsSync(ThemeGalleryDir)) {
    return;
  }
  for (i = 0; i < THEME_GALLERY_CACHE_EXTS.length; i++) {
    ext = THEME_GALLERY_CACHE_EXTS[i];
    if (ext === keepExt) {
      continue;
    }
    siblingName = themeFolder + suffix + ext;
    siblingPath = ThemeGalleryDir + '/' + siblingName;
    if (fs.existsSync(siblingPath)) {
      fs.removeSync(siblingPath);
      galleryLog(self.logger, 'verbose', 'removed leftover cache ' + siblingName);
    }
  }
};

peppyScreensaver.prototype.ensureThemeGalleryCacheEntry = function (themeFolder, previewPath, cacheKeySuffix) {
  var self = this;
  try {
    if (!fs.existsSync(ThemeGalleryDir)) {
      fs.mkdirSync(ThemeGalleryDir, { recursive: true });
    }
    var ext = path.extname(previewPath).toLowerCase() || '.png';
    var cacheName = themeFolder + (cacheKeySuffix || '') + ext;
    var cachePath = ThemeGalleryDir + '/' + cacheName;
    var srcStat = fs.statSync(previewPath);
    var version = String(Math.floor(srcStat.mtimeMs)) + '-' + String(srcStat.size);
    var needCopy = true;
    if (fs.existsSync(cachePath)) {
      var dstStat = fs.statSync(cachePath);
      if (dstStat.size === srcStat.size && dstStat.mtimeMs >= srcStat.mtimeMs) {
        galleryLog(self.logger, 'trace', 'cache hit ' + cacheName + ' <- ' + previewPath);
        needCopy = false;
      } else if (dstStat.size !== srcStat.size) {
        galleryLog(self.logger, 'verbose', 'cache stale size ' + cacheName + ' (' + dstStat.size + ' != ' + srcStat.size + ')');
      }
    }
    if (needCopy) {
      fs.copySync(previewPath, cachePath);
      galleryLog(self.logger, 'verbose', 'cached ' + cacheName + ' <- ' + previewPath);
    }
    self.removeThemeGalleryCacheSiblings(themeFolder, ext, cacheKeySuffix);
    return {
      sectionImage: ThemeGallerySectionPrefix + cacheName,
      version: version
    };
  } catch (e) {
    galleryLog(self.logger, 'verbose', 'cache failed for ' + themeFolder + ': ' + e.message);
    return null;
  }
};

peppyScreensaver.prototype.ensureThemeGallerySelectPage = function (themeFolder) {
  try {
    if (!themeFolder || themeFolder.indexOf('/') !== -1 || themeFolder.indexOf('..') !== -1) {
      return null;
    }
    if (!fs.existsSync(ThemeGalleryDir)) {
      fs.mkdirSync(ThemeGalleryDir, { recursive: true });
    }
    var cacheName = themeFolder + '.select.html';
    var cachePath = ThemeGalleryDir + '/' + cacheName;
    var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title></title></head><body>' +
      '<script>(function(){var f=' + escapeThemeGalleryJsString(themeFolder) + ';' +
      'fetch("/api/v1/pluginEndpoint",{method:"POST",headers:{"Content-Type":"application/json"},' +
      'body:JSON.stringify({endpoint:"peppy_screensaver_theme",data:{folder:f}})})' +
      '.catch(function(){}).finally(function(){if(window.top===window.self){window.location.href="/#/plugin/user_interface-peppy_screensaver";}});})();</script>' +
      '</body></html>';
    fs.writeFileSync(cachePath, html, 'utf8');
    return ThemeGallerySectionPrefix + cacheName;
  } catch (e) {
    return null;
  }
};

peppyScreensaver.prototype.collectThemeGalleryEntries = function () {
  var self = this;
  var themes = [];
  var files = fs.readdirSync(base_folder_P);

  files.forEach(function (file) {
    var folderPath = base_folder_P + file;
    var stat = fs.statSync(folderPath);
    if (!stat.isDirectory() || file.indexOf('_') === -1) {
      return;
    }
    var resolved = self.resolveThemeFolderPreview(file, 'collectThemeGalleryEntries');
    if (!resolved) {
      return;
    }
    var previewPath = resolved.path;
    var cached = self.ensureThemeGalleryCacheEntry(file, previewPath);
    if (!cached) {
      return;
    }
    var selectSectionImage = self.ensureThemeGallerySelectPage(file);
    if (!selectSectionImage) {
      return;
    }
    themes.push({
      folder: file,
      label: self.formatThemeShortLabel(file) + ' \u00b7 ' + self.parseThemeResolution(file),
      shortLabel: self.formatThemeShortLabel(file),
      resolution: self.parseThemeResolution(file),
      sectionImage: cached.sectionImage,
      previewVersion: cached.version,
      selectSectionImage: selectSectionImage,
      previewSource: resolved.source,
      previewSection: resolved.section
    });
  });

  themes.sort(function (a, b) {
    if (a.resolution !== b.resolution) {
      return a.resolution.localeCompare(b.resolution, undefined, { numeric: true });
    }
    return a.shortLabel.localeCompare(b.shortLabel);
  });

  return themes;
};

peppyScreensaver.prototype.buildThemeGalleryHtml = function (themes, activeFolder) {
  var self = this;
  if (!themes.length) {
    return '';
  }

  // Volumio modal-custom.html binds message with ng-bind-html ($sanitize).
  // style= and <style> are stripped; class and HTML table/img attrs survive.
  // Tables size from image intrinsic min-content, so 3 columns + large
  // previews overflow phone portrait. Use 2 columns and Bootstrap
  // img-responsive (max-width:100%) so thumbs cannot force horizontal clip.
  var activeLabel = escapeThemeGalleryHtml(self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_GALLERY_ACTIVE'));
  var html = '<p>' + escapeThemeGalleryHtml(self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_GALLERY_SELECT_HINT')) + '</p>';
  html += '<table align="center" width="100%" cellspacing="4" cellpadding="2">';
  var colsPerRow = THEME_GALLERY_COLS;
  var colWidth = Math.floor(100 / colsPerRow);
  var currentResolution = null;
  var firstResolution = true;
  var rowThemes = [];

  function flushRow(themesInRow, centered) {
    var padLeft = 0;
    var idx;
    var theme;
    var isActive;
    var label;
    var imgSrc;
    var frameStart;
    var frameEnd;

    if (!themesInRow.length) {
      return;
    }
    if (centered && themesInRow.length < colsPerRow) {
      padLeft = Math.floor((colsPerRow - themesInRow.length) / 2);
    }
    html += '<tr>';
    for (idx = 0; idx < padLeft; idx++) {
      html += '<td width="' + colWidth + '%"></td>';
    }
    for (idx = 0; idx < themesInRow.length; idx++) {
      theme = themesInRow[idx];
      isActive = theme.folder === activeFolder;
      label = escapeThemeGalleryHtml(theme.shortLabel);
      imgSrc = '/albumart?sectionimage=' + theme.sectionImage + '&t=' + theme.previewVersion;
      frameStart = isActive ? buildThemeGalleryActiveFrameOpen() : '';
      frameEnd = isActive ? buildThemeGalleryActiveFrameClose() : '';

      html += '<td align="center" valign="top" width="' + colWidth + '%">';
      html += frameStart;
      html += '<img class="img-responsive" width="100%" src="' + imgSrc + '" alt="' + label + '"/>';
      html += '<br/>';
      if (isActive) {
        html += '<font color="' + THEME_GALLERY_ACTIVE_BORDER + '"><b>' + label + ' (' + activeLabel + ')</b></font>';
      } else {
        // target attribute is required: it makes AngularJS $location skip its
        // same-origin link-rewriting handler, so the browser actually navigates
        // to the select.html shim instead of routing inside the SPA.
        html += '<a target="_self" href="/albumart?sectionimage=' + theme.selectSectionImage + '"><b>' + label + '</b></a>';
      }
      html += frameEnd;
      html += '</td>';
    }
    for (idx = padLeft + themesInRow.length; idx < colsPerRow; idx++) {
      html += '<td width="' + colWidth + '%"></td>';
    }
    html += '</tr>';
  }

  themes.forEach(function (theme) {
    if (theme.resolution !== currentResolution) {
      if (rowThemes.length) {
        flushRow(rowThemes, true);
        rowThemes = [];
      }
      if (!firstResolution) {
        html += '<tr><td colspan="' + colsPerRow + '"><hr/></td></tr>';
      }
      firstResolution = false;
      currentResolution = theme.resolution;
      html += '<tr><td align="center" colspan="' + colsPerRow + '"><b>' +
        escapeThemeGalleryHtml(currentResolution) + '</b></td></tr>';
    }
    rowThemes.push(theme);
    if (rowThemes.length >= colsPerRow) {
      flushRow(rowThemes, false);
      rowThemes = [];
    }
  });

  if (rowThemes.length) {
    flushRow(rowThemes, true);
  }

  html += '</table>';
  return html;
};

peppyScreensaver.prototype.buildThemeGalleryButtons = function () {
  var self = this;
  return [{
    name: self.commandRouter.getI18nString('COMMON.CANCEL'),
    class: 'btn btn-link btn-sm',
    emit: '',
    payload: ''
  }];
};

peppyScreensaver.prototype.applyActiveThemeFolder = function (folder) {
  var self = this;

  galleryLog(self.logger, 'basic', 'applyActiveThemeFolder called folder=' + folder);

  if (!folder || folder.indexOf('/') !== -1 || folder.indexOf('..') !== -1 || folder.indexOf('_') === -1) {
    galleryLog(self.logger, 'verbose', 'applyActiveThemeFolder rejected invalid folder');
    return { changed: false, error: 'invalid' };
  }

  var folderPath = base_folder_P + folder;
  if (!fs.existsSync(folderPath) || !fs.statSync(folderPath).isDirectory()) {
    return { changed: false, error: 'not_found' };
  }

  if (!fs.existsSync(PeppyConf)) {
    return { changed: false, error: 'no_config' };
  }

  if (!spectrum_config && fs.existsSync(SpectrumConf)) {
    spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
  }

  if (peppy_config.current[meterFolderStr] === folder) {
    galleryLog(self.logger, 'basic', 'applyActiveThemeFolder unchanged (already active)');
    return { changed: false };
  }

  var partFile = folder.split('_');
  var upperc = /\b([^-])/g;
  var str_empty = fs.existsSync(folderPath + '/meters.txt') ? '' : ' (empty)';
  var folderTitle = (partFile[1]).replace(upperc, function (c) { return c.toUpperCase(); }) + '-' + partFile[2] + ' ' + partFile[0] + str_empty;

  peppy_config.current[meterFolderStr] = folder;
  if (spectrum_config) {
    spectrum_config.current[SpectrumFolderStr] = folder;
  }
  self.config.set('activeFolder', folder);
  self.config.set('activeFolder_title', folderTitle);
  peppy_config.current.meter = 'random';
  self.config.set('randomSelection', '');
  self.checkMetersFile();

  var dimensions = { width: '', height: '' };
  try {
    var files = fs.readdirSync(folderPath);
    files.forEach(function (file) {
      if (file.indexOf('-ext.') >= 0) {
        dimensions = sizeOf(folderPath + '/' + file);
      }
    });
  } catch (e) {
    self.logger.warn(id + 'applyActiveThemeFolder: could not read dimensions: ' + e.message);
  }
  peppy_config.current['screen.width'] = dimensions.width;
  peppy_config.current['screen.height'] = dimensions.height;

  fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, { whitespace: true }));
  if (spectrum_config) {
    fs.writeFileSync(SpectrumConf, ini.stringify(spectrum_config, { whitespace: true }));
  }
  try { self.updateConfigVersion(); } catch (e) {}
  if (fs.existsSync(runFlag)) {
    fs.removeSync(runFlag);
  }

  uiNeedsUpdate = true;
  self.updateUIConfig();

  galleryLog(self.logger, 'basic', 'applyActiveThemeFolder applied ' + folder + ' -> ' + folderTitle);
  return { changed: true, label: folderTitle };
};

peppyScreensaver.prototype.selectThemeFromGallery = function (data) {
  var self = this;
  var defer = libQ.defer();
  var folder = null;
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');

  if (typeof data === 'string') {
    folder = data;
  } else if (data && data.folder) {
    folder = data.folder;
  }

  galleryLog(self.logger, 'basic', 'selectThemeFromGallery REST call folder=' + folder);

  if (!folder) {
    self.logger.warn(id + 'selectThemeFromGallery: missing folder in REST payload');
    defer.resolve();
    return defer.promise;
  }

  try {
    if (fs.existsSync(PeppyConf)) {
      peppy_config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
      base_folder_P = peppy_config.current['base.folder'] + '/';
      if (base_folder_P === '/') {
        base_folder_P = PeppyPath + '/';
      }
    }
    if (fs.existsSync(SpectrumConf)) {
      spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
    }
  } catch (e) {
    self.logger.error(id + 'selectThemeFromGallery: failed to reload config: ' + e.message);
    defer.resolve();
    return defer.promise;
  }

  var result = self.applyActiveThemeFolder(folder);
  galleryLog(self.logger, 'basic', 'selectThemeFromGallery result changed=' + result.changed + (result.error ? ' error=' + result.error : ''));
  if (result.error === 'no_config') {
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG'));
  } else if (result.error) {
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_GALLERY_INVALID'));
  } else if (!result.changed) {
    self.commandRouter.pushToastMessage('info', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_CHANGES'));
  } else {
    self.commandRouter.pushToastMessage('success', pluginName, self.commandRouter.getI18nString('COMMON.SETTINGS_SAVED_SUCCESSFULLY'));
  }

  if (!result.error) {
    self.commandRouter.closeModals();
  }

  defer.resolve();
  return defer.promise;
};

// Unified save for the "Themes & Artwork" section. Persists the artist-fanart
// settings (enable / personal key / timed interval), and only triggers theme
// removal when a theme is explicitly selected (the dropdown defaults to an empty
// placeholder, so a normal save never deletes anything). Removal still goes
// through the confirm modal in removeThemeFolder.
peppyScreensaver.prototype.saveThemesArtwork = function (data) {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');

  try {
    var enabled = (data && (data.fanartEnabled === true || data.fanartEnabled === 'true'));
    var keyMode = (data && data.fanartKeyMode && typeof data.fanartKeyMode === 'object')
      ? data.fanartKeyMode.value
      : (data && data.fanartKeyMode);
    if (keyMode !== 'project') { keyMode = 'personal'; }
    var key = (data && typeof data.fanart_personal_key === 'string') ? data.fanart_personal_key.trim() : '';
    var interval = parseInt(data && data.fanartInterval, 10);
    if (isNaN(interval) || interval < 0) { interval = 0; }
    if (interval > 3600) { interval = 3600; }
    var transition = (data && data.fanartTransition && typeof data.fanartTransition === 'object')
      ? data.fanartTransition.value
      : (data && data.fanartTransition);
    if (['none', 'fade', 'merge'].indexOf(transition) === -1) { transition = 'none'; }
    var transitionMs = parseInt(data && data.fanartTransitionMs, 10);
    if (isNaN(transitionMs) || transitionMs < 50) { transitionMs = 600; }
    if (transitionMs > 3000) { transitionMs = 3000; }
    var order = (data && data.fanartOrder && typeof data.fanartOrder === 'object')
      ? data.fanartOrder.value
      : (data && data.fanartOrder);
    if (['sequential', 'random'].indexOf(order) === -1) { order = 'sequential'; }
    var unlimitedWanted = (data && (data.fanartUnlimitedImages === true || data.fanartUnlimitedImages === 'true'));
    var wasUnlimited = self.config.get('fanartUnlimitedImages') === true;
    var pendingUnlimitedEnable = (unlimitedWanted && !wasUnlimited);
    var unlimitedDisabled = (!unlimitedWanted && wasUnlimited);

    self.config.set('fanartEnabled', enabled);
    self.config.set('fanartKeyMode', keyMode);
    self.config.set('fanart_personal_key', key);
    self.config.set('fanartInterval', interval);
    self.config.set('fanartOrder', order);
    self.config.set('fanartTransition', transition);
    self.config.set('fanartTransitionMs', transitionMs);
    // Off→On for unlimited is gated by openModal confirm; do not set true here.
    if (unlimitedDisabled) {
      self.config.set('fanartUnlimitedImages', false);
      try { self._clearFanartImageCache(); } catch (eClearOff) {
        self.logger.error(id + 'saveThemesArtwork: clear cache on unlimited Off: ' + eClearOff.message);
      }
    } else if (!pendingUnlimitedEnable && unlimitedWanted) {
      self.config.set('fanartUnlimitedImages', true);
    }

    // --- Theme + font settings that live in config.txt / config.json (moved here
    //     from the old global section): keep-themes flag, active theme folder
    //     (with spectrum mirror + screen size), and the system-fonts toggle. ---
    var doNotDelete = data && data.doNotDeleteThemes === true;
    if (self.config.get('doNotDeleteThemes') !== doNotDelete) {
      self.config.set('doNotDeleteThemes', doNotDelete);
    }
    try {
      if (doNotDelete) {
        if (!fs.existsSync(DATA_DIR)) { fs.mkdirSync(DATA_DIR, { recursive: true }); }
        fs.writeFileSync(DATA_DIR + '/.preserve', '', 'utf8');
      } else {
        if (fs.existsSync(DATA_DIR + '/.preserve')) { fs.unlinkSync(DATA_DIR + '/.preserve'); }
      }
    } catch (ePreserve) {
      self.logger.error(id + 'saveThemesArtwork: failed to sync preserve-themes flag: ' + ePreserve.message);
    }

    var folderChanged = false;
    if (fs.existsSync(PeppyConf)) {
      var peppyChanged = false;
      if (!spectrum_config && fs.existsSync(SpectrumConf)) {
        spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
      }

      // active theme folder (+ spectrum mirror, meter reset, screen size)
      if (data && data.activeFolder && peppy_config.current[meterFolderStr] !== data.activeFolder.value) {
        peppy_config.current[meterFolderStr] = data.activeFolder.value;
        if (spectrum_config) { spectrum_config.current[SpectrumFolderStr] = data.activeFolder.value; }
        self.config.set('activeFolder', data.activeFolder.value);
        self.config.set('activeFolder_title', data.activeFolder.label);
        peppy_config.current.meter = 'random';
        self.config.set('randomSelection', '');
        self.checkMetersFile();

        // screen width/height from the active folder's -ext image
        var dimensions = { 'width': '', 'height': '' };
        try {
          var files = fs.readdirSync(base_folder_P + data.activeFolder.value);
          files.forEach(function (file) {
            if (file.indexOf('-ext.') >= 0) {
              dimensions = sizeOf(base_folder_P + data.activeFolder.value + '/' + file);
              files.length = 0;
            }
          });
        } catch (eDim) {
          self.logger.error(id + 'saveThemesArtwork: screen size detect failed: ' + eDim.message);
        }
        peppy_config.current['screen.width'] = dimensions.width;
        peppy_config.current['screen.height'] = dimensions.height;

        peppyChanged = true;
        folderChanged = true;
        if (spectrum_config) {
          fs.writeFileSync(SpectrumConf, ini.stringify(spectrum_config, { whitespace: true }));
        }
      }

      // use system fonts (SDL2 only, matching the prior global-section behaviour)
      if (use_SDL2) {
        var useSystemFonts = (data && data.useSystemFonts) ? 'True' : 'False';
        if (peppy_config.current['use.system.fonts'] != useSystemFonts) {
          peppy_config.current['use.system.fonts'] = useSystemFonts;
          peppyChanged = true;
        }
      }

      if (peppyChanged) {
        fs.writeFileSync(PeppyConf, ini.stringify(peppy_config, { whitespace: true }));
      }
    }

    // Bump the config version (so remote clients pick up the change) and remove the
    // run flag so the running screensaver reloads and applies the new artwork
    // settings immediately, consistent with the other settings sections.
    try { self.updateConfigVersion(); } catch (e) {}
    if (fs.existsSync(runFlag)) { fs.removeSync(runFlag); }
    // A folder switch resets the active meter to random / refreshes options, so the
    // settings page must be refreshed to reflect the new state.
    if (folderChanged) { try { self.updateUIConfig(); } catch (eUi) {} }

    self.commandRouter.pushToastMessage('success', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEMES_ARTWORK_SAVED'));

    // Gate unlimited fanart: Off→On requires explicit crash-risk confirm.
    if (pendingUnlimitedEnable) {
      self.commandRouter.broadcastMessage('openModal', {
        title: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.FANART_UNLIMITED_CONFIRM_TITLE'),
        message: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.FANART_UNLIMITED_CONFIRM_MSG'),
        size: 'lg',
        buttons: [
          {
            name: self.commandRouter.getI18nString('COMMON.CANCEL'),
            class: 'btn btn-default',
            emit: 'callMethod',
            payload: {
              endpoint: 'user_interface/peppy_screensaver',
              method: 'cancelFanartUnlimitedImages',
              data: {}
            }
          },
          {
            name: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.FANART_UNLIMITED_CONFIRM_BTN'),
            class: 'btn btn-warning',
            emit: 'callMethod',
            payload: {
              endpoint: 'user_interface/peppy_screensaver',
              method: 'enableFanartUnlimitedImagesConfirmed',
              data: {}
            }
          }
        ]
      });
    }
  } catch (e) {
    self.logger.error(id + 'saveThemesArtwork: ' + e.message);
  }

  // Only fall through to removal when a real theme folder was picked.
  var folder = (data && data.themeToRemove && typeof data.themeToRemove === 'object')
    ? data.themeToRemove.value
    : (data && data.themeToRemove);
  if (self.isValidThemeFolderName(folder)) {
    self.removeThemeFolder(data);
  }

  defer.resolve();
  return defer.promise;
};

peppyScreensaver.prototype.enableFanartUnlimitedImagesConfirmed = function () {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');
  try {
    self.config.set('fanartUnlimitedImages', true);
    self._clearFanartImageCache();
    try { self.updateConfigVersion(); } catch (eVer) {}
    if (fs.existsSync(runFlag)) { fs.removeSync(runFlag); }
    try { self.updateUIConfig(); } catch (eUi) {}
    self.commandRouter.pushToastMessage('success', pluginName,
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.FANART_UNLIMITED_ENABLED'));
    galleryLog(self.logger, 'basic', 'fanartUnlimitedImages enabled (no image cap; crash risk accepted)');
  } catch (e) {
    self.logger.error(id + 'enableFanartUnlimitedImagesConfirmed: ' + e.message);
    self.commandRouter.pushToastMessage('error', pluginName, e.message);
  }
  defer.resolve();
  return defer.promise;
};

peppyScreensaver.prototype.cancelFanartUnlimitedImages = function () {
  var self = this;
  var defer = libQ.defer();
  try {
    // Ensure switch stays Off in UI (config was never set On).
    self.config.set('fanartUnlimitedImages', false);
    self.updateUIConfig();
  } catch (e) {
    self.logger.error(id + 'cancelFanartUnlimitedImages: ' + e.message);
  }
  try { self.commandRouter.broadcastMessage('closeModals', ''); } catch (eClose) {}
  defer.resolve();
  return defer.promise;
};

// Theme removal (Item 2). onSave from the Theme gallery section shows a confirm
// modal; the modal's confirm button calls removeThemeFolderConfirmed. Deletion is
// not persisted across plugin updates (built-ins return on reinstall, by design).
peppyScreensaver.prototype.removeThemeFolder = function (data) {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');
  var folder = (data && data.themeToRemove && typeof data.themeToRemove === 'object')
    ? data.themeToRemove.value
    : (data && data.themeToRemove);

  if (!self.isValidThemeFolderName(folder)) {
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_INVALID'));
    defer.resolve();
    return defer.promise;
  }

  var title = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_CONFIRM_TITLE');
  var msg = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_CONFIRM_MSG') + ' ' + folder;
  self.commandRouter.broadcastMessage('openModal', {
    title: title,
    message: msg,
    size: 'lg',
    buttons: [
      {
        name: self.commandRouter.getI18nString('COMMON.CANCEL'),
        class: 'btn btn-default',
        emit: 'closeModals',
        payload: ''
      },
      {
        name: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_BTN'),
        class: 'btn btn-warning',
        emit: 'callMethod',
        payload: {
          endpoint: 'user_interface/peppy_screensaver',
          method: 'removeThemeFolderConfirmed',
          data: { folder: folder }
        }
      }
    ]
  });

  defer.resolve();
  return defer.promise;
};

peppyScreensaver.prototype.isValidThemeFolderName = function (folder) {
  return !!folder && typeof folder === 'string' &&
    folder.indexOf('/') === -1 && folder.indexOf('..') === -1 && folder.indexOf('_') !== -1;
};

// Safely remove base+folder only when it resolves under the expected templates root.
peppyScreensaver.prototype.removeThemeTreeFolder = function (baseDir, folder) {
  var self = this;
  if (!baseDir) {
    return false;
  }
  var root = path.resolve(baseDir);
  var target = path.resolve(path.join(root, folder));
  if (target.indexOf(root + path.sep) !== 0) {
    self.logger.warn(id + 'removeThemeTreeFolder: refusing path outside root: ' + target);
    return false;
  }
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
    fs.removeSync(target);
    return true;
  }
  return false;
};

peppyScreensaver.prototype.removeThemeFolderConfirmed = function (data) {
  var self = this;
  var defer = libQ.defer();
  var pluginName = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME');
  var folder = data && data.folder;

  self.commandRouter.closeModals();

  if (!self.isValidThemeFolderName(folder)) {
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_INVALID'));
    defer.resolve();
    return defer.promise;
  }

  // Reload configs so base paths and active folder are current
  try {
    if (fs.existsSync(PeppyConf)) {
      peppy_config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
      base_folder_P = peppy_config.current['base.folder'] + '/';
      if (base_folder_P === '/') {
        base_folder_P = PeppyPath + '/';
      }
    }
    if (fs.existsSync(SpectrumConf)) {
      spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
      base_folder_S = spectrum_config.current['base.folder'] + '/';
      if (base_folder_S === '/') {
        base_folder_S = SpectrumPath + '/';
      }
    }
  } catch (e) {
    self.logger.error(id + 'removeThemeFolderConfirmed: failed to reload config: ' + e.message);
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_INVALID'));
    defer.resolve();
    return defer.promise;
  }

  if (!fs.existsSync(base_folder_P + folder)) {
    self.commandRouter.pushToastMessage('error', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_INVALID'));
    defer.resolve();
    return defer.promise;
  }

  // Enumerate remaining meter theme folders to guard the last-skin case
  var allFolders = [];
  try {
    fs.readdirSync(base_folder_P).forEach(function (f) {
      if (f.indexOf('_') !== -1 && fs.statSync(base_folder_P + f).isDirectory()) {
        allFolders.push(f);
      }
    });
  } catch (e) {
    self.logger.error(id + 'removeThemeFolderConfirmed: enumerate failed: ' + e.message);
  }
  var remaining = allFolders.filter(function (f) { return f !== folder; });
  if (remaining.length === 0) {
    self.commandRouter.pushToastMessage('warning', pluginName, self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_LAST'));
    defer.resolve();
    return defer.promise;
  }

  // If removing the active theme, switch to another one first so configs stay valid
  var wasActive = (peppy_config.current[meterFolderStr] === folder);
  var switchedTo = null;
  if (wasActive) {
    switchedTo = remaining[0];
    self.applyActiveThemeFolder(switchedTo);
  }

  // Delete from both trees (meters + spectrum); spectrum twin is optional
  self.removeThemeTreeFolder(base_folder_P, folder);
  self.removeThemeTreeFolder(base_folder_S, folder);

  // Drop the cached gallery preview for the removed folder, if present
  try {
    if (fs.existsSync(ThemeGalleryDir)) {
      fs.readdirSync(ThemeGalleryDir).forEach(function (f) {
        var cacheExt = path.extname(f).toLowerCase();
        var cacheBase = cacheExt ? f.slice(0, -cacheExt.length) : f;
        if (f === folder + '.select.html' || (cacheBase === folder && THEME_GALLERY_CACHE_EXTS.indexOf(cacheExt) !== -1)) {
          fs.removeSync(ThemeGalleryDir + '/' + f);
        }
      });
    }
  } catch (e) {
    galleryLog(self.logger, 'verbose', 'removeThemeFolderConfirmed: cache cleanup failed: ' + e.message);
  }

  galleryLog(self.logger, 'basic', 'removeThemeFolderConfirmed removed ' + folder + (wasActive ? ' (was active -> ' + switchedTo + ')' : ''));

  if (wasActive) {
    self.commandRouter.pushToastMessage('success', pluginName,
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_ACTIVE_RESET') + ' ' + switchedTo);
  } else {
    self.commandRouter.pushToastMessage('success', pluginName,
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_REMOVE_DONE') + ' ' + folder);
  }

  uiNeedsUpdate = true;
  self.updateUIConfig();

  defer.resolve();
  return defer.promise;
};

peppyScreensaver.prototype.showThemeGallery = function () {
  var self = this;
  var defer = libQ.defer();

  if (!fs.existsSync(PeppyConf)) {
    self.commandRouter.pushToastMessage(
      'error',
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NO_PEPPYCONFIG')
    );
    defer.resolve();
    return defer.promise;
  }

  try {
    peppy_config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
    base_folder_P = peppy_config.current['base.folder'] + '/';
    if (base_folder_P === '/') {
      base_folder_P = PeppyPath + '/';
    }
  } catch (e) {
    self.logger.error(id + 'showThemeGallery: failed to reload config: ' + e.message);
    defer.resolve();
    return defer.promise;
  }

  var activeFolder = peppy_config.current[meterFolderStr];
  galleryLog(self.logger, 'basic', 'showThemeGallery called, activeFolder=' + activeFolder + ', base=' + base_folder_P);
  var themes = self.collectThemeGalleryEntries();
  galleryLog(self.logger, 'basic', 'showThemeGallery collected ' + themes.length + ' theme(s)');
  themes.forEach(function (theme) {
    galleryLog(self.logger, 'trace', '  theme ' + theme.folder + ' preview=' + theme.previewSource + (theme.previewSection ? ' [' + theme.previewSection + ']' : ''));
  });
  var html = self.buildThemeGalleryHtml(themes, activeFolder);
  if (!html) {
    galleryLog(self.logger, 'basic', 'showThemeGallery: no themes with preview assets');
    self.commandRouter.pushToastMessage(
      'info',
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
      self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_GALLERY_NONE')
    );
    defer.resolve();
    return defer.promise;
  }

  self.commandRouter.broadcastMessage('openModal', {
    title: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.THEME_GALLERY_TITLE'),
    message: html,
    size: 'lg',
    buttons: self.buildThemeGalleryButtons()
  });

  defer.resolve();
  return defer.promise;
};

// global functions
//-------------------------------------------------------------
// Clamp `value` to [attrib[0], attrib[1]] (placeholder attrib[2] on invalid input).
// isFloat=true preserves fractional values (e.g. transition.duration, rotation.speed);
// otherwise the value is coerced to an integer. Note: parseInt truncates floats, so
// float fields MUST pass isFloat=true or values like 0.5 silently become 0.
peppyScreensaver.prototype.minmax = function (item, value, attrib, isFloat) {
  var self = this;
  var num = isFloat ? parseFloat(value) : parseInt(value, 10);
  if (Number.isNaN(num) || !isFinite(value)) {
      uiNeedsUpdate = true;
      return attrib[2];
  }
    if (num < attrib[0]) {
        setTimeout(function () {
            self.commandRouter.pushToastMessage("info", self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.' + item.toUpperCase()) + ': ' + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.INFO_MIN'));
        }, 700);        
        uiNeedsUpdate = true;
        return attrib[0];
    }
    if (num > attrib[1]) {
        setTimeout(function () {
            self.commandRouter.pushToastMessage("info", self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.' + item.toUpperCase()) + ': ' + self.commandRouter.getI18nString('PEPPY_SCREENSAVER.INFO_MAX'));
        }, 700); 
        uiNeedsUpdate = true;
        return attrib[1];
    }
    return num;
};

peppyScreensaver.prototype.updateUIConfig = function () {
  const self = this;
  const defer = libQ.defer();

  self.commandRouter.getUIConfigOnPlugin('user_interface', 'peppy_screensaver', {})
    .then(function (uiconf) {
      self.commandRouter.broadcastMessage('pushUiConfig', uiconf);
    });
  self.commandRouter.broadcastMessage('pushUiConfig');
  uiNeedsUpdate = false;
  return defer.promise;
};

// Normalize template folder permissions for SMB share access
// When enabled: dirs 777, files 666 (writable by SMB nobody:nogroup)
// When disabled: dirs 755, files 644 (standard permissions)
peppyScreensaver.prototype.normalizeTemplatePermissions = function (enable) {
  var self = this;
  var defer = libQ.defer();
  var templateDirs = [
      DATA_DIR + '/templates',
      DATA_DIR + '/templates_spectrum'
  ];
  
  var dirMode = enable ? '777' : '755';
  var fileMode = enable ? '666' : '644';
  var processed = 0;
  var total = templateDirs.length;
  
  templateDirs.forEach(function(dir) {
      if (fs.existsSync(dir)) {
          // chmod directories first, then files
          // chown to volumio:volumio first (reclaims SMB nobody:nogroup files),
          // then chmod dirs, then fix file permissions
          var cmd = '/usr/bin/sudo /bin/chown -R volumio:volumio ' + dir + ' && /usr/bin/sudo /bin/chmod -R ' + dirMode + ' ' + dir + ' && /usr/bin/sudo /usr/bin/find ' + dir + ' -type f -exec /bin/chmod ' + fileMode + ' {} +';
          exec(cmd, function(error, stdout, stderr) {
              if (error) {
                  self.logger.error(id + 'normalizeTemplatePermissions: error on ' + dir + ': ' + error);
              } else {
                  self.logger.info(id + 'normalizeTemplatePermissions: ' + dir + ' set to dirs=' + dirMode + ' files=' + fileMode);
              }
              processed++;
              if (processed >= total) { defer.resolve(); }
          });
      } else {
          processed++;
          if (processed >= total) { defer.resolve(); }
      }
  });
  
  if (total === 0) { defer.resolve(); }
  return defer.promise;
};

peppyScreensaver.prototype.checkDSPactive = function (DSD){
  const self = this;
  const defer = libQ.defer();
  let DSPMessage = "";
  let DSPMessageTitle = "";
  let DSPactive = self.getPluginStatus ('audio_interface', 'fusiondsp') === 'STARTED';
	    
    if(DSD && DSPactive){	
        DSPMessageTitle = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.DSPWARNING_TITLE');
        DSPMessage = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.DSPWARNING');
    }
    if(!DSD && !DSPactive){
        DSPMessageTitle = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NODSPWARNING_TITLE');
        DSPMessage = self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NODSPWARNING');
    }
    if (DSPMessage != ""){
        setTimeout(function () {
            self.commandRouter.pushToastMessage('warning', DSPMessageTitle, DSPMessage);
        }, 1500);
    }

  return defer.promise;
};


peppyScreensaver.prototype.checkMetersFile = function (){
    const self = this;
    const defer = libQ.defer();
    var meters_file = base_folder_P + peppy_config.current[meterFolderStr] + '/meters.txt';
  
    if (!fs.existsSync(meters_file)){
        setTimeout(function () {
            self.commandRouter.pushToastMessage('warning', self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NOMETERSWARNING_TITLE'), self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NOMETERSWARNING'));
        }, 1500);
    }

    return defer.promise;
};

peppyScreensaver.prototype.checkListMode = function (listStr){
    const self = this;
	
	var meters_file = base_folder_P + peppy_config.current[meterFolderStr] + '/meters.txt';
	var meterSectArray = [];
    var listError = [];
	var listArray = (listStr).split(',');
	var not_found = false;
	
	if (fs.existsSync(meters_file)){
	    var metersconfig = ini.parse(fs.readFileSync(meters_file, 'utf-8'));
		
		// get sections from file	
		for (var section in metersconfig) {
			meterSectArray.push(section);
		}
		// check if list entry in section
		for (var i in listArray) {
			if (!meterSectArray.includes(listArray[i].trim())) {
                listError.push(listArray[i]);
                not_found = true;
            }
		}
	
	} else {
		not_found = true;
	}
  
    if (not_found){
        setTimeout(function () {
        // create a hint as modal
        var responseData = {
        title: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NOTINLIST_TITLE'),
        message: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.NOTINLIST') + listError,
        size: 'lg',
        buttons: [
            {
            name: self.commandRouter.getI18nString('COMMON.GOT_IT'),
            class: 'btn btn-info ng-scope',
            emit: '',
            payload: ''
            }
        ]
        };
        self.commandRouter.broadcastMessage('openModal', responseData);
        }, 1000);
		return false;
    }

    return true;
};


peppyScreensaver.prototype.install_dummy = function () {
  const self = this;
  let defer = libQ.defer();
  
  // Detect architecture
  var arch = '';
  try { arch = execSync('cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'').toString().trim(); } catch(e) {}
  var isX64 = (arch === 'x64');
  
  try {
    execSync("/usr/bin/sudo /sbin/modprobe snd-dummy index=7 pcm_substreams=1 fake_buffer=0", { uid: 1000, gid: 1000 });
    self.commandRouter.pushConsoleMessage('snd-dummy loaded');
    
    // x64: also load snd-aloop for Spotify meter path (Loopback has flexible buffer params)
    if (isX64) {
      try {
        execSync("/usr/bin/sudo /sbin/modprobe snd-aloop index=6 pcm_substreams=2", { uid: 1000, gid: 1000 });
        self.commandRouter.pushConsoleMessage('snd-aloop loaded for x64 Spotify');
      } catch (err) {
        self.logger.info('failed to load snd-aloop: ' + err);
      }
    }
    
    defer.resolve();
  } catch (err) {
    self.logger.info('failed to load snd-dummy' + err);
  }
};

peppyScreensaver.prototype.install_mkfifo = function (fifoName) {
  const self = this;
  let defer = libQ.defer();
  
  try {
    exec('/usr/bin/mkfifo -m 646 ' + fifoName, { uid: 1000, gid: 1000 });
    self.commandRouter.pushConsoleMessage(fifoName + ' created');
    defer.resolve();
  } catch (err) {
    self.logger.info('failed to create ' + fifoName + ' ' + err);
  }    
};

// peppyalsa opens these write-only. No reader → ENXIO at snd_pcm_open of any
// metered PCM, including before the screensaver (the real reader) appears.
// Hold RDWR and never read: the kernel sees a reader, the Python meter still
// gets every byte. Do not depend on install_mkfifo (async exec).
peppyScreensaver.prototype.holdMeterFifos = function () {
  var self = this;
  self.releaseMeterFifos();
  self._meterFifoFds = [];
  ['/tmp/myfifo', '/tmp/myfifosa'].forEach(function (fifoName) {
    try {
      if (!fs.existsSync(fifoName)) {
        execSync('/usr/bin/mkfifo -m 646 ' + fifoName, { uid: 1000, gid: 1000 });
      }
      var fd = fs.openSync(fifoName, fs.constants.O_RDWR | fs.constants.O_NONBLOCK);
      self._meterFifoFds.push(fd);
    } catch (err) {
      self.logger.info(id + 'cannot hold ' + fifoName + ': ' + err);
    }
  });
};

peppyScreensaver.prototype.releaseMeterFifos = function () {
  var fds = this._meterFifoFds;
  this._meterFifoFds = [];
  if (!fds) return;
  fds.forEach(function (fd) {
    try { fs.closeSync(fd); } catch (e) { /* already closed */ }
  });
};

// switch alsa config
peppyScreensaver.prototype.switch_alsaConfig = function (alsaConf) {
    const self = this;
    var defer = libQ.defer();
    // x64: ALWAYS enable MPD output - it's the only source for meter data
    var arch_cmd = 'cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'';
    var arch = '';
    try { arch = execSync(arch_cmd).toString().trim(); } catch(e) {}
    var isX64 = (arch === 'x64');
    // MPD output for meter: enable on x64 (always) or Pi DSD mode
    // Disable for Pi modular ALSA - uses inline meter instead
    var enableDSD = alsaConf == 1 ? true : false;
    var enableMPDOutput = isX64 ? true : enableDSD;
    alsaLog(self.logger, 'basic', 'switch_alsaConfig: alsaConf=' + alsaConf + ' isX64=' + isX64 + ' enableMPDOutput=' + enableMPDOutput);
    
    self.MPD_setOutput(MPD_include, enableMPDOutput)
//        .then(self.MPD_allowedFormats.bind(self, MPD, enableDSD)) // not more needed
        .then(self.writeAsoundConfigModular.bind(self, alsaConf))
        .then(self.updateALSAConfigFile.bind(self))
//        .then(self.updateMountpoint.bind(self, MPD, MPDtmpl))     // not more needed with MPD_include
//        .then(self.recreate_mpdconf.bind(self))                   // not more needed with MPD_include
        .then(self.restartMpd.bind(self))
        .then(function() {
            // Set MPD output state via mpc after restart (config file alone doesn't control live state)
            var mpcCmd = enableMPDOutput ? 'mpc enable 1' : 'mpc disable 1';
            setTimeout(function() {
                exec(mpcCmd, { uid: 1000, gid: 1000 }, function(error, stdout, stderr) {
                    if (error) {
                        self.logger.warn('peppy_screensaver: Failed to set MPD output: ' + error);
                    } else {
                        self.logger.info('peppy_screensaver: MPD output 1 ' + (enableMPDOutput ? 'enabled' : 'disabled'));
                    }
                });
            }, 1000); // Wait for MPD to fully restart
        });
    defer.resolve();
    return defer.promise;    
};

// switch display port
peppyScreensaver.prototype.switch_DisplayPort = function (DispOut) {
    const self = this;
    var defer = libQ.defer();
    
    if (fs.existsSync(RunPeppyFile)){
        var runPeppydata = fs.readFileSync(RunPeppyFile, 'utf8');
        if (DispOut == "0") {
            runPeppydata = runPeppydata.replace('DISPLAY=:1', 'DISPLAY=:' + DispOut);
        } else {
            runPeppydata = runPeppydata.replace('DISPLAY=:0', 'DISPLAY=:' + DispOut);
        }

        fs.writeFile(RunPeppyFile, runPeppydata, 'utf8', function (err) {
            if (err) {
                self.logger.info('Cannot write ' + RunPeppyFile + err);
                defer.resolve(); // resolve anyway to not block chain
            } else {               
                defer.resolve();
            }
        });
    } else {
        defer.resolve();
    }

    return defer.promise;
};

// enable spotify alsa pipe
peppyScreensaver.prototype.switch_Spotify = function (useSpotify) {
    const self = this;
    var defer = libQ.defer();
    //var useDSP = fs.existsSync(dsp_config) && self.config.get('useDSP');

    // only if spotify installed
    if (fs.existsSync(spotify_config)){
        var spotifydata = fs.readFileSync(spotify_config, 'utf8'); 
        if (useSpotify) {
            spotifydata = spotifydata.replace('volumio', 'spotify');
        } else {
            spotifydata = spotifydata.replace('spotify', 'volumio');
        }

        fs.writeFile(spotify_config, spotifydata, 'utf8', function (err) {
            if (err) {
                self.logger.info('Cannot write ' + spotify_config + err);
                defer.resolve(); // resolve anyway to not block chain
            } else {              
                var cmdret = self.commandRouter.executeOnPlugin('music_service', 'spop', 'initializeLibrespotDaemon', '');
                defer.resolve();
            }
        });
    } else {
        defer.resolve();
    }

    return defer.promise;    
};

// switch airplay
peppyScreensaver.prototype.switch_Airplay = function (useAirplay) {
    const self = this;
    var defer = libQ.defer();

    if (fs.existsSync(AIRtmpl)){
        if (useAirplay) {
			if (!fs.existsSync(AIR)){
				fs.copySync(AIRtmpl, AIR); // copy orignal file
				var airplaydata = fs.readFileSync(AIR, 'utf8'); 
				airplaydata = airplaydata.replace('${device}', 'airplay');
				fs.writeFileSync(AIR, airplaydata);
			}
			// mount template
			self.mount_tmpl(AIR, AIRtmpl);
			
        } else {
			if (fs.existsSync(AIR)){
				//unmount air_tmpl file, if mounted
				self.unmount_tmpl(AIRtmpl)
					.then(function() {fs.removeSync(AIR);});
			}
        }
        
        // restart airplay, if running
        if (self.getPluginStatus ('music_service', 'airplay_emulation') === 'STARTED'){
            var cmdret = self.commandRouter.executeOnPlugin('music_service', 'airplay_emulation', 'startShairportSync', '');
        }
		defer.resolve();
    } else {
        defer.resolve();
    }

    return defer.promise;
};
    
// callback if mixer or outputdevice changed
// update of asound template
peppyScreensaver.prototype.switch_alsaModular = function () {
    const self = this;

    setTimeout(function () {
        var outputdevice = self.getAlsaConfigParam('outputdevice');
        var softmixer = self.getAlsaConfigParam('softvolume');
        // only if outputdevice or mixer changed
        if (last_outputdevice !== outputdevice || last_softmixer !== softmixer) {
            alsaLog(self.logger, 'basic', 'switch_alsaModular: outputdevice changed ' + last_outputdevice + ' -> ' + outputdevice + ' or softmixer changed ' + last_softmixer + ' -> ' + softmixer);
            var alsaConf = parseInt(self.config.get('alsaSelection'),10);
            if (alsaConf == 0) { // and only for modular alsa      
                self.writeAsoundConfigModular(alsaConf).then(self.updateALSAConfigFile.bind(self));
            }                
        }
        last_outputdevice = outputdevice;
        last_softmixer = softmixer;
    }, 500 );
};

// check, if Pygame 2 with SDL2 installed)
peppyScreensaver.prototype.get_SDL2_enabled = function (data) {
    const self = this;
    var defer = libQ.defer();
  
    // Get architecture and set PYTHONPATH for plugin-local packages
    var arch_cmd = 'cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'';
    var arch = execSync(arch_cmd).toString().trim();
    var pythonpath = '/data/plugins/user_interface/peppy_screensaver/lib/' + arch + '/python';
    var python_str = 'PYTHONPATH=' + pythonpath + ' python3 -c "import pygame; print(pygame.version.ver)"';

    exec(python_str, { uid: 1000, gid: 1000 }, function (error, stdout, stderr) {
    if (error) {
        self.logger.warn(id + 'An error occurred on pygame check', error);
        defer.resolve(false);
    } else {
        // Check for pygame 2.x anywhere in output (welcome message precedes version)
        if (stdout.includes('pygame 2.') || stdout.match(/^2\./m)) {
            defer.resolve(true);
        } else {
            defer.resolve(false);
        }            
    }
  });
    return defer.promise;
};

// check if installed memory smaller then 4GB)
peppyScreensaver.prototype.get_lt_4gb = function (data) {
    const self = this;
    var defer = libQ.defer();
  
    var get_str = "free -m | grep Mem: | awk '{print $2}'"   

    exec(get_str, { uid: 1000, gid: 1000 }, function (error, stdout, stderr) {
    if (error) {
        self.logger.warn(id + 'An error occurred on get memory', error);
    } else {
        if (parseInt(stdout, 10) < 3000) {
            defer.resolve(true);
            return true;
        } else {
            defer.resolve(false);
            return false;
        }            
    }
  });
    return defer.promise;
};
                         
// check, if MPD output enabled
peppyScreensaver.prototype.get_output_enabled = function (data) {
    const self = this;
    var defer = libQ.defer();
    var found = false;
    var count = 0;
       
    lineReader.eachLine(data, function(line) {
  
        if (line.includes('---> output peppymeter')) {
            found = true;
        }
        if (found) {count += 1;}

        if (count === 3) {
            if (line.includes('no')) {
                defer.resolve (false);
                return false
            } else {
                defer.resolve (true);
                return true
            }
        }           
    })
    return defer.promise;
};

// enable the MPD output for peppymeter 
peppyScreensaver.prototype.MPD_setOutput = function (data, enableDSD) {
  const self = this;
  let defer = libQ.defer();
  var sedStr = enableDSD ? "sed -i '/---> output peppymeter/,+2{/---> output peppymeter/,+1{b};s/no/yes/}' " : "sed -i '/---> output peppymeter/,+2{/---> output peppymeter/,+1{b};s/yes/no/}' ";

  exec(sedStr +  data, { uid: 1000, gid: 1000 }, function (error, stdout, stderr) {
    if (error) {
        self.logger.warn(id + 'An error occurred when change MPD output', error);
    } else {
        setTimeout(function () {defer.resolve();}, 100);
    }
  });

  return defer.promise;
};


// inject additional include file to mpd.conf.tmpl
peppyScreensaver.prototype.add_mpd_include = function (data) {
  const self = this;
  let defer = libQ.defer();

    var MPDdata = fs.readFileSync(data, 'utf8'); 
    if (!MPDdata.includes('include_optional')){
            
        exec("sed -i '/# Files and directories/a include_optional    \x22\/data\/configuration\/music_service\/mpd\/mpd_custom.conf\x22' " + data, { uid: 1000, gid: 1000 }, function (error, stdout, stderr    ) {
            if (error) {
                self.logger.warn(id + 'An error occurred when add MPD include entry', error);
            } else {
                setTimeout(function () {defer.resolve();}, 100);
            }       
        });
    } else {
        defer.resolve();
    }
                
  return defer.promise;
};

peppyScreensaver.prototype.rebootMessage = function () {
  var self = this;
  var responseData = {
    title: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.MPD_CHANGED'),
    message: self.commandRouter.getI18nString('PEPPY_SCREENSAVER.MPD_CHANGED_REBOOT'),
    size: 'lg',
    buttons: [
        {
          name: self.commandRouter.getI18nString('COMMON.RESTART'),
          class: 'btn btn-info',
          emit: 'reboot',
          payload: ''
        },
      {
        name: self.commandRouter.getI18nString('COMMON.CONTINUE'),
        class: 'btn btn-info',
        emit: 'closeModals',
        payload: ''
      }
    ]
  };

  self.commandRouter.broadcastMessage('openModal', responseData);
};

//mount a copy of changed file over 
peppyScreensaver.prototype.mount_tmpl = function (data_source, data_dest) {
  var self = this;
  var defer = libQ.defer();
  
  exec('/bin/df ' + data_dest + ' | /bin/grep ' + data_dest + ' && /bin/echo || /bin/echo volumio | /usr/bin/sudo -S /bin/mount --bind ' + data_source + ' ' + data_dest, function (error, stdout, stderr) {        
    if (error) {
        self.logger.error(id + 'Error mount ' + data_source + ' ' + error);
    } else {
        defer.resolve();
    }    
  });        
  
  return defer.promise;
};

//unmount a copy of changed file
peppyScreensaver.prototype.unmount_tmpl = function (data_dest) {
  var self = this;
  var defer = libQ.defer();

  exec('/bin/df ' + data_dest + ' | /bin/grep ' + data_dest + ' && /bin/echo volumio | /usr/bin/sudo -S /bin/umount ' + data_dest, { uid: 1000, gid: 1000 }, function (error, stdout, stderr) {        
    if (error) {
        self.logger.error(id + 'Error unmount ' + data_dest + ' ' + error);
        defer.resolve(); // resolve anyway to not block chain
    } else {
        defer.resolve();
    }    
  });        
  
  return defer.promise;
};

// restart MPD-deamon
peppyScreensaver.prototype.restartMpd = function () {
  var self = this;
  var defer = libQ.defer();

  setTimeout(function () {
    self.commandRouter.executeOnPlugin('music_service', 'mpd', 'restartMpd', '');
    defer.resolve();
  }, 500);

  return defer.promise;
};

// copy MPD_include file
peppyScreensaver.prototype.copy_MPD_include = function (data, data_dest) {
  var self = this;
  var defer = libQ.defer();
  
  try {

    fs.copySync(data, data_dest);
  
    exec('/bin/chmod 777 ' + data_dest, function (error, stdout, stderr) {        
        if (error) {
            self.logger.error(id + 'Error chmod ' + data_dest + ' ' + error);
        } else {
            defer.resolve();
        }    
    });        

  } catch (err) {
    defer.resolve();
  }
  
  return defer.promise;
};

// recreate active /etc/mpd.conf
peppyScreensaver.prototype.recreate_mpdconf = function () {
  const self = this;
  let defer = libQ.defer();
  
  self.commandRouter.executeOnPlugin('music_service', 'mpd', 'createMPDFile', function(error) {
    if (error) {
        self.logger.error(id + 'Cannot create /etc/mpd.conf ' + error);
    } else {
        defer.resolve();
    }
  });
  return defer.promise;
};

// write asound.conf from template and remove variables
peppyScreensaver.prototype.writeAsoundConfigModular = function (alsaConf) {
  var self = this;
  
  // Detect architecture and select appropriate template
  var arch_cmd = 'cat /etc/os-release | grep ^VOLUMIO_ARCH | tr -d \'VOLUMIO_ARCH="\'';
  var arch = '';
  try { arch = execSync(arch_cmd).toString().trim(); } catch(e) {}
  var isX64 = (arch === 'x64');
  
  // Use x64-specific template on x64 systems, but keep output filename same
  var tmplFile = isX64 ? '/Peppyalsa.postPeppyalsa.5.x64.conf' : asound;
  var asoundTmpl = __dirname + tmplFile + '.tmpl';
  var asoundConf = __dirname + '/asound' + asound;  // Output always uses standard name
  self.logger.info(id + 'ALSA template: ' + asoundTmpl + ' (isX64=' + isX64 + ')');
  var conf;
  var defer = libQ.defer();
  var useDSP = fs.existsSync(dsp_config) && self.config.get('useDSP');
  var plugType = self.config.get('useUSBDAC') ? 'copy' : 'empty';
  var useSpot = self.config.get('useSpotify');
  alsaLog(self.logger, 'verbose', 'writeAsoundConfigModular: alsaConf=' + alsaConf + ' useDSP=' + useDSP + ' isX64=' + isX64 + ' plugType=' + plugType + ' useSpot=' + useSpot);
  alsaLog(self.logger, 'verbose', 'writeAsoundConfigModular: template=' + asoundTmpl + ' output=' + asoundConf);

  if (fs.existsSync(asoundTmpl)) {
    var asounddata = fs.readFileSync(asoundTmpl, 'utf8');
    var peppyalsaMode;
    
    if (alsaConf == 1) { // DSD native
        if (!useDSP) {
            conf = asounddata.replace('${alsaDirect}', 'Peppyalsa');
            peppyalsaMode = 'DSD-passthrough';
        } else {
            peppyalsaMode = 'DSD-with-bridge (no Peppyalsa assignment)';
        }

    } else {  // modular alsa
        if (useDSP) {
            // Fusion bridge on: inline meter (no multi, no dummy, no rate constraint)
            conf = asounddata.replace('${alsaInlineMeter}', 'Peppyalsa');
            peppyalsaMode = 'inline-meter (bridge on)';
        } else {
            // Use inline meter to capture ALL audio sources (MPD, DAB/FM, airplay, etc.)
            conf = asounddata.replace('${alsaMeter}', 'Peppyalsa');
            peppyalsaMode = 'multi-duplicate (bridge off)';
        }
    }
    alsaLog(self.logger, 'basic', 'Peppyalsa mode: ' + peppyalsaMode);

    conf = conf.replace('${alsaInlineMeter}', 'peppy3_off');
    conf = conf.replace('${alsaMeter}', 'peppy1_off');
    conf = conf.replace('${alsaDirect}', 'peppy2_off');
    conf = conf.replace('${type}', plugType);

    //for spotify / Soloist — exclusive. Conflict leaves pcm.spotify empty.
    var connectProvider = self.connectProvider();
    if (!useDSP) {
        if (connectProvider === 'spop' && useSpot){
            conf = conf.replace('${spotMeter}', 'spotify');
        } else if (connectProvider === 'soloist' && self.config.get('useSoloist') === true && alsaConf == 1) {
            conf = conf.replace('${spotMeter}', 'spotify');
        } else {
            conf = conf.replace('${spotDirect}', 'spotify');
        }
    }
    conf = conf.replace('${spotMeter}', 'spotify2_off');
    conf = conf.replace('${spotDirect}', 'spotify1_off');
        
    // change alsa config depend on outputdevice and mixer
    // no reformat possible for softmixer
    // for internal cards (hdmi, headphone) 44100 kHz
    // for external sound cards 16000 kHz (the only rate without error)
    // removed since 3.569
    //var outputdevice = self.getAlsaConfigParam('outputdevice');
    //var softmixer = self.getAlsaConfigParam('softvolume');
        
    //if (outputdevice == 'softvolume') {
    //    outputdevice = self.getAlsaConfigParam ('softvolumenumber');
    //}

//    var slave_b = softmixer ? 'mpd_peppyalsa' : 'reformat'; 
//    conf = conf.replace('${slave_b}', slave_b);            
//    var rate = parseInt(outputdevice,10) > 1 ? 16000 : 44100;
//    conf = conf.replace('${rate}', rate);    
        
    alsaLog(self.logger, 'trace', 'writeAsoundConfigModular: generated config:\n' + conf);
    fs.writeFile(asoundConf, conf, 'utf8', function (err) {
        if (err) {
            self.logger.info('Cannot write ' + asoundConf + ': ' + err);
            defer.resolve(); // resolve anyway to not block chain
        } else {
            alsaLog(self.logger, 'basic', 'config written: ' + asoundConf);
            if (self.connectProvider() === 'spop'){
                var cmdret = self.commandRouter.executeOnPlugin('music_service', 'spop', 'initializeLibrespotDaemon', '');            
            }
            defer.resolve();
        }
    });
  }

return defer.promise;  
};



peppyScreensaver.prototype.getAlsaConfigParam = function (data) {
	var self = this;
	return self.commandRouter.executeOnPlugin('audio_interface', 'alsa_controller', 'getConfigParam', data);
};

peppyScreensaver.prototype.disableSoftMixer = function (data) {
	var self = this;
	return self.commandRouter.executeOnPlugin('audio_interface', 'alsa_controller', 'disableSoftMixer', data);
};

peppyScreensaver.prototype.writeSoftMixerFile = function (data) {
	var self = this;
	return self.commandRouter.executeOnPlugin('audio_interface', 'alsa_controller', 'writeSoftMixerFile', data);
};

peppyScreensaver.prototype.updateALSAConfigFile = function () {
	var self = this;
    var defer = libQ.defer();
    var done = false;
    var finish = function () {
        if (done) return;
        done = true;
        self.notifySoloistMetering();
        defer.resolve();
    };
    var ret;
    try {
        ret = self.commandRouter.executeOnPlugin('audio_interface', 'alsa_controller', 'updateALSAConfigFile');
    } catch (e) {
        self.logger.error(id + 'updateALSAConfigFile: ' + e);
        finish();
        return defer.promise;
    }
    if (ret && typeof ret.then === 'function') {
        ret.then(finish).fail(finish);
    } else {
        finish();
    }
    return defer.promise;
};
    
//--------------------------------------------------------------

// called from commandrouter to find the language file
peppyScreensaver.prototype.getI18nFile = function (langCode) {
  const i18nFiles = fs.readdirSync(path.join(__dirname, 'i18n'));
  const langFile = 'strings_' + langCode + '.json';

  // check for i18n file fitting the system language
  if (i18nFiles.some(function (i18nFile) { return i18nFile === langFile; })) {
    return path.join(__dirname, 'i18n', langFile);
  }
  // return default i18n file
  return path.join(__dirname, 'i18n', 'strings_en.json');
};

peppyScreensaver.prototype.getConfigParam = function (key) {
  var self = this;
  return self.config.get(key);
};

peppyScreensaver.prototype.setConfigParam = function (data) {
  var self = this;
  self.config.set(data.key, data.value);
};

peppyScreensaver.prototype.getPluginStatus = function (category, name) {
  var self = this;
  
  var PlugInConfig = new (require('v-conf'))();
  PlugInConfig.loadFile(PluginConfiguration);
  var retStr = PlugInConfig.get(category + '.' + name + '.status');
  retStr = typeof retStr === 'undefined' ? 'null' : retStr;
  return retStr;  
};

// Operator enables Soloist or stock Spotify Connect, not both.
peppyScreensaver.prototype.connectProvider = function () {
  var soloist = fs.existsSync(soloist_index) && this.getPluginStatus('music_service', 'soloist_connect') === 'STARTED';
  var spop = fs.existsSync(spotify_config) && this.getPluginStatus('music_service', 'spop') === 'STARTED';
  if (soloist && spop) return 'conflict';
  if (soloist) return 'soloist';
  if (spop) return 'spop';
  return 'none';
};

peppyScreensaver.prototype.soloistMeteringWanted = function () {
  var useDSP = fs.existsSync(dsp_config) && this.config.get('useDSP');
  var dsd = parseInt(this.config.get('alsaSelection'), 10) === 1;
  return this.connectProvider() === 'soloist' && !useDSP && dsd && this.config.get('useSoloist') === true;
};

peppyScreensaver.prototype.notifySoloistMetering = function () {
  if (this.getPluginStatus('music_service', 'soloist_connect') !== 'STARTED') return;
  this.commandRouter.executeOnPlugin(
    'music_service',
    'soloist_connect',
    'setPeppyMetering',
    this.soloistMeteringWanted()
  );
};
//-------------------------------------------------------------

// Continuity Engine - backup and restore helper methods
// -------------------------------------------------------------

// List all valid backups under BackupsPath.
// Returns array of {name, createdMs, createdLabel, pluginVersion, path}
// sorted newest first. Entries without a valid manifest.json are skipped.
peppyScreensaver.prototype.listSettingsBackups = function () {
    var self = this;
    var results = [];
    
    try {
        if (!fs.existsSync(BackupsPath)) {
            return results;
        }
        
        var entries = fs.readdirSync(BackupsPath);
        entries.forEach(function (entry) {
            var entryPath = BackupsPath + '/' + entry;
            var manifestPath = entryPath + '/' + BackupManifestName;
            
            try {
                if (!fs.statSync(entryPath).isDirectory()) return;
                if (!fs.existsSync(manifestPath)) return;
                
                var manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
                if (!manifest || typeof manifest !== 'object') return;
                if (manifest.schema_version === undefined) return;
                
                var createdMs = 0;
                var createdLabel = '';
                if (manifest.created) {
                    var d = new Date(manifest.created);
                    createdMs = d.getTime();
                    if (!isNaN(createdMs)) {
                        var pad = function (n) { return n < 10 ? '0' + n : '' + n; };
                        createdLabel = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
                    }
                }
                
                results.push({
                    name: entry,
                    createdMs: createdMs,
                    createdLabel: createdLabel || '?',
                    pluginVersion: manifest.plugin_version || '?',
                    path: entryPath
                });
            } catch (e) {
                self.logger.warn(id + 'listSettingsBackups: skipping invalid entry ' + entry + ': ' + e.message);
            }
        });
    } catch (e) {
        self.logger.error(id + 'listSettingsBackups: ' + e.message);
    }
    
    results.sort(function (a, b) { return b.createdMs - a.createdMs; });
    return results;
};

// Create a new backup with the name typed in the UI.
// Copies config.json, peppymeter config.txt and spectrum config.txt into
// a named subdirectory of BackupsPath and writes a manifest.json.
peppyScreensaver.prototype.createSettingsBackup = function (data) {
    var self = this;
    var defer = libQ.defer();
    
    try {
        var rawName = (data && data.backupName !== undefined) ? String(data.backupName) : '';
        var backupName = rawName.trim();
        
        if (!backupName) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NAME_REQUIRED'));
            defer.resolve();
            return defer.promise;
        }
        if (!BackupNameRegex.test(backupName) || backupName.indexOf('..') !== -1) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NAME_INVALID'));
            defer.resolve();
            return defer.promise;
        }
        
        if (!fs.existsSync(BackupsPath)) {
            fs.mkdirSync(BackupsPath, { recursive: true });
        }
        
        var targetDir = BackupsPath + '/' + backupName;
        
        // Collision: reject with toast, do not overwrite
        if (fs.existsSync(targetDir)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NAME_EXISTS'));
            defer.resolve();
            return defer.promise;
        }
        
        // Disk-space guard. Skipped silently if statfsSync is unavailable
        // for any reason (older filesystems, mount quirks, etc).
        try {
            if (typeof fs.statfsSync === 'function') {
                var stats = fs.statfsSync(BackupsPath);
                var freeBytes = stats.bavail * stats.bsize;
                if (freeBytes < BackupMinFreeBytes) {
                    self.commandRouter.pushToastMessage('error',
                        self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                        self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_DISK_FULL'));
                    defer.resolve();
                    return defer.promise;
                }
            }
        } catch (e) {
            self.logger.warn(id + 'createSettingsBackup: statfsSync failed, skipping disk check: ' + e.message);
        }
        
        // Non-blocking warning for clutter. Create still proceeds.
        var existingList = self.listSettingsBackups();
        if (existingList.length >= BackupWarnCount) {
            self.commandRouter.pushToastMessage('warning',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_COUNT_WARN'));
        }
        
        // Verify source files exist before we create any destination files
        var configFile = self.commandRouter.pluginManager.getConfigurationFile(self.context, 'config.json');
        if (!fs.existsSync(configFile)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_SOURCE_MISSING') + ': config.json');
            defer.resolve();
            return defer.promise;
        }
        if (!fs.existsSync(PeppyConf)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_SOURCE_MISSING') + ': peppymeter config.txt');
            defer.resolve();
            return defer.promise;
        }
        if (!fs.existsSync(SpectrumConf)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_SOURCE_MISSING') + ': spectrum config.txt');
            defer.resolve();
            return defer.promise;
        }
        
        fs.mkdirSync(targetDir, { recursive: true });
        fs.copySync(configFile, targetDir + '/config.json');
        fs.copySync(PeppyConf, targetDir + '/' + PeppyConfBackupName);
        fs.copySync(SpectrumConf, targetDir + '/' + SpectrumConfBackupName);
        
        var manifest = {
            schema_version: BackupSchemaVersion,
            plugin_version: peppyPluginVersion,
            created: new Date().toISOString(),
            name: backupName,
            files: ['config.json', PeppyConfBackupName, SpectrumConfBackupName]
        };
        fs.writeFileSync(targetDir + '/' + BackupManifestName, JSON.stringify(manifest, null, 2));
        
        self.logger.info(id + 'createSettingsBackup: created backup "' + backupName + '"');
        self.commandRouter.pushToastMessage('success',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_CREATED'));
        
        self.updateUIConfig();
        defer.resolve();
    } catch (e) {
        self.logger.error(id + 'createSettingsBackup: ' + e.message);
        self.commandRouter.pushToastMessage('error',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_CREATE_FAILED'));
        defer.resolve();
    }
    
    return defer.promise;
};

// Restore a backup by name. Validates manifest and parses all files
// before overwriting anything, so a corrupt backup cannot damage the
// current live config.
peppyScreensaver.prototype.restoreSettingsBackup = function (data) {
    var self = this;
    var defer = libQ.defer();
    
    try {
        var backupName = '';
        if (data && data.selectedBackup) {
            backupName = (typeof data.selectedBackup === 'object') ? data.selectedBackup.value : String(data.selectedBackup);
        }
        backupName = (backupName || '').trim();
        
        if (!backupName) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NOT_SELECTED'));
            defer.resolve();
            return defer.promise;
        }
        
        // Path-traversal guard
        if (!BackupNameRegex.test(backupName) || backupName.indexOf('..') !== -1 || backupName.indexOf('/') !== -1 || backupName.indexOf('\\') !== -1) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NAME_INVALID'));
            defer.resolve();
            return defer.promise;
        }
        
        var sourceDir = BackupsPath + '/' + backupName;
        var manifestPath = sourceDir + '/' + BackupManifestName;
        
        if (!fs.existsSync(sourceDir) || !fs.existsSync(manifestPath)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NOT_FOUND'));
            defer.resolve();
            return defer.promise;
        }
        
        var manifest;
        try {
            manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
        } catch (e) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_MANIFEST_INVALID'));
            defer.resolve();
            return defer.promise;
        }
        
        if (!manifest || typeof manifest !== 'object' || manifest.schema_version === undefined) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_MANIFEST_INVALID'));
            defer.resolve();
            return defer.promise;
        }
        
        if (manifest.schema_version > BackupSchemaVersion) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_SCHEMA_UNSUPPORTED'));
            defer.resolve();
            return defer.promise;
        }
        
        var srcConfigJson = sourceDir + '/config.json';
        var srcPeppyConf = sourceDir + '/' + PeppyConfBackupName;
        var srcSpectrumConf = sourceDir + '/' + SpectrumConfBackupName;
        
        if (!fs.existsSync(srcConfigJson) || !fs.existsSync(srcPeppyConf) || !fs.existsSync(srcSpectrumConf)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_FILES_MISSING'));
            defer.resolve();
            return defer.promise;
        }
        
        // Parse everything in the backup before touching live files, so a
        // corrupt backup is detected and rejected without any damage.
        try {
            JSON.parse(fs.readFileSync(srcConfigJson, 'utf8'));
        } catch (e) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_CONFIG_CORRUPT'));
            defer.resolve();
            return defer.promise;
        }
        try {
            ini.parse(fs.readFileSync(srcPeppyConf, 'utf8'));
        } catch (e) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_PEPPYCONF_CORRUPT'));
            defer.resolve();
            return defer.promise;
        }
        try {
            ini.parse(fs.readFileSync(srcSpectrumConf, 'utf8'));
        } catch (e) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_SPECTRUMCONF_CORRUPT'));
            defer.resolve();
            return defer.promise;
        }
        
        // All checks passed: perform the restore
        var configFile = self.commandRouter.pluginManager.getConfigurationFile(self.context, 'config.json');
        
        fs.copySync(srcConfigJson, configFile);
        fs.copySync(srcPeppyConf, PeppyConf);
        fs.copySync(srcSpectrumConf, SpectrumConf);
        
        // Reload in-memory caches so subsequent saves do not stomp the restored values
        self.config.loadFile(configFile);
        peppy_config = ini.parse(fs.readFileSync(PeppyConf, 'utf-8'));
        base_folder_P = peppy_config.current['base.folder'] + '/';
        if (base_folder_P == '/') { base_folder_P = PeppyPath + '/'; }
        spectrum_config = ini.parse(fs.readFileSync(SpectrumConf, 'utf-8'));
        base_folder_S = spectrum_config.current['base.folder'] + '/';
        if (base_folder_S == '/') { base_folder_S = SpectrumPath + '/'; }
        
        // Re-apply derived state from the restored config.json. Order matters:
        // alsa config first (rebuilds asound.conf), then display port (edits
        // run_peppymeter.sh), then spotify/airplay/SMB permissions.
        var alsaconf = parseInt(self.config.get('alsaSelection'), 10);
        self.switch_alsaConfig(alsaconf);
        
        var dispOut = parseInt(self.config.get('displayOutput'), 10);
        self.switch_DisplayPort(dispOut);
        
        if (self.connectProvider() === 'spop') {
            var useSpot = self.config.get('useSpotify');
            self.switch_Spotify(useSpot);
        }
        if (fs.existsSync(AIRtmpl) && self.getPluginStatus('music_service', 'airplay_emulation') === 'STARTED') {
            var useAir = self.config.get('useAirplay');
            self.switch_Airplay(useAir);
        }
        
        var smbEnabled = self.config.get('smbShareAccess') === true;
        self.normalizeTemplatePermissions(smbEnabled);
        
        // Keep the doNotDeleteThemes .preserve flag file in sync with the
        // restored value so uninstall/install behaves as the restored
        // config.json expects.
        try {
            var doNotDelete = self.config.get('doNotDeleteThemes') === true;
            if (doNotDelete) {
                if (!fs.existsSync(DATA_DIR)) { fs.mkdirSync(DATA_DIR, { recursive: true }); }
                fs.writeFileSync(DATA_DIR + '/.preserve', '', 'utf8');
            } else {
                if (fs.existsSync(DATA_DIR + '/.preserve')) { fs.unlinkSync(DATA_DIR + '/.preserve'); }
            }
        } catch (e) {
            self.logger.warn(id + 'restoreSettingsBackup: preserve flag sync failed: ' + e.message);
        }
        
        // Update config version hash so remote clients pick up the new config
        self.updateConfigVersion();
        
        // Remove runFlag so peppymeter restarts on next trigger
        if (fs.existsSync(runFlag)) { fs.removeSync(runFlag); }
        
        self.logger.info(id + 'restoreSettingsBackup: restored backup "' + backupName + '"');
        self.commandRouter.pushToastMessage('success',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_RESTORED'));
        
        self.updateUIConfig();
        defer.resolve();
    } catch (e) {
        self.logger.error(id + 'restoreSettingsBackup: ' + e.message);
        self.commandRouter.pushToastMessage('error',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_RESTORE_FAILED'));
        defer.resolve();
    }
    
    return defer.promise;
};

// Delete a backup by name. Refuses to touch anything outside BackupsPath
// even if a traversal attempt somehow slips past the name regex.
peppyScreensaver.prototype.deleteSettingsBackup = function (data) {
    var self = this;
    var defer = libQ.defer();
    
    try {
        var backupName = '';
        if (data && data.selectedBackupDelete) {
            backupName = (typeof data.selectedBackupDelete === 'object') ? data.selectedBackupDelete.value : String(data.selectedBackupDelete);
        }
        backupName = (backupName || '').trim();
        
        if (!backupName) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NOT_SELECTED'));
            defer.resolve();
            return defer.promise;
        }
        
        if (!BackupNameRegex.test(backupName) || backupName.indexOf('..') !== -1 || backupName.indexOf('/') !== -1 || backupName.indexOf('\\') !== -1) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NAME_INVALID'));
            defer.resolve();
            return defer.promise;
        }
        
        var targetDir = BackupsPath + '/' + backupName;
        if (!fs.existsSync(targetDir)) {
            self.commandRouter.pushToastMessage('error',
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
                self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_NOT_FOUND'));
            defer.resolve();
            return defer.promise;
        }
        
        // Belt-and-braces: resolve and confirm still within BackupsPath
        var resolved = path.resolve(targetDir);
        var resolvedRoot = path.resolve(BackupsPath);
        if (resolved.indexOf(resolvedRoot + '/') !== 0 && resolved !== resolvedRoot) {
            self.logger.error(id + 'deleteSettingsBackup: refusing to delete outside backups root: ' + resolved);
            defer.resolve();
            return defer.promise;
        }
        
        fs.removeSync(targetDir);
        
        self.logger.info(id + 'deleteSettingsBackup: deleted backup "' + backupName + '"');
        self.commandRouter.pushToastMessage('success',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_DELETED'));
        
        self.updateUIConfig();
        defer.resolve();
    } catch (e) {
        self.logger.error(id + 'deleteSettingsBackup: ' + e.message);
        self.commandRouter.pushToastMessage('error',
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.PLUGIN_NAME'),
            self.commandRouter.getI18nString('PEPPY_SCREENSAVER.BACKUP_DELETE_FAILED'));
        defer.resolve();
    }
    
    return defer.promise;
};

peppyScreensaver.prototype.setUIConfig = function(data) {
	var self = this;
	//Perform your installation tasks here
};

peppyScreensaver.prototype.getConf = function(varName) {
	var self = this;
	//Perform your installation tasks here
};

peppyScreensaver.prototype.setConf = function(varName, varValue) {
	var self = this;
	//Perform your installation tasks here
};
