"""Motor determinista de decisiones (O3).

Uso: ``from src.decision_agents.pipeline import OperationalPipeline, PipelineConfig``.
Este ``__init__`` no importa submódulos a propósito, para evitar ciclos con
``src.correlation`` y ``src.tracking`` (que importan ``config``).
"""
