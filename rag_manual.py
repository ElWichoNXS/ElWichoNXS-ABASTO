"""Soluciona el RAG de abastecimiento con el método manual de Álvaro.

Uso:  python rag_manual.py RAG.xlsx Productos.xlsx salida.xlsx [dias_transcurridos]

Hojas 1-6 (se insertan columnas, todo con fórmulas de Excel):
  CONS DIA    = CONSUMO_ACUM_30D / dias_transcurridos   (13 el 14-oct; = fecha BI - 1 día)
  MINIMO      = EXHIBICION
  MAXIMO      = ROUND(MINIMO + EMPAQUE/2, 0)
  DG MAX = MAXIMO/CONS DIA | DIF = MAX-MIN | % Empaque = DIF/EMPAQUE
  SE CONFIGURA= "CORREGIR" si ROQ < EMPAQUE/2, si no "OK"
Hoja 7 (TDF con LTC, sin columnas nuevas): MINIMO/MAXIMO con las mismas reglas, pero solo
  en filas donde NO se puede cargar subempaque (no apto PTL, familia/funda no subempacable,
  o bodega sin STOCK_FISICO). Las que sí se pueden subempacar quedan en blanco (cargar
  subempaque sugerido). Se añade la hoja DINAMICA con conteo de casos por producto.
"""
import sys, pandas as pd, openpyxl
from openpyxl.styles import PatternFill, Font
from copy import copy

EXC = {'CERVEZAS', 'CERVEZAS SIN ALCOHOL', 'AGUAS'}
AMARILLO = PatternFill('solid', fgColor='FFFF00')

def main(rag, prod, out, dias=13):
    P = pd.read_excel(prod)
    apto = {int(c): str(a).strip().upper() == 'SI' for c, a in zip(
        pd.to_numeric(P['Estadístico'], errors='coerce'), P['Apto para PTL']) if pd.notna(c)}
    wb = openpyxl.load_workbook(rag)
    resumen = {}
    for ws in wb.worksheets:
        if not ws.title.startswith('TAREA_'):
            continue
        n = int(ws.title.split('_')[1])
        if n < 7:
            ws.insert_cols(16)       # CONS DIA
            ws.insert_cols(19, 4)    # DG MAX, DIF, % Empaque, SE CONFIGURA
            for c, t in zip((16, 19, 20, 21, 22), ('CONS DIA', 'DG MAX', 'DIF', '% Empaque', 'SE CONFIGURA')):
                ws.cell(3, c, t)
                src = ws.cell(3, 15); d = ws.cell(3, c)
                d.font, d.fill, d.border, d.alignment = copy(src.font), copy(src.fill), copy(src.border), copy(src.alignment)
            for r in range(4, ws.max_row + 1):
                if ws.cell(r, 6).value is None:
                    continue
                ws[f'P{r}'] = f'=+O{r}/{dias}'
                ws[f'Q{r}'] = f'=+AA{r}'
                ws[f'R{r}'] = f'=+ROUND(Q{r}+(L{r}/2),0)'
                ws[f'S{r}'] = f'=IFERROR(R{r}/P{r},0)'
                ws[f'T{r}'] = f'=+R{r}-Q{r}'
                ws[f'U{r}'] = f'=+T{r}/L{r}'
                ws[f'V{r}'] = f'=+IF(W{r}<(L{r}/2),"CORREGIR","OK")'
            resumen[n] = ws.max_row - 3
        else:
            h = {ws.cell(3, c).value: c for c in range(1, ws.max_column + 1)}
            L = lambda k: openpyxl.utils.get_column_letter(h[k])
            hecho = 0
            for r in range(4, ws.max_row + 1):
                cod = ws.cell(r, h['COD_PRODUCTO']).value
                if cod is None:
                    continue
                fam = str(ws.cell(r, h['FAMILIA']).value or '').upper() if 'FAMILIA' in h else ''
                desc = str(ws.cell(r, h['DESC_PRODUCTO']).value or '').upper()
                no_sub = fam in EXC or 'FUNDA' in fam or 'FUNDA' in desc
                puede = apto.get(int(cod), False) and not no_sub
                bod = ws.cell(r, h['STOCK_FISICO_BODEGA']).value or 0
                if puede and bod > 0:
                    continue         # candidato a cargar subempaque sugerido
                ws[f'{L("MINIMO")}{r}'] = f'=+{L("EXHIBICION")}{r}'
                ws[f'{L("MAXIMO")}{r}'] = f'=+ROUND({L("MINIMO")}{r}+({L("EMPAQUE")}{r}/2),0)'
                for k in ('MINIMO', 'MAXIMO'):
                    ws[f'{L(k)}{r}'].fill = AMARILLO
                hecho += 1
            resumen[n] = (hecho, ws.max_row - 3)
    # hoja dinámica: casos por producto en TAREA_7
    ws7 = wb['TAREA_7']
    h = {ws7.cell(3, c).value: c for c in range(1, ws7.max_column + 1)}
    cnt = {}
    for r in range(4, ws7.max_row + 1):
        cod = ws7.cell(r, h['COD_PRODUCTO']).value
        if cod is not None:
            cnt[cod] = cnt.get(cod, 0) + 1
    dn = wb.create_sheet('DINAMICA DE LA HOJA 7')
    dn.append(['COD_PRODUCTO', 'Cantidad de casos'])
    for k, v in sorted(cnt.items(), key=lambda x: -x[1]):
        dn.append([k, v])
    dn.append(['Total', sum(cnt.values())])
    for c in dn[1]:
        c.font = Font(bold=True)
    wb.save(out)
    print(resumen)

if __name__ == '__main__':
    a = sys.argv
    main(a[1], a[2], a[3], int(a[4]) if len(a) > 4 else 13)
