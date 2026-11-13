"""Lee dataset.json y expone los parametros del pipeline. Para cambiar de datos se edita dataset.json, no este archivo."""
import calendar
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVO_DATASET = RAIZ / "dataset.json"
CACHE = RAIZ / "pipeline" / "_cache"       # intermedios (parquet); se puede borrar
INPUTS_DIR = RAIZ / "dashboard" / "inputs" # lo que lee el dashboard

_d = json.loads(ARCHIVO_DATASET.read_text(encoding="utf-8"))


def _ruta(valor):
    p = Path(valor)
    return p if p.is_absolute() else RAIZ / p


NOMBRE_DATASET = _d["nombre"]
DATA_DIR = _ruta(_d["carpeta_datos"])
MODELO_DIR = _ruta(_d["carpeta_modelo"])
PREDICCIONES_ML = [_ruta(v) for v in _d.get("predicciones_ml", [])]   # CSV de ML por grupo; ver unir_predicciones.py
ARCHIVOS = _d["archivos"]
COLUMNAS = _d.get("columnas", {})          # {base: {nombre_estandar: nombre_en_el_archivo}}

# Ventana temporal: features hasta CORTE; conversion real solo despues (backtest).
CORTE = _d["corte"]
_anio, _mes = divmod(CORTE, 100)
FECHA_CORTE = f"{_anio}-{_mes:02d}-{calendar.monthrange(_anio, _mes)[1]:02d}"
_serie = [_anio * 12 + _mes - 1 - i for i in range(11, -1, -1)]
PERIODOS_FEATURES = [m // 12 * 100 + m % 12 + 1 for m in _serie]   # 12 meses que terminan en CORTE
INICIO_VENTANA = PERIODOS_FEATURES[0]
TRIM_INICIAL = (PERIODOS_FEATURES[0], PERIODOS_FEATURES[2])        # miden el crecimiento de ventas
TRIM_FINAL = (PERIODOS_FEATURES[9], PERIODOS_FEATURES[11])

TC_USD = _d["tipo_cambio_usd"]
SEGMENTO_ACEPTANTE = _d["segmento_aceptante"]
SUPUESTOS = _d["supuestos"]                # valores iniciales de los controles del simulador
CAPACIDAD_MAX = _d["capacidad_max"]

# Filas que viajan al navegador (el resto solo existe agregado).
TOP_LISTA = {"A": 15000, "B": 15000, "C": 5000}
N_ANCLAS = 20
N_PROVEEDORES_ANCLA = 36


def ruta_base(base):
    return DATA_DIR / ARCHIVOS[base]


def _lector(ruta, opciones=""):
    r = ruta.as_posix().replace("'", "''")
    return f"read_parquet('{r}')" if ruta.suffix.lower() == ".parquet" else f"read_csv('{r}'{opciones})"


def columnas_archivo(base):
    """Columnas tal como vienen en el archivo, sin renombrar."""
    import duckdb
    return [c[0] for c in duckdb.sql(f"SELECT * FROM {_lector(ruta_base(base))} LIMIT 0").description]


def fuente(base):
    """Expresion SQL que lee una base con los nombres de columna estandar. Acepta .csv y .parquet."""
    ruta, mapa = ruta_base(base), COLUMNAS.get(base) or {}
    ciiu = mapa.get("ciiu", "ciiu")
    # ciiu parece numero en las primeras filas, pero debe leerse como texto.
    opciones = f", types={{'{ciiu}':'VARCHAR'}}" if base == "maestro" and ciiu in columnas_archivo(base) else ""
    lector = _lector(ruta, opciones)
    if not mapa:
        return lector
    renombres = ", ".join(f'"{origen}" AS {estandar}' for estandar, origen in mapa.items())
    return f"(SELECT * RENAME ({renombres}) FROM {lector})"
