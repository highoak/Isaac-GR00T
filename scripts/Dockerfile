FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-setuptools \
    wget \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

# Copy all project files from parent directory
COPY .. /app/
# Ensure rp_handler.py is in the right place
COPY ../rp_handler.py /app/rp_handler.py
COPY ../getting_started /app/getting_started/

# Install PyTorch first
RUN pip3 install --no-cache-dir \
    torch==2.2.2+cu118 \
    torchvision==0.17.2+cu118 \
    torchaudio==2.2.2+cu118 \
    --extra-index-url https://download.pytorch.org/whl/cu118

# Install Hugging Face packages with latest compatible versions
RUN pip3 install --no-cache-dir \
    huggingface-hub==0.26.2 \
    diffusers==0.30.2 \
    transformers==4.45.2 \
    accelerate==1.2.1 \
    peft==0.14.0

# Install other dependencies
RUN pip3 install --no-cache-dir \
    numpy \
    pillow \
    websockets \
    lerobot \
    "networkx<3.2" \
    runpod

# Install remaining dependencies
RUN pip3 install --no-cache-dir \
    albumentations==1.4.18 \
    av==12.3.0 \
    einops==0.8.1 \
    h5py==3.12.1 \
    kornia==0.7.4 \
    matplotlib==3.10.0 \
    opencv-python==4.8.0.74 \
    omegaconf==2.3.0 \
    timm==1.0.14 \
    protobuf==3.20.3

# Set Python path to include the app directory
ENV PYTHONPATH=/app:$PYTHONPATH

# Download models
RUN git lfs install && \
    git clone --depth 1 https://huggingface.co/phospho-app/so100_strawberry_grape-915h3ndhhf /app/models

EXPOSE 8765

# Verify files exist
RUN ls -la /app/ && \
    echo "Checking for rp_handler.py:" && \
    ls -la /app/rp_handler.py

# Run the RunPod handler
CMD ["python3", "-u", "/app/rp_handler.py"]