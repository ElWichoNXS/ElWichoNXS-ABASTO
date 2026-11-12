"""
motor_tdf.py  -  Decide qué estadísticos que hoy están en método M (Min/Max) pueden volver a TDF.

Es el camino inverso a motor_minmax.procesar y usa la MISMA clasificación del pronóstico
(motor_minmax.clasificar_pronostico). Un estadístico en M pasa a TDF si:
  1) su pronóstico es NORMAL (no es cero, ni sin pronóstico, ni lineal), y
  2) el nivel que TDF buscaría tener en el local (Proyectado + Cubrimiento + Exhibición + Destacado) alcanza
     el 50 % del EMPAQUE (sin subempaque) o el 100 % del SUBEMPAQUE (con subempaque), y
  3) su exclusión permite despachar desde el CD: LI, vacía, IP y SP sí; IT y ST no (se quedan en M).
Si pasa a TDF pero no tuvo venta en el mes (con pronóstico normal), cambia igual y queda con una ALERTA.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

from motor_minmax import Params, clasificar_pronostico

VERSION_TDF = "2026-11-12-a"

EXCLUSIONES_BLOQUEAN = ("IT", "ST")           # sin transferencia del CD al local: se quedan en M
ETQ_EXCLUSION = {"LI": "LI / vacía", "IT": "IT · bloqueo total", "IP": "IP · bloqueo parcial",
                 "ST": "ST · suspensión total", "SP": "SP · suspensión parcial"}


@dataclass
class ParamsTDF:
    excl_bloquean: tuple = EXCLUSIONES_BLOQUEAN   # códigos de EXCLUSION que impiden pasar a TDF
    alerta_sin_venta: bool = True                 # marca los que pasan sin venta en el mes


def _codigo_exclusion(serie: pd.Series) -> pd.Series:
    """LI y vacío significan lo mismo (liberado)."""
    c = serie.fillna("").astype(str).str.strip().str.upper()
    return c.where(c != "", "LI").where(~c.isin(["NAN", "NONE"]), "LI")


def procesar_m_a_tdf(df_bi: pd.DataFrame, p: Params | None = None, pt: ParamsTDF | None = None,
                     cols_pronostico: list | None = None):
    """Evalúa las filas del BI con Método = M. Devuelve (resultado, resumen).
    `resultado` trae una fila por Local x ESTADISTICO en M, con DECISION ('Pasar a TDF' / 'Dejar en M'), MOTIVO y ALERTA."""
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

    df, info = clasificar_pronostico(df_m, p, cols_pronostico)
    df = df.reset_index(drop=True)
    df["EXCLUSION"] = _codigo_exclusion(df["EXCLUSION"]) if "EXCLUSION" in df.columns else "LI"
    cod = df["EXCLUSION"]
    bloqueado = cod.isin([c.upper() for c in pt.excl_bloquean])
    clase = df["CLASE PRONOSTICO"]
    nivel_bajo = df["NIVEL BAJO"].astype(bool)
    con_sub = df["_CON_SUB"].astype(bool)
    pron_ok = (clase == "Normal") & ~nivel_bajo
    pasa = pron_ok & ~bloqueado

    motivo = np.select(
        [bloqueado, clase == "Sin pronóstico", clase == "Cero", clase == "Lineal", nivel_bajo & con_sub, nivel_bajo],
        ["Exclusión " + cod + ": no se puede despachar desde el CD",
         "Sin pronóstico", "Pronóstico cero", "Pronóstico lineal (repetido)",
         f"Nivel TDF < {p.pct_subempaque_cobertura:.0%} del subempaque",
         f"Nivel TDF < {p.pct_empaque_cobertura:.0%} del empaque"],
        default="Pronóstico normal y nivel TDF suficiente")
    df["DECISION"] = np.where(pasa, "Pasar a TDF", "Dejar en M")
    df["MOTIVO"] = motivo
    sin_venta = pasa & (df["CONSUMOS ACU"].astype(float) <= 0)
    df["ALERTA"] = np.where(sin_venta & pt.alerta_sin_venta,
                            f"Sin venta en los {p.dias_transcurridos:g} días transcurridos del mes, con pronóstico normal", "")

    pegar = ["DECISION", "MOTIVO", "ALERTA", "Método", "CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA",
             "EXCLUSION", "EMPAQUE", "SUBEMPAQUE", "Exhi", "Min", "Max", "CONSUMOS ACU", "CONSUMO DIA", "INV NETO", "Físico",
             "PROMEDIO PRONOSTICO DIA", "CLASE PRONOSTICO", "COBERTURA TDF", "UMBRAL TDF", "% COBERTURA/UMBRAL",
             "FREC EFECTIVA", "Dias SS"]
    res = df[[c for c in pegar if c in df.columns]].copy()
    res["Método"] = "M"
    res["ESTADISTICO"] = pd.to_numeric(res["ESTADISTICO"], errors="coerce").astype("Int64")

    pas = res[res["DECISION"] == "Pasar a TDF"]
    quedan = res[res["DECISION"] == "Dejar en M"]
    resumen = {
        "filas_bi": n_bi,
        "filas_m": len(res),
        "filas_otro_metodo": otros,
        "pasan": len(pas),
        "quedan": len(quedan),
        "alertas_sin_venta": int((pas["ALERTA"] != "").sum()),
        "estadisticos_pasan": int(pas["ESTADISTICO"].nunique()),
        "locales_pasan": int(pas["Local"].nunique()) if "Local" in pas else 0,
        "estadisticos_m": int(res["ESTADISTICO"].nunique()),
        "por_motivo_quedan": quedan["MOTIVO"].str.replace(r"^Exclusión (\w+):.*$", r"Exclusión \1", regex=True).value_counts().to_dict(),
        "pasan_por_exclusion": pas["EXCLUSION"].value_counts().to_dict(),
        "dias_de_pronostico": info["dias_de_pronostico"],
        "columnas_pronostico_usadas": info["columnas_pronostico_usadas"],
    }
    return res, resumen


def hoja_carga(res: pd.DataFrame) -> pd.DataFrame:
    """Filas que se cargan al sistema para pasarlas a TDF."""
    s = res[res["DECISION"] == "Pasar a TDF"]
    cols = [c for c in ("CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION") if c in s.columns]
    out = s[cols].copy()
    out["MÉTODO ACTUAL"] = "M"
    out["MÉTODO NUEVO"] = "TDF"
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
    quedan = res[res["DECISION"] == "Dejar en M"].reset_index(drop=True)
    carga = hoja_carga(res)
    ent = {"EMPAQUE", "SUBEMPAQUE", "Exhi", "Min", "Max", "CONSUMOS ACU", "INV NETO", "Físico", "FREC EFECTIVA", "Dias SS"}
    dec = {"CONSUMO DIA", "PROMEDIO PRONOSTICO DIA", "COBERTURA TDF", "UMBRAL TDF"}
    ambar = PatternFill("solid", fgColor="FFE699")
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
                ancho = {"DESCRIPCION": 44, "MOTIVO": 52, "ALERTA": 62, "DESIGNACION": 22}.get(col, min(max(len(str(col)) + 2, 10), 30))
                ws.column_dimensions[get_column_letter(i)].width = ancho
                fmt = "0" if col in ent else ("0.0" if col in dec else ("0%" if col == "% COBERTURA/UMBRAL" else None))
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
                    f"{', '.join(pt.excl_bloquean) or 'ninguna'}")
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

        titulo("1. Resultado general")
        encabezado_tabla(["Concepto", "Filas", "% de las filas en M"])
        tot = max(resumen["filas_m"], 1)
        linea(["Filas del BI en método M (evaluadas)", resumen["filas_m"], 1.0], True)
        linea(["Pasan a TDF", resumen["pasan"], resumen["pasan"] / tot], True)
        linea(["   · de ellas, con ALERTA (sin venta en el mes)", resumen["alertas_sin_venta"], resumen["alertas_sin_venta"] / tot])
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

        titulo("4. Reglas aplicadas")
        reglas = [
            ("Pasa a TDF si…", f"el pronóstico es normal (ni cero, ni lineal) y el nivel que TDF busca tener en el local "
                               f"(Proyectado + Cubrimiento + Exhibición + Destacado) llega al {p.pct_empaque_cobertura:.0%} del EMPAQUE "
                               f"(sin subempaque) o al {p.pct_subempaque_cobertura:.0%} del SUBEMPAQUE (con subempaque)."),
            ("Exclusiones", f"LI, vacía, IP y SP pueden pasar a TDF porque se puede despachar desde el CD. "
                            f"{', '.join(pt.excl_bloquean) or 'Ninguna'} se quedan en M: no se despacha del CD al local."),
            ("ALERTA", "Si pasa a TDF pero no tuvo venta en el mes, cambia igual y se marca para identificarlo (hojas PASAN A TDF y CARGA TDF)."),
            ("Hoja CARGA TDF", "Local, estadístico y método nuevo de las filas que pasan a TDF; la última columna (ALERTA) se puede borrar antes de cargar."),
        ]
        for k, v in reglas:
            r = fila[0]
            a = wr.cell(row=r, column=2, value=k); a.font = Font(bold=True, name="Arial", size=10); a.alignment = Alignment(vertical="top", indent=1)
            wr.merge_cells(start_row=r, start_column=3, end_row=r, end_column=5)
            b = wr.cell(row=r, column=3, value=v); b.font = Font(name="Arial", size=10); b.alignment = Alignment(wrap_text=True, vertical="top")
            wr.row_dimensions[r].height = 15 * (1 + len(v) // 62)
            fila[0] += 1
