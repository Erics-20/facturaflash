"""Extrae texto de una imagen usando EasyOCR en español."""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from PIL.Image import Image

# Singleton: se inicializa una sola vez por sesión para no recargar modelos
_ocr_reader = None


def _get_reader():
    global _ocr_reader
    if _ocr_reader is None:
        # Fix SSL en Python 3.12 framework (macOS) — certifi provee los root certs
        try:
            import certifi, os
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            pass
        import easyocr
        # 'es' incluye español; gpu=False para CPU-only
        _ocr_reader = easyocr.Reader(['es'], gpu=False, verbose=False)
    return _ocr_reader


def extract_text(image: "Image") -> str:
    """
    Corre EasyOCR sobre la imagen PIL y retorna el texto plano.

    El texto mantiene el orden de lectura de arriba a abajo.
    Lanza RuntimeError si EasyOCR no está disponible o falla.
    """
    try:
        import easyocr  # noqa: F401 — validar disponibilidad
    except ImportError:
        raise RuntimeError(
            "EasyOCR no está instalado. Ejecuta: pip install easyocr"
        )

    try:
        import numpy as np
    except ImportError:
        raise RuntimeError("numpy no está instalado.")

    reader = _get_reader()
    img_array = np.array(image.convert("RGB"))

    # detail=1 devuelve (bbox, texto, confianza); paragraph=False preserva líneas
    results = reader.readtext(img_array, detail=1, paragraph=False)

    # Ordenar por posición vertical (coordenada Y del bbox) para mantener orden
    results_sorted = sorted(results, key=lambda r: r[0][0][1])

    lines = [text for (_bbox, text, _conf) in results_sorted if text.strip()]
    return "\n".join(lines)


def mock_ocr_text() -> str:
    """Texto OCR simulado para modo demo."""
    return (
        "DISTRIBUIDORA ALIMENTOS DEL PERU SAC\n"
        "RUC: 20100030798\n"
        "FACTURA ELECTRONICA F001-00042301\n"
        "Fecha: 15/06/2024\n"
        "--------------------------------------------\n"
        "DESCRIPCION          CANT  P.UNIT  SUBTOTAL\n"
        "--------------------------------------------\n"
        "ACEITE VEGETAL 1L      24   5.50    132.00\n"
        "AZUCAR RUBIA 1KG       12   3.80     45.60\n"
        "ARROZ EXTRA 5KG         6  18.00    108.00\n"
        "LECHE EVAP. 400G       48   2.90    139.20\n"
        "FIDEOS SPAGHETTI 500G  30   2.20     66.00\n"
        "--------------------------------------------\n"
        "OP. GRAVADA:                        473.85\n"
        "IGV 18%:                             84.51\n"
        "TOTAL:                              558.36\n"
    )
