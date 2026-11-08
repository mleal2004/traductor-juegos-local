"""Traductor con OCR: lee el texto japonés de la ventana de un juego y escribe la traducción encima.

Uso:   python traductor_ocr.py

1) Te pregunta qué ventana quieres usar.
2) Te muestra una captura de esa ventana: arrastra el ratón para marcar la(s) zona(s) donde sale el
   texto (por ejemplo, el cuadro de diálogo). Se guardan para la próxima vez.
3) Una capa transparente (que no bloquea los clics) dibuja la traducción sobre esas zonas.

Todo funciona en tu PC (modelos en ./modelo_ocr y ./modelo_nllb), sin internet.
La ventana del juego debe estar visible (no tapada por otras) para que la captura funcione.
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).parent))

MODELO_OCR = Path(__file__).parent / "modelo_ocr"
CONFIG = Path(__file__).parent / "traductor_ocr_regiones.json"
user32 = ctypes.windll.user32
TRANSPARENTE = "#ff00ff"
_ocr = None


# ---------------------------------------------------------------- OCR
def cargar_ocr():
    global _ocr
    if _ocr is None:
        import torch
        from transformers import AutoImageProcessor, VisionEncoderDecoderModel
        proc = AutoImageProcessor.from_pretrained(str(MODELO_OCR))
        modelo = VisionEncoderDecoderModel.from_pretrained(str(MODELO_OCR)).eval()
        vocab = [l.rstrip("\n") for l in open(MODELO_OCR / "vocab.txt", encoding="utf-8")]
        _ocr = (proc, modelo, vocab, torch)
    return _ocr


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
            if i == 3:      # [SEP]: fin
                break
            if i < 5:       # [PAD] [UNK] [CLS] [MASK]
                continue
            t = vocab[i]
            out.append(t[2:] if t.startswith("##") else t)
        res.append(limpiar("".join(out)))
    return res


def limpiar(s: str) -> str:
    """Quita la basura típica que mete el OCR al cortar entre letras (signos ASCII sueltos)."""
    s = s.replace("…", "...").replace(" ", "")
    s = re.sub(r"[,'\"`:;|#()\\^_\[\]{}<>]", "", s)
    s = re.sub(r"(?<!\.)\.{1,2}(?!\.)", "", s)
    s = re.sub(r"\.{3,}", "…", s)
    s = re.sub(r"[!?](?=[぀-鿿])", "", s)
    s = s.replace("*", "")
    s = re.sub(r"(?<=[^\n「『（(])[「『]", "", s)  # corchetes de apertura sueltos en medio de una frase
    if len(re.findall(r"[぀-ヿ一-鿿]", s)) >= 3:
        s = re.sub(r"[A-Za-z0-9]", "", s)
    return s


def a_cuadrado(img: Image.Image) -> Image.Image:
    """Centra el recorte en un lienzo cuadrado del color de fondo (el modelo trabaja con 224x224)."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    fondo = tuple(int(v) for v in np.median(np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]]), axis=0))
    lado = max(img.width, img.height) + 8
    lienzo = Image.new("RGB", (lado, lado), fondo)
    lienzo.paste(img, ((lado - img.width) // 2, (lado - img.height) // 2))
    return lienzo


def trocear_linea(img: Image.Image):
    """Parte un renglón ancho en tramos de unas 4 letras, cortando por los huecos entre letras."""
    m = mascara_tinta(img)
    h = img.height
    col = m.mean(axis=0) > 0.01
    objetivo, maximo = int(h * 0.75 * 4), int(h * 0.75 * 6)
    tramos, ini, x = [], 0, 0
    w = img.width
    while ini < w:
        fin = min(w, ini + objetivo)
        if fin < w:
            # buscar el hueco más cercano después del objetivo (hasta el máximo)
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
    # unir tramos separados por menos de 4 px (acentos, puntos de las ふりがな...)
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


FIN_FRASE = "。！？!?…」』）♪"


def ocr_region(img: Image.Image) -> str:
    """Texto de la región. Las líneas se unen si la frase continúa; si no, se separan con salto."""
    out = ""
    for l in dividir_lineas(img):
        t = leer_linea(l)
        if not t:
            continue
        out += ("\n" if out and out[-1] in FIN_FRASE else "") + t
    return out


# ---------------------------------------------------------------- ventanas
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
                if r.right - r.left > 200 and r.bottom - r.top > 120 and buf.value != "Program Manager":
                    res.append((h, buf.value))
        return True
    user32.EnumWindows(cb, 0)
    return res


def rect_ventana(h):
    if not user32.IsWindow(h) or user32.IsIconic(h):
        return None
    r = wt.RECT()
    try:  # límites visibles reales (sin el borde invisible de Windows 10/11)
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            raise OSError
    except Exception:
        user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def elegir_ventana(raiz):
    lista = ventanas()
    top = tk.Toplevel(raiz)
    top.title("¿Qué ventana quieres traducir?")
    top.geometry("560x380+120+120")
    top.attributes("-topmost", True)
    tk.Label(top, text="Haz doble clic en la ventana del juego:").pack(pady=6)
    lb = tk.Listbox(top, font=("Segoe UI", 11))
    lb.pack(fill="both", expand=True, padx=8, pady=4)
    for _, t in lista:
        lb.insert("end", t)
    elegido = []

    def ok(_=None):
        if lb.curselection():
            elegido.append(lista[lb.curselection()[0]])
            top.destroy()
    lb.bind("<Double-Button-1>", ok)
    tk.Button(top, text="Usar esta ventana", command=ok).pack(pady=6)
    top.wait_window()
    return elegido[0] if elegido else None


# ---------------------------------------------------------------- regiones
def cargar_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def elegir_regiones(raiz, hwnd):
    """Muestra una captura de la ventana y deja arrastrar rectángulos. Devuelve [[x0,y0,x1,y1]...]."""
    rect = rect_ventana(hwnd)
    img = ImageGrab.grab(bbox=rect, all_screens=True)
    esc = min(1.0, (raiz.winfo_screenwidth() * 0.85) / img.width, (raiz.winfo_screenheight() * 0.8) / img.height)
    vista = img.resize((int(img.width * esc), int(img.height * esc)))
    top = tk.Toplevel(raiz)
    top.title("Marca con el ratón dónde sale el texto (puedes marcar varias zonas)")
    top.attributes("-topmost", True)
    from PIL import ImageTk
    foto = ImageTk.PhotoImage(vista)
    lienzo = tk.Canvas(top, width=vista.width, height=vista.height, highlightthickness=0, cursor="crosshair")
    lienzo.pack()
    lienzo.create_image(0, 0, anchor="nw", image=foto)
    lienzo.image = foto
    regiones, ids, estado = [], [], {}

    def pulsa(e):
        estado["i"] = (e.x, e.y)
        estado["r"] = lienzo.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff00", width=3)

    def arrastra(e):
        x0, y0 = estado["i"]
        lienzo.coords(estado["r"], x0, y0, e.x, e.y)

    def suelta(e):
        x0, y0 = estado["i"]
        a, b = sorted((x0, e.x)), sorted((y0, e.y))
        if a[1] - a[0] > 15 and b[1] - b[0] > 10:
            regiones.append([int(a[0] / esc), int(b[0] / esc), int(a[1] / esc), int(b[1] / esc)])
            ids.append(estado["r"])
        else:
            lienzo.delete(estado["r"])

    def borrar():
        if ids:
            lienzo.delete(ids.pop()); regiones.pop()
    lienzo.bind("<ButtonPress-1>", pulsa)
    lienzo.bind("<B1-Motion>", arrastra)
    lienzo.bind("<ButtonRelease-1>", suelta)
    barra = tk.Frame(top)
    barra.pack(fill="x")
    tk.Button(barra, text="Borrar última zona", command=borrar).pack(side="left", padx=6, pady=4)
    tk.Button(barra, text="Listo", command=top.destroy).pack(side="right", padx=6, pady=4)
    top.wait_window()
    return regiones


# ---------------------------------------------------------------- capa de traducción
def preparar_capa(ov):
    ov.update_idletasks()
    h = user32.GetParent(ov.winfo_id()) or ov.winfo_id()
    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = -20, 0x80000, 0x20, 0x80
    st = user32.GetWindowLongW(h, GWL_EXSTYLE)
    user32.SetWindowLongW(h, GWL_EXSTYLE, st | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)
    if not os.environ.get("TRADUCTOR_VER"):
        user32.SetWindowDisplayAffinity(h, 0x11)  # WDA_EXCLUDEFROMCAPTURE: la capa no sale en las capturas


def estilo(crop: Image.Image):
    """Imita el aspecto del texto original: color de fondo, color de letra, tamaño y grosor aproximados."""
    a = np.asarray(crop.convert("RGB"), dtype=np.float32)
    m = mascara_tinta(crop)
    lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    bg = np.median(a[~m] if (~m).any() else a.reshape(-1, 3), axis=0)  # píxeles que no son letra
    fg = np.median(a[m], axis=0) if m.any() else None                  # píxeles de letra
    if fg is None or abs(lum(fg) - lum(bg)) < 70:                       # poco contraste: blanco o negro
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


def principal(buscar=None):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    raiz = tk.Tk()
    raiz.title("Traductor OCR (ja → es)")
    raiz.geometry("560x220+60+60")
    raiz.attributes("-topmost", True)
    log = tk.Text(raiz, wrap="word", font=("Segoe UI", 12), padx=8, pady=6)
    log.pack(fill="both", expand=True)

    def mostrar(t):
        log.delete("1.0", "end"); log.insert("1.0", t)

    if buscar:  # modo directo: python traductor_ocr.py --ventana "parte del título"
        cand = [(h, t) for h, t in ventanas() if buscar.lower() in t.lower()]
        sel = cand[0] if cand else None
    else:
        sel = elegir_ventana(raiz)
    if not sel:
        return
    hwnd, titulo = sel
    cfg = cargar_config()
    regiones = cfg.get(titulo)
    if regiones and not buscar and not messagebox.askyesno("Zonas guardadas", f"Hay {len(regiones)} zona(s) guardada(s) para «{titulo}».\n¿Usarlas?", parent=raiz):
        regiones = None
    if not regiones:
        regiones = elegir_regiones(raiz, hwnd)
        if not regiones:
            return
        cfg[titulo] = regiones
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")

    mostrar("Cargando los modelos (la primera vez tarda un poco)…")
    ov = tk.Toplevel(raiz)
    ov.overrideredirect(True)
    ov.attributes("-topmost", True)
    ov.attributes("-transparentcolor", TRANSPARENTE)
    lienzo = tk.Canvas(ov, bg=TRANSPARENTE, highlightthickness=0)
    lienzo.pack(fill="both", expand=True)
    preparar_capa(ov)

    import traductor_local
    est = [{"sig": None, "estable": 0, "hecho": None, "dibujo": None, "ocupado": False} for _ in regiones]
    cola = []

    def trabajo(i, crop, sig):
        try:
            jp = ocr_region(crop)
            if not traductor_local.JA.search(jp):
                es = ""
            else:
                es = traductor_local.traducir_texto(jp)
            cola.append((i, jp, es, estilo(crop)))
        finally:
            est[i]["ocupado"] = False
            est[i]["hecho"] = sig

    def dibujar():
        while cola:
            i, jp, es, (bg, fg, tam, neg) = cola.pop(0)
            est[i]["dibujo"] = (es, bg, fg, tam, neg)
            if es:
                mostrar(f"{jp}\n\n{es}")
        lienzo.delete("all")
        for i, reg in enumerate(regiones):
            d = est[i]["dibujo"]
            if d and d[0]:
                es, bg, fg, tam0, neg = d
                x0, y0, x1, y1 = reg
                lienzo.create_rectangle(x0, y0, x1, y1, fill=bg, outline="")
                tam = ajustar(es, x1 - x0, y1 - y0, raiz, tam0, neg)
                lienzo.create_text(x0 + 6, y0 + 3, anchor="nw", text=es, fill=fg, width=x1 - x0 - 12,
                                   font=("Segoe UI", -tam, "bold" if neg else "normal"))

    def tick():
        rect = rect_ventana(hwnd)
        if rect is None:
            ov.withdraw()
            if not user32.IsWindow(hwnd):
                raiz.destroy()
                return
            raiz.after(500, tick)
            return
        ov.deiconify()
        l, t, r, b = rect
        ov.geometry(f"{r - l}x{b - t}+{l}+{t}")
        try:
            if os.environ.get("TRADUCTOR_VER"):  # modo prueba: la capa sale en las capturas, así que se oculta un instante
                ov.withdraw(); ov.update()
            img = ImageGrab.grab(bbox=rect, all_screens=True)
            if os.environ.get("TRADUCTOR_VER"):
                ov.deiconify()
        except Exception:
            raiz.after(500, tick)
            return
        for i, reg in enumerate(regiones):
            crop = img.crop(tuple(reg))
            sig = firma(crop)
            e = est[i]
            if e["sig"] is None or np.abs(sig - e["sig"]).mean() > 4:
                e["sig"], e["estable"] = sig, 0
            else:
                e["estable"] += 1
            nuevo = e["hecho"] is None or np.abs(sig - e["hecho"]).mean() > 4
            if e["estable"] >= 1 and nuevo and not e["ocupado"]:
                e["ocupado"] = True
                threading.Thread(target=trabajo, args=(i, crop, sig), daemon=True).start()
        dibujar()
        raiz.after(350, tick)

    threading.Thread(target=lambda: (cargar_ocr(), traductor_local.traducir_texto("テスト"),
                                     raiz.after(0, lambda: mostrar("Listo. Aparece texto japonés en la zona marcada y lo traduzco."))),
                     daemon=True).start()
    raiz.after(500, tick)
    raiz.mainloop()


if __name__ == "__main__":
    a = sys.argv[1:]
    principal(a[a.index("--ventana") + 1] if "--ventana" in a else None)
