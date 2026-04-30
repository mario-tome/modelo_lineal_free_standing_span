import streamlit as st
from logica.constantes import get_defaults

# Claves que pertenecen al estado de simulación (compartidas entre sesiones)
SIM_KEYS = frozenset({
    "lineal", "longitud_campo", "running", "finished", "paused",
    "log", "historial", "gps_track", "tower_trails", "gps_prev",
    "vel_real", "pos_prev", "tramos_ok_prev", "ar_pasadas",
    "caja_slow_prev", "trayectoria_ead_mm", "trayectoria_erumbo_deg",
})


class SimState(dict):
    """Dict con acceso por atributo: sim.lineal, sim.running…"""
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


@st.cache_resource
def get_sim() -> SimState:
    """Singleton compartido entre todas las sesiones del mismo proceso Streamlit."""
    defaults = get_defaults()
    return SimState({k: v for k, v in defaults.items() if k in SIM_KEYS})
