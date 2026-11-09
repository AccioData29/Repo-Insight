"""Enriquecimiento OPCIONAL con Claude: reescribe reglas en lenguaje de negocio.

Solo se ejecuta si: (a) el servidor tiene ANTHROPIC_API_KEY y (b) la persona lo activó explícitamente.
Se envían únicamente los fragmentos mínimos (condición/mensaje ya redactados, sin secretos), nunca el repositorio completo.
Si falla, el informe queda igual (determinista) y se anota en el registro.
"""
from __future__ import annotations

import json
import re
from typing import Callable

import httpx

from .. import config
from ..models import Rule


def available() -> bool:
    return bool(config.ANTHROPIC_API_KEY)


def enrich_rules(rules: list[Rule], log: Callable[[str], None]) -> int:
    if not available():
        return 0
    # prioriza reglas con mensajes/condiciones (las de mayor valor para negocio)
    pool = [r for r in rules if r.category in ("Restricción de negocio", "Condición / umbral", "Estado y transición", "Validación de datos")]
    pool = pool[: config.AI_MAX_RULES]
    if not pool:
        return 0
    payload = [{"id": r.id, "categoria": r.category, "descripcion_actual": r.description,
                "codigo": (r.condition or "")[:200], "resultado": (r.outcome or "")[:160]} for r in pool]
    prompt = (
        "Eres analista de negocio. Reescribe cada regla en español claro, en una sola frase imperativa o condicional, "
        "sin jerga técnica ni nombres de variables, usando solo lo que está en los datos (no inventes reglas). "
        "Responde SOLO un JSON: {\"<id>\": {\"titulo\": \"≤ 80 caracteres\", \"descripcion\": \"1-2 frases\"}}.\n\n"
        + json.dumps(payload, ensure_ascii=False))
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": config.ANTHROPIC_API_KEY or "", "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": config.AI_MODEL, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]},
            timeout=120)
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as exc:
        log(f"Enriquecimiento con IA omitido: {type(exc).__name__}")
        return 0
    n = 0
    by_id = {r.id: r for r in rules}
    for rid, v in data.items():
        rule = by_id.get(rid)
        if rule and isinstance(v, dict) and v.get("descripcion"):
            rule.title = str(v.get("titulo") or rule.title)[:120]
            rule.description = str(v["descripcion"])[:500]
            rule.ai_enriched = True
            n += 1
    return n
