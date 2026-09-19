#!/usr/bin/env python3
"""Comprueba que el catalogo generado en public/ esta completo y cabe en un hosting gratuito.

Valida que cada producto del catalogo tenga sus dos WebP, que no queden imagenes huerfanas,
que no haya referencias repetidas y que el peso quepa en los limites de Cloudflare Pages.
Sale con codigo 1 si algo falla.
"""

import collections
import json
import os
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE = os.path.join(BASE, "public")
CATALOG = os.path.join(SITE, "catalog.json")

CF_MAX_FILES = 20000
CF_MAX_FILE_MB = 25


def main():
    problemas = []

    with open(CATALOG, encoding="utf-8") as f:
        catalog = json.load(f)
    products = catalog["products"]

    refs = [p["ref"] for p in products]
    repetidas = {r for r in refs if refs.count(r) > 1}
    if repetidas:
        problemas.append("referencias repetidas: %s" % sorted(repetidas)[:10])

    # Cada archivo de Drive tiene que tener SU referencia. Si dos la comparten no se nota
    # hasta que la fusion de duplicados se deshace (los bytes de Drive cambian solos) y ese
    # dia salen dos productos con el mismo numero.
    with open(os.path.join(BASE, "data", "refs.json"), encoding="utf-8") as f:
        guardadas = json.load(f)["refs"]
    compartidas = collections.Counter(guardadas.values())
    compartidas = sorted(r for r, n in compartidas.items() if n > 1)
    if compartidas:
        problemas.append("en refs.json hay referencias asignadas a varios archivos de "
                         "Drive: %s" % compartidas[:10])

    esperadas = set(refs)
    for carpeta in ("grid", "full"):
        d = os.path.join(SITE, "img", carpeta)
        presentes = {n[:-5] for n in os.listdir(d) if n.endswith(".webp")}
        faltan = esperadas - presentes
        sobran = presentes - esperadas
        if faltan:
            problemas.append("faltan %d imagenes en img/%s: %s"
                             % (len(faltan), carpeta, sorted(faltan)[:5]))
        if sobran:
            problemas.append("hay %d imagenes huerfanas en img/%s: %s"
                             % (len(sobran), carpeta, sorted(sobran)[:5]))

    suma_categorias = sum(c["count"] for c in catalog["categories"])
    if suma_categorias != len(products):
        problemas.append("los contadores de categoria suman %d pero hay %d productos"
                         % (suma_categorias, len(products)))

    for p in products:
        orden = catalog["sizeOrder"]
        if p["sizes"] != [s for s in orden if s in p["sizes"]]:
            problemas.append("tallas desordenadas en %s: %s" % (p["ref"], p["sizes"]))
            break

    total_bytes, total_files, mayor = 0, 0, 0
    for root, _, files in os.walk(SITE):
        for n in files:
            size = os.path.getsize(os.path.join(root, n))
            total_bytes += size
            total_files += 1
            mayor = max(mayor, size)
    if total_files > CF_MAX_FILES:
        problemas.append("%d archivos, por encima del limite de %d de Cloudflare Pages"
                         % (total_files, CF_MAX_FILES))
    if mayor > CF_MAX_FILE_MB * 1024 * 1024:
        problemas.append("hay un archivo de mas de %d MB" % CF_MAX_FILE_MB)

    con_tallas = [p for p in products if p["sizes"]]
    print("Productos:        %d" % len(products))
    print("Categorias:       %d" % len(catalog["categories"]))
    print("Marcas:           %s" % (", ".join(catalog["brands"]) or "-"))
    print("Con tallas:       %d" % len(con_tallas))
    print("Multitalla (2+):  %d" % len([p for p in con_tallas if len(p["sizes"]) > 1]))
    print("Peso de public/:  %.0f MB en %d archivos" % (total_bytes / 1048576, total_files))
    print("Archivo mayor:    %.1f MB" % (mayor / 1048576))

    if problemas:
        print("\nPROBLEMAS:")
        for p in problemas:
            print("  - %s" % p)
        return 1
    print("\nTodo correcto: catalogo completo. Compilar con: npm run build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
