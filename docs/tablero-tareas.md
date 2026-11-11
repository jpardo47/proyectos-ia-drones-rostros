# Tablero de tareas

Actualizado: 2026-11-11. El estado verificado de cada tarea está en `docs/estado_general.md`.

| ID | Dueño / modelo | Entrada | Archivos | Dependencias | Entregable | Pruebas | Línea |
|---|---|---|---|---|---|---|---|
| A0 | Fable 5.2 (sesión principal) | plan maestro | carpetas, `CLAUDE.md`, `.gitignore`, `README.md` | — | estructura definitiva + `legacy/` | inspección del árbol | — |
| A1 | Fable 5.2 | Node/npx | `~/.claude/skills/find-skills` | — | `find-skills` instalada | `npx skills list -g` | — |
| A2 | Fable 5.2 | plan maestro | `.claude/agents/*.md` (10) | A0 | definiciones de subagentes | frontmatter válido | — |
| A3 | Fable 5.2 | plan maestro §7 | `contracts/`, P3 `src/contracts/` | A0 | contrato + interfaces + 7 nodos | prueba de humo contrato ↔ esquema | — |
| D1 | gestor-descarga-datasets / Haiku 5.5 | kit existente | `kit_descarga_datasets/` | A0 | kit con reanudación, verificación y registro | `--verificar`, monitor `--una-vez` | A |
| D2 | gestor-descarga-datasets / Haiku 5.5 | D1 | `<proyecto>/data/raw/`, `docs/estado_datasets.md`, `logs/descargas/` | D1 | datasets pequeños descargados y verificados | hash / tamaño | A |
| K1 | ingeniero-datos-skills / Haiku 5.5 | resultados de `skills find` | `docs/skills-inventory.md`, `docs/datasets.md`, `.claude/skills/` | A1 | Skills revisadas e inventario | `npx skills list` | A |
| B1 | ingeniero-simulacion-blender / Sonnet 5.5 | A3 | P3 `src/simulation/`, `blender/`, `data/synthetic/` | A3 | simulador + CLI + escenas Blender | `pytest tests/simulation tests/blender` | B |
| B2 | ingeniero-remote-id / Opus 5.5 | A3 | P3 `src/remote_id/`, `src/ingestion/` | A3 | parser, validación, ingesta, adaptadores | `pytest tests/remote_id tests/ingestion` | B |
| B3 | ingeniero-fusion-decisiones / Opus 5.5 | A3 | P3 `src/correlation/`, `src/tracking/`, `src/decision_agents/`, `src/audit/` | A3 | pipeline operativo y motor de estados | `pytest tests/correlation tests/tracking tests/decision_agents tests/audit` | B |
| B4 | ingeniero-api-dashboard / Sonnet 5.5 | A3 | P3 `src/storage/`, `src/stations/`, `src/orchestration/`, `src/api/`, `src/dashboard/`, `app.py` | A3 (firmas); B1–B3 para integración real | SQLite, API, dashboard, `app.py demo` | `pytest tests/storage tests/api tests/orchestration` | B |
| B5 | Fable 5.2 | B1–B4 | integración P3 | B1–B4 | demo de extremo a extremo verificada | `pytest` completo + `app.py demo` | B |
| C1 | ingeniero-uniface / Sonnet 5.5 | — | P1 completo | LFW (D2) solo para evaluación | pipeline UniFace + UI + CSV | `pytest` + demo CLI | C |
| C2 | ingeniero-audio-ia / Opus 5.5 | `contracts/` | P2 completo | audio (D2) para entrenamiento real | pipeline acústico + exportación | `pytest` + `predict.py` | C |
| Q1 | ingeniero-qa-devops / Haiku 5.5 | B5, C1, C2 | `tests/integration/`, `.github/workflows/`, `docs/reporte-pruebas.md` | B5, C1, C2 | 12 escenarios, CI, reporte | ejecución real de pytest | — |
| R1 | Fable 5.2 (o arquitecto-revisor) | todo | `docs/estado_general.md` | Q1 | revisión e informe final | — | — |

## Regla de colisiones

Cada tarea escribe solo en sus archivos. `requirements.txt` de P3, `CLAUDE.md`, `contracts/` y
`src/contracts/` solo los edita el coordinador. Los commits los hace únicamente el coordinador.
