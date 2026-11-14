# Publicar el asistente como página web (Streamlit Community Cloud)

El resultado es una página pública, por ejemplo `https://asistente-datasheets.streamlit.app`,
que cualquiera abre desde el navegador del PC o del celular sin instalar nada. Cada persona
escribe **su propia clave de Gemini**: tu cuota no se gasta y no hay que compartir archivos.

```
Navegador ──► Streamlit Community Cloud (gratis, hasta 2,7 GB de RAM; la app usa ~1,6 GB)
                 ├── código ............... este repo público (web/app.py)
                 ├── base de conocimiento .. se clona del repo privado con un token de solo lectura
                 └── API de Gemini ......... con la clave de cada usuario
```

Los PDF siguen privados: la página solo muestra las respuestas y los fragmentos citados.

> **Por qué no Hugging Face Spaces:** desde julio de 2026 las cuentas gratuitas nuevas solo
> pueden crear Spaces estáticos; Docker, Gradio y CPU básico piden créditos (D25).

## Publicarlo (una sola vez, unos 15 minutos)

### 1. Token de GitHub de solo lectura

La app necesita leer el repo privado `rag-datasheets-datos`.

1. Abre <https://github.com/settings/personal-access-tokens/new> (*Fine-grained token*).
2. **Token name:** `streamlit-datos`. **Expiration:** la máxima que permita (anota la fecha).
3. **Repository access → Only select repositories →** `EfMC/rag-datasheets-datos`.
4. **Permissions → Repository permissions → Contents → Read-only.** Nada más.
5. **Generate token** y cópialo (solo se muestra una vez). No lo pegues en ningún chat.

### 2. Crear la app

1. Entra a <https://share.streamlit.io> con **Continue with GitHub** y autoriza el acceso.
2. **Create app → Yup, I have an app** y llena:
   - **Repository:** `EfMC/rag-datasheets-mecatronica`
   - **Branch:** `main`
   - **Main file path:** `web/app.py`
   - **App URL:** por ejemplo `asistente-datasheets`
3. **Advanced settings:**
   - **Python version:** 3.12
   - **Secrets:** pega esto con tu token entre comillas:

     ```toml
     GH_TOKEN_DATOS = "github_pat_..."
     # Opcional: solo entra quien conozca este código
     # CODIGO_ACCESO = "una-palabra"
     ```
4. **Save** (en algunas versiones el botón dice **Deploy**).

La primera instalación tarda unos 5–10 minutos (se ve el registro a la derecha). La primera
visita después tarda 1–2 minutos más mientras descarga la base y carga los modelos; desde
ahí cada pregunta tarda entre 15 s y 1 min.

### 3. Compartirlo

Envía el enlace. Cada persona crea su clave en <https://aistudio.google.com/apikey> (un
minuto, con cualquier cuenta de Google), la pega en el recuadro 🔑 y pregunta.

## Mantenimiento

| Situación | Qué hacer |
|---|---|
| Agregaste un documento (`agregar_documento.py ... --git`) | Nada: la app revisa el repo privado cada 30 minutos y recarga el índice. Para verlo ya: menú **⋮ → Reboot app** en share.streamlit.io. |
| Cambiaste el código y lo subiste a GitHub | Nada: Streamlit Cloud lo detecta y reinicia la app solo. |
| La app dice que está dormida | Es normal tras 12 h sin visitas: el botón que aparece en la página la despierta (1–2 min). |
| Vence el token de GitHub | Crea uno nuevo (paso 1) y reemplázalo en **Settings → Secrets**. |
| Error al arrancar | La página explica si falta el token o no tiene permiso; el detalle está en **Manage app → Logs**. |
| *This app has gone over its resource limits* | Reboot desde share.streamlit.io; si se repite, avísame (se puede aligerar con modelos ONNX). |

## Privacidad de las claves

- La clave viaja del navegador del usuario al servidor de la app y de ahí a Google, solo
  para sus preguntas. Vive en la memoria de su sesión: no se escribe en disco ni en los
  registros, y los mensajes de error la ocultan.
- Las respuestas ya generadas se guardan en una caché compartida (sin la clave): si alguien
  repite una pregunta idéntica, la respuesta sale al instante y no gasta cuota de nadie.
- Quien administra la app controla el código que corre. Como el código es público,
  cualquiera puede revisar que la clave no se guarda.

## Probarlo en tu PC

```bash
pip install -r web/requirements.txt
streamlit run web/app.py          # abre http://localhost:8501
```

En tu PC usa la base de siempre (la carpeta de OneDrive o `conocimiento/`), así que no
necesita el token.
