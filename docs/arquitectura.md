# Arquitectura

Tres proyectos Python independientes (cada uno con su entorno, `requirements.txt` y pruebas).
El único acoplamiento es un contrato de datos: `contracts/observation.schema.json`.

```mermaid
flowchart LR
  subgraph P1[P1 demo-reconocimiento-facial-uniface]
    F1[foto autorizada] --> F2[detector UniFace] --> F3[embedding] --> F4[galería + similitud] --> F5[CSV / UI]
  end
  subgraph P2[P2 demo-deteccion-drones-audio]
    A1[WAV] --> A2[log-mel / MFCC] --> A3[clasificador drone/no_drone] --> A4[observación acústica<br/>sin coordenadas]
  end
  subgraph P3[P3 demo-localizacion-drones-popayan]
    S1[simulación<br/>truth separado] -->|RawEvent| I1[agent_ingestion<br/>agent_validator]
    I1 -->|Observation| C1[agent_correlator] --> T1[agent_tracker] --> Q1[agent_quality] --> E1[agent_evidence] --> D1[motor de estados] --> AL[agent_alerts]
    D1 --> AU[agent_audit]
    AL --> DB[(SQLite)]
    AU --> DB
    DB --> API[FastAPI] --> UI[Dashboard Streamlit + Folium<br/>teselas públicas OSM]
    S1 -.-> BL[Blender: imágenes + etiquetas YOLO]
  end
  A4 -. observation.schema.json .-> I1
```

P1 no se conecta con P2 ni P3: es una demo de visión independiente y no se usa para identificar
a personas que operan drones.

## Proyecto 3 — módulos y dueños

| Ruta | Contenido | Dueño |
|---|---|---|
| `src/contracts/` | `Observation`, tipos de dominio, formato `rid-demo-1`, interfaces | Fable |
| `src/simulation/`, `blender/` | escenarios, trayectorias, sensores virtuales, escenas | S3 (Sonnet) |
| `src/remote_id/`, `src/ingestion/` | parser, validación, conversión, adaptadores | O2 (Opus) |
| `src/correlation/`, `src/tracking/`, `src/decision_agents/`, `src/audit/` | fusión, estados, alertas, auditoría | O3 (Opus) |
| `src/storage/`, `src/stations/`, `src/orchestration/`, `src/api/`, `src/dashboard/`, `app.py` | SQLite, orquestación, API, UI | S2 (Sonnet) |
| `tests/integration/`, CI | QA | H2 (Haiku) |

Las firmas exactas están en `demo-localizacion-drones-popayan/src/contracts/INTERFACES.md`.

## Decisiones de arquitectura

1. **Contrato único de 16 campos.** `Observation` no admite campos extra. Lo que no cabe
   (estación de control reportada, punto de despegue) viaja en `IngestionResult.related_locations`
   con un rol explícito, de modo que nunca se confunda con la posición del dron.
2. **Reglas en el contrato, no en la UI.** El contrato rechaza: observación acústica con
   coordenadas; `is_simulated` incoherente con `data_origin`; latitud sin longitud; altitud sin
   referencia; marca temporal sin zona.
3. **Verdad separada de lo observado.** `ScenarioResult.truth` nunca entra al pipeline; se guarda
   en una tabla aparte y solo se dibuja como capa opcional rotulada.
4. **Nodos institucionales sin coordenadas.** `INST-SIM-01/02` son fuentes lógicas: no tienen
   latitud ni longitud, no aparecen en el mapa ni en el GeoJSON. Así el repositorio no contiene
   ni sugiere ubicaciones de instalaciones reales.
5. **Estaciones civiles por regla geométrica.** Desplazamientos de ~2,5 km desde un punto
   público de referencia (Parque Caldas). Son inventadas y se pueden mover editando un JSON.
6. **Determinismo.** Semilla fija, tiempo inyectado (`now_utc`), identificadores derivados del
   contenido. Mismo escenario + misma semilla = mismos resultados y mismas pruebas.
7. **Agentes operativos = módulos Python.** No llaman a modelos de lenguaje. Los subagentes de
   Claude solo desarrollan el software.
8. **Independencia de fuentes.** Dos recepciones del mismo mensaje Remote ID no corroboran nada:
   son la misma autodeclaración. La corroboración exige evidencia técnicamente independiente.
9. **Alertas informativas.** Estado + motivo + evidencia + petición de revisión humana. Sin
   niveles de amenaza ni recomendaciones de acción.
10. **Entornos fuera de OneDrive** (`%USERPROFILE%\.venvs\...`) para no sincronizar miles de
    archivos. Los datasets sí quedan dentro de cada proyecto (`data/raw/`, ignorado por git).

## Límites declarados

- La simulación de 100 m a 10 km prueba el software; no demuestra alcance de ningún equipo.
- Una clasificación acústica no produce coordenadas, altura ni distancia.
- RSSI por sí solo no produce localización.
- Remote ID puede faltar o ser inexacto; la ubicación de la estación de control es *reportada*,
  no verificada, y no identifica a ninguna persona.
- El formato `rid-demo-1` es de ejemplo; no es compatible a nivel binario con equipos reales.
- No hay sensores, cámaras ni drones físicos conectados. Cualquier prueba física requiere revisar
  antes la normativa colombiana aplicable y contar con autorización.
