import streamlit as st
from .constantes import get_defaults

# Conjunto de claves que pertenecen al estado de la simulación (no a la UI de Streamlit).
# Usado para inicializar y resetear el SimState correctamente.
CLAVES_SIMULACION = frozenset(get_defaults().keys())


class SimState(dict):
    """Diccionario con acceso por atributo: sim.en_marcha, sim.lineal…"""
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


@st.cache_resource
def get_sim() -> SimState:
    """Estado global compartido entre todas las sesiones del mismo proceso Streamlit."""
    return SimState(get_defaults())
