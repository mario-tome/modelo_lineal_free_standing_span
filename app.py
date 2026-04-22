import streamlit as st
from constantes import get_defaults
from estilos import CSS
from teclado import manejar_teclado
from sidebar import renderizar_sidebar
from panel import panel_principal

st.set_page_config(
    page_title="Gemelo Digital Lineal",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(CSS, unsafe_allow_html=True)

for clave, valor in get_defaults().items():
    if clave not in st.session_state:
        st.session_state[clave] = valor

manejar_teclado()
renderizar_sidebar()
panel_principal()
