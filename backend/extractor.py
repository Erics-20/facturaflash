"""Llama a la API de Anthropic para extraer cabecera y productos del texto OCR."""

from __future__ import annotations
import json
import re
import os

from ai.prompts import EXTRACTION_PROMPT, PRODUCTS_ONLY_PROMPT

MODEL_ID = "claude-haiku-4-5-20251001"

_REQUIRED_PRODUCT_FIELDS = {"descripcion", "cantidad", "precio_unitario", "subtotal"}


def _get_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError(
            "La librería 'anthropic' no está instalada. Ejecuta: pip install anthropic"
        )
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY no está configurada. "
            "Crea un archivo .env con ANTHROPIC_API_KEY=tu_key."
        )
    return Anthropic(api_key=api_key)


def process_invoice(ocr_text: str, qr_data: dict | None = None) -> dict:
    """
    Punto de entrada principal del pipeline de extracción.

    Lógica de fusión QR + OCR:
      - Con QR: cabecera exacta del QR (ruc, serie, fecha, total) +
                Claude extrae proveedor y productos del OCR.
      - Sin QR: Claude infiere cabecera completa + productos del OCR.

    Returns:
        {
          "cabecera": {proveedor, ruc, serie_numero, fecha, total},
          "productos": [{descripcion, cantidad, precio_unitario, subtotal}, ...],
          "fuente_cabecera": "qr" | "ocr"
        }
    """
    if qr_data:
        # ── Cabecera desde QR (datos exactos de SUNAT) ───────────────────
        cabecera = {
            "proveedor":    "",   # el QR no lo trae; Claude lo aporta abajo
            "ruc":          qr_data.get("ruc_emisor", ""),
            "serie_numero": qr_data.get("serie_numero", ""),
            "fecha":        qr_data.get("fecha_emision", ""),
            "total":        _to_number(qr_data.get("monto_total")),
        }
        # Claude extrae proveedor + productos (prompt más corto)
        productos, proveedor = _extract_products_and_supplier(ocr_text)
        cabecera["proveedor"] = proveedor
        return {"cabecera": cabecera, "productos": productos, "fuente_cabecera": "qr"}
    else:
        # ── Cabecera + productos completos desde OCR vía Claude ──────────
        result = extract_invoice(ocr_text, qr_data=None)
        result["fuente_cabecera"] = "ocr"
        return result


def extract_invoice(ocr_text: str, qr_data: dict | None = None) -> dict:
    """
    Envía el texto OCR a Claude y retorna cabecera + productos como JSON validado.

    Args:
        ocr_text: texto crudo extraído por EasyOCR.
        qr_data:  dict con datos del QR (None si no se detectó QR).

    Returns:
        Dict con claves:
          - "cabecera": {proveedor, ruc, serie_numero, fecha, total}
          - "productos": [{descripcion, cantidad, precio_unitario, subtotal}, ...]

    Raises:
        ValueError: si la API key falta.
        RuntimeError: si la respuesta de Claude no es JSON parseable.
    """
    client = _get_client()

    context_parts = []
    if qr_data:
        qr_clean = {k: v for k, v in qr_data.items() if k != "qr_raw"}
        context_parts.append(
            f"Datos del QR SUNAT (usar para cabecera cuando estén disponibles):\n"
            f"{json.dumps(qr_clean, ensure_ascii=False)}"
        )
    context_parts.append(f"Texto OCR de la factura:\n{ocr_text}")

    full_content = EXTRACTION_PROMPT + "\n\n" + "\n\n".join(context_parts)

    message = client.messages.create(
        model=MODEL_ID,
        max_tokens=2048,
        messages=[{"role": "user", "content": full_content}],
    )

    raw = message.content[0].text.strip()
    return _parse_and_validate(raw)


def _extract_products_and_supplier(ocr_text: str) -> tuple[list[dict], str]:
    """
    Llama a Claude con el prompt de solo-productos para facturas con QR.
    Retorna (lista_productos, nombre_proveedor).
    """
    client = _get_client()
    full_content = PRODUCTS_ONLY_PROMPT + f"\n\nTexto OCR de la factura:\n{ocr_text}"

    message = client.messages.create(
        model=MODEL_ID,
        max_tokens=2048,
        messages=[{"role": "user", "content": full_content}],
    )

    raw = message.content[0].text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Claude no devolvió JSON válido.\nRespuesta:\n{raw[:500]}") from exc

    proveedor = str(data.get("proveedor") or "").strip()
    productos_raw = data.get("productos") or []
    productos = [
        {
            "descripcion":     str(item.get("descripcion") or "").strip(),
            "cantidad":        _to_number(item.get("cantidad")),
            "precio_unitario": _to_number(item.get("precio_unitario")),
            "subtotal":        _to_number(item.get("subtotal")),
        }
        for item in productos_raw
        if isinstance(item, dict)
    ]
    return productos, proveedor


def _parse_and_validate(raw: str) -> dict:
    """Parsea la respuesta de Claude y valida la estructura esperada."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Claude no devolvió JSON válido.\nRespuesta:\n{raw[:500]}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Se esperaba un objeto JSON, se recibió: {type(data).__name__}")

    # Normalizar cabecera
    cabecera_raw = data.get("cabecera") or {}
    cabecera = {
        "proveedor":    str(cabecera_raw.get("proveedor") or "").strip(),
        "ruc":          str(cabecera_raw.get("ruc") or "").strip(),
        "serie_numero": str(cabecera_raw.get("serie_numero") or "").strip(),
        "fecha":        str(cabecera_raw.get("fecha") or "").strip(),
        "total":        _to_number(cabecera_raw.get("total")),
    }

    # Normalizar productos
    productos_raw = data.get("productos") or []
    productos: list[dict] = []
    for item in productos_raw:
        if not isinstance(item, dict):
            continue
        productos.append({
            "descripcion":     str(item.get("descripcion") or "").strip(),
            "cantidad":        _to_number(item.get("cantidad")),
            "precio_unitario": _to_number(item.get("precio_unitario")),
            "subtotal":        _to_number(item.get("subtotal")),
        })

    return {"cabecera": cabecera, "productos": productos}


def _to_number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


# ── Compatibilidad con código existente que llama extract_products ────────────

def extract_products(ocr_text: str, qr_data: dict | None = None) -> list[dict]:
    """Wrapper de compatibilidad — retorna solo la lista de productos."""
    result = extract_invoice(ocr_text, qr_data)
    return result["productos"]


def extract_products_demo() -> list[dict]:
    """Datos de productos simulados para el modo demo."""
    return [
        {"descripcion": "ACEITE VEGETAL 1L",    "cantidad": 24, "precio_unitario": 5.50,  "subtotal": 132.00},
        {"descripcion": "AZUCAR RUBIA 1KG",     "cantidad": 12, "precio_unitario": 3.80,  "subtotal":  45.60},
        {"descripcion": "ARROZ EXTRA 5KG",      "cantidad":  6, "precio_unitario": 18.00, "subtotal": 108.00},
        {"descripcion": "LECHE EVAP. 400G",     "cantidad": 48, "precio_unitario":  2.90, "subtotal": 139.20},
        {"descripcion": "FIDEOS SPAGHETTI 500G","cantidad": 30, "precio_unitario":  2.20, "subtotal":  66.00},
    ]
