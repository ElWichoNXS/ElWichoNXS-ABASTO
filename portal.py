"""Menú para cambiar entre las apps de abastecimiento (cada una vive en su propio repositorio).

Para agregar una app nueva o cambiar una dirección, edita APPS en este archivo
(está repetido en cada repositorio: mantenlo igual en todos).
"""
import streamlit as st

APPS = [
    # (nombre, ícono Material de Streamlit, dirección en Streamlit Cloud)
    ("Verificación de traspasos", ":material/fact_check:", "https://verificaciondesolicitudesagotados-kkf5f8ke8v4c9ovjzrv6nk.streamlit.app/"),
    ("Min / Max por local", ":material/stacked_bar_chart:", "https://elwichonxs-abasto-kbt59qziqyexuqjhmhyan6.streamlit.app/"),
    ("Distribución de estadísticos", ":material/local_shipping:", ""),  # pendiente: pegar aquí la dirección cuando se publique
]


def menu_apps(actual: str) -> None:
    """Dibuja en la barra lateral el menú de apps. `actual` = nombre de la app que se está viendo."""
    with st.sidebar, st.container(key="menu_apps"):
        st.markdown("#### Mis apps")
        for i, (nombre, icono, url) in enumerate(APPS):
            if nombre == actual:
                # la clave "app_actual" es la que estilo.py resalta en rojo
                st.button(f"{icono} {nombre}", disabled=True, width="stretch", key="app_actual",
                          help="Estás en esta app")
            elif url:
                st.link_button(f"{icono} {nombre}", url, width="stretch")
            else:
                st.button(f"{icono} {nombre}", disabled=True, width="stretch", key=f"app_pendiente_{i}",
                          help="Dirección pendiente de configurar en portal.py")
        st.divider()
