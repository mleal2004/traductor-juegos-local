"""Detección y seguimiento de texto en tiempo real (sin marcar zonas a mano).

Cada fotograma:
  1. se buscan cajas de texto con OpenCV (unos milisegundos),
  2. se «siguen» entre fotogramas (una caja que se mueve o reaparece conserva su lectura),
  3. solo las cajas nuevas o cuyo contenido cambió pasan por el OCR (en un hilo aparte),
  4. las líneas se agrupan en frases/menús y se traducen en segundo plano.
La interfaz solo lee `grupos` (con su traducción) y los dibuja en la vista y sobre el juego.
"""
import queue
import re
import threading
import time

import cv2
import numpy as np
from PIL import Image

JA_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
FIN_FRASE = "。！？!?…」』）♪"
UMBRALES = {"Baja": 0.92, "Media": 0.80, "Alta": 0.55}      # confianza mínima del OCR según la sensibilidad
INTERVALOS = {"Rápida": 0.06, "Normal": 0.12, "Ahorro": 0.35}


# ═════════════════════════════════════════════ detección de cajas (OpenCV)
def fusionar(cajas):
    """Une cajas de la misma línea (se solapan en vertical y están a menos de ~0.9 de alto de distancia)."""
    cajas = sorted(cajas)
    cambio = True
    while cambio:
        cambio, out = False, []
        for c in cajas:
            for k, d in enumerate(out):
                h = max(c[3] - c[1], d[3] - d[1])
                solape = min(c[3], d[3]) - max(c[1], d[1])
                hueco = max(c[0], d[0]) - min(c[2], d[2])
                if solape > 0.55 * min(c[3] - c[1], d[3] - d[1]) and hueco < 0.9 * h:
                    out[k] = (min(c[0], d[0]), min(c[1], d[1]), max(c[2], d[2]), max(c[3], d[3]))
                    cambio = True
                    break
            else:
                out.append(c)
        cajas = sorted(out)
    return cajas


def detectar_cajas(rgb: np.ndarray, max_ancho=960):
    """Cajas (x0, y0, x1, y1) donde hay trazos que parecen texto. rgb: matriz H×W×3."""
    h, w = rgb.shape[:2]
    if h < 12 or w < 12:
        return []
    f = min(1.0, max_ancho / w)
    peq = cv2.resize(rgb, (max(1, int(w * f)), max(1, int(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else rgb
    gris = cv2.cvtColor(peq, cv2.COLOR_RGB2GRAY)
    sh, sw = gris.shape
    grad = cv2.morphologyEx(gris, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    t, _ = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    bw = (grad > max(t * 0.55, 12)).astype(np.uint8) * 255
    # quitar líneas largas y rectas (marcos de cuadros, bordes, decoración): el texto tiene trazos cortos
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, int(sw * 0.06)), 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, int(sh * 0.10))))
    rectas = cv2.bitwise_or(cv2.morphologyEx(bw, cv2.MORPH_OPEN, kh), cv2.morphologyEx(bw, cv2.MORPH_OPEN, kv))
    bw = cv2.bitwise_and(bw, cv2.bitwise_not(cv2.dilate(rectas, np.ones((3, 3), np.uint8))))
    cerrado =cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)))
    n, _, st, _ = cv2.connectedComponentsWithStats(cerrado, connectivity=8)
    cajas = []
    for i in range(1, n):
        x, y, ww, hh, _a = st[i]
        if hh < 3 or hh > sh * 0.30 or ww < 3 or ww > sw * 0.95 or ww > max(hh, 8) * 14:
            continue
        dens = float((bw[y:y + hh, x:x + ww] > 0).mean())
        if dens < 0.10 or dens > 0.95:
            continue
        cajas.append((int(x), int(y), int(x + ww), int(y + hh)))
    cajas = [c for c in fusionar(cajas) if (c[2] - c[0]) >= 0.6 * (c[3] - c[1]) and (c[3] - c[1]) >= 10]
    finales = []
    for a, b, c, d in cajas:
        caja = (int(a / f), int(b / f), int(c / f), int(d / f))
        finales.append(quitar_iconos(rgb, caja))
    return finales


def quitar_iconos(rgb: np.ndarray, caja):
    """Recorta de los extremos de la caja los símbolos (cursores ▶, viñetas) cuyo color no es el del texto."""
    x0, y0, x1, y1 = caja
    h = y1 - y0
    crop = rgb[y0:y1, x0:x1]
    if crop.size == 0 or x1 - x0 < 2 * h:
        return caja
    g = cv2.cvtColor(np.ascontiguousarray(crop), cv2.COLOR_RGB2GRAY)
    _, m = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    tinta = m > 0
    if tinta.mean() > 0.5:
        tinta = ~tinta
    col = tinta.any(axis=0)
    segs, ini, fin, vacio = [], None, 0, 0
    for x, v in enumerate(col):
        if v:
            ini = x if ini is None else ini
            fin, vacio = x, 0
        elif ini is not None:
            vacio += 1
            if vacio >= max(3, int(0.2 * h)):
                segs.append((ini, fin))
                ini = None
    if ini is not None:
        segs.append((ini, fin))
    if len(segs) < 2:
        return caja
    colores = [np.median(crop[:, a:b + 1][tinta[:, a:b + 1]], axis=0) for a, b in segs]
    ref = colores[int(np.argmax([b - a for a, b in segs]))]
    quedan = [i for i, (a, b) in enumerate(segs)
              if not ((i == 0 or i == len(segs) - 1) and (b - a) < 1.2 * h and np.linalg.norm(colores[i] - ref) > 90)]
    if not quedan or len(quedan) == len(segs):
        return caja
    return (x0 + max(0, segs[quedan[0]][0] - 1), y0, x0 + segs[quedan[-1]][1] + 2, y1)


def clave(rgb_crop: np.ndarray) -> np.ndarray:
    """Huella binaria 8×32 del recorte: no cambia si solo cambia el fondo o el resaltado de color."""
    g = cv2.cvtColor(np.ascontiguousarray(rgb_crop), cv2.COLOR_RGB2GRAY)
    p = cv2.resize(g, (32, 8), interpolation=cv2.INTER_AREA)
    return p > p.mean()


def distancia(a: np.ndarray, b: np.ndarray) -> float:
    return float((a != b).mean())


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def contraste(rgb_crop: np.ndarray) -> float:
    """Diferencia de brillo entre las letras y el fondo (el texto real suele tener bastante)."""
    g = cv2.cvtColor(np.ascontiguousarray(rgb_crop), cv2.COLOR_RGB2GRAY)
    _, m = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    a, b = g[m > 0], g[m == 0]
    return abs(float(a.mean()) - float(b.mean())) if len(a) and len(b) else 0.0


# ═════════════════════════════════════════════ seguimiento y lectura
class Item:
    """Una línea de texto detectada."""
    __slots__ = ("bbox", "bits", "bits_ocr", "vistos", "perdidos", "estable", "jp", "conf", "estado", "estilo", "en_cola")

    def __init__(self, bbox, bits):
        self.bbox, self.bits, self.bits_ocr = bbox, bits, None
        self.vistos, self.perdidos, self.estable = 1, 0, 0
        self.jp, self.conf, self.estado, self.estilo, self.en_cola = "", 0.0, "nuevo", None, False


class Analizador:
    """Motor en tiempo real. `f` trae las funciones que dependen de los modelos:
    usa_manga(origen), ocr_cajas(crops)->[(texto, confianza)], ocr_ventana(frame, origen)->[(texto, bbox)],
    estilo(crop)->(bg, fg, tam, negrita), traducir(texto)->str."""

    def __init__(self, app, f):
        self.app, self.f = app, f
        self.items, self.grupos, self.version = [], [], 0
        self.lock = threading.Lock()
        self.cache_ocr, self.trad, self.pend_trad = [], {}, set()
        self.cola = queue.Queue()
        self.gen, self.fin, self.error = 0, False, ""
        self.seq_ant, self.sig_win, self.sig_ocr, self.estable_win, self.win_ocupado = -1, None, None, 0, False
        self.n_detectadas = 0
        threading.Thread(target=self._detector, daemon=True).start()
        threading.Thread(target=self._lector, daemon=True).start()

    def reiniciar(self):
        with self.lock:
            self.gen += 1
            self.items, self.grupos = [], []
            self.cache_ocr.clear()
            self.trad.clear()
            self.pend_trad.clear()
            self.sig_win = self.sig_ocr = None
            self.win_ocupado = False
            self.seq_ant = -1
            self.version += 1
        try:
            while True:
                self.cola.get_nowait()
        except queue.Empty:
            pass

    # ───────────────────────── hilo detector (rápido)
    def _detector(self):
        while not self.fin:
            a = self.app
            try:
                if not a.activo or a.cap.frame is None or not (a.listo["ocr"] and a.listo["trad"]):
                    time.sleep(0.08)
                    continue
                seq = a.cap.seq
                if seq == self.seq_ant:
                    time.sleep(0.02)
                    continue
                self.seq_ant = seq
                t0 = time.time()
                frame = a.cap.frame
                if self.f["usa_manga"](a.origen):
                    self._paso_manga(frame)
                else:
                    self._paso_windows(frame)
                self._agrupar()
                time.sleep(max(0.0, INTERVALOS.get(a.velocidad, 0.12) - (time.time() - t0)))
            except Exception as e:
                self.error = str(e)[:80]
                time.sleep(0.2)

    def _paso_manga(self, frame):
        a = self.app
        rgb = np.asarray(frame)
        H, W = rgb.shape[:2]
        zonas = [tuple(int(v) for v in z) for z in a.zonas] or [(0, 0, W, H)]
        cajas = []
        for x0, y0, x1, y1 in zonas:
            for c in detectar_cajas(rgb[y0:y1, x0:x1]):
                cajas.append((c[0] + x0, c[1] + y0, c[2] + x0, c[3] + y0))
        cajas.sort(key=lambda c: -(c[2] - c[0]) * (c[3] - c[1]))
        cajas = cajas[:50]
        self.n_detectadas = len(cajas)
        with self.lock:
            gen, usados, nuevos = self.gen, set(), []
            for c in cajas:
                mejor, mi = None, 0.4
                for it in self.items:
                    if id(it) in usados:
                        continue
                    v = iou(c, it.bbox)
                    if v > mi:
                        mejor, mi = it, v
                bits = clave(rgb[c[1]:c[3], c[0]:c[2]])
                if mejor is not None:
                    it = mejor
                    usados.add(id(it))
                    it.bbox, it.perdidos, it.vistos = c, 0, it.vistos + 1
                    it.estable = 0 if distancia(bits, it.bits) > 0.12 else it.estable + 1
                    it.bits = bits
                else:
                    it = Item(c, bits)
                    usados.add(id(it))
                    nuevos.append(it)
                if it.estable >= 1 and it.vistos >= 2 and not it.en_cola and \
                        (it.bits_ocr is None or distancia(it.bits, it.bits_ocr) > 0.12):
                    self._pedir_ocr(it, rgb, gen)
            for it in self.items:
                if id(it) not in usados:
                    it.perdidos += 1
            self.items = [it for it in self.items + nuevos if it.perdidos <= 4]

    def _pedir_ocr(self, it, rgb, gen):
        for bits, jp, conf, estado, estilo in self.cache_ocr:    # ¿ya lo leí antes (mismo texto)?
            if distancia(bits, it.bits) <= 0.06:
                it.jp, it.conf, it.estado, it.estilo, it.bits_ocr = jp, conf, estado, estilo, it.bits
                self.version += 1
                return
        x0, y0, x1, y1 = it.bbox
        H, W = rgb.shape[:2]
        crop = Image.fromarray(rgb[max(0, y0 - 3):min(H, y1 + 3), max(0, x0 - 3):min(W, x1 + 3)].copy())
        it.en_cola = True
        self.cola.put(("ocr", gen, it, crop, it.bits.copy()))

    def _paso_windows(self, frame):
        a = self.app
        g = cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2GRAY)
        sig = cv2.resize(g, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)
        self.estable_win = self.estable_win + 1 if (self.sig_win is not None and np.abs(sig - self.sig_win).mean() < 2.5) else 0
        self.sig_win = sig
        cambio = self.sig_ocr is None or np.abs(sig - self.sig_ocr).mean() > 3
        if cambio and self.estable_win >= 1 and not self.win_ocupado:
            self.win_ocupado = True
            self.cola.put(("win", self.gen, frame.copy(), sig, [tuple(z) for z in a.zonas]))

    # ───────────────────────── hilo lector (lento: OCR y traducción)
    def _lector(self):
        while not self.fin:
            try:
                trabajos = [self.cola.get(timeout=0.2)]
            except queue.Empty:
                continue
            try:
                while len(trabajos) < 10:
                    trabajos.append(self.cola.get_nowait())
            except queue.Empty:
                pass
            try:
                ocrs = [t for t in trabajos if t[0] == "ocr"]
                if ocrs:
                    self._hacer_ocr(ocrs)
                for t in trabajos:
                    if t[0] == "win":
                        self._hacer_win(t)
                    elif t[0] == "trad":
                        self._hacer_trad(t)
            except Exception as e:
                self.error = str(e)[:80]

    def _valido(self, texto, conf, crop) -> bool:
        if not texto:
            return False
        jp = len(JA_RE.findall(texto))
        letras = len(re.sub(r"[\s…・\.\-ー!！?？、。,]", "", texto))
        if jp < 2 or jp < 0.6 * max(1, letras):
            return False
        if conf < UMBRALES.get(self.app.sens, 0.8):
            return False
        return contraste(np.asarray(crop.convert("RGB"))) >= 45

    def _hacer_ocr(self, ocrs):
        resultados = self.f["ocr_cajas"]([t[3] for t in ocrs])
        for (_, gen, it, crop, bits), (texto, conf) in zip(ocrs, resultados):
            it.en_cola = False
            if gen != self.gen:
                continue
            ok = self._valido(texto, conf, crop)
            estilo = None
            if ok:
                try:
                    estilo = self.f["estilo"](crop)
                except Exception:
                    ok = False
            it.jp, it.conf, it.estado, it.estilo, it.bits_ocr = (texto if ok else ""), conf, ("ok" if ok else "no"), estilo, bits
            self.cache_ocr.append((bits, it.jp, conf, it.estado, estilo))
            del self.cache_ocr[:-300]
            self.version += 1

    def _hacer_win(self, t):
        _, gen, frame, sig, zonas = t
        try:
            lineas = self.f["ocr_ventana"](frame, self.app.origen)
        finally:
            self.win_ocupado = False
        if gen != self.gen:
            return
        items = []
        for texto, bbox in lineas:
            cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
            if zonas and not any(z[0] <= cx <= z[2] and z[1] <= cy <= z[3] for z in zonas):
                continue
            it = Item(tuple(int(v) for v in bbox), None)
            it.jp, it.conf, it.estado, it.vistos = texto, 1.0, "ok", 9
            try:
                it.estilo = self.f["estilo"](frame.crop(bbox))
            except Exception:
                it.estilo = ("#14171d", "#ffffff", 22, False)
            items.append(it)
        with self.lock:
            self.items = items
            self.sig_ocr = sig
            self.version += 1

    def _hacer_trad(self, t):
        _, gen, jp = t
        es = self.f["traducir"](jp)
        if gen == self.gen:
            self.trad[jp] = es
            if len(self.trad) > 3000:
                self.trad.pop(next(iter(self.trad)))
            self.version += 1
        self.pend_trad.discard(jp)

    # ───────────────────────── agrupar líneas en frases / menús
    def _agrupar(self):
        sep = "" if self.app.origen.split("_")[0] in ("jpn", "zho", "yue", "tha") else " "
        # 1) trozos de la misma línea visual (separados por una coma, un espacio...) → una sola línea
        trozos = sorted(((i.bbox, i.jp, i.estilo) for i in self.items if i.estado == "ok" and i.jp), key=lambda t: t[0][0])
        lineas = []
        for bbox, jp, est in trozos:
            h, cy = max(1, bbox[3] - bbox[1]), (bbox[1] + bbox[3]) / 2
            for L in lineas:
                lh, ly = max(1, L["bbox"][3] - L["bbox"][1]), (L["bbox"][1] + L["bbox"][3]) / 2
                if abs(cy - ly) < 0.4 * max(h, lh) and 0.6 <= h / lh <= 1.6 and 0 <= bbox[0] - L["bbox"][2] <= 1.3 * max(h, lh):
                    L["jp"] += sep + jp
                    L["bbox"] = (L["bbox"][0], min(L["bbox"][1], bbox[1]), bbox[2], max(L["bbox"][3], bbox[3]))
                    break
            else:
                lineas.append({"bbox": bbox, "jp": jp, "estilo": est})
        # 2) líneas seguidas de una misma frase (diálogo que ocupa varias líneas) → un solo grupo
        lineas.sort(key=lambda L: (L["bbox"][1], L["bbox"][0]))
        grupos = []
        for it in lineas:
            h = max(1, it["bbox"][3] - it["bbox"][1])
            for g in grupos:
                u = g[-1]
                uh = max(1, u["bbox"][3] - u["bbox"][1])
                gap = it["bbox"][1] - u["bbox"][3]
                if (0.7 <= h / uh <= 1.4 and -0.3 * h <= gap <= 0.5 * h and abs(it["bbox"][0] - u["bbox"][0]) <= 0.9 * h
                        and len(u["jp"]) >= 8 and u["jp"][-1] not in FIN_FRASE):
                    g.append(it)
                    break
            else:
                grupos.append([it])
        salida = []
        for g in grupos:
            jp = sep.join(i["jp"] for i in g)
            bbox = (min(i["bbox"][0] for i in g), min(i["bbox"][1] for i in g), max(i["bbox"][2] for i in g), max(i["bbox"][3] for i in g))
            es = self.trad.get(jp)
            if es is None and jp not in self.pend_trad:
                self.pend_trad.add(jp)
                self.cola.put(("trad", self.gen, jp))
            salida.append({"bbox": bbox, "jp": jp, "es": es, "estilo": g[0]["estilo"], "n": len(g)})
        # estabilizar para que no parpadee: se conserva la posición anterior si casi no cambió (la detección «tiembla» unos píxeles),
        # y un texto que desaparece de golpe se mantiene unos ciclos por si fue solo un fallo de detección
        viejos = self.grupos
        for g in salida:
            for v in viejos:
                if v["jp"] == g["jp"] and max(abs(a - b) for a, b in zip(v["bbox"], g["bbox"])) <= 4:
                    g["bbox"] = v["bbox"]
                    break
        for v in viejos:
            if v["es"] and v.get("fantasma", 0) < 5 and not any(iou(v["bbox"], g["bbox"]) > 0.5 for g in salida):
                salida.append(dict(v, fantasma=v.get("fantasma", 0) + 1))
        firma_nueva = [(g["bbox"], g["jp"], g["es"]) for g in salida]
        if firma_nueva != [(g["bbox"], g["jp"], g["es"]) for g in self.grupos]:
            self.version += 1
        self.grupos = salida

    def parar(self):
        self.fin = True
