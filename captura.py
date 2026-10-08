"""Captura de pantalla y selector de región sobre la pantalla "congelada"."""

import tkinter as tk

import mss
from PIL import Image, ImageEnhance, ImageTk


def capturar(region=None):
    """Captura `region` = (x, y, ancho, alto) en coordenadas del escritorio virtual.

    Sin región captura todos los monitores. Devuelve (imagen, (x, y, ancho, alto)).
    """
    with mss.mss() as sct:
        if region is None:
            m = sct.monitors[0]
            region = (m["left"], m["top"], m["width"], m["height"])
        x, y, w, h = region
        foto = sct.grab({"left": x, "top": y, "width": w, "height": h})
    return Image.frombytes("RGB", foto.size, foto.bgra, "raw", "BGRX"), region


class SelectorRegion:
    """Muestra la captura a pantalla completa oscurecida y deja marcar un rectángulo.

    Llama a `al_terminar(region, recorte)`, o a `al_terminar(None, None)` si se cancela (Esc / click derecho).
    """

    def __init__(self, root: tk.Tk, captura: Image.Image, origen, al_terminar):
        self.captura = captura
        self.ox, self.oy, w, h = origen
        self.al_terminar = al_terminar
        self.inicio = None
        self.rect = None
        self.resaltado = None
        self.foto_resaltado = None

        self.ventana = tk.Toplevel(root)
        self.ventana.overrideredirect(True)
        self.ventana.attributes("-topmost", True)
        self.ventana.geometry(f"{w}x{h}+{self.ox}+{self.oy}")

        self.canvas = tk.Canvas(
            self.ventana, width=w, height=h, highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack()
        oscura = ImageEnhance.Brightness(captura).enhance(0.55)
        self.foto_fondo = ImageTk.PhotoImage(oscura)
        self.canvas.create_image(0, 0, image=self.foto_fondo, anchor="nw")
        self.canvas.create_text(  # centrado en el monitor principal, que empieza en (0, 0)
            root.winfo_screenwidth() // 2 - self.ox, 30 - self.oy,
            text="Arrastrá para marcar el texto a traducir  ·  Esc para cancelar",
            fill="white", font=("Segoe UI", 13, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._presionar)
        self.canvas.bind("<B1-Motion>", self._mover)
        self.canvas.bind("<ButtonRelease-1>", self._soltar)
        self.canvas.bind("<Button-3>", lambda e: self._terminar(None))
        self.ventana.bind("<Escape>", lambda e: self._terminar(None))
        self.ventana.lift()
        self.ventana.focus_force()

    def _presionar(self, e):
        self.inicio = (e.x, e.y)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#3b82f6", width=2)

    def _caja(self, e):
        x0, y0 = self.inicio
        x = min(max(e.x, 0), self.captura.width)
        y = min(max(e.y, 0), self.captura.height)
        return min(x0, x), min(y0, y), max(x0, x), max(y0, y)

    def _mover(self, e):
        if not self.inicio:
            return
        x0, y0, x1, y1 = self._caja(e)
        if self.resaltado:
            self.canvas.delete(self.resaltado)
            self.resaltado = None
        if x1 - x0 > 1 and y1 - y0 > 1:
            self.foto_resaltado = ImageTk.PhotoImage(self.captura.crop((x0, y0, x1, y1)))
            self.resaltado = self.canvas.create_image(x0, y0, image=self.foto_resaltado, anchor="nw")
        self.canvas.coords(self.rect, x0, y0, x1, y1)
        self.canvas.tag_raise(self.rect)

    def _soltar(self, e):
        if not self.inicio:
            return
        x0, y0, x1, y1 = self._caja(e)
        if x1 - x0 < 8 or y1 - y0 < 8:
            self._terminar(None)
            return
        region = (self.ox + x0, self.oy + y0, x1 - x0, y1 - y0)
        self._terminar(region, self.captura.crop((x0, y0, x1, y1)))

    def _terminar(self, region, recorte=None):
        self.ventana.destroy()
        self.al_terminar(region, recorte)
