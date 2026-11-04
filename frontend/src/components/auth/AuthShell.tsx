import Image from "next/image";

import styles from "./AuthShell.module.css";

export { styles as authStyles };

/** Card around the password screens that live outside the dashboard. */
export default function AuthShell({
  title,
  lead,
  children,
}: {
  title: string;
  lead?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <main className={styles.container}>
      <div className={styles.box}>
        <div className={styles.brand}>
          <Image src="/slab-logo.svg" alt="SLAB" width={64} height={52} priority />
          <h1 className={styles.title}>{title}</h1>
          {lead && <p className={styles.lead}>{lead}</p>}
        </div>
        {children}
      </div>
    </main>
  );
}
