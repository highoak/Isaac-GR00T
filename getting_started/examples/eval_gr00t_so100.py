# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import asyncio
import websockets
import json
import base64
from PIL import Image
from io import BytesIO
import numpy as np
import torch
from gr00t.model.policy import Gr00tPolicy
from gr00t.experiment.data_config import DATA_CONFIG_MAP

# GR00T Model Wrapper Class
class GR00TModel:
    def __init__(self, model_path, data_config_name="so100", embodiment_tag="so100"):
        """Initialize the GR00T model with the specified weights and configuration."""
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        data_config = DATA_CONFIG_MAP[data_config_name]
        modality_config = data_config.modality_config()
        modality_transform = data_config.transform()
        self.policy = Gr00tPolicy(
            model_path=model_path,
            modality_config=modality_config,
            modality_transform=modality_transform,
            embodiment_tag=embodiment_tag,
            denoising_steps=4
        )
        self.policy.to(self.device)

    def get_action(self, obs_dict):
        """Compute the action from the observation dictionary."""
        with torch.no_grad():
            action = self.policy.get_action(obs_dict)
        return action

# Initialize the GR00T model (adjust model path as needed)
model_path = "/app/models"  # local directory, already downloaded in Docker image
model = GR00TModel(model_path)

# Helper to build FeeTech write packets (2-byte Goal_Position at address 42)
GOAL_POS_ADDR = 0x2A

def feetech_write_position_command(servo_id: int, pos_val: int):
    pkt = [0xFF, 0xFF, servo_id, 0x07, 0x03, GOAL_POS_ADDR, pos_val & 0xFF, (pos_val >> 8) & 0xFF]
    pkt.append((~sum(pkt[2:])) & 0xFF)
    return pkt

async def handle_client(websocket, path):
    """Handle incoming WebSocket connections and process client messages."""
    print("Client connected!")
    try:
        async for message in websocket:
            # Check for shutdown message
            if message == "shutdown":
                print("Received shutdown signal")
                await websocket.close()
                return

            try:
                # Parse the incoming JSON message from the client
                data = json.loads(message)
                img_base64 = data["image"]  # Base64-encoded video frame
                responses = data.get("responses", None)  # Robot state responses (optional)

                # Decode the base64 image into a numpy array
                img_data = base64.b64decode(img_base64)
                img = Image.open(BytesIO(img_data))
                img_array = np.array(img)

                # Process robot state from responses (if provided)
                if responses and len(responses) > 0:
                    # Assuming responses are joint positions; adjust based on FeeTech format
                    state = np.array(responses[0][:6], dtype=np.float64)  # 5 joints + gripper
                else:
                    state = np.zeros(6, dtype=np.float64)  # Default state if no response

                # Prepare observation dictionary for GR00T model
                obs_dict = {
                    "video.webcam": img_array[np.newaxis, :, :, :],  # Shape: (1, H, W, C)
                    "state.single_arm": state[:5][np.newaxis, :],    # Shape: (1, 5)
                    "state.gripper": state[5:6][np.newaxis, :],      # Shape: (1, 1)
                    "annotation.human.task_description": ["Pick up the fruits and place them on the plate."],
                }

                # Compute action using the GR00T model
                action = model.get_action(obs_dict)

                # Build FeeTech packets from action (5 joints + gripper)
                sa = action["action.single_arm"][0]  # (5,)
                grip = action.get("action.gripper", np.array([0.0]))[0]
                joint_vals = np.concatenate([sa, [grip]])

                # Convert degrees to 0-1000 range (rough, MVP)
                pos_units = (joint_vals / 300 * 1000).astype(int)
                serialized_commands = [feetech_write_position_command(i + 1, val) for i, val in enumerate(pos_units)]

                # Generate read commands to query robot state (for all 6 servos)
                def feetech_read_position_command(servo_id):
                    packet = [0xFF, 0xFF, servo_id, 0x04, 0x02, 0x38, 0x02]
                    checksum = (~sum(packet[2:])) & 0xFF
                    packet.append(checksum)
                    return packet

                read_commands = [
                    {"command": feetech_read_position_command(id), "length": 8}
                    for id in range(1, 7)  # Servo IDs 1-6
                ]

                # Prepare response for the client
                response = {"write_commands": serialized_commands, "read_commands": read_commands}

                # Send the response back to the client
                await websocket.send(json.dumps(response))

            except Exception as e:
                print(f"Error processing client message: {e}")
                # Don't close connection on processing error, wait for next message
                continue
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")
    except Exception as e:
        print(f"Unexpected error in handle_client: {e}")
    finally:
        print("Client handler finished")

async def main():
    """Start the WebSocket server."""
    server = await websockets.serve(handle_client, "0.0.0.0", 8765)
    print("WebSocket server running on port 8765")
    await server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())