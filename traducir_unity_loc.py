"""Pone en español las tablas de Unity Localization (.bundle) de un juego Unity.

Uso:  python traducir_unity_loc.py <bundle> [codigo_origen=eng_Latn]

Traduce el texto de cada tabla (m_Localized) con el modelo local NLLB y lo guarda
en el mismo bundle (antes hace una copia .bak_antes_de_traducir).
Conserva etiquetas <...>, variables {...} y [...].
"""
import re
import shutil
import sys
from pathlib import Path

import ctranslate2
import UnityPy
from transformers import AutoTokenizer

MODELO = Path(__file__).parent / "modelo_nllb"
PROT = re.compile(r"(\{[^{}]*\}|<[^<>]*>|\[[^\[\]]*\]|\\n|\n|\r)")
LETRAS = {"eng_Latn": re.compile(r"[A-Za-z]{2,}"), "jpn_Jpan": re.compile(r"[぀-ヿ一-鿿]")}


def main():
    ruta = Path(sys.argv[1])
    src = sys.argv[2] if len(sys.argv) > 2 else "eng_Latn"
    letras = LETRAS[src]
    tok = AutoTokenizer.from_pretrained(str(MODELO), src_lang=src)
    trad = ctranslate2.Translator(str(MODELO), device="cpu", compute_type="int8", intra_threads=8)

    def traducir(frases):
        toks = [tok.convert_ids_to_tokens(tok.encode(f)) for f in frases]
        res = trad.translate_batch(toks, target_prefix=[["spa_Latn"]] * len(frases),
                                   beam_size=4, max_decoding_length=256)
        return [tok.decode(tok.convert_tokens_to_ids(r.hypotheses[0][1:]), skip_special_tokens=True)
                for r in res]

    bak = Path(str(ruta) + ".bak_antes_de_traducir")
    if not bak.exists():
        shutil.copy2(ruta, bak)
    env = UnityPy.load(str(bak))  # siempre se parte del respaldo original

    objetos = []
    for o in env.objects:
        if o.type.name == "MonoBehaviour":
            t = o.read_typetree()
            if "m_TableData" in t:
                objetos.append((o, t))

    # reunir frases únicas
    pend = sorted({s.strip() for _, t in objetos for e in t["m_TableData"]
                   for tr in [e["m_Localized"]] for s in PROT.split(tr)
                   if s.strip() and not PROT.fullmatch(s) and letras.search(s)}, key=len)
    print(len(pend), "frases únicas por traducir", flush=True)
    cache = {}
    for k in range(0, len(pend), 16):
        lote = pend[k:k + 16]
        for s, r in zip(lote, traducir(lote)):
            cache[s] = r

    def conv(texto):
        out = []
        for p in PROT.split(texto):
            if p and not PROT.fullmatch(p) and letras.search(p):
                lead, trail = p[:len(p) - len(p.lstrip())], p[len(p.rstrip()):]
                out.append(lead + cache.get(p.strip(), p.strip()) + trail)
            else:
                out.append(p)
        return "".join(out)

    n = 0
    for o, t in objetos:
        for e in t["m_TableData"]:
            nuevo = conv(e["m_Localized"])
            if nuevo != e["m_Localized"]:
                e["m_Localized"] = nuevo
                n += 1
        o.save_typetree(t)
    ruta.write_bytes(env.file.save(packer="original"))
    print(n, "entradas traducidas; guardado en", ruta)


if __name__ == "__main__":
    main()
