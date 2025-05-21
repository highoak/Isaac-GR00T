FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-setuptools \
    wget \
    git-lfs \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY ../ /app
COPY gr00t /app/gr00t
COPY pyproject.toml .

# Install PyTorch first
RUN pip3 install --no-cache-dir \
    torch==2.2.2+cu118 \
    torchvision==0.17.2+cu118 \
    torchaudio==2.2.2+cu118 \
    --extra-index-url https://download.pytorch.org/whl/cu118

# Install Hugging Face dependencies with compatible versions
RUN pip3 install --no-cache-dir \
    transformers==4.30.2 \
    diffusers==0.18.2 \
    huggingface-hub==0.15.1 \
    accelerate==0.20.3 \
    peft==0.4.0

# Install other project dependencies
RUN pip3 install --no-cache-dir \
    numpy \
    pillow \
    websockets \
    lerobot \
    "networkx<3.2"

# Install the project
RUN pip3 install .

# Download models
RUN git lfs install && \
    git clone --depth 1 https://huggingface.co/phospho-app/so100_strawberry_grape-915h3ndhhf /app/models

EXPOSE 8765
CMD ["python3","-u","getting_started/examples/eval_gr00t_so100.py"]