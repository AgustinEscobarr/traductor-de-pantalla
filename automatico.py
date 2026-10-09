"""Modo automático: vigila una región y la vuelve a traducir cada vez que su texto cambia."""

import threading
import time
import traceback
from dataclasses import dataclass

import captura
import config
import ocr
import traduccion

ESPERA_TRAS_ERROR = 3  # segundos antes de reintentar si falló el OCR o la traducción
ESPERA_TRAS_LIMITE = 60  # si Google limitó los pedidos, insistir enseguida lo empeora


@dataclass
class _Lectura:
    clave: str  # ver ocr.clave
    bloques: list
    desde: float  # desde cuándo está ese mismo texto en pantalla (time.monotonic)


def _leer(imagen, anterior: _Lectura | None) -> _Lectura:
    """OCR de la imagen. Si el texto es el mismo que antes, conserva desde cuándo está."""
    bloques = ocr.reconocer(imagen)
    clave = ocr.clave(bloques)
    desde = anterior.desde if anterior is not None and anterior.clave == clave else time.monotonic()
    return _Lectura(clave, bloques, desde)


class Vigilante(threading.Thread):
    """Mira `region` cada INTERVALO_AUTO_MS y, cuando su texto cambió y se quedó quieto durante
    ESPERA_ESTABLE_MS, llama a `al_estabilizarse(imagen, bloques)` desde este hilo.

    Esperar a que el texto se quede quieto evita traducir diálogos que aparecen letra por letra.
    El OCR solo corre cuando la imagen cambia, y la traducción solo cuando cambia el texto: con un
    video de fondo se lee seguido, pero se traduce una vez por subtítulo.
    """

    def __init__(self, region, al_estabilizarse, al_fallar):
        super().__init__(daemon=True)
        self.region = region
        self.al_estabilizarse = al_estabilizarse
        self.al_fallar = al_fallar
        self._parar = threading.Event()
        self._olvidar = threading.Event()

    def detener(self):
        self._parar.set()

    def volver_a_traducir(self):
        """Traduce otra vez el texto actual aunque no haya cambiado (ej. se cambió el idioma)."""
        self._olvidar.set()

    def run(self):
        firma_leida = None  # firma de la última imagen que pasó por el OCR
        lectura = None  # el texto en pantalla, esperando quedarse quieto
        traducido = None  # la clave del texto de la última traducción mostrada
        while not self._parar.wait(config.INTERVALO_AUTO_MS / 1000):
            if self._olvidar.is_set():
                self._olvidar.clear()
                traducido = None
            try:
                imagen, _ = captura.capturar(self.region)
                firma = captura.firma(imagen)
                leida_ahora = firma_leida is None or captura.cambio(firma, firma_leida)
                if leida_ahora:
                    lectura = _leer(imagen, lectura)
                    firma_leida = firma
                if lectura.clave == traducido:
                    continue
                if (time.monotonic() - lectura.desde) * 1000 < config.ESPERA_ESTABLE_MS:
                    continue
                if not leida_ahora:
                    # Una última lectura antes de traducir: los cambios chicos (la última letra de
                    # un diálogo) no siempre alcanzan para disparar el OCR.
                    confirmada = _leer(imagen, lectura)
                    firma_leida = firma
                    if confirmada.desde != lectura.desde:
                        lectura = confirmada  # todavía estaba cambiando: esperar de nuevo
                        continue
                    lectura = confirmada
                if self._parar.is_set():
                    return
                self.al_estabilizarse(imagen, lectura.bloques)
                traducido = lectura.clave
            except (traduccion.ErrorTraduccion, ocr.ErrorOcr) as e:
                self.al_fallar(str(e))
                limitado = isinstance(e, traduccion.Limitado)
                self._parar.wait(ESPERA_TRAS_LIMITE if limitado else ESPERA_TRAS_ERROR)
            except Exception as e:
                traceback.print_exc()
                self.al_fallar(f"Error: {e}")
                self._parar.wait(ESPERA_TRAS_ERROR)
