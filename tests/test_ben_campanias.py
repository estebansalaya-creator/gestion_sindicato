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

print("Errores del servidor (24/11/2026)")
import smtplib   # noqa: E402


def falso_smtp(falla_en=None, error=None, rechazos=None, mail_resp=(250, b"2.1.0 OK")):
    """Un smtplib.SMTP de mentira que falla en el paso pedido."""
    class F:
        def __init__(s, host, puerto, timeout=None):
            if falla_en == "conectar":
                raise error
        def ehlo(s):
            return (250, b"smtp.x at your service, [1.2.3.4]\nSIZE 35882577")
        def starttls(s):
            if falla_en == "tls":
                raise error
            return (220, b"2.0.0 Ready to start TLS")
        def login(s, u, p):
            if falla_en == "login":
                raise error
            return (235, b"2.7.0 Accepted")
        def mail(s, de):
            return mail_resp
        def rset(s):
            return (250, b"OK")
        def send_message(s, msg, to_addrs=None):
            if falla_en == "enviar":
                raise error
            return rechazos or {}
        def quit(s):
            pass
    return F


real_smtp = smtplib.SMTP
m = C.armar_mensaje(camp, dest, de, None, "u", "AEDA")
try:
    for paso, error, texto in [
        ("conectar", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "cortó la conexión sin responder, al conectar"),
        ("conectar", TimeoutError("timed out"), "no respondió a tiempo, al conectar"),
        ("conectar", OSError(101, "Network is unreachable"), "no hay salida de red"),
        ("tls", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "al iniciar el cifrado"),
        ("login", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), "al iniciar sesión"),
        ("enviar", smtplib.SMTPDataError(550, b"5.4.5 Daily user sending limit exceeded"), "5.4.5 Daily user sending limit"),
        ("enviar", smtplib.SMTPSenderRefused(421, b"4.7.0 Try again later", "b@aeda.org.ar"), "421 4.7.0"),
        ("enviar", smtplib.SMTPRecipientsRefused({"juan@mail.com": (421, b"4.7.0 Try again later")}), "421 4.7.0"),
    ]:
        smtplib.SMTP = falso_smtp(paso, error)
        try:
            mailer._entregar(cfg, m, ["juan@mail.com"])
            ok(False, f"{paso}: {texto}")
        except mailer.MailConexionError as e:
            ok(texto in str(e) and "smtp.x:587" in str(e), f"{paso}: {texto}")

    smtplib.SMTP = falso_smtp("enviar", smtplib.SMTPRecipientsRefused({"juan@mail.com": (550, b"5.1.1 User unknown")}))
    try:
        mailer._entregar(cfg, m, ["juan@mail.com"])
        ok(False, "un 550 a todos los destinatarios sigue siendo de ellos")
    except smtplib.SMTPRecipientsRefused:
        ok(True, "un 550 a todos los destinatarios sigue siendo de ellos")
    smtplib.SMTP = falso_smtp("login", smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted"))
    try:
        mailer._entregar(cfg, m, ["juan@mail.com"])
        ok(False, "usuario o contraseña: SMTPAuthenticationError como siempre")
    except smtplib.SMTPAuthenticationError:
        ok(True, "usuario o contraseña: SMTPAuthenticationError como siempre")

    # entregar(): el corte se registra y se levanta (la campaña se pausa); un rechazo, no.
    smtplib.SMTP = falso_smtp("conectar", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"))
    conn = Conn(cfg)
    try:
        mailer.entregar(conn, C.armar_mensaje(camp, dest, de, None, "u", "AEDA"), codigo="campania", de=de)
        ok(False, "un corte del servidor corta la campaña")
    except mailer.MailError as e:
        ok(isinstance(e, mailer.MailConexionError) and "al conectar" in str(e), "un corte del servidor corta la campaña")
    ok(conn.inserts and conn.inserts[0][-3] == "error" and "al conectar" in conn.inserts[0][-2],
       "y queda en mail_envios con el motivo")
    smtplib.SMTP = falso_smtp("enviar", smtplib.SMTPRecipientsRefused({"juan@mail.com": (550, b"5.1.1 User unknown")}))
    r = mailer.entregar(Conn(cfg), C.armar_mensaje(camp, dest, de, None, "u", "AEDA"), codigo="campania", de=de)
    ok(r["estado"] == "error" and r["error"] == "juan@mail.com: 550 5.1.1 User unknown",
       "un rechazo de la dirección es del destinatario y no corta")

    # diagnosticar(): no manda nada y dice dónde se corta.
    smtplib.SMTP = falso_smtp()
    pasos = mailer.diagnosticar(Conn(dict(cfg, activo=0)))
    ok([p["ok"] for p in pasos] == [True] * 4 and "[1.2.3.4]" in pasos[0]["detalle"]
       and "SIZE" not in pasos[0]["detalle"], "diagnóstico sin falla: 4 pasos, con la IP del EHLO (apagado también)")
    smtplib.SMTP = falso_smtp("login", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"))
    pasos = mailer.diagnosticar(Conn(cfg))
    ok([p["ok"] for p in pasos] == [True, True, False] and "al iniciar sesión" in pasos[-1]["detalle"],
       "diagnóstico: se corta al iniciar sesión")
    smtplib.SMTP = falso_smtp(mail_resp=(550, b"5.4.5 Daily user sending limit exceeded"))
    pasos = mailer.diagnosticar(Conn(cfg))
    ok(not pasos[-1]["ok"] and "5.4.5" in pasos[-1]["detalle"] and "límite" in pasos[-1]["detalle"],
       "diagnóstico: el límite de Gmail al presentar el remitente")
    smtplib.SMTP = falso_smtp("conectar", smtplib.SMTPServerDisconnected("Connection unexpectedly closed"))
    pasos = mailer.diagnosticar(Conn(cfg))
    ok(len(pasos) == 1 and not pasos[0]["ok"] and "Railway" in pasos[0]["detalle"], "diagnóstico: se corta al conectar")
finally:
    smtplib.SMTP = real_smtp

print("Eliminar")
ok(C.puede_eliminar({"estado": "borrador"}) is None, "un borrador se elimina")
ok(C.puede_eliminar({"estado": "enviada"}) is None, "una enviada se elimina")
ok(C.puede_eliminar({"estado": "cancelada"}) is None, "una cancelada se elimina")
ok(C.puede_eliminar({"estado": "pausada"}) is None, "una pausada (sin hilo) se elimina")
ok(C.puede_eliminar({"estado": "pausada"}, en_curso=True) is not None, "con el hilo andando, no")
ok(C.puede_eliminar({"estado": "enviando"}) is not None, "enviando, no")
ok(C.puede_eliminar({"estado": "enviada", "entrega_generada": "2026-11-18"}) is not None, "con padrón de entrega, no")

print("Editar una pausada y el flyer perdido (24/11/2026)")
ok(C.puede_editar({"estado": "borrador"}) is None, "un borrador se edita")
ok(C.puede_editar({"estado": "pausada"}) is None, "una pausada se edita (el contenido)")
ok(C.puede_editar({"estado": "pausada"}, en_curso=True) is not None, "pausada con el hilo andando, no")
ok(C.puede_editar({"estado": "enviando"}) is not None, "enviando, no")
ok(C.puede_editar({"estado": "enviada"}) is not None and C.puede_editar({"estado": "cancelada"}) is not None,
   "enviada o cancelada, no")
ok(not C.flyer_perdido({"flyer_archivo": None}), "sin flyer no hay flyer perdido")
ok(C.flyer_perdido({"flyer_archivo": "campanias/no-existe-0000.png", "flyer_nombre": "x.png"}),
   "flyer cargado y archivo ausente: perdido")

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
        h = render_template("beneficios/campania.html", camp=c2, cuenta=None, n_dest=0, por_estado={"pendiente": 5},
                            con_error=[], cfg={"activo": 1}, estados=C.ESTADOS, destinos=C.DESTINOS, vista="",
                            institucion="AEDA", corriendo=False, es_imagen=True, flyer_falta=True, puede_editar=True)
        ok("no está en el servidor" in h and "Editar" in h and "/flyer" not in h,
           "ficha pausada con el flyer perdido: aviso, Editar y sin la imagen rota")
        h = render_template("beneficios/campania_form.html", camp=dict(c2, destino="padron"), errores=[],
                            destinos=C.DESTINOS, convenios=[], max_mb=5, filtro=C.filtro_de({"sexo": "F"}),
                            atributos=[], solo_contenido=True, flyer_falta=True)
        ok('id="destino" onchange="verConvenio(); contar()" disabled' in h and "solo-lectura\" disabled" in h
           and "La lista ya está armada: 10 direcciones" in h and "cargalo de nuevo abajo" in h,
           "formulario de una pausada: a quién va, sin poder cambiarlo")
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
