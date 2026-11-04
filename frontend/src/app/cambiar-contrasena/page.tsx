"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import AuthShell, { authStyles as styles } from "@/components/auth/AuthShell";
import ChangePasswordForm from "@/components/auth/ChangePasswordForm";
import { useAuth } from "@/context/AuthContext";

/** Where a user with a temporary password lands (AuthContext's guard keeps
 *  them here) until they choose their own. */
export default function CambiarContrasenaPage() {
  const { user, setMe, logout } = useAuth();
  const router = useRouter();
  const owes = !!user?.must_change_password;

  // Nothing owed (a bookmark, a back button): a voluntary change lives in
  // the sidebar's "Cambiar contraseña", not here.
  useEffect(() => {
    if (user && !owes) router.replace("/centro-de-mando");
  }, [user, owes, router]);

  if (!user || !owes) return null;

  return (
    <AuthShell
      title="Elegí tu contraseña"
      lead={
        <>
          Ingresaste con una contraseña temporal. Antes de seguir, elegí una
          propia para <strong>{user.email}</strong>.
        </>
      }
    >
      <ChangePasswordForm
        currentLabel="Contraseña temporal"
        onDone={(me) => {
          setMe(me);
          router.push("/centro-de-mando");
        }}
      />
      <button type="button" className={styles.link} onClick={logout}>
        Cerrar sesión
      </button>
    </AuthShell>
  );
}
