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
    decimales_repeticion: int = 4        # semana 2 == semana 1 (redondeo a 4 dec.)
    umbral_dg_exhi: float = 2.0          # Exhi/consumo < 2 días -> sube a cobertura
    max_dias_ss_ajuste: int = 4          # el ajuste fino aplica si Dias SS <= 4
    min_empaque_sub1: int = 6            # SUBEMPAQUE=1 solo si EMPAQUE >= 6
    familias_sub1: tuple = ("VINOS", "ESPUMANTE", "WHISKY", "DESTILADAS")
    skus_sub1: tuple = (242984000, 243138001, 243146006, 243317000, 243379004)


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
    """Lista de aptos: col A = ESTADISTICO, col C = Si/No (como el XLOOKUP original)."""
    a = pd.read_excel(archivo, header=0)
    a = a.iloc[:, [0, 2]]
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

    # 1) SUMA 12 días y repetición de la semana 1 en la semana 2 -------------
    suma = np.nansum(V, axis=1)
    rep = np.all(np.round(V[:, 7:12], p.decimales_repeticion)
                 == np.round(V[:, 0:5], p.decimales_repeticion), axis=1)
    # filas sin pronóstico (todo NaN) -> suma 0 -> entran por el umbral
    df["SUMA"] = np.round(suma, 4)

    cond_bajo = suma <= p.umbral_pronostico_12d
    cond_rep = rep & ~np.all(np.isnan(V), axis=1)
    df["_motivo"] = np.where(cond_bajo, "Pronóstico 12d <= umbral",
                     np.where(cond_rep, "Pronóstico repetido (sem2 = sem1)", ""))
    df = df[cond_bajo | cond_rep].copy()
    df = df.reset_index(drop=True)

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
            np.where(caso_b, xround(R * F, 1), E))
    df["Min"] = min_
    df["_regla_min"] = np.where(caso_a, "A: consumo>exhi -> ROUND(R*FREC,0)",
                         np.where(caso_b, "B: exhi<2d cobertura -> ROUND(R*FREC,1)",
                                  "C: Min = Exhi"))

    # 6) MAX -------------------------------------------------------------------
    sub = df["SUBEMPAQUE"].astype(float)
    df["Max"] = np.where(sub > 0, df["Min"] + sub,
                         xround(df["Min"] + df["EMPAQUE"] / 2, 0))

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
        "por_pronostico_repetido": int((cond_rep & ~cond_bajo).sum()),
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
            "DG EXHIBICION", "DG EXHI = DG MIN", "SUMA", "_motivo", "_regla_min"]
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
