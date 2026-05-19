import math
import streamlit as st
from V2.modelos import METROS_POR_GRADO_LAT


def get_origen_latlon() -> tuple:
    """Latitud y longitud de origen según el modo de conexión activo"""
    modo = st.session_state.get("k_conexion_modo", "ninguno")
    if modo == "caja":
        return (st.session_state.get("k_caja_lat_e7", 404168000) / 1e7, st.session_state.get("k_caja_lon_e7", -37038000) / 1e7)
    if modo == "gps":
        return (st.session_state.get("k_gps_lat_e7", 404168000) / 1e7, st.session_state.get("k_gps_lon_e7", -37038000) / 1e7)
    return (40.4168, -3.7038)


def parse_trayectoria(texto: str, lat_origen: float, lon_origen: float) -> list:
    """Convierte texto "lat_e7 lon_e7" (una línea por punto) a lista de (x, y) en metros"""
    mpg_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(lat_origen))
    puntos = []
    for linea in texto.strip().splitlines():
        partes = linea.strip().split()
        if len(partes) < 2:
            continue
        try:
            lat = int(partes[0]) / 1e7
            lon = int(partes[1]) / 1e7
            y = (lat - lat_origen) * METROS_POR_GRADO_LAT
            x = (lon - lon_origen) * mpg_lon
            puntos.append((x, y))
        except (ValueError, ZeroDivisionError):
            continue
    return puntos


def calcular_errores(gps_x: float, gps_y: float,
                     puntos_trayectoria: list,
                     historial_posiciones: list,
                     en_marcha_atras: bool = False) -> tuple:
    """Calcula error de distancia (mm) y rumbo (grados) respecto a la trayectoria"""
    if len(puntos_trayectoria) < 2:
        return None, None

    dist_min = float("inf")
    indice_seg = 0
    for i in range(len(puntos_trayectoria) - 1):
        x0, y0 = puntos_trayectoria[i]
        x1, y1 = puntos_trayectoria[i + 1]
        ddx, ddy = x1 - x0, y1 - y0
        L2 = ddx * ddx + ddy * ddy
        if L2 == 0:
            d = math.hypot(gps_x - x0, gps_y - y0)
        else:
            t = max(0.0, min(1.0, ((gps_x - x0) * ddx + (gps_y - y0) * ddy) / L2))
            d = math.hypot(gps_x - (x0 + t * ddx), gps_y - (y0 + t * ddy))
        if d < dist_min:
            dist_min   = d
            indice_seg = i

    error_dist_mm = dist_min * 1000.0

    x0, y0 = puntos_trayectoria[indice_seg]
    x1, y1 = puntos_trayectoria[indice_seg + 1]
    azimut_obj = math.degrees(math.atan2(x1 - x0, y1 - y0))
    if en_marcha_atras:
        azimut_obj += 180.0

    error_rumbo = None
    if historial_posiciones and len(historial_posiciones) >= 2:
        xa, ya = historial_posiciones[-2]
        xb, yb = historial_posiciones[-1]
        if (xb - xa) ** 2 + (yb - ya) ** 2 > 1e-10:
            azimut_actual = math.degrees(math.atan2(xb - xa, yb - ya))
            dif = azimut_actual - azimut_obj
            while dif >  180: dif -= 360
            while dif < -180: dif += 360
            error_rumbo = dif

    return error_dist_mm, error_rumbo
