# Repo Insight

Entienda un repositorio sin leer todo el código. Usted entrega el enlace; el sistema analiza la **rama de producción en solo lectura** y produce un informe interactivo (vista negocio / vista técnica) con:

- **Reglas de negocio** (validaciones, restricciones, autorizaciones, procesos programados, parámetros, restricciones de BD), cada una con confianza y evidencia `archivo:línea`.
- **Flujos del sistema** (diagramas Mermaid + narrativa) desde los puntos de entrada hasta datos y sistemas externos.
- **Deuda técnica** con urgencia (crítica ≤7 días, alta ≤30, media ≤90, baja oportunista).
- **Arquitectura detectada** y **recomendaciones** con justificación técnica, costos y cuándo *no* aplicarlas.
- Exportación a Markdown, JSON e impresión/PDF.

## Ejecutar

```bash
# Con Docker
docker compose up --build        # http://localhost:8000

# Sin Docker (requiere Python 3.13, Node 22 y git)
cd frontend && npm ci && npm run build && cd ..
cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
```

Desarrollo: `uvicorn app.main:app --reload` en `backend/` y `npm run dev` en `frontend/` (proxy `/api`).
Pruebas: `cd backend && pytest`.

## Flujo en pantalla

1. URL + plataforma (autodetectada y **validada**: un enlace de GitLab marcado como GitHub se rechaza) + privacidad (público / privado / detectar).
2. Si es privado, el sistema indica **el permiso mínimo** de la plataforma (p. ej. GitHub: token de grano fino con *Contents: Read-only* y *Metadata: Read-only*) y pide el token.
3. Rama de producción: la indicada, o se deduce (`production`, `prod`, `release`, `main`, `master`, por defecto) y **se avisa si fue una suposición**.
4. Progreso → informe.

## Modelo de seguridad

- Solo `https` y lista exacta de hosts por plataforma (anti-SSRF).
- Privacidad detectada con `git ls-remote` sin credenciales.
- El token viaja por variables de entorno del proceso `git` (nunca en URL ni argumentos), se usa una vez y se descarta; los errores se limpian de credenciales.
- Clonado superficial (`--depth 1`), sin hooks, sin pedir credenciales interactivas, tamaño y número de archivos limitados; el clon se borra siempre al terminar.
- **El código analizado nunca se ejecuta.** Los secretos encontrados se enmascaran en cada fragmento del informe.
- Trabajos en memoria con vencimiento (1 h): no hay base de datos ni persistencia.

## Arquitectura

```
backend/app
  providers.py   plataformas (GitHub, GitLab, Azure DevOps, Bitbucket): parseo, validación, permisos, auth
  git_ops.py     ls-remote, rama de producción, clonado seguro
  jobs.py        orquestación y estado del análisis
  analyzer/      inventario · reglas · flujos · arquitectura · deuda · recomendaciones · (enrich opcional)
frontend/src     React + TypeScript + Vite + Mermaid
```

**Añadir una plataforma:** una clase en `providers.py` con host, patrones de URL, plantilla de enlace a archivo, cabecera de autenticación y texto de permisos; registrarla en la lista de proveedores.

**Añadir un detector de deuda / regla:** una función en `analyzer/debt.py` (`DETECTORS`) o `analyzer/rules.py`, con una prueba en `tests/`.

## Variables de entorno

`ANTHROPIC_API_KEY` (opcional: reescribe reglas con IA; apagado por defecto), `WORK_DIR`, `MAX_REPO_MB`, `FRONTEND_DIST`.

## Límites (léalos antes de confiar en el informe)

- Es **análisis estático heurístico**: puede tener falsos positivos y falsos negativos. Cada hallazgo muestra su confianza y evidencia para verificarlo.
- Cobertura más profunda en .NET, Java, Python, Node/TypeScript y Angular/React; otros lenguajes tienen cobertura parcial.
- No ve lo que no está en el código: reglas en procesos manuales, base de datos viva, configuración de producción, volumen real.
- Fechas de fin de soporte de tecnologías: verifíquelas con el fabricante.
- La mejora con IA no ha sido probada contra la API real; GitLab, Azure DevOps y Bitbucket están implementados y validados con pruebas, pero no contra servidores reales.
