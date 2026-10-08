"""
app.py  -  Interfaz Streamlit para calcular Min/Max (Pronóstico cero)
Ejecutar:  streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st

from motor_minmax import (ColumnasPronosticoError, Params, exportar_excel, leer_aptos,
                          leer_bi, marcar_revision, procesar, sugerir_subempaque)

st.set_page_config(page_title="Min/Max · Pronóstico cero", layout="wide")
st.title("Min / Max por local · Pronóstico cero")
st.caption("Carga el Excel crudo del BI, ajusta los parámetros de la izquierda y descarga el archivo procesado.")

# ---------------- Parámetros (barra lateral) ----------------
with st.sidebar:
    st.header("Parámetros de negocio")
    st.caption("Pasa el mouse sobre el signo ❓ de cada parámetro para ver qué significa.")

    st.subheader("1. Consumo")
    p = Params(
        dias_transcurridos=st.number_input(
            "Días de consumo transcurridos", 1, 31, 5,
            help="Número de días del mes que han pasado. El BI entrega el consumo ACUMULADO del mes "
                 "(columna CONSUMOS ACU) y el programa lo divide para este número para obtener el "
                 "CONSUMO DIA. Ejemplo: si hoy es 7 de octubre y el BI llega hasta ayer, son 6 días. "
                 "Cámbialo cada vez que descargues el BI."),
    )

    st.subheader("2. Qué productos pasan de TDF a Min/Max")
    p.pct_empaque_min_max = st.number_input(
        "Pronóstico × frecuencia menor a (% del empaque final)", 0.05, 3.0, 0.5, step=0.05, format="%.2f",
        help="Pasa a Min/Max el producto cuyo (pronóstico promedio diario × FREC del local) sea MENOR a este "
             "porcentaje del empaque final (Empq_final). 0.50 = 50 %. Si el pronóstico por ciclo de despacho "
             "no llega ni a media caja, el forecast no justifica abastecer por TDF. Subir este valor "
             "hace que pasen más productos a Min/Max.")
    p.umbral_unicos = st.number_input(
        "Pronóstico repetido: UNICOS menor o igual a", 0, 12, 5,
        help="También pasa a Min/Max el producto con pronóstico REPETIDO. UNICOS = cuántos de los valores diarios "
             "del pronóstico aparecen una sola vez. Un número bajo significa que el forecast repite los "
             "mismos valores (la semana 2 copia a la semana 1), por lo que no es confiable para abastecer por TDF. "
             "Con 5, pasan los productos que tienen 5 o menos valores únicos.")

    st.subheader("3. Cálculo del Min")
    p.umbral_dg_exhi = st.number_input(
        "Exhibición cubre menos de (días)", 0.5, 10.0, 2.0,
        help="Regla B del Min. Si los días que cubre la exhibición (Exhi ÷ consumo diario) son menos que "
             "este valor, el Min sube a cubrir la frecuencia de despacho.")
    p.usar_frec_efectiva = st.checkbox(
        "Usar el mayor intervalo real entre despachos", False,
        help="Apagado (recomendado): se usa FREC ENTRE DESP tal como viene del BI (promedio de días entre "
             "despachos). Encendido: se usa el hueco MÁS LARGO entre despachos según los días "
             "LUNES…DOMINGO. Ejemplo: despacha Mar-Sáb-Dom; el BI dice 2 días, pero entre Mar y Sáb pasan 4. "
             "También afecta el filtro de la sección 2.")

    st.subheader("4. Cálculo del Max")
    p.dias_cobertura_max = st.number_input(
        "Cobertura adicional del Max (días)", 0.0, 60.0, 0.0, step=0.5,
        help="0 = desactivado (recomendado): Max = Min + SUBEMPAQUE, o Min + EMPAQUE÷2 si no tiene subempaque. "
             "Si pones un número N mayor que 0, el incremento sobre el Min sube hasta cubrir N días de "
             "consumo, en múltiplos del incremento mínimo de despacho.")

    st.subheader("5. Diagnóstico del pronóstico")
    p.umbral_venta_prom_dia = st.number_input(
        "Pronóstico insuficiente si promedio diario < (u/día)", 0.0, 10.0, 1.0,
        help="Solo informativo (columna DIAG PRONOSTICO). Si el pronóstico promedio por día "
             "(SUMA ÷ días de pronóstico) es menor a este valor, se marca como 'insuficiente'.")

    st.subheader("6. Hoja REVISAR · casos extremos")
    st.caption("La hoja REVISAR solo trae 3 casos: inventario negativo, consumo muy superior a la exhibición y sobre stock crítico.")
    p.sobrestock_dias = st.number_input(
        "Sobre stock crítico: cobertura del Max mayor a (días)", 1.0, 730.0, 120.0,
        help="Se envía a REVISAR si el Max cubre más de estos días de consumo (Max ÷ CONSUMO DIA). "
             "Si el producto no tiene consumo en el mes, no se marca.")
    p.consumo_bajo_exhi = st.number_input(
        "Sobrestock por exhibición: consumo diario menor a (u/día)", 0.05, 5.0, 0.5, step=0.05, format="%.2f",
        help="Si el consumo diario es menor a este valor y la sola exhibición ya cubre más días que el límite de sobre stock, "
             "el caso se muestra en REVISAR con la leyenda 'Sobrestock por exhibición' (prioridad BAJA, informativo).")
    p.pct_exhi_en_cobertura = st.number_input(
        "Sobre stock explicado por la Exhibición: Exhi cubre ≥ (% de los días del Max)", 0.1, 1.0, 0.8, step=0.05, format="%.2f",
        help="Si los días que cubre la exhibición (Exhi ÷ CONSUMO DIA) son al menos este porcentaje de los días que cubre el Max, "
             "el exceso de stock se debe a la exhibición del local y NO se envía a REVISAR. 0.80 = 80 %.")
    p.factor_consumo_exhi = st.number_input(
        "Incongruencia: consumo diario ≥ (veces la Exhibición)", 1.0, 20.0, 3.0, step=0.5,
        help="Se envía a REVISAR si el CONSUMO DIA es esta cantidad de veces la Exhi o más. Con 3, el consumo diario triplica la exhibición.")

    st.subheader("7. Sugerencias de subempaque")
    st.caption("Se sugiere subempacar solo si cumple AL MENOS UNO de los tres criterios.")
    p.pvp_alto = st.number_input(
        "Criterio 1 · PVP alto: precio de venta ≥", 0.0, 1000.0, 5.0, step=0.5,
        help="Un producto se considera de PVP alto si su precio de venta al público es mayor o igual a este valor. "
             "El valor por defecto (5.00) corresponde aproximadamente al 10 % de productos más caros del BI.")
    p.sub_consumo_bajo_dia = st.number_input(
        "Criterio 2 · Bajo consumo: consumo diario <", 0.0, 100.0, 1.0, step=0.25,
        help="Un producto es de bajo consumo si su CONSUMO DIA es menor a este número de unidades por día.")
    p.sub_pct_exhi_max = st.number_input(
        "Criterio 3 · Exhibición menor a (% del empaque)", 0.05, 3.0, 0.5, step=0.05, format="%.2f",
        help="% de exhibición = Exhi ÷ EMPAQUE. Si la exhibición es menor a este porcentaje del empaque "
             "(0.50 = 50 %), el producto es candidato a subempacar.")
    p.min_empaque_sugerir_sub = st.number_input(
        "Solo si EMPAQUE ≥ (unidades)", 1, 100, 6,
        help="Solo se sugiere subempacar productos cuyo empaque tenga al menos esta cantidad de unidades.")
    p.min_locales_con_sub = st.number_input(
        "El SKU debe estar subempacado en al menos N locales", 1, 50, 1,
        help="Se sugiere subempacar un producto en un local solo si el mismo SKU ya está subempacado "
             "en al menos N locales del BI. Esa evidencia define también el valor de subempaque sugerido.")
    fam = st.text_area(
        "Familias que NUNCA se subempacan (una por línea)", "\n".join(p.familias_no_subempacar),
        help="Productos de estas familias jamás aparecen en las sugerencias de subempaque. "
             "Por defecto: CERVEZAS, CERVEZAS SIN ALCOHOL y AGUAS.")
    p.familias_no_subempacar = tuple(x.strip().upper() for x in fam.splitlines() if x.strip())
    excl = st.text_area(
        "ESTADISTICOS que NO se deben subempacar (uno por línea)", "",
        help="Códigos de ESTADISTICO específicos que nunca se subempacan, aunque cumplan los criterios. "
             "Ejemplo: 243138001. Escribe un código por línea.")
    p.skus_no_subempacar = tuple(int(x) for x in excl.split() if x.strip().isdigit())
    extra = st.text_area(
        "SKUs subempacables aunque el BI no los muestre subempacados (uno por línea)", "",
        help="Códigos de ESTADISTICO que sabes que se pueden subempacar aunque en ningún local "
             "figuren con subempaque en el BI.")
    p.skus_sub_extra = tuple(int(x) for x in extra.split() if x.strip().isdigit())

# ---------------- Carga ----------------
c1, c2 = st.columns(2)
f_bi = c1.file_uploader("1) Excel del BI (obligatorio)", type=["xlsx"])
f_ap = c2.file_uploader("2) Maestro de productos (columnas 'Estadístico' y 'Apto para PTL')",
                        type=["xlsx"])

if f_bi:
    with st.spinner("Leyendo archivos…"):
        bi = leer_bi(f_bi)
        aptos = leer_aptos(f_ap) if f_ap else None

    try:
        with st.spinner("Procesando…"):
            salida, r = procesar(bi, aptos, p)
    except ColumnasPronosticoError as e:
        # No se reconocieron las columnas de pronóstico: se pide elegirlas a mano
        st.error(f"{e} Elige abajo las columnas del pronóstico diario.")
        st.markdown("**Columnas que trae tu archivo** (las del pronóstico diario son varias seguidas, una por día; normalmente 12):")
        todas = [c for c in e.todas]
        etiquetas = {c: str(c) for c in todas}
        elegidas = st.multiselect(
            "Selecciona las columnas de pronóstico diario (entre 7 y 12), en orden",
            options=todas, format_func=lambda c: etiquetas[c],
            help="Son las columnas con la venta pronosticada por día (una por cada uno de los próximos días).")
        if not (7 <= len(elegidas) <= 12):
            st.info(f"Seleccionadas: {len(elegidas)}. Elige entre 7 y 12 columnas.")
            st.stop()
        try:
            with st.spinner("Procesando…"):
                salida, r = procesar(bi, aptos, p, cols_pronostico=elegidas)
        except ValueError as e2:
            st.error(str(e2))
            st.stop()
    except ValueError as e:
        st.error(str(e))
        st.stop()

    if r["dias_de_pronostico"] < 12:
        st.info(f"El BI trae **{r['dias_de_pronostico']} días de pronóstico** (no 12). "
                f"El pronóstico promedio diario se calcula dividiendo para {r['dias_de_pronostico']}. "
                f"Columnas usadas: {r['columnas_pronostico_usadas']}.")
    if r["posible_truncado_bi"]:
        st.warning("El BI trae ~30.000 filas: la descarga puede estar truncada. "
                   "Verifica que no falten locales/SKUs.")
    if not f_ap:
        st.info("Sin lista de aptos: se asumió APTO = 'Si' para todos "
                "(afecta solo a la regla B de Min).")

    rev = marcar_revision(salida, p)
    sug = sugerir_subempaque(salida, p)
    r.pop("filas_con_aviso_revisar", None)       # métrica vieja (DG EXHI = DG MIN), ya no se usa
    r["sugerencias_subempaque"] = len(sug)
    r["filas_en_hoja_REVISAR"] = len(rev)
    r["revisar_prioridad_alta"] = int((rev["PRIORIDAD"] == "Prioridad ALTA").sum())

    k = st.columns(5)
    k[0].metric("Filas BI", f"{r['filas_bi']:,}")
    k[1].metric("Pasan a Min/Max", f"{r['filas_resultado']:,}")
    k[2].metric("Min = Exhi (regla C)", f"{r['regla_C']:,}")
    k[3].metric("Ajustadas (A + B)", f"{r['regla_A'] + r['regla_B']:,}")
    k[4].metric("Casos en hoja REVISAR", f"{len(rev):,}",
                f"{r['revisar_prioridad_alta']} de prioridad alta", delta_color="off")

    st.subheader("Segmentación del BI: qué se queda en TDF y qué pasa a Min/Max")
    seg = pd.DataFrame({
        "Segmento": ["Pasa a Min/Max · pronóstico cero o sin pronóstico",
                     "Pasa a Min/Max · pronóstico bajo",
                     "Pasa a Min/Max · pronóstico bajo y repetido",
                     "Pasa a Min/Max · solo pronóstico repetido",
                     "SE QUEDA EN TDF (ninguna condición)", "Total BI"],
        "Filas": [r["segmento_1_pasa_pronostico_cero"], r["segmento_2_pasa_pronostico_bajo"],
                  r["segmento_3_pasa_pronostico_bajo_y_repetido"], r["segmento_4_pasa_solo_pronostico_repetido"],
                  r["segmento_5_queda_en_TDF"], r["segmento_total_BI"]]})
    seg["% del BI"] = (seg["Filas"] / r["segmento_total_BI"]).map("{:.1%}".format)
    st.dataframe(seg, hide_index=True, use_container_width=True)

    k2 = st.columns(4)
    k2[0].metric("Frec. efectiva > BI", f"{r['frec_efectiva_mayor_que_bi']:,}")
    k2[1].metric("Pronóstico insuficiente", f"{r['pronostico_insuficiente']:,}")
    k2[2].metric("Pronóstico repetido", f"{r['pronostico_valores_repetidos']:,}")
    k2[3].metric("Pronóstico ciclo > Exhi", f"{r['pronostico_ciclo_mayor_exhi']:,}")

    t1, t2, t3 = st.tabs(["Resultado (pasan a Min/Max)", "Casos a revisar", "Sugerir subempaque"])
    t1.dataframe(salida.head(500), use_container_width=True)
    t2.dataframe(rev, use_container_width=True)
    t3.caption("Productos sin subempaque con PVP alto, bajo consumo o exhibición < 50 % del empaque, cuyo mismo SKU ya está subempacado en otros locales. "
               "Es una propuesta de cambio de maestro: el Max de la hoja principal usa el SUBEMPAQUE actual del BI.")
    t3.dataframe(sug, use_container_width=True)

    buf = io.BytesIO()
    exportar_excel(salida, rev, r, buf, sug)
    st.download_button("⬇️ Descargar Excel procesado", buf.getvalue(),
                       file_name="Pronostico_cero_procesado.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ======================================================================
# REGLAS DE CÁLCULO (siempre visible, al final de la página)
# ======================================================================
st.divider()
st.header("📘 Reglas que usa el programa para calcular el Min y el Max")
st.caption("Los valores resaltados son los parámetros que tienes configurados en este momento.")

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
El cálculo es por cada combinación **Local × Estadístico**. El producto **pasa de TDF a Min/Max** si el forecast
no es confiable para abastecer, es decir, si cumple **cualquiera** de estas tres condiciones; si no cumple ninguna,
**se queda en TDF** y no aparece en el archivo:

1. **Pronóstico cero o sin pronóstico:** la suma de los días de pronóstico es 0.
2. **Pronóstico bajo:** `pronóstico promedio diario × FREC  <  {p.pct_empaque_min_max:.0%} del Empq_final`.
3. **Pronóstico repetido:** `UNICOS ≤ {p.umbral_unicos}`. UNICOS cuenta cuántos de los valores diarios del pronóstico aparecen una sola vez;
   si el forecast copia los mismos valores (semana 2 = semana 1), casi no hay valores únicos y el pronóstico no es confiable.

**Importante:** las condiciones 1 y 3 aplican **aunque el producto tenga subempaque / Empq_final = 1**. Con empaque 1, TDF puede
completar la necesidad de a una unidad y siempre cubre la exhibición, pero si el forecast es cero o está repetido el pronóstico
está mal, y TDF trabajaría con un dato incorrecto; por eso pasa a Min/Max.

Detalle de la condición 2:

- **Pronóstico promedio diario** = suma del pronóstico de todos los días que trae el BI (**SUMA**, normalmente 12; si el BI trae menos, por ejemplo 11, se divide para esos días).
- **FREC** = días entre despachos del local (**FREC ENTRE DESP** del BI{", o el mayor intervalo real entre despachos" if p.usar_frec_efectiva else ""}).
- **Empq_final** = empaque con el que realmente se despacha (el SUBEMPAQUE si existe; si no, el EMPAQUE).

**Idea de fondo:** si en el ciclo entre dos despachos se espera vender menos de {p.pct_empaque_min_max:.0%} de un empaque, el forecast
es tan pequeño que no sirve para abastecer bien; conviene un Min/Max fijo. Las columnas `PRON x FREC`, `% PRON/EMPQ`, `UNICOS`
y `MOTIVO MIN/MAX` del Excel muestran, fila por fila, por qué pasó a Min/Max.

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

with st.expander("Reglas de sugerencia de SUBEMPAQUE"):
    st.markdown(f"""
Un producto sin subempaque en un local aparece en la hoja **SUGERIR SUBEMPAQUE** solo si cumple **todo** lo siguiente:

1. **Nunca** es de las familias: **{", ".join(p.familias_no_subempacar) or "(ninguna)"}**, ni es un ESTADISTICO excluido manualmente
   ({", ".join(map(str, p.skus_no_subempacar)) if p.skus_no_subempacar else "ninguno"}).
2. Cumple **al menos uno** de estos criterios:
   - **PVP alto:** PVP ≥ **{p.pvp_alto:g}**.
   - **Bajo consumo:** CONSUMO DIA < **{p.sub_consumo_bajo_dia:g}** unidades/día.
   - **Exhibición baja:** Exhi ÷ EMPAQUE < **{p.sub_pct_exhi_max:.0%}**.
3. Tiene EMPAQUE ≥ **{p.min_empaque_sugerir_sub}** unidades.
4. El mismo SKU **ya está subempacado** en al menos **{p.min_locales_con_sub}** local(es) del BI (o está en la lista manual);
   ese valor es el subempaque sugerido.

**Prioridad:** ALTA si cumple 2 o 3 criterios; MEDIA si cumple solo uno. La hoja muestra cuánto bajaría el Max si se subempaca.
""")

with st.expander("Hojas del Excel que se descarga"):
    st.markdown(f"""
- **Pronóstico cero:** los productos que pasan a Min/Max, con Min y Max listos para cargar. Incluye columnas de control
  (`DIF`, `%`, `DG MIN`, `DGMAX`, `CON>EXHI`, `DG EXHI = DG MIN`, `PRON x FREC`, `% PRON/EMPQ`, `% CONSUMO/EMPQ`).
- **REVISAR:** **solo casos extremos**; el resto de avisos operativos no se lista.
  - *Prioridad ALTA:* **Inventario Físico Negativo** (`INV NETO < 0`) y **Consumo diario triplica la Exhibición** (`CONSUMO DIA ≥ {p.factor_consumo_exhi:g} × Exhi`).
  - *Prioridad MEDIA:* **Sobre stock: Cobertura > {p.sobrestock_dias:g} días** (`Max ÷ CONSUMO DIA`), salvo que la Exhibición cubra al menos el {p.pct_exhi_en_cobertura:.0%} de esos días (stock ligado a la exhibición, no se revisa).
  - *Prioridad BAJA (informativo):* **Sobrestock por exhibición**: consumo diario < {p.consumo_bajo_exhi:g} y la sola exhibición cubre más de {p.sobrestock_dias:g} días. El inventario está atado a llenar la exhibición.
  - Los productos sin consumo no se revisan: solo se mantiene la exhibición (Min = Exhi).
- **SUGERIR SUBEMPAQUE:** propuestas de cambio de maestro (ver reglas arriba).
- **Resumen:** indicadores del proceso y esta misma leyenda de reglas.
""")
