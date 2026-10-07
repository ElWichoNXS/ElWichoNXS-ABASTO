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
    dias_transcurridos: int = 5          # días del mes transcurridos: CONSUMO DIA = CONSUMOS ACU (consumo acumulado del mes) / dias_transcurridos
    umbral_pronostico_12d: float = 6.0   # se conserva la fila si SUMA 12 días <= 6
    umbral_unicos: int = 5               # se conserva si UNICOS <= 5 (valores que aparecen 1 sola vez)
    # --- criterios de la hoja REVISAR ---
    revisar_ratio_consumo: float = 5.0   # consumo real 12d vs pronóstico 12d (x veces)
    revisar_dgmax_dias: float = 60.0     # cobertura Max > 60 días de consumo
    revisar_var_bi: float = 0.5          # Min nuevo vs Min vigente del BI: cambio > 50 %
    umbral_dg_exhi: float = 2.0          # Exhi/consumo < 2 días -> sube a cobertura
    max_dias_ss_ajuste: int = 4          # el ajuste fino aplica si Dias SS <= 4
    # --- Sugerencias de subempaque (el Max usa SIEMPRE el SUBEMPAQUE real del BI) ---
    min_empaque_sugerir_sub: int = 6     # solo se sugiere subempacar si EMPAQUE >= 6
    min_locales_con_sub: int = 1         # el SKU debe estar subempacado en >= N locales del BI
    familias_alto_valor: tuple = ("VINOS", "ESPUMANTE", "WHISKY", "DESTILADAS", "COCTELES")  # prioridad ALTA
    skus_sub_extra: tuple = ()           # SKUs que sabes subempacables aunque el BI no los muestre subempacados
    # --- NUEVO (punto 1): cobertura por días reales de despacho ---
    usar_frec_efectiva: bool = False     # (validado: el proceso manual usa la FREC del BI) usa el MAYOR intervalo entre despachos (no el promedio del BI)
    # --- NUEVO (punto 2): validación del pronóstico ---
    umbral_venta_prom_dia: float = 1.0   # pronóstico promedio < 1 unid/día = "insuficiente"
    # --- NUEVO (punto 6): Max por cobertura sobre el incremento mínimo de despacho ---
    dias_cobertura_max: float = 0.0      # 0 = desactivado (Max = Min + SUBEMPAQUE o EMPAQUE/2)


# --------------------------------------------------------------------------
# UTILIDADES
# --------------------------------------------------------------------------
def xround(x, n: int = 0):
    """ROUND de Excel (mitad hacia arriba en valor absoluto), vectorizado.
    Python/NumPy redondean a par ('banker's rounding'), Excel no."""
    x = np.asarray(x, dtype=float)
    f = 10.0 ** n
    return np.sign(x) * np.floor(np.abs(x) * f + 0.5 + 1e-9) / f


def a_entero(x) -> pd.Series:
    """Convierte a entero (ROUND de Excel). NaN/inf -> 0. Siempre devuelve int64."""
    ser = pd.to_numeric(pd.Series(x), errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0)
    return pd.Series(xround(ser.values, 0).astype("int64"), index=ser.index)


DIAS_SEM = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]


def _mayor_intervalo(codigo: int) -> int:
    """Mayor número de días entre dos despachos consecutivos (semana circular)."""
    pos = [i for i in range(7) if (codigo >> i) & 1]
    if not pos:
        return 0
    return max(((pos[(k + 1) % len(pos)] - pos[k]) % 7) or 7 for k in range(len(pos)))


def frec_efectiva(df: pd.DataFrame, p: "Params") -> pd.Series:
    """Días que debe cubrir el stock entre dos despachos.
    El BI trae FREC ENTRE DESP = promedio (7 / n° de días de despacho). Un local que
    despacha Mar-Sáb-Dom tiene FREC=2, pero entre Dom y Mar... y entre Mar y Sáb pasan 4 días.
    Aquí se usa el MAYOR intervalo real (columnas LUNES..DOMINGO), nunca menos que el del BI."""
    base = pd.to_numeric(df["FREC ENTRE DESP"], errors="coerce").fillna(1).clip(lower=1)
    if not p.usar_frec_efectiva or any(c not in df.columns for c in DIAS_SEM):
        return base.astype(int)
    M = np.stack([df[c].astype(str).str.strip().str.upper().isin(["Y", "S", "SI", "1"]).values
                  for c in DIAS_SEM], axis=1)
    codigos = (M * (1 << np.arange(7))).sum(axis=1)
    tabla = {int(c): _mayor_intervalo(int(c)) for c in np.unique(codigos)}
    gap = pd.Series(codigos, index=df.index).map(tabla).astype(float)
    if "Ciclo de Revisión" in df.columns:
        gap[df["Ciclo de Revisión"].astype(str).str.lower().str.contains("todos")] = 1
    ef = np.where(gap > 0, np.maximum(gap, base), base)
    return pd.Series(ef, index=df.index).astype(int)


def _evidencia_subempaque(df: pd.DataFrame) -> pd.DataFrame:
    """Por SKU, en TODO el BI: en cuántos locales está y en cuántos ya está subempacado."""
    t = df[["ESTADISTICO", "SUBEMPAQUE"]].copy()
    t["ESTADISTICO"] = pd.to_numeric(t["ESTADISTICO"], errors="coerce")
    t["SUBEMPAQUE"] = pd.to_numeric(t["SUBEMPAQUE"], errors="coerce").fillna(0)
    t = t.dropna(subset=["ESTADISTICO"])
    t["ESTADISTICO"] = t["ESTADISTICO"].astype("int64")
    tot = t.groupby("ESTADISTICO").size().rename("_N_LOC_SKU")
    con = t[t["SUBEMPAQUE"] > 0]
    n_sub = con.groupby("ESTADISTICO").size().rename("_N_LOC_SUB")
    ref = con.groupby("ESTADISTICO")["SUBEMPAQUE"].agg(lambda x: x.mode().iloc[0]).rename("_SUB_REF")
    vals = con.groupby("ESTADISTICO")["SUBEMPAQUE"].agg(
        lambda x: ", ".join(f"{int(k)} ({v})" for k, v in x.value_counts().items())).rename("_SUB_VALORES")
    return pd.concat([tot, n_sub, ref, vals], axis=1).reset_index()


def _calc_max(minimo, R, empaque, sub, p: "Params"):
    """Max = Min + incremento. Incremento = SUBEMPAQUE; si es 0, EMPAQUE/2 (con ROQ < EMPAQUE/2
    el sistema no despacha). Opcional: cobertura de N días en múltiplos del incremento."""
    minimo = np.asarray(minimo, dtype=float); R = np.asarray(R, dtype=float)
    empaque = np.asarray(empaque, dtype=float); sub = np.asarray(sub, dtype=float)
    incr_base = np.where(sub > 0, sub, xround(empaque / 2, 0))
    incr = incr_base.copy()
    if p.dias_cobertura_max > 0:
        ok = (incr_base > 0) & (R > 0)
        cob = np.where(ok, np.ceil(R * p.dias_cobertura_max / np.where(ok, incr_base, 1)) * incr_base, 0)
        incr = np.maximum(incr_base, cob)
    regla = np.where(incr > incr_base, "Cobertura (R x días objetivo)",
             np.where(sub > 0, "Min + SUBEMPAQUE", "Min + EMPAQUE/2"))
    mx = np.maximum(a_entero(minimo + incr).values, minimo.astype("int64")).astype("int64")
    return mx, regla


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
    ev = _evidencia_subempaque(df)          # evidencia de subempaque en TODO el BI (antes de filtrar)

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

    # Entradas numéricas limpias (cada Local x ESTADISTICO conserva su propia Exhi)
    for c in ("Exhi", "EMPAQUE", "SUBEMPAQUE", "CONSUMOS ACU", "FREC ENTRE DESP", "Dias SS"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # 2b) Frecuencia efectiva (punto 1) y diagnóstico del pronóstico (punto 2) -----
    df["FREC EFECTIVA"] = frec_efectiva(df, p)
    cum = np.nancumsum(V, axis=1)
    idx = np.clip(df["FREC EFECTIVA"].values, 1, 12) - 1
    df["PRON CICLO"] = np.round(cum[np.arange(len(df)), idx], 2)      # venta pronosticada hasta el próximo despacho
    df["PRON PROM DIA"] = np.round(df["SUMA"] / 12, 2)
    insuf = df["PRON PROM DIA"] < p.umbral_venta_prom_dia
    rep = df["UNICOS"] <= p.umbral_unicos
    df["DIAG PRONOSTICO"] = np.select(
        [df["_sin_pronostico"], rep & insuf, rep, insuf],
        ["Sin pronóstico", "Repetido e insuficiente", "Valores repetidos", "Insuficiente (<1 u/día)"],
        default="Pronóstico normal")
    df["SUMA < EXHI"] = np.where(df["SUMA"] < pd.to_numeric(df["Exhi"], errors="coerce").fillna(0),
                                 "Si", "No")

    # 3) SUBEMPAQUE: se respeta el del BI (lo que el sistema realmente tiene configurado).
    #    Las propuestas de subempacar van aparte (ver sugerir_subempaque).
    df = df.merge(ev, on="ESTADISTICO", how="left")
    df["SUBEMPAQUE"] = pd.to_numeric(df["SUBEMPAQUE"], errors="coerce").fillna(0)

    # Min/Max vigentes del BI: float por los vacíos -> entero anulable (Int64)
    for src, dst in (("Min", "Min BI vigente"), ("Max", "Max BI vigente")):
        if src in df:
            df[dst] = pd.to_numeric(df[src], errors="coerce").round(0).astype("Int64")
        else:
            df[dst] = pd.array([pd.NA] * len(df), dtype="Int64")

    # 4) Consumo diario --------------------------------------------------------
    R = df["CONSUMOS ACU"].astype(float) / p.dias_transcurridos
    df["CONSUMO DIA"] = R

    # 5) MIN -------------------------------------------------------------------
    E = df["Exhi"].astype(float)
    F = df["FREC EFECTIVA"].astype(float)
    ds_exhi = np.where(R > 0, E / R.where(R > 0), np.inf)

    caso_a = R > E                                             # consumo > exhibición
    caso_b = (~caso_a) & (R * F > E) & (df["APTO"] == "Si") & \
             (ds_exhi < p.umbral_dg_exhi) & (df["Dias SS"] <= p.max_dias_ss_ajuste)

    min_ = np.where(caso_a, xround(R * F, 0),
            np.where(caso_b, xround(R * F, 0), E))
    df["Min"] = a_entero(min_).values
    df["_regla_min"] = np.where(caso_a, "A: consumo>exhi -> ROUND(R*FREC,0)",
                         np.where(caso_b, "B: exhi<2d cobertura -> ROUND(R*FREC,0)",
                                  "C: Min = Exhi"))

    # 6) MAX -------------------------------------------------------------------
    mx, regla = _calc_max(df["Min"], R, df["EMPAQUE"], df["SUBEMPAQUE"], p)
    df["Max"] = mx
    df["_regla_max"] = regla
    assert df["Min"].dtype == "int64" and df["Max"].dtype == "int64"

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
        "skus_sin_dato_apto": sin_apto if aptos is not None else None,
        "filas_con_aviso_revisar": int((df["DG EXHI = DG MIN"] == "REVISAR").sum()),
        "frec_efectiva_mayor_que_bi": int((df["FREC EFECTIVA"] > df["FREC ENTRE DESP"]).sum()),
        "pronostico_insuficiente": int(df["DIAG PRONOSTICO"].isin(["Insuficiente (<1 u/día)", "Repetido e insuficiente"]).sum()),
        "pronostico_valores_repetidos": int(df["DIAG PRONOSTICO"].isin(["Valores repetidos", "Repetido e insuficiente"]).sum()),
        "pronostico_ciclo_mayor_exhi": int((df["PRON CICLO"] > df["Exhi"]).sum()),
        "max_por_cobertura": int((df["_regla_max"] == "Cobertura (R x días objetivo)").sum()),
        "max_min_empaque_mitad": int((df["_regla_max"] == "Min + EMPAQUE/2").sum()),
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
            cols += ["CONSUMO DIA", "APTO", "Min", "Max", "DIF", "%", "DG MIN", "DGMAX",
                     "FREC EFECTIVA", "PRON PROM DIA", "PRON CICLO", "DIAG PRONOSTICO", "SUMA < EXHI"]
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
    F = df["FREC EFECTIVA"] if "FREC EFECTIVA" in df else df["FREC ENTRE DESP"]
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
        ("Prioridad MEDIA", "Pronóstico hasta el próximo despacho > Exhibición (Min = Exhi puede quedar corto)",
         (df["PRON CICLO"] > df["Exhi"]) & ~df["_regla_min"].str.startswith("A")),
        ("Prioridad MEDIA", "Pronóstico con valores repetidos y consumo real > pronóstico (revisar calidad del pronóstico)",
         df["DIAG PRONOSTICO"].isin(["Valores repetidos", "Repetido e insuficiente"]) & (R > df["PRON PROM DIA"] * 2) & (R >= 1)),
        ("Prioridad MEDIA", f"Consumo real 12d > {p.revisar_ratio_consumo:g}x el pronóstico",
         (cons12 > p.revisar_ratio_consumo * df["SUMA"]) & (cons12 > 12)),
        ("Prioridad MEDIA", f"Cobertura del Max > {p.revisar_dgmax_dias:g} días de consumo",
         df["DGMAX"] > p.revisar_dgmax_dias),
        ("Prioridad MEDIA", f"Min nuevo difiere > {p.revisar_var_bi:.0%} del Min vigente en BI",
         df["Min BI vigente"].notna() &
         ((df["Min"] - df["Min BI vigente"].astype(float)).abs() >
          p.revisar_var_bi * df["Min BI vigente"].astype(float).abs())),
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
            "Dias SS", "FREC ENTRE DESP", "FREC EFECTIVA", "CONSUMOS ACU", "CONSUMO DIA", "Exhi",
            "Físico", "INV NETO", "FISICO_WH", "SUMA", "UNICOS", "PRON PROM DIA", "PRON CICLO",
            "DIAG PRONOSTICO", "_regla_max", "Min BI vigente", "Max BI vigente", "Min", "Max",
            "DG MIN", "DGMAX", "_regla_min"]
    return rev[[c for c in cols if c in rev.columns]].reset_index(drop=True)


# --------------------------------------------------------------------------
# HOJA "SUGERIR SUBEMPAQUE"
# --------------------------------------------------------------------------
def sugerir_subempaque(df: pd.DataFrame, p: Params | None = None) -> pd.DataFrame:
    """Productos SIN subempaque en un local que conviene subempacar, siempre que el mismo
    SKU ya esté subempacado en otros locales del BI (o figure en `skus_sub_extra`).
    Es una propuesta de cambio de maestro: el Max de la hoja principal NO la aplica."""
    p = p or Params()
    emp = df["EMPAQUE"].astype(float)
    inc_act = pd.Series(xround(emp / 2, 0), index=df.index)
    n_sub = df["_N_LOC_SUB"].fillna(0)
    evid_bi = n_sub >= p.min_locales_con_sub
    extra = df["ESTADISTICO"].isin(p.skus_sub_extra)
    sub_sug = pd.Series(np.where(evid_bi, df["_SUB_REF"], np.where(extra, 1, np.nan)), index=df.index)
    sub_sug = np.minimum(sub_sug, emp)

    alto = df["FAMILIA"].isin(p.familias_alto_valor)
    incr_mayor_exhi = inc_act > df["Exhi"]
    cand = ((df["SUBEMPAQUE"] == 0) & (emp >= p.min_empaque_sugerir_sub) & (evid_bi | extra) &
            (sub_sug > 0) & (sub_sug < inc_act) & (alto | incr_mayor_exhi))
    s = df[cand].copy()
    if s.empty:
        return pd.DataFrame()
    s["SUB SUGERIDO"] = sub_sug[cand].astype(int)
    mx_sub, _ = _calc_max(s["Min"], s["CONSUMO DIA"], s["EMPAQUE"], s["SUB SUGERIDO"], p)
    s["MAX CON SUB"] = mx_sub
    s["REDUCCION MAX"] = s["Max"] - s["MAX CON SUB"]
    s["REDUCCION VALOR"] = (s["REDUCCION MAX"] * pd.to_numeric(s["PVP"], errors="coerce")).round(2)
    s["EVIDENCIA"] = np.where(s["_N_LOC_SUB"].fillna(0) >= p.min_locales_con_sub,
                              "Subempacado en " + s["_N_LOC_SUB"].fillna(0).astype(int).astype(str)
                              + " de " + s["_N_LOC_SKU"].fillna(0).astype(int).astype(str) + " locales",
                              "SKU de la lista manual")
    s["VALORES EN OTROS LOCALES"] = s["_SUB_VALORES"].fillna("")
    s["MOTIVO"] = np.where(alto[cand], "Familia de alto valor", "Incremento EMPAQUE/2 mayor que la Exhi")
    s["PRIORIDAD"] = np.where(alto[cand], "Prioridad ALTA", "Prioridad MEDIA")
    s = s.rename(columns={"SUBEMPAQUE": "SUB ACTUAL", "Max": "MAX ACTUAL"})
    cols = ["PRIORIDAD", "MOTIVO", "CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA",
            "EMPAQUE", "SUB ACTUAL", "SUB SUGERIDO", "EVIDENCIA", "VALORES EN OTROS LOCALES", "Exhi",
            "CONSUMO DIA", "Min", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX", "PVP", "REDUCCION VALOR"]
    s = s[[c for c in cols if c in s.columns]]
    return s.sort_values(["PRIORIDAD", "REDUCCION VALOR"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# EXPORTACIÓN A EXCEL (3 hojas)
# --------------------------------------------------------------------------
def exportar_excel(df: pd.DataFrame, rev: pd.DataFrame, resumen: dict, destino,
                   sug: pd.DataFrame | None = None) -> None:
    """Escribe: 'Pronóstico cero' (resultado), 'REVISAR' (casos complejos) y 'Resumen'."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    sug = sug if sug is not None else pd.DataFrame()
    privadas = [c for c in df.columns if isinstance(c, str) and c.startswith("_")]
    privadas += ["Min BI vigente", "Max BI vigente"]
    res = df.drop(columns=[c for c in privadas if c in df.columns])
    res.columns = [c.strftime("%Y-%m-%d") if isinstance(c, (dt.datetime, pd.Timestamp)) else c
                   for c in res.columns]

    leyenda = pd.DataFrame({
        "Concepto": [
            "CONSUMO DIA", "Filas que se conservan", "FREC EFECTIVA", "Diagnóstico del pronóstico",
            "Regla C (mayoría)", "Regla A", "Regla B", "Max",
            "SUBEMPAQUE", "Hoja SUGERIR SUBEMPAQUE", "Hoja REVISAR"],
        "Descripción": [
            "CONSUMOS ACU (consumo acumulado del mes que entrega el BI) / días del mes transcurridos (parámetro)",
            "SUMA pronóstico 12 días <= umbral  O  UNICOS <= 5 (valores que aparecen 1 sola vez)",
            "Mayor intervalo (días) entre dos despachos según LUNES..DOMINGO; nunca menor que FREC ENTRE DESP del BI. Se usa en reglas A y B",
            "PRON PROM DIA = SUMA/12 (<1 u/día = insuficiente); UNICOS bajo = valores repetidos; PRON CICLO = venta pronosticada hasta el próximo despacho; SUMA < EXHI = pronóstico no alcanza la exhibición",
            "Min = Exhi",
            "Si CONSUMO DIA > Exhi: Min = ROUND(CONSUMO DIA x FREC ENTRE DESP; 0)",
            "Si APTO=Si, Exhi/CONSUMO DIA < 2 días, Dias SS <= 4 y consumo x FREC > Exhi: Min = ROUND(consumo x FREC; 0)",
            "SUBEMPAQUE > 0: Max = Min + SUBEMPAQUE; si no: Max = Min + ROUND(EMPAQUE/2; 0) (con ROQ < EMPAQUE/2 el sistema no despacha). Opcional: cobertura de N días en múltiplos de ese incremento",
            "Se respeta el SUBEMPAQUE del BI (el real del sistema); el Max nunca asume un subempaque que no existe",
            "Productos sin subempaque cuyo mismo SKU ya está subempacado en otros locales y donde conviene (familia de alto valor, o EMPAQUE/2 > Exhi). Es una propuesta de cambio de maestro; muestra el Max resultante",
            "Casos fuera de parámetros o complejos; revisar de arriba hacia abajo (ALTA primero)"],
    })
    rs = pd.DataFrame(list(resumen.items()), columns=["Indicador", "Valor"])

    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        res.to_excel(w, index=False, sheet_name="Pronóstico cero")
        rev.to_excel(w, index=False, sheet_name="REVISAR")
        if len(sug):
            sug.to_excel(w, index=False, sheet_name="SUGERIR SUBEMPAQUE")
        rs.to_excel(w, index=False, sheet_name="Resumen")
        leyenda.to_excel(w, index=False, sheet_name="Resumen", startrow=len(rs) + 3)

        hdr_fill = PatternFill("solid", fgColor="1F3864")
        hojas = [("Pronóstico cero", res), ("REVISAR", rev)] + ([("SUGERIR SUBEMPAQUE", sug)] if len(sug) else [])
        for nombre, d in hojas:
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
        # formato numérico: enteros sin decimales, coberturas con 1 decimal
        ent = {"Min", "Max", "Min BI vigente", "Max BI vigente", "DIF", "Exhi", "EMPAQUE",
               "SUBEMPAQUE", "CONSUMOS ACU", "UNICOS", "FREC EFECTIVA", "FREC ENTRE DESP", "Físico",
               "SUB ACTUAL", "SUB SUGERIDO", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX"}
        dec = {"DG MIN", "DGMAX", "DG EXHIBICION", "CONSUMO DIA", "%", "PRON PROM DIA", "PRON CICLO",
               "PVP", "REDUCCION VALOR"}
        for nombre, d in hojas:
            ws_ = w.sheets[nombre]
            for i, col in enumerate(d.columns, 1):
                fmt = "0" if col in ent else ("0.0" if col in dec else None)
                if fmt:
                    for r in range(2, len(d) + 2):
                        ws_.cell(row=r, column=i).number_format = fmt
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
