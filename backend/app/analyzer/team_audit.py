"""Auditoría del equipo a partir del historial de git: prácticas de trabajo, riesgo de concentración y coautorías.

Qué evalúa: controles de proceso VISIBLES en git (revisión por pares, trazabilidad, calidad de mensajes, tamaño de cambios, factor de bus,
continuidad, pruebas, identidades) y qué respaldo tiene cada coautoría declarada.
Qué NO es: una evaluación de desempeño de personas. Las líneas de código no miden productividad ni calidad; aquí solo se usan para estimar
dónde vive el conocimiento y qué riesgo existe si una persona se va. No se miden horarios ni se muestran correos.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timedelta
from typing import Any

from ..models import (AreaOwnership, AuditCheck, CoauthorAudit, Collaborator, PersonActivity, TeamAudit, TeamTimeline,
                      TimelineSeries)

_AI_CLS = ("ia_autor", "ia_coautor")
_TRACE = re.compile(r"(?<![\w/])#\d{1,6}\b|\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b|\b(?:HU|US|AJ|RF|REQ|E)-[\w-]+", re.I)
_CONV = re.compile(r"^(feat|fix|docs|refactor|test|tests|chore|perf|build|ci|style|revert|merge|release)(\([^)]+\))?!?:\s", re.I)
_VAGUE = re.compile(r"^(update|updates|fix|fixes|wip|changes?|misc|stuff|asdf|\.+|test|commit|cambios?|arreglos?)\b.{0,12}$", re.I)
_PR = re.compile(r"(?i)^merge pull request|^merged pr|\(#\d+\)\s*$")     # evidencia de PR (no una fusión local)


def _top_area(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) == 1:
        return "(raíz)"
    if parts[0] in ("app", "src", "packages", "apps", "services") and len(parts) >= 3:
        return "/".join(parts[:2])
    return parts[0]


def _days(a: str, b: str) -> int:
    try:
        return max(0, (datetime.fromisoformat(a[:10]) - datetime.fromisoformat(b[:10])).days)
    except ValueError:
        return 0


def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _check(id_: str, label: str, status: str, detail: str, why: str = "", fix: str = "", sev: str | None = None) -> AuditCheck:
    return AuditCheck(id=id_, label=label, status=status, severity=sev if status in ("parcial", "no_cumple") else None,  # type: ignore[arg-type]
                      detail=detail, why=why, how_to_fix=fix)


def _timeline(commits: list[Any], coauthors: list[CoauthorAudit]) -> TeamTimeline | None:
    """Actividad por periodo y por colaborador. Igual que la gráfica «Contributors» de GitHub: sin commits de fusión, y el coautor
    de un commit recibe el crédito completo de ese commit (commits y líneas agregadas)."""
    real = [c for c in commits if c.parents <= 1]
    if not real:
        return None
    days = [_date.fromisoformat(c.date[:10]) for c in real]
    first, last = min(days), max(days)
    monthly = (last - first).days > 730
    def bucket(d: _date) -> _date:
        return d.replace(day=1) if monthly else d - timedelta(days=d.weekday())
    start, end = bucket(first), bucket(last)
    buckets: list[_date] = []
    cur = start
    while cur <= end:
        buckets.append(cur)
        cur = (cur.replace(year=cur.year + (cur.month == 12), month=cur.month % 12 + 1) if monthly else cur + timedelta(days=7))
    idx = {b: i for i, b in enumerate(buckets)}
    nb = len(buckets)
    total_c, total_a = [0] * nb, [0] * nb
    acc: dict[str, dict] = {}

    def add(name: str, kind: str, role: str, i: int, added: int) -> None:
        a = acc.setdefault(name.strip().lower(), dict(name=name, kind=kind, roles=set(), c=[0] * nb, a=[0] * nb))
        a["roles"].add(role)
        a["c"][i] += 1
        a["a"][i] += added
        if kind == "persona" and a["kind"] != "persona":
            a["kind"] = kind

    for c, d in zip(real, days):
        i = idx[bucket(d)]
        total_c[i] += 1
        total_a[i] += c.added
        add(c.author, "ia" if c.cls == "ia_autor" else "bot" if c.cls == "bot" else "persona", "autor", i, c.added)
        for nm, kind in c.coauthors:
            add(nm, kind, "coautor", i, c.added)
    series = []
    for a in sorted(acc.values(), key=lambda x: -sum(x["c"])):
        roles = a["roles"]
        role = "autor y coautor" if len(roles) == 2 else next(iter(roles))
        series.append(TimelineSeries(name=a["name"], kind=a["kind"], role=role, commits=a["c"], added=a["a"],  # type: ignore[arg-type]
                                     total_commits=sum(a["c"]), total_added=sum(a["a"])))
    # ---- lecturas que sustentan la auditoría ----
    ins: list[str] = []
    n_real, tot_added = len(real), sum(total_a)
    active = sum(1 for x in total_c if x)
    unit = "mes" if monthly else "semana"
    pk = max(range(nb), key=lambda i: total_c[i])
    ins.append(f"El trabajo se concentra: la {unit} del {buckets[pk].isoformat()} reúne {total_c[pk]} de {n_real} commits ({_pct(total_c[pk], n_real)}%).")
    if nb >= 8:
        tail = sum(total_c[-4:])
        ins.append(f"Las últimas 4 {unit}s concentran el {_pct(tail, n_real)}% de los commits; hubo actividad en {active} de {nb} {unit}s.")
    ia_total = next((x for x in series if x.kind == "ia"), None)
    authors = [x for x in series if x.kind == "persona" and "autor" in x.role]
    if ia_total and authors:
        ins.append(f"«{ia_total.name}» figura en {ia_total.total_commits} commits, casi los mismos que «{authors[0].name}» ({authors[0].total_commits}): "
                   "la actividad de la persona y la de la IA son prácticamente la misma.") if ia_total.total_commits >= 0.8 * authors[0].total_commits else None
    for x in series:
        if x.kind == "persona" and x.role == "coautor" and x.total_commits <= 3 and tot_added and x.total_added / tot_added >= 0.02:
            ins.append(f"{x.name} figura en {x.total_commits} commit(s) que agregaron {x.total_added:,} líneas ({_pct(x.total_added, tot_added)}% de todo lo agregado). "
                       "Es una coautoría de peso que conviene respaldar con commits propios o con el PR donde se revisó.".replace(",", "."))
    ins = [i for i in ins if i]
    return TeamTimeline(granularity="mes" if monthly else "semana", buckets=[b.isoformat() for b in buckets], total_commits=total_c, total_added=total_a,  # type: ignore[arg-type]
                        series=series, insights=ins,
                        note="Igual que la gráfica «Contributors» de GitHub: no cuenta commits de fusión y el coautor de un commit recibe el crédito completo de ese commit.")


def build(commits: list[Any], survive: Counter, blames: dict[str, dict[str, int]], by_sha: dict[str, Any],
          collabs: list[Collaborator], total: int) -> TeamAudit:
    if not commits:
        return TeamAudit(applicable=False, headline="Sin historial para auditar.")
    n = len(commits)
    last_date = max(c.date for c in commits)
    people = [c for c in collabs if c.kind == "persona"]
    key = lambda name: name.strip().lower()           # noqa: E731
    person_keys = {key(c.name) for c in people}

    # ---------- factor de bus y concentración ----------
    shares = sorted((c.codebase_share_pct for c in people), reverse=True)
    acc, bus = 0.0, 0
    for s in shares:
        acc += s
        bus += 1
        if acc > 50:
            break
    bus = bus if shares else 0
    top = shares[0] if shares else 0.0

    # ---------- actividad ----------
    activity: list[PersonActivity] = []
    for c in people:
        d = _days(last_date, c.last_commit) if c.last_commit else 0
        status = "activa" if d <= 30 else "reciente" if d <= 90 else "inactiva"
        activity.append(PersonActivity(name=c.name, status=status, last_commit=c.last_commit, days_since=d, codebase_share_pct=c.codebase_share_pct))  # type: ignore[arg-type]
    inactive_share = sum(a.codebase_share_pct for a in activity if a.status == "inactiva")

    # ---------- áreas ----------
    per_area: dict[str, Counter] = defaultdict(Counter)
    ai_area: Counter = Counter()
    for rel, counts in blames.items():
        area = _top_area(rel)
        for sha, lines in counts.items():
            c = by_sha.get(sha)
            who = c.author if c else "(historial anterior)"
            per_area[area][who] += lines
            if c and c.cls in _AI_CLS:
                ai_area[area] += lines
    areas: list[AreaOwnership] = []
    for area, cnt in sorted(per_area.items(), key=lambda kv: -sum(kv[1].values()))[:10]:
        tot = sum(cnt.values())
        owner, ol = cnt.most_common(1)[0]
        areas.append(AreaOwnership(area=area, lines=tot, owner=owner, owner_pct=_pct(ol, tot), ai_pct=_pct(ai_area[area], tot), contributors=len(cnt)))
    single_owner = [a for a in areas if a.contributors == 1 or a.owner_pct >= 90]

    prs = sum(1 for c in commits if _PR.search(c.subject))
    reviewed = sum(1 for c in commits if re.search(r"(?im)^(reviewed-by|approved-by|acked-by):", c.body))

    # ---------- coautorías ----------
    authored = Counter(key(c.author) for c in commits)
    co: dict[tuple[str, str], dict] = {}
    for c in commits:
        for nm, kind in c.coauthors:
            d = co.setdefault((key(nm), kind), dict(name=nm, kind=kind, commits=0, pair=Counter(), areas=Counter(), first=c.date, last=c.date))
            d["commits"] += 1
            d["pair"][c.author] += 1
            d["first"], d["last"] = min(d["first"], c.date), max(d["last"], c.date)
            for rel, lines in c.files.items():
                d["areas"][_top_area(rel)] += max(1, lines)
    coauthors: list[CoauthorAudit] = []
    for (k, kind), d in sorted(co.items(), key=lambda kv: -kv[1]["commits"]):
        own = authored.get(k, 0)
        if kind == "persona":
            if own:
                note = f"También figura como autora/autor de {own} commit(s): su colaboración es verificable."
            else:
                note = ("Figura como coautor/a (GitHub la/lo muestra como contribuyente por esa coautoría) pero no publicó commits propios en esta rama: "
                        "su aporte no se puede verificar en git (puede ser trabajo en pareja o un reconocimiento). Conviene confirmarlo.")
        else:
            humans = ", ".join(list(d["pair"])[:2])
            note = (f"Herramienta de IA declarada. Quien publica ese código es {humans}; no hay revisión independiente registrada en git."
                    if not (prs or reviewed) else f"Herramienta de IA declarada. Publica {humans}; hay PR o revisiones en el historial, aunque no ligadas commit a commit.")
        coauthors.append(CoauthorAudit(name=d["name"], kind=kind, commits=d["commits"], paired_with=[p for p, _ in d["pair"].most_common(3)],  # type: ignore[arg-type]
                                       areas=[a for a, _ in d["areas"].most_common(3)], first_commit=d["first"][:10], last_commit=d["last"][:10],
                                       authored_commits=own, verifiable=bool(own) if kind == "persona" else False, note=note))
    with_co = sum(1 for c in commits if c.coauthors)
    human_co = [x for x in coauthors if x.kind == "persona"]

    # ---------- controles ----------
    checks: list[AuditCheck] = []
    review_share = _pct(max(prs, reviewed), n)
    ai_commits = [c for c in commits if c.cls in _AI_CLS]
    if len(person_keys) < 2:
        checks.append(_check("revision", "Revisión por pares", "no_cumple", "Una sola persona publica todos los cambios" + (f" ({prs} PR, {reviewed} «Reviewed-by»)" if prs or reviewed else "") + ": no hay una segunda persona que los revise en git.",
                             "Sin una segunda mirada, los errores y las malas prácticas (propias o de la IA) llegan a producción sin filtro.",
                             "Trabajar con ramas y Pull Requests, exigir al menos una aprobación y proteger la rama de producción.", "high" if ai_commits else "medium"))
    elif review_share >= 30:
        checks.append(_check("revision", "Revisión por pares", "cumple", f"{prs} fusiones de PR y {reviewed} commits con revisión explícita ({review_share}%)."))
    else:
        checks.append(_check("revision", "Revisión por pares", "parcial" if review_share > 0 else "no_cumple",
                             f"Solo {review_share}% de los commits pasa por fusión de PR o revisión explícita.",
                             "Hay equipo, pero la mayoría de los cambios entra sin revisión visible.", "Exigir Pull Requests con aprobación para la rama de producción.", "medium"))
    if ai_commits:
        rev_ai = reviewed > 0 or prs > 0
        checks.append(_check("ia_supervision", "Supervisión del código generado por IA", "parcial" if rev_ai else "no_cumple",
                             f"{len(ai_commits)} commits con IA declarada; " + ("hay fusiones/revisiones en el historial, pero no se puede ligar cada commit de IA a una revisión." if rev_ai else "ninguno muestra revisión independiente."),
                             "El código de IA debe revisarse como el de cualquier persona nueva del equipo: es rápido de producir y fácil de aceptar sin entender.",
                             "Revisión obligatoria de PR para cambios con IA, pruebas automáticas como condición de fusión y registro de quién aprobó.", "high" if not rev_ai else "medium"))
    trace = sum(1 for c in commits if _TRACE.search(c.subject + " " + c.body))
    ts = _pct(trace, n)
    checks.append(_check("trazabilidad", "Trazabilidad de cambios (ticket/historia en el commit)", "cumple" if ts >= 60 else "parcial" if ts >= 25 else "no_cumple",
                         f"{trace} de {n} commits ({ts}%) referencian una historia, ticket o requisito.",
                         "Sin referencia al requisito no se puede auditar por qué se hizo un cambio ni conectarlo con el negocio.",
                         "Incluir el identificador de la historia en cada commit o en el nombre de la rama.", "medium" if ts < 25 else "low"))
    conv = sum(1 for c in commits if _CONV.match(c.subject))
    vague = sum(1 for c in commits if _VAGUE.match(c.subject.strip()))
    cs = _pct(conv, n)
    checks.append(_check("mensajes", "Mensajes de commit claros", "cumple" if cs >= 70 and vague <= n * 0.05 else "parcial" if cs >= 30 else "no_cumple",
                         f"{cs}% usa un formato convencional (feat/fix/docs…) y {vague} commit(s) tienen mensajes vagos.",
                         "Mensajes claros permiten generar el historial de cambios y entender incidentes.", "Adoptar «Conventional Commits» y validarlos en el CI.", "low"))
    big = sum(1 for c in commits if c.added >= 800 or len(c.files) >= 25)
    bs = _pct(big, n)
    checks.append(_check("tamano", "Cambios pequeños y revisables", "cumple" if bs <= 10 else "parcial" if bs <= 25 else "no_cumple",
                         f"{big} de {n} commits ({bs}%) son muy grandes (800+ líneas o 25+ archivos).",
                         "Los cambios gigantes no se pueden revisar con rigor y son difíciles de revertir.", "Entregar en incrementos pequeños, uno por historia o corrección.", "medium" if bs > 25 else "low"))
    if people:
        checks.append(_check("bus", "Conocimiento repartido (factor de bus)", "cumple" if bus >= 3 else "parcial" if bus == 2 else "no_cumple",
                             f"Factor de bus {bus}: {'una sola persona concentra' if bus == 1 else f'{bus} personas concentran'} más de la mitad del código vigente (la principal tiene {top}%).",
                             "Si esa persona se va, nadie más conoce el sistema a fondo.", "Rotar quién trabaja cada área, hacer revisión cruzada y documentar decisiones.", "high" if bus == 1 else "medium"))
    if len(people) >= 1:
        with_tests = [c for c in people if c.test_share_pct >= 5]
        eligible = [c for c in people if c.lines_surviving >= 50]
        if eligible:
            ok = len([c for c in eligible if c in with_tests])
            st = "cumple" if ok == len(eligible) else "parcial" if ok else "no_cumple"
            checks.append(_check("pruebas", "Cada persona escribe pruebas", st, f"{ok} de {len(eligible)} contribuyentes con aporte relevante tienen al menos 5% de sus líneas en pruebas.",
                                 "Si solo algunas personas prueban, el resto del código no tiene red de seguridad.", "Acordar que todo cambio incluya sus pruebas.", "medium"))
    multi = [c for c in people if len({x.email for x in commits if key(x.author) == key(c.name)}) > 1]
    checks.append(_check("identidad", "Identidades consistentes en el historial", "parcial" if multi else "cumple",
                         f"{len(multi)} persona(s) firman con más de un correo." if multi else "Cada persona usa una identidad única.",
                         "Con identidades duplicadas se reparte mal el aporte y la auditoría pierde precisión.", "Consolidar con un archivo .mailmap y configurar user.name/user.email.", "low"))
    if people:
        checks.append(_check("continuidad", "Continuidad del conocimiento", "cumple" if inactive_share < 20 else "parcial" if inactive_share < 50 else "no_cumple",
                             f"{round(inactive_share, 1)}% del código vigente pertenece a personas sin actividad en más de 90 días." if inactive_share else "Quien escribió el código vigente sigue activo.",
                             "Código cuyo autor ya no participa es código que nadie sabe explicar.", "Traspasar y documentar lo que escribieron personas que ya no participan.", "medium"))
    if human_co:
        unv = [x for x in human_co if not x.verifiable]
        checks.append(_check("coautorias", "Coautorías humanas verificables", "cumple" if not unv else "parcial",
                             (f"{len(unv)} de {len(human_co)} coautor(es) humano(s) no tienen commits propios: " + ", ".join(x.name for x in unv[:3]) + ".") if unv
                             else "Todos los coautores humanos también aparecen como autores.",
                             "Una coautoría sin commits propios no se puede comprobar en git.", "Pedir que quien colabora publique sus propios commits o registrar el trabajo en pareja en el PR.", "low"))

    bad = [c for c in checks if c.status == "no_cumple"]
    high = [c for c in bad if c.severity == "high"]
    partial = [c for c in checks if c.status == "parcial"]
    level = "riesgoso" if len(high) >= 2 or len(bad) >= 4 else "mejorable" if bad or len(partial) >= 2 else "solido"
    worst = ", ".join(c.label.lower() for c in (high or bad)[:3]).replace(" ia", " IA")
    solo = " (equipo de una sola persona: los controles dependen de su disciplina individual)" if len(people) == 1 else ""
    headline = {
        "solido": "El equipo muestra controles de proceso sólidos en git.",
        "mejorable": "El equipo tiene bases de proceso, pero hay controles por reforzar" + (f": {worst}." if worst else "."),
        "riesgoso": f"El proceso de trabajo tiene riesgos importantes: {worst}.",
    }[level] + solo
    return TeamAudit(
        applicable=True, level=level, headline=headline, people=len(people), bus_factor=bus, top_share_pct=top,  # type: ignore[arg-type]
        commits_with_coauthor_pct=_pct(with_co, n), checks=checks, coauthors=coauthors, areas=areas, activity=activity, timeline=_timeline(commits, coauthors),
        limits=[
            "Es una auditoría de proceso con evidencia de git, no una evaluación de desempeño: las líneas de código no miden productividad ni calidad de una persona.",
            "No se miden horarios ni se muestran correos. Los nombres vienen del historial y pueden ser alias o cuentas compartidas.",
            "Una revisión hecha fuera del repositorio (reunión, chat, programación en pareja) no deja rastro y no se cuenta como revisión.",
            "El factor de bus se estima con las líneas vigentes: un archivo pequeño pero crítico puede tener un solo dueño y no verse aquí.",
            "No se evalúan firmas de commits ni protecciones de rama: eso se configura en la plataforma, no en el historial.",
            "La coautoría declarada es autodeclarada: git no verifica que la persona participó.",
        ] + (["Se muestran solo las 10 áreas con más código." ] if len(per_area) > 10 else []))
