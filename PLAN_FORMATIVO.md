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
| ~~0.1~~ | ✅ **RESUELTA (2026-09-02): es Sub 20.** El cliente confirma que para ellos es Sub 20; "Sub 21" es sólo cómo nombran el archivo. **No se agrega ninguna fila a `Bracket`** y el archivo `SUB 21 - 2026 - CAT 07-05` alimenta el bracket Sub 20 que ya existe | — |
| ~~0.2~~ | ✅ **RESUELTA (2026-09-02): se crean.** Criterio del cliente: *manda lo que entregaron, se borran si no hay info*. Y hay — ver §2.3 | — |
| ~~0.3~~ | ✅ **RESUELTA (2026-09-02): se queda `Serie XXXX - Sub YY`.** Es lo que ya produce `season_label_parts()`, así que **no hay migración** ni cambio de código | — |
| ~~0.4~~ | ⚠️ **SUPUESTO (2026-09-02): se tratan como equivalentes.** Decisión del cliente para no bloquear. Es un SUPUESTO, no un hecho verificado — ver §3.4 |
| ~~0.5~~ | ✅ **RESUELTA (2026-09-02)** por el club, las cinco. Ver §1.1 | — |

---

## 1. Puerta de calidad — antes de importar nada

**El paso más importante del plan.** Estos datos entran a gráficos clínicos y a
cálculos de maduración; un nombre mal escrito crea un jugador fantasma y una
fecha invertida corre un cálculo.

### 1.1 Fechas de nacimiento contradictorias ✅ RESUELTAS (2026-09-02)

Confirmadas por el club una por una:

| Jugador | GPS | Evaluaciones | **Correcta** | Ganó |
|---|---|---|---|---|
| `ALONSO MUÑOZ` | 2014-08-02 | 2014-02-08 | **2014-02-08** | Evaluaciones |
| `VICENTE NILO` | 2015-12-02 | 2015-02-12 | **2015-12-02** | GPS |
| `IVO IBARRA` | 2012-01-14 | 2012-01-16 | **2012-01-16** | Evaluaciones |
| `BRANKO GEZAN GARCIA` | 2006-08-03 | 2006-02-17 | **2006-08-03** | GPS |
| `DAVID GUZMAN VIVANCO` | 2008-06-09 | 2008-06-09 | **2008-06-09** | ambos |

⚠️ **Ninguno de los dos archivos es autoritativo para la fecha de nacimiento.**
Dos respuestas salieron de cada uno, así que **no existe la regla fácil** de
"ante conflicto gana tal archivo": cada caso se resuelve preguntando. Vale para
los conflictos que aparezcan al importar el resto.

Las cinco respuestas eligieron uno de los dos candidatos existentes — ninguna
trajo una fecha nueva, lo que sugiere que las buscaron en la ficha y no las
estimaron.

### 1.1.b Los dos David Guzmán

Confirmado: **son dos jugadores distintos**, y se distinguen por apellido
materno.

| Nombre real | Nacimiento | Categoría | Posición |
|---|---|---|---|
| `DAVID GUZMAN VIVANCO` | 2008-06-09 | U18 | Centro delantero |
| `DAVID GUZMAN BASCUR` | 2011-02-10 | U15 | Mediocampista |

⚠️ **El archivo de GPS tiene un error**: en la fila del U15 lo registra como
`DAVID GUZMAN VIVANCO` cuando es `BASCUR`. Al importar hay que **corregir ese
nombre**, no sólo separar las fechas — si se importa tal cual, el nombre sigue
apuntando a dos personas.

Esto también resuelve el único caso decidible de la cola de 72 personas COMET sin
vincular, que llevaba días ambiguo por dos homónimos con RUT distinto.

### 1.1.c La columna `CATEGORÍA` es derivada y volátil — no se importa

Sostuve acá que había 7 homónimos más además de los dos David. **Era falso**, y
la causa está en la propia planilla. `CATEGORÍA` (columna D de `JUGADORES`) es:

```
=IFS(C>18.9,"U21", C>16.9,"U18", C>15.9,"U16", C>14.9,"U15",
     C>13.9,"U14", C>12.9,"U13", C>11.9,"U12", C>10.9,"U11")
donde  C = YEARFRAC(B, TODAY())
```

Dos fallas independientes salen de ahí:

1. **Fecha vacía → `U21`/`U20`.** `YEARFRAC(vacío, TODAY())` cuenta desde 1900 y
   da **126,67 años**, así que dispara el primer peldaño. Las 16 filas sin fecha
   están etiquetadas U20/U21 por eso, no porque alguien lo decidiera. Los 7
   "homónimos de Sub 20" eran **filas duplicadas** de chicos de U13–U15 que sí
   tienen fecha: las hojas de plantel (`U13`, `U14`, `U15`) los listan una sola
   vez. La fecha del chico **sí** hay que copiarla a esa fila.
2. **Sin peldaño bajo 10.9 → `#N/A`.** Los 4 sin categoría son nacidos entre
   octubre y diciembre de 2015 (10,68–10,89 años hoy) y se caen del `IFS`. Sus
   19 compañeros de cohorte 2015 dicen `U11`, y la hoja `U11` los incluye a los
   cuatro. Con `TODAY()` esto se "arregla" solo en unas semanas, lo que es peor
   que si quedara roto: la etiqueta es función del reloj, no un dato.

**Consecuencia:** SLAB importa **`FECHA NACIMIENTO`** —el hecho— y calcula la
etiqueta Sub N por temporada recorriendo `Bracket.order`, que es lo que ya hace
`Category.season_label_parts()`. La `CATEGORÍA` del archivo se usa sólo como
contraste, nunca como fuente. Es el mismo antipatrón que corregimos en
`CometCompetitionLink`: guardar un join en vez del hecho.

El emparejamiento va por **nombre + categoría deducida de la cohorte**, con RUT
donde el club lo tenga. Medido sobre el maestro: 0 colisiones reales una vez
aplicadas las 5 fechas que confirmó el club, y el único homónimo verdadero del
club son los dos David (§1.1.b), que se separan por apellido materno.

**Fechas cruzadas:** de 299 jugadores presentes en los dos archivos con fecha,
**294 coinciden**. Los 5 que discrepan son los que el club ya resolvió; dos eran
día/mes invertido (`ALONSO MUNOZ`, `VICENTE NILO`) y no siguen un patrón
sistemático. Residuo no verificable: 113 de 299 tienen día y mes ≤ 12, así que
una inversión idéntica en ambos archivos no se detectaría. No hay indicio de que
exista.

### 1.2 Nombres de wellness sin respaldo en el maestro

El formulario de check-in es **texto libre**: quien lo completa tipea el nombre y
nada lo valida. Caso encontrado: `JOHN LAUREN` (160 apariciones, sólo en
check-ins) contra `JOHN LAURENT` (765, en el maestro, 2009-03-14, U18).

**Pendiente:** cruzar TODOS los nombres de check-in contra el maestro y producir
la lista de etiquetas sin jugador. Sirve para dos cosas: que el club limpie la
planilla, y que carguemos los alias que SLAB necesita para emparejar.

### 1.3 Huecos del maestro — 20 filas, 13 resueltas en local

De las 16 filas sin fecha de nacimiento y las 4 con `#N/A`, sólo **7 requieren
al club**. Las otras 13 se resuelven con las hojas de plantel del propio archivo:

| Caso | Filas | Resolución |
|---|---|---|
| Categoría `#N/A` | 4 | **U11** (Serie 2015). Confirmado dos veces: hoja `U11` + cohorte 2015 → Sub 11 en 2026 |
| Fila duplicada de un chico que sí tiene fecha | 7 | Copiar su fecha. Arellano/Campos/de Araya/Mandiola → U13, Díaz/Acevedo → U14, Pérez → U15 |
| Jugador **a prueba**, no del plantel | 2 | `LUCAS GONZALEZ`, `RENATO LOPEZ` — sólo en `REGISTRO JUGADORES A PRUEBA`. No se importan como plantel |
| Jugador real de plantel, falta la fecha | 3 | `CRISTOBAL GUERRERO` (U20), `SANTINO RIVERA` (U15), `TOMAS VALDES` (U16) → **pedir al club** |
| Sin plantel ni fecha | 4 | `DAWUD BAKHIT`, `GONZALO AHUMADA`, `JOAQUIN CAMUS`, `VICENTE MUÑOZ` → **pedir fecha y confirmar si son plantel o prueba** |

Detalle con archivo · hoja · fila: `~/Downloads/formativo_datos_faltantes.csv`.

### Criterio de salida de la fase 1

Un CSV canónico `jugador → fecha nac. → cohorte → posición` (sin columna de
categoría: se calcula) con **cero** conflictos de fecha, revisado por el club.
Las 7 filas pendientes no bloquean la importación del resto: entran con cohorte
nula y quedan listadas para completar. Sí bloquean el maturity offset de esos 7.

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

### 2.2 Sub 20: el archivo "SUB 21" va al bracket que ya existe

Decidido el 2026-09-02: **es Sub 20.** Así que la escalera de la ANFP no cambia
—sigue en 11·12·13·14·15·16·18·20·Primera— y COMET, que sólo publica
competencias "Sub 20", encaja sin traducción.

Queda una cosa por reconciliar, y no es un error: el archivo dice **CAT 07-05**
(nacidos 2005–2007) mientras `SUB-20` en SLAB tiene **43 jugadores nacidos entre
2004 y 2010**, y sus partidos 2026 los juegan 2007 (55 %), 2006 (23 %), 2008
(19 %) y 2009 (3 %).

Eso es coherente con lo que ya sabíamos: **Sub 20 es un plantel de bracket, no
una cohorte** — se arma por nivel con varias generaciones, igual que el Primer
Equipo. Por eso conserva su nombre guardado en lugar de un año, y por eso el
backfill nunca le pudo asignar `cohort_year` (33 % de año dominante, bajo el
umbral de 70 %). El 19 % de 2008 son préstamos hacia arriba.

Al importar hay que **usar el archivo como plantel declarado y no como filtro**:
un 2008 que aparece en un partido Sub 20 no es un dato malo, es un ascenso.

### 2.3 Lo que falta crear

| Qué | Cuánto | Nota |
|---|---|---|
| Categoría 2015 (Sub 11 2026) | **38 jugadores**, ninguno en SLAB | Engancha los 25 partidos desprendidos y ~69 de las 72 personas COMET sin vincular |
| U8, U9, U10 | **58 jugadores** | Se recrean (ver abajo) |
| Jugadores nuevos del maestro | del orden de 100+ | Contar exacto tras la fase 1 |

#### U8, U9 y U10: se recrean, y con menos de lo que uno supondría

Se habían borrado el 2026-08-26 por estar completamente vacías, y lo estaban.
Ahora la data entregada las respalda:

| | Jugadores | Carreras | Neuromuscular | Resistencia | Fuerza | GPS | Wellness |
|---|---|---|---|---|---|---|---|
| U8 | 17 | 34 | 16 | — | — | — | — |
| U9 | 20 | 38 | 15 | — | — | — | — |
| U10 | 21 | 48 | 27 | — | — | — | — |

**178 filas de examen** entre 2026-03-11 y 2026-07-08. Tres consecuencias:

1. **Sólo se les cuelgan dos plantillas**, Carreras y Neuromuscular. No hay una
   sola fila de Resistencia ni de Fuerza para estas tres — coherente con que esos
   tests arrancan en U12 y U13. Es exactamente para lo que sirve
   `applicable_categories`.
2. **No hay hojas de GPS** para U8–U10. La cantera chica no usa GPS.
3. **No hay archivo de wellness** tampoco (la carpeta arranca en SUB 11), así que
   su plantel sale **del maestro** y no de una `Lista Check In`. Es la única parte
   del plan donde el maestro es la única fuente de plantel.

### 2.4 Pertenencias con fechas reales

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

### 3.3 Bandas por categoría ✅ HECHO en local (2026-09-02)

Resultó **mucho más chico de lo planeado**, porque media pieza ya estaba: al
mirar el código, `AlertRule` **ya era por categoría** (tiene FK a `Category`) —
lo que faltaba es que los umbrales salieran de la regla y no del campo
compartido. `_band_evaluation` hacía:

```python
field_def = _field_definition(rule)
ranges = list((field_def or {}).get("reference_ranges") or [])
```

Así que una regla para Sub 11 y otra para Sub 20 leían **los mismos números**.

**El cambio**: una regla BAND puede traer `config["ranges"]` con sus propios
umbrales; sin eso cae a las del campo, así que **ninguna regla existente
cambia**. Cero modelos nuevos, cero migración de datos (sólo el help_text).

Se validan con el **mismo** validador que `TemplateField.reference_ranges` — si
divergieran, una banda válida en un lado sería inválida en el otro y nadie
sabría cuál manda.

Y se relajó un chequeo que ahora estorbaba: `clean()` exigía que el campo
tuviera bandas, porque sin ellas la regla nunca dispararía. Con umbrales propios
eso ya no es cierto, y seguir exigiéndolo bloqueaba justamente el caso nuevo.

El test que sostiene todo es `test_el_mismo_valor_cae_en_bandas_distintas_por_categoria`:
90 kg de RM Back Squat es "Regular" para un Sub 13 y "Muy Deficiente" para un
Sub 18, con las bandas reales de las hojas del club. Verificado que **falla sin
el arreglo** — una alerta con el umbral equivocado se ve igual que una correcta,
así que sin ese test nadie lo notaría.

⚠️ **Lo que NO cubre**: el lado de la VISUALIZACIÓN. Los gráficos siguen leyendo
`reference_ranges` del campo, así que la banda que se dibuja es la del default.
Se atacó primero la alerta porque es la que carga una decisión; el gráfico es
informativo. Queda anotado como pendiente.

#### El problema original, para referencia

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

### 3.4 El supuesto de HSR, y qué cuesta si es falso

El formativo mide HSR sobre **>20 km/h** y `gps_sesion` está etiquetado
**>19,8 km/h**. Por decisión del cliente (2026-09-02) se importan al mismo campo
tratándolos como equivalentes.

**Queda escrito como supuesto y no como hecho**, porque tiene una consecuencia
acotada pero real:

- El sesgo es **sistemático y en una sola dirección**: un umbral más alto mide
  menos distancia, así que el HSR del formativo queda algo por debajo. No es
  ruido que se promedie: siempre va para el mismo lado.
- **Dentro de una misma fuente no molesta.** El panel de contexto físico de
  `/desarrollo` compara a un jugador contra el plantel con el que jugó **en los
  mismos partidos**, y esas filas vienen del mismo archivo: mismo umbral en los
  dos lados de la comparación.
- **Donde sí molesta es al cruzar fuentes**: comparar el HSR de un juvenil
  (archivo del club, >20) contra el del plantel profesional (Catapult, >19,8)
  subestima al juvenil. Y ése es justamente el análisis que el club pidió —
  "cómo le va al que sube".

Si más adelante se confirma que la diferencia importa, la salida es separar el
campo o anotar la procedencia en el resultado; **no** re-etiquetar en silencio.
Mientras tanto la etiqueta del campo sigue diciendo >19,8, que para los datos
del formativo es una aproximación.

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
| **1** | ✅ Puerta de calidad: CSV canónico, conflictos resueltos, alias listados | 0 conflictos, 0 `#N/A`, revisado por el club |
| **2** | ✅ Categorías faltantes + jugadores del maestro + alias | Todo nombre del maestro resuelve a un jugador |
| **3** | ✅ Pertenencias con fecha real de primera aparición | 469 de 479 con spell; 394 con fecha del dato del club, no estimada |
| **4** | ✅ Plantillas (5) + 2 campos de pulso + `applicable_categories` | Carreras/Neuromuscular en 12 categorías, Fuerza/Resistencia en 7 (Sub 13+), GPS en 10 (Sub 11+) |
| **5** | ✅ Bandas por categoría | Un Sub 11 y un Sub 20 con el mismo valor caen en bandas distintas |
| **6** | ✅ Importar evaluaciones físicas | 5061 resultados en 396 jugadores, 2024-01-22 → 2026-07-15; conteos verificados contra la planilla |
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

---

## 6. La fase 3 no era lo que el plan suponía

El plan pedía "spells de pertenencia desde el histórico", esperando que un
jugador que cambió de categoría mostrara dos spells. **Con categorías por
cohorte ese caso casi no existe**: un Serie 2013 es Serie 2013 para siempre. Lo
que se mueve es el bracket, y eso ya lo modela `TeamSeason` por temporada.

Los libros del club lo muestran sin ambigüedad: **248 de 501 jugadores**
invierten a una cohorte que cambia entre temporadas —`CLEMENTE SALAS` da 2006,
2007 y 2008 entre 2024 y 2026— no porque se haya movido, sino porque estuvo
tres años en Sub 18 mientras su cohorte envejecía debajo. Leer eso como tres
pertenencias inventaría traspasos que nunca ocurrieron.

Lo que sí faltaba, y es lo que se hizo:

- **159 pertenencias** para los jugadores que la fase 2 creó y no tenían
  ninguna.
- **235 fechas reemplazadas por la primera aparición real** en los datos del
  club. 219 de ellas venían de `backfill_cohorts`, que usaba la fecha del
  primer *partido*; un entrenamiento anterior prueba que el jugador ya estaba,
  así que la fecha del partido era sólo lo más antiguo que ese comando veía.
  `since` es una cota inferior, no un hecho en disputa.
- **56 citaciones inactivas** para quienes jugaron sobre su serie en 2026.
  Inactivas a propósito: `active=True` ensancha el acceso a datos de menores
  (`api.scoping.scope_players`), y concederlo desde una planilla es un cambio
  de permisos, no una importación. Las 56 activas que ya existían no se tocan.

Seis jugadores del maestro quedan sin pertenencia porque no aparecen en ninguna
sesión fechada. Sin fecha honesta, no se les fabrica una.

### Límite conocido de `implied_cohort`

La inversión etiqueta→cohorte sólo es válida cuando el jugador juega su propio
peldaño. En Sub 18 y Sub 20 no hay a dónde subir, así que un jugador que se
queda ahí varias temporadas invierte a una cohorte móvil. Se usa únicamente
para los 7 jugadores sin fecha de nacimiento en ninguna parte, y su estimación
va marcada como tal; si cae en los brackets altos hay que tratarla como
desconocida.

---

## 7. Fase 4 — lo que el dato corrigió del diseño

Dos suposiciones del §3.1 no sobrevivieron a mirar las columnas:

- **`FUERZA` no tiene 3 columnas sino 72.** Es un perfil carga-velocidad: para
  cada carga de 20 a 160 kg, tres intentos en m/s más el mejor. Esparso —1297
  de 1979 filas no traen ninguna celda de carga— así que el resumen (1RM,
  última carga, %RM, FR) es lo que está en todas las filas y la curva es
  opcional. Se importa el mejor por carga y se descartan los tres intentos,
  que son borrador: el club ya calcula el mejor y es el que usa.
- **Resistencia son dos protocolos, no uno.** El test de palier (862 filas,
  Course Navette) y los 1000 metros (116 filas) no comparten ni una columna
  útil, y no se pueden graficar juntos. Son dos plantillas.

`FUERZA` y `PRESS DE BANCO` sí se unificaron: misma estructura, distinto
ejercicio, así que el ejercicio es un campo `categorical` y no una plantilla
duplicada.

### Fórmulas verificadas contra las celdas del club

Cada una se comprobó antes de codificarla, porque una fórmula casi correcta
devuelve un número plausible que nadie recalcula a mano:

| Campo | Fórmula | Verificación |
|---|---|---|
| `metros` (palier) | `palier × 40` | exacta en 862/862 |
| `vo2_max` (palier) | `0.336 × palier + 36.4` | exacta en 862/862 |
| `%RM` | `última_carga ÷ 1RM × 100` | exacta en 729/729 |
| `FR` | `1RM ÷ peso corporal` | falla en 2/682, ambos tipeos de celda |
| `vam` (1000 m) | `metros ÷ tiempo` | exacta |

Dos columnas se **importan** en vez de calcularse: `vam` del test de palier es
un lookup de 91 filas (hoja `VAM`) que el motor de fórmulas no puede hacer, y
`vo2_max` del 1000 m no es función sólo del tiempo (240 s da 48,3 y 251 s da
51,1). Inventarles una fórmula reescribiría los números del club en silencio.

⚠️ Consecuencia del `vam` importado: es un valor histórico. Si el club revisa
su tabla, las filas viejas conservan el valor viejo.

### El bug que casi dejó el GPS juvenil sin importar

`applicable_categories` es la puerta que lee la API. La primera versión filtró
las categorías con `departments=dept`, copiando el patrón de
`seed_fatiga_central` — y en este club **sólo `Primer Equipo` tiene
departamentos vinculados**, así que las cinco plantillas no se le ofrecían a
nadie. Además `gps_sesion` y `gps_partido` aplicaban únicamente a Primer
Equipo, o sea que los ~13.000 registros juveniles de GPS no habrían tenido
plantilla donde caer y la importación habría reportado "0 emparejados" sin
explicar por qué.

⚠️ **`seed_fatiga_central` sigue con ese filtro**, así que la plantilla de
Fatiga Central probablemente sólo aplica a Primer Equipo en este club. No se
tocó acá porque es de otro departamento; queda anotado.

⚠️ **Ninguna categoría formativa tiene `Category.departments` poblado** (ni las
que ya existían). Eso no bloquea los exámenes —`applicable_categories` es la
puerta— pero sí vacía la lista de departamentos del reporte diario para esas
categorías. Queda anotado, sin tocar, porque afecta superficies fuera de esta
fase.

### Tercera vez que el techo de `Bracket.for_age` hay que frenarlo

Devuelve Sub 11 para un chico de 8 años, correcto para su pregunta ("¿cuál es
el peldaño más bajo que lo admite?") y equivocado para ésta. Sin guard, las
Series 2016–2018 pasaban un corte de "Sub 11 y más" y quedaban con GPS, que
nunca corrieron. Cubierto por test en los tres lugares.

---

## 8. Fase 6 — cuatro bugs de parseo, los cuatro silenciosos

Cada uno dejaba el reporte limpio mientras perdía o corrompía datos. Van
anotados porque el archivo del club los va a volver a traer:

| Hoja | Qué pasaba | Efecto si no se detectaba |
|---|---|---|
| `CARRERAS` | La columna que nombra el test está titulada **`NEUROMUSCULAR`** — el club armó la hoja copiando la otra | 0 de 4341 filas leídas, reporte en verde |
| `PRESS DE BANCO` | Encabezado con un `FECHA` fantasma al frente: los datos arrancan en `JUGADOR` | `PESO CORPORAL` se leía de la columna de la posición |
| `FUERZA` | Las cargas no intentadas vienen en **0**, no vacías | 678 de 682 sesiones rechazadas por el piso de 0,1 m/s |
| varias | 200 filas sin fecha (119 en `PRESS DE BANCO`, 62 en `1000 METROS`) | se descartaban sin decir nada |

El corrimiento se detecta **por tipo, no por nombre de hoja**: la columna del
jugador tiene que traer texto y la de nacimiento una fecha. Así una hoja que el
club arregle (o rompa) después se maneja sin editar código.

### Qué se cargó

| Plantilla | Resultados |
|---|---|
| `carreras` | 2119 |
| `neuromuscular` | 1413 |
| `resistencia` | 853 |
| `fuerza` | 666 |
| `resistencia_1000m` | 10 |

**5061 resultados, 396 jugadores, del 2024-01-22 al 2026-07-15.** Verificado
contra la planilla: `t10_best` en 1297 resultados contra 1338 filas T10 en el
origen, COD 870 contra 876, CMJ 1293 contra 1322. La diferencia son los 16
nombres que no resuelven a un jugador.

Re-correrlo crea 0: el dedup va por `result_data["origen_id"]`.

### Rango: se descarta el valor, no la sesión

7 valores imposibles — `v_60kg=45992` (un número de fecha en una columna de
velocidad), un T30 de 2,68 s (30 m a 40 km/h), un tiro a 4 km/h. Se descarta el
**valor** y la fila se carga igual, por dos razones: un día de test trae varias
pruebas y una celda mala no es razón para perder el T10 de ese día, y como
`best` es un MÍNIMO en los tests de tiempo, dejar el valor imposiblemente bajo
lo haría ganar y sería la cifra que muestra el gráfico.

### Procedencia

Cada fila lleva `origen`, `origen_hoja` y `origen_id` en `result_data`,
siguiendo el patrón que ya usa Catapult con `catapult_activity_id`. Sin eso,
una vez cargadas nadie puede distinguir un HSR de la planilla del club (>20
km/h) de uno de Catapult (>19,8) — y comparar los dos es exactamente lo que el
club pidió.

### Para el club

- **200 filas sin fecha**: las 119 de `PRESS DE BANCO` (la hoja no tiene
  columna de fecha) y 62 de `1000 METROS`.
- **16 nombres sin jugador**, entre ellos typos (`DAMINA SOLIS`) y filas con
  sólo el apellido (`OLIVEROS`, `CORNEJO`).
- **7 celdas con valores imposibles**, listadas en el reporte del importador.
