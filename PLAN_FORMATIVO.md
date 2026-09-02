# Plan — integrar los datos oficiales de Formativo (U. de Chile)

Fuente: `U de Chile - Formativo/`, entregada el 2026-09-02 y declarada por el club
como **la fuente de verdad** del fútbol formativo.

| Archivo | Contenido | Volumen |
|---|---|---|
| `Wellness - Check in & Out/` (8 archivos) | Un archivo por categoría. Planteles + histórico de check-ins desde 2024 | — |
| `GPS CATEGORÍAS.xlsx` | Maestro de jugadores + GPS por categoría (U11–U20) + partidos + sparring | ~13.000 filas |
| `EVALUACIONES FÍSICAS CATEGORÍAS.xlsx` | Maestro + Resistencia, Carreras, Neuromuscular, Fuerza, VAM, Press banco | ~15.000 filas |

---

## 0. Lo que hay que decidir antes de escribir código

Ninguna es opinión mía: cada una cambia lo que se construye.

| # | Decisión | Por qué bloquea |
|---|---|---|
| 0.1 | **¿Sub 21 o Sub 20?** El club dice "Sub 21"; la ANFP los inscribe en Sub 20 y COMET no tiene ninguna competencia Sub 21 | Define si `Bracket` necesita una fila nueva o si "Sub 21" es sólo el nombre interno del plantel |
| 0.2 | **¿Recreamos U8, U9 y U10?** Se borraron el 2026-08-26 por estar vacías (y lo estaban). El maestro tiene **55 jugadores** en esas tres | Sin ellas, 55 jugadores no tienen dónde entrar |
| 0.3 | **¿"Categoría 2014" o "Serie 2014"?** El club usa "categoría" (dicen *"cat 2008"*); nosotros renombramos a "Serie" el 2026-08-26 | Es una migración de datos; conviene hacerla una sola vez |
| 0.4 | **HSR: ¿>20 o >19,8 km/h?** El formativo mide >20, `gps_sesion` dice >19,8 | Si el umbral difiere, los números **no son comparables** con los del plantel profesional. Es definicional, no cosmético |
| 0.5 | **Las 5 fechas de nacimiento en conflicto** (ver §1) | Alimentan el maturity offset: un error de meses corre la edad decimal |

---

## 1. Puerta de calidad — antes de importar nada

**El paso más importante del plan.** Estos datos entran a gráficos clínicos y a
cálculos de maduración; un nombre mal escrito crea un jugador fantasma y una
fecha invertida corre un cálculo.

### 1.1 Fechas de nacimiento contradictorias entre los dos archivos

| Jugador | GPS | Evaluaciones | Lectura |
|---|---|---|---|
| `DAVID GUZMAN VIVANCO` | 2008-06-09 | 2011-02-10 | **Son DOS jugadores distintos.** Tres años de diferencia. Resuelve el único caso "decidible" de la cola COMET, que estaba ambiguo por homónimos con RUT distinto |
| `ALONSO MUÑOZ` | 2014-08-02 | 2014-02-08 | día/mes invertidos |
| `VICENTE NILO` | 2015-12-02 | 2015-02-12 | día/mes invertidos |
| `IVO IBARRA` | 2012-01-14 | 2012-01-16 | 2 días |
| `BRANKO GEZAN GARCIA` | 2006-08-03 | 2006-02-17 | distinta, sin patrón |

### 1.2 Nombres de wellness sin respaldo en el maestro

El formulario de check-in es **texto libre**: quien lo completa tipea el nombre y
nada lo valida. Caso encontrado: `JOHN LAUREN` (160 apariciones, sólo en
check-ins) contra `JOHN LAURENT` (765, en el maestro, 2009-03-14, U18).

**Pendiente:** cruzar TODOS los nombres de check-in contra el maestro y producir
la lista de etiquetas sin jugador. Sirve para dos cosas: que el club limpie la
planilla, y que carguemos los alias que SLAB necesita para emparejar.

### 1.3 Huecos del maestro

- **13 de 433** jugadores sin fecha de nacimiento → sin maturity offset posible
- **4** con categoría `#N/A`

### Criterio de salida de la fase 1

Un CSV canónico `jugador → fecha nac. → categoría → posición` con **cero**
conflictos y cero `#N/A`, revisado por el club. Nada se importa antes.

---

## 2. Categorías y planteles

### 2.1 El convenio, confirmado por tres fuentes independientes

> **`Sub N` en la temporada S ← nacidos en (S − N)**, y donde dos categorías
> comparten competencia, entra también el año de abajo.

Verificado contra: los nombres de archivo, los planteles reales, y las
apariciones en partidos COMET.

⚠️ **La hoja `FICHA` de los archivos de wellness está sin mantener** — va uno o
dos años atrasada (la del Sub 18 tiene el plantel de 2024). **Se lee `Lista Check
In`, nunca `FICHA`.** Conviene avisarle al club: si alguien consulta la FICHA
para decidir algo, está viendo un plantel viejo.

### 2.2 Lo que falta crear

| Qué | Cuánto | Nota |
|---|---|---|
| Categoría 2015 (Sub 11 2026) | **38 jugadores**, ninguno en SLAB | Engancha los 25 partidos desprendidos y ~69 de las 72 personas COMET sin vincular |
| U8, U9, U10 | 55 jugadores | Sujeto a 0.2 |
| Jugadores nuevos del maestro | del orden de 100+ | Contar exacto tras la fase 1 |

### 2.3 Pertenencias con fechas reales

El histórico de check-ins desde 2024 muestra a cada jugador en su categoría a lo
largo del tiempo — **es la primera fuente real para `PlayerTeamMembership`**.
Hoy esas filas se escribieron con la heurística "fecha del primer partido", que
para dos jugadores del Sudamericano puso el 2025-03-27 como si fuera su ingreso.

---

## 3. Plantillas de examen

### 3.1 Decisión: cinco plantillas, NO una por categoría

Medido: las categorías chicas hacen un **subconjunto anidado**, nunca algo
distinto. Ninguna mide un campo que las mayores no tengan.

| Familia | Variantes | Corte |
|---|---|---|
| Carreras | 2 | U8–U11: T10, T30 · U12–U20: + COD 505 izq/der |
| Neuromuscular | 2 | U8–U12: CMJ · U13–U20: + TIRO (km/h) |
| GPS | 2 | U11–U16: 22 col · U18–U20: + 2 de frecuencia cardíaca |
| Resistencia | 1 | sólo la hacen U12+ |
| Fuerza | 1 | sólo la hacen U13+ |

Con dos variantes anidadas por familia, duplicar plantillas cuesta más de lo que
resuelve: serían 10 copias del mismo examen que hay que editar diez veces. Los
campos que una categoría no mide **quedan opcionales y vacíos**.

Y "quién hace el test" ya está resuelto: `applicable_categories`. Resistencia no
se le cuelga a U8–U11, Fuerza no se le cuelga a U8–U12. Cero desarrollo.

**El disparador para revisar esto** sería divergencia en vez de subconjunto: que
una categoría necesite un campo que las otras no tienen. Hoy no pasa en ninguna
de las cinco familias.

### 3.2 GPS: se reusa `gps_sesion`, no se crea una tercera

11 de 13 métricas ya tienen campo:

| Formativo | `gps_sesion` |
|---|---|
| DURACIÓN (m) | `tot_dur` |
| DT (m) | `tot_dist` |
| MM | `mpm` |
| AC / DEC (#) >3ms2 | `acc` / `dec` |
| VMÁX (km/h) | `max_vel` |
| PL (UA) | `player_load` |
| HSR (m) | `hsr` ⚠️ ver 0.4 |
| SPRINT (m) / (#) | `sprint_dist` / `sprints` |
| **Heart Rate — AVG HR (%)** | **falta** |
| **Heart Rate — Max HR (BPM)** | **falta** |

Se agregan los dos campos de pulso. Eso preserva la regla de **exactamente dos
exámenes de GPS en todo el sistema** (`gps_partido` + `gps_sesion`), que fue una
decisión deliberada y no un accidente.

`LOCALIA`, `CALIDAD OPONENTE` y `RESULTADO` indican que parte de esas filas son
**partidos**, no sesiones → van a `gps_partido`.

### 3.3 El único desarrollo nuevo: bandas por categoría

Las hojas `FORMATO CONDICIONAL` del club son el mismo test con umbrales
distintos por edad:

| RM Back Squat | Sub 13-14 y 11 | Sub 15-16 y 18-20 |
|---|---|---|
| "Muy Deficiente" | < 68,3 kg | < 125 kg |
| "Bueno" | 100,4–115,6 | 161–175 |

Hoy `TemplateField.reference_ranges` es una lista plana **sin variación por
categoría**, así que una plantilla compartida le diría a un Sub 11 que 100 kg de
sentadilla es "Regular" — el umbral de un Sub 20.

**Y esas bandas disparan alertas.** Un campo vacío de más es ruido visual; una
alerta con el umbral equivocado es una decisión equivocada. Es acá donde hay que
trabajar, no en duplicar plantillas.

Precedente en el modelo: `Category.load_config` ya guarda parámetros de ACWR por
categoría. Va en la misma dirección que los pedidos del doctor: *el club es dueño
del parámetro*.

---

## 4. Importadores

| Hoja | Formato | Consecuencia |
|---|---|---|
| `CARRERAS`, `NEUROMUSCULAR` | **largo** — una fila por jugador/fecha/test, con el nombre del test en una columna | **Un importador cubre toda la familia.** Agregar un test es dato, no código |
| `RESISTENCIA`, `FUERZA` | ancho — columnas fijas | Un importador por hoja |
| GPS por categoría | ancho, 22–24 col | Extender el importador de `gps_sesion` |

Todos con el patrón que ya usamos: **dry-run por defecto**, reporte de
emparejados / sin emparejar / rechazados, idempotencia por (jugador, fecha,
test), y validación de rango contra el `min`/`max` del campo.

⚠️ **Emparejamiento por nombre.** El pipeline genérico usa alias y nombre
completo exacto; no hace el matcheo por tokens del importador histórico. Con las
etiquetas del club (apellido materno, mayúsculas, typos) hay que **cargar alias
primero**, que es la salida de la fase 1.2.

---

## 5. Orden de ejecución

Cada fase termina con una verificación que se puede correr.

| Fase | Qué | Verificación |
|---|---|---|
| **1** | Puerta de calidad: CSV canónico, conflictos resueltos, alias listados | 0 conflictos, 0 `#N/A`, revisado por el club |
| **2** | Categorías faltantes + jugadores del maestro + alias | Todo nombre del maestro resuelve a un jugador |
| **3** | Pertenencias desde el histórico de check-ins | Un jugador que cambió de categoría muestra dos spells con fechas reales |
| **4** | Plantillas (5) + los 2 campos de pulso + `applicable_categories` | El formulario de cada categoría muestra sólo lo que mide |
| **5** | Bandas por categoría | Un Sub 11 y un Sub 20 con el mismo valor caen en bandas distintas |
| **6** | Importar evaluaciones físicas (~15k filas), en seco y después en firme | Conteos por familia y categoría contra la planilla |
| **7** | Importar GPS (~13k filas) | Ídem, y los partidos van a `gps_partido` |
| **8** | Re-verificar los módulos que dependen de esto | `/crecimiento` y `/desarrollo` con datos juveniles reales |

**La fase 8 es la recompensa:** con GPS juvenil cargado se desbloquea la
detección de talento por variables físicas, que hoy está bloqueada por datos y no
por código (0 filas de GPS en toda la cantera).

---

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Importar sobre nombres sucios crea jugadores fantasma | La fase 1 es una puerta, no una sugerencia |
| Fechas invertidas corren el maturity offset | Resolver las 5 antes; el rango de plausibilidad ya las atrapa si aparecen más |
| HSR con umbral distinto hace incomparables los datos juveniles y profesionales | Decisión 0.4 antes de importar |
| El club sigue editando la `FICHA` creyendo que es la fuente | Avisar que leemos `Lista Check In` |
| 28.000 filas de golpe | Dry-run por familia y categoría, con conteos contra la planilla antes de escribir |

---

## 7. Lo que este plan NO incluye

- **Proyección de talla adulta (%PAH)**: sigue bloqueada por las tallas de los
  padres, que el club está evaluando conseguir.
- **Femenino**: sin respuesta del club sobre cómo nombrar esas categorías.
- **Selecciones**: las hojas `U17WC`, `U20 WC` y `WC CLUBES` del GPS son de
  selección nacional. Mismo problema conceptual que los 6 partidos del
  Sudamericano que desprendimos: son partidos reales de otro equipo. Decidir
  aparte.
