"""
afiliados_dni.py — «Carga de DNI» (/afiliados/dni, menú Padrón de Afiliados).

Pedido del 25/11/2026: subir las fotos del DNI en una pantalla general, que
busque si la persona está en el padrón y, si está, guarde frente y dorso en su
documentación y recorte la cara para la foto de la ficha.

En dos pasos, como la carga de comprobantes:

1. **Leer** (`accion=leer`). Una o dos imágenes, en cualquier orden.
   lector_dni.py dice cuál es el frente (el del código PDF417 o el de la cara),
   lee el código y recorta la foto. Las imágenes y la foto quedan en
   `tmp_dni/` (disco y bucket: el paso 2 lo puede atender otra instancia) con
   una ficha de 32 hex, y un .json con lo leído: al formulario viaja la ficha,
   nunca una ruta ni los datos.
   Se busca al afiliado por el número de documento del código (en
   `nro_documento` y en los 8 del medio del CUIL). Cada candidato sale con lo
   que coincide y lo que no (apellido, nombres, nacimiento, sexo).
   Si el código no se leyó, se puede buscar a mano por número.
2. **Guardar** (`accion=guardar`), con el afiliado elegido: cada imagen va a
   la documentación con su tipo («DNI — frente» / «DNI — dorso», por código
   en p_tipo_documentacion) y la foto a `p_afiliados.foto`. Todo auditado.
   Nada se guarda sin que alguien elija el afiliado y confirme: el número del
   código puede coincidir con otra persona (dos personas con el mismo DNI en
   AEDA, un familiar mal cargado).

Si no está en el padrón, se ofrece el alta con los datos del código ya
puestos (/afiliados?nuevo=1&…); después del alta se vuelve a cargar el DNI.

`?para=<id>` (el botón «Cargar DNI» de la ficha) trae a ese afiliado como
candidato aunque el número no coincida, con el aviso.

Permiso: la opción de menú de esta pantalla (modifica la ficha).
"""

from __future__ import annotations

import json
import re
import secrets
import time
import unicodedata
from datetime import date
from pathlib import Path

from flask import (Blueprint, render_template, request, redirect, url_for, flash, send_file)

import afiliado_foto as _foto
import almacenamiento
import documentacion as _doc
import lector_dni
from afiliados import _afiliado, _catalogos, _registrar, _usuario, puede_abm
from db import get_connection, puede, validasesion

afiliados_dni_bp = Blueprint("afiliados_dni", __name__, template_folder="templates")

URL = "/afiliados/dni"
TMP = "tmp_dni"
RE_FICHA = re.compile(r"^[0-9a-f]{32}$")
EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_MB = 10
MAX_IMAGENES = 2
LADOS = {"frente": "dni_frente", "dorso": "dni_dorso"}


# ─────────────────────────────────────────────────────────────────────────────
# Archivos de paso
# ─────────────────────────────────────────────────────────────────────────────

def _tmp() -> Path:
    d = almacenamiento.base() / TMP
    d.mkdir(parents=True, exist_ok=True)
    return d


def _limpiar_viejos():
    """Lo de cargas abandonadas (más de 2 días), en el disco y de vez en cuando en el bucket."""
    limite = time.time() - 2 * 86400
    for viejo in _tmp().glob("*"):
        try:
            if viejo.is_file() and viejo.stat().st_mtime < limite:
                almacenamiento.borrar(viejo)
        except OSError:
            pass
    if secrets.randbelow(50) == 0:
        almacenamiento.limpiar_viejos(TMP, 2)


def _ruta_tmp(ficha: str, sufijo: str) -> Path | None:
    if not RE_FICHA.match(ficha or "") or not re.match(r"^[a-z0-9_.]+$", sufijo):
        return None
    return _tmp() / f"{ficha}_{sufijo}"


def _leer_carga(ficha: str) -> dict | None:
    p = _ruta_tmp(ficha, "carga.json")
    datos = almacenamiento.leer(p) if p else None
    return json.loads(datos) if datos else None


def _guardar_carga(ficha: str, carga: dict):
    almacenamiento.guardar(_ruta_tmp(ficha, "carga.json"),
                           json.dumps(carga, ensure_ascii=False, default=str).encode("utf-8"),
                           "application/json")


def _borrar_carga(ficha: str, carga: dict):
    for img in carga.get("imagenes", []):
        almacenamiento.borrar(_ruta_tmp(ficha, img["archivo"]))
    if carga.get("foto"):
        almacenamiento.borrar(_ruta_tmp(ficha, carga["foto"]))
    almacenamiento.borrar(_ruta_tmp(ficha, "carga.json"))


# ─────────────────────────────────────────────────────────────────────────────
# Búsqueda y comparación
# ─────────────────────────────────────────────────────────────────────────────

def _plano(txt) -> str:
    """Mayúsculas, sin acentos ni signos: para comparar nombres."""
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]", " ", t.upper())


def _palabras(txt) -> list[str]:
    return [p for p in _plano(txt).split() if len(p) > 1]


def comparar(datos: dict | None, af: dict) -> list[dict]:
    """
    Lo que dice el DNI frente a la ficha: [{campo, dni, ficha, ok}].
    ok = None cuando el DNI no trae el dato (no se puede comparar).
    """
    if not datos:
        return []
    ficha_pal = set(_palabras(af.get("apellido_nombres")))
    ape, nom = _palabras(datos.get("apellido")), _palabras(datos.get("nombres"))
    fn_dni = datos.get("fecha_nacimiento")
    fn_ficha = af.get("fecha_nacimiento")
    filas = [
        {"campo": "Documento", "dni": datos.get("dni"), "ficha": af.get("nro_documento") or "—",
         "ok": str(datos.get("dni") or "").lstrip("0") == str(af.get("nro_documento") or "").lstrip("0")},
        {"campo": "Apellido", "dni": datos.get("apellido"), "ficha": af.get("apellido_nombres"),
         "ok": bool(ape) and all(p in ficha_pal for p in ape)},
        {"campo": "Nombres", "dni": datos.get("nombres"), "ficha": af.get("apellido_nombres"),
         # Con el primer nombre alcanza: AEDA a veces tiene uno solo.
         "ok": bool(nom) and nom[0] in ficha_pal},
        {"campo": "Nacimiento", "dni": fn_dni.strftime("%d/%m/%Y") if fn_dni else "—",
         "ficha": fn_ficha.strftime("%d/%m/%Y") if fn_ficha else "—",
         "ok": (fn_dni == fn_ficha) if (fn_dni and fn_ficha) else None},
        {"campo": "Sexo", "dni": datos.get("sexo") or datos.get("sexo_codigo") or "—",
         "ficha": af.get("sexo") or "—",
         "ok": (datos["sexo"] == af.get("sexo")) if (datos.get("sexo") and af.get("sexo")) else None},
    ]
    return filas


def _candidatos(cur, dni: str, para: int | None) -> list[dict]:
    """Los afiliados con ese documento (o con él en el CUIL), más el de `?para=`."""
    filas: list[dict] = []
    columnas = """a.id_afiliado, a.cuil, a.apellido_nombres, a.tipo_documento, a.nro_documento, a.sexo,
                  a.fecha_nacimiento, a.cod_parentesco, a.activo, a.fecha_baja, a.foto,
                  p.descripcion AS parentesco"""
    if dni:
        cur.execute(f"""
            SELECT {columnas} FROM p_afiliados a
              LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
             WHERE (a.nro_documento REGEXP '^[0-9]+$' AND CAST(a.nro_documento AS UNSIGNED) = %s)
                OR (a.cuil REGEXP '^[0-9]{{11}}$' AND SUBSTRING(a.cuil, 3, 8) = LPAD(%s, 8, '0'))
             ORDER BY a.activo DESC, a.cod_parentesco, a.apellido_nombres""", (int(dni), dni))
        filas = list(cur.fetchall())
    if para and not any(f["id_afiliado"] == para for f in filas):
        cur.execute(f"""SELECT {columnas} FROM p_afiliados a
                          LEFT JOIN p_parentesco p ON p.codigo = a.cod_parentesco
                         WHERE a.id_afiliado = %s""", (para,))
        f = cur.fetchone()
        if f:
            f["no_coincide"] = True
            filas.insert(0, f)
    return filas


def _tipos_dni(cur) -> dict[str, int]:
    cur.execute("SELECT codigo, id_tipo_doc FROM p_tipo_documentacion WHERE codigo IN (%s, %s) AND activo = 1",
                tuple(LADOS.values()))
    por_codigo = {f["codigo"]: f["id_tipo_doc"] for f in cur.fetchall()}
    return {lado: por_codigo[c] for lado, c in LADOS.items() if c in por_codigo}


# ─────────────────────────────────────────────────────────────────────────────
# Pantalla
# ─────────────────────────────────────────────────────────────────────────────

def _guardia():
    if not validasesion():
        return redirect(url_for("login"))
    if not puede(URL):
        flash("!No tenés permiso para la carga de DNI.")
        return redirect(url_for("menu"))
    return None


def _entero(valor) -> int | None:
    v = str(valor or "").strip()
    return int(v) if v.isdigit() else None


@afiliados_dni_bp.route(URL, methods=["GET", "POST"])
def carga_dni():
    salida = _guardia()
    if salida:
        return salida
    para = _entero(request.values.get("para"))
    accion = request.form.get("accion", "") if request.method == "POST" else ""

    if accion == "leer":
        return _leer(para)
    if accion == "buscar":
        return _resultado(request.form.get("ficha", ""), para, dni_manual=re.sub(r"\D", "", request.form.get("dni", "")))
    if accion == "guardar":
        return _guardar(request.form.get("ficha", ""))
    if accion == "descartar":
        carga = _leer_carga(request.form.get("ficha", ""))
        if carga:
            _borrar_carga(request.form["ficha"], carga)
        return redirect(url_for("afiliados_dni.carga_dni", para=para or None))

    afiliado_para = None
    if para:
        with get_connection() as conn:
            with conn.cursor() as cur:
                afiliado_para = _afiliado(cur, para)
    return render_template("afiliados/carga_dni.html", paso="subir", para=para, afiliado_para=afiliado_para,
                           faltan=lector_dni.disponible(), max_mb=MAX_MB)


def _leer(para):
    archivos = [a for a in request.files.getlist("imagenes") if a and a.filename][:MAX_IMAGENES + 1]
    volver = redirect(url_for("afiliados_dni.carga_dni", para=para or None))
    if not archivos:
        flash("!Elegí la foto del frente del DNI (y, si la tenés, la del dorso).")
        return volver
    if len(archivos) > MAX_IMAGENES:
        flash(f"!Hasta {MAX_IMAGENES} imágenes: el frente y el dorso.")
        return volver

    _limpiar_viejos()
    ficha = secrets.token_hex(16)
    carga = {"imagenes": [], "foto": None, "datos": None, "para": para}
    try:
        for i, arch in enumerate(archivos):
            original = Path(arch.filename).name.strip() or f"dni_{i + 1}.jpg"
            ext = Path(original).suffix.lower()
            if ext not in EXTENSIONES:
                flash(f"!{original}: tiene que ser una foto (JPG, PNG o WEBP).")
                return volver
            contenido = arch.read()
            if not contenido:
                flash(f"!{original}: el archivo está vacío.")
                return volver
            if len(contenido) > MAX_MB * 1024 * 1024:
                flash(f"!{original}: supera los {MAX_MB} MB.")
                return volver
            leido = lector_dni.leer(contenido)
            nombre = f"img{i}{ext}"
            almacenamiento.guardar(_ruta_tmp(ficha, nombre), contenido, _doc.MIME.get(ext, ""))
            carga["imagenes"].append({"archivo": nombre, "original": original, "lado": leido["lado"],
                                      "avisos": leido["avisos"], "domicilio": leido["domicilio"],
                                      "codigo_leido": bool(leido["datos"])})
            if leido["datos"] and not carga["datos"]:
                carga["datos"] = leido["datos"]
            if leido["foto"] and not carga["foto"]:
                carga["foto"] = "foto.jpg"
                almacenamiento.guardar(_ruta_tmp(ficha, "foto.jpg"), leido["foto"], "image/jpeg")
    except lector_dni.LectorError as e:
        flash(f"!{e}")
        return volver

    # Dos imágenes del mismo lado: la que no tiene el código es la otra.
    imgs = carga["imagenes"]
    if len(imgs) == 2 and imgs[0]["lado"] == imgs[1]["lado"]:
        otra = 1 if imgs[0]["codigo_leido"] else 0 if imgs[1]["codigo_leido"] else 1
        imgs[otra]["lado"] = "dorso" if imgs[0]["lado"] == "frente" else "frente"
        imgs[otra]["avisos"].append("Se tomó como " + imgs[otra]["lado"] + " por descarte: revisalo.")
    _guardar_carga(ficha, carga)
    return redirect(url_for("afiliados_dni.carga_dni_ver", ficha=ficha))


@afiliados_dni_bp.route(URL + "/<ficha>")
def carga_dni_ver(ficha):
    """El resultado de la lectura (paso 2), por GET: se puede recargar sin volver a subir."""
    salida = _guardia()
    if salida:
        return salida
    return _resultado(ficha, None)


def _resultado(ficha: str, para, dni_manual: str = ""):
    carga = _leer_carga(ficha)
    if not carga:
        flash("!Esa carga ya no está (se guardó, se descartó o pasaron más de dos días). Subí las fotos otra vez.")
        return redirect(url_for("afiliados_dni.carga_dni"))
    para = para or carga.get("para")
    datos = carga.get("datos")
    if datos:       # en el .json las fechas quedaron como texto ISO
        for k in ("fecha_nacimiento", "fecha_emision", "fecha_vencimiento"):
            if isinstance(datos.get(k), str):
                datos[k] = date.fromisoformat(datos[k]) if datos[k] else None
    dni = dni_manual or (datos or {}).get("dni") or ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            candidatos = _candidatos(cur, dni, para)
    for c in candidatos:
        c["comparacion"] = comparar(datos, c)
        c["diferencias"] = sum(1 for f in c["comparacion"] if f["ok"] is False)
    # Preelegido: el único, o el que coincide en todo.
    sin_dif = [c for c in candidatos if not c["diferencias"] and not c.get("no_coincide")]
    elegido = (candidatos[0]["id_afiliado"] if len(candidatos) == 1
               else sin_dif[0]["id_afiliado"] if len(sin_dif) == 1 else None)

    alta = None
    if datos and not candidatos:
        alta = {"nuevo": 1, "tipo_documento": "DU", "nro_documento": datos["dni"],
                "apellido_nombres": datos["apellido_nombres"],
                "fecha_nacimiento": datos.get("fecha_nacimiento") or "",
                "sexo": datos.get("sexo") or ""}
    return render_template("afiliados/carga_dni.html", paso="resultado", ficha=ficha, carga=carga,
                           datos=datos, dni_buscado=dni, dni_manual=dni_manual, candidatos=candidatos,
                           elegido=elegido, alta=alta, para=para, puede_abm=puede_abm(),
                           faltan=[], max_mb=MAX_MB)


@afiliados_dni_bp.route(URL + "/<ficha>/<archivo>")
def carga_dni_archivo(ficha, archivo):
    """Las imágenes y la foto de una carga en curso, para mostrarlas en el paso 2."""
    salida = _guardia()
    if salida:
        return salida
    carga = _leer_carga(ficha)
    validos = {i["archivo"] for i in (carga or {}).get("imagenes", [])} | {(carga or {}).get("foto")}
    p = _ruta_tmp(ficha, archivo) if archivo in validos else None
    real = almacenamiento.local(p) if p else None
    if not real or not real.is_file():
        return ("", 404)
    return send_file(real, mimetype=_doc.MIME.get(real.suffix.lower()), max_age=0)


def _guardar(ficha: str):
    carga = _leer_carga(ficha)
    if not carga:
        flash("!Esa carga ya no está. Subí las fotos otra vez.")
        return redirect(url_for("afiliados_dni.carga_dni"))
    volver = redirect(url_for("afiliados_dni.carga_dni_ver", ficha=ficha))
    id_af = _entero(request.form.get("id_afiliado"))
    if not id_af:
        flash("!Elegí a qué afiliado van el DNI y la foto.")
        return volver
    lados = {i: request.form.get(f"lado_{i}", "") for i in range(len(carga["imagenes"]))}
    usar_foto = bool(request.form.get("usar_foto")) and carga.get("foto")
    if not any(v in LADOS for v in lados.values()) and not usar_foto:
        flash("!No quedó nada para guardar: marcá al menos una imagen o la foto.")
        return volver

    datos = carga.get("datos") or {}
    obs = "Carga de DNI" + "".join(
        f" · {r} {datos[k]}" for k, r in (("tramite", "trámite"), ("ejemplar", "ejemplar")) if datos.get(k))
    nuevos: list[Path] = []
    foto_vieja = None
    with get_connection() as conn:
        conn.begin()        # documentos, foto y auditoría: todo o nada
        try:
            with conn.cursor() as cur:
                cat = _catalogos(cur)
                af = _afiliado(cur, id_af)
                if af is None:
                    conn.rollback()
                    flash("!Ese afiliado no existe.")
                    return volver
                tipos = _tipos_dni(cur)
                guardados = []
                for i, img in enumerate(carga["imagenes"]):
                    lado = lados.get(i)
                    if lado not in LADOS:
                        continue
                    if lado not in tipos:
                        raise _doc.DocumentoError(f"Falta el tipo de documentación «{LADOS[lado]}» "
                                                  "(Tablas Auxiliares → tipos de documentación).")
                    origen = _ruta_tmp(ficha, img["archivo"])
                    ext = Path(img["archivo"]).suffix
                    nombre = f"DNI {lado} {datos.get('dni') or af.get('nro_documento') or ''}".strip() + ext
                    nuevo = _doc.guardar_copia(cur, "afiliado", id_af, tipos[lado], origen, nombre,
                                               obs, _usuario())
                    nuevos.append(nuevo["archivo"])
                    guardados.append(f"DNI — {lado} · {nombre}")
                for g in guardados:
                    _registrar(cur, id_af, af["cuil"], {"documentacion": None}, {"documentacion": g},
                               {"documentacion": "Documentación"}, "MODIFICACION", cat,
                               observaciones="Documento agregado desde la carga de DNI")
                if usar_foto:
                    contenido = almacenamiento.leer(_ruta_tmp(ficha, carga["foto"]))
                    if not contenido:
                        raise _doc.DocumentoError("La foto recortada ya no está: subí las fotos otra vez.")
                    foto_vieja = af.get("foto")
                    destino = _foto.guardar(id_af, contenido)
                    nuevos.append(destino)
                    cur.execute("UPDATE p_afiliados SET foto = %s WHERE id_afiliado = %s",
                                (_foto.relativa(destino), id_af))
                    _registrar(cur, id_af, af["cuil"], {"foto": "con foto" if foto_vieja else None},
                               {"foto": "nueva, del DNI"}, {"foto": "Foto"}, "MODIFICACION", cat,
                               observaciones="Foto recortada del DNI")
            conn.commit()
        except _doc.DocumentoError as e:
            conn.rollback()
            for p in nuevos:
                almacenamiento.borrar(p)
            flash(f"!{e}")
            return volver
        except Exception:
            conn.rollback()
            for p in nuevos:
                almacenamiento.borrar(p)
            raise
    if foto_vieja:
        _foto.borrar(foto_vieja)
    _borrar_carga(ficha, carga)
    partes = []
    if guardados:
        partes.append(f"{len(guardados)} {'imágenes' if len(guardados) > 1 else 'imagen'} en Documentación")
    if usar_foto:
        partes.append("la foto en la ficha")
    flash(f"DNI guardado en la ficha de {af['apellido_nombres']}: " + " y ".join(partes) + ".")
    return redirect(url_for("afiliados.abm_afiliados", edit=id_af) if puede_abm()
                    else url_for("afiliados.padron", ver=id_af))
