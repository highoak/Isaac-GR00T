import os
import asyncio
import websockets
import runpod
from .getting_started.examples.eval_gr00t_so100 import handle_client

async def ws_server():
    server = await websockets.serve(handle_client, "0.0.0.0", 8765)
    await server.wait_closed()

def handler(job):
    try:
        # Get the IP and port from RunPod environment
        ip = os.environ.get("RUNPOD_HTTP_IP")
        port = os.environ.get("RUNPOD_TCP_PORT_8765", 8765)
        
        if not ip:
            return {
                "error": "Failed to get RunPod IP address"
            }

        # Start the WebSocket server
        loop = asyncio.get_event_loop()
        server_task = loop.create_task(ws_server())
        
        # Return the connection details immediately
        return {
            "ip": ip,
            "port": int(port)
        }

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    runpod.serverless.start({
        "handler": handler
    })