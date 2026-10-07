# Min / Max por local · Pronóstico cero

Archivos: `motor_minmax.py` (lógica), `app.py` (interfaz Streamlit), `requirements.txt`.

    pip install -r requirements.txt
    streamlit run app.py

Cargar: (1) Excel crudo del BI, (2) maestro de productos con 'Estadístico' y 'Apto para PTL' (opcional).
Cada fila Local x Estadístico se calcula con su propia Exhi, FREC y SUBEMPAQUE.
El Max usa el SUBEMPAQUE real del BI. La hoja SUGERIR SUBEMPAQUE propone subempacar productos
cuyo mismo SKU ya está subempacado en otros locales (cambio de maestro, no se aplica al Max).

## Parámetro clave: Días de consumo transcurridos
El BI entrega el consumo ACUMULADO del mes (CONSUMOS ACU). El programa lo divide para los días del mes
transcurridos para obtener el CONSUMO DIA. **Cámbialo cada vez que descargues el BI** (por defecto 5).

Cada parámetro de la barra lateral tiene un signo ❓ con su explicación, y al final de la página hay una
sección con las reglas de cálculo del Min y del Max (que se actualiza con los valores configurados).
