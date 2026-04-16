import math, random, threading, time as _time

try:
    import serial as _serial_module
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False


# Conecta/desconecta el motor de una torre.
# Torres guía: modo duty cycle (ciclos ON/OFF de 60 s para controlar la velocidad media).
# Torres intermedias: indicador de alineación (ON = desalineada, OFF = alineada).
class Contactor:

    CERRADO = "CERRADO"   # Motor ON
    ABIERTO  = "ABIERTO"  # Motor OFF

    def __init__(self, velocidad_porcentaje: float = 0.0):
        """velocidad_porcentaje: duty cycle en % (solo relevante en torres guía)"""
        self.duty_cycle = velocidad_porcentaje / 100.0
        self.estado     = self.ABIERTO

    # Uso en torres guía
    def actualizar_duty_cycle(self, segundo_en_ciclo: int, duracion_ciclo: int = 60):
        """Cierra o abre el contactor según el segundo actual dentro del ciclo (duty cycle)"""
        tiempo_activo = self.duty_cycle * duracion_ciclo
        self.estado   = self.CERRADO if segundo_en_ciclo < tiempo_activo else self.ABIERTO

    def cerrar(self):
        """Motor ON: torre desalineada, recuperando posición."""
        self.estado = self.CERRADO

    def abrir(self):
        """Motor OFF: torre alineada."""
        self.estado = self.ABIERTO

    @property
    def esta_cerrado(self) -> bool:
        return self.estado == self.CERRADO

    def __repr__(self):
        return f"Contactor(duty={self.duty_cycle * 100:.0f}%, estado={self.estado})"


# Torre base: X fija (posición lateral), Y avanza al norte cuando el motor está ON.
# Cada torre tiene un porcentaje de patinaje aleatorio que simula irregularidades del terreno.
class Torre:

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0):
        self.posicion_x        = posicion_x
        self.posicion_y        = posicion_y
        self.longitud_tramo    = longitud_tramo
        self.velocidad_nominal = velocidad_nominal
        self.porcentaje_patinaje = random.uniform(0.0, 5.0)  # imperfección única por torre

    def avanzar(self, segundos: float, direccion: int = 1) -> float:
        """
        Mueve la torre durante 'segundos' a velocidad nominal.
        direccion =  1 → hacia el norte (avance normal)
        direccion = -1 → hacia el sur   (marcha atrás)
        El patinaje reduce ligeramente la velocidad según el terreno.
        Devuelve los metros recorridos (positivo siempre; el signo lo da direccion).
        """
        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = self.velocidad_nominal * (segundos / 60.0) * factor_patinaje
        self.posicion_y += metros_avanzados * direccion
        return metros_avanzados

    @property
    def posicion(self) -> tuple:
        return (self.posicion_x, self.posicion_y)

    def __repr__(self):
        return f"{self.__class__.__name__}(x={self.posicion_x:.0f}m, y={self.posicion_y:.3f}m)"


# Torres de los extremos: Cart (izquierda) y End-tower (derecha).
# Son las únicas con contactor de duty cycle — su ciclo ON/OFF marca el ritmo de avance de todo el lineal.
class Torre_Guia(Torre):

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 velocidad_porcentaje: float = 50.0,
                 ruido_lateral: float = 0.0):
        # ruido_lateral: deriva lateral aleatoria por metro avanzado (0=perfecto, 0.070=loco)
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor     = Contactor(velocidad_porcentaje)
        self.ruido_lateral = ruido_lateral

    def avanzar(self, segundos: float, direccion: int = 1) -> float:
        """Avanza (o retrocede) si el contactor está cerrado. Aplica ruido lateral del terreno."""
        if self.contactor.esta_cerrado:
            metros = super().avanzar(segundos, direccion)
            if self.ruido_lateral > 0.0 and metros > 0.0:
                self.posicion_x += random.gauss(0.0, self.ruido_lateral * metros)
            return metros
        return 0.0

    def __repr__(self):
        ruido_txt = f"  [ruido={self.ruido_lateral:.3f}]" if self.ruido_lateral > 0.0 else ""
        return (f"Torre_Guia(x={self.posicion_x:.3f}m, y={self.posicion_y:.3f}m,"
                f" contactor={self.contactor.estado}){ruido_txt}")


# Torres intermedias: contactor de alineación ON/OFF (sin duty cycle).
# ON = desalineada, motor activo recuperando posición. OFF = alineada, motor parado.
# La del extremo derecho del tramo rígido tiene motor más rápido (cubre más ángulo en el mismo tiempo).
class Torre_Intermedia(Torre):

    FACTOR_SOBREVELOCIDAD        = 1.5   # motor intermedio normal: ×1.5 la velocidad nominal
    FACTOR_SOBREVELOCIDAD_RAPIDA = 2.0   # motor rápido (extremo der. tramo rígido): ×2.0
    UMBRAL_ARRANQUE              = 0.30  # desalineación mínima (metros) para activar el motor

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 es_motor_rapido: bool = False):
        # es_motor_rapido: True solo para la torre del extremo derecho del tramo rígido
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor      = Contactor()   # contactor de alineación (sin duty cycle)
        self.es_motor_rapido = es_motor_rapido

    @property
    def factor_sobrevelocidad(self) -> float:
        return (self.FACTOR_SOBREVELOCIDAD_RAPIDA
                if self.es_motor_rapido
                else self.FACTOR_SOBREVELOCIDAD)

    def seguir(self, y_izq: float, y_der: float, segundos: float,
               direccion: int = 1) -> float:
        """
        Sigue al vecino más adelantado (avance) o más retrasado (marcha atrás).
        Se activa cuando la desviación supera UMBRAL_ARRANQUE. Nunca sobrepasa al vecino.
        """
        # Multiplicar por direccion invierte el sentido del gap en marcha atrás
        gap_izq = (y_izq - self.posicion_y) * direccion
        gap_der = (y_der - self.posicion_y) * direccion
        desviacion = max(gap_izq, gap_der)

        if desviacion < self.UMBRAL_ARRANQUE:
            self.contactor.abrir()
            return 0.0

        self.contactor.cerrar()
        factor_patinaje        = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        velocidad_recuperacion = self.velocidad_nominal * self.factor_sobrevelocidad
        capacidad_por_segundo  = velocidad_recuperacion * (segundos / 60.0) * factor_patinaje
        metros_avanzados       = min(desviacion, capacidad_por_segundo)

        self.posicion_y += metros_avanzados * direccion
        return metros_avanzados

    def seguir_arco(self, y_objetivo: float, segundos: float,
                    direccion: int = 1) -> float:
        """
        Modo giro: persigue la posición interpolada en el arco sin umbral de activación.
        Funciona hacia el norte (avance) o hacia el sur (marcha atrás) según direccion.
        """
        diferencia = (y_objetivo - self.posicion_y) * direccion
        if diferencia <= 0.005:          # ya en posición → motor parado
            self.contactor.abrir()
            return 0.0

        self.contactor.cerrar()
        factor_patinaje        = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        velocidad_recuperacion = self.velocidad_nominal * self.factor_sobrevelocidad
        capacidad_por_segundo  = velocidad_recuperacion * (segundos / 60.0) * factor_patinaje
        metros_avanzados       = min(diferencia, capacidad_por_segundo)

        self.posicion_y += metros_avanzados * direccion
        return metros_avanzados

    def __repr__(self):
        rapido_txt = " [MOTOR RAPIDO]" if self.es_motor_rapido else ""
        return (f"Torre_Intermedia(x={self.posicion_x:.0f}m, y={self.posicion_y:.3f}m,"
                f" contactor={self.contactor.estado}){rapido_txt}")


# Segmento entre dos torres. Mide su ángulo e inclinación (0° = perfectamente alineado).
# El tramo rígido central (Free Standing Span) no puede doblarse: sus torres se mueven como un bloque.
class Tramo:

    TOLERANCIA_ALINEACION = 0.05  # diferencia máxima para considerarse alineado (metros)

    def __init__(self, torre_izquierda: Torre, torre_derecha: Torre,
                 es_rigido: bool = False):
        self.torre_izquierda = torre_izquierda
        self.torre_derecha   = torre_derecha
        self.es_rigido       = es_rigido

    @property
    def longitud_horizontal(self) -> float:
        """Distancia fija en X entre las dos torres del tramo (metros)"""
        return abs(self.torre_derecha.posicion_x - self.torre_izquierda.posicion_x)

    @property
    def desviacion_norte(self) -> float:
        """Diferencia en Y entre torre derecha e izquierda (0 = alineado, + = derecha adelantada)."""
        return self.torre_derecha.posicion_y - self.torre_izquierda.posicion_y

    @property
    def angulo_grados(self) -> float:
        """Ángulo de inclinación del tramo respecto al eje horizontal"""
        if self.longitud_horizontal == 0:
            return 0.0
        return math.degrees(math.atan2(self.desviacion_norte, self.longitud_horizontal))

    @property
    def esta_alineado(self) -> bool:
        """True si la desviación está dentro de la tolerancia (5 cm)"""
        return abs(self.desviacion_norte) < self.TOLERANCIA_ALINEACION

    def __repr__(self):
        rigido_txt = " [RIGIDO]" if self.es_rigido else ""
        return (f"Tramo(x={self.torre_izquierda.posicion_x:.0f}m"
                f"->{self.torre_derecha.posicion_x:.0f}m,"
                f" desv={self.desviacion_norte:+.3f}m,"
                f" angulo={self.angulo_grados:+.3f}grd){rigido_txt}")


# GPS virtual asignado a una Torre_Intermedia.
# Convierte X/Y (metros) a lat/lon reales usando el Cart como origen geográfico.
# Emite coordenadas como enteros ×10⁷ (ej. 40.1234567° → 401234567) por puerto serie cada segundo.
# Sin puerto configurado puede imprimir por consola para depuración.
class GPS:

    # 1 grado de latitud ≈ 111 320 m
    _METROS_POR_GRADO_LAT = 111_320.0

    def __init__(self,
                 torre: "Torre_Intermedia",
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str = None,
                 baudrate: int = 9600,
                 verbose_consola: bool = False):
        # lat/lon_origen: coordenadas GPS reales del Cart al inicio (X=0, Y=0)
        # puerto_serial: 'COM3', '/dev/ttyUSB0', etc. None = sin hardware
        # verbose_consola: imprime coordenadas por consola cuando no hay puerto serie
        self.torre            = torre
        self.lat_origen       = lat_origen
        self.lon_origen       = lon_origen
        self.puerto_serial    = puerto_serial
        self.baudrate         = baudrate
        self.verbose_consola  = verbose_consola
        self._conexion        = None   # objeto serial; se abre al primer uso
        self._hilo            = None   # hilo de transmisión en background
        self._activo          = False  # controla el bucle del hilo

    # Conversión de coordenadas  X/Y (metros) → lat/lon (grados)
    @property
    def latitud(self) -> float:
        """Latitud actual de la torre en grados decimales"""
        return self.lat_origen + (self.torre.posicion_y / self._METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        """Longitud actual de la torre en grados decimales"""
        metros_por_grado_lon = (self._METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen)))
        return self.lon_origen + (self.torre.posicion_x / metros_por_grado_lon)

    @property
    def lat_e7(self) -> int:
        """Latitud en formato entero ×10⁷ (para hardware GPS)"""
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        """Longitud en formato entero ×10⁷ (para hardware GPS)"""
        return round(self.longitud * 1e7)

    # Comunicación serie
    def _abrir_puerto(self) -> bool:
        """Intenta abrir el puerto serie. Devuelve True si está listo."""
        if self.puerto_serial is None:
            return False
        if not _SERIAL_DISPONIBLE:
            print("[GPS] pyserial no instalado. Ejecuta: pip install pyserial")
            return False
        try:
            if self._conexion is None or not self._conexion.is_open:
                self._conexion = _serial_module.Serial(
                    self.puerto_serial, self.baudrate, timeout=1
                )
            return True
        except Exception as e:
            print(f"[GPS] Error abriendo {self.puerto_serial}: {e}")
            return False

    def cerrar_puerto(self):
        """Cierra el puerto serie si está abierto."""
        if self._conexion and self._conexion.is_open:
            self._conexion.close()

    def iniciar_transmision_background(self):
        """Lanza un hilo en segundo plano que transmite la posición 1 vez/segundo real."""
        if self.puerto_serial is None and not self.verbose_consola:
            return   # nada que hacer: ni puerto ni consola
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo   = threading.Thread(target=self._bucle_transmision, daemon=True)
        self._hilo.start()

    def detener_transmision_background(self):
        """Señaliza al hilo que pare. El puerto serie se cierra solo al salir del bucle."""
        self._activo = False

    def _bucle_transmision(self):
        """Bucle del hilo de transmisión: envía por USB o imprime por consola cada segundo."""
        conexion = None
        if self.puerto_serial is not None:
            try:
                conexion = _serial_module.Serial(
                    self.puerto_serial, self.baudrate,
                    timeout=1, write_timeout=1,
                    rtscts=False, dsrdtr=False, xonxoff=False,
                )
            except Exception as e:
                print(f"[GPS] Error abriendo {self.puerto_serial}: {e}")
                return

        while self._activo:
            mensaje = f"LAT:{self.lat_e7},LON:{self.lon_e7}\n"
            if conexion is not None:
                try:
                    conexion.write(mensaje.encode("utf-8"))
                    conexion.flush()
                except Exception as e:
                    print(f"[GPS] Error en transmisión: {e}")
                    break
            if self.verbose_consola:
                print(f"[GPS] {mensaje.strip()}  ({self.latitud:.7f}°, {self.longitud:.7f}°)")
            _time.sleep(1.0)

        if conexion is not None:
            conexion.close()

    def transmitir(self):
        """Envía la posición actual por USB (o consola si verbose). Formato: LAT:xxx,LON:xxx"""
        mensaje = f"LAT:{self.lat_e7},LON:{self.lon_e7}\n"

        if self._abrir_puerto():
            try:
                self._conexion.write(mensaje.encode("utf-8"))
            except Exception as e:
                print(f"[GPS] Error al transmitir: {e}")
        elif self.verbose_consola:
            print(f"[GPS] {mensaje.strip()}"
                  f"  ({self.latitud:.7f}°, {self.longitud:.7f}°)")

    def __repr__(self):
        puerto_txt = self.puerto_serial if self.puerto_serial else "consola"
        return (f"GPS(torre_x={self.torre.posicion_x:.0f}m,"
                f" lat={self.latitud:.7f}°, lon={self.longitud:.7f}°,"
                f" puerto={puerto_txt})")


# Gestiona la comunicación bidireccional con la caja de interfaz Arduino (115 200 baud).
#
# La caja conecta el gemelo digital con el algoritmo de guiado físico:
#   PC → Arduino  (1 Hz)  "Lat 415191807 Lon -47151090 Carr 2"  — posición GPS
#   Arduino → PC  (evento) "SLOW_DOWN_CART_ON/OFF"               — orden de ralentizar Cart
#                           "SLOW_DOWN_END_TOWER_ON/OFF"          — orden de ralentizar End-tower
#                           "SAFETY_OK / SAFETY_FAIL"             — estado de seguridad
#                           "GPS_OK / GPS_FAIL"                   — estado del GPS de la caja
#
# carr = calidad RTK reportada: 0 = sin RTK  1 = RTK float  2 = RTK FIX
class CajaInterfaz:

    BAUDRATE = 115_200

    def __init__(self,
                 torre,
                 lat_origen: float,
                 lon_origen: float,
                 puerto_serial: str,
                 carr: int = 2):
        # torre: torre cuya posición X/Y se convierte a GPS y se envía al Arduino
        # lat_origen / lon_origen: coordenadas del Cart en el punto de inicio (X=0, Y=0)
        # puerto_serial: puerto USB del Arduino ('COM3', '/dev/ttyUSB0', …)
        self.torre         = torre
        self.lat_origen    = lat_origen
        self.lon_origen    = lon_origen
        self.puerto_serial = puerto_serial
        self.carr          = carr

        # Estado recibido del algoritmo de guiado vía Arduino
        self.slow_down_cart:      bool = False
        self.slow_down_end_tower: bool = False
        self.safety_ok:           bool = True
        self.gps_ok:              bool = True
        self.ultimo_mensaje:      str  = ""

        self._activo = False
        self._hilo   = None

    # Misma conversión X/Y → lat/lon que la clase GPS
    @property
    def latitud(self) -> float:
        return self.lat_origen + (self.torre.posicion_y / GPS._METROS_POR_GRADO_LAT)

    @property
    def longitud(self) -> float:
        metros_por_grado_lon = GPS._METROS_POR_GRADO_LAT * math.cos(math.radians(self.lat_origen))
        return self.lon_origen + (self.torre.posicion_x / metros_por_grado_lon)

    @property
    def lat_e7(self) -> int:
        return round(self.latitud * 1e7)

    @property
    def lon_e7(self) -> int:
        return round(self.longitud * 1e7)

    def iniciar(self):
        """Abre el puerto serie y lanza el hilo de comunicación bidireccional."""
        if not _SERIAL_DISPONIBLE:
            print("[CajaInterfaz] pyserial no instalado — ejecuta: pip install pyserial")
            return
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._activo = True
        self._hilo   = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        """Señaliza al hilo de comunicación que se detenga."""
        self._activo = False

    def _bucle(self):
        """Hilo único: envía GPS al Arduino cada segundo y procesa los mensajes entrantes."""
        try:
            ser = _serial_module.Serial(
                self.puerto_serial, self.BAUDRATE,
                timeout=0.1,       # readline() no bloquea más de 100 ms
                write_timeout=1,
                rtscts=False, dsrdtr=False, xonxoff=False,
            )
        except Exception as e:
            print(f"[CajaInterfaz] No se pudo abrir {self.puerto_serial}: {e}")
            return

        ultimo_envio = 0.0
        while self._activo:
            ahora = _time.time()

            # Enviar GPS al Arduino cada segundo
            if ahora - ultimo_envio >= 1.0:
                trama = f"Lat {self.lat_e7} Lon {self.lon_e7} Carr {self.carr}\n"
                try:
                    ser.write(trama.encode("utf-8"))
                    ser.flush()
                    ultimo_envio = ahora
                except Exception as e:
                    print(f"[CajaInterfaz] Error enviando GPS: {e}")
                    break

            # Leer y procesar mensajes del Arduino (sin bloqueo, timeout 100 ms)
            try:
                linea = ser.readline().decode("utf-8", errors="replace").strip()
                if linea:
                    self.ultimo_mensaje = linea
                    self._procesar(linea)
            except Exception as e:
                if self._activo:
                    print(f"[CajaInterfaz] Error leyendo: {e}")
                break

        ser.close()

    def _procesar(self, msg: str):
        """Actualiza el estado interno según el mensaje recibido del Arduino."""
        if   msg == "SLOW_DOWN_CART_ON":         self.slow_down_cart      = True
        elif msg == "SLOW_DOWN_CART_OFF":         self.slow_down_cart      = False
        elif msg == "SLOW_DOWN_END_TOWER_ON":     self.slow_down_end_tower = True
        elif msg == "SLOW_DOWN_END_TOWER_OFF":    self.slow_down_end_tower = False
        elif msg == "SAFETY_OK":                  self.safety_ok           = True
        elif msg == "SAFETY_FAIL":                self.safety_ok           = False
        elif msg == "GPS_OK":                     self.gps_ok              = True
        elif msg == "GPS_FAIL":                   self.gps_ok              = False


# Orquestador del lineal Free Standing Span (FSS).
# Gestiona guías (duty cycle), intermedias (alineación), tramo rígido central y modo giro.
# Comienza PARADO — usar start() para ponerlo en marcha.
class Lineal:
    DURACION_CICLO = 60  # segundos por ciclo de duty cycle de las torres guía

    def __init__(self,
                 numero_tramos: int          = 5,
                 longitud_tramo: float       = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float    = 3.0,
                 ruido_lateral: float        = 0.0):
        # numero_tramos: mínimo 3 (torres totales = numero_tramos + 1)
        # velocidad_porcentaje: duty cycle de las guías — velocidad media = nominal × (pct/100)
        # ruido_lateral: deriva lateral por metro avanzado (0 = sin ruido)
        if numero_tramos < 3:
            raise ValueError(
                "El lineal Free Standing Span necesita mínimo 3 tramos"
            )

        self.numero_tramos        = numero_tramos
        self.longitud_tramo       = longitud_tramo
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal    = velocidad_nominal

        # Tramo rígido: el tramo central del lineal
        self.indice_tramo_rigido = numero_tramos // 2

        # Torre más rápida: extremo DERECHO del tramo rígido
        self.indice_torre_motor_rapido = self.indice_tramo_rigido + 1

        # torres[0] = Cart (izq), torres[1..N-1] = intermedias, torres[N] = End-tower (der)
        self.torres = []

        self.torres.append(Torre_Guia(
            posicion_x           = 0.0,
            posicion_y           = 0.0,
            longitud_tramo       = longitud_tramo,
            velocidad_nominal    = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral        = ruido_lateral,
        ))

        for i in range(1, numero_tramos):
            es_rapida = (i == self.indice_torre_motor_rapido)
            self.torres.append(Torre_Intermedia(
                posicion_x        = longitud_tramo * i,
                posicion_y        = 0.0,
                longitud_tramo    = longitud_tramo,
                velocidad_nominal = velocidad_nominal,
                es_motor_rapido   = es_rapida
            ))

        self.torres.append(Torre_Guia(
            posicion_x           = longitud_tramo * numero_tramos,
            posicion_y           = 0.0,
            longitud_tramo       = longitud_tramo,
            velocidad_nominal    = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral        = ruido_lateral,
        ))

        # Crear tramos
        self.tramos = []
        for i in range(numero_tramos):
            es_rigido = (i == self.indice_tramo_rigido)
            self.tramos.append(Tramo(self.torres[i], self.torres[i + 1], es_rigido=es_rigido))

        # Accesos directos
        self.guia_izquierda = self.torres[0]    # Cart (extremo izquierdo)
        self.guia_derecha   = self.torres[-1]   # Guía (extremo derecho)

        # Contadores de simulación
        self.tiempo_total_segundos = 0
        self.ciclo_actual          = 0
        self._segundo_en_ciclo     = 0
        self._en_marcha            = False   # el lineal comienza PARADO

        self._mr_on_en_ciclo      = 0      # segundos ON del motor rápido en el ciclo actual
        self.motor_rapido_pct_on  = 0.0   # % ON del motor rápido en el último ciclo completo

        # Dirección de marcha:  1 = avance (norte), -1 = marcha atrás (sur)
        self.direccion: int = 1

        # GPS y caja de interfaz (se asignan después con asignar_gps() / asignar_caja())
        self.gps:            GPS           | None = None
        self.caja_interfaz:  CajaInterfaz  | None = None


    def asignar_gps(self,
                    indice_torre: int,
                    lat_origen: float,
                    lon_origen: float,
                    puerto_serial: str = None,
                    baudrate: int = 9600,
                    verbose_consola: bool = False):
        """Asigna un GPS a la torre intermedia indicada (indice entre 1 y N-1)."""
        if not (1 <= indice_torre <= self.numero_tramos - 1):
            raise ValueError(
                f"indice_torre debe estar entre 1 y {self.numero_tramos - 1} "
                f"(solo torres intermedias)"
            )
        torre = self.torres[indice_torre]
        if not isinstance(torre, Torre_Intermedia):
            raise ValueError(f"La torre {indice_torre} no es una Torre_Intermedia")

        self.gps = GPS(torre, lat_origen, lon_origen, puerto_serial, baudrate, verbose_consola)

    def asignar_caja(self,
                     indice_torre: int,
                     lat_origen: float,
                     lon_origen: float,
                     puerto_serial: str,
                     carr: int = 2):
        """Conecta la caja de interfaz Arduino a la torre intermedia indicada."""
        if not (1 <= indice_torre <= self.numero_tramos - 1):
            raise ValueError(
                f"indice_torre debe estar entre 1 y {self.numero_tramos - 1}"
            )
        self.caja_interfaz = CajaInterfaz(
            torre         = self.torres[indice_torre],
            lat_origen    = lat_origen,
            lon_origen    = lon_origen,
            puerto_serial = puerto_serial,
            carr          = carr,
        )

    def start(self):
        """Pone el lineal en marcha."""
        self._en_marcha = True

    def stop(self):
        """Detiene el lineal. El tiempo sigue corriendo pero ninguna torre avanza."""
        self._en_marcha = False
        self.guia_izquierda.contactor.abrir()
        self.guia_derecha.contactor.abrir()

    def invertir_direccion(self):
        """Alterna entre avance (norte) y marcha atrás (sur)."""
        self.direccion *= -1

    @property
    def en_marcha_atras(self) -> bool:
        """True cuando el lineal está en marcha atrás (dirección sur)"""
        return self.direccion == -1

    def set_speed(self, velocidad_porcentaje: float):
        """Cambia el duty cycle de ambas torres guía en % durante la simulación"""
        self.velocidad_porcentaje = max(0.0, min(100.0, velocidad_porcentaje))
        dc = self.velocidad_porcentaje / 100.0
        self.guia_izquierda.contactor.duty_cycle = dc
        self.guia_derecha.contactor.duty_cycle   = dc


    def avanza(self, segundos: int = 1, transmitir_gps: bool = True,
               modo_giro: str | None = None):
        """
        Avanza la simulación el número de segundos indicado.
        modo_giro None = operación normal. 'der' = Cart pivota, End-tower barre arco. 'izq' = al revés.
        transmitir_gps False cuando Streamlit usa el hilo GPS propio para no bloquear la UI.
        """
        for _ in range(segundos):
            self.tiempo_total_segundos += 1
            self._segundo_en_ciclo      = self.tiempo_total_segundos % self.DURACION_CICLO

            if self._segundo_en_ciclo == 0:
                self.ciclo_actual += 1
                self.motor_rapido_pct_on = self._mr_on_en_ciclo / self.DURACION_CICLO * 100.0
                self._mr_on_en_ciclo     = 0

            if not self._en_marcha:
                continue  # el tiempo pasa pero las torres no se mueven

            if modo_giro is None:
                # Operación normal: duty cycle en ambas guías
                self.guia_izquierda.contactor.actualizar_duty_cycle(
                    self._segundo_en_ciclo, self.DURACION_CICLO)
                self.guia_derecha.contactor.actualizar_duty_cycle(
                    self._segundo_en_ciclo, self.DURACION_CICLO)
                self.guia_izquierda.avanzar(1, self.direccion)
                self.guia_derecha.avanzar(1, self.direccion)
            
            elif modo_giro == 'izq':
                # Cart barre arco, End-tower es pivote fijo
                self.guia_izquierda.contactor.cerrar()
                self._avanzar_en_arco(self.guia_izquierda, self.guia_derecha, 1, self.direccion)
                self.guia_derecha.contactor.abrir()
            elif modo_giro == 'der':
                # End-tower barre arco, Cart es pivote fijo
                self.guia_derecha.contactor.cerrar()
                self._avanzar_en_arco(self.guia_derecha, self.guia_izquierda, 1, self.direccion)
                self.guia_izquierda.contactor.abrir()

            # Snapshot de posiciones Y para que todas las intermedias reaccionen al mismo instante
            snapshot_y = [t.posicion_y for t in self.torres]
            k = self.indice_tramo_rigido
            N = len(self.torres) - 1

            if modo_giro is None:
                # Cada intermedia compara con sus dos vecinos y sigue al más adelantado
                for i in range(1, N):
                    self.torres[i].seguir(snapshot_y[i - 1], snapshot_y[i + 1], 1, self.direccion)
            else:
                # En giro cada intermedia persigue su punto en la línea Cart→End-tower
                y0 = snapshot_y[0]
                yN = snapshot_y[N]
                for i in range(1, N):
                    y_obj = y0 + (yN - y0) * (i / N)
                    self.torres[i].seguir_arco(y_obj, 1, self.direccion)

            self._actualizar_posiciones_x()

            if self.torres[self.indice_torre_motor_rapido].contactor.esta_cerrado:
                self._mr_on_en_ciclo += 1

            if self.gps is not None and transmitir_gps:
                self.gps.transmitir()


    # Propiedades de estado
    @property
    def posicion_norte(self) -> float:
        """Posición media del lineal en el eje norte (metros)"""
        return sum(t.posicion_y for t in self.torres) / len(self.torres)

    @property
    def longitud_total(self) -> float:
        """Longitud total del lineal de extremo a extremo (metros)"""
        return self.numero_tramos * self.longitud_tramo

    @property
    def esta_alineado(self) -> bool:
        """True si todos los tramos están dentro de la tolerancia de alineación (5 cm)"""
        return all(t.esta_alineado for t in self.tramos)


    def estado(self):
        """Imprime un resumen detallado del estado actual del lineal"""
        vel_media    = self.velocidad_nominal * (self.velocidad_porcentaje / 100.0)
        alineado_txt = "Correcto" if self.esta_alineado else "Corrigiendo desviacion..."
        estado_txt   = "EN MARCHA" if self._en_marcha else "PARADO"

        print()
        print(f"  Sistema de Riego Lineal / Free Standing Span ")
        print(f"  Estado               : {estado_txt}")
        print(f"  Tiempo transcurrido  : {self._tiempo_formateado()}   Ciclo #{self.ciclo_actual}")
        print()
        print(f"  Configuracion del lineal")
        print(f"    Tramos             : {self.numero_tramos}  (longitud total: {self.longitud_total:.0f} m)")
        print(f"    Torres             : {len(self.torres)}  "
              f"(guia izq + {self.numero_tramos - 1} intermedias + guia der)")
        print(f"    Tramo rigido       : Tramo {self.indice_tramo_rigido + 1} (tramo central)")
        print(f"    Motor nominal      : {self.velocidad_nominal:.2f} m/min  (cualquier motor cuando esta ON)")
        print(f"    Duty cycle guias   : {self.velocidad_porcentaje:.0f}%  "
              f"->  {vel_media:.2f} m/min velocidad media")
        print()
        print(f"  Posicion y alineacion")
        print(f"    Posicion norte     : {self.posicion_norte:.2f} m")
        print(f"    Alineacion         : {alineado_txt}")
        print()
        print("  Torres")
        for i, torre in enumerate(self.torres):
            if i == 0:
                etiqueta = "Guia Izq (Cart)  "
            elif i == len(self.torres) - 1:
                etiqueta = "Guia Der         "
            elif i == self.indice_torre_motor_rapido:
                etiqueta = f"Intermedia {i} [++] "  # [++] = motor mas rapido
            else:
                etiqueta = f"Intermedia {i}      "
            print(f"    [{etiqueta}]  {torre}")
        print()
        print("  Tramos  (desviacion = diferencia en Y entre torre der e izq del tramo)")
        for i, tramo in enumerate(self.tramos, 1):
            print(f"    [Tramo {i}]  {tramo}")
        print()
        if self.gps is not None:
            print("  GPS")
            print(f"    {self.gps}")
            print()

    def _actualizar_posiciones_x(self):
        """
        Recalcula la X de cada torre manteniendo √(dx²+dy²) = longitud del tramo.
        Cascada izquierda: propagada desde el Cart hacia el centro.
        Cascada derecha: propagada desde el End-tower hacia el centro.
        Tramo rígido: cuerpo rígido, su centro se promedia entre ambas cascadas.
        """
        k = self.indice_tramo_rigido
        N = len(self.torres) - 1

        def _dx(t_izq, t_der):
            # Componente X de un tramo manteniendo su longitud física
            L  = t_izq.longitud_tramo
            dy = t_der.posicion_y - t_izq.posicion_y
            return math.sqrt(max(0.0, L * L - dy * dy))

        # Cascada izquierda: torres 1..k-1
        for i in range(1, k):
            t_izq = self.torres[i - 1]
            t     = self.torres[i]
            t.posicion_x = t_izq.posicion_x + _dx(t_izq, t)

        # Cascada derecha: torres k+2..N-1
        for i in range(N - 1, k + 1, -1):
            t     = self.torres[i]
            t_der = self.torres[i + 1]
            t.posicion_x = t_der.posicion_x - _dx(t, t_der)

        # Tramo rígido: centrar entre la estimación izquierda y derecha
        t_km1 = self.torres[k - 1]
        t_k   = self.torres[k]
        t_k1  = self.torres[k + 1]
        t_k2  = self.torres[k + 2]
        x_k_izq  = t_km1.posicion_x + _dx(t_km1, t_k)
        x_k1_der = t_k2.posicion_x  - _dx(t_k1, t_k2)
        dx_fss   = _dx(t_k, t_k1)
        x_centro = (x_k_izq + x_k1_der) / 2.0
        t_k.posicion_x  = x_centro - dx_fss / 2.0
        t_k1.posicion_x = x_centro + dx_fss / 2.0

    def _avanzar_en_arco(self, guia_libre: "Torre_Guia", guia_pivote: "Torre_Guia",
                        segundos: float, direccion: int = 1) -> float:
        """
        Mueve la guía libre en arco alrededor del pivote (actualiza X e Y).
        El sentido de rotación se elige para que Y suba (avance) o baje (marcha atrás).
        Devuelve los metros de arco recorridos.
        """
        x0 = guia_pivote.posicion_x
        y0 = guia_pivote.posicion_y

        dx = guia_libre.posicion_x - x0
        dy = guia_libre.posicion_y - y0
        R  = math.sqrt(dx * dx + dy * dy)

        if R < 1.0:          # caso deguías superpuestas
            return 0.0

        factor_patinaje = 1.0 - (guia_libre.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        arc_len = guia_libre.velocidad_nominal * (segundos / 60.0) * factor_patinaje

        current_angle = math.atan2(dy, dx)
        delta_angle   = arc_len / R

        # Sentido angular para que la Y se mueva en la dirección correcta:
        # avance  + OESTE → clockwise (restar)   avance  + ESTE → CCW (sumar)
        # atrás   + OESTE → CCW (sumar)          atrás   + ESTE → clockwise (restar)
        # Equivale a: restar si (dx<0) XOR (marcha atrás)
        if (guia_libre.posicion_x < x0) == (direccion == 1):
            new_angle = current_angle - delta_angle
        else:
            new_angle = current_angle + delta_angle

        # Ruido lateral del terreno como perturbación angular
        if guia_libre.ruido_lateral > 0.0 and arc_len > 0.0:
            new_angle += random.gauss(0.0, guia_libre.ruido_lateral * arc_len / R)

        new_x = x0 + R * math.cos(new_angle)
        new_y = y0 + R * math.sin(new_angle)

        # Detener si el arco cruzó el límite: Y no puede moverse en contra de la dirección
        if (new_y - guia_libre.posicion_y) * direccion <= 0:
            return 0.0

        guia_libre.posicion_x = new_x
        guia_libre.posicion_y = new_y
        return arc_len

    def resetear_arco_giro(self):
        """Alinea las intermedias sobre la línea Cart→End-tower antes de iniciar un giro."""
        N  = len(self.torres) - 1
        y0 = self.torres[0].posicion_y
        yN = self.torres[N].posicion_y
        for i in range(1, N):
            self.torres[i].posicion_y = y0 + (yN - y0) * (i / N)
            self.torres[i].contactor.abrir()
        self._actualizar_posiciones_x()

    def _tiempo_formateado(self) -> str:
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"

    def __repr__(self):
        return (f"Lineal(tramos={self.numero_tramos},"
                f" longitud_tramo={self.longitud_tramo}m,"
                f" duty={self.velocidad_porcentaje}%,"
                f" nominal={self.velocidad_nominal}m/min)")
