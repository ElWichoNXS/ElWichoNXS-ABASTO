"""Menú para cambiar entre las apps de abastecimiento (cada una vive en su propio repositorio).

Para agregar una app nueva o cambiar una dirección, edita APPS en este archivo
(está repetido en cada repositorio: mantenlo igual en todos).
"""
import streamlit as st

APPS = [
    # (nombre, ícono, dirección en Streamlit Cloud)
    ("Verificación de traspasos", "📦", "https://verificaciondesolicitudesagotados-kkf5f8ke8v4c9ovjzrv6nk.streamlit.app/"),
    ("Min / Max por local", "📊", "https://elwichonxs-abasto-kbt59qziqyexuqjhmhyan6.streamlit.app/"),
]


def menu_apps(actual: str) -> None:
    """Dibuja en la barra lateral el menú de apps. `actual` = nombre de la app que se está viendo."""
    with st.sidebar:
        st.markdown("#### 🧭 Mis apps")
        for nombre, icono, url in APPS:
            if nombre == actual:
                st.button(f"{icono} {nombre}", disabled=True, width="stretch", key=f"_app_{nombre}",
                          help="Estás en esta app")
            elif url:
                st.link_button(f"{icono} {nombre}", url, width="stretch")
            else:
                st.button(f"{icono} {nombre}", disabled=True, width="stretch", key=f"_app_{nombre}",
                          help="Dirección pendiente de configurar en portal.py")
        st.divider()
