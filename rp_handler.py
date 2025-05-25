import os
import asyncio
import websockets
import runpod
import threading
import time
from getting_started.examples.eval_gr00t_so100 import handle_client

# Global variable to track server status
websocket_server = None

def start_websocket_server():
    """Start the WebSocket server in a separate thread"""
    async def run_server():
        global websocket_server
        try:
            websocket_server = await websockets.serve(handle_client, "0.0.0.0", 8765)
            print("WebSocket server started on port 8765")
            await websocket_server.wait_closed()
        except Exception as e:
            print(f"WebSocket server error: {e}")

    # Run the async server in a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_server())

def handler(job):
    try:
        # Get the IP and port from RunPod environment
        ip = os.environ.get("RUNPOD_HTTP_IP")
        port = os.environ.get("RUNPOD_TCP_PORT_8765", 8765)
        
        if not ip:
            return {
                "error": "Failed to get RunPod IP address"
            }

        # Start the WebSocket server in a daemon thread
        server_thread = threading.Thread(target=start_websocket_server, daemon=True)
        server_thread.start()
        
        # Give the server a moment to start
        time.sleep(2)
        
        print(f"Returning connection details: {ip}:{port}")
        
        # Return the connection details
        return {
            "ip": ip,
            "port": int(port)
        }

    except Exception as e:
        print(f"Handler error: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    runpod.serverless.start({
        "handler": handler
    })