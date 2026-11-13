"""Convierte los CSV por grupo del equipo de ML en los archivos que lee el dashboard.

Entrada: las rutas de "predicciones_ml" en dataset.json, con los splits test y forecast.
Salida en carpeta_modelo: predicciones.csv, importancia_variables.csv, metadata.json y backtest.json.

    p_conversion    prob_calibrada del split forecast (probabilidad de operar el mes siguiente)
    monto_esperado  ESTIMADO aqui, porque ML no lo entrega:
                    con historial, desembolso medio por mes activo;
                    sin historial, ventas mensuales a aceptantes por la proporcion observada en usuarios.

Si ML entrega importancia_variables.csv en esa carpeta, se conserva.
"""
import json
import sys
from datetime import date

import duckdb
import numpy as np
import polars as pl
from scipy.stats import rankdata

import config as C


MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


def fallar(msg):
    sys.exit(f"ERROR en las predicciones de ML: {msg}")


def gini(y, p):
    pos = int(y.sum())
    if not 0 < pos < len(y):
        return None
    rk = rankdata(p)
    return round(float(2 * (rk[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (len(y) - pos)) - 1), 4)


COLS = {"id_empresa", "periodo", "split", "prob_calibrada", "target_real"}
partes = []
for i, ruta in enumerate(C.PREDICCIONES_ML, 1):
    df = pl.read_csv(ruta, schema_overrides={"id_empresa": pl.Utf8}, infer_schema_length=200000)
    if faltan := COLS - set(df.columns):
        fallar(f"a {ruta.name} le faltan: {', '.join(sorted(faltan))}")
    partes.append(df.select(sorted(COLS)).with_columns(pl.lit(i).alias("archivo")))
ml = pl.concat(partes)
forecast, test = ml.filter(pl.col("split") == "forecast"), ml.filter(pl.col("split") == "test")
for nombre, x in (("forecast", forecast), ("test", test)):
    if x.is_empty():
        fallar(f"no hay filas del split {nombre}")
    if x["id_empresa"].n_unique() != x.height:
        fallar(f"id_empresa repetido en el split {nombre}")
    if not x["prob_calibrada"].is_between(0, 1).all():
        fallar(f"prob_calibrada fuera de [0,1] en el split {nombre}")
if forecast["periodo"].n_unique() != 1 or forecast["periodo"][0] != C.CORTE:
    fallar(f"el forecast es del periodo {forecast['periodo'].unique().to_list()} y el corte de dataset.json es {C.CORTE}")

# Mismas candidatas que el resto del dashboard: clientes pyme con ventas a aceptantes o con lead.
f = pl.read_parquet(C.CACHE / "features_empresa.parquet")
candidatas = f.filter(pl.col("es_cliente") & (pl.col("segmento") != C.SEGMENTO_ACEPTANTE)
                      & (pl.col("fecha_alta_cliente").cast(pl.Utf8) <= C.FECHA_CORTE).fill_null(False)
                      & ((pl.col("vol_aceptantes") > 0) | (pl.col("flag_lead") == 1)))
sin_prediccion = f.filter(~pl.col("es_cliente") & (pl.col("vol_aceptantes") > 0)).height

ops = pl.from_arrow(duckdb.sql(f"""
    SELECT id_cedente AS id_empresa, CAST(strftime(fecha_operacion,'%Y%m') AS INT) AS periodo,
           sum(monto_desembolsado * CASE WHEN moneda='USD' THEN {C.TC_USD} ELSE 1 END) AS monto
    FROM {C.fuente('factoring')} WHERE tipo='factoring' GROUP BY 1,2""").arrow())


def monto_mensual(hasta):
    return ops.filter(pl.col("periodo") <= hasta).group_by("id_empresa").agg(pl.col("monto").mean().alias("monto_mes"))


historial = monto_mensual(C.CORTE)
base = candidatas.select("id_empresa", (pl.col("vol_aceptantes") / 12).alias("acept_mes")).join(historial, on="id_empresa", how="left")
proporcion = float(base.filter(pl.col("monto_mes").is_not_null() & (pl.col("acept_mes") > 0))
                   .select((pl.col("monto_mes") / pl.col("acept_mes")).median()).item())
piso = float(historial["monto_mes"].quantile(.10))
base = base.with_columns(pl.coalesce(pl.col("monto_mes"), pl.max_horizontal(pl.col("acept_mes") * proporcion, pl.lit(piso))).alias("monto_esperado"))

pred = forecast.join(base.select("id_empresa", "monto_esperado"), on="id_empresa", how="inner").select(
    "id_empresa", pl.col("prob_calibrada").round(6).alias("p_conversion"), pl.col("monto_esperado").round(2))

# Validacion fuera de muestra con el split test: lo que se predijo un mes antes contra lo que ocurrio.
ids = candidatas.select("id_empresa")
t = test.join(ids, on="id_empresa", how="inner").sort(["prob_calibrada", "id_empresa"], descending=[True, False])
y, p = t["target_real"].to_numpy().astype(int), t["prob_calibrada"].to_numpy()
pos, n = int(y.sum()), len(y)
acum = np.cumsum(y)
ganancia = [{"x": round(i / 20, 2), "y": round(float(acum[max(int(n * i / 20) - 1, 0)] / pos), 4)} for i in range(1, 21)]
periodo_test = int(test["periodo"].max())
historicas = monto_mensual(periodo_test)
usan = t.join(historicas.select("id_empresa"), on="id_empresa", how="inner")
nuevas = t.join(historicas.select("id_empresa"), on="id_empresa", how="anti")
siguiente = ops.filter(pl.col("periodo") > periodo_test).filter(pl.col("periodo") == pl.col("periodo").min())
real = usan.filter(pl.col("target_real") == 1).join(historicas, on="id_empresa").join(
    siguiente.select("id_empresa", pl.col("monto").alias("real")), on="id_empresa")
la, lb = np.log1p(real["monto_mes"].to_numpy()), np.log1p(real["real"].to_numpy())
r2 = round(float(1 - ((lb - la) ** 2).sum() / ((lb - lb.mean()) ** 2).sum()), 4) if len(real) > 1 else None
backtest = {
    "gini": gini(y, p), "r2_monto": r2, "ganancia": ganancia, "n": n, "conversiones": pos, "tasa_base": round(pos / n, 5),
    "ventana": int(siguiente["periodo"][0]),
    "por_grupo": {"usan": gini(usan["target_real"].to_numpy().astype(int), usan["prob_calibrada"].to_numpy()),
                  "nuevas": gini(nuevas["target_real"].to_numpy().astype(int), nuevas["prob_calibrada"].to_numpy())},
}

C.MODELO_DIR.mkdir(exist_ok=True)
pred.write_csv(C.MODELO_DIR / "predicciones.csv")
(C.MODELO_DIR / "backtest.json").write_text(json.dumps(backtest, ensure_ascii=False), encoding="utf-8")
(C.MODELO_DIR / "metadata.json").write_text(json.dumps({
    "tipo": "modelo", "nombre": "Modelo ML", "version": f"forecast {MESES[C.CORTE % 100 - 1]} {C.CORTE // 100}", "fecha": date.today().isoformat(),
    "monto": "Estimado con el historial", "horizonte": "1 mes",
}, ensure_ascii=False, indent=2), encoding="utf-8")
ruta_imp = C.MODELO_DIR / "importancia_variables.csv"
if not ruta_imp.exists():
    ruta_imp.write_text("variable,etiqueta,importancia,direccion\n", encoding="utf-8")

print(f"candidatas con prediccion: {pred.height:,} de {candidatas.height:,} clientes | no clientes sin prediccion: {sin_prediccion:,}")
print(f"monto: proporcion de ventas a aceptantes {proporcion:.3f}, piso S/ {piso:,.0f}")
print(f"test: gini usuarios {backtest['por_grupo']['usan']} | gini nuevas {backtest['por_grupo']['nuevas']} | r2 monto {r2}")
