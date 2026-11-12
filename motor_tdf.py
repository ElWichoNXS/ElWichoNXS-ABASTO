"""
motor_tdf.py  -  Decide qué estadísticos que hoy están en método M (Min/Max) pueden volver a TDF
y sugiere los días de stock de seguridad (DSS) que se deben cargar al pasarlos.

Es el camino inverso a motor_minmax.procesar y usa la MISMA clasificación del pronóstico
(motor_minmax.clasificar_pronostico). Un estadístico en M pasa a TDF si:
  1) su pronóstico es NORMAL (no es cero, ni sin pronóstico, ni lineal), y
  2) el ROQ, es decir lo que TDF enviaría (Proyectado + Cubrimiento + Exhibición + Destacado) calculado con el
     DSS SUGERIDO (no con el DSS que trae el BI), alcanza el 50 % del EMPAQUE (sin subempaque) o el 100 % del
     SUBEMPAQUE (con subempaque), y
  3) su exclusión permite despachar desde el CD: LI, vacía, IP y SP sí; IT y ST no (se quedan en M).
El DSS sugerido no depende de quién pasa (solo de la frecuencia y la venta real), así que no hay circularidad.

DSS SUGERIDO (para los que pasan a TDF; en TDF es obligatorio cargarlo):
  - Base = frecuencia de despacho (FREC EFECTIVA).
  - Lo que TDF envía = Proyectado + Cubrimiento + Exhibición (+ Destacado), con
        Proyectado  = pronóstico del día 0 (día de despacho)
        Cubrimiento = pronóstico de los (FREC + DSS) días siguientes al día 0 (más allá del BI, el promedio diario)
  - Si Proyectado + Cubrimiento no alcanza la venta real hasta el próximo despacho (CONSUMO DIA x FREC),
    se suben los DSS hasta que alcance, con un tope configurable.
Alertas (solo informan): sin venta en el mes, venta real muy superior al pronóstico, y venta del ciclo que no se cubre ni con el tope.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from motor_minmax import Params, clasificar_pronostico

VERSION_TDF = "2026-11-12-c"

EXCLUSIONES_BLOQUEAN = ("IT", "ST")           # sin transferencia del CD al local: se quedan en M
ETQ_EXCLUSION = {"LI": "LI / vacía", "IT": "IT · bloqueo total", "IP": "IP · bloqueo parcial",
                 "ST": "ST · suspensión total", "SP": "SP · suspensión parcial"}
MOT_FREC = "Frecuencia de despacho"
MOT_CONSUMO = "Frecuencia + consumo alto"
MOT_TOPE = "Consumo alto: no cubre ni con el DSS máximo"


@dataclass
class ParamsTDF:
    excl_bloquean: tuple = EXCLUSIONES_BLOQUEAN   # códigos de EXCLUSION que impiden pasar a TDF
    alerta_sin_venta: bool = True                 # marca los que pasan sin venta en el mes
    dss_tope: int = 10                            # máximo de días de stock de seguridad que se sugiere


def _codigo_exclusion(serie: pd.Series) -> pd.Series:
    """LI y vacío significan lo mismo (liberado)."""
    c = serie.fillna("").astype(str).str.strip().str.upper()
    return c.where(c != "", "LI").where(~c.isin(["NAN", "NONE"]), "LI")


def sugerir_dss(frec, cum, venta_dia, tope: int):
    """Días de stock de seguridad sugeridos por fila.
    frec: frecuencia efectiva (días); cum[:, h] = pronóstico acumulado de los días 0..h (= Proyectado + Cubrimiento con horizonte h);
    venta_dia: CONSUMO DIA real. Devuelve (dss, motivo, envio_cubre, no_cubre):
      dss         = max(frecuencia, menor DSS con el que Proyectado + Cubrimiento alcanza CONSUMO DIA x frecuencia), con tope max(tope, frecuencia)
      envio_cubre = Proyectado + Cubrimiento con ese DSS
      no_cubre    = True si ni con el tope alcanza la venta del ciclo"""
    frec = np.asarray(frec).astype(int)
    n = len(frec)
    idx = np.arange(n)
    venta_ciclo = np.asarray(venta_dia, dtype=float) * frec
    base = np.clip(frec, 0, None)
    cap = np.maximum(int(tope), base)
    necesario = cap + 1                                    # cap + 1 = no alcanza ni con el tope
    ultimo = cum.shape[1] - 1
    for d in range(int(cap.max()) if n else 0, -1, -1):    # de mayor a menor: al final queda el menor DSS que cubre
        ok = (cum[idx, np.minimum(frec + d, ultimo)] >= venta_ciclo - 1e-9) & (d <= cap)
        necesario = np.where(ok, d, necesario)
    no_cubre = necesario > cap
    dss = np.minimum(np.maximum(base, necesario), cap)
    envio = cum[idx, np.minimum(frec + dss, ultimo)]
    motivo = np.where(no_cubre, MOT_TOPE, np.where(dss > base, MOT_CONSUMO, MOT_FREC))
    return dss, motivo, envio, no_cubre


def procesar_m_a_tdf(df_bi: pd.DataFrame, p: Params | None = None, pt: ParamsTDF | None = None,
                     cols_pronostico: list | None = None):
    """Evalúa las filas del BI con Método = M. Devuelve (resultado, resumen).
    `resultado` trae una fila por Local x ESTADISTICO en M, con DECISION ('Pasar a TDF' / 'Dejar en M'), MOTIVO, ALERTA y,
    en los que pasan a TDF, los días de stock de seguridad sugeridos."""
    p = p or Params()
    pt = pt or ParamsTDF()
    if "Método" not in df_bi.columns:
        raise ValueError("El archivo no tiene la columna «Método» (M / TDF / TEM). Sube el BI donde se vea el método de cada estadístico.")
    metodo = df_bi["Método"].astype(str).str.strip().str.upper()
    n_bi = len(df_bi)
    otros = metodo[metodo != "M"].value_counts().to_dict()
    df_m = df_bi[metodo == "M"].copy()
    if df_m.empty:
        raise ValueError("El archivo no tiene filas en método M. Sube el BI con los estadísticos que hoy están en Min/Max.")

    df, info = clasificar_pronostico(df_m, p, cols_pronostico, max_dss=max(int(pt.dss_tope), 20))
    df = df.reset_index(drop=True)
    df["EXCLUSION"] = _codigo_exclusion(df["EXCLUSION"]) if "EXCLUSION" in df.columns else "LI"
    cod = df["EXCLUSION"]
    bloqueado = cod.isin([c.upper() for c in pt.excl_bloquean])
    clase = df["CLASE PRONOSTICO"]
    con_sub = df["_CON_SUB"].astype(bool)

    # ---- DSS sugerido y ROQ con ese DSS (para todas las filas: el ROQ se mide con lo que realmente se enviaría) ----
    frec = df["FREC EFECTIVA"].values.astype(int)
    R = df["CONSUMO DIA"].astype(float).values
    prom = df["PROMEDIO PRONOSTICO DIA"].astype(float).values
    cum = info["_cum"]
    idx = np.arange(len(df))
    dss, mot_dss, envio, no_cubre = sugerir_dss(frec, cum, R, pt.dss_tope)
    exhi = df["Exhi"].astype(float).values
    dest = pd.to_numeric(df["DESTACADOS"], errors="coerce").fillna(0).values if "DESTACADOS" in df.columns else np.zeros(len(df))
    roq = envio + exhi + dest                              # ROQ = Proyectado + Cubrimiento + Exhibición (+ Destacado), con el DSS sugerido
    umbral = df["UMBRAL TDF"].astype(float).values
    nivel_bajo = pd.Series(roq < umbral - 1e-9, index=df.index)
    df["ROQ (DSS SUGERIDO)"] = np.round(roq, 2)
    df["% ROQ/UMBRAL"] = roq / np.where(umbral > 0, umbral, np.nan)
    pron_ok = (clase == "Normal") & ~nivel_bajo
    pasa = (pron_ok & ~bloqueado).values

    motivo = np.select(
        [bloqueado, clase == "Sin pronóstico", clase == "Cero", clase == "Lineal", nivel_bajo & con_sub, nivel_bajo],
        ["Exclusión " + cod + ": no se puede despachar desde el CD",
         "Sin pronóstico", "Pronóstico cero", "Pronóstico lineal (repetido)",
         f"ROQ con el DSS sugerido < {p.pct_subempaque_cobertura:.0%} del subempaque",
         f"ROQ con el DSS sugerido < {p.pct_empaque_cobertura:.0%} del empaque"],
        default="Pronóstico normal y ROQ suficiente")
    df["DECISION"] = np.where(pasa, "Pasar a TDF", "Dejar en M")
    df["MOTIVO"] = motivo

    # ---- Días de stock de seguridad sugeridos (solo para los que pasan a TDF) ----
    df["DIAS SS ACTUAL"] = df["Dias SS"]
    df["DIAS SS SUGERIDO"] = pd.array(np.where(pasa, dss, -1), dtype="Int64")
    df.loc[~pasa, "DIAS SS SUGERIDO"] = pd.NA
    df["MOTIVO DSS"] = np.where(pasa, mot_dss, "")
    df["VENTA DEL CICLO"] = np.where(pasa, R * frec, np.nan)
    df["PROY+CUBR (DSS SUGERIDO)"] = np.where(pasa, envio, np.nan)
    df["VENTA REAL / PRONOSTICO"] = np.where(pasa & (prom > 0), R / np.where(prom > 0, prom, np.nan), np.nan)

    # ---- Alertas (solo informan) ----
    sin_venta = pasa & (df["CONSUMOS ACU"].astype(float).values <= 0) & pt.alerta_sin_venta
    venta_alta = pasa & (R >= p.consumo_min_subestima) & (prom > 0) & (R >= p.factor_consumo_vs_pron * prom)
    a1 = np.where(sin_venta, f"Sin venta en los {p.dias_transcurridos:g} días transcurridos del mes, con pronóstico normal", "")
    a2 = np.where(venta_alta, [f"Venta real {r / q:.1f} veces el pronóstico ({r:.2f} vs {q:.2f} u/día)" if q > 0 else "" for r, q in zip(R, prom)], "")
    a3 = np.where(pasa & no_cubre,
                  [f"Ni con el DSS máximo ({d}) el envío cubre la venta del ciclo ({v:.1f} vs {e:.1f} u)" for d, v, e in zip(dss, R * frec, envio)], "")
    df["ALERTA"] = [" | ".join(x for x in t if x) for t in zip(a1, a2, a3)]

    pegar = ["DECISION", "MOTIVO", "DIAS SS SUGERIDO", "MOTIVO DSS", "ALERTA", "Método", "CD", "Local", "DESIGNACION", "ESTADISTICO",
             "DESCRIPCION", "FAMILIA", "EXCLUSION", "EMPAQUE", "SUBEMPAQUE", "Exhi", "Min", "Max", "CONSUMOS ACU", "CONSUMO DIA",
             "PROMEDIO PRONOSTICO DIA", "VENTA REAL / PRONOSTICO", "VENTA DEL CICLO", "PROY+CUBR (DSS SUGERIDO)", "DIAS SS ACTUAL",
             "FREC EFECTIVA", "INV NETO", "Físico", "CLASE PRONOSTICO", "ROQ (DSS SUGERIDO)", "UMBRAL TDF", "% ROQ/UMBRAL"]
    res = df[[c for c in pegar if c in df.columns]].copy()
    res["Método"] = "M"
    res["ESTADISTICO"] = pd.to_numeric(res["ESTADISTICO"], errors="coerce").astype("Int64")

    pas = res[res["DECISION"] == "Pasar a TDF"]
    quedan = res[res["DECISION"] == "Dejar en M"]
    al = pas["ALERTA"]
    resumen = {
        "filas_bi": n_bi,
        "filas_m": len(res),
        "filas_otro_metodo": otros,
        "pasan": len(pas),
        "quedan": len(quedan),
        "con_alerta": int((al != "").sum()),
        "alertas_sin_venta": int(al.str.contains("Sin venta", regex=False).sum()),
        "alertas_venta_alta": int(al.str.contains("Venta real", regex=False).sum()),
        "alertas_no_cubre": int(al.str.contains("Ni con el DSS máximo", regex=False).sum()),
        "estadisticos_pasan": int(pas["ESTADISTICO"].nunique()),
        "locales_pasan": int(pas["Local"].nunique()) if "Local" in pas else 0,
        "estadisticos_m": int(res["ESTADISTICO"].nunique()),
        "por_motivo_quedan": quedan["MOTIVO"].str.replace(r"^Exclusión (\w+):.*$", r"Exclusión \1", regex=True).value_counts().to_dict(),
        "pasan_por_exclusion": pas["EXCLUSION"].value_counts().to_dict(),
        "dss_por_valor": {int(k): int(v) for k, v in pas["DIAS SS SUGERIDO"].value_counts().sort_index().items()},
        "dss_por_motivo": pas["MOTIVO DSS"].value_counts().to_dict(),
        "dss_tope": int(pt.dss_tope),
        "dias_de_pronostico": info["dias_de_pronostico"],
        "columnas_pronostico_usadas": info["columnas_pronostico_usadas"],
    }
    return res, resumen


def hoja_carga(res: pd.DataFrame) -> pd.DataFrame:
    """Filas que se cargan al sistema para pasarlas a TDF, con los días de stock de seguridad a colocar."""
    s = res[res["DECISION"] == "Pasar a TDF"]
    cols = [c for c in ("CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION") if c in s.columns]
    out = s[cols].copy()
    out["MÉTODO ACTUAL"] = "M"
    out["MÉTODO NUEVO"] = "TDF"
    out["DIAS SS SUGERIDO"] = s["DIAS SS SUGERIDO"].values
    out["ALERTA"] = s["ALERTA"].values
    return out.reset_index(drop=True)


def exportar_excel_tdf(res: pd.DataFrame, resumen: dict, destino, p: Params | None = None, pt: ParamsTDF | None = None) -> None:
    """Hojas: Resumen, PASAN A TDF, CARGA TDF y SE QUEDAN EN M."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    p = p or Params()
    pt = pt or ParamsTDF()
    ROJO, ROJO_OSC, GRIS_CLARO, BLANCO = "E30613", "A30410", "F4F4F4", "FFFFFF"
    pasan = res[res["DECISION"] == "Pasar a TDF"].reset_index(drop=True)
    quedan = res[res["DECISION"] == "Dejar en M"].drop(columns=["DIAS SS SUGERIDO", "MOTIVO DSS", "VENTA REAL / PRONOSTICO", "VENTA DEL CICLO",
                                                               "PROY+CUBR (DSS SUGERIDO)", "ALERTA"], errors="ignore").reset_index(drop=True)
    carga = hoja_carga(res)
    ent = {"EMPAQUE", "SUBEMPAQUE", "Exhi", "Min", "Max", "CONSUMOS ACU", "INV NETO", "Físico", "FREC EFECTIVA", "DIAS SS ACTUAL", "DIAS SS SUGERIDO"}
    dec = {"CONSUMO DIA", "PROMEDIO PRONOSTICO DIA", "ROQ (DSS SUGERIDO)", "UMBRAL TDF", "VENTA REAL / PRONOSTICO", "VENTA DEL CICLO",
           "PROY+CUBR (DSS SUGERIDO)"}
    ambar = PatternFill("solid", fgColor="FFE699")
    azul_claro = PatternFill("solid", fgColor="DDEBF7")
    lado = Side(style="thin", color="D9D9D9")

    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        wr = w.book.create_sheet("Resumen")
        pasan.to_excel(w, index=False, sheet_name="PASAN A TDF")
        carga.to_excel(w, index=False, sheet_name="CARGA TDF")
        quedan.to_excel(w, index=False, sheet_name="SE QUEDAN EN M")
        w.book.move_sheet("Resumen", offset=-(len(w.book.sheetnames) - 1))
        if "Sheet" in w.book.sheetnames:
            del w.book["Sheet"]

        for nombre, d, color in (("PASAN A TDF", pasan, "1FA391"), ("CARGA TDF", carga, "4B86E6"), ("SE QUEDAN EN M", quedan, "8C8C8C")):
            ws = w.sheets[nombre]
            ws.sheet_properties.tabColor = color
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.row_dimensions[1].height = 32
            ws.sheet_view.zoomScale = 90
            for i, col in enumerate(d.columns, 1):
                c = ws.cell(row=1, column=i)
                c.font = Font(bold=True, color=BLANCO, name="Arial", size=10)
                c.fill = PatternFill("solid", fgColor=ROJO_OSC)
                c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                ancho = {"DESCRIPCION": 44, "MOTIVO": 52, "MOTIVO DSS": 34, "ALERTA": 70, "DESIGNACION": 22}.get(col, min(max(len(str(col)) + 2, 10), 30))
                ws.column_dimensions[get_column_letter(i)].width = ancho
                fmt = "0" if col in ent else ("0.0" if col in dec else ("0%" if col == "% ROQ/UMBRAL" else None))
                if fmt:
                    for r in range(2, len(d) + 2):
                        ws.cell(row=r, column=i).number_format = fmt
                if col == "ALERTA":
                    for r, v in enumerate(d[col].tolist(), 2):
                        if v:
                            cel = ws.cell(row=r, column=i)
                            cel.fill = ambar
                            cel.font = Font(bold=True, name="Arial", color="7F6000")
                    c.fill = PatternFill("solid", fgColor="D39A2E")
                if col == "DIAS SS SUGERIDO":              # el valor a cargar en TDF
                    c.fill = PatternFill("solid", fgColor="2F75B5")
                    ws.column_dimensions[get_column_letter(i)].width = 14
                    for r in range(2, len(d) + 2):
                        cel = ws.cell(row=r, column=i)
                        cel.fill = azul_claro
                        cel.font = Font(bold=True, name="Arial", color="1F4E79")
                        cel.alignment = Alignment(horizontal="center")

        # ---------------- Resumen ----------------
        wr.sheet_properties.tabColor = "2B2B2B"
        wr.sheet_view.showGridLines = False
        wr.column_dimensions["A"].width = 2
        wr.column_dimensions["B"].width = 58
        for col in "CDE":
            wr.column_dimensions[col].width = 18
        ahora = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5)))
        wr["B1"] = "Min/Max → TDF · estadísticos que pueden volver a TDF"
        wr["B1"].font = Font(bold=True, size=15, color=ROJO, name="Arial")
        wr["B2"] = (f"Generado el {ahora:%d-%m-%Y} · {resumen['dias_de_pronostico']} días de pronóstico · "
                    f"{p.dias_transcurridos:g} días de venta transcurridos · umbral {p.pct_empaque_cobertura:.0%} del empaque "
                    f"o {p.pct_subempaque_cobertura:.0%} del subempaque · exclusiones que se quedan en M: "
                    f"{', '.join(pt.excl_bloquean) or 'ninguna'} · DSS máximo sugerido: {pt.dss_tope}")
        wr["B2"].font = Font(size=9, color="7F7F7F", name="Arial")
        wr["B2"].alignment = Alignment(wrap_text=True, vertical="top")
        wr.row_dimensions[2].height = 28
        fila = [4]

        def encabezado_tabla(titulos):
            r = fila[0]
            for k, t in enumerate(titulos):
                c = wr.cell(row=r, column=2 + k, value=t)
                c.font = Font(bold=True, color=BLANCO, name="Arial", size=10)
                c.fill = PatternFill("solid", fgColor=ROJO_OSC)
                c.alignment = Alignment(horizontal="left" if k == 0 else "center", vertical="center", wrap_text=True, indent=1 if k == 0 else 0)
            fila[0] += 1

        def linea(vals, negrita=False):
            r = fila[0]
            for k, v in enumerate(vals):
                c = wr.cell(row=r, column=2 + k, value=v)
                c.font = Font(name="Arial", size=10, bold=negrita)
                c.border = Border(bottom=lado)
                c.alignment = Alignment(horizontal="left" if k == 0 else "center", indent=1 if k == 0 else 0, wrap_text=True, vertical="center")
                if k and isinstance(v, (int, float)):
                    c.number_format = "0.0%" if isinstance(v, float) and v <= 1 and k == 2 else "#,##0"
                if r % 2 == 0:
                    c.fill = PatternFill("solid", fgColor=GRIS_CLARO)
            fila[0] += 1

        def titulo(txt):
            fila[0] += 1
            c = wr.cell(row=fila[0], column=2, value=txt)
            c.font = Font(bold=True, size=12, color=ROJO, name="Arial")
            fila[0] += 1

        tot = max(resumen["filas_m"], 1)
        titulo("1. Resultado general")
        encabezado_tabla(["Concepto", "Filas", "% de las filas en M"])
        linea(["Filas del BI en método M (evaluadas)", resumen["filas_m"], 1.0], True)
        linea(["Pasan a TDF", resumen["pasan"], resumen["pasan"] / tot], True)
        linea(["   · de ellas, con alguna ALERTA", resumen["con_alerta"], resumen["con_alerta"] / tot])
        linea(["Se quedan en M", resumen["quedan"], resumen["quedan"] / tot], True)
        linea(["Estadísticos distintos que pasan a TDF", resumen["estadisticos_pasan"]])
        linea(["Locales con al menos un estadístico que pasa a TDF", resumen["locales_pasan"]])
        if resumen["filas_otro_metodo"]:
            linea(["Filas del BI con otro método (no se evalúan): " + ", ".join(f"{k} {v}" for k, v in resumen["filas_otro_metodo"].items()),
                   int(sum(resumen["filas_otro_metodo"].values()))])

        titulo("2. Por qué se quedan en M")
        encabezado_tabla(["Motivo", "Filas", "% de los que se quedan"])
        for k, v in resumen["por_motivo_quedan"].items():
            linea([k, int(v), v / max(resumen["quedan"], 1)])
        if not resumen["por_motivo_quedan"]:
            linea(["(ninguno)", 0])

        titulo("3. Los que pasan a TDF, según su exclusión")
        encabezado_tabla(["Exclusión", "Filas"])
        for k, v in resumen["pasan_por_exclusion"].items():
            linea([ETQ_EXCLUSION.get(k, k), int(v)])
        if not resumen["pasan_por_exclusion"]:
            linea(["(ninguno)", 0])

        titulo("4. Días de stock de seguridad sugeridos (los que pasan a TDF)")
        encabezado_tabla(["Motivo del DSS", "Filas", "% de los que pasan"])
        for k, v in resumen["dss_por_motivo"].items():
            linea([k, int(v), v / max(resumen["pasan"], 1)])
        fila[0] += 1
        encabezado_tabla(["DSS sugerido (días)", "Filas", "% de los que pasan"])
        for k, v in resumen["dss_por_valor"].items():
            linea([f"{k} día" + ("" if k == 1 else "s"), int(v), v / max(resumen["pasan"], 1)])

        titulo("5. Alertas (solo informan)")
        encabezado_tabla(["Alerta", "Filas", "% de los que pasan"])
        for etq, k in (("Sin venta en el mes, con pronóstico normal", "alertas_sin_venta"),
                       (f"Venta real ≥ {p.factor_consumo_vs_pron:g} veces el pronóstico (y ≥ {p.consumo_min_subestima:g} u/día)", "alertas_venta_alta"),
                       (f"Ni con el DSS máximo ({pt.dss_tope}) el envío cubre la venta del ciclo", "alertas_no_cubre")):
            linea([etq, resumen[k], resumen[k] / max(resumen["pasan"], 1)])

        titulo("6. Reglas aplicadas")
        reglas = [
            ("Pasa a TDF si…", f"el pronóstico es normal (ni cero, ni lineal) y el ROQ con el DSS sugerido "
                               f"(Proyectado + Cubrimiento + Exhibición + Destacado, o sea lo que TDF enviaría) llega al {p.pct_empaque_cobertura:.0%} del EMPAQUE "
                               f"(sin subempaque) o al {p.pct_subempaque_cobertura:.0%} del SUBEMPAQUE (con subempaque)."),
            ("Exclusiones", f"LI, vacía, IP y SP pueden pasar a TDF porque se puede despachar desde el CD. "
                            f"{', '.join(pt.excl_bloquean) or 'Ninguna'} se quedan en M: no se despacha del CD al local."),
            ("DSS sugerido", "Base = frecuencia de despacho. Lo que TDF envía es Proyectado (pronóstico del día de despacho) + Cubrimiento (pronóstico de "
                             "los FREC + DSS días siguientes) + Exhibición (+ Destacado). Si Proyectado + Cubrimiento no alcanza la venta real hasta el "
                             f"próximo despacho (CONSUMO DIA × frecuencia), se suben los DSS hasta que alcance, con un máximo de {pt.dss_tope}."),
            ("ALERTA", "Solo informa: sin venta en el mes, venta real muy superior al pronóstico, o venta del ciclo que no se cubre ni con el DSS máximo."),
            ("Hoja CARGA TDF", "Local, estadístico, método nuevo (TDF) y días de stock de seguridad a colocar; la última columna (ALERTA) se puede borrar antes de cargar."),
        ]
        for k, v in reglas:
            r = fila[0]
            a = wr.cell(row=r, column=2, value=k); a.font = Font(bold=True, name="Arial", size=10); a.alignment = Alignment(vertical="top", indent=1)
            wr.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)
            b = wr.cell(row=r, column=3, value=v); b.font = Font(name="Arial", size=10); b.alignment = Alignment(wrap_text=True, vertical="top")
            wr.row_dimensions[r].height = 15 * (1 + len(v) // 62)
            fila[0] += 1
