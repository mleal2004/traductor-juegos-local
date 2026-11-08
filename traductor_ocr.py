"""Traductor OCR (japonés → español): lee el texto de la ventana de un juego y lo traduce encima, en vivo.

Uso:   python traductor_ocr.py
       python traductor_ocr.py --ventana "parte del título" [--auto]

· Elige la ventana en la lista: la vista previa es en tiempo real y funciona aunque otra app la tape.
· Arrastra sobre la vista para marcar dónde sale el texto (por ejemplo, el cuadro de diálogo).
· Pulsa «Iniciar traducción»: la traducción aparece en el panel y sobre el juego (si la ventana está visible).

Todo corre en tu equipo (modelos en ./modelo_ocr y ./modelo_nllb), sin internet.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

import customtkinter as ctk
import numpy as np
from PIL import Image, ImageGrab, ImageTk

sys.path.insert(0, str(Path(__file__).parent))
import deteccion
import idiomas

RAIZ = Path(__file__).parent
RUTA = {"ocr": RAIZ / "modelo_ocr"}   # carpeta del modelo de OCR en uso
CONFIG = Path(__file__).parent / "traductor_ocr_config.json"
CONFIG_VIEJA = Path(__file__).parent / "traductor_ocr_regiones.json"
user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
TRANSPARENTE = "#ff00ff"
TITULO_APP = "Traductor OCR"

# Paleta
BG, SURF, SURF2, BORDE = "#0d0f13", "#151922", "#1c212c", "#2a3140"
TXT, MUTED = "#e8ebf2", "#8791a7"
ACC, ACC_H, OK, WARN, BAD = "#6f8cff", "#8ba2ff", "#3ddc97", "#ffb454", "#ff6b6b"


# ═══════════════════════════════════════════════════════════════ OCR
_ocr = None


_ocr_lock = threading.Lock()


def cargar_ocr():
    global _ocr
    with _ocr_lock:
        if _ocr is None:
            import torch
            from transformers import AutoImageProcessor, VisionEncoderDecoderModel
            ruta = RUTA["ocr"]
            proc = AutoImageProcessor.from_pretrained(str(ruta))
            modelo = VisionEncoderDecoderModel.from_pretrained(str(ruta)).eval()
            vocab = [l.rstrip("\n") for l in open(ruta / "vocab.txt", encoding="utf-8")]
            _ocr = (proc, modelo, vocab, torch)
        return _ocr


# ═══════════════════════════════════════════════════════════════ Catálogo de modelos
MODELOS = [
    dict(id="ocr_manga", tipo="ocr", nombre="manga-ocr base", clave="pytorch_model.bin", mb=444, carpeta="modelo_ocr",
         desc="Lee texto japonés de juegos y manga. Es el OCR que usa el programa.", repo="kha-white/manga-ocr-base",
         patrones=["*.json", "*.txt", "*.bin"], lic="Apache 2.0"),
    dict(id="nllb_600m", tipo="trad", nombre="NLLB-200 · 600M  (ligero)", clave="model.bin", mb=700, carpeta="modelos/nllb_600m",
         desc="Rápido y liviano; la calidad de traducción es algo menor.", repo="JustFrederik/nllb-200-distilled-600M-ct2-int8",
         extra=[("facebook/nllb-200-distilled-600M", ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"])],
         lic="CC-BY-NC 4.0 (no comercial)"),
    dict(id="nllb_1_3b", tipo="trad", nombre="NLLB-200 · 1.3B  (recomendado)", clave="model.bin", mb=1401, carpeta="modelo_nllb",
         desc="Buen equilibrio entre calidad y velocidad.", repo="OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
         lic="CC-BY-NC 4.0 (no comercial)"),
    dict(id="nllb_3_3b", tipo="trad", nombre="NLLB-200 · 3.3B  (máxima calidad)", clave="model.bin", mb=3379, carpeta="modelos/nllb_3_3b",
         desc="La mejor calidad; es más lenta y usa unos 4 GB de memoria.", repo="OpenNMT/nllb-200-3.3B-ct2-int8",
         lic="CC-BY-NC 4.0 (no comercial)"),
]
POR_ID = {m["id"]: m for m in MODELOS}
DEFECTO = {"ocr": "ocr_manga", "trad": "nllb_1_3b"}
TIPOS = {"ocr": "OCR · lee el texto de la pantalla", "trad": "Traducción · 200 idiomas"}


def carpeta_de(m):
    return RAIZ / m["carpeta"]


def instalado(m):
    c = carpeta_de(m)
    return (c / m["clave"]).exists() and (m["tipo"] == "ocr" or (c / "tokenizer.json").exists())


def tam_carpeta(c):
    t = 0
    for d, _, fs in os.walk(c):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return t


def modelo_elegido(cfg, tipo):
    """Modelo en uso para ese tipo: el elegido si está instalado; si no, cualquier instalado del tipo."""
    m = POR_ID.get(cfg["opciones"].get("modelo_" + tipo, DEFECTO[tipo]))
    if m and m["tipo"] == tipo and instalado(m):
        return m
    return next((x for x in MODELOS if x["tipo"] == tipo and instalado(x)), None)


def aplicar_modelo(tipo, m):
    """Deja de usar el modelo anterior y prepara el nuevo (se carga en el siguiente uso)."""
    global _ocr
    if tipo == "ocr":
        _ocr = None
        if m:
            RUTA["ocr"] = carpeta_de(m)
    else:
        import traducir
        import traductor_local
        traducir._tok = traducir._trad = None
        traductor_local._cache.clear()
        if m:
            traducir.MODELO = carpeta_de(m)


def descargar_modelo(m):
    """Descarga el modelo (y los archivos extra) a su carpeta. Se puede reanudar si se corta."""
    from huggingface_hub import snapshot_download
    c = carpeta_de(m)
    c.mkdir(parents=True, exist_ok=True)
    snapshot_download(m["repo"], local_dir=str(c), allow_patterns=m.get("patrones"))
    for repo, pats in m.get("extra", []):
        snapshot_download(repo, local_dir=str(c), allow_patterns=pats)


def fmt_mb(mb):
    return f"{mb / 1024:.1f} GB" if mb >= 1000 else f"{mb:.0f} MB"


def limpiar(s: str) -> str:
    """Quita la basura típica que mete el OCR al cortar entre letras (signos ASCII sueltos)."""
    s = s.replace("…", "...").replace(" ", "")
    s = re.sub(r"[,'\"`:;|#()\\^_\[\]{}<>]", "", s)
    s = re.sub(r"(?<!\.)\.{1,2}(?!\.)", "", s)
    s = re.sub(r"\.{3,}", "…", s)
    s = re.sub(r"[!?](?=[぀-鿿])", "", s)
    s = s.replace("*", "")
    s = re.sub(r"(?<=[^\n「『（(])[「『]", "", s)
    if len(re.findall(r"[぀-ヿ一-鿿]", s)) >= 3:
        s = re.sub(r"[A-Za-z0-9]", "", s)
    return s


def leer_lote(imgs) -> list:
    """OCR de varias imágenes pequeñas a la vez."""
    if not imgs:
        return []
    proc, modelo, vocab, torch = cargar_ocr()
    pv = proc([i.convert("L").convert("RGB") for i in imgs], return_tensors="pt").pixel_values
    with torch.no_grad():
        todos = modelo.generate(pv, max_length=60)
    res = []
    for ids in todos.tolist():
        out = []
        for i in ids:
            if i == 3:      # [SEP]
                break
            if i < 5:       # [PAD] [UNK] [CLS] [MASK]
                continue
            t = vocab[i]
            out.append(t[2:] if t.startswith("##") else t)
        res.append(limpiar("".join(out)))
    return res


def a_cuadrado(img: Image.Image) -> Image.Image:
    """Centra el recorte en un lienzo cuadrado del color de fondo (el modelo trabaja con 224x224)."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    fondo = tuple(int(v) for v in np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0))
    lado = max(img.width, img.height) + 8
    lienzo = Image.new("RGB", (lado, lado), fondo)
    lienzo.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2))
    return lienzo


def _otsu(g: np.ndarray) -> float:
    hist, _ = np.histogram(g, bins=256, range=(0, 256))
    total = g.size
    suma = float((np.arange(256) * hist).sum())
    sb, wb, mx, th = 0.0, 0, 0.0, 128
    for t in range(256):
        wb += hist[t]
        if wb == 0:
            continue
        wf = total - wb
        if wf == 0:
            break
        sb += t * hist[t]
        mb, mf = sb / wb, (suma - sb) / wf
        v = wb * wf * (mb - mf) ** 2
        if v > mx:
            mx, th = v, t
    return th


def mascara_tinta(img: Image.Image) -> np.ndarray:
    g = np.asarray(img.convert("L"), dtype=np.float32)
    m = g > _otsu(g)
    return ~m if m.mean() > 0.5 else m  # la tinta es el color minoritario


def dividir_lineas(img: Image.Image):
    """Separa una región en líneas de texto (proyección horizontal de la tinta)."""
    m = mascara_tinta(img)
    h = m.shape[0]
    filas = m.mean(axis=1) > 0.006
    tramos, ini = [], None
    for y in range(h + 1):
        v = filas[y] if y < h else False
        if v and ini is None:
            ini = y
        elif not v and ini is not None:
            tramos.append([ini, y]); ini = None
    unidos = []
    for t in tramos:
        if unidos and t[0] - unidos[-1][1] < 4:
            unidos[-1][1] = t[1]
        else:
            unidos.append(t)
    lineas = []
    for a, b in unidos:
        if b - a < 8:
            continue
        a, b = max(0, a - 4), min(h, b + 4)
        lineas.append(img.crop((0, a, img.width, b)))
    return lineas


def trocear_linea(img: Image.Image, letras=4):
    """Parte un renglón ancho en tramos de unas 4 letras, cortando por los huecos entre letras."""
    m = mascara_tinta(img)
    h, w = img.height, img.width
    col = m.mean(axis=0) > 0.01
    objetivo, maximo = int(h * 0.75 * letras), int(h * 0.75 * (letras + 2))
    tramos, ini = [], 0
    while ini < w:
        fin = min(w, ini + objetivo)
        if fin < w:
            corte = None
            for x in range(fin, min(w, ini + maximo)):
                if not col[x]:
                    corte = x
                    break
            fin = corte if corte is not None else min(w, ini + maximo)
        if col[ini:fin].any():
            tramos.append(img.crop((max(0, ini - 1), 0, min(w, fin + 1), h)))
        ini = fin
    return tramos


def leer_linea(img: Image.Image) -> str:
    return "".join(leer_lote([a_cuadrado(t) for t in trocear_linea(img)]))


FIN_FRASE = "。！？!?…」』）♪"


def ocr_manga(img: Image.Image) -> str:
    """OCR de japonés con manga-ocr. Las líneas se unen si la frase continúa; si no, se separan con salto."""
    out = ""
    for l in dividir_lineas(img):
        t = leer_linea(l)
        if t:
            out += ("\n" if out and out[-1] in FIN_FRASE else "") + t
    return out


# ── OCR de Windows (cualquier idioma que tenga su paquete de OCR instalado en Windows)
class OcrWindows:
    def __init__(self):
        self.p, self.lock, self.instalados = None, threading.Lock(), None

    def _pedir(self, linea):
        with self.lock:
            if self.p is None or self.p.poll() is not None:
                self.p = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(RAIZ / "ocr_windows.ps1")],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                    creationflags=0x08000000)   # sin ventana de consola
            self.p.stdin.write(linea + "\n")
            self.p.stdin.flush()
            return json.loads(self.p.stdout.readline() or "{}")

    def cargar_idiomas(self):
        try:
            self.instalados = self._pedir("IDIOMAS|-").get("idiomas", [])
        except Exception:
            self.instalados = []
        return self.instalados

    def etiqueta(self, origen):
        """Etiqueta de Windows (p. ej. 'en-US') si ese idioma tiene OCR instalado; None si no."""
        base = idiomas.WINDOWS.get(origen)
        if not base or self.instalados is None:
            return None
        return next((t for t in self.instalados if t.lower().startswith(base.lower())), None)

    def leer_lineas(self, img, origen):
        """Lee todo el fotograma y devuelve cada línea con su posición: [(texto, (x0, y0, x1, y1))]."""
        tag = self.etiqueta(origen)
        if not tag:
            raise RuntimeError("Windows no tiene OCR para " + idiomas.nombre(origen))
        ruta = os.path.join(tempfile.gettempdir(), f"traductor_ocr_{os.getpid()}_f.png")
        img.save(ruta)
        r = self._pedir(f"L|{tag}|{ruta}")
        if "error" in r:
            raise RuntimeError(r["error"])
        lineas = r.get("lineas", [])
        lineas = [lineas] if isinstance(lineas, dict) else lineas
        sin_espacios = origen in idiomas.SIN_ESPACIOS
        out = []
        for l in lineas:
            t = l.get("t", "").replace(" ", "") if sin_espacios else l.get("t", "").strip()
            if t:
                out.append((t, (l["x"], l["y"], l["x"] + l["w"], l["y"] + l["h"])))
        return out

    def leer(self, img, origen):
        tag = self.etiqueta(origen)
        if not tag:
            raise RuntimeError("Windows no tiene OCR para " + idiomas.nombre(origen))
        if img.height < 90:   # el OCR de Windows lee mejor el texto grande
            f = 90 / img.height
            img = img.resize((int(img.width * f), 90), Image.LANCZOS)
        ruta = os.path.join(tempfile.gettempdir(), f"traductor_ocr_{os.getpid()}.png")
        img.save(ruta)
        r = self._pedir(f"{tag}|{ruta}")
        if "error" in r:
            raise RuntimeError(r["error"])
        sin_espacios = origen in idiomas.SIN_ESPACIOS
        out = ""
        for l in (x.strip() for x in r.get("text", "").split("\n")):
            if not l:
                continue
            l = l.replace(" ", "") if sin_espacios else l
            sep = "\n" if (out and out[-1] in FIN_FRASE + ".:;") else ("" if sin_espacios else " ")
            out += (sep if out else "") + l
        return out


ocr_win = OcrWindows()


def usa_manga(origen):
    """manga-ocr solo se usa para japonés (es el mejor para texto de juegos); el resto, OCR de Windows."""
    return origen == "jpn_Jpan" and instalado(POR_ID["ocr_manga"])


def ocr_region(img: Image.Image, origen="jpn_Jpan") -> str:
    return ocr_manga(img) if usa_manga(origen) else ocr_win.leer(img, origen)


# ── lectura para la detección automática (ver deteccion.py)
def leer_lote_conf(imgs) -> list:
    """Como leer_lote, pero devuelve también la confianza (0–1) de cada lectura."""
    if not imgs:
        return []
    proc, modelo, vocab, torch = cargar_ocr()
    pv = proc([i.convert("L").convert("RGB") for i in imgs], return_tensors="pt").pixel_values
    with torch.no_grad():
        out = modelo.generate(pv, max_length=60, output_scores=True, return_dict_in_generate=True)
    sc = getattr(out, "sequences_scores", None)
    res = []
    for b, ids in enumerate(out.sequences.tolist()):
        toks = []
        for i in ids:
            if i == 3:
                break
            if i < 5:
                continue
            t = vocab[i]
            toks.append(t[2:] if t.startswith("##") else t)
        res.append((limpiar("".join(toks)), float(np.exp(float(sc[b]))) if sc is not None else 1.0))
    return res


def ocr_cajas(crops) -> list:
    """OCR de japonés para varias cajas de texto. Devuelve [(texto, confianza)] en el mismo orden."""
    piezas, dueno = [], []
    for k, c in enumerate(crops):
        # un texto corto se lee entero (más fiable); solo los muy largos se parten en trozos de ~8 letras
        partes = [c] if c.width / max(1, c.height) <= 10 else trocear_linea(c, 8)
        for t in partes:
            piezas.append(a_cuadrado(t))
            dueno.append(k)
    por = [[] for _ in crops]
    for k, lect in zip(dueno, leer_lote_conf(piezas)):
        por[k].append(lect)
    return [("".join(t for t, _ in p), float(np.mean([c for _, c in p])) if p else 0.0) for p in por]


def ocr_ventana(frame, origen):
    """OCR de Windows sobre todo el fotograma: [(texto, (x0, y0, x1, y1))] por línea."""
    return ocr_win.leer_lineas(frame, origen)


def maquetar(es, bbox, estilo, raiz, max_x):
    """Dónde y cómo dibujar la traducción de un texto: (rect, texto con saltos, tamaño, fondo, color, negrita).
    Una línea suelta (p. ej. una opción de menú) puede crecer a la derecha; una frase de varias líneas se ajusta a su caja."""
    bg, fg, tam0, neg = estilo
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    una = bh < tam0 * 1.9
    permitido = max(bw, min(max_x - x0 - 4, int(bw * 1.7) + 50)) if una else bw
    lineas, tam, f = [es], 9, None
    for tam in range(min(tam0 + 2, 42), 8, -1):
        f = tkfont.Font(root=raiz, family="Segoe UI", size=-tam, weight="bold" if neg else "normal")
        lineas, act = [], ""
        for p in es.split():
            prueba = (act + " " + p).strip()
            if f.measure(prueba) > permitido - 12 and act:
                lineas.append(act)
                act = p
            else:
                act = prueba
        lineas.append(act)
        alto = len(lineas) * f.metrics("linespace")
        if (una and len(lineas) == 1) or (not una and alto <= bh + 6):
            break
    ancho = max(f.measure(l) for l in lineas) + 12
    alto = len(lineas) * f.metrics("linespace")
    h_rect = max(bh + 2, alto + 4)
    rect = (x0 - 3, y0 - 1, max(x1 + 3, x0 + ancho), y0 - 1 + h_rect)
    return rect, "\n".join(lineas), tam, bg, fg, neg


def estilo(crop: Image.Image):
    """Imita el aspecto del texto original: color de fondo, color de letra, tamaño y grosor aproximados."""
    a = np.asarray(crop.convert("RGB"), dtype=np.float32)
    m = mascara_tinta(crop)
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    bg = np.median(a[~m] if (~m).any() else a.reshape(-1, 3), axis=0)
    fg = np.median(a[m], axis=0) if m.any() else None
    if fg is None or abs(lum(fg) - lum(bg)) < 70:
        fg = (255, 255, 255) if lum(bg) < 140 else (16, 16, 16)
    lineas = dividir_lineas(crop)
    alto = float(np.median([l.height - 8 for l in lineas])) if lineas else 24.0
    tam = int(max(10, min(42, alto * 0.98)))
    filas = m[m.any(axis=1)]
    negrita = bool(filas.size and filas.mean() > 0.22)
    hexa = lambda c: "#%02x%02x%02x" % tuple(int(v) for v in c)
    return hexa(bg), hexa(fg), tam, negrita


def ajustar(texto, ancho, alto, raiz, tam_max=30, negrita=False):
    """Mayor tamaño de letra (hasta tam_max) con el que el texto cabe en (ancho x alto)."""
    for tam in range(min(tam_max, 40), 8, -1):
        f = tkfont.Font(root=raiz, family="Segoe UI", size=-tam, weight="bold" if negrita else "normal")
        lineas, act = [], ""
        for p in texto.split():
            prueba = (act + " " + p).strip()
            if f.measure(prueba) > ancho - 12 and act:
                lineas.append(act); act = p
            else:
                act = prueba
        lineas.append(act)
        if len(lineas) * f.metrics("linespace") <= alto - 6:
            return tam
    return 9


def firma(crop):
    return np.asarray(crop.convert("L").resize((48, 16)), dtype=np.int16)


# ═══════════════════════════════════════════════════════════════ Windows: ventanas y captura
class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def ventanas():
    res = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        if user32.IsWindowVisible(h) and not user32.IsIconic(h):
            n = user32.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(h, buf, n + 1)
                r = wt.RECT()
                user32.GetWindowRect(h, ctypes.byref(r))
                if (r.right - r.left > 200 and r.bottom - r.top > 120 and buf.value != "Program Manager"
                        and not buf.value.startswith(TITULO_APP)):
                    res.append((h, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return res


def rect_visible(h):
    """Rectángulo visible de la ventana en pantalla (sin el borde invisible de Windows 10/11)."""
    r = wt.RECT()
    try:
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            raise OSError
    except Exception:
        user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def print_window(h):
    """Captura el contenido de la ventana aunque esté tapada por otras (PrintWindow + PW_RENDERFULLCONTENT)."""
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    w, hh = r.right - r.left, r.bottom - r.top
    if w <= 0 or hh <= 0:
        return None, r
    sdc = user32.GetDC(0)
    mdc = gdi32.CreateCompatibleDC(sdc)
    bmp = gdi32.CreateCompatibleBitmap(sdc, w, hh)
    old = gdi32.SelectObject(mdc, bmp)
    ok = user32.PrintWindow(h, mdc, 2)
    bi = BMIH(ctypes.sizeof(BMIH), w, -hh, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * hh * 4)
    gdi32.GetDIBits(mdc, bmp, 0, hh, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(0, sdc)
    if not ok:
        return None, r
    return Image.frombuffer("RGBA", (w, hh), buf, "raw", "BGRA", 0, 1).convert("RGB"), r


def capturar(h):
    """(imagen del área visible, rectángulo en pantalla, modo). Modo: 'directa' o 'pantalla' (respaldo)."""
    l, t, rr, b = rect_visible(h)
    img, wr = print_window(h)
    if img is not None and np.asarray(img.resize((64, 36))).max() > 2:
        ox, oy = max(0, l - wr.left), max(0, t - wr.top)
        return img.crop((ox, oy, min(img.width, ox + (rr - l)), min(img.height, oy + (b - t)))), (l, t, rr, b), "directa"
    try:  # respaldo: foto de la pantalla (solo sirve si la ventana está a la vista)
        return ImageGrab.grab(bbox=(l, t, rr, b), all_screens=True), (l, t, rr, b), "pantalla"
    except Exception:
        return None, (l, t, rr, b), "error"


def visible_en(h, x, y):
    """¿La ventana h está a la vista (no tapada por otra) en el punto de pantalla (x, y)?"""
    p = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
    if not p:
        return False
    return user32.GetAncestor(p, 2) == user32.GetAncestor(h, 2)


class Capturador(threading.Thread):
    """Captura la ventana elegida en segundo plano (vista en tiempo real)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.hwnd, self.frame, self.rect, self.seq, self.modo = None, None, None, 0, "—"
        self.intervalo, self._fin = 0.12, False

    def run(self):
        while not self._fin:
            h = self.hwnd
            if h:
                if not user32.IsWindow(h):
                    self.modo, self.frame = "cerrada", None
                elif user32.IsIconic(h):
                    self.modo = "minimizada"
                else:
                    try:
                        img, rect, modo = capturar(h)
                        if img is not None:
                            self.frame, self.rect, self.modo = img, rect, modo
                            self.seq += 1
                    except Exception:
                        pass
            time.sleep(self.intervalo)

    def parar(self):
        self._fin = True


# ═══════════════════════════════════════════════════════════════ Configuración
def cargar_config():
    cfg = {"ventanas": {}, "opciones": {"capa": True, "estilo": True, "velocidad": "Normal", "ultima": ""}}
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except Exception:
        try:  # migrar el formato anterior {titulo: [zonas]}
            for k, v in json.loads(CONFIG_VIEJA.read_text(encoding="utf-8")).items():
                cfg["ventanas"][k] = {"zonas": v}
        except Exception:
            pass
    return cfg


def guardar_config(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════ Interfaz
VELOCIDADES = {"Rápida": 0.25, "Normal": 0.45, "Ahorro": 0.9}


class ElegirIdioma(ctk.CTkToplevel):
    """Selector de idioma con buscador (202 idiomas)."""

    def __init__(self, app, titulo, actual, al_elegir):
        super().__init__(app, fg_color=BG)
        self.title(titulo)
        self.geometry("460x660+220+70")
        self.actual, self.al_elegir, self.todos = actual, al_elegir, False
        F = lambda s, w="normal": ctk.CTkFont(family="Segoe UI", size=s, weight=w)
        self.F = F
        self.after(250, lambda: (self.lift(), self.focus_force(), self.entrada.focus_set()))
        ctk.CTkLabel(self, text=titulo, font=F(19, "bold"), text_color=TXT, anchor="w").pack(anchor="w", padx=22, pady=(18, 0))
        ctk.CTkLabel(self, text="Escribe para buscar entre los 202 idiomas del modelo", font=F(12), text_color=MUTED, anchor="w").pack(anchor="w", padx=22, pady=(0, 8))
        self.var = ctk.StringVar()
        self.var.trace_add("write", lambda *_: self._filtrar())
        self.entrada = ctk.CTkEntry(self, textvariable=self.var, placeholder_text="Buscar idioma…", height=40, corner_radius=10,
                                    fg_color=SURF2, border_color=BORDE, font=F(14))
        self.entrada.pack(fill="x", padx=20, pady=(0, 10))
        self.lista = ctk.CTkScrollableFrame(self, fg_color=SURF, corner_radius=12)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._filtrar()

    @staticmethod
    def _norm(s):
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")

    def _boton(self, cod):
        sel = cod == self.actual
        ctk.CTkButton(self.lista, text=f"{idiomas.nombre(cod)}   ·   {cod}", anchor="w", height=34, corner_radius=8, font=self.F(13),
                      fg_color=ACC if sel else "transparent", hover_color=ACC_H if sel else BORDE, text_color="#ffffff" if sel else TXT,
                      command=lambda: (self.al_elegir(cod), self.destroy())).pack(fill="x", pady=1, padx=2)

    def _filtrar(self):
        for w in self.lista.winfo_children():
            w.destroy()
        q = self._norm(self.var.get().strip())
        if q:
            hallados = [c for c in idiomas.lista_ordenada() if q in self._norm(idiomas.nombre(c)) or q in c.lower()]
            if not hallados:
                ctk.CTkLabel(self.lista, text="Ningún idioma coincide.", font=self.F(13), text_color=MUTED).pack(pady=20)
            for c in hallados[:80]:
                self._boton(c)
            return
        ctk.CTkLabel(self.lista, text="POPULARES", font=self.F(11, "bold"), text_color=ACC, anchor="w").pack(anchor="w", padx=8, pady=(6, 2))
        for c in idiomas.POPULARES:
            self._boton(c)
        if self.todos:
            ctk.CTkLabel(self.lista, text="TODOS", font=self.F(11, "bold"), text_color=ACC, anchor="w").pack(anchor="w", padx=8, pady=(12, 2))
            for c in idiomas.lista_ordenada()[len(idiomas.POPULARES):]:
                self._boton(c)
        else:
            ctk.CTkButton(self.lista, text="Ver los 202 idiomas…", height=34, corner_radius=8, fg_color=SURF2, hover_color=BORDE, text_color=TXT,
                          font=self.F(12), command=lambda: (setattr(self, "todos", True), self._filtrar())).pack(fill="x", pady=(12, 4), padx=2)


class GestorModelos(ctk.CTkToplevel):
    """Lista los modelos, permite descargarlos, elegir cuál usar y eliminarlos."""

    def __init__(self, app):
        super().__init__(app, fg_color=BG)
        self.app = app
        self.title("Modelos · " + TITULO_APP)
        self.geometry("860x700+120+60")
        self.minsize(760, 560)
        self.after(250, lambda: (self.lift(), self.focus_force()))
        self.descargas = {}
        self.filas = {}
        F = lambda s, w="normal": ctk.CTkFont(family="Segoe UI", size=s, weight=w)
        cab = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0)
        cab.pack(fill="x")
        ctk.CTkLabel(cab, text="Modelos de inteligencia artificial", font=F(20, "bold"), text_color=TXT, anchor="w").pack(anchor="w", padx=24, pady=(16, 0))
        ctk.CTkLabel(cab, text="Se descargan una sola vez y después todo funciona sin internet. Puedes tener varios y cambiar entre ellos cuando quieras.",
                     font=F(12), text_color=MUTED, anchor="w", wraplength=780, justify="left").pack(anchor="w", padx=24, pady=(2, 6))
        self.lbl_uso = ctk.CTkLabel(cab, text="", font=F(12), text_color=ACC, anchor="w")
        self.lbl_uso.pack(anchor="w", padx=24, pady=(0, 14))
        cuerpo = ctk.CTkScrollableFrame(self, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True, padx=14, pady=10)
        for tipo, titulo in TIPOS.items():
            ctk.CTkLabel(cuerpo, text=titulo.upper(), font=F(11, "bold"), text_color=ACC, anchor="w").pack(anchor="w", padx=8, pady=(12, 4))
            for m in (x for x in MODELOS if x["tipo"] == tipo):
                self._fila(cuerpo, m, F)
            if tipo == "ocr":
                self._tarjeta_windows(cuerpo, F)
        self._refrescar()
        self._ciclo()

    def _tarjeta_windows(self, padre, F):
        caja = ctk.CTkFrame(padre, fg_color=SURF, corner_radius=12)
        caja.pack(fill="x", padx=6, pady=5)
        caja.grid_columnconfigure(0, weight=1)
        izq = ctk.CTkFrame(caja, fg_color="transparent")
        izq.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=12)
        l1 = ctk.CTkFrame(izq, fg_color="transparent")
        l1.pack(anchor="w")
        ctk.CTkLabel(l1, text="OCR de Windows (integrado)", font=F(15, "bold"), text_color=TXT).pack(side="left")
        ctk.CTkLabel(l1, text="INTEGRADO", font=F(11, "bold"), corner_radius=8, padx=8, fg_color=ACC, text_color="#ffffff").pack(side="left", padx=10)
        ctk.CTkLabel(izq, text="Lee texto en cualquier idioma que tenga su paquete de OCR instalado en Windows. Se usa para todos los idiomas "
                     "menos el japonés (que usa manga-ocr si está instalado). No hay nada que descargar aquí.",
                     font=F(12), text_color=MUTED, anchor="w", justify="left", wraplength=480).pack(anchor="w", pady=(3, 0))
        self.lbl_win = ctk.CTkLabel(izq, text="", font=F(11), text_color=MUTED, anchor="w", justify="left", wraplength=480)
        self.lbl_win.pack(anchor="w", pady=(3, 0))
        ctk.CTkButton(caja, text="Añadir idiomas de OCR en Windows", width=210, height=34, corner_radius=10, fg_color=SURF2, hover_color=ACC,
                      text_color=TXT, font=F(12), command=lambda: os.startfile("ms-settings:regionlanguage")).grid(row=0, column=1, padx=(8, 16), pady=12)

    def _fila(self, padre, m, F):
        caja = ctk.CTkFrame(padre, fg_color=SURF, corner_radius=12)
        caja.pack(fill="x", padx=6, pady=5)
        caja.grid_columnconfigure(0, weight=1)
        izq = ctk.CTkFrame(caja, fg_color="transparent")
        izq.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=12)
        l1 = ctk.CTkFrame(izq, fg_color="transparent")
        l1.pack(anchor="w")
        ctk.CTkLabel(l1, text=m["nombre"], font=F(15, "bold"), text_color=TXT).pack(side="left")
        chip = ctk.CTkLabel(l1, text="", font=F(11, "bold"), corner_radius=8, padx=8)
        chip.pack(side="left", padx=10)
        ctk.CTkLabel(izq, text=m["desc"], font=F(12), text_color=MUTED, anchor="w", justify="left", wraplength=480).pack(anchor="w", pady=(3, 0))
        info = ctk.CTkLabel(izq, text="", font=F(11), text_color=MUTED, anchor="w", justify="left", wraplength=480)
        info.pack(anchor="w", pady=(3, 0))
        der = ctk.CTkFrame(caja, fg_color="transparent", width=210)
        der.grid(row=0, column=1, sticky="e", padx=(8, 16), pady=12)
        barra = ctk.CTkProgressBar(der, width=190, height=10, progress_color=ACC, fg_color=BORDE)
        lbl = ctk.CTkLabel(der, text="", font=F(12), text_color=TXT)
        b_desc = ctk.CTkButton(der, text="⬇  Descargar", width=190, height=36, corner_radius=10, fg_color=ACC, hover_color=ACC_H, font=F(13, "bold"),
                               command=lambda: self._descargar(m))
        b_usar = ctk.CTkButton(der, text="Usar este", width=190, height=34, corner_radius=10, fg_color=OK, hover_color="#5ae8aa", text_color="#06251a",
                               font=F(13, "bold"), command=lambda: self._usar(m))
        b_borrar = ctk.CTkButton(der, text="Eliminar", width=190, height=30, corner_radius=10, fg_color=SURF2, hover_color=BAD, text_color=TXT,
                                 font=F(12), command=lambda: self._eliminar(m))
        self.filas[m["id"]] = dict(chip=chip, info=info, barra=barra, lbl=lbl, desc=b_desc, usar=b_usar, borrar=b_borrar, estado=None)

    def _estado(self, m):
        d = self.descargas.get(m["id"])
        if d and not d["fin"]:
            return "descargando"
        if d and d["error"] and not instalado(m):
            return "error"
        if not instalado(m):
            return "no"
        en_uso = modelo_elegido(self.app.cfg, m["tipo"])
        return "uso" if en_uso and en_uso["id"] == m["id"] else "si"

    def _refrescar(self):
        total = 0
        for m in MODELOS:
            f, est = self.filas[m["id"]], self._estado(m)
            c = carpeta_de(m)
            tam = tam_carpeta(c) if c.exists() else 0
            total += tam
            if est == "descargando":
                p = min(0.99, tam / (m["mb"] * 1e6))
                f["barra"].set(p)
                f["lbl"].configure(text=f"Descargando… {int(p * 100)} %  ({fmt_mb(tam / 1e6)} de ~{fmt_mb(m['mb'])})")
            f["info"].configure(text=f"Tamaño: ~{fmt_mb(m['mb'])}  ·  Licencia: {m['lic']}  ·  Origen: huggingface.co/{m['repo']}"
                                + (f"\nEn tu equipo: {fmt_mb(tam / 1e6)}  ·  {c}" if instalado(m) else ""))
            if est != f["estado"]:
                f["estado"] = est
                for w in ("barra", "lbl", "desc", "usar", "borrar"):
                    f[w].pack_forget()
                chip = {"uso": ("EN USO", OK, "#06251a"), "si": ("INSTALADO", BORDE, TXT), "no": ("NO INSTALADO", SURF2, MUTED),
                        "descargando": ("DESCARGANDO", WARN, "#2b1a00"), "error": ("ERROR", BAD, "#2b0000")}[est]
                f["chip"].configure(text=chip[0], fg_color=chip[1], text_color=chip[2])
                if est == "descargando":
                    f["barra"].pack(pady=(4, 6)); f["lbl"].pack()
                elif est == "error":
                    f["lbl"].configure(text="Falló: " + (self.descargas[m["id"]]["error"] or ""), text_color=BAD, wraplength=190)
                    f["lbl"].pack(pady=(0, 6)); f["desc"].configure(text="⟳  Reintentar"); f["desc"].pack()
                elif est == "no":
                    f["desc"].configure(text="⬇  Descargar"); f["desc"].pack()
                elif est == "si":
                    f["usar"].pack(pady=(0, 6)); f["borrar"].pack()
                else:   # en uso: no se puede eliminar mientras se usa
                    f["lbl"].configure(text="Es el que está activo", text_color=MUTED, wraplength=0)
                    f["lbl"].pack()
        self.lbl_uso.configure(text=f"Espacio usado por los modelos: {fmt_mb(total / 1e6)}")
        if hasattr(self, "lbl_win"):
            ins = ocr_win.instalados
            self.lbl_win.configure(text="Consultando los idiomas de OCR de Windows…" if ins is None else
                                   ("Idiomas con OCR en este equipo: " + (", ".join(ins) if ins else "ninguno")
                                    + "\nPara más idiomas: Configuración → Hora e idioma → Idioma y región → Añadir un idioma "
                                      "(deja marcado «Reconocimiento óptico de caracteres»). Después reinicia este programa."))

    def _ciclo(self):
        try:
            self._refrescar()
            for m in MODELOS:  # al terminar una descarga, si faltaba ese tipo, se activa solo
                d = self.descargas.get(m["id"])
                if d and d["fin"] and not d["error"] and not d.get("aplicado"):
                    d["aplicado"] = True
                    self.app.modelo_descargado(m)
        except Exception:
            pass
        if self.winfo_exists():
            self.after(600, self._ciclo)

    def _descargar(self, m):
        if self._estado(m) == "descargando":
            return
        est = {"error": None, "fin": False}

        def tarea():
            try:
                descargar_modelo(m)
            except Exception as e:
                est["error"] = (str(e) or e.__class__.__name__)[:90]
            est["fin"] = True
        self.descargas[m["id"]] = est
        threading.Thread(target=tarea, daemon=True).start()
        self._refrescar()

    def _usar(self, m):
        self.app.cfg["opciones"]["modelo_" + m["tipo"]] = m["id"]
        guardar_config(self.app.cfg)
        self.app.cambiar_modelo(m["tipo"])
        self._refrescar()

    def _eliminar(self, m):
        from tkinter import messagebox
        tam = tam_carpeta(carpeta_de(m)) / 1e6
        if messagebox.askyesno("Eliminar modelo", f"¿Eliminar «{m['nombre'].strip()}»?\n\nSe liberarán {fmt_mb(tam)}. Si lo quieres usar después, "
                               "tendrás que descargarlo otra vez.", parent=self):
            shutil.rmtree(carpeta_de(m), ignore_errors=True)
            self.descargas.pop(m["id"], None)
            self.app.faltan = self.app._calc_faltan()
            self._refrescar()


class App(ctk.CTk):
    def __init__(self, buscar=None, auto=False, org=None, dst=None):
        super().__init__(fg_color=BG)
        self.title(f"{TITULO_APP} · traductor en vivo")
        self.geometry("1340x800+30+20")
        self.minsize(1120, 700)
        self.cfg = cargar_config()
        self.cap = Capturador()
        self.cap.start()
        self.hwnd = None
        self.titulo = None
        self.zonas = []        # áreas opcionales que limitan dónde se busca texto (vacío = toda la ventana)
        self.activo = False
        self.listo = {"ocr": False, "trad": False, "error": ""}
        self.ultimo_jp, self.ultimo_es = "", ""
        self.vista = (0, 0, 1.0)   # origen x, y y escala de la vista previa
        self.seq_dibujado, self._ver_dibujada, self._firma_textos = -1, -1, None
        self.sucio = True
        self.arrastre = None
        self.foto = None
        self.capa_firma = None
        self.gestor = None
        self._maq_cache = {}
        self.tapadas = 0
        self._t_capa = 0.0
        o_ = self.cfg["opciones"]
        self.origen = org or o_.get("origen", "jpn_Jpan")
        self.destino = dst or o_.get("destino", "spa_Latn")
        self.velocidad = o_.get("velocidad", "Normal")
        self.sens = o_.get("sensibilidad", "Media")
        self.faltan = self._calc_faltan()
        self.an = deteccion.Analizador(self, dict(
            usa_manga=usa_manga, ocr_cajas=ocr_cajas, ocr_ventana=ocr_ventana, estilo=estilo,
            traducir=lambda t: __import__("traductor_local").traducir_texto(t)))
        self._construir()
        self._crear_capa()
        threading.Thread(target=self._cargar_modelos, daemon=True).start()
        threading.Thread(target=ocr_win.cargar_idiomas, daemon=True).start()
        if self.faltan:
            self.after(900, self.abrir_modelos)
        self.protocol("WM_DELETE_WINDOW", self._cerrar)
        self._refrescar_ventanas()
        o = self.cfg["opciones"]
        if buscar or o.get("ultima"):
            for h, t in ventanas():
                if (buscar and buscar.lower() in t.lower()) or (not buscar and t == o.get("ultima")):
                    self.seleccionar(h, t)
                    break
        if auto:
            self.after(800, self._alternar)
        self.after(150, self._tick)

    # ─────────────────────────────── construcción de la interfaz
    def _construir(self):
        F = lambda s, w="normal": ctk.CTkFont(family="Segoe UI", size=s, weight=w)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Cabecera
        cab = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=68)
        cab.grid(row=0, column=0, columnspan=3, sticky="ew")
        cab.grid_columnconfigure(3, weight=0)
        cab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(cab, text="◐", font=F(30, "bold"), text_color=ACC).grid(row=0, column=0, rowspan=2, padx=(22, 10), pady=10)
        ctk.CTkLabel(cab, text=TITULO_APP, font=F(20, "bold"), text_color=TXT, anchor="w").grid(row=0, column=1, sticky="sw", pady=(12, 0))
        ctk.CTkLabel(cab, text="Traducción en vivo · sin internet", font=F(12), text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="nw")
        langs = ctk.CTkFrame(cab, fg_color=SURF2, corner_radius=12)
        langs.grid(row=0, column=2, rowspan=2, padx=8, pady=12)
        self.btn_org = ctk.CTkButton(langs, text="", width=190, height=38, corner_radius=10, fg_color="transparent", hover_color=BORDE,
                                     text_color=TXT, font=F(13, "bold"), command=lambda: self._elegir_idioma("origen"))
        self.btn_org.pack(side="left", padx=(6, 0), pady=4)
        ctk.CTkButton(langs, text="⇄", width=36, height=38, corner_radius=10, fg_color="transparent", hover_color=ACC, text_color=ACC_H,
                      font=F(16, "bold"), command=self._intercambiar).pack(side="left", pady=4)
        self.btn_dst = ctk.CTkButton(langs, text="", width=190, height=38, corner_radius=10, fg_color="transparent", hover_color=BORDE,
                                     text_color=TXT, font=F(13, "bold"), command=lambda: self._elegir_idioma("destino"))
        self.btn_dst.pack(side="left", padx=(0, 6), pady=4)
        chips = ctk.CTkFrame(cab, fg_color="transparent")
        chips.grid(row=0, column=3, rowspan=2, padx=20)
        ctk.CTkButton(chips, text="⬇  Modelos", width=112, height=32, corner_radius=9, fg_color=SURF2, hover_color=ACC, text_color=TXT,
                      font=F(13, "bold"), command=self.abrir_modelos).pack(side="left", padx=(0, 14))
        self.chip_mod = ctk.CTkLabel(chips, text="● Modelos: cargando…", font=F(12), text_color=WARN)
        self.chip_mod.pack(side="left", padx=10)
        self.chip_cap = ctk.CTkLabel(chips, text="● Captura: —", font=F(12), text_color=MUTED)
        self.chip_cap.pack(side="left", padx=10)

        # Barra lateral izquierda: ventanas
        izq = ctk.CTkFrame(self, fg_color=SURF, corner_radius=14, width=300)
        izq.grid(row=1, column=0, sticky="ns", padx=(16, 8), pady=14)
        izq.grid_propagate(False)
        izq.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(izq, text="1 · VENTANA", font=F(11, "bold"), text_color=ACC).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 0))
        ctk.CTkLabel(izq, text="Elige la ventana del juego", font=F(12), text_color=MUTED).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 8))
        self.lista = ctk.CTkScrollableFrame(izq, fg_color=SURF2, corner_radius=10, width=264)
        self.lista.grid(row=2, column=0, sticky="nsew", padx=12)
        ctk.CTkButton(izq, text="⟳  Actualizar lista", height=34, corner_radius=10, fg_color=SURF2, hover_color=BORDE,
                      text_color=TXT, font=F(13), command=self._refrescar_ventanas).grid(row=3, column=0, sticky="ew", padx=12, pady=12)
        izq.grid_columnconfigure(0, weight=1)

        # Centro: vista en vivo
        cen = ctk.CTkFrame(self, fg_color=SURF, corner_radius=14)
        cen.grid(row=1, column=1, sticky="nsew", padx=8, pady=14)
        cen.grid_rowconfigure(1, weight=1)
        cen.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(cen, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        ctk.CTkLabel(top, text="VISTA EN VIVO", font=F(11, "bold"), text_color=ACC).pack(side="left")
        self.lbl_titulo = ctk.CTkLabel(top, text="", font=F(12), text_color=MUTED)
        self.lbl_titulo.pack(side="left", padx=12)
        self.lienzo = tk.Canvas(cen, bg="#0a0c10", highlightthickness=0, cursor="crosshair")
        self.lienzo.grid(row=1, column=0, sticky="nsew", padx=14)
        self.lienzo.bind("<Configure>", lambda e: setattr(self, "sucio", True))
        self.lienzo.bind("<ButtonPress-1>", self._pulsa)
        self.lienzo.bind("<B1-Motion>", self._arrastra)
        self.lienzo.bind("<ButtonRelease-1>", self._suelta)
        self.lienzo.bind("<Button-3>", self._borrar_en)
        ctk.CTkLabel(cen, text="El texto se detecta solo en toda la ventana  ·  (opcional) arrastra para limitar la búsqueda a un área; clic derecho la quita",
                     font=F(12), text_color=MUTED).grid(row=2, column=0, pady=(8, 12))

        # Panel derecho
        der = ctk.CTkFrame(self, fg_color=SURF, corner_radius=14, width=350)
        der.grid(row=1, column=2, sticky="ns", padx=(8, 16), pady=14)
        der.grid_propagate(False)
        der.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(der, text="2 · ÁREAS (OPCIONAL)", font=F(11, "bold"), text_color=ACC).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        self.zonas_frame = ctk.CTkFrame(der, fg_color=SURF2, corner_radius=10)
        self.zonas_frame.grid(row=1, column=0, sticky="ew", padx=12)
        fila = ctk.CTkFrame(der, fg_color="transparent")
        fila.grid(row=2, column=0, sticky="ew", padx=12, pady=8)
        ctk.CTkButton(fila, text="Solo el cuadro de diálogo", height=32, corner_radius=9, fg_color=SURF2, hover_color=BORDE,
                      text_color=TXT, font=F(12), command=self._sugerir).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(fila, text="Quitar", height=32, width=76, corner_radius=9, fg_color=SURF2, hover_color=BAD,
                      text_color=TXT, font=F(12), command=self._borrar_todas).pack(side="left")

        ctk.CTkLabel(der, text="3 · AJUSTES", font=F(11, "bold"), text_color=ACC).grid(row=3, column=0, sticky="w", padx=16, pady=(6, 4))
        aj = ctk.CTkFrame(der, fg_color=SURF2, corner_radius=10)
        aj.grid(row=4, column=0, sticky="ew", padx=12)
        o = self.cfg["opciones"]
        self.sw_capa = ctk.CTkSwitch(aj, text="Mostrar la traducción sobre el juego", font=F(12), progress_color=ACC, command=self._guardar_opciones)
        self.sw_capa.pack(anchor="w", padx=14, pady=(12, 6))
        self.sw_estilo = ctk.CTkSwitch(aj, text="Imitar color y tamaño del texto", font=F(12), progress_color=ACC, command=self._guardar_opciones)
        self.sw_estilo.pack(anchor="w", padx=14, pady=6)
        (self.sw_capa.select() if o.get("capa", True) else self.sw_capa.deselect())
        (self.sw_estilo.select() if o.get("estilo", True) else self.sw_estilo.deselect())
        ctk.CTkLabel(aj, text="Velocidad de lectura", font=F(12), text_color=MUTED).pack(anchor="w", padx=14, pady=(6, 2))
        self.seg_vel = ctk.CTkSegmentedButton(aj, values=list(deteccion.INTERVALOS), font=F(12), selected_color=ACC, selected_hover_color=ACC_H,
                                              unselected_color=BORDE, command=lambda v: self._guardar_opciones())
        self.seg_vel.pack(fill="x", padx=14, pady=(0, 8))
        self.seg_vel.set(self.velocidad)
        ctk.CTkLabel(aj, text="Sensibilidad (alta = detecta más, pero puede inventar textos)", font=F(12), text_color=MUTED, wraplength=300,
                     justify="left").pack(anchor="w", padx=14, pady=(2, 2))
        self.seg_sens = ctk.CTkSegmentedButton(aj, values=["Baja", "Media", "Alta"], font=F(12), selected_color=ACC, selected_hover_color=ACC_H,
                                               unselected_color=BORDE, command=lambda v: self._guardar_opciones())
        self.seg_sens.pack(fill="x", padx=14, pady=(0, 14))
        self.seg_sens.set(self.sens)

        ctk.CTkLabel(der, text="4 · TRADUCCIÓN", font=F(11, "bold"), text_color=ACC).grid(row=5, column=0, sticky="w", padx=16, pady=(10, 4))
        res = ctk.CTkFrame(der, fg_color=SURF2, corner_radius=10)
        res.grid(row=6, column=0, sticky="ew", padx=12)
        self.lbl_jp = ctk.CTkLabel(res, text="Texto original (OCR)", font=F(11), text_color=MUTED)
        self.lbl_jp.pack(anchor="w", padx=14, pady=(10, 0))
        self.txt_jp = ctk.CTkTextbox(res, height=54, font=F(13), fg_color=BG, text_color=TXT, corner_radius=8, wrap="word")
        self.txt_jp.pack(fill="x", padx=12, pady=(2, 6))
        self.lbl_es = ctk.CTkLabel(res, text="Traducción", font=F(11), text_color=MUTED)
        self.lbl_es.pack(anchor="w", padx=14)
        self.txt_es = ctk.CTkTextbox(res, height=96, font=F(14), fg_color=BG, text_color=TXT, corner_radius=8, wrap="word")
        self.txt_es.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkButton(res, text="Copiar traducción", height=30, corner_radius=8, fg_color=BORDE, hover_color=ACC, text_color=TXT,
                      font=F(12), command=self._copiar).pack(fill="x", padx=12, pady=(0, 12))

        # Pie
        pie = ctk.CTkFrame(self, fg_color=SURF, corner_radius=0, height=70)
        pie.grid(row=2, column=0, columnspan=3, sticky="ew")
        pie.grid_columnconfigure(0, weight=1)
        self.lbl_estado = ctk.CTkLabel(pie, text="Elige una ventana para empezar.", font=F(13), text_color=MUTED, anchor="w")
        self.lbl_estado.grid(row=0, column=0, sticky="w", padx=24, pady=20)
        self.btn_inicio = ctk.CTkButton(pie, text="▶   Iniciar traducción", width=250, height=44, corner_radius=12, fg_color=ACC,
                                        hover_color=ACC_H, text_color="#ffffff", font=F(15, "bold"), command=self._alternar)
        self.btn_inicio.grid(row=0, column=1, padx=22, pady=12)
        self._pintar_zonas()
        self._mostrar_textos("", "")
        self._etiquetas_idioma()

    # ─────────────────────────────── ventanas
    def _refrescar_ventanas(self):
        for w in self.lista.winfo_children():
            w.destroy()
        for h, t in ventanas():
            sel = (h == self.hwnd)
            ctk.CTkButton(self.lista, text=("●  " if sel else "     ") + (t if len(t) < 34 else t[:33] + "…"), anchor="w", height=34, corner_radius=8,
                          fg_color=ACC if sel else "transparent", hover_color=ACC_H if sel else BORDE, text_color="#ffffff" if sel else TXT,
                          font=ctk.CTkFont(family="Segoe UI", size=13), command=lambda h=h, t=t: self.seleccionar(h, t)).pack(fill="x", pady=2, padx=2)

    def seleccionar(self, hwnd, titulo):
        self.hwnd, self.titulo = hwnd, titulo
        self.cap.hwnd = hwnd
        self.cap.frame = None
        self.zonas = [list(z) for z in self.cfg["ventanas"].get(titulo, {}).get("zonas", [])]
        self.cfg["opciones"]["ultima"] = titulo
        self._reiniciar_estado()
        self.lbl_titulo.configure(text="—  " + (titulo if len(titulo) < 60 else titulo[:59] + "…"))
        self._pintar_zonas()
        self._refrescar_ventanas()
        guardar_config(self.cfg)
        self.sucio = True

    def _reiniciar_estado(self):
        self.an.reiniciar()
        self._firma_textos = None
        self._mostrar_textos("", "")
        self.sucio = True

    # ─────────────────────────────── zonas
    def _guardar_zonas(self):
        self.cfg["ventanas"].setdefault(self.titulo, {})["zonas"] = self.zonas
        guardar_config(self.cfg)

    def _pintar_zonas(self):
        for w in self.zonas_frame.winfo_children():
            w.destroy()
        if not self.zonas:
            ctk.CTkLabel(self.zonas_frame, text="Sin áreas: busco texto en toda la ventana.\nArrastra sobre la vista solo si quieres limitar la búsqueda.",
                         font=ctk.CTkFont(family="Segoe UI", size=12), text_color=MUTED, justify="left", wraplength=290).pack(padx=14, pady=12, anchor="w")
            return
        for i, z in enumerate(self.zonas):
            fila = ctk.CTkFrame(self.zonas_frame, fg_color="transparent")
            fila.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(fila, text=f"▭  Área {i + 1}", font=ctk.CTkFont(family="Segoe UI", size=13), text_color=TXT).pack(side="left", padx=6)
            ctk.CTkLabel(fila, text=f"{z[2] - z[0]}×{z[3] - z[1]} px", font=ctk.CTkFont(family="Segoe UI", size=11), text_color=MUTED).pack(side="left")
            ctk.CTkButton(fila, text="✕", width=28, height=26, corner_radius=7, fg_color=BORDE, hover_color=BAD, text_color=TXT,
                          command=lambda i=i: self._quitar(i)).pack(side="right")

    def _quitar(self, i):
        if 0 <= i < len(self.zonas):
            del self.zonas[i]
            self._reiniciar_estado()
            self._pintar_zonas()
            self._guardar_zonas()
            self.sucio = True

    def _borrar_todas(self):
        self.zonas = []
        self._reiniciar_estado()
        self._pintar_zonas()
        if self.titulo:
            self._guardar_zonas()
        self.sucio = True

    def _sugerir(self):
        f = self.cap.frame
        if f is None:
            return
        w, h = f.size
        self.zonas.append([int(w * 0.06), int(h * 0.70), int(w * 0.94), int(h * 0.97)])
        self._reiniciar_estado()
        self._pintar_zonas()
        self._guardar_zonas()
        self.sucio = True

    # ─────────────────────────────── ratón sobre la vista
    def _a_frame(self, x, y):
        ox, oy, esc = self.vista
        return (x - ox) / esc, (y - oy) / esc

    def _pulsa(self, e):
        if self.cap.frame is None:
            return
        self.arrastre = [e.x, e.y, e.x, e.y]

    def _arrastra(self, e):
        if self.arrastre:
            self.arrastre[2:] = [e.x, e.y]
            self.sucio = True

    def _suelta(self, e):
        if not self.arrastre:
            return
        x0, y0 = self._a_frame(self.arrastre[0], self.arrastre[1])
        x1, y1 = self._a_frame(e.x, e.y)
        self.arrastre = None
        f = self.cap.frame
        if f is not None:
            a, b = sorted((max(0, int(x0)), min(f.width, int(x1)))), sorted((max(0, int(y0)), min(f.height, int(y1))))
            if a[1] - a[0] > 30 and b[1] - b[0] > 16:
                self.zonas.append([a[0], b[0], a[1], b[1]])
                self._pintar_zonas()
                self._guardar_zonas()
        self.sucio = True

    def _borrar_en(self, e):
        x, y = self._a_frame(e.x, e.y)
        for i in range(len(self.zonas) - 1, -1, -1):
            z = self.zonas[i]
            if z[0] <= x <= z[2] and z[1] <= y <= z[3]:
                self._quitar(i)
                return

    # ─────────────────────────────── opciones y textos
    def _guardar_opciones(self):
        o = self.cfg["opciones"]
        o["capa"], o["estilo"], o["velocidad"] = bool(self.sw_capa.get()), bool(self.sw_estilo.get()), self.seg_vel.get()
        o["sensibilidad"] = self.seg_sens.get()
        self.velocidad, self.sens = o["velocidad"], o["sensibilidad"]
        guardar_config(self.cfg)
        self.capa_firma = None

    def _mostrar_textos(self, jp, es):
        for caja, t in ((self.txt_jp, jp), (self.txt_es, es)):
            caja.configure(state="normal")
            caja.delete("1.0", "end")
            caja.insert("1.0", t)
            caja.configure(state="disabled")

    def _copiar(self):
        self.clipboard_clear()
        self.clipboard_append(self.ultimo_es)

    # ─────────────────────────────── modelos y traducción
    def _calc_faltan(self):
        """Modelos imprescindibles que no están instalados (el OCR solo es imprescindible para japonés)."""
        f = []
        if modelo_elegido(self.cfg, "trad") is None:
            f.append("trad")
        if self.origen == "jpn_Jpan" and modelo_elegido(self.cfg, "ocr") is None:
            f.append("ocr")
        return f

    def _cargar_modelos(self, tipos=("ocr", "trad")):
        try:
            self.listo["error"] = ""
            import traducir
            import traductor_local
            traducir.configurar_idiomas(self.origen, self.destino)
            if "ocr" in tipos:
                m = modelo_elegido(self.cfg, "ocr")
                if m:
                    aplicar_modelo("ocr", m)
                if usa_manga(self.origen):
                    cargar_ocr()
                self.listo["ocr"] = True   # con OCR de Windows no hay nada que cargar
            if "trad" in tipos:
                m = modelo_elegido(self.cfg, "trad")
                if m:
                    aplicar_modelo("trad", m)
                    traductor_local.traducir_texto("テスト" if self.origen.split("_")[0] in ("jpn", "zho", "yue", "kor") else "test")
                    self.listo["trad"] = True
        except Exception as e:
            self.listo["error"] = str(e)[:90]

    def cambiar_modelo(self, tipo):
        """Usa el modelo elegido en «Modelos» (se recarga en segundo plano)."""
        self.listo[tipo] = False
        self.faltan = self._calc_faltan()
        self.an.reiniciar()
        threading.Thread(target=self._cargar_modelos, args=((tipo,),), daemon=True).start()

    def modelo_descargado(self, m):
        """Al terminar una descarga: si faltaba un modelo de ese tipo, se activa el recién descargado."""
        if m["tipo"] in self.faltan:
            self.cfg["opciones"]["modelo_" + m["tipo"]] = m["id"]
            guardar_config(self.cfg)
            self.cambiar_modelo(m["tipo"])

    # ─────────────────────────────── idiomas
    def _etiquetas_idioma(self):
        self.btn_org.configure(text=f"{idiomas.nombre(self.origen)}  ▾")
        self.btn_dst.configure(text=f"{idiomas.nombre(self.destino)}  ▾")
        self.lbl_jp.configure(text=f"Texto original · {idiomas.nombre(self.origen)}")
        self.lbl_es.configure(text=f"Traducción · {idiomas.nombre(self.destino)}")
        self.title(f"{TITULO_APP} · {idiomas.nombre(self.origen)} → {idiomas.nombre(self.destino)}")

    def _elegir_idioma(self, cual):
        actual = self.origen if cual == "origen" else self.destino
        titulo = "Idioma del texto del juego" if cual == "origen" else "Traducir a"
        ElegirIdioma(self, titulo, actual, lambda cod: self._fijar_idioma(cual, cod))

    def _fijar_idioma(self, cual, cod):
        if cual == "origen":
            self.origen = cod
        else:
            self.destino = cod
        self._aplicar_idiomas()

    def _intercambiar(self):
        self.origen, self.destino = self.destino, self.origen
        self._aplicar_idiomas()

    def _aplicar_idiomas(self):
        """Guarda el par de idiomas, lo aplica al traductor y reinicia la lectura."""
        o = self.cfg["opciones"]
        o["origen"], o["destino"] = self.origen, self.destino
        guardar_config(self.cfg)
        self._etiquetas_idioma()
        self.faltan = self._calc_faltan()
        self._reiniciar_estado()
        self.capa_firma = None
        self.listo["ocr"] = False
        threading.Thread(target=self._cargar_modelos, args=(("ocr",),), daemon=True).start()
        try:
            import traducir
            import traductor_local
            traducir.configurar_idiomas(self.origen, self.destino)
            traductor_local._cache.clear()
        except Exception:
            pass

    def ocr_problema(self):
        """Mensaje si no hay forma de leer texto en el idioma de origen; None si todo bien."""
        if usa_manga(self.origen) or ocr_win.instalados is None:
            return None
        if ocr_win.etiqueta(self.origen):
            return None
        n = idiomas.nombre(self.origen)
        if self.origen == "jpn_Jpan":
            return "Falta el OCR de japonés: descarga «manga-ocr» en ⬇ Modelos."
        return f"Windows no tiene OCR para «{n}». Añádelo en ⬇ Modelos → «Añadir idiomas de OCR en Windows»."

    def abrir_modelos(self):
        if self.gestor is not None and self.gestor.winfo_exists():
            self.gestor.lift()
            return
        self.gestor = GestorModelos(self)

    def _alternar(self):
        if not self.activo and self.ocr_problema():
            return
        self.activo = not self.activo
        self.an.reiniciar()
        self._firma_textos = None
        if self.activo:
            self.btn_inicio.configure(text="■   Detener traducción", fg_color=BAD, hover_color="#ff8585")
        else:
            self.btn_inicio.configure(text="▶   Iniciar traducción", fg_color=ACC, hover_color=ACC_H)
            self.capa_firma = None
        self.sucio = True

    # ─────────────────────────────── textos detectados (los calcula deteccion.py en segundo plano)
    def _grupos_visibles(self):
        return [g for g in self.an.grupos if g["es"] and g["estilo"]] if self.activo else []

    def _maqueta(self, g, ancho_max):
        """Posición y tamaño con que se dibuja la traducción de un grupo (con memoria para no recalcular)."""
        est = g["estilo"] if self.sw_estilo.get() else ("#14171d", "#ffffff", g["estilo"][2], False)
        clave = (g["es"], g["bbox"], est, ancho_max)
        r = self._maq_cache.get(clave)
        if r is None:
            if len(self._maq_cache) > 400:
                self._maq_cache.clear()
            r = self._maq_cache[clave] = maquetar(g["es"], g["bbox"], est, self, ancho_max)
        return r

    def _actualizar_textos(self):
        gs = [g for g in self.an.grupos if g["es"]] if self.activo else []
        firma_ = tuple((g["jp"], g["es"]) for g in gs)
        if firma_ == self._firma_textos:
            return
        self._firma_textos = firma_
        self.ultimo_jp = "\n".join(g["jp"] for g in gs)
        self.ultimo_es = "\n".join(g["es"] for g in gs)
        self._mostrar_textos(self.ultimo_jp, self.ultimo_es)

    # ─────────────────────────────── vista previa y capa
    def _dibujar_vista(self):
        f, cv = self.cap.frame, self.lienzo
        if not self.sucio and self.cap.seq == self.seq_dibujado and self.an.version == self._ver_dibujada:
            return
        self.sucio, self.seq_dibujado, self._ver_dibujada = False, self.cap.seq, self.an.version
        cw, ch = max(50, cv.winfo_width()), max(50, cv.winfo_height())
        cv.delete("all")
        if f is None:
            msg = {"minimizada": "La ventana está minimizada.\nRestáurala para ver la imagen.", "cerrada": "La ventana se cerró."}.get(
                self.cap.modo, "Elige una ventana de la lista de la izquierda")
            cv.create_text(cw // 2, ch // 2, text=msg, fill=MUTED, font=("Segoe UI", 14), justify="center")
            return
        esc = min(cw / f.width, ch / f.height)
        w, h = max(1, int(f.width * esc)), max(1, int(f.height * esc))
        ox, oy = (cw - w) // 2, (ch - h) // 2
        self.vista = (ox, oy, esc)
        self.foto = ImageTk.PhotoImage(f.resize((w, h), Image.BILINEAR))
        cv.create_image(ox, oy, anchor="nw", image=self.foto)
        for i, z in enumerate(self.zonas):   # áreas opcionales que limitan la detección
            cv.create_rectangle(ox + z[0] * esc, oy + z[1] * esc, ox + z[2] * esc, oy + z[3] * esc, outline=OK, width=2, dash=(6, 3))
            cv.create_text(ox + z[0] * esc + 6, oy + z[1] * esc + 6, anchor="nw", text=f"Área {i + 1}", fill=OK, font=("Segoe UI", 9, "bold"))
        for g in self._grupos_visibles():
            rect, texto, tam, bg, fg, neg = self._maqueta(g, f.width)
            x0, y0, x1, y1 = ox + rect[0] * esc, oy + rect[1] * esc, ox + rect[2] * esc, oy + rect[3] * esc
            cv.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
            fuente = ("Segoe UI", -max(7, int(tam * esc)), "bold" if neg else "normal")
            if "\n" in texto:
                cv.create_text(x0 + 5 * esc, y0 + 2 * esc, anchor="nw", text=texto, fill=fg, font=fuente)
            else:
                cv.create_text(x0 + 5 * esc, (y0 + y1) / 2, anchor="w", text=texto, fill=fg, font=fuente)
        if self.arrastre:
            a = self.arrastre
            cv.create_rectangle(a[0], a[1], a[2], a[3], outline=ACC, width=2)

    def _crear_capa(self):
        self.capa = tk.Toplevel(self)
        self.capa.overrideredirect(True)
        self.capa.attributes("-topmost", True)
        self.capa.attributes("-transparentcolor", TRANSPARENTE)
        self.capa_cv = tk.Canvas(self.capa, bg=TRANSPARENTE, highlightthickness=0)
        self.capa_cv.pack(fill="both", expand=True)
        self.capa.update_idletasks()
        h = user32.GetParent(self.capa.winfo_id()) or self.capa.winfo_id()
        st = user32.GetWindowLongW(h, -20)
        # transparente a los clics, sin robar el foco, fuera de la barra de tareas
        user32.SetWindowLongW(h, -20, st | 0x80000 | 0x20 | 0x80 | 0x08000000)
        if not os.environ.get("TRADUCTOR_VER"):
            user32.SetWindowDisplayAffinity(h, 0x11)   # no sale en capturas de pantalla (modo de respaldo)
        self.capa.withdraw()

    def _subir_capa(self):
        """Pone la capa por encima de todo (HWND_TOPMOST) sin quitarle el foco al juego."""
        self._t_capa = time.time()
        h = user32.GetParent(self.capa.winfo_id()) or self.capa.winfo_id()
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        # HWND_TOPMOST = (HWND)-1; sin mover, sin cambiar tamaño, sin activar
        user32.SetWindowPos(h, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)

    def _actualizar_capa(self):
        o = self.cfg["opciones"]
        rect = self.cap.rect
        f = self.cap.frame
        if (not self.activo or not o.get("capa", True) or rect is None or f is None
                or self.cap.modo in ("minimizada", "cerrada")):
            self.capa.withdraw()
            self.capa_firma = None
            return
        l, t, r, b = rect
        items, tapadas = [], 0
        for g in self._grupos_visibles():
            m = self._maqueta(g, f.width)
            x0, y0, x1, y1 = m[0]
            pts = [(l + x0 + 4, t + y0 + 4), (l + (x0 + x1) // 2, t + (y0 + y1) // 2), (l + x1 - 4, t + y1 - 4)]
            if all(visible_en(self.hwnd, x, y) for x, y in pts):
                items.append(m)
            else:
                tapadas += 1
        self.tapadas = tapadas
        firma_ = (rect, tuple((m[0], m[1]) for m in items), bool(self.sw_estilo.get()))
        ahora = time.time()
        if firma_ == self.capa_firma:
            if items and ahora - self._t_capa > 1.0:   # Windows puede reordenar las ventanas «siempre encima»: se vuelve a subir
                self._subir_capa()
            return
        self._t_capa = ahora
        self.capa_firma = firma_
        if not items:
            self.capa.withdraw()
            return
        self.capa.geometry(f"{r - l}x{b - t}+{l}+{t}")
        self.capa.deiconify()
        self._subir_capa()
        cv = self.capa_cv
        cv.delete("all")
        for (x0, y0, x1, y1), texto, tam, bg, fg, neg in items:
            cv.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
            fuente = ("Segoe UI", -tam, "bold" if neg else "normal")
            if "\n" in texto:
                cv.create_text(x0 + 5, y0 + 2, anchor="nw", text=texto, fill=fg, font=fuente)
            else:
                cv.create_text(x0 + 5, (y0 + y1) / 2, anchor="w", text=texto, fill=fg, font=fuente)

    # ─────────────────────────────── bucle principal
    def _tick(self):
        try:
            self._dibujar_vista()
            self._actualizar_capa()
            self._actualizar_textos()
            self._actualizar_estado()
        except Exception as e:
            self.an.error = "interfaz: " + str(e)[:60]
        self.after(110, self._tick)

    def _actualizar_estado(self):
        L = self.listo
        if L["error"]:
            self.chip_mod.configure(text="● Modelos: error", text_color=BAD)
        elif self.faltan:
            self.chip_mod.configure(text="● Modelos: faltan", text_color=BAD)
        elif L["ocr"] and L["trad"]:
            self.chip_mod.configure(text="● Modelos: listos", text_color=OK)
        else:
            self.chip_mod.configure(text="● Modelos: cargando…", text_color=WARN)
        m = self.cap.modo
        self.chip_cap.configure(text={"directa": "● Captura: directa (funciona si está tapada)", "pantalla": "● Captura: pantalla (debe verse la ventana)",
                                      "minimizada": "● Captura: ventana minimizada", "cerrada": "● Captura: ventana cerrada"}.get(m, "● Captura: —"),
                                text_color={"directa": OK, "pantalla": WARN}.get(m, MUTED))
        if self.faltan:
            txt = "Faltan modelos: pulsa «⬇ Modelos» (arriba a la derecha) y descárgalos."
        elif not self.hwnd:
            txt = "Elige una ventana para empezar."
        elif L["error"]:
            txt = "Error al cargar los modelos: " + L["error"]
        elif self.ocr_problema():
            txt = self.ocr_problema()
        elif not (L["ocr"] and L["trad"]):
            txt = "Cargando los modelos de OCR y traducción (la primera vez tarda un poco)…"
        elif not self.activo:
            txt = "Todo listo. Pulsa «Iniciar traducción»."
        elif self.tapadas and self.cfg["opciones"].get("capa", True):
            txt = "Traduciendo · la ventana está tapada: la capa se oculta, mira la traducción aquí en el panel."
        else:
            n = sum(1 for g in self.an.grupos if g["es"])
            txt = (f"Traduciendo en vivo · {n} texto(s) en pantalla" if n else
                   f"Buscando texto en la ventana… ({self.an.n_detectadas} candidato(s))") + (f"  ·  {self.an.error}" if self.an.error else "")
        self.lbl_estado.configure(text=txt)

    def _cerrar(self):
        self.cap.parar()
        self.an.parar()
        try:
            self.capa.destroy()
        except Exception:
            pass
        self.destroy()


def main():
    a = sys.argv[1:]
    buscar = a[a.index("--ventana") + 1] if "--ventana" in a else None
    org = a[a.index("--origen") + 1] if "--origen" in a else None
    dst = a[a.index("--destino") + 1] if "--destino" in a else None
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    App(buscar=buscar, auto="--auto" in a, org=org, dst=dst).mainloop()


if __name__ == "__main__":
    main()
