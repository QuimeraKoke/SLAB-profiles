// "Programar la carga semanal" — Control de carga › Planificación, starting
// signed in. Explains where the match reference comes from with an animation
// drawn from the demo club's real rows (exportar_datos.py), then plans,
// saves and publishes a week. Demo club only (seed_demo_carga).
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { explicacion } from "./explicacion.mjs";

export const titulo = "Programar la carga semanal";
const APP = process.env.APP_URL ?? "http://localhost:3001";
const RAIZ = path.resolve(import.meta.dirname, "../..");
const METRICAS = ["tot_dist", "hsr", "sprint_dist", "acc", "dec"];
// Illustrative % per day (DT, HSR, Sprint, ACC, DEC): a demo, not advice.
const PLAN = {
  "MD+2": [40, 20, 10, 40, 40],
  "MD+3": [60, 50, 40, 70, 70],
  "MD-3": [70, 60, 50, 80, 80],
  "MD-2": [55, 70, 80, 50, 50],
  "MD-1": [35, 30, 30, 30, 30],
};
const EJEMPLO = { grupo: "MC", dia: "MD-3", pct: 70 };

const miles = (n) => Math.round(n).toLocaleString("es-CL");

export function preparar(dir) {
  const salida = execFileSync("docker", ["compose", "exec", "-T", "backend", "python", "manage.py", "shell"], {
    cwd: RAIZ, input: readFileSync(path.join(import.meta.dirname, "exportar_datos.py")),
  }).toString();
  const datos = JSON.parse(salida.split("@@DATOS@@")[1]);
  datos.dias = Math.round((new Date(datos.fin) - new Date(datos.inicio)) / 86400000);
  return {
    datos,
    animacion: explicacion(dir, datos, EJEMPLO),
    objetivo: miles(datos.referencia[EJEMPLO.grupo].dt * EJEMPLO.pct / 100),
  };
}

export const pasos = (d) => {
  const sec = (t, id) => t.page.locator(`section[aria-labelledby=${id}]`);
  // The plan rows are labelled by MD (the server computes them from the match).
  const fila = (t, md) => sec(t, "lc-plan").locator("tbody tr").filter({ hasText: md });
  let volver = `${APP}/control-carga?tab=planificacion`;

  return [
    {
      texto: "Así programas la carga de la semana en SLAB.",
      antes: async (t) => {
        await t.page.goto(`${APP}/login`, { waitUntil: "networkidle" });
        await t.page.getByLabel("Correo").fill("demo@laroja.cl");
        await t.page.getByLabel("Contraseña").fill("laroja2026");
        await t.page.getByRole("button", { name: "Ingresar" }).click();
        await t.page.waitForURL((u) => !u.pathname.startsWith("/login"));
      },
      abre: `${APP}/centro-de-mando`,
      accion: (t) => t.titulo("Programar la carga semanal", "Control de carga › Planificación"),
    },
    {
      texto: "Entra a «Control de carga» y abre la pestaña «Planificación».",
      accion: async (t) => {
        await t.titulo(null);
        await t.clic(t.page.getByRole("link", { name: "Control de carga" }));
        await t.page.waitForURL("**/control-carga**");
        await t.page.waitForLoadState("networkidle");
        await t.page.getByRole("button", { name: "Nueva semana" }).waitFor(); // hydrated
        await t.clic(t.page.getByRole("tab", { name: "Planificación" }));
        await t.page.waitForURL("**tab=planificacion**");
      },
    },
    {
      texto: "Pulsa «Nueva semana». SLAB propone las fechas y detecta el partido del sábado.",
      accion: async (t) => {
        await t.clic(t.page.getByRole("button", { name: "Nueva semana" }));
        const sab = t.page.getByRole("dialog").getByLabel(/vs PERÚ/i);
        await sab.waitFor();
        await t.sleep(300);
        await t.resaltar(sab.locator(".."));
      },
    },
    {
      texto: "Corrige lo que haga falta, como el domingo de descanso, y pulsa «Crear semana».",
      accion: async (t) => {
        const dom = t.page.getByRole("dialog").getByLabel(/^dom/i);
        await t.señalar(dom);
        await dom.selectOption({ label: "Descanso" });
        await t.sleep(500);
        await t.clic(t.page.getByRole("button", { name: "Crear semana" }));
        await sec(t, "lc-dias").waitFor();
        volver = t.page.url();
      },
    },
    {
      texto: "Cada día queda etiquetado por su distancia al partido: MD-1 es la víspera; MD+2, dos días después.",
      voz: "Cada día queda etiquetado según su distancia al partido: eme de menos uno es la víspera; eme de más dos, dos días después.",
      accion: async (t) => {
        await t.sleep(400);
        await t.resaltar(sec(t, "lc-dias").locator("> div").nth(1));
      },
    },
    {
      texto: "El objetivo de cada día es un % de la carga de partido. ¿De dónde sale esa carga?",
      voz: "El objetivo de cada día es un porcentaje de la carga de partido. ¿De dónde sale esa carga?",
      accion: async (t) => {
        await t.sleep(1800);
        await t.ir(d.animacion);
      },
    },
    {
      texto: `SLAB toma los partidos oficiales del equipo de los últimos ${d.datos.dias} días.`,
      accion: (t) => t.page.evaluate(() => window.paso(1)),
    },
    {
      texto: `Solo cuentan los jugadores que jugaron más de ${d.datos.min_minutos} minutos.`,
      accion: (t) => t.page.evaluate(() => window.paso(2)),
    },
    {
      texto: "Los agrupa por posición: la que el club anotó en el GPS de cada partido.",
      accion: (t) => t.page.evaluate(() => window.paso(3)),
    },
    {
      texto: "Y promedia cada métrica. Ese promedio es el 100 % de cada posición.",
      voz: "Y promedia cada métrica. Ese promedio es el cien por ciento de cada posición.",
      accion: (t) => t.page.evaluate(() => window.paso(4)),
    },
    {
      texto: `Tú eliges el % de cada día: un mediocampista al ${EJEMPLO.pct} % el MD-3 debe correr ${d.objetivo} metros.`,
      voz: `Tú eliges el porcentaje de cada día: un mediocampista al ${EJEMPLO.pct} por ciento el eme de menos tres, debe correr ${d.objetivo} metros.`,
      accion: (t) => t.page.evaluate(() => window.paso(5)),
    },
    {
      texto: "En la app, la tabla «Referencia de partido» muestra ese 100 % por posición.",
      voz: "En la app, la tabla Referencia de partido muestra ese cien por ciento por posición.",
      accion: async (t) => {
        await t.ir(volver);
        await t.ver(sec(t, "lc-ref"));
        await t.resaltar(sec(t, "lc-ref").locator("table"));
      },
    },
    {
      texto: "La columna «Base» dice cuántos jugadores y partidos se usaron, y abajo está el detalle.",
      voz: "La columna Base dice cuántos jugadores y partidos se usaron, y abajo está el detalle.",
      accion: async (t) => {
        const base = sec(t, "lc-ref").locator("thead th").last();
        const ultima = sec(t, "lc-ref").locator("tbody tr").last().locator("td").last();
        const [a, b] = [await base.boundingBox(), await ultima.boundingBox()];
        await t.page.evaluate(([x, y, w, h]) => window.__tut.resaltar(x, y, w, h),
          [a.x - 6, a.y - 6, Math.max(a.width, b.width) + 12, b.y + b.height - a.y + 12]);
        await t.sleep(2200);
        await t.resaltar(sec(t, "lc-ref").locator("p").last());
      },
    },
    {
      texto: "Ahora escribe el % de cada día y métrica.",
      voz: "Ahora escribe el porcentaje de cada día y métrica.",
      accion: async (t) => {
        await t.ver(sec(t, "lc-plan"), "start");
        const inputs = fila(t, "MD-3").locator("input");
        for (const [i, v] of PLAN["MD-3"].entries()) {
          await t.escribir(inputs.nth(i), String(v));
        }
      },
    },
    {
      texto: "Completa los demás días. Una celda vacía significa «sin objetivo», no cero.",
      voz: "Completa los demás días. Una celda vacía significa sin objetivo, no cero.",
      accion: async (t) => {
        for (const [md, valores] of Object.entries(PLAN)) {
          if (md === "MD-3") continue;
          const inputs = fila(t, md).locator("input");
          for (const [i, v] of valores.entries()) await t.rellenar(inputs.nth(i), String(v));
        }
      },
    },
    {
      texto: "Abajo ves el objetivo en metros de cada posición.",
      accion: async (t) => {
        await t.ver(sec(t, "lc-obj"));
        await t.clic(sec(t, "lc-obj").getByRole("button", { name: EJEMPLO.grupo, exact: true }));
        await t.sleep(300);
        await t.resaltar(sec(t, "lc-obj").locator("tbody tr").filter({ hasText: EJEMPLO.dia }));
      },
    },
    {
      texto: "Pulsa «Guardar»…",
      voz: "Pulsa Guardar.",
      accion: async (t) => {
        await t.clic(t.page.getByRole("button", { name: "Guardar", exact: true }));
        await t.page.getByText(/guardada/).waitFor();
      },
    },
    {
      texto: "…y «Publicar»: la referencia queda fija toda la semana, aunque se jueguen otros partidos.",
      voz: "Y luego, Publicar: la referencia queda fija toda la semana, aunque se jueguen otros partidos.",
      accion: async (t) => {
        await t.clic(t.page.getByRole("button", { name: "Publicar", exact: true }));
        const dlg = t.page.getByRole("dialog");
        await dlg.waitFor();
        await t.sleep(1800);
        await t.clic(dlg.getByRole("button", { name: "Publicar" }));
        await t.page.getByText(/publicada/).waitFor();
      },
    },
    {
      texto: "Durante la semana, en «Carga GPS» verás si cada jugador cumplió su objetivo.",
      voz: "Durante la semana, en Carga GPS, verás si cada jugador cumplió su objetivo.",
      accion: async (t) => {
        await t.ver(t.page.getByRole("tab", { name: "Carga GPS" }));
        await t.clic(t.page.getByRole("tab", { name: "Carga GPS" }));
        await t.page.waitForLoadState("networkidle");
      },
    },
  ];
};
