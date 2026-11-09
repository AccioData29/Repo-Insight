"""Proveedores de repositorios (GitHub, GitLab, Azure DevOps, Bitbucket).

Cada proveedor sabe:
  * reconocer y normalizar una URL (y rechazar la que no le corresponde),
  * qué permiso de SOLO LECTURA hay que pedir para un repo privado,
  * cómo autenticar `git` con un token sin dejarlo en la línea de comandos,
  * cómo construir un enlace al archivo/línea para la vista técnica.

Agregar una plataforma nueva = escribir una subclase de `Provider` y registrarla en `PROVIDERS`.
La validación es estricta (host exacto + https) para evitar SSRF y descargas hacia hosts arbitrarios.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .models import PermissionHelp, Platform


@dataclass
class ParsedRepo:
    platform: Platform
    host: str
    owner: str            # org / grupo / workspace
    repo: str
    project: str = ""     # solo Azure DevOps
    branch_hint: str = ""
    clone_url: str = ""
    web_url: str = ""


class UrlError(ValueError):
    pass


_SAFE_SEG = re.compile(r"^[A-Za-z0-9_.\-~%]+$")


def _check_segments(parts: list[str]) -> None:
    for p in parts:
        if not p or p in (".", "..") or not _SAFE_SEG.match(p):
            raise UrlError("El enlace contiene caracteres no permitidos en la ruta del repositorio.")


def _strip_git(name: str) -> str:
    return name[:-4] if name.endswith(".git") else name


def _normalize_input(raw: str) -> str:
    raw = raw.strip()
    # git@github.com:owner/repo.git  ->  https://github.com/owner/repo.git
    m = re.match(r"^git@([\w.\-]+):(.+)$", raw)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"
    if raw.startswith("ssh://"):
        p = urlparse(raw)
        return f"https://{p.hostname}{p.path}"
    return raw


class Provider:
    platform: Platform
    label: str
    hosts: tuple[str, ...]
    analysis_supported = True

    def parse(self, url: str) -> ParsedRepo:
        raise NotImplementedError

    def permission_help(self, parsed: ParsedRepo) -> PermissionHelp:
        raise NotImplementedError

    def auth_header(self, token: str) -> str:
        raise NotImplementedError

    def blob_template(self, parsed: ParsedRepo) -> str:
        return ""

    # util
    def _host_ok(self, host: str) -> bool:
        return host.lower() in self.hosts


class GitHub(Provider):
    platform = Platform.github
    label = "GitHub"
    hosts = ("github.com", "www.github.com")

    def parse(self, url: str) -> ParsedRepo:
        p = urlparse(_normalize_input(url))
        if p.scheme != "https" or not self._host_ok(p.hostname or ""):
            raise UrlError("El enlace no corresponde a GitHub (se espera https://github.com/<dueño>/<repo>).")
        parts = [s for s in p.path.split("/") if s]
        if len(parts) < 2:
            raise UrlError("Falta el repositorio: use https://github.com/<dueño>/<repo>.")
        owner, repo = parts[0], _strip_git(parts[1])
        _check_segments([owner, repo])
        hint = "/".join(parts[3:]) if len(parts) >= 4 and parts[2] == "tree" else ""
        return ParsedRepo(self.platform, "github.com", owner, repo, branch_hint=hint,
                          clone_url=f"https://github.com/{owner}/{repo}.git",
                          web_url=f"https://github.com/{owner}/{repo}")

    def permission_help(self, parsed: ParsedRepo) -> PermissionHelp:
        return PermissionHelp(
            needed=True,
            token_kind="Token de acceso personal de granularidad fina (fine-grained PAT)",
            scopes=["Repository access: solo este repositorio", "Contents: Read-only", "Metadata: Read-only"],
            create_url="https://github.com/settings/personal-access-tokens/new",
            steps=[
                "Abra el enlace e indique un nombre y una fecha de expiración corta (p. ej. 7 días).",
                f"En «Repository access» elija «Only select repositories» y seleccione {parsed.owner}/{parsed.repo}.",
                "En «Permissions → Repository permissions» marque Contents: Read-only (Metadata se agrega solo).",
                "Genere el token y péguelo aquí. Solo se usa en memoria para clonar y se descarta al terminar.",
            ],
            note="Si el repositorio pertenece a una organización, puede requerir aprobación del administrador.",
        )

    def auth_header(self, token: str) -> str:
        return "AUTHORIZATION: basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()

    def blob_template(self, parsed: ParsedRepo) -> str:
        return f"{parsed.web_url}/blob/{{sha}}/{{path}}#L{{line}}"


class GitLab(Provider):
    platform = Platform.gitlab
    label = "GitLab"
    hosts = ("gitlab.com", "www.gitlab.com")

    def parse(self, url: str) -> ParsedRepo:
        p = urlparse(_normalize_input(url))
        if p.scheme != "https" or not self._host_ok(p.hostname or ""):
            raise UrlError("El enlace no corresponde a GitLab (se espera https://gitlab.com/<grupo>/<repo>).")
        path = p.path.split("/-/")[0]
        parts = [s for s in path.split("/") if s]
        if len(parts) < 2:
            raise UrlError("Falta el repositorio: use https://gitlab.com/<grupo>/<repo>.")
        parts[-1] = _strip_git(parts[-1])
        _check_segments(parts)
        full = "/".join(parts)
        hint = ""
        m = re.search(r"/-/tree/(.+)$", p.path)
        if m:
            hint = m.group(1).rstrip("/")
        return ParsedRepo(self.platform, "gitlab.com", "/".join(parts[:-1]), parts[-1], branch_hint=hint,
                          clone_url=f"https://gitlab.com/{full}.git", web_url=f"https://gitlab.com/{full}")

    def permission_help(self, parsed: ParsedRepo) -> PermissionHelp:
        return PermissionHelp(
            needed=True,
            token_kind="Project Access Token o Personal Access Token",
            scopes=["read_repository"],
            create_url="https://gitlab.com/-/user_settings/personal_access_tokens",
            steps=[
                "Cree un token con fecha de expiración corta.",
                "Marque únicamente el alcance «read_repository» (rol mínimo: Reporter).",
                "Péguelo aquí; se usa solo en memoria y se descarta al terminar.",
            ],
        )

    def auth_header(self, token: str) -> str:
        return "AUTHORIZATION: basic " + base64.b64encode(f"oauth2:{token}".encode()).decode()

    def blob_template(self, parsed: ParsedRepo) -> str:
        return f"{parsed.web_url}/-/blob/{{sha}}/{{path}}#L{{line}}"


class AzureDevOps(Provider):
    platform = Platform.azure_devops
    label = "Azure DevOps"
    hosts = ("dev.azure.com",)

    def parse(self, url: str) -> ParsedRepo:
        p = urlparse(_normalize_input(url))
        host = (p.hostname or "").lower()
        parts = [s for s in p.path.split("/") if s]
        if p.scheme != "https":
            raise UrlError("El enlace no corresponde a Azure DevOps (se espera https://dev.azure.com/<org>/<proyecto>/_git/<repo>).")
        if host == "dev.azure.com":
            # https://dev.azure.com/org/project/_git/repo  (también con usuario@ delante)
            if len(parts) < 4 or parts[2] != "_git":
                raise UrlError("Use el formato https://dev.azure.com/<org>/<proyecto>/_git/<repo>.")
            org, project, repo = parts[0], parts[1], _strip_git(parts[3])
        elif host.endswith(".visualstudio.com"):
            org = host.split(".")[0]
            if len(parts) < 3 or parts[1] != "_git":
                raise UrlError("Use el formato https://<org>.visualstudio.com/<proyecto>/_git/<repo>.")
            project, repo = parts[0], _strip_git(parts[2])
        else:
            raise UrlError("El enlace no corresponde a Azure DevOps (se espera https://dev.azure.com/<org>/<proyecto>/_git/<repo>).")
        _check_segments([org, project, repo])
        return ParsedRepo(self.platform, "dev.azure.com", org, repo, project=project,
                          clone_url=f"https://dev.azure.com/{org}/{project}/_git/{repo}",
                          web_url=f"https://dev.azure.com/{org}/{project}/_git/{repo}")

    def permission_help(self, parsed: ParsedRepo) -> PermissionHelp:
        return PermissionHelp(
            needed=True,
            token_kind="Personal Access Token (PAT)",
            scopes=["Code: Read"],
            create_url=f"https://dev.azure.com/{parsed.owner}/_usersSettings/tokens",
            steps=[
                "Cree un PAT con expiración corta y organización específica.",
                "En «Scopes → Custom defined» marque solo «Code → Read».",
                "Péguelo aquí; se usa solo en memoria y se descarta al terminar.",
            ],
        )

    def auth_header(self, token: str) -> str:
        return "AUTHORIZATION: basic " + base64.b64encode(f":{token}".encode()).decode()

    def blob_template(self, parsed: ParsedRepo) -> str:
        return f"{parsed.web_url}?path=/{{path}}&version=GC{{sha}}&line={{line}}&lineStartColumn=1"


class Bitbucket(Provider):
    platform = Platform.bitbucket
    label = "Bitbucket"
    hosts = ("bitbucket.org", "www.bitbucket.org")

    def parse(self, url: str) -> ParsedRepo:
        p = urlparse(_normalize_input(url))
        if p.scheme != "https" or not self._host_ok(p.hostname or ""):
            raise UrlError("El enlace no corresponde a Bitbucket (se espera https://bitbucket.org/<workspace>/<repo>).")
        parts = [s for s in p.path.split("/") if s]
        if len(parts) < 2:
            raise UrlError("Falta el repositorio: use https://bitbucket.org/<workspace>/<repo>.")
        owner, repo = parts[0], _strip_git(parts[1])
        _check_segments([owner, repo])
        return ParsedRepo(self.platform, "bitbucket.org", owner, repo,
                          clone_url=f"https://bitbucket.org/{owner}/{repo}.git",
                          web_url=f"https://bitbucket.org/{owner}/{repo}")

    def permission_help(self, parsed: ParsedRepo) -> PermissionHelp:
        return PermissionHelp(
            needed=True,
            token_kind="Repository Access Token",
            scopes=["Repositories: Read"],
            create_url=f"https://bitbucket.org/{parsed.owner}/{parsed.repo}/admin/access-tokens",
            steps=[
                "En el repositorio abra Settings → Security → Access tokens.",
                "Cree un token con el único permiso «Repositories: Read».",
                "Péguelo aquí; se usa solo en memoria y se descarta al terminar.",
            ],
        )

    def auth_header(self, token: str) -> str:
        return "AUTHORIZATION: basic " + base64.b64encode(f"x-token-auth:{token}".encode()).decode()

    def blob_template(self, parsed: ParsedRepo) -> str:
        return f"{parsed.web_url}/src/{{sha}}/{{path}}#lines-{{line}}"


PROVIDERS: dict[Platform, Provider] = {
    p.platform: p for p in (GitHub(), GitLab(), AzureDevOps(), Bitbucket())
}


def detect_platform(url: str) -> Optional[Platform]:
    """Detecta la plataforma solo por el host (sin validar el resto de la ruta)."""
    try:
        host = (urlparse(_normalize_input(url)).hostname or "").lower()
    except ValueError:
        return None
    for prov in PROVIDERS.values():
        if host in prov.hosts or (prov.platform == Platform.azure_devops and host.endswith(".visualstudio.com")):
            return prov.platform
    return None


def parse_repo(url: str, forced: Optional[Platform] = None) -> tuple[Provider, ParsedRepo]:
    """Valida la URL contra la plataforma detectada y, si el usuario eligió una, que coincidan."""
    if not url or len(url) > 500:
        raise UrlError("Ingrese el enlace del repositorio.")
    detected = detect_platform(url)
    if detected is None:
        raise UrlError("No reconozco la plataforma de ese enlace. Soportadas: GitHub, GitLab, Azure DevOps y Bitbucket (https).")
    if forced and forced not in (Platform.unknown, detected):
        raise UrlError(
            f"El enlace pertenece a {PROVIDERS[detected].label}, pero eligió {PROVIDERS[forced].label}. "
            "Corrija la plataforma o el enlace."
        )
    prov = PROVIDERS[detected]
    return prov, prov.parse(url)
