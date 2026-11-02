# Siesta: agentes especializados, revisión independiente y selección de modelos

## Objetivo y decisiones cerradas

Implementar las 11 mejoras acordadas mediante 17 issues verificables, separando
los cambios grandes en incrementos funcionales.

- **Seguimiento:** exclusivamente en este repositorio, bajo
  `docs/plans/siesta-agents/`.
- **Agentes:** definiciones explícitas cargadas por el pipeline; Python controla
  permisos, verificaciones y commits.
- **Modelos:** selección de Ollama local o cloud por fase y agente, conservada
  al reanudar.
- **Revisión:** contexto independiente del autor; correcciones automáticas
  dentro del alcance autorizado.
- **Aprendizaje:** activación automática después de revisión y validación,
  únicamente para futuras ejecuciones.
- **Entrega:** incrementos revisados sobre `development`, con estado,
  dependencias, criterios de aceptación y evidencia de validación.

## Interfaces y reglas compartidas

- Cada invocación identifica fase y agente; el registro determina instrucciones
  y permisos, y el resolvedor selecciona el modelo.
- La API del frontal ofrecerá catálogo de modelos, configuración del proyecto y
  comprobación explícita de compatibilidad; el lanzamiento recibirá modelos y
  política de revisión.
- El estado de ejecución mostrará agente, modelo y situación de revisión,
  manteniendo las protecciones actuales de origen y token.
- Informes, versiones y resultados se guardarán en `.siesta/`; la reanudación
  usará el mecanismo existente.
- Las aprobaciones quedarán vinculadas a contenido, requisitos, definición del
  agente, instrucciones y configuración de modelos.
- El contexto incluirá un manifiesto de archivos y fragmentos incluidos y
  omitidos. La falta de contexto se registrará como evidencia insuficiente.
- Se usarán los perfiles Ollama/Pi existentes. No se descargarán modelos ni se
  gestionarán cuentas desde el navegador.
- Habrá un solo proyecto activo por fábrica. Las escrituras de KB,
  reparaciones y commits serán serializadas.

## Orden de ejecución

1. I01 → I02 → I03 → I04 → I05: agentes explícitos y revisión por cambio.
2. I14 → I15: selección de modelos desde el frontal.
3. I06 → I07 → I08 → I09 → I10 → I11 → I12 → I13: intención, diseño y
   aprendizaje.
4. I16 → I17: estado, presupuestos, compatibilidad y validación integral.

Las issues y su evidencia están en [issues.md](issues.md). El estado inicial
queda registrado allí; cada issue se cierra solo con evidencia comprobable.

## Validación prevista

- Suite Python: `python -B -m unittest discover -s tests -v` desde `factory`.
- Snake: `node --test tests/test_snake.mjs` desde el repositorio.
- Navegador: `node tests/web_smoke.mjs` desde `factory`.
- Las evaluaciones con modelos reales se documentan separadas de las pruebas
  simuladas, con modelo, configuración, duración, resultado y limitaciones.
