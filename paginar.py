"""
paginar.py — Grillas paginadas en el servidor.

La mayoría de las grillas manda todas sus filas y `gestion_admTable` (base.html)
filtra, ordena y pagina en el navegador. Con miles de filas eso no escala: el
padrón de afiliados (5.617) pesaba 8,5 MB de HTML y tardaba en armarse y en
dibujarse. Una grilla grande manda una página: los filtros, el orden y la página
viajan en la URL (un form GET) y la base devuelve solo esas filas.

Del lado de la plantilla (ver /estilos, «Grilla paginada en el servidor»):

    <form method="get" id="frm-x" class="filter-bar"> … filtros con name=… </form>
    <table class="data-table" data-servidor="frm-x"> th con data-col="clave" </table>
    {{ ui.paginacion_srv(pag) }}

y `base.html` engancha el orden por columna y el buscador en vivo.
"""

from __future__ import annotations

from math import ceil

from flask import url_for

TAMANOS = (20, 50, 100)
TAMANO_DEFAULT = 50


def tamano(valor) -> int:
    """Filas por página: solo las de la lista. «Todos» no existe a propósito:
    es exactamente lo que hacía lenta la grilla."""
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return TAMANO_DEFAULT
    return n if n in TAMANOS else TAMANO_DEFAULT


def pagina(valor) -> int:
    try:
        return max(1, int(valor))
    except (TypeError, ValueError):
        return 1


def paginador(total: int, pag: int, tam: int, endpoint: str, args: dict) -> dict:
    """Lo que dibuja `ui.paginacion_srv` y el contador de la barra.

    `args` son los parámetros del listado (filtros, orden, tamaño): cada enlace
    los repite y cambia solo la página. Los vacíos no viajan, para que la URL
    quede legible.
    """
    paginas = max(1, ceil(total / tam)) if tam else 1
    pag = min(max(1, pag), paginas)
    base = {k: v for k, v in args.items() if v not in (None, "") and k != "pagina"}

    def url(p):
        return url_for(endpoint, **base, **({"pagina": p} if p > 1 else {}))

    def boton(etiqueta, p, activo=False):
        deshabilitado = p < 1 or p > paginas or (p == pag and not activo)
        return {"etiqueta": etiqueta, "url": None if deshabilitado else url(p),
                "activo": activo}

    enlaces = [boton("«", 1 if pag > 1 else 0), boton("‹", pag - 1)]
    lo, hi = max(1, pag - 2), min(paginas, pag + 2)
    if lo > 1:
        enlaces.append(boton("1", 1))
        if lo > 2:
            enlaces.append({"sep": True})
    for p in range(lo, hi + 1):
        enlaces.append(boton(str(p), p, activo=(p == pag)))
    if hi < paginas:
        if hi < paginas - 1:
            enlaces.append({"sep": True})
        enlaces.append(boton(str(paginas), paginas))
    enlaces += [boton("›", pag + 1), boton("»", paginas if pag < paginas else 0)]

    desde = 0 if total == 0 else (pag - 1) * tam + 1
    hasta = min(pag * tam, total)
    return {"total": total, "pagina": pag, "paginas": paginas, "tam": tam,
            "desde": desde, "hasta": hasta, "offset": (pag - 1) * tam,
            "enlaces": enlaces}
