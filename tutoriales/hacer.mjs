// Usage: node hacer.mjs <tutorial>   (e.g. node hacer.mjs recuperar-contrasena)
// Output: salida/<tutorial>.mp4 + .srt
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

import { grabar, montar, narrar } from "./lib/escena.mjs";

const nombre = process.argv[2];
if (!nombre) {
  console.error("Uso: node hacer.mjs <tutorial>");
  process.exit(1);
}
const tut = await import(`./${nombre}/guion.mjs`);
const trabajo = path.join(import.meta.dirname, "salida", `.${nombre}`);
rmSync(trabajo, { recursive: true, force: true });
mkdirSync(trabajo, { recursive: true });

const datos = tut.preparar ? tut.preparar(trabajo) : {};
const pasos = tut.pasos(datos);
console.log(`Narrando ${pasos.length} pasos…`);
const voces = await narrar(pasos);
console.log(`Grabando (${voces.reduce((s, v) => s + v.dur, 0).toFixed(0)} s de voz)…`);
try {
  const toma = await grabar(pasos, voces, trabajo);
  const salida = path.join(import.meta.dirname, "salida", `${nombre}.mp4`);
  montar(toma, voces, pasos, salida);
  console.log(`Listo: ${salida}`);
} finally {
  tut.limpiar?.();
}
