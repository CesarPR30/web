# Dashboard de campaña de factoring

Herramienta para que negocio decida a qué empresas contactar. Para pasar a las bases, el modelo y los supuestos oficiales, seguir [GUIA_DATOS_REALES.md](GUIA_DATOS_REALES.md).

**Para verlo:** abrir `dashboard/index.html` con doble clic. No necesita servidor ni internet.

## Usar en otra computadora

```
git clone https://github.com/CesarPR30/web.git
cd web
pip install -r requirements.txt
```

El dashboard abre de inmediato con los datos ya generados. El repositorio no incluye:

- Las bases completas, porque GitHub no acepta archivos de más de 100 MB. Cópialas en `data/full/` o indica otra carpeta en `dataset.json`.
- Las predicciones del equipo de ML (`modelo/predicciones_grupo*.csv`). Cópialas en `modelo/` o cambia `predicciones_ml` en `dataset.json`.
- El video y el PDF del caso.

Para probar sin bases ni modelo, usa la muestra incluida en `data/sample/`:

```
python actualizar.py --data data/sample --corte 202512 --simular
```

Antes, en `dataset.json`, borra `predicciones_ml` y usa `"carpeta_modelo": "modelo"`.

**Publicarlo en la web:** en GitHub, *Settings > Pages*, elige la rama `main` y la carpeta `/ (root)`. El dashboard queda en `https://cesarpr30.github.io/web/`. El repositorio es público: cualquiera con el enlace verá las cifras.

## Cómo está armado

```
dataset.json: carpetas, archivos, columnas, corte y supuestos

data/full/*.csv
    └─ pipeline/01_features.py ────────► pipeline/_cache/ (features al corte)
                                              │
pipeline/02_predicciones_simuladas.py ──►  modelo/      ◄── AQUÍ ENTRA EL MODELO REAL
                                              │
       pipeline/03_build_inputs.py ◄──────────┘
                    │
                    ▼
          dashboard/inputs/*.js ──► dashboard/index.html
```

## Cambiar de datos

Edita [dataset.json](dataset.json) y haz doble clic en `ACTUALIZAR.bat`. Requiere `duckdb`, `polars`, `numpy` y `scipy`.

También se puede indicar la carpeta desde la terminal. Estos valores quedan guardados en `dataset.json`:

```
python actualizar.py --data D:/bases_v2 --modelo D:/modelo_v2 --corte 202603
```

| Opción | Para qué sirve |
|---|---|
| `--simular` | Genera predicciones simuladas para probar un dataset sin modelo. Se niega a sobrescribir un modelo real. |
| `--revisar` | Solo revisa las bases, sin cambiar el dashboard. |
| `--forzar` | Recalcula aunque las bases no hayan cambiado. |

Si las bases no cambiaron, se reutilizan las features. Con los 3 GB de `data/full`, la actualización completa tarda unos 10 s.

Si la revisión encuentra un problema, indica qué corregir y no toca el dashboard. Si las bases cambiaron y las predicciones son simuladas, pide `--simular` para no mezclar datos de dos fuentes.

## Predicciones actuales del equipo de ML

`dataset.json` usa hoy `modelo/predicciones_grupo1.csv`, `2` y `3`. [unir_predicciones.py](pipeline/unir_predicciones.py) los une en `modelo_ml/` en cada actualización. Si ML entrega versiones nuevas con el mismo formato, basta reemplazarlas y ejecutar `ACTUALIZAR.bat`.

| Tema | Qué hace hoy |
|---|---|
| Corte | Junio de 2026, porque es el periodo del `forecast`. |
| Probabilidad | `prob_calibrada`: operar el **mes siguiente**, no en 6 meses. |
| Monto | **Estimado, no viene de ML.** Con historial, desembolso medio por mes activo. Sin historial, ventas mensuales a aceptantes por la proporción observada en usuarios. |
| Captación | No aparece: ML no puntuó a los no clientes. |
| Importancia de variables | Tarjeta oculta hasta que ML entregue `modelo_ml/importancia_variables.csv`. |
| Confiabilidad | Sale del split `test`: predicción de mayo contra lo ocurrido en junio. El Gini se muestra por separado porque el combinado está inflado. |

Para volver a las predicciones simuladas, en `dataset.json` borra `predicciones_ml`, usa `"carpeta_modelo": "modelo"` y `"corte": 202512`, y ejecuta `python actualizar.py --simular`.

## Ajustes del dashboard

El botón de engranaje, arriba a la derecha, abre el panel de ajustes. Permite:

- Ocultar pestañas y secciones. Las cabeceras y los números se reordenan solos, y el espacio libre se reparte entre las tarjetas visibles.
- Cambiar el título, el pie de página y los nombres de las pestañas.
- Ver qué dataset y qué modelo están cargados.

Los cambios se guardan en el navegador. Para llevarlos a otra computadora, usa **Descargar ajustes.js** y reemplaza `dashboard/inputs/ajustes.js`. `actualizar.py` no modifica ese archivo.

Las vistas nuevas se registran en `SECCIONES`, en [app.js](dashboard/assets/app.js).

## Conectar el modelo real

1. Hacer que el modelo escriba estos 3 archivos en la carpeta `carpeta_modelo` de `dataset.json`.
2. Ejecutar `ACTUALIZAR.bat`. No hay que tocar el dashboard.

### `predicciones.csv`

| Columna | Tipo | Significado |
|---|---|---|
| `id_empresa` | texto | Una fila por empresa. Debe existir en las bases. |
| `p_conversion` | 0 a 1 | Probabilidad de hacer factoring en los 6 meses siguientes si se la contacta. |
| `monto_esperado` | soles | Desembolso en esos 6 meses **si convierte**. No multiplicar por la probabilidad. |

Incluir solo empresas candidatas a campaña: pymes clientes y no clientes con ventas a aceptantes. Las corporativas no van, porque actúan como aceptantes.

### `importancia_variables.csv`

| Columna | Significado |
|---|---|
| `variable` | Nombre técnico. |
| `etiqueta` | Texto que verá negocio. |
| `importancia` | Peso; idealmente suma 1. Por ejemplo, SHAP medio absoluto normalizado. |
| `direccion` | `+` o `-`. |

La frase para el jurado usa estos cuatro nombres de `variable` si están presentes: `pct_ventas_aceptantes`, `factoring_previo`, `crecimiento_ventas`, `uso_linea_credito`.

### `metadata.json`

```json
{"tipo": "modelo", "nombre": "LightGBM", "version": "v1", "fecha": "2026-11-13"}
```

Con `tipo` distinto de `simulado`, la cabecera muestra el nombre y la versión del modelo.

Si un archivo no cumple el contrato, la actualización se detiene y dice qué falló: columnas faltantes, IDs repetidos o inexistentes, nulos, probabilidades fuera de rango o montos negativos.

## Reglas de cálculo

- Grupos: **A** Lead actual · **B** Habilitable (pyme sin lead, con ventas a aceptantes y P ≥ umbral) · **C** Captación (no cliente, misma condición).
- Valor esperado = P × monto × margen − costo de contacto (más onboarding en C).
- Se contacta por valor esperado descendente hasta agotar la capacidad o hasta que deja de ser rentable.
- El simulador recorre toda la base mediante cubetas agregadas (`simulador.js`). La lista lleva las 35,000 empresas de mayor valor (`TOP_LISTA`). Ambos coinciden con diferencias menores a 0.1%, salvo con umbrales altos o "Solo nuevos": ahí la lista puede quedarse sin filas y conviene subir `TOP_LISTA`.
