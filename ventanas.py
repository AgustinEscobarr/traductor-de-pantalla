"""Ajustes de ventanas de Windows que tkinter no ofrece (con ctypes, sin dependencias extra)."""

import ctypes
import tkinter as tk

_user32 = ctypes.windll.user32

WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004 o posterior
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20  # los clics pasan a la ventana de abajo (junto con WS_EX_LAYERED)
WS_EX_TOOLWINDOW = 0x80  # sin botón en la barra de tareas
WS_EX_NOACTIVATE = 0x08000000  # no le quita el foco a la ventana activa


def hwnd(ventana: tk.Misc) -> int:
    """El HWND de la ventana de nivel superior (winfo_id es el de su contenido)."""
    ventana.update_idletasks()
    return _user32.GetParent(ventana.winfo_id())


def excluir_de_captura(ventana: tk.Misc) -> bool:
    """La ventana se sigue viendo, pero las capturas de pantalla ven lo que hay debajo.

    Así el programa puede leer el texto que tapa su propia traducción. También la oculta al
    compartir pantalla. Devuelve False si Windows no lo permite (versiones anteriores a 2004).
    """
    return bool(_user32.SetWindowDisplayAffinity(hwnd(ventana), WDA_EXCLUDEFROMCAPTURE))


def hacer_atravesable(ventana: tk.Misc):
    """Los clics y el foco pasan a lo que haya debajo, como si la ventana no estuviera.

    Llamarla después de `-transparentcolor`, que es lo que vuelve la ventana "layered".
    """
    h = hwnd(ventana)
    estilo = _user32.GetWindowLongW(h, GWL_EXSTYLE)
    _user32.SetWindowLongW(
        h, GWL_EXSTYLE, estilo | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    )
