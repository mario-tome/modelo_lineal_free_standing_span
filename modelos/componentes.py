import math, random, threading, time as _time

def avanzar_en_circunferencia(centro_x, centro_y, radio, inicio_x, inicio_y, distancia):
    """
    Posición final de un móvil que recorre una distancia sobre una circunferencia
    distancia > 0 = sentido antihorario, distancia < 0 = sentido horario
    """
    angulo_inicial = math.atan2(inicio_y - centro_y, inicio_x - centro_x)
    angulo_recorrido = distancia / radio
    angulo_final = angulo_inicial + angulo_recorrido

    x_final = centro_x + radio * math.cos(angulo_final)
    y_final = centro_y + radio * math.sin(angulo_final)

    return x_final, y_final

try:
    import serial as _serial_module
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

# Constante geográfica (1 grado de latitud ≈ 111 320 m)
METROS_POR_GRADO_LAT = 111_320.0

# CONECTA/DESCONECTA el motor de una torre
# TORRES GUÍA: duty cycle (ciclos ON/OFF de 60 s para controlar la velocidad media)
# TORRES INTERMEDIAS: indicador de alineación (ON = desalineada, OFF = alineada)
class Contactor:

    CERRADO = "CERRADO" # motor ON
    ABIERTO = "ABIERTO" # motor OFF

    def __init__(self, velocidad_porcentaje: float = 0.0):
        """velocidad_porcentaje: duty cycle en %"""
        self.duty_cycle = velocidad_porcentaje / 100.0
        self.estado     = self.ABIERTO

    def actualizar_duty_cycle(self, segundo_en_ciclo: int, duracion_ciclo: int = 60):
        """cierra o abre el contactor según el segundo actual dentro del ciclo"""
        tiempo_activo = self.duty_cycle * duracion_ciclo
        self.estado   = self.CERRADO if segundo_en_ciclo < tiempo_activo else self.ABIERTO

    def cerrar(self):
        self.estado = self.CERRADO

    def abrir(self):
        self.estado = self.ABIERTO

    @property
    def esta_cerrado(self) -> bool:
        return self.estado == self.CERRADO


# TORRE DEL LINEAL: puede ser guía o intermedia
# posición (x, y), longitud del tramo al siguiente, velocidad nominal (m/min) y porcentaje de patinaje aleatorio
class Torre:

    def __init__(self, posicion_x: float, posicion_y: float, 
                 longitud_tramo: float, velocidad_nominal: float = 3.0):
        
        self.posicion_x = posicion_x
        self.posicion_y = posicion_y
        self.longitud_tramo = longitud_tramo
        self.velocidad_nominal = velocidad_nominal
        self.porcentaje_patinaje = random.uniform(0.0, 5.0) # única por torre

    def avanzar(self, segundos: float, direccion: int = 1, rumbo: float = 0.0) -> float:
        """
        Mueve la torre durante en la dirección del rumbo actual del lineal
        rumbo: ángulo en radianes desde el norte (positivo = este)
        Devuelve los metros recorridos
        """
        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = self.velocidad_nominal * (segundos / 60.0) * factor_patinaje
        self.posicion_x += math.sin(rumbo) * metros_avanzados * direccion
        self.posicion_y += math.cos(rumbo) * metros_avanzados * direccion
        return metros_avanzados


# Torres de los extremos: Cart (izquierda) y End-tower (derecha)
# Contactor de duty cycle: su ciclo ON/OFF marca el ritmo de avance
# En modo slow_down abandonan el duty cycle y copian el ON/OFF del motor rápido
class Torre_Guia(Torre):

    def __init__(self, posicion_x: float, posicion_y: float, longitud_tramo: float, 
                 velocidad_nominal: float = 3.0, velocidad_porcentaje: float = 50.0, ruido_lateral: float = 0.0):

        # RUIDO LATERAL: deriva lateral aleatoria por metro avanzado (0 = perfecto, 0.070 = loco)
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor = Contactor(velocidad_porcentaje)
        self.ruido_lateral = ruido_lateral

    def avanzar(self, segundos: float, direccion: int = 1, rumbo: float = 0.0) -> float:
        """
        Avanza o retrocede si el contactor está cerrado, en la dirección del rumbo
        El ruido lateral se aplica perpendicular al rumbo
        """
        if self.contactor.esta_cerrado:
            metros = super().avanzar(segundos, direccion, rumbo)
            if self.ruido_lateral > 0.0 and metros > 0.0:
                ruido = random.gauss(0.0, self.ruido_lateral * metros)
                self.posicion_x += math.cos(rumbo) * ruido
                self.posicion_y -= math.sin(rumbo) * ruido
            return metros
        return 0.0


# Torres intermedias: contactor de alineación ON/OFF (sin duty cycle)
# - ON = desalineada, motor activo recuperando posición
# - OFF = alineada, motor parado
# La del extremo derecho del tramo rígido tiene motor más rápido (cubre más ángulo en el mismo tiempo)
class Torre_Intermedia(Torre):

    FACTOR_SOBREVELOCIDAD = 1.5 # motor intermedio normal: ×1.5 la velocidad nominal
    FACTOR_SOBREVELOCIDAD_RAPIDA = 2.0 # motor rápido ×2.0
    UMBRAL_ARRANQUE = 0.10 # retraso mínimo para activar motor
    UMBRAL_ADELANTO = 0.10 # adelanto máximo antes de apagar motor

    def __init__(self, posicion_x: float, posicion_y: float, longitud_tramo: float, 
                 velocidad_nominal: float = 3.0, es_motor_rapido: bool = False):

        # es_motor_rapido: True para la torre del extremo derecho del tramo rígido
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor = Contactor()
        self.es_motor_rapido = es_motor_rapido

    @property
    def factor_sobrevelocidad(self) -> float:
        return (self.FACTOR_SOBREVELOCIDAD_RAPIDA
                if self.es_motor_rapido
                else self.FACTOR_SOBREVELOCIDAD)

    def seguir(self, objetivo_x: float, objetivo_y: float, segundos: float,
               direccion: int = 1,
               pivot_x: float = None, pivot_y: float = None,
               rumbo: float = 0.0) -> float:
        """
        Sigue el objetivo (objetivo_x, objetivo_y) en la diagonal Cart→End-tower
        El desfase se proyecta sobre el rumbo para que funcione tanto si el lineal va recto al norte como en diagonal
        El signo del arco se calcula respecto al rumbo para que el giro sea correcto en cualquier dirección
        """
        # Proyección del vector (objetivo - posición) sobre el eje de avance del lineal
        dx = objetivo_x - self.posicion_x
        dy = objetivo_y - self.posicion_y
        avance_x = math.sin(rumbo)
        avance_y = math.cos(rumbo)
        desviacion = (dx * avance_x + dy * avance_y) * direccion  # + atrasada, - adelantada

        if desviacion >= self.UMBRAL_ARRANQUE:
            self.contactor.cerrar()
        elif desviacion <= -self.UMBRAL_ADELANTO:
            self.contactor.abrir()

        if not self.contactor.esta_cerrado:
            return 0.0

        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = self.velocidad_nominal * self.factor_sobrevelocidad * (segundos / 60.0) * factor_patinaje

        if pivot_x is not None and pivot_y is not None:
            # Derecha del rumbo (perpendicular apuntando a la derecha del avance)
            # antihorario si la torre está a la derecha del pivote, horario si está a la izquierda
            derecha_x = math.cos(rumbo)
            derecha_y = -math.sin(rumbo)
            dot = (self.posicion_x - pivot_x) * derecha_x + (self.posicion_y - pivot_y) * derecha_y
            signo_avance   = 1 if dot > 0 else -1
            distancia_arco = metros_avanzados * direccion * signo_avance
            self.posicion_x, self.posicion_y = avanzar_en_circunferencia(
                pivot_x, pivot_y, self.longitud_tramo,
                self.posicion_x, self.posicion_y, distancia_arco
            )
        else:
            self.posicion_x += avance_x * metros_avanzados * direccion
            self.posicion_y += avance_y * metros_avanzados * direccion

        return metros_avanzados


# Segmento entre dos torres
# Mide su ángulo e inclinación
# El tramo rígido central (Free Standing Span) no puede doblarse
class Tramo:

    TOLERANCIA_ALINEACION = 0.05  # diferencia máxima para considerarse alineado (metros)

    def __init__(self, torre_izquierda: Torre, torre_derecha: Torre, es_rigido: bool = False):

        self.torre_izquierda = torre_izquierda
        self.torre_derecha = torre_derecha
        self.es_rigido = es_rigido
        self.angulo_referencia: float = 0.0

    @property
    def longitud_horizontal(self) -> float:
        """Distancia en X entre las dos torres del tramo"""
        return abs(self.torre_derecha.posicion_x - self.torre_izquierda.posicion_x)

    @property
    def desviacion_norte(self) -> float:
        """Diferencia absoluta en Y entre torre derecha e izquierda"""
        return self.torre_derecha.posicion_y - self.torre_izquierda.posicion_y

    @property
    def desviacion_norte_relativa(self) -> float:
        """Desviación en Y del tramo respecto al ángulo esperado del lineal (0 = perfectamente alineado)"""
        if self.longitud_horizontal == 0:
            return self.desviacion_norte
        dy_esperado = math.tan(math.radians(self.angulo_referencia)) * self.longitud_horizontal
        return self.desviacion_norte - dy_esperado

    @property
    def angulo_grados(self) -> float:
        """Ángulo absoluto del tramo respecto al eje horizontal (0 = horizontal, positivo = sentido antihorario)"""
        if self.longitud_horizontal == 0:
            return 0.0
        return math.degrees(math.atan2(self.desviacion_norte, self.longitud_horizontal))

    @property
    def angulo_relativo_grados(self) -> float:
        """Ángulo del tramo relativo al ángulo de referencia del lineal (0 = alineado con el rumbo)"""
        return self.angulo_grados - self.angulo_referencia

    @property
    def esta_alineado(self) -> bool:
        """True si la desviación relativa al rumbo del lineal está dentro de la tolerancia"""
        return abs(self.desviacion_norte_relativa) < self.TOLERANCIA_ALINEACION


def _aplicar_interferencia_gps(lat_e7: int, lon_e7: int, interferencia_mm: float, lat_origen: float) -> tuple:
    """
    Simula el error real de un receptor GPS RTK (≤ 15 mm)
    Devuelve (lat_e7, lon_e7) con ruido sin tocar las coordenadas originales del modelo
    """
    if interferencia_mm == 0.0:
        return lat_e7, lon_e7
    metros_por_grado_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(lat_origen))
    desvio_lat_m = random.uniform(-interferencia_mm, interferencia_mm) / 1000.0
    desvio_lon_m = random.uniform(-interferencia_mm, interferencia_mm) / 1000.0
    lat_con_ruido = lat_e7 + round(desvio_lat_m / METROS_POR_GRADO_LAT * 1e7)
    lon_con_ruido = lon_e7 + round(desvio_lon_m / metros_por_grado_lon * 1e7)
    return lat_con_ruido, lon_con_ruido


# GPS virtual asignado a una Torre_Intermedia
# Convierte X/Y (metros) a lat/lon reales usando el Cart como origen geográfico
# Emite coordenadas como enteros ×10⁷ por puerto serie cada segundo
# Sin puerto configurado puede imprimir por consola para depuración
class GPS:

    def __init__(self, torre: "Torre_Intermedia",
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str = None,
                 baudrate: int = 9600,
                 verbose_consola: bool = False):

        self.torre = torre
        self.lat_origen = lat_origen
        self.lon_origen = lon_origen
        self.puerto_serial = puerto_serial
        self.baudrate = baudrate
        self.verbose_consola = verbose_consola
        self._conexion = None
        self._hilo = None
        self._activo = False
        self.interferencia_gps_mm: float = 0.0 

    @property
    def latitud(self) -> float:
        """Latitud actual de la torre en grados decimales"""
        return self.lat_origen + (self.torre.posicion_y / METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        """Longitud actual de la torre en grados decimales"""
        metros_por_grado_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen))
        return self.lon_origen + (self.torre.posicion_x / metros_por_grado_lon)

    @property
    def lat_e7(self) -> int:
        """Latitud en formato entero ×10⁷"""
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        """Longitud en formato entero ×10⁷"""
        return round(self.longitud * 1e7)

    def iniciar_transmision_background(self):
        """Lanza un hilo en segundo plano que transmite la posición 1 vez/segundo real por USB o consola"""
        if self.puerto_serial is None and not self.verbose_consola:
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo   = threading.Thread(target=self._bucle_transmision, daemon=True)
        self._hilo.start()

    def detener_transmision_background(self):
        """Señaliza al hilo que pare. El puerto serie se cierra solo al salir del bucle"""
        self._activo = False

    def _bucle_transmision(self):
        """Bucle del hilo de transmisión: envía por USB o imprime por consola cada segundo"""
        conexion = None

        if self.puerto_serial is not None:
            try:
                conexion = _serial_module.Serial(
                    self.puerto_serial, self.baudrate,
                    timeout=1, write_timeout=1,
                    rtscts=False, dsrdtr=False, xonxoff=False,
                )
            except Exception as e:
                print(f"Error abriendo {self.puerto_serial}: {e}")
                return

        while self._activo:
            lat_emitido, lon_emitido = _aplicar_interferencia_gps(
                self.lat_e7, self.lon_e7, self.interferencia_gps_mm, self.lat_origen
            )
            mensaje = f"LAT:{lat_emitido},LON:{lon_emitido}\n"
            if conexion is not None:
                try:
                    conexion.write(mensaje.encode("utf-8"))
                    conexion.flush()
                except Exception as e:
                    print(f"Error en transmisión: {e}")
                    break
            if self.verbose_consola:
                print(f"GPS {mensaje.strip()}  (real: {self.latitud:.7f}°, {self.longitud:.7f}°)")
            _time.sleep(1.0)

        if conexion is not None:
            conexion.close()

# Gestiona la comunicación bidireccional con la caja de interfaz Arduino (115 200 baud)
# PC al Arduino (1 Hz) la posición GPS: "Lat 415191807 Lon -47151090 Carr 2"
# Arduino al PC:
# - "SLOW_DOWN_CART_ON/OFF": orden de ralentizar Cart
# - "SLOW_DOWN_END_TOWER_ON/OFF": orden de ralentizar End-tower
# - "SAFETY_OK / SAFETY_FAIL": estado de seguridad
# - "GPS_OK / GPS_FAIL": estado del GPS de la caja
# carr = calidad RTK reportada: 0 = sin RTK  1 = RTK float  2 = RTK FIX
class CajaInterfaz:

    BAUDRATE = 115_200

    def __init__(self,
                 torre: "Torre_Intermedia",
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str,
                 carr: int = 2):

        self.torre = torre
        self.lat_origen = lat_origen
        self.lon_origen = lon_origen
        self.puerto_serial = puerto_serial
        self.carr = carr

        # estado recibido del algoritmo de guiado vía Arduino
        self.slow_down_cart: bool = False
        self.slow_down_end_tower: bool = False
        self.safety_ok: bool = True
        self.gps_ok: bool = True
        self.ultimo_mensaje: str  = ""

        self._activo = False
        self._hilo = None
        self.interferencia_gps_mm: float = 0.0 

    @property
    def latitud(self) -> float:
        return self.lat_origen + (self.torre.posicion_y / METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        metros_por_grado_lon = METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen))
        return self.lon_origen + (self.torre.posicion_x / metros_por_grado_lon)

    @property
    def lat_e7(self) -> int:
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        return round(self.longitud * 1e7)

    def iniciar(self):
        """Abre el puerto serie y lanza el hilo de comunicación bidireccional con la caja Arduino"""
        if not _SERIAL_DISPONIBLE:
            print("Pyserial no instalado, ejecuta: pip install pyserial")
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        """Señaliza al hilo de comunicación que se detenga"""
        self._activo = False

    def _bucle(self):
        """Único hilo, envía GPS al Arduino cada segundo y procesa los mensajes entrantes"""
        try:
            ser = _serial_module.Serial(
                self.puerto_serial, self.BAUDRATE,
                timeout=0.1,
                write_timeout=1,
                rtscts=False, dsrdtr=False, xonxoff=False,
            )
        except Exception as e:
            print(f"No se pudo abrir {self.puerto_serial}: {e}")
            return

        ultimo_envio = 0.0
        while self._activo:
            ahora = _time.time()

            # Enviar GPS al Arduino cada segundo
            if ahora - ultimo_envio >= 1.0:
                lat_emitido, lon_emitido = _aplicar_interferencia_gps(
                    self.lat_e7, self.lon_e7, self.interferencia_gps_mm, self.lat_origen
                )
                trama = f"Lat {lat_emitido} Lon {lon_emitido} Carr {self.carr}\n"
                try:
                    ser.write(trama.encode("utf-8"))
                    ser.flush()
                    ultimo_envio = ahora
                except Exception as e:
                    print(f"Error enviando GPS: {e}")
                    break

            # Leer y procesar mensajes del Arduino
            try:
                linea = ser.readline().decode("utf-8", errors="replace").strip()
                if linea:
                    self.ultimo_mensaje = linea
                    self._procesar(linea)
            except Exception as e:
                if self._activo:
                    print(f"Error leyendo: {e}")
                break

        ser.close()

    def _procesar(self, msg: str):
        """Actualiza el estado interno según el mensaje recibido del Arduino"""
        if   msg == "SLOW_DOWN_CART_ON": self.slow_down_cart = True
        elif msg == "SLOW_DOWN_CART_OFF": self.slow_down_cart = False
        elif msg == "SLOW_DOWN_END_TOWER_ON": self.slow_down_end_tower = True
        elif msg == "SLOW_DOWN_END_TOWER_OFF": self.slow_down_end_tower = False
        elif msg == "SAFETY_OK":  self.safety_ok = True
        elif msg == "SAFETY_FAIL": self.safety_ok = False
        elif msg == "GPS_OK": self.gps_ok = True
        elif msg == "GPS_FAIL": self.gps_ok = False
