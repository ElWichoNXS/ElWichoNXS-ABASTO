# Min / Max por local · Pronóstico cero

Archivos: `motor_minmax.py` (lógica), `app.py` (interfaz Streamlit), `requirements.txt`.

    pip install -r requirements.txt
    streamlit run app.py

Cargar: (1) Excel crudo del BI, (2) maestro de productos con 'Estadístico' y 'Apto para PTL' (opcional).
Cada fila Local x Estadístico se calcula con su propia Exhi, FREC y SUBEMPAQUE.
El Max usa el SUBEMPAQUE real del BI. La hoja SUGERIR SUBEMPAQUE propone subempacar productos
cuyo mismo SKU ya está subempacado en otros locales (cambio de maestro, no se aplica al Max).
