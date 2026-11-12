"""Pruebas del módulo Min/Max -> TDF con datos inventados.  Ejecutar:  python tests/test_motor_tdf.py"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from motor_minmax import Params  # noqa: E402
from motor_tdf import ParamsTDF, hoja_carga, procesar_m_a_tdf, exportar_excel_tdf  # noqa: E402

FECHAS = [f"{d:02d}/NOV/2026" for d in range(12, 24)]
NORMAL = [1.2, 0.8, 1.5, 0.9, 1.1, 0.7, 1.3, 0.6, 1.4, 0.95, 1.05, 0.85]


def fila(est, pron, exclusion="", metodo="M", exhi=6, emp=12, sub=0, cons=5):
    d = {"Método": metodo, "CD": 100, "Local": 101, "DESIGNACION": "CENTRO", "ESTADISTICO": est, "DESCRIPCION": f"PRODUCTO {est}",
         "EXCLUSION": exclusion, "Dias SS": 0, "EMPAQUE": emp, "SUBEMPAQUE": sub, "CONSUMOS ACU": cons, "INV NETO": 3, "Físico": 3,
         "Min": 6, "Max": 12, "Exhi": exhi, "DESTACADOS": 0, "FREC ENTRE DESP": 2, "FAMILIA": "SECOS"}
    d.update(dict(zip(FECHAS, pron)))
    return d


def main():
    filas = [
        fila(1, NORMAL, "LI"),                                    # pasa
        fila(2, NORMAL, "", cons=0),                              # pasa, vacía, sin venta -> alerta
        fila(3, NORMAL, "IP"),                                    # pasa
        fila(4, NORMAL, "SP"),                                    # pasa
        fila(5, NORMAL, "IT"),                                    # se queda por exclusión
        fila(6, NORMAL, "ST"),                                    # se queda por exclusión
        fila(7, [0.0] * 12),                                      # cero
        fila(8, [0.3] * 12),                                      # lineal
        fila(9, [np.nan] * 12),                                   # sin pronóstico
        fila(10, NORMAL, exhi=1, emp=24),                         # nivel bajo (empaque)
        fila(11, NORMAL, exhi=1, emp=24, sub=6),                  # nivel bajo (subempaque)
        fila(12, NORMAL, metodo="TDF"),                           # otro método: no se evalúa
        fila(13, NORMAL, "IT", cons=0),                           # exclusión bloquea aunque no haya venta
    ]
    df = pd.DataFrame(filas)
    res, r = procesar_m_a_tdf(df, Params(dias_transcurridos=11), ParamsTDF())
    d = res.set_index("ESTADISTICO")
    esperado = {1: "Pasar a TDF", 2: "Pasar a TDF", 3: "Pasar a TDF", 4: "Pasar a TDF", 5: "Dejar en M", 6: "Dejar en M",
                7: "Dejar en M", 8: "Dejar en M", 9: "Dejar en M", 10: "Dejar en M", 11: "Dejar en M", 13: "Dejar en M"}
    for est, dec in esperado.items():
        assert d.loc[est, "DECISION"] == dec, (est, d.loc[est, ["DECISION", "MOTIVO"]].tolist())
    assert 12 not in d.index and r["filas_otro_metodo"] == {"TDF": 1}
    assert d.loc[5, "MOTIVO"].startswith("Exclusión IT") and d.loc[6, "MOTIVO"].startswith("Exclusión ST")
    assert d.loc[7, "MOTIVO"] == "Pronóstico cero" and d.loc[8, "MOTIVO"].startswith("Pronóstico lineal")
    assert d.loc[9, "MOTIVO"] == "Sin pronóstico"
    assert "empaque" in d.loc[10, "MOTIVO"] and "subempaque" in d.loc[11, "MOTIVO"]
    assert d.loc[13, "ALERTA"] == ""                               # la alerta es solo para los que pasan
    assert d.loc[2, "ALERTA"] != "" and d.loc[1, "ALERTA"] == ""
    assert r["pasan"] == 4 and r["alertas_sin_venta"] == 1 and r["quedan"] == 8 and r["filas_m"] == 12
    c = hoja_carga(res)
    assert list(c["ESTADISTICO"]) == [1, 2, 3, 4] and set(c["MÉTODO NUEVO"]) == {"TDF"}
    # las exclusiones que bloquean se pueden cambiar
    res2, r2 = procesar_m_a_tdf(df, Params(dias_transcurridos=11), ParamsTDF(excl_bloquean=("ST",)))
    assert res2.set_index("ESTADISTICO").loc[5, "DECISION"] == "Pasar a TDF" and r2["pasan"] == 6
    # sin alerta si se desactiva
    res3, r3 = procesar_m_a_tdf(df, Params(dias_transcurridos=11), ParamsTDF(alerta_sin_venta=False))
    assert r3["alertas_sin_venta"] == 0
    # Excel
    import io
    import openpyxl
    buf = io.BytesIO()
    exportar_excel_tdf(res, r, buf, Params(dias_transcurridos=11))
    wb = openpyxl.load_workbook(buf)
    assert wb.sheetnames == ["Resumen", "PASAN A TDF", "CARGA TDF", "SE QUEDAN EN M"], wb.sheetnames
    assert wb["PASAN A TDF"].max_row == 5 and wb["SE QUEDAN EN M"].max_row == 9
    # sin filas en M o sin la columna Método: error claro
    for malo in (df.drop(columns=["Método"]), df.assign(**{"Método": "TDF"})):
        try:
            procesar_m_a_tdf(malo)
            raise AssertionError("debía fallar")
        except ValueError:
            pass
    print("OK: todas las pruebas pasaron")


if __name__ == "__main__":
    main()
