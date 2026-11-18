/** Where players (or their guardians) write to exercise their data rights
 *  (acceso, rectificación, supresión, oposición, portabilidad). One SLAB
 *  mailbox for every club; SLAB coordinates with the club (the controller). */
export const PRIVACY_EMAIL = process.env.NEXT_PUBLIC_PRIVACY_EMAIL || "privacidad@s-lab.cl";

/** Public page with the procedure — shareable, no login. */
export const PRIVACY_PATH = "/privacidad";

export const privacyMailto = (subject = "Solicitud de derechos sobre datos personales") =>
  `mailto:${PRIVACY_EMAIL}?subject=${encodeURIComponent(subject)}`;
