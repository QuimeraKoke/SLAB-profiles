// "¿Cómo llega el plantel a entrenar?" — Centro de mando › Resumen, starting
// signed in: the one screen with the week and, per player, today's check-in,
// the last match and the load; then where the detail lives (Check-in / out,
// Fatiga post-partido, Kinesia y lesiones). Demo club only (seed_demo_daily).
import { execFileSync } from "node:child_process";
import path from "node:path";

export const titulo = "¿Cómo llega el plantel a entrenar?";
const APP = process.env.APP_URL ?? "http://localhost:3001";
const RAIZ = path.resolve(import.meta.dirname, "../..");

export function preparar() {
  execFileSync("docker", ["compose", "exec", "-T", "backend", "python", "manage.py", "seed_demo_daily", "--commit"],
    { cwd: RAIZ, stdio: "inherit" });
  return {};
}

export const pasos = () => {
  const sec = (t, id) => t.page.locator(`section[aria-labelledby=${id}]`);
  const fila = (t, nombre) => sec(t, "ds-table").locator("tbody tr").filter({ hasText: nombre });
  const pestaña = (t, nombre) => t.page.getByRole("tab", { name: nombre, exact: true });

  return [
    {
      texto: "Así ves, en una sola pantalla, cómo llega cada jugador a entrenar.",
      antes: async (t) => {
        await t.page.goto(`${APP}/login`, { waitUntil: "networkidle" });
        await t.page.getByLabel("Correo").fill("demo@laroja.cl");
        await t.page.getByLabel("Contraseña").fill("laroja2026");
        await t.page.getByRole("button", { name: "Ingresar" }).click();
        await t.page.waitForURL((u) => !u.pathname.startsWith("/login"));
      },
      abre: `${APP}/centro-de-mando`,
      accion: (t) => t.titulo("¿Cómo llega el plantel a entrenar?", "Centro de mando › Resumen"),
    },
    {
      texto: "En el Centro de mando, abre la pestaña «Resumen».",
      voz: "En el Centro de mando, abre la pestaña Resumen.",
      accion: async (t) => {
        await t.titulo(null);
        await t.clic(pestaña(t, "Resumen"));
        await t.page.waitForURL("**tab=resumen**");
        await sec(t, "ds-table").waitFor();
        await t.page.waitForLoadState("networkidle");
      },
    },
    {
      texto: "Arriba, la semana: carga, golpe del último partido, check-in y disponibles.",
      voz: "Arriba ves la semana: la carga, el golpe del último partido, el check-in y los disponibles.",
      accion: async (t) => {
        await t.ver(sec(t, "su-sentence"));
        await t.resaltar(sec(t, "su-sentence"));
      },
    },
    {
      texto: "Debajo, las señales de hoy: cuántos llegan con molestias, cansados, sin check-in o fuera de lo planificado.",
      voz: "Debajo, las señales de hoy: cuántos llegan con molestias, cansados, sin check in, o fuera de lo planificado.",
      accion: async (t) => {
        await t.ver(sec(t, "ds-head"));
        await t.resaltar(sec(t, "ds-head"));
      },
    },
    {
      texto: "Y la tabla muestra a cada jugador: check-in de hoy, último partido y carga vs lo planificado.",
      voz: "Y la tabla muestra a cada jugador: su check in de hoy, el último partido, y su carga contra lo planificado.",
      accion: async (t) => {
        await t.ver(sec(t, "ds-table").locator("thead"));
        await t.resaltar(sec(t, "ds-table").locator("thead"), 4);
      },
    },
    {
      texto: "Check-in: Nils Reichmuth contestó fatiga y daño muscular bajos…",
      voz: "En el check in, Nils Reichmuth marcó fatiga y daño muscular bajos.",
      accion: async (t) => {
        const f = fila(t, "Nils Reichmuth");
        await t.ver(f);
        await t.señalar(f.locator("td").nth(0));
        await t.resaltar(f);
      },
    },
    {
      texto: "…y su salto cayó 11 % después del partido: le pegó fuerte.",
      voz: "Y su salto cayó once por ciento después del partido: le pegó fuerte.",
      accion: async (t) => {
        const f = fila(t, "Nils Reichmuth");
        await t.señalar(f.locator("td").nth(1));
        await t.resaltar(f.locator("td").nth(1));
      },
    },
    {
      texto: "La carga compara lo que hizo en la semana con lo planificado: Maripán va 25 % sobre el plan.",
      voz: "La carga compara lo que hizo en la semana con lo planificado: Maripán va veinticinco por ciento sobre el plan.",
      accion: async (t) => {
        const f = fila(t, "Guillermo Maripán");
        await t.ver(f);
        await t.señalar(f.locator("td").nth(2));
        await t.resaltar(f.locator("td").nth(2));
      },
    },
    {
      texto: "Toca una señal para ver solo a esos jugadores: por ejemplo, los que marcaron molestias.",
      accion: async (t) => {
        await t.ver(sec(t, "ds-head"));
        await t.clic(t.page.getByRole("button", { name: /Molestia en el check-in/ }));
        await t.page.waitForURL("**ver=molestia**");
        await t.sleep(500);
        await t.ver(sec(t, "ds-table").locator("tbody"));
        await t.resaltar(sec(t, "ds-table").locator("tbody"));
      },
    },
    {
      texto: "SLAB no decide por ti: te muestra cómo llega cada uno, y tú defines quién entrena y con qué intensidad.",
      voz: "Eslab no decide por ti: te muestra cómo llega cada uno, y tú defines quién entrena, y con qué intensidad.",
      accion: async (t) => {
        await t.ver(sec(t, "ds-head"));
        await t.clic(t.page.getByRole("button", { name: "Ver todo el plantel" }));
        await t.page.waitForURL((u) => !u.search.includes("ver="));
      },
    },
    {
      texto: "¿Necesitas más detalle? En «Check-in / out» ves dónde les duele, en el mapa del cuerpo.",
      voz: "¿Necesitas más detalle? En Check in, ves dónde les duele, en el mapa del cuerpo.",
      accion: async (t) => {
        await t.ver(pestaña(t, "Check-in / out"));
        await t.clic(pestaña(t, "Check-in / out"));
        const mapa = t.page.getByRole("heading", { name: "¿Dónde les duele?" });
        await mapa.waitFor();
        await t.page.waitForLoadState("networkidle");
        const caja = t.page.locator("section").filter({ has: mapa });
        await t.ver(caja);
        await t.resaltar(caja);
      },
    },
    {
      texto: "En «Fatiga post-partido», el salto de cada jugador antes y después de cada partido.",
      voz: "En Fatiga post partido, el salto de cada jugador antes y después de cada partido.",
      accion: async (t) => {
        await t.ver(pestaña(t, "Fatiga post-partido"));
        await t.clic(pestaña(t, "Fatiga post-partido"));
        await t.page.waitForLoadState("networkidle");
        await t.sleep(600);
      },
    },
    {
      texto: "Y en «Kinesia y lesiones», quién está en readaptación y cuándo vuelve.",
      voz: "Y en Kinesia y lesiones, quién está en readaptación y cuándo vuelve.",
      accion: async (t) => {
        await t.clic(pestaña(t, "Kinesia y lesiones"));
        const h = t.page.getByRole("heading", { name: /No disponibles/ });
        await h.waitFor();
        await t.page.waitForLoadState("networkidle");
        const caja = t.page.locator("section").filter({ has: h });
        await t.ver(caja);
        await t.resaltar(caja);
      },
    },
    {
      texto: "Todo parte en «Resumen»: una vista para decidir el entrenamiento del día.",
      voz: "Todo parte en Resumen: una vista para decidir el entrenamiento del día.",
      accion: async (t) => {
        await t.ver(pestaña(t, "Resumen"));
        await t.clic(pestaña(t, "Resumen"));
        await sec(t, "ds-table").waitFor();
        await t.page.waitForLoadState("networkidle");
      },
    },
  ];
};
