"""Atajos de teclado globales con la API RegisterHotKey de Windows (sin dependencias extra)."""

import ctypes
import threading
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_NOREPEAT = 0x4000
_MODIFICADORES = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}


def parsear(atajo: str):
    """'ctrl+alt+t' -> (modificadores, código de tecla virtual)."""
    mods, vk = 0, None
    for parte in atajo.lower().replace(" ", "").split("+"):
        if parte in _MODIFICADORES:
            mods |= _MODIFICADORES[parte]
        elif len(parte) == 1 and parte.isalnum():
            vk = ord(parte.upper())
        elif parte.startswith("f") and parte[1:].isdigit() and 1 <= int(parte[1:]) <= 24:
            vk = 0x70 + int(parte[1:]) - 1
        else:
            raise ValueError(f"Tecla no reconocida en el atajo '{atajo}': {parte}")
    if vk is None:
        raise ValueError(f"El atajo '{atajo}' no tiene una tecla principal.")
    return mods, vk


class AtajosGlobales:
    """Registra atajos y llama a su callback (desde un hilo propio) cuando se presionan."""

    def __init__(self, atajos: dict[str, callable]):
        self._atajos = list(atajos.items())
        self._hilo = None
        self._id_hilo = None
        self.fallidos: list[str] = []
        self._listo = threading.Event()

    def iniciar(self):
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()
        self._listo.wait(2)

    def detener(self):
        if self._id_hilo:
            _user32.PostThreadMessageW(self._id_hilo, WM_QUIT, 0, 0)

    def _bucle(self):
        # RegisterHotKey asocia el atajo al hilo que lo registra: los mensajes llegan a este bucle.
        self._id_hilo = _kernel32.GetCurrentThreadId()
        registrados = {}
        for i, (atajo, callback) in enumerate(self._atajos, start=1):
            mods, vk = parsear(atajo)
            if _user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                registrados[i] = callback
            else:
                self.fallidos.append(atajo)  # otro programa ya usa ese atajo
        self._listo.set()

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in registrados:
                registrados[msg.wParam]()
        for i in registrados:
            _user32.UnregisterHotKey(None, i)
