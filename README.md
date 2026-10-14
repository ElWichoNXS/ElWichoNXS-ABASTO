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
- **Pronóstico lineal:** el modelo aún no aprendió y repite valores. De los **12 días** de pronóstico hay menos de 6 valores únicos (`UNICOS ≤ 5`; único = valor que aparece una sola vez). **Excepción:** si el modelo solo copió la semana (días 8 a 12 iguales a los días 1 a 5, columna `SEMANA COPIADA`), se juzga solo la primera semana: es lineal si tiene un valor repetido y los valores únicos no superan a los repetidos (con empate también es lineal). Ejemplos de primera semana: `5,5,5,5,5,5,5` y `3,3,4,4,5,5,6` → lineales; `2,2,3,4,5,6,6` (3 únicos, 2 repetidos) y 7 valores distintos → no lineales.
- **Nivel TDF bajo:** TDF envía `Proyectado + Cubrimiento + Exhibición (+ Destacado)` (Proyectado = pronóstico del día 0; Cubrimiento = suma del pronóstico de los (FREC + Dias SS) días siguientes; más allá de los 12 días del BI se usa el promedio). Si ese nivel es menor al **50 % del EMPAQUE** (sin subempaque) o al **100 % del SUBEMPAQUE** (con subempaque), el producto pasa a Min/Max; si lo alcanza, se queda en TDF. Es la única vía para un pronóstico normal.

La columna `MOTIVO MIN/MAX` indica por qué pasó cada fila.

## Cómo se calcula el Min y el Max
- **Min:** `Cobertura = CONSUMO DIA × (FREC + días de seguridad) + Exhi` (días de seguridad = 0 por defecto). A) `CONSUMO DIA > Exhi` y B) con consumo → `Min = ROUND(Cobertura)`; C) sin consumo → `Min = Exhi`. **D) Sobrestock:** si el Min es mayor que la Exhi y `DG MIN` (Min ÷ consumo diario) supera 20 días (configurable), el Min baja a `Exhi + SUBEMPAQUE` (con subempaque) o `Exhi + ROUND(EMPAQUE ÷ 2)` (sin subempaque); nunca sube el Min.
- **Consumo del mes anterior (opcional):** tercer archivo con local, estadístico y consumo del mes anterior. Con la casilla «Usar el consumo del mes anterior» marcada, la base del consumo diario es ese consumo ÷ 30 días (donde haya dato); desmarcada, se usa el consumo del BI; `FUENTE CONSUMO` indica cuál se usó.
- **Max:** con SUBEMPAQUE > 0 → `Min + SUBEMPAQUE`; sin subempaque → `Min + ROUND(EMPAQUE ÷ 2)`. Opcionalmente, cobertura de N días. Siempre se respeta el SUBEMPAQUE real del BI.
- Los Dias SS del BI solo se usan para decidir el cambio de método; el Min usa sus propios días de seguridad.

## Excel que se descarga
- **Pronóstico cero:** los productos que pasan a Min/Max, con las columnas Min y Max resaltadas. La columna `EN REVISAR` (`Sí` = prioridad ALTA/MEDIA, `Informativo`, `No`) permite filtrar los casos de la hoja REVISAR; `Exhi` queda junto a `DIF`.
- **REVISAR:** solo casos extremos: inventario negativo (ALTA), consumo ≥ 3 veces la exhibición (ALTA), sobre stock crítico con Max que cubre más de N días (MEDIA), **pronóstico que subestima el consumo real** (consumo ≥ 3 × el promedio pronosticado y ≥ 2 u/día; MEDIA; acción: revisar el pronóstico con planificación de demanda) y sobre stock por cubrir la exhibición (**Informativo**: la exhibición la define el área comercial y siempre se abastece, solo se mapea). Cada caso trae **ACCIÓN PRINCIPAL** y **SUGERENCIA A REALIZAR** (corregir dato, notificar al área comercial, subempacar si es viable, o dejar mapeado), la **VIABILIDAD SUBEMPAQUE** y una **ALERTA PVP** cuando el subempaque recomendado es de un producto con PVP menor al mínimo.
- **SUGERIR SUBEMPAQUE:** propuestas de cambio de maestro para evitar sobrestock. Un producto se sugiere solo si: es apto (`Apto para PTL = Si`), no es de las familias excluidas (CERVEZAS, CERVEZAS SIN ALCOHOL, AGUAS) ni un estadístico excluido, tiene EMPAQUE ≥ 7, el mismo SKU ya está subempacado en al menos N locales, tiene **PVP ≥ el mínimo** (filtro obligatorio, configurable) y enviar el empaque completo genera sobrestock (el local tarda más de N días en venderlo, o no tuvo consumo) o el PVP es alto.
- **Resumen:** tarjetas e indicadores del cambio de método, clasificación por motivo, reglas del Min y el Max, unidades, casos de REVISAR y sus acciones, subempaque, dónde se concentran los cambios, diagnóstico, parámetros usados y reglas aplicadas.

## Parámetros
Cada parámetro de la barra lateral tiene un signo ❓ con su explicación, y al final de la página hay una sección con las reglas (se actualiza con los valores configurados). Modo claro/oscuro: menú ⋮ → Settings → Theme.

## Solución del RAG de abastecimiento (`rag_manual.py`)

Replica el método manual del analista sobre el archivo `RAG_ABASTECIMIENTO_SECOS`:
`python rag_manual.py RAG.xlsx Productos.xlsx salida.xlsx [días_transcurridos]`

- Hojas 1–6: `CONS DIA = CONSUMO_ACUM_30D ÷ días transcurridos` (fecha BI − 1), `MINIMO = EXHIBICION`,
  `MAXIMO = ROUND(MINIMO + EMPAQUE/2)`, más `DG MAX`, `DIF`, `% Empaque` y `SE CONFIGURA`
  (`CORREGIR` si ROQ < EMPAQUE/2). Todo con fórmulas de Excel.
- Hoja 7 (TDF con LTC): Min/Max con la misma regla solo donde no se puede cargar subempaque
  (no apto PTL, cerveza/agua/funda, o bodega sin STOCK_FISICO). Criterio pendiente de confirmar.
- Se agrega la hoja de conteo de casos por producto de la hoja 7.
