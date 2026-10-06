"""
app.py  -  Interfaz Streamlit para calcular Min/Max (Pronóstico cero)
Ejecutar:  streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st

from motor_minmax import Params, leer_aptos, leer_bi, procesar

st.set_page_config(page_title="Min/Max · Pronóstico cero", layout="wide")
st.title("Min / Max por local · Pronóstico cero")
st.caption("Carga el Excel crudo del BI y descarga el archivo procesado.")

# ---------------- Parámetros (barra lateral) ----------------
with st.sidebar:
    st.header("Parámetros de negocio")
    p = Params(
        dias_ventana_consumo=st.number_input("Días de la ventana de consumo", 1, 30, 5),
        umbral_pronostico_12d=st.number_input("Umbral pronóstico 12 días (≤)", 0.0, 100.0, 6.0),
        umbral_dg_exhi=st.number_input("Exhi cubre menos de (días) → sube Min", 0.5, 10.0, 2.0),
        max_dias_ss_ajuste=st.number_input("Ajuste fino solo si Dias SS ≤", 0, 30, 4),
    )
    skus_extra = st.text_area("SKUs con SUBEMPAQUE = 1 (uno por línea)",
                              "\n".join(map(str, p.skus_sub1)))
    p.skus_sub1 = tuple(int(x) for x in skus_extra.split() if x.strip().isdigit())

# ---------------- Carga ----------------
c1, c2 = st.columns(2)
f_bi = c1.file_uploader("1) Excel del BI (obligatorio)", type=["xlsx"])
f_ap = c2.file_uploader("2) Lista de APTOS (opcional: col A = ESTADISTICO, col C = Si/No)",
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

    st.dataframe(salida.head(500), use_container_width=True)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        salida.to_excel(w, index=False, sheet_name="Pronóstico cero")
        pd.DataFrame([r]).T.rename(columns={0: "valor"}).to_excel(w, sheet_name="Resumen")
    st.download_button("⬇️ Descargar Excel procesado", buf.getvalue(),
                       file_name="Pronostico_cero_procesado.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
