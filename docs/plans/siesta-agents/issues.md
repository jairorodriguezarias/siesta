# Issues: agentes especializados, revisión independiente y selección de modelos

Estados: `In progress`, `Pending`, `Blocked` o `Done`. Una issue `Done` debe
incluir evidencia verificable y referencias a tests o documentación.

## Issue #1: Definir agentes y conectarlos al pipeline

**Estado:** Done
**Dependencias:** ninguna.

Crear un registro de agentes con identidad, definición Markdown, rol de modelo,
herramientas permitidas, contexto admisible y formato de respuesta. Conectar
inicialmente los roles existentes; los nuevos especialistas se añaden en sus
issues.

**Aceptación:**

- Cada llamada identifica al agente y carga su definición real.
- Python aplica permisos; una declaración textual no habilita herramientas.
- Una definición requerida ausente o inválida produce un error explícito.
- Las llamadas aisladas reciben la definición directamente, sin descubrimiento
  implícito de instrucciones del proyecto.

**Evidencia de verificación:**

- `tests.test_agents`: identidad y definición, errores de carga, permisos,
  contexto, registro de llamadas y selección de fábrica.
- `tests.test_pi`, `tests.test_skill_context`, `tests.test_launcher` y
  `tests.test_native_isolation`: compatibilidad de argumentos, aislamiento,
  habilidades y allowlist del worker con el parser nativo de Pi.
- `python -B -m unittest discover -s tests -v`: suite completa aprobada usando
  un entorno virtual temporal con `pytest 9.2.0`.
- La primera ejecución con el Python del sistema no pudo completar pruebas de
  proyectos porque ese intérprete no tenía `pytest`; no se instaló en el entorno
  global ni se añadió al repositorio.

## Issue #2: Resolver modelos por fase y agente

**Estado:** Done
**Dependencias:** #1.

Introducir configuración de ejecución seleccionable por CLI y frontal, con
selecciones por fase y excepciones por agente.

**Aceptación:**

- Prioridad: selección de fase y agente → selección de fase → configuración
  actual del rol.
- Entrevista, especificación y planificación pueden usar modelos distintos.
- La selección efectiva se guarda con el proyecto y se reutiliza al reanudar.
- Cambiar una selección no altera llamadas activas ni la configuración global.
- Las configuraciones actuales de tres roles siguen funcionando.

**Verificación:** precedencia, rutas heredadas, selección efectiva en Pi,
reanudación y aislamiento entre proyectos.

**Evidencia de verificación:**

- `tests.test_model_selection`: prioridad de ruta, selección efectiva en los
  argumentos de Pi, defaults heredados, validación y persistencia del proyecto.
- `tests.test_integration.PipelineRun.test_cli_saves_and_uses_phase_agent_model_selection`:
  ejecución CLI con rutas seleccionadas y guardadas.
- `tests.test_web_runner` y `tests.test_web`: validación y transferencia de
  selección por la API local; los controles del navegador corresponden a I15.
- `PYTHONPATH=tests python -B -m unittest test_iterations -v`: reanudación y
  compatibilidad con iteraciones existentes.
- `python -B -m unittest discover -s tests -v`: suite completa aprobada con el
  entorno virtual temporal que proporciona `pytest 9.2.0`.
- `docs/model-selection.md`: formato, precedencia, CLI y API.

## Issue #3: Crear el mecanismo común de revisión y corrección

**Estado:** Done
**Dependencias:** #1–#2.

Implementar informes estructurados, validación de resultados, seguimiento de
hallazgos, límites y conservación de evidencia.

**Aceptación:**

- Cada hallazgo identifica gravedad, requisito o ubicación, evidencia y
  corrección solicitada.
- Respuestas inválidas, revisores fallidos o evidencia insuficiente impiden
  aprobar.
- Modo normal: máximo tres rondas, dos reparaciones y una ronda limpia para
  aprobar.
- Modo profundo: máximo cinco rondas y dos rondas limpias consecutivas sobre la
  misma versión.
- Un revisor fallido dispone de un reintento. Ampliar contexto consume ese
  mismo reintento.
- El autor puede aportar contraevidencia; una evaluación independiente resuelve
  la disputa.
- Las correcciones repiten las comprobaciones afectadas.

**Verificación:** falsos positivos, informes contradictorios, reincidencias,
agotamiento de intentos y conservación de límites al reanudar.

**Evidencia de verificación:**

- tests.test_reviews: estructura estricta y evidencia de informes, rechazo de
  respuestas inválidas, reintento único, ampliación de contexto, límites
  normal/profundo, reanudación tras interrupción, disputas, reparaciones y
  repetición obligatoria de comprobaciones afectadas.
- python -B -m unittest discover -s tests -v: 373 tests aprobados con el
  entorno virtual temporal que proporciona pytest 9.2.0.
- docs/review-policy.md: esquema de informe, políticas y transiciones.
- La capa común ya está lista; los flujos finales y por issue se conectan en
  I04 e I05.

## Issue #4: Sustituir la revisión final por especialistas independientes

**Estado:** Done
**Dependencias:** #3.

Incorporar un revisor de integración y requisitos y otro de calidad del código.

**Aceptación:**

- Ambos reciben contratos, código y evidencia; no reciben historial del autor ni
  justificaciones informales.
- Ambos deben aprobar antes del proxy existente.
- Las correcciones reciben tests y una nueva revisión.
- La aprobación queda vinculada al contenido y configuración revisados.

**Verificación:** rechazo de especialista y proxy, reparación satisfactoria y
cambios posteriores a una aprobación.

**Evidencia de verificación:**

- `tests.test_agents.AgentPermissions.test_review_specialists_are_separate_tool_free_agents`:
  ambos agentes tienen identidades y permisos independientes sin herramientas.
- `tests.test_reviews.ReviewBudgets.test_required_reviewer_group_needs_each_independent_pass`,
  `test_external_approval_waits_until_both_specialists_pass` y
  `test_external_rejection_becomes_a_repairable_finding`: rechazo hasta que
  ambos especialistas aprueben y adjudicación del proxy. La reanudación después
  de evidencia insuficiente conserva la ronda y el reintento asignado.
- `tests.test_recovery_gates.RecoveryGates.test_review_repairs_are_reviewed_and_approved_before_completion`
  y `test_unapproved_or_unusable_review_cannot_close_review_phase`: reparación,
  nueva revisión y rechazo de informes inválidos o proxy no aprobado.
- `tests.test_skill_context.SkillContext.test_review_proxy_receives_intent_specification_and_decision_details`
  `test_review_configuration_fingerprint_includes_specialist_route`,
  `test_review_repair_can_add_the_project_first_test_suite`,
  `test_expanded_review_context_contains_real_additional_source` y
  `test_review_context_retry_fails_when_no_more_evidence_exists`: contexto
  contractual y de pruebas, reparaciones con tests, ampliación real del
  contexto, y vínculo de aprobación con la ruta seleccionada.
- `tests.test_iterations.IterationRuns.test_missing_verification_fingerprint_reuses_only_the_bound_review`
  y `tests.test_recovery_gates.RecoveryGates.test_resume_retries_pending_issue_from_every_later_checkpoint`:
  reanudación vinculada al contenido revisado; los cambios vuelven a pasar por
  revisión y verificación.
- `tests.test_integration`: el proxy se consulta solo tras ambos informes; los
  proyectos con regresiones rojas siguen a verificación, que conserva el
  resultado `UNVERIFIED`.
- `python -B -m unittest discover -s tests -v`: suite completa, 384 tests,
  aprobada con el entorno virtual temporal que proporciona pytest.
- `docs/review-policy.md`: definición de revisores independientes, contexto,
  proxy, reparaciones y vínculo de aprobación.

## Issue #5: Revisar cada issue antes de completarla

**Estado:** Pending
**Dependencias:** #3–#4.

Introducir revisión independiente después de los tests y antes del registro de
finalización.

**Aceptación:**

- El revisor examina cambios, contexto de código, tests y requisitos de la
  issue.
- Comprueba que se conserva el trabajo anterior sin exigir funcionalidades
  futuras.
- Una issue rechazada no se completa ni sirve de base a la siguiente.
- Las reparaciones respetan los límites y usan la recuperación existente.
- Las issues declaran si requieren revisión adicional por autenticación,
  migraciones o interfaces públicas; el diseño valida esa decisión.

**Verificación:** defecto con tests verdes, reparación con regresión,
recuperación de archivos y reanudación sin commits duplicados.

## Issue #6: Revisar la intención al finalizar la entrevista

**Estado:** Pending
**Dependencias:** #3.

Añadir un crítico que compare la intención candidata con la petición original y
las respuestas explícitas.

**Aceptación:**

- Funciona en entrevista interactiva y en cierre autónomo.
- Detecta requisitos omitidos, contradicciones y ampliaciones injustificadas.
- Corrige automáticamente lo que resuelva la evidencia existente.
- Una decisión nueva que corresponda al usuario bloquea la especificación y se
  registra.
- Conserva la confirmación de intención del flujo interactivo.

**Verificación:** requisito perdido, alcance inventado, objeción resuelta y
cierre autónomo bloqueado.

## Issue #7: Ampliar la revisión del diseño y reparar el plan

**Estado:** Pending
**Dependencias:** #3, #6.

Reunir comprensión, crítica de simplicidad y preparación para implementar.

**Aceptación:**

- Cada requisito tiene una issue y estrategia de comprobación.
- El planificador puede proponer reparaciones documentales dentro de la
  intención aprobada.
- Python valida, guarda y registra revisiones antes de volver a evaluarlas.
- Estas reparaciones solo ocurren antes de implementar; los trabajadores no
  pueden alterar especificación ni plan.

**Verificación:** requisitos sin cobertura, dependencia imposible, reparación
válida, cambio de alcance y límites agotados.

## Issue #8: Guardar propuestas de aprendizaje y fijar versiones de skills

**Estado:** Pending
**Dependencias:** #1–#2.

Separar observaciones de KB, propuestas de modificación y versiones activas.

**Aceptación:**

- Cada propuesta conserva contenido anterior, nuevo, motivo y evidencia.
- Una ejecución usa versiones fijadas de sus skills también al reanudar.
- Las propuestas no sustituyen inmediatamente archivos activos.
- El aprendizaje solo modifica skills de fábrica.

**Verificación:** modificación durante una ejecución, reanudación con versiones
fijadas y propuestas a skills no autorizadas.

## Issue #9: Ejecutar escenarios de prueba de skills

**Estado:** Pending
**Dependencias:** #1.

Añadir lector y ejecutor de `test_scenarios.yaml`, integrado con la evaluación
existente. YAML será dependencia de desarrollo, no requisito para usar el
frontal.

**Aceptación:**

- Escenarios con identificador, skill, entradas y comprobaciones explícitas.
- Rechazo de estructuras o comprobaciones desconocidas.
- Resultados separados para formato, ejecución simulada y evaluación real.
- Las afirmaciones sobre herramientas requieren registros de ejecución.

**Verificación:** YAML incorrecto, aserción desconocida, respuesta que afirma
ejecutar sin hacerlo y escenario válido.

## Issue #10: Probar el protocolo de aprobación

**Estado:** Pending
**Dependencias:** #9.

Añadir `TEST.md` y escenarios ejecutables para `human-proxy`.

**Aceptación:**

- Cubrir aprobación, rechazo, petición de revisión y respuesta ambigua.
- Ejemplos dentro de bloques de código nunca autorizan acciones.
- El proxy recibe intención, decisiones y contexto pertinente.

**Verificación:** escenarios conectados al ejecutor y regresiones del protocolo.

## Issue #11: Probar el ejecutor de issues

**Estado:** Pending
**Dependencias:** #5, #9.

Añadir el paquete de pruebas de `issue-executor`.

**Aceptación:**

- Cubrir implementación, consulta, solicitud de aprobación, reintento y bloqueo.
- Narrar acciones no equivale a ejecutarlas.
- La finalización exige evidencia real y respeta documentos protegidos.

**Verificación:** escenarios del protocolo y ejecución controlada en proyecto
temporal.

## Issue #12: Probar el aprendizaje y sus propuestas

**Estado:** Pending
**Dependencias:** #8–#9.

Añadir el paquete de pruebas de `factory-learner`.

**Aceptación:**

- Cubrir propuestas completas, incompletas, contradictorias y sin evidencia.
- Preservar ejemplos de skills sin interpretarlos como acciones.
- Detectar propuestas que debiliten verificaciones o atribuyan herramientas
  inexistentes.

**Verificación:** escenarios del aprendiz y regresiones del parser.

## Issue #13: Revisar y activar automáticamente mejoras de skills

**Estado:** Pending
**Dependencias:** #3, #8, #12.

Incorporar revisor independiente y validación antes de activar una mejora.

**Aceptación:**

- El revisor compara versiones anterior y candidata con la evidencia.
- La candidata supera escenarios pertinentes, incluida evaluación real de
  comportamiento cuando cambien instrucciones.
- Sin validación suficiente, permanece pendiente.
- La activación es atómica, conserva la versión anterior y afecta ejecuciones
  futuras.
- Un aprendizaje rechazado no cambia el veredicto del producto verificado.

**Verificación:** aceptación, rechazo, evaluación fallida, conflicto de versión
y recuperación ante interrupción.

## Issue #14: Descubrir y validar modelos Ollama

**Estado:** Pending
**Dependencias:** #2.

Añadir al backend catálogo de modelos locales y cloud, unido al perfil Pi de
Siesta.

**Aceptación:**

- Mostrar identificador exacto, origen conocido, registro en Pi y estado de
  validación.
- Distinguir modelo anunciado, instalado y comprobado.
- Las credenciales permanecen en el servidor.
- Comprobación explícita de compatibilidad; las pruebas de herramientas usan un
  directorio temporal.
- Modelos con configuración insuficiente quedan pendientes de preparación.
- Un error nunca sustituye silenciosamente el modelo.

**Verificación:** Ollama no disponible, catálogo mixto, fallo de autenticación,
modelo sin registrar y herramientas incompatibles.

## Issue #15: Elegir modelos desde el frontal

**Estado:** Pending
**Dependencias:** #2, #14.

Añadir controles a «Nuevo proyecto» y reanudación, conservando la estética
actual.

**Aceptación:**

- Selector por fase y opciones avanzadas por agente.
- Etiquetas Local/Cloud y selecciones heredadas visibles.
- La elección llega a la llamada real de Pi.
- Reanudar recupera configuración; un cambio crea revisión e invalida
  aprobaciones afectadas.
- Controles bloqueados durante una ejecución activa.
- Snake, entrevista, recarga y vista móvil mantienen su comportamiento.

**Verificación:** navegador con modelos distintos por fase, errores,
reanudación y captura de rutas utilizadas.

## Issue #16: Mostrar agentes, revisiones y consumo de ejecución

**Estado:** Pending
**Dependencias:** #3, #15.

Ampliar estado del pipeline y ventana de actividad.

**Aceptación:**

- Mostrar fase, agente, modelo, ronda y hallazgos bloqueantes.
- Permitir elegir política normal o profunda antes de iniciar.
- Conservar presupuesto al reanudar: por defecto, 20 llamadas/60 minutos activos
  por revisión normal y 40 llamadas/120 minutos en profunda.
- Reintentos, reparaciones y adjudicaciones consumen presupuesto.
- La espera del usuario no consume tiempo activo.
- Tokens y coste son desconocidos si no hay datos fiables.

**Verificación:** presupuesto agotado, reanudación, errores y ausencia de
métricas del proveedor.

## Issue #17: Compatibilidad, validación integral y documentación

**Estado:** Pending
**Dependencias:** #1–#16.

Completar migración de proyectos existentes, evaluaciones y documentación.

**Aceptación:**

- Proyectos activos antiguos se revalidan antes de continuar si falta evidencia.
- Se conserva el historial completado; revalidar no reimplementa ni duplica
  registros.
- Proyectos terminados no repiten aprendizaje ni commits de finalización.
- Versiones y configuración fijadas durante migración dejan evidencia.
- Documentación, agentes, rutas y skills coinciden.
- Evaluar un proyecto local, uno cloud y uno mixto cuando haya perfiles
  compatibles; casos no ejecutados quedan señalados.

**Verificación:** suite completa, migraciones, navegador y evaluaciones reales
con comprobaciones externas al código generado.
