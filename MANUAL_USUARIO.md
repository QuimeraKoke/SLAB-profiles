# Manual de uso — Panel de administración SLAB

Esta guía está pensada para personas **no técnicas** que necesitan
configurar y mantener la plataforma SLAB usando solamente el panel
de administración. No vas a tener que abrir terminales ni escribir
código en ningún momento.

> ¿Eres técnico? Hay un manual paralelo (`MANUAL_ADMIN.md`) con la
> versión completa que cubre comandos del servidor, despliegue y
> resolución de problemas avanzados.

---

## Índice

1. [Bienvenida y cómo leer este manual](#1-bienvenida-y-cómo-leer-este-manual)
2. [Conceptos básicos en lenguaje simple](#2-conceptos-básicos-en-lenguaje-simple)
3. [Cómo entrar al panel](#3-cómo-entrar-al-panel)
4. [Paso 1 — Crear el club](#4-paso-1--crear-el-club)
5. [Paso 2 — Crear los departamentos](#5-paso-2--crear-los-departamentos)
6. [Paso 3 — Crear las categorías](#6-paso-3--crear-las-categorías)
7. [Paso 4 — Crear las posiciones](#7-paso-4--crear-las-posiciones)
8. [Paso 5 — Cargar los jugadores](#8-paso-5--cargar-los-jugadores)
9. [Paso 6 — Crear los usuarios del staff](#9-paso-6--crear-los-usuarios-del-staff)
10. [Paso 7 — Configurar los permieres de cada usuario](#10-paso-7--configurar-los-permisos-de-cada-usuario)
11. [Paso 8 — Crear plantillas de exámenes](#11-paso-8--crear-plantillas-de-exámenes)
12. [Paso 9 — Configurar visualizaciones (dashboards)](#12-paso-9--configurar-visualizaciones-dashboards)
13. [Paso 10 — Configurar metas y alertas automáticas](#13-paso-10--configurar-metas-y-alertas-automáticas)
14. [Tareas frecuentes](#14-tareas-frecuentes)
15. [Preguntas frecuentes](#15-preguntas-frecuentes)
16. [Lista de verificación final](#16-lista-de-verificación-final)

---

## 1. Bienvenida y cómo leer este manual

### Qué vas a poder hacer al terminar

- Crear un club desde cero.
- Configurar departamentos, categorías y posiciones.
- Cargar el plantel de jugadores.
- Crear cuentas para médicos, físicos, técnicos y nutricionistas.
- Definir qué puede ver cada uno.
- Diseñar plantillas de exámenes (formularios) sin programar.
- Armar dashboards con gráficos y tablas.
- Configurar alertas automáticas.

### Convenciones de la guía

- En **negrita** aparecen los textos exactos que verás en pantalla.
- Las flechas `→` indican una secuencia de clics. Por ejemplo:
  **Inicio → Core → Clubs → Add club** significa "primero haz clic
  en Core, luego en Clubs, luego en Add club".
- Los recuadros con 💡 son **consejos** que ayudan pero no son
  obligatorios.
- Los recuadros con ⚠️ son **advertencias importantes** que conviene
  no saltar.

### Estimación de tiempo

Si sigues la guía en orden, puedes tener todo listo en **2 a 3 horas**
para un club nuevo con un plantel completo.

---

## 2. Conceptos básicos en lenguaje simple

Antes de hacer clic en nada, conviene tener claros estos siete
conceptos. Los vamos a usar todo el tiempo.

### Club

El **club** es el equipo o institución completa. Por ejemplo
"Universidad de Chile" o "SLAB". Todo lo demás (jugadores, staff,
plantillas) cuelga de un club.

### Categoría

Una **categoría** es un plantel dentro del club. Ejemplos: "Primer
Equipo", "Sub-20", "Femenino". Un club puede tener muchas categorías;
cada una con sus propios jugadores y staff.

### Departamento

Un **departamento** es un área de trabajo: Médico, Físico, Táctico,
Nutricional. Cada departamento tiene su propio staff, sus propias
plantillas y sus propias visualizaciones.

> 💡 No confundir con departamentos en sentido administrativo. Aquí
> "departamento" es funcional: un grupo de profesionales que trabaja
> sobre un mismo aspecto de la salud o el rendimiento del jugador.

### Posición

La **posición** es el rol del jugador en cancha: arquero, defensor,
mediocampista, delantero. Cada club define su propia lista.

### Jugador

Cada **jugador** pertenece a una categoría y, opcionalmente, ocupa
una posición.

### Usuario

Un **usuario** es una persona que puede ingresar al sistema con
email y contraseña. No todos los usuarios ven lo mismo: lo que ven
depende de sus **permisos**.

### Plantilla de examen

Una **plantilla** es un formulario configurable. Por ejemplo:
- "Pentacompartimental" tiene campos para peso, talla, pliegues
  cutáneos y calcula automáticamente el IMC y la masa adiposa.
- "Lesiones" tiene campos para tipo de lesión, parte del cuerpo,
  severidad y fecha esperada de retorno.

Tú puedes crear tantas plantillas como quieras y configurar qué
campos tiene cada una.

### Resultado / Toma

Un **resultado** es una vez que se llenó una plantilla para un
jugador en una fecha. Por ejemplo: "el martes pasado, Juan registró
peso 72 kg, IMC 21.5". Cada plantilla puede tener cientos de
resultados a lo largo del tiempo.

---

## 3. Cómo entrar al panel

### Ingreso

1. Abre en el navegador la URL del panel:
   `https://<tu-backend>.up.railway.app/admin/`
   (Tu equipo técnico te dio esta dirección.)
2. Ingresa tu **usuario** y **contraseña**.
3. Vas a ver el listado de "Site administration" con todas las
   secciones.

### Primer impresión del panel

El panel está organizado en **aplicaciones** (Apps). Las que vamos
a usar más son:

| Aplicación                           | Para qué sirve                          |
|--------------------------------------|------------------------------------------|
| **Authentication and Authorization** | Crear usuarios y contraseñas             |
| **Core**                             | Club, departamentos, categorías, posiciones, jugadores, permieres |
| **Exams**                            | Plantillas de exámenes y resultados      |
| **Dashboards**                       | Visualizaciones (dashboards y reportes)  |
| **Goals**                            | Metas y alertas automáticas              |
| **Events**                           | Citaciones y eventos del jugador         |

### Botones que vas a usar siempre

- **Add** (verde, arriba a la derecha): crear un registro nuevo.
- **Save** (abajo): guardar los cambios.
- **Save and continue editing**: guardar pero quedarse en la pantalla
  para seguir editando.
- **Save and add another**: guardar y empezar uno nuevo del mismo
  tipo.
- **Delete**: borrar (¡sin vuelta atrás!).
- **History**: ver qué cambió y quién lo modificó.

> ⚠️ El panel está en inglés en algunos textos del sistema, pero
> los datos y las descripciones que escribimos están en español.
> Acostúmbrate a la mezcla.

---

## 4. Paso 1 — Crear el club

> 💡 Si ya hay un club creado, puedes saltar este paso e ir al
> siguiente.

### Pasos

1. En la pantalla principal, haz clic en **Core → Clubs**.
2. Arriba a la derecha, **Add club** (botón verde con un +).
3. Completar:
   - **Name**: el nombre completo del club. Ejemplo:
     `Universidad de Chile`.
4. **Save**.

### Qué hacer después

Quédate en la página del club recién creado. Vamos a usarla de
referencia para los siguientes pasos.

---

## 5. Paso 2 — Crear los departamentos

Cada club tiene sus propios departamentos. Lo recomendado para un
demo es crear los cuatro departamentos estándar.

### Pasos

1. **Core → Departments → Add department**.
2. Completar:
   - **Club**: elegir el club que creaste recién.
   - **Slug**: un identificador corto, sin acentos, en minúsculas.
     Sugerencias:
     - `medico` para Médico
     - `fisico` para Físico
     - `tactico` para Táctico
     - `nutricional` para Nutricional
     - `psicosocial` para Psicosocial (opcional)
   - **Name**: el nombre visible, este sí con acentos. Ejemplo:
     `Médico`.
3. **Save and add another** y repetir hasta tener los 4 (o 5)
   departamentos.

### Cómo deberían quedar

Una vez listos, en **Core → Departments** vas a ver una tabla
parecida a:

| Name        | Slug         | Club                  |
|-------------|--------------|------------------------|
| Médico      | medico       | Universidad de Chile  |
| Físico      | fisico       | Universidad de Chile  |
| Táctico     | tactico      | Universidad de Chile  |
| Nutricional | nutricional  | Universidad de Chile  |

> ⚠️ El **slug** no se debe cambiar después de crearlo. Otros
> sistemas dentro de la app lo usan como identificador interno.

---

## 6. Paso 3 — Crear las categorías

Las categorías son los **planteles** dentro del club: Primer
Equipo, Sub-20, Femenino, etc.

### Pasos

1. **Core → Categories → Add category**.
2. Completar:
   - **Club**: el club.
   - **Name**: por ejemplo `Primer Equipo`.
   - **Departments**: marca **todos los departamentos** que aplican
     a esta categoría. Si dejas alguno sin marcar, los jugadores de
     esta categoría no van a tener esa pestaña en su perfil.
3. **Save**.
4. Repetir para cada categoría que tenga el club.

### Tip importante

> 💡 Si más adelante quieres agregar Psicosocial al Primer Equipo,
> vuelve a esta categoría, marca Psicosocial en **Departments**, y
> guarda. La pestaña aparece automáticamente en los perfiles.

---

## 7. Paso 4 — Crear las posiciones

Cada club define su propia lista de posiciones. Sugerencia para
fútbol:

| Posición       | Abreviación | Orden |
|----------------|-------------|-------|
| Arquero        | POR         | 1     |
| Defensor       | DF          | 2     |
| Mediocampista  | MC          | 3     |
| Delantero      | DEL         | 4     |

### Pasos

1. **Core → Positions → Add position**.
2. Completar:
   - **Club**: el club.
   - **Name**: por ejemplo `Arquero`.
   - **Abbreviation**: por ejemplo `POR`.
   - **Sort order**: número entero. Empezamos en 1 para que el
     arquero aparezca primero, después 2 para defensor, etc.
3. **Save and add another** y repetir.

> 💡 Las abreviaciones son las que aparecen en la "Vista de campo"
> del sistema, así que conviene mantenerlas cortas (3 letras).

---

## 8. Paso 5 — Cargar los jugadores

Ahora cargamos el plantel.

### Paeres por cada jugador

1. **Core → Players → Add player**.
2. Completar:
   - **Category**: la categoría a la que pertenece (ej. Primer
     Equipo).
   - **Position**: su posición principal (ej. Mediocampista). Es
     opcional.
   - **First name**: nombre.
   - **Last name**: apellido.
   - **Date of birth**: fecha de nacimiento. La edad se calcula
     sola.
   - **Sex**: Masculino / Femenino. Algunos cálculos clínicos lo
     usan.
   - **Nationality**: ej. `Chile`. Texto libre.
   - **Jersey number**: dorsal (opcional).
   - **Is active**: dejarlo marcado. Solo desmarcar cuando un
     jugador deja el club.
3. **Save and add another** y repetir.

### Datos opcionales útiles

- **Photo**: foto del jugador. Aparece en su perfil y en la vista
  de campo.
- **Current weight kg / Current height cm**: si los completas aquí,
  eeres valores aparecen como base hasta que se cargue el primer
  pentacompartimental. Después se actualizan automáticamente.

> ⚠️ Si tienes una planilla con muchos jugadores, pídele a tu
> equipo técnico que los importe en lote. Cargar 30 jugadores a
> mano lleva ~45 minutos.

---

## 9. Paso 6 — Crear los usuarios del staff

Ahora damos de alta a las personas que van a usar la app: médicos,
físicos, técnicos, nutricionistas.

### Pasos

1. **Authentication and Authorization → Users → Add user**.
2. Completar **todos los campos del formulario** (son obligatorios):
   - **Username**: nombre de usuario interno. Sugerencia:
     `nombre.apellido` o el email completo.
   - **Nombre** (First name).
   - **Apellido** (Last name).
   - **Email**: el login en la app web es por email, no por username.
   - **Password**: una contraseña inicial. El usuario la puede
     cambiar después.
   - **Password confirmation**: la misma contraseña.
3. **Save**.

> 💡 Si dejas vacío alguno de nombre, apellido o email, el formulario
> te bloquea con un mensaje rojo. Esta validación está activa para que
> el nombre del usuario aparezca correctamente en la barra lateral de
> la app web (y para que pueda ingresar — el login es por email).

4. Te lleva a la página de edición. **Ajustar opcionalmente**:
   - **Active**: dejarlo marcado.
   - **Staff status**: marcar **solo si** el usuario también va a
     usar este panel de administración. Para un médico de a pie
     que solo usa la app web, dejar **desmarcado**.
   - **Superuser status**: dejar **desmarcado** salvo que sea otro
     administrador como tú.
5. **Save**.

### Tabla de roles típicos

| Rol del staff             | Staff status | Superuser status |
|---------------------------|:------------:|:----------------:|
| Administrador del sistema | ✓            | ✓                |
| DT con acceso al admin    | ✓            | ✗                |
| Médico (solo app web)     | ✗            | ✗                |
| Físico (solo app web)     | ✗            | ✗                |
| Nutricionista             | ✗            | ✗                |

> 💡 Recomendado: tener **dos** superusuarios distintos por las
> dudas (tú + un backup). No usar la cuenta personal como única
> vía de acceso.

---

## 10. Paso 7 — Configurar los permieres de cada usuario

Crear el usuario no le da acceso a nada todavía. Hay que decirle al
sistema **qué club, qué categorías y qué departamentos** puede ver.

Eso se hace con un **Staff membership**.

### Pasos

1. **Core → Staff memberships → Add staff membership**.
2. Completar:
   - **User**: elige el usuario que creaste.
   - **Club**: el club al que pertenece.
   - **All categories**: marcalo si esta persona ve **todas** las
     categorías del club. Por ejemplo, el médico de cabecera del
     club ve Primer Equipo + Sub-20 + Femenino.
   - **Categories**: si **NO** marcaste "All categories", elige aquí
     las categorías específicas. Si marcaste "All", esta lista se
     ignora.
   - **All departments**: marcalo si la persona ve **todos** los
     departamentos. Útil para el cuerpo técnico que necesita ver
     médico + físico + táctico al mismo tiempo.
   - **Departments**: si NO marcaste "All departments", elige los
     departamentos específicos.
3. **Save**.

### Ejemplos prácticos

**Médico del Primer Equipo** (solo ve médico, solo ve Primer Equipo):
- All categories: ❌
- Categories: Primer Equipo
- All departments: ❌
- Departments: Médico

**Físico de todas las categorías**:
- All categories: ✓
- Categories: (se ignora)
- All departments: ❌
- Departments: Físico

**Director técnico**:
- All categories: ✓
- All departments: ✓

### Cómo verificar que funcionó

Pídele al usuario que ingrese a la app web (`/login`). Debería ver
solo lo que le permitiste. Si entra y se queda en la pantalla de
login, lo más probable es que falte el email en su usuario o el
**Staff membership** no se guardó.

### 10.1 ¿Editor o Solo Lectura? — Grupos de permisos

Lo que vimos arriba (Staff Membership) controla **qué datos ve** el
usuario. Aparte de eso, hay un segundo control: **qué acciones puede
hacer** sobre eeres datos. Para eso se usan los **grupos de Django**.

Hay dos grupos pre-creados:

| Grupo | Qué permite |
|---|---|
| **Editor** | Crear, editar y borrar resultados de exámenes, lesiones, eventos, partidos, jugadores, objetivos, adjuntos. |
| **Solo Lectura** | Solo ver. No puede agregar / editar / borrar nada. |

Las dos capas se combinan así:

| Usuario | Staff Membership (datos) | Grupo (acciones) | Qué pasa |
|---|---|---|---|
| Dr. González | Médico, Primer Equipo | Editor | Ve Médico de Primer Equipo, edita libremente. |
| Dr. Pérez | Médico, Primer Equipo | Solo Lectura | Ve lo mismo pero **no** ve botones de "+ Agregar", "Editar", "Borrar". |
| Becario | Médico + Físico, Sub-20 | Solo Lectura | Lee de los dos departamentos, no toca nada. |
| DT | Todo, Primer Equipo | Editor | Edita todo en Primer Equipo. |

#### Paeres para asignar un grupo

1. **Authentication and Authorization → Users**.
2. Click en el usuario.
3. Bajar hasta la sección **"Groups"**.
4. En el cuadro de la izquierda elige **Editor** o **Solo Lectura** y
   haz click en la flecha → para moverlo al cuadro de la derecha
   ("Chosen groups").
5. **Save**.

> 💡 Un usuario solo debería tener **uno** de los dos grupos. Tener
> los dos no rompe nada (Editor incluye todo lo de Solo Lectura),
> pero es confuso. Convención: cada usuario, un grupo.

> ⚠️ Los usuarios existentes al momento de activar este sistema
> quedaron automáticamente como **Editor** para no romper el demo.
> Si quieres convertir alguno a Solo Lectura, sacalo del grupo Editor
> y agregalo al grupo Solo Lectura.

### 10.2 Ver contratos / salarios — Permiso individual

El bloque de **contrato** del perfil (con salario, bonos, fechas)
**no aparece** para los usuarios por default. Es información
sensible, así que se da uno por uno.

Para que un usuario pueda ver el bloque de contrato:

1. **Authentication and Authorization → Users → click en el usuario**.
2. Bajar hasta la sección **"User permissions"**.
3. En el cuadro de la izquierda busca **"core | contract | Can view
   contract"**. Haz click en la flecha → para moverlo a la derecha.
4. **Save**.

Si además quieres que pueda **crear / editar / borrar contratos** (no
solo verlos), agrega también:
- **"core | contract | Can add contract"**
- **"core | contract | Can change contract"**
- **"core | contract | Can delete contract"**

> 💡 Estos permieres NO se otorgan automáticamente con el grupo
> Editor — son específicos porque el cliente típico solo quiere que
> el DT y el manager de finanzas vean salarios, no todo el cuerpo
> médico.

### 10.3 Probar que los permieres funcionen

1. **Probar Solo Lectura**: ingresa con un usuario de Solo Lectura.
   En el perfil de un jugador → pestaña Médico → no debería aparecer
   la barra **"Registrar nueva entrada"**. Los íconos ✏️ y 🗑 en las
   filas de historial tampoco aparecen.
2. **Probar `view_contract`**: ingresa con un usuario que NO tenga
   ese permiso. En el perfil del jugador, en la parte superior
   derecha donde dice "CONTRATO VIGENTE": no debería aparecer ese
   bloque. Si le otorgas el permiso y refrescas, aparece.

---

## 11. Paso 8 — Crear plantillas de exámenes

Las plantillas son **formularios reutilizables** para cargar datos
de los jugadores. Por ejemplo: "Pentacompartimental",
"Hidratación", "GPS partido".

> 💡 Para un demo inicial, lo más rápido es **pedirle a tu equipo
> técnico que ejecute los seeds** que cargan plantillas
> pre-armadas. Esta sección la usás cuando quieres:
> - Crear una plantilla nueva desde cero.
> - Modificar una plantilla existente.

### 11.1 Crear la plantilla vacía

1. **Exams → Exam templates → Add exam template**.
2. Completar la sección principal:
   - **Name**: nombre visible. Ejemplo: `Hidratación`.
   - **Slug**: lo deja en blanco — el sistema lo genera solo a
     partir del nombre.
   - **Department**: a qué departamento pertenece. Ejemplo:
     `Médico`.
   - **Applicable categories**: marca las categorías que pueden
     usar esta plantilla. Si no marcas ninguna, la plantilla no
     aparece para nadie.
3. La sección **Asociación a partido** la dejas como está
   (desactivada) salvo que sea una plantilla específica de partido
   (como GPS partido).
4. La sección **Plantilla episódica** la dejas como está
   (desactivada) salvo para Lesiones.
5. **Save and continue editing**.

> ⚠️ Hasta aquí la plantilla está creada pero **no tiene campos**.
> Sin campos, el formulario está vacío.

### 11.2 Agregar campos a la plantilla

Después de guardar, abajo aparece la sección **Template fields**.
Aquí agregas cada campo del formulario.

#### Paeres por cada campo

1. Hacer clic en **Add another Template field**.
2. Completar:
   - **Sort order**: número que define el orden visual (1, 2, 3...).
   - **Key**: identificador interno, en minúsculas, sin espacios ni
     acentos. Ejemplo: `densidad_urinaria`.
   - **Label**: texto visible en el formulario. Ejemplo: `Densidad
     urinaria`.
   - **Type**: el tipo de dato. Ver tabla abajo.
   - **Unit**: la unidad de medida si corresponde. Ejemplo: `g/mL`.
   - **Group**: agrupador visual opcional. Ejemplo: `Indicadores
     clínicos`. Los campos del mismo grupo se renderizan juntos.
   - **Options**: si el tipo es "Categorical", una lista de valores
     posibles separados por comas. Ejemplo: `leve, moderada,
     severa`.
   - **Required**: marcalo si el campo es obligatorio.

#### Tipos de campo

| Type        | Para qué sirve                                | Ejemplo                          |
|-------------|-----------------------------------------------|----------------------------------|
| Number      | Valores numéricos                             | peso, distancia, rating          |
| Text        | Texto libre                                   | observaciones, motivo            |
| Date        | Una fecha                                     | fecha de inicio, fecha de retorno|
| Categorical | Lista cerrada de opciones                     | severidad, parte del cuerpo      |
| Boolean     | Sí / No                                       | requiere seguimiento             |
| Calculated  | Computado por una fórmula al guardar          | IMC, masa adiposa                |

#### Ejemplo concreto: campo "Peso"

- **Sort order**: `1`
- **Key**: `peso`
- **Label**: `Peso`
- **Type**: `Number`
- **Unit**: `kg`
- **Group**: `Antropometría`
- **Required**: ✓

#### Ejemplo: campo "Severidad"

- **Sort order**: `5`
- **Key**: `severity`
- **Label**: `Severidad`
- **Type**: `Categorical`
- **Options**: `Leve, Moderada, Severa`
- **Required**: ✓

#### Ejemplo: campo calculado "IMC"

- **Sort order**: `10`
- **Key**: `imc`
- **Label**: `IMC`
- **Type**: `Calculated`
- **Unit**: `kg/m²`
- **Formula**: `peso / (talla / 100) ^ 2`

#### Dirección del cambio (para campos numéricos)

Cuando agregas un campo numérico que va a aparecer en un dashboard
con indicador de cambio (Δ), puedes decirle al sistema **qué dirección
del cambio es buena**. Eso controla el color del delta en el Roster
Matrix:

| **Direction of good** | Significado | Ejemplo |
|---|---|---|
| **Neutro (sin opinión)** | El delta se pinta azul (sube) o naranja (baja), sin juicio | Talla, dorsal |
| **Más es mejor** | Verde si sube, rojo si baja | CMJ (altura de salto), masa muscular |
| **Menos es mejor** | Verde si baja, rojo si sube | CK (marcador de daño), peso a perder |

> 💡 Si dejas el campo en "Neutro", todo sigue funcionando como antes.
> Solo recomendable activar la opción cuando el cambio en el indicador
> tenga una interpretación clínica clara y compartida por el equipo.

#### Rangos de referencia clínica (para campos numéricos)

Cuando una métrica tiene rangos clínicos conocidos (por ejemplo CK:
normal entre 30 y 200 U/L), puedes cargarlos en el campo **`reference
ranges`** del Template Field. Eso activa dos beneficios:

1. **Hint debajo del input** mientras el médico carga el valor:
   - Si el campo está vacío, aparece un resumen compacto:
     `Rangos: Bajo <30 · Normal 30-200 · Elevado 200-400 · Severo ≥400`.
   - Mientras tipea, el resumen se reemplaza por la banda activa en
     su color: **Normal (30-200)** verde, **Severo (≥400)** rojo, etc.
2. **Borde de color en los dashboards**: cada celda numérica del
   `Roster Matrix` o de la `Comparison Table` recibe un borde con
   el color de la banda en la que cae el valor. Tooltip explicativo
   al pasar el mouse.

##### Cómo cargarlas en el admin

En el inline del campo (sección **Template fields** de la plantilla),
busca el campo **Reference ranges**. Es un editor de JSON. Pega una
lista de bandas, ejemplo CK:

```json
[
  {"label": "Bajo",    "max": 30,                    "color": "#fbbf24"},
  {"label": "Normal",  "min": 30,  "max": 200,       "color": "#16a34a"},
  {"label": "Elevado", "min": 200, "max": 400,       "color": "#f59e0b"},
  {"label": "Severo",  "min": 400,                   "color": "#dc2626"}
]
```

Reglas:

- **`label`** es obligatorio en cada banda.
- **`min`** y **`max`** son opcionales por separado, pero **al menos
  uno tiene que estar** por banda. `min` es inclusivo y `max` es
  exclusivo: un valor de exactamente `30` cae en `{min: 30, max: 200}`,
  no en `{max: 30}`.
- **`color`** es opcional. Si no lo ponés, el sistema elige uno
  automáticamente según el label ("normal" → verde, "elevado" →
  naranja, "severo" → rojo, "bajo" → amarillo).
- Las bandas tienen que estar **ordenadas y sin solaparse**. Como
  máximo una banda puede quedar abierta en cada extremo (la más
  baja sin `min`, la más alta sin `max`).
- Solo aplica a campos `Number` o `Calculated`.

> 💡 Si el JSON está mal armado, el sistema **bloquea el guardado**
> con un mensaje rojo explicando qué banda tiene el problema (label
> faltante, bandas solapadas, etc.). Es la forma más segura — no se
> guarda nada inválido.

##### Caso de uso simple: un solo "rango normal"

Si solo quieres decir "el rango normal es 30-200" (sin distinguir
"bajo" / "elevado" / "severo"), basta con una banda:

```json
[{"label": "Normal", "min": 30, "max": 200}]
```

Valores fuera del rango quedarán **sin banda activa** — el form no
muestra advertencia y los dashboards no pintan borde de color. Si
quieres que valores extremos sean visibles, agrega bandas adicionales
("Bajo" y "Alto").

> 💡 Las fórmulas pueden referenciar otros campos por su `key`.
> Para fórmulas complejas (raíces, condicionales), pide ayuda al
> equipo técnico.

> 💡 **No todos los campos numéricos necesitan bandas.** Algunos
> indicadores (como el IMC en deportistas musculados) tienen rangos
> de referencia poblacionales que no aplican bien al deporte de
> élite — un futbolista profesional típicamente sale "sobrepeso" en
> bandas OMS aunque tenga grasa baja. Cuando eso pasa, conviene
> dejar el campo **sin bandas** y agregar el indicador como dato
> informativo en una tabla, sin semáforo.

3. **Save**.

### 11.3 Marcar la plantilla como activa

Vuelve arriba en la página y guarda nuevamente con **Save**. Ahora
la plantilla aparece en los perfiles de los jugadores de las
categorías marcadas.

### 11.4 Bloqueo automático

Una vez que se carga el primer resultado de una plantilla, el sistema
la **bloquea** (`Is locked: ✓`) para proteger la integridad de los
datos históricos.

> ⚠️ Una plantilla bloqueada **no puede modificarse en su lugar**.
> Si necesitás cambiar sus campos (agregar uno nuevo, renombrar o
> eliminar uno existente, modificar las opciones de un campo
> categórico), la respuesta correcta es **crear una nueva versión**.
> Ver §11.5.

### 11.5 Crear una nueva versión de una plantilla

Imaginá que tu plantilla "Pentacompartimental" ya tiene 300
resultados cargados (y por lo tanto está bloqueada), y ahora necesitás
agregar un nuevo campo de medición. La nueva versión permite hacerlo
sin perder ni una sola toma anterior.

#### Cómo funciona, en simple

- Una plantilla tiene una **familia**. Todas las versiones
  comparten la familia.
- En todo momento, una sola versión está **activa**. Cuando los
  médicos cargan datos nuevos, siempre van a la activa.
- Los resultados viejos siguen apuntando a la versión vieja, **pero
  los dashboards los ven igual** — el sistema combina automáticamente
  todas las versiones de la misma familia.

#### Pasos

1. Ir a **Exams → Exam templates**.
2. Buscar la plantilla en el listado (la activa tiene
   `Is active version: ✓`).
3. Marcar el checkbox a la izquierda de la fila.
4. En el menú **"Action"** arriba del listado, elegir
   **"Crear nueva versión (forkear)"**.
5. Hacer click en **"Go"** (o **"Ir"**).
6. El sistema:
   - Crea automáticamente la versión nueva (ej. v2).
   - Copia todos los campos actuales como punto de partida.
   - Reasigna todas las visualizaciones (dashboards) para que ahora
     apunten a la versión nueva.
   - Marca la nueva como activa y la vieja como inactiva.
7. Te aparece un mensaje verde en la parte superior confirmando la
   creación, con un recordatorio sobre los campos eliminados.
8. Click en la **nueva versión** desde el listado para editarla y
   hacer tus cambios (agregar el nuevo campo, etc.).
9. **Guardar** la nueva versión.

#### Qué pasa con los datos viejos

| Cambio que hagas en la nueva versión | Datos viejos en dashboards |
|---|---|
| Agregar un campo nuevo | Siguen visibles (los viejos simplemente no tienen ese campo) |
| Modificar un campo existente (label, unidad, opciones) | Siguen visibles |
| Modificar una fórmula | Siguen visibles |
| **Eliminar un campo** | Los datos viejos de ese campo dejan de aparecer en los dashboards (el dato sigue en la base, pero los widgets no lo muestran) |
| **Renombrar un campo** (cambiar su `key`) | Igual que eliminar: los datos quedan "huérfanos" para los dashboards |

> 💡 Cuando guardas una nueva versión con campos eliminados o
> renombrados, el sistema te muestra una **advertencia amarilla** con
> la lista exacta de los campos afectados. Sirve como doble chequeo
> antes de irte de la pantalla.

#### Best practices

- **Nunca elimines un campo** si vas a necesitar la historia de ese
  campo. Mejor dejarlo y crear el nuevo al lado.
- **Para renombrar un campo**: agrega el nuevo `key`, copiá los datos
  manualmente si hace falta (con ayuda del equipo técnico) y recién
  ahí elimina el viejo. O deja los dos durante la transición.
- Después de crear una versión nueva, **revisa los dashboards** para
  asegurarte de que muestran lo que esperas. Si algún widget aparece
  vacío, probablemente el campo se renombró y hay que actualizar el
  widget (ver §12).
- Las versiones viejas **no se borran**: quedan en el listado en
  estado "inactivo" como respaldo histórico.

---

## 12. Paso 9 — Configurar visualizaciones (dashboards)

Las visualizaciones son lo que ven los usuarios cuando entran al
perfil de un jugador o al reporte del equipo. Tenemos **dos tipos**:

| Tipo                    | Dónde se ve                       | Para qué                          |
|-------------------------|-----------------------------------|-----------------------------------|
| **Department layout**   | Pestaña del departamento en el perfil del jugador | Datos de un jugador en particular |
| **Team report layout**  | `/reportes/<departamento>` en la app web | Datos del plantel completo        |

### 12.1 Crear un Department layout (vista por jugador)

#### Pasos

1. **Dashboards → Department layouts → Add department layout**.
2. Completar:
   - **Department**: por ejemplo `Médico`.
   - **Category**: por ejemplo `Primer Equipo`.
   - **Name**: una etiqueta interna. Ejemplo: `Médico Primer Equipo`.
   - **Is active**: dejarlo marcado.
3. **Save and continue editing**.

#### Agregar secciones

Una sección agrupa varios widgets bajo un título. Ejemplo: "Mapa
de lesiones" puede tener un solo widget grande, mientras que
"Indicadores clínicos" puede tener dos widgets lado a lado (CK e
Hidratación).

1. Abajo, **Layout sections → Add another Layout section**.
2. Completar:
   - **Title**: ej. `Mapa de lesiones`.
   - **Sort order**: 1, 2, 3...
   - **Is collapsible**: marcalo si el usuario puede plegar la
     sección.
   - **Default collapsed**: marcalo si quieres que arranque
     plegada.
3. **Save and continue editing**.

#### Agregar widgets a la sección

Click en la sección para abrirla y ver sus widgets.

1. **Widgets → Add another Widget**.
2. Completar:
   - **Section**: la sección recién creada.
   - **Chart type**: ver tabla abajo.
   - **Title**: ej. `Lesiones por región`.
   - **Column span**: cuánto ocupa horizontalmente, de 1 a 12. 12 =
     ancho completo, 6 = mitad, 4 = un tercio.
   - **Chart height**: alto en píxeles (opcional).
   - **Sort order**: 1, 2, 3...

#### Tipos de gráfico para vista por jugador

| Chart type            | Para qué                                                    |
|-----------------------|--------------------------------------------------------------|
| Line with selector    | Línea con un menú para elegir qué métrica mostrar           |
| Multi-line            | Varias líneas a la vez (ej. evolución de las 5 masas)       |
| Comparison table      | Tabla con las últimas N tomas, una columna por toma         |
| Grouped bar           | Barras agrupadas (ej. masa adiposa vs. muscular últimos 3)  |
| Body map heatmap      | Mapa de cuerpo coloreado (Lesiones)                         |

#### Asociar datos al widget

Cada widget necesita saber **de qué plantilla** sacar los datos
y **qué campos** mostrar.

1. Dentro del widget, **Widget data sources → Add another Widget
   data source**.
2. Completar:
   - **Template**: la plantilla de exámenes (ej. `Pentacompartimental`).
   - **Field keys**: lista de campos separados por comas. Ejemplo:
     `peso, imc, masa_adiposa`. Tienen que coincidir con los **Key**
     de los campos definidos en la plantilla.
   - **Aggregation**: cómo se combinan los datos:
     - `Latest` — solo el último valor.
     - `Last N` — los últimos N (definir N en "Aggregation param").
     - `All` — todos los registros.
   - **Aggregation param**: el N para "Last N". Ejemplo: `5`.
   - **Label**: cómo mostrar este conjunto en la leyenda. Ejemplo:
     `Peso (kg)`.
   - **Color**: color hex opcional. Ejemplo: `#3b82f6`.
3. **Save**.

> 💡 Para gráficos con un solo conjunto de datos, una sola **Widget
> data source** alcanza. Para comparar dos plantillas distintas en
> un mismo gráfico, agregas una segunda fuente.

### 12.2 Crear un Team report layout (vista del plantel)

Similar al anterior pero usando **Dashboards → Team report layouts**.

#### Tipos de gráfico para vista del plantel

| Chart type             | Para qué                                                  |
|------------------------|------------------------------------------------------------|
| Team roster matrix     | Tabla: 1 jugador por fila, 1 métrica por columna          |
| Team status counts     | Pila visual: cuántos hay en cada estado                   |
| Team distribution      | Histograma de una métrica en todo el plantel              |
| Team trend line        | Promedio del plantel en el tiempo                         |
| Team active records    | Lista de medicaciones activas, lesiones abiertas, etc.    |
| Team activity coverage | Semáforo: ¿quién está al día con sus evaluaciones?        |
| Team leaderboard       | Top N jugadores ordenados por una métrica (podio)         |

El proceso de agregar secciones, widgets y data sources es el
mismo que para los Department layouts.

#### Tip: "Team activity coverage" — ¿quién está vencido?

Cuando lo configuras, agregas **una data source por plantilla** que
quieres monitorear (ej. una data source para CK, otra para Hidratación,
otra para Pentacompartimental). El widget muestra una tabla con
todos los jugadores y, para cada plantilla, **cuántos días pasaron
desde la última toma**:

- **Verde** (≤ 30 días por default): al día.
- **Amarillo** (entre 31 y 60): vencimiento próximo.
- **Rojo** (> 60 días): claramente vencido.
- **Gris**: el jugador nunca tuvo una toma de esa plantilla.

Los umbrales 30 / 60 se pueden cambiar editando el `display_config`
del widget (`green_max` y `yellow_max`).

#### Tip: "Team leaderboard" — top N por una métrica

Eligís **una plantilla y un campo** (ej. GPS Partido → distancia
total). En `display_config`:
- `aggregator`: `sum` (suma de todos los partidos del período),
  `avg` (promedio), `max` (máximo en un partido) o `latest` (último
  partido nada más).
- `limit`: cuántos jugadores mostrar (default 5, rango 3-20).
- `order`: `desc` (mayor a menor — el default y lo normal para
  rankings) o `asc` (menor a mayor — útil para "los 5 que menos
  corrieron").

Los primeros 3 puestos reciben tinte oro / plata / bronce
automáticamente.

### 12.3 Probar que se vean bien

Una vez creado el layout, pídele a un usuario con permieres de ver
ese departamento que ingrese a:
- `/perfil/<jugador>` para vistas por jugador.
- `/reportes/<slug-departamento>` para vistas de plantel.

Si algún widget aparece vacío, lo más probable es que:
- La plantilla no tenga resultados cargados todavía.
- Los `Field keys` del data source no coincidan con los `Key` de
  la plantilla (un typo es suficiente).

### 12.4 Cómo navega un especialista (Nutricionista, Médico, etc.)

Cada profesional **entra a su departamento desde el menú lateral**
(`Reportes → Nutricional`, por ejemplo). Esa página tiene **dos
tabs** que cubren los dos flujos de trabajo más comunes:

| Tab | Cuándo lo usa | Qué muestra |
|---|---|---|
| **Plantel** (default) | "Quiero ver al grupo completo, distribuciones, semáforos, quién está vencido para evaluación" | Todos los widgets que armaste en el **Team Report Layout** (§12.2) — roster matrix, distribuciones, etc. |
| **Por jugador** | "Quiero ver el perfil completo de un jugador específico y registrar una nueva toma sin salir de mi departamento" | Picker de jugador arriba → al elegir uno aparece el dashboard del jugador (igual que `/perfil/<id>?tab=<departamento>`) + la barra **"+ Registrar nueva entrada"** para cargar examen |

> 💡 La pestaña **"Por jugador"** evita que el especialista tenga que
> ir a `Equipo` → click jugador → tab del departamento. Le permite
> quedarse adentro de su sección y trabajar **jugador-por-jugador**
> sin perder contexto.

#### Para que esto funcione

- **Department layout** configurado (§12.1) — porque el tab "Por
  jugador" muestra justamente ese layout para el jugador seleccionado.
- **Team report layout** configurado (§12.2) — para que el tab
  "Plantel" tenga widgets.

Sin un Team layout, el tab "Plantel" muestra un placeholder amigable
diciendo "Sin reporte configurado". Sin un Department layout, el tab
"Por jugador" muestra las tarjetas de plantillas en grid (vista legacy).

---

## 13. Paso 10 — Configurar metas y alertas automáticas

Una **meta** es un umbral o límite que dispara una alerta cuando
se cumple (o se incumple). Por ejemplo:
- "Alertar si el IMC de un jugador supera 24."
- "Alertar si el peso baja más de 2 kg en los últimos 30 días."

### 13.1 Crear una meta

1. **Goals → Goals → Add goal**.
2. Completar la información básica:
   - **Player**: el jugador específico al que se aplica la meta.
   - **Template**: la plantilla de la cual se lee el dato (ej.
     `Pentacompartimental`).
   - **Field key**: el campo a evaluar (ej. `imc`).
   - **Status**: `Active` para que se evalúe.
3. **Tipo de meta**:
   - **Bound**: umbral fijo. Configurar:
     - **Operator**: `<=`, `>=`, `<`, `>`, `==`.
     - **Threshold**: el valor numérico.
   - **Variation**: cambio respecto a una ventana móvil. Configurar:
     - **Direction**: `increase`, `decrease`, `any`.
     - **Window days**: ej. `30`.
     - **Threshold pct**: variación porcentual. Ej. `5` = 5%.
4. **Severity**: `info`, `warning`, `critical`.
5. **Save**.

### 13.2 Cómo se evalúan

El sistema corre **todos los días a las 5:00 AM (UTC)** una tarea
que recorre todas las metas activas. Si alguna se dispara:
1. Se crea una **Alert** que aparece en la 🔔 campana del navbar.
2. Se envía un **email** al staff del departamento (si el envío
   de emails está configurado).

### 13.3 Ver y resolver alertas

Las alertas se gestionan desde la **app web** (no desde el panel
de admin). El staff hace click en la campana, ve la alerta, y la
marca como **acknowledged** (vista) o **resolved** (resuelta).

> 💡 También puedes ver todas las alertas históricas desde el
> panel: **Goals → Alerts**.

---

## 14. Tareas frecuentes

### 14.1 Cambiar la contraseña de un usuario

1. **Authentication and Authorization → Users**.
2. Click en el usuario.
3. Arriba, donde dice "Password", click en el link **this form**.
4. Ingresa la nueva contraseña dos veces.
5. **Change password**.

### 14.2 Dar de baja a un jugador

1. **Core → Players**.
2. Click en el jugador.
3. Desmarcar **Is active**.
4. **Save**.

> 💡 No borrar al jugador (con el botón "Delete"). Sus datos
> históricos quedan, simplemente no aparece más en los rosters
> activos.

### 14.3 Mover un jugador a otra categoría

1. **Core → Players → click en el jugador**.
2. Cambiar **Category**.
3. **Save**.

### 14.4 Cambiar permieres de un usuario

1. **Core → Staff memberships**.
2. Click en el membership de ese usuario.
3. Modificar las categorías o departamentos.
4. **Save**.
5. Pedirle al usuario que cierre sesión y vuelva a entrar para que
   los nuevos permieres tomen efecto.

### 14.5 Editar un resultado cargado por error

1. **Exams → Exam results**.
2. Buscar por jugador o plantilla en el filtro de la derecha.
3. Click en el resultado erróneo → editar campos en
   **Result data** → **Save**.

> 💡 Mejor todavía: pídele al usuario que lo cargó que use el
> botón ✏️ (lápiz) en la app web, en el historial del jugador.
> Es más intuitivo.

### 14.6 Borrar un resultado completamente

Solo si es un error de carga no recuperable.

1. **Exams → Exam results → buscar el resultado → Delete**.
2. Confirmar.

> ⚠️ Si el resultado pertenecía a un Episodio (por ejemplo, una
> lesión), borrar el último resultado puede dejar el episodio
> "huérfano". En ese caso, ir a **Exams → Episodes** y manejar el
> episodio aparte.

### 14.7 Reabrir una lesión cerrada

1. **Exams → Episodes → click en el episodio**.
2. Cambiar **Status** de `closed` a `open`.
3. **Save**.
4. Volver a la app web y cargar un nuevo `ExamResult` con el stage
   correspondiente (`recovery`, `reintegration`, etc.).

### 14.8 Cargar un nuevo medicamento al listado WADA

Esto es **avanzado** y requiere editar el JSON del campo
`medicamento` en la plantilla `Medicación`. Pídele al equipo
técnico que lo haga — modificar mal el JSON puede romper el
sistema de alertas.

---

## 15. Preguntas frecuentes

### "Creé un usuario y no puede entrar a la app web"

Causas habituales en orden de probabilidad:

1. **No tiene email** en su `User`. El login es por email. Verificar
   en **Users → editar → Email address**.
2. **No tiene Staff membership**. Crearlo (§10).
3. La contraseña es incorrecta. Resetearla (§14.1).

### "Un médico ve jugadores que no debería ver"

Probablemente su `StaffMembership` tiene marcado **All categories**.
Desmarcarlo y elegir solo las categorías que le corresponden.

### "Cargué un examen pero no aparece en el dashboard"

Verificar:
1. ¿La plantilla tiene la categoría correcta en **Applicable
   categories**?
2. ¿El layout está configurado para mostrar esa plantilla?
3. ¿El **Field key** del Widget data source coincide exactamente
   con el **Key** del campo en la plantilla?

### "El IMC sale como 0 o vacío"

El campo IMC es **calculado**. Para que tenga valor se necesitan
los campos `peso` y `talla`. Si alguno está vacío, el cálculo
falla silenciosamente.

### "Quiero agregar un departamento nuevo (ej. Psicología)"

1. **Core → Departments → Add department** (§5).
2. **Core → Categories → editar las categorías existentes →
   marcar el nuevo departamento → Save** (§6).
3. Crear plantillas para ese departamento (§11).
4. Crear layouts para ese departamento (§12).
5. Otorgar permieres al staff que va a usarlo (§10).

### "Puedo bajar los datos a Excel?"

Hoy no hay export integrado. Pídele a tu equipo técnico una
exportación puntual; pueden generarte un CSV en minutos.

### "Cómo veo qué hizo cada usuario?"

Cada modelo tiene un botón **History** arriba a la derecha en la
página de edición. Te muestra cuándo se creó, cuándo se modificó
y por quién (solo cambios desde el panel de admin; los cambios
desde la app web no aparecen aquí).

### "Borré algo por error, lo puedo recuperar?"

No, las eliminaciones son definitivas. Pídele a tu equipo técnico
que restaure desde un backup si es algo crítico. **Por eso recomendamos
"Is active = ❌" en lugar de Delete cuando es posible.**

---

## 16. Lista de verificación final

Antes de dar la plataforma por configurada, repasá:

### Estructura básica

- [ ] El club está creado.
- [ ] Hay 4 (o 5) departamentos creados con slug correcto.
- [ ] Las categorías están creadas y vinculadas a sus
      departamentos.
- [ ] Las posiciones están creadas y ordenadas.

### Datos de jugadores

- [ ] El plantel completo está cargado.
- [ ] Cada jugador tiene categoría y posición.
- [ ] Los datos básicos (nombre, apellido, fecha de nacimiento,
      sexo) están completos.

### Usuarios y permisos

- [ ] Hay al menos dos superadministradores.
- [ ] Cada usuario del staff tiene **email** completo.
- [ ] Cada usuario del staff tiene su **Staff membership**.
- [ ] Probaste que cada usuario ve solo lo que le corresponde.

### Plantillas

- [ ] Las plantillas que el equipo necesita están creadas.
- [ ] Cada plantilla está marcada como aplicable a las categorías
      correctas.
- [ ] Cada plantilla tiene sus campos configurados.

### Dashboards

- [ ] Cada departamento tiene al menos un **Department layout**
      (vista por jugador).
- [ ] Cada departamento tiene al menos un **Team report layout**
      (vista de plantel).
- [ ] Los widgets tienen sus data sources apuntando a las
      plantillas correctas.

### Alertas (opcional pero recomendado)

- [ ] Las metas críticas están creadas (ej. IMC, peso, lesiones).
- [ ] El servicio de email está configurado y probado con una
      alerta de prueba.

### Documentación interna

- [ ] El equipo del club sabe cómo entrar a la app web.
- [ ] Cada miembro del staff conoce su email y contraseña.
- [ ] Hay un contacto de soporte técnico identificado para
      problemas que excedan este manual.

---

**Versión del manual**: ver `git log MANUAL_USUARIO.md`. Si
encuentras un paso que no funciona como aquí se describe, lo más
probable es que la app haya cambiado — avisale al equipo técnico
para que actualicemos el manual.

---

## 17. Funcionalidades clínicas avanzadas

Capa de inteligencia médica que se construyó después de la primera
demo. Todo lo de esta sección ya viene activo con los comandos de
seeding — no requiere configuración adicional salvo cuando se indique.

### 17.1 Alertas automáticas por bandas (BAND alerts)

Cuando una plantilla tiene **bandas de referencia clínicas** definidas
en uno de sus campos numéricos (ej. % Masa Adiposa con bandas Élite /
Bueno / Aceptable / Elevado), el sistema crea automáticamente una
regla de alerta sobre la banda "roja" (la más severa) y dispara una
alerta crítica cada vez que un jugador entra a esa zona.

**Cómo se detecta la banda "roja"**: por el color. La heurística mira
el HEX del campo `color` de cada banda y elige la más cálida/rojiza
(R - max(G, B) > 50). Sin necesidad de marcar manualmente. Si querés
forzar, agregás `"alert": true` en una o más bandas.

**Auto-resuelve**: cuando el jugador vuelve a una banda segura en la
siguiente toma, la alerta se marca como "Resuelta" sola. No se queda
fantasmal forever.

**Para correrlo**: una sola vez por instalación
```bash
docker compose exec backend python manage.py seed_band_alerts
```

Se re-corre cuando agregás plantillas nuevas con bandas. Es
idempotente — preserva edits manuales del admin (severity / mensaje).

### 17.2 Widgets de alertas

**En el perfil del jugador → tab Resumen**: panel "ALERTAS ACTIVAS"
en la parte superior con borde rojo cuando hay alertas. Solo aparece
si el jugador tiene al menos una alerta activa.

**En cada tab departamental del jugador** (Médico / Físico /
Nutricional / Táctico): sección plegable "Alertas activas" filtrada
a alertas cuya plantilla pertenece a ese departamento.

**En la vista de equipo de cada departamento**: sección "Jugadores
con alertas" en la parte superior. Ranquea por cantidad de alertas
críticas → totales. Cada card es expandible y muestra todas las
alertas del jugador.

### 17.3 Plantillas médicas nuevas

**Molestias**: hoja diaria de tratamientos médicos (kinesiología,
quiropráctica, etc.). Campos: tipo, zona, comentarios. No episódica
— cada entrada es un registro independiente. Múltiples entradas por
día por jugador permitidas. Se ve en el perfil del jugador como
"Molestias recientes" y en el reporte del equipo como "Molestias
del plantel".

**Check-IN**: cuestionario diario de bienestar con 5 dimensiones
escala Likert 1-5 (1 = peor, 5 = mejor en TODAS):
- DOMS (dolor muscular post-esfuerzo)
- Estado de ánimo
- Estrés
- Fatiga
- Sueño

Total Bienestar = suma (rango 5-25). Se calcula automáticamente.

Los 5 ítems tienen bandas: 1-2 = Bajo (rojo), 3 = Aceptable (amarillo),
4-5 = Bueno (verde). Por eso disparan alertas automáticas cuando un
jugador reporta 1 o 2 en cualquier dimensión.

**Visualización del Check-IN del equipo**: chart de barras agrupadas
por día. Cada día muestra 5 barras (una por dimensión) + una línea
negra arriba con el Total Bienestar.

### 17.4 Reporte GPS por partido (Físico)

El reporte de equipo del departamento Físico ahora es **por partido**.
Hay un selector grande arriba donde elegís qué partido analizar — todo
el resto de la página se filtra a ese partido.

**Estructura**:
- **General**: promedios del partido entero
- **Primer tiempo**: solo métricas del 1T (sufijo `_p1`)
- **Segundo tiempo**: solo métricas del 2T (sufijo `_p2`)

Para que esto funcione, los registros GPS **tienen que estar
linkeados a un evento de tipo partido**. Si tenés data histórica sin
eventos linkeados, corré:

```bash
docker compose exec backend python manage.py backfill_match_events \
    --create-synthetic --window-days 3
```

A partir de ahí, cuando cargás un GPS nuevo el formulario te obliga
a elegir el partido al que corresponde (`link_to_match=True` en la
plantilla).

### 17.5 Visualizaciones especiales

- **CK del plantel**: barras verticales con 3 líneas de referencia
  (límite inferior 200, superior 500, promedio del equipo calculado
  en vivo).
- **Densidad urinaria**: barras con 3 bandas sombreadas (Hidratado
  verde / Amarillo / Deshidratado rojo). Eje Y zoomeado 1.000-1.040
  con 3 decimales para que las diferencias en la 3ª decimal se vean.

Todas estas visualizaciones son ajustables desde el admin Django
editando el `display_config` del widget. Ver `DASHBOARDS.md` § 3 para
la referencia completa de tipos de chart.
