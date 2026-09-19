import { defineConfig } from "vite";

export default defineConfig({
  // Rutas relativas: el sitio funciona igual en la raiz de un dominio que en un subdirectorio
  // (por ejemplo usuario.github.io/la-fabrica), sin tener que reconstruir.
  base: "./",

  server: {
    port: 8080,
    // Expone el servidor en la red local para poder abrirlo desde el movil.
    host: true,
    open: false,
  },

  preview: {
    port: 8081,
    host: true,
  },

  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Las fotos ya estan optimizadas por scripts/build.py: no hay que tocarlas.
    assetsInlineLimit: 0,
  },
});
