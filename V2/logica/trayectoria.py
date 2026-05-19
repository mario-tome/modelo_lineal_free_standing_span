import math
import streamlit as st
from V2.modelos import METROS_POR_GRADO_LAT


def get_origen_latlon() -> tuple:
    """Latitud y longitud de origen según el modo de conexión activo."""
    modo = st.session_state.get("k_conexion_modo", "ninguno")
    if modo == "caja":
        return (
            st.session_state.get("k_caja_lat_e7", 404168000) / 1e7,
            st.session_state.get("k_caja_lon_e7", -37038000) / 1e7,
        )
    if modo == "gps":
        return (
            st.session_state.get("k_gps_lat_e7", 404168000) / 1e7,
            st.session_state.get("k_gps_lon_e7", -37038000) / 1e7,
        )
    return (40.4168, -3.7038)


def parse_trayectoria(texto: str, lat_origen: float, lon_origen: float) -> list:
    """Convierte texto "lat_e7 lon_e7" (una línea por punto) a lista de (x, y) en metros."""
    metros_por_grado_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(lat_origen))
    puntos = []
    for linea in texto.strip().splitlines():
        partes = linea.strip().split()
        if len(partes) < 2:
            continue
        try:
            lat = int(partes[0]) / 1e7
            lon = int(partes[1]) / 1e7
            y   = (lat - lat_origen) * METROS_POR_GRADO_LAT
            x   = (lon - lon_origen) * metros_por_grado_lon
            puntos.append((x, y))
        except (ValueError, ZeroDivisionError):
            continue
    return puntos


def calcular_errores(gps_x: float, gps_y: float,
                     puntos_trayectoria: list,
                     historial_posiciones: list,
                     en_marcha_atras: bool = False) -> tuple:
    """
    Calcula el error de distancia (mm) y de rumbo (grados) entre la posición GPS
    y el segmento de trayectoria más cercano.
    Devuelve (error_distancia_mm, error_rumbo_grados) o (None, None) si no hay suficientes datos.
    """
    if len(puntos_trayectoria) < 2:
        return None, None

    # Busca el segmento de trayectoria más cercano al GPS
    distancia_minima = float("inf")
    indice_segmento  = 0
    for i in range(len(puntos_trayectoria) - 1):
        x0, y0 = puntos_trayectoria[i]
        x1, y1 = puntos_trayectoria[i + 1]
        delta_x = x1 - x0
        delta_y = y1 - y0
        longitud_cuadrada = delta_x ** 2 + delta_y ** 2
        if longitud_cuadrada == 0:
            distancia = math.hypot(gps_x - x0, gps_y - y0)
        else:
            # Proyección del punto GPS sobre el segmento (0 = inicio, 1 = fin)
            proyeccion = max(0.0, min(1.0, ((gps_x - x0) * delta_x + (gps_y - y0) * delta_y) / longitud_cuadrada))
            distancia  = math.hypot(gps_x - (x0 + proyeccion * delta_x),
                                    gps_y - (y0 + proyeccion * delta_y))
        if distancia < distancia_minima:
            distancia_minima = distancia
            indice_segmento  = i

    error_distancia_mm = distancia_minima * 1000.0

    # Azimut objetivo del segmento más cercano
    x0, y0 = puntos_trayectoria[indice_segmento]
    x1, y1 = puntos_trayectoria[indice_segmento + 1]
    azimut_objetivo = math.degrees(math.atan2(x1 - x0, y1 - y0))
    if en_marcha_atras:
        azimut_objetivo += 180.0

    # Error de rumbo: diferencia entre el azimut actual del lineal y el objetivo
    error_rumbo = None
    if historial_posiciones and len(historial_posiciones) >= 2:
        xa, ya = historial_posiciones[-2]
        xb, yb = historial_posiciones[-1]
        if (xb - xa) ** 2 + (yb - ya) ** 2 > 1e-10:
            azimut_actual = math.degrees(math.atan2(xb - xa, yb - ya))
            error_azimut  = azimut_actual - azimut_objetivo
            error_rumbo   = (error_azimut + 180) % 360 - 180

    return error_distancia_mm, error_rumbo
