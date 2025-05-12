#!/bin/bash

# Run the Docker container with Serial Proxy port exposed

# Option 1: Standard port mapping (recommended for most users)
echo "Starting container with standard port mapping..."
echo "Access the Serial Proxy at: http://localhost:5000"
echo "----------------------------------------------"
docker run -it --rm \
  -p 5000:5000 \
  --name isaac-gr00t-serial \
  isaac-gr00t:latest \
  bash -c "python /workspace/scripts/serial_proxy_server.py"

# Option 2: Host network mode (alternative if option 1 doesn't work)
# Note: This gives the container direct access to the host's network interfaces
# Uncomment the lines below to use this mode instead
#
# echo "Starting container with host network mode..."
# echo "Access the Serial Proxy at: http://localhost:5000"
# echo "----------------------------------------------"
# docker run -it --rm \
#   --network host \
#   --name isaac-gr00t-serial \
#   isaac-gr00t:latest \
#   bash -c "python /workspace/scripts/serial_proxy_server.py"

# Note: Web Serial API requires a secure context (HTTPS or localhost)
# If accessing via IP address, you may need to enable a Chrome flag:
# chrome://flags/#unsafely-treat-insecure-origin-as-secure 