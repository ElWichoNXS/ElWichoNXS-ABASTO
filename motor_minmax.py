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
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# PARÁMETROS DE NEGOCIO (todos editables desde la interfaz)
# --------------------------------------------------------------------------
@dataclass
class Params:
    dias_transcurridos: int = 5          # días del mes transcurridos: CONSUMO DIA = CONSUMOS ACU (consumo acumulado del mes) / dias_transcurridos
    # --- Qué filas pasan de TDF a Min/Max ---
    factor_prom_exhi: float = 0.55       # regla 3: promedio diario del pronóstico < 55 % de la Exhibición ...
    pct_empaque_cobertura: float = 0.5   # regla 4: ... Y promedio x (FREC + Dias SS) < 50 % del Empq_final (si lo cubre, se queda en TDF)
    dias_repetidos_lineal: int = 7       # pronóstico "lineal": en la PRIMERA semana (7 días) al menos N días repiten valor (7 = toda la semana)
    # --- Cálculo del Min ---
    umbral_dg_exhi: float = 2.0          # Exhi/consumo < 2 días -> sube a cobertura (regla B)
    usar_frec_efectiva: bool = False     # False: FREC del BI (promedio). True: MAYOR intervalo real entre despachos
    # --- Cálculo del Max ---
    dias_cobertura_max: float = 0.0      # 0 = desactivado (Max = Min + SUBEMPAQUE o EMPAQUE/2)
    # --- Diagnóstico del pronóstico ---
    umbral_venta_prom_dia: float = 1.0   # pronóstico promedio < 1 unid/día = "insuficiente"
    # --- Hoja REVISAR (solo casos extremos) ---
    sobrestock_dias: float = 20.0       # sobre stock crítico: cobertura del Max (Max / CONSUMO DIA) > 20 días
    factor_consumo_exhi: float = 3.0     # incongruencia severa: CONSUMO DIA >= 3 x Exhi
    consumo_bajo_exhi: float = 0.5       # corte para separar "Sobrestock por cubrir exhibición" en consumo <= 0.5 y > 0.5 u/día
    pct_exhi_en_cobertura: float = 0.8   # no es sobre stock si la Exhi explica >= 80 % de los días de cobertura del Max
    # --- Sugerencias de subempaque (el Max usa SIEMPRE el SUBEMPAQUE real del BI) ---
    min_empaque_sugerir_sub: int = 7     # solo se sugiere subempacar si EMPAQUE >= 7
    min_locales_con_sub: int = 10         # el SKU debe estar subempacado en >= N locales del BI
    sub_dias_venta_empaque: float = 12.0 # criterio 1 (sobrestock): el local tarda > 12 días en vender UN empaque completo
    pvp_alto: float = 5.0                # criterio 2: producto de PVP alto (>= 5): también se revisa su subempaque
    exigir_apto_subempaque: bool = True  # solo se sugiere si el maestro dice 'Apto para PTL' = Si
    exigir_pvp_alto: bool = True         # solo se sugiere si PVP >= pvp_alto (filtro obligatorio)
    familias_no_subempacar: tuple = ("CERVEZAS", "CERVEZAS SIN ALCOHOL", "AGUAS")  # nunca se subempacan
    skus_no_subempacar: tuple = ()       # ESTADISTICOS específicos que nunca se subempacan
    skus_sub_extra: tuple = ()           # SKUs que sabes subempacables aunque el BI no los muestre subempacados


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
        lambda x: ", ".join(f"{int(k)} ({v} {'Local' if v == 1 else 'Locales'})" for k, v in x.value_counts().items())).rename("_SUB_VALORES")
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


MIN_DIAS_PRON = 7     # mínimo de días de pronóstico aceptados
MAX_DIAS_PRON = 12    # se usan como máximo los primeros 12 días


class ColumnasPronosticoError(ValueError):
    """No se pudieron identificar las 12 columnas de pronóstico diario."""
    def __init__(self, mensaje, encontradas, todas):
        super().__init__(mensaje)
        self.encontradas = encontradas      # columnas reconocidas como fecha
        self.todas = todas                  # todas las columnas del archivo


_MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
          "jan": 1, "apr": 4, "aug": 8, "dec": 12}
_RE_FECHA = [
    re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}([ T].*)?$"),          # 2026-10-07 [00:00:00]
    re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}([ T].*)?$"),        # 07/10/2026
    re.compile(r"^\d{1,2}[-/. ]([a-zA-Z]{3,10})\.?([-/. ]\d{2,4})?$"),  # 07-oct, 07-oct-26
    re.compile(r"^([a-zA-Z]{3,10})\.?[-/. ]\d{1,2}([-/. ]\d{2,4})?$"),  # oct-07
]


def _es_fecha(c) -> bool:
    """True si el encabezado representa una fecha (datetime, texto con formato de fecha o serial de Excel)."""
    if isinstance(c, (dt.datetime, dt.date, pd.Timestamp)):
        return True
    if isinstance(c, (int, float, np.integer, np.floating)) and not isinstance(c, bool):
        return 40000 <= float(c) <= 60000          # serial de Excel (años 2009-2064)
    if isinstance(c, str):
        t = c.strip()
        if re.fullmatch(r"\d{5}(\.0+)?", t):         # serial de Excel guardado como texto
            return 40000 <= float(t) <= 60000
        for rx in _RE_FECHA:
            m = rx.match(t)
            if m:
                g = m.group(1) if m.lastindex else None
                if g is not None and rx.pattern.count("a-zA-Z") and g[:3].lower() not in _MESES:
                    return False
                return True
    return False


def _cols_fecha(df: pd.DataFrame) -> list:
    """Columnas de pronóstico diario (encabezado tipo fecha)."""
    return [c for c in df.columns if _es_fecha(c)]


def leer_bi(archivo) -> pd.DataFrame:
    """Lee el Excel crudo del BI (primera hoja)."""
    return pd.read_excel(archivo)


def leer_aptos(archivo) -> pd.DataFrame:
    """Maestro de productos: columnas 'Estadístico' y 'Apto para PTL' (Si / No).
    'Apto para PTL' se usa en la regla B del Min y como aptitud para subempaque."""
    a = pd.read_excel(archivo)
    a.columns = [str(c).strip() for c in a.columns]
    col_e = next(c for c in a.columns if c.lower().startswith("estad"))
    col_a = next(c for c in a.columns if c.lower().startswith("apto"))
    a2 = a[[col_e, col_a]].copy()
    a2.columns = ["ESTADISTICO", "APTO"]
    a2["ESTADISTICO"] = pd.to_numeric(a2["ESTADISTICO"], errors="coerce")
    a2 = a2.dropna(subset=["ESTADISTICO"]).drop_duplicates("ESTADISTICO")
    a2["ESTADISTICO"] = a2["ESTADISTICO"].astype("int64")
    a2["APTO"] = a2["APTO"].astype(str).str.strip().str.capitalize()
    return a2


# --------------------------------------------------------------------------
# PROCESO PRINCIPAL
# --------------------------------------------------------------------------
def procesar(df_bi: pd.DataFrame, aptos: pd.DataFrame | None = None,
             p: Params | None = None, cols_pronostico: list | None = None):
    p = p or Params()
    df = df_bi.copy()
    df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    requeridas = ["Local", "ESTADISTICO", "CONSUMOS ACU", "Exhi", "EMPAQUE",
                  "SUBEMPAQUE", "Dias SS", "FREC ENTRE DESP", "FAMILIA"]
    faltan = [c for c in requeridas if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas en el archivo del BI: {faltan}")

    if cols_pronostico:                      # elegidas a mano por el usuario
        fechas = [c for c in df.columns if c in set(cols_pronostico)]
        if len(fechas) != len(cols_pronostico):
            raise ValueError("Alguna de las columnas de pronóstico elegidas no existe en el archivo.")
    else:
        fechas = _cols_fecha(df)
        if len(fechas) < MIN_DIAS_PRON:
            raise ColumnasPronosticoError(
                f"Se necesitan al menos {MIN_DIAS_PRON} columnas de pronóstico diario (fechas) y se reconocieron {len(fechas)}.",
                fechas, list(df.columns))
    fechas = fechas[:MAX_DIAS_PRON]
    n_dias = len(fechas)          # el BI trae 12 días, o menos si el pronóstico arranca el día de la descarga
    V = df[fechas].apply(pd.to_numeric, errors="coerce").values

    n_in = len(df)
    ev = _evidencia_subempaque(df)          # evidencia de subempaque en TODO el BI (antes de filtrar)

    # Entradas numéricas limpias (cada Local x ESTADISTICO conserva su propia Exhi)
    for c in ("Exhi", "EMPAQUE", "SUBEMPAQUE", "CONSUMOS ACU", "FREC ENTRE DESP", "Dias SS"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    if "Empq_final" in df.columns:
        df["Empq_final"] = pd.to_numeric(df["Empq_final"], errors="coerce")
    else:
        df["Empq_final"] = np.nan
    df["Empq_final"] = df["Empq_final"].where(df["Empq_final"] > 0,
                                              np.where(df["SUBEMPAQUE"] > 0, df["SUBEMPAQUE"], df["EMPAQUE"]))
    df["FREC EFECTIVA"] = frec_efectiva(df, p)

    # 1) SUMA 12 días y UNICOS (= SUMA(--(CONTAR.SI(rango;rango)=1)) de Excel) ----
    suma = np.round(np.nansum(V, axis=1), 4)          # mismo valor que se muestra en la columna SUMA
    igual = (V[:, :, None] == V[:, None, :]).sum(axis=2)     # NaN nunca es igual
    unicos = (igual == 1).sum(axis=1)
    df["TOTAL PRONOSTICO"] = np.round(suma, 4)
    df["UNICOS"] = unicos
    # Pronóstico LINEAL: se mira solo la primera semana (días 1-7). Que desde el día 8 el modelo copie la semana
    # no es linealidad; lineal es que en los 7 primeros días el valor se repita (ventas todos los días).
    V7 = V[:, :7]
    igual7 = (V7[:, :, None] == V7[:, None, :]).sum(axis=2)
    dias_rep = (igual7 >= 2).sum(axis=1)                     # días de la semana 1 que comparten valor con otro día
    df["DIAS REPETIDOS SEM1"] = dias_rep
    sin_pron = np.all(np.isnan(V), axis=1)

    # Filtro TDF -> Min/Max. Pasa a Min/Max si:
    #   1) pronóstico CERO / inexistente (SUMA = 0)                      -> siempre pasa
    #   2) pronóstico LINEAL: UNICOS <= umbral (repetido / plano)         -> siempre pasa
    #   3) y 4) JUNTAS: promedio diario del pronóstico < 55 % de la Exhi  Y
    #           promedio x (FREC + Dias SS) < 50 % del Empq_final
    #      Si cumple la 3 pero el forecast SÍ cubre la mitad del empaque final, se queda en TDF.
    # Si no cumple ninguna, el pronóstico es normal y se queda en TDF.
    exhi_v = pd.to_numeric(df["Exhi"], errors="coerce").fillna(0).values
    prom_v = suma / n_dias
    cob_v = prom_v * (df["FREC EFECTIVA"].values + df["Dias SS"].values)    # unidades que cubre el forecast hasta el próximo despacho + SS
    cero = suma == 0
    lineal = dias_rep >= p.dias_repetidos_lineal
    r3 = prom_v < p.factor_prom_exhi * exhi_v
    r4 = cob_v < p.pct_empaque_cobertura * df["Empq_final"].values
    r34 = r3 & r4
    cond_mm = cero | lineal | r34
    seg = {                                   # segmentos mutuamente excluyentes (suman el total del BI)
        "1_pasa_pronostico_cero": int(cero.sum()),
        "2_pasa_pronostico_lineal": int((lineal & ~cero).sum()),
        "3_pasa_prom_exhi_y_cobertura_empaque": int((r34 & ~lineal & ~cero).sum()),
        "4_tdf_rescatado_por_cobertura_empaque": int((r3 & ~r4 & ~lineal & ~cero).sum()),
        "5_tdf_pronostico_normal": int((~cond_mm & ~(r3 & ~r4)).sum()),
        "total_BI": n_in,
    }
    motivo = np.where(cero, "Pronóstico cero",
              np.where(lineal, "Pronóstico lineal (repetido)",
              np.where(r34, f"Promedio < {p.factor_prom_exhi:.0%} de la Exhibición y cobertura (FREC+SS) < {p.pct_empaque_cobertura:.0%} del empaque", "")))
    df["MOTIVO MIN/MAX"] = motivo
    df["COBERTURA TDF"] = np.round(cob_v, 2)
    df["% COBERTURA/EMPQ"] = cob_v / df["Empq_final"].replace(0, np.nan).values
    df["% PROM/EXHI"] = prom_v / np.where(exhi_v > 0, exhi_v, np.nan)
    df = df[cond_mm].copy().reset_index(drop=True)
    V = V[cond_mm]
    sin_pron = sin_pron[cond_mm]
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

    # 2b) Diagnóstico del pronóstico ---------------------------------------------
    cum = np.nancumsum(V, axis=1)
    idx = np.clip(df["FREC EFECTIVA"].values, 1, n_dias) - 1
    df["PRON CICLO"] = np.round(cum[np.arange(len(df)), idx], 2)      # venta pronosticada hasta el próximo despacho
    df["PROMEDIO PRONOSTICO DIA"] = np.round(df["TOTAL PRONOSTICO"] / n_dias, 2)
    insuf = df["PROMEDIO PRONOSTICO DIA"] < p.umbral_venta_prom_dia
    rep = df["DIAS REPETIDOS SEM1"] >= p.dias_repetidos_lineal
    etq_insuf = f"Insuficiente (<{p.umbral_venta_prom_dia:g} u/día)"
    df["DIAG PRONOSTICO"] = np.select(
        [df["_sin_pronostico"], rep & insuf, rep, insuf],
        ["Sin pronóstico", "Repetido e insuficiente", "Valores repetidos", etq_insuf],
        default="Pronóstico normal")

    # 3) SUBEMPAQUE: se respeta el del BI (lo que el sistema realmente tiene configurado).
    #    Las propuestas de subempacar van aparte (ver sugerir_subempaque).
    df = df.merge(ev, on="ESTADISTICO", how="left")
    df["SUBEMPAQUE"] = pd.to_numeric(df["SUBEMPAQUE"], errors="coerce").fillna(0)

    # 4) Consumo diario --------------------------------------------------------
    R = df["CONSUMOS ACU"].astype(float) / p.dias_transcurridos
    df["CONSUMO DIA"] = R
    df["% CONSUMO/EMPQ"] = R * df["FREC EFECTIVA"] / df["Empq_final"]

    # 5) MIN -------------------------------------------------------------------
    E = df["Exhi"].astype(float)
    F = df["FREC EFECTIVA"].astype(float)
    ds_exhi = np.where(R > 0, E / R.where(R > 0), np.inf)

    caso_a = R > E                                             # consumo > exhibición
    caso_b = (~caso_a) & (R * F > E) & (df["APTO"] == "Si") & \
             (ds_exhi < p.umbral_dg_exhi)

    min_ = np.where(caso_a, xround(R * F, 0),
            np.where(caso_b, xround(R * F, 0), E))
    df["Min"] = a_entero(min_).values
    df["_regla_min"] = np.where(caso_a, "A: consumo>exhi -> ROUND(R*FREC,0)",
                         np.where(caso_b, f"B: exhi<{p.umbral_dg_exhi:g}d cobertura -> ROUND(R*FREC,0)",
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
        **{f"segmento_{k}": v for k, v in seg.items()},
        "regla_A": int(caso_a.sum()),
        "regla_B": int(caso_b.sum()),
        "regla_C": int((~caso_a & ~caso_b).sum()),
        "skus_sin_dato_apto": sin_apto if aptos is not None else None,
        "filas_con_aviso_revisar": int((df["DG EXHI = DG MIN"] == "REVISAR").sum()),
        "frec_efectiva_mayor_que_bi": int((df["FREC EFECTIVA"] > df["FREC ENTRE DESP"]).sum()),
        "pronostico_insuficiente": int(df["DIAG PRONOSTICO"].isin([etq_insuf, "Repetido e insuficiente"]).sum()),
        "pronostico_valores_repetidos": int(df["DIAG PRONOSTICO"].isin(["Valores repetidos", "Repetido e insuficiente"]).sum()),
        "pronostico_ciclo_mayor_exhi": int((df["PRON CICLO"] > df["Exhi"]).sum()),
        "max_por_cobertura": int((df["_regla_max"] == "Cobertura (R x días objetivo)").sum()),
        "max_min_empaque_mitad": int((df["_regla_max"] == "Min + EMPAQUE/2").sum()),
        "pronostico_cero_o_sin_pronostico": int((df["TOTAL PRONOSTICO"] == 0).sum()),
        "dias_de_pronostico": n_dias,
        "columnas_pronostico_usadas": f"{fechas[0]} ... {fechas[-1]}" if fechas else "",
        "posible_truncado_bi": n_in >= 29999,
    }

    # orden de columnas: las del BI, con los calculados donde los pones tú
    orden_bi = [c for c in df_bi.columns if isinstance(c, str) and c.strip() in df.columns]
    orden_bi = [c.strip() for c in orden_bi]
    calc = ["CONSUMO DIA", "APTO", "DIF", "%", "DG MIN", "DGMAX", "CON>EXHI",
            "DG EXHIBICION", "DG EXHI = DG MIN", "TOTAL PRONOSTICO", "UNICOS", "DIAS REPETIDOS SEM1", "_regla_min", "_sin_pronostico"]
    base = [c for c in orden_bi if c not in ("Min", "Max") and c not in calc]
    cols = []
    for c in base:
        cols.append(c)
        if c == "Físico":
            cols += ["CONSUMO DIA", "APTO", "Min", "Max", "DIF", "%", "DG MIN", "DGMAX",
                     "FREC EFECTIVA", "PROMEDIO PRONOSTICO DIA", "TOTAL PRONOSTICO", "UNICOS", "DIAS REPETIDOS SEM1", "% CONSUMO/EMPQ",
                     "PRON CICLO", "DIAG PRONOSTICO", "% PROM/EXHI", "COBERTURA TDF", "% COBERTURA/EMPQ", "MOTIVO MIN/MAX"]
        if c == "Exhi":
            cols += ["CON>EXHI", "DG EXHIBICION", "DG EXHI = DG MIN"]
    resto = [c for c in df.columns if c not in cols]
    df = df[cols + resto]
    return df, resumen


# --------------------------------------------------------------------------
# HOJA "REVISAR": casos fuera de parámetros o complejos
# --------------------------------------------------------------------------
def marcar_revision(df: pd.DataFrame, p: Params | None = None) -> pd.DataFrame:
    """Solo CASOS EXTREMOS (3 validaciones):
       1) Sobre stock crítico: cobertura del Max > p.sobrestock_dias días de consumo
          (se excluye si la Exhi cubre >= p.pct_exhi_en_cobertura de esos días; sin consumo no aplica: solo se mantiene la Exhi).
       2) Inventario físico negativo: INV NETO < 0.
       3) Incongruencia severa: CONSUMO DIA >= p.factor_consumo_exhi x Exhi."""
    p = p or Params()
    R = df["CONSUMO DIA"]
    F = df["FREC EFECTIVA"] if "FREC EFECTIVA" in df else df["FREC ENTRE DESP"]
    inv = pd.to_numeric(df["INV NETO"], errors="coerce")
    exhi = pd.to_numeric(df["Exhi"], errors="coerce").fillna(0)
    consumo_ciclo = R * F
    df = df.copy()
    df["CONSUMO CICLO"] = consumo_ciclo
    df["DIAS INVENTARIO"] = np.where(R > 0, inv / R.where(R > 0), np.inf)
    df["UNIDADES SOBRE MAX"] = (inv - df["Max"]).clip(lower=0)
    df["FALTANTE VS CICLO"] = (consumo_ciclo - df["Min"]).clip(lower=0)
    df["COBERTURA MAX (DIAS)"] = df["Max"] / R.where(R > 0)       # NaN si no hay consumo

    df["COBERTURA EXHI (DIAS)"] = exhi / R.where(R > 0)           # días que cubre la exhibición
    # Sobre stock ligado a la exhibición (la Exhi cubre casi los mismos días que el Max) es normal: no se revisa.
    exhi_explica = df["COBERTURA EXHI (DIAS)"] >= p.pct_exhi_en_cobertura * df["COBERTURA MAX (DIAS)"]
    # Sobrestock por cubrir la exhibición: la exhibición sola supera sobrestock_dias, o explica >= pct_exhi_en_cobertura
    # de los días del Max. Se separa por consumo diario: <= 0.5 u/día y > 0.5 u/día.
    cob_exhi = df["COBERTURA EXHI (DIAS)"]
    sobre_exhi = (R > 0) & ((cob_exhi > p.sobrestock_dias) |
                            ((df["COBERTURA MAX (DIAS)"] > p.sobrestock_dias) & exhi_explica.fillna(False)))
    sobre_exhi_bajo = sobre_exhi & (R <= p.consumo_bajo_exhi)
    sobre_exhi_alto = sobre_exhi & (R > p.consumo_bajo_exhi)
    sobrestock = (df["COBERTURA MAX (DIAS)"] > p.sobrestock_dias) & ~sobre_exhi
    inv_neg = inv < 0
    incongruencia = (R > 0) & (R >= p.factor_consumo_exhi * exhi)

    reglas = [
        ("Prioridad ALTA", "Inventario Físico Negativo", inv_neg),
        ("Prioridad ALTA", "Consumo diario triplica la Exhibición", incongruencia),
        ("Prioridad MEDIA", f"Sobre stock: Cobertura > {p.sobrestock_dias:g} días", sobrestock),
        ("Informativo", f"Sobrestock por cubrir exhibición (consumo <= {p.consumo_bajo_exhi:g} u/día)", sobre_exhi_bajo),
        ("Informativo", f"Sobrestock por cubrir exhibición (consumo > {p.consumo_bajo_exhi:g} u/día)", sobre_exhi_alto),
    ]
    motivos = pd.Series("", index=df.index, dtype=object)
    prio = pd.Series("", index=df.index, dtype=object)
    n = pd.Series(0, index=df.index)
    for pr, texto, cond in reglas:
        cond = pd.Series(cond, index=df.index).fillna(False).astype(bool)
        motivos = pd.Series(np.where(cond, np.where(motivos == "", texto, motivos + " | " + texto), motivos),
                            index=df.index, dtype=object)
        prio = pd.Series(np.where(cond & (prio != "Prioridad ALTA"), pr, prio), index=df.index, dtype=object)
        n = n + cond.astype(int)
    rev = df[n > 0].copy()
    rev.insert(0, "MOTIVOS DE REVISIÓN", motivos[n > 0])
    rev.insert(0, "PRIORIDAD", prio[n > 0])
    rev.insert(2, "N° MOTIVOS", n[n > 0])
    rev["_ord"] = rev["PRIORIDAD"].map({"Prioridad ALTA": 0, "Prioridad MEDIA": 1, "Informativo": 2})
    rev = rev.sort_values(["_ord", "UNIDADES SOBRE MAX", "FALTANTE VS CICLO"], ascending=[True, False, False]).drop(columns="_ord")
    rev["DIAS INVENTARIO"] = rev["DIAS INVENTARIO"].replace(np.inf, 9999)   # sin consumo en el mes
    rev = _sugerir_acciones(rev, p)
    cols = ["PRIORIDAD", "MOTIVOS DE REVISIÓN", "ACCIÓN PRINCIPAL", "ALERTA PVP", "SUGERENCIA A REALIZAR", "N° MOTIVOS", "CD", "Local", "DESIGNACION",
            "ESTADISTICO", "DESCRIPCION", "FAMILIA", "APTO", "Empq_final", "SUBEMPAQUE", "FREC EFECTIVA",
            "CONSUMO DIA", "CONSUMO CICLO", "Exhi", "INV NETO", "DIAS INVENTARIO", "UNIDADES SOBRE MAX",
            "Min", "Max", "COBERTURA EXHI (DIAS)", "COBERTURA MAX (DIAS)", "FALTANTE VS CICLO", "PVP",
            "VIABILIDAD SUBEMPAQUE", "SUB SUGERIDO", "MAX CON SUB", "REDUCCION MAX", "_regla_min", "MOTIVO MIN/MAX"]
    return rev[[c for c in cols if c in rev.columns]].reset_index(drop=True)


def _sugerir_acciones(rev: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Para cada caso de REVISAR: analiza si subempacar es viable y propone la acción a realizar.
    Prioridad de soluciones: 1) corregir el dato (inventario / consumo), 2) subempacar si es viable y reduce el Max,
    3) si no hay solución operativa, queda mapeado; el sobre stock por cubrir la exhibición es solo informativo (la exhibición la define el área comercial)."""
    if rev.empty:
        for c in ("ACCIÓN PRINCIPAL", "ALERTA PVP", "SUGERENCIA A REALIZAR", "VIABILIDAD SUBEMPAQUE", "SUB SUGERIDO", "MAX CON SUB", "REDUCCION MAX"):
            rev[c] = pd.Series(dtype=object)
        return rev
    rev = rev.copy()
    emp = pd.to_numeric(rev["EMPAQUE"], errors="coerce").fillna(0).astype(float)
    R = rev["CONSUMO DIA"].astype(float)
    sub_act = pd.to_numeric(rev["SUBEMPAQUE"], errors="coerce").fillna(0)
    n_sub = rev["_N_LOC_SUB"].fillna(0) if "_N_LOC_SUB" in rev else pd.Series(0, index=rev.index)
    extra = rev["ESTADISTICO"].isin(p.skus_sub_extra)
    ref = rev["_SUB_REF"] if "_SUB_REF" in rev else pd.Series(np.nan, index=rev.index)
    sub_sug = pd.Series(np.where(n_sub >= 1, ref, np.where(extra, 1, np.nan)), index=rev.index, dtype=float)
    sub_sug = np.minimum(sub_sug, emp)
    inc_act = pd.Series(xround(emp / 2, 0), index=rev.index)
    prohibido_fam = rev["FAMILIA"].astype(str).str.strip().str.upper().isin([f.upper() for f in p.familias_no_subempacar])
    prohibido_sku = rev["ESTADISTICO"].isin(p.skus_no_subempacar)
    no_apto = (rev["APTO"] != "Si") if (p.exigir_apto_subempaque and "APTO" in rev) else pd.Series(False, index=rev.index)

    mx_sub, _ = _calc_max(rev["Min"], R, emp, sub_sug.fillna(0), p)
    mx_sub = pd.Series(mx_sub, index=rev.index)
    reduccion = (rev["Max"] - mx_sub).where(sub_sug.notna() & (sub_sug > 0))

    viab, estado = [], []
    for i in rev.index:
        if sub_act[i] > 0:
            viab.append(f"Ya tiene subempaque ({sub_act[i]:g})"); estado.append("ya")
        elif prohibido_fam[i] or prohibido_sku[i]:
            viab.append("No viable: familia o estadístico excluido de subempaque"); estado.append("no")
        elif no_apto[i]:
            viab.append("No viable: no es apto para PTL según el maestro"); estado.append("no")
        elif emp[i] < p.min_empaque_sugerir_sub:
            viab.append(f"No viable: empaque de {emp[i]:g} (mínimo {p.min_empaque_sugerir_sub})"); estado.append("no")
        elif not (n_sub[i] >= 1 or extra[i]):
            viab.append("No viable: el SKU no está subempacado en ningún local"); estado.append("no")
        elif not (sub_sug[i] > 0 and sub_sug[i] < inc_act[i]) or not (reduccion[i] > 0):
            viab.append(f"No útil: el subempaque de referencia ({sub_sug[i]:g}) no reduce el Max"); estado.append("no")
        elif n_sub[i] >= p.min_locales_con_sub or extra[i]:
            viab.append(f"Viable: SKU subempacado en {int(n_sub[i])} locales"); estado.append("si")
        else:
            viab.append(f"Posible, validar: SKU subempacado solo en {int(n_sub[i])} local(es) (mínimo {p.min_locales_con_sub})"); estado.append("posible")

    rev["VIABILIDAD SUBEMPAQUE"] = viab
    ok_sub = pd.Series([e in ("si", "posible") for e in estado], index=rev.index)
    rev["SUB SUGERIDO"] = sub_sug.where(ok_sub).astype("Float64").round(0)
    rev["MAX CON SUB"] = mx_sub.where(ok_sub).astype("Float64").round(0)
    rev["REDUCCION MAX"] = reduccion.where(ok_sub).astype("Float64").round(0)

    exhi = pd.to_numeric(rev["Exhi"], errors="coerce").fillna(0)
    inv = pd.to_numeric(rev["INV NETO"], errors="coerce")
    cexhi = rev["COBERTURA EXHI (DIAS)"]
    cmax = rev["COBERTURA MAX (DIAS)"]
    pvp = _num(rev["PVP"]) if "PVP" in rev else pd.Series(np.nan, index=rev.index)
    # Nota operativa: la exhibición la define el área comercial y el retiro de productos del surtido tampoco es decisión
    # de abastecimiento. Por eso el sobre stock por cubrir la exhibición es solo informativo, y las únicas acciones
    # propias son corregir el dato, notificar y subempacar (si es viable).
    acciones, textos, alertas = [], [], []
    for k, i in enumerate(rev.index):
        motivos = str(rev.at[i, "MOTIVOS DE REVISIÓN"]).split(" | ")
        partes, principal = [], None
        alerta = ""

        def add(cat, txt):
            nonlocal principal
            if principal is None:
                principal = cat
            partes.append(txt)

        for mo in motivos:
            if mo.startswith("Inventario"):
                add("Corregir inventario",
                    f"Corregir inventario: INV NETO = {inv[i]:g}. Hacer conteo físico y ajustar el inventario del local; "
                    "con inventario negativo el abastecimiento queda distorsionado.")
            elif mo.startswith("Consumo diario"):
                rel = f"{R[i] / exhi[i]:.1f} veces" if exhi[i] > 0 else "con Exhi = 0, muy por encima de"
                add("Notificar al área comercial",
                    f"Notificar al área comercial: el consumo diario ({R[i]:.1f}) es {rel} la Exhi ({exhi[i]:g}); posible exhibición "
                    f"insuficiente o consumo atípico (promoción, dato erróneo). El Min ya está en {int(rev.at[i, 'Min'])} (regla A).")
            elif mo.startswith("Sobre stock"):
                e = estado[k]
                if e in ("si", "posible"):
                    if p.exigir_pvp_alto and pd.notna(pvp[i]) and pvp[i] < p.pvp_alto:
                        alerta = f"PVP bajo ({pvp[i]:.2f} < {p.pvp_alto:g})"
                    aviso = (f" ⚠ ALERTA: el PVP ({pvp[i]:.2f}) es menor al PVP mínimo ({p.pvp_alto:g}); por eso no aparece en la hoja "
                             "SUGERIR SUBEMPAQUE. Validar si conviene igual." if alerta else "")
                    if e == "si":
                        add("Subempacar",
                            f"SUBEMPACAR a {int(rev.at[i, 'SUB SUGERIDO'])}: {viab[k][8:]}. El Max baja de {int(rev.at[i, 'Max'])} a "
                            f"{int(rev.at[i, 'MAX CON SUB'])} (−{int(rev.at[i, 'REDUCCION MAX'])} u; cobertura de {cmax[i]:.0f} a "
                            f"{(rev.at[i, 'MAX CON SUB'] / R[i]):.0f} días).{aviso}")
                    else:
                        add("Evaluar subempaque",
                            f"Evaluar SUBEMPACAR a {int(rev.at[i, 'SUB SUGERIDO'])} (solo en {int(n_sub[i])} local(es); validar con el maestro): "
                            f"el Max bajaría de {int(rev.at[i, 'Max'])} a {int(rev.at[i, 'MAX CON SUB'])}. Si no se aprueba, "
                            f"queda mapeado como sobre stock.{aviso}")
                elif e == "ya":
                    add("Sin solución operativa (mapeado)",
                        f"Ya está subempacado ({sub_act[i]:g}). El sobre stock queda mapeado (el Max cubre {cmax[i]:.0f} días).")
                else:
                    add("Sin solución operativa (mapeado)",
                        f"Subempacar no es posible ({viab[k]}). El sobre stock queda mapeado (el Max cubre {cmax[i]:.0f} días).")
            elif mo.startswith("Sobrestock por cubrir exhibición"):
                add("Informativo",
                    f"Informativo: sobre stock por cubrir la exhibición definida por el área comercial (la Exhi cubre {cexhi[i]:.0f} días; "
                    f"consumo {R[i]:.2f} u/día). Se abastece igual; queda mapeado.")
        acciones.append(principal or "Informativo")
        textos.append(" | ".join(partes))
        alertas.append(alerta)
    rev["ACCIÓN PRINCIPAL"] = acciones
    rev["ALERTA PVP"] = alertas
    rev["SUGERENCIA A REALIZAR"] = textos
    return rev


def marcar_en_revision(df: pd.DataFrame, rev: pd.DataFrame) -> pd.DataFrame:
    """Agrega a la hoja principal la columna EN REVISAR para filtrar los casos de la hoja REVISAR:
    'Sí' = prioridad ALTA/MEDIA (hay algo que gestionar), 'Informativo' = solo mapeado, 'No' = no está en REVISAR.
    La prioridad queda en una columna privada (_PRIORIDAD_REVISAR) solo para colorear la fila al exportar."""
    df = df.drop(columns=[c for c in ("EN REVISAR", "PRIORIDAD REVISAR", "ACCIÓN REVISAR", "_PRIORIDAD_REVISAR")
                          if c in df.columns]).copy()
    llaves = [c for c in ("CD", "Local", "ESTADISTICO") if c in df.columns and c in rev.columns]
    if not llaves or rev.empty:
        df["EN REVISAR"] = "No"
        df["_PRIORIDAD_REVISAR"] = ""
        return df
    mapa = rev[llaves + ["PRIORIDAD"]].drop_duplicates(llaves)
    unido = df[llaves].merge(mapa, on=llaves, how="left")
    pr = unido["PRIORIDAD"]
    df["EN REVISAR"] = np.where(pr.isna().values, "No", np.where(pr.eq("Informativo").values, "Informativo", "Sí"))
    df["_PRIORIDAD_REVISAR"] = unido["PRIORIDAD"].fillna("").values
    return df


# --------------------------------------------------------------------------
# HOJA "SUGERIR SUBEMPAQUE"
# --------------------------------------------------------------------------
def _num(serie: pd.Series) -> pd.Series:
    """Convierte a número precios que pueden venir como texto: '1.00', '1,50', '$ 1.234,50', '1,234.50'."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")

    def conv(v):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        if isinstance(v, (int, float, np.integer, np.floating)):
            return float(v)
        s = re.sub(r"[^0-9,.\-]", "", str(v))
        if not s:
            return np.nan
        if "," in s and "." in s:                       # el último separador es el decimal
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:                                  # solo coma: decimal si hay 1-2 dígitos después
            s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return np.nan
    return serie.map(conv).astype(float)


def sugerir_subempaque(df: pd.DataFrame, p: Params | None = None) -> pd.DataFrame:
    """Productos SIN subempaque en un local que conviene subempacar PARA EVITAR SOBRESTOCK.
    Un producto se sugiere solo si cumple TODO lo siguiente:
      1. Es apto para subempaque: el maestro de productos dice 'Apto para PTL' = Si, no es de las familias excluidas
         (CERVEZAS, CERVEZAS SIN ALCOHOL, AGUAS), no es un ESTADISTICO excluido y tiene EMPAQUE >= mínimo.
      2. El mismo SKU ya está subempacado en al menos N locales del BI (o figura en `skus_sub_extra`).
      3. Hay riesgo de sobrestock: enviar el EMPAQUE completo genera sobrestock (el local tarda más de N días en
         venderlo, o no tuvo consumo) O el producto es de PVP alto (no conviene enviar stock de más con valor alto).
    Es una propuesta de cambio de maestro: el Max de la hoja principal NO la aplica."""
    p = p or Params()
    emp = df["EMPAQUE"].astype(float)
    R = df["CONSUMO DIA"].astype(float)
    inc_act = pd.Series(xround(emp / 2, 0), index=df.index)
    n_sub = df["_N_LOC_SUB"].fillna(0)
    evid_bi = n_sub >= p.min_locales_con_sub
    extra = df["ESTADISTICO"].isin(p.skus_sub_extra)
    sub_sug = pd.Series(np.where(evid_bi, df["_SUB_REF"], np.where(extra, 1, np.nan)), index=df.index)
    sub_sug = np.minimum(sub_sug, emp)

    prohibido = (df["FAMILIA"].astype(str).str.strip().str.upper().isin([f.upper() for f in p.familias_no_subempacar])
                 | df["ESTADISTICO"].isin(p.skus_no_subempacar))
    # Apto = columna 'Apto para PTL' del maestro de productos (sin maestro se asume "Si")
    no_apto = (df["APTO"] != "Si") if p.exigir_apto_subempaque else pd.Series(False, index=df.index)

    # Sobrestock si se envía el empaque completo
    dias_emp = pd.Series(np.where(R > 0, emp / R.where(R > 0), np.nan), index=df.index)   # días que tarda en venderse un empaque
    sin_consumo = R <= 0
    c_sobre = sin_consumo | (dias_emp > p.sub_dias_venta_empaque)
    pvp = _num(df["PVP"])
    c_pvp = pvp >= p.pvp_alto
    # PVP mínimo: filtro obligatorio (un producto barato no se sugiere aunque tenga sobrestock)
    filtro_pvp = c_pvp if p.exigir_pvp_alto else pd.Series(True, index=df.index)

    cand = ((df["SUBEMPAQUE"] == 0) & (emp >= p.min_empaque_sugerir_sub) & (evid_bi | extra) &
            (sub_sug > 0) & (sub_sug < inc_act) & ~prohibido & ~no_apto & filtro_pvp & (c_sobre | c_pvp))
    s = df[cand].copy()
    if s.empty:
        return pd.DataFrame()
    s["SUB SUGERIDO"] = sub_sug[cand].astype(int)
    s["DIAS VENDER EMPAQUE"] = dias_emp[cand]
    s["DIAS VENDER SUB"] = np.where(R[cand] > 0, s["SUB SUGERIDO"] / R[cand].where(R[cand] > 0), np.nan)
    mx_sub, _ = _calc_max(s["Min"], s["CONSUMO DIA"], s["EMPAQUE"], s["SUB SUGERIDO"], p)
    s["MAX CON SUB"] = mx_sub
    s["REDUCCION MAX"] = s["Max"] - s["MAX CON SUB"]
    s["REDUCCION VALOR"] = (s["REDUCCION MAX"] * pvp[cand]).round(2)
    s["EVIDENCIA"] = np.where(s["_N_LOC_SUB"].fillna(0) >= p.min_locales_con_sub,
                              "Subempacado en " + s["_N_LOC_SUB"].fillna(0).astype(int).astype(str)
                              + " de " + s["_N_LOC_SKU"].fillna(0).astype(int).astype(str) + " locales",
                              "SKU de la lista manual")
    s["VALORES EN OTROS LOCALES"] = s["_SUB_VALORES"].fillna("")
    so, sc, pv = c_sobre[cand], sin_consumo[cand], c_pvp[cand]
    s["MOTIVO"] = [
        " + ".join(x for x in (
            ("Sobrestock: sin consumo, un empaque completo queda parado" if c else
             f"Sobrestock: un empaque tarda más de {p.sub_dias_venta_empaque:g} días en venderse") if o else "",
            "PVP alto" if v else "") if x)
        for o, c, v in zip(so, sc, pv)]
    s["PRIORIDAD"] = np.where(so & pv, "Prioridad ALTA", "Prioridad MEDIA")
    s = s.rename(columns={"SUBEMPAQUE": "SUB ACTUAL", "Max": "MAX ACTUAL"})
    s["PVP"] = pvp[cand].values
    cols = ["PRIORIDAD", "MOTIVO", "CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA", "PVP",
            "EMPAQUE", "SUB ACTUAL", "SUB SUGERIDO", "APTO", "EVIDENCIA", "VALORES EN OTROS LOCALES",
            "CONSUMO DIA", "DIAS VENDER EMPAQUE", "DIAS VENDER SUB", "Exhi", "Min", "MAX ACTUAL", "MAX CON SUB",
            "REDUCCION MAX", "REDUCCION VALOR"]
    s = s[[c for c in cols if c in s.columns]]
    return s.sort_values(["PRIORIDAD", "REDUCCION VALOR"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------
# EXPORTACIÓN A EXCEL (3 hojas)
# --------------------------------------------------------------------------
def _leyenda(p: "Params") -> list[tuple[str, str]]:
    """Reglas explicadas, con los parámetros realmente usados."""
    frec = "el mayor intervalo real entre despachos" if p.usar_frec_efectiva else "FREC ENTRE DESP del BI"
    cob = (f"; cobertura adicional de {p.dias_cobertura_max:g} días en múltiplos de ese incremento"
           if p.dias_cobertura_max > 0 else "")
    return [
        ("Contexto", "Todo el BI está en método TDF (abastecimiento por forecast). Las filas de la hoja 'Pronóstico cero' son las que conviene "
                     "pasar a método Min/Max, donde se usan los Min y Max configurados por local y estadístico en lugar del forecast."),
        ("Qué pasa a Min/Max", f"(1) Pronóstico cero o sin pronóstico; (2) pronóstico lineal (en la primera semana, {p.dias_repetidos_lineal} o más de los 7 días repiten valor; que desde el día 8 el modelo copie la semana no cuenta); o (3 y 4 juntas) el promedio diario del "
                               f"pronóstico es menor al {p.factor_prom_exhi:.0%} de la Exhibición Y promedio x (FREC + Dias SS) no cubre ni el {p.pct_empaque_cobertura:.0%} del "
                               "Empq_final. Si cumple la 3 pero el forecast cubre esa parte del empaque, se queda en TDF. Cero y lineal pasan siempre."),
        ("Promedio diario", "TOTAL PRONOSTICO (suma de los días de pronóstico del BI) / N° de días de pronóstico."),
        ("CONSUMO DIA", f"CONSUMOS ACU (consumo acumulado del mes que entrega el BI) / {p.dias_transcurridos} días transcurridos."),
        ("FREC", f"Días entre despachos: {frec}."),
        ("Min · regla A", "Si CONSUMO DIA > Exhi: Min = ROUND(CONSUMO DIA x FREC; 0)."),
        ("Min · regla B", f"Si el producto es apto, la Exhi cubre menos de {p.umbral_dg_exhi:g} días y CONSUMO DIA x FREC > Exhi: Min = ROUND(CONSUMO DIA x FREC; 0)."),
        ("Min · regla C", "Cualquier otro caso (la mayoría): Min = Exhi."),
        ("Max", f"Con SUBEMPAQUE > 0: Max = Min + SUBEMPAQUE. Sin subempaque: Max = Min + ROUND(EMPAQUE / 2; 0), porque el sistema no despacha si lo "
                f"que falta es menos de media caja{cob}. Siempre se respeta el SUBEMPAQUE real del BI."),
        ("Hoja REVISAR", f"Solo casos extremos: inventario físico negativo (ALTA); consumo diario >= {p.factor_consumo_exhi:g} veces la Exhibición (ALTA); "
                         f"sobre stock crítico, con Max / CONSUMO DIA > {p.sobrestock_dias:g} días (MEDIA); y sobre stock por cubrir la exhibición (solo informativo: la exhibición la define el área comercial y siempre se abastece). "
                         "Cada caso trae ACCIÓN PRINCIPAL y SUGERENCIA A REALIZAR: corregir el dato, notificar al área comercial, subempacar si es viable y reduce el Max (con ALERTA PVP si el PVP es menor al mínimo), o dejarlo mapeado. "
                         "En 'Pronóstico cero' esas filas se marcan (EN REVISAR) para filtrarlas."),
        ("Hoja SUGERIR SUBEMPAQUE", f"Productos sin subempaque donde enviar el empaque completo genera sobrestock (el local tarda más de {p.sub_dias_venta_empaque:g} días en "
                                    f"venderlo o no tuvo consumo) o de PVP alto; {'solo con PVP >= ' + format(p.pvp_alto, 'g') + ' (filtro obligatorio); ' if p.exigir_pvp_alto else 'PVP >= ' + format(p.pvp_alto, 'g') + ' = alto; '}aptos según el maestro ('Apto para PTL' = Si); EMPAQUE >= {p.min_empaque_sugerir_sub}; "
                                    f"y el mismo SKU ya subempacado en al menos {p.min_locales_con_sub} locales. Nunca {', '.join(p.familias_no_subempacar) or '(ninguna familia)'}."),
        ("Columnas de control", "% PROM/EXHI = promedio diario / Exhibición; COBERTURA TDF = promedio x (FREC + Dias SS); % COBERTURA/EMPQ = esa cobertura / Empq_final; "
                                "DG MIN / DGMAX = días de consumo que cubren el Min / el Max; CON>EXHI = REVISAR si el consumo diario supera el Min."),
    ]


def exportar_excel(df: pd.DataFrame, rev: pd.DataFrame, resumen: dict, destino,
                   sug: pd.DataFrame | None = None, p: "Params | None" = None) -> None:
    """Escribe: 'Pronóstico cero' (resultado), 'REVISAR', 'SUGERIR SUBEMPAQUE' y 'Resumen' (con formato)."""
    import math
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    p = p or Params()
    sug = sug if sug is not None else pd.DataFrame()
    df = marcar_en_revision(df, rev)
    privadas = [c for c in df.columns if isinstance(c, str) and c.startswith("_")]
    res = df.drop(columns=[c for c in privadas if c in df.columns])
    res.columns = [c.strftime("%Y-%m-%d") if isinstance(c, (dt.datetime, pd.Timestamp)) else c
                   for c in res.columns]
    prio_rev = df["_PRIORIDAD_REVISAR"].values if "_PRIORIDAD_REVISAR" in df.columns else [""] * len(df)
    # Orden: ... Min, Max, EN REVISAR, Exhi, DIF ...  (Exhi se mueve justo antes de DIF)
    if "Max" in res.columns:
        pegadas = [c for c in ("EN REVISAR", "Exhi") if c in res.columns]
        resto = [c for c in res.columns if c not in pegadas]
        pos = resto.index("Max") + 1
        res = res[resto[:pos] + pegadas + resto[pos:]]

    # Paleta
    ROJO, ROJO_OSC, ROJO_CLARO, ROSA = "E30613", "A30410", "FDECEC", "F9C9CD"
    GRIS_OSC, GRIS_CLARO, BLANCO = "2B2B2B", "F4F4F4", "FFFFFF"
    f_rojo = PatternFill("solid", fgColor=ROJO)
    f_gris = PatternFill("solid", fgColor=GRIS_OSC)
    f_min = PatternFill("solid", fgColor=ROJO_CLARO)
    f_max = PatternFill("solid", fgColor=ROSA)
    lado = Side(style="thin", color="E3C4C6")
    borde = Border(bottom=lado)

    with pd.ExcelWriter(destino, engine="openpyxl") as w:
        res.to_excel(w, index=False, sheet_name="Pronóstico cero")
        rev.to_excel(w, index=False, sheet_name="REVISAR")
        if len(sug):
            sug.to_excel(w, index=False, sheet_name="SUGERIR SUBEMPAQUE")
        wr = w.book.create_sheet("Resumen")

        # ---------------- Hojas de datos ----------------
        hojas = [("Pronóstico cero", res, ROJO), ("REVISAR", rev, "ED7D31")] + \
                ([("SUGERIR SUBEMPAQUE", sug, "2F75B5")] if len(sug) else [])
        destacar_min = {"Min"}
        destacar_max = {"Max", "MAX ACTUAL", "MAX CON SUB"}
        ent = {"Min", "Max", "DIF", "Exhi", "EMPAQUE", "SUBEMPAQUE", "CONSUMOS ACU", "UNICOS", "DIAS REPETIDOS SEM1", "FREC EFECTIVA",
               "FREC ENTRE DESP", "Físico", "SUB ACTUAL", "SUB SUGERIDO", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX"}
        pct = {"% CONSUMO/EMPQ", "% EXHI/EMPAQUE", "% PROM/EXHI", "% COBERTURA/EMPQ"}
        dec = {"COBERTURA TDF", "DIAS VENDER EMPAQUE", "DIAS VENDER SUB", "DG MIN", "DGMAX", "DG EXHIBICION",
               "CONSUMO DIA", "%", "PROMEDIO PRONOSTICO DIA", "PRON CICLO", "CONSUMO CICLO", "FALTANTE VS CICLO",
               "DIAS INVENTARIO", "COBERTURA MAX (DIAS)", "COBERTURA EXHI (DIAS)", "REDUCCION VALOR",
               "TOTAL PRONOSTICO"}
        dos_dec = {"PVP", "REDUCCION VALOR"}
        for nombre, d, color_tab in hojas:
            ws = w.sheets[nombre]
            ws.sheet_properties.tabColor = color_tab
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            ws.row_dimensions[1].height = 34
            ws.sheet_view.zoomScale = 90
            n = len(d)
            for i, col in enumerate(d.columns, 1):
                es_min, es_max = col in destacar_min, col in destacar_max
                c = ws.cell(row=1, column=i)
                c.font = Font(bold=True, color=BLANCO, name="Arial", size=10)
                c.fill = f_rojo if (es_min or es_max) else f_gris
                c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                ancho = 70 if col == "MOTIVOS DE REVISIÓN" else min(max(len(str(col)) + 2, 10), 40)
                if col == "DESCRIPCION":
                    ancho = 42
                if col == "MOTIVO MIN/MAX":
                    ancho = 48
                if es_min or es_max:
                    ancho = max(ancho, 12)
                ws.column_dimensions[get_column_letter(i)].width = ancho
                fmt = ("0" if col in ent else ("0.00" if col in dos_dec else ("0.0" if col in dec else ("0%" if col in pct else None))))
                if fmt or es_min or es_max:
                    for r in range(2, n + 2):
                        cel = ws.cell(row=r, column=i)
                        if fmt:
                            cel.number_format = fmt
                        if es_min or es_max:
                            cel.fill = f_min if es_min else f_max
                            cel.font = Font(bold=True, name="Arial", color=ROJO_OSC)
                            cel.alignment = Alignment(horizontal="center")
                if col in ("SUGERENCIA A REALIZAR", "MOTIVOS DE REVISIÓN", "VIABILIDAD SUBEMPAQUE") and n:
                    for r in range(2, n + 2):
                        ws.cell(row=r, column=i).alignment = Alignment(wrap_text=True, vertical="top")
                if col == "SUGERENCIA A REALIZAR":
                    ws.column_dimensions[get_column_letter(i)].width = 95
                if col == "ALERTA PVP":
                    ws.column_dimensions[get_column_letter(i)].width = 22
                    for r in range(2, n + 2):
                        cel = ws.cell(row=r, column=i)
                        cel.alignment = Alignment(wrap_text=True, vertical="top")
                        if cel.value:
                            cel.font = Font(bold=True, color="9C0006", name="Arial")
                            cel.fill = PatternFill("solid", fgColor="FFC7CE")
                if col in ("ACCIÓN PRINCIPAL", "PRIORIDAD") and nombre == "REVISAR":
                    ws.column_dimensions[get_column_letter(i)].width = 40 if col == "ACCIÓN PRINCIPAL" else 17
                    for r in range(2, n + 2):
                        ws.cell(row=r, column=i).alignment = Alignment(wrap_text=True, vertical="top")
                if col == "VIABILIDAD SUBEMPAQUE":
                    ws.column_dimensions[get_column_letter(i)].width = 42
                if col == "EN REVISAR":
                    ws.column_dimensions[get_column_letter(i)].width = 12
                    ws.cell(row=1, column=i).fill = PatternFill("solid", fgColor="ED7D31")
                if str(col) in ("CON>EXHI", "DG EXHI = DG MIN") and n:
                    rango = f"{get_column_letter(i)}2:{get_column_letter(i)}{n + 1}"
                    ws.conditional_formatting.add(rango, CellIsRule(
                        operator="equal", formula=['"REVISAR"'],
                        font=Font(bold=True, color="9C0006"), fill=PatternFill("solid", bgColor="FFC7CE")))

        # Marca de color en las filas de la hoja principal que están en REVISAR
        wp = w.sheets["Pronóstico cero"]
        col_idx = {c: i for i, c in enumerate(res.columns, 1)}
        pf = {"Prioridad ALTA": PatternFill("solid", fgColor="F8CBAD"),
              "Prioridad MEDIA": PatternFill("solid", fgColor="FFE699"),
              "Informativo": PatternFill("solid", fgColor="DDEBF7")}
        if "EN REVISAR" in col_idx:
            ie = col_idx["EN REVISAR"]
            for r, (en, pr) in enumerate(zip(res["EN REVISAR"], prio_rev), 2):
                if en in ("Sí", "Informativo"):
                    c = wp.cell(row=r, column=ie)
                    c.fill = pf.get(pr, PatternFill("solid", fgColor="FFE699"))
                    c.font = Font(bold=True, name="Arial")
                    c.alignment = Alignment(horizontal="center")
                    for nombre_col in ("Local", "ESTADISTICO"):
                        if nombre_col in col_idx:
                            wp.cell(row=r, column=col_idx[nombre_col]).fill = pf.get(pr, PatternFill("solid", fgColor="FFE699"))
        ws = w.sheets["REVISAR"]
        alta = PatternFill("solid", fgColor="F8CBAD")
        media = PatternFill("solid", fgColor="FFF2CC")
        baja = PatternFill("solid", fgColor="DDEBF7")
        for r in range(2, len(rev) + 2):
            v = str(ws.cell(row=r, column=1).value)
            ws.cell(row=r, column=1).fill = alta if "ALTA" in v else baja if "Informativo" in v else media
            ws.cell(row=r, column=1).font = Font(bold=True, name="Arial")

        # ---------------- Hoja Resumen ----------------
        wr.sheet_properties.tabColor = GRIS_OSC
        wr.sheet_view.showGridLines = False
        wr.column_dimensions["A"].width = 2
        for col in "BCDEFG":
            wr.column_dimensions[col].width = 19
        wr.column_dimensions["H"].width = 2

        n_in, n_mm = resumen["filas_bi"], resumen["filas_resultado"]
        n_tdf = n_in - n_mm
        est_mm = int(df["ESTADISTICO"].nunique())
        loc_mm = int(df["Local"].nunique()) if "Local" in df else 0
        fila = [1]

        def celda(r, c, v=None, font=None, fill=None, fmt=None, al=None, border=None):
            x = wr.cell(row=r, column=c)
            if v is not None:
                x.value = v
            if font: x.font = font
            if fill: x.fill = fill
            if fmt: x.number_format = fmt
            if al: x.alignment = al
            if border: x.border = border
            return x

        def unir(r, c1, c2, r2=None):
            wr.merge_cells(start_row=r, start_column=c1, end_row=r2 or r, end_column=c2)

        # Banner
        for r in (1, 2, 3):
            for c in range(2, 8):
                celda(r, c, fill=f_rojo if r < 3 else PatternFill("solid", fgColor=ROJO_OSC))
        unir(1, 2, 7); unir(2, 2, 7); unir(3, 2, 7)
        celda(1, 2, "RESUMEN DEL PROCESO · MIN / MAX", Font(bold=True, size=18, color=BLANCO, name="Arial"),
              al=Alignment(vertical="center", indent=1))
        celda(2, 2, "Qué cambió de método (TDF → Min/Max), cómo se clasificó y qué revisar",
              Font(size=11, color="FFE5E7", name="Arial"), al=Alignment(vertical="center", indent=1))
        fecha = dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        celda(3, 2, f"Generado: {fecha}   ·   Días de consumo transcurridos: {p.dias_transcurridos}   ·   "
                    f"Días de pronóstico en el BI: {resumen['dias_de_pronostico']}",
              Font(size=9, color=BLANCO, name="Arial"), al=Alignment(vertical="center", indent=1))
        wr.row_dimensions[1].height = 34
        wr.row_dimensions[2].height = 20
        fila[0] = 5

        # Tarjetas KPI (3 por fila, cada una ocupa 2 columnas)
        def tarjetas(items):
            r = fila[0]
            for k, (etq, val, fmt) in enumerate(items):
                c1 = 2 + 2 * k
                for rr in (r, r + 1):
                    for cc in (c1, c1 + 1):
                        celda(rr, cc, fill=PatternFill("solid", fgColor=ROJO_CLARO),
                              border=Border(left=Side(style="thick", color=ROJO) if cc == c1 else None))
                unir(r, c1, c1 + 1); unir(r + 1, c1, c1 + 1)
                celda(r, c1, etq, Font(size=9, bold=True, color="6B6B6B", name="Arial"),
                      al=Alignment(indent=1, vertical="center"))
                celda(r + 1, c1, val, Font(size=20, bold=True, color=ROJO, name="Arial"), fmt=fmt,
                      al=Alignment(indent=1, vertical="center", horizontal="left"))
            wr.row_dimensions[r].height = 18
            wr.row_dimensions[r + 1].height = 30
            fila[0] = r + 3

        tarjetas([("FILAS DEL BI (Local x Estadístico)", n_in, "#,##0"),
                  ("PASAN A MIN/MAX", n_mm, "#,##0"),
                  ("SE QUEDAN EN TDF", n_tdf, "#,##0")])
        tarjetas([("% DEL BI QUE CAMBIA DE MÉTODO", n_mm / n_in if n_in else 0, "0.0%"),
                  ("ESTADÍSTICOS DISTINTOS EN MIN/MAX", est_mm, "#,##0"),
                  ("LOCALES CON CAMBIOS", loc_mm, "#,##0")])

        def titulo(txt):
            r = fila[0]
            for c in range(2, 8):
                celda(r, c, border=Border(bottom=Side(style="medium", color=ROJO)))
            unir(r, 2, 7)
            celda(r, 2, txt, Font(bold=True, size=13, color=GRIS_OSC, name="Arial"),
                  border=Border(bottom=Side(style="medium", color=ROJO)))
            wr.row_dimensions[r].height = 22
            fila[0] = r + 1

        def tabla(heads, filas, fmts=None):
            """heads: ['Concepto', 'Filas', ...] (máx. 4). Concepto ocupa B:D; los valores E, F, G."""
            r = fila[0]
            fmts = fmts or ["#,##0", "#,##0", "0.0%"]
            for c in range(2, 8):
                celda(r, c, fill=f_gris)
            unir(r, 2, 4)
            celda(r, 2, heads[0], Font(bold=True, color=BLANCO, name="Arial", size=10), al=Alignment(indent=1))
            for k, h in enumerate(heads[1:]):
                celda(r, 5 + k, h, Font(bold=True, color=BLANCO, name="Arial", size=10),
                      al=Alignment(horizontal="center", wrap_text=True, vertical="center"))
            wr.row_dimensions[r].height = 26
            for j, fl in enumerate(filas):
                rr = r + 1 + j
                fondo = PatternFill("solid", fgColor=GRIS_CLARO if j % 2 else BLANCO)
                for c in range(2, 8):
                    celda(rr, c, fill=fondo, border=borde)
                unir(rr, 2, 4)
                celda(rr, 2, fl[0], Font(name="Arial", size=10), al=Alignment(indent=1, wrap_text=True, vertical="center"))
                for k, v in enumerate(fl[1:]):
                    celda(rr, 5 + k, v, Font(name="Arial", size=10, bold=(k == 0)),
                          fmt=fmts[k] if isinstance(v, (int, float, np.integer, np.floating)) else None,
                          al=Alignment(horizontal="center", vertical="center"))
                largo = len(str(fl[0]))
                wr.row_dimensions[rr].height = 16 if largo <= 52 else 16 * math.ceil(largo / 52)
            fila[0] = r + len(filas) + 2

        def por_grupo(serie_grupo, df_base, orden=None, nombres=None):
            tot = len(df_base) or 1
            filas = []
            g = df_base.groupby(serie_grupo, dropna=False)
            claves = list(orden) if orden else list(g.groups.keys())
            for k in claves:
                if k not in g.groups:
                    continue
                sub = df_base.loc[g.groups[k]]
                filas.append(((nombres or {}).get(k, str(k)), len(sub), int(sub["ESTADISTICO"].nunique()), len(sub) / tot))
            return filas

        # 1) Qué cambió
        titulo("1. Cambio de método: de dónde partimos y a dónde llegamos")
        seg = [
            ("Pronóstico cero o sin pronóstico", resumen["segmento_1_pasa_pronostico_cero"], "Min/Max"),
            (f"Pronóstico lineal ({p.dias_repetidos_lineal} o más días repetidos en la 1ª semana)", resumen["segmento_2_pasa_pronostico_lineal"], "Min/Max"),
            (f"Promedio < {p.factor_prom_exhi:.0%} de la Exhi y cobertura < {p.pct_empaque_cobertura:.0%} del empaque (reglas 3 y 4)",
             resumen["segmento_3_pasa_prom_exhi_y_cobertura_empaque"], "Min/Max"),
            (f"Promedio bajo, pero el forecast cubre {p.pct_empaque_cobertura:.0%} del empaque", resumen["segmento_4_tdf_rescatado_por_cobertura_empaque"], "TDF"),
            ("Pronóstico normal", resumen["segmento_5_tdf_pronostico_normal"], "TDF"),
        ]
        filas = [("Total BI · todo viene en TDF", n_in, 1.0, "TDF")]
        filas += [(a, b, b / n_in if n_in else 0, c) for a, b, c in seg]
        filas += [("RESULTADO · se quedan en TDF", n_tdf, n_tdf / n_in if n_in else 0, "TDF"),
                  ("RESULTADO · pasan a Min/Max", n_mm, n_mm / n_in if n_in else 0, "Min/Max")]
        tabla(["Segmento", "Filas", "% del BI", "Método final"], filas, ["#,##0", "0.0%"])

        # 2) Clasificación por motivo
        titulo("2. Clasificación de lo que pasa a Min/Max (por motivo)")
        if "MOTIVO MIN/MAX" in df:
            tabla(["Motivo del cambio", "Filas", "Estadísticos distintos", "% de los que pasan"],
                  por_grupo("MOTIVO MIN/MAX", df) + [("TOTAL", n_mm, est_mm, 1.0)])

        # 3) Regla del Min
        titulo("3. Cómo quedó el Min (regla aplicada)")
        if "_regla_min" in df:
            nombres_min = {"A": "A · consumo diario > Exhi → Min = ROUND(consumo x FREC)",
                           "B": "B · Exhi cubre poco y consumo x FREC > Exhi → Min = ROUND(consumo x FREC)",
                           "C": "C · Min = Exhi (la exhibición)"}
            claves = {str(k)[:1]: k for k in df["_regla_min"].dropna().unique()}
            filas = por_grupo("_regla_min", df, orden=[claves[k] for k in "ABC" if k in claves],
                              nombres={claves[k]: nombres_min[k] for k in claves if k in nombres_min})
            tabla(["Regla del Min", "Filas", "Estadísticos distintos", "% de los que pasan"], filas)

        # 4) Regla del Max
        titulo("4. Cómo quedó el Max")
        sub_si = df[df["SUBEMPAQUE"] > 0]
        sub_no = df[~(df["SUBEMPAQUE"] > 0)]
        filas = [("Con SUBEMPAQUE → Max = Min + SUBEMPAQUE", len(sub_si), int(sub_si["ESTADISTICO"].nunique()), len(sub_si) / (n_mm or 1)),
                 ("Sin subempaque → Max = Min + ROUND(EMPAQUE / 2)", len(sub_no), int(sub_no["ESTADISTICO"].nunique()), len(sub_no) / (n_mm or 1))]
        if resumen.get("max_por_cobertura"):
            filas.append(("Max ampliado por cobertura adicional de días", resumen["max_por_cobertura"], None, resumen["max_por_cobertura"] / (n_mm or 1)))
        tabla(["Regla del Max", "Filas", "Estadísticos distintos", "% de los que pasan"], filas)

        # 5) Unidades
        titulo("5. Unidades configuradas")
        s_min, s_max, s_exhi = int(df["Min"].sum()), int(df["Max"].sum()), int(pd.to_numeric(df["Exhi"], errors="coerce").fillna(0).sum())
        tabla(["Concepto", "Unidades"], [
            ("Suma de la Exhibición de las filas que pasan", s_exhi),
            ("Suma de los Min", s_min),
            ("Suma de los Max", s_max),
            ("Diferencia Max − Min (colchón de reposición)", s_max - s_min),
            ("Filas con Min por encima de la Exhi (reglas A y B)", int((df["Min"] > pd.to_numeric(df["Exhi"], errors="coerce").fillna(0)).sum())),
        ], ["#,##0"])

        # 6) REVISAR
        titulo("6. Casos para revisar (hoja REVISAR)")
        if len(rev):
            orden = ["Prioridad ALTA", "Prioridad MEDIA", "Informativo"]
            tot_r = len(rev)
            filas = []
            for k in orden:
                s = rev[rev["PRIORIDAD"] == k]
                if len(s):
                    filas.append((k, len(s), int(s["ESTADISTICO"].nunique()), len(s) / tot_r))
            filas.append(("TOTAL", tot_r, int(rev["ESTADISTICO"].nunique()), 1.0))
            tabla(["Prioridad", "Filas", "Estadísticos distintos", "% del total"], filas)
        else:
            tabla(["Prioridad", "Filas"], [("Sin casos para revisar", 0)])

        if len(rev) and "ACCIÓN PRINCIPAL" in rev:
            titulo("6b. Acción sugerida para los casos de REVISAR")
            orden_a = ["Corregir inventario", "Notificar al área comercial", "Subempacar", "Evaluar subempaque",
                       "Sin solución operativa (mapeado)", "Informativo"]
            filas = []
            for k in orden_a:
                s = rev[rev["ACCIÓN PRINCIPAL"] == k]
                if len(s):
                    filas.append((k, len(s), int(s["ESTADISTICO"].nunique()), len(s) / len(rev)))
            n_alerta = int((rev["ALERTA PVP"].astype(str) != "").sum()) if "ALERTA PVP" in rev else 0
            if n_alerta:
                filas.append(("⚠ Con alerta de PVP bajo (subempaque recomendado con PVP < mínimo)", n_alerta,
                              int(rev.loc[rev["ALERTA PVP"].astype(str) != "", "ESTADISTICO"].nunique()), n_alerta / len(rev)))
            tabla(["Acción principal", "Filas", "Estadísticos distintos", "% del total"], filas)

        # 7) Subempaque
        titulo("7. Sugerencias de subempaque (hoja SUGERIR SUBEMPAQUE)")
        if len(sug):
            filas = []
            for k in ["Prioridad ALTA", "Prioridad MEDIA", "Prioridad BAJA"]:
                s = sug[sug["PRIORIDAD"] == k]
                if len(s):
                    filas.append((k, len(s), int(s["ESTADISTICO"].nunique()), len(s) / len(sug)))
            filas.append(("TOTAL", len(sug), int(sug["ESTADISTICO"].nunique()), 1.0))
            if "REDUCCION MAX" in sug:
                filas.append(("Unidades de Max que se evitarían", int(pd.to_numeric(sug["REDUCCION MAX"], errors="coerce").fillna(0).sum()), None, None))
            tabla(["Prioridad", "Filas", "Estadísticos distintos", "% del total"], filas)
        else:
            tabla(["Prioridad", "Filas"], [("Sin sugerencias con los parámetros actuales", 0)])

        # 8) Top locales / familias
        titulo("8. Dónde se concentran los cambios")
        if "Local" in df:
            top = df.groupby("Local").agg(f=("ESTADISTICO", "size"), e=("ESTADISTICO", "nunique")).sort_values("f", ascending=False).head(10)
            tabla(["Top 10 locales", "Filas", "Estadísticos distintos", "% de los que pasan"],
                  [(f"Local {k}", int(v.f), int(v.e), v.f / (n_mm or 1)) for k, v in top.iterrows()])
        if "FAMILIA" in df:
            top = df.groupby("FAMILIA").agg(f=("ESTADISTICO", "size"), e=("ESTADISTICO", "nunique")).sort_values("f", ascending=False).head(10)
            tabla(["Top 10 familias", "Filas", "Estadísticos distintos", "% de los que pasan"],
                  [(str(k), int(v.f), int(v.e), v.f / (n_mm or 1)) for k, v in top.iterrows()])

        # 9) Diagnóstico / avisos
        titulo("9. Diagnóstico del pronóstico y avisos")
        tabla(["Indicador (sobre las filas que pasan)", "Filas"], [
            ("Pronóstico insuficiente (promedio < %g u/día)" % p.umbral_venta_prom_dia, resumen["pronostico_insuficiente"]),
            ("Pronóstico con valores repetidos", resumen["pronostico_valores_repetidos"]),
            ("Pronóstico del ciclo mayor que la Exhi", resumen["pronostico_ciclo_mayor_exhi"]),
            ("Frecuencia efectiva mayor que la del BI", resumen["frec_efectiva_mayor_que_bi"]),
        ], ["#,##0"])
        avisos = []
        if resumen.get("posible_truncado_bi"):
            avisos.append("El BI trae ~30.000 filas: la descarga puede estar truncada. Verifica que no falten locales o SKUs.")
        if resumen["dias_de_pronostico"] < 12:
            avisos.append(f"El BI trae {resumen['dias_de_pronostico']} días de pronóstico (no 12); los promedios se calculan con esos días.")
        if resumen.get("skus_sin_dato_apto") is None:
            avisos.append("No se cargó el maestro de productos: se asumió APTO = 'Si' para todos.")
        elif resumen.get("skus_sin_dato_apto"):
            avisos.append(f"{resumen['skus_sin_dato_apto']} productos no aparecen en el maestro: se trataron como APTO = 'Si'.")
        if not avisos:
            avisos.append("Sin avisos: no se detectaron problemas en la carga.")
        r = fila[0]
        for a in avisos:
            for c in range(2, 8):
                celda(r, c, fill=PatternFill("solid", fgColor="FFF2CC"))
            unir(r, 2, 7)
            celda(r, 2, "⚠ " + a, Font(name="Arial", size=10), al=Alignment(indent=1, wrap_text=True, vertical="center"))
            wr.row_dimensions[r].height = 18 if len(a) < 110 else 32
            r += 1
        fila[0] = r + 1

        # 10) Parámetros usados
        titulo("10. Parámetros usados en este cálculo")
        params = [
            ("Días de consumo transcurridos", p.dias_transcurridos),
            ("Regla 3 · promedio < % de la Exhibición", f"{p.factor_prom_exhi:.0%}"),
            ("Regla 4 · promedio x (FREC + Dias SS) < % del empaque final", f"{p.pct_empaque_cobertura:.0%}"),
            ("Pronóstico lineal: días repetidos en la 1ª semana >=", p.dias_repetidos_lineal),
            ("Exhibición cubre menos de (días)", p.umbral_dg_exhi),
            ("Usar el mayor intervalo real entre despachos", "Sí" if p.usar_frec_efectiva else "No"),
            ("Cobertura adicional del Max (días)", p.dias_cobertura_max),
            ("Sobre stock crítico: Max cubre más de (días)", p.sobrestock_dias),
            ("Incongruencia: consumo >= (veces la Exhibición)", p.factor_consumo_exhi),
            ("Subempaque · días para vender un empaque completo >", p.sub_dias_venta_empaque),
            ("Subempaque · PVP alto >=", p.pvp_alto),
            ("Subempaque · exigir PVP alto (filtro obligatorio)", "Sí" if p.exigir_pvp_alto else "No"),
            ("Subempaque · exigir producto apto", "Sí" if p.exigir_apto_subempaque else "No"),
            ("Subempaque · EMPAQUE >=", p.min_empaque_sugerir_sub),
            ("Subempaque · SKU subempacado en al menos N locales", p.min_locales_con_sub),
            ("Familias que nunca se subempacan", ", ".join(p.familias_no_subempacar) or "—"),
        ]
        r = fila[0]
        for c in range(2, 8):
            celda(r, c, fill=f_gris)
        unir(r, 2, 5); unir(r, 6, 7)
        celda(r, 2, "Parámetro", Font(bold=True, color=BLANCO, name="Arial", size=10), al=Alignment(indent=1))
        celda(r, 6, "Valor", Font(bold=True, color=BLANCO, name="Arial", size=10), al=Alignment(horizontal="center"))
        for j, (k, v) in enumerate(params):
            rr = r + 1 + j
            fondo = PatternFill("solid", fgColor=GRIS_CLARO if j % 2 else BLANCO)
            for c in range(2, 8):
                celda(rr, c, fill=fondo, border=borde)
            unir(rr, 2, 5); unir(rr, 6, 7)
            celda(rr, 2, k, Font(name="Arial", size=10), al=Alignment(indent=1))
            celda(rr, 6, v, Font(name="Arial", size=10, bold=True), al=Alignment(horizontal="center", wrap_text=True),
                  fmt="General")
        fila[0] = r + len(params) + 2

        # 11) Reglas
        titulo("11. Reglas que se aplicaron")
        r = fila[0]
        for j, (k, v) in enumerate(_leyenda(p)):
            rr = r + j
            fondo = PatternFill("solid", fgColor=GRIS_CLARO if j % 2 else BLANCO)
            for c in range(2, 8):
                celda(rr, c, fill=fondo, border=borde)
            unir(rr, 2, 3); unir(rr, 4, 7)
            celda(rr, 2, k, Font(name="Arial", size=10, bold=True, color=ROJO_OSC), al=Alignment(indent=1, vertical="top", wrap_text=True))
            celda(rr, 4, v, Font(name="Arial", size=10), al=Alignment(wrap_text=True, vertical="top"))
            wr.row_dimensions[rr].height = 15 * max(1, math.ceil(len(v) / 78)) + 4
