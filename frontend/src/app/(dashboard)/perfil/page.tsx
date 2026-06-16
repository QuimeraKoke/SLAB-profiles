import { redirect } from "next/navigation";

// QW-1 sibling: `/perfil` standalone was a dead-end placeholder ("Selecciona
// un jugador desde el plantel"). Removed from the sidebar in QW-10; this
// route now redirects to the roster for anyone who reaches it via a stale
// bookmark or typed URL.
export default function PerfilIndex() {
  redirect("/equipo");
}
