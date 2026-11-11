"""Estilo visual compartido por las apps de abastecimiento (Distribución, Min/Max y Verificación de traspasos).

Dirección: herramienta de trabajo diaria para abastecimiento. Una sola pieza fuerte —la franja roja del
encabezado con los pasos— y todo lo demás sobrio: superficies blancas, líneas finas, números tabulares.
Tipografía: Archivo (grotesca de alto rendimiento; ancho semicondensado para títulos y cifras).
"""
import altair as alt
import streamlit as st

# Súbela al cambiar estilo.py o portal.py: las apps comparan este número y recargan los módulos
# (Streamlit Cloud a veces conserva en memoria la versión anterior tras actualizar el repositorio).
VERSION = "2026-11-11.2"

# ---- Marca
ROJO, ROJO_OSC = "#E30613", "#A30410"
# ---- Neutros
TINTA, GRAFITO, NIEBLA_TXT = "#1C2127", "#59626E", "#8C949F"
FONDO, SUPERFICIE, LINEA, LINEA_2, REJILLA = "#F3F4F6", "#FFFFFF", "#DEE2E7", "#C5CBD3", "#EEF0F3"
ROJO_SUAVE = "#FDECED"
# ---- Estados (los mismos colores en KPIs, gráficos y barras)
C_OK, C_ALT, C_BAJO, C_EXT, C_PEND = "#188C7C", "#3A6FD8", "#C7861A", "#D3343F", "#8C949F"
NEUTRO = GRAFITO
# compatibilidad con nombres anteriores
TEXTO, TEXTO_2, TEXTO_3 = TINTA, GRAFITO, NIEBLA_TXT
BORDE, TARJETA = LINEA, SUPERFICIE

FUENTE = "Archivo"
ICONO = {"": "info", "ok": "check_circle", "warn": "warning", "err": "error"}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,100..900&display=swap');
html, body, .stApp, h1, h2, h3, h4, h5, p, label, li, button, input, textarea, [data-testid="stMarkdownContainer"] {{
    font-family:'{FUENTE}', system-ui, -apple-system, 'Segoe UI', sans-serif; }}
.stApp {{ background:{FONDO}; color:{TINTA}; }}
.block-container {{ padding-top:1.4rem; padding-bottom:3rem; max-width:1440px; }}
header[data-testid="stHeader"] {{ background:transparent; }}
h1, h2, h3, h4, h5 {{ color:{TINTA}; font-stretch:87.5%; }}
.ms {{ font-family:'Material Symbols Rounded'; font-weight:400; font-style:normal; font-size:1.15em; line-height:1;
    display:inline-block; vertical-align:-.2em; letter-spacing:normal; text-transform:none; white-space:nowrap;
    -webkit-font-feature-settings:'liga'; font-feature-settings:'liga'; }}

/* ================= Encabezado: franja roja + pasos ================= */
.hero {{ background:{ROJO}; border-radius:10px; padding:26px 32px 24px 32px; display:flex; justify-content:space-between;
    align-items:center; gap:32px; flex-wrap:wrap; position:relative; overflow:hidden; }}
.hero::after {{ content:""; position:absolute; left:0; right:0; bottom:0; height:4px; background:{ROJO_OSC}; }}
.hero h1 {{ color:#fff !important; margin:0; padding:0; font-size:2.05rem; font-weight:800; font-stretch:80%;
    letter-spacing:-.01em; line-height:1.05; }}
.hero p {{ color:rgba(255,255,255,.86) !important; margin:8px 0 0 0; font-size:.95rem; max-width:62ch; line-height:1.45; }}
.pasos {{ display:flex; align-items:flex-start; margin:0; padding:0; list-style:none; }}
.paso {{ display:flex; flex-direction:column; align-items:center; gap:8px; width:118px; position:relative; }}
.paso::before {{ content:""; position:absolute; top:15px; right:50%; width:100%; height:2px; background:rgba(255,255,255,.32); }}
.paso:first-child::before {{ display:none; }}
.paso .nodo {{ width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; z-index:1;
    font-size:.9rem; font-weight:700; font-variant-numeric:tabular-nums; color:rgba(255,255,255,.8);
    background:{ROJO}; border:2px solid rgba(255,255,255,.45); }}
.paso .txt {{ font-size:.78rem; font-weight:600; color:rgba(255,255,255,.75); text-align:center; line-height:1.2; }}
.paso.hecho .nodo {{ background:#fff; border-color:#fff; color:{ROJO}; }}
.paso.hecho::before, .paso.actual::before {{ background:#fff; }}
.paso.actual .nodo {{ background:#fff; border-color:#fff; color:{ROJO}; box-shadow:0 0 0 5px rgba(255,255,255,.28); }}
.paso.hecho .txt, .paso.actual .txt {{ color:#fff; }}

/* ================= KPIs: tarjetas separadas con color ================= */
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin:12px 0 14px 0; }}
.kpi {{ background:{SUPERFICIE}; border:1px solid {LINEA}; border-radius:10px; padding:15px 18px 16px 18px;
    position:relative; overflow:hidden; }}
.kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--ac, {ROJO}); }}
.kpi .l {{ font-size:.8rem; font-weight:600; color:{GRAFITO}; line-height:1.25; }}
.kpi .v {{ font-size:2.1rem; font-weight:700; font-stretch:80%; line-height:1.1; margin-top:6px; color:var(--ac, {TINTA});
    font-variant-numeric:tabular-nums; letter-spacing:-.01em; }}
.kpi .s {{ font-size:.78rem; color:{NIEBLA_TXT}; margin-top:2px; }}

/* ================= Secciones y avisos ================= */
.seccion {{ margin:28px 0 12px 0; font-size:1.2rem; font-weight:700; font-stretch:87.5%; color:{TINTA}; line-height:1.2; }}
.seccion small {{ display:block; font-weight:400; font-stretch:100%; color:{GRAFITO}; font-size:.85rem; margin-top:4px; }}
.nota {{ background:{SUPERFICIE}; border:1px solid {LINEA}; border-left:3px solid {GRAFITO}; padding:11px 16px 11px 14px;
    border-radius:8px; font-size:.88rem; color:{GRAFITO}; display:flex; gap:10px; align-items:flex-start; line-height:1.45; }}
.nota .ms {{ color:{GRAFITO}; font-size:1.25rem; vertical-align:0; }}
.nota b {{ color:{TINTA}; }}
.nota.ok {{ border-left-color:{C_OK}; }} .nota.ok .ms {{ color:{C_OK}; }}
.nota.warn {{ border-left-color:{C_BAJO}; }} .nota.warn .ms {{ color:{C_BAJO}; }}
.nota.err {{ border-left-color:{ROJO}; }} .nota.err .ms {{ color:{ROJO}; }}

/* ================= Barra de reparto (módulo 2) ================= */
.flujo {{ display:flex; gap:2px; border-radius:8px; overflow:hidden; margin:6px 0 4px 0; }}
.flujo div {{ padding:10px 12px; color:#fff; font-size:.8rem; font-weight:700; white-space:nowrap; overflow:hidden;
    text-overflow:ellipsis; font-variant-numeric:tabular-nums; }}
.leyenda {{ display:flex; gap:20px; flex-wrap:wrap; font-size:.82rem; color:{GRAFITO}; margin-top:8px; }}
.leyenda b {{ color:{TINTA}; font-variant-numeric:tabular-nums; }}
.leyenda span::before {{ content:""; display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:7px; background:var(--c); }}

/* ================= Barra lateral ================= */
section[data-testid="stSidebar"] {{ background:{SUPERFICIE}; border-right:1px solid {LINEA}; }}
section[data-testid="stSidebar"] h2 {{ color:{TINTA} !important; font-size:1.05rem; font-weight:700; padding-top:.4rem; }}
section[data-testid="stSidebar"] h4 {{ color:{NIEBLA_TXT} !important; font-size:.8rem; font-weight:600; margin-bottom:2px; }}
section[data-testid="stSidebar"] hr {{ margin:14px 0 6px 0; }}
.st-key-menu_apps {{ gap:2px !important; }}
.st-key-menu_apps a, .st-key-menu_apps button {{ justify-content:flex-start !important; border:none !important;
    background:transparent !important; box-shadow:none !important; border-radius:6px !important; color:{GRAFITO} !important;
    font-weight:500 !important; padding:7px 10px !important; min-height:0 !important; }}
.st-key-menu_apps a > div, .st-key-menu_apps button > div, .st-key-menu_apps a > div > span, .st-key-menu_apps button > div > span,
.st-key-menu_apps [data-testid="stMarkdownContainer"], .st-key-menu_apps [data-testid="stTooltipHoverTarget"] {{
    justify-content:flex-start !important; width:100% !important; text-align:left !important; }}
.st-key-menu_apps p {{ text-align:left !important; display:flex; align-items:center; gap:10px; }}
.st-key-menu_apps p span[role="img"] {{ font-size:1.15rem; vertical-align:middle !important; }}
.st-key-menu_apps a:hover {{ background:{FONDO} !important; color:{TINTA} !important; }}
.st-key-menu_apps a p, .st-key-menu_apps button p {{ color:inherit !important; }}
.st-key-menu_apps [class*="st-key-app_pendiente"] button:disabled {{ background:transparent !important;
    color:{NIEBLA_TXT} !important; box-shadow:none !important; opacity:1 !important; cursor:not-allowed; }}
.st-key-menu_apps .st-key-app_actual button:disabled {{ background:{ROJO_SUAVE} !important; color:{ROJO_OSC} !important; opacity:1 !important;
    font-weight:600 !important; box-shadow:inset 3px 0 0 {ROJO} !important; border-radius:0 6px 6px 0 !important; }}
section[data-testid="stSidebar"] div[data-testid="stExpander"] {{ box-shadow:none; }}

/* ================= Carga de archivos ================= */
div[data-testid="stFileUploader"] label p {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:{TINTA};
    font-weight:600; font-size:.92rem; }}
div[data-testid="stFileUploader"] section {{ background:{SUPERFICIE}; border:1.5px dashed {LINEA_2}; border-radius:8px;
    min-height:92px; align-items:center; transition:border-color .15s, background .15s; }}
div[data-testid="stFileUploader"] section:hover {{ border-color:{ROJO}; background:#FFFBFB; }}
div[data-testid="stFileUploader"] section button {{ background:{ROJO}; color:#fff; border:none; border-radius:6px; font-weight:600; }}
div[data-testid="stFileUploader"] section button:hover {{ background:{ROJO_OSC}; color:#fff; }}
div[data-testid="stFileUploader"] section button p, div[data-testid="stFileUploader"] section button span {{ color:#fff; }}
div[data-testid="stFileUploaderFile"] {{ background:{FONDO}; border-radius:6px; padding:4px 8px; }}

/* ================= Botones ================= */
button[data-testid="stBaseButton-primary"], div[data-testid="stDownloadButton"] button {{
    background:{ROJO}; color:#fff; border:none; border-radius:8px; font-weight:600; min-height:44px; }}
button[data-testid="stBaseButton-primary"]:hover, div[data-testid="stDownloadButton"] button:hover {{
    background:{ROJO_OSC}; color:#fff; border:none; }}
button[data-testid="stBaseButton-primary"] p, div[data-testid="stDownloadButton"] button p,
div[data-testid="stDownloadButton"] button span {{ color:#fff; }}
button[data-testid="stBaseButton-secondary"] {{ background:{SUPERFICIE}; border:1px solid {LINEA_2}; border-radius:8px;
    font-weight:600; color:{TINTA}; }}
button[data-testid="stBaseButton-secondary"]:hover {{ border-color:{ROJO}; color:{ROJO}; }}
.st-key-plantilla button {{ background:{SUPERFICIE} !important; color:{TINTA} !important; border:1px solid {LINEA_2} !important;
    min-height:40px !important; }}
.st-key-plantilla button p, .st-key-plantilla button span {{ color:inherit !important; }}
.st-key-plantilla button:hover {{ border-color:{ROJO} !important; color:{ROJO} !important; background:{SUPERFICIE} !important; }}
button:focus-visible, a:focus-visible {{ outline:2px solid {ROJO} !important; outline-offset:2px; }}

/* ================= Selector de módulo ================= */
div[data-testid="stButtonGroup"] [role="radiogroup"] {{ background:#E7E9ED; border-radius:9px; padding:3px; display:inline-flex; gap:2px; }}
div[data-testid="stButtonGroup"] button {{ border:none !important; border-radius:7px !important; font-weight:600;
    padding:7px 18px; background:transparent; color:{GRAFITO}; min-height:38px; }}
div[data-testid="stButtonGroup"] button:hover {{ color:{TINTA}; background:rgba(255,255,255,.55); }}
div[data-testid="stButtonGroup"] button[aria-checked="true"] {{ background:{SUPERFICIE} !important;
    color:{TINTA} !important; box-shadow:0 1px 2px rgba(28,33,39,.12), 0 1px 1px rgba(28,33,39,.06); }}
div[data-testid="stButtonGroup"] button[aria-checked="true"] p {{ color:{TINTA} !important; }}
div[data-testid="stButtonGroup"] button[aria-checked="true"] [data-testid="stIconMaterial"] {{ color:{ROJO}; }}
div[data-testid="stButtonGroup"] [data-testid="stIconMaterial"] {{ font-size:1.15rem; }}

/* ================= Pestañas: pastillas, la activa en rojo =================
   Streamlit nuevo usa role="tablist"/stTab; las versiones anteriores, baseweb. Se cubren ambas. */
div[data-baseweb="tab-list"], [data-testid="stTabs"] [role="tablist"] {{ gap:4px; background:{SUPERFICIE};
    border:1px solid {LINEA}; border-radius:10px; padding:4px; margin-top:14px; width:fit-content; max-width:100%;
    overflow-x:auto; }}
button[data-baseweb="tab"], [data-testid="stTab"] {{ border-radius:7px; padding:8px 16px !important; height:auto;
    margin:0 !important; transition:background .15s; }}
button[data-baseweb="tab"] p, [data-testid="stTab"] p {{ font-weight:600; color:{GRAFITO}; font-size:.92rem; }}
button[data-baseweb="tab"]:hover, [data-testid="stTab"]:hover {{ background:{FONDO}; }}
button[data-baseweb="tab"][aria-selected="true"], [data-testid="stTab"][aria-selected="true"] {{ background:{ROJO}; }}
button[data-baseweb="tab"][aria-selected="true"] p, [data-testid="stTab"][aria-selected="true"] p {{ color:#fff !important; }}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"], [data-testid="stTabs"] .react-aria-SelectionIndicator
    {{ display:none !important; }}

/* ================= Chips de estado al cargar archivos ================= */
.chips {{ display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 2px 0; }}
.chip {{ display:inline-flex; align-items:center; gap:5px; background:{FONDO}; color:{GRAFITO}; border:1px solid {LINEA};
    border-radius:999px; padding:3px 10px; font-size:.8rem; font-weight:500; font-variant-numeric:tabular-nums; }}
.chip b {{ color:{TINTA}; font-weight:700; }}
.chip.ok {{ background:#E7F4F1; border-color:#BFE3DC; color:#0F6B5F; }}
.chip.ok b {{ color:#0F6B5F; }}
.chip .ms {{ font-size:1rem; vertical-align:0; }}

/* ================= Estado vacío ================= */
.vacio {{ background:{SUPERFICIE}; border:1.5px dashed {LINEA_2}; border-radius:10px; padding:28px 24px; margin-top:18px;
    text-align:center; }}
.vacio .ico {{ width:50px; height:50px; border-radius:12px; background:{ROJO_SUAVE}; color:{ROJO}; display:inline-flex;
    align-items:center; justify-content:center; margin-bottom:10px; }}
.vacio .ico .ms {{ font-size:1.7rem; vertical-align:0; }}
.vacio h3 {{ font-size:1.15rem !important; font-weight:700; margin:0 0 4px 0; padding:0; }}
.vacio p {{ color:{GRAFITO}; font-size:.9rem; margin:0 auto; max-width:60ch; }}
.vacio .pv-lista {{ display:flex; justify-content:center; gap:10px; flex-wrap:wrap; margin-top:16px; }}
.vacio .pv {{ display:flex; align-items:center; gap:8px; background:{FONDO}; border:1px solid {LINEA}; border-radius:8px;
    padding:7px 12px; font-size:.84rem; color:{GRAFITO}; font-weight:600; }}
.vacio .pv i {{ font-style:normal; width:20px; height:20px; border-radius:50%; background:{SUPERFICIE}; border:1px solid {LINEA_2};
    display:inline-flex; align-items:center; justify-content:center; font-size:.72rem; font-weight:700; }}
.vacio .pv.ok {{ background:#E7F4F1; border-color:#BFE3DC; color:#0F6B5F; }}
.vacio .pv.ok i {{ background:{C_OK}; border-color:{C_OK}; color:#fff; }}
.vacio .pv i .ms {{ font-size:.85rem; vertical-align:0; }}

/* ================= Paneles de gráficos, tablas, desplegables ================= */
div[class*="st-key-tarjeta"] {{ background:{SUPERFICIE}; border:1px solid {LINEA}; border-radius:10px; padding:18px 20px 12px 20px; }}
.tit-graf {{ font-weight:700; color:{TINTA}; font-size:1rem; font-stretch:87.5%; }}
.sub-graf {{ color:{GRAFITO}; font-size:.82rem; margin:3px 0 8px 0; }}
div[data-testid="stDataFrame"] {{ border:1px solid {LINEA}; border-radius:8px; overflow:hidden; background:{SUPERFICIE}; }}
div[data-testid="stExpander"] details {{ border:1px solid {LINEA}; border-radius:8px; background:{SUPERFICIE}; }}
div[data-testid="stExpander"] summary p {{ font-weight:600; color:{TINTA}; }}
div[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{ color:{GRAFITO}; }}
div[data-baseweb="input"], div[data-baseweb="select"] > div {{ border-radius:6px !important; }}
[data-testid="stCaptionContainer"] {{ color:{GRAFITO}; }}
hr {{ border-color:{LINEA}; }}

@media (max-width: 760px) {{
  .hero {{ padding:20px; }} .hero h1 {{ font-size:1.6rem; }}
  .kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }} .kpi .v {{ font-size:1.7rem; }}
  .paso {{ width:96px; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition:none !important; }} }}
</style>
"""

_n_graf = [0]          # contador de paneles de gráfico (claves únicas por ejecución)


def ico(nombre: str) -> str:
    """Ícono Material (para HTML propio)."""
    return f'<span class="ms" aria-hidden="true">{nombre}</span>'


def encabezado(titulo: str, subtitulo: str, pasos: list[tuple[str, bool]], eyebrow: str = "") -> None:
    """Franja roja con el título y los pasos conectados. pasos: (etiqueta, completado).
    El primer paso sin completar se marca como actual. (`eyebrow` se mantiene por compatibilidad.)"""
    actual = next((i for i, (_, ok) in enumerate(pasos) if not ok), None)
    nodos = ""
    for i, (lbl, ok) in enumerate(pasos):
        clase = "hecho" if ok else ("actual" if i == actual else "")
        marca = ico("check") if ok else str(i + 1)
        nodos += f'<li class="paso {clase}"><div class="nodo">{marca}</div><div class="txt">{lbl}</div></li>'
    st.markdown(f'<div class="hero"><div><h1>{titulo}</h1><p>{subtitulo}</p></div>'
                f'<ol class="pasos" aria-label="Pasos">{nodos}</ol></div>', unsafe_allow_html=True)


def aplicar_estilo():
    _n_graf[0] = 0
    st.markdown(CSS, unsafe_allow_html=True)


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


def chips(items):
    """Chips de estado bajo un archivo cargado. items: textos con HTML; el primero va en verde con check."""
    html = "".join(f'<span class="chip ok">{ico("check_circle")}{t}</span>' if i == 0 else f'<span class="chip">{t}</span>'
                   for i, t in enumerate(items))
    st.markdown(f'<div class="chips">{html}</div>', unsafe_allow_html=True)


def vacio(titulo, texto, pasos):
    """Tarjeta de estado vacío que muestra qué archivos faltan. pasos: (etiqueta, completado)."""
    pv = "".join(f'<div class="pv{" ok" if ok else ""}"><i>{ico("check") if ok else i + 1}</i>{lbl}</div>'
                 for i, (lbl, ok) in enumerate(pasos))
    st.markdown(f'<div class="vacio"><div class="ico">{ico("upload_file")}</div><h3>{titulo}</h3><p>{texto}</p>'
                f'<div class="pv-lista">{pv}</div></div>', unsafe_allow_html=True)


def nota_html(texto, tipo=""):
    return f'<div class="nota {tipo}">{ico(ICONO.get(tipo, "info"))}<div>{texto}</div></div>'


def nota(texto, tipo=""):
    st.markdown(nota_html(texto, tipo), unsafe_allow_html=True)


def n(x):
    x = float(x or 0)
    return f"{int(round(x)):,}".replace(",", ".") if abs(x - round(x)) < 1e-9 else f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def alto_tabla(filas, maximo=460):
    """Alto justo para la tabla (sin filas vacías), con tope."""
    return min(maximo, 35 * (filas + 1) + 3)


def pct(a, b):
    return f"{a / b:.0%}" if b else "0%"


def grafico(titulo, sub, chart):
    _n_graf[0] += 1
    with st.container(key=f"tarjeta_{_n_graf[0]}"):
        st.markdown(f'<div class="tit-graf">{titulo}</div>' + (f'<div class="sub-graf">{sub}</div>' if sub else
                    '<div style="height:8px"></div>'), unsafe_allow_html=True)
        # fit-x: el ancho se ajusta al panel; el alto se respeta (la leyenda no aplasta las barras)
        chart = chart.properties(autosize=alt.AutoSizeParams(type="fit-x", contains="padding"), background=SUPERFICIE)
        chart = (chart.configure_view(stroke=None)
                 .configure_axis(gridColor=REJILLA, domain=False, tickColor=LINEA, labelColor=GRAFITO, titleColor=GRAFITO,
                                 labelFontSize=11, titleFontSize=11, titleFontWeight=600, labelPadding=6)
                 .configure_axisY(ticks=False, grid=False)
                 .configure(font=FUENTE)
                 .configure_text(font=FUENTE)
                 .configure_legend(labelColor=GRAFITO, titleColor=GRAFITO, labelFontSize=11, symbolType="square"))
        st.altair_chart(chart, width="stretch", theme=None)   # sin tema de Streamlit: fondo del panel
