"""OCR con RapidOCR (modelos PaddleOCR sobre ONNX Runtime, incluidos en el programa)
y agrupado de líneas en bloques."""

import statistics
from dataclasses import dataclass, field

from PIL import Image

import config


class ErrorOcr(RuntimeError):
    pass


@dataclass
class Linea:
    texto: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def alto(self):
        return self.y1 - self.y0


@dataclass
class Bloque:
    lineas: list[Linea] = field(default_factory=list)

    @property
    def texto(self):
        texto = ""
        for linea in self.lineas:
            if texto.endswith("-") and linea.texto[:1].islower():
                texto = texto[:-1] + linea.texto  # palabra cortada con guion
            else:
                texto = f"{texto} {linea.texto}" if texto else linea.texto
        return texto

    @property
    def caja(self):
        return (
            min(l.x0 for l in self.lineas),
            min(l.y0 for l in self.lineas),
            max(l.x1 for l in self.lineas),
            max(l.y1 for l in self.lineas),
        )

    @property
    def alto_linea(self):
        return statistics.median(l.alto for l in self.lineas)


_motor = None


def _obtener_motor():
    global _motor
    if _motor is None:
        try:
            from rapidocr import RapidOCR  # import pesado: se hace en el hilo de trabajo

            _motor = RapidOCR(params={
                "Global.use_cls": False,  # el texto de pantalla es horizontal
                "Global.log_level": "error",
                "Global.text_score": config.CONFIANZA_MINIMA_OCR,
                # Por defecto agranda toda imagen a 736 px de lado mínimo: 4 veces más lento
                # y sin mejorar la lectura de texto de pantalla.
                "Det.limit_type": "max",
                "Det.limit_side_len": config.LADO_MAXIMO_OCR,
            })
        except Exception as e:
            raise ErrorOcr(f"No se pudo cargar el motor de OCR ({e}).") from e
    return _motor


def precargar():
    """Carga el modelo de antemano para que la primera traducción no espere."""
    _obtener_motor()


def reconocer_lineas(imagen: Image.Image) -> list[Linea]:
    """Devuelve las líneas de texto con sus cajas en coordenadas de `imagen`.

    Las cajas de RapidOCR incluyen un pequeño margen alrededor de las letras.
    """
    resultado = _obtener_motor()(imagen.convert("RGB"))
    if resultado.boxes is None or resultado.txts is None:
        return []
    lineas = []
    for caja, texto in zip(resultado.boxes, resultado.txts):
        texto = texto.strip()
        if texto:
            xs, ys = caja[:, 0], caja[:, 1]
            lineas.append(
                Linea(texto, float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))
            )
    return lineas


def _pertenece(bloque: Bloque, linea: Linea) -> bool:
    ultima = bloque.lineas[-1]
    alto = min(ultima.alto, linea.alto)
    if not 0.7 <= linea.alto / max(ultima.alto, 1) <= 1.43:
        return False  # tamaños de letra distintos (ej. título y párrafo)
    hueco = linea.y0 - ultima.y1
    if hueco < -0.5 * alto or hueco > 0.5 * alto:  # las cajas de un párrafo casi se tocan
        return False
    x0, _, x1, _ = bloque.caja
    se_solapan = min(x1, linea.x1) - max(x0, linea.x0) > 0
    alineadas = abs(linea.x0 - x0) < 2 * alto
    return se_solapan or alineadas


def agrupar_en_bloques(lineas: list[Linea]) -> list[Bloque]:
    """Une líneas consecutivas de un mismo párrafo (soporta varias columnas)."""
    bloques: list[Bloque] = []
    for linea in sorted(lineas, key=lambda l: (l.y0, l.x0)):
        destino = next((b for b in reversed(bloques) if _pertenece(b, linea)), None)
        if destino is None:
            bloques.append(Bloque([linea]))
        else:
            destino.lineas.append(linea)
    return bloques


def reconocer(imagen: Image.Image) -> list[Bloque]:
    return agrupar_en_bloques(reconocer_lineas(imagen))
