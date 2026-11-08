"""Traductor local japonés -> español (modelo NLLB en ./modelo_nllb), sin internet.

Dos modos:

  python traductor_local.py portapapeles
      Abre una ventana siempre visible que traduce al español todo texto japonés que se copie al
      portapapeles. Pensado para usar con Textractor (extensión "Copy to Clipboard") u otro
      programa que capture el texto de un juego.

  python traductor_local.py servidor [puerto]
      Servidor HTTP SOLO local (127.0.0.1, puerto 5000 por defecto) con una API tipo LibreTranslate:
        POST /translate   {"q": "texto", "source": "ja", "target": "es"}  ->  {"translatedText": "..."}
        GET  /translate?q=texto                                            ->  {"translatedText": "..."}
        GET  /languages
      Para programas que permitan configurar un servidor LibreTranslate propio.
"""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import idiomas
import traducir  # modelo NLLB local (ja -> es)

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
_lock = threading.Lock()
_cache: dict[str, str] = {}
JA = re.compile("[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ가-힯]")   # japonés, chino y coreano


def necesita(linea: str) -> bool:
    """¿La línea tiene texto en el idioma de origen que valga la pena traducir?"""
    if traducir.ORIGEN.split("_")[0] in ("jpn", "zho", "yue", "kor"):
        return bool(JA.search(linea))
    return any(c.isalpha() for c in linea)


def traducir_texto(texto: str) -> str:
    """Traduce texto japonés (varias líneas) a español, conservando los saltos de línea."""
    salida = []
    for linea in texto.replace("\r\n", "\n").split("\n"):
        if not linea.strip():
            salida.append("")
            continue
        if not necesita(linea):
            salida.append(linea)
            continue
        glos = idiomas.buscar_glosario(linea, traducir.ORIGEN, traducir.DESTINO)   # menús y botones típicos
        if glos:
            salida.append(glos)
            continue
        if linea in _cache:
            salida.append(_cache[linea])
            continue
        with _lock:
            traducir.cargar_modelo()
            trozos = traducir.partir(linea.strip())
            res = " ".join(traducir.traducir_lote(trozos))
        _cache[linea] = res
        salida.append(res)
    return "\n".join(salida)


# ---------- servidor ----------
class Manejador(BaseHTTPRequestHandler):
    def _enviar(self, obj, codigo=200):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/languages":
            return self._enviar([{"code": "ja", "name": "Japanese", "targets": ["es"]},
                                 {"code": "es", "name": "Spanish", "targets": []}])
        if u.path == "/translate":
            q = parse_qs(u.query).get("q", [""])[0]
            return self._enviar({"translatedText": traducir_texto(q)})
        self._enviar({"info": "Traductor local ja->es. Usa POST /translate"})

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo).decode("utf-8", "replace")
        try:
            if "json" in self.headers.get("Content-Type", ""):
                q = json.loads(cuerpo).get("q", "")
            else:
                q = parse_qs(cuerpo).get("q", [""])[0]
        except ValueError:
            return self._enviar({"error": "petición inválida"}, 400)
        if isinstance(q, list):
            return self._enviar({"translatedText": [traducir_texto(x) for x in q]})
        self._enviar({"translatedText": traducir_texto(q)})

    def log_message(self, *a):
        pass


def servidor(puerto=5000):
    traducir.cargar_modelo()
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)  # solo local
    print(f"Servidor listo en http://127.0.0.1:{puerto}  (Ctrl+C para cerrar)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------- ventana de portapapeles ----------
def portapapeles():
    import tkinter as tk
    raiz = tk.Tk()
    raiz.title("Traductor local (ja → es)")
    raiz.attributes("-topmost", True)
    raiz.geometry("760x240+80+80")
    caja = tk.Text(raiz, wrap="word", font=("Segoe UI", 16), padx=10, pady=8)
    caja.pack(fill="both", expand=True)
    caja.insert("1.0", "Cargando el modelo…")
    estado = {"ultimo": ""}

    def trabajar(texto):
        res = traducir_texto(texto)
        raiz.after(0, lambda: (caja.delete("1.0", "end"), caja.insert("1.0", res)))

    def revisar():
        try:
            t = raiz.clipboard_get()
        except tk.TclError:
            t = ""
        if t != estado["ultimo"]:
            estado["ultimo"] = t
            if necesita(t):
                threading.Thread(target=trabajar, args=(t,), daemon=True).start()
        raiz.after(300, revisar)

    threading.Thread(target=lambda: (traducir.cargar_modelo(),
                                     raiz.after(0, lambda: (caja.delete("1.0", "end"),
                                                            caja.insert("1.0", "Listo. Copia texto japonés para traducirlo.")))),
                     daemon=True).start()
    raiz.after(300, revisar)
    raiz.mainloop()


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 else ""
    if modo == "servidor":
        servidor(int(sys.argv[2]) if len(sys.argv) > 2 else 5000)
    elif modo == "portapapeles":
        portapapeles()
    else:
        sys.exit(__doc__)
