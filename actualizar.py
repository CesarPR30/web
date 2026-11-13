"""Actualiza el dashboard con los datos de dataset.json. Revisa las bases antes de procesarlas.

    python actualizar.py                         usa dataset.json tal como esta
    python actualizar.py --data D:/bases_v2      cambia la carpeta de bases
    python actualizar.py --modelo D:/modelo_v2   cambia la carpeta del modelo
    python actualizar.py --corte 202603          cambia el mes de corte
    python actualizar.py --simular               genera predicciones simuladas para probar
    python actualizar.py --revisar               solo revisa, no cambia el dashboard
    python actualizar.py --forzar                recalcula aunque las bases no hayan cambiado

--data, --modelo y --corte quedan guardados en dataset.json.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PIPELINE = RAIZ / "pipeline"
DATASET = RAIZ / "dataset.json"
sys.path.insert(0, str(PIPELINE))

REQUERIDAS = {
    "maestro": ["id_empresa", "rubro", "segmento", "ventas_anuales", "antiguedad_anios", "score_riesgo", "rating",
                "flag_lead", "fecha_alta_cliente", "departamento"],
    "transacciones": ["id_pagador", "id_receptor", "periodo", "monto", "moneda", "dias_credito"],
    "factoring": ["id_cedente", "fecha_operacion", "monto_desembolsado", "comision", "moneda", "tasa_anual", "plazo_dias"],
    "perfil": ["id_empresa", "periodo", "ventas_mes", "n_productos", "uso_linea_credito", "tiene_credito"],
}
ARCHIVOS_MODELO = ["predicciones.csv", "importancia_variables.csv", "metadata.json"]


def guardar_cambios(args):
    d = json.loads(DATASET.read_text(encoding="utf-8"))
    cambios = {"carpeta_datos": args.data, "carpeta_modelo": args.modelo, "corte": args.corte}
    cambios = {k: v for k, v in cambios.items() if v is not None and d.get(k) != v}
    if cambios:
        d.update(cambios)
        DATASET.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"dataset.json actualizado: {', '.join(cambios)}")


def revisar(C, simular):
    """Devuelve (errores, avisos). No modifica nada."""
    import duckdb
    errores, avisos = [], []
    if not C.DATA_DIR.is_dir():
        return [f"No existe la carpeta de datos: {C.DATA_DIR}"], avisos
    if not 190001 <= C.CORTE <= 299912 or not 1 <= C.CORTE % 100 <= 12:
        return [f"El corte debe tener formato AAAAMM. Valor actual: {C.CORTE}"], avisos

    disponibles = sorted(p.name for p in C.DATA_DIR.iterdir() if p.suffix.lower() in (".csv", ".parquet"))
    faltan = [b for b in REQUERIDAS if not C.ruta_base(b).exists()]
    for b in faltan:
        errores.append(f'No está el archivo de {b}: "{C.ARCHIVOS[b]}". Hay en la carpeta: {", ".join(disponibles) or "ninguno"}. '
                       'Corrige "archivos" en dataset.json.')
    for b, requeridas in REQUERIDAS.items():
        if b in faltan:
            continue
        mapa = C.COLUMNAS.get(b) or {}
        reales = C.columnas_archivo(b)
        ausentes = [c for c in requeridas if mapa.get(c, c) not in reales]
        ausentes += [c for c in mapa if c not in requeridas and mapa[c] not in reales]
        if ausentes:
            errores.append(f'En {b} faltan: {", ".join(ausentes)}. El archivo trae: {", ".join(reales)}. '
                           f'Si tienen otro nombre, indícalo en "columnas" > "{b}" de dataset.json.')
    if errores:
        return errores, avisos

    con = duckdb.connect()
    con.execute(f"CREATE VIEW maestro AS SELECT * FROM {C.fuente('maestro')}")
    con.execute(f"CREATE VIEW factoring AS SELECT * FROM {C.fuente('factoring')}")
    con.execute(f"CREATE VIEW perfil AS SELECT * FROM {C.fuente('perfil')}")

    tipos = "SELECT data_type FROM information_schema.columns WHERE table_name=? AND column_name=?"
    tipo_fecha = con.execute(tipos, ["factoring", "fecha_operacion"]).fetchone()[0]
    if "DATE" not in tipo_fecha and "TIMESTAMP" not in tipo_fecha:
        return [f"En factoring, fecha_operacion debe ser una fecha AAAA-MM-DD. Se leyó como {tipo_fecha}."], avisos
    tipo_periodo = con.execute(tipos, ["perfil", "periodo"]).fetchone()[0]
    if "INT" not in tipo_periodo:
        return [f"En perfil, periodo debe ser un entero AAAAMM. Se leyó como {tipo_periodo}."], avisos

    ini, fin = con.execute("SELECT min(periodo), max(periodo) FROM perfil").fetchone()
    if ini is None:
        return ["La base de perfil está vacía."], avisos
    if not ini <= C.CORTE <= fin:
        errores.append(f"El corte {C.CORTE} está fuera del perfil histórico, que va de {ini} a {fin}.")
    if C.INICIO_VENTANA < ini:
        avisos.append(f"Hay menos de 12 meses antes del corte: el perfil empieza en {ini}. El crecimiento de ventas puede salir incompleto.")

    if not con.execute("SELECT 1 FROM maestro WHERE segmento = ? LIMIT 1", [C.SEGMENTO_ACEPTANTE]).fetchone():
        hay = [r[0] for r in con.execute("SELECT DISTINCT segmento FROM maestro ORDER BY 1").fetchall()]
        errores.append(f'No hay empresas del segmento aceptante "{C.SEGMENTO_ACEPTANTE}". Segmentos en la base: {hay}.')
    leads = {r[0] for r in con.execute("SELECT DISTINCT flag_lead FROM maestro").fetchall()}
    if not leads <= {0, 1, None}:
        errores.append(f"flag_lead debe ser 0 o 1. Valores encontrados: {sorted(map(str, leads))}.")
    otras = [r[0] for r in con.execute("SELECT DISTINCT moneda FROM factoring WHERE moneda NOT IN ('PEN','USD')").fetchall()]
    if otras:
        avisos.append(f"Hay monedas sin convertir a soles: {otras}. Solo USD se convierte.")
    ops_antes, ops_post = con.execute(f"""SELECT count(*) FILTER (WHERE fecha_operacion <= DATE '{C.FECHA_CORTE}'),
        count(*) FILTER (WHERE fecha_operacion > DATE '{C.FECHA_CORTE}') FROM factoring""").fetchone()
    if not ops_antes:
        errores.append("No hay operaciones de factoring antes del corte: no se puede calcular el margen histórico.")
    if not ops_post:
        avisos.append("No hay operaciones posteriores al corte: el dashboard ocultará la tarjeta de confiabilidad.")

    faltan_ml = [str(r) for r in C.PREDICCIONES_ML if not r.exists()]
    if faltan_ml:
        errores.append(f'Faltan las predicciones de ML: {", ".join(faltan_ml)}. Corrige "predicciones_ml" en dataset.json.')
    faltan_modelo = [a for a in ARCHIVOS_MODELO if not (C.MODELO_DIR / a).exists()]
    if faltan_modelo and not simular and not C.PREDICCIONES_ML:
        errores.append(f'Faltan en {C.MODELO_DIR}: {", ".join(faltan_modelo)}. Para probar sin modelo, usa --simular.')
    return errores, avisos


def huella(C):
    """Identifica las bases y los parametros que afectan a las features."""
    archivos = {}
    for b in REQUERIDAS:
        ruta = C.ruta_base(b)
        archivos[b] = [str(ruta), ruta.stat().st_size, ruta.stat().st_mtime_ns]
    return {"archivos": archivos, "columnas": C.COLUMNAS, "corte": C.CORTE, "tc": C.TC_USD, "aceptante": C.SEGMENTO_ACEPTANTE}


def tipo_modelo(C):
    ruta = C.MODELO_DIR / "metadata.json"
    return json.loads(ruta.read_text(encoding="utf-8")).get("tipo") if ruta.exists() else None


def paso(script):
    t = time.time()
    print(f"\n> {script}", flush=True)
    entorno = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, script], cwd=PIPELINE, env=entorno)
    if r.returncode:
        sys.exit(f"\nSe detuvo en {script}. Corrige el error de arriba y vuelve a ejecutar.")
    print(f"  listo en {time.time() - t:.0f}s", flush=True)


def main():
    a = argparse.ArgumentParser(description="Actualiza el dashboard con los datos de dataset.json.")
    a.add_argument("--data", help="carpeta con las bases")
    a.add_argument("--modelo", help="carpeta con los 3 archivos del modelo")
    a.add_argument("--corte", type=int, help="mes de corte, AAAAMM")
    a.add_argument("--simular", action="store_true", help="genera predicciones simuladas")
    a.add_argument("--revisar", action="store_true", help="solo revisa las bases")
    a.add_argument("--forzar", action="store_true", help="recalcula aunque las bases no hayan cambiado")
    args = a.parse_args()

    guardar_cambios(args)
    import config as C
    print(f'Dataset "{C.NOMBRE_DATASET}" | datos: {C.DATA_DIR} | modelo: {C.MODELO_DIR} | corte: {C.CORTE}')

    errores, avisos = revisar(C, args.simular)
    for m in avisos:
        print(f"AVISO: {m}")
    if errores:
        print("\nNo se actualizó el dashboard:")
        for m in errores:
            print(f"  - {m}")
        sys.exit(1)
    print("Bases revisadas: correctas.")
    if args.revisar:
        return

    if args.simular and C.PREDICCIONES_ML:
        sys.exit('\nHay predicciones de ML en dataset.json. Quita "predicciones_ml" para usar --simular.')
    if args.simular and tipo_modelo(C) not in (None, "simulado"):
        sys.exit(f"\n{C.MODELO_DIR} tiene un modelo real y --simular lo sobrescribiría. Usa otra carpeta con --modelo.")

    t0 = time.time()
    ruta_huella = C.CACHE / "huella.json"
    previa = json.loads(ruta_huella.read_text(encoding="utf-8")) if ruta_huella.exists() else None
    actual = huella(C)
    cambio = previa != actual

    if previa and cambio and not args.simular and not C.PREDICCIONES_ML:
        if tipo_modelo(C) == "simulado":
            sys.exit("\nLas bases cambiaron y las predicciones simuladas son de las anteriores. "
                     "Usa --simular para rehacerlas o --modelo para indicar el modelo de estas bases.")
        print("AVISO: las bases cambiaron. Confirma que el modelo se entrenó con estas mismas bases.")

    if cambio or args.forzar or not (C.CACHE / "features_empresa.parquet").exists():
        ruta_huella.unlink(missing_ok=True)
        paso("01_features.py")
        ruta_huella.write_text(json.dumps(actual, ensure_ascii=False), encoding="utf-8")
    else:
        print("\nLas bases no cambiaron: se reutilizan las features.")
    if args.simular:
        paso("02_predicciones_simuladas.py")
    if C.PREDICCIONES_ML:
        paso("unir_predicciones.py")
    paso("03_build_inputs.py")

    print(f"\nDashboard actualizado en {time.time() - t0:.0f}s. Recarga dashboard/index.html para verlo.")
    if tipo_modelo(C) == "simulado":
        print("AVISO: las predicciones son simuladas. No presentes estas cifras como resultados.")


if __name__ == "__main__":
    main()
