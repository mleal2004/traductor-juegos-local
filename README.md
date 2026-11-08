# traductor-juegos-local

Herramientas para **traducir del japonés al español, sin internet**, textos de videojuegos de PC usando modelos que corren en tu propio equipo (nada se envía a servicios externos).

> ⚠️ **Uso responsable.** Este repositorio no incluye juegos, textos de juegos ni modelos. Úsalo solo con juegos que poseas y para uso personal. La traducción es automática: habrá frases torpes y errores de OCR. Haz siempre copia de seguridad antes de modificar archivos de un juego (los scripts ya crean copias `.bak_antes_de_traducir`).

## Qué incluye

| Archivo | Para qué sirve |
|---|---|
| `traducir.py` | Traduce documentos de texto (`.txt`, `.md`) y contiene el motor de traducción local (NLLB) que usan los demás. |
| `traducir_rpgmaker.py` | RPG Maker MV/MZ: traduce diálogos, opciones, nombres y base de datos de los `.json`. Escribe nombres propios en rōmaji. `--plugins` también traduce argumentos de texto de comandos de plugin. |
| `rpgmaker/ZZ_Cheat.js` | Plugin de trucos para RPG Maker MV/MZ: oro máximo, nivel máximo, daño máximo, interruptores (galería) activados. |
| `traducir_unity_loc.py` | Unity con *Localization*: traduce las tablas de texto de un `.bundle`. |
| `traducir_unity_raw.py` | Unity (Mono): busca cadenas japonesas serializadas en `level*`/`*.assets` y las reescribe en español. |
| `traducir_godot_pck.py` | Godot 4: traduce los `.translation` de un `.pck` y lo reempaqueta. |
| `traductor_local.py` | Servidor local (API tipo LibreTranslate) y ventana que traduce lo que copies al portapapeles. |
| `traductor_ocr.py` | **Aplicación con interfaz**: vista en vivo de la ventana de un juego (aunque otra app la tape), OCR y traducción en tiempo real, capa sobre el juego, selector de 202 idiomas y gestor para descargar/listar/elegir/eliminar modelos. |
| `idiomas.py` | Los 202 idiomas del modelo con nombre en español y su equivalencia con el OCR de Windows. |
| `ocr_windows.ps1` | Puente con el OCR integrado de Windows (para idiomas distintos del japonés). |

## Instalación

Necesitas Python 3.10+ (probado en Windows 11 con Python 3.15).

```bash
pip install -r requirements.txt
```

### Modelos (se descargan una vez)

```bash
# Traducción ja -> es (CTranslate2, ~1,3 GB)
python -c "from huggingface_hub import snapshot_download as s; s('OpenNMT/nllb-200-distilled-1.3B-ct2-int8', local_dir='modelo_nllb')"

# OCR para traductor_ocr.py (~450 MB)
python -c "from huggingface_hub import snapshot_download as s; s('kha-white/manga-ocr-base', local_dir='modelo_ocr', allow_patterns=['*.json','*.txt','*.bin'])"
```

Las carpetas `modelo_nllb` y `modelo_ocr` deben quedar junto a los scripts. También puedes descargarlos (y otros más ligeros o más precisos) desde la propia aplicación `traductor_ocr.py`, botón **⬇ Modelos**.

### Idiomas y OCR
La traducción acepta los 202 idiomas de NLLB-200 (elige origen y destino en la barra superior). El OCR usa **manga-ocr** para japonés y el **OCR de Windows** para el resto de idiomas: Windows solo lee los idiomas que tengan su paquete de OCR instalado (Configuración → Hora e idioma → Idioma y región → Añadir un idioma).

## Uso

```bash
# Documentos
python traducir.py "C:\ruta\a\la\carpeta"

# RPG Maker (copia antes la carpeta data a data_original_ja)
python traducir_rpgmaker.py "juego\data_original_ja" "juego\data"

# Unity con Localization (hace copia del bundle)
python traducir_unity_loc.py "ruta\a\tabla.bundle" eng_Latn

# Unity (Mono): carpeta *_Data
python traducir_unity_raw.py "juego\juego_Data"

# Godot 4
python traducir_godot_pck.py "juego\juego.pck"

# Traductor en vivo por OCR (aplicación con interfaz)
python traductor_ocr.py
python traductor_ocr.py --ventana "parte del título" --origen eng_Latn --destino spa_Latn --auto

# Servidor local (127.0.0.1:5000) o ventana de portapapeles
python traductor_local.py servidor
python traductor_local.py portapapeles
```

Para el plugin de RPG Maker, copia `rpgmaker/ZZ_Cheat.js` a `js/plugins/` del juego y añade una entrada `ZZ_Cheat` al final de `js/plugins.js` con los parámetros `gold`, `level`, `dmg`, `stills` (`"1"` activa) y `switches` (lista JSON de números de interruptores).

## Limitaciones

- Texto cifrado o en formatos propietarios (por ejemplo, empaquetados cifrados) no se puede editar; para esos casos sirve `traductor_ocr.py`.
- Las fuentes del juego pueden no tener tildes ni `ñ`.
- El OCR (manga-ocr) puede fallar en 1 o 2 caracteres por frase.
- El texto en español es más largo que el japonés y puede salirse de los cuadros.

## Licencia

[MIT](LICENSE). Los modelos descargados tienen sus propias licencias (NLLB-200: CC-BY-NC 4.0, uso no comercial; manga-ocr: Apache 2.0).
