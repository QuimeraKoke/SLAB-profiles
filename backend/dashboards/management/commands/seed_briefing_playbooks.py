"""Seed research-grounded "briefing playbooks" into each department's
InsightAgent knowledge base.

Each playbook is a set of decision rules (señal → acción · prioridad ·
responsable · CTA) distilled from the sports-science literature, used by
the Centro de mando Briefing to turn live squad data into ranked,
actionable recommendation cards. The numbers themselves come from the
live data / templates (not hardcoded here), per the reference-layer design.

Idempotent: replaces any existing "## Playbook de briefing" section in the
agent's knowledge, preserving the rest. Run:

    docker compose exec backend python manage.py seed_briefing_playbooks
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

_MARKER = "## Playbook de briefing"

# key (InsightAgent.key == department slug) → playbook markdown.
PLAYBOOKS: dict[str, str] = {
    "fisico": """## Playbook de briefing — Físico

### Señales prioritarias
- ACWR en zona de riesgo (sobre el techo del *sweet-spot*) → reducir carga aguda 48 h, sustituir trabajo de alta velocidad por carga aeróbica controlada · prioridad alta · responsable Preparador físico · CTA "Ajustar microciclo"
- Pico súbito de carga HSR sobre el techo semanal → capar exposición de alta velocidad esta sesión y revisar la progresión semanal · prioridad alta · responsable Preparador físico · CTA "Capar HSR"
- Salto de distancia de sprint respecto a la media de 4 semanas → verificar contexto (partido vs entrenamiento) y diferir nuevas exposiciones máximas · prioridad alta · responsable Preparador físico · CTA "Revisar sprint"
- Asimetría isquiosural marcada (Nordic / isométrica prona) → programar trabajo excéntrico unilateral del lado débil y reevaluar en 2–3 semanas · prioridad alta · responsable Readaptador · CTA "Plan excéntrico"
- Caída de fuerza Nordic absoluta vs línea base individual → marcar como factor de riesgo modificable; reforzar excéntricos y vigilar exposición a sprint · prioridad media · responsable Readaptador · CTA "Reforzar Nordic"
- Descenso de CMJ por sobre el cambio mínimo significativo (~5%) → señal de fatiga neuromuscular; aligerar pliometría/velocidad y priorizar recuperación · prioridad media · responsable Preparador físico · CTA "Bajar carga NM"
- Monotonía / strain semanal elevados → introducir variación e incrementar contraste duro/suave en el microciclo · prioridad media · responsable Preparador físico · CTA "Variar microciclo"
- Acel/desac ≥3 m/s² acumulados muy por sobre lo habitual → vigilar carga mecánica; gestionar densidad de tareas con cambios de dirección · prioridad media · responsable Preparador físico · CTA "Gestionar mecánica"
- Jugador en RTP que aún no alcanza su carga crónica de referencia → no habilitar para competir; continuar progresión gradual de exposición · prioridad alta · responsable Readaptador · CTA "Mantener fase RTP"
- Déficit de velocidad máxima vs histórico individual → investigar fatiga residual o estado isquiosural antes de tareas de máxima velocidad · prioridad baja · responsable Preparador físico · CTA "Revisar Vmáx"

### Notas de interpretación
- ACWR: cargas agudas muy por encima de la crónica se asocian a 2–7× más lesiones; el *sweet-spot* se sitúa en ~0,8–1,3 y el riesgo escala sobre ~1,5 (Gabbett; Hulin; Duhig 2016 para spikes de HSR). Interpretar con carga crónica suficiente como amortiguador.
- Asimetría / fuerza isquiosural: la debilidad excéntrica es el factor de riesgo modificable mejor documentado para lesión isquiosural (Opar, Bourne, Timmins). Asimetrías persistentes >10–15% señalan déficit unilateral; combinar con historial e HSR.
- Exposición a alta velocidad: el HSR/sprint es protector cuando es consistente y graduado (Malone); el peligro está en el *salto agudo*, no en el volumen per se (Buchheit).
- CMJ como detector de fatiga: cambios reales requieren superar el cambio mínimo significativo (~5%); la fatiga neuromuscular suele tocar fondo a 48–72 h post-partido (Bourdon et al. 2017).
- Monotonía y strain: superar umbrales individuales de strain predice enfermedad/lesión mejor que la carga absoluta; buscar variación intra-microciclo (Foster).
- Reintroducción de carga en RTP: restaurar la carga crónica de carrera antes de competir, progresando de control a caos (Taberner, control-chaos continuum).""",

    "medico": """## Playbook de briefing — Médico

### Señales prioritarias
- Episodio de lesión abierto sin fecha estimada de retorno → forzar definición de fecha objetivo y criterios de alta · prioridad alta · responsable Médico · CTA "Definir RTP"
- Estimación de retorno vencida con episodio aún abierto → reevaluar etapa y plan; descartar recaída o complicación · prioridad alta · responsable Médico · CTA "Reevaluar"
- Jugador en reintegración con test RTP final pendiente → bloquear disponibilidad hasta completar batería objetiva (fuerza, asimetría, carga) · prioridad alta · responsable Médico · CTA "Agendar test RTP"
- Test RTP con asimetría interlimb >10% o déficit de fuerza → no habilitar; extender reintegración · prioridad alta · responsable Médico · CTA "Mantener en reintegración"
- CK elevado persistente sobre baseline individual → modular carga, diferir entrenamiento de alta intensidad, revisar recuperación · prioridad media · responsable Médico · CTA "Modular carga"
- Molestia recurrente en la misma región corporal (≥3 registros) → evaluar lesión subclínica antes de que escale a episodio · prioridad media · responsable Kinesiólogo · CTA "Evaluar región"
- Aumento de frecuencia de molestias en bloque de carga alta → cruzar con plan de carga; ajustar progresión de reintegración · prioridad media · responsable Kinesiólogo · CTA "Revisar carga"
- Medicación con bandera WADA (prohibida) sin TUE vigente → suspender/sustituir o iniciar TUE de inmediato · prioridad alta · responsable Médico · CTA "Gestionar TUE"
- Medicación que requiere TUE marcada "pendiente" → confirmar solicitud y plazos · prioridad alta · responsable Médico · CTA "Verificar TUE"
- Jugador marcado "disponible" sin cierre formal del episodio → cerrar episodio o revertir estado; evitar alta administrativa sin clínica · prioridad media · responsable Médico · CTA "Cerrar episodio"
- Reintegración temprana retornando a carga competitiva completa → verificar progresión gradual de carga antes de exposición total · prioridad media · responsable Kinesiólogo · CTA "Graduar exposición"

### Notas de interpretación
- La decisión de RTP no es binaria: aplicar el modelo de 3 pasos (estado de salud → riesgo de la actividad → tolerancia al riesgo, Creighton & Shrier 2010; marco StARRT, Shrier 2015), con decisión compartida.
- En isquiotibiales, hasta ~67% de jugadores presentan déficit de fuerza >10% al alta; usar criterios objetivos (fuerza, asimetría, dolor en extensión activa) y no solo tiempo: el RTP precoz se asocia a mayor reincidencia.
- El CK refleja daño/carga muscular pero tiene alta variabilidad: interpretar contra baseline individual y en ventana estandarizada (pico ~24–48 h), siempre como parte de una batería, nunca aislado.
- Cuantificar la relación carga aguda:crónica (~0,8–1,3, Blanch & Gabbett 2016) para confirmar que el jugador toleró la carga antes de competir.
- La reincidencia domina la epidemiología: las lesiones isquiosurales son ~24% del total en fútbol de élite (Ekstrand, UEFA Elite Club Injury Study); las primeras semanas de reintegración son las de mayor riesgo.
- Bajo responsabilidad objetiva (strict liability) de WADA, la mera presencia de una sustancia prohibida es infracción; contrastar toda medicación con la Lista de Prohibiciones vigente y contar con TUE aprobada antes del uso.""",

    "nutricional": """## Playbook de briefing — Nutrición

### Señales prioritarias
- Densidad urinaria sobre el umbral de deshidratación (cribado pre-entreno/pre-partido) → rehidratar antes de iniciar la sesión y reevaluar · prioridad alta · responsable Nutricionista · CTA "Rehidratar y reevaluar"
- Densidad urinaria limítrofe sostenida en varios cribados → ajustar la pauta diaria de líquidos y educar al jugador · prioridad media · responsable Nutricionista · CTA "Ajustar pauta hídrica"
- Aumento sostenido de la sumatoria de pliegues → revisar balance energético y carga; plan de recomposición · prioridad alta · responsable Nutricionista · CTA "Plan recomposición"
- % grasa (Faulkner) fuera del rango ISAK/Holway de referencia → contextualizar vs norma posicional y definir objetivo individual · prioridad media · responsable Nutricionista · CTA "Definir objetivo"
- Caída de masa muscular con pérdida de peso → descartar baja disponibilidad energética (LEA); recalcular requerimientos · prioridad alta · responsable Nutricionista · CTA "Evaluar disponibilidad energética"
- Tendencia de peso fuera del objetivo pre-partido → ajustar fueling y timing de comidas previas · prioridad alta · responsable Nutricionista · CTA "Ajustar fueling match-day"
- Masa adiposa al alza con masa muscular estable → periodizar carbohidratos según la carga semanal · prioridad media · responsable Nutricionista · CTA "Periodizar CHO"
- Sin medición ISAK reciente (dato antropométrico vencido) → agendar control con antropometrista acreditado · prioridad baja · responsable Nutricionista · CTA "Agendar ISAK"

### Notas de interpretación
- Hidratación: ACSM y NATA fijan euhidratación en densidad urinaria ≤1.020; valores superiores en el cribado pre-esfuerzo indican deshidratación a corregir antes de entrenar (Sawka et al. 2007; Casa et al. 2000). Es tamizaje, no diagnóstico único.
- Cadencia antropométrica: monitorizar composición por bloques (no a diario); el ISAK exige TEM <5% y la fiabilidad depende del antropometrista, por lo que conviene mantener el mismo evaluador.
- Norma posicional: interpretar pliegues y % grasa contra referencias ISAK/Holway estratificadas por posición y sexo.
- Tendencia sobre punto único: priorizar la trayectoria (sumatoria de pliegues, masa adiposa, peso) por encima de un dato aislado; un cambio menor al error técnico no es señal clínica.
- Fueling y periodización: el consenso IOC 2024 recomienda periodizar energía y carbohidratos según la carga y vigilar la baja disponibilidad energética (LEA).""",

    "psicosocial": """## Playbook de briefing — Psicosocial / Bienestar

### Señales prioritarias
- Total Bienestar en banda baja sostenido (≥3 días) → activar conversación individual y revisar carga reciente · prioridad alta · responsable Ciencias del deporte · CTA "Agendar 1:1"
- Caída marcada de sueño vs baseline individual → indagar higiene de sueño, viajes y horarios; ajustar sesión matinal · prioridad alta · responsable Ciencias del deporte · CTA "Revisar sueño"
- Caída marcada de ánimo vs baseline individual → cribado psicosocial breve; descartar estresor extradeportivo · prioridad alta · responsable Psicólogo · CTA "Cribar ánimo"
- Fatiga + DOMS elevados tras doble sesión o microciclo intenso → considerar descarga/recovery; cruzar con carga (sRPE) · prioridad alta · responsable Ciencias del deporte · CTA "Modular carga"
- Estrés elevado persistente con ánimo a la baja → posible overreaching no funcional / burnout temprano; derivar · prioridad alta · responsable Psicólogo · CTA "Derivar"
- Divergencia individuo vs media del equipo (outlier) → focalizar al jugador aunque el índice grupal esté "bueno" · prioridad media · responsable Ciencias del deporte · CTA "Marcar jugador"
- Tendencia descendente del índice de equipo en el microciclo → revisar planificación de carga colectiva pre-partido · prioridad media · responsable Ciencias del deporte · CTA "Revisar microciclo"
- DOMS localizado y recurrente en un jugador → screening físico; coordinar con kinesiología · prioridad media · responsable Ciencias del deporte · CTA "Coordinar kine"
- Baja tasa de respuesta del cuestionario → recordatorio y refuerzo de adherencia; los datos faltantes invalidan promedios · prioridad media · responsable Ciencias del deporte · CTA "Reforzar adherencia"

### Notas de interpretación
- Las medidas subjetivas reflejan carga aguda y crónica con mayor sensibilidad y consistencia que los marcadores objetivos (Saw, Main & Gastin 2016): base para priorizarlas.
- El cuestionario sigue la lógica Hooper & Mackinnon (1995): sueño, fatiga, estrés y DOMS suman un índice; SLAB añade ánimo. Interpretar el total y las dimensiones por separado.
- Usar baselines individuales (desviación vs media móvil del propio jugador), no cortes absolutos: el cambio relativo intrasujeto detecta fatiga mejor que un umbral fijo (McLean/Coutts).
- El sueño es el principal motor de recuperación; su déficit deteriora rendimiento, cognición e inmunidad y aumenta el riesgo lesional (Fullagar et al. 2015): tratar caídas de sueño como señal temprana.
- Distinguir overreaching funcional (mejora tras descanso) de no funcional / OTS, donde estrés y ánimo deprimidos persisten pese al descanso (Meeusen et al. 2013); escalar ante tendencias, no datos aislados.
- La adherencia es un problema de calidad de dato: baja tasa de respuesta o respuestas planas sesgan los promedios (Saw et al. 2015).""",

    "tactico": """## Playbook de briefing — Táctico

### Señales prioritarias
- Acumulación alta de minutos en ventana congestionada → proponer rotación o gestión de carga para el próximo partido · prioridad alta · responsable Cuerpo técnico · CTA "Planificar rotación"
- Jugador clave sin rotación en microciclo de doble partido (<72–96 h) → evaluar descanso o minutaje parcial · prioridad alta · responsable Cuerpo técnico · CTA "Revisar titularidad"
- Caída de demandas de alta velocidad (HSR/sprints) vs el perfil propio del jugador → contrastar con recuperación y minutos recientes; descartar fatiga residual · prioridad alta · responsable Cuerpo técnico · CTA "Abrir perfil GPS"
- Pico agudo de HSR/sprints respecto a la carga crónica del jugador → atenuar la carga de entrenamiento siguiente · prioridad alta · responsable Cuerpo técnico · CTA "Ajustar carga"
- Desbalance de minutaje por línea/posición → redistribuir minutos dentro de la línea afectada · prioridad media · responsable Cuerpo técnico · CTA "Equilibrar línea"
- Caída marcada de distancia/HSR en 2.ª mitad vs 1.ª recurrente → revisar acondicionamiento o el momento de sustitución · prioridad media · responsable Cuerpo técnico · CTA "Ver split por tiempo"
- Citaciones consecutivas sin minutos → confirmar disponibilidad real y rol planificado · prioridad baja · responsable Cuerpo técnico · CTA "Revisar citaciones"
- Acumulación de tarjetas con riesgo de suspensión inminente → planificar alternativa por posición · prioridad media · responsable Cuerpo técnico · CTA "Preparar reemplazo"
- Dependencia excesiva de un titular (cuota de minutos muy alta) → diseñar plan de relevo gradual · prioridad media · responsable Cuerpo técnico · CTA "Plan de relevo"

### Notas de interpretación
- Las demandas de carrera son específicas por posición: laterales, mediocampistas y extremos cubren más HSR y sprint que los centrales (Di Salvo; Bradley). Comparar contra el estándar de la línea, no un umbral único.
- La congestión de calendario (≥2 partidos/semana) eleva la incidencia de lesión pese a que el rendimiento físico se mantenga; la rotación es la mitigación principal (Dupont et al. 2010).
- El rendimiento físico no anticipa la lesión en congestión: 72–96 h bastan para recuperar rendimiento, pero no para normalizar el riesgo. No esperar a ver caídas para rotar.
- Leer el GPS de cada partido contra el perfil propio del jugador (baseline individual), no contra la media del plantel.
- Los picos agudos de HSR/sprint sobre la carga crónica se asocian a mayor riesgo (ACWR; Malone); usar como alerta de ajuste, no como diagnóstico aislado.
- La fatiga aparece intra-partido: menor HSR y distancia en los últimos 15 min; la caída 2.ª vs 1.ª mitad es señal útil de gestión de minutaje (Carling).""",
}


class Command(BaseCommand):
    help = "Seed research-grounded briefing playbooks into department InsightAgents."

    def handle(self, *args, **opts):
        from dashboards.models import InsightAgent

        for key, playbook in PLAYBOOKS.items():
            agent = InsightAgent.objects.filter(key=key).first()
            if agent is None:
                self.stdout.write(self.style.WARNING(
                    f"No InsightAgent with key='{key}' — run seed_insight_agents first."
                ))
                continue
            base = (agent.knowledge or "").split(_MARKER)[0].rstrip()
            agent.knowledge = (base + "\n\n" + playbook).strip() if base else playbook
            agent.save()  # bumps revision + config_fingerprint → reports/briefing regenerate
            self.stdout.write(self.style.SUCCESS(
                f"[{key}] playbook seeded ({len(playbook)} chars; agent rev {agent.revision})."
            ))
