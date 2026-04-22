import math
import streamlit as st
from modelo import METROS_POR_GRADO_LAT


def get_origen_latlon() -> tuple:
    modo = st.session_state.get("k_conexion_modo", "ninguno")
    if modo == "caja":
        return (st.session_state.get("k_caja_lat_e7", 404168000) / 1e7,
                st.session_state.get("k_caja_lon_e7", -37038000) / 1e7)
    if modo == "gps":
        return (st.session_state.get("k_gps_lat_e7",  404168000) / 1e7,
                st.session_state.get("k_gps_lon_e7",  -37038000) / 1e7)
    return (40.4168, -3.7038)


def parse_trayectoria(texto: str, lat_origen: float, lon_origen: float) -> list:
    metros_por_grado_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(lat_origen))
    puntos = []
    for linea in texto.strip().splitlines():
        partes = linea.strip().split()
        if len(partes) < 2:
            continue
        try:
            lat = int(partes[0]) / 1e7
            lon = int(partes[1]) / 1e7
            y = (lat - lat_origen) * METROS_POR_GRADO_LAT
            x = (lon - lon_origen) * metros_por_grado_lon
            puntos.append((x, y))
        except (ValueError, ZeroDivisionError):
            continue
    return puntos


def calcular_errores(gps_x: float, gps_y: float, puntos_trayectoria: list, historial_posiciones: list) -> tuple:
    if len(puntos_trayectoria) < 2:
        return None, None

    distancia_minima = float("inf")
    indice_segmento  = 0
    for i in range(len(puntos_trayectoria) - 1):
        x_inicio, y_inicio = puntos_trayectoria[i]
        x_fin,    y_fin    = puntos_trayectoria[i + 1]
        delta_x, delta_y   = x_fin - x_inicio, y_fin - y_inicio
        longitud_segmento_cuadrado = delta_x * delta_x + delta_y * delta_y
        if longitud_segmento_cuadrado == 0:
            distancia = math.hypot(gps_x - x_inicio, gps_y - y_inicio)
        else:
            proyeccion = max(0.0, min(1.0,
                ((gps_x - x_inicio) * delta_x + (gps_y - y_inicio) * delta_y) / longitud_segmento_cuadrado))
            distancia = math.hypot(
                gps_x - (x_inicio + proyeccion * delta_x),
                gps_y - (y_inicio + proyeccion * delta_y),
            )
        if distancia < distancia_minima:
            distancia_minima = distancia
            indice_segmento  = i

    error_distancia_mm = distancia_minima * 1000.0

    x_inicio, y_inicio = puntos_trayectoria[indice_segmento]
    x_fin,    y_fin    = puntos_trayectoria[indice_segmento + 1]
    azimut_objetivo    = math.degrees(math.atan2(x_fin - x_inicio, y_fin - y_inicio))

    error_rumbo = None
    if historial_posiciones and len(historial_posiciones) >= 2:
        x_anterior, y_anterior = historial_posiciones[-2]
        x_actual,   y_actual   = historial_posiciones[-1]
        delta_x_movimiento     = x_actual - x_anterior
        delta_y_movimiento     = y_actual - y_anterior
        if delta_x_movimiento ** 2 + delta_y_movimiento ** 2 > 1e-10:
            azimut_actual = math.degrees(math.atan2(delta_x_movimiento, delta_y_movimiento))
            diferencia    = azimut_actual - azimut_objetivo
            while diferencia >  180: diferencia -= 360
            while diferencia < -180: diferencia += 360
            error_rumbo = diferencia

    return error_distancia_mm, error_rumbo
