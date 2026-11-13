"""Paso 2 (TEMPORAL). Inventa predicciones plausibles para poder construir el dashboard.

BORRAR ESTE PASO cuando exista el modelo real: el modelo debe escribir los mismos 3 archivos.

    modelo/predicciones.csv          id_empresa, p_conversion, monto_esperado   (obligatorio)
    modelo/importancia_variables.csv variable, etiqueta, importancia, direccion (obligatorio)
    modelo/metadata.json             tipo, nombre, version, fecha               (obligatorio)

Definicion de cada columna:
    p_conversion    probabilidad [0,1] de hacer factoring en los 6 meses tras la campana si se le contacta
    monto_esperado  soles desembolsados en esos 6 meses SI convierte (no ponderado por p)

Esto NO es un modelo: es una formula a mano con ruido, sin entrenamiento y sin usar _ground_truth.csv.
"""
import json
from datetime import date

import numpy as np
import polars as pl

import config as C

rng = np.random.default_rng(2026)
f = pl.read_parquet(C.CACHE / "features_empresa.parquet")

# Universo evaluable: pymes clientes al corte y no clientes con ventas a aceptantes.
fecha_alta = f["fecha_alta_cliente"].cast(pl.Utf8)
cliente_ok = f["es_cliente"] & (f["segmento"] != C.SEGMENTO_ACEPTANTE) & (fecha_alta <= C.FECHA_CORTE).fill_null(False)
evaluable = (cliente_ok & ((f["vol_aceptantes"] > 0) | (f["flag_lead"] == 1))) | (~f["es_cliente"] & (f["vol_aceptantes"] > 0))
f = f.filter(evaluable)
n = len(f)

cli = f["es_cliente"].to_numpy()
vol_ac = f["vol_aceptantes"].to_numpy()
ventas = f["ventas_12m"].fill_null(0).to_numpy()
total = f["vol_total"].to_numpy()
pct = np.clip(np.divide(vol_ac, np.where(cli, ventas, total), out=np.zeros(n), where=np.where(cli, ventas, total) > 0), 0, 1)
crec = np.where(cli, np.clip(np.log((f["ventas_q4"].fill_null(0).to_numpy() + 1) / (f["ventas_q1"].fill_null(0).to_numpy() + 1)), -1, 1), 0)
prev = (f["ops_previas"].to_numpy() > 0).astype(float)
lead = f["flag_lead"].to_numpy().astype(float)
uso = np.where(cli, f["uso_linea"].fill_null(0).to_numpy(), 0)

aportes = {
    "pct_ventas_aceptantes": ("% de ventas a aceptantes", 2.0 * pct, "+"),
    "factoring_previo": ("Ya usó factoring", 1.1 * prev, "+"),
    "crecimiento_ventas": ("Crecimiento de ventas", 0.7 * crec, "+"),
    "flag_lead": ("Marcada como lead", 0.45 * lead, "+"),
    "uso_linea_credito": ("Uso de línea de crédito", 0.5 * (uso - 0.4), "+"),
}
logit = -4.3 + sum(a[1] for a in aportes.values()) - 0.6 * (~cli) + rng.normal(0, 0.4, n)
p = 1 / (1 + np.exp(-logit))

base = 0.35 * vol_ac / 2                                    # 12 meses -> semestre, fraccion descontable
historico = f["monto_previo"].to_numpy() / 2
monto = np.where(prev > 0, 0.5 * base + 0.5 * historico, base) * rng.lognormal(0, 0.45, n)
# Rango coherente con lo observado: sin esto la cola lognormal da montos de S/ 200 M y Captacion domina.
monto = np.where(cli, monto, 0.5 * monto)
monto = np.maximum(6e6 * (1 - np.exp(-monto / 6e6)), 1500)   # tope suave

C.MODELO_DIR.mkdir(exist_ok=True)
pl.DataFrame({"id_empresa": f["id_empresa"], "p_conversion": np.round(p, 5), "monto_esperado": np.round(monto, 2)}).write_csv(
    C.MODELO_DIR / "predicciones.csv")

imp = {k: float(np.abs(v[1] - v[1].mean()).mean()) for k, v in aportes.items()}
s = sum(imp.values())
pl.DataFrame({
    "variable": list(imp),
    "etiqueta": [aportes[k][0] for k in imp],
    "importancia": [round(v / s, 4) for v in imp.values()],
    "direccion": [aportes[k][2] for k in imp],
}).sort("importancia", descending=True).write_csv(C.MODELO_DIR / "importancia_variables.csv")

(C.MODELO_DIR / "metadata.json").write_text(json.dumps({
    "tipo": "simulado", "nombre": "Predicciones simuladas", "version": "plantilla",
    "fecha": date.today().isoformat(),
}, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"filas={n:,}  p media={p.mean():.3f}  p50={np.median(p):.3f}  p99={np.quantile(p, .99):.3f}")
print(f"monto p50={np.median(monto):,.0f}  p90={np.quantile(monto, .9):,.0f}  media={monto.mean():,.0f}")
real = f.filter(pl.col("conv_real"))["monto_real"]
if len(real):
    print(f"referencia real post-corte: n={len(real):,} p50={real.median():,.0f} media={real.mean():,.0f}")
