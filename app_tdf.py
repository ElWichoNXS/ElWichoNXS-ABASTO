"""
app_tdf.py  -  Módulo «Min/Max → TDF»: decide qué estadísticos que hoy están en método M pueden volver a TDF.
Se abre desde el selector de módulos de app.py (misma app, mismo estilo). La lógica está en motor_tdf.py.
"""
import io
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from estilo import C_ALT, C_BAJO, C_EXT, C_OK, chips, encabezado, grafico, kpis, n, nota_html, seccion, vacio
from motor_minmax import ColumnasPronosticoError, Params, leer_bi
from motor_tdf import EXCLUSIONES_BLOQUEAN, VERSION_TDF, ParamsTDF, exportar_excel_tdf, procesar_m_a_tdf

VERSION_APP_TDF = "2026-11-12-a"
TIPOS_ARCHIVO = ["xlsx", "xlsm", "xls", "xlsb", "ods", "csv", "txt"]
ETQ_COD = {"LI": "LI · liberado (también vacía)", "IP": "IP · bloqueo parcial", "SP": "SP · suspensión parcial",
           "IT": "IT · bloqueo total", "ST": "ST · suspensión total"}


@st.cache_data(show_spinner=False, max_entries=3)
def calcular_tdf(bytes_bi, params, excl, alerta, cols_pronostico, version=VERSION_TDF):
    p = Params(**params)
    pt = ParamsTDF(excl_bloquean=tuple(excl), alerta_sin_venta=bool(alerta))
    bi = leer_bi(io.BytesIO(bytes_bi))
    res, r = procesar_m_a_tdf(bi, p, pt, list(cols_pronostico) if cols_pronostico else None)
    buf = io.BytesIO()
    exportar_excel_tdf(res, r, buf, p, pt)
    return res, r, buf.getvalue()


def _barras(df, cat, val, color, alto=None):
    df = df.copy()
    df["_et"] = df[cat].astype(str) + "  ·  " + df[val].map(lambda v: f"{v:,.0f}".replace(",", "."))
    return alt.Chart(df).mark_bar(cornerRadiusEnd=4, size=20, color=color).encode(
        y=alt.Y("_et:N", sort="-x", title=None, axis=alt.Axis(labelLimit=330)),
        x=alt.X(f"{val}:Q", title=None, axis=alt.Axis(format="~s", grid=True)),
        tooltip=[alt.Tooltip(f"{cat}:N", title="Categoría"), alt.Tooltip(f"{val}:Q", title="Filas", format=",")],
    ).properties(height=alto or max(120, 34 * len(df) + 20))


def _tabla(df, clave, columnas, extra_filtros=None, max_filas=2000, cfg=None):
    """Filtros (local, familia, búsqueda y los que se pidan) + tabla con las columnas esenciales."""
    f = st.columns([1.2, 1.2, 1.6, 1])
    locales = sorted(df["Local"].dropna().unique().tolist()) if "Local" in df else []
    fams = sorted(df["FAMILIA"].dropna().astype(str).unique().tolist()) if "FAMILIA" in df else []
    s_loc = f[0].multiselect("Local", locales, key=f"tdf_{clave}_loc", placeholder="Todos")
    s_fam = f[1].multiselect("Familia", fams, key=f"tdf_{clave}_fam", placeholder="Todas")
    q = f[2].text_input("Buscar en estadístico o descripción", key=f"tdf_{clave}_q", placeholder="Ej.: 243138 o ARROZ")
    todas = f[3].toggle("Todas las columnas", key=f"tdf_{clave}_all")
    out = df
    for col, etiqueta in (extra_filtros or []):
        vals = sorted(out[col].dropna().unique().tolist(), key=str)
        sel = st.multiselect(etiqueta, vals, key=f"tdf_{clave}_{col}", placeholder="Todos")
        if sel:
            out = out[out[col].isin(sel)]
    if s_loc:
        out = out[out["Local"].isin(s_loc)]
    if s_fam:
        out = out[out["FAMILIA"].astype(str).isin(s_fam)]
    if q.strip():
        qq = q.strip().lower()
        m = out["ESTADISTICO"].astype(str).str.contains(qq, regex=False)
        if "DESCRIPCION" in out:
            m |= out["DESCRIPCION"].astype(str).str.lower().str.contains(qq, regex=False)
        out = out[m]
    cols = list(out.columns) if todas else [c for c in columnas if c in out.columns]
    st.caption(f"{n(len(out))} filas" + (f" (se muestran las primeras {n(max_filas)}; descarga el Excel para verlas todas)"
                                         if len(out) > max_filas else ""))
    st.dataframe(out[cols].head(max_filas), hide_index=True, width="stretch", height=430, column_config=cfg or {})


def main():
    hoy = datetime.now(ZoneInfo("America/Guayaquil"))
    dias_def = max(1, min(31, hoy.day - 1))

    # ---------------- Barra lateral ----------------
    with st.sidebar:
        st.header("Parámetros")
        st.caption("Cada grupo se abre y se cierra por separado. El ícono de ayuda junto a cada parámetro explica qué hace.")
        p = Params()
        with st.expander("1 · Consumo", expanded=True):
            p.dias_transcurridos = st.number_input(
                "Días de consumo transcurridos", min_value=1, max_value=31, value=dias_def, key="tdf_dias",
                help="Días de venta completos del mes (el día en curso no cuenta). El BI entrega el consumo acumulado del mes "
                     "(CONSUMOS ACU); sirve para detectar los estadísticos que pasan a TDF sin venta y marcarlos con alerta. "
                     "Cámbialo cada vez que descargues el BI.")
        with st.expander("2 · Cuándo un estadístico vuelve a TDF"):
            p.pct_empaque_cobertura = st.number_input(
                "Sin subempaque: nivel TDF desde (% del empaque)", min_value=0.05, max_value=3.0, value=0.50, step=0.05, format="%.2f",
                key="tdf_pct_emp",
                help="Nivel TDF = Proyectado + Cubrimiento + Exhibición + Destacado. Sin subempaque, vuelve a TDF si ese nivel llega "
                     "a este porcentaje del empaque (0,50 = la mitad). Es la misma regla que usa el módulo TDF → Min/Max, al revés.")
            p.pct_subempaque_cobertura = st.number_input(
                "Con subempaque: nivel TDF desde (% del subempaque)", min_value=0.05, max_value=3.0, value=1.00, step=0.05, format="%.2f",
                key="tdf_pct_sub",
                help="Igual, pero para productos con subempaque: vuelve a TDF si el nivel llega a este porcentaje del subempaque (1,00 = uno completo).")
            p.umbral_unicos = st.number_input(
                "Pronóstico lineal: valores únicos en los 12 días menor o igual a", min_value=0, max_value=12, value=5, key="tdf_unicos",
                help="Un pronóstico es lineal cuando el modelo todavía no aprendió y repite valores. Se cuentan los valores que aparecen una sola "
                     "vez en los 12 días. Si el modelo solo copió la semana en los días 8 a 12, se juzga solo la primera semana. "
                     "Los lineales se quedan en M.")
        with st.expander("3 · Exclusiones y alertas"):
            excl = st.multiselect(
                "Exclusiones que se quedan en M", list(ETQ_COD), default=list(EXCLUSIONES_BLOQUEAN), format_func=ETQ_COD.get, key="tdf_excl",
                help="Con IT y ST no se puede transferir del CD a los locales, así que esos estadísticos se quedan en Min/Max. "
                     "Los de LI, vacía, IP y SP sí se despachan desde el CD (IP y SP hasta agotar el stock) y pueden pasar a TDF.")
            alerta = st.checkbox(
                "Alertar los que pasan a TDF sin venta en el mes", value=True, key="tdf_alerta",
                help="Si el estadístico tiene pronóstico normal pero no vendió nada en el mes, igual pasa a TDF y queda marcado en la columna "
                     "ALERTA para identificarlo (por ejemplo, un producto en quiebre o recién llegado).")

    # ---------------- Encabezado y carga ----------------
    f_bi_ok = st.session_state.get("tdf_f_bi") is not None
    encabezado("Min/Max → TDF · Pronóstico",
               "Decide qué estadísticos que hoy están en Min/Max pueden volver a TDF.",
               [("Cargar el BI", f_bi_ok), ("Ajustar parámetros", f_bi_ok), ("Revisar y descargar", f_bi_ok)])
    seccion("Carga del archivo", "Sube el BI con los estadísticos que hoy están en método M")
    c1, c2 = st.columns([1, 1])
    f_bi = c1.file_uploader("BI con los estadísticos en M", type=TIPOS_ARCHIVO, key="tdf_f_bi",
                            help="Archivo del BI con el pronóstico de 12 días por local y estadístico y la columna «Método». "
                                 "Solo se evalúan las filas con Método = M; las de TDF o TEM se ignoran. Acepta Excel y CSV/TXT.")
    c2.markdown(nota_html("Pasa a TDF el estadístico con <b>pronóstico normal</b> (ni cero ni lineal) y nivel TDF suficiente, "
                          "siempre que su exclusión permita despachar desde el CD (LI, vacía, IP y SP). Los IT y ST se quedan en M. "
                          "Si no tuvo venta en el mes, pasa igual y queda con una <b>alerta</b>."), unsafe_allow_html=True)
    if not f_bi:
        vacio("Carga el BI para ver el resultado",
              "Sube el archivo del BI con los estadísticos en método M para ver cuáles pueden volver a TDF y descargar el archivo de cambios.",
              [("BI con filas en M", False)])
        return

    params = asdict(p)
    bytes_bi = f_bi.getvalue()
    try:
        with st.spinner("Procesando el BI…"):
            res, r, xlsx = calcular_tdf(bytes_bi, params, tuple(excl), alerta, None, VERSION_TDF)
    except ColumnasPronosticoError as e:
        st.error(f"{e} Elige abajo las columnas del pronóstico diario.")
        elegidas = st.multiselect("Selecciona las columnas de pronóstico diario (entre 7 y 12), en orden", options=list(e.todas), format_func=str,
                                  help="Son las columnas con la venta pronosticada por día (una por cada uno de los próximos días).")
        if not (7 <= len(elegidas) <= 12):
            st.info(f"Seleccionadas: {len(elegidas)}. Elige entre 7 y 12 columnas.")
            return
        try:
            with st.spinner("Procesando el BI…"):
                res, r, xlsx = calcular_tdf(bytes_bi, params, tuple(excl), alerta, tuple(elegidas), VERSION_TDF)
        except ValueError as e2:
            st.error(str(e2))
            return
    except ValueError as e:
        st.error(str(e))
        return

    with c1:
        chips([f"<b>{n(r['filas_m'])}</b> filas en M", f"<b>{n(r['estadisticos_m'])}</b> estadísticos",
               f"<b>{r['dias_de_pronostico']}</b> días de pronóstico"])
    if r["filas_otro_metodo"]:
        st.info("El archivo también trae filas con otro método (" + ", ".join(f"{k}: {n(v)}" for k, v in r["filas_otro_metodo"].items())
                + "). No se evalúan: solo se revisan las que están en M.")
    if r["dias_de_pronostico"] < 12:
        st.info(f"El BI trae **{r['dias_de_pronostico']} días de pronóstico** (no 12). Columnas usadas: {r['columnas_pronostico_usadas']}.")

    pasan = res[res["DECISION"] == "Pasar a TDF"]
    quedan = res[res["DECISION"] == "Dejar en M"]
    con_alerta = pasan[pasan["ALERTA"] != ""]
    d1, d2 = st.columns([3, 1.4], vertical_alignment="center")
    d1.markdown(nota_html(f'<b>{n(r["pasan"])}</b> de <b>{n(r["filas_m"])}</b> filas en M pueden volver a TDF '
                          f'({r["pasan"] / max(r["filas_m"], 1):.1%}); <b>{n(r["alertas_sin_venta"])}</b> de ellas no tuvieron venta en el mes y quedan con alerta. '
                          'Descarga el Excel: la hoja CARGA TDF trae lo que se cambia.', "ok"), unsafe_allow_html=True)
    d2.download_button("Descargar Excel de cambios", xlsx, icon=":material/download:", key="tdf_descarga",
                       file_name=f"Min_Max_a_TDF_{hoy:%d-%m-%Y}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

    kpis([("Filas en M evaluadas", n(r["filas_m"]), f"{n(r['estadisticos_m'])} estadísticos distintos", C_ALT),
          ("Pasan a TDF", n(r["pasan"]), f"{n(r['estadisticos_pasan'])} estadísticos · {n(r['locales_pasan'])} locales", C_OK),
          ("Con alerta", n(r["alertas_sin_venta"]), "Pasan a TDF sin venta en el mes", C_BAJO),
          ("Se quedan en M", n(r["quedan"]), "Pronóstico cero, lineal, nivel bajo o exclusión", C_EXT)])

    t_res, t_pas, t_ale, t_que = st.tabs(["Resumen", f"Pasan a TDF ({n(len(pasan))})", f"Con alerta ({n(len(con_alerta))})",
                                          f"Se quedan en M ({n(len(quedan))})"])
    with t_res:
        g1, g2 = st.columns(2)
        with g1:
            mot = pd.Series(r["por_motivo_quedan"]).rename_axis("Motivo").reset_index(name="Filas")
            if len(mot):
                grafico("Por qué se quedan en M", "Motivo principal de cada fila que no pasa a TDF.", _barras(mot, "Motivo", "Filas", C_EXT))
            else:
                st.info("Todas las filas en M pueden volver a TDF.")
        with g2:
            fam = pasan["FAMILIA"].astype(str).value_counts().head(10).rename_axis("Familia").reset_index(name="Filas")
            if len(fam):
                grafico("Familias que más pasan a TDF", "Top 10 por número de filas.", _barras(fam, "Familia", "Filas", C_OK))
            else:
                st.info("Ninguna fila pasa a TDF con los parámetros actuales.")
        seccion("Estadísticos que más pasan a TDF", "Cuántos locales cambian y cuántos de ellos no tuvieron venta (alerta)")
        if len(pasan):
            top = pasan.groupby(["ESTADISTICO", "DESCRIPCION"]).agg(Locales=("Local", "nunique"), Con_alerta=("ALERTA", lambda s: int((s != "").sum()))
                                                                     ).reset_index().sort_values("Locales", ascending=False).head(15)
            top = top.rename(columns={"Con_alerta": "Con alerta"})
            tot_m = res.groupby("ESTADISTICO")["Local"].nunique().rename("En M")
            top = top.merge(tot_m, left_on="ESTADISTICO", right_index=True, how="left")
            st.dataframe(top, hide_index=True, width="stretch", height=min(460, 35 * (len(top) + 1) + 3))
    cols_pas = ["MOTIVO", "ALERTA", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA", "EXCLUSION", "Exhi", "Min", "Max",
                "CONSUMOS ACU", "PROMEDIO PRONOSTICO DIA", "COBERTURA TDF", "UMBRAL TDF"]
    with t_pas:
        _tabla(pasan, "pas", cols_pas, extra_filtros=[("EXCLUSION", "Exclusión")])
    with t_ale:
        if len(con_alerta):
            st.markdown(nota_html("Estos estadísticos pasan a TDF porque su pronóstico es normal, pero <b>no tuvieron venta en el mes</b>. "
                                  "Conviene revisar si están en quiebre, si son nuevos o si el pronóstico está desfasado.", "warn"), unsafe_allow_html=True)
            _tabla(con_alerta, "ale", cols_pas, extra_filtros=[("ESTADISTICO", "Estadístico")])
        else:
            st.info("Ningún estadístico pasa a TDF sin venta en el mes.")
    with t_que:
        _tabla(quedan, "que", ["MOTIVO", "CLASE PRONOSTICO", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA", "EXCLUSION",
                               "Exhi", "Min", "Max", "COBERTURA TDF", "UMBRAL TDF"], extra_filtros=[("MOTIVO", "Motivo")])
