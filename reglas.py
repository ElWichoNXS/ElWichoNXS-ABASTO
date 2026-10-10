"""Reglas de cálculo que se muestran en la app (cada bloque se puede minimizar por separado)."""
import streamlit as st


def mostrar_reglas(p):
    with st.expander("Contexto · TDF vs Min/Max", expanded=True):
        st.markdown("""
Toda la data del BI está en método **TDF (TIA Demand Forecast)**: el abastecimiento se calcula con el **forecast / pronóstico**.

Al configurar un producto en un local con **Min y Max**, se cambia el método de abastecimiento: el sistema deja de
mirar el forecast y repone con los **mínimos y máximos configurados por local y por estadístico**.

Este programa hace dos cosas: (1) decide **qué productos conviene pasar de TDF a Min/Max** y (2) **calcula su Min y Max**.
Como la data viene en TDF, los Min/Max que traiga el BI no se usan (no aplican en ese método), y tampoco los
*Días SS* (stock de seguridad de TDF).
""")

    with st.expander("Paso 1 · Qué productos pasan de TDF a Min/Max", expanded=True):
        st.markdown(f"""
El cálculo es por cada combinación **Local × Estadístico**. El producto **pasa de TDF a Min/Max** si cumple **una** de estas dos
vías; si no cumple ninguna, **se queda en TDF** y no aparece en el archivo:

**Vía A · siempre pasa (el pronóstico está mal):**
1. **Pronóstico cero o sin pronóstico:** la suma de los días de pronóstico es 0.
2. **Pronóstico lineal:** el modelo aún no aprendió y repite valores. De los **12 días** de pronóstico, hay **{p.umbral_unicos} o menos valores únicos** (`UNICOS ≤ {p.umbral_unicos}`, es decir, menos de {p.umbral_unicos + 1}); un valor único es el que aparece una sola vez.
   Por eso se revisa con 12 días de venta pronosticada. **Excepción:** si el modelo solo **copió la semana** (los días 8 a 12 son iguales a los días 1 a 5; columna `SEMANA COPIADA = Sí`), se juzga únicamente la **primera semana**: es lineal si tiene
   al menos un valor repetido y los valores únicos **no superan** a los repetidos (`VALORES UNICOS SEM1 ≤ VALORES REPETIDOS SEM1`; con empate, por ejemplo 2 únicos y 2 repetidos, también es lineal). Ejemplos de primera semana: `5,5,5,5,5,5,5` (0 únicos, 1 repetido) → lineal; `3,3,4,4,5,5,6` (1 único, 3 repetidos) → lineal;
   `2,2,3,4,5,6,6` (3 únicos, 2 repetidos) → no lineal; `4.1,3.2,3.4,1.9,4.5,4.4,3.6` (7 únicos) → no lineal.

**Vía B · pasa solo si se cumplen las reglas 3 y 4 JUNTAS (el pronóstico es muy bajo):**

3. **Promedio del pronóstico < {p.factor_prom_exhi:.0%} de la exhibición:** `promedio diario del pronóstico < {p.factor_prom_exhi:.0%} × Exhi`.
4. **El forecast no cubre ni la mitad del empaque final:** `promedio diario × (FREC + Dias SS) < {p.pct_empaque_cobertura:.0%} × Empq_final`.

Si cumple la regla 3 pero el forecast **sí** cubre la mitad del empaque final (regla 4 no se cumple), **se queda en TDF**.
Si el promedio × (FREC + Dias SS) llega al {p.pct_empaque_cobertura:.0%} del empaque final o más, TDF puede despachar con ese forecast.

- **Promedio diario** = suma del pronóstico de todos los días que trae el BI (**TOTAL PRONOSTICO**, normalmente 12 días) ÷ N° de días de pronóstico (**PROMEDIO PRONOSTICO DIA**; si el BI trae menos de 12 días, se divide para esos días).
- **FREC** = días entre despachos del local (**FREC ENTRE DESP**{", o el mayor intervalo real entre despachos" if p.usar_frec_efectiva else ""}).
- **Dias SS** = días de stock de seguridad de TDF. Se usan **solo para decidir el cambio de método**; no intervienen en el cálculo del Min ni del Max.
- **Empq_final** = empaque con el que realmente se despacha (el SUBEMPAQUE si existe; si no, el EMPAQUE).

**Importante:** las reglas 1 y 2 aplican **aunque el producto tenga subempaque / Empq_final = 1** y sin importar la cobertura del empaque. Con empaque 1, TDF puede
completar la necesidad de a una unidad y siempre cubre la exhibición, pero si el forecast es cero o es lineal el pronóstico
está mal, y TDF trabajaría con un dato incorrecto; por eso pasa a Min/Max.

Las columnas `TOTAL PRONOSTICO`, `PROMEDIO PRONOSTICO DIA`, `UNICOS`, `VALORES UNICOS SEM1`, `VALORES REPETIDOS SEM1`, `SEMANA COPIADA`, `% PROM/EXHI`, `COBERTURA TDF`, `% COBERTURA/EMPQ` y `MOTIVO MIN/MAX` del Excel muestran, fila por fila, por qué pasó a Min/Max.

**Consumo diario.** El BI entrega el consumo acumulado del mes; se divide para los días transcurridos:

`CONSUMO DIA = CONSUMOS ACU ÷ {p.dias_transcurridos} días transcurridos`

**APTO.** Se toma del maestro de productos (columna *Apto para PTL*). Si no cargas el maestro,
se asume "Si" para todos y la regla B del Min puede aplicarse a más productos de los debidos.
""")

    with st.expander("Paso 2 · Regla del MIN (se evalúa en este orden)", expanded=True):
        st.markdown(f"""
Todos los valores se redondean al **entero más cercano** (mitad hacia arriba, como el `REDONDEAR` de Excel).

| Regla | Condición | Min |
|---|---|---|
| **A** | El consumo diario es **mayor que la exhibición** (`CONSUMO DIA > Exhi`) | `REDONDEAR(CONSUMO DIA × FREC)` |
| **B** | No aplica A, y además: el producto es **apto**, la exhibición cubre **menos de {p.umbral_dg_exhi:g} días** (`Exhi ÷ CONSUMO DIA`) y `CONSUMO DIA × FREC > Exhi` | `REDONDEAR(CONSUMO DIA × FREC)` |
| **C** | Cualquier otro caso (la gran mayoría) | `Min = Exhi` (la exhibición) |

**Idea de fondo:** el Min nunca puede ser menor que la exhibición. Solo sube cuando la venta diaria es
tan alta que la exhibición no alcanza a cubrir los días hasta el próximo despacho.
""")

    with st.expander("Paso 3 · Regla del MAX", expanded=True):
        extra_txt = (f"\n\n**Cobertura adicional activa:** el incremento sube hasta cubrir **{p.dias_cobertura_max:g} días** "
                     "de consumo, en múltiplos del incremento mínimo de despacho." if p.dias_cobertura_max > 0 else
                     "\n\nLa cobertura adicional está **desactivada** (el Max solo suma el incremento mínimo de despacho).")
        st.markdown(f"""
El Max es el Min más un **incremento mínimo de despacho**:

| Situación del producto en el BI | Max |
|---|---|
| Tiene **SUBEMPAQUE** (> 0) | `Min + SUBEMPAQUE` |
| **No** tiene subempaque | `Min + REDONDEAR(EMPAQUE ÷ 2)` |

**Por qué EMPAQUE ÷ 2:** el sistema no despacha cuando la cantidad a reponer es menor a la mitad del empaque.
Por eso el Max debe estar al menos media caja por encima del Min.

El programa **siempre respeta el SUBEMPAQUE real del BI**: nunca asume un subempaque que el sistema no tiene.
Las propuestas para subempacar van aparte, en la hoja *SUGERIR SUBEMPAQUE* (es un cambio de maestro, no se aplica al Max).{extra_txt}
""")

    with st.expander("Reglas de sugerencia de SUBEMPAQUE", expanded=True):
        st.markdown(f"""
**Objetivo:** proponer subempacar **solo** los productos donde enviar el empaque completo generaría **sobrestock**
(o stock de más con un valor alto). Un producto sin subempaque en un local aparece en la hoja **SUGERIR SUBEMPAQUE** solo si cumple **todo** lo siguiente:

1. **Es apto para subempaque:**
   - **Nunca** es de las familias: **{", ".join(p.familias_no_subempacar) or "(ninguna)"}**, ni es un ESTADISTICO excluido manualmente
     ({", ".join(map(str, p.skus_no_subempacar)) if p.skus_no_subempacar else "ninguno"}).
   - {"Es **apto**: en el maestro de productos su columna **Apto para PTL = Si**." if p.exigir_apto_subempaque else "No se valida la aptitud del maestro de productos (opción desactivada)."}
   - Tiene EMPAQUE ≥ **{p.min_empaque_sugerir_sub}** unidades (con empaques pequeños subempacar no aporta).
2. **El mismo SKU ya está subempacado** en al menos **{p.min_locales_con_sub}** local(es) del BI (o está en la lista manual);
   el valor más común en esos locales es el subempaque sugerido.
3. **Hay riesgo de sobrestock**, es decir, cumple **al menos una**:
   - **Empaque completo = sobrestock:** el local tarda más de **{p.sub_dias_venta_empaque:g} días** en vender un empaque
     (`EMPAQUE ÷ CONSUMO DIA`), o el producto **no tuvo consumo** en el mes (un empaque completo quedaría parado).
   - **PVP alto:** PVP ≥ **{p.pvp_alto:g}**. {"Es un filtro **obligatorio**: un producto con PVP menor a ese valor nunca se sugiere, aunque tenga sobrestock. Los de PVP alto se revisan aunque el empaque se venda rápido." if p.exigir_pvp_alto else "Es un criterio adicional: se revisa aunque el empaque se venda rápido, para no enviar stock de más con un valor alto."}

**Prioridad:** ALTA si cumple las dos (sobrestock y PVP alto); MEDIA si cumple solo una. La hoja ordena por el valor que se evitaría
inmovilizar y muestra, para cada caso, los días que tardaría en venderse el empaque contra el subempaque, y cuánto bajaría el Max.
""")

    with st.expander("Hojas del Excel que se descarga", expanded=True):
        st.markdown(f"""
- **Pronóstico cero:** los productos que pasan a Min/Max, con Min y Max listos para cargar. Las filas que además están en REVISAR se marcan con la columna `EN REVISAR` (`Sí` = prioridad ALTA/MEDIA, `Informativo`, `No`; pintada según la prioridad) para poder filtrarlas; el detalle está en la hoja REVISAR. Incluye columnas de control
  (`DIF`, `%`, `DG MIN`, `DGMAX`, `CON>EXHI`, `DG EXHI = DG MIN`, `% PROM/EXHI`, `COBERTURA TDF`, `% COBERTURA/EMPQ`, `% CONSUMO/EMPQ`).
- **REVISAR:** **solo casos extremos**; el resto de avisos operativos no se lista.
  - *Prioridad ALTA:* **Inventario Físico Negativo** (`INV NETO < 0`) y **Consumo diario triplica la Exhibición** (`CONSUMO DIA ≥ {p.factor_consumo_exhi:g} × Exhi`).
  - *Prioridad MEDIA:* **Sobre stock: Cobertura > {p.sobrestock_dias:g} días** (`Max ÷ CONSUMO DIA`), excepto lo que se explica por la exhibición (ver Informativo).
  - *Informativo:* **Sobrestock por cubrir exhibición**. La exhibición la define el área comercial y siempre se abastece, así que solo se deja mapeado: el exceso de stock se debe a llenar la exhibición (la Exhi sola cubre más de {p.sobrestock_dias:g} días, o cubre al menos el {p.pct_exhi_en_cobertura:.0%} de los días del Max). Se separa en dos: **consumo ≤ {p.consumo_bajo_exhi:g} u/día** y **consumo > {p.consumo_bajo_exhi:g} u/día**.
  - Los productos sin consumo no se revisan: solo se mantiene la exhibición (Min = Exhi).
  - **Cada caso trae una ACCIÓN PRINCIPAL y una SUGERENCIA A REALIZAR.** Orden de soluciones: (1) corregir el dato (inventario negativo, consumo atípico); (2) **subempacar**, si es viable
    (apto, no es de una familia excluida, empaque ≥ {p.min_empaque_sugerir_sub} y el SKU ya está subempacado en ≥ {p.min_locales_con_sub} locales) y reduce el Max, mostrando el subempaque y el Max resultante;
    (3) si no hay solución operativa, el caso queda **mapeado** (no se propone mover exhibiciones ni retirar productos, porque no depende de abastecimiento); (4) informativo. La columna *VIABILIDAD SUBEMPAQUE* explica por qué sí o no, y *ALERTA PVP* avisa cuando el subempaque recomendado es de un producto con PVP menor al mínimo configurado (por eso no aparece en SUGERIR SUBEMPAQUE).
- **SUGERIR SUBEMPAQUE:** propuestas de cambio de maestro para evitar sobrestock (ver reglas arriba).
- **Resumen:** indicadores del proceso y esta misma leyenda de reglas.
""")
