# Min / Max por local · Pronóstico cero

Automatiza la decisión de qué productos del BI (todos descargados en método **TDF**, abastecimiento por forecast)
conviene pasar a método **Min/Max**, y calcula su **Min** y **Max** (siempre enteros).

Archivos: `motor_minmax.py` (lógica), `app.py` (interfaz Streamlit), `requirements.txt`, `.streamlit/config.toml` (tema rojo/blanco, modo claro y oscuro).

    pip install -r requirements.txt
    streamlit run app.py

## Qué se carga
1. **Excel del BI** (obligatorio).
2. **Maestro de productos** (opcional) con las columnas `Estadístico` y `Apto para PTL`. "Si" = apto para subempaque; sin maestro se asume "Si" para todos.

Cámbialo cada vez que descargues el BI: **Días de consumo transcurridos** (el BI da el consumo acumulado del mes; `CONSUMO DIA = CONSUMOS ACU ÷ días transcurridos`).

## Qué pasa de TDF a Min/Max (cada fila Local × Estadístico)
Pasa si cumple **una** de estas vías:
- **Pronóstico cero** (suma de los días de pronóstico = 0).
- **Pronóstico lineal:** en la **primera semana** (días 1 a 7) al menos 7 días repiten valor (parámetro). Se vende todos los días, así que un pronóstico normal varía día a día. Que desde el día 8 el modelo copie la semana **no** cuenta como lineal.
- **Reglas 3 y 4 juntas:** promedio diario del pronóstico < 55 % de la Exhibición **y** promedio × (FREC + Dias SS) < 50 % del empaque final (`Empq_final`). Si cumple la 3 pero el forecast cubre la mitad del empaque, se queda en TDF.

La columna `MOTIVO MIN/MAX` indica por qué pasó cada fila.

## Cómo se calcula el Min y el Max
- **Min:** A) si `CONSUMO DIA > Exhi` → `ROUND(CONSUMO DIA × FREC)`; B) si es apto, la Exhi cubre menos de 2 días y `CONSUMO DIA × FREC > Exhi` → `ROUND(CONSUMO DIA × FREC)`; C) en cualquier otro caso `Min = Exhi`.
- **Max:** con SUBEMPAQUE > 0 → `Min + SUBEMPAQUE`; sin subempaque → `Min + ROUND(EMPAQUE ÷ 2)`. Opcionalmente, cobertura de N días. Siempre se respeta el SUBEMPAQUE real del BI.
- Los Dias SS solo se usan para decidir el cambio de método, no para el Min ni el Max.

## Excel que se descarga
- **Pronóstico cero:** los productos que pasan a Min/Max, con las columnas Min y Max resaltadas. La columna `EN REVISAR` (`Sí` = prioridad ALTA/MEDIA, `Informativo`, `No`) permite filtrar los casos de la hoja REVISAR; `Exhi` queda junto a `DIF`.
- **REVISAR:** solo casos extremos: inventario negativo (ALTA), consumo ≥ 3 veces la exhibición (ALTA), sobre stock crítico con Max que cubre más de N días (MEDIA) y sobre stock por cubrir la exhibición (**Informativo**: la exhibición la define el área comercial y siempre se abastece, solo se mapea). Cada caso trae **ACCIÓN PRINCIPAL** y **SUGERENCIA A REALIZAR** (corregir dato, notificar al área comercial, subempacar si es viable, o dejar mapeado), la **VIABILIDAD SUBEMPAQUE** y una **ALERTA PVP** cuando el subempaque recomendado es de un producto con PVP menor al mínimo.
- **SUGERIR SUBEMPAQUE:** propuestas de cambio de maestro para evitar sobrestock. Un producto se sugiere solo si: es apto (`Apto para PTL = Si`), no es de las familias excluidas (CERVEZAS, CERVEZAS SIN ALCOHOL, AGUAS) ni un estadístico excluido, tiene EMPAQUE ≥ 7, el mismo SKU ya está subempacado en al menos N locales, tiene **PVP ≥ el mínimo** (filtro obligatorio, configurable) y enviar el empaque completo genera sobrestock (el local tarda más de N días en venderlo, o no tuvo consumo) o el PVP es alto.
- **Resumen:** tarjetas e indicadores del cambio de método, clasificación por motivo, reglas del Min y el Max, unidades, casos de REVISAR y sus acciones, subempaque, dónde se concentran los cambios, diagnóstico, parámetros usados y reglas aplicadas.

## Parámetros
Cada parámetro de la barra lateral tiene un signo ❓ con su explicación, y al final de la página hay una sección con las reglas (se actualiza con los valores configurados). Modo claro/oscuro: menú ⋮ → Settings → Theme.
