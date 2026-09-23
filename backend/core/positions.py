"""El catálogo canónico de posiciones: qué línea es cada una y en qué orden va.

Una sola fuente de verdad, porque el problema que esto resuelve fue tener dos.
El catálogo de la U. de Chile creció como dos vocabularios superpuestos —uno
genérico (`Arquero`, `Mediocampista`, `Delantero`, `Defensor`), otro granular
(`Defensa central`, `Lateral derecho`, `Volante interior`, …)— y comparar entre
divisiones por nombre exacto dejaba a 154 de 354 jugadores sin contraparte,
todos los laterales incluidos.

`Position.role` es la LÍNEA, no la granularidad. Su docstring siempre lo dijo
("Optional grouping shown above the name"); lo que había escrito ahí era
`General` / `Específica`, que no agrupa nada.

Mantener esto acá y no dentro de un comando es deliberado: lo leen el
normalizador (`normalize_positions`), el importador del plantel formativo y
—cuando exista— la comparación entre divisiones. Si cada uno tuviera su copia,
volveríamos al problema original con más pasos.

Módulo sin dependencias de Django a propósito: es dato, se testea sin ORM.
"""
from __future__ import annotations

# Las cuatro líneas, en orden de cancha.
ARQUERO = "Arquero"
DEFENSA = "Defensa"
MEDIO = "Mediocampo"
ATAQUE = "Ataque"

LINEAS = (ARQUERO, DEFENSA, MEDIO, ATAQUE)

# abreviatura → (línea, orden).
#
# La clave es la abreviatura y no el nombre porque es única por club
# (`unique_together = [("club", "abbreviation"), ...]`) y estable; los nombres
# varían hasta en mayúsculas entre filas hermanas ("Lateral Volante izquierdo"
# vs "Lateral volante derecho").
#
# Los tramos dejan hueco (10/20/30) para sumar una posición a una línea sin
# renumerar el catálogo entero.
CANON: dict[str, tuple[str, int]] = {
    "POR": (ARQUERO, 0),

    "D":   (DEFENSA, 10),    # Defensa — genérica, el club no especificó
    "DF":  (DEFENSA, 11),    # Defensor — genérica
    "DC":  (DEFENSA, 12),    # Defensa central
    "L":   (DEFENSA, 13),    # Lateral, sin lado
    "LD":  (DEFENSA, 14),
    "LI":  (DEFENSA, 15),
    "LVD": (DEFENSA, 16),
    "LVI": (DEFENSA, 17),

    "MC":  (MEDIO, 20),      # Mediocampista — genérica
    "VC":  (MEDIO, 21),
    "VI2": (MEDIO, 22),      # Volante interior
    "VO":  (MEDIO, 23),
    "VD":  (MEDIO, 24),
    "VI":  (MEDIO, 25),      # Volante izquierdo
    "DEL": (ATAQUE, 30),     # Delantero — genérica
    "DC2": (ATAQUE, 31),     # Delantero centro
    "EX":  (ATAQUE, 32),     # Extremo, sin lado
    "ED":  (ATAQUE, 33),
    "EI":  (ATAQUE, 34),
}


def linea_de(abreviatura: str) -> str | None:
    """La línea de una abreviatura, o `None` si no está en el catálogo.

    `None` no es un detalle: una posición sin línea no tiene contra qué medirse
    en una comparación entre divisiones, y quien la reciba tiene que decirlo en
    vez de inventarle una.
    """
    entrada = CANON.get(abreviatura)
    return entrada[0] if entrada else None
