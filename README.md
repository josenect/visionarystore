# Catálogo web — Visionary Store

Landing estática que muestra el catálogo de la tienda con filtros por categoría, marca y talla,
precio de cada prenda, paginación, buscador y pedido directo por WhatsApp.

Las fotos viven en la [carpeta de Drive de la tienda](https://drive.google.com/drive/folders/1YnoCOHVXLUl6bVvJUOikugu3ra8hUL3P);
este proyecto las lee, las optimiza y genera el sitio.

> Parte del catálogo de NEPTUS STORE (`~/ropa/neptus`), con el que comparte el código. Cada
> tienda es un proyecto aparte, con su propio repositorio y su propio sitio en Netlify.

### Cómo está organizado este Drive, y cómo se lee

Categorías con subcarpetas y carpetas de talla, como NEPTUS, pero con cuatro particularidades:

1. **Fotos sin extensión** (`Boss Beige 260mil💣`). El crawler distingue foto y carpeta por el
   enlace de Drive, no por la extensión; si no, se perderían 182 de las 528.
2. **El nombre no identifica el producto.** La misma foto se sube a cada talla en distinto orden
   y a veces con otro nombre, y muchas prendas distintas se llaman igual (`💲170.000`). Por eso
   aquí se agrupa **por contenido**: dos fotos que son la misma imagen son un producto con las
   tallas de las dos (`CATALOGO_AGRUPAR="contenido"` en el `.env`).
3. **El precio va en el nombre**: de la foto (`💲170.000`, `260mil`) o, si no lo trae, de su
   carpeta (`Básicas 110mil`). Se muestra en cada producto y en el mensaje de WhatsApp. El nombre
   de la prenda (`Boss Azul Oscuro`) y la marca (Boss, Carolina Herrera, Lacoste) también.
4. **Emojis** en carpetas y tallas: se quitan en la web; en Drive no se toca nada.

> **¿Buscas dónde cambiar el teléfono, el nombre o la carpeta de Drive?**
> Están en el archivo **[`.env`](.env)** de la raíz. El mapa completo, incluidos el logo y los
> iconos, en **[CONFIGURACION.md](CONFIGURACION.md)**.

---

## Por qué hace falta convertir las fotos

La mayoría de las fotos de este Drive son **HEIC** (el formato del iPhone), que Chrome, Firefox
y Android no muestran. El build las convierte a WebP en dos tamaños (miniatura y foto grande).

Si la misma foto aparece dentro de `TALLA M`, `TALLA L`… se agrupa en un producto con sus
tallas marcadas. De las **528 fotos** actuales salen **228 productos**.

---

## Puesta en marcha

Hace falta **Node** (para Vite) y **Python 3.9+ con Pillow** (para generar el catálogo).

```bash
npm install          # una sola vez
npm run dev          # abre http://localhost:8080  (y la IP de red para verlo en el móvil)
npm run build        # genera dist/ , que es lo que se publica
npm run preview      # sirve dist/ tal cual quedará publicado
```

## Cómo actualizar el catálogo cuando suban fotos nuevas a Drive

```bash
npm run catalogo     # crawl.py + build.py + verify.py
npm run build        # vuelve a generar dist/
```

`npm run catalogo` descarga y convierte **solo lo nuevo**. Luego se publica `dist/`.

La primera ejecución tarda unos 25–35 minutos porque descarga ~1.000 fotos. Las siguientes
tardan segundos: lo ya descargado queda en `data/cache/` y no se vuelve a bajar.

> **Importante:** las referencias (`BUZ-0001`, `CMT-0012`…) se guardan en `data/refs.json` y
> **no cambian nunca**. Como el dueño se las pasa a los clientes por WhatsApp, ese archivo no
> se debe borrar. Si se borra, todas las referencias se renumeran.

> El crawler necesita que la carpeta de Drive siga compartida como
> **"cualquiera con el enlace"**. Si se quita, deja de funcionar.

---

## Cómo publicarlo gratis (Netlify)

Se publica **`dist/`** (lo genera `npm run build`). `netlify.toml` ya trae el build command y
la carpeta de salida, así que Netlify lo detecta solo.

### Opción rápida — arrastrar la carpeta

1. Entrar en [app.netlify.com](https://app.netlify.com) y crear una cuenta gratis.
2. **Sites → Add new site → Deploy manually**.
3. Arrastrar la carpeta **`dist`** completa.

Para actualizar: entrar al sitio → *Deploys* → arrastrar `dist` otra vez.

### Opción con Git — se actualiza solo

1. Subir este repositorio a GitHub.
2. Netlify → **Add new site → Import an existing project** → elegir el repo.
3. No hay que configurar nada: `netlify.toml` ya define `npm run build` y `dist`.
4. A partir de ahí, cada `git push` republica el sitio.

Vale igual para Cloudflare Pages o GitHub Pages con el mismo build command y carpeta. Como
Vite usa `base: "./"`, el sitio funciona tanto en la raíz de un dominio como en un
subdirectorio del tipo `usuario.github.io/visionary-store`.

---

## Cambiar el teléfono, el nombre o la carpeta de Drive

Todo está en el archivo **[`.env`](.env)** de la raíz: se edita, se confirma el cambio y se
sube. Netlify recompila solo.

| Variable | Qué cambia |
|---|---|
| `VITE_WHATSAPP` | Número que recibe los pedidos |
| `VITE_STORE` | Nombre del negocio (pie, título, etiquetas al compartir) |
| `VITE_TAGLINE` | Frase bajo el logo |
| `VITE_DRIVE_FOLDER` | Carpeta de Google Drive con las fotos |
| `VITE_PER_PAGE` | Productos por página |
| `VITE_POR_CATEGORIA` | Productos seguidos de la misma categoría |

Ese `.env` **sí va al repositorio**: no hay secretos, todo eso se ve en la propia web.

### Sin acceso al repositorio

Las mismas variables se pueden poner en **Netlify → Site configuration → Environment
variables**, un formulario con contraseña. Lo que se ponga ahí **gana** a lo escrito en el
`.env`, así que sirve para un cambio urgente.

> Son variables de **compilación**. Después de cambiarlas hay que pulsar **Deploys → Trigger
> deploy**; no basta con guardarlas.

---

## Sincronizar sin depender de nadie (el dueño, desde GitHub)

Cuando se suben fotos o carpetas nuevas a Drive, el dueño puede publicarlas él mismo:

1. Entrar a **github.com** con su cuenta (ahí está la contraseña).
2. En el repositorio → pestaña **Actions** → **Sincronizar catálogo** → botón **Run workflow**.
3. Esperar. El proceso lee Drive, descarga y convierte **solo lo nuevo**, y guarda el
   resultado en el repositorio. Netlify detecta el cambio y republica el sitio solo.

En total, un par de minutos. No hace falta tocar código ni tener nada instalado.

### Por qué está montado así y no dentro de Netlify

- La compilación gratuita de Netlify corta a los **15 minutos**, y la primera pasada del
  pipeline descarga ~1.000 fotos (25-35 min). GitHub Actions da 60.
- Y sobre todo: las referencias (`BUZ-0001`) se asignan con un contador guardado en
  `data/refs.json`. Netlify **no puede guardar ese archivo de vuelta** en el repositorio, así
  que en la siguiente publicación se renumerarían y las referencias que el dueño ya le pasó a
  sus clientes dejarían de existir. El Action sí lo guarda, junto con las fotos nuevas.

El workflow guarda entre ejecuciones las fotos ya descargadas (caché de GitHub), por eso la
segunda sincronización y las siguientes tardan segundos en vez de media hora.

> Requiere que el proyecto esté en un repositorio de GitHub y que Netlify esté conectado a él
> por Git (no vale el despliegue arrastrando la carpeta).

---

## Cambiar datos del negocio

Todo lo configurable está listado en **[CONFIGURACION.md](CONFIGURACION.md)**: teléfono,
nombre, frase, logo e iconos, carpeta de Drive, productos por página y los ajustes del
pipeline de imágenes, cada uno con el archivo exacto donde se toca.

Resumen de dónde vive cada cosa:

| Qué | Dónde |
|---|---|
| Teléfono, nombre, frase, carpeta de Drive, paginación | `.env` |
| Logo e iconos | `public/logo.png`, `public/icon-180.png`, `public/icon-512.png` |
| Texto del mensaje de WhatsApp | `src/app.js`, función `MSG` |
| Tamaños y calidad de las fotos | `scripts/build.py`, cabecera del archivo |

Todas las variables se pueden sobrescribir desde el panel de Netlify, sin acceso al
repositorio (ver arriba).

---

## Estructura

```
.env                 Datos del negocio: telefono, nombre, carpeta de Drive
CONFIGURACION.md     Dónde se cambia cada cosa (empieza por aquí)
index.html           Página (entrada de Vite)
src/app.js           Filtros, paginación, buscador y lightbox
src/styles.css       Estilos (móvil primero)
public/catalog.json  Catálogo generado
public/img/          Fotos ya optimizadas (WebP, dos tamaños)
public/_headers      Cabeceras de caché para Cloudflare/Netlify
vite.config.js       Puerto 8080, salida dist/, rutas relativas
netlify.toml         Build command y carpeta de publicación para Netlify

scripts/crawl.py     Lee la carpeta de Drive        -> data/tree.json
scripts/build.py     Descarga, agrupa y convierte   -> public/catalog.json + public/img/**
scripts/verify.py    Revisa que el catálogo esté completo
.github/workflows/   Sincronización que el dueño lanza desde GitHub
data/cache/          Fotos ya descargadas (no borrar: evita volver a bajarlas)
data/refs.json       Referencia de cada producto (NO BORRAR)
dist/                Resultado de npm run build: esto es lo que se publica
```

### Cómo se decide qué es un producto

1. Se recorre el árbol de Drive. Una carpeta `TALLA XL` no es un producto: es una talla de la
   categoría que la contiene.
2. Los archivos con el mismo nombre dentro de una misma categoría son **el mismo producto en
   distintas tallas** (verificado: son la misma imagen byte a byte).
3. Después se comparan las fotos por contenido (hash MD5) para fusionar las que se subieron
   dos veces con nombres distintos o que están repetidas en dos categorías. El hash sirve
   **solo para fusionar**: la referencia va atada al id del archivo en Drive, porque Drive
   regenera el JPEG desde el HEIC y devuelve bytes distintos en cada descarga.

### Ajustar el peso de las imágenes

En la cabecera de `scripts/build.py`:

```python
GRID_W, GRID_Q = 450, 72   # miniatura del grid  (~37 KB)
FULL_W, FULL_Q = 900, 72   # imagen al ampliar   (~130 KB)
```

Para regenerar con otros valores hay que borrar `public/img/` y volver a ejecutar `build.py`
(no vuelve a descargar de Drive, solo reconvierte).

---

## Requisitos

- **Node 18+** con npm — solo para Vite (servidor de desarrollo y compilación).
- **Python 3.9+ con Pillow** (`pip3 install Pillow`) — solo para generar el catálogo desde Drive.

El sitio publicado no lleva ninguna librería: es HTML, CSS y JS propios.
