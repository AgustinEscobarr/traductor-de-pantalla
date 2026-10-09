"""Ventana de ajustes: idiomas, atajos de teclado y espera del modo automático."""

import tkinter as tk
from tkinter import ttk

import atajos
import config

ESPERA_MINIMA, ESPERA_MAXIMA = 0.3, 3.0  # segundos
ATAJOS = [
    ("ATAJO_TRADUCIR", "Atajo para traducir una región"),
    ("ATAJO_REPETIR", "Atajo para repetir la última"),
    ("ATAJO_AUTO", "Atajo del modo automático"),
    ("ATAJO_TIEMPO_REAL", "Atajo del modo video"),
]


class VentanaAjustes:
    """Al guardar escribe los ajustes con config.guardar y llama a `al_guardar()`."""

    def __init__(self, root: tk.Tk, al_guardar):
        self.al_guardar = al_guardar
        self.ventana = v = tk.Toplevel(root)
        v.title("Ajustes · Traductor de pantalla")
        v.attributes("-topmost", True)
        v.resizable(False, False)
        marco = ttk.Frame(v, padding=14)
        marco.pack(fill="both", expand=True)
        marco.columnconfigure(1, weight=1)

        self.origen = self._combo(marco, 0, "Idioma del texto en pantalla", config.IDIOMAS_ORIGEN, config.IDIOMA_ORIGEN)
        self.destino = self._combo(marco, 1, "Traducir al", config.IDIOMAS_DESTINO, config.IDIOMA_DESTINO)

        ttk.Separator(marco).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)
        self.atajos = {}
        for fila, (clave, etiqueta) in enumerate(ATAJOS, start=3):
            ttk.Label(marco, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=3, padx=(0, 12))
            self.atajos[clave] = tk.StringVar(value=getattr(config, clave))
            ttk.Entry(marco, textvariable=self.atajos[clave], width=22).grid(row=fila, column=1, sticky="ew", pady=3)
        fila += 1
        ttk.Label(
            marco, foreground="gray",
            text="ctrl, alt, shift o win + una letra, un número o F1-F12. Ej.: ctrl+alt+t",
        ).grid(row=fila, column=0, columnspan=2, sticky="w")

        ttk.Separator(marco).grid(row=fila + 1, column=0, columnspan=2, sticky="ew", pady=10)
        fila += 2
        ttk.Label(marco, text="Modo automático: esperar antes de traducir\n(segundos sin cambios en el texto)").grid(
            row=fila, column=0, sticky="w", padx=(0, 12)
        )
        self.espera = tk.StringVar(value=f"{config.ESPERA_ESTABLE_MS / 1000:.1f}")
        ttk.Spinbox(
            marco, from_=ESPERA_MINIMA, to=ESPERA_MAXIMA, increment=0.1, format="%.1f",
            textvariable=self.espera, width=6,
        ).grid(row=fila, column=1, sticky="w")

        self.error = ttk.Label(marco, foreground="#dc2626", wraplength=380)
        self.error.grid(row=fila + 1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        botones = ttk.Frame(marco)
        botones.grid(row=fila + 2, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(botones, text="Cancelar", command=v.destroy).pack(side="right")
        ttk.Button(botones, text="Guardar", command=self._guardar).pack(side="right", padx=(0, 6))
        v.bind("<Escape>", lambda e: v.destroy())
        v.bind("<Return>", lambda e: self._guardar())

        v.update_idletasks()
        x = (v.winfo_screenwidth() - v.winfo_reqwidth()) // 2
        y = (v.winfo_screenheight() - v.winfo_reqheight()) // 3
        v.geometry(f"+{x}+{y}")
        v.focus_force()

    @staticmethod
    def _combo(padre, fila, etiqueta, idiomas, actual):
        ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=3, padx=(0, 12))
        combo = ttk.Combobox(padre, values=list(idiomas.values()), state="readonly", width=22)
        combo.current(list(idiomas).index(actual) if actual in idiomas else 0)
        combo.grid(row=fila, column=1, sticky="ew", pady=3)
        return combo

    def _guardar(self):
        nuevos = {clave: "".join(var.get().lower().split()) for clave, var in self.atajos.items()}
        try:
            combinaciones = [atajos.parsear(a) for a in nuevos.values()]
        except ValueError as e:
            self.error.configure(text=str(e))
            return
        if len(set(combinaciones)) < len(combinaciones):
            self.error.configure(text="Dos acciones no pueden usar el mismo atajo.")
            return
        try:
            espera = float(self.espera.get().replace(",", "."))
        except ValueError:
            self.error.configure(text="La espera tiene que ser un número de segundos, por ejemplo 0.7.")
            return
        espera = min(max(espera, ESPERA_MINIMA), ESPERA_MAXIMA)

        config.guardar(
            IDIOMA_ORIGEN=list(config.IDIOMAS_ORIGEN)[self.origen.current()],
            IDIOMA_DESTINO=list(config.IDIOMAS_DESTINO)[self.destino.current()],
            ESPERA_ESTABLE_MS=round(espera * 1000),
            **nuevos,
        )
        self.ventana.destroy()
        self.al_guardar()

    def existe(self) -> bool:
        try:
            return bool(self.ventana.winfo_exists())
        except tk.TclError:
            return False

    def traer_al_frente(self):
        self.ventana.deiconify()
        self.ventana.lift()
        self.ventana.focus_force()
