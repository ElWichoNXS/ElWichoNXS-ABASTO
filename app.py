"""
app.py  -  Interfaz Streamlit para calcular Min/Max (Pronóstico cero)
Ejecutar:  streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st

from motor_minmax import (ColumnasPronosticoError, Params, exportar_excel, leer_aptos,
                          leer_bi, marcar_en_revision, marcar_revision, procesar, sugerir_subempaque)

st.set_page_config(page_title="Min/Max · Pronóstico cero", page_icon="📦", layout="wide")

# Colores que funcionan igual en modo claro y oscuro (no dependen de detectar el tema):
# el texto y los fondos heredan del tema de Streamlit; solo el rojo es fijo.
ROJO = "#E4252F"                                   # legible sobre blanco y sobre fondo oscuro
BORDE = "color-mix(in srgb, currentColor 18%, transparent)"
SUAVE = "color-mix(in srgb, currentColor 62%, transparent)"
TARJETA = "color-mix(in srgb, currentColor 5%, transparent)"

st.markdown(f"""
<style>
.block-container {{ padding-top: 1.2rem; max-width: 1500px; }}
h1, h2, h3, h4 {{ letter-spacing: -0.2px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* Banner (siempre rojo con texto blanco) */
.hero {{
    background: linear-gradient(110deg, #E30613 0%, #A30410 100%);
    border-radius: 14px; padding: 26px 32px; margin-bottom: 22px;
    box-shadow: 0 6px 18px rgba(227,6,19,.30);
}}
.hero h1 {{ color: #fff !important; margin: 0; font-size: 2rem; font-weight: 800; }}
.hero p  {{ color: #ffe5e7 !important; margin: 6px 0 0 0; font-size: 1rem; }}
.hero .tag {{ display:inline-block; background:#fff; color:#E30613; font-weight:700;
    font-size:.72rem; letter-spacing:1px; padding:3px 10px; border-radius:20px; margin-bottom:10px; }}

/* Barra lateral */
section[data-testid="stSidebar"] {{ border-right: 3px solid #E30613; }}
section[data-testid="stSidebar"] h2 {{
    color: #fff !important; background: #E30613; padding: 10px 14px; border-radius: 8px;
    font-size: 1.05rem; margin-bottom: 4px;
}}
section[data-testid="stSidebar"] h3 {{
    color: {ROJO} !important; font-size: .95rem; border-bottom: 2px solid {BORDE};
    padding-bottom: 4px; margin-top: 1.1rem;
}}

/* Tarjetas de métricas */
div[data-testid="stMetric"] {{
    background: {TARJETA}; border: 1px solid {BORDE}; border-left: 6px solid #E30613;
    border-radius: 10px; padding: 14px 16px;
}}
div[data-testid="stMetricLabel"] p {{ font-weight: 600; opacity: .75; }}
div[data-testid="stMetricValue"] {{ color: {ROJO}; font-weight: 800; }}

/* Carga de archivos */
div[data-testid="stFileUploader"] section {{
    background: rgba(227,6,19,.08); border: 2px dashed #E30613; border-radius: 12px;
}}
div[data-testid="stFileUploader"] label p {{ font-weight: 700; }}

/* Botones */
.stButton > button, .stDownloadButton > button {{
    background: #E30613; color: #fff; border: none; border-radius: 10px;
    padding: .65rem 1.4rem; font-weight: 700; box-shadow: 0 3px 10px rgba(227,6,19,.3);
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background: #B00510; color: #fff; border: none;
}}
.stButton > button p, .stDownloadButton > button p {{ color: #fff; }}

/* Pestañas */
button[data-baseweb="tab"] {{ font-weight: 700; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {ROJO}; }}
div[data-baseweb="tab-highlight"] {{ background-color: #E30613; height: 3px; }}

/* Tablas y expanders */
div[data-testid="stDataFrame"] {{ border: 1px solid {BORDE}; border-radius: 10px; overflow: hidden; }}
div[data-testid="stExpander"] {{ border: 1px solid {BORDE}; border-radius: 10px; background: {TARJETA}; }}
div[data-testid="stExpander"] summary p {{ font-weight: 700; color: {ROJO}; }}
hr {{ border-color: {BORDE}; }}

/* Títulos de sección */
.seccion {{
    border-left: 6px solid #E30613; padding: 2px 0 2px 12px; margin: 26px 0 12px 0;
    font-size: 1.25rem; font-weight: 800;
}}
.seccion small {{ display:block; font-weight:400; opacity:.65; font-size:.85rem; }}
</style>
""", unsafe_allow_html=True)


def seccion(titulo, sub=""):
    st.markdown(f'<div class="seccion">{titulo}<small>{sub}</small></div>', unsafe_allow_html=True)


st.markdown("""
<div class="hero">
  <span class="tag">ABASTECIMIENTO</span>
  <h1>Min / Max por local · Pronóstico cero</h1>
  <p>Carga el Excel crudo del BI, ajusta los parámetros de la izquierda y descarga el archivo procesado.</p>
</div>
""", unsafe_allow_html=True)

# ---------------- Parámetros (barra lateral) ----------------
with st.sidebar:
    st.header("⚙️ Parámetros de negocio")
    st.caption("Pasa el mouse sobre el signo ❓ de cada parámetro para ver qué significa. "
               "🌓 Modo claro/oscuro: menú ⋮ (arriba a la derecha) → Settings → Theme.")

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
    p.factor_prom_exhi = st.number_input(
        "Regla 3 · Promedio diario del pronóstico menor a (% de la Exhibición)", 0.05, 3.0, 0.55, step=0.05, format="%.2f",
        help="Primera mitad de la condición de cambio. El promedio diario del pronóstico (suma de los días ÷ días de pronóstico) "
             "debe ser menor a este porcentaje de la Exhibición del local. 0.55 = 55 %. Por sí sola NO cambia el método: "
             "debe cumplirse JUNTO con la regla 4 (cobertura del empaque).")
    p.pct_empaque_cobertura = st.number_input(
        "Regla 4 · Promedio × (FREC + Dias SS) menor a (% del empaque final)", 0.05, 3.0, 0.5, step=0.05, format="%.2f",
        help="Segunda mitad de la condición. Se calcula promedio diario del pronóstico × (días de frecuencia de despacho + días de stock "
             "de seguridad). Si ese forecast NO cubre ni este porcentaje del empaque final (0.50 = la mitad), y además se cumple la regla 3, "
             "el producto pasa a Min/Max. Si SÍ lo cubre, se queda en TDF. Los Dias SS se usan solo para esta decisión (en TDF), no para "
             "calcular el Min ni el Max.")
    st.caption("**Pronóstico lineal** (también pasa a Min/Max): se mira solo la primera semana (días 1 a 7). "
               "Es lineal si los valores únicos (aparecen una sola vez) no superan a los valores repetidos. "
               "Que desde el día 8 se copie la semana no cuenta. Ver el detalle en las reglas, al final de la página.")

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
             "(TOTAL PRONOSTICO ÷ días de pronóstico) es menor a este valor, se marca como 'insuficiente'.")

    st.subheader("6. Hoja REVISAR · casos extremos")
    st.caption("La hoja REVISAR solo trae 3 casos: inventario negativo, consumo muy superior a la exhibición y sobre stock crítico.")
    p.sobrestock_dias = st.number_input(
        "Sobre stock crítico: cobertura del Max mayor a (días)", 1.0, 730.0, 20.0,
        help="Se envía a REVISAR si el Max cubre más de estos días de consumo (Max ÷ CONSUMO DIA). "
             "Si el producto no tiene consumo en el mes, no se marca.")
    p.consumo_bajo_exhi = st.number_input(
        "Sobrestock por cubrir exhibición: corte de consumo (u/día)", 0.05, 5.0, 0.5, step=0.05, format="%.2f",
        help="Los casos de sobre stock causados por cubrir la exhibición se muestran en REVISAR (informativo) en dos categorías: "
             "consumo diario menor o igual a este valor, y consumo diario mayor a este valor.")
    p.pct_exhi_en_cobertura = st.number_input(
        "Sobre stock explicado por la Exhibición: Exhi cubre ≥ (% de los días del Max)", 0.1, 1.0, 0.8, step=0.05, format="%.2f",
        help="Si los días que cubre la exhibición (Exhi ÷ CONSUMO DIA) son al menos este porcentaje de los días que cubre el Max, "
             "el exceso de stock se debe a la exhibición del local y NO se envía a REVISAR. 0.80 = 80 %.")
    p.factor_consumo_exhi = st.number_input(
        "Incongruencia: consumo diario ≥ (veces la Exhibición)", 1.0, 20.0, 3.0, step=0.5,
        help="Se envía a REVISAR si el CONSUMO DIA es esta cantidad de veces la Exhi o más. Con 3, el consumo diario triplica la exhibición.")

    st.subheader("7. Sugerencias de subempaque")
    st.caption("Se sugiere subempacar solo para evitar sobrestock: cuando enviar el empaque completo sobra, "
               "o cuando el producto es de PVP alto.")
    p.sub_dias_venta_empaque = st.number_input(
        "Sobrestock: el local tarda más de (días) en vender un empaque completo", 1.0, 365.0, 12.0, step=1.0,
        help="Días que tarda el local en vender UN empaque completo = EMPAQUE ÷ CONSUMO DIA. Si tarda más que este número, "
             "enviar el empaque completo genera sobrestock y el producto es candidato a subempacar. "
             "Ejemplo: empaque de 12 con consumo de 0.2 u/día tarda 60 días. Si el producto no tuvo consumo en el mes, "
             "también cuenta como sobrestock. Bajar el valor sugiere más productos.")
    p.pvp_alto = st.number_input(
        "PVP alto: precio de venta ≥", 0.0, 1000.0, 5.0, step=0.5,
        help="Precio de venta al público (columna PVP del BI) a partir del cual un producto se considera de PVP alto. "
             "Con 'Exigir PVP alto' activado, un producto con PVP menor a este valor NUNCA se sugiere para subempaque, "
             "aunque tenga sobrestock. Con 5.00, un producto de 1.00 queda fuera.")
    p.exigir_pvp_alto = st.checkbox(
        "Exigir PVP alto para sugerir subempaque", True,
        help="Activado (recomendado): solo se sugieren productos con PVP mayor o igual al valor de arriba. "
             "Desactivado: basta el sobrestock, y el PVP alto solo sirve como criterio adicional.")
    p.exigir_apto_subempaque = st.checkbox(
        "Exigir que el producto sea apto para subempaque", True,
        help="Un producto es apto si en el maestro de productos (archivo 2) su columna 'Apto para PTL' dice 'Si'. "
             "Si dice 'No', nunca se sugiere subempacarlo. Si no cargas el maestro, se asume 'Si' para todos y no se bloquea nada.")
    p.min_empaque_sugerir_sub = st.number_input(
        "Solo si EMPAQUE ≥ (unidades)", 1, 100, 7,
        help="Solo se sugiere subempacar productos cuyo empaque tenga al menos esta cantidad de unidades.")
    p.min_locales_con_sub = st.number_input(
        "El SKU debe estar subempacado en al menos N locales", 1, 50, 10,
        help="Se sugiere subempacar un producto en un local solo si el mismo SKU ya está subempacado "
             "en al menos N locales del BI (prueba de que se puede subempacar). Esa evidencia define también el "
             "valor de subempaque sugerido: el más común entre los locales donde ya está subempacado.")
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
seccion("Carga de archivos", "Sube el BI y, opcionalmente, el maestro de productos")
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
        st.info("Sin maestro de productos: se asumió APTO = 'Si' para todos. Afecta la regla B del Min y las "
                "sugerencias de subempaque (no se descarta ningún producto por no ser apto).")

    rev = marcar_revision(salida, p)
    salida = marcar_en_revision(salida, rev)
    sug = sugerir_subempaque(salida, p)
    r.pop("filas_con_aviso_revisar", None)       # métrica vieja (DG EXHI = DG MIN), ya no se usa
    r["sugerencias_subempaque"] = len(sug)
    r["filas_en_hoja_REVISAR"] = len(rev)
    r["revisar_prioridad_alta"] = int((rev["PRIORIDAD"] == "Prioridad ALTA").sum())

    seccion("Resultados", "Indicadores principales del proceso")
    k = st.columns(5)
    k[0].metric("Filas BI", f"{r['filas_bi']:,}")
    k[1].metric("Pasan a Min/Max", f"{r['filas_resultado']:,}")
    k[2].metric("Min = Exhi (regla C)", f"{r['regla_C']:,}")
    k[3].metric("Ajustadas (A + B)", f"{r['regla_A'] + r['regla_B']:,}")
    k[4].metric("Casos en hoja REVISAR", f"{len(rev):,}",
                f"{r['revisar_prioridad_alta']} de prioridad alta", delta_color="off")

    seccion("Segmentación del BI", "Qué se queda en TDF y qué pasa a Min/Max")
    seg = pd.DataFrame({
        "Segmento": ["Pasa a Min/Max · pronóstico cero o sin pronóstico",
                     "Pasa a Min/Max · pronóstico lineal (repetido)",
                     f"Pasa a Min/Max · promedio < {p.factor_prom_exhi:.0%} de la Exhibición y cobertura (FREC+SS) < {p.pct_empaque_cobertura:.0%} del empaque",
                     f"SE QUEDA EN TDF · promedio < {p.factor_prom_exhi:.0%} de la Exhibición pero el forecast cubre {p.pct_empaque_cobertura:.0%} del empaque",
                     "SE QUEDA EN TDF · pronóstico normal", "Total BI"],
        "Filas": [r["segmento_1_pasa_pronostico_cero"], r["segmento_2_pasa_pronostico_lineal"],
                  r["segmento_3_pasa_prom_exhi_y_cobertura_empaque"], r["segmento_4_tdf_rescatado_por_cobertura_empaque"],
                  r["segmento_5_tdf_pronostico_normal"], r["segmento_total_BI"]]})
    seg["% del BI"] = (seg["Filas"] / r["segmento_total_BI"]).map("{:.1%}".format)
    seg["_pct"] = seg["Filas"] / r["segmento_total_BI"]
    st.dataframe(
        seg.rename(columns={"_pct": "Proporción"}), hide_index=True, width="stretch",
        column_config={
            "Filas": st.column_config.NumberColumn(format="%d"),
            "Proporción": st.column_config.ProgressColumn(format=" ", min_value=0.0, max_value=1.0),
        })

    seccion("Diagnóstico del pronóstico")
    k2 = st.columns(4)
    k2[0].metric("Frec. efectiva > BI", f"{r['frec_efectiva_mayor_que_bi']:,}")
    k2[1].metric("Pronóstico insuficiente", f"{r['pronostico_insuficiente']:,}")
    k2[2].metric("Pronóstico repetido", f"{r['pronostico_valores_repetidos']:,}")
    k2[3].metric("Pronóstico ciclo > Exhi", f"{r['pronostico_ciclo_mayor_exhi']:,}")

    seccion("Detalle", "Revisa el resultado antes de descargar")
    t1, t2, t3 = st.tabs(["Resultado (pasan a Min/Max)", "Casos a revisar", "Sugerir subempaque"])
    t1.dataframe(salida.head(500), width="stretch")
    t2.dataframe(rev, width="stretch")
    t3.caption("Productos donde enviar el empaque completo genera sobrestock (o de PVP alto) y que son aptos para subempaque, "
               "con el mismo SKU ya subempacado en otros locales. Es una propuesta de cambio de maestro: "
               "el Max de la hoja principal usa el SUBEMPAQUE actual del BI.")
    t3.dataframe(sug, width="stretch")

    buf = io.BytesIO()
    exportar_excel(salida, rev, r, buf, sug, p)
    st.download_button("⬇️ Descargar Excel procesado", buf.getvalue(),
                       file_name="Pronostico_cero_procesado.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ======================================================================
# REGLAS DE CÁLCULO (siempre visible, al final de la página)
# ======================================================================
st.divider()
seccion("📘 Reglas que usa el programa para calcular el Min y el Max", "Se actualizan con los parámetros que tienes configurados")

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
2. **Pronóstico lineal:** se mira solo la **primera semana** (días 1 a 7). Como se vende todos los días, un pronóstico normal varía día a día; si se repite, el modelo aún no aprendió.
   Se cuentan los **valores únicos** (valores distintos que aparecen una sola vez) y los **valores repetidos** (valores distintos que aparecen 2 o más veces). Es lineal si hay al menos un valor repetido y los únicos **no superan** a los repetidos
   (`VALORES UNICOS SEM1 ≤ VALORES REPETIDOS SEM1`). Ejemplos: `5,5,5,5,5,5,5` (0 únicos, 1 repetido) → lineal; `3,3,4,4,5,5,6` (1 único, 3 repetidos) → lineal; `2,2,3,4,5,6,6` (3 únicos, 2 repetidos) → no lineal;
   `4.1,3.2,3.4,1.9,4.5,4.4,3.6` (7 únicos) → no lineal. Si desde el día 8 el modelo vuelve a copiar la semana, **no** se considera lineal.
   si el forecast repite los mismos valores o es plano (por ejemplo, la semana 2 copia a la semana 1), el pronóstico no es confiable.

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

Las columnas `TOTAL PRONOSTICO`, `PROMEDIO PRONOSTICO DIA`, `UNICOS`, `VALORES UNICOS SEM1`, `VALORES REPETIDOS SEM1`, `% PROM/EXHI`, `COBERTURA TDF`, `% COBERTURA/EMPQ` y `MOTIVO MIN/MAX` del Excel muestran, fila por fila, por qué pasó a Min/Max.

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

with st.expander("Hojas del Excel que se descarga"):
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
