# Proyectos IA — Drones y Rostros (Popayán)

Tres demostraciones independientes de Python, de **investigación y simulación**.

| # | Carpeta | Qué hace |
|---|---|---|
| 1 | `demo-reconocimiento-facial-uniface/` | Detección facial, embeddings y comparación con galería usando UniFace, con fotografías autorizadas. |
| 2 | `demo-deteccion-drones-audio/` | Clasificador acústico ligero `drone` / `no_drone` a partir de WAV; exporta observaciones para el proyecto 3. |
| 3 | `demo-localizacion-drones-popayan/` | Plataforma de simulación multisensor sobre cartografía pública de Popayán: estaciones virtuales, Remote ID de ejemplo, correlación, seguimiento, alertas informativas con revisión humana, auditoría y escenas sintéticas en Blender. |

Además:

- `kit_descarga_datasets/` — descargador de datasets públicos y monitor de progreso.
- `contracts/` — contrato de observación compartido entre los proyectos 2 y 3.
- `docs/` — arquitectura, tablero de tareas, estado general, estado de datasets, inventario de Skills.
- `.claude/agents/` — definiciones de los diez subagentes de desarrollo.
- `CLAUDE.md` — reglas de trabajo del repositorio.

## Avisos

- El proyecto 3 funciona **solo con datos sintéticos**. Nada de lo que muestra es una detección real.
- Las estaciones son **ficticias**. Los nodos `INST-SIM-*` son abstractos y no tienen coordenadas;
  no representan instalaciones reales.
- Las pruebas de 100 m a 10 km demuestran el software, no el alcance de ningún equipo.
- La clasificación de audio no produce coordenadas, altura ni distancia.
- El proyecto 1 solo debe usarse con fotografías autorizadas.
- Los datasets, pesos y bases de datos no se suben al repositorio.

## Inicio rápido (proyecto 3)

```bash
cd demo-localizacion-drones-popayan
python -m venv C:/Users/<usuario>/.venvs/p3-popayan
C:/Users/<usuario>/.venvs/p3-popayan/Scripts/python.exe -m pip install -r requirements.txt
C:/Users/<usuario>/.venvs/p3-popayan/Scripts/python.exe app.py demo --scenario basico --seed 42
C:/Users/<usuario>/.venvs/p3-popayan/Scripts/python.exe app.py dashboard
```

Cada proyecto tiene su propio `README.md` con instalación y comandos.
