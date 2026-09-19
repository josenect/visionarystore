#!/usr/bin/env python3
"""Convierte data/tree.json en el catalogo publicable: public/catalog.json + public/img/**.

Pasos: aplanar el arbol -> agrupar variantes de talla por nombre de archivo -> descargar el
JPEG que Drive genera de cada foto -> fusionar duplicados por hash de contenido ->
asignar referencias estables -> codificar WebP en dos tamanos.

Es incremental: lo ya descargado en data/cache/ no se vuelve a bajar y las referencias ya
asignadas en data/refs.json nunca cambian. La referencia va atada al id del archivo en Drive,
que es permanente; el hash del contenido solo sirve para fusionar duplicados dentro de una
pasada, porque Drive devuelve bytes distintos cada vez que regenera el JPEG.

Uso:  python3 scripts/build.py [--limit N]
"""

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.request

from PIL import Image, ImageOps

import config   # lee el .env de la raiz, el unico sitio con los datos del negocio

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TREE = os.path.join(BASE, "data", "tree.json")
CACHE = os.path.join(BASE, "data", "cache")
REFS = os.path.join(BASE, "data", "refs.json")
SITE = os.path.join(BASE, "public")
IMG_GRID = os.path.join(SITE, "img", "grid")
IMG_FULL = os.path.join(SITE, "img", "full")
IMG_CAT = os.path.join(SITE, "img", "cat")   # una miniatura cuadrada por categoria

# Tamanos de salida. Bajar estos valores es la palanca para reducir el peso del sitio.
GRID_W, GRID_Q = 450, 72
FULL_W, FULL_Q = 900, 72
CAT_W, CAT_Q = 260, 68   # miniatura del selector de bienvenida, recortada en cuadrado
SOURCE_W = 1400          # ancho que le pedimos al thumbnail de Drive
DOWNLOAD_WORKERS = 4     # subir esto dispara los 429 de Google

SIZE_ORDER = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]

# Variantes de escritura que aparecen al nombrar carpetas a mano: son la misma talla.
SIZE_ALIASES = {
    "XXL": "2XL", "XXXL": "3XL", "XXXXL": "4XL", "XXXXXL": "5XL",
    "2XLARGE": "2XL", "SMALL": "S", "MEDIUM": "M", "LARGE": "L", "XLARGE": "XL",
}

# Marcas que se adivinan solas, en el nombre de una subcarpeta o de una foto: (patron, marca).
# Por PALABRA ENTERA: la 'CH' de Carolina Herrera no debe saltar dentro de "CHAQUETA".
# Una marca que no este aqui se declara igual con una carpeta 'MARCA Nombre'.
BRANDS = [
    (r"\bCAROLINA\s+HERRERA\b", "CAROLINA HERRERA"),
    (r"\bCH\b", "CAROLINA HERRERA"),
    (r"\bHUGO\s+BOSS\b", "HUGO BOSS"),
    (r"\bBOSS\b", "HUGO BOSS"),
    (r"\bLACOSTE\b", "LACOSTE"),
]

# Prefijos de referencia fijos: el dueno pasa estas refs a sus clientes, no pueden cambiar.
# Las claves son las categorias YA LIMPIAS (sin emojis). Una que no este aqui recibe las tres
# primeras letras de su nombre, y aqui eso haria chocar CAMISAS y CAMISETAS en "CAM".
PREFIX = {
    "BOXERS ORIGINALES": "BOX", "BUZOS": "BUZ", "CAMISAS": "CAM",
    "CAMISETAS": "CMT", "TIPO POLO": "POL",
}

# Como se decide que dos fotos son el mismo producto en varias tallas (ver .env):
#   "nombre"    : mismo nombre de archivo en varias carpetas TALLA.
#   "contenido" : misma imagen. En este Drive la misma foto se sube a cada talla en distinto
#                 orden y a veces con otro nombre, y muchas prendas distintas se llaman igual
#                 ("💲170.000"): por nombre se cruzaban (9 de 9 mal en MANGA LARGA).
AGRUPAR = config.leer().get("CATALOGO_AGRUPAR", "nombre").strip().lower()

# Firma de cada foto para agrupar por contenido: la imagen reducida a 16x16 en color. La misma
# foto subida a dos carpetas da ~0 aunque Drive devuelva bytes distintos en cada descarga;
# fotos distintas, mucho mas. El umbral sale de medir este Drive (ver agrupar_por_contenido).
FIRMA_LADO = 16
# Medido en el Drive de Visionary (528 fotos): 447 a menos de 2 de su gemela (la misma foto en
# otra talla), 78 a 15 o mas (otra prenda) y nada entre 2 y 4. Los dos casos del medio, vistos
# a ojo: a 5.5 la misma camiseta BOSS fotografiada dos veces seguidas (se junta, bien) y a 12.5
# dos camisetas Karl Lagerfeld distintas (se separan, bien). 8 queda con margen a los dos lados.
UMBRAL_MISMA_FOTO = 8.0

print_lock = threading.Lock()


# --------------------------------------------------------------------------- aplanado

def leaves(node, path):
    """Genera (path, node) por cada carpeta que contiene archivos."""
    if node["files"]:
        yield path, node
    for child in node["folders"]:
        yield from leaves(child, path + [child["name"]])


def brand_of(texto):
    """Marca que aparece en un nombre ('Hoodie Carolina Herrera Beige' -> 'CAROLINA HERRERA')."""
    if not texto:
        return None
    up = texto.upper()
    for patron, marca in BRANDS:
        if re.search(patron, up):
            return marca
    return None


def parse_size(folder_name):
    """'TALLA XXL' -> '2XL', 'Talla L⚜️' -> 'L'. None si la carpeta se llama solo 'TALLA'.

    Se queda solo con letras y numeros: en Drive las carpetas llevan emojis detras de la
    talla, y 'L⚜️' saldria como una talla desconocida en vez de la L.
    """
    partes = folder_name.split(None, 1)
    if len(partes) < 2:
        return None
    s = re.sub(r"[^A-Z0-9]", "", partes[1].upper())
    return SIZE_ALIASES.get(s, s) or None


# ------------------------------------------------------ nombres limpios, precio y nombre

# Precio escrito a mano: "💲170.000", "170.000", "260mil", "260 mil".
PRECIO_PUNTOS = re.compile(r"(\d{1,3}(?:[.,]\d{3})+)")
PRECIO_MIL = re.compile(r"(\d+)\s*mil\b", re.I)
NOMBRE_CAMARA = re.compile(r"^(IMG|DSC|PXL|WhatsApp Image)[\s_-]", re.I)
EXTENSION_FOTO = re.compile(r"\.(heic|heif|jpe?g|png|webp)\s*$", re.I)


def sin_emojis(texto):
    """Quita emojis y simbolos decorativos; deja letras (con tildes), numeros y puntuacion."""
    texto = unicodedata.normalize("NFC", texto)
    # So: emojis y simbolos. Sk/Cf/Mn/Co: modificadores, uniones invisibles y el selector de
    # variante (el FE0F que acompana a muchos emojis). Tras NFC las tildes van dentro de la
    # letra, asi que quitar las marcas sueltas no se lleva ninguna. Cn: los emojis mas
    # recientes (el corazon celeste 🩵) que la tabla Unicode de Python aun no conoce y marca
    # como "sin asignar"; un caracter sin asignar nunca es texto de verdad.
    limpio = "".join(c for c in texto
                     if unicodedata.category(c) not in ("So", "Sk", "Cf", "Mn", "Co", "Cn"))
    return re.sub(r"\s+", " ", limpio).strip()


def precio_de(texto):
    """'💲170.000' -> 170000, 'Boss Beige 260mil💣' -> 260000. Sin precio, None."""
    if not texto:
        return None
    m = PRECIO_PUNTOS.search(texto)
    if m:
        return int(re.sub(r"[.,]", "", m.group(1)))
    m = PRECIO_MIL.search(texto)
    if m:
        return int(m.group(1)) * 1000
    return None


def quitar_precio(texto):
    texto = PRECIO_PUNTOS.sub(" ", texto)
    texto = PRECIO_MIL.sub(" ", texto)
    return re.sub(r"\s+", " ", texto).strip(" -·")


def limpiar_carpeta(nombre):
    """Nombre de carpeta para la web: sin emojis ni precio. 'Básicas 110mil😎' -> 'Básicas'."""
    return quitar_precio(sin_emojis(nombre)) or sin_emojis(nombre)


def nombre_categoria(nombre):
    """Primer nivel del Drive tal como se ve en la web y en PREFIX: sin numero de orden,
    sin emojis y sin precio. '1 BUZOS🏂❄️' -> 'BUZOS'."""
    return limpiar_carpeta(orden_categoria(nombre)[1])


def nombre_de(archivo):
    """Nombre del producto escrito en la foto, o None si no lo trae.

    'Boss Azul Oscuro 260mil💣' -> 'Boss Azul Oscuro'. Las fotos con nombre de camara
    (IMG_6470.HEIC) o solo con el precio ('💲170.000') no tienen nombre. Tampoco las que solo
    dicen la marca ('💲155.000 CH'): la marca ya se muestra aparte.
    """
    base = EXTENSION_FOTO.sub("", archivo)
    if NOMBRE_CAMARA.match(base):
        return None
    nombre = quitar_precio(sin_emojis(base))
    if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2,}", nombre):
        return None
    if brand_of(nombre) and not re.sub(r"(?i)\b(CH|BOSS|HUGO|CAROLINA|HERRERA|LACOSTE)\b", "", nombre).strip():
        return None
    return nombre


def size_key(s):
    """Ordena las tallas conocidas; las desconocidas van al final, alfabeticamente."""
    return (SIZE_ORDER.index(s), "") if s in SIZE_ORDER else (len(SIZE_ORDER), s)


# --------------------------------------------------------- nombres que declaran su papel
#
# Todo lo de aqui abajo es OPCIONAL. El catalogo sigue adivinando igual que siempre: primer
# nivel = categoria, 'JEANS DIESEL' = marca DIESEL, lo demas = subcarpeta. Estos nombres solo
# sirven para decir a mano lo que adivinar no acierta -- una marca que el codigo no conoce, o
# un orden de categorias distinto del alfabetico -- y conviven carpeta a carpeta con el resto.

NUMERO_AL_INICIO = re.compile(r"^\s*(\d+)\s+(.+)$")


def orden_categoria(nombre):
    """'1 GORRAS' -> (1, 'GORRAS'). Sin numero -> al final, por orden alfabetico.

    El numero no llega a la web: la categoria se sigue llamando GORRAS, que es lo que va en
    los enlaces que ya circulan (?cat=GORRAS) y la clave de PREFIX.
    """
    m = NUMERO_AL_INICIO.match(nombre)
    if m:
        return int(m.group(1)), m.group(2).strip()
    return None, nombre.strip()


def declara(segmento, palabra):
    """'MARCA Diesel' con palabra='MARCA' -> 'Diesel'. Si no la declara, None.

    Solo la palabra completa. 'M Diesel' no vale a proposito: una carpeta real llamada
    'T SHIRTS' se leeria como la talla SHIRTS.
    """
    partes = segmento.split(None, 1)
    if len(partes) == 2 and partes[0].upper() == palabra:
        return partes[1].strip()
    return None


def collect_products(tree):
    """Agrupa los archivos en productos. La misma foto en varias carpetas TALLA es un producto.

    Devuelve (productos, tallas_desconocidas). Las tallas que no estan en SIZE_ORDER se
    conservan igualmente: se avisa por pantalla en vez de tirarlas en silencio.
    """
    products = {}  # (categoria, subcarpetas, marca, filename, repeticion) -> dict
    desconocidas = {}
    for path, node in leaves(tree, []):
        if not path:
            continue
        # El primer nivel siempre es la categoria; el numero de delante, si lo trae, solo dice
        # en que puesto va. Emojis y precio tampoco forman parte del nombre en la web.
        category = nombre_categoria(path[0])
        # Precio escrito en una carpeta ('Básicas 110mil'): vale para las fotos de dentro que no
        # traen el suyo. Manda la carpeta mas cercana a la foto.
        precio_carpeta = precio_de(path[0])
        size, marca, subs = None, None, []
        for seg in path[1:]:
            if seg.upper().startswith("TALLA"):
                # parse_size devuelve None si la carpeta se llama 'TALLA' a secas.
                talla = parse_size(seg)
                if talla:
                    size = talla
                    if size not in SIZE_ORDER:
                        desconocidas.setdefault(size, set()).add(" / ".join(path))
                continue
            declarada = declara(seg, "MARCA")
            if declarada:
                marca = sin_emojis(declarada).upper()
                continue
            precio_carpeta = precio_de(seg) or precio_carpeta
            subs.append(limpiar_carpeta(seg))
        sub = subs[0] if subs else None
        # Sin carpeta MARCA se sigue adivinando la marca del nombre de la subcarpeta, como
        # siempre: 'JEANS DIESEL' no deja de funcionar porque exista otra forma de decirlo.
        brand = marca or brand_of(sub)
        # Drive admite dos archivos DISTINTOS con el mismo nombre en una misma carpeta, asi que
        # el nombre no basta como clave: se numera cada repeticion dentro de su propia carpeta.
        # La n-esima copia de un nombre se empareja con la n-esima de las demas carpetas TALLA;
        # si el emparejamiento no fuera el correcto, la fusion por hash posterior lo arregla.
        # La talla queda FUERA de la clave (la misma foto en TALLA M y TALLA L es un producto
        # con dos tallas) y la marca DENTRO, para no fusionar dos marcas distintas.
        repetido = {}
        for f in node["files"]:
            n = repetido[f["name"]] = repetido.get(f["name"], 0) + 1
            # Por contenido, cada foto entra sola y la agrupacion se hace despues mirando las
            # imagenes (agrupar_por_contenido). Por nombre, como siempre.
            if AGRUPAR == "contenido":
                key = (category, tuple(subs), f["id"])
            else:
                key = (category, tuple(subs), brand, f["name"], n)
            p = products.get(key)
            if p is None:
                p = products[key] = {
                    "cat": category, "sub": sub, "subs": tuple(subs),
                    "brand": brand or brand_of(f["name"]),
                    "name": nombre_de(f["name"]),
                    "price": precio_de(f["name"]) or precio_carpeta,
                    "file": f["name"], "drive": f["id"], "sizes": set(),
                }
            if size:
                p["sizes"].add(size)
    if AGRUPAR == "contenido":
        # Orden fijo entre pasadas: de el depende que referencia estrena cada foto nueva.
        ordered = sorted(products.values(),
                         key=lambda p: (p["cat"], p["subs"], p["file"], p["drive"]))
        return ordered, desconocidas
    ordered = sorted(products.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][3], kv[0][4]))
    return [p for _, p in ordered], desconocidas


# --------------------------------------------------------------------------- descarga

def download(product, index, total):
    """Baja a data/cache/ el JPEG que Drive genera desde el HEIC. Reintenta con backoff."""
    dest = os.path.join(CACHE, product["drive"] + ".jpg")
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        return dest
    url = "https://drive.google.com/thumbnail?id=%s&sz=w%d" % (product["drive"], SOURCE_W)
    for intento in range(5):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                data = r.read()
            if len(data) < 1024:
                raise ValueError("respuesta vacia (%d bytes)" % len(data))
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            with print_lock:
                if index % 25 == 0:
                    print("  descargadas %d/%d" % (index, total), flush=True)
            return dest
        except Exception as e:
            if intento == 4:
                with print_lock:
                    print("  !! fallo %s: %s" % (product["file"], e), flush=True)
                return None
            time.sleep(2 ** intento)
    return None


# ---------------------------------------------------------------- agrupar por contenido

def firma(path):
    """La foto reducida a FIRMA_LADO x FIRMA_LADO en color, como bytes."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        return im.resize((FIRMA_LADO, FIRMA_LADO), Image.BOX).tobytes()


def distancia(a, b):
    """Diferencia media por canal entre dos firmas, de 0 (identicas) a 255."""
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def agrupar_por_contenido(products, paths):
    """Junta en un producto las fotos que son la misma imagen, dentro de su categoria.

    Solo compara fotos de la misma categoria y subcarpeta: nunca junta una camisa con un buzo
    aunque se parezcan. De cada grupo sale un producto con todas las tallas de sus fotos, el
    nombre mas descriptivo, el precio mas bajo y todos sus ids de Drive (cada id conserva su
    propia referencia; el producto muestra la mas antigua).
    """
    fotos = [(p, path) for p, path in zip(products, paths) if path]
    for p, path in fotos:
        p["firma"] = firma(path)

    familias = {}
    for p, _ in fotos:
        familias.setdefault((p["cat"], p["subs"]), []).append(p)

    padre = {id(p): p for p, _ in fotos}

    def raiz(p):
        while padre[id(p)] is not p:
            padre[id(p)] = padre[id(padre[id(p)])]
            p = padre[id(p)]
        return p

    vecina = []   # distancia de cada foto a la mas parecida de su familia: para ver el umbral
    for miembros in familias.values():
        for i, a in enumerate(miembros):
            mejor = None
            for j, b in enumerate(miembros):
                if i == j:
                    continue
                d = distancia(a["firma"], b["firma"])
                mejor = d if mejor is None else min(mejor, d)
                if j > i and d < UMBRAL_MISMA_FOTO:
                    ra, rb = raiz(a), raiz(b)
                    if ra is not rb:
                        padre[id(rb)] = ra
            if mejor is not None:
                vecina.append(mejor)

    # Cuantas fotos tienen su gemela a cada distancia. Si el umbral esta bien puesto, hay un
    # hueco claro entre "la misma foto en otra talla" (casi 0) y "otra prenda" (lejos).
    tramos = [(0, 1), (1, 2), (2, 4), (4, 6), (6, 10), (10, 15), (15, 25), (25, 999)]
    print("  distancia a la foto mas parecida (umbral %.1f):" % UMBRAL_MISMA_FOTO)
    for lo, hi in tramos:
        n = sum(1 for d in vecina if lo <= d < hi)
        print("    %5s - %-4s %4d %s" % (lo, hi if hi < 999 else "", n, "#" * min(n, 60)))

    grupos = {}
    for p, _ in fotos:      # fotos ya viene en el orden fijo de collect_products
        grupos.setdefault(id(raiz(p)), []).append(p)

    unicos = []
    for miembros in grupos.values():
        base = miembros[0]
        nombres = [m["name"] for m in miembros if m["name"]]
        precios = [m["price"] for m in miembros if m["price"]]
        unicos.append(dict(
            base,
            sizes=set().union(*(m["sizes"] for m in miembros)),
            name=max(nombres, key=len) if nombres else None,
            price=min(precios) if precios else None,
            brand=next((m["brand"] for m in miembros if m["brand"]), None),
            ids=[m["drive"] for m in miembros],
            also_in=[],
        ))
    print("  %d fotos -> %d productos" % (len(fotos), len(unicos)))
    return unicos


# --------------------------------------------------------------------------- referencias

def load_refs():
    """Devuelve (refs, reservadas): id de Drive -> referencia, y numeros ya gastados.

    La clave es el id del archivo en Drive, que es permanente. NO se puede usar el hash del
    contenido: Drive genera el JPEG desde el HEIC al vuelo y devuelve bytes distintos cada
    vez (comprobado: la mitad de las fotos cambian de tamano entre dos descargas), asi que
    con el hash media tienda se renumeraba cada vez que la cache se enfriaba.
    """
    if not os.path.exists(REFS):
        return {}, set()
    with open(REFS, encoding="utf-8") as f:
        datos = json.load(f)
    if datos.get("version") != 2:
        raise SystemExit(
            "data/refs.json tiene un formato antiguo (referencias por hash del contenido).\n"
            "Ese formato renumera los productos y las referencias ya estan con los clientes.\n"
            "No se continua para no reasignarlas; ver CONFIGURACION.md."
        )
    return datos["refs"], set(datos.get("reservadas", []))


def serializar(catalogo):
    """El texto exacto de catalog.json. Compacto, y siempre igual para los mismos datos."""
    return json.dumps(catalogo, ensure_ascii=False, separators=(",", ":"))


def save_refs(refs, reservadas):
    with open(REFS, "w", encoding="utf-8") as f:
        json.dump({"version": 2,
                   "refs": dict(sorted(refs.items(), key=lambda kv: kv[1])),
                   "reservadas": sorted(reservadas)}, f, indent=1)


def make_ref(category, refs, reservadas, counters):
    # La clave es el nombre SIN el numero de orden, que es como llega desde collect_products.
    # Importa: con el numero dentro, renombrar 'CAMISETA 270gr' a '6 CAMISETA 270gr' tiraria
    # el prefijo C27 y lo cambiaria por CAM, que ya es de CAMISAS 1.1.
    prefix = PREFIX.get(category)
    if not prefix:
        prefix = (re.sub(r"[^A-Z]", "", category.upper()) + "XXX")[:3]
    n = counters.get(prefix, 0)
    # Las reservadas son numeros que un dia se publicaron y luego quedaron sueltos: no se
    # reutilizan, o un cliente pediria la foto de otro.
    used = set(refs.values()) | reservadas
    while True:
        n += 1
        candidate = "%s-%04d" % (prefix, n)
        if candidate not in used:
            counters[prefix] = n
            return candidate


def num_ref(ref):
    """Orden estable de referencias: por prefijo y numero, no alfabetico."""
    prefix, _, num = ref.rpartition("-")
    return (prefix, int(num) if num.isdigit() else 0)


# --------------------------------------------------------------------------- imagenes

def encode(src, ref):
    """Genera las dos versiones WebP. Devuelve (ancho, alto) de la version del grid."""
    grid_path = os.path.join(IMG_GRID, ref + ".webp")
    full_path = os.path.join(IMG_FULL, ref + ".webp")
    if os.path.exists(grid_path) and os.path.exists(full_path):
        with Image.open(grid_path) as im:
            return im.size
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        out = None
        for path, width, quality in ((full_path, FULL_W, FULL_Q), (grid_path, GRID_W, GRID_Q)):
            copy = im
            if im.width > width:
                copy = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            copy.save(path, "WEBP", quality=quality, method=5)
            out = copy.size
        return out


def hacer_portada(ref):
    """Miniatura cuadrada para el selector de categorias, recortada por el centro."""
    destino = os.path.join(IMG_CAT, ref + ".webp")
    if os.path.exists(destino):
        return
    with Image.open(os.path.join(IMG_GRID, ref + ".webp")) as im:
        lado = min(im.width, im.height)
        izq = (im.width - lado) // 2
        arriba = (im.height - lado) // 3     # un tercio: la prenda suele estar arriba
        im = im.crop((izq, arriba, izq + lado, arriba + lado))
        im.resize((CAT_W, CAT_W), Image.LANCZOS).save(destino, "WEBP", quality=CAT_Q, method=5)


def fusionar_por_hash(products, paths):
    """Modo por nombre: la misma foto subida dos veces o repetida entre categorias."""
    print("\nFusionando duplicados por contenido...")
    by_hash, merged = {}, 0
    for product, path in zip(products, paths):
        if not path:
            continue
        with open(path, "rb") as f:
            product["hash"] = hashlib.md5(f.read()).hexdigest()
        first = by_hash.get(product["hash"])
        if first is None:
            by_hash[product["hash"]] = product
            product["also_in"] = []
            # Todos los ids de Drive que acaban en este producto. La referencia se busca por
            # cualquiera de ellos: si manana los bytes no coinciden y el grupo se parte, cada
            # foto recupera la suya en vez de estrenar numero.
            product["ids"] = [product["drive"]]
        else:
            first["ids"].append(product["drive"])
            first["sizes"] |= product["sizes"]
            label = product["sub"] or product["cat"]
            if product["cat"] != first["cat"] and label not in first["also_in"]:
                first["also_in"].append(label)
            merged += 1
    unique = list(by_hash.values())
    print("  %d fusionados -> %d productos unicos" % (merged, len(unique)))
    return unique


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="procesar solo N productos (para pruebas)")
    args = ap.parse_args()

    for d in (CACHE, IMG_GRID, IMG_FULL, IMG_CAT):
        os.makedirs(d, exist_ok=True)

    with open(TREE, encoding="utf-8") as f:
        tree = json.load(f)

    products, desconocidas = collect_products(tree)
    print("Archivos en Drive: %d" % sum(1 for _ in _all_files(tree)))
    print("Productos tras agrupar tallas: %d" % len(products))
    if desconocidas:
        print("\n  AVISO: tallas no reconocidas (se publican igual, pero revisa el nombre")
        print("  de la carpeta en Drive o anade la talla a SIZE_ORDER en este script):")
        for talla in sorted(desconocidas, key=size_key):
            print("    '%s' en %s" % (talla, ", ".join(sorted(desconocidas[talla]))))
    if args.limit:
        products = products[:args.limit]
        print("(--limit) procesando %d" % len(products))

    print("\nDescargando desde Drive (%d en paralelo)..." % DOWNLOAD_WORKERS)
    with concurrent.futures.ThreadPoolExecutor(DOWNLOAD_WORKERS) as pool:
        paths = list(pool.map(
            lambda it: download(it[1], it[0], len(products)), enumerate(products, 1)))

    if AGRUPAR == "contenido":
        print("\nAgrupando por contenido (la misma foto en varias tallas es un producto)...")
        unique = agrupar_por_contenido(products, paths)
    else:
        unique = fusionar_por_hash(products, paths)

    refs, reservadas = load_refs()
    counters = {}
    for ref in list(refs.values()) + list(reservadas):
        prefix, _, num = ref.rpartition("-")
        if num.isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(num))

    print("\nCodificando WebP...")
    # Se cuentan por separado referencias y productos: con duplicados fusionados un producto
    # reune varios archivos, y cada archivo tiene su propia referencia.
    entries, nuevas, conocidos = [], 0, 0
    for i, product in enumerate(unique, 1):
        # Cada archivo de Drive tiene SU referencia, y no se la cede a nadie: la fusion de
        # duplicados depende de los bytes, que Drive cambia entre descargas, asi que un grupo
        # puede partirse manana. Si dos ids compartieran numero, al partirse saldria repetido.
        ya_tenia = all(d in refs for d in product["ids"])
        for d in product["ids"]:
            if d not in refs:
                refs[d] = make_ref(product["cat"], refs, reservadas, counters)
                nuevas += 1
        conocidos += ya_tenia
        # El producto fusionado se muestra con la mas antigua del grupo, que es la que lleva
        # mas tiempo circulando entre los clientes.
        ref = min((refs[d] for d in product["ids"]), key=num_ref)
        src = os.path.join(CACHE, product["drive"] + ".jpg")
        try:
            w, h = encode(src, ref)
        except Exception as e:
            print("  !! %s (%s): %s" % (ref, product["file"], e))
            continue
        entrada = {
            "ref": ref,
            "cat": product["cat"],
            "sub": product["sub"],
            "brand": product["brand"],
            # Se ordenan pero no se filtran: una talla rara se publica igual, ya se aviso arriba.
            "sizes": sorted(product["sizes"], key=size_key),
            "w": w, "h": h,
            "drive": product["drive"],
            "also_in": product["also_in"],
        }
        # Nombre y precio escritos en la foto o en su carpeta. Solo si existen: sin ellos la
        # ficha queda como en las tiendas que no los usan.
        if product.get("name"):
            entrada["name"] = product["name"]
        if product.get("price"):
            entrada["price"] = product["price"]
        entries.append(entrada)
        if i % 100 == 0:
            print("  %d/%d" % (i, len(unique)), flush=True)
    print("  %d referencias nuevas, %d productos que ya tenian referencia"
          % (nuevas, conocidos))

    save_refs(refs, reservadas)

    # Orden del catalogo: primero las carpetas numeradas ('1 GORRAS') por su numero, y detras
    # el resto alfabeticamente, como venian de Drive. El numero se compara como numero y no
    # como texto, o la 10 se colaria entre la 1 y la 2. Este orden es el unico: de aqui salen
    # los chips, el selector de bienvenida y el intercalado de "ver todo el catalogo".
    categories = []
    # Con el nombre ya limpio (sin numero, emojis ni precio), igual que en cada producto.
    ordenadas = sorted(
        ((orden_categoria(c["name"])[0], nombre_categoria(c["name"])) for c in tree["folders"]),
        key=lambda o: (0, o[0], "") if o[0] is not None else (1, 0, o[1].upper()))
    for _, name in ordenadas:
        items = [e for e in entries if e["cat"] == name]
        if not items:
            continue
        sizes = sorted({s for e in items for s in e["sizes"]}, key=size_key)
        # El primer producto hace de portada. Miniatura propia y no la del grid: en el
        # selector se ven 18 a la vez y las del grid pesarian el triple.
        portada = items[0]["ref"]
        try:
            hacer_portada(portada)
        except Exception as e:
            print("  !! portada de %s: %s" % (name, e))
            portada = None
        categories.append({"name": name, "count": len(items),
                           "sizes": sizes, "thumb": portada})

    catalog = {
        # store y drive son informativos: dicen que genero este archivo y el sitio no los lee.
        "store": config.obligatorio("VITE_STORE"),
        # generated SI se ve: es el "actualizado ..." del pie. Se rellena abajo.
        "generated": None,
        "drive": "https://drive.google.com/drive/folders/" + config.obligatorio("VITE_DRIVE_FOLDER"),
        "categories": categories,
        "brands": sorted({e["brand"] for e in entries if e["brand"]}),
        "sizeOrder": SIZE_ORDER,
        "products": entries,
    }

    # La fecha es la del ultimo cambio REAL del catalogo, no la de la ultima ejecucion. Con la
    # fecha de hoy en cada pasada el archivo nunca salia igual al de ayer: el workflow veia un
    # cambio aunque Drive no lo tuviera, y cada ejecucion programada acababa en commit y en un
    # despliegue de Netlify, que se cobra. Se monta el catalogo con la fecha anterior y se
    # comparan los bytes, que es exactamente lo que mira git: si coinciden, nada cambio.
    ruta = os.path.join(SITE, "catalog.json")
    try:
        with open(ruta, encoding="utf-8") as f:
            previo = f.read()
        fecha_previa = json.loads(previo).get("generated")
    except (OSError, ValueError):
        previo = fecha_previa = None      # primera vez, o archivo roto: fecha de hoy
    catalog["generated"] = fecha_previa
    if fecha_previa is None or serializar(catalog) != previo:
        catalog["generated"] = datetime.date.today().isoformat()
    else:
        print("\nCatalogo sin cambios: se conserva la fecha %s" % fecha_previa)

    # Misma funcion para comparar y para escribir: asi no pueden salir bytes distintos.
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(serializar(catalog))

    # public/img lo genera este script: si una foto se borro de Drive, su .webp sobra.
    # Sin esta limpieza quedaria huerfano, verify.py fallaria y tumbaria la sincronizacion
    # automatica. Con --limit el catalogo esta recortado a proposito, asi que no se toca nada.
    if not args.limit:
        vivas = {e["ref"] for e in entries}
        portadas = {c["thumb"] for c in categories if c.get("thumb")}
        borradas = 0
        for carpeta, validas in ((IMG_GRID, vivas), (IMG_FULL, vivas), (IMG_CAT, portadas)):
            for nombre in os.listdir(carpeta):
                if nombre.endswith(".webp") and nombre[:-5] not in validas:
                    os.remove(os.path.join(carpeta, nombre))
                    borradas += 1
        if borradas:
            print("  %d imagenes huerfanas borradas (sus fotos ya no estan en Drive)" % borradas)

    print("\nListo: %d productos en %d categorias -> public/catalog.json"
          % (len(entries), len(categories)))


def _all_files(node):
    for f in node["files"]:
        yield f
    for c in node["folders"]:
        yield from _all_files(c)


if __name__ == "__main__":
    sys.exit(main())
