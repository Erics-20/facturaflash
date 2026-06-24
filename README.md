# FacturaFlash

> Digitalizamos las facturas de compra de bodegas y microempresas peruanas con una sola foto, eliminando el tipeo manual al sistema de la tienda.

---

## Enlaces importantes

| | |
|---|---|
| 🔗 **Demo en vivo** | [facturaflash.streamlit.app](https://facturaflash-vsopyzcwbchtmntlpl6rhh.streamlit.app) |
| 🎥 **Video demo** (2-3 min) | [youtube.com/watch?v=_6owS7uW8Jk](https://www.youtube.com/watch?v=_6owS7uW8Jk) |
| 📊 **Pitch deck** | [docs/PitchDeck_FacturaFlash.pdf](docs/PitchDeck_FacturaFlash.pdf) |

---

## El problema

Las bodegas y microempresas en Perú reciben decenas de facturas de compra cada semana y las registran a mano, tipeando producto por producto en su sistema o cuaderno. Es un proceso lento, repetitivo y propenso a errores que consume tiempo que el dueño podría dedicar al negocio.

---

## La solución

FacturaFlash convierte una foto de la factura en una tabla digital lista para exportar, en segundos y sin tipeo.

**Pipeline:**
1. La app lee el **QR SUNAT** de la factura (si existe) para obtener cabecera exacta: RUC emisor, serie-número, fecha y total.
2. **EasyOCR** extrae el texto completo de la imagen.
3. **Claude AI** interpreta el texto OCR y estructura los productos en JSON.
4. Si no hay QR legible, Claude infiere también la cabecera del texto.

El resultado es una tabla editable de productos con subtotales, exportable a Excel o CSV con un clic.

---

## Cómo correrlo en local

**Requisito:** Python 3.12. No usar 3.13 — PyTorch y EasyOCR aún no lo soportan.

```bash
# 1. Clonar el repo
git clone https://github.com/Erics-20/facturaflash.git
cd facturaflash

# 2. Crear entorno virtual con Python 3.12
python3.12 -m venv .venv312
source .venv312/bin/activate      # Windows: .venv312\Scripts\activate

# 3. Instalar dependencias (incluye torch CPU vía --extra-index-url)
pip install -r requirements.txt

# 4. Configurar API key de Anthropic
cp .env.example .env
# Editar .env y reemplazar el valor de ANTHROPIC_API_KEY

# 5. Lanzar la app
streamlit run frontend/app.py
```

La app abre en `http://localhost:8501`. Sin API key, activa el toggle **Modo Demo** en la barra lateral.

> La primera ejecución descarga los modelos de EasyOCR (~100 MB), que quedan cacheados en `~/.EasyOCR/`.

**En Streamlit Cloud** la API key va en **Settings → Secrets**, no en `.env`:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

---

## Arquitectura

```
Foto/imagen
     │
     ▼
┌─────────────────────────────────────┐
│         frontend/app.py             │
│            (Streamlit)              │
└──────┬──────────────────┬───────────┘
       │                  │
       ▼                  ▼
┌─────────────┐   ┌──────────────┐
│ qr_reader   │   │   ocr.py     │
│  (OpenCV    │   │  (EasyOCR    │
│  QR SUNAT)  │   │   español)   │
└──────┬──────┘   └──────┬───────┘
       │    cabecera      │ texto crudo
       │    exacta o      │
       │    None          ▼
       │         ┌──────────────────┐
       │         │  extractor.py    │
       └────────►│  (Claude API)    │
                 │  JSON productos  │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   Tabla editable │
                 │  (st.data_editor)│
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  exporter.py     │
                 │  Excel / CSV     │
                 └──────────────────┘
```

### Estructura de carpetas

```
facturaflash/
├── frontend/
│   └── app.py              ← UI Streamlit: orquesta todo el pipeline
├── backend/
│   ├── qr_reader.py        ← decodifica el QR SUNAT (OpenCV, multi-estrategia)
│   ├── ocr.py              ← extrae texto de la imagen (EasyOCR, español)
│   ├── extractor.py        ← llama a Claude y parsea la respuesta JSON
│   └── exporter.py         ← genera el .xlsx y .csv descargables
├── ai/
│   └── prompts.py          ← prompts de extracción (editables sin tocar código)
├── data/
│   └── samples/            ← fotos de facturas de prueba
├── docs/
│   └── PitchDeck_FacturaFlash.pdf
├── notebooks/
│   └── exploracion.ipynb   ← exploración y prueba de módulos individuales
├── requirements.txt        ← dependencias Python (torch CPU vía extra-index-url)
├── packages.txt            ← dependencias del sistema para Streamlit Cloud
├── .python-version         ← fija Python 3.12 en el deploy
└── .env.example
```

---

## Herramientas del curso usadas

| Herramienta | Archivo | Por qué |
|---|---|---|
| **EasyOCR** | `backend/ocr.py` | OCR multilenguaje en Python puro, sin dependencias de servicios externos; modelo en español para facturas peruanas |
| **API de Claude / Anthropic** | `backend/extractor.py`, `ai/prompts.py` | Extracción estructurada tipo Lectura 14 del curso: el prompt instruye a Claude a devolver JSON estricto con cabecera y lista de productos |
| **Streamlit** | `frontend/app.py` | Permite construir un frontend web completo (file uploader, tabla editable, descarga) en Python puro, sin HTML/JS |

El flujo de extracción con Claude replica directamente el patrón de la Lectura 14: prompt con esquema JSON esperado → llamada a la API → parseo de la respuesta estructurada.

---

## Nota sobre uso de agentes de IA

El proyecto fue construido con asistencia de **Claude Code** como co-founder técnico: arquitectura, debugging del pipeline OCR→Claude, diseño del flujo de `st.data_editor` con session_state y preparación del deploy. El diseño del producto, el problema a resolver y las decisiones de negocio son del autor.

---

## Autor

**Eric Segura** — solo founder  
Proyecto final del curso *Data Science con Python 2026-I*, Universidad del Pacífico.

---

## Licencia

MIT — ver [LICENSE](LICENSE).
