"""Configuracion de las pruebas de integracion de P3 (ejecutan el flujo completo con modulos reales)."""
from __future__ import annotations


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: prueba de extremo a extremo (ejecuta escenarios reales del simulador; tarda ~1 min por escenario)",
    )
