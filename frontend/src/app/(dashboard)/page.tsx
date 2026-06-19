import { redirect } from "next/navigation";

// The dashboard home is the Centro de mando — the daily command-center view.
export default function DashboardIndex() {
  redirect("/centro-de-mando");
}
