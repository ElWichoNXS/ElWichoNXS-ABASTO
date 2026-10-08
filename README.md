# Min / Max por local · Pronóstico cero

Archivos: `motor_minmax.py` (lógica), `app.py` (interfaz Streamlit), `requirements.txt`.

    pip install -r requirements.txt
    streamlit run app.py

Cargar: (1) Excel crudo del BI, (2) maestro de productos con 'Estadístico' y 'Apto para PTL' (opcional).
Toda la data del BI está en método TDF (forecast). El programa decide qué productos pasan a Min/Max
(pronóstico promedio diario x FREC < 50 % de Empq_final) y calcula su Min y Max.
Cada fila Local x Estadístico se calcula con su propia Exhi, FREC y SUBEMPAQUE.
El Max usa el SUBEMPAQUE real del BI. La hoja SUGERIR SUBEMPAQUE propone subempacar productos con PVP alto, bajo consumo o Exhi/EMPAQUE < 50 %
cuyo mismo SKU ya está subempacado en otros locales; nunca CERVEZAS, CERVEZAS SIN ALCOHOL ni AGUAS, y se puede
excluir un ESTADISTICO específico (cambio de maestro, no se aplica al Max).

## Parámetro clave: Días de consumo transcurridos
El BI entrega el consumo ACUMULADO del mes (CONSUMOS ACU). El programa lo divide para los días del mes
transcurridos para obtener el CONSUMO DIA. **Cámbialo cada vez que descargues el BI** (por defecto 5).

Cada parámetro de la barra lateral tiene un signo ❓ con su explicación, y al final de la página hay una
sección con las reglas de cálculo del Min y del Max (que se actualiza con los valores configurados).

## Apto para subempaque
Sale de la columna **Apto para PTL** del maestro de productos (archivo 2): "Si" = apto, "No" = nunca se sugiere subempacar. Sin maestro se asume "Si".
