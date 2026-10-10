"""
app.py  -  Interfaz Streamlit para calcular Min/Max (Pronóstico cero)
Ejecutar:  streamlit run app.py
"""
import io
from dataclasses import asdict

import altair as alt
import pandas as pd
import streamlit as st

from motor_minmax import (ColumnasPronosticoError, Params, exportar_excel, leer_aptos,
                          leer_bi, marcar_en_revision, marcar_revision, procesar, sugerir_subempaque)
from reglas import mostrar_reglas

st.set_page_config(page_title="Min/Max · Pronóstico cero", page_icon="📦", layout="wide")

# ----------------------------------------------------------------------
# Estilo: rojo y blanco como base. Los colores de texto y fondo heredan del tema
# (claro/oscuro); solo el rojo y los acentos son fijos.
# ----------------------------------------------------------------------
ROJO, ROJO_OSC = "#E30613", "#A30410"
C_MINMAX, C_TDF, C_AMBAR, C_VERDE = "#E5414B", "#4B86E6", "#D39A2E", "#1FA391"   # paleta validada
BORDE = "color-mix(in srgb, currentColor 16%, transparent)"
TARJETA = "color-mix(in srgb, currentColor 4%, transparent)"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, .stApp, h1, h2, h3, h4, p, label, li, button, input, textarea {{ font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }}
.block-container {{ padding-top: 1rem; max-width: 1480px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* Encabezado */
.hero {{ background: linear-gradient(115deg, {ROJO} 0%, {ROJO_OSC} 100%); border-radius: 16px;
    padding: 22px 30px; display: flex; justify-content: space-between; align-items: center; gap: 24px;
    box-shadow: 0 8px 24px rgba(227,6,19,.25); flex-wrap: wrap; }}
.hero h1 {{ color:#fff !important; margin:0; font-size:1.75rem; font-weight:800; letter-spacing:-.4px; padding:0; }}
.hero p {{ color:#ffe3e5 !important; margin:4px 0 0 0; font-size:.95rem; }}
.pasos {{ display:flex; gap:10px; flex-wrap:wrap; }}
.paso {{ display:flex; align-items:center; gap:8px; background:rgba(255,255,255,.14); color:#fff;
    padding:7px 14px 7px 8px; border-radius:30px; font-size:.82rem; font-weight:600; }}
.paso b {{ width:22px; height:22px; border-radius:50%; background:rgba(255,255,255,.28); display:flex;
    align-items:center; justify-content:center; font-size:.78rem; }}
.paso.ok {{ background:#fff; color:{ROJO}; }}
.paso.ok b {{ background:{ROJO}; color:#fff; }}

/* Tarjetas de indicadores */
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin:6px 0 4px 0; }}
.kpi {{ background:{TARJETA}; border:1px solid {BORDE}; border-radius:14px; padding:16px 18px; position:relative; overflow:hidden; }}
.kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:5px; background:var(--ac, {ROJO}); }}
.kpi .l {{ font-size:.8rem; font-weight:600; opacity:.7; }}
.kpi .v {{ font-size:1.9rem; font-weight:800; letter-spacing:-.6px; line-height:1.15; margin-top:2px; }}
.kpi .s {{ font-size:.78rem; opacity:.62; margin-top:2px; }}

/* Títulos */
.seccion {{ margin: 22px 0 8px 0; font-size:1.12rem; font-weight:800; letter-spacing:-.2px; }}
.seccion small {{ display:block; font-weight:400; opacity:.62; font-size:.84rem; letter-spacing:0; margin-top:1px; }}
.nota {{ border-left:4px solid {ROJO}; background:{TARJETA}; padding:10px 14px; border-radius:0 10px 10px 0; font-size:.88rem; }}

/* Barra lateral */
section[data-testid="stSidebar"] {{ border-right:1px solid {BORDE}; }}
section[data-testid="stSidebar"] h2 {{ color:{ROJO} !important; font-size:1.15rem; font-weight:800; }}
section[data-testid="stSidebar"] div[data-testid="stExpander"] {{ border-radius:10px; margin-bottom:6px; }}

/* Controles */
div[data-testid="stFileUploader"] section {{ background:rgba(227,6,19,.06); border:2px dashed {ROJO}; border-radius:14px; }}
button[data-testid="stBaseButton-primary"], div[data-testid="stDownloadButton"] button {{
    background:{ROJO}; color:#fff; border:none; border-radius:10px; font-weight:700; box-shadow:0 3px 10px rgba(227,6,19,.3); }}
button[data-testid="stBaseButton-primary"]:hover, div[data-testid="stDownloadButton"] button:hover {{ background:{ROJO_OSC}; color:#fff; border:none; }}
button[data-testid="stBaseButton-primary"] p, div[data-testid="stDownloadButton"] button p {{ color:#fff; }}
button[data-testid="stBaseButton-secondary"] {{ border:1.5px solid {ROJO}; border-radius:10px; font-weight:600; }}
button[data-testid="stBaseButton-secondary"]:hover {{ background:rgba(227,6,19,.10); border-color:{ROJO}; color:{ROJO}; }}
button[data-baseweb="tab"] {{ font-weight:700; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color:{ROJO}; }}
div[data-baseweb="tab-highlight"] {{ background-color:{ROJO}; height:3px; }}
div[data-testid="stDataFrame"] {{ border:1px solid {BORDE}; border-radius:12px; overflow:hidden; }}
div[data-testid="stExpander"] {{ border:1px solid {BORDE}; border-radius:12px; background:{TARJETA}; }}
div[data-testid="stExpander"] summary p {{ font-weight:700; }}
div[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius:14px; }}
hr {{ border-color:{BORDE}; }}
</style>
""", unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Utilidades de presentación
# ----------------------------------------------------------------------
def seccion(titulo, sub=""):
    st.markdown(f'<div class="seccion">{titulo}<small>{sub}</small></div>', unsafe_allow_html=True)


def kpis(items):
    """items: (etiqueta, valor, subtítulo, color)"""
    html = "".join(
        f'<div class="kpi" style="--ac:{c}"><div class="l">{l}</div><div class="v">{v}</div><div class="s">{s}</div></div>'
        for l, v, s, c in items)
    st.markdown(f'<div class="kpis">{html}</div>', unsafe_allow_html=True)


def n(x):
    return f"{int(x):,}".replace(",", ".")


def grafico(titulo, sub, chart):
    with st.container(border=True):
        st.markdown(f"**{titulo}**" + (f"  \n<span style='opacity:.62;font-size:.82rem'>{sub}</span>" if sub else ""),
                    unsafe_allow_html=True)
        st.altair_chart(chart, width="stretch")


def barras_h(df, cat, val, color=None, escala=None, alto=None, titulo_val="Filas", orden="-x"):
    """Barras horizontales; el valor va en la etiqueta del eje (se lee igual en modo claro y oscuro) y en el tooltip."""
    df = df.copy()
    df["_et"] = df[cat].astype(str) + "  ·  " + df[val].map(lambda v: f"{v:,.0f}".replace(",", "."))
    if isinstance(orden, list):
        orden = [df.loc[df[cat] == o, "_et"].iloc[0] for o in orden]
    alto = alto or max(120, 34 * len(df) + 20)
    enc_color = (alt.Color(f"{color}:N", scale=escala, legend=alt.Legend(title=None, orient="bottom"))
                 if color else alt.value(C_MINMAX))
    return alt.Chart(df).mark_bar(cornerRadiusEnd=4, size=20).encode(
        y=alt.Y("_et:N", sort=orden, title=None, axis=alt.Axis(labelLimit=330)),
        x=alt.X(f"{val}:Q", title=None, axis=alt.Axis(format="~s", grid=True)),
        color=enc_color,
        tooltip=[alt.Tooltip(f"{cat}:N", title="Categoría"), alt.Tooltip(f"{val}:Q", title=titulo_val, format=",")]
    ).properties(height=alto)


ESC_DESTINO = alt.Scale(domain=["Pasa a Min/Max", "Se queda en TDF"], range=[C_MINMAX, C_TDF])
ESC_REV = alt.Scale(domain=["Sí", "Informativo", "No"], range=[C_MINMAX, C_AMBAR, C_VERDE])


# ----------------------------------------------------------------------
# Valores iniciales de los parámetros (deben ser los que se ven al abrir la app)
# ----------------------------------------------------------------------
_P0 = Params()
DEFAULTS = {
    "dias_transcurridos": 5, "factor_prom_exhi": 0.55, "pct_empaque_cobertura": 0.50, "umbral_unicos": 5,
    "umbral_dg_exhi": 2.0, "usar_frec_efectiva": False, "dias_cobertura_max": 0.0,
    "umbral_venta_prom_dia": 1.0, "sobrestock_dias": 20.0, "consumo_bajo_exhi": 0.5,
    "pct_exhi_en_cobertura": 0.80, "factor_consumo_exhi": 3.0, "sub_dias_venta_empaque": 12.0,
    "pvp_alto": 5.0, "exigir_pvp_alto": True, "exigir_apto_subempaque": True, "min_empaque_sugerir_sub": 7,
    "min_locales_con_sub": 10, "familias_txt": "\n".join(_P0.familias_no_subempacar),
    "excl_txt": "", "extra_txt": "",
}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(f"p_{_k}", _v)


def _restablecer():
    for k, v in DEFAULTS.items():
        st.session_state[f"p_{k}"] = v


def num(label, clave, mn, mx, help, step=None, fmt=None):
    d = DEFAULTS[clave]
    kw = dict(min_value=mn, max_value=mx, key=f"p_{clave}", help=help)
    if step is not None:
        kw["step"] = step
    if fmt:
        kw["format"] = fmt
    return st.number_input(label, **kw) if isinstance(d, (int, float)) else None


# ---------------- Barra lateral ----------------
with st.sidebar:
    st.header("Parámetros")
    st.caption("Cada grupo se abre y se cierra por separado. El signo ❓ explica cada parámetro.")
    st.button("↺ Restablecer valores iniciales", on_click=_restablecer, width="stretch")

    p = Params()
    with st.expander("1 · Consumo", expanded=True):
        p.dias_transcurridos = num(
            "Días de consumo transcurridos", "dias_transcurridos", 1, 31,
            "Número de días del mes que han pasado. El BI entrega el consumo ACUMULADO del mes "
            "(columna CONSUMOS ACU) y el programa lo divide para este número para obtener el "
            "CONSUMO DIA. Ejemplo: si hoy es 7 de octubre y el BI llega hasta ayer, son 6 días. "
            "Cámbialo cada vez que descargues el BI.")

    with st.expander("2 · Qué pasa de TDF a Min/Max"):
        p.factor_prom_exhi = num(
            "Regla 3 · Promedio diario del pronóstico menor a (% de la Exhibición)", "factor_prom_exhi", 0.05, 3.0,
            "Primera mitad de la condición de cambio. El promedio diario del pronóstico (suma de los días ÷ días de pronóstico) "
            "debe ser menor a este porcentaje de la Exhibición del local. 0.55 = 55 %. Por sí sola NO cambia el método: "
            "debe cumplirse JUNTO con la regla 4 (cobertura del empaque).", step=0.05, fmt="%.2f")
        p.pct_empaque_cobertura = num(
            "Regla 4 · Promedio × (FREC + Dias SS) menor a (% del empaque final)", "pct_empaque_cobertura", 0.05, 3.0,
            "Segunda mitad de la condición. Se calcula promedio diario del pronóstico × (días de frecuencia de despacho + días de stock "
            "de seguridad). Si ese forecast NO cubre ni este porcentaje del empaque final (0.50 = la mitad), y además se cumple la regla 3, "
            "el producto pasa a Min/Max. Si SÍ lo cubre, se queda en TDF. Los Dias SS se usan solo para esta decisión (en TDF), no para "
            "calcular el Min ni el Max.", step=0.05, fmt="%.2f")
        p.umbral_unicos = num(
            "Pronóstico lineal: valores únicos en los 12 días menor o igual a", "umbral_unicos", 0, 12,
            "También pasa a Min/Max el producto con pronóstico LINEAL: el modelo todavía no aprendió y repite valores. "
            "Se cuentan los valores únicos de los 12 días (los que aparecen una sola vez; la columna UNICOS). Con 5 son lineales los que tienen "
            "menos de 6 valores únicos, es decir, la mayoría de los 12 días se repite. Por eso la revisión se hace sobre los 12 días. "
            "Excepción: si el modelo solo copió la semana (los días 8 a 12 son iguales a los días 1 a 5), se juzga solo la primera semana: "
            "es lineal si los valores únicos no superan a los repetidos. Así una semana normal que se copia no cuenta como lineal.")

    with st.expander("3 · Cálculo del Min"):
        p.umbral_dg_exhi = num(
            "Exhibición cubre menos de (días)", "umbral_dg_exhi", 0.5, 10.0,
            "Regla B del Min. Si los días que cubre la exhibición (Exhi ÷ consumo diario) son menos que "
            "este valor, el Min sube a cubrir la frecuencia de despacho.", step=0.5)
        p.usar_frec_efectiva = st.checkbox(
            "Usar el mayor intervalo real entre despachos", key="p_usar_frec_efectiva",
            help="Apagado (recomendado): se usa FREC ENTRE DESP tal como viene del BI (promedio de días entre "
                 "despachos). Encendido: se usa el hueco MÁS LARGO entre despachos según los días "
                 "LUNES…DOMINGO. Ejemplo: despacha Mar-Sáb-Dom; el BI dice 2 días, pero entre Mar y Sáb pasan 4. "
                 "También afecta el filtro del grupo 2.")

    with st.expander("4 · Cálculo del Max"):
        p.dias_cobertura_max = num(
            "Cobertura adicional del Max (días)", "dias_cobertura_max", 0.0, 60.0,
            "0 = desactivado (recomendado): Max = Min + SUBEMPAQUE, o Min + EMPAQUE÷2 si no tiene subempaque. "
            "Si pones un número N mayor que 0, el incremento sobre el Min sube hasta cubrir N días de "
            "consumo, en múltiplos del incremento mínimo de despacho.", step=0.5)

    with st.expander("5 · Diagnóstico del pronóstico"):
        p.umbral_venta_prom_dia = num(
            "Pronóstico insuficiente si promedio diario < (u/día)", "umbral_venta_prom_dia", 0.0, 10.0,
            "Solo informativo (columna DIAG PRONOSTICO). Si el pronóstico promedio por día "
            "(TOTAL PRONOSTICO ÷ días de pronóstico) es menor a este valor, se marca como 'insuficiente'.")

    with st.expander("6 · Hoja REVISAR"):
        st.caption("Trae 3 casos: inventario negativo, consumo muy superior a la exhibición y sobre stock crítico.")
        p.sobrestock_dias = num(
            "Sobre stock crítico: cobertura del Max mayor a (días)", "sobrestock_dias", 1.0, 730.0,
            "Se envía a REVISAR si el Max cubre más de estos días de consumo (Max ÷ CONSUMO DIA). "
            "Si el producto no tiene consumo en el mes, no se marca.")
        p.consumo_bajo_exhi = num(
            "Sobrestock por cubrir exhibición: corte de consumo (u/día)", "consumo_bajo_exhi", 0.05, 5.0,
            "Los casos de sobre stock causados por cubrir la exhibición se muestran en REVISAR (informativo) en dos categorías: "
            "consumo diario menor o igual a este valor, y consumo diario mayor a este valor.", step=0.05, fmt="%.2f")
        p.pct_exhi_en_cobertura = num(
            "Sobre stock explicado por la Exhibición: Exhi cubre ≥ (% de los días del Max)", "pct_exhi_en_cobertura", 0.1, 1.0,
            "Si los días que cubre la exhibición (Exhi ÷ CONSUMO DIA) son al menos este porcentaje de los días que cubre el Max, "
            "el exceso de stock se debe a la exhibición del local y NO se envía a REVISAR. 0.80 = 80 %.", step=0.05, fmt="%.2f")
        p.factor_consumo_exhi = num(
            "Incongruencia: consumo diario ≥ (veces la Exhibición)", "factor_consumo_exhi", 1.0, 20.0,
            "Se envía a REVISAR si el CONSUMO DIA es esta cantidad de veces la Exhi o más. Con 3, el consumo diario triplica la exhibición.",
            step=0.5)

    with st.expander("7 · Sugerencias de subempaque"):
        st.caption("Se sugiere subempacar solo para evitar sobrestock o cuando el producto es de PVP alto.")
        p.sub_dias_venta_empaque = num(
            "Sobrestock: el local tarda más de (días) en vender un empaque completo", "sub_dias_venta_empaque", 1.0, 365.0,
            "Días que tarda el local en vender UN empaque completo = EMPAQUE ÷ CONSUMO DIA. Si tarda más que este número, "
            "enviar el empaque completo genera sobrestock y el producto es candidato a subempacar. "
            "Ejemplo: empaque de 12 con consumo de 0.2 u/día tarda 60 días. Si el producto no tuvo consumo en el mes, "
            "también cuenta como sobrestock. Bajar el valor sugiere más productos.", step=1.0)
        p.pvp_alto = num(
            "PVP alto: precio de venta ≥", "pvp_alto", 0.0, 1000.0,
            "Precio de venta al público (columna PVP del BI) a partir del cual un producto se considera de PVP alto. "
            "Con 'Exigir PVP alto' activado, un producto con PVP menor a este valor NUNCA se sugiere para subempaque, "
            "aunque tenga sobrestock. Con 5.00, un producto de 1.00 queda fuera.", step=0.5)
        p.exigir_pvp_alto = st.checkbox(
            "Exigir PVP alto para sugerir subempaque", key="p_exigir_pvp_alto",
            help="Activado (recomendado): solo se sugieren productos con PVP mayor o igual al valor de arriba. "
                 "Desactivado: basta el sobrestock, y el PVP alto solo sirve como criterio adicional.")
        p.exigir_apto_subempaque = st.checkbox(
            "Exigir que el producto sea apto para subempaque", key="p_exigir_apto_subempaque",
            help="Un producto es apto si en el maestro de productos (archivo 2) su columna 'Apto para PTL' dice 'Si'. "
                 "Si dice 'No', nunca se sugiere subempacarlo. Si no cargas el maestro, se asume 'Si' para todos y no se bloquea nada.")
        p.min_empaque_sugerir_sub = num(
            "Solo si EMPAQUE ≥ (unidades)", "min_empaque_sugerir_sub", 1, 100,
            "Solo se sugiere subempacar productos cuyo empaque tenga al menos esta cantidad de unidades.")
        p.min_locales_con_sub = num(
            "El SKU debe estar subempacado en al menos N locales", "min_locales_con_sub", 1, 50,
            "Se sugiere subempacar un producto en un local solo si el mismo SKU ya está subempacado "
            "en al menos N locales del BI (prueba de que se puede subempacar). Esa evidencia define también el "
            "valor de subempaque sugerido: el más común entre los locales donde ya está subempacado.")
        fam = st.text_area(
            "Familias que NUNCA se subempacan (una por línea)", key="p_familias_txt",
            help="Productos de estas familias jamás aparecen en las sugerencias de subempaque. "
                 "Por defecto: CERVEZAS, CERVEZAS SIN ALCOHOL y AGUAS.")
        p.familias_no_subempacar = tuple(x.strip().upper() for x in fam.splitlines() if x.strip())
        excl = st.text_area(
            "ESTADISTICOS que NO se deben subempacar (uno por línea)", key="p_excl_txt",
            help="Códigos de ESTADISTICO específicos que nunca se subempacan, aunque cumplan los criterios. "
                 "Ejemplo: 243138001. Escribe un código por línea.")
        p.skus_no_subempacar = tuple(int(x) for x in excl.split() if x.strip().isdigit())
        extra = st.text_area(
            "SKUs subempacables aunque el BI no los muestre subempacados (uno por línea)", key="p_extra_txt",
            help="Códigos de ESTADISTICO que sabes que se pueden subempacar aunque en ningún local "
                 "figuren con subempaque en el BI.")
        p.skus_sub_extra = tuple(int(x) for x in extra.split() if x.split() and x.strip().isdigit())


# ----------------------------------------------------------------------
# Cálculo (en caché: filtrar tablas no vuelve a procesar el BI)
# ----------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=3)
def calcular(bytes_bi, bytes_ap, params, cols_pronostico):
    p = Params(**params)
    bi = leer_bi(io.BytesIO(bytes_bi))
    aptos = leer_aptos(io.BytesIO(bytes_ap)) if bytes_ap else None
    salida, r = procesar(bi, aptos, p, cols_pronostico=list(cols_pronostico) if cols_pronostico else None)
    rev = marcar_revision(salida, p)
    salida = marcar_en_revision(salida, rev)
    sug = sugerir_subempaque(salida, p)
    r.pop("filas_con_aviso_revisar", None)
    r["sugerencias_subempaque"] = len(sug)
    r["filas_en_hoja_REVISAR"] = len(rev)
    r["revisar_prioridad_alta"] = int((rev["PRIORIDAD"] == "Prioridad ALTA").sum())
    buf = io.BytesIO()
    exportar_excel(salida, rev, r, buf, sug, p)
    return salida, r, rev, sug, buf.getvalue()


@st.cache_data(show_spinner=False, max_entries=1)
def columnas_bi(bytes_bi):
    return [str(c) for c in leer_bi(io.BytesIO(bytes_bi)).columns]


def tabla_filtrada(df, clave, cols_defecto, extra_filtros=None, cfg=None, max_filas=2000):
    """Muestra filtros (local, familia, búsqueda) + tabla con columnas esenciales."""
    f = st.columns([1.2, 1.2, 1.6, 1])
    locales = sorted(df["Local"].dropna().unique().tolist()) if "Local" in df else []
    fams = sorted(df["FAMILIA"].dropna().astype(str).unique().tolist()) if "FAMILIA" in df else []
    s_loc = f[0].multiselect("Local", locales, key=f"{clave}_loc", placeholder="Todos")
    s_fam = f[1].multiselect("Familia", fams, key=f"{clave}_fam", placeholder="Todas")
    q = f[2].text_input("Buscar en estadístico o descripción", key=f"{clave}_q", placeholder="Ej.: 243138 o ARROZ")
    todas = f[3].toggle("Todas las columnas", key=f"{clave}_all")
    out = df
    if extra_filtros:
        for col, etiqueta in extra_filtros:
            vals = [v for v in out[col].dropna().unique().tolist()]
            sel = st.multiselect(etiqueta, sorted(vals, key=str), key=f"{clave}_{col}", placeholder="Todos")
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
    cols = [c for c in out.columns if not str(c).startswith("_")] if todas else [c for c in cols_defecto if c in out.columns]
    vista = out[cols].copy()
    vista.columns = [c.strftime("%d-%m") if hasattr(c, "strftime") else c for c in vista.columns]
    st.caption(f"{n(len(out))} filas" + (f" (se muestran las primeras {n(max_filas)}; descarga el Excel para verlas todas)"
                                         if len(out) > max_filas else ""))
    st.dataframe(vista.head(max_filas), hide_index=True, width="stretch", height=430, column_config=cfg or {})


# ----------------------------------------------------------------------
# Encabezado + pasos
# ----------------------------------------------------------------------
f_bi_estado = st.session_state.get("f_bi") is not None
paso_cls = lambda ok: "paso ok" if ok else "paso"
st.markdown(f"""
<div class="hero">
  <div>
    <h1>Min / Max por local · Pronóstico cero</h1>
    <p>Decide qué productos pasan de TDF a Min/Max y calcula su mínimo y máximo.</p>
  </div>
  <div class="pasos">
    <div class="{paso_cls(f_bi_estado)}"><b>1</b>Cargar el BI</div>
    <div class="{paso_cls(f_bi_estado)}"><b>2</b>Ajustar parámetros</div>
    <div class="{paso_cls(f_bi_estado)}"><b>3</b>Revisar y descargar</div>
  </div>
</div>
""", unsafe_allow_html=True)

# Botón de reglas (ocultas por defecto; cada bloque se minimiza por separado)
st.session_state.setdefault("ver_reglas", False)
st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
b1, b2 = st.columns([1, 3])
if b1.button("Ocultar las reglas de cálculo" if st.session_state["ver_reglas"] else "📘 Ver las reglas de cálculo",
             key="btn_reglas", type="secondary", width="stretch"):
    st.session_state["ver_reglas"] = not st.session_state["ver_reglas"]
    st.rerun()
if st.session_state["ver_reglas"]:
    seccion("Reglas que usa el programa", "Se actualizan con los parámetros que tienes configurados. Minimiza cada bloque con su flecha.")
    mostrar_reglas(p)

# ---------------- Carga ----------------
seccion("Carga de archivos", "Sube el BI y, opcionalmente, el maestro de productos aptos")
c1, c2 = st.columns(2)
f_bi = c1.file_uploader("1) Excel del BI (obligatorio)", type=["xlsx"], key="f_bi")
f_ap = c2.file_uploader("2) Maestro de productos (columnas 'Estadístico' y 'Apto para PTL')", type=["xlsx"], key="f_ap")

if not f_bi:
    st.markdown('<div class="nota">Sube el Excel del BI para ver el resumen, los casos a revisar y descargar el archivo procesado. '
                'Los parámetros de la izquierda ya traen sus valores iniciales.</div>', unsafe_allow_html=True)
    st.stop()

bytes_bi = f_bi.getvalue()
bytes_ap = f_ap.getvalue() if f_ap else None
params = asdict(p)
cols_man = None
try:
    with st.spinner("Procesando el BI…"):
        salida, r, rev, sug, xlsx = calcular(bytes_bi, bytes_ap, params, cols_man)
except ColumnasPronosticoError as e:
    st.error(f"{e} Elige abajo las columnas del pronóstico diario.")
    elegidas = st.multiselect(
        "Selecciona las columnas de pronóstico diario (entre 7 y 12), en orden",
        options=list(e.todas), format_func=str,
        help="Son las columnas con la venta pronosticada por día (una por cada uno de los próximos días).")
    if not (7 <= len(elegidas) <= 12):
        st.info(f"Seleccionadas: {len(elegidas)}. Elige entre 7 y 12 columnas.")
        st.stop()
    try:
        with st.spinner("Procesando el BI…"):
            salida, r, rev, sug, xlsx = calcular(bytes_bi, bytes_ap, params, tuple(elegidas))
    except ValueError as e2:
        st.error(str(e2))
        st.stop()
except ValueError as e:
    st.error(str(e))
    st.stop()

if r["dias_de_pronostico"] < 12:
    st.info(f"El BI trae **{r['dias_de_pronostico']} días de pronóstico** (no 12). El promedio diario se calcula dividiendo para "
            f"{r['dias_de_pronostico']}. Columnas usadas: {r['columnas_pronostico_usadas']}.")
if not f_ap:
    st.info("Sin maestro de productos: se asumió APTO = 'Si' para todos. Afecta la regla B del Min y las "
            "sugerencias de subempaque (no se descarta ningún producto por no ser apto).")

total_bi = r["segmento_total_BI"]
n_mm = r["filas_resultado"]
n_rev_si = int((salida["EN REVISAR"] == "Sí").sum())
n_info = int((salida["EN REVISAR"] == "Informativo").sum())
dias_p = r["dias_de_pronostico"]

# Descarga destacada
d1, d2 = st.columns([3, 1.4])
d1.markdown(f'<div class="nota"><b>{n(n_mm)}</b> de <b>{n(total_bi)}</b> filas del BI pasan de TDF a Min/Max '
            f'({n_mm / max(total_bi, 1):.1%}). Revisa las pestañas y descarga el Excel con las 4 hojas.</div>',
            unsafe_allow_html=True)
d2.download_button("⬇️ Descargar Excel procesado", xlsx, file_name="Pronostico_cero_procesado.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

t_res, t_cla, t_rev, t_sub, t_det = st.tabs(["Resumen", "Clasificación", "Revisar", "Subempaque", "Resultado"])

# ============================ RESUMEN ============================
with t_res:
    kpis([
        ("Filas del BI", n(total_bi), "Local × estadístico en TDF", C_TDF),
        ("Pasan a Min/Max", n(n_mm), f"{n_mm / max(total_bi, 1):.1%} del BI", C_MINMAX),
        ("Min = Exhibición", n(r["regla_C"]), f"{r['regla_C'] / max(n_mm, 1):.0%} de los que pasan", C_VERDE),
        ("Min ajustado (A + B)", n(r["regla_A"] + r["regla_B"]), "Consumo o exhibición corta", C_AMBAR),
        ("Casos a revisar", n(n_rev_si), f"{n(n_info)} más son informativos", ROJO),
    ])

    seg = pd.DataFrame({
        "Segmento": ["Pronóstico cero", "Pronóstico lineal", "Reglas 3 + 4 (promedio bajo)",
                     "Rescatado: el forecast cubre el empaque", "Pronóstico normal"],
        "Filas": [r["segmento_1_pasa_pronostico_cero"], r["segmento_2_pasa_pronostico_lineal"],
                  r["segmento_3_pasa_prom_exhi_y_cobertura_empaque"], r["segmento_4_tdf_rescatado_por_cobertura_empaque"],
                  r["segmento_5_tdf_pronostico_normal"]],
        "Destino": ["Pasa a Min/Max"] * 3 + ["Se queda en TDF"] * 2})
    g1, g2 = st.columns([1.7, 1])
    with g1:
        grafico("Qué pasa con cada fila del BI", "Cuántas pasan a Min/Max y por qué vía; el resto se queda en TDF.",
                barras_h(seg, "Segmento", "Filas", "Destino", ESC_DESTINO, orden=list(seg["Segmento"]), alto=250))
    with g2:
        dona = pd.DataFrame({"Destino": ["Pasa a Min/Max", "Se queda en TDF"], "Filas": [n_mm, total_bi - n_mm]})
        dona["Porcentaje"] = dona["Filas"] / max(total_bi, 1)
        ch = alt.Chart(dona).mark_arc(innerRadius=58, stroke="rgba(0,0,0,0)").encode(
            theta="Filas:Q", color=alt.Color("Destino:N", scale=ESC_DESTINO, legend=alt.Legend(title=None, orient="bottom")),
            tooltip=["Destino:N", alt.Tooltip("Filas:Q", format=","), alt.Tooltip("Porcentaje:Q", format=".1%")]).properties(height=250)
        grafico("Proporción del BI", "Destino de las filas", ch)

    g3, g4, g5 = st.columns(3)
    with g3:
        rm = pd.DataFrame({"Regla": ["C · Min = Exhibición", "B · Exhibición corta", "A · Consumo > Exhi"],
                           "Filas": [r["regla_C"], r["regla_B"], r["regla_A"]]})
        grafico("Cómo se calculó el Min", "Regla aplicada a cada fila que pasa a Min/Max.",
                barras_h(rm, "Regla", "Filas", orden=list(rm["Regla"]), alto=150))
    with g4:
        vc = salida["_regla_max"].map(lambda x: "Min + subempaque" if "SUBEMPAQUE" in str(x) else "Min + empaque ÷ 2").value_counts()
        vc = vc.rename_axis("Max").reset_index(name="Filas")
        grafico("Cómo se calculó el Max", "Con subempaque del BI o con la mitad del empaque.",
                barras_h(vc, "Max", "Filas", alto=150))
    with g5:
        dg = salida["DIAG PRONOSTICO"].value_counts().rename_axis("Diagnóstico").reset_index(name="Filas")
        grafico("Calidad del pronóstico", "Diagnóstico de las filas que pasan.", barras_h(dg, "Diagnóstico", "Filas", alto=190))

    # Top locales por cantidad de filas, apiladas por estado de revisión
    sal = salida.copy()
    sal["Local "] = sal["Local"].astype(str) + " · " + sal["DESIGNACION"].astype(str).str.title()
    top_loc = sal["Local "].value_counts().head(12).index.tolist()
    dl = sal[sal["Local "].isin(top_loc)].groupby(["Local ", "EN REVISAR"]).size().reset_index(name="Filas")
    ch_l = alt.Chart(dl).mark_bar(cornerRadiusEnd=3, stroke="rgba(255,255,255,0)", strokeWidth=2).encode(
        y=alt.Y("Local :N", sort=top_loc, title=None, axis=alt.Axis(labelLimit=240)),
        x=alt.X("Filas:Q", title=None, axis=alt.Axis(format="~s")),
        color=alt.Color("EN REVISAR:N", scale=ESC_REV, legend=alt.Legend(title="En revisar", orient="bottom")),
        order=alt.Order("EN REVISAR:N", sort="descending"),
        tooltip=[alt.Tooltip("Local :N", title="Local"), alt.Tooltip("EN REVISAR:N", title="En revisar"),
                 alt.Tooltip("Filas:Q", format=",")]).properties(height=330)
    top_fam = salida["FAMILIA"].astype(str).value_counts().head(12).rename_axis("Familia").reset_index(name="Filas")
    h1, h2 = st.columns(2)
    with h1:
        grafico("Locales con más productos en Min/Max", "Top 12, según cuántos de sus productos requieren revisión.", ch_l)
    with h2:
        grafico("Familias con más productos en Min/Max", "Top 12 familias.",
                barras_h(top_fam, "Familia", "Filas", alto=330))

# ============================ CLASIFICACIÓN ============================
with t_cla:
    seccion("Por qué cada fila pasó a Min/Max", "Distribución por motivo y por regla de cálculo")
    mot = salida["MOTIVO MIN/MAX"].value_counts().rename_axis("Motivo").reset_index(name="Filas")
    mot["%"] = mot["Filas"] / max(n_mm, 1)
    st.dataframe(mot, hide_index=True, width="stretch", column_config={
        "Filas": st.column_config.NumberColumn(format="%d"),
        "%": st.column_config.ProgressColumn("Proporción", format="percent", min_value=0.0, max_value=1.0)})

    cA, cB = st.columns(2)
    with cA:
        # Pronóstico promedio diario vs exhibición: ayuda a ver por qué entran por reglas 3 y 4
        mu = salida[["% PROM/EXHI"]].dropna() if "% PROM/EXHI" in salida else pd.DataFrame()
        if len(mu):
            mu = mu.assign(v=mu["% PROM/EXHI"].clip(upper=2.0))
            hist = alt.Chart(mu).mark_bar(color=C_MINMAX, cornerRadiusEnd=2).encode(
                x=alt.X("v:Q", bin=alt.Bin(maxbins=24), title="Promedio del pronóstico ÷ Exhibición (tope 200 %)", axis=alt.Axis(format="%")),
                y=alt.Y("count():Q", title="Filas"),
                tooltip=[alt.Tooltip("count():Q", title="Filas", format=",")]).properties(height=260)
            regla = alt.Chart(pd.DataFrame({"x": [p.factor_prom_exhi]})).mark_rule(color=C_AMBAR, strokeDash=[6, 4], size=2).encode(x="x:Q")
            grafico("Promedio del pronóstico frente a la exhibición", f"La línea marca la regla 3 ({p.factor_prom_exhi:.0%}).", hist + regla)
    with cB:
        cb = salida["CONSUMO DIA"].astype(float)
        cov = (salida["Max"] / cb.where(cb > 0)).dropna()
        if len(cov):
            dcv = pd.DataFrame({"v": cov.clip(upper=120)})
            hist2 = alt.Chart(dcv).mark_bar(color=C_TDF, cornerRadiusEnd=2).encode(
                x=alt.X("v:Q", bin=alt.Bin(maxbins=30), title="Días que cubre el Max con el consumo actual (tope 120)"),
                y=alt.Y("count():Q", title="Filas"),
                tooltip=[alt.Tooltip("count():Q", title="Filas", format=",")]).properties(height=260)
            lim = alt.Chart(pd.DataFrame({"x": [p.sobrestock_dias]})).mark_rule(color=C_MINMAX, strokeDash=[6, 4], size=2).encode(x="x:Q")
            grafico("Cobertura del Max", f"La línea marca el sobre stock crítico ({p.sobrestock_dias:g} días).", hist2 + lim)

# ============================ REVISAR ============================
with t_rev:
    n_alta = int((rev["PRIORIDAD"] == "Prioridad ALTA").sum())
    n_media = int((rev["PRIORIDAD"] == "Prioridad MEDIA").sum())
    n_inf = int((rev["PRIORIDAD"] == "Informativo").sum())
    kpis([("Prioridad alta", n(n_alta), "Inventario negativo o consumo ≫ exhibición", ROJO),
          ("Prioridad media", n(n_media), "Sobre stock crítico", C_AMBAR),
          ("Informativo", n(n_inf), "Sobrestock por cubrir exhibición", C_TDF),
          ("Total en la hoja", n(len(rev)), "Casos de REVISAR", C_VERDE)])
    if len(rev):
        ac = rev["ACCIÓN PRINCIPAL"].value_counts().rename_axis("Acción").reset_index(name="Casos")
        r1, r2 = st.columns(2)
        with r1:
            grafico("Qué hay que hacer con estos casos", "Acción principal sugerida.", barras_h(ac, "Acción", "Casos", alto=max(150, 40 * len(ac))))
        with r2:
            red = rev.dropna(subset=["REDUCCION MAX"]).groupby(rev["FAMILIA"].astype(str))["REDUCCION MAX"].sum()
            red = red.sort_values(ascending=False).head(10).rename_axis("Familia").reset_index(name="Unidades")
            if len(red):
                grafico("Unidades de Max que se evitarían al subempacar", "Top 10 familias; suma de REDUCCION MAX.",
                        barras_h(red, "Familia", "Unidades", titulo_val="Unidades", alto=max(150, 34 * len(red) + 20)))
            else:
                st.info("Ningún caso de REVISAR reduce el Max con subempaque.")
    seccion("Detalle de los casos", "Filtra por local, familia o prioridad")
    tabla_filtrada(rev, "rev",
                   ["PRIORIDAD", "ACCIÓN PRINCIPAL", "SUGERENCIA A REALIZAR", "Local", "DESIGNACION", "ESTADISTICO",
                    "DESCRIPCION", "FAMILIA", "CONSUMO DIA", "Exhi", "Min", "Max", "COBERTURA MAX (DIAS)",
                    "SUB SUGERIDO", "REDUCCION MAX", "MOTIVOS DE REVISIÓN"],
                   extra_filtros=[("PRIORIDAD", "Prioridad")])

# ============================ SUBEMPAQUE ============================
with t_sub:
    st.markdown('<div class="nota">Productos donde enviar el empaque completo genera sobrestock (o son de PVP alto), son aptos '
                'y el mismo SKU ya está subempacado en otros locales. Es una propuesta de cambio de maestro: el Max de la hoja '
                'principal usa el SUBEMPAQUE actual del BI.</div>', unsafe_allow_html=True)
    if len(sug) == 0:
        st.info("Con los parámetros actuales no hay sugerencias de subempaque.")
    else:
        kpis([("Sugerencias", n(len(sug)), "Local × estadístico", ROJO),
              ("Prioridad alta", n((sug["PRIORIDAD"] == "Prioridad ALTA").sum()), "Sobrestock y PVP alto a la vez", C_MINMAX),
              ("SKUs distintos", n(sug["ESTADISTICO"].nunique()), "Códigos a subempacar", C_TDF),
              ("Reducción de Max", n(pd.to_numeric(sug["REDUCCION VALOR"], errors="coerce").fillna(0).sum()),
               "Unidades menos en total", C_VERDE)])
        s1, s2 = st.columns(2)
        with s1:
            ms = sug["MOTIVO"].str.replace(r"^Sobrestock: ", "", regex=True).value_counts().rename_axis("Motivo").reset_index(name="Sugerencias")
            grafico("Por qué se sugiere", "Motivo de cada sugerencia.", barras_h(ms, "Motivo", "Sugerencias", alto=max(140, 44 * len(ms))))
        with s2:
            fs = sug["FAMILIA"].astype(str).value_counts().head(10).rename_axis("Familia").reset_index(name="Sugerencias")
            grafico("Familias con más sugerencias", "Top 10.", barras_h(fs, "Familia", "Sugerencias", alto=max(140, 34 * len(fs) + 20)))
        tabla_filtrada(sug, "sug",
                       ["PRIORIDAD", "MOTIVO", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA", "PVP", "EMPAQUE",
                        "SUB ACTUAL", "SUB SUGERIDO", "EVIDENCIA", "VALORES EN OTROS LOCALES", "CONSUMO DIA",
                        "DIAS VENDER EMPAQUE", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX"],
                       extra_filtros=[("PRIORIDAD", "Prioridad")])

# ============================ RESULTADO ============================
with t_det:
    seccion("Filas que pasan a Min/Max", "Es la hoja «Pronóstico cero» del Excel. Aquí se muestran las columnas esenciales.")
    tabla_filtrada(salida, "res",
                   ["Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA", "Exhi", "Empq_final", "SUBEMPAQUE",
                    "CONSUMO DIA", "Min", "Max", "MOTIVO MIN/MAX", "EN REVISAR"],
                   extra_filtros=[("EN REVISAR", "En revisar"), ("MOTIVO MIN/MAX", "Motivo")],
                   cfg={"Min": st.column_config.NumberColumn(format="%d"), "Max": st.column_config.NumberColumn(format="%d")})
