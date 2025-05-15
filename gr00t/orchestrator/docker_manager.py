"""
Docker operations manager for handling container operations on remote hosts.
"""

from typing import Tuple, Optional
from .ssh_manager import SSHManager
import logging

logger = logging.getLogger(__name__)

class DockerManager:
    def __init__(self, ssh_manager: SSHManager):
        self.ssh_manager = ssh_manager
        self.default_image = "nvidia/gr00t:latest"  # Update with actual image name

    def pull_image(self, image_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Pull a Docker image on the remote host.
        
        Args:
            image_name: Optional image name to pull, defaults to GR00T image
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        image = image_name or self.default_image
        success, stdout, stderr = self.ssh_manager.execute_command(f"docker pull {image}")
        
        if success:
            return True, f"Successfully pulled image: {image}"
        return False, f"Failed to pull image: {stderr}"

    def run_finetuning(self, 
                      dataset_path: str,
                      output_path: str,
                      steps: int,
                      learning_rate: float) -> Tuple[bool, str]:
        """
        Run finetuning task in a Docker container.
        
        Args:
            dataset_path: Path to dataset on remote host
            output_path: Path for output on remote host
            steps: Number of training steps
            learning_rate: Learning rate for training
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        cmd = (
            f"docker run --gpus all -v {dataset_path}:/data "
            f"-v {output_path}:/output {self.default_image} "
            f"python /scripts/gr00t_finetune.py "
            f"--steps {steps} --lr {learning_rate}"
        )
        
        success, stdout, stderr = self.ssh_manager.execute_command(cmd)
        
        if success:
            return True, "Finetuning completed successfully"
        return False, f"Finetuning failed: {stderr}"

    def run_inference(self, model_path: str) -> Tuple[bool, str]:
        """
        Run inference service in a Docker container.
        
        Args:
            model_path: Path to model on remote host
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        cmd = (
            f"docker run --gpus all -v {model_path}:/model "
            f"{self.default_image} python /scripts/inference_service.py "
            f"--model /model"
        )
        
        success, stdout, stderr = self.ssh_manager.execute_command(cmd)
        
        if success:
            return True, "Inference service started successfully"
        return False, f"Failed to start inference service: {stderr}" 