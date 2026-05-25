classDiagram
direction TB

    %% ─────────────────────────────────────────────────────────────────────
    %% módulo: modelos/componentes.py
    %% ─────────────────────────────────────────────────────────────────────

    class METROS_POR_GRADO_LAT {
        <<constante módulo>>
        +valor: float = 111320.0
    }

    class avanzar_en_circunferencia {
        <<function>>
        +avanzar_en_circunferencia(centro_x, centro_y, radio, inicio_x, inicio_y, distancia) tuple
    }

    class _metros_recorridos {
        <<function privada>>
        +_metros_recorridos(velocidad_nominal: float, factor_velocidad: float, segundos: float, porcentaje_patinaje: float) float
    }

    class _aplicar_interferencia_gps {
        <<function privada>>
        +_aplicar_interferencia_gps(lat_e7: int, lon_e7: int, interferencia_mm: float, lat_origen: float) tuple
    }

    class _aplicar_interferencia_cartesiana {
        <<function privada>>
        +_aplicar_interferencia_cartesiana(x: float, y: float, interferencia_mm: float) tuple
    }

    class TramoFinal {
        +posicion_x: float
        +posicion_y: float
        +longitud_tramo: float
        +velocidad_nominal: float
        +velocidad_porcentaje: float
        +ruido_lateral: float
        +porcentaje_patinaje: float
        +motor_activo: bool
        +__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal: float = 3.0, velocidad_porcentaje: float = 50.0, ruido_lateral: float = 0.0)
        +actualizar_motor(segundo_en_ciclo: int, duracion_ciclo: int = 60)
        +avanzar(segundos: float, direccion: int = 1, rumbo: float = 0.0) float
    }

    class TramoIntermedio {
	    «class» FACTOR_VELOCIDAD_NORMAL: float = 1.5
	    «class» UMBRAL_ARRANQUE: float = 0.10
	    «class» UMBRAL_ADELANTO: float = 0.10
        +posicion_x: float
        +posicion_y: float
        +longitud_tramo: float
        +velocidad_nominal: float
        +factor_velocidad: float
        +porcentaje_patinaje: float
        +motor_activo: bool
        +__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal: float = 3.0, factor_velocidad: float = FACTOR_VELOCIDAD_NORMAL)
        +seguir(objetivo_x: float, objetivo_y: float, segundos: float, direccion: int = 1, pivote_x: float = None, pivote_y: float = None, rumbo: float = 0.0) float
        -_avanzar_en_arco(pivote_x: float, pivote_y: float, metros: float, direccion: int, rumbo: float)
    }

    class FreeStandingSpan {
	    «class» FACTOR_MOTOR_IZQUIERDO: float = 1.5
	    «class» FACTOR_MOTOR_RAPIDO: float = 2.0
	    «class» TOLERANCIA_ALINEACION: float = 0.05
        +tramo_izq: TramoIntermedio
        +tramo_der: TramoIntermedio
        +longitud: float
        -_angulo_referencia_grados: float
        +angulo_referencia_grados: float «prop»
        +esta_alineado: bool «prop»
        +__init__(tramo_izq: TramoIntermedio, tramo_der: TramoIntermedio, longitud: float)
        +actualizar(cart_x: float, cart_y: float, end_x: float, end_y: float) float
    }

    class AntenaGPS {
        +seccion_inicio
        +seccion_fin
        +metros_desde_inicio: float
        +lat_origen: float
        +lon_origen: float
        +interferencia_gps_mm: float
        +posicion_x: float «prop»
        +posicion_y: float «prop»
        +latitud: float «prop»
        +longitud: float «prop»
        +lat_e7: int «prop»
        +lon_e7: int «prop»
        +__init__(seccion_inicio, seccion_fin, metros_desde_inicio: float, lat_origen: float, lon_origen: float)
        -_fraccion_en_tramo() float
    }

    class CajaInterfaz {
	    «class» BAUDRATE: int = 115200
        +antena_path: AntenaGPS
        +antena_heading: AntenaGPS
        +puerto_path: str
        +puerto_heading: str
        +carr: int
        +modo_coordenadas: str
        +slow_down_cart: bool
        +slow_down_end_tower: bool
        +safety_ok: bool
        +gps_ok: bool
        +ultimo_mensaje: str
        +interferencia_gps_mm: float
        -_activo: bool
        -_hilo
        +__init__(antena_path: AntenaGPS, antena_heading: AntenaGPS, puerto_path: str, puerto_heading: str, carr: int = 2, modo_coordenadas: str = "geo")
        +iniciar()
        +detener()
        -_bucle()
        -_formatear_mensajes() tuple
        -_procesar(msg: str)
    }

    class Centro {
        <<uso futuro>>
        +posicion_x: float
        +posicion_y: float
        +__init__(posicion_x: float = 0.0, posicion_y: float = 0.0)
    }

    class TramoCorner {
        <<uso futuro>>
        +posicion_x: float
        +posicion_y: float
        +longitud_tramo: float
        +angulo_giro: float
        +__init__(posicion_x: float, posicion_y: float, longitud_tramo: float, angulo_giro: float = 0.0)
    }

    %% ─────────────────────────────────────────────────────────────────────
    %% módulo: modelos/lineal.py
    %% ─────────────────────────────────────────────────────────────────────

    class Lineal {
	    «class» DURACION_CICLO: int = 60
        +numero_tramos: int
        +longitud_tramo: float
        +velocidad_porcentaje: float
        +velocidad_nominal: float
        +indice_fss_izq: int
        +indice_fss_der: int
        +secciones: list
        +fss: FreeStandingSpan
        +tramo_cart: TramoFinal
        +tramo_end: TramoFinal
        +torre_rapida: TramoIntermedio
        +tiempo_total_segundos: int
        +ciclo_actual: int
        +motor_rapido_pct_on: float
        +direccion: int
        +slow_down_cart: bool
        +slow_down_end_tower: bool
        +caja_interfaz: CajaInterfaz | None
        -_segundo_en_ciclo: int
        -_en_marcha: bool
        -_segundos_motor_rapido_on: int
        -_angulo_referencia_grados: float
        +posicion_norte: float «prop»
        +longitud_total: float «prop»
        +esta_alineado: bool «prop»
        +en_marcha_atras: bool «prop»
        +rumbo: float «prop»
        +__init__(numero_tramos: int = 5, longitud_tramo: float = 50.0, velocidad_porcentaje: float = 50.0, velocidad_nominal: float = 3.0, ruido_lateral: float = 0.0)
        +start()
        +stop()
        +invertir_direccion()
        +set_speed(velocidad_porcentaje: float)
        +asignar_caja(indice_tramo: int, metros_path: float, metros_heading: float, lat_origen: float, lon_origen: float, puerto_path: str, puerto_heading: str, carr: int = 2, modo_coordenadas: str = "geo")
        +avanza(segundos: int = 1)
        +get_span_info(indice: int) dict
        +get_span_alineado(indice: int) bool
        -_tiempo_formateado() str
        -_validar_seccion_intermedia(indice_seccion: int) TramoIntermedio
    }

    %% ─────────────────────────────────────────────────────────────────────
    %% Relaciones
    %% ─────────────────────────────────────────────────────────────────────

    FreeStandingSpan --> TramoIntermedio : referencia izq y der
    AntenaGPS --> TramoFinal : seccion_inicio / seccion_fin
    AntenaGPS --> TramoIntermedio : seccion_inicio / seccion_fin
    AntenaGPS --> METROS_POR_GRADO_LAT : usa
    AntenaGPS --> _aplicar_interferencia_gps : usa
    AntenaGPS --> _aplicar_interferencia_cartesiana : usa
    CajaInterfaz *-- AntenaGPS : compone (path y heading)
    CajaInterfaz --> _aplicar_interferencia_gps : usa
    CajaInterfaz --> _aplicar_interferencia_cartesiana : usa
    TramoIntermedio --> avanzar_en_circunferencia : usa (arco)
    TramoIntermedio --> _metros_recorridos : usa
    TramoFinal --> _metros_recorridos : usa
    _aplicar_interferencia_gps --> METROS_POR_GRADO_LAT : usa
    _aplicar_interferencia_cartesiana --> METROS_POR_GRADO_LAT : usa
    Lineal *-- TramoFinal : compone (secciones Cart y End)
    Lineal *-- TramoIntermedio : compone (secciones intermedias)
    Lineal *-- FreeStandingSpan : compone
    Lineal o-- CajaInterfaz : agregación
