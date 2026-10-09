"""Modo video (tiempo real): traduce subtítulos que cambian rápido y muestra cada traducción
durante el mismo tiempo que estuvo su subtítulo original en pantalla.

Tres piezas trabajan a la vez:
- Lector (hilo propio): mira la región muy seguido y la separa en segmentos: cada subtítulo, o
  cada hueco sin subtítulo, con el momento en que apareció y en el que cambió.
- Traducciones (hilos del ejecutor): traducen cada segmento apenas se confirma.
- Reproductor (hilo de la interfaz): muestra los segmentos traducidos en orden, cada uno durante
  lo que duró su original, sin acortar ninguno.

Como la traducción va un poco atrasada respecto del video, el subtítulo original que aparece
mientras tanto se tapa enseguida con un recuadro de su color de fondo.
"""

import difflib
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from PIL import Image

import captura
import config
import ocr
import overlay
import traduccion

TICK_MS = 50  # cada cuánto el reproductor decide si pasar al siguiente subtítulo
ESPERA_TRAS_ERROR = 3  # segundos antes de volver a leer si falló el OCR
PAUSA_MINIMA = 0.02  # segundos entre lecturas aunque el OCR haya tardado más que el intervalo
MAX_VISTOS = 20  # lecturas sin confirmar que se recuerdan (si el texto no se estabiliza nunca)


def parecidas(a: str, b: str) -> bool:
    """Si dos claves (ver ocr.clave) son el mismo subtítulo leído con pequeñas diferencias."""
    if a == b:
        return True
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= config.PARECIDO_MINIMO


@dataclass
class Segmento:
    """Un subtítulo, o un hueco sin subtítulo, tal como estuvo en pantalla."""

    clave: str
    bloques: list
    imagen: Image.Image
    inicio: float  # time.monotonic() de cuando apareció
    fin: float | None = None  # de cuando cambió; None mientras siga en pantalla
    traducciones: list[str] | None = None

    @property
    def listo(self) -> bool:
        return not self.bloques or self.traducciones is not None

    @property
    def duracion(self) -> float | None:
        return None if self.fin is None else self.fin - self.inicio


class Lector(threading.Thread):
    """Mira la región cada INTERVALO_TIEMPO_REAL_MS y la separa en segmentos.

    - `al_tapar(imagen, bloques)`: apenas aparece un texto distinto, sin esperar a confirmarlo,
      para taparlo enseguida.
    - `al_segmento(segmento)`: cuando un texto nuevo se lee igual dos veces seguidas; en ese
      momento el segmento anterior recibe su `fin`. Confirmar con dos lecturas filtra los
      fundidos y los errores sueltos del OCR.
    """

    def __init__(self, region, al_tapar, al_segmento, al_fallar):
        super().__init__(daemon=True)
        self.region = region
        self.al_tapar = al_tapar
        self.al_segmento = al_segmento
        self.al_fallar = al_fallar
        self._parar = threading.Event()

    def detener(self):
        self._parar.set()

    def run(self):
        firma_leida = None  # firma de la última imagen que pasó por el OCR
        tapado = None  # clave de lo último que se mandó a tapar
        vigente = None  # el segmento confirmado que está en pantalla
        vistos = []  # (clave, momento) leídos desde que el texto dejó de ser el de `vigente`
        espera = config.INTERVALO_TIEMPO_REAL_MS / 1000
        while not self._parar.wait(espera):
            momento = time.monotonic()
            try:
                imagen, _ = captura.capturar(self.region)
                firma = captura.firma(imagen)
                sin_cambios = firma_leida is not None and not captura.cambio(firma, firma_leida)
                if sin_cambios and not vistos:
                    continue
                bloques = ocr.reconocer(
                    imagen, lado_maximo=config.LADO_OCR_TIEMPO_REAL, hilos=config.HILOS_OCR_VIDEO
                )
                firma_leida = firma
                actual = ocr.clave(bloques)
                if tapado is None or not parecidas(actual, tapado):
                    tapado = actual
                    self.al_tapar(imagen, bloques)
                if vigente is not None and parecidas(actual, vigente.clave):
                    vistos.clear()  # lo distinto era un error suelto del OCR
                    continue
                vistos = vistos[-MAX_VISTOS:] + [(actual, momento)]
                if len(vistos) >= 2 and parecidas(actual, vistos[-2][0]):
                    # Confirmado. El corte va en la primera vez que se vio este texto, aunque en
                    # el medio haya habido lecturas con errores o un fundido.
                    inicio = next(m for c, m in vistos if parecidas(c, actual))
                    if vigente is not None:
                        vigente.fin = inicio
                    vigente = Segmento(actual, bloques, imagen, inicio=inicio)
                    vistos.clear()
                    self.al_segmento(vigente)
            except ocr.ErrorOcr as e:
                self.al_fallar(str(e))
                self._parar.wait(ESPERA_TRAS_ERROR)
            except Exception as e:
                traceback.print_exc()
                self.al_fallar(f"Error: {e}")
                self._parar.wait(ESPERA_TRAS_ERROR)
            finally:
                # Se descuenta lo que tardó el OCR, para leer cada INTERVALO_TIEMPO_REAL_MS y no
                # cada (intervalo + OCR); la pausa mínima deja respirar al procesador.
                transcurrido = time.monotonic() - momento
                espera = max(PAUSA_MINIMA, config.INTERVALO_TIEMPO_REAL_MS / 1000 - transcurrido)
        # Desde este hilo, para no descartar el motor en medio de una lectura.
        if config.HILOS_OCR_VIDEO != config.HILOS_OCR:  # si no, es el motor de los demás modos
            ocr.liberar(config.HILOS_OCR_VIDEO)


class Reproductor:
    """Decide qué segmento traducido mostrar: en orden, cada uno durante lo que duró su original.

    No acorta nada, ni subtítulos ni silencios. Si una traducción llega tarde, el segmento anterior
    queda más tiempo en pantalla y desde ahí todo sigue con ese atraso: el atraso es el de la
    traducción más demorada desde que se encendió el modo.

    No usa ventanas ni hilos: la interfaz llama a `avanzar` seguido y dibuja `actual` si cambió.
    """

    def __init__(self):
        self.pendientes: deque[Segmento] = deque()
        self.actual: Segmento | None = None
        self.desde: float | None = None  # cuándo se empezó a mostrar `actual`

    def agregar(self, segmento: Segmento):
        self.pendientes.append(segmento)

    def avanzar(self, ahora: float) -> bool:
        """Pasa a los segmentos siguientes que correspondan. Devuelve True si cambió `actual`."""
        cambio = False
        while self.pendientes and self.pendientes[0].listo:
            if self.actual is None:
                self.desde = ahora
            else:
                if self.actual.duracion is None:
                    break  # su original sigue en pantalla
                programado = self.desde + self.actual.duracion
                if ahora < programado:
                    break
                # Si el siguiente estaba listo a tiempo, arranca justo cuando terminó el anterior
                # (así no se acumula el retraso de cada tick); si no, desde ahora.
                desde = programado if ahora - programado < 0.1 else ahora
                self._registrar(self.actual, desde - self.desde)
                self.desde = desde
            self.actual = self.pendientes.popleft()
            cambio = True
        return cambio

    def _registrar(self, segmento: Segmento, mostrado: float):
        """Una línea por segmento en el registro, para poder revisar los tiempos con un video real."""
        texto = " / ".join(segmento.traducciones)[:60] if segmento.bloques else "(silencio)"
        print(
            f"Video: {mostrado:.2f} s en pantalla, original {segmento.duracion:.2f} s, "
            f"atraso {self.desde - segmento.inicio:.2f} s: {texto}"
        )


class ModoTiempoReal:
    """Lo que usa la app: arranca el lector, traduce los segmentos y los va mostrando en el overlay.

    `en_ui(funcion)` hace que `funcion` corra en el hilo de la interfaz (la cola de la app).
    """

    def __init__(self, root, overlay_, region, en_ui):
        self.root = root
        self.overlay = overlay_
        self.region = region
        self.en_ui = en_ui
        self.reproductor = Reproductor()
        self.tapar = None  # (imagen, bloques) de lo que hay ahora en pantalla
        self.aviso = None  # (mensaje, hasta cuándo mostrarlo)
        self.activo = False
        self._redibujar = False
        self._tick = None
        self.lector = None
        self.ejecutor = None

    def iniciar(self) -> bool:
        """Devuelve False si Windows no permite excluir el overlay de las capturas."""
        if not self.overlay.mostrar_atravesable(self.region):
            return False
        self.activo = True
        self.ejecutor = ThreadPoolExecutor(max_workers=2)
        self.lector = Lector(self.region, self._al_tapar, self._al_segmento, self._al_fallar)
        self.lector.start()
        self._tick = self.root.after(TICK_MS, self._avanzar)
        return True

    def detener(self):
        self.activo = False
        if self.lector:
            self.lector.detener()
        if self._tick:
            self.root.after_cancel(self._tick)
            self._tick = None
        if self.ejecutor:
            self.ejecutor.shutdown(wait=False, cancel_futures=True)
        self.overlay.cerrar()

    # ---------- llamados desde el hilo del lector ----------

    def _al_tapar(self, imagen, bloques):
        self.en_ui(lambda: self._nuevo_tapar(imagen, bloques))

    def _al_segmento(self, segmento):
        if not self.activo:
            return
        if segmento.bloques:
            try:
                self.ejecutor.submit(self._traducir, segmento)
            except RuntimeError:
                return  # el ejecutor ya se cerró: el modo se está deteniendo
        self.en_ui(lambda: self.reproductor.agregar(segmento))

    def _al_fallar(self, mensaje):
        self.en_ui(lambda: self._avisar(mensaje))

    # ---------- en los hilos del ejecutor ----------

    def _traducir(self, segmento):
        textos = [b.texto for b in segmento.bloques]
        try:
            segmento.traducciones = traduccion.traducir(textos)
        except Exception as e:
            if not isinstance(e, traduccion.ErrorTraduccion):
                traceback.print_exc()
            mensaje = str(e)
            segmento.traducciones = textos  # se muestra el original para no frenar la reproducción
            self.en_ui(lambda: self._avisar(mensaje))

    # ---------- en el hilo de la interfaz ----------

    def _nuevo_tapar(self, imagen, bloques):
        if self.activo:
            self.tapar = (imagen, bloques)
            self._redibujar = True

    def _avisar(self, mensaje):
        if self.activo:
            self.aviso = (mensaje, time.monotonic() + config.SEGUNDOS_AVISO * 2)
            self._redibujar = True

    def _avanzar(self):
        self._tick = self.root.after(TICK_MS, self._avanzar)
        ahora = time.monotonic()
        if self.reproductor.avanzar(ahora):
            self._redibujar = True
        if self.aviso and ahora > self.aviso[1]:
            self.aviso = None
            self._redibujar = True
        if self._redibujar:
            self._redibujar = False
            self._dibujar()

    def _dibujar(self):
        segmento = self.reproductor.actual
        if segmento is not None and segmento.bloques:
            imagen = overlay.renderizar(
                segmento.imagen, segmento.bloques, segmento.traducciones,
                transparente=True, tapar=self.tapar,
            )
        elif self.tapar is not None:
            imagen = overlay.renderizar(self.tapar[0], [], [], transparente=True, tapar=self.tapar)
        else:
            imagen = overlay.lienzo_transparente((self.region[2], self.region[3]))
        if self.aviso:
            imagen = overlay.con_aviso(imagen, self.aviso[0])
        self.overlay.actualizar(imagen)
