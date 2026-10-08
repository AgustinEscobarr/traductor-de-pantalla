"""Configuración del traductor de pantalla. Editá estos valores a gusto."""

# Idiomas de la traducción (códigos ISO; IDIOMA_ORIGEN puede ser "auto").
# El OCR incluido lee texto en varios idiomas, no depende de esta opción.
IDIOMA_ORIGEN = "en"
IDIOMA_DESTINO = "es"

# Atajos globales: modificadores (ctrl, alt, shift, win) + una tecla (letra, número o F1-F12).
# Se evita Ctrl+Shift+T porque los navegadores lo usan para reabrir pestañas.
ATAJO_TRADUCIR = "ctrl+alt+t"
ATAJO_REPETIR = "ctrl+alt+r"

# Fuente usada para dibujar la traducción (se prueban en orden).
FUENTES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
]
TAMANO_MINIMO_FUENTE = 8

# OCR: regiones más grandes que esto (en píxeles) se achican antes de detectar el texto.
LADO_MAXIMO_OCR = 2000
# Las líneas leídas con menos confianza que esto (0 a 1) se descartan.
CONFIANZA_MINIMA_OCR = 0.5

# Color del borde que marca la región traducida.
COLOR_BORDE = (59, 130, 246)

# Segundos que se muestra un aviso ("No se detectó texto", errores) antes de cerrarse.
SEGUNDOS_AVISO = 2.5
