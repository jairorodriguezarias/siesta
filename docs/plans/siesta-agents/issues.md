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

**Estado:** Done
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

**Evidencia de verificación:**

- `tests.test_recovery_gates.RecoveryGates.test_issue_review_repairs_then_rechecks_and_approves_before_completion`:
  un finding dispara reparación, nuevo test y revisión; la reanudación no repite
  revisiones de una issue ya completada.
- `test_issue_review_repair_regression_blocks_and_archives_issue`,
  `test_issue_review_rejection_never_records_completion` y
  `test_issue_tests_cannot_change_the_product_they_approve`: una reparación roja
  o tests que mutan el producto impiden completar y la recuperación restaura el
  base sin arrancar la siguiente issue.
- `test_extended_issue_review_invokes_both_independent_specialists`,
  `tests.test_repository` y `tests.test_design`: rutas extendidas, detección de
  riesgos y validación del diseño.
- `tests.test_integration`: flujos de ejecución existentes con revisión por
  issue y conteos de llamadas actualizados.
- `python -B -m unittest discover -s tests -v`: suite completa aprobada,
  393 tests, `EXIT_CODE=0`.
- `docs/review-policy.md` y `docs/architecture.md`: flujo, contexto, riesgos y
  módulos documentados.

## Issue #6: Revisar la intención al finalizar la entrevista

**Estado:** Done
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

**Evidencia de verificación:**

- `tests.test_intent_review`: aprobación, corrección respaldada por una cita
  literal, bloqueo de una decisión nueva, rechazo de evidencia procedente de
  resúmenes no aceptados y separación entre respuestas humanas y texto no
  confiable del transcript.
- `tests.test_phases.InterviewDialog` y `tests.test_phases.AbandonedInterview`:
  confirmación interactiva conservada, refinamientos enviados como respuestas
  explícitas y crítica aplicada también al cierre autónomo.
- `tests.test_integration.PipelineRun.test_intent_critic_blocks_specification_for_a_new_user_decision`:
  un bloqueo queda registrado sin crear `spec.md`; el flujo autónomo aprobado
  continúa hasta completar las fases.
- `tests.test_agents` y `tests.test_model_selection`: agente sin herramientas,
  contexto aislado y ruta específica de modelo en argumentos reales de Pi.
- `python -B -m unittest discover -s tests -v`: suite completa aprobada,
  403 tests, `EXIT_CODE=0`, con el entorno virtual temporal que proporciona
  `pytest 9.2.0`.
- `docs/architecture.md` y `docs/review-policy.md`: gate de intención, límites
  de evidencia y registro de decisiones sin resolver.

## Issue #7: Ampliar la revisión del diseño y reparar el plan

**Estado:** Done
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

**Evidencia de verificación:**

- `tests.test_design.DesignGate.test_plan_coverage_requires_each_requirement_and_test_strategy`
  y `test_plan_rejects_self_forward_and_missing_dependencies`: toda aceptación
  aparece en un issue con estrategia de prueba; las dependencias inexistentes,
  circulares o adelantadas se rechazan.
- `test_design_repair_is_validated_committed_then_reviewed_again`,
  `test_invalid_scope_repair_is_not_written_or_committed` y
  `test_design_repair_budget_is_bounded`: reparación registrada y confirmada
  antes de volver a revisar, rechazo de cambios de aceptación y límite de dos
  reparaciones persistido al reanudar.
- `test_design_approval_is_bound_to_specialist_model_routes`: cambiar la ruta
  de un especialista invalida la aprobación previa.
- `tests.test_agents` y `tests.test_model_selection`: tres especialistas con
  herramientas deshabilitadas y rutas específicas para revisión y reparación.
- `tests.test_integration`: suite completa de 48 pruebas fake-Pi aprobada;
  `tests.test_recovery_gates` y `PYTHONPATH=tests python -B -m unittest
  test_iterations -v`: recuperación, dependencias entre issues, reanudación e
  inmutabilidad de issues completadas.
- `python -B -m unittest discover -s tests -v`: suite completa aprobada,
  414 tests, `EXIT_CODE=0`, con el entorno virtual temporal que proporciona
  `pytest 9.2.0`.
- `docs/architecture.md`, `docs/review-policy.md`, `docs/model-selection.md`,
  `docs/skills-and-context.md` y `docs/getting-started.md` describen las lentes,
  límites, reparación, rutas y evidencia local.

## Issue #8: Guardar propuestas de aprendizaje y fijar versiones de skills

**Estado:** Done
**Dependencias:** #1–#2.

Separar observaciones de KB, propuestas de modificación y versiones activas.

**Aceptación:**

- Cada propuesta conserva contenido anterior, nuevo, motivo y evidencia.
- Una ejecución usa versiones fijadas de sus skills también al reanudar.
- Las propuestas no sustituyen inmediatamente archivos activos.
- El aprendizaje solo modifica skills de fábrica.

**Verificación:** modificación durante una ejecución, reanudación con versiones
fijadas y propuestas a skills no autorizadas.

**Evidencia de verificación:**

- `tests.test_skill_versions`: snapshots adaptados y de fábrica, reanudación
  frente a cambios del árbol activo, rechazo de skills añadidas tarde,
  detección de alteraciones del snapshot, manifiesto con symlink y alias de
  symlink en la ruta de origen.
- `tests.test_learn.SkillProposals`: cada propuesta completa conserva el
  contenido anterior fijado, candidato, motivo y evidencia sin modificar el
  archivo activo; se rechazan skills adaptadas, colisiones, traversal y bloques
  incompletos.
- `tests.test_skill_context.SkillContext.test_run_pi_uses_project_pinned_skill_after_active_file_changes`:
  Pi recibe las instrucciones fijadas aunque el archivo activo cambie.
- La suite completa, `/tmp/siesta-test-venv/bin/python -B -m unittest discover -s tests -v`,
  aprobó 425 tests, `EXIT_CODE=0`.
- `docs/skills-and-context.md` y `docs/architecture.md`: formato de pinning,
  propuestas, evidencia y límites.

## Issue #9: Ejecutar escenarios de prueba de skills

**Estado:** Done
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

**Evidencia de verificación:**

- `tests.test_skill_scenarios`: YAML inválido, claves duplicadas y desconocidas,
  aserciones no soportadas, marcadores dentro de fences, escenarios válidos,
  separación de resultados de simulación y evaluación real, y afirmaciones de
  ejecución que fallan sin registros estructurados.
- `tests.test_evaluate`: regresiones de las evaluaciones de producto existentes.
- Suite completa: 436 tests, `/tmp/siesta-test-venv/bin/python -B -m unittest discover -s tests -v`,
  `EXIT_CODE=0`. La etapa de modelo real se probó con un invocador controlado;
  no se hizo una llamada a un modelo.
- `requirements-dev.txt` añade PyYAML; el lector lo importa solo al usar los
  escenarios. `docs/testing.md` documenta la ejecución y sus límites.

## Issue #10: Probar el protocolo de aprobación

**Estado:** Done
**Dependencias:** #9.

Añadir `TEST.md` y escenarios ejecutables para `human-proxy`.

**Aceptación:**

- Cubrir aprobación, rechazo, petición de revisión y respuesta ambigua.
- Ejemplos dentro de bloques de código nunca autorizan acciones.
- El proxy recibe intención, decisiones y contexto pertinente.

**Verificación:** escenarios conectados al ejecutor y regresiones del protocolo.

**Evidencia de verificación:**

- `factory/skills/human-proxy/test_scenarios.yaml` y `TEST.md`: casos para
  aprobación, rechazo, evidencia insuficiente y un marcador de aprobación
  dentro de un fence. Los prompts contienen intención, decisiones, especificación
  y contexto pertinente.
- `tests.test_skill_scenarios.SkillScenarioValidation.test_human_proxy_scenarios_cover_decisions_and_supply_full_context`:
  valida el formato y ejecuta los cuatro fixtures a través del lector de
  escenarios.
- `tests.test_skill_context.SkillContext.test_issue_proxy_uses_decision_details_even_when_summaries_are_empty`:
  el proxy de runtime recibe la intención, la decisión, la especificación y la
  issue activa.
- `tests.test_text.ExplicitApproval`, `tests.test_text.WithoutFences` y la suite
  completa: 437 tests aprobados, `EXIT_CODE=0`. No se hizo una llamada a un
  modelo real para esta issue.

## Issue #11: Probar el ejecutor de issues

**Estado:** Done
**Dependencias:** #5, #9.

Añadir el paquete de pruebas de `issue-executor`.

**Aceptación:**

- Cubrir implementación, consulta, solicitud de aprobación, reintento y bloqueo.
- Narrar acciones no equivale a ejecutarlas.
- La finalización exige evidencia real y respeta documentos protegidos.

**Verificación:** escenarios del protocolo y ejecución controlada en proyecto
temporal.

**Evidencia de verificación:**

- `factory/skills/issue-executor/test_scenarios.yaml` y `TEST.md`: implementación
  con logs, consulta, solicitud de aprobación, implementación tras guía y
  consulta persistente sin resolución.
- `tests.test_issue_executor_scenarios`: ejecuta los cinco escenarios; comprueba
  que una narración de escritura/tests sin registro estructurado falla; crea un
  proyecto temporal y confirma que una regresión roja queda fallida y que un
  pytest real pasa con su test ID registrado.
- `tests.test_recovery_gates.RecoveryGates.test_unusable_retries_after_consultation_do_not_complete_issue`:
  las respuestas inutilizables tras consulta no escriben el nodo de finalización.
- `test_issue_executor_completion_uses_real_test_evidence_and_preserves_documents`:
  pipeline completa con Git y pytest reales; la evidencia marca el test como
  aprobado y `spec.md` e `issues.md` conservan sus bytes originales.
- Suite completa: 441 tests, `/tmp/siesta-test-venv/bin/python -B -m unittest discover -s tests -v`,
  `EXIT_CODE=0`.

## Issue #12: Probar el aprendizaje y sus propuestas

**Estado:** Done
**Dependencias:** #8–#9.

Añadir el paquete de pruebas de `factory-learner`.

**Aceptación:**

- Cubrir propuestas completas, incompletas, contradictorias y sin evidencia.
- Preservar ejemplos de skills sin interpretarlos como acciones.
- Detectar propuestas que debiliten verificaciones o atribuyan herramientas
  inexistentes.

**Verificación:** escenarios del aprendiz y regresiones del parser.

**Evidencia:** `factory-learner/TEST.md` y `test_scenarios.yaml` cubren cuatro
resultados; `test_factory_learner_scenarios.py` comprueba el parser, ejemplos
literales, propuesta pendiente sin activación y rechazo de instrucciones que
debilitan verificaciones o inventan herramientas. Suite completa: 445 tests,
`/tmp/siesta-test-venv/bin/python -B -m unittest discover -s tests -q`, exit 0.

## Issue #13: Revisar y activar automáticamente mejoras de skills

**Estado:** Done
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

**Evidencia:** `pipeline/skill_activation.py` exige evaluación de formato,
simulación y ejecución real junto con informe válido de `skill-reviewer`;
compara el contenido activo con la versión propuesta, conserva la anterior y
recupera swaps interrumpidos. `test_skill_activation.py` cubre aceptación,
rechazo, evaluación fallida, conflicto, reintento inválido y recuperación.
El aprendizaje captura errores de activación sin alterar el veredicto del
producto. La evaluación real de propuestas futuras requiere un modelo Pi
disponible y escenarios de la skill afectada. Suite completa: 451 tests,
`/tmp/siesta-test-venv/bin/python -B -m unittest discover -s tests -q`, exit 0.

## Issue #14: Descubrir y validar modelos Ollama

**Estado:** Done
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

**Evidencia:** `pipeline/model_catalog.py` cruza el catálogo Pi con `/api/tags`
sin exponer credenciales, y realiza una prueba explícita de texto y escritura
nativa en un directorio temporal. `test_model_catalog.py` cubre catálogo mixto,
Ollama caído, modelo no registrado, autenticación fallida, incompatibilidad de
herramientas y ruta exacta. `test_web.py` comprueba origen y token HTTP.
Suite completa: 457 tests, `/tmp/siesta-test-venv/bin/python -B -m unittest
discover -s tests -q`, exit 0. En este perfil, el catálogo real muestra 11
modelos; los defaults cloud antiguos están instalados pero no registrados en
Pi, y `glm-5.3-flash:cloud` está instalado y registrado.

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
