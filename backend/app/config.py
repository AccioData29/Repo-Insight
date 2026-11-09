"""Configuración central. Todo se puede sobreescribir con variables de entorno."""
from __future__ import annotations

import os
from pathlib import Path

WORK_DIR = Path(os.getenv("WORK_DIR", "/tmp/repo-insight"))
CLONE_TIMEOUT = int(os.getenv("CLONE_TIMEOUT", "300"))
LSREMOTE_TIMEOUT = int(os.getenv("LSREMOTE_TIMEOUT", "30"))
MAX_REPO_MB = int(os.getenv("MAX_REPO_MB", "500"))

# Límites del análisis (protegen memoria y tiempo)
MAX_FILE_BYTES = int(os.getenv("MAX_FILE_BYTES", str(512 * 1024)))
MAX_FILES = int(os.getenv("MAX_FILES", "25000"))

JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "3600"))

# Enriquecimiento opcional con Claude (redacción en lenguaje de negocio).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
AI_MAX_RULES = int(os.getenv("AI_MAX_RULES", "60"))

# Orden de preferencia para adivinar la rama de producción cuando el usuario no la indica.
PRODUCTION_BRANCH_CANDIDATES = ["production", "prod", "release", "main", "master"]

FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
