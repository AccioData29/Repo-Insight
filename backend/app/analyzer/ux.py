"""Evaluación de UI/UX a partir del código fuente (análisis estático).

Qué SÍ puede decir: si la interfaz sigue prácticas verificables en el código (accesibilidad, estados de carga/error/vacío,
formularios, consistencia visual, textos, adaptación a pantallas, navegación, pruebas) y si el canal elegido es coherente
con lo que el producto declara hacer.
Qué NO puede decir: si el diseño es bonito, claro o fácil para personas reales. Eso requiere pruebas con usuarios.
Cada chequeo muestra su evidencia y su confianza; los resultados son indicios, no un veredicto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models import EntryPoint, UxCheck, UxDimension, UxFinding, UxReview
from .common import FileInfo, Inventory, ev, sentence, words

_NONPROD = re.compile(r"(?i)(^|/)(tests?|__tests__|testing|fixtures?|mocks?|__mocks__|e2e|specs?|evidencias|docs?|poc|spikes?\w*|samples?|examples?|storybook)(/|$)|\.(test|spec|stories)\.|(^|/)tools/")
_RN = re.compile(r"""from\s+['"](?:react-native|expo)[^'"]*['"]""")
_JSX_WEB = re.compile(r"<(?:div|button|input|img|form|a|span|ul|table|section|main|nav)\b")
_UI_EXT = (".tsx", ".jsx", ".vue", ".html", ".cshtml", ".razor", ".svelte", ".xaml", ".xml", ".js", ".ts")

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class UiFile:
    fi: FileInfo
    text: str
    kind: str          # rn | web | android | xaml
    lines: list[str]


@dataclass
class Hit:
    f: UiFile
    line: int
    text: str


def _collect(inv: Inventory) -> list[UiFile]:
    out: list[UiFile] = []
    for fi in inv.files:
        if fi.is_test or fi.is_generated or fi.ext not in _UI_EXT or _NONPROD.search(fi.rel) or fi.size > 400_000:
            continue
        low = fi.rel.lower()
        if fi.ext == ".xml":
            if not re.search(r"(^|/)res/layout[^/]*/", low):
                continue
            kind = "android"
        elif fi.ext == ".xaml":
            kind = "xaml"
        else:
            text = inv.text(fi)
            if not text:
                continue
            if fi.ext in (".ts", ".js"):
                if not _RN.search(text) or "<" not in text:
                    continue
                kind = "rn"
            elif _RN.search(text):
                kind = "rn"
            elif fi.ext in (".html",) and not re.search(r"(?i)<(button|input|form|a\s|img|select|textarea|mat-)", text):
                continue
            elif fi.ext in (".tsx", ".jsx") and not _JSX_WEB.search(text):
                continue
            else:
                kind = "web"
            out.append(UiFile(fi, text, kind, text.splitlines()))
            continue
        text = inv.text(fi)
        if text:
            out.append(UiFile(fi, text, kind, text.splitlines()))
    return out


def _lines(files: list[UiFile], rx: re.Pattern, limit: int = 400) -> list[Hit]:
    hits: list[Hit] = []
    for f in files:
        for i, line in enumerate(f.lines, 1):
            if len(line) < 500 and rx.search(line) and not line.lstrip().startswith(("//", "*", "/*")):
                hits.append(Hit(f, i, line))
                if len(hits) >= limit:
                    return hits
    return hits


def _count(files: list[UiFile], rx: re.Pattern) -> int:
    return sum(len(rx.findall(f.text)) for f in files)


def _n(hits: list, lim: int) -> str:
    return f"{len(hits)}+" if len(hits) >= lim else str(len(hits))


def _evidence(hits: list[Hit], n: int = 6):
    seen, out = set(), []
    for h in hits:
        if h.f.fi.rel in seen:
            continue
        seen.add(h.f.fi.rel)
        out.append(ev(h.f.fi, h.line, h.text))
        if len(out) >= n:
            break
    return out


def _check(dim: str, label: str, passed: bool, detail: str, hits: Optional[list[Hit]] = None, *, severity: Optional[str] = None,
           why: str = "", fix: str = "", confidence: str = "media", occurrences: Optional[int] = None) -> UxCheck:
    return UxCheck(dimension=dim, label=label, passed=passed, detail=detail, evidence=_evidence(hits or []),
                   severity=severity if not passed else None, why_it_matters=why, how_to_fix=fix, confidence=confidence,  # type: ignore[arg-type]
                   occurrences=occurrences if occurrences is not None else len(hits or []),
                   files_affected=len({h.f.fi.rel for h in hits or []}))


# =============================================================================
# Chequeos por dimensión
# =============================================================================
_RN_INTERACTIVE = re.compile(r"<(?:Pressable|TouchableOpacity|TouchableHighlight|TouchableWithoutFeedback|Button|TextInput|Switch)\b")
_WEB_INTERACTIVE = re.compile(r"<(?:button|a\s|input|select|textarea)\b|\(click\)=|@click|\bonClick=", re.I)
_A11Y_PROPS = re.compile(r"\b(?:accessibilityLabel|accessibilityRole|accessible|accessibilityHint|accessibilityState|aria-label|aria-labelledby|aria-describedby|role|alt|htmlFor|contentDescription|AutomationProperties\.Name)\s*[=:]|<label\b|\[attr\.aria", re.I)


def _accessibility(files: list[UiFile]) -> list[UxCheck]:
    d = "accesibilidad"
    out: list[UxCheck] = []
    rn = [f for f in files if f.kind == "rn"]
    web = [f for f in files if f.kind == "web"]
    for group, tag_rx, name in ((rn, _RN_INTERACTIVE, "app móvil"), (web, _WEB_INTERACTIVE, "web")):
        if not group:
            continue
        tags = _count(group, tag_rx)
        if tags < 3:
            continue
        props = _count(group, _A11Y_PROPS)
        cov = min(1.0, props / tags)
        bare = [Hit(f, next((i for i, l in enumerate(f.lines, 1) if tag_rx.search(l)), 1),
                    next((l for l in f.lines if tag_rx.search(l)), "")) for f in group
                if tag_rx.search(f.text) and not _A11Y_PROPS.search(f.text)]
        ok = cov >= 0.6
        sev = None if ok else ("high" if cov < 0.2 else "medium")
        out.append(_check(
            d, "Botones y campos con etiqueta accesible", ok,
            f"{props} etiquetas/roles de accesibilidad para {tags} elementos interactivos en {name} (cobertura ≈ {int(cov * 100)}%).",
            bare, severity=sev,
            why="Las personas que usan lector de pantalla (TalkBack, VoiceOver, NVDA) oyen «botón» sin saber para qué sirve y no pueden completar la tarea. "
                "También afecta a quien navega con teclado o con control por voz.",
            fix="Agregar etiqueta y rol a cada elemento interactivo (accessibilityLabel/accessibilityRole en React Native, aria-label o <label> en web) "
                "y centralizarlo en los componentes base para que las pantallas lo hereden.",
            confidence="media", occurrences=max(0, tags - props)))
    if web:
        imgs = _lines(web, re.compile(r"<img\b(?![^>]*\balt\s*=)", re.I))
        out.append(_check(d, "Imágenes con texto alternativo", not imgs, "Imágenes <img> sin atributo alt." if imgs else "Todas las imágenes declaran alt.",
                          imgs, severity="medium",
                          why="Sin texto alternativo, el contenido de la imagen no existe para quien no la ve y las búsquedas no la entienden.",
                          fix="Agregar alt descriptivo (o alt=\"\" si es decorativa).", confidence="alta"))
        clickable = _lines(web, re.compile(r"<(?:div|span|li)\b[^>]*(?:onClick|\(click\)|@click)(?![^>]*\brole=)", re.I))
        out.append(_check(d, "Elementos clicables con semántica correcta", not clickable,
                          "Se usan <div>/<span> como botones sin rol." if clickable else "No se detectan <div>/<span> usados como botones.",
                          clickable, severity="medium",
                          why="Un <div> clicable no recibe foco con teclado ni se anuncia como botón: la función queda inaccesible para parte de los usuarios.",
                          fix="Usar <button> o <a>, o agregar role, tabIndex y manejo de teclado.", confidence="media"))
    scale = _lines(files, re.compile(r"allowFontScaling\s*=\s*\{\s*false\s*\}|maxFontSizeMultiplier\s*=\s*\{\s*1(\.0)?\s*\}"))
    if rn:
        out.append(_check(d, "Respeta el tamaño de letra del sistema", not scale,
                          "Se desactiva el escalado de fuente." if scale else "No se bloquea el tamaño de letra del sistema.", scale, severity="medium",
                          why="Quien necesita letra grande (adultos mayores, baja visión) no podrá agrandar los textos de la aplicación.",
                          fix="Eliminar allowFontScaling={false} y probar los diseños con la letra más grande del sistema.", confidence="alta"))
    return out


_ASYNC = re.compile(r"\bawait\b|\bfetch\(|axios|HttpClient|\.then\(|useQuery|subscribe\(", re.I)
_LOADING = re.compile(r"ActivityIndicator|isLoading|\bloading\b|\bspinner\b|skeleton|mat-spinner|ProgressBar|ProgressView|procesando|cargando|setProcessing|isProcessing|busy", re.I)
_ERRFB = re.compile(r"errorMessage|setError|\berrors?\.|ErrorBoundary|mat-error|invalid-feedback|role=\"alert\"|accessibilityRole=\"alert\"|accessibilityLiveRegion|Alert\.alert|toast|snackbar|validation-message|ValidationMessage|helperText|errorText", re.I)
_LIST = re.compile(r"FlatList|SectionList|\.map\(\s*\(?\w+|\*ngFor|v-for|<ul|<table|<RecyclerView|ListView", re.I)
_EMPTY = re.compile(r"ListEmptyComponent|EmptyState|\bempty\b|sin (?:datos|resultados|movimientos|registros)|no hay|no se encontr|vac[ií]o|no results|noData|nothing", re.I)
_OK_FB = re.compile(r"toast|snackbar|Alert\.alert|guardado|guardada|\bsaved\b|[ée]xito|success|confirmaci[oó]n", re.I)


def _states(files: list[UiFile]) -> list[UxCheck]:
    d = "estados"
    out: list[UxCheck] = []
    has_async = _count(files, _ASYNC) > 0
    if has_async:
        loading = _lines(files, _LOADING, 20)
        out.append(_check(d, "Indica que está trabajando (carga/procesamiento)", bool(loading),
                          f"{_n(loading, 20)} referencias a indicadores de carga." if loading else "Hay llamadas asíncronas pero ningún indicador de carga.",
                          loading, severity="medium",
                          why="Sin señal de progreso la persona cree que la app se congeló, toca varias veces o abandona.",
                          fix="Mostrar un indicador (spinner/skeleton) mientras se espera y deshabilitar la acción repetida.", confidence="media"))
    err = _lines(files, _ERRFB, 20)
    out.append(_check(d, "Comunica los errores a la persona", bool(err),
                      f"{_n(err, 20)} referencias a mensajes de error en pantalla." if err else "No se detectan mensajes de error visibles.",
                      err, severity="high",
                      why="Si algo falla en silencio, la persona no sabe si su acción funcionó ni cómo corregirla.",
                      fix="Mostrar un mensaje claro que diga qué pasó y qué hacer, junto al campo o la acción afectada.", confidence="media"))
    lists = _lines(files, _LIST, 20)
    if lists:
        empty = _lines(files, _EMPTY, 20)
        out.append(_check(d, "Tiene estados vacíos pensados (sin datos)", bool(empty),
                          f"{_n(empty, 20)} referencias a estados vacíos." if empty else "Hay listados pero ningún mensaje para cuando no hay datos.",
                          empty, severity="low",
                          why="Una pantalla en blanco al inicio no orienta a quien usa la aplicación por primera vez.",
                          fix="Mostrar un mensaje y una acción sugerida («Aún no hay movimientos. Registre el primero»).", confidence="media"))
    ok = _lines(files, _OK_FB, 20)
    out.append(_check(d, "Confirma las acciones exitosas", bool(ok),
                      f"{_n(ok, 20)} referencias a confirmaciones." if ok else "No se observan confirmaciones de éxito.",
                      ok, severity="low",
                      why="Sin confirmación la persona duda si la operación quedó guardada, sobre todo en datos importantes.",
                      fix="Confirmar con un mensaje breve (toast/snackbar) o cambiando de pantalla de forma clara.", confidence="baja"))
    return out


_INPUT = re.compile(r"<TextInput\b|<input\b|<textarea\b|<select\b|mat-form-field|<TextBox\b|<EditText\b|<Entry\b", re.I)


def _forms(files: list[UiFile]) -> list[UxCheck]:
    d = "formularios"
    inputs = _lines(files, _INPUT, 600)
    if not inputs:
        return []
    out: list[UxCheck] = []
    val = _lines(files, re.compile(r"helperText|errorText|mat-error|invalid-feedback|ValidationMessage|asp-validation|errors?\.\w+|fieldError|aria-invalid|accessibilityRole=\"alert\"", re.I), 20)
    out.append(_check(d, "Valida y explica el error junto al campo", bool(val),
                      f"{_n(val, 20)} referencias a mensajes de validación." if val else "No se detectan mensajes de validación asociados a los campos.",
                      val, severity="medium",
                      why="Un formulario que solo rechaza sin decir por qué obliga a adivinar y genera abandono.",
                      fix="Validar al salir del campo y mostrar el motivo junto a él, con lenguaje de la persona usuaria.", confidence="media"))
    hints = _lines(files, re.compile(r"keyboardType|textContentType|autoComplete|autoCapitalize|returnKeyType|inputMode|inputmode|type=[\"'](?:email|tel|number|password|date|url)[\"']|autocomplete=", re.I), 20)
    out.append(_check(d, "Usa el teclado y el autocompletado adecuados", bool(hints),
                      f"{_n(hints, 20)} campos con tipo/teclado específico." if hints else "Los campos no declaran tipo de teclado ni autocompletado.",
                      hints, severity="low",
                      why="Escribir un correo o un monto con el teclado equivocado es lento y propenso a errores, sobre todo en el celular.",
                      fix="Declarar keyboardType/inputMode, autocomplete y returnKeyType según el dato que se pide.", confidence="media"))
    if any(f.kind == "rn" for f in files):
        kb = _lines(files, re.compile(r"KeyboardAvoidingView|KeyboardAwareScrollView|keyboardShouldPersistTaps|keyboardVerticalOffset"), 10)
        out.append(_check(d, "El teclado no tapa los campos", bool(kb),
                          "Se maneja la aparición del teclado." if kb else "No se maneja la aparición del teclado.", kb, severity="medium",
                          why="Si el teclado tapa el campo o el botón de enviar, la persona no ve lo que escribe.",
                          fix="Envolver los formularios en KeyboardAvoidingView o un ScrollView con keyboardShouldPersistTaps.", confidence="media"))
    dbl = _lines(files, re.compile(r"\bdisabled\s*=|:disabled|\[disabled\]|isSubmitting|submitting|isLoading|isProcessing|setProcessing|setBusy|\bbusy\b", re.I), 10)
    out.append(_check(d, "Evita enviar dos veces la misma acción", bool(dbl),
                      "Se deshabilita la acción mientras procesa." if dbl else "No se observa bloqueo de doble envío.", dbl, severity="medium",
                      why="Un doble toque puede registrar dos veces un pago, un movimiento o una solicitud.",
                      fix="Deshabilitar el botón y mostrar progreso mientras la operación está en curso; hacer la operación idempotente en el servidor.", confidence="baja"))
    # formularios largos
    big = []
    for f in files:
        n = len(_INPUT.findall(f.text))
        if n >= 9 and not re.search(r"(?i)wizard|stepper|step\s*\d|paso\s*\d|mat-step|steps?\b", f.text):
            big.append(Hit(f, next((i for i, l in enumerate(f.lines, 1) if _INPUT.search(l)), 1), f"{n} campos en un solo formulario"))
    out.append(_check(d, "Formularios largos divididos en pasos", not big,
                      f"{len(big)} pantalla(s) con 9 o más campos sin pasos." if big else "No hay formularios largos sin dividir.", big, severity="low",
                      why="Cuantos más campos se piden de una vez, menos personas terminan el formulario.",
                      fix="Dividir en pasos con progreso visible, pedir solo lo indispensable y reutilizar datos ya conocidos.", confidence="baja"))
    return out


_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _consistency(inv: Inventory, files: list[UiFile]) -> list[UxCheck]:
    d = "consistencia"
    out: list[UxCheck] = []
    shared = [f for f in inv.dirs if f in ("components", "shared", "ui", "design-system", "common", "widgets")]
    out.append(_check(d, "Componentes visuales reutilizables", bool(shared),
                      f"Carpeta(s) de componentes: {', '.join(sorted(shared))}." if shared else "No hay una carpeta de componentes compartidos.",
                      severity="medium", why="Sin componentes comunes cada pantalla resuelve a su manera botones, campos y mensajes, y la experiencia se vuelve inconsistente.",
                      fix="Extraer botones, campos, tarjetas y mensajes a una biblioteca interna de componentes.", confidence="media"))
    theme_files = [f for f in inv.files if re.search(r"(?i)(^|/)(theme|themes|tokens?|colors?|palette|design-tokens|_variables)[^/]*\.(ts|tsx|js|json|s?css|less|xml|dart)$|styles?/(colors|theme)", f.rel)]
    css_vars = _lines(files, re.compile(r"--[a-z][\w-]*\s*:"), 5)
    has_theme = bool(theme_files or css_vars)
    out.append(_check(d, "Colores y espaciados definidos en un solo lugar (tema)", has_theme,
                      "Existe un archivo de tema/tokens." if has_theme else "No se detecta un tema o tokens de diseño.",
                      severity="medium", why="Cambiar la identidad visual, mejorar el contraste o agregar modo oscuro exige tocar decenas de archivos.",
                      fix="Definir tokens (colores, tipografía, espaciado) y consumirlos en lugar de valores sueltos.", confidence="media"))
    non_theme = [f for f in files if not re.search(r"(?i)(theme|tokens?|colors?|palette|variables|\.s?css$|\.less$)", f.fi.rel)]
    hexes = _lines(non_theme, _HEX, 800)
    distinct = {m.group(0).lower() for h in hexes for m in _HEX.finditer(h.text)}
    limit = 12 if not has_theme else 30
    bad = len(distinct) > limit
    out.append(_check(d, "Pocos colores escritos directamente en las pantallas", not bad,
                      f"{len(distinct)} colores distintos escritos directamente en {len({h.f.fi.rel for h in hexes})} archivo(s)." if hexes else "No hay colores escritos en las pantallas.",
                      hexes if bad else [], severity="low",
                      why="Muchos colores sueltos suelen ser tonos casi iguales: la interfaz pierde coherencia y es difícil garantizar contraste.",
                      fix="Reducir a una paleta corta, nombrarla y reutilizarla.", confidence="media", occurrences=len(distinct)))
    inline = _lines(files, re.compile(r"style=\{\{"), 800)
    heavy = len(inline) > 40
    out.append(_check(d, "Estilos agrupados y no en línea", not heavy,
                      f"{len(inline)} estilos en línea." if inline else "Casi no hay estilos en línea.", inline if heavy else [], severity="low",
                      why="Los estilos en línea se duplican y dificultan mantener el mismo aspecto en toda la app.",
                      fix="Mover a hojas de estilo/StyleSheet con nombres significativos.", confidence="baja"))
    return out


_I18N = re.compile(r"i18next|react-intl|formatjs|ngx-translate|@angular/localize|vue-i18n|expo-localization|react-native-localize|\.resx|gettext|IStringLocalizer|useTranslation|\$localize|FormattedMessage|Intl\.", re.I)
_TEXTS_FILE = re.compile(r"(?i)(^|/)([\w-]*(texts?|strings|messages|labels|copy|translations?)|locales?|i18n)\.(ts|tsx|js|json|xml|resx)$|(^|/)(locales?|i18n|translations?)/")


def _texts(inv: Inventory, files: list[UiFile]) -> list[UxCheck]:
    d = "textos"
    i18n = _lines(files, _I18N, 5)
    central = [f for f in inv.files if _TEXTS_FILE.search(f.rel) and not f.is_test]
    out: list[UxCheck] = []
    lit_rx = re.compile(r">\s*[A-Za-zÁÉÍÓÚÑáéíóúñ¿¡][^<>{}=;]{3,}<")
    lit = _lines([f for f in files if f.kind in ("web", "rn")], lit_rx, 400)
    ok = bool(i18n or central)
    out.append(_check(d, "Textos centralizados o traducibles", ok or len(lit) < 15,
                      ("Hay textos centralizados" + (f" ({len(central)} archivo(s))" if central else "") + (" y librería de idiomas" if i18n else "") + ".") if ok
                      else (f"{len(lit)} textos escritos directamente en las pantallas, sin librería de idiomas." if lit else "Pocos textos incrustados."),
                      lit if not ok and len(lit) >= 15 else [], severity="low",
                      why="Cambiar el tono, corregir ortografía o ofrecer otro idioma obliga a editar el código de cada pantalla.",
                      fix="Mover los textos a un catálogo (archivo de textos o librería de internacionalización).", confidence="media"))
    return out


def _adaptability(files: list[UiFile]) -> list[UxCheck]:
    d = "adaptabilidad"
    out: list[UxCheck] = []
    web = [f for f in files if f.kind == "web"]
    rn = [f for f in files if f.kind == "rn"]
    android = [f for f in files if f.kind == "android"]
    if web:
        r = _lines(files, re.compile(r"@media|clamp\(|minmax\(|flex-wrap|grid-template|container-type|useMediaQuery|BreakpointObserver|\bcol-(?:sm|md|lg)\b|name=\"viewport\"|sm:|md:|lg:"), 10)
        out.append(_check(d, "Se adapta a distintos tamaños de pantalla", bool(r),
                          "Hay reglas responsivas." if r else "No se detectan reglas responsivas ni viewport.", r, severity="medium",
                          why="Una página que no se adapta obliga a hacer zoom y desplazarse de lado en el celular, donde hoy ocurre la mayor parte del uso.",
                          fix="Diseñar mobile-first con media queries/grid fluido y declarar el viewport.", confidence="media"))
    if rn:
        r = _lines(files, re.compile(r"useWindowDimensions|Dimensions\.get|SafeAreaView|useSafeAreaInsets|SafeAreaProvider|KeyboardAvoidingView|Platform\.(?:OS|select)"), 10)
        out.append(_check(d, "Respeta áreas seguras y tamaños de pantalla", bool(r),
                          "Se usan áreas seguras/dimensiones." if r else "No se manejan áreas seguras ni dimensiones.", r, severity="low",
                          why="En celulares con notch o barras de sistema el contenido puede quedar tapado.",
                          fix="Usar SafeAreaProvider/SafeAreaView y medidas relativas.", confidence="media"))
    dark = _lines(files, re.compile(r"prefers-color-scheme|useColorScheme|Appearance\.|data-theme|ThemeProvider|darkMode|DayNight|colorScheme"), 5)
    out.append(_check(d, "Ofrece modo oscuro / sigue el tema del sistema", bool(dark),
                      "Hay soporte de tema claro/oscuro." if dark else "No se detecta soporte de modo oscuro.", dark, severity="low",
                      why="Es una preferencia de uso común y, para algunas personas, una necesidad de confort visual.",
                      fix="Definir paleta clara y oscura sobre tokens y respetar la preferencia del sistema.", confidence="baja"))
    return out


def _navigation(files: list[UiFile], screens: int) -> list[UxCheck]:
    d = "navegacion"
    if screens < 2:
        return []
    out: list[UxCheck] = []
    lib = _lines(files, re.compile(r"react-navigation|expo-router|react-router|RouterModule|vue-router|NavigationContainer|createStackNavigator|<Routes\b|routerLink|NavController|Shell\.Current|BottomTabBar|TabBar|Navigator\b|navigation|navbar|<nav\b", re.I), 10)
    out.append(_check(d, "Estructura de navegación definida", bool(lib),
                      "Hay navegación explícita (rutas, pestañas o barra)." if lib else f"{screens} pantallas sin una estructura de navegación reconocible.",
                      lib, severity="medium", why="Si no hay una estructura clara, las personas se pierden entre pantallas.",
                      fix="Definir un mapa de navegación (pestañas para lo principal, pila para el detalle) y documentarlo.", confidence="baja"))
    back = _lines(files, re.compile(r"goBack|BackHandler|history\.back|navigate\(-1\)|Location\.back|onBackPressed|backButton|\bVolver\b|\bAtr[aá]s\b|\bCancelar\b|onBack\b|onClose\b", re.I), 10)
    out.append(_check(d, "Permite volver o cancelar en cada pantalla", bool(back),
                      "Se manejan acciones de volver/cancelar." if back else "No se observan acciones de volver o cancelar.", back, severity="low",
                      why="Quedar atrapado en un flujo sin salida genera frustración, sobre todo si se entró por error.",
                      fix="Agregar «Volver/Cancelar» visibles y manejar el botón atrás del sistema.", confidence="baja"))
    return out


def _perf(files: list[UiFile]) -> list[UxCheck]:
    rn = [f for f in files if f.kind == "rn"]
    if not rn:
        return []
    bad = []
    for f in rn:
        if "<ScrollView" in f.text and re.search(r"\.map\(", f.text) and "FlatList" not in f.text and "SectionList" not in f.text:
            bad.append(Hit(f, next((i for i, l in enumerate(f.lines, 1) if "<ScrollView" in l), 1), "ScrollView con .map(...) en vez de FlatList"))
    return [_check("rendimiento", "Listados largos con virtualización", not bad,
                   f"{len(bad)} pantalla(s) pintan listados completos dentro de un ScrollView." if bad else "Los listados usan componentes virtualizados o no se detectan listados largos.",
                   bad, severity="low", why="Con cientos de registros la pantalla tarda en abrir y consume memoria; en celulares modestos se siente lenta.",
                   fix="Usar FlatList/SectionList (o paginación) para listados que pueden crecer.", confidence="baja")]


def _ui_tests(inv: Inventory, files: list[UiFile]) -> list[UxCheck]:
    d = "pruebas"
    rx = re.compile(r"@testing-library|react-test-renderer|detox|maestro|cypress|playwright|selenium|storybook|espresso|appium|protractor|karma|bunit|jest-expo", re.I)
    manifests = [f for f in inv.files if f.name in ("package.json", "build.gradle", "pubspec.yaml") or f.ext in (".csproj",)]
    hit_files = [f for f in manifests if rx.search(inv.text(f))]
    test_ids = _lines(files, re.compile(r"testID=|data-testid|data-cy|data-test"), 5)
    ui_test_files = [f for f in inv.files if f.is_test and re.search(r"(?i)screen|page|component|\.tsx$|\.spec\.ts$|e2e", f.rel)]
    ok = bool(hit_files or ui_test_files)
    hits = [Hit(UiFile(f, "", "web", []), 1, "dependencia de pruebas de interfaz") for f in hit_files[:3]]
    out = [_check(d, "Pruebas automáticas de la interfaz", ok,
                  (f"{len(ui_test_files)} archivo(s) de prueba de interfaz y {len(test_ids)}+ identificadores de prueba." if ok else "No se detectan pruebas de interfaz."),
                  hits, severity="low", why="Sin pruebas, cada cambio visual puede romper un flujo sin que nadie lo note hasta producción.",
                  fix="Cubrir los recorridos principales (entrar, registrar, consultar) con pruebas de componente y de extremo a extremo.", confidence="media")]
    axe = [f for f in manifests if re.search(r"jest-axe|axe-core|pa11y|lighthouse|cypress-axe|axe-playwright", inv.text(f), re.I)]
    out.append(_check(d, "Pruebas automáticas de accesibilidad", bool(axe),
                      "Hay herramientas de accesibilidad automática." if axe else "No hay verificación automática de accesibilidad.",
                      [], severity="low", why="La accesibilidad se degrada sin que nadie lo note si no se mide en cada cambio.",
                      fix="Integrar jest-axe/axe-core/Lighthouse en el CI.", confidence="media"))
    return out


def _complexity(files: list[UiFile]) -> list[UxCheck]:
    big: list[Hit] = []
    for f in files:
        if f.kind not in ("rn", "web"):
            continue
        hooks = len(re.findall(r"\buse(?:State|Effect|Ref|Callback|Memo|Reducer)\(", f.text))
        if hooks >= 14 or len(f.lines) > 600:
            big.append(Hit(f, 1, f"{hooks} hooks · {len(f.lines)} líneas"))
    return [_check("mantenibilidad", "Pantallas con una sola responsabilidad", not big,
                   f"{len(big)} pantalla(s) concentran demasiada lógica (muchos hooks o más de 600 líneas)." if big else "Las pantallas tienen un tamaño razonable.",
                   big, severity="medium" if len(big) >= 3 else "low",
                   why="Las pantallas muy cargadas son las que más se rompen al cambiar: cada mejora de experiencia cuesta más y tarda más.",
                   fix="Separar lógica en hooks/servicios y la pantalla en componentes pequeños.", confidence="media")]


# =============================================================================
# Ensamblado
# =============================================================================
DIM_INFO = {
    "accesibilidad": ("Accesibilidad", "¿Pueden usarla personas con lector de pantalla, letra grande o solo teclado?"),
    "estados": ("Estados y retroalimentación", "¿Le dice a la persona qué está pasando: cargando, error, sin datos, éxito?"),
    "formularios": ("Formularios", "¿Pedir datos es fácil, guiado y sin errores evitables?"),
    "consistencia": ("Consistencia visual", "¿Se ve y se comporta igual en todas las pantallas?"),
    "textos": ("Textos e idioma", "¿Los mensajes están ordenados y se pueden cambiar sin tocar el código?"),
    "adaptabilidad": ("Adaptación a pantallas y temas", "¿Funciona bien en distintos tamaños, orientaciones y temas?"),
    "navegacion": ("Navegación", "¿Se entiende dónde está la persona y cómo moverse?"),
    "rendimiento": ("Rendimiento percibido", "¿Se siente ágil con volúmenes reales de datos?"),
    "pruebas": ("Pruebas de interfaz", "¿Hay red de seguridad para cambiar la interfaz sin romperla?"),
    "mantenibilidad": ("Facilidad de evolución", "¿Se puede mejorar la interfaz sin miedo a romperla?"),
}
WHY_ORDER = list(DIM_INFO)


def _surface(files: list[UiFile], inv: Inventory) -> tuple[str, list[str]]:
    kinds = {f.kind for f in files}
    labels = []
    web_text = " ".join(f.text[:2000] for f in files if f.kind == "web")[:60_000]
    if "rn" in kinds:
        labels.append("Aplicación móvil multiplataforma (React Native)")
    if "android" in kinds:
        labels.append("Aplicación móvil Android nativa")
    if "xaml" in kinds:
        labels.append("Aplicación de escritorio o móvil (XAML)")
    if "web" in kinds:
        fw = "Angular" if re.search(r"\*ngFor|\(click\)|mat-", web_text) else "Vue" if any(f.fi.ext == ".vue" for f in files) \
            else "Razor/MVC" if any(f.fi.ext in (".cshtml", ".razor") for f in files) else "React/HTML"
        labels.append(f"Aplicación web ({fw})")
    return (" + ".join(labels) if labels else "Sin interfaz de usuario detectada"), labels


def _readme(inv: Inventory) -> str:
    for fi in inv.files:
        if fi.rel.lower() in ("readme.md", "readme.rst", "readme.txt", "readme"):
            return inv.text(fi)[:6000]
    return ""


def _pertinence(surface_labels: list[str], files: list[UiFile], screens: list[str], inv: Inventory, forms_present: bool) -> list[str]:
    readme = _readme(inv).lower()
    out: list[str] = []
    mobile = any("móvil" in s for s in surface_labels)
    web = any("web" in s for s in surface_labels)
    offline = bool(re.search(r"sin conexi[oó]n|offline|sin internet|local-first", readme))
    pwa = bool(_lines(files, re.compile(r"serviceWorker|manifest\.webmanifest|workbox"), 1))
    if mobile and offline:
        out.append("El canal es coherente con el objetivo declarado: una aplicación móvil nativa que guarda los datos en el dispositivo permite usarla sin conexión, "
                   "algo que una página web no ofrece de forma confiable.")
    elif mobile:
        out.append("El canal elegido es una aplicación móvil. Es adecuado si las personas usuarias la necesitan en movimiento o usan funciones del dispositivo "
                   "(cámara, notificaciones); si se usa sobre todo en un escritorio, una versión web ampliaría el alcance.")
    elif web:
        out.append("El canal elegido es web: no requiere instalación y llega a cualquier dispositivo."
                   + (" Incluye señales de aplicación instalable (PWA), lo que mejora el uso en celular." if pwa else
                      " No se detectan señales de aplicación instalable (PWA); si el uso principal es en celular, vale la pena evaluarla."))
    if screens:
        sample = ", ".join(sentence(s) for s in screens[:6])
        out.append(f"La interfaz cubre {len(screens)} recorrido(s) o pantallas principales: {sample}. "
                   "Conviene validar con quien opera el negocio que son los recorridos que más se usan y que no falta ninguno crítico.")
    sensitive = re.search(r"financ|gasto|ingreso|pago|banco|salud|m[eé]dic|cl[ií]nic|paciente|gobierno|tribut|factura|n[oó]mina", readme)
    if sensitive:
        out.append("El producto maneja información sensible o decisiones económicas/de salud. En ese contexto la claridad de los mensajes de error, "
                   "la confirmación de acciones y la accesibilidad son requisitos de confianza, no mejoras opcionales.")
    if forms_present:
        out.append("La captura de datos es parte central del uso. Cada campo adicional reduce la cantidad de personas que terminan; "
                   "revise que solo se pida lo indispensable y que lo ya conocido se reutilice.")
    out.append("Esta evaluación se basa en el código. La pertinencia real (si la interfaz resuelve la necesidad de las personas y se entiende a la primera) "
               "solo se confirma con pruebas de uso con 5 a 8 personas representativas.")
    return out


def build(inv: Inventory, entry_points: list[EntryPoint]) -> UxReview:
    files = _collect(inv)
    if not files:
        return UxReview(applicable=False, surface="Sin interfaz de usuario detectada", verdict="no_aplica",
                        headline="No se detectó una interfaz de usuario en este repositorio (parece un servicio sin pantallas).",
                        screens=0, ui_files=0, dimensions=[], findings=[], pertinence=[],
                        limits=["Si la interfaz vive en otro repositorio, analícelo por separado para evaluar su UI/UX."])
    surface, labels = _surface(files, inv)
    screen_names = [re.sub(r"\s+(screen|page)$", "", words(e.name), flags=re.I) for e in entry_points if e.kind == "Pantalla"]
    if not screen_names:
        names = {f.fi.name.rsplit(".", 1)[0] for f in files if re.search(r"(Screen|Page)\.(tsx|jsx|vue)$|\.component\.html$|\.cshtml$|\.razor$", f.fi.name)}
        screen_names = sorted(re.sub(r"\s+(screen|page)$", "", words(n), flags=re.I) for n in names)
    screens = len(screen_names)

    checks: list[UxCheck] = []
    checks += _accessibility(files) + _states(files) + _forms(files) + _consistency(inv, files) + _texts(inv, files) \
        + _adaptability(files) + _navigation(files, screens) + _perf(files) + _ui_tests(inv, files) + _complexity(files)

    dims: list[UxDimension] = []
    for did in WHY_ORDER:
        cs = [c for c in checks if c.dimension == did]
        if not cs:
            continue
        passed = sum(1 for c in cs if c.passed)
        ratio = passed / len(cs)
        hard_fail = any((not c.passed) and c.severity in ("high", "critical") for c in cs)
        medium_fail = any((not c.passed) and c.severity == "medium" for c in cs)
        status = "bueno" if ratio == 1 else "debil" if (hard_fail or (ratio < 0.5 and medium_fail)) else "aceptable"
        name, question = DIM_INFO[did]
        dims.append(UxDimension(id=did, name=name, question=question, status=status, checks=cs, passed=passed, total=len(cs)))  # type: ignore[arg-type]

    findings: list[UxFinding] = []
    for c in checks:
        if c.passed or not c.severity:
            continue
        findings.append(UxFinding(
            id="", dimension=c.dimension, title=c.label, severity=c.severity, why_it_matters=c.why_it_matters, how_to_fix=c.how_to_fix,
            detail=c.detail, occurrences=c.occurrences, files_affected=c.files_affected, evidence=c.evidence, confidence=c.confidence))  # type: ignore[arg-type]
    findings.sort(key=lambda f: (SEV_ORDER[f.severity], WHY_ORDER.index(f.dimension)))
    for i, f in enumerate(findings, 1):
        f.id = f"UX-{i:02d}"

    weak = [d for d in dims if d.status == "debil"]
    has_high = any(f.severity in ("critical", "high") for f in findings)
    verdict = "deficiente" if has_high or len(weak) >= 3 else "mejorable" if findings else "bueno"
    strong = [d.name.lower() for d in dims if d.status == "bueno"]
    headline = {
        "bueno": "La interfaz sigue las prácticas verificables en el código. Falta confirmarlo con personas usuarias.",
        "mejorable": f"La interfaz tiene bases sólidas pero {len(findings)} punto(s) a mejorar"
                     + (f" ({', '.join(d.name.lower() for d in weak)} es lo más débil)." if weak else "."),
        "deficiente": f"La interfaz tiene brechas importantes de usabilidad o accesibilidad ({len(findings)} hallazgo(s); "
                      + (f"lo más débil: {', '.join(d.name.lower() for d in weak)}" if weak else "hay al menos uno de prioridad alta") + ").",
    }[verdict]
    if verdict != "bueno" and strong:
        headline += f" Bien resuelto: {', '.join(strong[:3])}."
    forms_present = any(d.id == "formularios" for d in dims)
    return UxReview(
        applicable=True, surface=surface, verdict=verdict, headline=headline, screens=screens, screen_names=screen_names[:40],  # type: ignore[arg-type]
        ui_files=len(files), dimensions=dims, findings=findings, pertinence=_pertinence(labels, files, screen_names, inv, forms_present),
        limits=[
            "No se evalúa el aspecto visual, la claridad de los textos ni el orden de la información: eso requiere ver la aplicación y probarla con personas.",
            "La accesibilidad se estima contando etiquetas y roles en el código. Si la app usa componentes propios que ya los incluyen, un hallazgo puede ser un falso positivo.",
            "No se mide contraste de color, tamaño real de los botones ni comportamiento con lector de pantalla.",
        ])
