#!/usr/bin/env python3
"""
PeppyMeter Remote Client

Connects to a PeppyMeter server running on Volumio and displays
the meter visualization on a remote display.

This client uses the same rendering code as the Volumio plugin
(volumio_peppymeter.py, volumio_turntable.py, etc.) but receives
audio level data over the network instead of from local ALSA/pipe.

Features:
- Auto-discovery of PeppyMeter servers via UDP broadcast
- Receives audio level data over UDP
- Receives metadata via Volumio's socket.io
- Mounts templates via SMB from the server
- Fetches config.txt via HTTP from server
- Renders using full Volumio PeppyMeter code (turntable, cassette, meters)

Installation:
    curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash

Usage:
    peppy_remote                    # Auto-discover server
    peppy_remote --server hanger    # Connect to specific server
    peppy_remote --test             # Simple test display
"""

import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================
DISCOVERY_PORT = 5579
DISCOVERY_TIMEOUT = 10  # seconds to wait for discovery
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SMB_MOUNT_BASE = os.path.join(SCRIPT_DIR, "mnt")  # Local mount point (portable)
SMB_SHARE_PATH = "Internal Storage/peppy_screensaver"
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

# Default configuration
DEFAULT_CONFIG = {
    "server": {
        "host": None,           # None = auto-discover
        "level_port": 5580,
        "volumio_port": 3000,
        "discovery_port": 5579,
        "discovery_timeout": 10
    },
    "display": {
        "windowed": True,       # True = movable window with title bar
        "position": None,       # None = centered, or [x, y]
        "fullscreen": False,
        "monitor": 0
    },
    "templates": {
        "use_smb": True,
        "local_path": None      # Override path for templates
    }
}


def load_config():
    """Load configuration from file, return merged with defaults."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # Deep copy
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                user_config = json.load(f)
            # Deep merge user config into defaults
            for section in config:
                if section in user_config:
                    if isinstance(config[section], dict):
                        config[section].update(user_config[section])
                    else:
                        config[section] = user_config[section]
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config file: {e}")
    
    return config


def save_config(config):
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except IOError as e:
        print(f"Error saving config: {e}")
        return False


def run_config_wizard():
    """Interactive configuration wizard."""
    config = load_config()
    
    def clear_screen():
        os.system('clear' if os.name != 'nt' else 'cls')
    
    def show_menu():
        clear_screen()
        print("=" * 50)
        print(" PeppyMeter Remote Client Configuration")
        print("=" * 50)
        print()
        
        # Server settings
        host = config["server"]["host"] or "auto-discover"
        print("Server Settings:")
        print(f"  1. Server host:       {host}")
        print(f"  2. Level port:        {config['server']['level_port']}")
        print(f"  3. Volumio port:      {config['server']['volumio_port']}")
        print(f"  4. Discovery timeout: {config['server']['discovery_timeout']}s")
        print()
        
        # Display settings
        mode = "fullscreen" if config["display"]["fullscreen"] else ("windowed" if config["display"]["windowed"] else "frameless")
        pos = config["display"]["position"]
        pos_str = f"{pos[0]}, {pos[1]}" if pos else "centered"
        print("Display Settings:")
        print(f"  5. Window mode:       {mode}")
        print(f"  6. Position:          {pos_str}")
        print(f"  7. Monitor:           {config['display']['monitor']}")
        print()
        
        # Template settings
        smb = "yes" if config["templates"]["use_smb"] else "no"
        local = config["templates"]["local_path"] or "(none)"
        print("Template Settings:")
        print(f"  8. Use SMB mount:     {smb}")
        print(f"  9. Local path:        {local}")
        print()
        
        print("-" * 50)
        print("  S = Save and exit")
        print("  R = Run with these settings")
        print("  D = Reset to defaults")
        print("  Q = Quit without saving")
        print()
    
    def get_input(prompt, default=None):
        """Get user input with optional default."""
        if default is not None:
            result = input(f"{prompt} [{default}]: ").strip()
            return result if result else str(default)
        return input(f"{prompt}: ").strip()
    
    def config_server_host():
        print()
        print("Server host:")
        print("  1. Auto-discover (recommended)")
        print("  2. Enter hostname (e.g., volumio, hanger)")
        print("  3. Enter IP address")
        print()
        choice = input("Choice [1]: ").strip() or "1"
        
        if choice == "1":
            config["server"]["host"] = None
        elif choice == "2":
            host = input("Hostname: ").strip()
            if host:
                config["server"]["host"] = host
        elif choice == "3":
            ip = input("IP address: ").strip()
            if ip:
                config["server"]["host"] = ip
    
    def config_window_mode():
        print()
        print("Window mode:")
        print("  1. Windowed (movable, with title bar)")
        print("  2. Frameless (kiosk style, fixed position)")
        print("  3. Fullscreen")
        print()
        choice = input("Choice [1]: ").strip() or "1"
        
        if choice == "1":
            config["display"]["windowed"] = True
            config["display"]["fullscreen"] = False
        elif choice == "2":
            config["display"]["windowed"] = False
            config["display"]["fullscreen"] = False
        elif choice == "3":
            config["display"]["windowed"] = False
            config["display"]["fullscreen"] = True
    
    def config_position():
        print()
        print("Window position:")
        print("  1. Centered")
        print("  2. Top-left (0, 0)")
        print("  3. Custom coordinates")
        print()
        choice = input("Choice [1]: ").strip() or "1"
        
        if choice == "1":
            config["display"]["position"] = None
        elif choice == "2":
            config["display"]["position"] = [0, 0]
        elif choice == "3":
            try:
                x = int(input("X position: ").strip() or "0")
                y = int(input("Y position: ").strip() or "0")
                config["display"]["position"] = [x, y]
            except ValueError:
                print("Invalid input, using centered")
                config["display"]["position"] = None
    
    def config_port(key, name):
        print()
        current = config["server"][key]
        try:
            value = int(get_input(f"{name}", current))
            config["server"][key] = value
        except ValueError:
            print("Invalid port number")
    
    def config_smb():
        print()
        print("Use SMB mount for templates?")
        print("  1. Yes (mount from Volumio server)")
        print("  2. No (use local templates)")
        print()
        choice = input("Choice [1]: ").strip() or "1"
        config["templates"]["use_smb"] = (choice == "1")
        
        if choice == "2":
            path = input("Local templates path: ").strip()
            if path:
                config["templates"]["local_path"] = path
    
    # Main loop
    while True:
        show_menu()
        choice = input("Choice: ").strip().upper()
        
        if choice == "1":
            config_server_host()
        elif choice == "2":
            config_port("level_port", "Level port")
        elif choice == "3":
            config_port("volumio_port", "Volumio port")
        elif choice == "4":
            try:
                value = int(get_input("Discovery timeout (seconds)", config["server"]["discovery_timeout"]))
                config["server"]["discovery_timeout"] = value
            except ValueError:
                print("Invalid number")
        elif choice == "5":
            config_window_mode()
        elif choice == "6":
            config_position()
        elif choice == "7":
            try:
                value = int(get_input("Monitor number", config["display"]["monitor"]))
                config["display"]["monitor"] = value
            except ValueError:
                print("Invalid number")
        elif choice == "8":
            config_smb()
        elif choice == "9":
            path = input("Local templates path (empty to clear): ").strip()
            config["templates"]["local_path"] = path if path else None
        elif choice == "S":
            if save_config(config):
                print(f"\nConfiguration saved to: {CONFIG_FILE}")
            input("Press Enter to continue...")
            break
        elif choice == "R":
            save_config(config)
            print("\nStarting PeppyMeter Remote Client...")
            return config  # Return config to run with
        elif choice == "D":
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            print("\nReset to defaults")
            input("Press Enter to continue...")
        elif choice == "Q":
            print("\nExiting without saving")
            return None
        else:
            input("Invalid choice. Press Enter to continue...")
    
    return None  # Don't run after saving

# =============================================================================
# Server Discovery
# =============================================================================
class ServerDiscovery:
    """Discovers PeppyMeter servers via UDP broadcast."""
    
    def __init__(self, port=DISCOVERY_PORT, timeout=DISCOVERY_TIMEOUT):
        self.port = port
        self.timeout = timeout
        self.servers = {}  # {ip: discovery_data}
        self._stop = False
    
    def discover(self):
        """Listen for server announcements, return dict of discovered servers."""
        print(f"Discovering PeppyMeter servers on UDP port {self.port}...")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)  # 1 second timeout for each recv
        sock.bind(('', self.port))
        
        start_time = time.time()
        
        while not self._stop and (time.time() - start_time) < self.timeout:
            try:
                data, addr = sock.recvfrom(1024)
                try:
                    info = json.loads(data.decode('utf-8'))
                    if info.get('service') == 'peppy_level_server':
                        ip = addr[0]
                        if ip not in self.servers:
                            hostname = info.get('hostname', ip)
                            print(f"  Found: {hostname} ({ip})")
                            self.servers[ip] = {
                                'ip': ip,
                                'hostname': hostname,
                                'level_port': info.get('level_port', 5580),
                                'volumio_port': info.get('volumio_port', 3000),
                                'version': info.get('version', 1),
                                'config_version': info.get('config_version', '')
                            }
                        else:
                            # Update config_version if changed
                            new_version = info.get('config_version', '')
                            if new_version and new_version != self.servers[ip].get('config_version'):
                                self.servers[ip]['config_version'] = new_version
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
            except socket.timeout:
                continue
            except Exception as e:
                print(f"  Discovery error: {e}")
                break
        
        sock.close()
        return self.servers
    
    def stop(self):
        self._stop = True


# =============================================================================
# Config Fetcher (HTTP)
# =============================================================================
class ConfigFetcher:
    """
    Fetches config.txt from server via HTTP.
    
    Uses Volumio plugin API endpoint to get config without SMB symlink issues.
    The server IP address from discovery is used for robust connectivity.
    """
    
    def __init__(self, server_ip, volumio_port=3000):
        self.server_ip = server_ip
        self.volumio_port = volumio_port
        self.cached_config = None
        self.cached_version = None
    
    def fetch(self):
        """
        Fetch config from server via HTTP.
        
        Returns (success, config_content, version) tuple.
        """
        # Use direct IP address for reliable connectivity
        url = f"http://{self.server_ip}:{self.volumio_port}/api/v1/pluginEndpoint?endpoint=peppy_screensaver&method=getRemoteConfig"
        
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                
                # Volumio REST API wraps plugin response in 'data' field
                # Response format: {"success": true, "data": {"success": true, "version": "...", "config": "..."}}
                if data.get('success'):
                    inner = data.get('data', {})
                    if inner.get('success'):
                        self.cached_config = inner.get('config', '')
                        self.cached_version = inner.get('version', '')
                        return True, self.cached_config, self.cached_version
                    else:
                        error = inner.get('error', 'Unknown error')
                        print(f"  Plugin error fetching config: {error}")
                        return False, None, None
                else:
                    error = data.get('error', 'Unknown error')
                    print(f"  Server error fetching config: {error}")
                    return False, None, None
                    
        except urllib.error.HTTPError as e:
            print(f"  HTTP error fetching config: {e.code} {e.reason}")
            return False, None, None
        except urllib.error.URLError as e:
            print(f"  URL error fetching config: {e.reason}")
            return False, None, None
        except json.JSONDecodeError as e:
            print(f"  JSON error parsing config response: {e}")
            return False, None, None
        except Exception as e:
            print(f"  Error fetching config: {e}")
            return False, None, None
    
    def has_changed(self, new_version):
        """Check if config version has changed."""
        return new_version and new_version != self.cached_version


# =============================================================================
# SMB Mount Manager
# =============================================================================
class SMBMount:
    """Manages SMB mount for remote templates."""
    
    def __init__(self, hostname, mount_point=None):
        self.hostname = hostname
        self.mount_point = Path(mount_point if mount_point else SMB_MOUNT_BASE)
        self.share_path = f"//{hostname}.local/{SMB_SHARE_PATH}"
        self._mounted = False
    
    def mount(self):
        """Mount the SMB share. Returns True on success."""
        # Create mount point
        self.mount_point.mkdir(parents=True, exist_ok=True)
        
        # Check if already mounted
        if self._is_mounted():
            print(f"SMB share already mounted at {self.mount_point}")
            self._mounted = True
            return True
        
        # Try guest mount first
        print(f"Mounting {self.share_path} at {self.mount_point}...")
        
        # Try guest mount
        result = subprocess.run(
            ['sudo', 'mount', '-t', 'cifs', self.share_path, str(self.mount_point),
             '-o', 'guest,ro,nofail'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            print("  Mounted as guest")
            self._mounted = True
            return True
        
        # Try with volumio credentials
        result = subprocess.run(
            ['sudo', 'mount', '-t', 'cifs', self.share_path, str(self.mount_point),
             '-o', 'user=volumio,password=volumio,ro,nofail'],
            capture_output=True, text=True
        )
        
        if result.returncode == 0:
            print("  Mounted with volumio credentials")
            self._mounted = True
            return True
        
        print(f"  Failed to mount: {result.stderr}")
        return False
    
    def unmount(self):
        """Unmount the SMB share."""
        if self._mounted and self._is_mounted():
            subprocess.run(['sudo', 'umount', str(self.mount_point)], 
                         capture_output=True)
            self._mounted = False
    
    def _is_mounted(self):
        """Check if the mount point is currently mounted."""
        result = subprocess.run(['mountpoint', '-q', str(self.mount_point)])
        return result.returncode == 0
    
    @property
    def templates_path(self):
        """Path to templates directory."""
        return self.mount_point / 'templates'


# =============================================================================
# Level Data Receiver
# =============================================================================
class LevelReceiver:
    """Receives audio level data over UDP."""
    
    def __init__(self, server_ip, port=5580):
        self.server_ip = server_ip
        self.port = port
        self.sock = None
        self._running = False
        self._thread = None
        
        # Current level data (thread-safe via GIL for simple reads)
        self.left = 0.0
        self.right = 0.0
        self.mono = 0.0
        self.seq = 0
        self.last_update = 0
    
    def start(self):
        """Start receiving level data in background thread."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.settimeout(1.0)
        self.sock.bind(('', self.port))
        
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        print(f"Level receiver started on UDP port {self.port}")
    
    def _receive_loop(self):
        """Background thread to receive level data."""
        while self._running:
            try:
                data, addr = self.sock.recvfrom(1024)
                if len(data) == 16:  # uint32 + 3 floats
                    seq, left, right, mono = struct.unpack('<Ifff', data)
                    self.seq = seq
                    self.left = left
                    self.right = right
                    self.mono = mono
                    self.last_update = time.time()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"Level receiver error: {e}")
                break
    
    def stop(self):
        """Stop receiving."""
        self._running = False
        if self.sock:
            self.sock.close()
        if self._thread:
            self._thread.join(timeout=2.0)
    
    def get_levels(self):
        """Get current level data as tuple (left, right, mono)."""
        return (self.left, self.right, self.mono)


# =============================================================================
# Remote Data Source (for PeppyMeter integration)
# =============================================================================
class RemoteDataSource:
    """
    A DataSource implementation that gets data from the LevelReceiver.
    This mimics PeppyMeter's DataSource interface for seamless integration.
    """
    
    def __init__(self, level_receiver):
        self.level_receiver = level_receiver
        self.volume = 100  # Used by some meters
        self.data = (0.0, 0.0, 0.0)  # (left, right, mono)
    
    def start_data_source(self):
        """Start the data source (already running via LevelReceiver)."""
        pass
    
    def stop_data_source(self):
        """Stop the data source."""
        pass
    
    def get_current_data(self):
        """Return current data as tuple (left, right, mono)."""
        return (self.level_receiver.left, 
                self.level_receiver.right, 
                self.level_receiver.mono)
    
    def get_current_left_channel_data(self):
        return self.level_receiver.left
    
    def get_current_right_channel_data(self):
        return self.level_receiver.right
    
    def get_current_mono_channel_data(self):
        return self.level_receiver.mono


# =============================================================================
# Setup Remote Config
# =============================================================================
def setup_remote_config(peppymeter_path, templates_path, config_fetcher):
    """
    Set up config.txt for remote client mode.
    
    Fetches config from server via HTTP and adjusts paths for local use.
    """
    import configparser
    
    config_path = os.path.join(peppymeter_path, "config.txt")
    server_config_fetched = False
    
    # Try to fetch config from server via HTTP
    if config_fetcher:
        print("Fetching config from server via HTTP...")
        success, config_content, version = config_fetcher.fetch()
        if success and config_content:
            try:
                with open(config_path, 'w') as f:
                    f.write(config_content)
                server_config_fetched = True
                print(f"  Config fetched successfully (version: {version})")
            except Exception as e:
                print(f"  Failed to write fetched config: {e}")
    
    if not server_config_fetched:
        print("Server config not available, using defaults")
    
    # Now read and adjust the config for local use
    config = configparser.ConfigParser()
    
    if os.path.exists(config_path):
        try:
            config.read(config_path)
        except Exception:
            pass  # Start fresh if parse error
    
    # Ensure all required sections exist
    if 'current' not in config:
        config['current'] = {}
    if 'sdl.env' not in config:
        config['sdl.env'] = {}
    if 'data.source' not in config:
        config['data.source'] = {}
    
    # Update paths for local client
    config['current']['base.folder'] = templates_path
    
    # SDL settings for windowed display (not embedded framebuffer)
    # These will be read by volumio_peppymeter's init_display()
    config['sdl.env']['framebuffer.device'] = ''
    config['sdl.env']['video.driver'] = ''  # Empty for auto-detect (X11/Wayland)
    config['sdl.env']['video.display'] = os.environ.get('DISPLAY', ':0')
    config['sdl.env']['mouse.enabled'] = 'False'
    config['sdl.env']['double.buffer'] = 'True'
    config['sdl.env']['no.frame'] = 'False'  # Allow window frame on desktop
    
    # Data source configuration
    # Keep 'pipe' type - it will fail silently (no data) since /tmp/myfifo doesn't exist
    # The actual data comes from RemoteDataSource which we inject at runtime
    # Don't use 'noise' - it generates random values causing chaotic meter behavior
    # Keep smooth buffer for smoother needle movement
    config['data.source']['smooth.buffer.size'] = '4'
    
    # Write adjusted config
    with open(config_path, 'w') as f:
        config.write(f)
    
    if server_config_fetched:
        meter_folder = config['current'].get('meter.folder', 'unknown')
        print(f"  Config adjusted for local use (meter: {meter_folder})")
    
    return config_path


# =============================================================================
# Full PeppyMeter Display (using volumio_peppymeter)
# =============================================================================
def run_peppymeter_display(level_receiver, server_info, templates_path, config_fetcher):
    """Run full PeppyMeter rendering using volumio_peppymeter code."""
    
    import ctypes
    
    # Set up paths - mirrors Volumio plugin structure
    screensaver_path = os.path.join(SCRIPT_DIR, "screensaver")
    peppymeter_path = os.path.join(screensaver_path, "peppymeter")
    
    if not os.path.exists(peppymeter_path):
        print(f"ERROR: PeppyMeter not found at {peppymeter_path}")
        print("Run the installer first:")
        print("  curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash")
        return False
    
    if not os.path.exists(os.path.join(screensaver_path, "volumio_peppymeter.py")):
        print(f"ERROR: volumio_peppymeter.py not found at {screensaver_path}")
        print("Run the installer to download Volumio custom handlers.")
        return False
    
    spectrum_path = os.path.join(screensaver_path, "spectrum")
    if not os.path.exists(spectrum_path):
        print(f"ERROR: PeppySpectrum not found at {spectrum_path}")
        print("Run the installer to download PeppySpectrum.")
        return False
    
    # Fetch and setup config BEFORE any imports that might read it
    config_path = setup_remote_config(peppymeter_path, templates_path, config_fetcher)
    
    # Set SDL environment for desktop BEFORE pygame import
    # This prevents volumio_peppymeter's init_display from setting framebuffer mode
    # Remove ALL framebuffer-related SDL variables
    for var in ['SDL_FBDEV', 'SDL_MOUSEDEV', 'SDL_MOUSEDRV', 'SDL_NOMOUSE']:
        os.environ.pop(var, None)
    
    # Remove SDL_VIDEODRIVER if it's set to framebuffer/headless modes OR empty string
    sdl_driver = os.environ.get('SDL_VIDEODRIVER', None)
    if sdl_driver is not None and (sdl_driver == '' or sdl_driver in ('dummy', 'fbcon', 'directfb')):
        del os.environ['SDL_VIDEODRIVER']
    
    # Ensure DISPLAY is set for X11
    if 'DISPLAY' not in os.environ:
        os.environ['DISPLAY'] = ':0'
    
    print(f"  SDL environment configured for desktop (DISPLAY={os.environ.get('DISPLAY')})")
    
    # Add paths to Python path
    # Order matters: screensaver first (volumio_*.py), then peppymeter, then spectrum
    spectrum_path = os.path.join(screensaver_path, "spectrum")
    if screensaver_path not in sys.path:
        sys.path.insert(0, screensaver_path)
    if peppymeter_path not in sys.path:
        sys.path.insert(0, peppymeter_path)
    if spectrum_path not in sys.path:
        sys.path.insert(0, spectrum_path)
    
    # Change to peppymeter directory (volumio_peppymeter expects this)
    original_cwd = os.getcwd()
    os.chdir(peppymeter_path)
    
    try:
        # Enable X11 threading
        try:
            ctypes.CDLL('libX11.so.6').XInitThreads()
        except Exception:
            pass  # Not on X11 or library not found
        
        print("Loading PeppyMeter...")
        
        # Import PeppyMeter components
        # Note: peppymeter.peppymeter because Peppymeter class is in peppymeter/peppymeter.py
        from peppymeter.peppymeter import Peppymeter
        from configfileparser import (
            SCREEN_INFO, WIDTH, HEIGHT, DEPTH, SDL_ENV, DOUBLE_BUFFER, SCREEN_RECT
        )
        from volumio_configfileparser import Volumio_ConfigFileParser, COLOR_DEPTH
        
        # Import volumio_peppymeter functions (NOT init_display - we have our own for desktop)
        from volumio_peppymeter import (
            start_display_output, CallBack,
            init_debug_config, log_debug, memory_limit
        )
        
        # Initialize base PeppyMeter
        print("Initializing PeppyMeter...")
        pm = Peppymeter(standalone=True, timer_controlled_random_meter=False, 
                       quit_pygame_on_stop=False)
        
        # Parse Volumio configuration
        parser = Volumio_ConfigFileParser(pm.util)
        meter_config_volumio = parser.meter_config_volumio
        
        # Initialize debug settings
        init_debug_config(meter_config_volumio)
        log_debug("=== PeppyMeter Remote Client starting ===", "basic")
        
        # Replace data source with remote data source
        print("Connecting remote data source...")
        remote_ds = RemoteDataSource(level_receiver)
        
        # Stop the original data source if it exists (prevents noise/pipe conflicts)
        original_ds = getattr(pm, 'data_source', None)
        if original_ds and original_ds != remote_ds:
            if hasattr(original_ds, 'stop_data_source'):
                try:
                    original_ds.stop_data_source()
                except Exception:
                    pass
        
        # Inject remote data source into both Peppymeter AND Meter
        # PeppyMeter's meter.run() uses self.data_source internally
        pm.data_source = remote_ds
        if hasattr(pm, 'meter') and pm.meter:
            pm.meter.data_source = remote_ds
        
        # Create callback handler
        callback = CallBack(pm.util, meter_config_volumio, pm.meter)
        pm.meter.callback_start = callback.peppy_meter_start
        pm.meter.callback_stop = callback.peppy_meter_stop
        pm.dependent = callback.peppy_meter_update
        pm.meter.malloc_trim = callback.trim_memory
        pm.malloc_trim = callback.exit_trim_memory
        
        # Get screen dimensions
        screen_w = pm.util.meter_config[SCREEN_INFO][WIDTH]
        screen_h = pm.util.meter_config[SCREEN_INFO][HEIGHT]
        depth = meter_config_volumio[COLOR_DEPTH]
        pm.util.meter_config[SCREEN_INFO][DEPTH] = depth
        print(f"Display: {screen_w}x{screen_h}")
        
        memory_limit()
        
        # Initialize display - CLIENT SPECIFIC (not using init_display from volumio_peppymeter)
        # volumio_peppymeter.init_display() sets SDL_FBDEV which breaks X11 desktop display
        # We initialize pygame directly for desktop use
        import pygame as pg
        
        # Ensure clean SDL environment for X11/Wayland desktop
        # These must be unset/correct BEFORE pg.display.init()
        for var in ['SDL_FBDEV', 'SDL_MOUSEDEV', 'SDL_MOUSEDRV', 'SDL_NOMOUSE']:
            os.environ.pop(var, None)
        # Don't set SDL_VIDEODRIVER - let SDL auto-detect (x11, wayland)
        os.environ.pop('SDL_VIDEODRIVER', None)
        if 'DISPLAY' not in os.environ:
            os.environ['DISPLAY'] = ':0'
        
        pg.display.init()
        pg.mouse.set_visible(False)
        pg.font.init()
        
        # Determine display flags from config (passed via environment)
        is_windowed = os.environ.get('PEPPY_DISPLAY_WINDOWED', '1') == '1'
        is_fullscreen = os.environ.get('PEPPY_DISPLAY_FULLSCREEN', '0') == '1'
        
        flags = 0
        if is_fullscreen:
            flags |= pg.FULLSCREEN
        elif not is_windowed:
            # Frameless kiosk mode
            flags |= pg.NOFRAME
        # If windowed, no special flags (default window with title bar)
        
        if pm.util.meter_config[SDL_ENV][DOUBLE_BUFFER]:
            flags |= pg.DOUBLEBUF
        
        screen = pg.display.set_mode((screen_w, screen_h), flags, depth)
        pm.util.meter_config[SCREEN_RECT] = pg.Rect(0, 0, screen_w, screen_h)
        
        # Set window title if windowed
        if is_windowed and not is_fullscreen:
            pg.display.set_caption("PeppyMeter Remote")
        
        pm.util.PYGAME_SCREEN = screen
        pm.util.screen_copy = pm.util.PYGAME_SCREEN
        
        mode_str = "fullscreen" if is_fullscreen else ("windowed" if is_windowed else "frameless")
        print(f"Starting meter display ({mode_str})...")
        print("Press ESC or Q to exit, or click/touch screen")
        
        # Create PeppyRunning file - start_display_output() checks for this
        # and exits if it doesn't exist (it's used by Volumio plugin to signal stop)
        peppy_running_file = '/tmp/peppyrunning'
        from pathlib import Path
        Path(peppy_running_file).touch()
        Path(peppy_running_file).chmod(0o777)
        
        try:
            # Run main display loop
            # Pass server IP for socket.io metadata connection (not localhost)
            start_display_output(pm, callback, meter_config_volumio,
                               volumio_host=server_info['ip'],
                               volumio_port=server_info['volumio_port'])
        finally:
            # Clean up PeppyRunning file
            if os.path.exists(peppy_running_file):
                os.remove(peppy_running_file)
        
        return True
        
    except ImportError as e:
        print(f"ERROR: Could not import PeppyMeter components: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"ERROR: PeppyMeter failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        os.chdir(original_cwd)


# =============================================================================
# Simple Test Display (pygame)
# =============================================================================
def run_test_display(level_receiver):
    """Simple pygame display for testing - shows VU bars."""
    
    # Ensure SDL environment is set for desktop (in case we're falling back after failure)
    os.environ.pop('SDL_FBDEV', None)
    os.environ.pop('SDL_MOUSEDEV', None)
    os.environ.pop('SDL_MOUSEDRV', None)
    os.environ.pop('SDL_NOMOUSE', None)
    os.environ.pop('SDL_VIDEODRIVER', None)  # Remove any driver setting
    if 'DISPLAY' not in os.environ:
        os.environ['DISPLAY'] = ':0'
    
    try:
        import pygame
    except ImportError:
        print("pygame not installed. Install with: pip install pygame")
        return
    
    # Quit pygame if it was partially initialized
    try:
        pygame.quit()
    except:
        pass
    
    pygame.init()
    screen = pygame.display.set_mode((800, 480))
    pygame.display.set_caption("PeppyMeter Remote - Test Mode")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 36)
    font_small = pygame.font.Font(None, 24)
    
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
        
        # Clear screen
        screen.fill((20, 20, 30))
        
        # Get levels
        left, right, mono = level_receiver.get_levels()
        
        # Draw VU bars
        bar_width = 60
        bar_max_height = 300
        bar_y = 100
        
        # Left channel
        left_height = int((left / 100.0) * bar_max_height)
        pygame.draw.rect(screen, (0, 200, 0), 
                        (200, bar_y + bar_max_height - left_height, bar_width, left_height))
        pygame.draw.rect(screen, (100, 100, 100), 
                        (200, bar_y, bar_width, bar_max_height), 2)
        left_text = font_small.render(f"L: {left:.1f}", True, (200, 200, 200))
        screen.blit(left_text, (200, bar_y + bar_max_height + 10))
        
        # Right channel
        right_height = int((right / 100.0) * bar_max_height)
        pygame.draw.rect(screen, (0, 200, 0), 
                        (300, bar_y + bar_max_height - right_height, bar_width, right_height))
        pygame.draw.rect(screen, (100, 100, 100), 
                        (300, bar_y, bar_width, bar_max_height), 2)
        right_text = font_small.render(f"R: {right:.1f}", True, (200, 200, 200))
        screen.blit(right_text, (300, bar_y + bar_max_height + 10))
        
        # Mono channel
        mono_height = int((mono / 100.0) * bar_max_height)
        pygame.draw.rect(screen, (0, 150, 200), 
                        (540, bar_y + bar_max_height - mono_height, bar_width, mono_height))
        pygame.draw.rect(screen, (100, 100, 100), 
                        (540, bar_y, bar_width, bar_max_height), 2)
        mono_text = font_small.render(f"M: {mono:.1f}", True, (200, 200, 200))
        screen.blit(mono_text, (540, bar_y + bar_max_height + 10))
        
        # Title
        title_text = font.render("PeppyMeter Remote - Test Display", True, (255, 255, 255))
        screen.blit(title_text, (50, 20))
        
        # Instructions
        info_text = font_small.render("Press ESC or Q to exit", True, (150, 150, 150))
        screen.blit(info_text, (50, 60))
        
        # Sequence number (for debugging)
        seq_text = font_small.render(f"Seq: {level_receiver.seq}", True, (100, 100, 100))
        screen.blit(seq_text, (650, 450))
        
        pygame.display.flip()
        clock.tick(30)
    
    pygame.quit()


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='PeppyMeter Remote Client',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--config', '-c', action='store_true',
                       help='Run interactive configuration wizard')
    parser.add_argument('--server', '-s', 
                       help='Server hostname or IP (skip discovery)')
    parser.add_argument('--level-port', type=int,
                       help='UDP port for level data')
    parser.add_argument('--volumio-port', type=int,
                       help='Volumio socket.io port')
    parser.add_argument('--no-mount', action='store_true',
                       help='Skip SMB mount (use local templates)')
    parser.add_argument('--templates', 
                       help='Path to templates directory (overrides SMB mount)')
    parser.add_argument('--test', action='store_true',
                       help='Run simple test display instead of full PeppyMeter')
    parser.add_argument('--discovery-timeout', type=int,
                       help='Discovery timeout in seconds')
    parser.add_argument('--windowed', action='store_true',
                       help='Run in windowed mode (movable window)')
    parser.add_argument('--fullscreen', action='store_true',
                       help='Run in fullscreen mode')
    
    args = parser.parse_args()
    
    # Run configuration wizard if requested
    if args.config:
        wizard_config = run_config_wizard()
        if wizard_config is None:
            # User quit without wanting to run
            return
        # wizard_config returned means user chose "Run"
        config = wizard_config
    else:
        # Load config from file
        config = load_config()
    
    # Command-line arguments override config file
    if args.server:
        config["server"]["host"] = args.server
    if args.level_port:
        config["server"]["level_port"] = args.level_port
    if args.volumio_port:
        config["server"]["volumio_port"] = args.volumio_port
    if args.discovery_timeout:
        config["server"]["discovery_timeout"] = args.discovery_timeout
    if args.windowed:
        config["display"]["windowed"] = True
        config["display"]["fullscreen"] = False
    if args.fullscreen:
        config["display"]["fullscreen"] = True
        config["display"]["windowed"] = False
    if args.no_mount:
        config["templates"]["use_smb"] = False
    if args.templates:
        config["templates"]["local_path"] = args.templates
        config["templates"]["use_smb"] = False
    
    # Store display config in environment for use by display init
    # (This is read by run_peppymeter_display)
    os.environ['PEPPY_DISPLAY_WINDOWED'] = '1' if config["display"]["windowed"] else '0'
    os.environ['PEPPY_DISPLAY_FULLSCREEN'] = '1' if config["display"]["fullscreen"] else '0'
    if config["display"]["position"]:
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{config['display']['position'][0]},{config['display']['position'][1]}"
    
    # Server discovery or manual specification
    server_info = None
    server_host = config["server"]["host"]
    
    if server_host:
        # Manual server specification
        # Try to resolve hostname to IP
        try:
            ip = socket.gethostbyname(server_host)
        except socket.gaierror:
            # Try with .local suffix
            try:
                ip = socket.gethostbyname(f"{server_host}.local")
            except socket.gaierror:
                ip = server_host  # Assume it's an IP
        
        server_info = {
            'ip': ip,
            'hostname': server_host,
            'level_port': config["server"]["level_port"],
            'volumio_port': config["server"]["volumio_port"]
        }
        print(f"Using server: {server_host} ({ip})")
    else:
        # Auto-discovery
        discovery = ServerDiscovery(
            port=config["server"]["discovery_port"],
            timeout=config["server"]["discovery_timeout"]
        )
        servers = discovery.discover()
        
        if not servers:
            print("No PeppyMeter servers found.")
            print("Use --server <hostname_or_ip> to specify manually.")
            print("Or run --config to configure settings.")
            sys.exit(1)
        elif len(servers) == 1:
            server_info = list(servers.values())[0]
            print(f"Using discovered server: {server_info['hostname']}")
        else:
            # Multiple servers - let user choose
            print("\nMultiple servers found:")
            server_list = list(servers.values())
            for i, srv in enumerate(server_list):
                print(f"  {i+1}. {srv['hostname']} ({srv['ip']})")
            
            while True:
                try:
                    choice = input("\nSelect server (number): ").strip()
                    idx = int(choice) - 1
                    if 0 <= idx < len(server_list):
                        server_info = server_list[idx]
                        break
                except (ValueError, KeyboardInterrupt):
                    print("\nCancelled.")
                    sys.exit(0)
    
    # SMB mount for templates (if enabled)
    smb_mount = None
    if config["templates"]["use_smb"] and not config["templates"]["local_path"]:
        smb_mount = SMBMount(server_info['hostname'])
        if not smb_mount.mount():
            print("WARNING: Could not mount SMB share. Templates may not be available.")
    
    # Config fetcher (uses HTTP to get config from server)
    config_fetcher = ConfigFetcher(server_info['ip'], server_info['volumio_port'])
    
    # Show config version if available from discovery
    if server_info.get('config_version'):
        print(f"Server config version: {server_info['config_version']}")
    
    # Start level receiver
    level_receiver = LevelReceiver(server_info['ip'], server_info['level_port'])
    level_receiver.start()
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        level_receiver.stop()
        if smb_mount:
            smb_mount.unmount()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Determine templates path
    if config["templates"]["local_path"]:
        templates_path = config["templates"]["local_path"]
    elif smb_mount and smb_mount._mounted:
        templates_path = str(smb_mount.templates_path)
    else:
        templates_path = os.path.join(SCRIPT_DIR, "data", "templates")
    
    # Run display
    if args.test:
        # Simple test display
        run_test_display(level_receiver)
    else:
        # Full PeppyMeter rendering
        success = run_peppymeter_display(level_receiver, server_info, 
                                         templates_path, config_fetcher)
        if not success:
            print("\nFalling back to test display...")
            run_test_display(level_receiver)
    
    # Cleanup
    level_receiver.stop()
    if smb_mount:
        smb_mount.unmount()


if __name__ == '__main__':
    main()
