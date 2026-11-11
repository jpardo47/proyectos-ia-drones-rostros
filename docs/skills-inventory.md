# Inventario de Skills

Fecha: 2026-11-11. Responsable: `ingeniero-datos-skills` (H1). Ámbito: Skills de agente para Claude Code.

## 1. Comprobante de find-skills

- Comando de verificación: `npx --yes skills list -g`
- Salida real (fila relevante): `find-skills  ~\.claude\skills\find-skills  Agents: Claude Code  Source: vercel-labs/skills`
- Archivo comprobado: `~/.claude/skills/find-skills/SKILL.md` (existe, 5 472 bytes).
- Evaluación de riesgo de la instalación original (informada por el coordinador, no repetida en esta sesión): Gen "Safe", Socket "0 alerts", Snyk "Med Risk".

## 2. Búsquedas realizadas

Fuente: `npx skills find` ejecutado por el coordinador. Resultados en
`<carpeta temporal de la sesión, no versionada>/skills_find.txt`.
Las instalaciones son las que muestra skills.sh en esos resultados.

| Tema buscado | Mejores resultados (instalaciones) | Decisión |
|---|---|---|
| python testing pytest | wshobson/agents@python-testing-patterns (40.1K); wshobson/agents@temporal-python-testing (11.3K) | `python-testing-patterns` revisada e INSTALADA |
| fastapi | fastapi/fastapi@fastapi (15.1K); wshobson/agents@fastapi-templates (26.5K) | `fastapi/fastapi@fastapi` revisada; DESCARTADA (riesgo alto) |
| machine learning | mindrally/skills@machine-learning (2.1K); 404kidwiz/…@machine-learning-engineer (788) | No revisada (no solicitada) |
| audio signal processing | alemusica/golden-helix-studio@audio-dsp (63); shortwavlabs/agent-skills@dsp (75) | DESCARTADA: audio/DSP, pocas instalaciones y autores sin reputación verificable |
| computer vision | mindrally/skills@computer-vision-opencv (3.9K); alirezarezvani/claude-skills@senior-computer-vision (1.2K) | No revisada (no solicitada) |
| geospatial maps | davila7/claude-code-templates@geopandas (407); openai/plugins@geospatial-and-cartographic-visualization (21) | DESCARTADA: geoespacial, sin revisión por norma del coordinador |
| blender 3d | majidmanzarpour/blender-game-skills@blender-image-to-3d (762) | DESCARTADA: Blender, pocas instalaciones |
| github actions ci | wshobson/agents@github-actions-templates (18.1K); callstackincubator/agent-skills@github-actions (12.1K); openai/skills@gh-fix-ci (11.9K) | `github-actions-templates` revisada e INSTALADA |
| dataset | huggingface/skills@huggingface-datasets (2.6K); wshobson/agents@dataset-curation (3.1K) | No revisada (no solicitada) |
| streamlit | streamlit/agent-skills@developing-with-streamlit (3.5K) | `developing-with-streamlit` revisada; DESCARTADA (repositorio archivado) |
| python | wshobson/agents@python-performance-optimization (37.7K); wshobson/agents@python-design-patterns (23.8K) | No revisada (no solicitada) |

## 3. Candidatas revisadas

Revisión: API pública de GitHub (`repos/<owner>/<repo>`, árbol de archivos) y lectura de los
`SKILL.md` en raw/API de GitHub, con búsqueda de scripts, credenciales, descargas remotas y envío de datos.

| Candidata | Repositorio y licencia | Estrellas del repo | Instalaciones | Hallazgos de la revisión | Riesgo (tabla CLI) | Decisión y motivo |
|---|---|---|---|---|---|---|
| fastapi/fastapi@fastapi | fastapi/fastapi, MIT, no archivado, último push 2026-11-11 | 104 614 | 15.1K | Mantenedor oficial. Solo documentación: `SKILL.md` (11 966 bytes) y 8 referencias en `fastapi/.agents/skills/fastapi/references/`. Sin scripts. Menciona el plugin opcional de FastAPI Cloud, sin comandos de descarga. | Gen **High Risk**; Socket 0 alerts; Snyk Low Risk | **DESCARTADA.** Incumple el criterio: Gen muestra riesgo alto. Se instaló por error en la primera ejecución (la tabla se muestra durante la instalación, y mi comando no la comprobó antes de copiar). Se desinstaló con `npx --yes skills remove fastapi -a claude-code -y`; `npx skills list` (proyecto) no muestra skills y no existe `.agents/skills`. |
| streamlit/agent-skills@developing-with-streamlit | streamlit/agent-skills, Apache-2.0, **archivado** (último push 2026-07-23) | 226 | 3.5K | `SKILL.md` (1 650 bytes) y `scripts/discover.py`, que ejecuta `subprocess.run` para localizar el intérprete de Python y avisa de `pip install streamlit`. Sin credenciales. | No ejecutada (no se instaló) | **DESCARTADA.** Repositorio archivado: no hay mantenimiento. |
| wshobson/agents@python-testing-patterns | wshobson/agents, MIT, no archivado, último push 2026-11-09 | 42 418 (repo) | 40.1K | Solo documentación: `SKILL.md` (7 282 bytes) y `references/advanced-patterns.md` y `details.md`. Ejemplos de pytest. Sin scripts ni descargas. Valores de prueba (`api_key = "test-key"`) solo en ejemplos. | Gen **Safe**; Socket 0 alerts; Snyk Low Risk | **INSTALADA** (ámbito proyecto). Cumple: licencia abierta, no archivado, ≥ 10 000 instalaciones, solo documentación, riesgo bajo. |
| wshobson/agents@github-actions-templates | wshobson/agents, MIT, no archivado | 42 418 (repo) | 18.1K | Solo `SKILL.md` (7 076 bytes), sin scripts. Plantillas YAML con referencias a secretos (`GITHUB_TOKEN`, claves AWS, `NPM_TOKEN`, webhook de Slack). Son ejemplos; no envían datos a ningún servicio por sí mismas. | Gen **Safe**; Socket 0 alerts; Snyk Low Risk | **INSTALADA** (ámbito proyecto). Cumple todos los criterios. Las plantillas no deben copiar secretos reales al repositorio. |

Revisión de las instalaciones de prueba: las dos wshobson se instalaron antes en un directorio temporal
del scratchpad para leer la tabla de riesgo, y después en el proyecto.

## 4. Skills instaladas (salida real de `npx --yes skills list`, ámbito proyecto)

```
Project Skills

github-actions-templates ~\OneDrive\Escritorio\Proyectos_IA_Drones_Rostros\.claude\skills\github-actions-templates
  Agents: Claude Code  Source: wshobson/agents
python-testing-patterns  ~\OneDrive\Escritorio\Proyectos_IA_Drones_Rostros\.claude\skills\python-testing-patterns
  Agents: Claude Code  Source: wshobson/agents
```

Rutas exactas:
- `.claude/skills/python-testing-patterns/`
- `.claude/skills/github-actions-templates/`

Skills globales ya existentes (no instaladas por este agente, solo listadas): `find-skills`, `graphify`, `skill-inspector` en `~/.claude/skills/`.

## 5. Uso previsto

| Skill | Proyecto / agente | Uso concreto |
|---|---|---|
| python-testing-patterns | P1, P2 y P3 (los agentes de cada proyecto al escribir pruebas) | Organizar pruebas con pytest: fixtures, parametrización y mocks. P3 se ejecuta con `~/.venvs/p3-popayan/Scripts/python.exe -m pytest`. Las pruebas cuentan solo si se ejecutan y se pega su salida. |
| github-actions-templates | Transversal (coordinador) | Borrador de `.github/workflows` con pytest por proyecto, solo cuando el coordinador lo pida. No se activa por defecto. Sin secretos reales en el repositorio. |

Nota: las Skills instaladas durante una sesión pueden requerir reiniciar Claude Code para cargarse.

## 6. Descartadas por categoría (no instalar)

- Audio/DSP: `alemusica/golden-helix-studio@audio-dsp`, `shortwavlabs/agent-skills@dsp`, `faust-dsp`, `vult-dsp`. Pocas instalaciones o autores sin reputación verificable. Esa parte de P2 se implementa con herramientas habituales.
- Blender: `majidmanzarpour/blender-game-skills@blender-image-to-3d` y similares. Pocas instalaciones.
- Geoespaciales: `davila7/claude-code-templates@geopandas`, `openai/plugins@geospatial-and-cartographic-visualization` y similares. Pocas instalaciones o sin revisión.
- Streamlit: `streamlit/agent-skills@developing-with-streamlit`. Repositorio archivado.
- FastAPI: `fastapi/fastapi@fastapi`. Riesgo alto en la CLI (Gen).
