"use client";

import React from "react";

import styles from "./page.module.css";

/** The examples of a problem; each one the API knows how to find in the sheet
 *  is a link that opens Drive right there. */
export default function Examples({ examples, locations, onOpen }: {
  examples: string[]; locations: string[]; onOpen: (index: number) => void;
}) {
  return (
    <>
      {examples.map((ex, k) => {
        const n = locations.indexOf(ex);
        return (
          <React.Fragment key={ex + k}>
            {k > 0 && " · "}
            {n >= 0 ? (
              <button type="button" className={styles.exLink} onClick={() => onOpen(n)}
                title="Ver en la planilla (otra pestaña)">{ex}</button>
            ) : ex}
          </React.Fragment>
        );
      })}
    </>
  );
}
