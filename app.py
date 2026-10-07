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
st.caption("Carga el Excel crudo del BI y descarga el archivo procesado.")

# ---------------- Parámetros (barra lateral) ----------------
with st.sidebar:
    st.header("Parámetros de negocio")
    p = Params(
        dias_ventana_consumo=st.number_input("Días de la ventana de consumo", 1, 30, 5),
        umbral_pronostico_12d=st.number_input("Umbral pronóstico 12 días (≤)", 0.0, 100.0, 6.0),
        umbral_unicos=st.number_input("UNICOS máximo (≤)", 0, 12, 5),
        umbral_dg_exhi=st.number_input("Exhi cubre menos de (días) → sube Min", 0.5, 10.0, 2.0),
        max_dias_ss_ajuste=st.number_input("Ajuste fino solo si Dias SS ≤", 0, 30, 4),
        usar_frec_efectiva=st.checkbox("Usar mayor intervalo real entre despachos (LUNES…DOMINGO)", False,
                                       help="Cubre el hueco más largo entre despachos en vez del promedio del BI."),
        umbral_venta_prom_dia=st.number_input("Pronóstico insuficiente si promedio diario < (u/día)", 0.0, 10.0, 1.0),
        dias_cobertura_max=st.number_input("Max: cobertura adicional (días, 0 = solo SUBEMPAQUE / EMPAQUE÷2)",
                                           0.0, 60.0, 0.0, step=0.5,
                                           help="Si > 0, el incremento sobre el Min sube a cubrir N días de consumo, "
                                                "en múltiplos del incremento mínimo de despacho."),
    )
    st.subheader("Sugerencias de subempaque")
    p.min_locales_con_sub = st.number_input("El SKU debe estar subempacado en al menos N locales", 1, 50, 1)
    fam = st.text_area("Familias de prioridad ALTA (una por línea)", "\n".join(p.familias_alto_valor))
    p.familias_alto_valor = tuple(x.strip().upper() for x in fam.splitlines() if x.strip())
    extra = st.text_area("SKUs subempacables aunque el BI no los muestre subempacados (uno por línea)", "")
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
