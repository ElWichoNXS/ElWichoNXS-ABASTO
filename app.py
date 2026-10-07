"""
app.py  -  Interfaz Streamlit para calcular Min/Max (Pronóstico cero)
Ejecutar:  streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st

from motor_minmax import (Params, exportar_excel, leer_aptos, leer_bi,
                          marcar_revision, procesar, sugerir_subempaque)

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

    st.subheader("2. Qué filas se conservan")
    p.umbral_pronostico_12d = st.number_input(
        "Pronóstico de 12 días ≤ (unidades)", 0.0, 100.0, 6.0,
        help="Se conservan los productos cuyo pronóstico total (suma de los 12 días, columna SUMA) es "
             "menor o igual a este valor: son productos con muy poca venta esperada ('pronóstico cero').")
    p.umbral_unicos = st.number_input(
        "UNICOS máximo (≤)", 0, 12, 5,
        help="UNICOS = cuántos de los 12 valores del pronóstico aparecen una sola vez. Un número bajo "
             "significa que el pronóstico repite los mismos valores (semana 2 copia a semana 1), es decir, "
             "no es confiable. Se conservan las filas con UNICOS menor o igual a este valor.")

    st.subheader("3. Cálculo del Min")
    p.umbral_dg_exhi = st.number_input(
        "Exhibición cubre menos de (días)", 0.5, 10.0, 2.0,
        help="Regla B del Min. Si los días que cubre la exhibición (Exhi ÷ consumo diario) son menos que "
             "este valor, el Min sube a cubrir la frecuencia de despacho.")
    p.max_dias_ss_ajuste = st.number_input(
        "Ajuste fino solo si Dias SS ≤", 0, 30, 4,
        help="Regla B del Min. 'Dias SS' son los días de stock de seguridad del producto. El ajuste fino "
             "solo se aplica a productos con stock de seguridad igual o menor a este número de días.")
    p.usar_frec_efectiva = st.checkbox(
        "Usar el mayor intervalo real entre despachos", False,
        help="Apagado (recomendado, es lo que haces manualmente): se usa FREC ENTRE DESP tal como viene del BI "
             "(promedio de días entre despachos). Encendido: se usa el hueco MÁS LARGO entre despachos "
             "según los días LUNES…DOMINGO. Ejemplo: despacha Mar-Sáb-Dom; el BI dice 2 días, pero entre "
             "Mar y Sáb pasan 4.")

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
             "(SUMA ÷ 12) es menor a este valor, se marca como 'insuficiente'.")

    st.subheader("6. Hoja REVISAR")
    p.revisar_ratio_consumo = st.number_input(
        "Consumo real mayor que X veces el pronóstico", 1.0, 20.0, 5.0,
        help="Marca para revisión los productos cuyo consumo real de 12 días supera en X veces "
             "el pronóstico: el pronóstico probablemente está subestimado.")
    p.revisar_dgmax_dias = st.number_input(
        "Cobertura del Max mayor a (días)", 1.0, 365.0, 60.0,
        help="Marca para revisión los productos donde el Max cubre más de estos días de consumo "
             "(posible sobre-inventario).")
    p.revisar_var_bi = st.number_input(
        "Cambio del Min vs Min vigente en BI mayor a", 0.0, 5.0, 0.5, step=0.05, format="%.2f",
        help="Marca para revisión si el Min nuevo difiere del Min que ya tiene el BI en más de este "
             "porcentaje. 0.50 = 50 %.")

    st.subheader("7. Sugerencias de subempaque")
    p.min_empaque_sugerir_sub = st.number_input(
        "Solo si EMPAQUE ≥ (unidades)", 1, 100, 6,
        help="Solo se sugiere subempacar productos cuyo empaque tenga al menos esta cantidad de unidades.")
    p.min_locales_con_sub = st.number_input(
        "El SKU debe estar subempacado en al menos N locales", 1, 50, 1,
        help="Se sugiere subempacar un producto en un local solo si el mismo SKU ya está subempacado "
             "en al menos N locales del BI (evidencia de que se puede).")
    fam = st.text_area(
        "Familias de prioridad ALTA (una por línea)", "\n".join(p.familias_alto_valor),
        help="Las sugerencias de estas familias (alto valor) salen como Prioridad ALTA; el resto como MEDIA.")
    p.familias_alto_valor = tuple(x.strip().upper() for x in fam.splitlines() if x.strip())
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
    with st.spinner("Procesando…"):
        bi = leer_bi(f_bi)
        aptos = leer_aptos(f_ap) if f_ap else None
        try:
            salida, r = procesar(bi, aptos, p)
        except ValueError as e:
            st.error(str(e))
            st.stop()

    if r["posible_truncado_bi"]:
        st.warning("El BI trae ~30.000 filas: la descarga puede estar truncada. "
                   "Verifica que no falten locales/SKUs.")
    if not f_ap:
        st.info("Sin lista de aptos: se asumió APTO = 'Si' para todos "
                "(afecta solo a la regla B de Min).")

    k = st.columns(5)
    k[0].metric("Filas BI", f"{r['filas_bi']:,}")
    k[1].metric("Filas resultado", f"{r['filas_resultado']:,}")
    k[2].metric("Min = Exhi (regla C)", f"{r['regla_C']:,}")
    k[3].metric("Ajustadas (A + B)", f"{r['regla_A'] + r['regla_B']:,}")
    k[4].metric("Para REVISAR", f"{r['filas_con_aviso_revisar']:,}")

    rev = marcar_revision(salida, p)
    sug = sugerir_subempaque(salida, p)
    r["sugerencias_subempaque"] = len(sug)
    r["filas_en_hoja_REVISAR"] = len(rev)
    r["revisar_prioridad_alta"] = int((rev["PRIORIDAD"] == "Prioridad ALTA").sum())
    st.metric("Casos en hoja REVISAR", f"{len(rev):,}",
              f"{r['revisar_prioridad_alta']} de prioridad alta", delta_color="off")

    k2 = st.columns(4)
    k2[0].metric("Frec. efectiva > BI", f"{r['frec_efectiva_mayor_que_bi']:,}")
    k2[1].metric("Pronóstico insuficiente", f"{r['pronostico_insuficiente']:,}")
    k2[2].metric("Pronóstico repetido", f"{r['pronostico_valores_repetidos']:,}")
    k2[3].metric("Pronóstico ciclo > Exhi", f"{r['pronostico_ciclo_mayor_exhi']:,}")

    t1, t2, t3 = st.tabs(["Resultado", "Casos a revisar", "Sugerir subempaque"])
    t1.dataframe(salida.head(500), use_container_width=True)
    t2.dataframe(rev, use_container_width=True)
    t3.caption("Productos sin subempaque cuyo mismo SKU ya está subempacado en otros locales. "
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
st.caption("Los valores entre paréntesis son los parámetros que tienes configurados en este momento.")

with st.expander("Paso 0 · Qué filas se procesan y cómo se obtiene el consumo diario", expanded=True):
    st.markdown(f"""
**Filas que se conservan.** Se calcula por cada combinación **Local × Estadístico**. De todo el BI solo se
procesan los productos de "pronóstico cero", es decir, los que cumplen **una** de estas condiciones:
- La suma del pronóstico de los 12 días (**SUMA**) es **≤ {p.umbral_pronostico_12d:g}** unidades.
- **UNICOS ≤ {p.umbral_unicos}**: pocos valores distintos en el pronóstico, es decir, el pronóstico se repite y no es confiable.

**Consumo diario.** El BI entrega el consumo acumulado del mes. Se divide para los días transcurridos:

`CONSUMO DIA = CONSUMOS ACU ÷ {p.dias_transcurridos} días transcurridos`

**APTO.** Se toma del maestro de productos (columna *Apto para PTL*). Si no cargas el maestro,
se asume "Si" para todos y la regla B del Min puede aplicarse a más productos de los debidos.
""")

with st.expander("Regla del MIN (se evalúa en este orden)", expanded=True):
    st.markdown(f"""
Todos los valores se redondean al **entero más cercano** (mitad hacia arriba, como el `REDONDEAR` de Excel).
`FREC` = días entre despachos (**FREC ENTRE DESP** del BI{", o el mayor intervalo real entre despachos" if p.usar_frec_efectiva else ""}).

| Regla | Condición | Min |
|---|---|---|
| **A** | El consumo diario es **mayor que la exhibición** (`CONSUMO DIA > Exhi`) | `REDONDEAR(CONSUMO DIA × FREC)` |
| **B** | No aplica A, y además: el producto es **apto**, la exhibición cubre **menos de {p.umbral_dg_exhi:g} días** (`Exhi ÷ CONSUMO DIA`), `Dias SS ≤ {p.max_dias_ss_ajuste}` y `CONSUMO DIA × FREC > Exhi` | `REDONDEAR(CONSUMO DIA × FREC)` |
| **C** | Cualquier otro caso (la gran mayoría) | `Min = Exhi` (la exhibición) |

**Idea de fondo:** el Min nunca puede ser menor que la exhibición. Solo sube cuando la venta diaria es
tan alta que la exhibición no alcanza a cubrir los días hasta el próximo despacho.
""")

with st.expander("Regla del MAX", expanded=True):
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

with st.expander("Hojas del Excel que se descarga"):
    st.markdown(f"""
- **Pronóstico cero:** el resultado completo, con Min y Max listos para cargar. Incluye columnas de control
  (`DIF`, `%`, `DG MIN`, `DGMAX`, `CON>EXHI`, `DG EXHI = DG MIN`).
- **REVISAR:** casos fuera de parámetros o complejos para revisar a mano, ordenados por prioridad (ALTA primero):
  - *Prioridad ALTA:* consumo mayor que la exhibición (regla A), producto sin pronóstico, inventario neto negativo, producto de temporada.
  - *Prioridad MEDIA:* exhibición que no cubre la frecuencia de despacho, pronóstico hasta el próximo despacho mayor que la exhibición,
    pronóstico repetido con consumo real muy superior, consumo real mayor a **{p.revisar_ratio_consumo:g}×** el pronóstico,
    cobertura del Max mayor a **{p.revisar_dgmax_dias:g} días**, y Min nuevo que difiere más de **{p.revisar_var_bi:.0%}** del Min vigente en el BI.
- **SUGERIR SUBEMPAQUE:** productos sin subempaque cuyo mismo SKU ya está subempacado en otros locales
  (EMPAQUE ≥ {p.min_empaque_sugerir_sub}). Muestra cuánto bajaría el Max si se subempaca.
- **Resumen:** indicadores del proceso y esta misma leyenda de reglas.
""")
