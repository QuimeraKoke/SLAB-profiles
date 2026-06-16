import { redirect } from "next/navigation";

// QW-1: the dashboard root has no real "Inicio" page yet. Send the user to
// the roster — it's the most useful landing for every role we have today.
// When a proper role-aware Inicio ships, replace this redirect with that page.
export default function DashboardIndex() {
  redirect("/equipo");
}
