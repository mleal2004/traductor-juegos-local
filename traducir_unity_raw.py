"""Traduce al español el texto japonés de un juego Unity (Mono) buscando cadenas serializadas.

Uso:  python traducir_unity_raw.py <carpeta *_Data> [--contar]

Recorre level*, sharedassets*.assets y resources.assets. En los objetos MonoBehaviour/TextAsset busca
cadenas [int32 longitud][bytes UTF-8][relleno a 4] con japonés, las traduce con el modelo local
y las reescribe ajustando longitud y alineación. Antes copia cada archivo a *.bak_antes_de_traducir.
"""
import json
import re
import shutil
import struct
import sys
import time
from pathlib import Path

import UnityPy

sys.path.insert(0, str(Path(__file__).parent))
import traducir  # modelo NLLB local (ja -> es)

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
PROT = re.compile(r"(<[^<>]*>|\{[^{}]*\}|\\[nrt])")
ARCHIVOS = re.compile(r"(level\d+|sharedassets\d+\.assets|resources\.assets)")
TIPOS = ("MonoBehaviour", "TextAsset")
cache: dict[str, str] = {}
pend: set[str] = set()


def candidatas(raw: bytes):
    """Genera (posición, longitud, texto) de cadenas serializadas con japonés."""
    n = len(raw)
    i = 0
    while i + 8 <= n:
        L = struct.unpack_from("<i", raw, i)[0]
        if 3 <= L <= 6000 and i + 4 + L <= n:
            b = raw[i + 4:i + 4 + L]
            pad = (-L) % 4
            if all(x == 0 for x in raw[i + 4 + L:i + 4 + L + pad]) and i + 4 + L + pad <= n:
                try:
                    s = b.decode("utf-8")
                except UnicodeDecodeError:
                    s = None
                if s and JA.search(s) and not any(ord(c) < 32 and c not in "\n\r\t" for c in s):
                    yield i, L, s
                    i += 4 + L + pad
                    continue
        i += 4  # los campos van alineados a 4 bytes
    return


def trozos(texto: str):
    out = []
    for linea in texto.split("\n"):
        for p in PROT.split(linea):
            if p and not PROT.fullmatch(p) and JA.search(p):
                out.append(p.strip())
    return out


def convertir(texto: str) -> str:
    lineas = []
    for linea in texto.split("\n"):
        partes = []
        for p in PROT.split(linea):
            if p and not PROT.fullmatch(p) and JA.search(p):
                lead, trail = p[:len(p) - len(p.lstrip())], p[len(p.rstrip()):]
                partes.append(lead + cache.get(p.strip(), p.strip()) + trail)
            else:
                partes.append(p)
        lineas.append("".join(partes))
    return "\n".join(lineas)


def reescribir(raw: bytes) -> bytes:
    out = bytearray()
    pos = 0
    for i, L, s in candidatas(raw):
        nuevo = convertir(s).encode("utf-8")
        pad_old = (-L) % 4
        out += raw[pos:i] + struct.pack("<i", len(nuevo)) + nuevo + b"\0" * ((-len(nuevo)) % 4)
        pos = i + 4 + L + pad_old
    out += raw[pos:]
    return bytes(out)


def main():
    global cache
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    contar = "--contar" in sys.argv
    datos = Path(args[0])
    cache_f = datos.parent / "traduccion_cache.json"
    if cache_f.exists():
        cache = json.loads(cache_f.read_text(encoding="utf-8"))
    solo = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:] if a.startswith("--solo=")), None)   # --solo=level1,level3
    archivos = sorted(p for p in datos.iterdir() if p.is_file() and ARCHIVOS.fullmatch(p.name) and (solo is None or p.name in solo))
    # Fuente: siempre el respaldo si existe
    fuentes = {}
    for p in archivos:
        bak = Path(str(p) + ".bak_antes_de_traducir")
        if not contar and not bak.exists():
            shutil.copy2(p, bak)
        fuentes[p] = bak if bak.exists() else p

    # Pasada 1: reunir
    for p, src in fuentes.items():
        env = UnityPy.load(str(src))
        for o in env.objects:
            if o.type.name in TIPOS:
                try:
                    raw = o.get_raw_data()
                except Exception:
                    continue
                for _, _, s in candidatas(raw):
                    pend.update(t for t in trozos(s) if t not in cache)
    print(f"Frases únicas por traducir: {len(pend)} ({sum(len(s) for s in pend)} caracteres)", flush=True)
    if contar:
        return
    lista = sorted(pend, key=len)
    traducir.cargar_modelo()
    t0 = time.time()
    for k in range(0, len(lista), 24):
        lote = lista[k:k + 24]
        partes = [q for s in lote for q in traducir.partir(s)]
        res = iter(traducir.traducir_lote(partes))
        for s in lote:
            cache[s] = " ".join(next(res) for _ in traducir.partir(s))
        if (k // 24) % 10 == 0:
            cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  {k + len(lote)}/{len(lista)} | {time.time() - t0:.0f}s", flush=True)
    cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # Pasada 2: escribir
    for p, src in fuentes.items():
        env = UnityPy.load(str(src))
        cambios = 0
        for o in env.objects:
            if o.type.name in TIPOS:
                try:
                    raw = o.get_raw_data()
                except Exception:
                    continue
                nuevo = reescribir(raw)
                if nuevo != raw:
                    o.set_raw_data(nuevo)
                    cambios += 1
        if cambios:
            p.write_bytes(env.file.save())
        print(f"  {p.name}: {cambios} objetos modificados", flush=True)
    print("Listo")


if __name__ == "__main__":
    main()
