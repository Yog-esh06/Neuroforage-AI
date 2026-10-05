"""OCR engines behind one interface. Engine is chosen by OCR_ENGINE (auto|rapidocr|tesseract|none)."""
from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass

import numpy as np

from app.core.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class OCRLine:
    text: str
    bbox: list[float]  # [x0, y0, x1, y1] in the coordinate space of the input image
    confidence: float  # 0..1


class OCRUnavailable(RuntimeError):
    pass


class _RapidOCR:
    name = "rapidocr"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR

        self._engine = RapidOCR()
        self._lock = threading.Lock()  # onnxruntime sessions are fine, the wrapper keeps state

    def run(self, image: np.ndarray) -> list[OCRLine]:
        with self._lock:
            result, _ = self._engine(image)
        lines: list[OCRLine] = []
        for box, text, conf in result or []:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            text = str(text).strip()
            if text:
                lines.append(OCRLine(text, [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))], float(conf)))
        return lines


class _Tesseract:
    name = "tesseract"

    def __init__(self):
        import pytesseract

        if not shutil.which("tesseract"):
            raise OCRUnavailable("tesseract binary not on PATH")
        self._pt = pytesseract

    def run(self, image: np.ndarray) -> list[OCRLine]:
        data = self._pt.image_to_data(image, output_type=self._pt.Output.DICT)
        lines: dict[tuple, list[int]] = {}
        for i, txt in enumerate(data["text"]):
            if txt.strip() and float(data["conf"][i]) >= 0:
                lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
        out = []
        for idxs in lines.values():
            text = " ".join(data["text"][i] for i in idxs)
            x0 = min(data["left"][i] for i in idxs)
            y0 = min(data["top"][i] for i in idxs)
            x1 = max(data["left"][i] + data["width"][i] for i in idxs)
            y1 = max(data["top"][i] + data["height"][i] for i in idxs)
            conf = sum(float(data["conf"][i]) for i in idxs) / len(idxs) / 100.0
            out.append(OCRLine(text, [float(x0), float(y0), float(x1), float(y1)], conf))
        return out


_engine = None
_engine_lock = threading.Lock()
_engine_error: str | None = None


def get_ocr_engine():
    """Lazy singleton. Returns None if OCR is disabled/unavailable (caller records a warning)."""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        choice = get_settings().ocr_engine.lower()
        if choice == "none":
            _engine_error = "OCR disabled (OCR_ENGINE=none)"
            return None
        order = {"auto": ["rapidocr", "tesseract"], "rapidocr": ["rapidocr"], "tesseract": ["tesseract"]}.get(choice, ["rapidocr"])
        errors = []
        for name in order:
            try:
                _engine = _RapidOCR() if name == "rapidocr" else _Tesseract()
                log.info("OCR engine ready: %s", name)
                return _engine
            except Exception as e:  # ImportError, OCRUnavailable, model load problems
                errors.append(f"{name}: {e}")
        _engine_error = "; ".join(errors)
        log.warning("No OCR engine available: %s", _engine_error)
        return None


def ocr_status() -> dict:
    eng = get_ocr_engine()
    return {"available": eng is not None, "engine": getattr(eng, "name", None), "error": _engine_error}


def run_ocr(image: np.ndarray) -> list[OCRLine]:
    eng = get_ocr_engine()
    if eng is None:
        raise OCRUnavailable(_engine_error or "No OCR engine available")
    return eng.run(image)
