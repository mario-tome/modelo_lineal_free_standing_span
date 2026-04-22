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


def calcular_errores(gps_x: float, gps_y: float, puntos_trayectoria: list, trail: list) -> tuple:
    if len(puntos_trayectoria) < 2:
        return None, None

    distancia_minima = float("inf")
    indice_segmento = 0
    for i in range(len(puntos_trayectoria) - 1):
        ax, ay = puntos_trayectoria[i]
        bx, by = puntos_trayectoria[i + 1]
        dx, dy = bx - ax, by - ay
        longitud_segmento_cuadrado = dx * dx + dy * dy
        if longitud_segmento_cuadrado == 0:
            distancia = math.hypot(gps_x - ax, gps_y - ay)
        else:
            t = max(0.0, min(1.0, ((gps_x - ax) * dx + (gps_y - ay) * dy) / longitud_segmento_cuadrado))
            distancia = math.hypot(gps_x - (ax + t * dx), gps_y - (ay + t * dy))
        if distancia < distancia_minima:
            distancia_minima = distancia
            indice_segmento = i

    error_distancia_mm = distancia_minima * 1000.0

    ax, ay = puntos_trayectoria[indice_segmento]
    bx, by = puntos_trayectoria[indice_segmento + 1]
    azimut_objetivo = math.degrees(math.atan2(bx - ax, by - ay))

    error_rumbo = None
    if trail and len(trail) >= 2:
        px, py = trail[-2]
        cx, cy = trail[-1]
        ddx, ddy = cx - px, cy - py
        if ddx * ddx + ddy * ddy > 1e-10:
            azimut_actual = math.degrees(math.atan2(ddx, ddy))
            diferencia = azimut_actual - azimut_objetivo
            while diferencia >  180: diferencia -= 360
            while diferencia < -180: diferencia += 360
            error_rumbo = diferencia

    return error_distancia_mm, error_rumbo
