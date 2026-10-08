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
    pct_empaque_min_max: float = 0.5     # pasa a Min/Max si (pronóstico promedio diario x FREC) < 50 % de Empq_final
    umbral_unicos: int = 5               # pasa a Min/Max si UNICOS <= 5 (pronóstico con valores repetidos = poco confiable)
    # --- Cálculo del Min ---
    umbral_dg_exhi: float = 2.0          # Exhi/consumo < 2 días -> sube a cobertura (regla B)
    usar_frec_efectiva: bool = False     # False: FREC del BI (promedio). True: MAYOR intervalo real entre despachos
    # --- Cálculo del Max ---
    dias_cobertura_max: float = 0.0      # 0 = desactivado (Max = Min + SUBEMPAQUE o EMPAQUE/2)
    # --- Diagnóstico del pronóstico ---
    umbral_venta_prom_dia: float = 1.0   # pronóstico promedio < 1 unid/día = "insuficiente"
    # --- Hoja REVISAR (solo casos extremos) ---
    sobrestock_dias: float = 120.0       # sobre stock crítico: cobertura del Max (Max / CONSUMO DIA) > 120 días
    factor_consumo_exhi: float = 3.0     # incongruencia severa: CONSUMO DIA >= 3 x Exhi
    consumo_bajo_exhi: float = 0.5       # consumo diario < 0.5 y solo la Exhi ya supera sobrestock_dias -> "Sobrestock por exhibición"
    pct_exhi_en_cobertura: float = 0.8   # no es sobre stock si la Exhi explica >= 80 % de los días de cobertura del Max
    # --- Sugerencias de subempaque (el Max usa SIEMPRE el SUBEMPAQUE real del BI) ---
    min_empaque_sugerir_sub: int = 6     # solo se sugiere subempacar si EMPAQUE >= 6
    min_locales_con_sub: int = 1         # el SKU debe estar subempacado en >= N locales del BI
    pvp_alto: float = 5.0                # criterio 1: PVP >= 5 (aprox. 10 % de productos más caros)
    sub_consumo_bajo_dia: float = 1.0    # criterio 2: consumo diario < 1 unidad/día = bajo consumo
    sub_pct_exhi_max: float = 0.5        # criterio 3: Exhi / EMPAQUE < 50 %
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
    suma = np.nansum(V, axis=1)
    igual = (V[:, :, None] == V[:, None, :]).sum(axis=2)     # NaN nunca es igual
    unicos = (igual == 1).sum(axis=1)
    df["SUMA"] = np.round(suma, 4)
    df["UNICOS"] = unicos
    sin_pron = np.all(np.isnan(V), axis=1)

    # Filtro TDF -> Min/Max: pronóstico promedio diario x frecuencia < X % del empaque final
    pron_prom = suma / n_dias
    #   a) pronóstico cero / sin pronóstico (SUMA = 0)
    #   b) pronóstico bajo: pronóstico promedio diario x FREC < X % de Empq_final
    #   c) pronóstico repetido: UNICOS <= umbral (el forecast copia los mismos valores = poco confiable)
    # Pasa a Min/Max si cumple CUALQUIERA; si no cumple ninguna, se queda en TDF.
    cero = suma == 0
    bajo = (pron_prom * df["FREC EFECTIVA"].values) < p.pct_empaque_min_max * df["Empq_final"].values
    repet = unicos <= p.umbral_unicos
    cond_mm = bajo | repet | cero
    seg = {                                   # segmentos mutuamente excluyentes (suman el total del BI)
        "1_pasa_pronostico_cero": int(cero.sum()),
        "2_pasa_pronostico_bajo": int((bajo & ~repet & ~cero).sum()),
        "3_pasa_pronostico_bajo_y_repetido": int((bajo & repet & ~cero).sum()),
        "4_pasa_solo_pronostico_repetido": int((repet & ~bajo & ~cero).sum()),
        "5_queda_en_TDF": int((~cond_mm).sum()),
        "total_BI": n_in,
    }
    motivo = np.where(cero, "Pronóstico cero",
              np.where(bajo & repet, "Pronóstico bajo + repetido",
              np.where(bajo, "Pronóstico bajo",
              np.where(repet, "Pronóstico repetido", ""))))
    df["MOTIVO MIN/MAX"] = motivo
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
    df["PRON PROM DIA"] = np.round(df["SUMA"] / n_dias, 2)
    df["PRON x FREC"] = np.round(df["SUMA"] / n_dias * df["FREC EFECTIVA"], 2)
    df["% PRON/EMPQ"] = df["PRON x FREC"] / df["Empq_final"]
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
        **{f"segmento_{k}": v for k, v in seg.items()},
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
        "pronostico_cero_o_sin_pronostico": int((df["SUMA"] == 0).sum()),
        "dias_de_pronostico": n_dias,
        "columnas_pronostico_usadas": f"{fechas[0]} ... {fechas[-1]}" if fechas else "",
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
                     "FREC EFECTIVA", "PRON PROM DIA", "PRON x FREC", "% PRON/EMPQ", "% CONSUMO/EMPQ",
                     "PRON CICLO", "DIAG PRONOSTICO", "SUMA < EXHI", "MOTIVO MIN/MAX"]
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
    # Consumo bajo (< 0.5/día) y la sola exhibición ya cubre más de sobrestock_dias: se muestra con leyenda aparte.
    sobre_exhi = (R > 0) & (R < p.consumo_bajo_exhi) & (df["COBERTURA EXHI (DIAS)"] > p.sobrestock_dias)
    sobrestock = (df["COBERTURA MAX (DIAS)"] > p.sobrestock_dias) & ~exhi_explica.fillna(False) & ~sobre_exhi
    inv_neg = inv < 0
    incongruencia = (R > 0) & (R >= p.factor_consumo_exhi * exhi)

    reglas = [
        ("Prioridad ALTA", "Inventario Físico Negativo", inv_neg),
        ("Prioridad ALTA", "Consumo diario triplica la Exhibición", incongruencia),
        ("Prioridad MEDIA", f"Sobre stock: Cobertura > {p.sobrestock_dias:g} días", sobrestock),
        ("Prioridad BAJA", "Sobrestock por exhibición", sobre_exhi),
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
    rev["_ord"] = rev["PRIORIDAD"].map({"Prioridad ALTA": 0, "Prioridad MEDIA": 1, "Prioridad BAJA": 2})
    rev = rev.sort_values(["_ord", "UNIDADES SOBRE MAX", "FALTANTE VS CICLO"], ascending=[True, False, False]).drop(columns="_ord")
    rev["DIAS INVENTARIO"] = rev["DIAS INVENTARIO"].replace(np.inf, 9999)   # sin consumo en el mes
    cols = ["PRIORIDAD", "MOTIVOS DE REVISIÓN", "N° MOTIVOS", "CD", "Local", "DESIGNACION",
            "ESTADISTICO", "DESCRIPCION", "FAMILIA", "APTO", "Empq_final", "SUBEMPAQUE", "FREC EFECTIVA",
            "CONSUMO DIA", "CONSUMO CICLO", "Exhi", "INV NETO", "DIAS INVENTARIO", "UNIDADES SOBRE MAX",
            "Min", "Max", "COBERTURA EXHI (DIAS)", "COBERTURA MAX (DIAS)", "FALTANTE VS CICLO", "_regla_min", "MOTIVO MIN/MAX"]
    return rev[[c for c in cols if c in rev.columns]].reset_index(drop=True)


# --------------------------------------------------------------------------
# HOJA "SUGERIR SUBEMPAQUE"
# --------------------------------------------------------------------------
def sugerir_subempaque(df: pd.DataFrame, p: Params | None = None) -> pd.DataFrame:
    """Productos SIN subempaque en un local que conviene subempacar.
    Reglas:
      1. Nunca: familias excluidas (CERVEZAS, CERVEZAS SIN ALCOHOL, AGUAS) ni ESTADISTICOS excluidos.
      2. Solo si cumple al menos UNO de: PVP alto, bajo consumo, o Exhi/EMPAQUE < 50 %.
      3. El mismo SKU debe estar ya subempacado en otros locales del BI (o figurar en `skus_sub_extra`).
    Es una propuesta de cambio de maestro: el Max de la hoja principal NO la aplica."""
    p = p or Params()
    emp = df["EMPAQUE"].astype(float)
    inc_act = pd.Series(xround(emp / 2, 0), index=df.index)
    n_sub = df["_N_LOC_SUB"].fillna(0)
    evid_bi = n_sub >= p.min_locales_con_sub
    extra = df["ESTADISTICO"].isin(p.skus_sub_extra)
    sub_sug = pd.Series(np.where(evid_bi, df["_SUB_REF"], np.where(extra, 1, np.nan)), index=df.index)
    sub_sug = np.minimum(sub_sug, emp)

    prohibido = (df["FAMILIA"].astype(str).str.strip().str.upper().isin([f.upper() for f in p.familias_no_subempacar])
                 | df["ESTADISTICO"].isin(p.skus_no_subempacar))
    pvp = pd.to_numeric(df["PVP"], errors="coerce")
    c_pvp = pvp >= p.pvp_alto
    c_cons = df["CONSUMO DIA"] < p.sub_consumo_bajo_dia
    pct_exhi = df["Exhi"] / emp.replace(0, np.nan)
    c_exhi = pct_exhi < p.sub_pct_exhi_max

    cand = ((df["SUBEMPAQUE"] == 0) & (emp >= p.min_empaque_sugerir_sub) & (evid_bi | extra) &
            (sub_sug > 0) & (sub_sug < inc_act) & ~prohibido & (c_pvp | c_cons | c_exhi))
    s = df[cand].copy()
    if s.empty:
        return pd.DataFrame()
    s["SUB SUGERIDO"] = sub_sug[cand].astype(int)
    s["% EXHI/EMPAQUE"] = pct_exhi[cand]
    mx_sub, _ = _calc_max(s["Min"], s["CONSUMO DIA"], s["EMPAQUE"], s["SUB SUGERIDO"], p)
    s["MAX CON SUB"] = mx_sub
    s["REDUCCION MAX"] = s["Max"] - s["MAX CON SUB"]
    s["REDUCCION VALOR"] = (s["REDUCCION MAX"] * pvp[cand]).round(2)
    s["EVIDENCIA"] = np.where(s["_N_LOC_SUB"].fillna(0) >= p.min_locales_con_sub,
                              "Subempacado en " + s["_N_LOC_SUB"].fillna(0).astype(int).astype(str)
                              + " de " + s["_N_LOC_SKU"].fillna(0).astype(int).astype(str) + " locales",
                              "SKU de la lista manual")
    s["VALORES EN OTROS LOCALES"] = s["_SUB_VALORES"].fillna("")
    n_crit = c_pvp[cand].astype(int) + c_cons[cand].astype(int) + c_exhi[cand].astype(int)
    partes = pd.DataFrame({"PVP alto": c_pvp[cand], "Bajo consumo": c_cons[cand],
                           f"Exhi < {p.sub_pct_exhi_max:.0%} del empaque": c_exhi[cand]})
    s["MOTIVO"] = partes.apply(lambda r: " + ".join(k for k, v in r.items() if v), axis=1)
    s["PRIORIDAD"] = np.where(n_crit >= 2, "Prioridad ALTA", "Prioridad MEDIA")
    s = s.rename(columns={"SUBEMPAQUE": "SUB ACTUAL", "Max": "MAX ACTUAL"})
    cols = ["PRIORIDAD", "MOTIVO", "CD", "Local", "DESIGNACION", "ESTADISTICO", "DESCRIPCION", "FAMILIA",
            "EMPAQUE", "SUB ACTUAL", "SUB SUGERIDO", "EVIDENCIA", "VALORES EN OTROS LOCALES", "Exhi",
            "% EXHI/EMPAQUE", "CONSUMO DIA", "Min", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX", "PVP",
            "REDUCCION VALOR"]
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
    res = df.drop(columns=[c for c in privadas if c in df.columns])
    res.columns = [c.strftime("%Y-%m-%d") if isinstance(c, (dt.datetime, pd.Timestamp)) else c
                   for c in res.columns]

    leyenda = pd.DataFrame({
        "Concepto": [
            "Contexto", "Qué filas aparecen aquí", "CONSUMO DIA", "FREC EFECTIVA",
            "Regla A del Min", "Regla B del Min", "Regla C del Min (mayoría)", "Max", "SUBEMPAQUE",
            "Hoja REVISAR", "Hoja SUGERIR SUBEMPAQUE", "Diagnóstico del pronóstico"],
        "Descripción": [
            "Todo el BI está en método TDF (abastecimiento por forecast). Las filas de este archivo son las que conviene pasar a método Min/Max, "
            "donde se usan los Min y Max configurados por local y estadístico en lugar del forecast",
            "Pasa a Min/Max el producto cuyo pronóstico NO es confiable para abastecer por forecast: (a) pronóstico cero o sin pronóstico, "
            "(b) pronóstico bajo: promedio diario x FREC < 50 % de Empq_final, o (c) pronóstico repetido: UNICOS <= 5. "
            "La columna MOTIVO MIN/MAX indica cuál aplicó. Los que no cumplen ninguna se quedan en TDF y no aparecen aquí",
            "CONSUMOS ACU (consumo acumulado del mes que entrega el BI) / días del mes transcurridos (parámetro)",
            "Días entre despachos. Por defecto es FREC ENTRE DESP del BI; opcionalmente el mayor intervalo real según LUNES..DOMINGO",
            "Si CONSUMO DIA > Exhi: Min = ROUND(CONSUMO DIA x FREC; 0)",
            "Si APTO=Si, Exhi/CONSUMO DIA < 2 días y consumo x FREC > Exhi: Min = ROUND(consumo x FREC; 0)",
            "Min = Exhi",
            "SUBEMPAQUE > 0: Max = Min + SUBEMPAQUE; si no: Max = Min + ROUND(EMPAQUE/2; 0) (con ROQ < EMPAQUE/2 el sistema no despacha). Opcional: cobertura de N días en múltiplos de ese incremento",
            "Se respeta el SUBEMPAQUE del BI (el real del sistema); el Max nunca asume un subempaque que no existe",
            "SOLO casos extremos: (1) inventario físico negativo (ALTA); (2) consumo diario >= 3 veces la Exhibición (ALTA); "
            "(3) sobre stock crítico: cobertura del Max (Max / CONSUMO DIA) > 120 días, salvo que la Exhibición cubra >= 80 % de esos días (stock ligado a la exhibición) (MEDIA); "
            "(4) 'Sobrestock por exhibición' (BAJA, informativo): consumo diario < 0.5 y la sola Exhibición ya cubre más de 120 días. "
            "No se listan advertencias operativas normales",
            "Productos sin subempaque que cumplen PVP alto, bajo consumo o Exhi/EMPAQUE < 50 %, cuyo mismo SKU ya está subempacado en otros locales. "
            "Nunca CERVEZAS, CERVEZAS SIN ALCOHOL ni AGUAS, ni los ESTADISTICOS excluidos. Es una propuesta de cambio de maestro; muestra el Max resultante",
            "PRON PROM DIA = SUMA / días de pronóstico del BI (normalmente 12; <1 u/día = insuficiente); UNICOS bajo = valores repetidos; PRON CICLO = venta pronosticada hasta el próximo despacho; SUMA < EXHI = pronóstico no alcanza la exhibición"],
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
        ent = {"Min", "Max", "DIF", "Exhi", "EMPAQUE",
               "SUBEMPAQUE", "CONSUMOS ACU", "UNICOS", "FREC EFECTIVA", "FREC ENTRE DESP", "Físico",
               "SUB ACTUAL", "SUB SUGERIDO", "MAX ACTUAL", "MAX CON SUB", "REDUCCION MAX"}
        pct = {"% PRON/EMPQ", "% CONSUMO/EMPQ", "% EXHI/EMPAQUE"}
        dec = {"DG MIN", "DGMAX", "DG EXHIBICION", "CONSUMO DIA", "%", "PRON PROM DIA", "PRON x FREC", "PRON CICLO", "CONSUMO CICLO", "FALTANTE VS CICLO", "DIAS INVENTARIO", "COBERTURA MAX (DIAS)", "COBERTURA EXHI (DIAS)",
               "PVP", "REDUCCION VALOR"}
        for nombre, d in hojas:
            ws_ = w.sheets[nombre]
            for i, col in enumerate(d.columns, 1):
                fmt = "0" if col in ent else ("0.0" if col in dec else ("0%" if col in pct else None))
                if fmt:
                    for r in range(2, len(d) + 2):
                        ws_.cell(row=r, column=i).number_format = fmt
        ws = w.sheets["REVISAR"]
        alta = PatternFill("solid", fgColor="F8CBAD")
        media = PatternFill("solid", fgColor="FFF2CC")
        baja = PatternFill("solid", fgColor="DDEBF7")
        for r in range(2, len(rev) + 2):
            ws.cell(row=r, column=1).fill = (alta if "ALTA" in str(ws.cell(row=r, column=1).value)
                                                  else baja if "BAJA" in str(ws.cell(row=r, column=1).value) else media)
        resaltar = [i for i, c in enumerate(rev.columns, 1) if c in ("Min", "Max")]
        for r in range(2, len(rev) + 2):
            for i in resaltar:
                ws.cell(row=r, column=i).font = Font(bold=True, name="Arial")
        wr = w.sheets["Resumen"]
        wr.column_dimensions["A"].width = 34
        wr.column_dimensions["B"].width = 110
