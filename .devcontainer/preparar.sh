#!/usr/bin/env bash
# Prepara el Codespace: dependencias, base de conocimiento y modelos.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== Instalando dependencias (PyTorch solo CPU: mucho más liviano) =="
python -m pip install --upgrade pip --quiet
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
python -m pip install -r requirements.txt --quiet

echo "== Descargando la base de conocimiento =="
REPO_DATOS="${RAG_REPO_DATOS:-EfMC/rag-datasheets-datos}"
if [ -d conocimiento/.git ]; then
  git -C conocimiento pull --ff-only || true
else
  git clone "https://github.com/${REPO_DATOS}.git" conocimiento \
    || echo "⚠ No se pudo clonar ${REPO_DATOS}. Revisa que el Codespace tenga permiso sobre ese repositorio."
fi

echo "== Descargando los modelos de embeddings y reranking (~1 GB, solo la primera vez) =="
python - <<'PY'
from sentence_transformers import CrossEncoder, SentenceTransformer
from rag import config
SentenceTransformer(config.MODELO_EMBEDDINGS, device="cpu")
CrossEncoder(config.MODELO_RERANK, device="cpu")
print("Modelos listos.")
PY

if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "⚠ Falta el secreto GEMINI_API_KEY: GitHub → Settings → Codespaces → Secrets."
fi
echo "Listo. Prueba: python preguntar.py"
