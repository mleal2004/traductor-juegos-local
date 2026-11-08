"""Idiomas disponibles (los 202 del modelo NLLB-200) con nombre en español y equivalencia con el OCR de Windows."""

NOMBRES = {
    "ace_Arab": "Achenés (árabe)", "ace_Latn": "Achenés", "acm_Arab": "Árabe mesopotámico", "acq_Arab": "Árabe taizí-adení",
    "aeb_Arab": "Árabe tunecino", "afr_Latn": "Afrikáans", "ajp_Arab": "Árabe levantino del sur", "aka_Latn": "Akan",
    "als_Latn": "Albanés", "amh_Ethi": "Amárico", "apc_Arab": "Árabe levantino del norte", "arb_Arab": "Árabe estándar",
    "ars_Arab": "Árabe najdí", "ary_Arab": "Árabe marroquí", "arz_Arab": "Árabe egipcio", "asm_Beng": "Asamés",
    "ast_Latn": "Asturiano", "awa_Deva": "Awadhi", "ayr_Latn": "Aimara", "azb_Arab": "Azerí del sur", "azj_Latn": "Azerí",
    "bak_Cyrl": "Baskir", "bam_Latn": "Bambara", "ban_Latn": "Balinés", "bel_Cyrl": "Bielorruso", "bem_Latn": "Bemba",
    "ben_Beng": "Bengalí", "bho_Deva": "Bhoyapurí", "bjn_Arab": "Banjar (árabe)", "bjn_Latn": "Banjar", "bod_Tibt": "Tibetano",
    "bos_Latn": "Bosnio", "bug_Latn": "Buginés", "bul_Cyrl": "Búlgaro", "cat_Latn": "Catalán", "ceb_Latn": "Cebuano",
    "ces_Latn": "Checo", "cjk_Latn": "Chokwe", "ckb_Arab": "Kurdo central", "crh_Latn": "Tártaro de Crimea", "cym_Latn": "Galés",
    "dan_Latn": "Danés", "deu_Latn": "Alemán", "dik_Latn": "Dinka", "dyu_Latn": "Diula", "dzo_Tibt": "Dzongkha",
    "ell_Grek": "Griego", "eng_Latn": "Inglés", "epo_Latn": "Esperanto", "est_Latn": "Estonio", "eus_Latn": "Vasco",
    "ewe_Latn": "Ewé", "fao_Latn": "Feroés", "fij_Latn": "Fiyiano", "fin_Latn": "Finés", "fon_Latn": "Fon", "fra_Latn": "Francés",
    "fur_Latn": "Friulano", "fuv_Latn": "Fulfulde nigeriano", "gaz_Latn": "Oromo", "gla_Latn": "Gaélico escocés",
    "gle_Latn": "Irlandés", "glg_Latn": "Gallego", "grn_Latn": "Guaraní", "guj_Gujr": "Guyaratí", "hat_Latn": "Criollo haitiano",
    "hau_Latn": "Hausa", "heb_Hebr": "Hebreo", "hin_Deva": "Hindi", "hne_Deva": "Chhattisgarhi", "hrv_Latn": "Croata",
    "hun_Latn": "Húngaro", "hye_Armn": "Armenio", "ibo_Latn": "Igbo", "ilo_Latn": "Ilocano", "ind_Latn": "Indonesio",
    "isl_Latn": "Islandés", "ita_Latn": "Italiano", "jav_Latn": "Javanés", "jpn_Jpan": "Japonés", "kab_Latn": "Cabilio",
    "kac_Latn": "Jingpo", "kam_Latn": "Kamba", "kan_Knda": "Canarés", "kas_Arab": "Cachemiro (árabe)",
    "kas_Deva": "Cachemiro (devanagari)", "kat_Geor": "Georgiano", "kaz_Cyrl": "Kazajo", "kbp_Latn": "Kabiyé",
    "kea_Latn": "Criollo caboverdiano", "khk_Cyrl": "Mongol", "khm_Khmr": "Jemer", "kik_Latn": "Kikuyu",
    "kin_Latn": "Kinyarwanda", "kir_Cyrl": "Kirguís", "kmb_Latn": "Kimbundu", "kmr_Latn": "Kurdo del norte",
    "knc_Arab": "Kanuri (árabe)", "knc_Latn": "Kanuri", "kon_Latn": "Kongo", "kor_Hang": "Coreano", "lao_Laoo": "Lao",
    "lij_Latn": "Ligur", "lim_Latn": "Limburgués", "lin_Latn": "Lingala", "lit_Latn": "Lituano", "lmo_Latn": "Lombardo",
    "ltg_Latn": "Latgaliano", "ltz_Latn": "Luxemburgués", "lua_Latn": "Luba-lulua", "lug_Latn": "Luganda", "luo_Latn": "Luo",
    "lus_Latn": "Mizo", "lvs_Latn": "Letón", "mag_Deva": "Magahi", "mai_Deva": "Maithili", "mal_Mlym": "Malayalam",
    "mar_Deva": "Maratí", "min_Latn": "Minangkabau", "mkd_Cyrl": "Macedonio", "mlt_Latn": "Maltés", "mni_Beng": "Manipurí",
    "mos_Latn": "Mossi", "mri_Latn": "Maorí", "mya_Mymr": "Birmano", "nld_Latn": "Neerlandés", "nno_Latn": "Noruego nynorsk",
    "nob_Latn": "Noruego bokmål", "npi_Deva": "Nepalí", "nso_Latn": "Sotho del norte", "nus_Latn": "Nuer", "nya_Latn": "Chichewa",
    "oci_Latn": "Occitano", "ory_Orya": "Oriya", "pag_Latn": "Pangasinán", "pan_Guru": "Panyabí", "pap_Latn": "Papiamento",
    "pbt_Arab": "Pastún", "pes_Arab": "Persa", "plt_Latn": "Malgache", "pol_Latn": "Polaco", "por_Latn": "Portugués",
    "prs_Arab": "Darí", "quy_Latn": "Quechua", "ron_Latn": "Rumano", "run_Latn": "Kirundi", "rus_Cyrl": "Ruso",
    "sag_Latn": "Sango", "san_Deva": "Sánscrito", "sat_Beng": "Santalí", "scn_Latn": "Siciliano", "shn_Mymr": "Shan",
    "sin_Sinh": "Cingalés", "slk_Latn": "Eslovaco", "slv_Latn": "Esloveno", "smo_Latn": "Samoano", "sna_Latn": "Shona",
    "snd_Arab": "Sindhi", "som_Latn": "Somalí", "sot_Latn": "Sesotho", "spa_Latn": "Español", "srd_Latn": "Sardo",
    "srp_Cyrl": "Serbio", "ssw_Latn": "Suazi", "sun_Latn": "Sundanés", "swe_Latn": "Sueco", "swh_Latn": "Suajili",
    "szl_Latn": "Silesio", "tam_Taml": "Tamil", "taq_Latn": "Tamasheq", "taq_Tfng": "Tamasheq (tifinagh)", "tat_Cyrl": "Tártaro",
    "tel_Telu": "Telugu", "tgk_Cyrl": "Tayiko", "tgl_Latn": "Tagalo", "tha_Thai": "Tailandés", "tir_Ethi": "Tigriña",
    "tpi_Latn": "Tok pisin", "tsn_Latn": "Setsuana", "tso_Latn": "Tsonga", "tuk_Latn": "Turcomano", "tum_Latn": "Tumbuka",
    "tur_Latn": "Turco", "twi_Latn": "Twi", "tzm_Tfng": "Tamazight", "uig_Arab": "Uigur", "ukr_Cyrl": "Ucraniano",
    "umb_Latn": "Umbundu", "urd_Arab": "Urdu", "uzn_Latn": "Uzbeko", "vec_Latn": "Véneto", "vie_Latn": "Vietnamita",
    "war_Latn": "Waray", "wol_Latn": "Wolof", "xho_Latn": "Xhosa", "ydd_Hebr": "Yidis", "yor_Latn": "Yoruba",
    "yue_Hant": "Cantonés", "zho_Hans": "Chino simplificado", "zho_Hant": "Chino tradicional", "zsm_Latn": "Malayo",
    "zul_Latn": "Zulú",
}
CODIGOS = sorted(NOMBRES)
POPULARES = ["jpn_Jpan", "eng_Latn", "spa_Latn", "zho_Hans", "zho_Hant", "kor_Hang", "fra_Latn", "deu_Latn", "ita_Latn", "por_Latn",
             "rus_Cyrl", "arb_Arab", "hin_Deva", "tur_Latn", "pol_Latn", "nld_Latn", "vie_Latn", "tha_Thai", "ind_Latn", "ukr_Cyrl", "cat_Latn"]

# Etiqueta de idioma del OCR de Windows (se comprueba que esté instalado en el equipo)
WINDOWS = {
    "eng_Latn": "en", "spa_Latn": "es", "jpn_Jpan": "ja", "kor_Hang": "ko", "zho_Hans": "zh-Hans", "zho_Hant": "zh-Hant",
    "yue_Hant": "zh-Hant", "fra_Latn": "fr", "deu_Latn": "de", "ita_Latn": "it", "por_Latn": "pt", "rus_Cyrl": "ru",
    "arb_Arab": "ar", "hin_Deva": "hi", "tur_Latn": "tr", "pol_Latn": "pl", "nld_Latn": "nl", "swe_Latn": "sv", "dan_Latn": "da",
    "nob_Latn": "nb", "nno_Latn": "nn", "fin_Latn": "fi", "ces_Latn": "cs", "ell_Grek": "el", "heb_Hebr": "he", "tha_Thai": "th",
    "vie_Latn": "vi", "ind_Latn": "id", "ukr_Cyrl": "uk", "hun_Latn": "hu", "ron_Latn": "ro", "bul_Cyrl": "bg", "hrv_Latn": "hr",
    "slk_Latn": "sk", "slv_Latn": "sl", "srp_Cyrl": "sr-Cyrl", "cat_Latn": "ca", "lit_Latn": "lt", "lvs_Latn": "lv",
    "est_Latn": "et", "zsm_Latn": "ms", "ben_Beng": "bn", "tam_Taml": "ta", "tel_Telu": "te", "mar_Deva": "mr", "urd_Arab": "ur",
    "pes_Arab": "fa", "isl_Latn": "is", "gle_Latn": "ga", "cym_Latn": "cy", "eus_Latn": "eu", "glg_Latn": "gl", "kaz_Cyrl": "kk",
}
SIN_ESPACIOS = ("jpn_Jpan", "zho_Hans", "zho_Hant", "yue_Hant", "tha_Thai")   # no usan espacios entre palabras
CJK = ("jpn_Jpan", "zho_Hans", "zho_Hant", "yue_Hant", "kor_Hang")


# Glosario de menús y botones típicos de juegos japoneses: el modelo traduce mal las frases de 1–3 palabras,
# así que estas se traducen por diccionario (japonés → español / inglés).
GLOSARIO = {
    ("jpn_Jpan", "spa_Latn"): {
        "はじめから": "Nueva partida", "初めから": "Nueva partida", "ニューゲーム": "Nueva partida", "つづきから": "Continuar", "続きから": "Continuar",
        "コンティニュー": "Continuar", "ロード": "Cargar", "セーブ": "Guardar", "ロードする": "Cargar", "セーブする": "Guardar",
        "コンフィグ": "Opciones", "オプション": "Opciones", "設定": "Ajustes", "環境設定": "Ajustes", "ゲームをおわる": "Salir del juego",
        "ゲームを終わる": "Salir del juego", "ゲーム終了": "Salir del juego", "終了": "Salir", "おわる": "Salir", "やめる": "Salir",
        "スキップ": "Saltar", "オート": "Auto", "バックログ": "Historial", "ログ": "Historial", "ギャラリー": "Galería", "回想": "Recuerdos",
        "回想モード": "Recuerdos", "CGモード": "Galería de CG", "音楽": "Música", "タイトルへ": "Volver al título", "タイトルに戻る": "Volver al título",
        "戻る": "Volver", "閉じる": "Cerrar", "はい": "Sí", "いいえ": "No", "決定": "Aceptar", "キャンセル": "Cancelar", "メニュー": "Menú",
        "ステータス": "Estado", "アイテム": "Objetos", "スキル": "Habilidades", "装備": "Equipo", "セーブデータ": "Datos guardados",
        "クイックセーブ": "Guardado rápido", "クイックロード": "Carga rápida", "全画面": "Pantalla completa", "ウィンドウ": "Ventana",
    },
    ("jpn_Jpan", "eng_Latn"): {
        "はじめから": "New Game", "初めから": "New Game", "ニューゲーム": "New Game", "つづきから": "Continue", "続きから": "Continue",
        "コンティニュー": "Continue", "ロード": "Load", "セーブ": "Save", "コンフィグ": "Options", "オプション": "Options", "設定": "Settings",
        "ゲームをおわる": "Quit Game", "ゲームを終わる": "Quit Game", "ゲーム終了": "Quit Game", "終了": "Quit", "スキップ": "Skip",
        "オート": "Auto", "バックログ": "Log", "ギャラリー": "Gallery", "回想": "Recollections", "戻る": "Back", "閉じる": "Close",
        "はい": "Yes", "いいえ": "No", "決定": "OK", "キャンセル": "Cancel", "メニュー": "Menu",
    },
}


def buscar_glosario(texto: str, origen: str, destino: str):
    """Traducción del glosario si el texto (sin espacios ni signos finales) coincide exactamente; si no, None."""
    d = GLOSARIO.get((origen, destino))
    if not d:
        return None
    t = texto.strip().replace(" ", "").replace("　", "").rstrip("。、…・!！?？")
    return d.get(t)


def nombre(cod: str) -> str:
    return NOMBRES.get(cod, cod)


def lista_ordenada():
    """Populares primero y luego el resto por nombre."""
    resto = sorted((c for c in CODIGOS if c not in POPULARES), key=lambda c: nombre(c).lower())
    return POPULARES + resto
