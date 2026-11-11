# CLAUDE.md — Proyectos_IA_Drones_Rostros

Tres demos de Python **independientes**, de investigación y simulación. Plan maestro:
`Prompt_Maestro_Claude_Popayan_Find_Skills.md`. Coordinador: sesión principal (Fable).

## Estructura

| Carpeta | Proyecto | Estado de datos |
|---|---|---|
| `demo-reconocimiento-facial-uniface/` | P1 — rostros con UniFace (fotos autorizadas) | LFW vía kit |
| `demo-deteccion-drones-audio/` | P2 — clasificador acústico `drone`/`no_drone` | audio vía kit |
| `demo-localizacion-drones-popayan/` | P3 — simulación multisensor Popayán | sintético, sin datasets |
| `kit_descarga_datasets/` | descargador + monitor | — |
| `contracts/` | `observation.schema.json` (P2 → P3) | — |
| `docs/` | arquitectura, tablero, estado, inventarios | — |
| `.claude/agents/` | 10 subagentes | — |

Carpetas antiguas: en `<proyecto>/legacy/`. No se borra nada sin revisar.

## Entornos (fuera de OneDrive, para no sincronizar miles de archivos)

- P1: `C:\Users\sebas\.venvs\p1-uniface`
- P2: `C:\Users\sebas\.venvs\p2-audio`
- P3: `C:\Users\sebas\.venvs\p3-popayan`

Python 3.11. Ejecutar siempre con `<venv>/Scripts/python.exe` desde la raíz del proyecto.
Blender 4.4.3: `C:\Program Files\Blender Foundation\Blender 4.4\blender.exe` (instalado con
winget el 2026-11-11). Renderizar con **Cycles por CPU**: en este equipo el motor Workbench
no compila sus shaders en modo `--background` y Blender se cierra. Pasar siempre rutas de
salida absolutas a Blender.

## Reglas para todos los agentes

1. **Propiedad de archivos.** Cada subagente escribe solo en sus rutas (ver su archivo en
   `.claude/agents/`). Archivos del coordinador, que nadie más edita: `CLAUDE.md`,
   `contracts/`, `docs/arquitectura.md`, `docs/tablero-tareas.md`, `docs/estado_general.md`,
   `.gitignore`, y en P3 `src/contracts/`, `requirements.txt`, `pytest.ini`,
   `data/stations/estaciones_ficticias.json`.
2. **Git.** Los subagentes NO ejecutan `git add`/`git commit`/`git push`. Solo el coordinador
   hace commits. Los commits **no llevan** líneas `Co-Authored-By` ni menciones a Claude/IA:
   el autor es únicamente el usuario configurado en git.
3. **Honestidad.** No inventar métricas, descargas, modelos entrenados ni alcances físicos.
   Etiquetar resultados: `IMPLEMENTADO_Y_PROBADO`, `IMPLEMENTADO_SIN_VALIDACION_COMPLETA`,
   `SIMULADO`, `PREPARADO_NO_EJECUTADO`, `BLOQUEADO`, `PENDIENTE`. Un test cuenta solo si se
   ejecutó y se pega su salida real.
4. **Simulado ≠ real.** Todo dato del simulador lleva `is_simulated=true` /
   `data_origin="simulation"` y se muestra como SIMULADO en UI, CSV y GeoJSON.
5. **Límites del dominio (P3).** Solo alertas informativas con revisión humana. Prohibido:
   clasificar amenazas u hostilidad, ordenar o sugerir acciones físicas, deducir la identidad
   de un piloto, buscar o estimar ubicaciones de instalaciones militares/policiales,
   interceptar comunicaciones privadas, interferir o suplantar señales. Los nodos
   `INST-SIM-*` son abstractos y **no tienen coordenadas**. Las pruebas de 100 m–10 km
   demuestran el software, no el alcance de ningún hardware. Audio no produce coordenadas.
   RSSI solo no produce localización.
6. **P1.** Solo fotografías autorizadas o datasets públicos de investigación. P1 no se
   relaciona con identificar personas que operan drones.
7. **Datos.** Datasets en `<proyecto>/data/raw/` (ignorado por git). No subir datasets,
   pesos, fotos personales, `.env` ni bases SQLite. Nada de descargas grandes sin revisar
   tamaño y espacio libre.
8. **Dependencias.** En P3 nadie ejecuta `pip install`: se piden al coordinador. En P1/P2 el
   dueño del proyecto mantiene su `requirements.txt`.
9. **Idioma.** Texto de usuario, README y docs en español. Código e identificadores en inglés
   o español consistente con el módulo.

## Comandos de referencia (P3)

```bash
cd demo-localizacion-drones-popayan
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe -m pytest
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe app.py demo --scenario basico --seed 42
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe app.py api
C:/Users/sebas/.venvs/p3-popayan/Scripts/python.exe app.py dashboard
```
