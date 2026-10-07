"""
motor_minmax.py
Motor de cálculo de estadísticos Min / Max por local ("Pronóstico cero").
Reconstruido por ingeniería inversa a partir de:
  - BASE BI - Pronóstico cero -06-10.xlsx   (input)
  - Pronóstico cero -06-10.xlsx             (output manual)

Uso:
    from motor_minmax import procesar
    salida, resumen = procesar(df_bi, aptos=None)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# PARÁMETROS DE NEGOCIO (todos editables desde la interfaz)
# --------------------------------------------------------------------------
@dataclass
class Params:
    dias_ventana_consumo: int = 5        # CONSUMO DIA = CONSUMOS ACU / 5
    umbral_pronostico_12d: float = 6.0   # se conserva la fila si SUMA 12 días <= 6
    umbral_unicos: int = 5               # se conserva si UNICOS <= 5 (valores que aparecen 1 sola vez)
    # --- criterios de la hoja REVISAR ---
    revisar_ratio_consumo: float = 5.0   # consumo real 12d vs pronóstico 12d (x veces)
    revisar_dgmax_dias: float = 60.0     # cobertura Max > 60 días de consumo
    revisar_var_bi: float = 0.5          # Min nuevo vs Min vigente del BI: cambio > 50 %
    skus_coctel_ambiguos: tuple = (242984000, 243146006)  # SUBEMPAQUE depende del local
    umbral_dg_exhi: float = 2.0          # Exhi/consumo < 2 días -> sube a cobertura
    max_dias_ss_ajuste: int = 4          # el ajuste fino aplica si Dias SS <= 4
    min_empaque_sub1: int = 6            # SUBEMPAQUE=1 solo si EMPAQUE >= 6
    familias_sub1: tuple = ("VINOS", "ESPUMANTE", "WHISKY", "DESTILADAS")
    skus_sub1: tuple = (243138001, 243317000, 243379004)   # cocteles con SUBEMPAQUE=1 casi siempre


# --------------------------------------------------------------------------
# UTILIDADES
# --------------------------------------------------------------------------
def xround(x, n: int = 0):
    """ROUND de Excel (mitad hacia arriba en valor absoluto), vectorizado.
    Python/NumPy redondean a par ('banker's rounding'), Excel no."""
    x = np.asarray(x, dtype=float)
    f = 10.0 ** n
    return np.sign(x) * np.floor(np.abs(x) * f + 0.5 + 1e-9) / f


def _cols_fecha(df: pd.DataFrame) -> list:
    """Columnas de pronóstico diario (encabezado tipo fecha)."""
    out = []
    for c in df.columns:
        if isinstance(c, (dt.datetime, dt.date, pd.Timestamp)):
            out.append(c)
        elif isinstance(c, str):
            try:
                pd.to_datetime(c, format="%Y-%m-%d")
                out.append(c)
            except Exception:
                pass
    return out


def leer_bi(archivo) -> pd.DataFrame:
    """Lee el Excel crudo del BI (primera hoja)."""
    return pd.read_excel(archivo)


def leer_aptos(archivo) -> pd.DataFrame:
    """Maestro de productos: usa 'Estadístico' y 'Apto para PTL' (por nombre de columna)."""
    a = pd.read_excel(archivo)
    a.columns = [str(c).strip() for c in a.columns]
    col_e = next(c for c in a.columns if c.lower().startswith("estad"))
    col_a = next(c for c in a.columns if c.lower().startswith("apto"))
    a = a[[col_e, col_a]].copy()
    a.columns = ["ESTADISTICO", "APTO"]
    a["ESTADISTICO"] = pd.to_numeric(a["ESTADISTICO"], errors="coerce")
    a = a.dropna(subset=["ESTADISTICO"]).drop_duplicates("ESTADISTICO")
    a["ESTADISTICO"] = a["ESTADISTICO"].astype("int64")
    a["APTO"] = a["APTO"].astype(str).str.strip().str.capitalize()
    return a


# --------------------------------------------------------------------------
# PROCESO PRINCIPAL
# --------------------------------------------------------------------------
def procesar(df_bi: pd.DataFrame, aptos: pd.DataFrame | None = None,
             p: Params | None = None):
    p = p or Params()
    df = df_bi.copy()
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    requeridas = ["Local", "ESTADISTICO", "CONSUMOS ACU", "Exhi", "EMPAQUE",
                  "SUBEMPAQUE", "Dias SS", "FREC ENTRE DESP", "FAMILIA"]
    faltan = [c for c in requeridas if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas en el archivo del BI: {faltan}")

    fechas = _cols_fecha(df)
    if len(fechas) < 12:
        raise ValueError("Se esperaban 12 columnas de pronóstico diario (fechas).")
    fechas = fechas[:12]
    V = df[fechas].apply(pd.to_numeric, errors="coerce").values

    n_in = len(df)

    # 1) SUMA 12 días y UNICOS (= SUMA(--(CONTAR.SI(rango;rango)=1)) de Excel) ----
    suma = np.nansum(V, axis=1)
    igual = (V[:, :, None] == V[:, None, :]).sum(axis=2)     # NaN nunca es igual
    unicos = (igual == 1).sum(axis=1)
    df["SUMA"] = np.round(suma, 4)
    df["UNICOS"] = unicos
    sin_pron = np.all(np.isnan(V), axis=1)

    cond_bajo = suma <= p.umbral_pronostico_12d
    cond_uni = unicos <= p.umbral_unicos
    df = df[cond_bajo | cond_uni].copy().reset_index(drop=True)
    V = V[(cond_bajo | cond_uni)]
    sin_pron = sin_pron[(cond_bajo | cond_uni)]
    df["_sin_pronostico"] = sin_pron

    # 2) APTO (equivale al XLOOKUP del archivo externo) -----------------------
    df["ESTADISTICO"] = df["ESTADISTICO"].astype("int64")
    if aptos is not None:
        df = df.merge(aptos, on="ESTADISTICO", how="left")
        sin_apto = int(df["APTO"].isna().sum())
        df["APTO"] = df["APTO"].fillna("Si")
    else:
        df["APTO"] = "Si"
        sin_apto = len(df)

    # 3) SUBEMPAQUE efectivo (override para vinos / licores / cocteles) -------
    sub_in = df["SUBEMPAQUE"].copy()
    forzar = (
        (sub_in == 0) & (df["EMPAQUE"] >= p.min_empaque_sub1) &
        (df["FAMILIA"].isin(p.familias_sub1) | df["ESTADISTICO"].isin(p.skus_sub1))
    )
    df["SUBEMPAQUE"] = np.where(forzar, 1, sub_in)

    df["Min BI vigente"] = df["Min"] if "Min" in df else np.nan
    df["Max BI vigente"] = df["Max"] if "Max" in df else np.nan
    df["_sub_original"] = sub_in

    # 4) Consumo diario --------------------------------------------------------
    R = df["CONSUMOS ACU"].astype(float) / p.dias_ventana_consumo
    df["CONSUMO DIA"] = R

    # 5) MIN -------------------------------------------------------------------
    E = df["Exhi"].astype(float)
    F = df["FREC ENTRE DESP"].astype(float)
    ds_exhi = np.where(R > 0, E / R.where(R > 0), np.inf)

    caso_a = R > E                                             # consumo > exhibición
    caso_b = (~caso_a) & (R * F > E) & (df["APTO"] == "Si") & \
             (ds_exhi < p.umbral_dg_exhi) & (df["Dias SS"] <= p.max_dias_ss_ajuste)

    min_ = np.where(caso_a, xround(R * F, 0),
            np.where(caso_b, xround(R * F, 0), E))
    df["Min"] = xround(min_, 0).astype("int64")
    df["_regla_min"] = np.where(caso_a, "A: consumo>exhi -> ROUND(R*FREC,0)",
                         np.where(caso_b, "B: exhi<2d cobertura -> ROUND(R*FREC,0)",
                                  "C: Min = Exhi"))

    # 6) MAX -------------------------------------------------------------------
    sub = df["SUBEMPAQUE"].astype(float)
    df["Max"] = xround(np.where(sub > 0, df["Min"] + sub,
                                df["Min"] + df["EMPAQUE"] / 2), 0).astype("int64")

    # 7) Columnas de control (idénticas a tu archivo manual) -------------------
    df["DIF"] = df["Max"] - df["Min"]
    df["%"] = df["DIF"] / df["Empq_final"].replace(0, np.nan) if "Empq_final" in df else np.nan
    Rn = R.where(R > 0)
    df["DG MIN"] = df["Min"] / Rn
    df["DGMAX"] = df["Max"] / Rn
    df["DG EXHIBICION"] = E / Rn
    df["CON>EXHI"] = np.where(R > df["Min"], "REVISAR", "OK")
    chk = pd.Series(np.where(np.isclose(df["DG EXHIBICION"], df["DG MIN"]),
                             "OK", "REVISAR"), index=df.index, dtype=object)
    chk[Rn.isna()] = np.nan          # consumo 0 -> no aplica (en Excel daría #DIV/0!)
    df["DG EXHI = DG MIN"] = chk

    resumen = {
        "filas_bi": n_in,
        "filas_resultado": len(df),
        "por_pronostico_bajo": int(cond_bajo.sum()),
        "por_unicos": int((cond_uni & ~cond_bajo).sum()),
        "regla_A": int(caso_a.sum()),
        "regla_B": int(caso_b.sum()),
        "regla_C": int((~caso_a & ~caso_b).sum()),
        "subempaque_forzado_a_1": int(forzar.sum()),
        "skus_sin_dato_apto": sin_apto if aptos is not None else None,
        "filas_con_aviso_revisar": int((df["DG EXHI = DG MIN"] == "REVISAR").sum()),
        "posible_truncado_bi": n_in >= 29999,
    }

    # orden de columnas: las del BI, con los calculados donde los pones tú
    orden_bi = [c for c in df_bi.columns if isinstance(c, str) and c.strip() in df.columns]
    orden_bi = [c.strip() for c in orden_bi]
    calc = ["CONSUMO DIA", "APTO", "DIF", "%", "DG MIN", "DGMAX", "CON>EXHI",
            "DG EXHIBICION", "DG EXHI = DG MIN", "SUMA", "UNICOS", "_regla_min", "_sin_pronostico"]
    base = [c for c in orden_bi if c not in ("Min", "Max") and c not in calc]
    cols = []
    for c in base:
        cols.append(c)
        if c == "Físico":
            cols += ["CONSUMO DIA", "APTO", "Min", "Max", "DIF", "%", "DG MIN", "DGMAX"]
        if c == "Exhi":
            cols += ["CON>EXHI", "DG EXHIBICION", "DG EXHI = DG MIN"]
    resto = [c for c in df.columns if c not in cols]
    df = df[cols + resto]
    return df, resumen


# --------------------------------------------------------------------------
# HOJA "REVISAR": casos fuera de parámetros o complejos
# --------------------------------------------------------------------------
def marcar_revision(df: pd.DataFrame, p: Params | None = None) -> pd.DataFrame:
    """Devuelve solo las filas que conviene revisar a mano, con el motivo."""
    p = p or Params()
    R = df["CONSUMO DIA"]
    F = df["FREC ENTRE DESP"]
    cons12 = R * 12
    reglas = [
        ("Prioridad ALTA", "Consumo diario > Exhibición (regla A)",
         df["_regla_min"].str.startswith("A")),
        ("Prioridad ALTA", "Sin pronóstico en los 12 días",
         df["_sin_pronostico"]),
        ("Prioridad ALTA", "Inventario neto negativo",
         df["INV NETO"] < 0),
        ("Prioridad ALTA", "Producto de temporada",
         df.get("TEMPORADA", 0) > 0),
        ("Prioridad MEDIA", "Exhibición con menos cobertura que la frecuencia de despacho (regla B / R×FREC > Exhi)",
         (R * F > df["Exhi"]) & ~df["_regla_min"].str.startswith("A")),
        ("Prioridad MEDIA", "Cóctel con SUBEMPAQUE a confirmar (depende del local)",
         (df["FAMILIA"] == "COCTELES") & (df["_sub_original"] == 0) &
         (df["EMPAQUE"] >= p.min_empaque_sub1) &
         ~df["ESTADISTICO"].isin(p.skus_sub1)),
        ("Prioridad MEDIA", f"Consumo real 12d > {p.revisar_ratio_consumo:g}x el pronóstico",
         (cons12 > p.revisar_ratio_consumo * df["SUMA"]) & (cons12 > 12)),
        ("Prioridad MEDIA", f"Cobertura del Max > {p.revisar_dgmax_dias:g} días de consumo",
         df["DGMAX"] > p.revisar_dgmax_dias),
        ("Prioridad MEDIA", f"Min nuevo difiere > {p.revisar_var_bi:.0%} del Min vigente en BI",
         df["Min BI vigente"].notna() &
         ((df["Min"] - df["Min BI vigente"]).abs() > p.revisar_var_bi * df["Min BI vigente"].abs())),
    ]
    motivos = pd.Series("", index=df.index, dtype=object)
    prio = pd.Series("", index=df.index, dtype=object)
    n = pd.Series(0, index=df.index)
    for pr, texto, cond in reglas:
        cond = pd.Series(cond, index=df.index).fillna(False).astype(bool)
        motivos = np.where(cond, np.where(motivos == "", texto, motivos + " | " + texto), motivos)
        motivos = pd.Series(motivos, index=df.index, dtype=object)
        prio = np.where(cond & (prio != "Prioridad ALTA"), pr, prio)
        prio = pd.Series(prio, index=df.index, dtype=object)
        n = n + cond.astype(int)
    rev = df[n > 0].copy()
    rev.insert(0, "MOTIVOS DE REVISIÓN", motivos[n > 0])
    rev.insert(0, "PRIORIDAD", prio[n > 0])
    rev.insert(2, "N° MOTIVOS", n[n > 0])
    rev = rev.sort_values(["PRIORIDAD", "N° MOTIVOS"], ascending=[True, False])
    cols = ["PRIORIDAD", "MOTIVOS DE REVISIÓN", "N° MOTIVOS", "CD", "Local", "DESIGNACION",
            "ESTADISTICO", "DESCRIPCION", "FAMILIA", "APTO", "EMPAQUE", "SUBEMPAQUE",
            "Dias SS", "FREC ENTRE DESP", "CONSUMOS ACU", "CONSUMO DIA", "Exhi", "INV NETO",
            "FISICO_WH", "SUMA", "UNICOS", "Min BI vigente", "Max BI vigente", "Min", "Max",
            "DG MIN", "DGMAX", "_regla_min"]
    return rev[[c for c in cols if c in rev.columns]].reset_index(drop=True)


# --------------------------------------------------------------------------
# EXPORTACIÓN A EXCEL (3 hojas)
# --------------------------------------------------------------------------
def exportar_excel(df: pd.DataFrame, rev: pd.DataFrame, resumen: dict, destino) -> None:
    """Escribe: 'Pronóstico cero' (resultado), 'REVISAR' (casos complejos) y 'Resumen'."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    privadas = [c for c in df.columns if isinstance(c, str) and c.startswith("_")]
    privadas += ["Min BI vigente", "Max BI vigente"]
    res = df.drop(columns=[c for c in privadas if c in df.columns])
    res.columns = [c.strftime("%Y-%m-%d") if isinstance(c, (dt.datetime, pd.Timestamp)) else c
                   for c in res.columns]

    leyenda = pd.DataFrame({
        "Concepto": [
            "Filas que se conservan",
            "Regla C (mayoría)", "Regla A", "Regla B", "Max",
            "SUBEMPAQUE", "Hoja REVISAR"],
        "Descripción": [
            "SUMA pronóstico 12 días <= umbral  O  UNICOS <= 5 (valores que aparecen 1 sola vez)",
            "Min = Exhi",
            "Si CONSUMO DIA > Exhi: Min = ROUND(CONSUMO DIA x FREC ENTRE DESP; 0)",
            "Si APTO=Si, Exhi/CONSUMO DIA < 2 días, Dias SS <= 4 y consumo x FREC > Exhi: Min = ROUND(consumo x FREC; 0)",
            "SUBEMPAQUE > 0: Max = Min + SUBEMPAQUE; si no: Max = ROUND(Min + EMPAQUE/2; 0)",
            "Se fuerza a 1 en vinos, espumantes, whisky, destiladas y cocteles definidos (EMPAQUE >= 6)",
            "Casos fuera de parámetros o complejos; revisar de arriba hacia abajo (ALTA primero)"],
    })
    rs = pd.DataFrame(list(resumen.items()), columns=["Indicador", "Valor"])

    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        res.to_excel(w, index=False, sheet_name="Pronóstico cero")
        rev.to_excel(w, index=False, sheet_name="REVISAR")
        rs.to_excel(w, index=False, sheet_name="Resumen")
        leyenda.to_excel(w, index=False, sheet_name="Resumen", startrow=len(rs) + 3)

        hdr_fill = PatternFill("solid", fgColor="1F3864")
        for nombre, d in (("Pronóstico cero", res), ("REVISAR", rev)):
            ws = w.sheets[nombre]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(d.columns, 1):
                c = ws.cell(row=1, column=i)
                c.font = Font(bold=True, color="FFFFFF", name="Arial")
                c.fill = hdr_fill
                c.alignment = Alignment(wrap_text=True, vertical="center")
                ancho = 70 if col == "MOTIVOS DE REVISIÓN" else min(max(len(str(col)) + 2, 10), 40)
                if col == "DESCRIPCION":
                    ancho = 42
                ws.column_dimensions[get_column_letter(i)].width = ancho
        ws = w.sheets["REVISAR"]
        alta = PatternFill("solid", fgColor="F8CBAD")
        media = PatternFill("solid", fgColor="FFF2CC")
        for r in range(2, len(rev) + 2):
            ws.cell(row=r, column=1).fill = alta if "ALTA" in str(ws.cell(row=r, column=1).value) else media
        resaltar = [i for i, c in enumerate(rev.columns, 1) if c in ("Min", "Max")]
        for r in range(2, len(rev) + 2):
            for i in resaltar:
                ws.cell(row=r, column=i).font = Font(bold=True, name="Arial")
        wr = w.sheets["Resumen"]
        wr.column_dimensions["A"].width = 34
        wr.column_dimensions["B"].width = 110
