# GR00T Orchestrator

The GR00T Orchestrator is a desktop-like interface for managing remote GPU instances and executing GR00T tasks. It provides a user-friendly way to:

1. Connect to remote GPU instances via SSH
2. Set up and manage Docker environments
3. Execute finetuning and inference tasks

## Features

- **Connection Management**: Secure SSH connectivity to remote GPU instances
- **Environment Setup**: Automated Docker and NVIDIA container toolkit installation
- **Task Execution**: 
  - Finetuning with customizable parameters
  - Inference service deployment
- **User Interface**: Clean, tab-based Gradio interface

## Installation

The orchestrator is included in the GR00T package. Ensure you have the required dependencies:

```bash
pip install gr00t[orchestrator]
```

## Usage

1. Launch the orchestrator:
```bash
python -m gr00t.orchestrator.main
```

2. Access the web interface at `http://localhost:7860`

3. Follow the tab-based workflow:
   - **Connection Setup**: Enter SSH credentials
   - **Environment Setup**: Install Docker and pull GR00T image
   - **Task Execution**: Run finetuning or inference tasks

## Requirements

- Python 3.10 or higher
- Gradio 4.19.2 or higher
- Paramiko 3.4.0 or higher
- Remote host with SSH access
- Docker and NVIDIA container toolkit (can be installed via the UI)

## Security Notes

- SSH credentials are stored in memory only during the session
- All connections are encrypted
- Docker commands are executed with proper isolation

## Troubleshooting

1. **Connection Issues**:
   - Verify SSH credentials
   - Check if the remote host is accessible
   - Ensure the SSH port is open

2. **Docker Issues**:
   - Verify Docker installation on remote host
   - Check NVIDIA container toolkit installation
   - Ensure proper GPU access

3. **Task Execution Issues**:
   - Verify dataset and model paths
   - Check GPU memory availability
   - Review Docker container logs 