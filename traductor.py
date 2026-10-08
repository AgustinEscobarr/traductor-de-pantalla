"""Traductor de pantalla: marcá una región y mirá su texto traducido al español encima.

Uso: python traductor.py  (o doble click en iniciar.bat)
"""

import ctypes
import os
import queue
import sys
import tkinter as tk
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

# Tiene que ir antes de crear ventanas: así tkinter y mss usan píxeles reales y las
# coordenadas coinciden aunque Windows tenga escalado de pantalla (125%, 150%...).
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()

# En el .exe sin consola no hay stdout/stderr: los mensajes y errores van a un archivo.
if sys.stderr is None:
    _carpeta_registro = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TraductorDePantalla"
    _carpeta_registro.mkdir(parents=True, exist_ok=True)
    _registro = _carpeta_registro / "registro.log"
    _modo = "w" if _registro.exists() and _registro.stat().st_size > 1_000_000 else "a"
    sys.stdout = sys.stderr = open(_registro, _modo, encoding="utf-8", buffering=1)

import atajos
import captura
import config
import ocr
import overlay
import traduccion

COLORES = {
    "fondo": "#1f2937",
    "boton": "#374151",
    "boton_activo": "#4b5563",
    "acento": "#3b82f6",
    "texto": "#f9fafb",
    "tenue": "#9ca3af",
}
ESPERA_OCULTAR_MS = 150  # tiempo para que la barra/overlay desaparezcan antes de capturar
NOMBRE_MUTEX = "TraductorDePantalla_Instancia"  # el mismo que AppMutex en instalador.iss
CARPETA_RECURSOS = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def ruta_recurso(nombre):
    """Ruta a un archivo incluido con el programa (funciona desde código y desde el .exe)."""
    return CARPETA_RECURSOS / nombre


def procesar(imagen):
    """Corre en el hilo de trabajo. Devuelve (imagen traducida, None) o (None, aviso)."""
    bloques = ocr.reconocer(imagen)
    if not bloques:
        return None, "No se detectó texto"
    traducciones = traduccion.traducir([b.texto for b in bloques])
    return overlay.renderizar(imagen, bloques, traducciones), None


def nombre_atajo(atajo):
    return "+".join(p.capitalize() if len(p) > 1 else p.upper() for p in atajo.split("+"))


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.report_callback_exception = self._error_inesperado
        icono = ruta_recurso("recursos/icono.ico")
        if icono.exists():
            self.root.iconbitmap(default=str(icono))
        self.cola = queue.Queue()  # acciones que otros hilos piden ejecutar en el hilo de la UI
        self.ejecutor = ThreadPoolExecutor(max_workers=1)
        self.overlay = overlay.Overlay(self.root)
        self.ultima_region = None
        self.ocupado = False
        self.tarea = 0  # identifica el pedido vigente para descartar resultados viejos

        self._crear_barra()
        self.atajos = atajos.AtajosGlobales({
            config.ATAJO_TRADUCIR: lambda: self.cola.put(self.traducir_region),
            config.ATAJO_REPETIR: lambda: self.cola.put(self.repetir),
        })
        self.atajos.iniciar()
        if self.atajos.fallidos:
            ocupados = ", ".join(nombre_atajo(a) for a in self.atajos.fallidos)
            self.ayuda.configure(text=f"Atajo en uso por otro programa: {ocupados}")

        self.root.after(50, self._atender_cola)
        self.ejecutor.submit(ocr.precargar)  # si falla, el error se muestra al traducir

    # ---------- barra flotante ----------

    def _crear_barra(self):
        r = self.root
        r.title("Traductor de pantalla")
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=COLORES["fondo"])

        fila = tk.Frame(r, bg=COLORES["fondo"], padx=6, pady=6)
        fila.pack(fill="x")
        agarre = tk.Label(
            fila, text="⠿", fg=COLORES["tenue"], bg=COLORES["fondo"],
            cursor="fleur", font=("Segoe UI", 13),
        )
        agarre.pack(side="left", padx=(0, 4))
        self._boton(fila, "🌐  Traducir región", self.traducir_region, COLORES["acento"]).pack(side="left")
        self._boton(fila, "↻ Repetir", self.repetir).pack(side="left", padx=(6, 0))
        self._boton(fila, "✕", self.salir).pack(side="left", padx=(6, 0))

        self.ayuda = tk.Label(
            r,
            text=f"{nombre_atajo(config.ATAJO_TRADUCIR)}: traducir  ·  "
                 f"{nombre_atajo(config.ATAJO_REPETIR)}: repetir",
            fg=COLORES["tenue"], bg=COLORES["fondo"], font=("Segoe UI", 8), pady=0,
        )
        self.ayuda.pack(fill="x", padx=6, pady=(0, 5))

        for widget in (agarre, self.ayuda):
            widget.bind("<ButtonPress-1>", self._empezar_arrastre)
            widget.bind("<B1-Motion>", self._arrastrar)

        r.update_idletasks()
        x = r.winfo_screenwidth() - r.winfo_reqwidth() - 40
        y = r.winfo_screenheight() - r.winfo_reqheight() - 100
        r.geometry(f"+{x}+{y}")

    def _boton(self, padre, texto, comando, color=None):
        color = color or COLORES["boton"]
        return tk.Button(
            padre, text=texto, command=comando, bg=color, fg=COLORES["texto"],
            activebackground=COLORES["boton_activo"], activeforeground=COLORES["texto"],
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2", font=("Segoe UI", 10),
        )

    def _empezar_arrastre(self, e):
        self._arrastre = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _arrastrar(self, e):
        dx, dy = self._arrastre
        self.root.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")

    def _ocultar_barra(self):
        self.root.attributes("-alpha", 0.0)

    def _mostrar_barra(self):
        self.root.attributes("-alpha", 1.0)
        self.root.attributes("-topmost", True)

    # ---------- flujo principal ----------

    def traducir_region(self):
        if self.ocupado:
            return
        self.ocupado = True
        self.overlay.cerrar()
        self._ocultar_barra()
        self.root.after(ESPERA_OCULTAR_MS, self._abrir_selector)

    def _abrir_selector(self):
        imagen, origen = captura.capturar()
        captura.SelectorRegion(self.root, imagen, origen, self._region_elegida)

    def _region_elegida(self, region, recorte):
        self._mostrar_barra()
        self.ocupado = False
        if region is not None:
            self.ultima_region = region
            self._traducir(region, recorte)

    def repetir(self):
        """Vuelve a capturar y traducir la última región (útil para diálogos que cambian)."""
        if self.ocupado:
            return
        if self.ultima_region is None:
            self.traducir_region()
            return
        self.ocupado = True
        self.overlay.cerrar()
        self._ocultar_barra()
        self.root.after(ESPERA_OCULTAR_MS, self._capturar_repeticion)

    def _capturar_repeticion(self):
        try:
            recorte, region = captura.capturar(self.ultima_region)
        finally:
            self._mostrar_barra()
            self.ocupado = False
        self._traducir(region, recorte)

    def _traducir(self, region, imagen):
        self.tarea += 1
        tarea = self.tarea
        self.overlay.mostrar(region, imagen, "Traduciendo…")
        futuro = self.ejecutor.submit(procesar, imagen)
        futuro.add_done_callback(lambda f: self.cola.put(lambda: self._resultado(tarea, f)))

    def _resultado(self, tarea, futuro):
        if tarea != self.tarea or not self.overlay.visible:
            return  # el usuario ya cerró el overlay o pidió otra traducción
        try:
            imagen, aviso = futuro.result()
        except (traduccion.ErrorTraduccion, ocr.ErrorOcr) as e:
            self.overlay.avisar(str(e))
            return
        except Exception as e:
            traceback.print_exc()
            self.overlay.avisar(f"Error: {e}")
            return
        if aviso:
            self.overlay.avisar(aviso)
        else:
            self.overlay.actualizar(imagen)

    # ---------- utilidades ----------

    def _atender_cola(self):
        try:
            while True:
                self.cola.get_nowait()()
        except queue.Empty:
            pass
        self.root.after(50, self._atender_cola)

    def _error_inesperado(self, tipo, valor, tb):
        traceback.print_exception(tipo, valor, tb)
        self.ocupado = False
        self._mostrar_barra()
        messagebox.showerror("Traductor de pantalla", f"Ocurrió un error:\n{valor}")

    def salir(self):
        self.atajos.detener()
        self.ejecutor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def ejecutar(self):
        self.root.mainloop()


def ya_esta_abierto():
    """Crea un mutex con nombre; si ya existía, hay otra instancia corriendo."""
    global _mutex
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, NOMBRE_MUTEX)  # se libera al cerrar el proceso
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def autoprueba():
    """OCR + traducción + dibujado sin ventanas, para comprobar el .exe empaquetado.

    Devuelve 0 si todo anduvo, 2 si el OCR anduvo pero la traducción no (sin internet), 1 si falló el OCR.
    """
    from PIL import Image, ImageDraw

    imagen = Image.new("RGB", (560, 70), "white")
    ImageDraw.Draw(imagen).text(
        (12, 18), "Save your changes before closing", font=overlay._fuente(24), fill="black"
    )
    texto = " ".join(b.texto for b in ocr.reconocer(imagen))
    print(f"OCR: {texto!r}")
    if "changes" not in texto:
        return 1
    try:
        traducida, aviso = procesar(imagen)
    except traduccion.ErrorTraduccion as e:
        print(f"Traducción: {e}")
        return 2
    print(f"Traducción: {traduccion.traducir([texto])[0]!r}")
    return 0 if traducida is not None else 1


if __name__ == "__main__":
    if "--autoprueba" in sys.argv:
        sys.exit(autoprueba())
    if ya_esta_abierto():
        ctypes.windll.user32.MessageBoxW(
            None, "El traductor ya está abierto.", "Traductor de pantalla", 0x40
        )
        sys.exit(0)
    App().ejecutar()
