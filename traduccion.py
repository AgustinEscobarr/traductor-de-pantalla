"""Traducción con los servicios gratuitos de Google Translate (sin API key).

Se usan dos direcciones distintas del servicio: si Google cambia o bloquea una (a otros
traductores ya les pasó), se sigue traduciendo con la otra.
"""

import collections

import requests

import config

URL_GTX = "https://translate.googleapis.com/translate_a/single"
URL_DICT = "https://clients5.google.com/translate_a/t"
MAX_BYTES = 4000  # por pedido (POST)
MAX_BYTES_URL = 1500  # por pedido cuando el texto va en la dirección (GET)
TIEMPO_MAXIMO = 8  # segundos por pedido

MENSAJE_CAMBIO = "El servicio de traducción cambió o no responde. Buscá una versión nueva del programa."

_cache: dict[tuple[str, str, str], str] = {}  # (origen, destino, texto) -> traducción
_sesion = requests.Session()
_preferido = 0  # índice en PROVEEDORES del último que anduvo
ultimo_idioma_detectado = None  # cuando el origen es "auto", el idioma que detectó Google


class ErrorTraduccion(RuntimeError):
    pass


class SinConexion(ErrorTraduccion):
    pass


class Limitado(ErrorTraduccion):
    pass


def _pedir(metodo, url, **kwargs):
    """Hace el pedido y devuelve el JSON, convirtiendo cada falla en un ErrorTraduccion entendible."""
    try:
        respuesta = _sesion.request(metodo, url, timeout=TIEMPO_MAXIMO, **kwargs)
    except requests.ConnectionError as e:
        raise SinConexion("Sin conexión a internet.") from e
    except requests.Timeout as e:
        raise ErrorTraduccion("El servicio de traducción no respondió a tiempo.") from e
    except requests.RequestException as e:
        raise ErrorTraduccion(MENSAJE_CAMBIO) from e
    if respuesta.status_code == 429:
        raise Limitado("Google limitó los pedidos por un rato. Probá de nuevo en unos minutos.")
    if not respuesta.ok:
        raise ErrorTraduccion(MENSAJE_CAMBIO)
    try:
        return respuesta.json()
    except ValueError as e:
        raise ErrorTraduccion(MENSAJE_CAMBIO) from e


def _lotes(textos: list[str], maximo: int):
    lote, largo = [], 0
    for texto in textos:
        tamano = len(texto.encode("utf-8")) + 1
        if lote and largo + tamano > maximo:
            yield lote
            lote, largo = [], 0
        lote.append(texto)
        largo += tamano
    if lote:
        yield lote


# ---------- proveedores: (textos, origen, destino) -> (traducciones, idioma detectado o None) ----------


def _gtx_uno(texto, origen, destino):
    datos = _pedir(
        "POST", URL_GTX,
        params={"client": "gtx", "sl": origen, "tl": destino, "dt": "t"},
        data={"q": texto},
    )
    try:
        segmentos = datos[0] or []
        traduccion = "".join(s[0] for s in segmentos if s and s[0])
        detectado = datos[2] if len(datos) > 2 and isinstance(datos[2], str) else None
    except (IndexError, TypeError, KeyError) as e:
        raise ErrorTraduccion(MENSAJE_CAMBIO) from e
    return traduccion, detectado


def _google_gtx(textos, origen, destino):
    """Un solo pedido con los textos separados por saltos de línea; si Google cambia la
    cantidad de líneas, los traduce de a uno."""
    traduccion, detectado = _gtx_uno("\n".join(textos), origen, destino)
    partes = traduccion.split("\n")
    if len(partes) != len(textos):
        resultados = [_gtx_uno(t, origen, destino) for t in textos]
        partes = [r[0] for r in resultados]
        detectado = resultados[0][1]
    return [p.strip() for p in partes], detectado


def _google_dict(textos, origen, destino):
    """Un parámetro q por texto; Google devuelve una traducción por cada uno, y con origen
    "auto" también el idioma detectado: [["traducción", "en"], ...]."""
    traducciones, detectados = [], []
    for lote in _lotes(textos, MAX_BYTES_URL):
        params = [("client", "dict-chrome-ex"), ("sl", origen), ("tl", destino)]
        datos = _pedir("GET", URL_DICT, params=params + [("q", t) for t in lote])
        try:
            if len(datos) != len(lote):
                raise ValueError("cantidad de traducciones distinta")
            for item in datos:
                if isinstance(item, str):
                    traducciones.append(item)
                else:
                    traducciones.append(item[0])
                    detectados.append(item[1])
        except (ValueError, IndexError, TypeError, KeyError) as e:
            raise ErrorTraduccion(MENSAJE_CAMBIO) from e
    detectado = collections.Counter(detectados).most_common(1)[0][0] if detectados else None
    return [t.strip() for t in traducciones], detectado


PROVEEDORES = [_google_gtx, _google_dict]


def _mas_relevante(errores: list[ErrorTraduccion]) -> ErrorTraduccion:
    """Si todos fallaron por falta de conexión, eso; si no, el error del servicio."""
    if all(isinstance(e, SinConexion) for e in errores):
        return errores[0]
    limitado = next((e for e in errores if isinstance(e, Limitado)), None)
    return limitado or next(e for e in errores if not isinstance(e, SinConexion))


def _traducir_lote(lote, origen, destino):
    """Prueba los proveedores empezando por el último que anduvo."""
    global _preferido, ultimo_idioma_detectado
    orden = [_preferido] + [i for i in range(len(PROVEEDORES)) if i != _preferido]
    errores = []
    for i in orden:
        try:
            partes, detectado = PROVEEDORES[i](lote, origen, destino)
        except ErrorTraduccion as e:
            errores.append(e)
            continue
        _preferido = i
        if detectado:
            ultimo_idioma_detectado = detectado
        return partes
    raise _mas_relevante(errores)


def traducir(textos: list[str]) -> list[str]:
    """Traduce una lista de textos con la menor cantidad de pedidos posible."""
    origen, destino = config.IDIOMA_ORIGEN, config.IDIOMA_DESTINO
    pendientes = [
        t for t in dict.fromkeys(textos)
        if (origen, destino, t) not in _cache and any(c.isalpha() for c in t)
    ]
    for lote in _lotes(pendientes, MAX_BYTES):
        partes = _traducir_lote(lote, origen, destino)
        _cache.update(((origen, destino, t), p) for t, p in zip(lote, partes))
    return [_cache.get((origen, destino, t), t) for t in textos]


def probar_proveedores(texto="Save your changes", origen="en", destino="es"):
    """Para la autoprueba: {proveedor: traducción, o el error si falló}, probando cada uno por separado."""
    resultado = {}
    for proveedor in PROVEEDORES:
        try:
            resultado[proveedor.__name__] = proveedor([texto], origen, destino)[0][0]
        except ErrorTraduccion as e:
            resultado[proveedor.__name__] = e
    return resultado
