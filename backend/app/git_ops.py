"""Operaciones git: detección de privacidad/ramas y clonado superficial de solo lectura.

Seguridad:
  * El token jamás va en la URL ni en los argumentos (se pasa por GIT_CONFIG_* en el entorno del proceso hijo).
  * Toda salida de error se limpia de credenciales antes de mostrarse.
  * El clon es superficial (depth=1), de una sola rama, sin submódulos y sin ejecutar hooks.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import config
from .models import Platform, Privacy
from .providers import PROVIDERS, ParsedRepo


class GitError(RuntimeError):
    pass


def _clean_env(token: Optional[str], platform: Platform) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()}
    env.update({
        "GIT_TERMINAL_PROMPT": "0",          # nunca pedir credenciales por consola
        "GIT_ASKPASS": "/bin/true",
        "GCM_INTERACTIVE": "never",
        "GIT_CONFIG_NOSYSTEM": "1",
        "LC_ALL": "C",
    })
    n = 0
    base = {
        "core.hooksPath": "/dev/null",
        "protocol.file.allow": "never",
        "protocol.ext.allow": "never",
        "submodule.recurse": "false",
    }
    items = list(base.items())
    if token:
        items.append(("http.extraheader", PROVIDERS[platform].auth_header(token)))
    env["GIT_CONFIG_COUNT"] = str(len(items))
    for i, (k, v) in enumerate(items):
        env[f"GIT_CONFIG_KEY_{i}"] = k
        env[f"GIT_CONFIG_VALUE_{i}"] = v
    return env


def scrub(text: str, token: Optional[str] = None) -> str:
    if token:
        text = text.replace(token, "***")
    text = re.sub(r"(?i)(authorization:\s*basic\s+)\S+", r"\1***", text)
    text = re.sub(r"https://[^/@\s]+@", "https://***@", text)
    return text.strip()


@dataclass
class RemoteInfo:
    reachable: bool
    branches: list[str] = field(default_factory=list)
    default_branch: Optional[str] = None
    auth_required: bool = False
    error: str = ""


def parse_ls_remote(stdout: str) -> tuple[list[str], Optional[str]]:
    branches: list[str] = []
    default: Optional[str] = None
    for line in stdout.splitlines():
        m = re.match(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", line)
        if m:
            default = m.group(1)
            continue
        m = re.match(r"^[0-9a-f]{40,64}\s+refs/heads/(.+)$", line)
        if m:
            branches.append(m.group(1))
    return sorted(set(branches)), default


def ls_remote(parsed: ParsedRepo, token: Optional[str] = None) -> RemoteInfo:
    """Consulta el remoto. Sin token: si responde, el repo es público. Con 'auth required', es privado (o no existe)."""
    # Los patrones se combinan con OR: HEAD (para --symref) y todas las ramas. Sin --heads, que excluiría HEAD.
    cmd = ["git", "ls-remote", "--symref", parsed.clone_url, "HEAD", "refs/heads/*"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=config.LSREMOTE_TIMEOUT,
                           env=_clean_env(token, parsed.platform))
    except subprocess.TimeoutExpired:
        return RemoteInfo(False, error="Tiempo de espera agotado al contactar la plataforma.")
    except FileNotFoundError:
        raise GitError("git no está instalado en el servidor.")
    if r.returncode == 0:
        branches, default = parse_ls_remote(r.stdout)
        return RemoteInfo(True, branches, default or (branches[0] if branches else None))
    err = scrub(r.stderr, token).lower()
    auth = any(s in err for s in ("authentication failed", "could not read username", "terminal prompts disabled",
                                  "http basic: access denied", "403", "401", "repository not found", "not found"))
    network = any(s in err for s in ("could not resolve host", "failed to connect", "connection refused",
                                     "proxy", "timed out", "ssl", "tls", "403 forbidden"))
    if network and not any(s in err for s in ("authentication failed", "could not read username", "repository not found")):
        return RemoteInfo(False, error="No fue posible conectar con la plataforma desde el servidor de análisis. "
                                       "Si es un entorno con lista de hosts permitidos, el host debe estar autorizado.")
    return RemoteInfo(False, auth_required=auth, error=scrub(r.stderr, token)[:300])


def guess_production_branch(branches: list[str], default: Optional[str], hint: str = "") -> tuple[Optional[str], str]:
    if hint and hint in branches:
        return hint, "Indicada en el enlace."
    lowered = {b.lower(): b for b in branches}
    for cand in config.PRODUCTION_BRANCH_CANDIDATES:
        if cand in lowered:
            if lowered[cand] == default and cand in ("main", "master"):
                return lowered[cand], "Rama por defecto del repositorio (no existe una rama llamada «production»; confirme que es la de producción)."
            return lowered[cand], f"Existe una rama llamada «{lowered[cand]}»."
    if default:
        return default, "Rama por defecto del repositorio (confirme que es la de producción)."
    return None, ""


@dataclass
class CloneResult:
    path: Path
    sha: str
    date: str
    message: str


def clone_shallow(parsed: ParsedRepo, branch: str, token: Optional[str], dest: Path) -> CloneResult:
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--single-branch", "--no-tags", "--branch", branch,
           "--", parsed.clone_url, str(dest)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=config.CLONE_TIMEOUT,
                           env=_clean_env(token, parsed.platform))
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitError("El clonado superó el tiempo máximo permitido.")
    if r.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitError("No se pudo clonar el repositorio: " + scrub(r.stderr, token)[:300])

    size_mb = _dir_size_mb(dest)
    if size_mb > config.MAX_REPO_MB:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitError(f"El repositorio ({size_mb:.0f} MB) supera el límite de {config.MAX_REPO_MB} MB.")

    def g(*args: str) -> str:
        return subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True,
                              env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"}).stdout.strip()

    return CloneResult(dest, g("rev-parse", "HEAD"), g("log", "-1", "--format=%cI"), g("log", "-1", "--format=%s")[:200])


def _dir_size_mb(path: Path) -> float:
    total = 0
    for p, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(p, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def privacy_from_probe(without_token: RemoteInfo) -> Privacy:
    if without_token.reachable:
        return Privacy.public
    if without_token.auth_required:
        return Privacy.private
    return Privacy.unknown
