"""Generador de data dummy — Datafest 2026, Caso Factoring.

Genera las 4 tablas descritas en datafest_caso_factoring.md:
    1_maestro_empresas.csv       1 fila por empresa cliente
    2_transacciones.csv          par (pagador, receptor) x periodo
    3_operaciones_factoring.csv  1 fila por operacion
    4_perfil_historico.csv       empresa cliente x mes
    _ground_truth.csv            variables latentes (solo para validar, NO entregar)

Ventana: 18 meses (202501-202606). Corte en 202512; target en 202601-202606.

Uso:
    python generate_data.py --n-empresas 5000 --out data/sample
    python generate_data.py --n-empresas 1000000 --out data/full   # escala GB
"""
import argparse
import os
import time

import numpy as np
import pandas as pd
import polars as pl

N_MESES = 18
CORTE = 12  # meses 0..11 = features, 12..17 = target
PERIODOS = np.array([int(p.strftime("%Y%m")) for p in pd.period_range("2025-01", periods=N_MESES, freq="M")])
INICIO_VENTANA = pd.Timestamp("2025-01-01")
FECHA_CORTE = pd.Timestamp("2025-12-31")
FECHA_OBS = pd.Timestamp("2026-06-30")
TC_USD = 3.75

SEGMENTOS = ["Micro", "Pequeña", "Mediana", "Corporativa"]
VENTAS_MED = {"Micro": 4e5, "Pequeña": 3e6, "Mediana": 1.5e7, "Corporativa": 2e8}
VENTAS_SIG = {"Micro": 0.6, "Pequeña": 0.5, "Mediana": 0.5, "Corporativa": 0.8}
GRADO_LAM = {"Micro": 1.0, "Pequeña": 2.0, "Mediana": 3.5, "Corporativa": 2.0}
ANTIG_MEDIA = {"Micro": 4, "Pequeña": 8, "Mediana": 13, "Corporativa": 25}
P_CREDITO = {"Micro": 0.35, "Pequeña": 0.6, "Mediana": 0.8, "Corporativa": 0.95}
P_TARJETA = {"Micro": 0.3, "Pequeña": 0.45, "Mediana": 0.6, "Corporativa": 0.8}
PRIMA_TASA = {"Micro": 0.05, "Pequeña": 0.03, "Mediana": 0.015, "Corporativa": 0.0}

RUBROS = ["Comercio", "Servicios", "Manufactura", "Construcción", "Agro", "Transporte", "Retail", "Minería"]
P_RUBRO_PYME = [0.40, 0.20, 0.14, 0.08, 0.07, 0.06, 0.05, 0.00]
P_RUBRO_CORP = [0.15, 0.10, 0.25, 0.05, 0.10, 0.00, 0.25, 0.10]
SECTOR = {"Agro": "Primario", "Minería": "Primario", "Manufactura": "Secundario", "Construcción": "Secundario"}
CIIU = {
    "Comercio": ["4610", "4620", "4630", "4649", "4690"],
    "Servicios": ["6201", "6920", "7020", "7110", "8299"],
    "Manufactura": ["1010", "1410", "1811", "2220", "2511"],
    "Construcción": ["4100", "4210", "4290", "4330"],
    "Agro": ["0111", "0113", "0122", "0150"],
    "Transporte": ["4923", "5210", "5229"],
    "Retail": ["4711", "4719", "4771"],
    "Minería": ["0710", "0729", "0990"],
}
# Multiplicadores mensuales ene..dic (se normalizan a media 1)
ESTACIONALIDAD = {
    "Comercio":     [0.9, 0.85, 1.1, 0.95, 0.95, 0.95, 1.1, 0.95, 0.95, 1.0, 1.1, 1.5],
    "Retail":       [0.85, 0.8, 1.15, 0.9, 1.0, 0.95, 1.15, 0.9, 0.9, 1.0, 1.15, 1.7],
    "Agro":         [1.1, 1.3, 1.5, 1.4, 1.2, 0.9, 0.8, 0.7, 0.7, 0.8, 0.9, 1.0],
    "Manufactura":  [0.9, 0.9, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.05, 1.1, 1.2, 1.1],
    "Construcción": [0.9, 0.75, 0.8, 0.95, 1.05, 1.1, 1.1, 1.1, 1.05, 1.05, 1.05, 1.1],
    "Servicios":    [0.95, 0.95, 1.05, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.05],
    "Transporte":   [0.9, 0.9, 1.05, 1.0, 1.0, 0.95, 1.05, 1.0, 1.0, 1.0, 1.05, 1.2],
    "Minería":      [1.0] * 12,
}
DEPARTAMENTOS = ["Lima", "Arequipa", "La Libertad", "Piura", "Lambayeque", "Cusco", "Junín", "Ica", "Callao"]
P_DEPTO = [0.60, 0.08, 0.07, 0.06, 0.05, 0.04, 0.04, 0.03, 0.03]
PROVINCIAS = {
    "Lima": ["Lima"] * 9 + ["Huaral", "Cañete"],
    "Arequipa": ["Arequipa", "Arequipa", "Camaná", "Islay"],
    "La Libertad": ["Trujillo", "Trujillo", "Pacasmayo", "Chepén"],
    "Piura": ["Piura", "Piura", "Sullana", "Paita"],
    "Lambayeque": ["Chiclayo", "Chiclayo", "Lambayeque", "Ferreñafe"],
    "Cusco": ["Cusco", "Cusco", "Urubamba", "La Convención"],
    "Junín": ["Huancayo", "Huancayo", "Tarma", "Chanchamayo"],
    "Ica": ["Ica", "Ica", "Chincha", "Pisco"],
    "Callao": ["Callao"],
}
DISTRITOS_LIMA = ["Cercado de Lima", "La Victoria", "San Isidro", "Miraflores", "Ate", "Surco", "Los Olivos",
                  "San Juan de Lurigancho", "Lurín", "Chorrillos", "Independencia", "San Borja", "Breña"]


def escribir_csv(cols, path, primero):
    """Append rapido con polars; NaN -> vacio (igual que pandas)."""
    df = pl.DataFrame(cols).fill_nan(None)
    with open(path, "wb" if primero else "ab") as fh:
        df.write_csv(fh, include_header=primero)


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def mes_idx(fechas):
    """Indice de mes relativo a 2025-01 (puede ser negativo)."""
    f = pd.DatetimeIndex(fechas)
    return ((f.year - 2025) * 12 + f.month - 1).to_numpy()


def generar(n, seed, out, b0_conv=-4.0, chunk_edges=20_000, chunk_cli=20_000):
    t0 = time.time()
    rng = np.random.default_rng(seed)
    os.makedirs(out, exist_ok=True)
    t = np.arange(N_MESES)

    # ------------------------------------------------------------------ universo
    n_acept = max(30, round(0.03 * n))
    n_nocli = round(0.20 * n)
    n_pyme = n - n_acept - n_nocli
    tipo = np.array(["acept"] * n_acept + ["pyme"] * n_pyme + ["nocli"] * n_nocli)
    rng.shuffle(tipo)
    es_acept, es_pyme, es_nocli = tipo == "acept", tipo == "pyme", tipo == "nocli"
    es_cli = ~es_nocli
    ids = np.array([f"E{i:07d}" for i in rng.permutation(n) + 1])

    segmento = np.empty(n, dtype=object)
    segmento[es_acept] = "Corporativa"
    segmento[es_pyme] = rng.choice(SEGMENTOS[:3], es_pyme.sum(), p=[0.5, 0.35, 0.15])
    segmento[es_nocli] = rng.choice(SEGMENTOS, es_nocli.sum(), p=[0.45, 0.35, 0.17, 0.03])
    seg_s = pd.Series(segmento)

    ventas_anuales = seg_s.map(VENTAS_MED).to_numpy() * np.exp(seg_s.map(VENTAS_SIG).to_numpy() * rng.standard_normal(n))
    num_empleados = np.maximum(1, np.round(ventas_anuales / 1.2e5 * rng.lognormal(0, 0.4, n))).astype(int)

    rubro = np.empty(n, dtype=object)
    corp = segmento == "Corporativa"
    rubro[~corp] = rng.choice(RUBROS, (~corp).sum(), p=P_RUBRO_PYME)
    rubro[corp] = rng.choice(RUBROS, corp.sum(), p=P_RUBRO_CORP)
    rub_s = pd.Series(rubro)
    rubro_idx = rub_s.map({r: i for i, r in enumerate(RUBROS)}).to_numpy()

    # antigüedad y fechas
    antig = 0.5 + rng.gamma(2.0, seg_s.map(ANTIG_MEDIA).to_numpy() / 2.0)
    inicio = (FECHA_CORTE - pd.to_timedelta(antig * 365.25, unit="D")).normalize()
    start_m = np.maximum(mes_idx(inicio), 0)

    en_ventana = rng.random(n) < 0.12
    dias_pre = np.maximum((INICIO_VENTANA - inicio).days.to_numpy(), 0)
    alta_pre = inicio + pd.to_timedelta(np.floor(rng.random(n) * dias_pre), unit="D")
    alta_win = INICIO_VENTANA + pd.to_timedelta(rng.integers(0, (pd.Timestamp("2026-04-30") - INICIO_VENTANA).days, n), unit="D")
    alta_win = pd.DatetimeIndex(np.maximum(alta_win.to_numpy(), inicio.to_numpy()))
    alta = pd.DatetimeIndex(np.where(en_ventana, alta_win.to_numpy(), alta_pre.to_numpy()))
    alta_m = mes_idx(alta)  # puede ser negativo (alta antes de la ventana)

    # ------------------------------------------------------------------ ventas mensuales latentes (PEN)
    seas = np.array([np.array(ESTACIONALIDAD[r]) / np.mean(ESTACIONALIDAD[r]) for r in RUBROS])
    g = rng.normal(0.03, 0.20, n)  # crecimiento anual latente
    V = ((ventas_anuales / 12)[:, None] * np.exp(g[:, None] * t / 12) * seas[rubro_idx][:, t % 12]
         * rng.lognormal(0, 0.12, (n, N_MESES)))
    V[t[None, :] < start_m[:, None]] = 0

    # ------------------------------------------------------------------ red comercial (Tabla 2)
    k = rng.poisson(seg_s.map(GRADO_LAM).to_numpy()) + 1
    k[rng.random(n) < 0.05] = 0  # caso borde: empresas sin ventas a la red
    seller = np.repeat(np.arange(n), k)
    # atractivo como comprador: ley de potencia (preferential attachment) + tamaño; aceptantes = anclas
    attract = (rng.pareto(1.3, n) + 1) * np.sqrt(ventas_anuales / ventas_anuales.mean())
    attract[es_acept] *= 4
    buyer = rng.choice(n, size=len(seller), p=attract / attract.sum())
    ok = (buyer != seller) & ~(es_nocli[buyer] & es_nocli[seller])  # el banco solo ve flujos con >=1 cliente
    pares = np.unique(seller[ok].astype(np.int64) * n + buyer[ok])
    seller, buyer = (pares // n).astype(np.int64), (pares % n).astype(np.int64)
    E = len(seller)

    share = np.clip(rng.beta(2, 3, n), 0.05, 0.85)  # % de ventas que pasa por la red observada
    gam = rng.gamma(0.7, 1.0, E)
    w = share[seller] * gam / np.bincount(seller, gam, minlength=n)[seller]

    freq = rng.beta(3, 1.2, E)
    e_start = np.where(rng.random(E) < 0.2, rng.integers(0, N_MESES, E), 0)
    e_end = np.maximum(np.where(rng.random(E) < 0.1, rng.integers(0, N_MESES, E), N_MESES - 1), e_start)
    activo = ((rng.random((E, N_MESES)) < freq[:, None]) & (t >= e_start[:, None]) & (t <= e_end[:, None])
              & (t >= start_m[seller][:, None]) & (t >= start_m[buyer][:, None]))
    A = V[seller]  # in-place para no duplicar matrices E x 18 en memoria
    A *= w[:, None]
    A *= rng.lognormal(0, 0.25, (E, N_MESES))
    A *= activo
    del activo
    # cobros de la red nunca superan el 95% de las ventas del receptor
    S = np.column_stack([np.bincount(seller, A[:, m], minlength=n) for m in range(N_MESES)])
    escala = np.where(S > 0.95 * V, 0.95 * V / np.where(S > 0, S, 1), 1.0)
    A *= escala[seller]
    A[A < 50] = 0

    usd = rng.random(E) < np.where(rubro[seller] == "Agro", 0.30, 0.10)
    moneda_e = np.where(usd, "USD", "PEN")
    es_acc_edge = es_acept[buyer] & es_pyme[seller]
    dias_cred = np.where(es_acc_edge, rng.choice([30, 45, 60, 90, 120], E, p=[0.15, 0.25, 0.3, 0.2, 0.1]),
                         rng.choice([0, 15, 30, 45, 60], E, p=[0.35, 0.2, 0.25, 0.12, 0.08]))
    canal_e = rng.choice(["transferencia", "pago_proveedores", "deposito", "cheque", "letra"], E,
                         p=[0.55, 0.2, 0.1, 0.05, 0.1])
    canal_e[es_acept[buyer]] = rng.choice(["transferencia", "pago_proveedores"], es_acept[buyer].sum(), p=[0.4, 0.6])
    lam_trx = rng.gamma(2, 1.5, E)

    # ------------------------------------------------------------------ features latentes al corte
    acc_pre = np.bincount(seller[es_acc_edge], A[es_acc_edge, :CORTE].sum(1), minlength=n)
    v_pre = V[:, :CORTE].sum(1)
    pct_acept = np.divide(acc_pre, v_pre, out=np.zeros(n), where=v_pre > 0)
    crec = np.clip(np.log((V[:, 9:12].sum(1) + 1) / (V[:, 0:3].sum(1) + 1)), -1, 1)

    # pares (arista aceptante, mes) donde se puede factorar: hay factura y el cedente ya es cliente
    cand_e, cand_m = np.nonzero((A > 0) & es_acc_edge[:, None] & (t[None, :] > alta_m[seller][:, None]))
    cand_s = seller[cand_e]

    def operaciones(mask_emp, m_lo, m_hi):
        sel = mask_emp[cand_s] & (cand_m >= m_lo) & (cand_m < m_hi)
        e, m, s = cand_e[sel], cand_m[sel], cand_s[sel]
        q = rng.uniform(0.2, 0.7, n)
        tomar = rng.random(len(e)) < q[s]
        # garantiza al menos 1 operacion por empresa seleccionada
        perm = rng.permutation(len(e))
        _, primero = np.unique(s[perm], return_index=True)
        tomar[perm[primero]] = True
        return e[tomar], m[tomar]

    elig_pre = np.zeros(n, bool)
    elig_pre[np.unique(cand_s[cand_m < CORTE])] = True
    usa_pre = elig_pre & (rng.random(n) < sigmoid(-2.5 + 4.0 * pct_acept + rng.normal(0, 0.5, n)))
    ope_pre_e, ope_pre_m = operaciones(usa_pre, 0, CORTE)
    prev = np.zeros(n, bool)
    prev[seller[ope_pre_e]] = True

    # flag lead (el banco lo marca al corte con un score imperfecto)
    cli_corte = es_pyme & (alta_m <= CORTE - 1)
    zlogv = (np.log(ventas_anuales) - np.log(ventas_anuales).mean()) / np.log(ventas_anuales).std()
    score_lead = 2.0 * pct_acept + 1.0 * prev + 0.3 * zlogv + rng.normal(0, 0.7, n)
    score_lead[~cli_corte] = -np.inf
    flag_lead = np.zeros(n, bool)
    flag_lead[np.argsort(-score_lead)[: round(0.10 * es_pyme.sum())]] = True

    # señal plantada para conversión post-corte
    logit = b0_conv + 1.5 * pct_acept + 0.8 * crec + 1.0 * prev + 0.5 * flag_lead + rng.normal(0, 0.5, n)
    p_conv = sigmoid(logit)
    elig_t = np.zeros(n, bool)
    elig_t[np.unique(cand_s[cand_m >= CORTE])] = True
    p_conv[~(elig_t & cli_corte)] = 0
    convierte = rng.random(n) < p_conv
    ope_t_e, ope_t_m = operaciones(convierte, CORTE, N_MESES)

    # ------------------------------------------------------------------ Tabla 3
    oe = np.concatenate([ope_pre_e, ope_t_e])
    om = np.concatenate([ope_pre_m, ope_t_m])
    n_ops = len(oe)
    oc, oa = seller[oe], buyer[oe]
    usd_op = usd[oe]
    vol = A[oe, om] / np.where(usd_op, TC_USD, 1)
    monto_factura = np.round(vol * rng.uniform(0.3, 0.9, n_ops), 2)
    mes_ini = pd.to_datetime(PERIODOS[om].astype(str), format="%Y%m")
    dia = np.floor(rng.random(n_ops) * mes_ini.days_in_month.to_numpy()).astype(int)
    fecha_op = mes_ini + pd.to_timedelta(dia, unit="D")
    plazo = np.maximum(15, dias_cred[oe] - rng.integers(0, 15, n_ops))
    fecha_venc = fecha_op + pd.to_timedelta(plazo, unit="D")
    tasa = np.clip(0.10 + seg_s.map(PRIMA_TASA).to_numpy()[oc] - 0.03 * usd_op + rng.normal(0, 0.015, n_ops), 0.06, 0.25)
    comision = np.round(np.maximum(50, 0.002 * monto_factura), 2)
    anticipo = rng.uniform(0.85, 0.98, n_ops)
    monto_desemb = np.round(np.maximum(monto_factura * anticipo * (1 - tasa * plazo / 360) - comision, 0), 2)
    atraso = np.where(rng.random(n_ops) < 0.85, 0, rng.geometric(0.08, n_ops))
    vigente = fecha_venc > FECHA_OBS
    vencida = ~vigente & (fecha_venc + pd.to_timedelta(atraso, unit="D") > FECHA_OBS)
    estado = np.where(vigente, "vigente", np.where(vencida, "vencida", "pagada"))
    dias_atraso = np.where(vigente, 0, np.where(vencida, (FECHA_OBS - fecha_venc).days, atraso))
    t3 = pd.DataFrame({
        "id_cedente": ids[oc], "id_aceptante": ids[oa],
        "fecha_operacion": fecha_op.strftime("%Y-%m-%d"), "fecha_vencimiento": fecha_venc.strftime("%Y-%m-%d"),
        "plazo_dias": plazo, "monto_factura": monto_factura, "monto_desembolsado": monto_desemb,
        "tasa_anual": np.round(tasa, 4), "comision": comision, "moneda": moneda_e[oe],
        "tipo": rng.choice(["factoring", "confirming", "descuento"], n_ops, p=[0.85, 0.10, 0.05]),
        "estado": estado, "dias_atraso": dias_atraso,
    }).sort_values(["fecha_operacion", "id_cedente"]).reset_index(drop=True)
    t3.insert(0, "id_operacion", [f"F{i:07d}" for i in range(1, len(t3) + 1)])
    t3.to_csv(f"{out}/3_operaciones_factoring.csv", index=False)

    usa_fact = np.zeros((n, N_MESES), bool)
    usa_fact[oc, om] = True

    # ------------------------------------------------------------------ Tabla 1
    depto = rng.choice(DEPARTAMENTOS, n, p=P_DEPTO)
    prov = np.array([PROVINCIAS[d][i % len(PROVINCIAS[d])] for d, i in zip(depto, rng.integers(0, 100, n))])
    dist = np.where(prov == "Lima", rng.choice(DISTRITOS_LIMA, n), prov)
    score = np.clip(600 + 60 * zlogv + 4 * np.minimum(antig, 20) + rng.normal(0, 70, n), 300, 950).round()
    rating = np.select([score >= 750, score >= 650, score >= 550, score >= 450], ["A", "B", "C", "D"], "E")
    t1 = pd.DataFrame({
        "id_empresa": ids, "rubro": rubro,
        "ciiu": [CIIU[r][i % len(CIIU[r])] for r, i in zip(rubro, rng.integers(0, 100, n))],
        "sector": rub_s.map(SECTOR).fillna("Terciario").to_numpy(), "segmento": segmento,
        "ventas_anuales": np.round(ventas_anuales, 2), "num_empleados": num_empleados,
        "departamento": depto, "provincia": prov, "distrito": dist,
        "fecha_inicio_actividades": inicio.strftime("%Y-%m-%d"), "antiguedad_anios": np.round(antig, 1),
        "fecha_alta_cliente": alta.strftime("%Y-%m-%d"),
        "score_riesgo": score, "rating": rating, "flag_lead": flag_lead.astype(int),
    })
    # ruido: nulos en rating/ubicación y mayúsculas inconsistentes
    nul_r = rng.random(n) < 0.07
    t1.loc[nul_r, ["score_riesgo", "rating"]] = np.nan
    t1.loc[rng.random(n) < 0.05, ["departamento", "provincia", "distrito"]] = np.nan
    t1.loc[rng.random(n) < 0.03, "distrito"] = np.nan
    sucio = rng.random(n) < 0.02
    t1.loc[sucio, "departamento"] = t1.loc[sucio, "departamento"].str.upper()
    t1[es_cli].to_csv(f"{out}/1_maestro_empresas.csv", index=False)

    # ------------------------------------------------------------------ Tabla 2 (por chunks)
    path2 = f"{out}/2_transacciones.csv"
    n_t2, primero = 0, True
    for i in range(0, E, chunk_edges):
        sub = A[i:i + chunk_edges]
        ei, mi = np.nonzero(sub > 0)
        ei += i
        n_sub = len(ei)
        escribir_csv({
            "id_transaccion": np.char.add("T", np.char.zfill(np.arange(n_t2 + 1, n_t2 + n_sub + 1).astype(str), 9)),
            "id_pagador": ids[buyer[ei]], "id_receptor": ids[seller[ei]], "periodo": PERIODOS[mi],
            "monto": np.round(A[ei, mi] / np.where(usd[ei], TC_USD, 1), 2), "moneda": moneda_e[ei],
            "n_trx": 1 + rng.poisson(lam_trx[ei]), "canal": canal_e[ei], "dias_credito": dias_cred[ei],
        }, path2, primero)
        n_t2 += n_sub
        primero = False

    # ------------------------------------------------------------------ Tabla 4 (por chunks de empresas)
    cli = np.nonzero(es_cli)[0]
    seg_c = segmento[cli]
    nc = len(cli)
    tiene_cuenta_c = rng.random(nc) < 0.96
    cred_c = rng.random(nc) < pd.Series(seg_c).map(P_CREDITO).to_numpy()
    cred_ini = np.maximum(alta_m[cli], 0) + np.where(rng.random(nc) < 0.3, rng.integers(0, 24, nc), 0)
    tarj_c = rng.random(nc) < pd.Series(seg_c).map(P_TARJETA).to_numpy()
    tarj_ini = np.maximum(alta_m[cli], 0) + np.where(rng.random(nc) < 0.3, rng.integers(0, 24, nc), 0)
    extra_c = rng.choice([0, 1, 2], nc, p=[0.6, 0.3, 0.1])
    linea_c = ventas_anuales[cli] * rng.uniform(0.08, 0.3, nc)
    uso_base_c = np.clip(rng.beta(2, 3, nc) + 0.4 * pct_acept[cli], 0, 0.98)

    path4, n_t4 = f"{out}/4_perfil_historico.csv", 0
    for j in range(0, nc, chunk_cli):
        ci, mi = np.nonzero(t[None, :] >= np.maximum(alta_m[cli[j:j + chunk_cli]], 0)[:, None])
        ci += j
        emp = cli[ci]
        tiene_credito = cred_c[ci] & (mi >= cred_ini[ci])
        tiene_tarjeta = tarj_c[ci] & (mi >= tarj_ini[ci])
        ventas_mes = V[emp, mi]
        uso = np.where(tiene_credito, np.clip(uso_base_c[ci] + rng.normal(0, 0.08, len(ci)), 0, 1), 0)
        n_sub = len(ci)
        vm = np.round(ventas_mes, 2)
        vm[rng.random(n_sub) < 0.02] = np.nan
        escribir_csv({
            "id_empresa": ids[emp], "periodo": PERIODOS[mi], "ventas_mes": vm,
            "n_productos": (tiene_cuenta_c[ci].astype(int) + tiene_credito + tiene_tarjeta + extra_c[ci] + usa_fact[emp, mi]),
            "tiene_cuenta": tiene_cuenta_c[ci].astype(int), "tiene_credito": tiene_credito.astype(int),
            "tiene_tarjeta": tiene_tarjeta.astype(int),
            "saldo_promedio": np.round(np.where(tiene_cuenta_c[ci], ventas_mes * rng.lognormal(np.log(0.25), 0.5, len(ci)), 0), 2),
            "saldo_deuda": np.round(linea_c[ci] * uso, 2), "uso_linea_credito": np.round(uso, 4),
            "usa_factoring": usa_fact[emp, mi].astype(int),
        }, path4, j == 0)
        n_t4 += n_sub

    # ------------------------------------------------------------------ ground truth
    pd.DataFrame({
        "id_empresa": ids, "tipo": tipo, "pct_ventas_aceptantes": np.round(pct_acept, 4),
        "crecimiento": np.round(crec, 4), "factoring_previo": prev.astype(int), "flag_lead": flag_lead.astype(int),
        "p_conversion": np.round(p_conv, 4), "convierte": convierte.astype(int),
    }).to_csv(f"{out}/_ground_truth.csv", index=False)

    # ------------------------------------------------------------------ resumen
    lead_c = flag_lead & cli_corte
    print(f"empresas={n:,} (aceptantes={n_acept}, pyme cliente={n_pyme}, no cliente={n_nocli})")
    print(f"T1={es_cli.sum():,}  T2={n_t2:,}  T3={len(t3):,}  T4={n_t4:,}  aristas={E:,}")
    print(f"pymes con >=1 aceptante comprador: {np.isin(np.arange(n)[es_pyme], seller[es_acc_edge]).mean():.1%}")
    print(f"factoring previo: {prev[es_pyme].mean():.1%} de pymes")
    print(f"conversión leads={convierte[lead_c].mean():.1%}  no leads={convierte[cli_corte & ~flag_lead].mean():.1%}")
    for f in sorted(os.listdir(out)):
        print(f"  {f:32s} {os.path.getsize(f'{out}/{f}') / 1e6:8.2f} MB")
    print(f"listo en {time.time() - t0:.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-empresas", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/sample")
    ap.add_argument("--b0", type=float, default=-4.0, help="intercepto del logit de conversión")
    a = ap.parse_args()
    generar(a.n_empresas, a.seed, a.out, a.b0)
