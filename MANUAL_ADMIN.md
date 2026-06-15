# Manual del administrador — SLAB

Guía operativa para las personas que usan y administran la plataforma
SLAB (médicos, físicos, técnicos, nutricionistas y superadministradores).

> Este manual cubre el **uso real** de la app: cómo navegar, registrar
> datos, configurar plantillas, leer dashboards y resolver problemas
> comunes. Para arquitectura técnica ver `PROJECT.md`; para despliegue
> ver `RAILWAY_DEPLOY.md`; para detalle del sistema de gráficos ver
> `DASHBOARDS.md`.

---

## Índice

1. [Roles y permisos](#1-roles-y-permisos)
2. [Acceso y primer ingreso](#2-acceso-y-primer-ingreso)
3. [Tour de la interfaz](#3-tour-de-la-interfaz)
4. [Operación diaria (frontend)](#4-operación-diaria-frontend)
5. [Lesiones, medicación y alertas](#5-lesiones-medicación-y-alertas)
6. [Configuración inicial (Django Admin)](#6-configuración-inicial-django-admin)
7. [Plantillas de exámenes](#7-plantillas-de-exámenes)
8. [Layouts: dashboards y reportes de equipo](#8-layouts-dashboards-y-reportes-de-equipo)
9. [Metas y alertas automáticas](#9-metas-y-alertas-automáticas)
10. [Mantenimiento del contenedor (Railway)](#10-mantenimiento-del-contenedor-railway)
11. [Solución de problemas](#11-solución-de-problemas)
12. [Glosario](#12-glosario)

---

## 1. Roles y permisos

SLAB usa **dos capas de permisos**:

- **Usuarios de Django** (`auth.User`): autenticación y acceso al
  panel `/admin/`. El flag `is_superuser=True` da acceso total al
  Admin sin restricciones.
- **`StaffMembership`**: limita lo que ve un usuario *no superadmin*
  en la app web (no en `/admin/`). Define a qué club, qué categorías
  y qué departamentos pertenece.

| Rol            | Acceso típico                                                                     |
|----------------|------------------------------------------------------------------------------------|
| Superadmin     | Acceso al `/admin/` + visualiza todos los clubes en la app web                    |
| Médico         | Su club, todas sus categorías, departamento `medico`                               |
| Físico         | Su club, todas sus categorías, departamento `fisico`                               |
| Nutricionista  | Su club, todas sus categorías, departamento `nutricional`                          |
| Técnico        | Su club, su categoría (ej. Primer Equipo), departamentos `tactico` + `fisico`     |
| DT cuerpo téc. | Su club, todas sus categorías, todos los departamentos                            |

### Reglas clave

- Sin `StaffMembership` el usuario no superadmin **no ve nada** en la
  app web (queda atrapado en `/login`).
- Los flags `all_categories` / `all_departments` son atajos: si están
  marcados, las listas explícitas se ignoran.
- Cambios en `StaffMembership` **se aplican al próximo login** del
  usuario afectado.

---

## 2. Acceso y primer ingreso

### URLs

| Para qué                     | URL                                              |
|------------------------------|--------------------------------------------------|
| App web (staff)              | `https://<frontend>.up.railway.app/`             |
| Login frontend               | `/login`                                         |
| Panel Django (superadmin)    | `https://<backend>.up.railway.app/admin/`        |

### Primer ingreso de un usuario nuevo

1. El superadmin crea el usuario en `/admin/` → **Authentication and
   Authorization → Users → Add user**.
2. El superadmin crea el `StaffMembership` correspondiente (ver §6).
3. El usuario va a `/login`, ingresa **email + contraseña**.
4. Es redirigido automáticamente a `/equipo`.

> **Importante**: el login es por **email**, no por username. Si un
> usuario reporta "no puedo ingresar", validar primero que el email
> en su `User` está bien escrito.

### Cambio de contraseña

- Superadmin: en `/admin/` → **Users → editar → 🔑 cambiar contraseña**.
- Auto-servicio: aún no implementado — depende del superadmin.

### Cerrar sesión

Click en el avatar (arriba a la derecha en escritorio, en la barra
inferior en móvil) → **Cerrar sesión**.

---

## 3. Tour de la interfaz

### Sidebar (escritorio) / Drawer (móvil)

- **Equipo** — vista de campo + roster.
- **Perfil** — accede al perfil del jugador seleccionado (sin selección,
  redirige a `/equipo`).
- **Reportes** — submenú con un ítem por departamento del usuario.
- **Configuraciones**:
  - **Jugadores** — alta/edición/baja de jugadores.
  - **Partidos** — crear y editar partidos.

### Navbar (arriba)

- **Selector de categoría** (izquierda): cambia el contexto. Persiste
  entre páginas. Toda la data filtra por la categoría seleccionada.
- **🔔 Campana de alertas**: muestra alertas críticas activas (lesiones
  abiertas, medicación con riesgo WADA, metas vencidas). Click en una
  alerta para abrir la pantalla relevante.
- **Avatar**: muestra el nombre del usuario logueado. Menú con cerrar
  sesión.

### Vista responsive

- **Tablet / móvil**: sidebar colapsa a drawer (botón hamburguesa).
  Widgets se reorganizan a columna única.
- **Escritorio**: 12 columnas, widgets pueden ocupar 4 / 6 / 8 / 12.

---

## 4. Operación diaria (frontend)

### 4.1 `/equipo` — Vista del plantel

Dos pestañas:

- **Vista de campo**: jugadores en posiciones de cancha (POR / DF / MC /
  DEL). Cada jugador muestra dorsal y un punto de color con su estado
  (verde disponible, rojo lesionado, naranja recuperación, amarillo
  reintegración).
- **Plantel completo**: tabla con todos los jugadores, búsqueda y
  ordenamiento. Click en un jugador → su perfil.

### 4.2 `/perfil/<id>` — Perfil del jugador

Header con foto, datos básicos, posición, edad, estado.

Pestañas (una por departamento al que el usuario tiene acceso):

| Pestaña      | Contenido                                                               |
|--------------|-------------------------------------------------------------------------|
| Resumen      | Métricas clave de cada departamento, último valor + tendencia          |
| Médico       | Lesiones (Episode UI), CK, hidratación, CMJ, medicación activa          |
| Físico       | GPS partido, GPS entrenamiento, comparativa últimos 5 partidos         |
| Táctico      | Rendimiento de partido, ratings, goles, asistencias                    |
| Nutricional  | Pentacompartimental, evolución antropométrica, fraccionamiento 5 masas |

#### Registrar un examen

1. En la pestaña del departamento → tarjeta de la plantilla → **+ Agregar**.
2. Se abre el formulario configurado por la plantilla.
3. Si la plantilla es **episódica** (Lesiones), aparece primero el
   "selector de episodio": **¿es una lesión nueva** o **continúa una
   existente?**.
4. Completar campos. Los campos calculados (IMC, masa adiposa, etc.) se
   computan al guardar.
5. **Guardar** — vuelve al perfil con el resultado en la tabla histórica.

#### Editar un examen ya registrado

1. En la tabla histórica del departamento, click en el ✏️ **lápiz** de
   la fila.
2. El modal abre con los valores actuales pre-cargados.
3. Modificar y **Guardar** → PATCH al backend, refresh de la tabla.

#### Eliminar un examen

Click en 🗑️ **papelera** de la fila → confirmar. Si el resultado está
asociado a un **Episodio abierto**, eliminarlo puede recomputar el
estado del jugador.

### 4.3 `/perfil/<id>/eventos` — Eventos del jugador

Lista de eventos (citaciones, evaluaciones agendadas, sesiones
clínicas). **+ Agregar evento** abre formulario con título, fecha,
duración, tipo, notas.

### 4.4 `/reportes/<departamento>` — Department Hub

Punto de entrada principal por departamento (nutricional, médico,
físico, táctico). Organizado en **dos tabs**:

#### Tab "Plantel" (default)

Vista agregada del plantel completo. Widgets:

- **Roster matrix**: tabla con un jugador por fila, una métrica por
  columna, semáforo automático vs. el rango del plantel.
- **Status counts**: cuántos disponibles / lesionados / etc.
- **Distribution**: histograma de una métrica.
- **Trend line**: promedio del plantel en el tiempo.
- **Active records**: lista de medicaciones activas, lesiones abiertas.
- **Activity coverage**: matriz de "quién está vencido para
  evaluación".
- **Leaderboard**: top N por una métrica.
- **Goal progress**: estado de metas por jugador.

Filtros disponibles (cross-cutting a todos los widgets):
- **Posición** (POR/DF/MC/DEL).
- **Período** (presets 30/60/90 días + personalizado, cap 90 días).
- **Jugadores** (multi-select; default "Todo el plantel").

Botón **📥 Descargar Excel** exporta los widgets renderizados.

#### Tab "Por jugador"

Permite al usuario quedarse adentro de su departamento y navegar
jugador-por-jugador sin pasar por `/equipo`. Renderea exactamente el
mismo contenido que `/perfil/<id>?tab=<departamento>`:

- Dashboard del departamento (donut, multi-line, comparison table,
  etc., todo según el `DepartmentLayout` configurado).
- Barra **"Registrar nueva entrada"** para cargar un examen sin salir.
- Tabla de historial con pencil/trash por fila (sujeto a permisos).
- Filtro de fecha propio del jugador (independiente del de Plantel).

**Estado URL-driven**: tab + jugador seleccionado se persisten en
query params (`?tab=por_jugador&player=<uuid>`), así el link es
compartible y sobrevive back/forward.

**Comportamientos importantes**:
- Cambiar la **categoría** en el navbar deselecciona el jugador
  automáticamente si ya no pertenece a la nueva.
- Sin jugador seleccionado → placeholder amigable que invita a
  elegir.

> 💡 Esta dualidad resuelve el feedback de la nutricionista de mayo
> 2026: "soy nutricionista, voy a mi sección y ahí trabajo el todo".
> El tab "Por jugador" es la entrada natural para ese mental model.

### 4.5 `/partidos` — Gestión de partidos

- Lista de partidos existentes.
- **+ Nuevo partido**: fecha, rival, local/visitante, competición,
  resultado.
- Click en un partido → editar y registrar **rendimiento por jugador**:
  formulario bulk para cargar minutos, rating, goles, asistencias,
  tarjetas, etc. de toda la convocatoria en una sola pantalla.

### 4.6 `/configuraciones/jugadores` — CRUD de jugadores

- Tabla con todos los jugadores activos de la categoría seleccionada.
- **+ Agregar**: nombre, apellido, fecha de nacimiento, sexo,
  nacionalidad, dorsal, posición.
- ✏️ Editar / 🗑️ Desactivar (soft-delete: `is_active=False`).

> Para alta masiva (CSV) → Django Admin → **Players → Import** (si está
> habilitado), o usar un comando custom (ver §10).

---

## 5. Lesiones, medicación y alertas

### 5.1 Ciclo de vida de una lesión (Episodio)

La plantilla **Lesiones** es **episódica**: cada lesión es un
**Episode** con varios `ExamResult` que la atraviesan en etapas:

```
diagnosticada → en recuperación → reintegración → cerrada
```

**Cómo registrar:**

1. Médico → perfil del jugador → pestaña Médico → **Lesiones → + Agregar**.
2. El selector de episodio pregunta:
   - **Nueva lesión** → crea Episode + primer ExamResult con stage
     `injured`.
   - **Continúa existente** → agrega ExamResult al Episode actual,
     cambia stage si corresponde.
3. Cuando se carga un ExamResult con `stage=closed` y
   `actual_return_date`, el Episodio se cierra automáticamente y el
   estado del jugador se recalcula.

**El estado del jugador (`Player.status`)** es un cache derivado del
**peor stage** entre todos sus episodios abiertos. Se actualiza por
señal post-save sin intervención manual.

### 5.2 Medicación + alertas WADA

La plantilla **Medicación** **NO es episódica** (cada prescripción es
una entrada plana con `fecha_inicio` / `fecha_fin`).

El campo `medicamento` tiene un mapa interno **medicamento →
clasificación WADA** (`PERMITIDO` / `CONDICIONAL` / `PROHIBIDO`).
Al guardar:

- Si el medicamento es **PROHIBIDO** o **CONDICIONAL**, se dispara una
  alerta automática (severity `critical` / `warning`).
- La alerta aparece en la **🔔 campana** del navbar.
- Si el worker de Celery está corriendo, también se envía un **email**
  al `DEFAULT_FROM_EMAIL` con detalle + link al perfil.

### 5.3 La campana de alertas

Click en el ícono 🔔 abre el panel con:

- **Críticas** (rojo): WADA prohibido, lesiones graves, metas
  vencidas.
- **Advertencias** (amarillo): WADA condicional, metas próximas a
  vencer.
- **Resueltas**: histórico de los últimos 30 días.

Click en una alerta → abre la pantalla relevante (perfil del
jugador, partido, etc.).

---

## 6. Configuración inicial (Django Admin)

Acceder a `https://<backend>.up.railway.app/admin/` con un usuario
`is_superuser=True`.

### 6.1 Crear un club

**Core → Clubs → Add club**

- `name`: ej. "Universidad de Chile"
- Guardar.

### 6.2 Crear departamentos

**Core → Departments → Add department**

- `club`: el creado arriba.
- `slug`: identificador interno corto: `medico`, `fisico`, `tactico`,
  `nutricional`, `psicosocial`. **Solo minúsculas, sin acentos.**
- `name`: nombre visible: "Médico", "Físico", etc.

> Crear los 4 departamentos estándar antes de seguir.

### 6.3 Crear categorías

**Core → Categories → Add category**

- `club`: idem.
- `name`: ej. "Primer Equipo", "Sub-20", "Femenino".
- `departments`: marcar **todos los departamentos** que aplican a esta
  categoría.

> El M2M `departments` controla qué pestañas ve un jugador de esa
> categoría en su perfil. Si una categoría no tiene `medico` marcado,
> los jugadores de esa categoría no ven la pestaña Médico.

### 6.4 Crear posiciones

**Core → Positions → Add position** (una por una):

- `club`, `name` (ej. "Arquero"), `abbreviation` (ej. "POR"),
  `sort_order` (1=POR, 2=DF, 3=MC, 4=DEL).

> Las posiciones son por club — cada equipo puede tener su propia
> taxonomía.

### 6.5 Crear usuarios

**Authentication and Authorization → Users → Add user**

El formulario de creación está customizado (`SLABUserAdmin` en
`core/admin.py`) y exige los siguientes campos como obligatorios:

- `username`
- `first_name`
- `last_name`
- `email`
- `password` + `password confirmation`

Después de guardar, en la página de edición se pueden ajustar
`is_staff` (acceso al `/admin/`) y `is_superuser` si corresponde.

> El modelo subyacente mantiene `blank=True` en `first_name` /
> `last_name` / `email`, así que `createsuperuser`, fixtures y
> scripts CLI siguen funcionando sin cambios. El gate vive solo en
> el form de la admin UI.

### 6.6 Crear `StaffMembership`

**Core → Staff memberships → Add staff membership**

- `user`: el usuario recién creado.
- `club`: a qué club pertenece.
- **Categorías**: marcar `all_categories` o seleccionar específicas.
- **Departamentos**: marcar `all_departments` o seleccionar
  específicos.
- Guardar.

### 6.7 Activar plantillas para una categoría

Cada `ExamTemplate` tiene un campo `applicable_categories` (M2M). Una
plantilla **NO aparece** para los jugadores de una categoría hasta que
esa categoría está en esa lista.

**Cómo activar masivamente desde la línea de comandos** (recomendado):

```bash
python manage.py seed_pentacompartimental \
    --department-slug nutricional \
    --all-applicable-categories \
    --club "Universidad de Chile"
```

(Reemplazar el comando + slug del departamento por la plantilla que
corresponda.)

### 6.8 Permieres de acción (Django Groups + perms granulares)

Capa **ortogonal** al `StaffMembership` scoping. Mientras
`StaffMembership` define **qué datos** ve un usuario,
los Django Groups + Permissions definen **qué acciones** puede
realizar sobre eeres datos.

#### Modelo

- **Dos grupos seed**: `Editor` (CRUD completo sobre ExamResult,
  Episode, Goal, Event, Player, Attachment, Alert, AlertRule —
  32 codenames) y `Solo Lectura` (solo `view_*` — 8 codenames).
- **Perms granulares sobre Contract**: `view_contract`,
  `add_contract`, `change_contract`, `delete_contract`. NO incluidos
  en ningún grupo seed; se asignan per-user.
- Superusers (`is_superuser=True`) bypassean todo.

#### Comando seed

```bash
docker compose exec backend python manage.py seed_role_groups
```

Idempotente. Backfill: usuarios sin grupo y no superuser se asignan
automáticamente a Editor. Paeres a saltar con `--skip-backfill`.
Ya está incluido como step 7 en `scripts/seed_all.sh`.

#### Implementación backend

**Helper + decorator** (`backend/api/routers.py`, top of file):

```python
def _has_perm(user, codename: str) -> bool:
    if not user or not user.is_authenticated: return False
    if user.is_superuser: return True
    return user.has_perm(codename)


def require_perm(codename: str):
    """Decorator: HttpError(403) when user lacks the perm."""
    ...
```

**Endpoints gated** (todos los POST/PATCH/DELETE relevantes):

| Endpoint | Codename |
|---|---|
| `POST /players` | `core.add_player` |
| `PATCH /players/{id}` | `core.change_player` |
| `DELETE /players/{id}` | `core.delete_player` |
| `GET /players/{id}/contracts` | `core.view_contract` |
| `POST/PATCH/DELETE /contracts` | `core.add_contract` / `change_contract` / `delete_contract` |
| `POST /results` (+ bulk + team) | `exams.add_examresult` |
| `PATCH /results/{id}` | `exams.change_examresult` |
| `DELETE /results/{id}` | `exams.delete_examresult` |
| `POST /events` | `events.add_event` |
| `PATCH /events/{id}` | `events.change_event` |
| `DELETE /events/{id}` | `events.delete_event` |
| `POST /goals` | `goals.add_goal` |
| `PATCH /goals/{id}` | `goals.change_goal` |
| `DELETE /goals/{id}` | `goals.delete_goal` |
| `PATCH /alerts/{id}` | `goals.change_alert` |
| `POST /attachments` | `attachments.add_attachment` |
| `DELETE /attachments/{id}` | `attachments.delete_attachment` |
| `PATCH /episodes/{id}` | `exams.change_episode` |

**Payload de auth** (`/auth/me`, `/auth/login`):

```json
{
  "user": {
    "id": 4,
    "email": "doctor@club.cl",
    ...
    "permissions": ["core.view_player", "exams.add_examresult", ...]
  },
  "membership": {...}
}
```

Superusers reciben `"permissions": ["*"]` en lugar de enumerar todo
el universo de codenames.

#### Frontend

`frontend/src/lib/permissions.ts`:
- `hasPermission(user, codename)` — pure helper; honra el `"*"`.
- `usePermission(codename)` — React hook.
- `useAnyPermission(codenames[])` — para esconder barras enteras.

**Patrón UI**: cuando una acción no está permitida, el **botón
desaparece** (no se renderiza disabled). Las columnas de tabla de
acciones se colapsan completamente cuando ninguna acción está
permitida.

#### Asignación desde Admin

**Para asignar un grupo a un usuario**:

1. `/admin/auth/user/<id>/`.
2. Sección **Groups** (al medio de la página).
3. Seleccionar Editor / Solo Lectura → flecha → → "Chosen groups".
4. **Save**.

**Para asignar un permiso granular** (ej. `view_contract`):

1. `/admin/auth/user/<id>/`.
2. Sección **User permissions** (debajo de Groups).
3. Buscar `core | contract | Can view contract` en la lista → flecha → → "Chosen".
4. **Save**.

---

## 7. Plantillas de exámenes

### 7.1 Estructura

Cada `ExamTemplate` tiene:

- `name`, `slug` (auto-derivado), `department`.
- **Flags de comportamiento** (booleanos, todos editables desde Django
  Admin):
  - `is_episodic` — agrupa resultados en `Episode` con stages (ver §7.4).
  - `is_locked` — fija el `config_schema` (ver §7.5).
  - `link_to_match` — obliga a vincular cada resultado a un partido
    (ver §7.3).
  - `show_injuries` — embebe el panel de lesiones en el form.
- `config_schema` (JSON): la lista de campos del formulario.
- `input_config` (JSON): comportamiento del registrar (modos de
  entrada, valores compartidos en tabla, etc.). Detalle en §7.3 / §7.6.
- `applicable_categories` (M2M): qué categorías la usan.

### 7.2 Tipos de campo

| `type`        | Para qué                              | Ejemplo                          |
|---------------|---------------------------------------|----------------------------------|
| `number`      | Valores numéricos con unidad          | peso, distancia, ratings         |
| `text`        | Texto libre                           | observaciones, motivo            |
| `date`        | Fecha                                 | fecha_inicio, expected_return    |
| `categorical` | Lista cerrada de opciones             | severity, stage, body_part       |
| `boolean`     | Sí / No                               | requiere_seguimiento             |
| `calculated`  | Computado por fórmula al guardar      | IMC, masa adiposa, suma pliegues |

**Atributo opcional `direction_of_good`** (solo numérico/calculado).
Permite a los widgets de visualización (hoy: `team_roster_matrix`)
colorear los deltas con semántica clínica en lugar del azul/naranja
neutro:

| Valor      | Significado                                       | Ejemplo |
|------------|---------------------------------------------------|---------|
| `neutral`  | Default — sin opinión; el delta se pinta azul/naranja según dirección | dorsal, talla |
| `up`       | Más es mejor → verde si sube, rojo si baja        | CMJ, masa muscular, fuerza |
| `down`     | Menos es mejor → verde si baja, rojo si sube      | CK, peso a perder, FC reposo |

Se edita en el inline de `TemplateField` (columna `direction_of_good`
en el form). Se incluye en `to_schema_dict` y se respeta en
`fork_new_version()`.

**Atributo opcional `reference_ranges`** (solo numérico/calculado).
Bandas clínicas multi-rango que activan:
- **Hint en el form de carga** (estático al estar vacío, dinámico
  con la banda activa al escribir).
- **Borde coloreado por celda** en `team_roster_matrix` y
  `comparison_table` widgets.

Formato JSON en el inline (campo `reference_ranges`):

```json
[
  {"label": "Bajo",    "max": 30,                    "color": "#fbbf24"},
  {"label": "Normal",  "min": 30,  "max": 200,       "color": "#16a34a"},
  {"label": "Elevado", "min": 200, "max": 400,       "color": "#f59e0b"},
  {"label": "Severo",  "min": 400,                   "color": "#dc2626"}
]
```

Reglas (validadas en `TemplateField._validate_reference_ranges()`):

- `label` obligatorio por banda.
- `min` inclusivo, `max` exclusivo, al menos uno por banda.
- Bandas ordenadas (low → high) y disjuntas (`curr.min ≥ prev.max`).
- Máximo una banda abierta por extremo (la más baja sin `min`, la
  más alta sin `max`).
- `color` opcional; si no, se deriva del label (`"normal"` → verde,
  `"severo"` → rojo, etc.).

**Frontend**:
- `lib/reference.ts` aporta `findBandForValue()`, `bandColor()`,
  `summarizeBands()`, `formatBandRange()`.
- `DynamicUploader.tsx` → `ReferenceBandsHint` renderiza el hint
  solo cuando `field.type === "number"` y hay bandas.
- `TeamRosterMatrix.tsx` y `ComparisonTable.tsx` aplican
  `box-shadow: inset 0 0 0 2px <color>` sobre cada celda numérica
  cuyo valor caiga en una banda. No compite con el coloreo
  `vs_team_range`.

**Complementario a `direction_of_good`**: `direction_of_good`
opinaba sobre **cambios** (Δ); `reference_ranges` sobre **valores
absolutos**. Los dos sistemas conviven sin solaparse.

**Atributos comunes a cualquier campo** (válidos en todos los tipos
salvo `calculated`):

| Atributo      | Tipo    | Para qué |
|---------------|---------|----------|
| `required`    | bool    | El form bloquea el guardado si el campo está vacío. Mensaje: "Falta el campo «<label>»". |
| `placeholder` | string  | Hint dentro del input vacío. |
| `group`       | string  | Agrupa campos en secciones visuales del form. |
| `help_text`   | string  | Texto auxiliar debajo del input. |

**Atributos solo para `type: "number"`** (además de `unit`,
`reference_ranges`, `direction_of_good`):

| Atributo | Tipo  | Para qué |
|----------|-------|----------|
| `min`    | number | Cota inferior. Aplicada como `min` HTML + validación en submit. |
| `max`    | number | Cota superior. Mismo doble enforcement. |

Ejemplo (en `rendimiento_de_partido` la calificación va 1-10):

```json
{
  "key": "rating",
  "label": "Calificación (1-10)",
  "type": "number",
  "unit": "/10",
  "min": 1,
  "max": 10
}
```

El form muestra el highlight rojo nativo del browser al teclear
fuera de rango y refusa guardar con mensaje claro
(`"Calificación (1-10)" debe ser ≤ 10`).

### 7.3 Plantillas atadas a un partido (`link_to_match`)

Cuando un examen sólo tiene sentido en el contexto de un partido
concreto (rendimiento, GPS de partido, etc.), encender
`link_to_match=True` lo convierte en una plantilla **match-attached**:

- El form de carga muestra un selector **"Asociar partido"
  obligatorio**. El partido elegido provee el `recorded_at`
  (sobrescribe lo que diga el form).
- `ExamResult.clean()` rechaza cualquier resultado sin `event_id` —
  protege contra cargas huérfanas vía API o admin directo.
- El payload ya guardado en `result_data` se mantiene, pero ahora
  todo nuevo registro **tiene que** vincularse.

#### Cuándo encenderlo

| Plantilla                           | `link_to_match` | Por qué |
|-------------------------------------|-----------------|---------|
| `rendimiento_de_partido`            | **True**        | El rating, minutos y goles solo tienen sentido por partido. |
| `gps_rendimiento_fisico_de_partido` | **True**        | Cada lectura corresponde a un partido específico. |
| `gps_entrenamiento`                 | False           | Las cargas de entrenamiento no son por partido. |
| `analisis_sangre`, `medicacion`     | False           | Mediciones clínicas independientes de cualquier evento. |

#### Activarlo en Django Admin

`/admin/exams/examtemplate/` → abrir la plantilla → marcar **"Link to
match"** → guardar.

#### Roster + valores por rol (futuro inmediato)

Las plantillas `link_to_match=True` permiten habilitar dos features
adicionales en el modo `team_table`:

- **Filtro a jugadores que vistieron** (`row_filter_to_dressed`):
  esconde del formulario a los jugadores con `match_role` `no_citado`,
  `lesionado`, etc.
- **Valores por defecto por rol** (`defaults_by_role`): pre-llena la
  fila según el rol del jugador en la convocatoria (titular →
  `minutes_played=90`, citado sin vestir → `minutes_played=0`, etc.).

Detalle en §7.6.

### 7.4 Plantillas episódicas

Una plantilla con `is_episodic=True` agrupa sus resultados en
**Episodes**. El frontend muestra el "selector de episodio" antes del
formulario. **Lesiones** es la única plantilla episódica del demo —
**Medicación** no lo es (es prescripción flat, ver §5.2).

### 7.5 Bloqueo (`is_locked`)

Una plantilla queda **locked** automáticamente cuando se le carga el
primer resultado. El bloqueo evita que se modifique el `config_schema`
in-place (romperá los datos existentes).

**Para cambiar el schema de una plantilla locked**: el flujo
recomendado es **crear una nueva versión** (ver §7.5). El antiguo
flujo `--unlock` sigue disponible para emergencias pero ya no es la
recomendación por default — destruye la garantía de integridad de los
datos históricos.

```bash
# Solo si entendés que vas a romper la consistencia de datos viejos:
python manage.py seed_lesiones \
    --department-slug medico \
    --all-applicable-categories \
    --club "Universidad de Chile" \
    --unlock
```

### 7.6 Configuración del registrar (`input_config`)

El JSON `ExamTemplate.input_config` controla cómo se ve el formulario
de carga. Es opcional — sin él, la plantilla se muestra solo en modo
single-player con defaults sensatos.

```jsonc
{
  "input_modes": ["team_table", "single"],     // qué modos ofrece el registrar
  "default_input_mode": "team_table",          // cuál se abre primero
  "allow_event_link": true,                    // espejado desde link_to_match (no editar a mano)
  "modifiers": {
    "prefill_from_last": false                 // copiar valores del último resultado al editar
  },
  "team_table": {
    "shared_fields": ["fecha"],                // campos entrados una sola vez (van en cada fila)
    "row_fields": ["minutes_played", "rating"], // override del orden / subset por fila
    "row_filter_to_dressed": true,             // (planificado) esconder bench / no_citado
    "row_group_by": "match_role",              // (planificado) sección por rol
    "defaults_by_role": {                      // (planificado) pre-fill por rol
      "titular":         {"minutes_played": 90, "started_eleven": true},
      "suplente_ingresa":{"started_eleven": false},
      "citado_no_vestir":{"minutes_played": 0,  "started_eleven": false}
    }
  }
}
```

**Claves clave**:

- `input_modes` — lista de modos disponibles. Hoy: `single`,
  `team_table`, `bulk_ingest`, `quick_list`.
- `default_input_mode` — qué tab se abre primero al entrar al
  registrar.
- `team_table.shared_fields` — campos cuyo valor es **igual para todo
  el equipo** en una carga (típicamente `fecha`). Aparecen una vez
  arriba de la grilla.
- `team_table.row_fields` — sobrescribe el orden / subset de columnas
  por fila. Omitir = "todos los campos no compartidos y no
  calculados".
- `team_table.row_filter_to_dressed` (planificado) — esconde a
  jugadores convocados con rol distinto de `titular`,
  `suplente_ingresa` o `citado_no_vestir`. Solo aplica si
  `link_to_match=True`.
- `team_table.defaults_by_role` (planificado) — pre-llena la fila
  según el rol del jugador en la convocatoria. Las celdas pre-llenas
  se marcan visualmente (italic / atenuadas) hasta que el coach las
  edite.

### 7.7 Versionado de plantillas (`family_id` + fork)

Cuando una plantilla locked necesita un cambio de schema, **forkear**
crea una nueva versión sin tocar la vieja. Los datos viejos siguen
ahí, atados a v1; los datos nuevos van a v2; y los dashboards
fusionan ambas versiones por `family_id` automáticamente.

#### Modelo (`exams/models.py::ExamTemplate`)

| Campo               | Tipo            | Para qué |
|---------------------|-----------------|----------|
| `family_id`         | UUIDField       | Compartido por todas las versiones de la misma plantilla |
| `version`           | PositiveIntegerField | Empieza en 1, incrementa con cada fork |
| `is_active_version` | BooleanField    | Exactamente una versión activa por familia (partial unique constraint) |

#### Crear nueva versión desde Admin

1. **Exams → Exam templates**.
2. Marcar el checkbox de la plantilla.
3. Menú **Action → "Crear nueva versión (forkear)" → Go**.
4. El sistema (en una transacción atómica):
   - Clona el modelo a `version + 1`.
   - Bulk-copia las `TemplateField` rows.
   - Copia el M2M `applicable_categories`.
   - **Reasigna todos los `WidgetDataSource` + `TeamReportWidgetDataSource`**
     de la versión vieja → nueva.
   - Flippea los flags: vieja `is_active_version=False`, nueva `=True`.
5. Mensaje verde de confirmación + recordatorio sobre campos
   eliminados.

#### Programáticamente

```python
template = ExamTemplate.objects.get(slug="pentacompartimental", is_active_version=True)
new_version = template.fork_new_version()
# new_version está unlocked, listo para editar config_schema
```

#### Cómo funcionan los reads (fan-out por `family_id`)

Los resolvers de dashboards consultan por familia, no por id:

```python
# Antes (en cualquier resolver):
ExamResult.objects.filter(template_id=template.id, ...)

# Ahora:
ExamResult.objects.filter(template__family_id=template.family_id, ...)
```

Esto significa que un `WidgetDataSource` apuntando a v2 **también
trae los resultados de v1**. Campos eliminados o renombrados en v2
desaparecen silenciosamente porque `result_data.get(key)` retorna
`None` (opción "a" del diseño — drop silencioso).

#### Detección de drift al guardar

`ExamTemplateAdmin.save_related()` compara `config_schema.fields[*].key`
entre la versión actual y la anterior. Si hay claves removidas, emite
un `messages.WARNING` listando exactamente cuáles. Implementación:
`exams/admin.py::_removed_field_keys_vs_previous_version()`.

#### Routing de writes

Tres lugares chequean `is_active_version=True` para que escrituras
nuevas siempre vayan a la versión vigente:

| Endpoint / función | Lugar |
|---|---|
| `GET /api/players/{id}/templates` (registrar picker) | `api/routers.py::list_player_templates` |
| `_build_template_namespaces` (fórmulas cross-template) | `exams/calculations.py` |
| `ExamTemplate.active_for_slug(slug)` (classmethod helper) | `exams/models.py` — disponible para seeds + scripts |

#### Constraints (Postgres)

```sql
-- Exactly one active version per family
CREATE UNIQUE INDEX exam_tpl_one_active_per_family
    ON exams_examtemplate (family_id) WHERE is_active_version = true;

-- Prevent duplicate (family, version) pairs
ALTER TABLE exams_examtemplate ADD CONSTRAINT exam_tpl_family_version_unique
    UNIQUE (family_id, version);
```

#### Migración

`exams/migrations/0018_examtemplate_versioning.py` agrega los
campos, **backfilea cada template existente como v1 de su propia
familia única** (`family_id = uuid4()`, `is_active_version=True`),
después agrega los constraints. Probado contra DB demo con 14
templates.

#### Limitaciones actuales (Slice 3 futuro)

- **Renombrar un campo** = perder history para ese campo (opción `a`
  del diseño). Para preservarla habrea que implementar `field_remap`
  por versión: un mapa `{old_key: new_key}` en el `config_schema` de
  v2 que el resolver lea para traducir antes de leer `result_data`.
- Versiones viejas **no se pueden eliminar** mientras tengan
  `ExamResult` apuntando (FK `PROTECT`).
- No hay diff visual de schemas entre versiones — abrir dos pestañas
  para comparar `config_schema_preview`.

### 7.8 Plantillas estándar del demo

| Slug                                  | Departamento  | Episódica | `link_to_match` | Notas                                       |
|---------------------------------------|---------------|-----------|-----------------|---------------------------------------------|
| `pentacompartimental`                 | nutricional   | No        | No              | 5 masas + IMC + suma pliegues               |
| `lesiones`                            | medico        | **Sí**    | No              | Episodios con stages                        |
| `medicacion`                          | medico        | No        | No              | Alertas WADA por medicamento                |
| `ck`                                  | medico        | No        | No              | Marcador bioquímico — entrada por equipo    |
| `densidad_urinaria`                   | medico        | No        | No              | (ex-`hidratacion`) — control de hidratación |
| `cmj`                                 | medico        | No        | No              | Test contramovimiento                       |
| `check_in`                            | medico        | No        | No              | Wellness diario (5 dimensiones)             |
| `molestias`                           | medico        | No        | No              | Bitácora de dolores / molestias diarias     |
| `hoja_diaria_medico`                  | medico        | No        | No              | Intervenciones diarias del cuerpo médico    |
| `analisis_sangre`                     | medico        | No        | No              | Panel anual de marcadores bioquímicos       |
| `fase_densidad`                       | medico        | No        | No              | Fase de ciclo + densidad urinaria + MAD     |
| `gps_rendimiento_fisico_de_partido`   | fisico        | No        | **Sí**          | GPS por partido — vinculado al evento       |
| `gps_entrenamiento`                   | fisico        | No        | No              | GPS entrenamiento                           |
| `rendimiento_de_partido`              | tactico       | No        | **Sí**          | Rating + estadísticas por partido           |
| `notas_diarias_<dept>`                | (cada uno)    | No        | No              | Bitácora textual diaria por departamento    |

---

## 8. Layouts: dashboards y reportes de equipo

### 8.1 Dos sistemas paralelos

| Modelo                | Dónde renderiza                | Para qué                         |
|-----------------------|--------------------------------|----------------------------------|
| `DepartmentLayout`    | `/perfil/<id>` (pestaña dept) | Vista por jugador                |
| `TeamReportLayout`    | `/reportes/<deptSlug>`        | Vista del plantel completo       |

Ambos modelan el dashboard como **secciones → widgets → fuentes de
datos** (`WidgetDataSource` apuntando a una `ExamTemplate`).

### 8.2 Tipos de gráfico (`ChartType`)

**Por jugador (DepartmentLayout)**:

- `line_with_selector` — línea con dropdown para elegir métrica.
- `multi_line` — varias líneas simultáneas.
- `comparison_table` — tabla últimas N tomas.
- `grouped_bar` — barras agrupadas.
- `body_map_heatmap` — mapa de cuerpo (Lesiones).

**Por equipo (TeamReportLayout)**:

- `team_roster_matrix` — fila por jugador, columna por métrica.
- `team_status_counts` — pila de cuántos hay en cada stage.
- `team_distribution` — histograma de una métrica.
- `team_trend_line` — promedio del plantel en el tiempo.
- `team_active_records` — lista de medicaciones activas / lesiones
  abiertas.
- `team_activity_coverage` — matriz de cumplimiento: días desde la
  última toma por plantilla, semáforo verde/amarillo/rojo/gris.
  `display_config`: `green_max` (default 30), `yellow_max` (default
  60). Configura una data source por plantilla a monitorear.
- `team_leaderboard` — top N por una métrica. `display_config`:
  `aggregator` (`sum`/`avg`/`max`/`latest`, default `sum`), `limit`
  (default 5, rango [3,20]), `order` (`desc` default / `asc`).

### 8.3 Editar layouts desde Admin

**Dashboards → Department layouts** (o **Team report layouts**) → click
en uno → ver / editar **Sections** y **Widgets** inline.

Para cada widget:

- `chart_type`, `title`, `column_span` (1-12), `chart_height` (px).
- `display_config` (JSON con opciones específicas del tipo).
- **Data sources** inline: plantilla + lista de campos +
  `aggregation` (`latest`, `last_n`, `all`) + `aggregation_param`.

### 8.4 Re-construir layouts del demo

Si los layouts quedaron mal, sobreescribir con:

```bash
python manage.py seed_demo_layouts \
    --club "Universidad de Chile" \
    --category "Primer Equipo"
```

Esto **reconstruye** los 4 layouts de jugador + 4 de equipo. Pasar
`--skip-existing` si quieres conservar los actuales.

---

## 9. Metas y alertas automáticas

### 9.1 Modelo `Goal`

Una `Goal` define un umbral o variación para un jugador específico
sobre un campo de una plantilla:

- `bound`: umbral fijo (peso < 80, IMC ≥ 22).
- `variation`: cambio respecto a una ventana móvil (peso bajó >2 kg
  en últimos 30 días).

Crear desde Admin: **Goals → Goals → Add goal**.

### 9.2 Evaluación

El **Celery beat** corre todos los días a las **05:00 UTC** la tarea
`goals.tasks.evaluate_due_goals`:

1. Recorre todas las metas activas.
2. Para cada una, compara contra los resultados disponibles.
3. Si dispara, crea una `Alert` y dispara el envío de email.

### 9.3 Alertas (`Alert`)

- **Severity**: `info`, `warning`, `critical`.
- **Status**: `open`, `acknowledged`, `resolved`.
- Aparecen en la 🔔 campana del navbar del usuario afectado (médico,
  físico, etc. según el departamento de la plantilla).

### 9.4 Email

Si el worker de Celery está corriendo y `EMAIL_BACKEND` está
configurado:

- Se envía a `DEFAULT_FROM_EMAIL` (en demo) o al destinatario
  configurado (en prod).
- El asunto incluye el nombre del jugador y la severidad.
- El cuerpo incluye link al perfil para "Ver caso".

### 9.5 Forzar evaluación manual

```bash
python manage.py shell -c "
from goals.tasks import evaluate_due_goals
evaluate_due_goals()
"
```

---

## 10. Mantenimiento del contenedor (Railway)

### 10.1 Abrir shell en el contenedor backend

Railway dashboard → servicio **backend** → **Deployments** → último
deploy → **⋯ → Open Shell**.

### 10.2 Comandos útiles

```bash
# Crear superusuario
python manage.py createsuperuser

# Aplicar migraciones nuevas
python manage.py migrate

# Re-popular toda la data demo (clubs + plantillas + resultados +
# layouts) — script idempotente con verificación al final
bash scripts/seed_all.sh

# Borrar TODOS los resultados de exámenes (¡destructivo!)
python manage.py shell -c "from exams.models import ExamResult; ExamResult.objects.all().delete()"

# Resetear la base completa
python manage.py flush --no-input

# Forzar evaluación de metas
python manage.py shell -c "from goals.tasks import evaluate_due_goals; evaluate_due_goals()"
```

### 10.3 Recolección de estáticos (Django Admin CSS/JS)

Se ejecuta automáticamente durante el build del Dockerfile. Si los
estáticos del Admin no cargan en producción, ver §11.2.

### 10.4 Variables de entorno críticas

| Variable                  | Backend | Frontend | Para qué                                   |
|---------------------------|:-------:|:--------:|--------------------------------------------|
| `DJANGO_SECRET_KEY`       | ✓       |          | Cookies de sesión                          |
| `JWT_SECRET`              | ✓       |          | Firmado de tokens JWT                      |
| `DJANGO_ALLOWED_HOSTS`    | ✓       |          | Hosts aceptados                            |
| `CSRF_TRUSTED_ORIGINS`    | ✓       |          | Origins permitidos para POST a `/admin/`   |
| `CORS_ALLOWED_ORIGINS`    | ✓       |          | Origins permitidos por CORS                |
| `POSTGRES_*`              | ✓       |          | Conexión a DB                              |
| `CELERY_BROKER_URL`       | ✓       |          | Redis para tareas                          |
| `AWS_*`                   | ✓       |          | S3 para attachments                        |
| `EMAIL_*`                 | ✓       |          | Envío de alertas                           |
| `FRONTEND_BASE_URL`       | ✓       |          | Links en emails                            |
| `NEXT_PUBLIC_API_URL`     |         | ✓        | URL del backend (build-time, ver §11.4)    |

---

## 11. Solución de problemas

### 11.1 "Login no funciona"

**Síntoma**: usuario ingresa credenciales correctas, recibe error
"credenciales inválidas" o queda en `/login`.

**Posibles causas**:
- El login es por **email**, no por username. Validar el email del
  `User` en Admin.
- El usuario no tiene `StaffMembership` y no es `is_superuser` →
  el guard de ruta lo bota a `/login`. Crear el `StaffMembership` (§6.6).
- El backend rechaza la request por CORS → ver consola del navegador.

### 11.2 "Los estáticos del Django Admin no cargan"

**Síntoma**: `/admin/` se ve sin estilos (HTML plano).

**Causa**: Whitenoise no está sirviendo `/static/`.

**Solución**:
1. Verificar que el Dockerfile del backend ejecuta
   `python manage.py collectstatic --no-input` durante el build.
2. Verificar que `whitenoise.middleware.WhiteNoiseMiddleware` está en
   `MIDDLEWARE` justo después de `SecurityMiddleware`.
3. Re-deploy.

### 11.3 "CSRF verification failed. Request aborted."

**Síntoma**: al hacer POST en cualquier formulario del Admin sale el
error de CSRF.

**Causa**: el dominio del frontend/backend no está en
`CSRF_TRUSTED_ORIGINS`.

**Solución**: en Railway → backend → Variables, agregar:

```
CSRF_TRUSTED_ORIGINS=https://<backend>.up.railway.app,https://<frontend>.up.railway.app
```

(Con `https://`, sin barra final, separados por comas.)

### 11.4 "Frontend apunta a `localhost:8000` en producción"

**Síntoma**: el navegador hace requests a `http://localhost:8000/api`
en lugar del backend de Railway.

**Causa**: `NEXT_PUBLIC_API_URL` no estaba seteada al momento del
build. Next.js inlinea esa variable en el bundle estático.

**Solución**:
1. En Railway → frontend → Variables: setear
   `NEXT_PUBLIC_API_URL=https://<backend>.up.railway.app/api`.
2. **Trigger a redeploy** (no basta con restart — el bundle ya está
   compilado con el valor anterior).
3. Hard-reload en el navegador (Cmd+Shift+R) para limpiar el bundle
   cacheado.

### 11.5 "No aparecen resultados en los dashboards"

**Síntoma**: los widgets dicen "Sin datos" para algunas plantillas.

**Diagnóstico**:

```bash
bash scripts/seed_all.sh
```

El bloque de **verificación** al final del script imprime:

- Plantillas que **no están enlazadas a ninguna categoría** (invisibles
  para el generador).
- Cantidad de resultados por plantilla (con `!` si es 0).
- Layouts presentes por departamento.

**Causa más común**: una plantilla quedó sin
`applicable_categories`. Re-correr el seeder de esa plantilla con
`--all-applicable-categories`, o dejar que `seed_all.sh` lo arregle
automáticamente (paso `ensure_template_categories`).

### 11.6 "Las alertas no llegan por email"

**Diagnóstico**:
1. Verificar que el servicio **worker** de Railway está corriendo
   (logs sin errores).
2. Verificar `EMAIL_BACKEND`. En demo es `console.EmailBackend` —
   los emails se imprimen en los **logs del worker**, no se envían.
   Para producción real cambiar a `smtp.EmailBackend` + credenciales
   SMTP (SES, SendGrid, etc.).
3. Verificar que existe al menos una `Goal` activa que dispare:
   ```bash
   python manage.py shell -c "from goals.models import Goal; print(Goal.objects.filter(is_active=True).count())"
   ```

### 11.7 "Quiero borrar todo y empezar de cero"

```bash
# Backend shell de Railway:
python manage.py flush --no-input
python manage.py createsuperuser
bash scripts/seed_all.sh
```

`flush` borra **todos los datos** pero conserva el schema. Útil para
reset de demo.

### 11.8 "Forkear una plantilla falla con un error de unique constraint"

**Síntoma**: el admin action "Crear nueva versión" devuelve un error
mencionando `exam_tpl_one_active_per_family` o
`exam_tpl_family_version_unique`.

**Causas posibles**:
- **Dos versiones quedaron marcadas como activas** en la misma
  familia (estado corrupto, no debería suceder con el flujo normal).
  Diagnóstico:
  ```bash
  python manage.py shell -c "
  from exams.models import ExamTemplate
  from django.db.models import Count
  bad = ExamTemplate.objects.filter(is_active_version=True).values('family_id').annotate(n=Count('id')).filter(n__gt=1)
  print(list(bad))
  "
  ```
  Fix: marcar manualmente una sola como activa.
- **Concurrencia**: dos admins hicieron fork al mismo tiempo en la
  misma plantilla. Recargar la página y reintentar — el primero ganó.

### 11.9 "Un usuario no puede crear / editar / borrar pero debería"

**Síntoma**: usuario reporta que no le aparecen botones de "+ Agregar",
"Editar" o "Borrar".

**Diagnóstico**:
```bash
docker compose exec backend python manage.py shell -c "
from django.contrib.auth.models import User
u = User.objects.get(email='usuario@club.cl')
print(f'is_superuser={u.is_superuser}')
print(f'groups={[g.name for g in u.groups.all()]}')
print(f'perms={sorted(u.get_all_permissions())[:5]}...')
"
```

**Causas habituales**:
- Está en grupo **Solo Lectura** y debería estar en **Editor**:
  reasignar en `/admin/auth/user/<id>/` → Groups.
- No está en ningún grupo (cuenta nueva post-backfill): asignar a Editor.
- Está bien en Editor pero la acción específica es de contrato:
  los perms de contrato son granulares — chequear "User permissions".

### 11.10 "Un usuario ve cosas que no debería ver (contratos / salarios)"

**Síntoma**: bloque CONTRATO VIGENTE aparece para un usuario que no
debería.

**Diagnóstico**: ese bloque está gateado por `core.view_contract`.
Si lo ve es porque:
- El usuario es superuser (bypass automático).
- Está en un grupo que incluye ese permiso (los grupos seed NO lo
  incluyen — alguien lo agregó manualmente).
- Tiene el permiso asignado directamente en "User permissions".

**Fix**: `/admin/auth/user/<id>/` → User permissions → mover
"core | contract | Can view contract" hacia la izquierda → Save.

### 11.11 "Después de forkear, un dashboard quedó vacío"

**Síntoma**: un widget que mostraba datos antes del fork ahora dice
"Sin datos".

**Causa habitual**: en la nueva versión se eliminó o renombró el
field key que el widget usa.

**Diagnóstico**:
1. Ir al widget en **Dashboards → Widgets**.
2. Mirar los `field_keys` en su `WidgetDataSource`.
3. Compararlos con el `config_schema` de la versión activa (en
   **Exams → Exam templates**).
4. Si el key no existe en la nueva versión, fue removido/renombrado.

**Fixes**:
- (a) Restaurar el field key en la nueva versión (volver atrás).
- (b) Actualizar el widget para usar el nuevo nombre del field.
- (c) Reactivar la versión vieja (si los datos viejos son lo que
  quieres mostrar):
  ```bash
  python manage.py shell -c "
  from exams.models import ExamTemplate
  v1 = ExamTemplate.objects.get(slug='pentacompartimental', version=1)
  v2 = ExamTemplate.objects.get(slug='pentacompartimental', version=2)
  ExamTemplate.objects.filter(pk=v2.pk).update(is_active_version=False)
  ExamTemplate.objects.filter(pk=v1.pk).update(is_active_version=True)
  "
  ```

---

## 12. Glosario

| Término               | Significado                                                                  |
|-----------------------|------------------------------------------------------------------------------|
| **Club**              | Organización deportiva (ej. Universidad de Chile)                            |
| **Categoría**         | Plantel dentro del club (ej. Primer Equipo, Sub-20)                          |
| **Departamento**      | Área funcional (médico, físico, táctico, nutricional, psicosocial)           |
| **Plantilla**         | Formulario configurable para registrar un tipo de evaluación                 |
| **Resultado**         | Una toma de datos: un `ExamResult` enlazado a un jugador y una plantilla     |
| **Episodio**          | Agrupador de resultados de una plantilla episódica (lesión)                  |
| **Stage**             | Etapa dentro de un episodio (`injured`, `recovery`, etc.)                    |
| **Layout**            | Configuración de cómo se ve un dashboard (qué widgets, qué orden, qué datos) |
| **Widget**            | Un gráfico o tabla individual dentro de un layout                            |
| **Meta (Goal)**       | Umbral configurable que dispara alertas automáticas                          |
| **Alerta**            | Notificación generada por una meta o por evento clínico (ej. WADA)           |
| **WADA**              | Lista internacional de sustancias prohibidas en deporte                      |
| **`StaffMembership`** | Modelo que define qué club / categorías / departamentos ve un usuario        |
| **`is_locked`**       | Bandera que protege una plantilla con datos cargados de cambios destructivos |
| **`is_episodic`**     | Bandera que activa el agrupamiento de resultados en Episodios                |
| **`family_id`**       | UUID compartido por todas las versiones de la misma plantilla                |
| **`is_active_version`** | Bandera: exactamente una versión por familia está activa (recibe escrituras nuevas) |
| **Fork (de plantilla)** | Crear una nueva versión de una plantilla cuyo schema necesita cambiar      |
| **Reference band**    | Rango clínico definido en `TemplateField.reference_ranges`. Cada banda tiene `label`, `min`/`max`, color opcional |
| **Hint dinámico**     | Texto debajo del input numérico que muestra la banda activa según el valor escrito |
| **Editor / Solo Lectura** | Django Groups que definen si un usuario puede mutar (CRUD) o solo ver. Ortogonales a `StaffMembership` |
| **Permiso granular**  | Perm asignado directamente a un usuario (no vía grupo). Hoy: `core.view_contract` y CRUD de Contract |
| **`@require_perm`**   | Decorator backend que retorna 403 cuando el user no tiene el perm; superusers bypassean |

---

---

## 13. Comandos avanzados — features clínicos

### 13.1 Alertas por banda (BAND alerts)

Sembrar reglas automáticas a partir de las `reference_ranges` clínicas
de cada campo numérico:

```bash
docker compose exec backend python manage.py seed_band_alerts
# Opcional:
#   --dry-run                  Reporta sin escribir
#   --no-backfill              Solo crea reglas; no genera alertas
#   --include-all-versions     Siembra en versiones no-activas también
#   --severity {info|warning|critical}   Default: critical
```

Idempotente — re-córrelo después de:
- Agregar plantillas con bandas
- Editar `reference_ranges` en algún campo
- Forkear plantillas (`--include-all-versions` cubre versiones nuevas)

**Cómo se detecta la banda "roja"**: por defecto, la banda con
mayor "rojez" (`R - max(G, B) > 50`). Override explícito: agregar
`"alert": true` en la(s) banda(s) en el JSON de `reference_ranges`.

**Auto-resolve**: cuando un jugador entra una lectura fuera de la
banda alert, las alertas BAND activas de esa regla se marcan como
`RESOLVED`. Solo BAND tiene auto-resolve — BOUND y VARIATION
mantienen su comportamiento de "no se autocierran".

### 13.2 Plantillas médicas nuevas

```bash
# Hoja diaria de tratamientos manuales (kinesiología, quiropráctica, ...)
docker compose exec backend python manage.py seed_molestias \
    --create-if-missing --department-slug medico \
    --all-applicable-categories --club "Universidad de Chile"

# Cuestionario diario de bienestar (5 Likert 1-5 + total calculado)
docker compose exec backend python manage.py seed_check_in \
    --create-if-missing --department-slug medico \
    --all-applicable-categories --club "Universidad de Chile"

# Re-sembrar las reglas BAND ahora que Check-IN tiene bandas:
docker compose exec backend python manage.py seed_band_alerts
```

### 13.3 GPS por partido — backfill de event_id

Cuando una plantilla tiene `link_to_match=True`, todo `ExamResult` que
se cargue contra ella requiere un `event` vinculado. Para datos
históricos que se guardaron sin evento:

```bash
docker compose exec backend python manage.py backfill_match_events \
    --window-days 3                 # busca evento ±3 días del recorded_at
    --create-synthetic              # si no hay match cercano, crea uno
    --dry-run                       # reporta sin escribir
```

Es seguro re-correrlo: solo afecta resultados con `event=None`.

### 13.4 Selector de partido (match_selector_config)

Para que un team report use selector de partido (no rango de fechas),
editar el `TeamReportLayout.match_selector_config` desde Django Admin
(`Dashboards → Team report layouts → <Departamento> → Team report —
Layout`):

```json
{
  "enabled": true,
  "event_type": "match",
  "required": true,
  "label": "Partido",
  "show_recent": 12
}
```

- `enabled=false` o `{}`: comportamiento clásico (date range)
- `required=true`: si la URL no trae `?match_id=`, auto-selecciona el
  más reciente
- `event_type`: filtra `Event.event_type` — útil si querés selector
  de sesiones de entrenamiento (`"training"`) en lugar de partidos

El layout `Físico` del seed demo ya viene con esto activado.

### 13.5 Re-sembrar layouts demo después de cambios

```bash
docker compose exec backend python manage.py seed_demo_layouts
```

Re-construye los 4 layouts (Médico / Físico / Táctico / Nutricional)
× 2 vistas (Player / Team). **Borra los widgets existentes y los
re-crea desde el spec en código** — usar `--skip-existing` para
preservar layouts que ya fueron editados manualmente.

### 13.6 Datos falsos completos para demo

```bash
# 1) Plantillas básicas
docker compose exec backend python manage.py seed_pentacompartimental --create-if-missing ...
docker compose exec backend python manage.py seed_lesiones --create-if-missing ...
docker compose exec backend python manage.py seed_ck ...
# ... etc. (ver § 7 para listado completo)

# 2) Las plantillas médicas nuevas
docker compose exec backend python manage.py seed_molestias ...
docker compose exec backend python manage.py seed_check_in ...

# 3) Reset + cadencia semanal de fake data (+ Molestias esporádicas
#    + Check-IN diario 30 días + pre-creación de match events)
docker compose exec backend python manage.py seed_fake_exams --reset

# 4) Reglas BAND derivadas + backfill de alertas
docker compose exec backend python manage.py seed_band_alerts

# 5) Layouts demo
docker compose exec backend python manage.py seed_demo_layouts
```

---

**Última actualización**: ver `git log MANUAL_ADMIN.md`. Este manual
debería actualizarse cuando: se agreguen nuevas pestañas en el
sidebar, cambien los slugs de departamentos, se agreguen tipos de
gráficos, o cambie el flujo de alertas.
