// The "¿De dónde sale la referencia?" animation: every dot is one player in
// one real match of the demo club (exportar_datos.py), so what it shows is the
// module's own calculation. Driven step by step with window.paso(n).
import { writeFileSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const GRUPOS = [
  { code: "DFC", label: "Defensa central", color: "#5B9BF5" },
  { code: "LAT", label: "Lateral", color: "#3CC6B0" },
  { code: "MC", label: "Mediocampista", color: "#F2B33D" },
  { code: "EXT", label: "Extremo", color: "#F0766A" },
  { code: "DC", label: "Centro delantero", color: "#B48CF2" },
];

export function explicacion(dir, datos, ejemplo) {
  const archivo = path.join(dir, "explicacion.html");
  writeFileSync(archivo, `<!doctype html><meta charset="utf-8"><title>Referencia de partido</title>
<style>
  *{box-sizing:border-box} html,body{margin:0;height:100%;overflow:hidden}
  body{background:radial-gradient(circle at 30% 20%,#1e2a44 0%,#0b1525 70%);color:#fff;
    font-family:-apple-system,"Segoe UI",Roboto,sans-serif}
  h1{position:absolute;left:0;right:0;top:34px;margin:0;text-align:center;font-size:34px;letter-spacing:-.3px}
  .lead{position:absolute;left:0;right:0;top:84px;text-align:center;font-size:19px;color:#c7d2e4;transition:opacity .4s}
  .stage{position:absolute;left:90px;right:90px;top:130px;height:440px}
  .card{position:absolute;top:0;height:300px;border:1px solid rgba(255,255,255,.14);border-radius:14px;
    background:rgba(255,255,255,.04);transition:opacity .6s}
  .card b{display:block;text-align:center;margin-top:14px;font-size:17px}
  .card span{display:block;text-align:center;font-size:14px;color:#9fb0cc;margin-top:2px}
  .card .cnt{position:absolute;bottom:12px;left:0;right:0;font-size:15px;color:#e5edf8;opacity:0;transition:opacity .5s}
  .dot{position:absolute;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;opacity:0;
    transition:left 1.1s cubic-bezier(.6,0,.3,1),top 1.1s cubic-bezier(.6,0,.3,1),opacity .6s,background .5s,transform .5s}
  .dot.in{opacity:1}
  .dot.in.out{background:#475569 !important;transform:scale(.6);opacity:.55}
  .dot.in.gone{opacity:0;transform:scale(.2)}
  .col{position:absolute;bottom:40px;width:150px;margin-left:-75px;text-align:center;opacity:0;transition:opacity .5s}
  .col b{display:block;font-size:22px} .col span{font-size:14px;color:#9fb0cc}
  .bar{position:absolute;bottom:96px;width:110px;margin-left:-55px;height:0;border-radius:10px 10px 4px 4px;
    transition:height 1s cubic-bezier(.3,0,.2,1),opacity .5s}
  .val{position:absolute;width:160px;margin-left:-80px;text-align:center;font-size:21px;font-weight:700;opacity:0;
    transition:opacity .5s,bottom 1s cubic-bezier(.3,0,.2,1)}
  .dim{opacity:.1 !important}
  .formula{position:absolute;right:70px;top:250px;width:400px;padding:22px 26px;border-radius:14px;background:#fff;color:#0f172a;
    opacity:0;transform:translateY(12px);transition:opacity .5s,transform .5s;font-size:19px;line-height:1.55}
  .formula.on{opacity:1;transform:none}
  .formula small{display:block;font-size:14px;color:#64748b;text-transform:uppercase;letter-spacing:.06em}
  .formula .res{font-size:30px;font-weight:800;margin-top:6px}
  .formula .op{color:#6d28d9;font-weight:700}
</style>
<h1 id="h">¿De dónde sale la referencia?</h1>
<div class="lead" id="lead"></div>
<div class="stage" id="stage"></div>
<div class="formula" id="formula"></div>
<script>
const D = ${JSON.stringify(datos)};
const G = ${JSON.stringify(GRUPOS)};
const EJ = ${JSON.stringify(ejemplo)};
const st = document.getElementById("stage"), W = st.clientWidth;
const fmt = (n) => Math.round(n).toLocaleString("es-CL");
const fecha = (s) => new Date(s + "T12:00").toLocaleDateString("es-CL", { day: "numeric", month: "short" }).replace(".", "");
const color = Object.fromEntries(G.map((g) => [g.code, g.color]));
const M = D.partidos.length, cw = (W - (M - 1) * 24) / M;
const dots = [];
D.partidos.forEach((p, i) => {
  const x0 = i * (cw + 24);
  const c = document.createElement("div");
  c.className = "card"; c.style.left = x0 + "px"; c.style.width = cw + "px";
  const ok = p.jugadores.filter((j) => j.min > D.min_minutos && j.grupo && color[j.grupo]).length;
  c.innerHTML = "<b>vs " + p.rival + "</b><span>" + fecha(p.fecha) + "</span><div class=cnt>" + ok + " de " + p.jugadores.length + " jugadores</div>";
  st.appendChild(c);
  p.jugadores.forEach((j, k) => {
    const d = document.createElement("div");
    d.className = "dot"; d.style.background = color[j.grupo] || "#94a3b8";
    const x = x0 + cw / 2 + ((k % 5) - 2) * 30, y = 92 + Math.floor(k / 5) * 32;
    d.style.left = x + "px"; d.style.top = y + "px";
    st.appendChild(d);
    dots.push({ el: d, j });
  });
});
const colX = (i) => W * (i + 0.5) / G.length;
const max = Math.max(...G.map((g) => D.referencia[g.code].dt));
const bars = G.map((g, i) => {
  const col = document.createElement("div"); col.className = "col"; col.style.left = colX(i) + "px";
  col.innerHTML = "<b style='color:" + g.color + "'>" + g.code + "</b><span>" + g.label + "</span>";
  const bar = document.createElement("div"); bar.className = "bar"; bar.style.left = colX(i) + "px"; bar.style.background = g.color;
  const val = document.createElement("div"); val.className = "val"; val.style.left = colX(i) + "px"; val.style.bottom = "100px";
  st.append(col, bar, val);
  return { g, col, bar, val };
});
const H = 250, alto = (v) => (v / max) * H;
const $ = (id) => document.getElementById(id);
window.paso = (n) => {
  if (n === 1) {
    $("lead").textContent = "Partidos oficiales de los últimos " + D.dias + " días";
    dots.forEach((d, i) => setTimeout(() => d.el.classList.add("in"), i * 12));
  }
  if (n === 2) {
    $("lead").textContent = "Solo jugadores con más de " + D.min_minutos + " minutos";
    dots.forEach((d) => { if (!(d.j.min > D.min_minutos) || !color[d.j.grupo]) d.el.classList.add("out"); });
    document.querySelectorAll(".cnt").forEach((c) => (c.style.opacity = 1));
  }
  if (n === 3) {
    $("lead").textContent = "Agrupados por posición";
    document.querySelectorAll(".card").forEach((c) => (c.style.opacity = 0));
    const n = {};
    dots.forEach((d) => {
      if (d.el.classList.contains("out")) { d.el.classList.add("gone"); return; }
      const i = G.findIndex((g) => g.code === d.j.grupo), k = (n[i] = (n[i] || 0) + 1) - 1;
      d.el.style.left = colX(i) + ((k % 4) - 1.5) * 26 + "px";
      d.el.style.top = 300 - 20 - Math.floor(k / 4) * 26 + "px";
    });
    bars.forEach((b) => (b.col.style.opacity = 1));
  }
  if (n === 4) {
    $("lead").textContent = "El promedio de cada posición es su 100 % · Distancia total";
    dots.forEach((d) => d.el.classList.add("gone"));
    bars.forEach((b) => {
      const v = D.referencia[b.g.code].dt;
      b.bar.style.height = alto(v) + "px";
      b.val.style.bottom = 96 + alto(v) + 8 + "px"; b.val.textContent = fmt(v) + " m"; b.val.style.opacity = 1;
    });
  }
  if (n === 5) {
    $("h").textContent = "Del 100 % al objetivo del día";
    $("lead").style.opacity = 0;
    const ref = D.referencia[EJ.grupo].dt, obj = ref * EJ.pct / 100;
    bars.forEach((b) => {
      if (b.g.code !== EJ.grupo) { [b.bar, b.val, b.col].forEach((e) => e.classList.add("dim")); return; }
      setTimeout(() => {
        b.bar.style.height = alto(obj) + "px";
        b.val.style.bottom = 96 + alto(obj) + 8 + "px"; b.val.textContent = fmt(obj) + " m";
      }, 1600);
    });
    $("formula").innerHTML = "<small>" + EJ.grupo + " · " + EJ.dia + " · Distancia total</small>" +
      fmt(ref) + " m <span class=op>× " + EJ.pct + " %</span><div class=res>= " + fmt(obj) + " m</div>";
    $("formula").classList.add("on");
  }
};
</script>`);
  return pathToFileURL(archivo).href;
}
