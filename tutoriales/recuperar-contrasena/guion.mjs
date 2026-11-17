// "¿Olvidaste tu contraseña?" — from the login screen to signed in again.
// Recorded on the local demo club (demo@laroja.cl); no real club data.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { tarjeta } from "../lib/escena.mjs";

export const titulo = "Recuperar tu contraseña";
const APP = process.env.APP_URL ?? "http://localhost:3001";
const NUEVA = "Cancha.Norte.26";
const RAIZ = path.resolve(import.meta.dirname, "../..");

function backendShell(code) {
  return execFileSync("docker", ["compose", "exec", "-T", "backend", "python", "manage.py", "shell"],
    { cwd: RAIZ, input: code }).toString();
}

/** A plain, unbranded inbox showing the real reset email. */
function bandeja(dir, correo) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const doc = `<base target="_top">${correo.html}`.replace(/"/g, "&quot;");
  const archivo = path.join(dir, "bandeja.html");
  writeFileSync(archivo, `<!doctype html><meta charset="utf-8"><title>Correo</title>
<style>
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{display:grid;grid-template-columns:220px 1fr;font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
    color:#1f2937;background:#f8fafc}
  nav{background:#eef2f7;padding:22px 16px;border-right:1px solid #e2e8f0}
  nav b{display:block;font-size:20px;margin-bottom:22px;color:#334155}
  nav div{padding:9px 12px;border-radius:8px;font-size:15px;color:#475569}
  nav .on{background:#dbe4f0;color:#0f172a;font-weight:600}
  main{overflow:auto}
  .fila{display:grid;grid-template-columns:150px 1fr 70px;gap:14px;align-items:center;padding:16px 24px;
    border-bottom:1px solid #e2e8f0;background:#fff;cursor:pointer;font-size:15px}
  .fila.nuevo{font-weight:700}
  .fila span:last-child{text-align:right;color:#64748b;font-weight:400;font-size:13px}
  .gris{color:#94a3b8;font-weight:400}
  header{padding:18px 24px;font-size:15px;color:#64748b;border-bottom:1px solid #e2e8f0}
  #msg{display:none} #msg h2{margin:0 0 6px;font-size:22px;color:#0f172a}
  #msg .meta{padding:20px 28px 10px;font-size:14px;color:#475569}
  iframe{width:100%;height:560px;border:0}
</style>
<nav><b>Correo</b><div class="on">Recibidos</div><div>Enviados</div><div>Spam</div></nav>
<main>
  <section id="lista">
    <header>Recibidos</header>
    <div class="fila nuevo" id="abrir" onclick="document.getElementById('lista').style.display='none';
      document.getElementById('msg').style.display='block'">
      <span>SLAB</span><span>${esc(correo.asunto)} <span class="gris">— Pediste cambiar tu contraseña…</span></span><span>ahora</span>
    </div>
    <div class="fila"><span>Cuerpo técnico</span><span class="gris">Citación jueves 9:00 — cancha 2</span><span>ayer</span></div>
    <div class="fila"><span>Logística</span><span class="gris">Horario de bus para el sábado</span><span>lun</span></div>
  </section>
  <section id="msg">
    <div class="meta"><h2>${esc(correo.asunto)}</h2>De: ${esc(correo.de)} · Para: ${esc(correo.para)}</div>
    <iframe srcdoc="${doc}"></iframe>
  </section>
</main>`);
  return pathToFileURL(archivo).href;
}

export function preparar(dir) {
  const salida = backendShell(
    execFileSync("cat", [path.join(import.meta.dirname, "exportar_correo.py")]));
  const correo = JSON.parse(salida.split("@@CORREO@@")[1]);
  return {
    correo,
    inicio: tarjeta(dir, "inicio", {
      titulo: "¿Olvidaste tu contraseña?",
      bajada: "Así eliges una nueva en menos de un minuto.",
    }),
    cierre: tarjeta(dir, "cierre", {
      titulo: "¿No te llegó el correo?",
      bajada: "Revisa spam, o pide otro enlace: vale por una hora y sirve una sola vez.<br>¿Dudas? Escribe a contacto@s-lab.cl",
    }),
    bandeja: bandeja(dir, correo),
  };
}

/** Puts the demo password back so the demo login keeps working. */
export function limpiar() {
  backendShell(`from django.contrib.auth import get_user_model
u = get_user_model().objects.get(email__iexact="demo@laroja.cl")
u.set_password("laroja2026"); u.save(update_fields=["password"])
`);
}

// Target: 25–35 s. Each line is short; the action runs while it is read.
export const pasos = (d) => [
  {
    texto: "¿Olvidaste tu contraseña? Así eliges una nueva.",
    abre: d.inicio,
  },
  {
    texto: "En el ingreso, pulsa «¿Olvidaste tu contraseña?».",
    voz: "En el ingreso, pulsa: ¿Olvidaste tu contraseña?",
    accion: async (t) => {
      await t.ir(`${APP}/login`);
      await t.clic(t.page.getByRole("link", { name: "¿Olvidaste tu contraseña?" }));
      await t.page.waitForURL("**/recuperar");
    },
  },
  {
    texto: "Escribe tu correo y pulsa «Enviar enlace».",
    voz: "Escribe tu correo, y pulsa: Enviar enlace.",
    accion: async (t) => {
      await t.escribir(t.page.getByLabel("Correo"), d.correo.para);
      await t.clic(t.page.getByRole("button", { name: "Enviar enlace" }));
      await t.page.getByRole("status").waitFor();
    },
  },
  {
    texto: "Abre el correo de SLAB y pulsa «Elegir nueva contraseña».",
    voz: "Abre el correo de eslab, y pulsa: Elegir nueva contraseña.",
    accion: async (t) => {
      await t.ir(d.bandeja);
      await t.clic(t.page.locator("#abrir"));
      await t.sleep(500);
      await t.clic(t.page.frameLocator("iframe").getByRole("link", { name: "Elegir nueva contraseña" }));
      await t.page.waitForURL("**/restablecer**");
    },
  },
  {
    texto: "Escribe tu contraseña nueva dos veces y pulsa «Guardar e ingresar».",
    voz: "Escribe tu contraseña nueva dos veces, y pulsa: Guardar e ingresar.",
    accion: async (t) => {
      await t.escribir(t.page.getByLabel("Nueva contraseña"), NUEVA);
      await t.escribir(t.page.getByLabel("Repítela"), NUEVA);
      await t.clic(t.page.getByRole("button", { name: "Guardar e ingresar" }));
      await t.page.waitForURL((u) => !u.pathname.startsWith("/restablecer"), { timeout: 20000 });
      await t.page.waitForLoadState("networkidle").catch(() => {});
    },
  },
  {
    texto: "Listo: ya estás dentro.",
  },
  {
    texto: "¿No te llegó? Revisa spam o pide otro enlace.",
    accion: (t) => t.ir(d.cierre),
  },
];
