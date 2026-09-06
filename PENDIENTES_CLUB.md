# SLAB · Formativo — datos que necesitamos del club

**Fecha:** 6 de septiembre de 2026
**Estado de la integración:** completa y en producción.

La integración del formativo está terminada y funcionando. En SLAB hay hoy
**480 jugadores en 16 categorías** y **134.976 registros** cargados: evaluaciones
físicas, GPS de partido y entrenamiento, los Check-IN y Check-OUT de wellness
desde febrero de 2024, y las fichas oficiales de partido de la ANFP. Los
formularios y planillas se sincronizan solos cada hora.

Los cuatro puntos de abajo son los únicos que **no podemos resolver nosotros**,
porque dependen de información que sólo el club tiene. **Ninguno bloquea el uso
de la plataforma.**

En los puntos 1 y 4 les proponemos una respuesta con la evidencia que la
sustenta: en la mayoría de los casos alcanza con **confirmar o corregir**.

---

## 1 · Dos nombres del wellness que corresponden a dos jugadores cada uno

**Registros afectados: 739**

Los formularios identifican al jugador por un campo de texto libre (`JUGADOR`).
Hay dos nombres que corresponden a **dos jugadores distintos**, y no importamos
esas respuestas: atribuirle a un jugador el bienestar de otro es peor que no
tener el dato.

La buena noticia es que **la mayoría ya quedó resuelta sola**. Como cada
documento declara su categoría en el título, pudimos atribuir las respuestas de
los documentos cuya categoría coincide con uno solo de los dos.

### `DAVID GUZMAN` — 1675 respuestas en total

| Documento | Respuestas | Período | Atribución |
|---|---|---|---|
| SUB 15 · CAT 11 | 802 | ene-2025 → hoy | ✅ David Guzmán **Bascur** (2011) |
| SUB 18 · CAT 08-07 | 406 | ene-2025 → jul-2026 | ✅ David Guzmán **Vivanco** (2008) |
| **SUB 14 · CAT 12** | **392** | **todo 2024** | ❓ **pendiente** |
| **SUB 21 · CAT 07-05** | **75** | **jul → sep 2026** | ❓ **pendiente** |

**Lo que proponemos**, por la edad que cada uno tenía en esas fechas:

- Las **392 de SUB 14, todas de 2024** → **Bascur**. En 2024 tenía 13 años, que
  es la edad de esa serie. Vivanco tenía 16.
- Las **75 de SUB 21, de julio a septiembre de 2026** → **Vivanco**. Hoy tiene
  18 y jugar en la serie superior es habitual. Bascur tiene 15.

### `FRANCO CÁCERES` — 867 respuestas en total

| Documento | Respuestas | Período | Atribución |
|---|---|---|---|
| SUB 18 · CAT 08-07 | 366 | ene-2025 → hoy | ✅ Franco Cáceres **Godoy** (2007) |
| SUB 16 · CAT 10 | 229 | ene-2025 → hoy | ✅ Franco Cáceres **Pérez** (2010) |
| **SUB 15 · CAT 11** | **272** | **todo 2024** | ❓ **pendiente** |

**Lo que proponemos**: las 272 → **Pérez**. En 2024 tenía 14 años, la edad de
esa serie. Godoy tenía 17.

### Qué necesitamos

1. **Confirmar o corregir** las tres atribuciones propuestas.
2. **La solución de fondo, para que no vuelva a pasar:** que en el desplegable
   de cada formulario el nombre quede único, agregando el segundo apellido —
   `GUZMAN BASCUR DAVID` y `GUZMAN VIVANCO DAVID`. Con eso las respuestas
   nuevas entran solas.

---

## 2 · Cuatro nombres que llenan wellness y no están en el plantel

**Registros afectados: 201**

Estos nombres llenan formularios hoy pero no existen en la planilla de plantel
que nos entregaron:

| Nombre en el formulario | Respuestas | Período | Documento |
|---|---|---|---|
| `JOHN CORTES` | 166 | 19-01-2026 → 05-09-2026 | SUB 21 · CAT 07-05 |
| `CHRISTIAN ROZAS` | 22 | 17-02-2026 → 18-06-2026 | SUB 14 · CAT 12 |
| `NICOLAS MARCANO` | 10 | 10-08-2026 → 04-09-2026 | SUB 12 · CAT 14 |
| `Opción 35` | 3 | 22-07-2026 → 27-07-2026 | SUB 13 · CAT 13 |

**`Opción 35`** parece un valor por defecto del formulario que alguien eligió
sin querer. Si es así, lo descartamos.

⚠️ **`JOHN CORTES`**: en el plantel de Primer Equipo hay un **Jhon Cortés
Gallego**. Puede ser la misma persona escrita distinto —y llenando el formulario
de SUB 21— o dos personas. No lo asumimos.

### Qué necesitamos

De cada uno: **nombre completo, fecha de nacimiento y categoría**. Con eso los
creamos y su historial entra completo.

Si alguno ya está en el plantel con el nombre escrito de otra forma (el caso de
`JOHN CORTES`), indicarlo y lo unificamos sin crear un duplicado.

> **Nota aparte:** hay otros **57 nombres** sin correspondencia, con **5.557
> respuestas** entre todos. Ninguno tiene actividad desde junio de 2026 y la
> mayoría dejó de responder durante 2024: son jugadores que ya no están en el
> club. No hacemos nada con ellos salvo que ustedes quieran conservar su
> historial, en cuyo caso los creamos como inactivos. Díganlo y lo hacemos.

---

## 3 · El umbral de hidratación

**Registros afectados: 46.551** — se ven en los gráficos, pero **sin alarma**.

El formulario pregunta "Señala tu nivel de hidratación" y las respuestas son
**litros de agua al día**, no una escala de 1 a 5. Lo detectamos midiendo:

| Litros | Respuestas | % |
|---|---|---|
| 1 | 3.865 | 8,3 % |
| **2** | **21.725** | **46,7 %** |
| **3** | **14.350** | **30,8 %** |
| 4 | 3.601 | 7,7 % |
| 5 | 1.536 | 3,3 % |
| 6 a 9 | 1.474 | 3,2 % |

Al principio lo cargamos como escala 1–5 y el sistema marcó **el 55 % de las
respuestas del plantel como críticas**: 284 alertas falsas que tapaban las
reales. Por eso lo dejamos **sin alarma** hasta que ustedes definan el criterio.

### Qué necesitamos

Del cuerpo médico: **desde cuántos litros hacia abajo es preocupante**, y si hay
un nivel intermedio de aviso. Por ejemplo:

> «Menos de 2 L = crítico · 2 L = aviso · 3 L o más = normal»

Si el criterio cambia por edad —un Sub 11 no toma lo mismo que un Sub 20—,
indíquenlo por serie y lo configuramos así.

**Las demás escalas ya están configuradas** con el criterio **1–2 crítico ·
3 aviso · 4–5 normal**, para calidad de sueño, nivel de fatiga, nivel de estrés,
estado de ánimo y daño muscular. Si quieren mover esos umbrales, se editan desde
SLAB sin intervención nuestra; les mostramos cómo cuando quieran.

> **Verificamos la dirección de la escala** antes de configurar nada: en su
> formulario **5 es siempre lo mejor**, también en fatiga, estrés y daño
> muscular. Lo confirmamos contra su propia columna `SUMA`, que es la suma
> directa de los cinco ítems: 25.146 respuestas coinciden exactamente. Si en
> algún momento cambian el sentido de una pregunta, avísennos: es un error
> invisible, porque todos los números siguen en rango.

---

## 4 · Siete jugadores de las planillas ANFP que no reconocemos

**Fichas de partido afectadas: 72**

La ficha oficial de la ANFP (COMET) trae para cada jugador un `personId`,
identificador **estable y permanente**. Vinculamos 255 jugadores
automáticamente; quedan **siete personas** cuyo nombre no coincide con nadie del
plantel. Sus 72 apariciones —minutos, tarjetas, goles— quedan sin cargar.

Se vincula **una sola vez por jugador**: el `personId` no cambia, así que una vez
resuelto queda resuelto para siempre.

| Nombre en COMET | `personId` | Dorsal | Qué proponemos |
|---|---|---|---|
| `ABBOTT FRANCISCO` | 8951811 | 15 | Sin candidato en el plantel — ¿es del club? |
| `GUZMAN DAVID` | 5162525 | 17 | ⚠️ Dos posibles: **David Guzman Bascur** (Serie 2011, nac. 2011) · **David Guzman Vivanco** (Serie 2008, nac. 2008) |
| `MANDIOLA THOMAS` | 7732897 | 4 | Sin candidato en el plantel — ¿es del club? |
| `MONTECINO ROBERTO` | 7596128 | 17 | Sin candidato en el plantel — ¿es del club? |
| `MORALES ALONSO` | 8415983 | 16 | ⚠️ Dos posibles: **Alonso Morales** (Serie 2014, nac. 2014) · **Alonso Morales Espinoza** (Serie 2016, nac. 2016) |
| `RIVERO RAUL` | 1781663 | 9 | Sin candidato en el plantel — ¿es del club? |
| `VILLAROEL MATEO` | 7278560 | 4 | Sin candidato en el plantel — ¿es del club? |

**Cinco de los siete no tienen ningún candidato** en el plantel: `ABBOTT
FRANCISCO`, `MANDIOLA THOMAS`, `MONTECINO ROBERTO`, `RIVERO RAUL` y `VILLAROEL
MATEO`. Lo más probable es que sean jugadores a prueba, refuerzos puntuales o
cargas erróneas de la ANFP — pero si alguno es del club y nos falta en la
planilla, díganlo y lo creamos.

**Los otros dos tienen dos candidatos cada uno** y no elegimos: son homónimos
reales del plantel, y atribuirle los partidos de uno al otro es un error que
después nadie detecta. Necesitamos que nos digan cuál es.

> Cómo se resuelve, del lado nuestro: cada `personId` se vincula una sola vez en
> SLAB (Administración → «Vínculos jugador COMET»). Desde ese momento todas sus
> fichas —las 72 pendientes y las futuras— se cargan solas.

### Qué necesitamos

Para cada uno: **a qué jugador del plantel corresponde**, o **que no es del
club** (puede ser un jugador a prueba, un refuerzo puntual, o un error de carga
de la ANFP).

Donde proponemos un candidato, alcanza con confirmar o corregir.

---

## Resumen

| Punto | Registros | Qué necesitamos | De quién |
|---|---|---|---|
| 1 · Homónimos del wellness | 739 | Confirmar 3 atribuciones + desambiguar el nombre en los formularios | Coordinación del formativo |
| 2 · Cuatro nombres nuevos | 201 | Nombre completo, fecha de nacimiento y categoría | Coordinación del formativo |
| 3 · Umbral de hidratación | 46.551 | Desde cuántos litros es preocupante | Cuerpo médico |
| 4 · Siete `personId` de COMET | 72 | A qué jugador corresponde cada uno | Coordinación del formativo |

**Nada de esto bloquea el uso de SLAB.** Son registros que ya están cargados
pero incompletos —sin alarma, sin atribuir o sin importar— y que con estas
respuestas quedan cerrados.
