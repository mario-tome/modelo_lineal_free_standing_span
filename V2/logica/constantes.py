TERRENOS = {
    "Perfecto (sin ruido)": 0.000,
    "Poco":                 0.006,
    "Normal":               0.012,
    "Irregular":            0.030,
    "Lineal loco":          0.070,
}


def get_defaults() -> dict:
    """Valores de arranque de la simulación. Todos los nombres en español descriptivo."""
    return {
        # Modelo
        "lineal":                  None,
        "longitud_campo":          800,

        # Estado de ejecución
        "en_marcha":               False,
        "completado":              False,
        "pausado":                 False,
        "motivo_pausa":            None,

        # Registro de eventos
        "registro":                [],

        # Históricos de posición y GPS
        "historial_posiciones":    [],
        "historial_gps":           [],
        "rastros_secciones":       None,
        "coordenadas_gps_previas": None,

        # Métricas en tiempo real
        "velocidad_real":          0.0,
        "posicion_norte_previa":   0.0,
        "alineacion_previa":       None,

        # Auto-reverse
        "numero_inversiones":      0,
        "auto_reverse_activo":     False,
        "limite_sur":              0.0,
        "limite_norte":            800.0,

        # Caja de interfaz Arduino
        "estado_previo_caja":      {"cart": False, "end": False, "safety": True, "gps": True},

        # Trayectoria GPS objetivo
        "trayectoria_activa":      False,
        "trayectoria_puntos":      None,
        "error_distancia_mm":      None,
        "error_rumbo_grados":      None,

        # Exportación CSV
        "csv_ruta":                None,
        "csv_filas_escritas":      0,
    }
