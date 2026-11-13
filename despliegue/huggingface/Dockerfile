# Imagen del asistente para Hugging Face Spaces (D25).
# Este archivo y README.md son lo único que va en el Space: el código se clona del
# repo público y la base de conocimiento se descarga del repo privado al arrancar.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face ejecuta el contenedor con el usuario 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /home/user/app

ARG REPO_CODIGO=https://github.com/EfMC/rag-datasheets-mecatronica.git
RUN git clone --depth 1 "$REPO_CODIGO" codigo

# PyTorch solo CPU (unos 200 MB en lugar de 2 GB) y el resto de dependencias
RUN pip install --no-cache-dir --user torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user -r codigo/requirements-web.txt

# Modelos de embeddings y reordenamiento dentro de la imagen: el arranque es más rápido
RUN cd codigo && python -c "from sentence_transformers import CrossEncoder, SentenceTransformer; \
from rag import config; SentenceTransformer(config.MODELO_EMBEDDINGS, device='cpu'); \
CrossEncoder(config.MODELO_RERANK, device='cpu')"
# Los modelos ya están en la imagen: no consultar el Hub en cada arranque
ENV HF_HUB_OFFLINE=1

EXPOSE 7860
CMD ["bash", "codigo/despliegue/arrancar.sh"]
