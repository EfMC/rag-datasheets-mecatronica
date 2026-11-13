# Publicar el asistente como página web (Hugging Face Spaces)

El resultado es una página pública, por ejemplo `https://efmc-asistente-datasheets.hf.space`,
que cualquiera abre desde el navegador (PC o celular) sin instalar nada. Cada persona
escribe **su propia clave de Gemini**: tu cuota no se gasta y no hay que compartir archivos.

```
Navegador ──► Space de Hugging Face (Docker, CPU gratis: 2 núcleos, 16 GB)
                 ├── código ............ se clona de este repo público
                 ├── base de conocimiento  se clona del repo privado con un token de solo lectura
                 └── app_web.py (Gradio) ─► API de Gemini con la clave de cada usuario
```

Los PDF siguen privados: la app solo muestra las respuestas y los fragmentos citados, y
bloquea el acceso a los archivos de la base (comprobado: devuelve 403).

## Publicarlo (una sola vez, unos 15 minutos)

### 1. Token de GitHub de solo lectura

El Space necesita leer el repo privado `rag-datasheets-datos`.

1. Abre <https://github.com/settings/personal-access-tokens/new> (*Fine-grained token*).
2. **Token name:** `hf-space-datos`. **Expiration:** la máxima que permita (anota la fecha).
3. **Repository access → Only select repositories →** `EfMC/rag-datasheets-datos`.
4. **Permissions → Repository permissions → Contents → Read-only.** Nada más.
5. **Generate token** y cópialo (solo se muestra una vez). No lo pegues en ningún chat.

### 2. Crear el Space

1. Crea una cuenta en <https://huggingface.co/join> (gratis).
2. Abre <https://huggingface.co/new-space> y llena:
   - **Space name:** `asistente-datasheets`
   - **Select the Space SDK:** **Docker** → plantilla **Blank**
   - **Space hardware:** *CPU basic · 2 vCPU · 16 GB · FREE*
   - **Public** (para que otros lo usen; los PDF no quedan expuestos).
3. **Create Space.**

### 3. Guardar el token como secreto

En el Space: **Settings → Variables and secrets → New secret**

| Nombre | Valor |
|---|---|
| `GH_TOKEN_DATOS` | el token del paso 1 |
| `CODIGO_ACCESO` *(opcional)* | una palabra clave si quieres que solo entren quienes la conozcan |

### 4. Subir los dos archivos del Space

En el Space: **Files → Add file → Upload files**, arrastra los dos archivos de la carpeta
`despliegue/huggingface/` (`Dockerfile` y `README.md`; el README reemplaza el que creó
Hugging Face) y pulsa **Commit changes to main**.

La construcción tarda unos 8 minutos la primera vez (pestaña **Logs → Build**). Cuando el
estado pasa a **Running**, la app está en `https://<tu-usuario>-asistente-datasheets.hf.space`.

### 5. Compartirlo

Envía el enlace. Cada persona crea su clave en <https://aistudio.google.com/apikey> (un
minuto, con cualquier cuenta de Google), la pega en la página y pregunta. Puede marcar
*Recordarla en este navegador* para no escribirla cada vez.

## Mantenimiento

| Situación | Qué hacer |
|---|---|
| Agregaste un documento (`agregar_documento.py ... --git`) | Nada: la app revisa el repo privado cada 30 minutos y recarga el índice. Para verlo ya: **Settings → Restart this Space**. |
| Cambiaste el código y lo subiste a GitHub | **Settings → Restart this Space** (al arrancar hace `git pull`). |
| Cambiaste `requirements*.txt` | **Settings → Factory rebuild**. |
| El Space dice *Sleeping* | Es normal tras 48 h sin visitas en el plan gratis: la primera visita lo despierta (1–2 min). |
| Vence el token de GitHub | Crea uno nuevo (paso 1) y reemplaza el secreto `GH_TOKEN_DATOS`. |
| *Runtime error* en el Space | Mira **Logs → Container**: el arranque explica si falta el token o no tiene permiso. |

## Privacidad de las claves

- La clave viaja del navegador del usuario a la app y de ahí a Google, solo para sus
  preguntas. No se escribe en disco ni en los registros, y los mensajes de error la ocultan.
- *Recordarla en este navegador* la guarda en el navegador de esa persona, no en el servidor.
- Las respuestas ya generadas se guardan en una caché compartida (sin la clave): si alguien
  repite una pregunta idéntica, la respuesta sale al instante y no gasta cuota de nadie.
- Quien administra el Space controla el código que corre. Como el código es público,
  cualquiera puede revisar que la clave no se guarda.

## Probarlo en tu PC antes de publicarlo

```bash
pip install -r requirements-web.txt
python app_web.py          # abre http://localhost:7860
```
