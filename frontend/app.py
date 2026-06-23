"""FacturaFlash — app principal de Streamlit."""

from __future__ import annotations
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Cargar .env en desarrollo local ─────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Soporte para st.secrets (Streamlit Cloud)
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ.setdefault("ANTHROPIC_API_KEY", st.secrets["ANTHROPIC_API_KEY"])
except Exception:
    pass

# ── Imports del backend ──────────────────────────────────────────────────────
from backend.qr_reader import extract_qr_data, mock_qr_data
from backend.ocr import extract_text, mock_ocr_text
from backend.extractor import process_invoice, extract_products_demo
from backend.exporter import to_excel_bytes, to_csv_string

# ── Configuración de página ──────────────────────────────────────────────────
st.set_page_config(
    page_title="FacturaFlash",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 1.05rem; }
  .stDownloadButton > button { width: 100%; }
  .badge-qr  { background:#d4edda; color:#155724; padding:2px 10px;
               border-radius:12px; font-size:.85rem; font-weight:600; }
  .badge-ocr { background:#fff3cd; color:#856404; padding:2px 10px;
               border-radius:12px; font-size:.85rem; font-weight:600; }
</style>
""", unsafe_allow_html=True)


# ── Helpers de recalculación de subtotal ────────────────────────────────────

def _safe_float(val) -> float | None:
    """Convierte un valor a float; retorna None para nulos o NaN."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) else f
    except (ValueError, TypeError):
        return None


def _apply_subtotal_rules(
    edited_raw: pd.DataFrame,
    base_df: pd.DataFrame,
    editor_key: str,
) -> tuple[pd.DataFrame, bool]:
    """
    Recalcula la columna 'subtotal' según las reglas de negocio:
      - Si el usuario cambió 'cantidad' o 'precio_unitario' en una fila
        → subtotal = round(cantidad × precio_unitario, 2)
      - Si el usuario cambió 'subtotal' directamente
        → conserva el valor manual (descuento)
      - Filas nuevas (added_rows) → siempre auto-calculan el subtotal

    Para detectar qué cambió en ESTE rerun usa el delta almacenado en
    st.session_state[editor_key] (formato interno de st.data_editor).

    Retorna (df_resultado, hubo_recalculo).
    """
    result = edited_raw.reset_index(drop=True).copy()
    hubo_recalculo = False

    # El delta del data_editor: {edited_rows, added_rows, deleted_rows}
    delta = st.session_state.get(editor_key) or {}
    edited_rows: dict = delta.get("edited_rows", {})
    added_rows: list  = delta.get("added_rows", [])

    # Filas editadas por el usuario en este rerun
    for row_idx_str, changes in edited_rows.items():
        i = int(row_idx_str)
        if i >= len(result):
            continue
        changed_cols = set(changes.keys())
        if "cantidad" in changed_cols or "precio_unitario" in changed_cols:
            qty   = _safe_float(result.at[i, "cantidad"])
            price = _safe_float(result.at[i, "precio_unitario"])
            if qty is not None and price is not None:
                result.at[i, "subtotal"] = round(qty * price, 2)
                hubo_recalculo = True
        # Si solo cambió "subtotal" (u otra columna): no tocamos nada → conserva

    # Filas nuevas: auto-calcular siempre
    new_start = len(base_df)
    for i in range(new_start, len(result)):
        qty   = _safe_float(result.at[i, "cantidad"])
        price = _safe_float(result.at[i, "precio_unitario"])
        if qty is not None and price is not None:
            result.at[i, "subtotal"] = round(qty * price, 2)
            hubo_recalculo = True

    return result, hubo_recalculo


# ── Session state ────────────────────────────────────────────────────────────
_EMPTY_PRODUCTS_DF = pd.DataFrame(
    columns=["descripcion", "cantidad", "precio_unitario", "subtotal"]
)

def _init_state():
    defaults = {
        "history": [],
        "result": None,
        "products_df": _EMPTY_PRODUCTS_DF.copy(),
        "invoice_version": 0,  # cambia con cada factura nueva
        "edit_version":    0,  # cambia con cada recalculación → resetea el delta interno
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("# ⚡ FacturaFlash")
    st.caption("Digitaliza facturas de compra con IA")
    st.divider()

    demo_mode: bool = st.toggle(
        "🎭 Modo Demo",
        value=False,
        help="Usa datos simulados — no necesitas imagen ni API key.",
    )

    if demo_mode:
        st.success("Modo demo activo")
    else:
        st.markdown("**🔑 API Key de Anthropic**")
        api_key_input = st.text_input(
            "ANTHROPIC_API_KEY",
            type="password",
            label_visibility="collapsed",
            placeholder="sk-ant-...",
        )
        if api_key_input:
            os.environ["ANTHROPIC_API_KEY"] = api_key_input.strip()

        if os.environ.get("ANTHROPIC_API_KEY", "").strip():
            st.success("API key configurada ✓")
        else:
            st.warning("API key no detectada")

    st.divider()
    with st.expander("ℹ️ Cómo funciona"):
        st.markdown("""
1. Sube la foto de tu factura.
2. La app intenta leer el **QR SUNAT** (RUC, serie, total…).
3. **EasyOCR** extrae el texto completo.
4. **Claude AI** extrae los productos (y la cabecera si no hay QR).
5. Edita la tabla si hay errores y exporta a Excel o CSV.

**Cabecera verde** = datos del QR (exactos).
**Cabecera amarilla** = datos inferidos por IA (revisa).
        """)


# ════════════════════════════════════════════════════════════════════════════
# CABECERA
# ════════════════════════════════════════════════════════════════════════════
st.title("⚡ FacturaFlash")
st.markdown("**Digitaliza en segundos las facturas de tus proveedores** — sin tipeo manual.")
st.divider()


# ════════════════════════════════════════════════════════════════════════════
# SUBIDA DE ARCHIVO
# ════════════════════════════════════════════════════════════════════════════
uploaded_file = None
if not demo_mode:
    uploaded_file = st.file_uploader(
        "Sube la foto de tu factura",
        type=["jpg", "jpeg", "png", "webp"],
        help="Foto con buena iluminación. Si tiene QR visible, mejor aún.",
    )
    if uploaded_file:
        col_prev, col_info = st.columns([1, 2])
        with col_prev:
            preview = Image.open(io.BytesIO(uploaded_file.read()))
            uploaded_file.seek(0)
            st.image(preview, caption="Vista previa", use_container_width=True)
        with col_info:
            st.markdown(f"**Archivo:** `{uploaded_file.name}`")
            st.markdown(f"**Tamaño:** {uploaded_file.size / 1024:.1f} KB")
            st.markdown(f"**Dimensiones:** {preview.width} × {preview.height} px")
else:
    st.info("🎭 **Modo Demo activo** — pulsa el botón para ver la app con datos simulados.")


# ════════════════════════════════════════════════════════════════════════════
# BOTÓN DE PROCESAMIENTO
# ════════════════════════════════════════════════════════════════════════════
process_clicked = st.button(
    "⚡ Procesar Factura",
    type="primary",
    use_container_width=True,
    disabled=(not demo_mode and uploaded_file is None),
)

if process_clicked:
    result: dict = {}

    with st.spinner("Procesando factura…"):

        # ── Cargar imagen ────────────────────────────────────────────────
        if demo_mode:
            result["filename"] = "demo_factura.jpg"
            image = None
        else:
            raw_bytes = uploaded_file.read()
            image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            result["filename"] = uploaded_file.name

        # ── Paso 1: Leer QR ──────────────────────────────────────────────
        with st.status("📷 Paso 1 — Leyendo código QR SUNAT…") as s1:
            if demo_mode:
                result["qr"] = mock_qr_data()
                s1.update(label="📷 Paso 1 — QR de demo cargado ✓", state="complete")
            else:
                try:
                    result["qr"] = extract_qr_data(image)
                    if result["qr"]:
                        s1.update(
                            label=f"📷 Paso 1 — QR detectado: {result['qr']['serie_numero']} ✓",
                            state="complete",
                        )
                    else:
                        result["qr"] = None
                        s1.update(
                            label="📷 Paso 1 — Sin QR legible (se usará IA para cabecera)",
                            state="complete",
                        )
                except Exception as exc:
                    result["qr"] = None
                    s1.update(label=f"📷 Paso 1 — Error QR: {exc}", state="error")

        # ── Paso 2: OCR ──────────────────────────────────────────────────
        with st.status("🔍 Paso 2 — Extrayendo texto con EasyOCR…") as s2:
            if demo_mode:
                result["ocr_text"] = mock_ocr_text()
                s2.update(label="🔍 Paso 2 — OCR de demo cargado ✓", state="complete")
            else:
                st.caption("Primera ejecución: descarga modelos EasyOCR ~100 MB a ~/.EasyOCR/")
                try:
                    result["ocr_text"] = extract_text(image)
                    n = result["ocr_text"].count("\n") + 1
                    s2.update(label=f"🔍 Paso 2 — {n} líneas extraídas ✓", state="complete")
                except RuntimeError as exc:
                    result["ocr_text"] = ""
                    result["ocr_error"] = str(exc)
                    s2.update(label=f"🔍 Paso 2 — Error OCR: {exc}", state="error")

        # ── Paso 3: Pipeline de fusión con Claude ─────────────────────────
        qr_tag = "QR" if result.get("qr") else "IA"
        with st.status(f"🤖 Paso 3 — Claude extrayendo datos (cabecera por {qr_tag})…") as s3:
            if demo_mode:
                result["cabecera"] = {
                    "proveedor": "DISTRIBUIDORA ALIMENTOS DEL PERU SAC",
                    "ruc": "20100030798",
                    "serie_numero": "F001-00042301",
                    "fecha": "2024-06-15",
                    "total": 558.36,
                }
                result["productos"] = extract_products_demo()
                result["fuente_cabecera"] = "qr"
                s3.update(label="🤖 Paso 3 — Datos de demo cargados ✓", state="complete")
            else:
                try:
                    extracted = process_invoice(
                        result.get("ocr_text", ""),
                        result.get("qr"),
                    )
                    result["cabecera"] = extracted["cabecera"]
                    result["productos"] = extracted["productos"]
                    result["fuente_cabecera"] = extracted["fuente_cabecera"]
                    n_prod = len(result["productos"])
                    s3.update(
                        label=f"🤖 Paso 3 — {n_prod} producto(s) extraído(s) ✓",
                        state="complete",
                    )
                except (ValueError, RuntimeError) as exc:
                    result["cabecera"] = {
                        "proveedor": "", "ruc": "", "serie_numero": "",
                        "fecha": "", "total": None,
                    }
                    result["productos"] = []
                    result["fuente_cabecera"] = "ocr"
                    result["claude_error"] = str(exc)
                    s3.update(label=f"🤖 Paso 3 — Error Claude: {exc}", state="error")

    result["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.result = result

    # Guardar productos como DataFrame UNA sola vez por factura.
    # invoice_version cambia → el data_editor recibe un key nuevo y limpia su delta.
    _productos = result.get("productos", [])
    st.session_state["products_df"] = (
        pd.DataFrame(_productos) if _productos else _EMPTY_PRODUCTS_DF.copy()
    )
    st.session_state["invoice_version"] += 1
    st.session_state["edit_version"] = 0   # nueva factura → delta limpio

    # Pre-setear los widgets de cabecera ANTES de que se rendericen.
    _cab = result.get("cabecera", {})
    st.session_state["cab_proveedor"] = _cab.get("proveedor", "")
    st.session_state["cab_ruc"]       = _cab.get("ruc", "")
    st.session_state["cab_serie"]     = _cab.get("serie_numero", "")
    st.session_state["cab_fecha"]     = _cab.get("fecha", "")
    st.session_state["cab_total"]     = float(_cab.get("total") or 0.0)

    # Guardar en historial
    cab = result.get("cabecera", {})
    st.session_state.history.append({
        "Fecha/Hora":   result["timestamp"],
        "Archivo":      result["filename"],
        "Proveedor":    cab.get("proveedor", "—"),
        "RUC":          cab.get("ruc", "—"),
        "Serie-Número": cab.get("serie_numero", "—"),
        "Total (S/)":   cab.get("total", "—"),
        "Productos":    len(result.get("productos", [])),
        "Fuente":       "🟢 QR" if result.get("fuente_cabecera") == "qr" else "🟡 IA",
    })

    st.success("✅ ¡Factura procesada!")


# ════════════════════════════════════════════════════════════════════════════
# RESULTADOS
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.result:
    result = st.session_state.result
    cab = result.get("cabecera", {})
    fuente = result.get("fuente_cabecera", "ocr")

    st.divider()
    st.subheader("📄 Resultados")

    # ── Badge de origen de cabecera ──────────────────────────────────────
    if fuente == "qr":
        st.markdown(
            '<span class="badge-qr">🟢 Cabecera desde QR SUNAT — datos exactos</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="badge-ocr">🟡 Cabecera inferida por IA — revisa los datos</span>',
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Sección cabecera editable ─────────────────────────────────────────
    # Los valores vienen de session_state (pre-seteados al procesar).
    # No se usa value= para evitar el conflicto clásico de Streamlit con keys fijas.
    with st.expander("📋 Cabecera de la factura (editable)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cab["proveedor"] = st.text_input("Proveedor", key="cab_proveedor")
            cab["ruc"]       = st.text_input("RUC",       key="cab_ruc")
        with c2:
            cab["serie_numero"] = st.text_input("Serie-Número",  key="cab_serie")
            cab["fecha"]        = st.text_input("Fecha emisión", key="cab_fecha")
        with c3:
            cab["total"] = st.number_input(
                "Total (S/)", min_value=0.0, format="%.2f", key="cab_total"
            )
            if result.get("qr"):
                st.markdown(
                    f"**IGV:** S/ {result['qr'].get('monto_igv', '—')}"
                )

    st.markdown("")

    # ── Tabs: productos + OCR ─────────────────────────────────────────────
    tab_prod, tab_ocr = st.tabs(["📦 Productos ✏️", "🔍 Texto OCR"])

    # Tab productos
    with tab_prod:
        if result.get("claude_error"):
            st.error(f"Error al extraer productos: {result['claude_error']}")

        st.caption("✏️ Haz clic en cualquier celda para editar · ＋ agrega fila · ✕ elimina")

        # El key combina invoice_version (reset por factura) y edit_version
        # (reset por recalculación de subtotal), para limpiar el delta interno
        # del data_editor en el momento correcto.
        editor_key = (
            f"product_editor"
            f"_{st.session_state['invoice_version']}"
            f"_{st.session_state['edit_version']}"
        )

        edited_raw: pd.DataFrame = st.data_editor(
            st.session_state["products_df"],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "descripcion": st.column_config.TextColumn(
                    "Descripción", width="large", required=True
                ),
                "cantidad": st.column_config.NumberColumn(
                    "Cantidad", min_value=0, step=1, format="%g"
                ),
                "precio_unitario": st.column_config.NumberColumn(
                    "Precio Unit. (S/)", min_value=0.0, format="%.2f"
                ),
                "subtotal": st.column_config.NumberColumn(
                    "Subtotal (S/)", min_value=0.0, format="%.2f"
                ),
            },
            key=editor_key,
        )

        # Aplicar reglas de recalculación leyendo el delta de este rerun
        edited_df, hubo_recalculo = _apply_subtotal_rules(
            edited_raw, st.session_state["products_df"], editor_key
        )

        # Si algo cambió: actualizar products_df y resetear el key del editor
        if not edited_raw.reset_index(drop=True).equals(
            st.session_state["products_df"].reset_index(drop=True)
        ):
            st.session_state["products_df"] = edited_df.copy()
            st.session_state["edit_version"] += 1
            if hubo_recalculo:
                # Rerun inmediato para que la celda subtotal muestre el nuevo valor
                st.rerun()

        # Totales
        if not edited_df.empty and "subtotal" in edited_df.columns:
            suma = pd.to_numeric(edited_df["subtotal"], errors="coerce").sum()
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Ítems", len(edited_df))
            mc2.metric("Suma subtotales (S/)", f"{suma:,.2f}")
            total_cab = cab.get("total")
            if total_cab:
                try:
                    diff = suma - float(total_cab)
                    mc3.metric(
                        "Diferencia vs. total factura",
                        f"{diff:+,.2f}",
                        help="Diferencia entre suma de subtotales y total de cabecera.",
                    )
                except (ValueError, TypeError):
                    pass

        st.divider()

        # Exportar
        st.markdown("**Exportar**")
        # Nombre del archivo usa la serie-número ya editada por el usuario
        serie_slug = (
            (cab.get("serie_numero") or "export")
            .strip().replace("-", "_").replace("/", "_")
        ) or "export"

        col_xlsx, col_csv = st.columns(2)
        with col_xlsx:
            st.download_button(
                label="📥 Descargar Excel (.xlsx)",
                data=to_excel_bytes(edited_df, cabecera=cab),
                file_name=f"factura_{serie_slug}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_csv:
            st.download_button(
                label="📄 Descargar CSV",
                data=to_csv_string(edited_df, cabecera=cab).encode("utf-8-sig"),
                file_name=f"factura_{serie_slug}.csv",
                mime="text/csv",
                use_container_width=True,
            )

    # Tab OCR
    with tab_ocr:
        if result.get("ocr_error"):
            st.error(f"Error OCR: {result['ocr_error']}")
        ocr_text = result.get("ocr_text", "")
        if ocr_text:
            st.text_area(
                "Texto extraído por EasyOCR (entrada de Claude)",
                value=ocr_text,
                height=350,
                disabled=True,
            )
        else:
            st.info("Sin texto OCR disponible.")


# ════════════════════════════════════════════════════════════════════════════
# HISTORIAL DE SESIÓN
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.history:
    st.divider()
    st.subheader("📜 Historial de la sesión")
    st.caption("Se borra al recargar la página.")
    st.dataframe(
        pd.DataFrame(st.session_state.history),
        use_container_width=True,
        hide_index=True,
    )
