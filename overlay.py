"""Dibuja la traducción sobre la captura y la muestra encima de la región original."""

import statistics
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

import config

_fuentes: dict[int, ImageFont.FreeTypeFont] = {}


def _fuente(tamano: int):
    if tamano not in _fuentes:
        for ruta in config.FUENTES:
            try:
                _fuentes[tamano] = ImageFont.truetype(ruta, tamano)
                break
            except OSError:
                continue
        else:
            _fuentes[tamano] = ImageFont.load_default(tamano)
    return _fuentes[tamano]


def _luminancia(color):
    r, g, b = color[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def _distancia(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _color_fondo(imagen: Image.Image, caja):
    """Mediana de los píxeles del anillo que rodea la caja (ahí casi siempre hay solo fondo)."""
    x0, y0, x1, y1 = caja
    w, h = imagen.size
    franjas = [
        (x0, max(y0 - 2, 0), x1, y0),
        (x0, y1, x1, min(y1 + 2, h)),
        (max(x0 - 2, 0), y0, x0, y1),
        (x1, y0, min(x1 + 2, w), y1),
    ]
    pixeles = []
    for f in franjas:
        if f[2] > f[0] and f[3] > f[1]:
            pixeles.extend(imagen.crop(f).getdata())
    if not pixeles:
        pixeles = list(imagen.crop(caja).getdata())
    return tuple(int(statistics.median(p[i] for p in pixeles)) for i in range(3))


def _color_texto(imagen: Image.Image, caja, fondo):
    """Promedio del 10% de píxeles más distintos al fondo; si no contrasta, blanco o negro."""
    pixeles = list(imagen.crop(caja).getdata())
    paso = max(1, len(pixeles) // 20000)
    pixeles = sorted(pixeles[::paso], key=lambda p: _distancia(p, fondo), reverse=True)
    top = pixeles[: max(1, len(pixeles) // 10)]
    color = tuple(sum(p[i] for p in top) // len(top) for i in range(3))
    if abs(_luminancia(color) - _luminancia(fondo)) < 90:
        color = (0, 0, 0) if _luminancia(fondo) > 128 else (255, 255, 255)
    return color


def _partir_en_lineas(draw, texto, fuente, ancho):
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}" if actual else palabra
        if actual and draw.textlength(prueba, font=fuente) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    return lineas


def _ajustar(draw, texto, ancho, alto, tamano_inicial):
    """Busca el tamaño de fuente más grande con el que el texto entra en la caja."""
    tamano = max(tamano_inicial, config.TAMANO_MINIMO_FUENTE)
    while True:
        fuente = _fuente(tamano)
        lineas = _partir_en_lineas(draw, texto, fuente, ancho)
        interlineado = round(tamano * 1.2)
        alto_total = interlineado * len(lineas)
        ancho_total = max(draw.textlength(l, font=fuente) for l in lineas)
        if (alto_total <= alto and ancho_total <= ancho) or tamano <= config.TAMANO_MINIMO_FUENTE:
            return fuente, lineas, interlineado, ancho_total, alto_total
        tamano -= 1


def renderizar(imagen: Image.Image, bloques, traducciones) -> Image.Image:
    original = imagen.convert("RGB")
    salida = original.copy()
    draw = ImageDraw.Draw(salida)
    for bloque, traduccion in zip(bloques, traducciones):
        if not traduccion or traduccion == bloque.texto:
            continue
        x0, y0, x1, y1 = (round(v) for v in bloque.caja)
        x0, y0 = max(x0 - 1, 0), max(y0 - 1, 0)
        x1, y1 = min(x1 + 1, original.width), min(y1 + 1, original.height)
        if x1 <= x0 or y1 <= y0:
            continue
        caja = (x0, y0, x1, y1)
        fondo = _color_fondo(original, caja)
        color = _color_texto(original, caja, fondo)

        ancho, alto = x1 - x0, y1 - y0
        # La caja del OCR mide ~1,3 veces el tamaño de la letra (incluye margen).
        fuente, lineas, interlineado, ancho_t, alto_t = _ajustar(
            draw, traduccion, ancho, alto, round(bloque.alto_linea * 0.78)
        )
        y_texto = y0 + max(0, (alto - alto_t) // 2)
        draw.rectangle(
            (x0, y0, max(x1, x0 + round(ancho_t)), max(y1, y_texto + alto_t)), fill=fondo
        )
        for i, linea in enumerate(lineas):
            draw.text((x0, y_texto + i * interlineado), linea, font=fuente, fill=color)
    return salida


def con_borde(imagen: Image.Image) -> Image.Image:
    imagen = imagen.copy()
    ImageDraw.Draw(imagen).rectangle(
        (0, 0, imagen.width - 1, imagen.height - 1), outline=config.COLOR_BORDE, width=2
    )
    return imagen


def con_aviso(imagen: Image.Image, mensaje: str) -> Image.Image:
    imagen = con_borde(imagen)
    draw = ImageDraw.Draw(imagen)
    fuente = _fuente(14)
    x0, y0, x1, y1 = draw.textbbox((8, 6), mensaje, font=fuente)
    draw.rounded_rectangle((x0 - 6, y0 - 4, x1 + 6, y1 + 4), radius=6, fill=config.COLOR_BORDE)
    draw.text((8, 6), mensaje, font=fuente, fill=(255, 255, 255))
    return imagen


class Overlay:
    """Ventana sin bordes, siempre encima, ubicada exactamente sobre la región traducida.

    Click izquierdo o Esc: cerrar. Click derecho: alternar entre original y traducción.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.ventana = None
        self.etiqueta = None
        self.original = None
        self.traducida = None
        self.viendo_original = False
        self._cierre_programado = None

    def mostrar(self, region, original: Image.Image, mensaje: str | None = None):
        self.cerrar()
        x, y, w, h = region
        self.original = original
        self.traducida = None
        self.viendo_original = False

        self.ventana = tk.Toplevel(self.root)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        self.ventana.geometry(f"{w}x{h}+{x}+{y}")
        self.etiqueta = tk.Label(self.ventana, bd=0, highlightthickness=0, cursor="hand2")
        self.etiqueta.pack(fill="both", expand=True)
        for widget in (self.ventana, self.etiqueta):
            widget.bind("<Button-1>", lambda e: self.cerrar())
            widget.bind("<Button-3>", lambda e: self._alternar())
        self.ventana.bind("<Escape>", lambda e: self.cerrar())
        self._poner_imagen(con_aviso(original, mensaje) if mensaje else con_borde(original))
        self.ventana.focus_force()

    def actualizar(self, traducida: Image.Image):
        if not self.ventana:
            return
        self.traducida = traducida
        self.viendo_original = False
        self._poner_imagen(con_borde(traducida))

    def avisar(self, mensaje: str, cerrar_luego=True):
        if not self.ventana:
            return
        self._poner_imagen(con_aviso(self.original, mensaje))
        if cerrar_luego:
            self._cierre_programado = self.root.after(
                int(config.SEGUNDOS_AVISO * 1000), self.cerrar
            )

    def cerrar(self):
        if self._cierre_programado:
            self.root.after_cancel(self._cierre_programado)
            self._cierre_programado = None
        if self.ventana:
            self.ventana.destroy()
        self.ventana = self.etiqueta = None

    @property
    def visible(self):
        return self.ventana is not None

    def _alternar(self):
        if self.traducida is None:
            return
        self.viendo_original = not self.viendo_original
        imagen = self.original if self.viendo_original else self.traducida
        self._poner_imagen(con_borde(imagen))

    def _poner_imagen(self, imagen: Image.Image):
        foto = ImageTk.PhotoImage(imagen)
        self.etiqueta.configure(image=foto)
        self.etiqueta.image = foto  # evitar que el recolector de basura la borre
