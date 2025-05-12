#!/usr/bin/env python3
# Apply eventlet monkey patch at the very beginning before any other imports
try:
    import eventlet
    eventlet.monkey_patch()
    USING_EVENTLET = True
except ImportError:
    USING_EVENTLET = False
    try:
        import gevent
        import gevent.monkey
        gevent.monkey.patch_all()
        USING_GEVENT = True
    except ImportError:
        USING_GEVENT = False
        
# Now import the rest of the modules
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import os
import threading
import time
import pty
import termios
import struct
import fcntl
import json
import logging
import errno
import subprocess
import sys
import stat

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set to True to enable verbose debug logging
DEBUG_MODE = True

# Print what async mode we're using
if USING_EVENTLET:
    logger.info("Using eventlet for WebSocket transport")
elif USING_GEVENT:
    logger.info("Using gevent for WebSocket transport")
else:
    logger.info("Using threading mode for WebSocket transport")

# Maximum number of reconnection attempts
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY = 2  # seconds

# Health monitor settings
HEALTH_CHECK_INTERVAL = 30  # seconds

# Target PTY device numbers we want
TARGET_PTY_DEVICES = {
    'port1': '/dev/pts/1',
    'port2': '/dev/pts/2',
}

# For auto-creating PTYs at startup
AUTO_CREATE_PORTS = True
DEFAULT_BAUD_RATE = 1000000  # 1M baud

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

# Configure SocketIO with improved settings
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode='eventlet' if USING_EVENTLET else ('gevent' if USING_GEVENT else None),
    logger=DEBUG_MODE,      # Enable socketio logging if in debug mode
    engineio_logger=DEBUG_MODE,
    max_http_buffer_size=1024 * 1024  # 1MB buffer for large transfers
)

# Virtual serial port management
virtual_ports = {
    'port1': {
        'master': None,
        'slave': None,
        'path': None,
        'is_open': False,
        'baud_rate': 9600,
        'data_bits': 8,
        'parity': 'none',
        'stop_bits': 1,
        'lock': threading.Lock(),
        'reconnect_attempts': 0,
        'last_error_time': 0
    },
    'port2': {
        'master': None,
        'slave': None,
        'path': None,
        'is_open': False,
        'baud_rate': 9600,
        'data_bits': 8,
        'parity': 'none',
        'stop_bits': 1,
        'lock': threading.Lock(),
        'reconnect_attempts': 0,
        'last_error_time': 0
    }
}

# Keep track of connected clients
connected_clients = {}

# Health monitor thread
health_check_thread = None
health_check_running = False

def prepare_pty_environment():
    """Prepare the PTY environment for creating specific numbered PTYs"""
    try:
        # Check current PTY devices
        logger.info("Checking current PTY setup")
        result = subprocess.run(["ls", "-la", "/dev/pts/"], capture_output=True, text=True)
        logger.info(f"Current PTY devices:\n{result.stdout}")
        
        # Check if devpts is mounted correctly with correct options
        try:
            devpts_info = None
            mount_output = subprocess.run(["mount"], capture_output=True, text=True).stdout
            mount_lines = mount_output.splitlines()
            for line in mount_lines:
                if "devpts" in line:
                    devpts_info = line
                    break
                    
            if devpts_info:
                logger.info(f"devpts mount info: {devpts_info}")
                
                # Check if we have ptmxmode set correctly
                if "ptmxmode=" in devpts_info:
                    if "ptmxmode=0666" in devpts_info:
                        logger.info("devpts mounted with ptmxmode=0666, good")
                    else:
                        logger.warning("devpts not mounted with ptmxmode=0666, might cause permission issues")
                else:
                    logger.warning("No ptmxmode option found in devpts mount")
            else:
                logger.warning("devpts doesn't appear to be properly mounted")
        except Exception as mount_err:
            logger.warning(f"Could not check mount info: {str(mount_err)}")
        
        # Check if ptmx exists and has correct permissions
        try:
            ptmx_stat = os.stat("/dev/ptmx")
            logger.info(f"PTMX permissions: {stat.filemode(ptmx_stat.st_mode)}")
            
            # Ensure PTY devices can be created
            if not stat.S_ISCHR(ptmx_stat.st_mode):
                logger.warning("/dev/ptmx is not a character device")
                
            # Check if it's world readable/writable
            if stat.S_IMODE(ptmx_stat.st_mode) & 0o666 != 0o666:
                logger.warning("/dev/ptmx permissions may be too restrictive")
                
                # Try to fix permissions if we're running as root
                if os.geteuid() == 0:
                    try:
                        os.chmod("/dev/ptmx", 0o666)
                        logger.info("Fixed /dev/ptmx permissions")
                    except Exception as chmod_err:
                        logger.warning(f"Could not fix /dev/ptmx permissions: {str(chmod_err)}")
        except Exception as ptmx_err:
            logger.warning(f"Could not check PTMX: {str(ptmx_err)}")
        
        # Check if we can create a test PTY
        try:
            test_master, test_slave = pty.openpty()
            test_name = os.ttyname(test_slave)
            logger.info(f"Successfully created test PTY: {test_name}")
            
            # Clean up the test PTY
            os.close(test_master)
            os.close(test_slave)
            logger.info("Test PTY successfully closed")
        except Exception as test_err:
            logger.error(f"Failed to create test PTY: {str(test_err)}")
            logger.error("PTY creation may not work correctly")
        
        # Clean up stale PTYs to make our target numbers available
        clean_stale_ptys()
        
        return True
    except Exception as e:
        logger.error(f"Error preparing PTY environment: {str(e)}")
        return False

def create_virtual_serial_port(port_id, try_specific_number=True):
    """Create a virtual serial port (pty) on the server side"""
    try:
        # Reset reconnect attempts counter
        virtual_ports[port_id]['reconnect_attempts'] = 0
        
        # Check if we can list current PTYs
        try:
            logger.info("Available PTYs before creation:")
            result = subprocess.run(["ls", "-la", "/dev/pts/"], capture_output=True, text=True)
            logger.info(result.stdout)
        except Exception as pts_err:
            logger.warning(f"Could not list PTYs: {str(pts_err)}")
        
        # If we want a specific device number, try a different approach
        target_path = TARGET_PTY_DEVICES.get(port_id)
        if try_specific_number and target_path:
            logger.info(f"Attempting to get specific PTY: {target_path}")
            
            # Try a simpler approach: create multiple PTYs until we get the one we want
            # or hit the maximum number of attempts
            max_attempts = 30
            for attempt in range(max_attempts):
                # Create a new PTY
                master, slave = pty.openpty()
                slave_name = os.ttyname(slave)
                
                logger.info(f"Attempt {attempt+1}/{max_attempts}: Created PTY {slave_name}")
                
                if slave_name == target_path:
                    logger.info(f"Successfully acquired target PTY: {target_path}")
                    break
                else:
                    # Not the one we want, close it and try again
                    os.close(master)
                    os.close(slave)
                    
                    # Small delay before next attempt
                    time.sleep(0.1)
                    
                    # If this was the last attempt and we didn't get what we wanted,
                    # try one more time and just use whatever we get
                    if attempt == max_attempts - 1:
                        logger.warning(f"Could not acquire target PTY {target_path} after {max_attempts} attempts.")
                        master, slave = pty.openpty()
                        slave_name = os.ttyname(slave)
                        logger.info(f"Falling back to PTY: {slave_name}")
        else:
            # Standard approach - just create a PTY
            master, slave = pty.openpty()
            slave_name = os.ttyname(slave)
        
        # Check if port is accessible and get file info
        try:
            slave_stat = os.stat(slave_name)
            logger.info(f"Port {port_id} details - slave: {slave_name}, mode: {oct(slave_stat.st_mode)}")
            
            # Try to get terminal size if possible
            try:
                master_fd_info = os.get_terminal_size(master)
                logger.info(f"Terminal size: {master_fd_info}")
            except OSError:
                logger.debug("Could not get terminal size (this is normal)")
        except Exception as stat_err:
            logger.warning(f"Could not get full port stats: {str(stat_err)}")
        
        logger.info(f"Created virtual serial port {port_id}: {slave_name}")
        
        # Test basic read/write access
        try:
            # Write test data
            test_data = b"TEST_DATA_1234"
            bytes_written = os.write(master, test_data)
            logger.info(f"Test write to {port_id} master: {bytes_written} bytes")
            
            # Try to read it back (non-blocking)
            orig_flags = fcntl.fcntl(master, fcntl.F_GETFL)
            fcntl.fcntl(master, fcntl.F_SETFL, orig_flags | os.O_NONBLOCK)
            try:
                read_data = os.read(master, 100)
                logger.info(f"Test read from {port_id} master: {read_data}")
            except BlockingIOError:
                logger.info(f"No data to read from {port_id} master (as expected)")
            finally:
                fcntl.fcntl(master, fcntl.F_SETFL, orig_flags)
        except Exception as test_err:
            logger.warning(f"Port {port_id} read/write test failed: {str(test_err)}")
        
        with virtual_ports[port_id]['lock']:
            virtual_ports[port_id]['master'] = master
            virtual_ports[port_id]['slave'] = slave
            virtual_ports[port_id]['path'] = slave_name
            virtual_ports[port_id]['is_open'] = True
        
        # Change permissions to make the port accessible to all users
        try:
            # Make the port world readable/writable
            os.chmod(slave_name, 0o666)
            logger.info(f"Changed permissions for {slave_name} to 0o666")
        except Exception as perm_err:
            logger.warning(f"Could not change permissions for {slave_name}: {str(perm_err)}")
        
        # Check available PTYs after creation
        try:
            logger.info("Available PTYs after creation:")
            result = subprocess.run(["ls", "-la", "/dev/pts/"], capture_output=True, text=True)
            logger.info(result.stdout)
        except Exception as pts_err:
            logger.warning(f"Could not list PTYs: {str(pts_err)}")
        
        return slave_name
    except Exception as e:
        logger.error(f"Error creating virtual port {port_id}: {str(e)}")
        raise

def close_virtual_serial_port(port_id):
    """Close the virtual serial port"""
    with virtual_ports[port_id]['lock']:
        if virtual_ports[port_id]['is_open']:
            try:
                os.close(virtual_ports[port_id]['master'])
            except OSError as e:
                logger.warning(f"Error closing master for {port_id}: {str(e)}")
                
            try:
                os.close(virtual_ports[port_id]['slave'])
            except OSError as e:
                logger.warning(f"Error closing slave for {port_id}: {str(e)}")
                
            virtual_ports[port_id]['is_open'] = False
            virtual_ports[port_id]['master'] = None
            virtual_ports[port_id]['slave'] = None
            virtual_ports[port_id]['path'] = None
            logger.info(f"Closed virtual serial port {port_id}")

def configure_port(port_id, baud_rate, data_bits, parity, stop_bits):
    """Configure the virtual serial port with the specified parameters"""
    with virtual_ports[port_id]['lock']:
        if not virtual_ports[port_id]['is_open']:
            logger.error(f"Cannot configure - port {port_id} not open")
            return False
            
        # Get current attributes
        attrs = termios.tcgetattr(virtual_ports[port_id]['slave'])
        logger.debug(f"Initial port {port_id} attributes: {attrs}")
        
        # Set baud rate
        speed_map = {
            300: termios.B300,
            1200: termios.B1200,
            2400: termios.B2400,
            4800: termios.B4800,
            9600: termios.B9600,
            19200: termios.B19200,
            38400: termios.B38400,
            57600: termios.B57600,
            115200: termios.B115200,
            1000000: termios.B1000000  # Added support for 1M baud rate
        }
        speed = speed_map.get(baud_rate, termios.B9600)
        if baud_rate not in speed_map:
            logger.warning(f"Unsupported baud rate {baud_rate}, falling back to 9600")
        
        attrs[4] = speed  # input speed
        attrs[5] = speed  # output speed
        
        # Set data bits
        if data_bits == 5:
            attrs[2] &= ~termios.CSIZE
            attrs[2] |= termios.CS5
        elif data_bits == 6:
            attrs[2] &= ~termios.CSIZE
            attrs[2] |= termios.CS6
        elif data_bits == 7:
            attrs[2] &= ~termios.CSIZE
            attrs[2] |= termios.CS7
        else:  # default: 8 bits
            attrs[2] &= ~termios.CSIZE
            attrs[2] |= termios.CS8
        
        # Set parity
        if parity == 'odd':
            attrs[2] |= termios.PARENB
            attrs[2] |= termios.PARODD
        elif parity == 'even':
            attrs[2] |= termios.PARENB
            attrs[2] &= ~termios.PARODD
        else:  # default: no parity
            attrs[2] &= ~termios.PARENB
        
        # Set stop bits
        if stop_bits == 2:
            attrs[2] |= termios.CSTOPB
        else:  # default: 1 stop bit
            attrs[2] &= ~termios.CSTOPB
        
        # Apply the attributes
        try:
            termios.tcsetattr(virtual_ports[port_id]['slave'], termios.TCSANOW, attrs)
            logger.debug(f"Final port {port_id} attributes: {attrs}")
            
            # Try to get actual baud rate to verify
            try:
                actual_attrs = termios.tcgetattr(virtual_ports[port_id]['slave'])
                if actual_attrs[4] != speed or actual_attrs[5] != speed:
                    logger.warning(f"Baud rate mismatch: requested {baud_rate}, got {actual_attrs[4]}/{actual_attrs[5]}")
            except Exception as verify_err:
                logger.warning(f"Could not verify final attributes: {str(verify_err)}")
                
        except Exception as config_err:
            logger.error(f"Failed to configure port {port_id}: {str(config_err)}")
            return False
            
        logger.info(f"Port configured: baud={baud_rate}, data_bits={data_bits}, parity={parity}, stop_bits={stop_bits}")
        
        # Store current configuration
        virtual_ports[port_id]['baud_rate'] = baud_rate
        virtual_ports[port_id]['data_bits'] = data_bits
        virtual_ports[port_id]['parity'] = parity
        virtual_ports[port_id]['stop_bits'] = stop_bits
        
        return True

def attempt_port_recovery(port_id):
    """Attempt to recover a failed port"""
    current_time = time.time()
    last_error = virtual_ports[port_id]['last_error_time']
    
    # Don't try recovery too frequently
    if current_time - last_error < RECONNECT_DELAY:
        return False
    
    virtual_ports[port_id]['last_error_time'] = current_time
    
    # Check if we should still attempt recovery
    if virtual_ports[port_id]['reconnect_attempts'] >= MAX_RECONNECT_ATTEMPTS:
        logger.error(f"Maximum reconnection attempts reached for {port_id}. Giving up.")
        return False
    
    virtual_ports[port_id]['reconnect_attempts'] += 1
    
    logger.info(f"Attempting to recover {port_id} (attempt {virtual_ports[port_id]['reconnect_attempts']})")
    
    # Close existing port if it's still marked as open
    if virtual_ports[port_id]['is_open']:
        close_virtual_serial_port(port_id)
    
    try:
        # Recreate the port
        port_path = create_virtual_serial_port(port_id)
        
        # Reconfigure the port
        configure_port(
            port_id,
            virtual_ports[port_id]['baud_rate'],
            virtual_ports[port_id]['data_bits'],
            virtual_ports[port_id]['parity'],
            virtual_ports[port_id]['stop_bits']
        )
        
        logger.info(f"Successfully recovered {port_id} at {port_path}")
        
        # Notify clients about recovery in a thread-safe way
        def notify_recovery():
            try:
                socketio.emit('port_status_change', {
                    'port_id': port_id,
                    'status': 'reconnected',
                    'path': port_path
                })
            except Exception as e:
                logger.error(f"Error emitting recovery notification: {str(e)}")
        
        threading.Thread(target=notify_recovery, daemon=True).start()
        
        return True
    except Exception as e:
        logger.error(f"Failed to recover {port_id}: {str(e)}")
        return False

# Helper function for logging binary data
def log_binary_data(data, prefix=""):
    if not DEBUG_MODE:
        return
    
    try:
        hex_data = data.hex()
        ascii_data = ''.join([chr(b) if 32 <= b <= 126 else '.' for b in data])
        logger.debug(f"{prefix} HEX: {hex_data} | ASCII: {ascii_data} | LEN: {len(data)}")
    except Exception as e:
        logger.error(f"Error logging binary data: {str(e)}")

# Data relay thread
def read_from_virtual_port(port_id):
    """Read data from the virtual port and send to clients"""
    logger.info(f"Starting virtual port {port_id} read thread")
    
    while True:
        try:
            with virtual_ports[port_id]['lock']:
                if not virtual_ports[port_id]['is_open']:
                    time.sleep(0.1)
                    continue
                
                try:
                    # Set the master to non-blocking mode for reading
                    orig_flags = fcntl.fcntl(virtual_ports[port_id]['master'], fcntl.F_GETFL)
                    fcntl.fcntl(virtual_ports[port_id]['master'], fcntl.F_SETFL, orig_flags | os.O_NONBLOCK)
                    
                    # Try to read from the master
                    try:
                        data = os.read(virtual_ports[port_id]['master'], 1024)
                        if data:
                            logger.debug(f"READ FROM {port_id}: {len(data)} bytes")
                            log_binary_data(data, f"{port_id} -> CLIENT")
                            
                            # Send data to clients with port information in a thread-safe way
                            def emit_serial_data():
                                try:
                                    socketio.emit('serial_data', {'data': data.hex(), 'port_id': port_id})
                                    logger.debug(f"SENT TO CLIENTS FROM {port_id}: {len(data)} bytes")
                                except Exception as e:
                                    logger.error(f"Error sending serial data: {str(e)}")
                            
                            threading.Thread(target=emit_serial_data, daemon=True).start()
                    except (OSError, BlockingIOError) as e:
                        # Check if it's a serious error or just "no data available"
                        if isinstance(e, OSError) and e.errno != errno.EAGAIN and e.errno != errno.EWOULDBLOCK:
                            logger.error(f"Error reading from {port_id}: {str(e)} (errno: {e.errno})")
                            # Mark for recovery
                            virtual_ports[port_id]['is_open'] = False
                            raise
                        # No data available, just continue
                        pass
                    
                    # Restore original flags
                    try:
                        fcntl.fcntl(virtual_ports[port_id]['master'], fcntl.F_SETFL, orig_flags)
                    except OSError as e:
                        logger.error(f"Error restoring flags for {port_id}: {str(e)}")
                        # Mark for recovery
                        virtual_ports[port_id]['is_open'] = False
                        raise
                    
                except Exception as e:
                    logger.error(f"Error handling {port_id}: {str(e)}")
                    # Mark port as closed if we hit an exception
                    virtual_ports[port_id]['is_open'] = False
            
            # Check if we need recovery outside the lock
            if not virtual_ports[port_id]['is_open']:
                # Notify clients about the disconnection in a thread-safe way
                def notify_disconnection():
                    try:
                        socketio.emit('port_status_change', {
                            'port_id': port_id,
                            'status': 'disconnected'
                        })
                    except Exception as e:
                        logger.error(f"Error emitting disconnect notification: {str(e)}")
                
                threading.Thread(target=notify_disconnection, daemon=True).start()
                logger.warning(f"Port {port_id} marked as closed, attempting recovery")
                
                # Try to recover the port
                recovery_result = attempt_port_recovery(port_id)
                logger.debug(f"Recovery attempt for {port_id} result: {recovery_result}")
        
        except Exception as e:
            logger.error(f"Unexpected error in {port_id} read thread: {str(e)}")
        
        # Don't hog the CPU
        time.sleep(0.01)

# Routes
@app.route('/')
def index():
    return render_template('serial_proxy.html')

@app.route('/api/port_status')
def port_status():
    return jsonify({
        'port1': {
            'is_open': virtual_ports['port1']['is_open'],
            'path': virtual_ports['port1']['path'],
            'baud_rate': virtual_ports['port1']['baud_rate'],
            'data_bits': virtual_ports['port1']['data_bits'],
            'parity': virtual_ports['port1']['parity'],
            'stop_bits': virtual_ports['port1']['stop_bits']
        },
        'port2': {
            'is_open': virtual_ports['port2']['is_open'],
            'path': virtual_ports['port2']['path'],
            'baud_rate': virtual_ports['port2']['baud_rate'],
            'data_bits': virtual_ports['port2']['data_bits'],
            'parity': virtual_ports['port2']['parity'],
            'stop_bits': virtual_ports['port2']['stop_bits']
        }
    })

@app.route('/api/create_port', methods=['POST'])
def api_create_port():
    try:
        data = request.json or {}
        port_id = data.get('port_id', 'port1')
        if port_id not in ['port1', 'port2']:
            return jsonify({'success': False, 'error': 'Invalid port ID'}), 400
        
        logger.info(f"Creating port {port_id} with parameters: {data}")
            
        port_path = create_virtual_serial_port(port_id)
        
        # Get configuration from request
        baud_rate = int(data.get('baud_rate', 9600))
        data_bits = int(data.get('data_bits', 8))
        parity = data.get('parity', 'none')
        stop_bits = int(data.get('stop_bits', 1))
        
        # Configure the port
        config_success = configure_port(port_id, baud_rate, data_bits, parity, stop_bits)
        logger.info(f"Port {port_id} configuration result: {config_success}")
        
        return jsonify({'success': True, 'port': port_path})
    except Exception as e:
        logger.error(f"Error creating port: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/close_port', methods=['POST'])
def api_close_port():
    try:
        data = request.json or {}
        port_id = data.get('port_id', 'port1')
        if port_id not in ['port1', 'port2']:
            return jsonify({'success': False, 'error': 'Invalid port ID'}), 400
            
        close_virtual_serial_port(port_id)
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error closing port: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# WebSocket events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    client_id = request.sid
    logger.info(f"Client connected: {client_id}")
    
    # Store client info
    connected_clients[client_id] = {
        'connect_time': time.time(),
        'last_activity': time.time(),
        'ip': request.remote_addr if hasattr(request, 'remote_addr') else 'unknown'
    }
    
    # Send current port status to newly connected client immediately
    # Use a thread-safe way to emit
    def send_initial_status():
        try:
            # Create a status update based on current port state
            status = {
                'port1': {
                    'is_open': virtual_ports['port1']['is_open'],
                    'path': virtual_ports['port1']['path'],
                    'baud_rate': virtual_ports['port1']['baud_rate'],
                    'data_bits': virtual_ports['port1']['data_bits'],
                    'parity': virtual_ports['port1']['parity'],
                    'stop_bits': virtual_ports['port1']['stop_bits']
                },
                'port2': {
                    'is_open': virtual_ports['port2']['is_open'],
                    'path': virtual_ports['port2']['path'],
                    'baud_rate': virtual_ports['port2']['baud_rate'],
                    'data_bits': virtual_ports['port2']['data_bits'],
                    'parity': virtual_ports['port2']['parity'],
                    'stop_bits': virtual_ports['port2']['stop_bits']
                }
            }
            
            socketio.emit('port_status_update', status, room=client_id)
            logger.debug(f"Sent initial port status to new client {client_id}")
        except Exception as e:
            logger.error(f"Error sending initial port status: {str(e)}")
    
    # Send initial status in a separate thread
    threading.Thread(target=send_initial_status, daemon=True).start()

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    client_id = request.sid
    logger.info(f"Client disconnected: {client_id}")
    
    # Remove from connected clients
    connected_clients.pop(client_id, None)

@socketio.on('heartbeat')
def handle_heartbeat(data):
    """Handle heartbeat from client to keep connection alive"""
    client_id = request.sid
    
    # Update client's last activity time
    if client_id in connected_clients:
        connected_clients[client_id]['last_activity'] = time.time()
    
    # Send heartbeat response back to client
    socketio.emit('heartbeat_response', data, room=client_id)
    
    if DEBUG_MODE:
        logger.debug(f"Heartbeat from {client_id}")

@socketio.on('serial_data')
def handle_serial_data(message):
    """Handle incoming serial data from the client"""
    try:
        # Update client's last activity time
        client_id = request.sid
        if client_id in connected_clients:
            connected_clients[client_id]['last_activity'] = time.time()
        
        # Decode hex string to bytes
        data = bytes.fromhex(message['data'])
        port_id = message.get('port_id', 'port1')  # Default to port1 for backward compatibility
        
        logger.debug(f"RECEIVED FROM CLIENT -> {port_id}: {len(data)} bytes")
        log_binary_data(data, f"CLIENT -> {port_id}")
        
        with virtual_ports[port_id]['lock']:
            if virtual_ports[port_id]['is_open']:
                try:
                    bytes_written = os.write(virtual_ports[port_id]['master'], data)
                    logger.debug(f"WRITTEN TO {port_id}: {bytes_written} of {len(data)} bytes")
                    if bytes_written != len(data):
                        logger.warning(f"Partial write to {port_id}: {bytes_written} of {len(data)} bytes")
                except Exception as write_err:
                    logger.error(f"Error writing to {port_id}: {str(write_err)}")
                    raise
            else:
                logger.warning(f"Dropping data for {port_id} - port not open")
    except Exception as e:
        logger.error(f"Error handling serial data: {str(e)}")

@socketio.on('port_config')
def handle_port_config(config):
    """Handle port configuration request"""
    try:
        # Update client's last activity time
        client_id = request.sid
        if client_id in connected_clients:
            connected_clients[client_id]['last_activity'] = time.time()
            
        baud_rate = int(config.get('baud_rate', 9600))
        data_bits = int(config.get('data_bits', 8))
        parity = config.get('parity', 'none')
        stop_bits = int(config.get('stop_bits', 1))
        port_id = config.get('port_id', 'port1')
        
        success = configure_port(port_id, baud_rate, data_bits, parity, stop_bits)
        
        socketio.emit('port_config_result', {
            'success': success,
            'port_id': port_id,
            'config': {
                'baud_rate': baud_rate,
                'data_bits': data_bits,
                'parity': parity,
                'stop_bits': stop_bits
            } if success else None
        }, room=client_id)
    except Exception as e:
        logger.error(f"Error configuring port: {str(e)}")
        socketio.emit('port_config_result', {
            'success': False,
            'error': str(e)
        }, room=request.sid)

@socketio.on_error()
def handle_error(e):
    """Handle WebSocket errors"""
    logger.error(f"SocketIO error: {str(e)}")

@socketio.on_error_default
def handle_default_error(e):
    """Handle default WebSocket errors"""
    logger.error(f"SocketIO default error: {str(e)}")

def emit_port_status(client_id=None):
    """Emit current port status to a specific client or all clients"""
    status = {
        'port1': {
            'is_open': virtual_ports['port1']['is_open'],
            'path': virtual_ports['port1']['path'],
            'baud_rate': virtual_ports['port1']['baud_rate'],
            'data_bits': virtual_ports['port1']['data_bits'],
            'parity': virtual_ports['port1']['parity'],
            'stop_bits': virtual_ports['port1']['stop_bits']
        },
        'port2': {
            'is_open': virtual_ports['port2']['is_open'],
            'path': virtual_ports['port2']['path'],
            'baud_rate': virtual_ports['port2']['baud_rate'],
            'data_bits': virtual_ports['port2']['data_bits'],
            'parity': virtual_ports['port2']['parity'],
            'stop_bits': virtual_ports['port2']['stop_bits']
        }
    }
    
    # Use a thread-safe way to emit to avoid context issues
    def safe_emit():
        try:
            if client_id:
                socketio.emit('port_status_update', status, room=client_id)
            else:
                socketio.emit('port_status_update', status)
        except Exception as e:
            logger.error(f"Error emitting port status: {str(e)}")
    
    # Run in thread to avoid blocking
    threading.Thread(target=safe_emit, daemon=True).start()

def start_health_monitor():
    """Start a thread to monitor health of connections and ports"""
    global health_check_thread, health_check_running
    
    if health_check_running:
        return
    
    health_check_running = True
    health_check_thread = threading.Thread(target=health_monitor_loop, daemon=True)
    health_check_thread.start()
    logger.info("Health monitor started")

def health_monitor_loop():
    """Monitor connections and port health"""
    global health_check_running
    
    try:
        while health_check_running:
            try:
                check_ports_health()
                check_clients_health()
                time.sleep(HEALTH_CHECK_INTERVAL)
            except Exception as e:
                logger.error(f"Error in health monitor: {str(e)}")
                time.sleep(5)  # Wait a bit on error
    except Exception as e:
        logger.error(f"Health monitor crashed: {str(e)}")
    finally:
        health_check_running = False
        logger.info("Health monitor stopped")

def check_ports_health():
    """Check if ports are still valid and fix if needed"""
    for port_id, port_info in virtual_ports.items():
        with port_info['lock']:
            if not port_info['is_open']:
                continue
                
            try:
                # Try to get port stats to verify it's still valid
                master = port_info['master']
                if master is not None:
                    fcntl.fcntl(master, fcntl.F_GETFL)
                else:
                    logger.warning(f"Port {port_id} master is None but marked as open")
                    port_info['is_open'] = False
                    continue
            except (OSError, IOError) as e:
                logger.warning(f"Port {port_id} health check failed: {str(e)}")
                port_info['is_open'] = False
                
                # Notify clients about the port issue in a thread-safe way
                def notify_disconnection():
                    try:
                        socketio.emit('port_status_change', {
                            'port_id': port_id,
                            'status': 'disconnected',
                            'reason': 'health_check_failed'
                        })
                    except Exception as emit_err:
                        logger.error(f"Error emitting port status change: {str(emit_err)}")
                
                # Run in thread to avoid blocking
                threading.Thread(target=notify_disconnection, daemon=True).start()
                
                # Try to recover the port
                attempt_port_recovery(port_id)

def check_clients_health():
    """Check if clients are still connected and ping them"""
    now = time.time()
    stale_clients = []
    
    for client_id, client_info in connected_clients.items():
        last_seen = client_info.get('last_activity', 0)
        if now - last_seen > 60:  # 60 seconds with no activity
            stale_clients.append(client_id)
            
    # Clean up stale clients
    for client_id in stale_clients:
        logger.warning(f"Removing stale client: {client_id}")
        connected_clients.pop(client_id, None)

def auto_create_ports():
    """Automatically create and configure both virtual serial ports at startup"""
    if not AUTO_CREATE_PORTS:
        logger.info("Auto-creation of ports is disabled")
        return
    
    logger.info("Auto-creating virtual serial ports...")
    
    # First prepare the PTY environment
    prepare_pty_environment()
    
    # Create port1
    try:
        logger.info("Creating port1...")
        # First try with specific number
        try:
            port_path = create_virtual_serial_port('port1', try_specific_number=True)
            
            if port_path and port_path == TARGET_PTY_DEVICES['port1']:
                logger.info(f"Successfully created port1 with target path: {port_path}")
            elif port_path:
                logger.info(f"Created port1 with alternate path: {port_path}")
            else:
                logger.error("Failed to create port1")
                raise Exception("Port creation returned None")
                
            # Configure with default settings
            configure_port(
                'port1',
                DEFAULT_BAUD_RATE,
                8,  # data bits
                'none',  # parity
                1   # stop bits
            )
            logger.info(f"Configured port1 with baud rate {DEFAULT_BAUD_RATE}")
        except Exception as specific_err:
            logger.warning(f"Failed to create port1 with specific number: {str(specific_err)}")
            
            # Fallback: try without specific number constraint
            logger.info("Falling back to any available PTY for port1")
            try:
                # Close port if it was partially opened
                if virtual_ports['port1']['is_open']:
                    close_virtual_serial_port('port1')
                    
                port_path = create_virtual_serial_port('port1', try_specific_number=False)
                if port_path:
                    logger.info(f"Created port1 with fallback path: {port_path}")
                    
                    # Configure with default settings
                    configure_port(
                        'port1',
                        DEFAULT_BAUD_RATE,
                        8,  # data bits
                        'none',  # parity
                        1   # stop bits
                    )
                    logger.info(f"Configured port1 with baud rate {DEFAULT_BAUD_RATE}")
                else:
                    logger.error("Failed to create port1 with fallback method")
            except Exception as fallback_err:
                logger.error(f"Failed to create port1 even with fallback: {str(fallback_err)}")
    except Exception as e:
        logger.error(f"Error creating port1: {str(e)}")
    
    # Create port2
    try:
        logger.info("Creating port2...")
        # First try with specific number
        try:
            port_path = create_virtual_serial_port('port2', try_specific_number=True)
            
            if port_path and port_path == TARGET_PTY_DEVICES['port2']:
                logger.info(f"Successfully created port2 with target path: {port_path}")
            elif port_path:
                logger.info(f"Created port2 with alternate path: {port_path}")
            else:
                logger.error("Failed to create port2")
                raise Exception("Port creation returned None")
                
            # Configure with default settings
            configure_port(
                'port2',
                DEFAULT_BAUD_RATE,
                8,  # data bits
                'none',  # parity
                1   # stop bits
            )
            logger.info(f"Configured port2 with baud rate {DEFAULT_BAUD_RATE}")
        except Exception as specific_err:
            logger.warning(f"Failed to create port2 with specific number: {str(specific_err)}")
            
            # Fallback: try without specific number constraint
            logger.info("Falling back to any available PTY for port2")
            try:
                # Close port if it was partially opened
                if virtual_ports['port2']['is_open']:
                    close_virtual_serial_port('port2')
                    
                port_path = create_virtual_serial_port('port2', try_specific_number=False)
                if port_path:
                    logger.info(f"Created port2 with fallback path: {port_path}")
                    
                    # Configure with default settings
                    configure_port(
                        'port2',
                        DEFAULT_BAUD_RATE,
                        8,  # data bits
                        'none',  # parity
                        1   # stop bits
                    )
                    logger.info(f"Configured port2 with baud rate {DEFAULT_BAUD_RATE}")
                else:
                    logger.error("Failed to create port2 with fallback method")
            except Exception as fallback_err:
                logger.error(f"Failed to create port2 even with fallback: {str(fallback_err)}")
    except Exception as e:
        logger.error(f"Error creating port2: {str(e)}")
    
    # Log summary of created ports
    logger.info("Virtual ports auto-creation summary:")
    for port_id, port_info in virtual_ports.items():
        if port_info['is_open']:
            logger.info(f"  {port_id}: {port_info['path']} @ {port_info['baud_rate']} baud")
        else:
            logger.warning(f"  {port_id}: Failed to create")

def clean_stale_ptys():
    """Attempt to clean up stale/unused PTYs to make specific numbers available"""
    try:
        logger.info("Checking for stale PTYs to clean up")
        
        # Run a specific reset command to try to reset the PTY subsystem
        try:
            logger.info("Attempting to reset PTY subsystem")
            # This command can help reset the PTY state in some systems
            os.system("echo -e '\\033c' > /dev/console 2>/dev/null || true")
        except Exception as reset_err:
            logger.debug(f"PTY reset command failed (this is usually ok): {str(reset_err)}")
        
        # Get list of all PTY devices
        pts_dir = "/dev/pts/"
        pts_files = os.listdir(pts_dir)
        logger.info(f"Current PTY files: {pts_files}")
        
        # Check for low-numbered PTYs
        for i in range(10):  # Check PTYs 0-9
            pty_path = f"/dev/pts/{i}"
            if str(i) in pts_files:
                logger.info(f"Found low-numbered PTY: {pty_path}")
                
                # Try to check if it's in use
                try:
                    # Use lsof to check if any process is using this PTY
                    result = subprocess.run(
                        ["lsof", pty_path], 
                        capture_output=True, 
                        text=True
                    )
                    
                    if result.returncode == 0 and result.stdout.strip():
                        logger.warning(f"PTY {pty_path} is in use:\n{result.stdout.strip()}")
                    else:
                        logger.info(f"PTY {pty_path} may be stale, attempting to release it")
                        
                        # Try a trick to release the TTY
                        try:
                            # Open then immediately close the TTY
                            fd = os.open(pty_path, os.O_RDWR | os.O_NONBLOCK)
                            os.close(fd)
                            logger.info(f"Successfully opened and closed {pty_path}")
                        except Exception as open_err:
                            logger.debug(f"Could not open {pty_path}: {str(open_err)}")
                except Exception as lsof_err:
                    logger.debug(f"lsof check failed for {pty_path}: {str(lsof_err)}")
        
        # Create and immediately close some PTYs to cycle through numbers
        try:
            logger.info("Cycling through PTYs to free up lower numbers")
            # Open and close many PTYs in quick succession to try to get the PTY allocator 
            # to wrap around and start from low numbers again
            for i in range(20):
                try:
                    m, s = pty.openpty()
                    name = os.ttyname(s)
                    logger.debug(f"Cycle {i+1}: Created temporary PTY: {name}")
                    os.close(m)
                    os.close(s)
                except Exception as cycle_err:
                    logger.debug(f"Error in PTY cycle {i+1}: {str(cycle_err)}")
            
            # Create a few more and leave them open temporarily
            temp_ptys = []
            for i in range(5):
                try:
                    m, s = pty.openpty()
                    name = os.ttyname(s)
                    temp_ptys.append((m, s, name))
                    logger.info(f"Created temporary holding PTY: {name}")
                except Exception as temp_err:
                    logger.debug(f"Error creating temp PTY {i+1}: {str(temp_err)}")
            
            # Now close them in reverse order, which might help with getting 
            # lower numbers on the next allocation
            for m, s, name in reversed(temp_ptys):
                try:
                    os.close(m)
                    os.close(s)
                    logger.info(f"Closed temporary PTY: {name}")
                except Exception as close_err:
                    logger.debug(f"Error closing temp PTY {name}: {str(close_err)}")
        except Exception as temp_err:
            logger.warning(f"Error with temporary PTYs: {str(temp_err)}")
        
        # Check what PTYs we have now
        try:
            after_pts_files = os.listdir(pts_dir)
            logger.info(f"PTY files after cleanup: {after_pts_files}")
        except Exception as ls_err:
            logger.warning(f"Error listing PTYs after cleanup: {str(ls_err)}")
            
        return True
    except Exception as e:
        logger.error(f"Error cleaning stale PTYs: {str(e)}")
        return False

if __name__ == '__main__':
    # Import necessary modules
    import errno
    
    # Print Python and system info for debugging
    import sys
    import platform
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Terminal: {os.environ.get('TERM', 'unknown')}")
    
    # Automatically create virtual ports at startup
    auto_create_ports()
    
    # Start the virtual port read threads
    read_thread1 = threading.Thread(target=read_from_virtual_port, args=('port1',), daemon=True)
    read_thread2 = threading.Thread(target=read_from_virtual_port, args=('port2',), daemon=True)
    read_thread1.start()
    read_thread2.start()
    
    # Start the health monitor
    start_health_monitor()
    
    # Start the Flask app
    host = os.environ.get('SERIAL_PROXY_HOST', '0.0.0.0')
    port = int(os.environ.get('SERIAL_PROXY_PORT', 5000))
    logger.info(f"Starting Serial Proxy Server on {host}:{port}")
    
    # Use better server for production
    try:
        # Set up app context to prevent "Working outside of application context" errors
        with app.app_context():
            socketio.run(app, host=host, port=port, debug=DEBUG_MODE, allow_unsafe_werkzeug=True)
    except TypeError:
        # Older versions of Flask-SocketIO might not have allow_unsafe_werkzeug
        with app.app_context():
            socketio.run(app, host=host, port=port, debug=DEBUG_MODE)
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}")
        sys.exit(1) 