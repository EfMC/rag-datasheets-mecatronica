#!/usr/bin/env bash
# Arranque del contenedor (Hugging Face Spaces o cualquier Docker): actualiza el código,
# descarga la base de conocimiento del repo privado y lanza la app web.
#
# Secretos/variables:
#   GH_TOKEN_DATOS  (obligatorio) token de GitHub de solo lectura sobre el repo privado
#   REPO_DATOS      (opcional) por defecto EfMC/rag-datasheets-datos
#   CODIGO_ACCESO   (opcional) si existe, la app lo pide antes de responder
set -uo pipefail
cd "$(dirname "$0")/.."

echo "== Actualizando el código =="
git pull --ff-only --quiet || echo "   (no se pudo actualizar; se usa la versión de la imagen)"

REPO_DATOS="${REPO_DATOS:-EfMC/rag-datasheets-datos}"
if [ -z "${GH_TOKEN_DATOS:-}" ]; then
  echo "ERROR: falta el secreto GH_TOKEN_DATOS (Settings del Space → Variables and secrets)."
  exit 1
fi
# El token viaja en una cabecera temporal: no queda escrito en .git/config
CABECERA="http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$GH_TOKEN_DATOS" | base64 -w0)"

echo "== Descargando la base de conocimiento ($REPO_DATOS) =="
if [ -d conocimiento/.git ]; then
  # fetch + reset: la copia del servidor nunca hace commits (ver Base.actualizar en app_web.py)
  git -C conocimiento -c "$CABECERA" fetch --quiet \
    && git -C conocimiento reset --hard --quiet '@{u}' || echo "   (no se pudo actualizar)"
else
  if ! git -c "$CABECERA" clone --quiet "https://github.com/${REPO_DATOS}.git" conocimiento; then
    echo "ERROR: no se pudo clonar ${REPO_DATOS}. Revisa que GH_TOKEN_DATOS tenga permiso de"
    echo "       lectura (Contents: Read-only) sobre ese repositorio y que no haya vencido."
    exit 1
  fi
fi

exec python app_web.py
