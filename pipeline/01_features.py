"""Paso 1. Construye la tabla empresa-features desde las 4 bases (out-of-core con DuckDB).

Salidas en pipeline/_cache:
    features_empresa.parquet   1 fila por empresa (features al corte + resultado real post-corte)
    aristas_aceptantes.parquet aceptante -> proveedor, con volumen al corte
    hist_factoring.parquet     historico mensual de factoring por rubro
    margen.json                ingreso historico por sol desembolsado

Las features usan SOLO informacion <= CORTE. Las columnas conv_real/monto_real se calculan
despues del corte y sirven unicamente para el backtest; nunca deben entrar a un modelo.
Uso: python pipeline/01_features.py
"""
import json
import time

import duckdb

import config as C

t0 = time.time()
C.CACHE.mkdir(exist_ok=True)
con = duckdb.connect()
con.execute("SET preserve_insertion_order=false")
con.execute(f"SET temp_directory='{(C.CACHE / 'tmp').as_posix()}'")


def paso(nombre, sql):
    t = time.time()
    con.execute(sql)
    print(f"  {nombre:28s} {time.time() - t:6.1f}s", flush=True)


paso("vistas", f"""
CREATE VIEW t1 AS SELECT * FROM {C.fuente('maestro')};
CREATE VIEW t2 AS SELECT id_pagador, id_receptor, periodo, dias_credito,
    monto * CASE WHEN moneda='USD' THEN {C.TC_USD} ELSE 1 END AS monto_pen
    FROM {C.fuente('transacciones')};
CREATE VIEW t3 AS SELECT *, CAST(strftime(fecha_operacion,'%Y%m') AS INT) AS periodo,
    monto_desembolsado * CASE WHEN moneda='USD' THEN {C.TC_USD} ELSE 1 END AS desembolso_pen,
    comision * CASE WHEN moneda='USD' THEN {C.TC_USD} ELSE 1 END AS comision_pen
    FROM {C.fuente('factoring')};
CREATE VIEW t4 AS SELECT * FROM {C.fuente('perfil')};
""")

# Limpieza de ubicacion: la columna trae mayusculas inconsistentes y nulos.
paso("maestro", f"""
CREATE TABLE emp AS SELECT id_empresa, rubro, segmento, ventas_anuales, num_empleados,
    antiguedad_anios, score_riesgo, rating, flag_lead, fecha_alta_cliente,
    CASE WHEN departamento IS NULL THEN 'Sin dato'
         WHEN upper(departamento) = 'LA LIBERTAD' THEN 'La Libertad'
         ELSE upper(left(departamento,1)) || lower(substr(departamento,2)) END AS departamento
    FROM t1;
CREATE TABLE acept AS SELECT id_empresa FROM emp WHERE segmento='{C.SEGMENTO_ACEPTANTE}';
""")

paso("red al corte (T2)", f"""
CREATE TABLE pares AS
    SELECT id_receptor, id_pagador, sum(monto_pen) AS vol, count(DISTINCT periodo) AS meses,
           sum(monto_pen*dias_credito)/nullif(sum(monto_pen),0) AS dias
    FROM t2 WHERE periodo BETWEEN {C.INICIO_VENTANA} AND {C.CORTE} GROUP BY ALL;
CREATE TABLE aristas AS SELECT p.*, id_pagador IN (SELECT id_empresa FROM acept) AS es_acept FROM pares p;
""")

paso("features de red", """
CREATE TABLE red AS
WITH tot AS (SELECT id_receptor, sum(vol) AS vol_total, count(*) AS n_compradores FROM aristas GROUP BY 1)
SELECT a.id_receptor AS id_empresa, t.vol_total, t.n_compradores,
       sum(CASE WHEN es_acept THEN vol ELSE 0 END) AS vol_aceptantes,
       sum(CASE WHEN es_acept THEN 1 ELSE 0 END) AS n_aceptantes,
       sum(pow(vol/nullif(t.vol_total,0),2)) AS hhi_compradores,
       sum(CASE WHEN es_acept THEN vol*dias ELSE 0 END)
         / nullif(sum(CASE WHEN es_acept THEN vol ELSE 0 END),0) AS dias_credito_acept,
       max(CASE WHEN es_acept THEN meses ELSE 0 END) AS meses_activos_acept
FROM aristas a JOIN tot t USING (id_receptor) GROUP BY ALL;
""")

paso("perfil mensual (T4)", f"""
CREATE TABLE perfil AS
SELECT id_empresa,
       sum(ventas_mes) AS ventas_12m,
       sum(CASE WHEN periodo BETWEEN {C.TRIM_INICIAL[0]} AND {C.TRIM_INICIAL[1]} THEN ventas_mes END) AS ventas_q1,
       sum(CASE WHEN periodo BETWEEN {C.TRIM_FINAL[0]} AND {C.TRIM_FINAL[1]} THEN ventas_mes END) AS ventas_q4,
       arg_max(n_productos, periodo) AS n_productos,
       arg_max(uso_linea_credito, periodo) AS uso_linea,
       arg_max(tiene_credito, periodo) AS tiene_credito
FROM t4 WHERE periodo BETWEEN {C.INICIO_VENTANA} AND {C.CORTE} GROUP BY 1;
""")

paso("factoring pre/post corte", f"""
CREATE TABLE fact AS
SELECT id_cedente AS id_empresa,
       count(*) FILTER (WHERE periodo <= {C.CORTE}) AS ops_previas,
       coalesce(sum(desembolso_pen) FILTER (WHERE periodo <= {C.CORTE}),0) AS monto_previo,
       count(*) FILTER (WHERE periodo > {C.CORTE}) AS ops_post,
       coalesce(sum(desembolso_pen) FILTER (WHERE periodo > {C.CORTE}),0) AS monto_real
FROM t3 GROUP BY 1;
""")

paso("tabla final", """
CREATE TABLE f AS
SELECT coalesce(e.id_empresa, r.id_empresa) AS id_empresa,
       e.id_empresa IS NOT NULL AS es_cliente,
       coalesce(e.rubro,'Sin dato') AS rubro, coalesce(e.segmento,'Sin dato') AS segmento,
       coalesce(e.departamento,'Sin dato') AS departamento,
       e.ventas_anuales, e.antiguedad_anios, e.score_riesgo, e.rating,
       coalesce(e.flag_lead,0) AS flag_lead, e.fecha_alta_cliente,
       coalesce(r.vol_total,0) AS vol_total, coalesce(r.n_compradores,0) AS n_compradores,
       coalesce(r.vol_aceptantes,0) AS vol_aceptantes, coalesce(r.n_aceptantes,0) AS n_aceptantes,
       r.hhi_compradores, r.dias_credito_acept, r.meses_activos_acept,
       p.ventas_12m, p.ventas_q1, p.ventas_q4, p.n_productos, p.uso_linea, p.tiene_credito,
       coalesce(x.ops_previas,0) AS ops_previas, coalesce(x.monto_previo,0) AS monto_previo,
       coalesce(x.ops_post,0) > 0 AS conv_real, coalesce(x.monto_real,0) AS monto_real
FROM emp e FULL JOIN red r USING (id_empresa)
LEFT JOIN perfil p ON p.id_empresa = coalesce(e.id_empresa, r.id_empresa)
LEFT JOIN fact x ON x.id_empresa = coalesce(e.id_empresa, r.id_empresa);
""")

con.execute(f"COPY f TO '{(C.CACHE / 'features_empresa.parquet').as_posix()}' (FORMAT parquet)")
con.execute(f"""COPY (SELECT id_pagador AS id_aceptante, id_receptor AS id_proveedor, vol, meses, dias
    FROM aristas WHERE es_acept) TO '{(C.CACHE / 'aristas_aceptantes.parquet').as_posix()}' (FORMAT parquet)""")
con.execute(f"""COPY (SELECT periodo, coalesce(e.rubro,'Sin dato') AS rubro, count(*) AS ops,
        count(DISTINCT id_cedente) AS cedentes, sum(desembolso_pen) AS desembolso,
        avg(tasa_anual) AS tasa, avg(plazo_dias) AS plazo
    FROM t3 LEFT JOIN emp e ON e.id_empresa=t3.id_cedente GROUP BY ALL)
    TO '{(C.CACHE / 'hist_factoring.parquet').as_posix()}' (FORMAT parquet)""")

# Margen historico: ingreso financiero + comision por cada sol desembolsado. No se inventa.
margen, tasa, plazo = con.execute(f"""SELECT
    (sum(desembolso_pen*tasa_anual*plazo_dias/360)+sum(comision_pen))/sum(desembolso_pen),
    sum(desembolso_pen*tasa_anual)/sum(desembolso_pen), sum(desembolso_pen*plazo_dias)/sum(desembolso_pen)
    FROM t3 WHERE periodo <= {C.CORTE}""").fetchone()
(C.CACHE / "margen.json").write_text(json.dumps({"margen": margen, "tasa": tasa, "plazo": plazo}))

for r in con.execute(f"""SELECT es_cliente, flag_lead, segmento='{C.SEGMENTO_ACEPTANTE}' corp, vol_aceptantes>0 con_acept,
        count(*), sum(conv_real::INT), median(vol_aceptantes) FROM f GROUP BY ALL ORDER BY 1,2,3,4""").fetchall():
    print(r)
print(f"margen {margen:.4f} tasa {tasa:.4f} plazo {plazo:.1f}")
print(f"listo en {time.time() - t0:.0f}s")
