"""
SSH connection manager for handling remote connections to GPU instances.
"""

import paramiko
from typing import Optional, Tuple, Dict
import logging
import os
import base64
from pathlib import Path
import re

class SSHManager:
    def __init__(self):
        self.client: Optional[paramiko.SSHClient] = None
        self.connected = False
        self.ssh_dir = Path.home() / '.ssh'
        self.ssh_dir.mkdir(mode=0o700, exist_ok=True)
        self.logger = logging.getLogger(__name__)
        # Enable debug logging for paramiko
        logging.getLogger("paramiko").setLevel(logging.DEBUG)

    def generate_ssh_key(self, key_name: str = 'gr00t') -> Tuple[bool, str, str]:
        """
        Generate a new SSH key pair in the format required by Hyperbolic.
        
        Args:
            key_name: Name of the key file (without extension)
            
        Returns:
            Tuple of (success: bool, public_key: str, private_key: str)
        """
        try:
            # Generate RSA key with 2048 bits
            key = paramiko.RSAKey.generate(2048)
            private_key_path = self.ssh_dir / f'{key_name}'
            public_key_path = self.ssh_dir / f'{key_name}.pub'
            
            # Save private key
            key.write_private_key_file(str(private_key_path))
            os.chmod(private_key_path, 0o600)
            
            # Get the public key in the correct format
            public_key = key.get_name() + ' ' + key.get_base64()
            
            # Save public key
            with open(public_key_path, 'w') as f:
                f.write(f"{public_key}\n")
            os.chmod(public_key_path, 0o644)
            
            self.logger.info(f"Generated SSH key pair: {public_key_path}, {private_key_path}")
            return True, public_key, str(private_key_path)
        except Exception as e:
            error_msg = f"Failed to generate SSH key: {str(e)}"
            self.logger.error(error_msg)
            return False, "", error_msg

    def parse_hyperbolic_ssh_string(self, ssh_string: str) -> Tuple[bool, Dict[str, str], str]:
        """
        Parse a Hyperbolic SSH connection string.
        
        Args:
            ssh_string: Hyperbolic SSH connection string
            
        Returns:
            Tuple of (success: bool, connection_params: Dict[str, str], error_message: str)
        """
        try:
            # Try to parse URL format first
            url_pattern = r'ssh://([^@]+)@([^:]+):(\d+)(/[^?]*)?(\?.*)?'
            url_match = re.match(url_pattern, ssh_string)
            
            if url_match:
                username, hostname, port, path, query = url_match.groups()
                params = {
                    'username': username,
                    'hostname': hostname,
                    'port': port,
                    'path': path or '',
                    'query': query or ''
                }
                return True, params, ""
            
            # Try to parse standard SSH command format
            # Format: ssh username@hostname -p port
            cmd_pattern = r'ssh\s+([^@]+)@([^\s]+)(?:\s+-p\s+(\d+))?'
            cmd_match = re.match(cmd_pattern, ssh_string)
            
            if cmd_match:
                username, hostname, port = cmd_match.groups()
                params = {
                    'username': username,
                    'hostname': hostname,
                    'port': port or '22',  # Default to port 22 if not specified
                    'path': '',
                    'query': ''
                }
                self.logger.info(f"Parsed SSH string: {params}")
                return True, params, ""
            
            return False, {}, "Invalid SSH string format"
        except Exception as e:
            error_msg = f"Failed to parse SSH string: {str(e)}"
            self.logger.error(error_msg)
            return False, {}, error_msg

    def connect(self, host: str, port: int, username: str, password: str = None, key_path: str = None) -> Tuple[bool, str]:
        """
        Establish SSH connection to remote host.
        
        Args:
            host: Remote host address
            port: SSH port
            username: SSH username
            password: Optional SSH password
            key_path: Optional path to SSH private key
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            if self.connected:
                self.disconnect()
                
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.logger.info(f"Connecting to {host}:{port} as {username}")
            
            if key_path:
                self.logger.info(f"Using key authentication with key: {key_path}")
                try:
                    # Check if key file exists
                    if not os.path.exists(key_path):
                        raise FileNotFoundError(f"SSH key file not found: {key_path}")
                    
                    # Check key file permissions
                    key_stat = os.stat(key_path)
                    if key_stat.st_mode & 0o777 != 0o600:
                        self.logger.warning(f"SSH key file has incorrect permissions: {key_path}")
                        self.logger.warning(f"Current permissions: {oct(key_stat.st_mode & 0o777)}")
                        self.logger.warning("Attempting to fix permissions...")
                        os.chmod(key_path, 0o600)
                    
                    # Try to load the key based on file extension or content
                    try:
                        # First try ED25519
                        key = paramiko.Ed25519Key.from_private_key_file(key_path)
                        self.logger.info("Loaded ED25519 key")
                    except Exception as ed25519_error:
                        self.logger.info(f"Not an ED25519 key: {str(ed25519_error)}")
                        try:
                            # Then try RSA
                            key = paramiko.RSAKey.from_private_key_file(key_path)
                            self.logger.info("Loaded RSA key")
                        except Exception as rsa_error:
                            self.logger.error(f"Failed to load key as RSA: {str(rsa_error)}")
                            raise Exception("Could not load key as either ED25519 or RSA")
                    
                    self.logger.info(f"Successfully loaded SSH key from: {key_path}")
                    self.logger.info(f"Key type: {key.get_name()}")
                    self.logger.info(f"Key fingerprint: {key.get_fingerprint().hex()}")
                    
                    # Try to connect with the key
                    self.client.connect(host, port, username, pkey=key)
                    self.logger.info("Successfully connected using SSH key")
                except Exception as key_error:
                    self.logger.error(f"Key authentication failed: {str(key_error)}")
                    # If key auth fails, try password if provided
                    if password:
                        self.logger.info("Falling back to password authentication")
                        self.client.connect(host, port, username, password)
                    else:
                        raise key_error
            else:
                self.logger.info("Using password authentication")
                self.client.connect(host, port, username, password)
                
            self.connected = True
            return True, "Successfully connected to remote host"
        except Exception as e:
            error_msg = f"Failed to connect: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def connect_with_hyperbolic(self, ssh_string: str, key_path: str = None) -> Tuple[bool, str]:
        """
        Connect using a Hyperbolic SSH string.
        
        Args:
            ssh_string: Hyperbolic SSH connection string
            key_path: Optional path to SSH private key
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        success, params, error = self.parse_hyperbolic_ssh_string(ssh_string)
        if not success:
            return False, error
            
        self.logger.info(f"Connecting to Hyperbolic instance: {params}")
        
        return self.connect(
            host=params['hostname'],
            port=int(params['port']),
            username=params['username'],
            key_path=key_path
        )

    def disconnect(self) -> None:
        """Close the SSH connection if it exists."""
        if self.client:
            self.client.close()
            self.client = None
            self.connected = False

    def execute_command(self, command: str) -> Tuple[bool, str, str]:
        """
        Execute a command on the remote host.
        
        Args:
            command: Command to execute
            
        Returns:
            Tuple of (success: bool, stdout: str, stderr: str)
        """
        if not self.connected or not self.client:
            return False, "", "Not connected to remote host"
            
        try:
            self.logger.info(f"Executing command: {command}")
            stdin, stdout, stderr = self.client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode()
            stderr_str = stderr.read().decode()
            self.logger.info(f"Command exit status: {exit_status}")
            if stderr_str:
                self.logger.warning(f"Command stderr: {stderr_str}")
            return exit_status == 0, stdout_str, stderr_str
        except Exception as e:
            error_msg = f"Failed to execute command: {str(e)}"
            self.logger.error(error_msg)
            return False, "", error_msg

    def setup_gr00t_environment(self) -> Tuple[bool, str]:
        """Set up the GR00T environment on the remote host."""
        try:
            # Check Python version
            python_check_cmd = "python3 --version"
            success, stdout, stderr = self.execute_command(python_check_cmd)
            if not success or "Python 3.10" not in stdout:
                self.logger.warning("Python 3.10 not found. Installing...")
                install_python_cmd = """
                sudo apt-get update && \
                sudo apt-get install -y software-properties-common && \
                sudo add-apt-repository -y ppa:deadsnakes/ppa && \
                sudo apt-get update && \
                sudo apt-get install -y python3.10 python3.10-venv python3.10-dev
                """
                success, stdout, stderr = self.execute_command(install_python_cmd)
                if not success:
                    return False, f"Failed to install Python 3.10: {stderr}"

            # Check for NVIDIA drivers
            nvidia_check_cmd = "nvidia-smi"
            success, stdout, stderr = self.execute_command(nvidia_check_cmd)
            if success:
                self.logger.info("NVIDIA drivers found")
                
                # Install CUDA if NVIDIA drivers are present
                cuda_cmd = """
                wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb && \
                sudo dpkg -i cuda-keyring_1.1-1_all.deb && \
                sudo apt-get update && \
                sudo apt-get -y install cuda
                """
                success, stdout, stderr = self.execute_command(cuda_cmd)
                if not success:
                    self.logger.warning(f"Failed to install CUDA: {stderr}")
            else:
                self.logger.warning(f"NVIDIA drivers not found: {stderr}")
                self.logger.warning("Please install NVIDIA drivers manually")

            # Check for Conda
            conda_check_cmd = "which conda"
            success, stdout, stderr = self.execute_command(conda_check_cmd)
            if not success:
                self.logger.info("Conda not found. Installing Miniconda...")
                
                # Download Miniconda installer
                download_cmd = """
                wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda.sh && \
                chmod +x ~/miniconda.sh
                """
                success, stdout, stderr = self.execute_command(download_cmd)
                if not success:
                    return False, f"Failed to download Miniconda: {stderr}"
                
                # Install Miniconda with specific options
                install_cmd = """
                bash ~/miniconda.sh -b -p $HOME/miniconda && \
                rm ~/miniconda.sh
                """
                success, stdout, stderr = self.execute_command(install_cmd)
                if not success:
                    return False, f"Failed to install Miniconda: {stderr}"
                
                # Initialize conda
                init_cmd = """
                $HOME/miniconda/bin/conda init bash && \
                $HOME/miniconda/bin/conda init zsh
                """
                success, stdout, stderr = self.execute_command(init_cmd)
                if not success:
                    self.logger.warning(f"Failed to initialize conda: {stderr}")
                
                # Update PATH
                path_cmd = """
                echo 'export PATH="$HOME/miniconda/bin:$PATH"' >> ~/.bashrc && \
                echo 'export PATH="$HOME/miniconda/bin:$PATH"' >> ~/.zshrc && \
                source ~/.bashrc
                """
                success, stdout, stderr = self.execute_command(path_cmd)
                if not success:
                    self.logger.warning(f"Failed to update PATH: {stderr}")

            # Clone GR00T repository if not exists
            clone_cmd = """
            if [ ! -d "~/Isaac-GR00T" ]; then
                cd ~ && \
                git clone https://github.com/NVIDIA/Isaac-GR00T.git
            fi
            """
            success, stdout, stderr = self.execute_command(clone_cmd)
            if not success:
                return False, f"Failed to clone GR00T repository: {stderr}"

            # Set up conda environment
            env_cmd = """
            cd ~/Isaac-GR00T && \
            $HOME/miniconda/bin/conda create -y -n gr00t python=3.10 && \
            $HOME/miniconda/bin/conda activate gr00t && \
            $HOME/miniconda/bin/conda install -y pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia && \
            $HOME/miniconda/bin/pip install flash-attn --no-build-isolation && \
            $HOME/miniconda/bin/pip install -e .
            """
            success, stdout, stderr = self.execute_command(env_cmd)
            if not success:
                return False, f"Failed to set up conda environment: {stderr}"

            self.logger.info("GR00T environment setup completed successfully")
            return True, "GR00T environment setup completed successfully"

        except Exception as e:
            error_msg = f"Failed to set up GR00T environment: {str(e)}"
            self.logger.error(error_msg)
            return False, error_msg

    def run_gr00t_inference(self, model_path: str = "nvidia/GR00T-N1-2B", embodiment_tag: str = "new_embodiment", data_config: str = "so100", denoising_steps: int = 4) -> Tuple[bool, str]:
        """
        Run the GR00T inference service on the remote host.
        
        Args:
            model_path: Path to the model checkpoint
            embodiment_tag: Tag of the embodiment to use
            data_config: Data configuration to use
            denoising_steps: Number of denoising steps to use
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        command = f"cd Isaac-GR00T && conda activate gr00t && python scripts/inference_service.py --server --model_path {model_path} --embodiment_tag {embodiment_tag} --data_config {data_config} --denoising_steps {denoising_steps}"
        
        success, stdout, stderr = self.execute_command(command)
        if not success:
            return False, f"Failed to run GR00T inference: {stderr}"
        
        return True, "GR00T inference service started successfully" 