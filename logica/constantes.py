# Desviación lateral máxima (en metros por metro avanzado) que introduce cada tipo de terreno.
# Un valor de 0.012 significa que la torre puede desviarse hasta ±1,2 cm por cada metro que avanza.
TERRENOS = {
    "Perfecto (sin ruido)":   0.000,
    "Poco":                  0.006,
    "Normal":                 0.012,
    "Irregular":              0.030,
    "Lineal loco":            0.070,
}


def get_defaults() -> dict:
    return {
        "lineal":          None,
        "longitud_campo":  800,
        "running":         False,
        "finished":        False,
        "paused":          False,
        "log":             [],
        "historial":       [],
        "gps_track":       [],
        "gps_prev":        None,
        "vel_real":        0.0,
        "pos_prev":        0.0,
        "tramos_ok_prev":  None,
        "k_vista_general": False,
        "tower_trails":    None,
        "marcha_atras_kbd": False,
        "ar_pasadas":       0,
        "caja_slow_prev":   {"cart": False, "end": False, "safety": True},
        "trayectoria_ead_mm":     None,
        "trayectoria_erumbo_deg": None,
        "trayectoria_activa":     False,
        "trayectoria_puntos_xy":  None,
        "sim_auto_reverse": False,
        "sim_ar_ymin":      0.0,
        "sim_ar_ymax":      800.0,
    }
