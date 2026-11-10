"""Traduce los scripts de diálogo de juegos Unity con el formato «Narrative» (TextAssets con !comandos, :hablantes y texto).

Uso:  python traducir_narrativa.py <archivo .assets> <nombre1,nombre2,...>

Solo se traducen las LÍNEAS DE DIÁLOGO. Se dejan intactos:
  · las líneas que empiezan por !  (comandos: música, personajes, expresiones... son claves que el juego busca por nombre),
  · @etiquetas, #comentarios y :hablantes,
  · las etiquetas [size=..] / <!comando ...> incrustadas dentro del texto.
Se parte siempre del respaldo *.bak_antes_de_traducir (se crea si no existe).
"""
import json
import re
import shutil
import sys
from pathlib import Path

import UnityPy

sys.path.insert(0, str(Path(__file__).parent))
import traductor_local

ETIQUETA = re.compile(r"(\[[^\[\]]*\]|<[^<>]*>)")
HABLANTE = (":", "：")
NO_TEXTO = ("!", "@", "#") + HABLANTE
JP = traductor_local.JA
CACHE: dict[str, str] = {}


def es_dialogo(linea: str) -> bool:
    s = linea.strip()
    return bool(s) and s[0] not in NO_TEXTO and bool(JP.search(s))


def traducir(texto: str) -> str:
    """Traduce una frase conservando las comillas 「」 de apertura y cierre."""
    m = re.match(r"^([「『（(]?)(.*?)([」』）)]?)$", texto, re.S)
    pre, nucleo, post = m.group(1), m.group(2), m.group(3)
    if not JP.search(nucleo):
        return texto
    if nucleo not in CACHE:
        CACHE[nucleo] = traductor_local.traducir_texto(nucleo).replace("\n", " ").strip()
    return pre + CACHE[nucleo] + post


def repartir(texto: str, longitudes: list[int]) -> list[str]:
    """Reparte la traducción en tantas líneas como tenía el original (proporcional a su largo)."""
    n = len(longitudes)
    if n == 1:
        return [texto]
    palabras = texto.split(" ")
    total = max(1, sum(longitudes))
    lineas, actual, acumulado, objetivo = [], [], 0, 0.0
    k = 0
    for p in palabras:
        actual.append(p)
        acumulado += len(p) + 1
        objetivo_k = len(texto) * sum(longitudes[:k + 1]) / total
        if acumulado >= objetivo_k and k < n - 1:
            lineas.append(" ".join(actual))
            actual, k = [], k + 1
    lineas.append(" ".join(actual))
    while len(lineas) < n:
        lineas.append("")
    return lineas


def traducir_linea_con_etiquetas(linea: str) -> str:
    """Traduce solo los trozos de texto japonés y deja las etiquetas tal cual."""
    base = linea.rstrip("\t ")
    cola = linea[len(base):]
    piezas = ETIQUETA.split(base)
    for i in range(0, len(piezas), 2):          # las posiciones pares son texto; las impares, etiquetas
        if JP.search(piezas[i]):
            lead = piezas[i][:len(piezas[i]) - len(piezas[i].lstrip())]
            piezas[i] = lead + traducir(piezas[i].strip())
    return "".join(piezas) + cola


def traducir_bloque(lineas: list[str]) -> list[str]:
    if any(ETIQUETA.search(l) for l in lineas):
        return [traducir_linea_con_etiquetas(l) for l in lineas]
    base = [l.rstrip("\t ") for l in lineas]
    colas = [l[len(b):] for l, b in zip(lineas, base)]
    es = traducir("".join(base))
    partes = repartir(es, [max(1, len(b)) for b in base])
    return [p + c for p, c in zip(partes, colas)]


def traducir_script(texto: str) -> str:
    bom = "﻿" if texto.startswith("﻿") else ""
    lineas = texto.lstrip("﻿").split("\r\n")
    out, i = [], 0
    while i < len(lineas):
        if es_dialogo(lineas[i]):
            j = i
            while j < len(lineas) and es_dialogo(lineas[j]):
                j += 1
            out.extend(traducir_bloque(lineas[i:j]))
            i = j
        else:
            out.append(lineas[i])
            i += 1
    return bom + "\r\n".join(out)


def main():
    ruta = Path(sys.argv[1])
    nombres = set(sys.argv[2].split(","))
    bak = Path(str(ruta) + ".bak_antes_de_traducir")
    if not bak.exists():
        shutil.copy2(ruta, bak)
    cache_f = ruta.parent.parent / "traduccion_cache_narrativa.json"
    if cache_f.exists():
        CACHE.update(json.loads(cache_f.read_text(encoding="utf-8")))
    env = UnityPy.load(str(bak))
    hechos = 0
    for o in env.objects:
        if o.type.name != "TextAsset":
            continue
        d = o.read()
        if d.m_Name not in nombres:
            continue
        original = d.m_Script if isinstance(d.m_Script, str) else bytes(d.m_Script).decode("utf-8", "replace")
        nuevo = traducir_script(original)
        d.m_Script = nuevo
        d.save()
        cache_f.write_text(json.dumps(CACHE, ensure_ascii=False), encoding="utf-8")
        n_orig = sum(1 for l in original.split("\r\n") if es_dialogo(l))
        print(f"  {d.m_Name}: {n_orig} líneas de diálogo traducidas", flush=True)
        hechos += 1
    ruta.write_bytes(env.file.save())
    print(f"Listo: {hechos} scripts escritos en {ruta.name}")


if __name__ == "__main__":
    main()
