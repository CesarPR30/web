# Guía para pasar a datos reales

Qué cambiar cuando lleguen las bases oficiales, el modelo y los supuestos de negocio. Las tres cosas pueden llegar por separado: aplica solo la sección que corresponda y termina siempre con [Regenerar y revisar](#4-regenerar-y-revisar).

Todo se configura en [dataset.json](dataset.json). El dashboard no se toca: se actualiza solo a partir de `dashboard/inputs/`.

## Qué hay que reemplazar

| Dato | Estado actual | Se reemplaza con |
|---|---|---|
| Bases (`data/full/`) | Datos elaborados del caso | Sección 1 |
| Probabilidad | Modelo de ML a 1 mes, no a 6 meses | Sección 2 |
| Monto | Estimado con el historial, no viene de ML | Sección 2 |
| Importancia de variables | Falta; tarjeta oculta | Sección 2 |
| Captación | ML no puntuó a los no clientes; grupo oculto | Sección 2 |
| Gini y curva de captura | Split `test` de ML, predicción de mayo contra junio de 2026 | Se recalculan con el modelo definitivo |
| Capacidad, costo de contacto, onboarding y umbral | Valores inventados | Sección 3 |
| Escenario "Hoy (al azar)" | Supone que el banco contacta leads sin priorizar | Sección 3 |
| Margen, base, leads, red e histórico | Se calculan de las bases | Se recalculan solos |

Lo conectado hoy está descrito en el [README](README.md#predicciones-actuales-del-equipo-de-ml). El monto es una estimación propia y la campaña cubre un mes: dilo si presentas esas cifras.

## 1. Bases oficiales

Copia los archivos en una carpeta y revisa estos puntos de `dataset.json`:

- [ ] **Carpeta:** `carpeta_datos`. Acepta una ruta relativa al proyecto o una ruta completa.
- [ ] **Nombres de archivo:** `archivos`. Pueden ser `.csv` o `.parquet`.
- [ ] **Corte:** `corte`, en formato `AAAAMM`. La ventana de 12 meses y los trimestres se calculan solos.
- [ ] **Tipo de cambio:** `tipo_cambio_usd`.
- [ ] **Aceptante:** `segmento_aceptante`. Hoy es toda empresa `Corporativa`.
- [ ] **Nombres de columna:** deben existir estas columnas.

| Base | Columnas que deben existir |
|---|---|
| Maestro | `id_empresa`, `rubro`, `segmento`, `ventas_anuales`, `antiguedad_anios`, `score_riesgo`, `rating`, `flag_lead`, `fecha_alta_cliente`, `departamento` |
| Transacciones | `id_pagador`, `id_receptor`, `periodo`, `monto`, `moneda`, `dias_credito` |
| Factoring | `id_cedente`, `fecha_operacion`, `monto_desembolsado`, `comision`, `moneda`, `tasa_anual`, `plazo_dias` |
| Perfil histórico | `id_empresa`, `periodo`, `ventas_mes`, `n_productos`, `uso_linea_credito`, `tiene_credito` |

Si una columna viene con otro nombre, indícalo en `columnas`. A la izquierda va el nombre de la tabla y a la derecha, el de tu archivo:

```json
"columnas": {
  "factoring": {"id_cedente": "ruc_vendedor"}
}
```

También hay que confirmar:

- [ ] **Formatos:** `periodo` como entero `AAAAMM`, `fecha_operacion` como fecha, `flag_lead` como 0/1 y `moneda` con el código `USD`. `actualizar.py` revisa estos formatos, salvo el `periodo` de transacciones.
- [ ] **Segmentos de pyme:** [03_build_inputs.py:200](pipeline/03_build_inputs.py#L200). Un valor distinto de `Micro`, `Pequeña` o `Mediana` aparece como `Sin dato`.
- [ ] **Operaciones posteriores al corte:** sin ellas no hay Gini, R² ni curva de captura, y el dashboard oculta esa tarjeta.

Si el tamaño de la base cambia mucho, ajusta `TOP_LISTA` en [config.py:41](pipeline/config.py#L41). Un valor mayor agrega empresas a la lista, pero hace más pesado el archivo que carga el navegador.

## 2. Modelo real

- [ ] El modelo escribe estos 3 archivos en la carpeta `carpeta_modelo` de `dataset.json`. El detalle de cada columna está en el [README](README.md#conectar-el-modelo-real).

| Archivo | Contenido |
|---|---|
| `predicciones.csv` | `id_empresa`, `p_conversion`, `monto_esperado` |
| `importancia_variables.csv` | `variable`, `etiqueta`, `importancia`, `direccion` |
| `metadata.json` | `tipo`, `nombre`, `version`, `fecha` |

- [ ] `metadata.json` lleva `tipo` distinto de `simulado`, por ejemplo `"modelo"`. Así aparece el nombre del modelo en la cabecera, y `--simular` no puede sobrescribir esa carpeta.
- [ ] `monto_esperado` es el monto si convierte. No debe venir multiplicado por la probabilidad.
- [ ] Las predicciones incluyen solo candidatas: sin corporativas ni aceptantes.
- [ ] **El backtest es fuera de muestra.** El dashboard compara las predicciones con lo ocurrido después del corte. Si esas mismas operaciones entrenaron el modelo, el Gini y el R² saldrán inflados. Usa predicciones de validación para esas empresas.
- [ ] `importancia_variables.csv` conserva los nombres `pct_ventas_aceptantes`, `factoring_previo`, `crecimiento_ventas` y `uso_linea_credito` cuando esas variables existan. Las demás se muestran en el gráfico, pero no entran en la comparación del perfil ([app.js:396](dashboard/assets/app.js#L396)).
- [ ] No uses `--simular` con el modelo real.

Si solo cambió el modelo, `actualizar.py` reutiliza las features y termina en segundos.

## 3. Supuestos de negocio

Pide estos valores al equipo de negocio y cámbialos en `supuestos`, en `dataset.json`:

- [ ] `capacidad_contactos`: contactos por campaña.
- [ ] `costo_contacto`: soles por empresa contactada.
- [ ] `costo_onboarding`: soles adicionales por cliente nuevo.
- [ ] `umbral_habilitacion`: probabilidad mínima para habilitar una empresa sin lead.

También hay que confirmar:

- [ ] **Escenario "Hoy":** si el banco ya prioriza sus leads, ajusta `escenarioHoy()` en [app.js:111](dashboard/assets/app.js#L111). De esto depende el múltiplo de valor frente a hoy.
- [ ] **Rangos de los controles:** están en [app.js:538](dashboard/assets/app.js#L538). Amplíalos si un valor real queda fuera, por ejemplo un margen sobre 4%. La capacidad máxima es `capacidad_max`, en `dataset.json`.
- [ ] **Umbral:** si cambias su rango o paso, cambia lo mismo en `EDGES_P`, en [03_build_inputs.py:89](pipeline/03_build_inputs.py#L89). Si no coinciden, el simulador y la lista dejan de cuadrar.

## 4. Regenerar y revisar

Haz doble clic en `ACTUALIZAR.bat`, o ejecuta:

```
python actualizar.py
```

El comando revisa las bases, salta el cálculo de features si no cambiaron y escribe los datos del dashboard. Si algo falla, dice qué corregir y no cambia el dashboard. Las opciones están al inicio de [actualizar.py](actualizar.py).

Abre `dashboard/index.html` y revisa:

- [ ] La cabecera muestra el corte correcto y el nombre del modelo.
- [ ] El panel de ajustes muestra el dataset y la fecha de actualización correctos.
- [ ] El embudo del Resumen cuadra con los conteos conocidos de la base.
- [ ] El margen histórico es razonable para el negocio. Hoy es 2.2%.
- [ ] Las probabilidades tienen sentido frente a la conversión real. Hoy el umbral de 3.5% se fijó para datos con cerca de 3% de conversión; con otra tasa hay que revisarlo.
- [ ] El Gini y la curva de captura son creíbles. Un Gini muy alto suele indicar fuga de información.
- [ ] El simulador y la lista dan el mismo resultado con los valores iniciales.
- [ ] La tabla y el CSV de la lista traen las mismas empresas.

## 5. Antes de presentar

- [ ] Toda la tabla inicial quedó reemplazada, o sabes qué cifra sigue siendo un supuesto y puedes decirlo.
- [ ] Regeneraste el video con los pasos de [video/README.md](video/README.md#regenerar-con-el-modelo-real). Conserva el aviso de la pista V2 hasta tener el modelo real.
- [ ] Actualizaste las cifras citadas en la presentación o en el guion.
- [ ] Revisaste en la computadora de la presentación que las pestañas y secciones sean las correctas. Ver [Ajustes del dashboard](README.md#ajustes-del-dashboard).
