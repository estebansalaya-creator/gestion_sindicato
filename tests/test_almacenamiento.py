"""
Pruebas de almacenamiento.py con un bucket S3 simulado (moto, sin red ni base):
que guardar suba la copia, que un archivo que falta en el disco se traiga del
bucket, que borrar se lleve los dos, y que cada módulo que sirve archivos los
encuentre después de un deploy.   python tests/test_almacenamiento.py
"""
import os, sys, tempfile, time, datetime as dt, io
from pathlib import Path
raiz = tempfile.mkdtemp()
os.environ.update(SIND_ADJUNTOS=raiz, SIND_BUCKET="prueba", SIND_BUCKET_REGION="us-east-1",
                  SIND_BUCKET_KEY_ID="x", SIND_BUCKET_SECRET="y")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from moto import mock_aws
except ImportError:
    print("Falta moto (pip install \"moto[s3]\" boto3): se saltea.")
    raise SystemExit(0)
m = mock_aws(); m.start()
import boto3; boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="prueba")
import objetos, almacenamiento as A
ok = [0, 0]
def v(c, msg):
    ok[0 if c else 1] += 1; print(("  OK   " if c else "  FALLA ") + msg)

p = Path(raiz) / "comprobantes" / "202611" / "x.pdf"
A.guardar(p, b"%PDF-1")
v(objetos.leer("comprobantes/202611/x.pdf") == b"%PDF-1", "guardar: disco y bucket, clave relativa")
p.unlink(); v(A.local(p).read_bytes() == b"%PDF-1", "local: sin el archivo en disco, lo trae del bucket")
A.borrar(p); v(not p.exists() and not objetos.existe("comprobantes/202611/x.pdf"), "borrar: disco y bucket")
v(A.clave_de(Path(raiz) / "arca" / "ta.json") == "", "arca/ (caché) no va al bucket")
v(A.clave_de("/otro/lado/x.pdf") == "" and A.clave_de(Path(raiz) / ".." / "x") == "", "fuera de la base, sin clave")
q = Path(raiz) / "chat" / "1" / "no.pdf"
A.local(q); t0 = len(A._faltan); A.local(q); v(t0 == 1 and not q.exists(), "lo que no está se recuerda (no pregunta al bucket en cada pedido)")
A.respaldar(q, b"ya"); v(A.local(q).read_bytes() == b"ya", "subirlo después borra el «no está»")

# Módulos
import comprobantes_datos as cd, documentacion as D, institucion as I, ben_campanias as B, fisca_novedades as N, mensajes as M
ficha = cd.guardar_tmp(b"%PDF-tmp"); tmp = Path(raiz) / "tmp_comprobantes" / f"{ficha}.pdf"
tmp.unlink(); v(cd.ruta_tmp(ficha) is not None, "comprobante: el PDF de la carga lo encuentra otra instancia")
rel = cd.archivar_pdf(cd.ruta_tmp(ficha), dt.date(2026, 11, 3), "c.pdf")
v(objetos.leer(rel) == b"%PDF-tmp", "comprobante: el PDF archivado va al bucket")
(Path(raiz) / rel).unlink(); v(cd.ruta_real(rel) is not None, "comprobante: el PDF archivado se recupera")
doc = {"id_documento": 1, "entidad_tipo": "afiliado", "entidad_id": 7, "nombre_archivo": "abc.pdf"}
A.guardar(Path(raiz) / "documentacion/afiliado/7/abc.pdf", b"doc")
(Path(raiz) / "documentacion/afiliado/7/abc.pdf").unlink()
v(D.ruta(doc) is not None, "documentación: se recupera del bucket")
class C:
    def execute(s, *a): pass
r = D.borrar(C(), doc); A.borrar(r); v(not objetos.existe("documentacion/afiliado/7/abc.pdf"), "documentación: borrar se lleva la copia")
A.guardar(Path(raiz) / "institucion/logo.png", b"png"); (Path(raiz) / "institucion/logo.png").unlink()
v(I.ruta_logo({"logo_path": "institucion/logo.png"}) is not None, "logo: se recupera")
I._borrar_logos(); v(not objetos.existe("institucion/logo.png"), "logo: borrar los logos limpia el bucket")
A.guardar(Path(raiz) / "campanias/f.png", b"f"); (Path(raiz) / "campanias/f.png").unlink()
v(B.ruta_flyer({"flyer_archivo": "campanias/f.png"}) is not None, "flyer: se recupera (lo usa el envío en segundo plano)")
A.guardar(Path(raiz) / "novedades_empresa/n.pdf", b"n"); (Path(raiz) / "novedades_empresa/n.pdf").unlink()
v(N.ruta_ficha({"ficha_archivo": "n.pdf"}) is not None, "ficha de la empresa: se recupera")
# limpieza de lo viejo de paso
s3 = boto3.client("s3", region_name="us-east-1")
v(A.limpiar_viejos("tmp_comprobantes", 2) == 0, "limpiar_viejos no toca lo reciente")
v(A.limpiar_viejos("tmp_comprobantes", -1) >= 1, "limpiar_viejos borra lo de más de N días")
# subida inicial
(Path(raiz) / "reintegros/3").mkdir(parents=True); (Path(raiz) / "reintegros/3/a.jpg").write_bytes(b"j")
(Path(raiz) / "arca").mkdir(); (Path(raiz) / "arca/ta.json").write_bytes(b"{}")
rc = A._main(["--subir", "--aplicar"])
v(objetos.existe("reintegros/3/a.jpg") and not objetos.existe("arca/ta.json"), "--subir --aplicar sube lo que falta, sin la caché")
print(f"\n{ok[0]} bien, {ok[1]} mal")
m.stop()
raise SystemExit(1 if ok[1] else 0)
