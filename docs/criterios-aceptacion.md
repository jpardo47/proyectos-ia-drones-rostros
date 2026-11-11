# Criterios de aceptación

Etiquetas: `IMPLEMENTADO_Y_PROBADO`, `IMPLEMENTADO_SIN_VALIDACION_COMPLETA`, `SIMULADO`,
`PREPARADO_NO_EJECUTADO`, `BLOQUEADO`, `PENDIENTE`. Una prueba cuenta solo si se ejecutó y se
conserva su salida real.

## P1 — reconocimiento facial UniFace

- [ ] Una fotografía autorizada produce detecciones (caja + puntuación).
- [ ] Con galería: embedding y comparación por similitud con umbral configurable.
- [ ] Salida `desconocido` cuando no supera el umbral o la galería está vacía.
- [ ] Exportación CSV.
- [ ] Interfaz Streamlit/Gradio y demo por línea de comandos documentadas.
- [ ] `pytest` pasa; las pruebas que requieren pesos se saltan limpiamente si no los hay.

## P2 — detección acústica

- [ ] Un WAV de ejemplo produce una salida reproducible del clasificador.
- [ ] División train/val/test por grabación original.
- [ ] Métricas (precisión, recall, F1) solo si hay conjunto de prueba legítimo; lo sintético se
      rotula `SIMULADO`.
- [ ] Exportación de observaciones válidas contra `contracts/observation.schema.json`, sin
      coordenadas.
- [ ] Ninguna inferencia de posición, altura o distancia.

## P3 — localización Popayán (simulación)

- [ ] Mapa público de referencia con atribución.
- [ ] Siete nodos ficticios: `CIV-01..05` con coordenadas inventadas; `INST-SIM-01/02` sin
      coordenadas.
- [ ] Secuencia de drones virtuales y mensajes Remote ID de prueba.
- [ ] Observaciones válidas e inválidas tratadas sin excepciones.
- [ ] Cambios de estado explicables (`rule_id`, motivo, evidencia).
- [ ] Dashboard con revisión humana y exportación CSV/GeoJSON.
- [ ] Auditoría persistida.
- [ ] Imagen sintética de Blender con etiqueta YOLO validada.

### Escenarios de prueba obligatorios (deterministas)

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Observación válida | `DETECCION_POSIBLE` |
| 2 | Pérdida de señal | `SEGUIMIENTO_PERDIDO` con motivo |
| 3 | Duplicados | se descartan; no cambian el estado |
| 4 | Fuentes contradictorias | `REQUIERE_REVISION` |
| 5 | Dos fuentes independientes consistentes | `DETECCION_CORROBORADA` |
| 6 | Datos obsoletos | rechazados (`STALE`) o `SEGUIMIENTO_PERDIDO` |
| 7 | Dron sin estación de control conocida | se acepta; control = desconocido |
| 8 | Punto de despegue sin controlador | despegue registrado; control = desconocido |
| 9 | Audio sin coordenadas | track sin puntos; nunca una posición |
| 10 | Estación caída | no aporta evidencia; estado visible |
| 11 | Datos malformados | `RejectedInput`, sin excepción |
| 12 | Simulado vs real | nunca se mezclan en un track; siempre rotulado |
