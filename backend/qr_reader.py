"""Lee el código QR SUNAT de una imagen y devuelve los campos como dict."""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PIL.Image import Image

_TIPO_COMPROBANTE = {
    "01": "Factura",
    "03": "Boleta de Venta",
    "07": "Nota de Crédito",
    "08": "Nota de Débito",
}


def extract_qr_data(image: "Image") -> dict | None:
    """
    Decodifica el QR SUNAT de una imagen PIL.

    Retorna un dict con claves: ruc_emisor, tipo_comprobante, tipo_label,
    serie, numero, serie_numero, fecha_emision, monto_igv, monto_total,
    hash_cpe, qr_raw.

    Si no se encuentra QR o hay un error, retorna None (sin lanzar excepción).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    img_rgb = image.convert("RGB")
    arr = __import__("numpy").array(img_rgb)
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    det = cv2.QRCodeDetector()

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 5
    )
    # Dos variantes de unsharp: suave (sigma=3) y agresiva (sigma=1)
    blur3 = cv2.GaussianBlur(gray, (0, 0), 3)
    unsharp_soft = cv2.addWeighted(gray, 1.5, blur3, -0.5, 0)
    blur1 = cv2.GaussianBlur(gray, (0, 0), 1)
    unsharp_hard = cv2.addWeighted(gray, 2.5, blur1, -1.5, 0)

    for scale in (1.0, 2.0, 3.0, 4.0):
        for base in (gray, adapt, clahe, unsharp_soft, unsharp_hard, bgr):
            candidate = cv2.resize(
                base, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC
            )
            data, _, _ = det.detectAndDecode(candidate)
            if data:
                return _parse_sunat_qr(data)

    return None


def _parse_sunat_qr(qr_raw: str) -> dict:
    """Parsea el texto crudo del QR SUNAT en un dict normalizado."""
    parts = [p.strip() for p in qr_raw.split("|")]

    # Formato nuevo (≥9 campos): ruc|tipo|serie|numero|igv|total|fecha|tipo_doc|ruc_receptor|hash...
    # Formato antiguo (7 campos): ruc|tipo|serie-numero|fecha|igv|total|hash
    if len(parts) >= 9 and not parts[2].startswith("F0") and len(parts[3]) > 5:
        # Podría ser el formato antiguo con serie-numero combinado
        pass

    if len(parts) >= 8 and len(parts[2]) <= 5:
        # Formato nuevo: serie y número separados
        ruc_emisor = parts[0]
        tipo_comp = parts[1]
        serie = parts[2]
        numero = parts[3]
        igv = parts[4]
        total = parts[5]
        fecha = parts[6]
        hash_cpe = parts[9] if len(parts) > 9 else ""
    else:
        # Formato antiguo: serie-numero combinados en parts[2]
        ruc_emisor = parts[0]
        tipo_comp = parts[1]
        serie_num = parts[2]
        fecha = parts[3] if len(parts) > 3 else ""
        igv = parts[4] if len(parts) > 4 else ""
        total = parts[5] if len(parts) > 5 else ""
        hash_cpe = parts[6] if len(parts) > 6 else ""
        # Separar serie y número si vienen juntos (e.g. "F001-00042301")
        if "-" in serie_num:
            serie, numero = serie_num.split("-", 1)
        else:
            serie = serie_num
            numero = ""

    serie_numero = f"{serie}-{numero}" if numero else serie

    return {
        "ruc_emisor": ruc_emisor,
        "tipo_comprobante": tipo_comp,
        "tipo_label": _TIPO_COMPROBANTE.get(tipo_comp, "Comprobante"),
        "serie": serie,
        "numero": numero,
        "serie_numero": serie_numero,
        "fecha_emision": _normalize_date(fecha),
        "monto_igv": igv,
        "monto_total": total,
        "hash_cpe": hash_cpe,
        "qr_raw": qr_raw,
    }


def _normalize_date(fecha: str) -> str:
    """Normaliza fecha a YYYY-MM-DD si viene en DD/MM/YYYY u otros formatos."""
    if not fecha:
        return ""
    # Quitar parte de hora si existe
    fecha = fecha.split(" ")[0].strip()
    if "/" in fecha:
        parts = fecha.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            # DD/MM/YYYY → YYYY-MM-DD
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return fecha


def mock_qr_data() -> dict:
    """Datos QR de ejemplo para modo demo."""
    return {
        "ruc_emisor": "20100030798",
        "tipo_comprobante": "01",
        "tipo_label": "Factura",
        "serie": "F001",
        "numero": "00042301",
        "serie_numero": "F001-00042301",
        "fecha_emision": "2024-06-15",
        "monto_igv": "84.51",
        "monto_total": "558.36",
        "hash_cpe": "DEMO_HASH_XYZ789ABC123",
        "qr_raw": "20100030798|01|F001|00042301|84.51|558.36|2024-06-15|6|10439876543|DEMO_HASH_XYZ789ABC123",
    }
