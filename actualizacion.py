"""Consulta en GitHub si hay una versión más nueva del programa."""

import requests

import config

URL = f"https://api.github.com/repos/{config.REPOSITORIO}/releases/latest"


def _numeros(version: str):
    return tuple(int(p) for p in version.strip().lstrip("vV").split("."))


def buscar():
    """Devuelve (versión, dirección de descarga) si hay una más nueva, o None.

    Nunca falla: sin internet, sin releases o con una respuesta rara simplemente devuelve None.
    """
    try:
        respuesta = requests.get(URL, timeout=5, headers={"Accept": "application/vnd.github+json"})
        respuesta.raise_for_status()
        datos = respuesta.json()
        etiqueta = datos["tag_name"]
        if _numeros(etiqueta) > _numeros(config.VERSION):
            return etiqueta.lstrip("vV"), datos["html_url"]
    except Exception:
        pass
    return None
