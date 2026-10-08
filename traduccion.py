"""Traducción con el servicio gratuito de Google Translate (sin API key)."""

import requests

import config

URL = "https://translate.googleapis.com/translate_a/single"
MAX_CARACTERES = 4000

_cache: dict[str, str] = {}
_sesion = requests.Session()


class ErrorTraduccion(RuntimeError):
    pass


def _traducir_texto(texto: str) -> str:
    try:
        respuesta = _sesion.post(
            URL,
            params={"client": "gtx", "sl": config.IDIOMA_ORIGEN, "tl": config.IDIOMA_DESTINO, "dt": "t"},
            data={"q": texto},
            timeout=10,
        )
        respuesta.raise_for_status()
        segmentos = respuesta.json()[0] or []
    except requests.RequestException as e:
        raise ErrorTraduccion(f"No se pudo conectar con Google Translate ({e.__class__.__name__}).") from e
    except (ValueError, IndexError, TypeError) as e:
        raise ErrorTraduccion("Respuesta inesperada de Google Translate.") from e
    return "".join(s[0] for s in segmentos if s and s[0])


def _lotes(textos: list[str]):
    lote, largo = [], 0
    for texto in textos:
        if lote and largo + len(texto) + 1 > MAX_CARACTERES:
            yield lote
            lote, largo = [], 0
        lote.append(texto)
        largo += len(texto) + 1
    if lote:
        yield lote


def traducir(textos: list[str]) -> list[str]:
    """Traduce una lista de textos con la menor cantidad de pedidos posible."""
    pendientes = [
        t for t in dict.fromkeys(textos)
        if t not in _cache and any(c.isalpha() for c in t)
    ]
    for lote in _lotes(pendientes):
        partes = _traducir_texto("\n".join(lote)).split("\n")
        if len(partes) != len(lote):
            partes = [_traducir_texto(t) for t in lote]
        _cache.update(zip(lote, (p.strip() for p in partes)))
    return [_cache.get(t, t) for t in textos]
