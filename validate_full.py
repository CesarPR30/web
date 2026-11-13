"""Validación out-of-core (DuckDB) de las tablas grandes: mismos chequeos que eda_rapido.ipynb.

Uso:
    python validate_full.py --dir data/full
"""
import argparse
import os
import time

import duckdb
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ap = argparse.ArgumentParser()
ap.add_argument("--dir", default="data/full")
D = ap.parse_args().dir
t0 = time.time()

con = duckdb.connect()
con.execute("SET preserve_insertion_order = false")
con.execute(f"""
CREATE VIEW t1 AS SELECT * FROM read_csv('{D}/1_maestro_empresas.csv', types={{'ciiu': 'VARCHAR'}});
CREATE VIEW t2 AS SELECT *, monto * CASE WHEN moneda = 'USD' THEN 3.75 ELSE 1 END AS monto_pen
                  FROM read_csv('{D}/2_transacciones.csv');
CREATE TABLE t3 AS SELECT *, CAST(strftime(fecha_operacion, '%Y%m') AS INT) AS periodo
                   FROM read_csv('{D}/3_operaciones_factoring.csv');
CREATE TABLE t4 AS SELECT * FROM read_csv('{D}/4_perfil_historico.csv');
CREATE TABLE cli AS SELECT id_empresa, fecha_alta_cliente, flag_lead, segmento FROM t1;
CREATE TABLE acept AS SELECT DISTINCT id_aceptante AS id FROM t3;
CREATE TABLE pares AS SELECT id_pagador, id_receptor, min(periodo) AS primer_periodo FROM t2 GROUP BY ALL;
""")
q = lambda s: con.execute(s).fetchone()[0]

print("Filas / tamaño:")
for i, (t, f) in enumerate([("t1", "1_maestro_empresas"), ("t2", "2_transacciones"),
                            ("t3", "3_operaciones_factoring"), ("t4", "4_perfil_historico")], 1):
    print(f"  {i} {f:28s} {q(f'SELECT count(*) FROM {t}'):>13,} filas  {os.path.getsize(f'{D}/{f}.csv') / 1e9:6.2f} GB")

chk = {
    "T3/T4 ids existen en T1": """SELECT
        (SELECT count(*) FROM t3 WHERE id_cedente NOT IN (SELECT id_empresa FROM cli) OR id_aceptante NOT IN (SELECT id_empresa FROM cli))
      + (SELECT count(*) FROM t4 ANTI JOIN cli USING (id_empresa))""",
    "todo factoring tiene relación previa en T2": """SELECT count(*) FROM t3 LEFT JOIN pares p
        ON p.id_pagador = t3.id_aceptante AND p.id_receptor = t3.id_cedente
        WHERE p.primer_periodo IS NULL OR p.primer_periodo > t3.periodo""",
    "monto_factura <= volumen transado": """SELECT count(*) FROM
        (SELECT id_aceptante, id_cedente, periodo, sum(monto_factura) f FROM t3 GROUP BY ALL) x
        LEFT JOIN (SELECT id_pagador, id_receptor, periodo, sum(monto) v FROM t2 GROUP BY ALL) y
        ON y.id_pagador = x.id_aceptante AND y.id_receptor = x.id_cedente AND y.periodo = x.periodo
        WHERE y.v IS NULL OR x.f > y.v + 0.01""",
    "desembolsado <= factura y op < vencimiento": """SELECT count(*) FROM t3
        WHERE monto_desembolsado > monto_factura OR fecha_operacion >= fecha_vencimiento""",
    "factoring después del alta": """SELECT count(*) FROM t3 JOIN cli ON cli.id_empresa = t3.id_cedente
        WHERE t3.fecha_operacion <= cli.fecha_alta_cliente""",
    "T4 no antes del alta": """SELECT count(*) FROM t4 JOIN cli USING (id_empresa)
        WHERE t4.periodo < greatest(CAST(strftime(fecha_alta_cliente, '%Y%m') AS INT), 202501)""",
    "alta >= inicio actividades": "SELECT count(*) FROM t1 WHERE fecha_alta_cliente < fecha_inicio_actividades",
    "cobros de red <= ventas_mes": """SELECT count(*) FROM
        (SELECT id_receptor, periodo, sum(monto_pen) c FROM t2 GROUP BY ALL) x
        JOIN t4 ON t4.id_empresa = x.id_receptor AND t4.periodo = x.periodo
        WHERE t4.ventas_mes IS NOT NULL AND x.c > t4.ventas_mes * 1.001""",
    "usa_factoring (T4) == ops en T3": """SELECT count(*) FROM
        (SELECT id_empresa, periodo FROM t4 WHERE usa_factoring = 1) a
        FULL JOIN (SELECT DISTINCT id_cedente id_empresa, periodo FROM t3) b USING (id_empresa, periodo)
        WHERE a.id_empresa IS NULL OR b.id_empresa IS NULL""",
    "sin pares nocli-nocli": """SELECT count(*) FROM pares
        WHERE id_pagador NOT IN (SELECT id_empresa FROM cli) AND id_receptor NOT IN (SELECT id_empresa FROM cli)""",
}
print("\nIntegridad (nº de violaciones):")
for k, s in chk.items():
    v = q(s)
    print(f"  {'OK ' if v == 0 else 'FALLA'} {k:45s} {v:,}")

print("\nDistribuciones:")
print("  segmento:", dict(con.execute("SELECT segmento, round(count(*) / sum(count(*)) OVER (), 3) FROM t1 GROUP BY 1 ORDER BY 2 DESC").fetchall()))
print("  flag_lead en Pyme:", round(q("SELECT avg(flag_lead) FROM t1 WHERE segmento <> 'Corporativa'"), 3))
print("  nulos rating / departamento:", round(q("SELECT avg((rating IS NULL)::INT) FROM t1"), 3),
      round(q("SELECT avg((departamento IS NULL)::INT) FROM t1"), 3))
print("  % filas T2 con pagador aceptante:", round(q("SELECT avg((id_pagador IN (SELECT id FROM acept))::INT) FROM t2"), 3))
print("  estado T3:", dict(con.execute("SELECT estado, round(count(*) / sum(count(*)) OVER (), 3) FROM t3 GROUP BY 1").fetchall()))

# señal: features reconstruidas solo con data <= corte
f = con.execute("""
WITH base AS (SELECT id_empresa, flag_lead FROM cli WHERE segmento <> 'Corporativa' AND fecha_alta_cliente <= DATE '2025-12-31'),
v AS (SELECT id_empresa, sum(ventas_mes) vpre,
             sum(ventas_mes) FILTER (WHERE periodo BETWEEN 202501 AND 202503) vini,
             sum(ventas_mes) FILTER (WHERE periodo BETWEEN 202510 AND 202512) vfin
      FROM t4 WHERE periodo <= 202512 GROUP BY 1),
ca AS (SELECT id_receptor id_empresa, sum(monto_pen) cob FROM t2
       WHERE periodo <= 202512 AND id_pagador IN (SELECT id FROM acept) GROUP BY 1),
pre AS (SELECT DISTINCT id_cedente id_empresa FROM t3 WHERE periodo <= 202512),
tgt AS (SELECT DISTINCT id_cedente id_empresa FROM t3 WHERE periodo > 202512)
SELECT b.flag_lead,
       -- ojo: least/greatest de DuckDB ignoran NULL, por eso el coalesce va adentro
       least(coalesce(ca.cob, 0) / v.vpre, 1) pct_acept,
       greatest(least(ln((coalesce(v.vfin, 0) + 1) / (coalesce(v.vini, 0) + 1)), 1), -1) crec,
       (pre.id_empresa IS NOT NULL)::INT fact_previo,
       (tgt.id_empresa IS NOT NULL)::INT AS target
FROM base b LEFT JOIN v USING (id_empresa) LEFT JOIN ca USING (id_empresa)
LEFT JOIN pre USING (id_empresa) LEFT JOIN tgt USING (id_empresa)
""").df()
print("\nSeñal plantada:")
print(f"  conversión leads={f.target[f.flag_lead == 1].mean():.1%}  no leads={f.target[f.flag_lead == 0].mean():.1%}")
X = f[["pct_acept", "crec", "fact_previo", "flag_lead"]]
lr = LogisticRegression().fit(X, f.target)
print("  coef (plantados 1.5, 0.8, 1.0, 0.5):", dict(zip(X.columns, lr.coef_[0].round(2))), "b0 =", lr.intercept_.round(2)[0])
print(f"  AUC: {roc_auc_score(f.target, lr.predict_proba(X)[:, 1]):.3f}")
print(f"\nlisto en {time.time() - t0:.0f}s")
