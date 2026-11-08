"""Traduce al español los textos de un juego RPG Maker MV/MZ (japonés -> español), sin internet.

Uso:
    python traducir_rpgmaker.py <carpeta_data_original> <carpeta_data_destino> [--contar]

- Lee SIEMPRE de la carpeta original (un respaldo) y escribe en la de destino,
  así se puede repetir sin traducir dos veces.
- Traduce: diálogos (101/401), nombres de hablante, opciones (102), texto en
  desplazamiento (405), nombre de mapas y la base de datos (nombres,
  descripciones, mensajes de batalla) y los términos del sistema.
- Conserva los códigos de texto (\\C[2], \\N[1], \\V[3]...).
- Guarda una caché (traduccion_cache.json) para poder reanudar.
- --contar: solo cuenta cuánto texto hay, no traduce.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import traducir  # modelo NLLB local

JA = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
CODIGO = re.compile(r"(\\[A-Za-z]+\[\d*\]|\\[.|!<>^{}$\\]|\\[A-Za-z](?![A-Za-z])|<[^<>\n]*>)")
PLUG357 = False  # --plugins: traduce también los argumentos de texto de comandos de plugin (357) y scripts simples
ANCHO = 52  # caracteres visibles por línea en la ventana de mensajes

DB = {
    "Actors": ("name", "nickname", "profile"),
    "Classes": ("name",),
    "Skills": ("name", "description", "message1", "message2"),
    "Items": ("name", "description"),
    "Weapons": ("name", "description"),
    "Armors": ("name", "description"),
    "Enemies": ("name",),
    "States": ("name", "message1", "message2", "message3", "message4"),
}

cache: dict[str, str] = {}
pendientes: set[str] = set()
modo_contar = False


# ---------- traducción de textos con códigos ----------
def partes(texto: str):
    """Divide en [(es_codigo, trozo)] para no traducir los códigos de texto."""
    return [(i % 2 == 1, t) for i, t in enumerate(CODIGO.split(texto)) if t != ""]


def necesita(t: str) -> bool:
    return bool(JA.search(t))


_kks = None


def romanizar(t: str) -> str:
    """Nombres propios: se escriben en rōmaji (Hepburn), no se traducen."""
    global _kks
    if _kks is None:
        import pykakasi
        _kks = pykakasi.kakasi()
    trozos = [x["hepburn"].strip() for x in _kks.convert(t) if x["hepburn"].strip()]
    return " ".join(p[:1].upper() + p[1:] for p in trozos)


REPETIDO = (re.compile(r"\b((?:\w+\s+){2,5}?)\1", re.I), re.compile(r"\b(\w+)(?:\s+\1\b){2,}", re.I))


def con_repeticion(s: str) -> bool:
    return any(r.search(s) for r in REPETIDO)


def pedir(texto: str, nombre: bool = False):
    """Registra los trozos japoneses de un texto para traducirlos en lote."""
    if nombre:
        return
    for es_cod, t in partes(texto):
        if not es_cod and necesita(t) and t.strip() not in cache:
            pendientes.add(t.strip())


def traducir_pendientes():
    if modo_contar or not pendientes:
        return
    traducir.cargar_modelo()
    lista = sorted(pendientes, key=len)
    for k in range(0, len(lista), 24):
        lote = lista[k:k + 24]
        trozos = [p for s in lote for p in traducir.partir(s)]
        res = iter(traducir.traducir_lote(trozos))
        for s in lote:
            cache[s] = " ".join(next(res) for _ in traducir.partir(s))
    pendientes.clear()


def aplicar(texto: str, nombre: bool = False) -> str:
    out = []
    for es_cod, t in partes(texto):
        if es_cod or not necesita(t):
            out.append(t)
        else:
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            nuevo = romanizar(t.strip()) if nombre else cache.get(t.strip(), t.strip())
            out.append(lead + nuevo + trail)
    return "".join(out)


def visible(s: str) -> int:
    return len(CODIGO.sub("", s))


def envolver(texto: str) -> list[str]:
    lineas, actual = [], ""
    for palabra in texto.split():
        if actual and visible(actual) + 1 + visible(palabra) > ANCHO:
            lineas.append(actual)
            actual = palabra
        else:
            actual = (actual + " " + palabra).strip()
    if actual:
        lineas.append(actual)
    return lineas or [""]


# ---------- recorrido de comandos de evento ----------
def bloques_401(lista):
    """Agrupa comandos consecutivos 401/405 (misma sangría) -> [(inicio, fin, código, sangría)]."""
    out, i = [], 0
    while i < len(lista):
        c = lista[i]
        if c.get("code") in (401, 405):
            j = i
            while j + 1 < len(lista) and lista[j + 1].get("code") == c["code"] \
                    and lista[j + 1].get("indent") == c.get("indent"):
                j += 1
            out.append((i, j, c["code"], c.get("indent", 0)))
            i = j + 1
        else:
            i += 1
    return out


def unir(lista, i, j):
    return "".join(str(lista[k]["parameters"][0]) for k in range(i, j + 1))


def tr_val(v, ejecutar):
    """Valor de argumento de plugin: texto, o JSON dentro de texto, o listas/dicts."""
    if isinstance(v, str):
        if v[:1] in "[{":
            try:
                obj = json.loads(v)
            except ValueError:
                obj = None
            if obj is not None:
                return json.dumps(tr_val(obj, ejecutar), ensure_ascii=False, separators=(",", ":"))
        if necesita(v):
            if not ejecutar:
                pedir(v)
                return v
            return aplicar(v)
        return v
    if isinstance(v, list):
        return [tr_val(x, ejecutar) for x in v]
    if isinstance(v, dict):
        return {k: tr_val(x, ejecutar) for k, x in v.items()}
    return v


SCRIPT_TXT = re.compile(r'(\$gameVariables\.setValue\(\d+,\s*")([^"]*)("\);?)')


def procesar_lista(lista, ejecutar):
    """Primera pasada (ejecutar=False): pide textos. Segunda: aplica traducciones."""
    for c in lista:
        cod, p = c.get("code"), c.get("parameters", [])
        if cod == 101 and len(p) > 4 and isinstance(p[4], str):
            pedir(p[4], True) if not ejecutar else p.__setitem__(4, aplicar(p[4], True))
        elif cod == 102 and p and isinstance(p[0], list):
            for n, s in enumerate(p[0]):
                pedir(s) if not ejecutar else p[0].__setitem__(n, aplicar(s))
        elif PLUG357 and cod == 357 and len(p) >= 4 and isinstance(p[3], dict):
            p[3] = tr_val(p[3], ejecutar)
        elif PLUG357 and cod in (355, 655) and p and isinstance(p[0], str):
            m = SCRIPT_TXT.fullmatch(p[0].strip())
            if m and necesita(m.group(2)):
                if not ejecutar:
                    pedir(m.group(2))
                else:
                    p[0] = m.group(1) + aplicar(m.group(2)) + m.group(3)
    for i, j, cod, ind in reversed(bloques_401(lista)):  # de atrás hacia delante: los índices no se mueven
        texto = unir(lista, i, j)
        if not necesita(texto):
            continue
        if not ejecutar:
            pedir(texto)
            continue
        if cod == 401:
            nuevas = envolver(aplicar(texto))
        else:
            nuevas = [aplicar(str(lista[k]["parameters"][0])) for k in range(i, j + 1)]
        lista[i:j + 1] = [{"code": cod, "indent": ind, "parameters": [s]} for s in nuevas]


def recorrer(x, ejecutar):
    if isinstance(x, dict):
        for k, v in list(x.items()):
            if k == "list" and isinstance(v, list) and v and isinstance(v[0], dict) and "code" in v[0]:
                procesar_lista(v, ejecutar)
            else:
                recorrer(v, ejecutar)
    elif isinstance(x, list):
        for v in x:
            recorrer(v, ejecutar)


def campo(d, k, ejecutar, nombre=False):
    v = d.get(k)
    if isinstance(v, str) and necesita(v):
        pedir(v, nombre) if not ejecutar else d.__setitem__(k, aplicar(v, nombre))


def procesar_archivo(nombre, datos, ejecutar):
    base = nombre[:-5]
    if base in DB:
        for e in datos:
            if e:
                for k in DB[base]:
                    campo(e, k, ejecutar, base == "Actors" and k in ("name", "nickname"))
    elif base == "System":
        t = datos.get("terms", {})
        for sec in ("basic", "commands", "params"):
            lst = t.get(sec, [])
            for n, s in enumerate(lst):
                if isinstance(s, str) and necesita(s):
                    pedir(s) if not ejecutar else lst.__setitem__(n, aplicar(s))
        for k, s in t.get("messages", {}).items():
            if isinstance(s, str) and necesita(s):
                pedir(s) if not ejecutar else t["messages"].__setitem__(k, aplicar(s))
    elif base.startswith("Map") and base != "MapInfos":
        campo(datos, "displayName", ejecutar)
        recorrer(datos.get("events", []), ejecutar)
    elif base in ("CommonEvents", "Troops"):
        recorrer(datos, ejecutar)


def main():
    global modo_contar, PLUG357
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    modo_contar = "--contar" in sys.argv
    PLUG357 = "--plugins" in sys.argv
    if len(args) != 2:
        sys.exit(__doc__)
    origen, destino = Path(args[0]), Path(args[1])
    cache_f = destino.parent / "traduccion_cache.json"
    if cache_f.exists():
        cache.update(json.loads(cache_f.read_text(encoding="utf-8")))
        malas = [k for k, v in cache.items() if con_repeticion(v)]
        for k in malas:  # traducciones con frases repetidas: se vuelven a hacer
            del cache[k]
        print(f"Caché: {len(cache)} frases reutilizadas, {len(malas)} descartadas por repetición", flush=True)

    archivos = sorted(origen.glob("*.json"))
    # Pasada 1: reunir todo el texto japonés (se traduce sin repetir frases)
    for f in archivos:
        procesar_archivo(f.name, json.loads(f.read_text(encoding="utf-8-sig")), False)
    chars = sum(len(s) for s in pendientes)
    print(f"Frases únicas por traducir: {len(pendientes)} ({chars} caracteres)", flush=True)
    if modo_contar:
        return
    t0 = time.time()
    lista = sorted(pendientes, key=len)
    traducir.cargar_modelo()
    hechos = 0
    for k in range(0, len(lista), 24):
        lote = lista[k:k + 24]
        trozos = [p for s in lote for p in traducir.partir(s)]
        res = iter(traducir.traducir_lote(trozos))
        for s in lote:
            cache[s] = " ".join(next(res) for _ in traducir.partir(s))
        hechos += len(lote)
        if (k // 24) % 10 == 0:
            cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"  {hechos}/{len(lista)} frases | {time.time()-t0:.0f}s", flush=True)
    pendientes.clear()
    cache_f.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # Pasada 2: escribir los JSON traducidos
    for f in archivos:
        datos = json.loads(f.read_text(encoding="utf-8-sig"))
        procesar_archivo(f.name, datos, True)
        (destino / f.name).write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")),
                                      encoding="utf-8")
    print("Listo:", len(archivos), "archivos escritos en", destino, flush=True)


if __name__ == "__main__":
    main()
