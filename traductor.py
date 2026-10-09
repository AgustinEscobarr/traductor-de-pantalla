"""Traductor de pantalla: marcá una región y mirá su texto traducido encima.

Uso: python traductor.py  (o doble click en iniciar.bat)
"""

import ctypes
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import messagebox

import config  # antes que el registro: define la carpeta de datos

# Tiene que ir antes de crear ventanas: así tkinter y mss usan píxeles reales y las
# coordenadas coinciden aunque Windows tenga escalado de pantalla (125%, 150%...).
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()

# En el .exe sin consola no hay stdout/stderr: los mensajes y errores van a un archivo.
if sys.stderr is None:
    config.CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    _registro = config.CARPETA_DATOS / "registro.log"
    _modo = "w" if _registro.exists() and _registro.stat().st_size > 1_000_000 else "a"
    sys.stdout = sys.stderr = open(_registro, _modo, encoding="utf-8", buffering=1)

import actualizacion
import ajustes
import atajos
import automatico
import captura
import ocr
import overlay
import tiempo_real
import traduccion
import ventanas

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


def codigo_en(codigo, idiomas):
    """El código de `idiomas` que corresponde a `codigo` (ej. "zh-TW" o "zh" -> "zh-CN"), o None."""
    if codigo in idiomas:
        return codigo
    base = codigo.split("-")[0]
    return next((c for c in idiomas if c.split("-")[0] == base), None)


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
        self.vigilante = None  # el modo automático, cuando está activo (nunca arranca solo)
        self.tiempo_real = None  # el modo video, cuando está activo (nunca arranca solo)
        self._mensaje_selector = captura.SelectorRegion.MENSAJE
        self._despues_de_elegir = self._traducir  # qué hacer con la región marcada en el selector
        self.atajos = None
        self.ventana_ajustes = None

        self._crear_barra()
        self._iniciar_atajos()

        self.root.after(50, self._atender_cola)
        self.ejecutor.submit(ocr.precargar)  # si falla, el error se muestra al traducir
        threading.Thread(target=self._buscar_actualizacion, daemon=True).start()

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
        self.boton_auto = self._boton(fila, "▶ Auto", self.alternar_auto)
        self.boton_auto.pack(side="left", padx=(6, 0))
        self.boton_video = self._boton(fila, "▶ Video", self.alternar_tiempo_real)
        self.boton_video.pack(side="left", padx=(6, 0))
        self.boton_idioma = self._boton(fila, "", self._abrir_menu_idioma)
        self.boton_idioma.pack(side="left", padx=(6, 0))
        self._boton(fila, "✕", self.salir).pack(side="left", padx=(6, 0))

        self.ayuda = tk.Label(r, fg=COLORES["tenue"], bg=COLORES["fondo"], font=("Segoe UI", 8), pady=0)
        self.ayuda.pack(fill="x", padx=6, pady=(0, 5))
        # Solo se muestra si hay una versión nueva (ver _avisar_version).
        self.aviso_version = tk.Label(
            r, fg=COLORES["acento"], bg=COLORES["fondo"], font=("Segoe UI", 8, "underline"),
            cursor="hand2", pady=0,
        )

        for widget in (agarre, self.ayuda):
            widget.bind("<ButtonPress-1>", self._empezar_arrastre)
            widget.bind("<B1-Motion>", self._arrastrar)

        self.var_destino = tk.StringVar(value=config.IDIOMA_DESTINO)
        self.menu_idioma = tk.Menu(r, tearoff=0)
        for codigo, nombre in config.IDIOMAS_DESTINO.items():
            self.menu_idioma.add_radiobutton(
                label=nombre, value=codigo, variable=self.var_destino, command=self._elegir_destino
            )
        self.menu_idioma.add_separator()
        self.menu_idioma.add_command(label="⇄  Invertir idiomas", command=self.invertir_idiomas)
        self.menu_idioma.add_command(label="Ajustes…", command=self.abrir_ajustes)
        self._actualizar_textos()

        r.update_idletasks()
        x = r.winfo_screenwidth() - r.winfo_reqwidth() - 40
        y = r.winfo_screenheight() - r.winfo_reqheight() - 100
        r.geometry(f"+{x}+{y}")
        # Que el modo automático no lea la barra si queda encima de la región vigilada.
        ventanas.excluir_de_captura(r)

    def _boton(self, padre, texto, comando, color=None):
        color = color or COLORES["boton"]
        return tk.Button(
            padre, text=texto, command=comando, bg=color, fg=COLORES["texto"],
            activebackground=COLORES["boton_activo"], activeforeground=COLORES["texto"],
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2", font=("Segoe UI", 10),
        )

    def _actualizar_textos(self):
        self.boton_idioma.configure(text=f"→ {config.IDIOMA_DESTINO.upper()} ▾")
        self.var_destino.set(config.IDIOMA_DESTINO)
        fallidos = self.atajos.fallidos if self.atajos else []
        if fallidos:
            ocupados = ", ".join(nombre_atajo(a) for a in fallidos)
            self.ayuda.configure(text=f"Atajo en uso por otro programa: {ocupados} (cambialo en Ajustes)")
        else:
            self.ayuda.configure(
                text=f"{nombre_atajo(config.ATAJO_TRADUCIR)}: traducir  ·  "
                     f"{nombre_atajo(config.ATAJO_REPETIR)}: repetir  ·  "
                     f"{nombre_atajo(config.ATAJO_AUTO)}: auto  ·  "
                     f"{nombre_atajo(config.ATAJO_TIEMPO_REAL)}: video"
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

    # ---------- idiomas y ajustes ----------

    def _abrir_menu_idioma(self):
        b = self.boton_idioma
        try:
            self.menu_idioma.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())
        finally:
            self.menu_idioma.grab_release()

    def _elegir_destino(self):
        config.guardar(IDIOMA_DESTINO=self.var_destino.get())
        self.aplicar_ajustes(atajos_cambiaron=False)

    def invertir_idiomas(self):
        """El idioma del que se venía traduciendo pasa a ser el destino (ej. de es→en a en→es)."""
        origen, destino = config.IDIOMA_ORIGEN, config.IDIOMA_DESTINO
        anterior = origen if origen != "auto" else (traduccion.ultimo_idioma_detectado or "en")
        nuevo_destino = codigo_en(anterior, config.IDIOMAS_DESTINO)
        if nuevo_destino is None or nuevo_destino == destino:
            nuevo_destino = "en" if destino != "en" else "es"
        nuevo_origen = "auto" if origen == "auto" else (codigo_en(destino, config.IDIOMAS_ORIGEN) or "auto")
        config.guardar(IDIOMA_ORIGEN=nuevo_origen, IDIOMA_DESTINO=nuevo_destino)
        self.aplicar_ajustes(atajos_cambiaron=False)

    def abrir_ajustes(self):
        if self.ventana_ajustes and self.ventana_ajustes.existe():
            self.ventana_ajustes.traer_al_frente()
        else:
            self.ventana_ajustes = ajustes.VentanaAjustes(self.root, self.aplicar_ajustes)

    def aplicar_ajustes(self, atajos_cambiaron=True):
        if atajos_cambiaron:
            self._iniciar_atajos()
        else:
            self._actualizar_textos()
        if self.vigilante:
            self.vigilante.volver_a_traducir()
        if self.tiempo_real:  # se reinicia para que los subtítulos nuevos salgan en el idioma nuevo
            region = self.tiempo_real.region
            self.detener_tiempo_real()
            self._iniciar_tiempo_real(region)

    def _iniciar_atajos(self):
        if self.atajos:
            self.atajos.detener()
        acciones = {
            config.ATAJO_TRADUCIR: self.traducir_region,
            config.ATAJO_REPETIR: self.repetir,
            config.ATAJO_AUTO: self.alternar_auto,
            config.ATAJO_TIEMPO_REAL: self.alternar_tiempo_real,
        }
        self.atajos = atajos.AtajosGlobales(
            {atajo: (lambda f=accion: self.cola.put(f)) for atajo, accion in acciones.items()}
        )
        self.atajos.iniciar()
        self._actualizar_textos()

    # ---------- versión nueva ----------

    def _buscar_actualizacion(self):
        """Corre en un hilo aparte: una sola consulta a GitHub al abrir el programa."""
        nueva = actualizacion.buscar()
        if nueva:
            self.cola.put(lambda: self._avisar_version(*nueva))

    def _avisar_version(self, version, url):
        self.aviso_version.configure(text=f"Nueva versión {version} disponible · clic para descargar")
        self.aviso_version.bind("<Button-1>", lambda e: webbrowser.open(url))
        self.aviso_version.pack(fill="x", padx=6, pady=(0, 5))

    # ---------- modo simple: marcar una región y traducirla una vez ----------

    def traducir_region(self):
        self._elegir_region(self._traducir)

    def _elegir_region(self, despues, mensaje=captura.SelectorRegion.MENSAJE):
        """Abre el selector; con la región marcada llama a `despues(region, recorte)`."""
        if self.ocupado:
            return
        self.detener_continuo()
        self.ocupado = True
        self._despues_de_elegir = despues
        self._mensaje_selector = mensaje
        self.overlay.cerrar()
        self._ocultar_barra()
        self.root.after(ESPERA_OCULTAR_MS, self._abrir_selector)

    def _abrir_selector(self):
        imagen, origen = captura.capturar()
        captura.SelectorRegion(self.root, imagen, origen, self._region_elegida, self._mensaje_selector)

    def _region_elegida(self, region, recorte):
        self._mostrar_barra()
        self.ocupado = False
        if region is not None:
            self.ultima_region = region
            self._despues_de_elegir(region, recorte)

    def repetir(self):
        """Vuelve a capturar y traducir la última región (útil para diálogos que cambian)."""
        if self.ocupado:
            return
        if self.ultima_region is None:
            self.traducir_region()
            return
        self.detener_continuo()
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

    # ---------- modo automático: la región se vuelve a traducir sola cuando su texto cambia ----------

    def alternar_auto(self):
        if self.vigilante:
            self.detener_auto()
        elif self.ultima_region is not None:
            self._iniciar_auto(self.ultima_region)
        else:
            self._elegir_region(self._iniciar_auto)

    def _iniciar_auto(self, region, recorte=None):
        if self.ocupado:
            return
        self.detener_continuo()
        self.tarea += 1  # descarta una traducción simple que todavía esté en curso
        if not self.overlay.mostrar_atravesable(region):
            self.ayuda.configure(text="El modo automático necesita Windows 10 versión 2004 o posterior")
            return
        self.ultima_region = region
        vigilante = automatico.Vigilante(
            region,
            al_estabilizarse=lambda imagen, bloques: self._traducir_auto(vigilante, imagen, bloques),
            al_fallar=lambda mensaje: self.cola.put(lambda: self._aviso_auto(vigilante, mensaje)),
        )
        self.vigilante = vigilante
        vigilante.start()
        self.boton_auto.configure(text="■ Auto", bg=COLORES["acento"])

    def detener_auto(self):
        if not self.vigilante:
            return
        self.vigilante.detener()
        self.vigilante = None
        self.overlay.cerrar()
        self.boton_auto.configure(text="▶ Auto", bg=COLORES["boton"])

    def _traducir_auto(self, vigilante, imagen, bloques):
        """Corre en el hilo del vigilante. Sin texto en pantalla, el overlay queda vacío."""
        if bloques:
            traducciones = traduccion.traducir([b.texto for b in bloques])
            salida = overlay.renderizar(imagen, bloques, traducciones, transparente=True)
        else:
            salida = overlay.lienzo_transparente(imagen.size)
        self.cola.put(lambda: self._mostrar_auto(vigilante, salida))

    def _mostrar_auto(self, vigilante, imagen):
        if vigilante is self.vigilante:  # si no, el modo automático ya se apagó
            self.overlay.actualizar(imagen)

    def _aviso_auto(self, vigilante, mensaje):
        if vigilante is self.vigilante:
            self.overlay.avisar(mensaje, cerrar_luego=False)

    # ---------- modo video: subtítulos en tiempo real, con el mismo tiempo de lectura ----------

    def alternar_tiempo_real(self):
        if self.tiempo_real:
            self.detener_tiempo_real()
        elif self.ultima_region is not None:
            self._iniciar_tiempo_real(self.ultima_region)
        else:
            self._elegir_region(
                self._iniciar_tiempo_real, mensaje="Marcá la zona donde aparecen los subtítulos"
            )

    def _iniciar_tiempo_real(self, region, recorte=None):
        if self.ocupado:
            return
        self.detener_continuo()
        self.tarea += 1  # descarta una traducción simple que todavía esté en curso
        modo = tiempo_real.ModoTiempoReal(self.root, self.overlay, region, self.cola.put)
        if not modo.iniciar():
            self.ayuda.configure(text="El modo video necesita Windows 10 versión 2004 o posterior")
            return
        self.ultima_region = region
        self.tiempo_real = modo
        self.boton_video.configure(text="■ Video", bg=COLORES["acento"])

    def detener_tiempo_real(self):
        if not self.tiempo_real:
            return
        self.tiempo_real.detener()
        self.tiempo_real = None
        self.boton_video.configure(text="▶ Video", bg=COLORES["boton"])

    def detener_continuo(self):
        """Apaga el modo automático o el de video (comparten el overlay, nunca van juntos)."""
        self.detener_auto()
        self.detener_tiempo_real()

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
        self.detener_continuo()
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

    Devuelve 0 si todo anduvo, 2 si el OCR anduvo pero algún servicio de traducción no
    (ej. sin internet), 1 si falló el OCR.
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
    resultados = traduccion.probar_proveedores(texto)
    for proveedor, resultado in resultados.items():
        print(f"Traducción ({proveedor}): {resultado!r}" if isinstance(resultado, str)
              else f"Traducción ({proveedor}) falló: {resultado}")
    if any(isinstance(r, Exception) for r in resultados.values()):
        return 2
    try:
        traducida, aviso = procesar(imagen)
    except traduccion.ErrorTraduccion as e:
        print(f"Traducción: {e}")
        return 2
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
