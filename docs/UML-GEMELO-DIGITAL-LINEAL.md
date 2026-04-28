classDiagram
direction TB

    class METROS_POR_GRADO_LAT {
        <<constante módulo>>
        +valor: float = 111320.0
    }

    class avanzar_en_circunferencia {
        <<function>>
        +avanzar_en_circunferencia(centro_x, centro_y, radio, inicio_x, inicio_y, distancia) tuple
    }

    class Contactor {
	    «class» CERRADO: str = "CERRADO"
	    «class» ABIERTO: str = "ABIERTO"
	    +duty_cycle: float
	    +estado: str
	    +esta_cerrado: bool «prop»
	    +__init__(velocidad_porcentaje: float = 0.0)
	    +actualizar_duty_cycle(segundo_en_ciclo: int, duracion_ciclo: int = 60)
	    +cerrar()
	    +abrir()
    }

    class Torre {
	    +posicion_x: float
	    +posicion_y: float
	    +longitud_tramo: float
	    +velocidad_nominal: float
	    +porcentaje_patinaje: float
	    +__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal: float = 3.0)
	    +avanzar(segundos: float, direccion: int = 1, rumbo: float = 0.0) float
    }

    class Torre_Guia {
	    +contactor: Contactor
	    +ruido_lateral: float
	    +__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal: float = 3.0, velocidad_porcentaje: float = 50.0, ruido_lateral: float = 0.0)
	    +avanzar(segundos: float, direccion: int = 1, rumbo: float = 0.0) float
    }

    class Torre_Intermedia {
	    «class» FACTOR_SOBREVELOCIDAD: float = 1.5
	    «class» FACTOR_SOBREVELOCIDAD_RAPIDA: float = 2.0
	    «class» UMBRAL_ARRANQUE: float = 0.10
	    «class» UMBRAL_ADELANTO: float = 0.10
	    +contactor: Contactor
	    +es_motor_rapido: bool
	    +factor_sobrevelocidad: float «prop»
	    +__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal: float = 3.0, es_motor_rapido: bool = False)
	    +seguir(objetivo_x: float, objetivo_y: float, segundos: float, direccion: int = 1, pivot_x: float = None, pivot_y: float = None, rumbo: float = 0.0) float
    }

    class Tramo {
	    «class» TOLERANCIA_ALINEACION: float = 0.05
	    +torre_izquierda: Torre
	    +torre_derecha: Torre
	    +es_rigido: bool
	    +angulo_referencia: float
	    +longitud_horizontal: float «prop»
	    +desviacion_norte: float «prop»
	    +desviacion_norte_relativa: float «prop»
	    +angulo_grados: float «prop»
	    +angulo_relativo_grados: float «prop»
	    +esta_alineado: bool «prop»
	    +__init__(torre_izquierda, torre_derecha, es_rigido: bool = False)
    }

    class GPS {
	    +torre: Torre_Intermedia
	    +lat_origen: float
	    +lon_origen: float
	    +puerto_serial: str | None
	    +baudrate: int
	    +verbose_consola: bool
	    -_conexion
	    -_hilo
	    -_activo: bool
	    +latitud: float «prop»
	    +longitud: float «prop»
	    +lat_e7: int «prop»
	    +lon_e7: int «prop»
	    +iniciar_transmision_background()
	    +detener_transmision_background()
	    -_bucle_transmision()
    }

    class CajaInterfaz {
	    «class» BAUDRATE: int = 115200
	    +torre: Torre_Intermedia
	    +lat_origen: float
	    +lon_origen: float
	    +puerto_serial: str
	    +carr: int
	    +slow_down_cart: bool
	    +slow_down_end_tower: bool
	    +safety_ok: bool
	    +gps_ok: bool
	    +ultimo_mensaje: str
	    -_activo: bool
	    -_hilo
	    +latitud: float «prop»
	    +longitud: float «prop»
	    +lat_e7: int «prop»
	    +lon_e7: int «prop»
	    +iniciar()
	    +detener()
	    -_bucle()
	    -_procesar(msg: str)
    }

    class Lineal {
	    «class» DURACION_CICLO: int = 60
	    +numero_tramos: int
	    +longitud_tramo: float
	    +velocidad_porcentaje: float
	    +velocidad_nominal: float
	    +indice_tramo_rigido: int
	    +indice_torre_motor_rapido: int
	    +torres: list~Torre~
	    +tramos: list~Tramo~
	    +guia_izquierda: Torre_Guia
	    +guia_derecha: Torre_Guia
	    +tiempo_total_segundos: int
	    +ciclo_actual: int
	    +direccion: int
	    +slow_down_cart: bool
	    +slow_down_end_tower: bool
	    +motor_rapido_pct_on: float
	    -_segundo_en_ciclo: int
	    -_segundos_motor_rapido_on: int
	    -_en_marcha: bool
	    +gps: GPS | None
	    +caja_interfaz: CajaInterfaz | None
	    +posicion_norte: float «prop»
	    +longitud_total: float «prop»
	    +esta_alineado: bool «prop»
	    +en_marcha_atras: bool «prop»
	    +rumbo: float «prop»
	    +__init__(numero_tramos: int = 5, longitud_tramo: float = 50.0, velocidad_porcentaje: float = 50.0, velocidad_nominal: float = 3.0, ruido_lateral: float = 0.0)
	    +asignar_gps(indice_torre, lat_origen, lon_origen, puerto_serial, baudrate, verbose_consola)
	    +asignar_caja(indice_torre, lat_origen, lon_origen, puerto_serial, carr)
	    +start()
	    +stop()
	    +invertir_direccion()
	    +set_speed(velocidad_porcentaje: float)
	    +avanza(segundos: int = 1)
	    -_actualizar_fss()
	    -_tiempo_formateado() str
    }

    Torre <|-- Torre_Guia : hereda
    Torre <|-- Torre_Intermedia : hereda
    Torre_Guia *-- Contactor : compone
    Torre_Intermedia *-- Contactor : compone
    Tramo --> Torre : referencia izq
    Tramo --> Torre : referencia der
    GPS --> Torre_Intermedia : referencia
    CajaInterfaz --> Torre_Intermedia : referencia
    Torre_Intermedia --> avanzar_en_circunferencia : usa
    Lineal *-- Torre : compone
    Lineal *-- Tramo : compone
    Lineal o-- GPS : agregación
    Lineal o-- CajaInterfaz : agregación
    Lineal --> Torre_Guia : usa
    GPS --> METROS_POR_GRADO_LAT : usa
    CajaInterfaz --> METROS_POR_GRADO_LAT : usa
