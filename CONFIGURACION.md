# Dónde se cambia cada cosa

Página única con todo lo configurable del catálogo. Si buscas dónde tocar algo, está aquí.

---

## Todo en un solo archivo: `.env`

Los datos del negocio viven en **[`.env`](.env)**, en la raíz del proyecto. Lo leen las tres
partes: la web, el crawler de Drive y el generador del catálogo.

| Qué | Variable |
|---|---|
| Teléfono que recibe los pedidos | `VITE_WHATSAPP` |
| Nombre del negocio | `VITE_STORE` |
| Frase bajo el logo | `VITE_TAGLINE` |
| **Carpeta de Google Drive** | `VITE_DRIVE_FOLDER` |
| Nombre del primer nivel del Drive en la web (aquí, "Marca") | `VITE_GRUPO` |
| Texto que ven Google y WhatsApp al compartir | `VITE_DESCRIPCION` |
| Cómo se juntan las tallas de un producto: `nombre` o `contenido` | `CATALOGO_AGRUPAR` |
| Enlace al local en Google Maps | `VITE_MAPS` |
| Ciudad que se lee junto al pin | `VITE_MAPS_LABEL` |
| Perfil de Instagram | `VITE_INSTAGRAM` |
| Perfil de TikTok | `VITE_TIKTOK` |
| Página de Facebook | `VITE_FACEBOOK` |
| Productos por página | `VITE_PER_PAGE` |
| Productos seguidos de la misma categoría | `VITE_POR_CATEGORIA` |

**Para cambiar algo**: editar el archivo, confirmar el cambio (commit) y subirlo. Netlify
recompila solo y en un par de minutos está en vivo.

El teléfono se puede escribir como sea (`+57 322 884 6559`, `322-884-6559`): la web le quita
todo lo que no sea dígito.

**Los tres enlaces de la cabecera se apagan solos**: si se deja una de esas variables vacía,
su icono no aparece. Así se quita TikTok, o la ubicación, sin tocar el código. Lo mismo vale
para `VITE_WHATSAPP`: sin número no se pinta el botón flotante.

> Este `.env` **sí va al repositorio**, al contrario de lo habitual: no hay ningún secreto,
> todo esto se ve en la propia web. Está anotado en `.gitignore` para que nadie lo excluya
> por costumbre.

### El nombre del negocio se propaga solo

Cambiar `VITE_STORE` actualiza a la vez el pie de página, el mensaje de WhatsApp, el título
de la pestaña y las etiquetas que leen Google y WhatsApp al compartir el enlace. Vite las
inyecta en `index.html` al compilar; no hay que tocar el HTML.

### Cambiarlo sin acceso al repositorio

Las mismas variables se pueden poner en **Netlify → Site configuration → Environment
variables**, que es un formulario con contraseña. **Lo que se ponga ahí gana** a lo escrito en
el `.env` (comprobado), así que sirve para un cambio urgente sin tocar código.

> Son variables de **compilación**. Después de cambiarlas hay que pulsar **Deploys → Trigger
> deploy**. No basta con guardarlas.

### El texto del mensaje de WhatsApp

Es lo único que no está en el `.env`, porque es código y no un dato: está en
[`src/app.js`](src/app.js), en la función `MSG`, al principio del archivo.

## El logo y los iconos

Son archivos, no variables: se cambian **reemplazando el archivo** por otro con el mismo nombre
en `public/`.

| Archivo | Dónde se ve | Formato |
|---|---|---|
| `public/logo.png` | Cabecera, pantalla de carga y selector de categorías | PNG **con fondo transparente** (es blanco sobre negro) |
| `public/icon-180.png` | Icono de la pestaña y al guardar en pantalla de inicio | PNG cuadrado, fondo opaco |
| `public/icon-512.png` | Imagen que sale al compartir el enlace | PNG cuadrado, fondo opaco |

El logo se muestra con alto fijo y ancho automático, así que no hace falta que la imagen nueva
tenga las mismas proporciones: la cabecera no se descuadra.

---

## Lo que NO hay que tocar

| Archivo | Por qué |
|---|---|
| `data/refs.json` | Guarda la referencia de cada producto. **El dueño se las pasa a los clientes por WhatsApp**: si se borra, todas se renumeran y las que ya circulan dejan de existir |
| `data/refs.json` → `reservadas` | Números que un día se publicaron y quedaron sueltos. Están ahí para **no volver a usarlos**: si se reciclaran, un cliente pediría una referencia y le llegaría otra prenda |
| `public/catalog.json` | Lo genera `scripts/build.py` en cada sincronización |
| `public/img/` | Fotos ya optimizadas, también generadas |
| `data/cache/` | Fotos descargadas de Drive. Borrarlo no rompe nada, pero la siguiente sincronización tardará 25-35 minutos en vez de segundos |

Dentro de `catalog.json` hay dos campos, `store` y `drive`, que **el sitio no usa**: quedan como
información de qué generó el archivo. Salen del `.env`, así que no hay nada que cambiar ahí.

### Por qué la referencia va atada al id de Drive

Cada producto se identifica por el **id del archivo en Google Drive**, que es permanente. Antes
se identificaba por el contenido de la foto (un hash), y estaba mal: las fotos son HEIC y Drive
genera el JPEG al vuelo, devolviendo **bytes distintos en cada descarga** (comprobado: la mitad
cambia de tamaño entre dos lecturas seguidas). Con el hash, cada vez que se vaciaba la caché
media tienda estrenaba referencia.

Consecuencia práctica: **una foto conserva su referencia siempre**, aunque se borre la caché o
se clone el repositorio de cero. La pierde solo si se borra de Drive y se vuelve a subir, porque
entonces Google le da un id nuevo.

---

## Ajustes del pipeline de imágenes

En la cabecera de [`scripts/build.py`](scripts/build.py), por si hay que bajar el peso del sitio:

| Constante | Qué controla | Valor |
|---|---|---|
| `GRID_W, GRID_Q` | Miniatura de la cuadrícula | 450px, calidad 72 (~37 KB) |
| `FULL_W, FULL_Q` | Foto al abrir el producto | 900px, calidad 72 (~130 KB) |
| `CAT_W, CAT_Q` | Portada de cada categoría | 260px, calidad 68 (~10 KB) |
| `SIZE_ORDER` | Tallas reconocidas y su orden | `XS` a `5XL` |
| `SIZE_ALIASES` | Equivalencias al nombrar carpetas | `XXL` → `2XL`, etc. |
| `PREFIX` | Prefijo de referencia por categoría | `CAMISETAS` → `CMT` |
| `BRANDS` | Marcas que se reconocen en nombres de foto y carpeta | `CH` → CAROLINA HERRERA |
| `UMBRAL_MISMA_FOTO` | Cuánto se parecen dos fotos para ser el mismo producto | 8 (medido en este Drive) |

Para regenerar con otros tamaños hay que **borrar la carpeta correspondiente** de `public/img/`
y volver a ejecutar `build.py`; si los archivos ya existen, no los rehace. No vuelve a descargar
de Drive.
