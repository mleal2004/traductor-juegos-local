"""Traduce documentos de texto (.txt, .md) del japonés al español, sin internet.

Usa el modelo local NLLB-200 1.3B (CTranslate2, int8) guardado en ./modelo_nllb

Uso:
    pip install ctranslate2 transformers
    python traducir.py <archivo_o_carpeta> [<otro> ...]

- Las carpetas se recorren de forma recursiva.
- Cada archivo X.txt genera X.es.txt al lado; el original no se modifica.
- Los archivos que ya terminan en .es.* se omiten.
"""
import re
import sys
from pathlib import Path

import ctranslate2
from tokenizers import Tokenizer   # solo el tokenizador (no hace falta PyTorch)

MODELO = Path(__file__).parent / "modelo_nllb"
ORIGEN, DESTINO = "jpn_Jpan", "spa_Latn"   # códigos NLLB-200 (ver idiomas.py); se cambian con configurar_idiomas()
EXTENSIONES = {".txt", ".md"}
CODIFICACIONES = ("utf-8-sig", "cp932", "utf-16")  # cp932 = Shift-JIS de Windows
MAX_CHARS = 300  # las líneas más largas se parten por frases
LOTE = 16

# Archivos que no son texto del juego (licencias, logs, depuración): se omiten.
EXCLUIR = ("credits.html", "lib_burst_generated.txt", "bakinplayer_log.txt",
           "dummy.txt", "lng.txt", "readme_en.txt")

_tok = _trad = None


_tok_lang = None


class _Tok:
    """Envoltorio mínimo del tokenizador NLLB: [idioma] + trozos + </s>."""

    def __init__(self, t, origen):
        self.t, self.origen = t, origen

    def tokens(self, texto):
        return [self.origen] + self.t.encode(texto, add_special_tokens=False).tokens + ["</s>"]

    def decode(self, tokens):
        ids = [self.t.token_to_id(x) for x in tokens]
        return self.t.decode([i for i in ids if i is not None], skip_special_tokens=True)


def cargar_modelo():
    global _tok, _trad, _tok_lang
    if _trad is None:
        print("[cargando modelo...]")
        _trad = ctranslate2.Translator(str(MODELO), device="cpu", compute_type="int8",
                                       intra_threads=8)
    if _tok is None or _tok_lang != ORIGEN:   # el tokenizador se recrea solo al cambiar el idioma de origen (es rápido)
        _tok = _Tok(Tokenizer.from_file(str(Path(MODELO) / "tokenizer.json")), ORIGEN)
        _tok_lang = ORIGEN


def configurar_idiomas(origen: str, destino: str):
    """Cambia el par de idiomas (códigos NLLB, p. ej. 'eng_Latn' → 'spa_Latn') sin recargar el modelo.
    El cambio se aplica en la siguiente llamada a cargar_modelo(), así que es seguro hacerlo mientras se traduce."""
    global ORIGEN, DESTINO
    ORIGEN, DESTINO = origen, destino


def leer(ruta: Path) -> str:
    datos = ruta.read_bytes()
    for enc in CODIFICACIONES:
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            continue
    return datos.decode("utf-8", errors="replace")


def partir(linea: str) -> list[str]:
    """Parte una línea larga en frases de hasta MAX_CHARS caracteres."""
    if len(linea) <= MAX_CHARS:
        return [linea]
    frases = re.findall(r".+?(?:[。！？!?]+|[.]+\s|$)", linea)
    trozos, actual = [], ""
    for f in frases:
        if len(actual) + len(f) > MAX_CHARS and actual:
            trozos.append(actual)
            actual = ""
        actual += f
    if actual:
        trozos.append(actual)
    return trozos


def traducir_lote(frases: list[str]) -> list[str]:
    tokens = [_tok.tokens(f) for f in frases]
    res = _trad.translate_batch(tokens, target_prefix=[[DESTINO]] * len(frases),
                                beam_size=4, max_decoding_length=512,
                                no_repeat_ngram_size=3, repetition_penalty=1.15)
    salida = []
    for r in res:
        salida.append(_tok.decode(r.hypotheses[0][1:]))  # quita el prefijo de idioma
    return salida


def traducir_texto(texto: str) -> str:
    lineas = texto.splitlines()
    # Se traducen solo las líneas con contenido; las vacías se conservan.
    # Las viñetas japonesas (〇, ●, ・...) se quitan antes y se reponen después:
    # el modelo las confunde con números ("〇" -> "0").
    viñeta = re.compile(r"^\s*([〇○◯●■□◆◇▼▲★☆・]+)\s*")
    pendientes = []  # (índice de línea, viñeta, [frases])
    for i, l in enumerate(lineas):
        if l.strip():
            m = viñeta.match(l)
            marca = "• " if m and m.group(1)[0] == "・" else (m.group(1) + " " if m else "")
            cuerpo = l[m.end():] if m else l.strip()
            if cuerpo.strip():
                pendientes.append((i, marca, partir(cuerpo.strip())))
    todas = [f for _, _, fs in pendientes for f in fs]
    traducidas = []
    for k in range(0, len(todas), LOTE):
        traducidas += traducir_lote(todas[k:k + LOTE])
    it = iter(traducidas)
    for i, marca, fs in pendientes:
        lineas[i] = marca + " ".join(next(it) for _ in fs)
    return "\n".join(lineas) + "\n"


def traducir_archivo(ruta: Path) -> None:
    destino = ruta.with_suffix(".es" + ruta.suffix)
    if destino.exists():
        print(f"[omitido] ya existe {destino.name}")
        return
    texto = leer(ruta)
    if not texto.strip():
        return
    cargar_modelo()
    print(f"[traduciendo] {ruta}")
    destino.write_text(traducir_texto(texto), encoding="utf-8")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        base = Path(arg)
        archivos = [base] if base.is_file() else sorted(base.rglob("*"))
        for f in archivos:
            if (f.is_file() and f.suffix.lower() in EXTENSIONES
                    and ".es" not in f.suffixes and f.name.lower() not in EXCLUIR):
                try:
                    traducir_archivo(f)
                except Exception as e:  # un archivo con error no detiene el resto
                    print(f"[error] {f}: {e}")


if __name__ == "__main__":
    main()
