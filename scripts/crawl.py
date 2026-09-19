#!/usr/bin/env python3
"""Recorre la carpeta publica de Drive de la tienda y vuelca el arbol a data/tree.json.

Usa la vista embebida de Drive (embeddedfolderview), que devuelve HTML plano con el id y el
nombre de cada entrada y no requiere autenticacion. Solo funciona mientras la carpeta siga
compartida con "cualquiera con el enlace".
"""

import concurrent.futures
import json
import os
import re
import urllib.request

import config   # lee el .env de la raiz, el unico sitio con los datos del negocio

ROOT_ID = config.obligatorio("VITE_DRIVE_FOLDER")
ROOT_NAME = config.obligatorio("VITE_STORE")
MAX_DEPTH = 4
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "tree.json")

# Cada entrada de la vista embebida es un bloque "flip-entry" con su id, su nombre y un enlace.
# Foto o carpeta se decide por ese enlace (/folders/ = carpeta) y NO por la extension del
# nombre: en Drive se pueden subir fotos sin extension ("Boss Beige 260mil💣"), y antes el
# crawler las tomaba por carpetas vacias. En Visionary eran 182 de 528 fotos perdidas.
ENTRY = re.compile(r'<div class="flip-entry" id="entry-([\w-]+)"(.*?)(?=<div class="flip-entry"|\Z)', re.S)
ENTRY_TITLE = re.compile(r'flip-entry-title">([^<]*)<')
# Archivos que no son fotos: se ignoran aunque esten en la carpeta.
NO_ES_FOTO = re.compile(r"\.(mp4|mov|avi|m4v|pdf|docx?|xlsx?|txt|zip)\s*$", re.I)


def listing(folder_id):
    """Devuelve [(id, nombre, es_carpeta)] de las entradas directas de una carpeta."""
    url = "https://drive.google.com/embeddedfolderview?id=%s#list" % folder_id
    for intento in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                html = r.read().decode("utf-8", "replace")
            out = []
            for entry_id, bloque in ENTRY.findall(html):
                titulo = ENTRY_TITLE.search(bloque)
                out.append((entry_id, titulo.group(1) if titulo else "", "/folders/" in bloque))
            return out
        except Exception as e:
            if intento == 3:
                print("  !! no se pudo leer %s: %s" % (folder_id, e))
                return []
    return []


def walk(folder_id, name, depth):
    node = {"id": folder_id, "name": name.strip(), "folders": [], "files": []}
    subfolders = []
    for child_id, child_name, es_carpeta in listing(folder_id):
        if es_carpeta:
            subfolders.append((child_id, child_name))
        elif not NO_ES_FOTO.search(child_name):
            node["files"].append({"id": child_id, "name": child_name.strip()})
    if subfolders and depth < MAX_DEPTH:
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            node["folders"] = list(
                pool.map(lambda c: walk(c[0], c[1], depth + 1), subfolders)
            )
    return node


def total_files(node):
    return len(node["files"]) + sum(total_files(c) for c in node["folders"])


def main():
    print("Leyendo Drive: %s" % ROOT_NAME)
    tree = walk(ROOT_ID, ROOT_NAME, 0)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(tree, f, ensure_ascii=False, indent=1)
    print("%d categorias, %d archivos -> %s" % (
        len(tree["folders"]), total_files(tree), os.path.relpath(OUT)))


if __name__ == "__main__":
    main()
