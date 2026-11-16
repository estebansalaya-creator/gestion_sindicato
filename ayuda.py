"""
ayuda.py — El registro de los manuales de uso (pedido del 15/11/2026).

El sistema de ayuda de gestion_adm (`ayuda.py`, `ayuda_render.py`,
`templates/ayuda/manual.html`), con el sistema de estilos de acá y sin las
demos animadas. Cada módulo del menú tiene su manual en un archivo
`ayuda_<módulo>.py` que es SOLO DATOS:

    CLAVE     "fiscalizacion"                 la URL: /ayuda/fiscalizacion
    MODULO    "Fiscalización de Cuotas"       el título
    INTRO     html                            qué es el módulo, en un párrafo o dos
    CIRCUITO  [(paso, descripción), …]        el recorrido, en tarjetas numeradas
    SECCIONES [{…}, …]                        una por pantalla (o por tema)

Una sección:

    id         ancla (única en todo el sistema: el botón Ayuda la busca por ahí)
    grupo      el rótulo que la agrupa en el índice (opcional)
    titulo     el nombre de la pantalla, como en el menú
    url        la dirección de la pantalla, sin parámetros: «Ir a la pantalla» y
               el permiso (`db.puede`); vacía en una sección de un tema
    endpoints  las pantallas que abren esta sección con el botón Ayuda
    resumen    una línea
    bloques    [{"tipo": …}, …]:
                 texto     {"html": …}                 un párrafo
                 lista     {"items": [html, …]}        viñetas
                 pasos     {"items": [html, …]}        pasos numerados
                 campos    {"items": [(rótulo, html)]} qué es cada dato o botón
                 criterio  {"html": …}                 cómo decide el sistema
                 aviso     {"html": …}                 lo que hay que tener en cuenta

**El botón Ayuda** (flotante, abajo a la derecha de base.html, y F1) abre el manual en la sección de la
pantalla en la que se está (`url_ayuda(endpoint)`); en una pantalla sin manual,
el índice de todos (/ayuda). Para que una pantalla nueva tenga ayuda alcanza
con poner su endpoint en `endpoints` de una sección; `tests/test_ayuda.py` avisa
de las que quedaron sin ayuda (las que no la necesitan van en `SIN_AYUDA`).

Este archivo no depende de Flask: los manuales se cargan y se verifican desde
un script suelto. Las pantallas están en ayuda_pantallas.py.
"""

from __future__ import annotations

import importlib
import re

#: Los manuales, en el orden del índice (el del menú).
MANUALES = (
    "ayuda_general",
    "ayuda_mesa",
    "ayuda_fiscalizacion",
    "ayuda_empleadores",
    "ayuda_padron",
    "ayuda_proveedores",
    "ayuda_tesoreria",
    "ayuda_pagos",
    "ayuda_reintegros",
    "ayuda_contabilidad",
    "ayuda_administracion",
)

TIPOS_BLOQUE = {"texto", "lista", "pasos", "campos", "criterio", "aviso"}

#: Pantallas que no llevan ayuda: no son pantallas (JSON, archivos, PDF) o son
#: de afuera (el portal de las empresas, el login). El resto, si no está en un
#: manual, lo marca tests/test_ayuda.py.
SIN_AYUDA = {
    "static", "login", "logout", "estilos", "ayuda.indice", "ayuda.manual",
    "portal.empresa", "portal.presentacion", "portal.planilla_portal", "portal.manual",
    "institucion.logo", "contactos.abm_areas",
    # El instructivo de las empresas, en PDF (instructivo_empresa.py).
    "portal.instructivo", "fisca_lsd.instructivo_interno",
}
#: Lo mismo por forma del endpoint: lo que devuelve datos o un archivo.
_RE_SIN_AYUDA = re.compile(
    r"(^|[._])(api|pdf|exportar|descargar|archivo|planilla|adjunto|constancia|logo|tmp|json)([._]|$)"
    r"|^(buscador|exportar)\.|_pdf|_ruta$|pdf_tmp|ver_documento"
    # Lo que la pantalla pide por detrás: la solapa de aportes, la consulta a
    # ARCA (y el avance de «Actualizar desde ARCA»), la razón social de un CUIT,
    # el código del plan, el detalle de un período del acta, el saldo inicial y
    # con qué se canceló un comprobante.
    r"|\.(aportes|consultar_arca|empleadores_arca_estado|buscar_empleador|plan_codigo|acta_periodo"
    r"|saldo_inicial_json|aplicaciones_de)$"
)

_cargados: dict[str, dict] = {}
_por_endpoint: dict[str, tuple[str, str]] = {}


def cargar() -> None:
    """Importa los manuales (una vez). Un manual mal armado se nota acá, al
    arrancar, y no cuando alguien abre la ayuda."""
    if _cargados:
        return
    for nombre in MANUALES:
        m = importlib.import_module(nombre)
        man = {"clave": m.CLAVE, "modulo": m.MODULO, "intro": m.INTRO,
               "circuito": list(getattr(m, "CIRCUITO", [])), "secciones": list(m.SECCIONES)}
        _cargados[m.CLAVE] = man
        for s in man["secciones"]:
            for ep in s.get("endpoints", []):
                _por_endpoint.setdefault(ep, (m.CLAVE, s["id"]))


def manuales() -> list[dict]:
    cargar()
    return list(_cargados.values())


def manual(clave: str) -> dict | None:
    cargar()
    return _cargados.get(clave)


def de_endpoint(endpoint: str | None) -> tuple[str, str] | None:
    """(manual, sección) de una pantalla, o None si no tiene ayuda."""
    cargar()
    return _por_endpoint.get(endpoint or "")


def sin_ayuda(endpoint: str) -> bool:
    return endpoint in SIN_AYUDA or bool(_RE_SIN_AYUDA.search(endpoint))


def verificar(reglas: list[tuple[str, str, set]], url_valida=None) -> list[str]:
    """
    Los problemas de los manuales contra las rutas de la aplicación.
    `reglas`: (ruta, endpoint, métodos) de cada regla del url_map.
    `url_valida(url)`: si una dirección es una pantalla (por defecto, si es
    igual a una ruta; la aplicación pasa el `match` de Werkzeug, que entiende
    las rutas con parámetros como /tesoreria/movimientos/nuevo/<operacion>).
    """
    cargar()
    problemas = []
    endpoints = {ep for _, ep, _ in reglas}
    rutas = {r for r, _, _ in reglas}
    url_valida = url_valida or (lambda u: u in rutas)
    ids = {}
    for man in _cargados.values():
        if not man["intro"].strip():
            problemas.append(f"{man['clave']}: sin introducción")
        for s in man["secciones"]:
            sid = s.get("id", "")
            donde = f"{man['clave']}#{sid}"
            if not sid or not re.fullmatch(r"[a-z0-9_-]+", sid):
                problemas.append(f"{donde}: id vacío o con caracteres raros")
            if sid in ids:
                problemas.append(f"{donde}: id repetido (también en {ids[sid]})")
            ids[sid] = man["clave"]
            for campo in ("titulo", "resumen", "bloques"):
                if not s.get(campo):
                    problemas.append(f"{donde}: falta {campo}")
            if s.get("url") and not url_valida(s["url"]):
                problemas.append(f"{donde}: la url {s['url']} no es una pantalla")
            for ep in s.get("endpoints", []):
                if ep not in endpoints:
                    problemas.append(f"{donde}: el endpoint {ep} no existe")
            for b in s.get("bloques", []):
                if b.get("tipo") not in TIPOS_BLOQUE:
                    problemas.append(f"{donde}: bloque de tipo {b.get('tipo')!r}")
                elif b["tipo"] in ("lista", "pasos", "campos") and not b.get("items"):
                    problemas.append(f"{donde}: {b['tipo']} sin items")
                elif b["tipo"] in ("texto", "criterio", "aviso") and not b.get("html"):
                    problemas.append(f"{donde}: {b['tipo']} sin html")
    return problemas


def sin_manual(reglas: list[tuple[str, str, set]]) -> list[str]:
    """Las pantallas (GET) que no están en ningún manual ni en SIN_AYUDA."""
    cargar()
    return sorted({ep for _, ep, metodos in reglas
                   if "GET" in metodos and ep not in _por_endpoint and not sin_ayuda(ep)})
