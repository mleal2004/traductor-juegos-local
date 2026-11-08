"""Pone en español los textos de un juego hecho con Godot 4 (archivo .pck).

Uso:  python traducir_godot_pck.py <juego.pck>

El juego guarda sus textos en archivos .translation (OptimizedTranslation) por idioma
(típico de proyectos Godot con Dialogue Manager).
Este script traduce al español el texto japonés (.ja.translation) y escribe el resultado
tanto en los .ja como en los .en, de modo que el juego salga en español con cualquiera de los dos.
Reempaqueta el .pck añadiendo los archivos nuevos al final (antes hace una copia .bak_antes_de_traducir).
"""
import hashlib
import json
import re
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import traducir  # modelo NLLB local (ja -> es)

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
PROT = re.compile(r"(\[[^\[\]]*\]|\{\{.*?\}\}|\{[^{}]*\}|<[^<>]*>|\\n)")
NIL, STR, BYTES, INT32 = 1, 5, 31, 32
cache: dict[str, str] = {}


# ---------- lectura/escritura de OptimizedTranslation (RSRC) ----------
def u32(d, p):
    return struct.unpack_from("<I", d, p)[0]


def parse(data: bytes):
    marca = b"\x15\x00\x00\x00OptimizedTranslation\x00"
    i = data.rfind(marca)
    p = i + len(marca)
    head = data[:p]
    n = u32(data, p)
    p += 4
    props = []
    for _ in range(n):
        idx, vt = u32(data, p), u32(data, p + 4)
        p += 8
        if vt == STR:
            L = u32(data, p)
            val = data[p + 4:p + 4 + L]
            p += 4 + L
        elif vt == INT32:
            c = u32(data, p)
            val = list(struct.unpack_from(f"<{c}I", data, p + 4))
            p += 4 + 4 * c
        elif vt == BYTES:
            c = u32(data, p)
            val = data[p + 4:p + 4 + c]
            p += 4 + c + (-c) % 4
        elif vt == NIL:
            val = None
        else:
            raise ValueError(f"tipo de variante {vt} no soportado")
        props.append([idx, vt, val])
    return head, props, data[p:]


def serialize(head, props, tail):
    out = bytearray(head) + struct.pack("<I", len(props))
    for idx, vt, val in props:
        out += struct.pack("<II", idx, vt)
        if vt == STR:
            out += struct.pack("<I", len(val)) + val
        elif vt == INT32:
            out += struct.pack("<I", len(val)) + struct.pack(f"<{len(val)}I", *val)
        elif vt == BYTES:
            out += struct.pack("<I", len(val)) + val + b"\0" * ((-len(val)) % 4)
    return bytes(out) + tail


def tablas(props):
    d = {p[0]: p for p in props}
    return d[4][2], d[5][2], d[6][2]  # hash_table, bucket_table, strings (por índice de nombre)


def elementos(ht, bt):
    """[(posición de la entrada en bt, clave)] en orden de bucket."""
    out = []
    for p in sorted(set(x for x in ht if x != 0xFFFFFFFF)):
        size = bt[p]
        for k in range(size):
            out.append((p + 2 + 4 * k, bt[p + 2 + 4 * k]))
    return out


def textos_ja(data):
    head, props, tail = parse(data)
    ht, bt, st = tablas(props)
    res = {}
    for pos, key in elementos(ht, bt):
        off, comp, unc = bt[pos + 1], bt[pos + 2], bt[pos + 3]
        if comp == unc and comp > 0:
            try:
                s = st[off:off + comp].rstrip(b"\0").decode("utf-8")
            except UnicodeDecodeError:
                continue
            if JA.search(s):
                res[key] = s
    return res


def reconstruir(data, es_por_clave):
    head, props, tail = parse(data)
    ht, bt, st = tablas(props)
    bt = list(bt)
    nuevo = bytearray()
    for pos, key in elementos(ht, bt):
        off, comp, unc = bt[pos + 1], bt[pos + 2], bt[pos + 3]
        if key in es_por_clave:
            blob = es_por_clave[key].encode("utf-8") + b"\0"
            c = u = len(blob)
        else:
            blob = st[off:off + comp]
            c, u = comp, unc
        bt[pos + 1], bt[pos + 2], bt[pos + 3] = len(nuevo), c, u
        nuevo += blob
    for pr in props:
        if pr[0] == 5:
            pr[2] = bt
        elif pr[0] == 6:
            pr[2] = bytes(nuevo)
    return serialize(head, props, tail)


# ---------- traducción ----------
def partes(linea):
    return [p for p in PROT.split(linea) if p and not PROT.fullmatch(p) and JA.search(p)]


def traducir_todo(textos):
    pend = sorted({p.strip() for t in textos for l in t.split("\n") for p in partes(l)} - set(cache), key=len)
    print(f"  {len(pend)} frases únicas por traducir", flush=True)
    traducir.cargar_modelo()
    for k in range(0, len(pend), 24):
        lote = pend[k:k + 24]
        trozos = [q for s in lote for q in traducir.partir(s)]
        res = iter(traducir.traducir_lote(trozos))
        for s in lote:
            cache[s] = " ".join(next(res) for _ in traducir.partir(s))
        if (k // 24) % 10 == 0:
            print(f"    {k + len(lote)}/{len(pend)}", flush=True)


def a_espanol(texto):
    lineas = []
    for l in texto.split("\n"):
        out = []
        for p in PROT.split(l):
            if p and not PROT.fullmatch(p) and JA.search(p):
                lead, trail = p[:len(p) - len(p.lstrip())], p[len(p.rstrip()):]
                out.append(lead + cache.get(p.strip(), p.strip()) + trail)
            else:
                out.append(p)
        lineas.append("".join(out))
    return "\n".join(lineas)


# ---------- .pck v3 ----------
def leer_pck(f):
    f.seek(0)
    assert f.read(4) == b"GDPC"
    ver, mj, mn, pt, flags = struct.unpack("<5I", f.read(20))
    base, diro = struct.unpack("<QQ", f.read(16))
    assert ver == 3, f"versión de pck {ver} no soportada"
    f.seek(diro)
    n = u32(f.read(4), 0)
    entradas = []
    for _ in range(n):
        l = u32(f.read(4), 0)
        raw = f.read(l)
        off, size = struct.unpack("<QQ", f.read(16))
        md5 = f.read(16)
        fl = u32(f.read(4), 0)
        entradas.append([raw, off, size, md5, fl])
    return base, diro, entradas


def main():
    pck = Path(sys.argv[1])
    bak = Path(str(pck) + ".bak_antes_de_traducir")
    if not bak.exists():
        shutil.copy2(pck, bak)
    cache_f = pck.parent / "traduccion_cache.json"
    if cache_f.exists():
        cache.update(json.loads(cache_f.read_text(encoding="utf-8")))

    fin = open(bak, "rb")
    base, diro, entradas = leer_pck(fin)
    nombre = lambda e: e[0].rstrip(b"\0").decode("utf-8")
    grupos = {}
    for e in entradas:
        m = re.fullmatch(r"(.*)\.(ja|en)\.translation", nombre(e))
        if m:
            grupos.setdefault(m.group(1), {})[m.group(2)] = e
    print(len(grupos), "grupos de traducción ja/en", flush=True)

    def leer(e):
        fin.seek(base + e[1])
        return fin.read(e[2])

    datos = {g: {l: leer(e) for l, e in d.items()} for g, d in grupos.items()}
    ja_textos = {g: textos_ja(d["ja"]) for g, d in datos.items() if "ja" in d}
    traducir_todo([t for d in ja_textos.values() for t in d.values()])
    cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    nuevos = {}
    for g, d in datos.items():
        es = {k: a_espanol(t) for k, t in ja_textos.get(g, {}).items()}
        for lang in ("ja", "en"):
            if lang in d:
                nuevos[nombre(grupos[g][lang])] = reconstruir(d[lang], es)

    # escribir el pck nuevo: original + archivos nuevos al final + directorio nuevo
    shutil.copy2(bak, pck)
    with open(pck, "r+b") as f:
        f.seek(0, 2)
        for e in entradas:
            nm = nombre(e)
            if nm in nuevos:
                pos = f.tell()
                pos += (-pos) % 16
                f.seek(pos)
                blob = nuevos[nm]
                f.write(blob)
                e[1], e[2], e[3] = pos - base, len(blob), hashlib.md5(blob).digest()
        pos = f.tell()
        f.write(b"\0" * ((-pos) % 16))
        nuevo_dir = f.tell()
        f.write(struct.pack("<I", len(entradas)))
        for raw, off, size, md5, fl in entradas:
            f.write(struct.pack("<I", len(raw)) + raw + struct.pack("<QQ", off, size) + md5 + struct.pack("<I", fl))
        f.seek(32)  # dir_offset en la cabecera v3
        f.write(struct.pack("<Q", nuevo_dir))
    print(f"Listo: {len(nuevos)} archivos .translation reescritos en {pck.name}", flush=True)


if __name__ == "__main__":
    main()
