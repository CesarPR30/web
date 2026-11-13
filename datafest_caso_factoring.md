# Datafest 2026 — Caso Factoring (resumen de trabajo)

> Nota: los datos del caso son elaborados para fines del concurso. Columnas y muestras de este documento son **supuestos** a validar con la data real.

---

## 1. El problema

**Negocio:** el banco tiene **capacidad comercial limitada** y debe decidir **a qué empresas Pyme contactar en la próxima campaña de factoring**, maximizando el valor obtenido.

**Etapas del reto:**
1. **Habilitar** — ampliar la base de empresas con potencial de factoring.
2. **Valorar** — estimar probabilidad de conversión y valor esperado.
3. **Priorizar** — elegir a quién contactar según la capacidad comercial.

**Dos formas de crecer:**
- **A · Convertir más:** mejorar la conversión dentro del ~10% de clientes Pyme que hoy tienen lead.
- **B · Habilitar más:** ampliar la base con lead (ej. de 10% a 20%).

**Cada equipo define:** su propio criterio de "cliente más valioso" y lo sustenta.
**Restricción clave:** capacidad limitada de la fuerza comercial.

**Base lead:** empresas ya marcadas como prospectos aptos para ofrecer factoring (~10% de Pyme). *Pendiente confirmar en qué tabla viene el flag (probable: Maestro o Perfil Histórico).*

**Como problema de datos:**
| Parte | Tipo | Target |
|---|---|---|
| P(convierte) | Clasificación | Hizo factoring en la ventana post-corte (Tabla 3) |
| Valor si convierte | Regresión | `monto_desembolsado` (Tabla 3) |
| A quién contactar | Optimización (knapsack) | Max Σ VE sujeto a N contactos |

`VE = P(conversión) × monto esperado × margen − costo de contacto`

**Evaluación:** Fase 1 técnica — bondad de ajuste 50%, calidad/factibilidad de propuestas 25%. Fase 2 — presentación ante jurado 25%.

---

## 2. Las 4 tablas

| Tabla | Qué es | Grano | Cobertura | Rol |
|---|---|---|---|---|
| **1 · Maestro de Empresas** | Ficha: rubro, tamaño, ubicación | 1 fila por empresa | Clientes del banco | Segmentar, filtrar universo, (¿flag lead?) |
| **2 · Transacciones** | Quién paga a quién y cuánto | Transacción o par × periodo | Clientes **y no clientes** | Red comercial: potencial, look-alike, captación |
| **3 · Operaciones de Factoring** | Adelantos de facturas | 1 fila por operación | Solo quienes usaron factoring | **Target** + mapa de aceptantes |
| **4 · Perfil Histórico** | Ventas y productos mes a mes | Empresa × mes | Clientes del banco | Señales de necesidad y tendencia |

### Columnas probables

**1 · Maestro de Empresas**
- `id_empresa` (llave)
- `rubro`, `ciiu`, `sector`
- `segmento` (micro / pequeña / mediana / corporativa)
- `tamaño` (`ventas_anuales`, `num_empleados`)
- `departamento`, `provincia`, `distrito`
- `fecha_inicio_actividades` / `antiguedad`
- `es_cliente_banco`, `fecha_alta_cliente`
- `rating` / `score_riesgo`
- `flag_lead` (supuesto)

**2 · Transacciones**
- `id_transaccion`
- `id_pagador`, `id_receptor`
- `monto`, `moneda`
- `fecha` / `periodo`
- `num_transacciones` (si viene agregada)
- `canal`
- `plazo_pago` / `dias_credito` (si existe)

**3 · Operaciones de Factoring**
- `id_operacion`
- `id_cedente` (empresa que adelanta)
- `id_aceptante` (quien paga la factura)
- `monto_desembolsado`, `monto_factura`
- `fecha_operacion`, `fecha_vencimiento` → `plazo`
- `tasa` / `comision`, `moneda`
- `estado`, `dias_atraso`
- `tipo` (factoring / confirming / descuento)

**4 · Perfil Histórico**
- `id_empresa`, `periodo` (YYYYMM)
- `ventas_mes`
- `n_productos`, `tiene_cuenta`, `tiene_credito`, `tiene_tarjeta`
- `saldo_promedio`, `saldo_deuda`
- `uso_linea_credito`
- `usa_factoring` (posible target)

### Diferencias clave

**Tabla 2 vs 3**
- 2 = el **comercio** entre empresas. 3 = el **financiamiento** de una parte de ese comercio con el banco.
- Cada factoring de la 3 debería tener su relación en la 2 (aceptante → cedente).
- Relaciones de la 2 **sin** factoring en la 3 = oportunidades no explotadas.

**Tabla 3 vs 4**
- 3 = lista de **eventos** de un solo producto (solo usuarios de factoring).
- 4 = **película mensual** de todas las empresas clientes.
- 3 aporta el target; 4 aporta el contexto previo para predecirlo.

### Cómo se cruzan
- **1 ↔ todas:** por `id_empresa`.
- **2 ↔ 3:** `id_aceptante` (3) aparece como `id_pagador` (2).
- **3 ↔ 4:** la 4 se corta **antes** de la fecha de la 3 (evitar leakage).

---

## 3. Enfoque por problema

### A · Convertir más (dentro del ~10% lead)
- **Universo:** empresas con flag lead.
- **Target:** Tabla 3 — hizo factoring en la ventana post-corte.
- **Features clave:**
  - Tabla 4: crecimiento de ventas, uso de líneas, productos
  - Tabla 3: historial previo (recurrencia, último monto)
  - Tabla 2: volumen pagado por aceptantes conocidos
- **Modelo:** propensión supervisada (LightGBM/XGBoost calibrado).
- **Salida:** ranking por VE, cortado por capacidad.
- **Riesgo:** leakage temporal.

### B · Habilitar más (~90% sin lead + no clientes)
- **Universo:** Pyme sin flag lead + no clientes que aparecen en Tabla 2.
- **Target:** no observado directamente → **look-alike** entrenado con usuarios de factoring.
- **Features clave:**
  - Tabla 2 (protagonista): ventas a aceptantes, concentración de cobros, volumen descontable, centralidad
  - Tabla 4: crecimiento, estacionalidad
  - Tabla 1: rubro y tamaño similares a usuarios
- **No clientes:** solo features de red; incluir costo de onboarding en su VE o listarlos aparte.
- **Riesgo:** sesgo de selección (nunca contactados).

### Features de red destacadas
- Grado de entrada/salida, PageRank
- Concentración de compradores (HHI)
- `% de ventas provenientes de aceptantes` (cruce 2 × 3)
- Valor de red: empresas ancla que arrastran a sus proveedores

### Estrategia de cadena
Cliente del banco que es aceptante y paga a proveedores no clientes → esos proveedores son leads ideales (relación existente, riesgo del pagador ya evaluado).

---

## 4. Reglas para data dummy

**Universo y proporciones**
- ~10k empresas: 80% clientes Pyme, 20% no clientes (solo en Tabla 2)
- Flag lead en ~10% de clientes
- ~300 aceptantes (empresas grandes / corporativas)
- 18 meses: corte en mes 12, target en meses 13–18

**Distribuciones**
- Ventas y montos: lognormal (cola larga)
- Tamaño correlacionado con ventas
- Rubro y ubicación desbalanceados (ej. comercio 40%, Lima 60%)
- Red con grado tipo ley de potencia (preferential attachment)
- Estacionalidad en Tabla 4 (picos dic/mar según rubro)

**Integridad**
- Todo `id_empresa` de 3 y 4 existe en 1
- Todo factoring en 3 tiene relación previa en 2 (aceptante → cedente)
- `monto_factoring ≤ volumen transado` con ese aceptante
- Tabla 4 solo clientes; Tabla 3 solo cedentes clientes
- Fechas coherentes (operación < vencimiento, nada antes del alta)

**Señal plantada**
```
logit(P) = −4 + 1.5·(% ventas a aceptantes) + 0.8·(crecimiento ventas)
           + 1.0·(factoring previo) + 0.5·lead + ruido
```
- Conversión: 5–15% en leads, 1–3% fuera
- Monto = fracción de ventas a aceptantes + ruido

**Anti-trampa**
- Features solo hasta el corte; target solo después
- 5–10% de nulos/ruido en rating, ubicación
- Casos borde: sin transacciones, conversores sin lead, no clientes con alto volumen

---

## 5. Muestras (ficticias, IDs consistentes)

**1 · Maestro de Empresas**
| id_empresa | rubro | segmento | departamento | antig_años | es_cliente | flag_lead |
|---|---|---|---|---|---|---|
| E001 | Comercio | Pequeña | Lima | 6 | 1 | 1 |
| E002 | Manufactura | Mediana | Arequipa | 12 | 1 | 0 |
| E003 | Servicios | Micro | Lima | 2 | 1 | 0 |
| E004 | Retail | Corporativa | Lima | 25 | 1 | 0 |
| E005 | Agro | Pequeña | Piura | 8 | 1 | 1 |

**2 · Transacciones** (E901 = no cliente)
| id_pagador | id_receptor | periodo | monto | n_trx | relación |
|---|---|---|---|---|---|
| E004 | E001 | 202509 | 85,000 | 4 | cliente→proveedor |
| E004 | E002 | 202509 | 210,000 | 6 | cliente→proveedor |
| E004 | E901 | 202509 | 120,000 | 3 | cliente→proveedor |
| E002 | E003 | 202509 | 12,500 | 2 | cliente→proveedor |
| E001 | E005 | 202510 | 30,000 | 1 | cliente→proveedor |

**3 · Operaciones de Factoring**
| id_operacion | id_cedente | id_aceptante | fecha_op | monto_desemb | plazo_días | estado |
|---|---|---|---|---|---|---|
| F1001 | E002 | E004 | 2025-10-03 | 180,000 | 60 | pagada |
| F1002 | E002 | E004 | 2025-12-05 | 195,000 | 60 | pagada |
| F1003 | E001 | E004 | 2026-01-15 | 70,000 | 45 | vigente |

**4 · Perfil Histórico**
| id_empresa | periodo | ventas_mes | n_productos | tiene_credito | usa_factoring |
|---|---|---|---|---|---|
| E001 | 202510 | 95,000 | 2 | 1 | 0 |
| E001 | 202511 | 110,000 | 2 | 1 | 0 |
| E001 | 202512 | 140,000 | 3 | 1 | 0 |
| E002 | 202512 | 260,000 | 4 | 1 | 1 |
| E003 | 202512 | 14,000 | 1 | 0 | 0 |

**Lectura de los casos**
- **E002:** cliente recurrente de factoring con aceptante E004.
- **E001:** lead con ventas crecientes que convierte en enero (post-corte dic) → problema A.
- **E901:** no cliente que vende a un aceptante → lead de captación, problema B.
- **E005:** lead pequeño, poca red, sin conversión.
- **E004:** aceptante ancla de la red.

---

## 6. Preguntas pendientes para la organización
1. ¿Cuál es exactamente el target (usó sí/no, monto) y en qué ventana?
2. ¿Qué métrica de evaluación (AUC, F1, RMSE)?
3. ¿En qué tabla viene el flag de lead y con qué fecha de corte?
4. ¿Las empresas no clientes de la Tabla 2 son elegibles para la campaña?
5. ¿Cuál es la llave común y la granularidad de cada tabla?
