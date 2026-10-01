# FROM python:3.13-slim
# WORKDIR /app
# COPY . user_agent/
# WORKDIR /app/user_agent
# RUN if [ -f requirements.txt ]; then pip install --no-cache-dir \
#     --extra-index-url https://download.pytorch.org/whl/cpu \
#     -r requirements.txt; fi
# EXPOSE 8088
# CMD ["python", "main.py"]


# Fetches and checksum-verifies the approved EasyOCR archives plus Docling's
# layout/TableFormer models into /ocr/cache. Runs once at build time so the
# runtime stage never downloads models (offline, deterministic OCR cache).
FROM python:3.13-slim AS ocr-artifacts

WORKDIR /build

# Must match the version pinned in requirements.txt (pre docling-slim split).
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    "docling==2.57.0"

# fetch_ocr_artifacts.py does `from ocr import ...`, so sources/ocr.py must
# land alongside it as a flat module, not under the survey_scribe package.
COPY fetch_ocr_artifacts.py ./fetch_ocr_artifacts.py
COPY sources/ocr.py ./ocr.py

RUN python fetch_ocr_artifacts.py


FROM python:3.13-slim

WORKDIR /app/user_agent

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

# Copy into a directory literally named survey_scribe so `import survey_scribe`
# resolves to a real package; main.py is duplicated at the top level as the
# agent entrypoint script run by CMD.
COPY . ./survey_scribe/
COPY main.py ./main.py

RUN if [ -f survey_scribe/requirements.txt ]; then \
    pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r survey_scribe/requirements.txt; \
    fi

# Baked-in, checksum-verified OCR cache; matches azure.yaml's
# DOCLING_ARTIFACTS_PATH environment variable for the hosted agent.
COPY --from=ocr-artifacts /ocr/cache /opt/ocr-cache
ENV DOCLING_ARTIFACTS_PATH=/opt/ocr-cache

EXPOSE 8088

CMD ["python", "main.py"]