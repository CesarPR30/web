"""Paso 3. Une features + predicciones y escribe los inputs del dashboard (dashboard/inputs/*.js).

Se escriben como .js (window.DASH.x = ...) y no como .json para que el dashboard abra con doble clic:
los navegadores bloquean fetch() en file://.

Grupos de campana:
    A  Lead actual     pyme cliente con flag_lead
    B  Habilitable     pyme cliente sin lead, con ventas a aceptantes
    C  Captacion       no cliente con ventas a aceptantes (va con costo de onboarding)
"""
import json
import math
import sys
from datetime import datetime

import duckdb
import numpy as np
import polars as pl

import config as C

ARCH_PRED = C.MODELO_DIR / "predicciones.csv"
ARCH_IMP = C.MODELO_DIR / "importancia_variables.csv"
ARCH_META = C.MODELO_DIR / "metadata.json"


def fallar(msg):
    sys.exit(f"ERROR en el contrato de predicciones: {msg}")


def validar(pred, imp, meta, f):
    for c in ("id_empresa", "p_conversion", "monto_esperado"):
        if c not in pred.columns:
            fallar(f"falta la columna {c} en predicciones.csv")
    for c in ("variable", "etiqueta", "importancia", "direccion"):
        if c not in imp.columns:
            fallar(f"falta la columna {c} en importancia_variables.csv")
    for c in ("tipo", "nombre", "version", "fecha"):
        if c not in meta:
            fallar(f"falta la clave {c} en metadata.json")
    if pred["id_empresa"].n_unique() != len(pred):
        fallar("id_empresa repetido")
    if pred["p_conversion"].null_count() or pred["monto_esperado"].null_count():
        fallar("hay nulos en p_conversion o monto_esperado")
    if not pred["p_conversion"].is_between(0, 1).all():
        fallar("p_conversion fuera de [0,1]")
    if (pred["monto_esperado"] < 0).any():
        fallar("monto_esperado negativo")
    faltan = pred.join(f.select("id_empresa"), on="id_empresa", how="anti").height
    if faltan:
        fallar(f"{faltan:,} id_empresa no existen en las bases")


def js(nombre, obj):
    C.INPUTS_DIR.mkdir(exist_ok=True)
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    ruta = C.INPUTS_DIR / f"{nombre}.js"
    ruta.write_text(f"window.DASH=window.DASH||{{}};window.DASH.{nombre}={txt};\n", encoding="utf-8")
    print(f"  {ruta.name:16s} {ruta.stat().st_size / 1e6:6.2f} MB")


def r(x, n=4):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), n)


f_all = pl.read_parquet(C.CACHE / "features_empresa.parquet")
pred = pl.read_csv(ARCH_PRED, schema_overrides={"id_empresa": pl.Utf8})
imp = pl.read_csv(ARCH_IMP)
meta_modelo = json.loads(ARCH_META.read_text(encoding="utf-8"))
validar(pred, imp, meta_modelo, f_all)

d = f_all.join(pred, on="id_empresa", how="inner").with_columns(
    pl.when(~pl.col("es_cliente")).then(pl.lit("C"))
      .when(pl.col("flag_lead") == 1).then(pl.lit("A")).otherwise(pl.lit("B")).alias("grupo"),
    (pl.col("ops_previas") > 0).alias("previo"),
    (pl.col("p_conversion") * pl.col("monto_esperado")).alias("pm"),
    (pl.col("vol_aceptantes") / pl.when(pl.col("es_cliente")).then(pl.col("ventas_12m")).otherwise(pl.col("vol_total"))
     ).clip(0, 1).fill_null(0).fill_nan(0).alias("pct_acept"),
    (((pl.col("ventas_q4").fill_null(0) + 1) / (pl.col("ventas_q1").fill_null(0) + 1)).log().clip(-1, 1)).alias("crec"),
)
margen_info = json.loads((C.CACHE / "margen.json").read_text())
S = C.SUPUESTOS
umbral = S["umbral_habilitacion"]
print(d.group_by("grupo", "previo").agg(pl.len(), pl.col("p_conversion").mean(), pl.col("pm").mean()).sort("grupo", "previo"))
print("sobre umbral:", d.filter(pl.col("p_conversion") >= umbral).group_by("grupo").len().sort("grupo"))

# ------------------------------------------------------------------ simulador: bins sobre toda la base
# Fino en P x monto (define el orden de contacto); bordes de P = pasos del slider de umbral.
EDGES_P = np.concatenate([[0.0], np.round(np.arange(0.01, 0.1001, 0.0025), 4)])
EDGES_PM = np.geomspace(1, 1e9, 420)
b = d.with_columns(
    pl.Series("bp", np.searchsorted(EDGES_P, d["p_conversion"].to_numpy(), side="right") - 1),
    pl.Series("bv", np.clip(np.searchsorted(EDGES_PM, d["pm"].to_numpy(), side="right"), 0, len(EDGES_PM))),
).group_by("grupo", "previo", "bp", "bv").agg(
    n=pl.len(), sp=pl.col("p_conversion").sum(), spm=pl.col("pm").sum(), sm=pl.col("monto_esperado").sum())
GRUPOS = ["A", "B", "C"]
bins = [[GRUPOS.index(g), int(pv), round(float(EDGES_P[bp]), 4), n, round(sp, 3), round(spm, 1), round(sm)]
        for g, pv, bp, n, sp, spm, sm in b.select("grupo", "previo", "bp", "n", "sp", "spm", "sm").iter_rows()]

# ------------------------------------------------------------------ resumen
n_total = f_all.height
n_pyme = f_all.filter(pl.col("es_cliente") & (pl.col("segmento") != C.SEGMENTO_ACEPTANTE)).height
n_nocli = f_all.filter(~pl.col("es_cliente")).height
n_acept = f_all.filter(pl.col("segmento") == C.SEGMENTO_ACEPTANTE).height
n_con_acept = d.filter(pl.col("grupo") != "C").height
habil = d.filter((pl.col("grupo") == "A") | (pl.col("p_conversion") >= umbral))
top30 = habil.sort("p_conversion", descending=True).head(int(habil.height * 0.3))


def concentracion(col, excluir=("Sin dato",)):
    baset = habil.filter(~pl.col(col).is_in(list(excluir))).group_by(col).agg(pl.len().alias("base"))
    topt = top30.filter(~pl.col(col).is_in(list(excluir))).group_by(col).agg(pl.len().alias("top"), pl.col("pm").sum().alias("pm"))
    t = baset.join(topt, on=col, how="left").fill_null(0)
    bt, tt = t["base"].sum(), t["top"].sum()
    return [{"nombre": a, "peso_base": r(x / bt), "peso_top": r(y / tt), "indice": r((y / tt) / (x / bt), 3), "valor": r(v, 0)}
            for a, x, y, v in t.select(col, "base", "top", "pm").sort("top", descending=True).iter_rows()]


resto = habil.join(top30.select("id_empresa"), on="id_empresa", how="anti")


def perfil(df):
    cli = df.filter(pl.col("es_cliente"))
    return {
        "pct_acept": r(df["pct_acept"].median()), "crec": r(cli["crec"].median()),
        "previo": r(df["previo"].mean()), "dias": r(df["dias_credito_acept"].median(), 0),
        "n_acept": r(df["n_aceptantes"].mean(), 2), "monto": r(df["monto_esperado"].median(), 0),
        "uso": r(cli["uso_linea"].mean()),
    }


hist = pl.read_parquet(C.CACHE / "hist_factoring.parquet")
serie = hist.group_by("periodo").agg(pl.col("ops").sum(), pl.col("desembolso").sum(), pl.col("cedentes").sum()).sort("periodo")
hist_rubro = hist.filter(pl.col("periodo") <= C.CORTE).group_by("rubro").agg(pl.col("desembolso").sum()).sort("desembolso", descending=True)

# Backtest contra operaciones reales posteriores al corte (solo clientes).
bt = d.filter(pl.col("es_cliente")).sort("p_conversion", descending=True)
y = bt["conv_real"].to_numpy().astype(int)
n_bt, pos = len(y), int(y.sum())


def calcular_backtest():
    rk = bt["p_conversion"].rank("average", descending=False).to_numpy()
    auc = (rk[y == 1].sum() - pos * (pos + 1) / 2) / (pos * (n_bt - pos))
    acum = np.cumsum(y)
    ganancia = [{"x": r(i / 20, 2), "y": r(acum[max(int(n_bt * i / 20) - 1, 0)] / pos)} for i in range(1, 21)]
    deciles = []
    edges = np.linspace(0, n_bt, 11).astype(int)
    pp = bt["p_conversion"].to_numpy()
    for i in range(10):
        a, z = edges[i], edges[i + 1]
        deciles.append({"decil": i + 1, "pred": r(pp[a:z].mean()), "real": r(y[a:z].mean())})
    conv = bt.filter(pl.col("conv_real"))
    la, lb = np.log1p(conv["monto_esperado"].to_numpy()), np.log1p(conv["monto_real"].to_numpy())
    r2 = 1 - ((lb - la) ** 2).sum() / ((lb - lb.mean()) ** 2).sum()
    leads_bt = bt.filter(pl.col("grupo") == "A")
    return {"gini": r(2 * auc - 1), "r2_monto": r(r2), "ganancia": ganancia, "deciles": deciles,
            "n": n_bt, "conversiones": pos, "tasa_base": r(pos / n_bt),
            "conv_leads": r(leads_bt["conv_real"].mean())}


# Un dataset sin operaciones posteriores al corte no tiene contra que validar: el dashboard oculta esa tarjeta.
# Si el modelo trae su propia validacion fuera de muestra (backtest.json), se usa esa.
ARCH_BT = C.MODELO_DIR / "backtest.json"
backtest = calcular_backtest() if 0 < pos < n_bt else json.loads(ARCH_BT.read_text(encoding="utf-8")) if ARCH_BT.exists() else None

resumen = {
    "embudo": {"universo": n_total, "pyme": n_pyme, "no_clientes": n_nocli, "aceptantes": n_acept,
               "evaluables": d.height, "con_aceptante": n_con_acept,
               "leads": d.filter(pl.col("grupo") == "A").height},
    "historico": [{"periodo": p, "ops": o, "desembolso": r(v, 0), "post": p > C.CORTE} for p, o, v in serie.select("periodo", "ops", "desembolso").iter_rows()],
    "hist_rubro": [{"nombre": a, "valor": r(v, 0)} for a, v in hist_rubro.iter_rows()],
    "concentracion": {"rubro": concentracion("rubro"), "departamento": concentracion("departamento"), "segmento": concentracion("segmento")},
    "perfil": {"top": perfil(top30), "resto": perfil(resto)},
    "importancia": imp.to_dicts(),
    "backtest": backtest,
}

# ------------------------------------------------------------------ lista y fichas
tops = pl.concat([d.filter(pl.col("grupo") == g).sort("pm", descending=True).head(k) for g, k in C.TOP_LISTA.items()])
con = duckdb.connect()
con.execute("SET preserve_insertion_order=false")
con.register("tops_v", tops.select("id_empresa", "es_cliente").to_arrow())
ar = pl.read_parquet(C.CACHE / "aristas_aceptantes.parquet")
ancla_top = ar.join(tops.select("id_empresa"), left_on="id_proveedor", right_on="id_empresa").sort("vol", descending=True).group_by("id_proveedor", maintain_order=True).first().select(
    pl.col("id_proveedor").alias("id_empresa"), pl.col("id_aceptante").alias("ancla"), pl.col("vol").alias("vol_ancla"))
tops = tops.join(ancla_top, on="id_empresa", how="left")

s1 = con.execute(f"""SELECT p.id_empresa, periodo, ventas_mes AS v FROM {C.fuente('perfil')} p
    JOIN tops_v t ON t.id_empresa=p.id_empresa WHERE t.es_cliente AND periodo<={C.CORTE}""").pl()
s2 = con.execute(f"""SELECT id_receptor AS id_empresa, periodo,
    sum(monto*CASE WHEN moneda='USD' THEN {C.TC_USD} ELSE 1 END) AS v FROM {C.fuente('transacciones')} x
    JOIN tops_v t ON t.id_empresa=x.id_receptor WHERE NOT t.es_cliente AND periodo<={C.CORTE} GROUP BY 1,2""").pl()
serie_emp = {}
idx = {p: i for i, p in enumerate(C.PERIODOS_FEATURES)}
for e, p, v in pl.concat([s1, s2]).iter_rows():
    if v is not None and p in idx:
        serie_emp.setdefault(e, [0] * 12)[idx[p]] = round(v / 1000)

rubros = sorted(tops["rubro"].unique().to_list())
deptos = sorted(tops["departamento"].unique().to_list())
segs = ["Micro", "Pequeña", "Mediana", "Sin dato"]
filas = []
for x in tops.iter_rows(named=True):
    filas.append([
        x["id_empresa"], GRUPOS.index(x["grupo"]), rubros.index(x["rubro"]), segs.index(x["segmento"]) if x["segmento"] in segs else 3,
        deptos.index(x["departamento"]), r(x["p_conversion"], 4), round(x["monto_esperado"]), int(x["previo"]),
        r((x["ventas_12m"] if x["es_cliente"] else x["vol_total"]) or 0, 0), r(x["pct_acept"], 3), r(x["crec"], 3) if x["es_cliente"] else None,
        x["n_aceptantes"], r(x["dias_credito_acept"], 0), x["rating"], x["ops_previas"], x["ancla"],
        r(x["vol_ancla"], 0), r(x["uso_linea"], 2), x["n_productos"], r(x["antiguedad_anios"], 1), serie_emp.get(x["id_empresa"]),
    ])
lista = {
    "campos": ["id", "g", "rubro", "seg", "depto", "p", "m", "prev", "ventas", "pct", "crec", "nac", "dias", "rating",
               "ops", "ancla", "volAncla", "uso", "prod", "antig", "serie"],
    "rubros": rubros, "departamentos": deptos, "segmentos": segs, "filas": filas,
    "periodos": C.PERIODOS_FEATURES,
}

# ------------------------------------------------------------------ red de aceptantes
sel = d.select("id_empresa", "grupo", "previo", "p_conversion", "monto_esperado", "pm")
ar2 = ar.join(sel, left_on="id_proveedor", right_on="id_empresa", how="left")
pot = ar2.with_columns(
    (pl.col("grupo").is_not_null() & ((pl.col("grupo") == "A") | (pl.col("p_conversion") >= umbral))).alias("oport"))
res = pot.group_by("id_aceptante").agg(
    pl.len().alias("n_prov"), pl.col("vol").sum().alias("vol"),
    pl.col("oport").sum().alias("n_oport"),
    pl.col("pm").filter(pl.col("oport") & ~pl.col("previo").fill_null(False)).sum().alias("potencial"),
    pl.col("previo").fill_null(False).sum().alias("n_usa"),
    (pl.col("grupo") == "C").fill_null(False).sum().alias("n_captacion"),
    pl.col("vol").filter(pl.col("previo").fill_null(False)).sum().alias("vol_usa"),
).sort("potencial", descending=True)
anclas_t = res.head(C.N_ANCLAS).join(f_all.select("id_empresa", "rubro", "departamento", "rating"), left_on="id_aceptante", right_on="id_empresa", how="left")
anclas = []
for a in anclas_t.iter_rows(named=True):
    # Muestra equilibrada: los de mayor valor por grupo, mas algunos que ya usan factoring como referencia.
    cand = pot.filter((pl.col("id_aceptante") == a["id_aceptante"]) & pl.col("oport")).sort("pm", descending=True)
    pv = pl.concat([cand.filter((pl.col("grupo") == g) & ~pl.col("previo")).head(C.N_PROVEEDORES_ANCLA // 4) for g in GRUPOS]
                   + [cand.filter(pl.col("previo")).head(C.N_PROVEEDORES_ANCLA // 4)])
    anclas.append({
        "id": a["id_aceptante"], "rubro": a["rubro"], "departamento": a["departamento"], "n_prov": a["n_prov"],
        "n_oport": a["n_oport"], "n_usa": a["n_usa"], "n_captacion": a["n_captacion"], "potencial": r(a["potencial"], 0),
        "vol": r(a["vol"], 0), "pct_vol_usa": r(a["vol_usa"] / a["vol"] if a["vol"] else 0),
        "proveedores": [[z["id_proveedor"], GRUPOS.index(z["grupo"]), int(z["previo"]), round(z["vol"]), r(z["p_conversion"], 4), round(z["monto_esperado"])]
                        for z in pv.iter_rows(named=True)],
    })

red = {"anclas": anclas, "totales": {"aceptantes": res.height, "con_potencial": res.filter(pl.col("potencial") > 0).height,
                                    "top_share": r(res.head(C.N_ANCLAS)["potencial"].sum() / res["potencial"].sum())}}

meta = {
    "generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "corte": C.CORTE, "modelo": meta_modelo,
    "dataset": {"nombre": C.NOMBRE_DATASET, "carpeta": C.DATA_DIR.name},
    "supuestos": S, "capacidad_max": C.CAPACIDAD_MAX,
    "margen": r(margen_info["margen"], 5), "tasa": r(margen_info["tasa"]), "plazo": r(margen_info["plazo"], 1),
    "grupos": [{"id": "A", "nombre": "Lead actual"}, {"id": "B", "nombre": "Habilitable"}, {"id": "C", "nombre": "Captación"}],
}

js("meta", meta)
js("resumen", resumen)
js("simulador", {"bins": bins})
js("lista", lista)
js("red", red)
print(f"gini={backtest['gini']} r2={backtest.get('r2_monto')} margen={meta['margen']}" if backtest else f"sin backtest; margen={meta['margen']}")
