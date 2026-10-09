"""Construye el instalador: entorno limpio -> PyInstaller -> autoprueba del .exe -> Inno Setup.

Uso:       python construir.py
Requiere:  Inno Setup 6  (winget install --id JRSoftware.InnoSetup -e)
Resultado: salida\\TraductorDePantalla-Setup-<VERSION>.exe
"""

import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

from config import VERSION  # la misma que usa la app para avisar de versiones nuevas

NOMBRE = "TraductorDePantalla"

RAIZ = Path(__file__).resolve().parent
BUILD = RAIZ / "build"
VENV = BUILD / "venv"
PYTHON_VENV = VENV / "Scripts" / "python.exe"
DIST = BUILD / "dist" / NOMBRE
ICONO_FUENTE = RAIZ / "recursos" / "icono.ico"  # el que se edita (cualquier tamaño o proporción)
ICONO = BUILD / "icono.ico"  # copia cuadrada y con todos los tamaños: la que se empaqueta
TAMANOS_ICONO = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
SALIDA = RAIZ / "salida"


def paso(titulo):
    print(f"\n=== {titulo}", flush=True)


def correr(*args):
    args = [str(a) for a in args]
    print("  >", " ".join(args), flush=True)
    subprocess.run(args, check=True)


def preparar_entorno():
    """Entorno virtual propio: así PyInstaller no arrastra paquetes globales (torch, etc.)."""
    if not PYTHON_VENV.exists():
        venv.create(VENV, with_pip=True)
    correr(
        PYTHON_VENV, "-m", "pip", "install", "--upgrade", "--quiet",
        "-r", RAIZ / "requirements.txt", "-r", RAIZ / "requirements-build.txt",
    )


def generar_icono():
    """Crea un ícono por defecto si no hay uno en recursos/icono.ico."""
    if ICONO_FUENTE.exists():
        return
    from PIL import Image, ImageDraw, ImageFont

    lado = 256
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, lado - 8, lado - 8), radius=56, fill=(59, 130, 246))
    letra = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 170)
    d.text((40, 4), "A", font=letra, fill="white")
    d.ellipse((128, 128, 244, 244), fill=(249, 115, 22), outline="white", width=8)
    chica = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 50)
    d.text((186, 186), "ES", font=chica, fill="white", anchor="mm")
    ICONO_FUENTE.parent.mkdir(exist_ok=True)
    img.save(ICONO_FUENTE, sizes=TAMANOS_ICONO)


def preparar_icono():
    """Windows necesita íconos cuadrados y con varios tamaños; si no, se ven estirados o borrosos."""
    from PIL import Image

    fuente = Image.open(ICONO_FUENTE)
    if fuente.format == "ICO":  # usar la imagen más grande que traiga el .ico
        fuente.size = max(fuente.ico.sizes(), key=lambda t: t[0] * t[1])
    fuente = fuente.convert("RGBA")
    lado = max(fuente.size)
    cuadrado = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    cuadrado.paste(fuente, ((lado - fuente.width) // 2, (lado - fuente.height) // 2))
    cuadrado = cuadrado.resize((256, 256), Image.LANCZOS)
    BUILD.mkdir(exist_ok=True)
    cuadrado.save(ICONO, sizes=TAMANOS_ICONO)


def empaquetar():
    correr(
        PYTHON_VENV, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onedir",
        "--name", NOMBRE,
        "--icon", ICONO,
        "--add-data", f"{ICONO};recursos",
        "--collect-all", "rapidocr",  # incluye los modelos .onnx y sus .yaml
        "--contents-directory", ".",
        "--exclude-module", "torch",
        "--exclude-module", "paddle",
        "--exclude-module", "openvino",
        "--distpath", BUILD / "dist",
        "--workpath", BUILD / "work",
        "--specpath", BUILD,
        RAIZ / "traductor.py",
    )
    # OpenCV trae FFmpeg para leer videos; el traductor no lo usa.
    for dll in DIST.rglob("opencv_videoio_ffmpeg*.dll"):
        dll.unlink()


def probar_exe():
    exe = DIST / f"{NOMBRE}.exe"
    resultado = subprocess.run([exe, "--autoprueba"], capture_output=True, text=True, timeout=300)
    salida = (resultado.stdout + resultado.stderr).strip()
    if salida:
        print("  " + salida.replace("\n", "\n  "))
    if resultado.returncode == 2:
        print("  Aviso: el OCR anduvo, pero algún servicio de traducción falló (ver arriba).")
    elif resultado.returncode != 0:
        sys.exit(f"El .exe empaquetado falló la autoprueba (código {resultado.returncode}).")


def buscar_iscc():
    candidatos = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for ruta in candidatos:
        if ruta.exists():
            return ruta
    return shutil.which("iscc")


def compilar_instalador():
    iscc = buscar_iscc()
    if not iscc:
        sys.exit("No se encontró Inno Setup 6. Instalalo con: winget install --id JRSoftware.InnoSetup -e")
    correr(
        iscc, "/Q", f"/DMyAppVersion={VERSION}", f"/DCarpetaApp={DIST}", f"/DIconoApp={ICONO}",
        RAIZ / "instalador.iss",
    )
    instalador = SALIDA / f"{NOMBRE}-Setup-{VERSION}.exe"
    tamano_app = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"\nListo: {instalador}")
    print(f"  Instalador: {instalador.stat().st_size / 2**20:.0f} MB  (instalado ocupa {tamano_app / 2**20:.0f} MB)")


if __name__ == "__main__":
    if Path(sys.prefix).resolve() != VENV.resolve():
        paso("1/5 Entorno virtual de construcción")
        preparar_entorno()
        # El resto corre dentro del entorno, que es el que tiene Pillow y PyInstaller.
        sys.exit(subprocess.run([str(PYTHON_VENV), __file__]).returncode)
    paso("2/5 Ícono")
    generar_icono()
    preparar_icono()
    paso("3/5 Empaquetando con PyInstaller")
    empaquetar()
    paso("4/5 Probando el .exe")
    probar_exe()
    paso("5/5 Creando el instalador con Inno Setup")
    compilar_instalador()
