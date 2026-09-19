#!/usr/bin/env python3
"""Lee los datos del negocio desde el .env de la raiz.

Existe para que haya UN solo sitio con el telefono, el nombre y la carpeta de Drive. Ese sitio
es el .env porque lo entienden las dos mitades del proyecto: Vite lo inyecta en la web sin
configurar nada, y aqui se lee con veinte lineas.

Una variable del entorno real gana al archivo, igual que hace Vite: asi lo que se ponga en el
panel de Netlify manda sobre lo que hay escrito aqui.

Uso:  from config import obligatorio;  obligatorio("VITE_DRIVE_FOLDER")
"""

import os
import re

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV = os.path.join(RAIZ, ".env")

# CLAVE=valor   con las comillas opcionales. Ignora comentarios y lineas vacias.
LINEA = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')

_cache = None


def leer():
    """Devuelve los valores del .env como diccionario. El resultado se reutiliza."""
    global _cache
    if _cache is not None:
        return _cache

    valores = {}
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8") as f:
            for linea in f:
                if not linea.strip() or linea.lstrip().startswith("#"):
                    continue
                m = LINEA.match(linea)
                if not m:
                    continue
                clave, valor = m.group(1), m.group(2)
                # Quitar las comillas que envuelven el valor, si las tiene.
                if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                    valor = valor[1:-1]
                valores[clave] = valor

    # El entorno real pisa al archivo, como hace Vite: es lo que permite que el panel de
    # Netlify mande sobre lo escrito en el repositorio.
    for clave in list(valores) + ["VITE_DRIVE_FOLDER", "VITE_STORE", "VITE_WHATSAPP"]:
        if os.environ.get(clave):
            valores[clave] = os.environ[clave]

    _cache = valores
    return valores


def obligatorio(clave):
    """Como leer()[clave], pero explicando que hacer si falta en vez de soltar un KeyError."""
    valor = leer().get(clave)
    if not valor:
        raise SystemExit(
            "Falta '%s' en el archivo .env de la raiz (o esta vacio).\n"
            "Ese archivo es el unico sitio con los datos del negocio; ver CONFIGURACION.md."
            % clave
        )
    return valor


if __name__ == "__main__":
    for clave, valor in sorted(leer().items()):
        print("%-22s %s" % (clave, valor))
