"""
test_ben_campanias.py — Beneficios › Campañas (ben_campanias.py) y el envío de
mailer.entregar, con datos inventados: sin base, sin red y sin servidor de correo.

    python tests/test_ben_campanias.py
"""
from __future__ import annotations

import datetime
import os
import sys
from decimal import Decimal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
for k in ("SIND_DB_USER", "SIND_DB_PASS", "SIND_SECRET_KEY"):
    os.environ.setdefault(k, "prueba")

import ben_campanias as C   # noqa: E402
import mailer              # noqa: E402

fallos = []


def ok(cond, txt):
    print(("  OK   " if cond else "  FALLA ") + txt)
    if not cond:
        fallos.append(txt)


print("Enlace de baja")
t = C.token_baja("Juan@Mail.com")
ok(C.email_de_token(t) == "juan@mail.com", "ida y vuelta (en minúsculas)")
ok(C.email_de_token(t[:-1] + ("0" if t[-1] != "0" else "1")) is None, "con la firma tocada no vale")
otro = C.token_baja("otro@mail.com")
ok(C.email_de_token(otro.split(".")[0] + "." + t.split(".")[1]) is None, "no se puede cambiar la dirección")
ok(C.email_de_token("basura") is None, "un token roto no rompe")

print("Texto")
ok(C.nombre_corto("PEREZ JUAN CARLOS") == "Juan Carlos", "el nombre de pila")
ok(C.texto_con_datos("Hola {nombre}:", "Ana") == "Hola Ana:", "{nombre}")
h = C.html_del_cuerpo("Hola <b>x</b>\nlínea\n\nVer https://aeda.org.ar/a?b=1")
ok("&lt;b&gt;" in h and "<br>" in h and h.count("<p") == 2, "escapa el HTML y arma párrafos")
ok('<a href="https://aeda.org.ar/a?b=1">' in h, "los enlaces quedan clicables")

print("El mensaje")
camp = {"titulo": "Pileta", "asunto": "Pileta de verano", "cuerpo": "Hola {nombre}:\n\nTe esperamos.",
        "flyer_tipo": "image/png", "flyer_nombre": "pileta.png"}
de = {"nombre": "AEDA", "email": "beneficios@aeda.org.ar", "responder_a": "consultas@aeda.org.ar"}
dest = {"email": "juan@mail.com", "nombre": "PEREZ JUAN", "id_afiliado": 1}
png = b"\x89PNG\r\n\x1a\nfalso"
m = C.armar_mensaje(camp, dest, de, png, "https://x/beneficios/baja/T", "AEDA")
cruda = m.as_string()
ok(m["To"] == "PEREZ JUAN <juan@mail.com>" and m["Reply-To"] == "consultas@aeda.org.ar", "un destinatario, con Reply-To")
ok(m["List-Unsubscribe"] == "<https://x/beneficios/baja/T>", "List-Unsubscribe")
ok("Hola Juan:" in m.get_body(("plain",)).get_content(), "texto con el nombre")
html_part = m.get_body(("html",)).get_content()
ok("cid:" in html_part and "No quiero recibir" in html_part, "el flyer dentro del HTML y el pie de baja")
ok("image/png" in cruda and "pileta.png" in cruda, "la imagen va relacionada al HTML")
m = C.armar_mensaje({**camp, "flyer_tipo": "application/pdf", "flyer_nombre": "f.pdf"}, dest, de, b"%PDF-1.4", "u", "AEDA")
ok(any(p.get_filename() == "f.pdf" for p in m.iter_attachments()), "un PDF va adjunto")
ok("cid:" not in m.get_body(("html",)).get_content(), "y no como imagen")
m = C.armar_mensaje({**camp, "flyer_tipo": None}, dest, de, None, "u", "AEDA")
ok(not list(m.iter_attachments()), "sin flyer, sin adjuntos")


class Cur:
    """Un cursor de mentira: devuelve las respuestas en orden y anota las consultas."""
    def __init__(self, respuestas):
        self.r, self.q = list(respuestas), []
    def execute(self, sql, params=None):
        self.q.append((sql, params))
    def executemany(self, sql, params):
        self.q.append((sql, params))
    def fetchall(self):
        return self.r.pop(0)
    def fetchone(self):
        x = self.r.pop(0)
        return x[0] if isinstance(x, list) else x
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


print("Destinatarios")
personas = [{"id_afiliado": 1, "apellido_nombres": "PEREZ JUAN"}, {"id_afiliado": 2, "apellido_nombres": "GOMEZ ANA"},
            {"id_afiliado": 3, "apellido_nombres": "SIN MAIL"}, {"id_afiliado": 4, "apellido_nombres": "BAJA"},
            {"id_afiliado": 5, "apellido_nombres": "MISMA CASA"}]
contactos = [{"entidad_id": 1, "email": " Juan@Mail.com "}, {"entidad_id": 1, "email": "segundo@mail.com"},
             {"entidad_id": 2, "email": "ana@mail.com"}, {"entidad_id": 4, "email": "baja@mail.com"},
             {"entidad_id": 5, "email": "juan@mail.com"}, {"entidad_id": 3, "email": "sin arroba"}]
cur = Cur([personas, contactos, [{"e": "baja@mail.com"}]])
lista, cuenta = C.destinatarios(cur, "titulares")
ok([d["email"] for d in lista] == ["juan@mail.com", "ana@mail.com"], f"una por afiliado, la primera: {[d['email'] for d in lista]}")
ok(cuenta == {"personas": 5, "sin_correo": 1, "baja": 1, "repetidas": 1}, f"la cuenta: {cuenta}")
ok("cod_parentesco = 0" in cur.q[0][0], "titulares: solo cod_parentesco 0")
cur = Cur([personas[:1], contactos, []])
C.destinatarios(cur, "todos")
ok("cod_parentesco" not in cur.q[0][0], "todos: titulares y familiares")
try:
    C.destinatarios(Cur([]), "adheridos")
    ok(False, "adheridos sin convenio da error")
except C.ErrorCampania:
    ok(True, "adheridos sin convenio da error")

print("Lista con los filtros del padrón")
f = C.filtro_de({"estado": "baja", "tipo": "titular", "sexo": "F", "edad_desde": "30", "edad_hasta": "50",
                 "atributo": "7", "q": "  perez  ", "orden": "edad", "basura": "x"})
ok(f == {"q": "perez", "estado": "baja", "tipo": "titular", "sexo": "F", "edad_desde": 30, "edad_hasta": 50,
         "atributo": "7"}, f"se guardan solo los filtros, validados: {f}")
ok(C.filtro_de({"estado": "cualquiera", "sexo": "Z", "edad_desde": "999"})["estado"] == "activo"
   and C.filtro_de({"sexo": "Z"})["sexo"] == "" and C.filtro_de({"edad_desde": "999"})["edad_desde"] is None,
   "lo inválido vuelve a su valor de siempre")
txt = C.describir_filtro(f, {7: "Tiene hijos"})
ok(txt == "Bajas · solo titulares · femenino · 30 a 50 años · atributo «Tiene hijos» · «perez»", txt)
ok(C.describir_filtro(None) == "Activos del padrón" and C.describir_filtro(C.filtro_de({"edad_hasta": "25"})) ==
   "Activos · hasta 25 años", "sin filtros y con un solo extremo")
cur = Cur([personas[:2], contactos, []])
lista, cuenta = C.destinatarios(cur, "padron", None, {"estado": "activo", "tipo": "familiar", "sexo": "",
                                                      "edad_desde": 18, "edad_hasta": None, "atributo": "", "q": "gomez"})
sql, params = cur.q[0]
ok("a.activo = 1" in sql and "cod_parentesco, -1) <> 0" in sql and ">= %s" in sql and "LIKE %s" in sql,
   "la consulta es la del padrón (estado, familiar, edad, buscar)")
ok(params[0] == 18 and "%gomez%" in params, f"con sus parámetros: {params}")
ok(len(lista) == 2 and cuenta["personas"] == 2, "y arma la lista igual que los demás destinos")

print("mailer.entregar (sin servidor)")


class Conn:
    def __init__(self, cfg, enviados=0):
        self.cfg, self.enviados, self.inserts, self.commits = cfg, enviados, [], 0
    def cursor(self):
        conn = self
        class K(Cur):
            def __init__(s):
                super().__init__([])
            def execute(s, sql, params=None):
                s.q.append(sql)
                if "INSERT INTO mail_envios" in sql:
                    conn.inserts.append(params)
            def fetchone(s):
                return conn.cfg if "mail_config" in s.q[-1] else {"n": conn.enviados}
        return K()
    def commit(self):
        self.commits += 1


cfg = {"id": 1, "host": "smtp.x", "puerto": 587, "seguridad": "starttls", "usuario": "u@x", "password_cif": None,
       "remitente_nombre": "AEDA", "remitente_email": "b@aeda.org.ar", "responder_a": None, "limite_diario": 3, "activo": 1}
entregados = []
real = mailer._entregar
mailer._entregar = lambda c, msg, destinos: entregados.append(destinos) or {}
try:
    m = C.armar_mensaje(camp, dest, de, png, "u", "AEDA")
    conn = Conn(cfg)
    r = mailer.entregar(conn, m, codigo="campania", entidad_tipo="afiliado", entidad_id=1, origen_tipo="campania",
                        origen_id=7, de=de)
    ok(r["estado"] == "ok" and entregados == [["juan@mail.com"]], "sale a la dirección del To")
    ok(conn.inserts and conn.inserts[0][3:5] == ("campania", 7) and conn.inserts[0][5] == "juan@mail.com",
       "queda en mail_envios con el origen")
    try:
        mailer.entregar(Conn(cfg, enviados=3), C.armar_mensaje(camp, dest, de, None, "u", "AEDA"), codigo="campania")
        ok(False, "el límite de 24 horas frena")
    except mailer.MailError as e:
        ok("límite" in str(e), "el límite de 24 horas frena")
    try:
        mailer.entregar(Conn(dict(cfg, activo=0)), C.armar_mensaje(camp, dest, de, None, "u", "AEDA"), codigo="campania")
        ok(False, "apagado no manda")
    except mailer.MailError:
        ok(True, "apagado no manda")
    mailer._entregar = lambda c, msg, destinos: {"juan@mail.com": (550, b"5.1.1 User unknown")}
    r = mailer.entregar(Conn(cfg), C.armar_mensaje(camp, dest, de, None, "u", "AEDA"), codigo="campania", de=de)
    ok(r["estado"] == "error" and "550 5.1.1 User unknown" in r["error"], "un rechazo queda como error con el motivo")
finally:
    mailer._entregar = real

print("Pantallas (con datos inventados)")
import app as A   # noqa: E402
from flask import render_template   # noqa: E402

c = {"id": 7, "titulo": "Pileta", "asunto": "Pileta de verano", "cuerpo": "Hola {nombre}", "destino": "titulares",
     "id_convenio": None, "convenio": None, "estado": "borrador", "total": 0, "enviados": 0, "errores": 0,
     "creada": datetime.datetime(2026, 11, 17, 9, 0), "usuario": "Esteban", "flyer_archivo": "campanias/x.png",
     "flyer_nombre": "x.png", "flyer_tipo": "image/png", "nota": None, "envio_desde": None, "envio_hasta": None,
     "pendientes": 0, "corriendo": False}
with A.app.test_request_context("/"):
    try:
        h = render_template("beneficios/campania.html", camp=c, cuenta={"personas": 5, "sin_correo": 1, "baja": 1,
                            "repetidas": 1}, n_dest=2, por_estado={}, con_error=[], cfg={"activo": 1},
                            estados=C.ESTADOS, destinos=C.DESTINOS, vista=C.html_del_cuerpo("Hola Juan"),
                            institucion="AEDA", corriendo=False, es_imagen=True,
                            filtro_txt=None)
        ok("Enviar a 2 direcciones" in h and "Lista en Excel" in h, "ficha en borrador")
        h = render_template("beneficios/campania.html", camp=dict(c, destino="padron"), cuenta=None, n_dest=0,
                            por_estado={}, con_error=[], cfg={"activo": 1}, estados=C.ESTADOS, destinos=C.DESTINOS,
                            vista="", institucion="AEDA", corriendo=False, es_imagen=True,
                            filtro_txt="Activos · femenino")
        ok("Padrón: Activos · femenino" in h, "la ficha dice los filtros")
        c2 = dict(c, estado="pausada", total=10, enviados=4, errores=1, nota="Se alcanzó el límite",
                  envio_desde=datetime.datetime(2026, 11, 17, 10, 0))
        h = render_template("beneficios/campania.html", camp=c2, cuenta=None, n_dest=0, por_estado={"pendiente": 5},
                            con_error=[{"nombre": "X", "email": "x@x.com", "estado": "error", "error": "550"}],
                            cfg={"activo": 1}, estados=C.ESTADOS, destinos=C.DESTINOS, vista="", institucion="AEDA",
                            corriendo=False, es_imagen=True)
        ok("Reanudar" in h and "Se alcanzó el límite" in h, "ficha pausada")
        h = render_template("beneficios/campanias.html", filas=[c2, dict(c2, destino="padron", filtro_txt="Activos")],
                            estados=C.ESTADOS, destinos=C.DESTINOS, cfg={})
        ok("Pileta" in h, "lista")
        h = render_template("beneficios/campania_form.html", camp=dict(c, destino="padron"), errores=[],
                            destinos=C.DESTINOS, convenios=[], max_mb=5,
                            filtro=C.filtro_de({"sexo": "F", "atributo": "7"}), atributos=[{"id": 7, "rotulo": "Tiene hijos"}])
        ok("Filtros del padrón" in h and 'value="F" selected' in h and 'value="7" selected' in h,
           "formulario con los filtros del padrón")
        h = render_template("beneficios/baja.html", email="juan@mail.com", hecho=False, institucion="AEDA")
        ok("no quiero recibir más" in h, "página pública de baja")
        import correo   # noqa: E402
        h = render_template("admin/correo.html", cfg={"activo": 0, "limite_diario": 500}, tipos=[], ultimos=[],
                            remitentes=[], areas=[], usuarios=[], editando=None, seguridades=correo.SEGURIDADES,
                            tiene_clave=False, hay_cifrado=False, sql_esquema="x")
        ok("SIND_FERNET_KEY" in h and "APAGADO" in h, "correo saliente")
        import paginar   # noqa: E402
        h = render_template("admin/correo_envios.html", envios=[{"id": 1, "enviado_at": datetime.datetime.now(),
                            "codigo": "campania", "tipo_nombre": None, "origen_tipo": "campania", "origen_id": 7,
                            "para": "juan@mail.com", "copias": None, "asunto": "A", "remitente": "b@x",
                            "adjuntos": None, "usuario_nombre": None, "estado": "ok", "error": None, "cuerpo": "Hola"}],
                            codigos=[], total=1, pag=paginar.paginador(1, 1, 50, "correo.envios", {}),
                            filtros={"origen_tipo": "campania", "origen_id": 7, "codigo": "", "estado": "", "q": ""})
        ok("Campaña de beneficios" in h, "envíos")
    except Exception as e:      # noqa: BLE001
        import traceback
        traceback.print_exc()
        ok(False, f"las pantallas se dibujan: {e}")

print()
print("FALLAS: " + ", ".join(fallos) if fallos else "Todo bien.")
sys.exit(1 if fallos else 0)
