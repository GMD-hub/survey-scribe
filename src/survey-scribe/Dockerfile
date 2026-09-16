# FROM python:3.13-slim
# WORKDIR /app
# COPY . user_agent/
# WORKDIR /app/user_agent
# RUN if [ -f requirements.txt ]; then pip install --no-cache-dir \
#     --extra-index-url https://download.pytorch.org/whl/cpu \
#     -r requirements.txt; fi
# EXPOSE 8088
# CMD ["python", "main.py"]


FROM python:3.13-slim

WORKDIR /app

# Native libraries required by Docling/OpenCV in a headless container
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxcb1 \
    libgl1 \
    libglib2.0-0 \
    libx11-6 \
    libxext6 \
    libsm6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY . user_agent/

WORKDIR /app/user_agent

RUN if [ -f requirements.txt ]; then \
    pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt; \
    fi

EXPOSE 8088

CMD ["python", "main.py"]