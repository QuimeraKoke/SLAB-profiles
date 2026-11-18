/**
 * Public page (no login): how a player — or the parent/guardian of a minor —
 * exercises his rights over the data a club keeps in SLAB (ARCO + portability,
 * Ley 19.628 / Ley 21.719). Linked from the login screen and from
 * Administración › Privacidad e IA so the club can share it.
 */
import Link from "next/link";

import { PRIVACY_EMAIL, privacyMailto } from "@/lib/privacy";
import styles from "./page.module.css";

const RIGHTS = [
  { name: "Acceso", text: "Saber qué datos tuyos hay en SLAB y recibir una copia." },
  { name: "Rectificación", text: "Corregir datos inexactos o incompletos." },
  { name: "Supresión", text: "Pedir que se borren tus datos cuando ya no corresponda tenerlos." },
  { name: "Oposición", text: "Oponerte a un uso determinado, por ejemplo al análisis con IA." },
  { name: "Portabilidad", text: "Recibir tus datos en un formato de uso común (Excel o PDF)." },
];

export default function PrivacidadPublicPage() {
  return (
    <main className={styles.page}>
      <article className={styles.doc}>
        <header className={styles.header}>
          <span className={styles.brand}>SLAB</span>
          <h1>Privacidad y tus datos</h1>
          <p className={styles.lead}>
            Tu club usa SLAB para registrar información deportiva y de salud del plantel: evaluaciones, lesiones,
            controles diarios y cargas de entrenamiento. El club es el responsable de esos datos; SLAB los guarda y
            procesa por encargo del club.
          </p>
        </header>

        <section>
          <h2>Tus derechos</h2>
          <dl className={styles.rights}>
            {RIGHTS.map((r) => (
              <div key={r.name}>
                <dt>{r.name}</dt>
                <dd>{r.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className={styles.how}>
          <h2>Cómo ejercerlos</h2>
          <p>
            Escribe a{" "}
            <a href={privacyMailto()} className={styles.email}>{PRIVACY_EMAIL}</a>{" "}
            indicando:
          </p>
          <ol>
            <li>Tu nombre completo y RUT.</li>
            <li>El club y la categoría en que estás o estuviste.</li>
            <li>Qué derecho quieres ejercer (por ejemplo, «quiero una copia de mis datos» o «quiero que se borren»).</li>
            <li>Una copia de tu cédula de identidad, para verificar que eres tú.</li>
          </ol>
          <p className={styles.note}>
            <strong>Si el jugador es menor de edad</strong>, la solicitud la hace su madre, padre o apoderado,
            adjuntando su cédula y un documento que acredite la relación.
          </p>
        </section>

        <section>
          <h2>Qué pasa después</h2>
          <ul>
            <li>Te confirmamos que recibimos la solicitud y verificamos tu identidad.</li>
            <li>La coordinamos con tu club, que es el responsable de los datos.</li>
            <li>Te respondemos dentro del plazo que fija la ley. Las copias se entregan en Excel o PDF.</li>
            <li>
              Si pides borrar datos y alguno debe conservarse por obligación legal (por ejemplo, registros médicos),
              te diremos cuáles y por qué.
            </li>
          </ul>
        </section>

        <section>
          <h2>Inteligencia artificial</h2>
          <p>
            Algunas funciones usan IA para analizar los datos. Antes de enviarlos, tu nombre y tus datos de
            contacto se reemplazan por un código; los datos clínicos y de carga sí se envían para el análisis. Cada
            club decide si usa estas funciones, y cada envío queda registrado.
          </p>
        </section>

        <footer className={styles.footer}>
          <Link href="/login">Ir al inicio de sesión</Link>
        </footer>
      </article>
    </main>
  );
}
