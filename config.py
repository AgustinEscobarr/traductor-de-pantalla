"""Configuración del traductor de pantalla.

Estos son los valores por defecto. Lo que el usuario cambia desde la ventana de Ajustes
(idiomas, atajos, espera del modo automático) se guarda en ARCHIVO_AJUSTES y pisa estos valores.
"""

import json
import os
from pathlib import Path

VERSION = "1.1.0"
REPOSITORIO = "AgustinEscobarr/traductor-de-pantalla"  # de acá se consultan las versiones nuevas

# Idiomas de la traducción (códigos de Google Translate). "auto" detecta el idioma de origen.
IDIOMA_ORIGEN = "auto"
IDIOMA_DESTINO = "es"

# Idiomas que lee el OCR incluido (alfabeto latino, chino y japonés; no lee coreano ni cirílico).
IDIOMAS_ORIGEN = {
    "auto": "Automático",
    "en": "Inglés",
    "es": "Español",
    "pt": "Portugués",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
    "zh-CN": "Chino",
    "ja": "Japonés",
}
IDIOMAS_DESTINO = {
    "es": "Español",
    "en": "Inglés",
    "pt": "Portugués",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
    "zh-CN": "Chino simplificado",
    "zh-TW": "Chino tradicional",
    "ja": "Japonés",
    "ko": "Coreano",
    "ru": "Ruso",
}

# Atajos globales: modificadores (ctrl, alt, shift, win) + una tecla (letra, número o F1-F12).
# Se evita Ctrl+Shift+T porque los navegadores lo usan para reabrir pestañas.
ATAJO_TRADUCIR = "ctrl+alt+t"
ATAJO_REPETIR = "ctrl+alt+r"
ATAJO_AUTO = "ctrl+alt+a"
ATAJO_TIEMPO_REAL = "ctrl+alt+s"  # "subtítulos"

# Modo automático: cada cuánto se mira la región y cuánto tiempo tiene que quedarse quieto
# el texto antes de traducirlo (así no se traducen diálogos a medio escribir).
INTERVALO_AUTO_MS = 300
ESPERA_ESTABLE_MS = 700

# Modo video (tiempo real): se mira la región mucho más seguido y cada traducción se muestra
# durante el mismo tiempo que estuvo su subtítulo original en pantalla (sin acortar ninguna).
INTERVALO_TIEMPO_REAL_MS = 100
LADO_OCR_TIEMPO_REAL = 960  # la imagen se achica a esto antes del OCR, para que sea rápido
PARECIDO_MINIMO = 0.85  # dos lecturas así de parecidas son el mismo subtítulo (el OCR varía entre cuadros)

# Fuente usada para dibujar la traducción (se prueban en orden).
FUENTES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]
# Segoe UI no tiene caracteres chinos, japoneses ni coreanos: para esos destinos se prueban antes estas.
FUENTES_POR_IDIOMA = {
    "zh": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"],
    "ja": [r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\msgothic.ttc"],
    "ko": [r"C:\Windows\Fonts\malgun.ttf"],
}
TAMANO_MINIMO_FUENTE = 8

# OCR: regiones más grandes que esto (en píxeles) se achican antes de detectar el texto.
LADO_MAXIMO_OCR = 2000
# Las líneas leídas con menos confianza que esto (0 a 1) se descartan.
CONFIANZA_MINIMA_OCR = 0.5
# Hilos del OCR. Con todos los núcleos lee apenas más rápido, pero entre lectura y lectura los deja
# girando en espera: el modo video llegaba a ocupar 8 núcleos; con 2 ocupa unos 2 y cada lectura
# tarda ~25 ms más.
HILOS_OCR = 2
# El modo video lee casi sin pausa (el video que se mueve detrás del subtítulo cuenta como cambio),
# así que ahí importa más el procesador que gasta cada lectura que lo que tarda: con 2 hilos gasta
# ~2,5 veces lo que dura; con 1 hilo tarda ~50% más pero gasta ~35% menos, y el modo pasa de ocupar
# unos 2,4 núcleos a uno. Usa un motor de OCR aparte (~43 MB, se libera al apagar el modo).
HILOS_OCR_VIDEO = 1

# Color del borde que marca la región traducida.
COLOR_BORDE = (59, 130, 246)
# Color que se vuelve transparente en el overlay del modo automático (uno que casi no aparece en pantalla).
COLOR_TRANSPARENTE = (255, 0, 254)

# Segundos que se muestra un aviso ("No se detectó texto", errores) antes de cerrarse.
SEGUNDOS_AVISO = 2.5

# ---------- ajustes del usuario ----------

CARPETA_DATOS = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TraductorDePantalla"
ARCHIVO_AJUSTES = CARPETA_DATOS / "ajustes.json"
AJUSTES_EDITABLES = (
    "IDIOMA_ORIGEN", "IDIOMA_DESTINO",
    "ATAJO_TRADUCIR", "ATAJO_REPETIR", "ATAJO_AUTO", "ATAJO_TIEMPO_REAL",
    "ESPERA_ESTABLE_MS",
)


def _cargar():
    """Aplica los ajustes guardados; un archivo roto o valores de otro tipo se ignoran."""
    try:
        datos = json.loads(ARCHIVO_AJUSTES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(datos, dict):
        return
    for clave in AJUSTES_EDITABLES:
        valor = datos.get(clave)
        if valor is not None and type(valor) is type(globals()[clave]):
            globals()[clave] = valor


def guardar(**cambios):
    """Cambia ajustes editables (ej. guardar(IDIOMA_DESTINO="en")) y los escribe en disco."""
    for clave, valor in cambios.items():
        if clave not in AJUSTES_EDITABLES:
            raise KeyError(clave)
        globals()[clave] = valor
    try:
        ARCHIVO_AJUSTES.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVO_AJUSTES.write_text(
            json.dumps({c: globals()[c] for c in AJUSTES_EDITABLES}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"No se pudieron guardar los ajustes: {e}")


_cargar()
