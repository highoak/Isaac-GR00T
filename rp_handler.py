import os, asyncio, websockets, runpod

async def ws_server():
    async def echo(ws):
        async for msg in ws:
            if msg == "shutdown":
                await ws.close()
                asyncio.get_event_loop().stop()
            # …here you would call handle_client() from eval_gr00t_so100.py …
    return await websockets.serve(echo, "0.0.0.0", 8765)

def handler(event):
    # 1) boot the WebSocket server
    asyncio.get_event_loop().create_task(ws_server())

    # 2) publish IP & port
    ip  = os.environ.get("RUNPOD_HTTP_IP")
    port = os.environ.get("RUNPOD_TCP_PORT_8765", 8765)
    runpod.serverless.progress_update({"ip": ip, "port": int(port)})

    # 3) block until shutdown
    asyncio.get_event_loop().run_forever()
    return {"shutdown": True}

# Start the Serverless function when the script is run
if __name__ == '__main__':
    runpod.serverless.start({
        'handler': handler,
        'return_aggregate_stream': True  # Enable streaming results back to the caller
    })