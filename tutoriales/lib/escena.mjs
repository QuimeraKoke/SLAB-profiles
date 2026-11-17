// Runner shared by every tutorial: records the real app with Playwright,
// draws a visible cursor, click ripples and subtitles, and times each step to
// its narration so the voice lands on top of the action.
//
// A tutorial is a module exporting `pasos`: [{ texto, accion? }]. `texto` is
// both the subtitle and what the voice says; `accion(t)` runs while it plays.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { chromium } from "playwright";

export const ANCHO = 1280;
export const ALTO = 720;
const PAUSA = 250; // ms of silence after each line

// Voice: ElevenLabs when ELEVENLABS_API_KEY is set, otherwise macOS `say`
// (a free draft voice). Generated lines are cached by text + voice, so
// re-recording only pays for lines that changed.
const EL_KEY = process.env.ELEVENLABS_API_KEY;
const EL_VOZ = process.env.ELEVENLABS_VOICE ?? "rixsIpPlTphvsJd2mI03"; // "Isabel", neutral Latin American
const EL_MODELO = process.env.ELEVENLABS_MODEL ?? "eleven_multilingual_v2";
const SAY_VOZ = process.env.VOZ ?? "Paulina";
const CACHE = path.join(import.meta.dirname, "..", "salida", ".voces");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function elevenlabs(texto, archivo) {
  const r = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${EL_VOZ}?output_format=mp3_44100_128`, {
    method: "POST",
    headers: { "xi-api-key": EL_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      text: texto,
      model_id: EL_MODELO,
      voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.1, speed: 1.0 },
    }),
  });
  if (!r.ok) throw new Error(`ElevenLabs ${r.status}`);
  writeFileSync(archivo, Buffer.from(await r.arrayBuffer()));
}

/** One audio file per line; returns their paths and durations. */
export async function narrar(pasos) {
  mkdirSync(CACHE, { recursive: true });
  const voces = [];
  for (const p of pasos) {
    const texto = p.voz ?? p.texto;
    const motor = EL_KEY ? `el:${EL_VOZ}:${EL_MODELO}` : `say:${SAY_VOZ}`;
    const id = createHash("sha1").update(`${motor}\n${texto}`).digest("hex").slice(0, 16);
    const archivo = path.join(CACHE, `${id}.${EL_KEY ? "mp3" : "aiff"}`);
    if (!existsSync(archivo)) {
      if (EL_KEY) await elevenlabs(texto, archivo);
      else execFileSync("say", ["-v", SAY_VOZ, "-r", "170", "-o", archivo, texto]);
    }
    const dur = Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration",
      "-of", "csv=p=0", archivo]).toString().trim());
    voces.push({ archivo, dur });
  }
  return voces;
}

// Injected in every page: cursor, ripple and subtitle layers on top of the app.
function capa() {
  const montar = () => {
    if (document.getElementById("__tut")) return;
    const root = document.createElement("div");
    root.id = "__tut";
    root.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483645";
    root.innerHTML = `
      <style>
        #__tut, #__tut * { pointer-events: none; }
        #__tut .cur { position: fixed; z-index: 2147483647; width: 22px; height: 22px;
          margin: -3px 0 0 -4px; transition: transform .12s; }
        #__tut .cur.press { transform: scale(.85); }
        #__tut .rip { position: fixed; z-index: 2147483646; width: 44px; height: 44px; margin: -22px 0 0 -22px;
          border-radius: 50%; border: 3px solid #f5b301; animation: __rip .6s ease-out forwards; }
        @keyframes __rip { from { transform: scale(.3); opacity: 1 } to { transform: scale(1.4); opacity: 0 } }
        #__tut .sub { position: fixed; z-index: 2147483645; left: 50%; bottom: 34px; transform: translateX(-50%);
          max-width: 980px; padding: 12px 22px; border-radius: 10px; background: rgba(10,16,28,.86);
          color: #fff; font: 600 22px/1.35 -apple-system, "Segoe UI", Roboto, sans-serif; text-align: center;
          box-shadow: 0 6px 24px rgba(0,0,0,.35); transition: opacity .25s; }
        #__tut .sub:empty { opacity: 0; }
        nextjs-portal { display: none !important; } /* dev-mode badge */
        #__tut .hl { position: fixed; z-index: 2147483640; border-radius: 12px; border: 3px solid #f5b301;
          box-shadow: 0 0 0 9999px rgba(8,12,22,.42); opacity: 0;
          transition: opacity .35s, left .5s, top .5s, width .5s, height .5s; }
        #__tut .hl.on { opacity: 1; }
        #__tut .ttl { position: fixed; z-index: 2147483641; left: 50%; top: 50%; transform: translate(-50%,-50%) scale(.96);
          padding: 30px 46px; border-radius: 16px; background: rgba(11,21,37,.94); color: #fff; text-align: center;
          font-family: -apple-system, "Segoe UI", Roboto, sans-serif; box-shadow: 0 18px 60px rgba(0,0,0,.45);
          opacity: 0; transition: opacity .4s, transform .4s; }
        #__tut .ttl.on { opacity: 1; transform: translate(-50%,-50%) scale(1); }
        #__tut .ttl b { display: block; font-size: 40px; letter-spacing: -.4px; }
        #__tut .ttl span { display: block; margin-top: 8px; font-size: 20px; color: #c7d2e4; }
      </style>
      <svg class="cur" viewBox="0 0 24 24"><path d="M4 2l16 10-7 1.6L9.6 21z"
        fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>
      <div class="sub"></div><div class="hl"></div><div class="ttl"><b></b><span></span></div>`;
    document.documentElement.appendChild(root);
  };
  window.__tut = {
    poner(texto, x, y) {
      montar();
      document.querySelector("#__tut .sub").textContent = texto ?? "";
      this.mover(x, y);
    },
    mover(x, y) {
      montar();
      const c = document.querySelector("#__tut .cur");
      c.style.left = `${x}px`;
      c.style.top = `${y}px`;
    },
    resaltar(x, y, w, h) {
      montar();
      const e = document.querySelector("#__tut .hl");
      Object.assign(e.style, { left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px` });
      e.classList.add("on");
    },
    quitar() {
      document.querySelector("#__tut .hl")?.classList.remove("on");
    },
    titulo(t, s) {
      montar();
      const e = document.querySelector("#__tut .ttl");
      e.querySelector("b").textContent = t ?? "";
      e.querySelector("span").textContent = s ?? "";
      e.classList.toggle("on", !!t);
    },
    clic(x, y) {
      montar();
      const r = document.createElement("div");
      r.className = "rip";
      r.style.left = `${x}px`;
      r.style.top = `${y}px`;
      document.getElementById("__tut").appendChild(r);
      setTimeout(() => r.remove(), 700);
      const c = document.querySelector("#__tut .cur");
      c.classList.add("press");
      setTimeout(() => c.classList.remove("press"), 160);
    },
  };
  document.addEventListener("DOMContentLoaded", montar);
}

/** Records `pasos` into `dir/video.webm` and returns the start time of each line. */
export async function grabar(pasos, voces, dir) {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: ANCHO, height: ALTO },
    recordVideo: { dir, size: { width: ANCHO, height: ALTO } },
    locale: "es-CL",
  });
  await context.addInitScript(capa);
  const page = await context.newPage();
  const tVideo = Date.now();

  const estado = { texto: "", x: ANCHO / 2, y: ALTO / 2 };
  const aplicar = () => page.evaluate(([t, x, y]) => window.__tut?.poner(t, x, y),
    [estado.texto, estado.x, estado.y]).catch(() => {});
  page.on("domcontentloaded", aplicar);

  const t = {
    page,
    sleep,
    async ir(url) {
      await page.goto(url, { waitUntil: "networkidle" });
      await aplicar();
    },
    async mover(x, y, ms = 450) {
      const n = Math.max(8, Math.round(ms / 16));
      const [x0, y0] = [estado.x, estado.y];
      for (let i = 1; i <= n; i++) {
        const k = i / n;
        const e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2; // ease in-out
        estado.x = x0 + (x - x0) * e;
        estado.y = y0 + (y - y0) * e;
        await page.mouse.move(estado.x, estado.y);
        await page.evaluate(([x, y]) => window.__tut?.mover(x, y), [estado.x, estado.y]).catch(() => {});
        await sleep(16);
      }
    },
    async clic(loc) {
      await loc.waitFor({ state: "visible" });
      const b = await loc.boundingBox();
      const [x, y] = [b.x + b.width / 2, b.y + b.height / 2];
      await this.mover(x, y);
      await sleep(150);
      await page.evaluate(([x, y]) => window.__tut?.clic(x, y), [x, y]);
      await page.mouse.click(x, y);
    },
    async escribir(loc, texto) {
      await this.clic(loc);
      await loc.pressSequentially(texto, { delay: 45 });
    },
    async señalar(loc) {
      const b = await loc.boundingBox();
      await this.mover(b.x + b.width / 2, b.y + b.height / 2);
    },
    /** Frame `loc` (dimming the rest) until the next step or `quitar()`. */
    async resaltar(loc, pad = 6) {
      const b = await loc.boundingBox();
      await page.evaluate(([x, y, w, h]) => window.__tut?.resaltar(x, y, w, h),
        [b.x - pad, b.y - pad, b.width + 2 * pad, b.height + 2 * pad]);
    },
    quitar: () => page.evaluate(() => window.__tut?.quitar()).catch(() => {}),
    /** Smooth-scroll `loc` to the middle of the screen. */
    async ver(loc, block = "center") {
      await loc.evaluate((el, block) => el.scrollIntoView({ behavior: "smooth", block }), block);
      await sleep(750);
    },
    /** Fill an input at once (no typing), for the "and so on" parts. */
    async rellenar(loc, texto) {
      await loc.fill(texto);
      await sleep(70);
    },
    titulo: (txt, sub) => page.evaluate(([a, b]) => window.__tut?.titulo(a, b), [txt, sub]),
  };

  // Headless Chrome records the FIRST site it renders short (a grey band at
  // the bottom) until a navigation to another site swaps the renderer. So
  // open a blank data: page first, then warm up: the first step's `antes(t)`
  // (e.g. log in) or a page (`calentar`), then its page (`abre`), all before
  // the clock starts: montar() trims this lead-in.
  await page.goto("data:text/html,<body style='background:%230b1525'>"); // a site no tutorial uses
  if (pasos[0]?.antes) await pasos[0].antes(t);
  for (const url of [pasos[0]?.calentar, pasos[0]?.abre].filter(Boolean)) {
    await page.goto(url, { waitUntil: "networkidle" });
  }
  await aplicar();
  await sleep(800);
  const t0 = Date.now();

  const inicios = [];
  for (const [i, paso] of pasos.entries()) {
    estado.texto = paso.texto;
    await aplicar();
    await t.quitar();
    const inicio = Date.now();
    inicios.push((inicio - t0) / 1000);
    try {
      await paso.accion?.(t);
    } catch (err) {
      const shot = path.join(dir, `error-paso-${i + 1}.png`);
      await page.screenshot({ path: shot }).catch(() => {});
      err.message = `Paso ${i + 1} («${paso.texto}»): ${err.message}\nCaptura: ${shot}`;
      await context.close();
      await browser.close();
      throw err;
    }
    const resta = voces[i].dur * 1000 + PAUSA - (Date.now() - inicio);
    if (resta > 0) await sleep(resta);
  }
  estado.texto = "";
  await aplicar();
  await sleep(600);

  const video = page.video();
  await context.close();
  await browser.close();
  return { video: await video.path(), inicios, recorte: (t0 - tVideo) / 1000 };
}

/** Video + voice lines → MP4, plus an .srt with the same lines. */
export function montar({ video, inicios, recorte }, voces, pasos, salida) {
  const entradas = ["-y", "-ss", String(recorte), "-i", video];
  voces.forEach((v) => entradas.push("-i", v.archivo));
  const retrasos = voces.map((_, i) => {
    const ms = Math.round(inicios[i] * 1000);
    return `[${i + 1}:a]adelay=${ms}|${ms}[a${i}]`;
  });
  const mezcla = `${voces.map((_, i) => `[a${i}]`).join("")}amix=inputs=${voces.length}:normalize=0[aout]`;
  execFileSync("ffmpeg", [
    ...entradas,
    "-filter_complex", [...retrasos, mezcla].join(";"),
    "-map", "0:v", "-map", "[aout]",
    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest",
    salida,
  ], { stdio: "inherit" });

  const hms = (s) => {
    const ms = Math.round(s * 1000);
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
  };
  const srt = pasos.map((p, i) =>
    `${i + 1}\n${hms(inicios[i])} --> ${hms(inicios[i] + voces[i].dur)}\n${p.texto}\n`).join("\n");
  writeFileSync(salida.replace(/\.mp4$/, ".srt"), srt);
}

/** Title / closing card rendered in the same browser (file://). */
export function tarjeta(dir, nombre, { titulo, bajada }) {
  const logo = pathToFileURL(path.resolve(import.meta.dirname, "../../frontend/public/slab-logo.svg")).href;
  const archivo = path.join(dir, `${nombre}.html`);
  writeFileSync(archivo, `<!doctype html><meta charset="utf-8"><title>${titulo}</title>
<style>
  html{background:#0b1525}
  html,body{margin:0;height:100%;overflow:hidden}
  body{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;
    background:radial-gradient(circle at 30% 20%,#1e2a44 0%,#0b1525 70%);color:#fff;
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif;text-align:center}
  img{width:120px;filter:brightness(0) invert(1) drop-shadow(0 6px 18px rgba(0,0,0,.4))}
  h1{font-size:46px;margin:0;letter-spacing:-.5px}
  p{font-size:22px;margin:0;color:#c7d2e4;max-width:820px;line-height:1.4}
</style>
<img src="${logo}" alt="SLAB"><h1>${titulo}</h1><p>${bajada ?? ""}</p>`);
  return pathToFileURL(archivo).href;
}
