#!/usr/bin/env python3
"""
PeppyMeter Remote Client

Connects to a PeppyMeter server running on Volumio and displays
the meter visualization on a remote display.

Features:
- Auto-discovery of PeppyMeter servers via UDP broadcast
- Receives audio level data over UDP
- Receives metadata via Volumio's socket.io
- Mounts templates via SMB from the server
- Renders using standard PeppyMeter skins

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
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================
DISCOVERY_PORT = 5579
DISCOVERY_TIMEOUT = 10  # seconds to wait for discovery
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SMB_MOUNT_BASE = os.path.join(SCRIPT_DIR, "mnt")  # Local mount point (portable)
SMB_SHARE_PATH = "Internal Storage/peppy_screensaver"

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
                                'version': info.get('version', 1)
                            }
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
    
    @property
    def config_path(self):
        """Path to config.txt."""
        return self.mount_point / 'config.txt'


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
# Metadata Receiver (Socket.IO)
# =============================================================================
class MetadataReceiver:
    """Receives metadata from Volumio via socket.io."""
    
    def __init__(self, server_ip, port=3000):
        self.server_ip = server_ip
        self.port = port
        self.sio = None
        self._running = False
        
        # Current metadata
        self.metadata = {
            'status': 'stop',
            'title': '',
            'artist': '',
            'album': '',
            'albumart': '',
            'seek': 0,
            'duration': 0,
            'volume': 0,
            'mute': False,
            'random': False,
            'repeat': False,
            'repeatSingle': False,
        }
    
    def start(self):
        """Connect to Volumio socket.io."""
        try:
            import socketio
        except ImportError:
            print("WARNING: python-socketio not installed. Metadata will not be available.")
            print("  Install with: pip install python-socketio[client]")
            return False
        
        # Volumio uses socket.io v2, need to specify engineio_logger for debugging
        # and use proper transport settings
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        
        @self.sio.on('pushState')
        def on_push_state(data):
            self._update_metadata(data)
        
        @self.sio.on('connect')
        def on_connect():
            print(f"Connected to Volumio at {self.server_ip}:{self.port}")
            self.sio.emit('getState')
        
        @self.sio.on('disconnect')
        def on_disconnect():
            print("Disconnected from Volumio")
        
        try:
            url = f"http://{self.server_ip}:{self.port}"
            print(f"Connecting to Volumio at {url}...")
            # Try different socket.io protocol versions
            # Volumio typically uses v2/v3 with polling transport
            try:
                self.sio.connect(url, transports=['polling', 'websocket'])
            except Exception:
                # Fall back to websocket only
                self.sio.connect(url, transports=['websocket'])
            self._running = True
            return True
        except Exception as e:
            print(f"Failed to connect to Volumio: {e}")
            # Try alternative approach with requests-based polling
            print("Trying alternative metadata approach...")
            self._start_http_polling()
            return False
    
    def _start_http_polling(self):
        """Fall back to HTTP polling for metadata if socket.io fails."""
        import threading
        import urllib.request
        import json
        
        def poll_loop():
            url = f"http://{self.server_ip}:{self.port}/api/v1/getState"
            while self._running:
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        data = json.loads(response.read().decode())
                        self._update_metadata(data)
                except Exception:
                    pass
                time.sleep(1)  # Poll every second
        
        self._running = True
        self._poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self._poll_thread.start()
        print("Using HTTP polling for metadata")
    
    def _update_metadata(self, data):
        """Update metadata from pushState event."""
        if isinstance(data, dict):
            for key in self.metadata:
                if key in data:
                    self.metadata[key] = data[key]
    
    def stop(self):
        """Disconnect from Volumio."""
        self._running = False
        if self.sio and self.sio.connected:
            self.sio.disconnect()
    
    def get_metadata(self):
        """Get current metadata dict."""
        return self.metadata.copy()


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
# Full PeppyMeter Display
# =============================================================================
def run_peppymeter_display(level_receiver, metadata_receiver, templates_path, smb_mount, server_info):
    """Run full PeppyMeter rendering with actual skins."""
    
    # Set up paths for PeppyMeter (installed at ./peppymeter by install.sh)
    peppymeter_path = os.path.join(SCRIPT_DIR, "peppymeter")
    
    if not os.path.exists(peppymeter_path):
        print(f"ERROR: PeppyMeter not found at {peppymeter_path}")
        print("Run the installer first:")
        print("  curl -sSL https://raw.githubusercontent.com/foonerd/peppy_screensaver/experimental-refactor/remote_client/install.sh | bash")
        return
    
    # Add PeppyMeter to Python path
    if peppymeter_path not in sys.path:
        sys.path.insert(0, peppymeter_path)
    
    # Change to PeppyMeter directory (it expects this)
    original_cwd = os.getcwd()
    os.chdir(peppymeter_path)
    
    try:
        # Import PeppyMeter components
        print("Loading PeppyMeter...")
        
        import ctypes
        try:
            ctypes.CDLL('libX11.so.6').XInitThreads()
        except Exception:
            pass  # Not on X11 or library not found
        
        # Import PeppyMeter after path setup
        from peppymeter import Peppymeter
        from configfileparser import SCREEN_INFO, WIDTH, HEIGHT, FRAME_RATE, SCREEN_RECT
        import pygame
        
        # Get config from server via SMB mount, or create default
        config_path = os.path.join(peppymeter_path, "config.txt")
        _setup_remote_config(config_path, templates_path, smb_mount)
        
        # Initialize PeppyMeter
        print("Initializing PeppyMeter...")
        pm = Peppymeter(standalone=True, timer_controlled_random_meter=False, 
                       quit_pygame_on_stop=False)
        
        # Stop the default data source that was started during init
        if hasattr(pm, 'data_source') and hasattr(pm.data_source, 'stop_data_source'):
            pm.data_source.stop_data_source()
        
        # Replace the data source with our remote data source
        print("Connecting remote data source...")
        remote_ds = RemoteDataSource(level_receiver)
        pm.data_source = remote_ds
        
        # Also update the meter's data source reference
        if hasattr(pm, 'meter') and hasattr(pm.meter, 'data_source'):
            pm.meter.data_source = remote_ds
        
        # Get screen dimensions from config
        try:
            screen_w = pm.util.meter_config[SCREEN_INFO][WIDTH]
            screen_h = pm.util.meter_config[SCREEN_INFO][HEIGHT]
            frame_rate = pm.util.meter_config.get(FRAME_RATE, 30)
        except (KeyError, TypeError):
            screen_w = 800
            screen_h = 480
            frame_rate = 30
        
        print(f"Display: {screen_w}x{screen_h} @ {frame_rate}fps")
        
        # Initialize display
        pm.init_display()
        
        print("Starting meter display...")
        print("Press ESC or Q to exit, or click/touch screen")
        
        # Use PeppyMeter's built-in display loop
        pm.start_display_output()
        
    except ImportError as e:
        print(f"ERROR: Could not import PeppyMeter: {e}")
        import traceback
        traceback.print_exc()
        print("\nFalling back to test display...")
        os.chdir(original_cwd)
        run_test_display(level_receiver, metadata_receiver)
        return
    except Exception as e:
        print(f"ERROR: PeppyMeter failed: {e}")
        import traceback
        traceback.print_exc()
        print("\nFalling back to test display...")
        os.chdir(original_cwd)
        run_test_display(level_receiver, metadata_receiver)
        return
    finally:
        os.chdir(original_cwd)


def _setup_remote_config(config_path, templates_path, smb_mount):
    """
    Set up config.txt for remote client mode.
    
    Priority:
    1. Copy from server via SMB mount (if available)
    2. Fall back to generating default config
    
    After copying/creating, update paths for local use.
    """
    import configparser
    import shutil
    
    server_config_copied = False
    
    # Try to copy config from server via SMB
    if smb_mount and smb_mount._mounted:
        server_config = smb_mount.config_path
        if server_config.exists():
            try:
                print(f"Using config from server: {server_config}")
                shutil.copy(str(server_config), config_path)
                server_config_copied = True
            except Exception as e:
                print(f"  Failed to copy server config: {e}")
    
    if not server_config_copied:
        print("Server config not available, using defaults")
    
    # Now read and adjust the config for local use
    config = configparser.ConfigParser()
    
    if os.path.exists(config_path):
        try:
            config.read(config_path)
        except Exception:
            pass  # Start fresh if parse error
    
    # Ensure all required sections exist with defaults
    _ensure_config_defaults(config)
    
    # Update paths for local client:
    # - base.folder must point to our local templates path
    # - SDL settings for desktop (not framebuffer)
    # - data.source set to noise (we override with RemoteDataSource anyway)
    config['current']['base.folder'] = templates_path
    
    # SDL settings for windowed display (not embedded framebuffer)
    config['sdl.env']['framebuffer.device'] = ''
    config['sdl.env']['video.driver'] = ''  # Empty for X11/desktop
    config['sdl.env']['video.display'] = ':0'
    config['sdl.env']['mouse.enabled'] = 'False'
    config['sdl.env']['double.buffer'] = 'True'
    
    # Data source - we override anyway, but use noise to avoid pipe errors
    config['data.source']['type'] = 'noise'
    config['data.source']['smooth.buffer.size'] = '0'
    
    # Write adjusted config
    with open(config_path, 'w') as f:
        config.write(f)
    
    if server_config_copied:
        print(f"  Config adjusted for local use (meter: {config['current'].get('meter.folder', 'unknown')})")


def _ensure_config_defaults(config):
    """Ensure all required config sections exist with defaults."""
    sections = {
        'current': {
            'meter': 'random',
            'random.meter.interval': '60',
            'base.folder': '',
            'meter.folder': '800x480',
            'screen.width': '',
            'screen.height': '',
            'exit.on.touch': 'False',
            'stop.display.on.touch': 'False',
            'output.display': 'True',
            'output.serial': 'False',
            'output.i2c': 'False',
            'output.pwm': 'False',
            'output.http': 'False',
            'use.logging': 'False',
            'use.cache': 'True',
            'cache.size': '20',
            'frame.rate': '30',
        },
        'sdl.env': {
            'framebuffer.device': '',
            'mouse.device': '',
            'mouse.driver': 'TSLIB',
            'mouse.enabled': 'False',
            'video.driver': '',
            'video.display': ':0',
            'double.buffer': 'True',
            'no.frame': 'False',
        },
        'serial.interface': {
            'device.name': '/dev/serial0',
            'baud.rate': '9600',
            'include.time': 'False',
            'update.period': '0.1',
        },
        'i2c.interface': {
            'port': '1',
            'left.channel.address': '0x21',
            'right.channel.address': '0x20',
            'output.size': '10',
            'update.period': '0.1',
        },
        'pwm.interface': {
            'frequency': '500',
            'gpio.pin.left': '24',
            'gpio.pin.right': '25',
            'update.period': '0.1',
        },
        'http.interface': {
            'target.url': 'http://localhost:8000/vumeter',
            'update.period': '0.033',
        },
        'web.server': {
            'http.port': '8001',
        },
        'data.source': {
            'type': 'noise',
            'polling.interval': '0.033',
            'pipe.name': '/dev/null',
            'volume.constant': '80.0',
            'volume.min': '0.0',
            'volume.max': '100.0',
            'volume.max.in.pipe': '100.0',
            'step': '6',
            'mono.algorithm': 'average',
            'stereo.algorithm': 'new',
            'smooth.buffer.size': '0',
        },
    }
    
    for section, values in sections.items():
        if section not in config:
            config[section] = {}
        for key, value in values.items():
            if key not in config[section]:
                config[section][key] = value


# =============================================================================
# Simple Test Display (pygame)
# =============================================================================
def run_test_display(level_receiver, metadata_receiver):
    """Simple pygame display for testing - shows VU bars and metadata."""
    try:
        import pygame
    except ImportError:
        print("pygame not installed. Install with: pip install pygame")
        return
    
    pygame.init()
    screen = pygame.display.set_mode((800, 480))
    pygame.display.set_caption("PeppyMeter Remote")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 36)
    font_small = pygame.font.Font(None, 24)
    
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
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
        
        # Draw metadata
        meta = metadata_receiver.get_metadata() if metadata_receiver else {}
        
        title = meta.get('title', 'No metadata')
        artist = meta.get('artist', '')
        status = meta.get('status', 'unknown')
        
        title_text = font.render(title[:50], True, (255, 255, 255))
        screen.blit(title_text, (50, 20))
        
        artist_text = font_small.render(artist[:60], True, (180, 180, 180))
        screen.blit(artist_text, (50, 55))
        
        status_text = font_small.render(f"Status: {status}", True, (150, 150, 150))
        screen.blit(status_text, (650, 20))
        
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
    parser.add_argument('--server', '-s', 
                       help='Server hostname or IP (skip discovery)')
    parser.add_argument('--level-port', type=int, default=5580,
                       help='UDP port for level data (default: 5580)')
    parser.add_argument('--volumio-port', type=int, default=3000,
                       help='Volumio socket.io port (default: 3000)')
    parser.add_argument('--no-mount', action='store_true',
                       help='Skip SMB mount (use local templates)')
    parser.add_argument('--templates', 
                       help='Path to templates directory (overrides SMB mount)')
    parser.add_argument('--test', action='store_true',
                       help='Run simple test display instead of full PeppyMeter')
    parser.add_argument('--discovery-timeout', type=int, default=DISCOVERY_TIMEOUT,
                       help=f'Discovery timeout in seconds (default: {DISCOVERY_TIMEOUT})')
    
    args = parser.parse_args()
    
    # Server discovery or manual specification
    server_info = None
    
    if args.server:
        # Manual server specification
        # Try to resolve hostname to IP
        try:
            ip = socket.gethostbyname(args.server)
        except socket.gaierror:
            # Try with .local suffix
            try:
                ip = socket.gethostbyname(f"{args.server}.local")
            except socket.gaierror:
                ip = args.server  # Assume it's an IP
        
        server_info = {
            'ip': ip,
            'hostname': args.server,
            'level_port': args.level_port,
            'volumio_port': args.volumio_port
        }
        print(f"Using server: {args.server} ({ip})")
    else:
        # Auto-discovery
        discovery = ServerDiscovery(timeout=args.discovery_timeout)
        servers = discovery.discover()
        
        if not servers:
            print("No PeppyMeter servers found.")
            print("Use --server <hostname_or_ip> to specify manually.")
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
    
    # SMB mount (if not disabled)
    smb_mount = None
    if not args.no_mount and not args.templates:
        smb_mount = SMBMount(server_info['hostname'])
        if not smb_mount.mount():
            print("WARNING: Could not mount SMB share. Templates may not be available.")
    
    # Start level receiver
    level_receiver = LevelReceiver(server_info['ip'], server_info['level_port'])
    level_receiver.start()
    
    # Start metadata receiver
    metadata_receiver = MetadataReceiver(server_info['ip'], server_info['volumio_port'])
    metadata_receiver.start()
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\nShutting down...")
        level_receiver.stop()
        metadata_receiver.stop()
        if smb_mount:
            smb_mount.unmount()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Determine templates path
    if args.templates:
        templates_path = args.templates
    elif smb_mount and smb_mount._mounted:
        templates_path = str(smb_mount.templates_path)
    else:
        templates_path = os.path.join(SCRIPT_DIR, "data", "templates")
    
    # Run display
    if args.test:
        # Simple test display
        run_test_display(level_receiver, metadata_receiver)
    else:
        # Full PeppyMeter rendering
        run_peppymeter_display(level_receiver, metadata_receiver, 
                               templates_path, smb_mount, server_info)
    
    # Cleanup
    level_receiver.stop()
    metadata_receiver.stop()
    if smb_mount:
        smb_mount.unmount()


if __name__ == '__main__':
    main()
