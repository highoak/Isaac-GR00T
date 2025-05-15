"""
UI components for the GR00T Orchestrator interface.
"""

import gradio as gr
from typing import Tuple, Dict, Any
import os
import json
from .ssh_manager import SSHManager
from .docker_manager import DockerManager

class OrchestratorUI:
    def __init__(self):
        self.ssh_manager = SSHManager()
        self.docker_manager = DockerManager(self.ssh_manager)

    def create_connection_tab(self) -> gr.Tab:
        """Create the connection tab with Hyperbolic SSH connection options."""
        with gr.Tab("Connection") as connection_tab:
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Hyperbolic SSH")
                    hyperbolic_ssh = gr.Textbox(
                        label="Hyperbolic SSH String",
                        placeholder="ssh username@hostname -p port"
                    )
                    hyperbolic_key_path = gr.Textbox(
                        label="Private Key Path",
                        placeholder="Path to your private key file"
                    )
                    connect_hyperbolic_btn = gr.Button("Connect to Hyperbolic")
                    
            with gr.Row():
                status = gr.Textbox(label="Connection Status", interactive=False)
                logs = gr.Textbox(label="Connection Logs", interactive=False, lines=10)
                
            def connect_hyperbolic(ssh_string, key_path):
                if not ssh_string:
                    return "Please provide Hyperbolic SSH string", "Missing SSH string"
                    
                if not key_path:
                    return "Please provide path to private key", "Missing key path"
                    
                logs_text = "Connecting to Hyperbolic instance...\n"
                
                success, message = self.ssh_manager.connect_with_hyperbolic(
                    ssh_string=ssh_string,
                    key_path=key_path
                )
                
                logs_text += f"{message}\n"
                
                if success:
                    logs_text += "Setting up GR00T environment...\n"
                    # Set up GR00T environment
                    setup_success, setup_message = self.ssh_manager.setup_gr00t_environment()
                    logs_text += setup_message + "\n"
                    
                    if not setup_success:
                        return f"{message}\n{setup_message}", logs_text
                    return f"{message}\n{setup_message}", logs_text
                return message, logs_text
                
            connect_hyperbolic_btn.click(
                fn=connect_hyperbolic,
                inputs=[hyperbolic_ssh, hyperbolic_key_path],
                outputs=[status, logs]
            )
            
        return connection_tab

    def create_training_tab(self) -> gr.Tab:
        """Create the training tab for model fine-tuning."""
        with gr.Tab("Training") as training_tab:
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Dataset Configuration")
                    dataset_path = gr.Textbox(
                        label="Dataset Path", 
                        placeholder="/path/to/dataset"
                    )
                    modality_json = gr.File(
                        label="Modality JSON File",
                        file_types=[".json"]
                    )
                    
                with gr.Column():
                    gr.Markdown("### Training Parameters")
                    output_dir = gr.Textbox(
                        label="Output Directory", 
                        value="/tmp/gr00t",
                        placeholder="/path/to/output"
                    )
                    max_steps = gr.Number(
                        label="Maximum Training Steps", 
                        value=10000,
                        precision=0
                    )
                    batch_size = gr.Number(
                        label="Batch Size", 
                        value=16,
                        precision=0
                    )
                    learning_rate = gr.Number(
                        label="Learning Rate", 
                        value=1e-4,
                        precision=6
                    )
                    num_gpus = gr.Number(
                        label="Number of GPUs", 
                        value=1,
                        precision=0
                    )
                    
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Model Configuration")
                    tune_llm = gr.Checkbox(label="Fine-tune Language Model", value=False)
                    tune_visual = gr.Checkbox(label="Fine-tune Vision Tower", value=True)
                    tune_projector = gr.Checkbox(label="Fine-tune Projector", value=True)
                    tune_diffusion_model = gr.Checkbox(label="Fine-tune Diffusion Model", value=True)
                    
                with gr.Column():
                    gr.Markdown("### Advanced Parameters")
                    lora_rank = gr.Number(
                        label="LoRA Rank", 
                        value=0,
                        precision=0
                    )
                    lora_alpha = gr.Number(
                        label="LoRA Alpha", 
                        value=16,
                        precision=0
                    )
                    lora_dropout = gr.Number(
                        label="LoRA Dropout", 
                        value=0.1,
                        precision=2
                    )
                    
            with gr.Row():
                train_btn = gr.Button("Start Training")
                status = gr.Textbox(label="Training Status", interactive=False)
                logs = gr.Textbox(label="Training Logs", interactive=False, lines=10)
                
            def start_training(
                dataset_path, modality_json, output_dir, max_steps, batch_size,
                learning_rate, num_gpus, tune_llm, tune_visual, tune_projector,
                tune_diffusion_model, lora_rank, lora_alpha, lora_dropout
            ):
                if not dataset_path:
                    return "Please provide dataset path", "Missing dataset path"
                
                if not modality_json:
                    return "Please provide modality JSON file", "Missing modality JSON"
                
                logs_text = "Starting training process...\n"
                
                # Save modality JSON to a temporary file on the remote host
                modality_path = os.path.join(os.path.dirname(dataset_path), "modality.json")
                success, message = self.ssh_manager.upload_file(
                    local_path=modality_json.name,
                    remote_path=modality_path
                )
                
                if not success:
                    return f"Failed to upload modality JSON: {message}", logs_text
                
                logs_text += f"Uploaded modality JSON to {modality_path}\n"
                
                # Prepare training command
                cmd = (
                    f"python scripts/gr00t_finetune.py "
                    f"--dataset-path {dataset_path} "
                    f"--output-dir {output_dir} "
                    f"--max-steps {max_steps} "
                    f"--batch-size {batch_size} "
                    f"--learning-rate {learning_rate} "
                    f"--num-gpus {num_gpus} "
                    f"--data-config gr1_arms_only "
                )
                
                if tune_llm:
                    cmd += "--tune-llm "
                if tune_visual:
                    cmd += "--tune-visual "
                if tune_projector:
                    cmd += "--tune-projector "
                if tune_diffusion_model:
                    cmd += "--tune-diffusion-model "
                
                if lora_rank > 0:
                    cmd += f"--lora-rank {lora_rank} "
                    cmd += f"--lora-alpha {lora_alpha} "
                    cmd += f"--lora-dropout {lora_dropout} "
                
                logs_text += f"Running command: {cmd}\n"
                
                # Execute training command
                success, stdout, stderr = self.ssh_manager.execute_command(cmd)
                
                if success:
                    logs_text += "Training completed successfully\n"
                    logs_text += stdout
                    return "Training completed successfully", logs_text
                else:
                    logs_text += f"Training failed: {stderr}\n"
                    return f"Training failed: {stderr}", logs_text
                
            train_btn.click(
                fn=start_training,
                inputs=[
                    dataset_path, modality_json, output_dir, max_steps, batch_size,
                    learning_rate, num_gpus, tune_llm, tune_visual, tune_projector,
                    tune_diffusion_model, lora_rank, lora_alpha, lora_dropout
                ],
                outputs=[status, logs]
            )
            
        return training_tab

    def create_inference_tab(self) -> gr.Tab:
        """Create the inference tab for model inference."""
        with gr.Tab("Inference") as inference_tab:
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Model Configuration")
                    model_path = gr.Textbox(
                        label="Model Path", 
                        placeholder="/path/to/model"
                    )
                    hf_token = gr.Textbox(
                        label="Hugging Face Token", 
                        type="password",
                        placeholder="hf_..."
                    )
                    hf_repo = gr.Textbox(
                        label="Hugging Face Repository", 
                        placeholder="username/repo-name"
                    )
                    
                with gr.Column():
                    gr.Markdown("### Inference Parameters")
                    num_gpus = gr.Number(
                        label="Number of GPUs", 
                        value=1,
                        precision=0
                    )
                    batch_size = gr.Number(
                        label="Batch Size", 
                        value=1,
                        precision=0
                    )
                    
            with gr.Row():
                start_inference_btn = gr.Button("Start Inference")
                upload_weights_btn = gr.Button("Upload Weights to Hugging Face")
                status = gr.Textbox(label="Inference Status", interactive=False)
                logs = gr.Textbox(label="Inference Logs", interactive=False, lines=10)
                
            def start_inference(model_path, num_gpus, batch_size):
                if not model_path:
                    return "Please provide model path", "Missing model path"
                
                logs_text = "Starting inference service...\n"
                
                # Prepare inference command
                cmd = (
                    f"python scripts/inference_service.py "
                    f"--model-path {model_path} "
                    f"--num-gpus {num_gpus} "
                    f"--batch-size {batch_size} "
                )
                
                logs_text += f"Running command: {cmd}\n"
                
                # Execute inference command
                success, stdout, stderr = self.ssh_manager.execute_command(cmd)
                
                if success:
                    logs_text += "Inference service started successfully\n"
                    logs_text += stdout
                    return "Inference service started successfully", logs_text
                else:
                    logs_text += f"Inference service failed: {stderr}\n"
                    return f"Inference service failed: {stderr}", logs_text
                
            def upload_weights(model_path, hf_token, hf_repo):
                if not model_path:
                    return "Please provide model path", "Missing model path"
                
                if not hf_token:
                    return "Please provide Hugging Face token", "Missing HF token"
                
                if not hf_repo:
                    return "Please provide Hugging Face repository", "Missing HF repo"
                
                logs_text = "Uploading weights to Hugging Face...\n"
                
                # Login to Hugging Face
                login_cmd = f"huggingface-cli login --token {hf_token}"
                success, stdout, stderr = self.ssh_manager.execute_command(login_cmd)
                
                if not success:
                    logs_text += f"Failed to login to Hugging Face: {stderr}\n"
                    return f"Failed to login to Hugging Face: {stderr}", logs_text
                
                logs_text += "Logged in to Hugging Face successfully\n"
                
                # Upload model to Hugging Face
                upload_cmd = f"huggingface-cli upload {hf_repo} {model_path}/*"
                success, stdout, stderr = self.ssh_manager.execute_command(upload_cmd)
                
                if success:
                    logs_text += "Weights uploaded successfully\n"
                    logs_text += stdout
                    return "Weights uploaded successfully", logs_text
                else:
                    logs_text += f"Failed to upload weights: {stderr}\n"
                    return f"Failed to upload weights: {stderr}", logs_text
                
            start_inference_btn.click(
                fn=start_inference,
                inputs=[model_path, num_gpus, batch_size],
                outputs=[status, logs]
            )
            
            upload_weights_btn.click(
                fn=upload_weights,
                inputs=[model_path, hf_token, hf_repo],
                outputs=[status, logs]
            )
            
        return inference_tab

    def create_ui(self) -> gr.Blocks:
        """Create the main UI with all tabs."""
        with gr.Blocks(title="GR00T Orchestrator") as ui:
            gr.Markdown("# GR00T Orchestrator")
            with gr.Tabs():
                self.create_connection_tab()
                self.create_training_tab()
                self.create_inference_tab()
                    
        return ui 