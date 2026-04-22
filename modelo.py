import math, random, threading, time as _time

def avanzar_en_circunferencia(centro_x, centro_y, radio, inicio_x, inicio_y, distancia):
    """
    Posición final de un móvil que recorre una distancia sobre una circunferencia.
    distancia > 0 = sentido antihorario, distancia < 0 = sentido horario
    """
    angulo_inicial   = math.atan2(inicio_y - centro_y, inicio_x - centro_x)
    angulo_recorrido = distancia / radio
    angulo_final     = angulo_inicial + angulo_recorrido

    x_final = centro_x + radio * math.cos(angulo_final)
    y_final  = centro_y + radio * math.sin(angulo_final)

    return x_final, y_final

try:
    import serial as _serial_module
    _SERIAL_DISPONIBLE = True
except ImportError:
    _SERIAL_DISPONIBLE = False

# Constante geográfica
METROS_POR_GRADO_LAT = 111_320.0  # 1 grado de latitud ≈ 111 320 m


# Conecta/desconecta el motor de una torre
# Torres guía: modo duty cycle (ciclos ON/OFF de 60 s para controlar la velocidad media)
# Torres intermedias: indicador de alineación (ON = desalineada, OFF = alineada)
class Contactor:

    CERRADO = "CERRADO" # motor ON
    ABIERTO = "ABIERTO" # motor OFF

    def __init__(self, velocidad_porcentaje: float = 0.0):
        """velocidad_porcentaje: duty cycle en % (solo relevante en torres guía)"""
        self.duty_cycle = velocidad_porcentaje / 100.0
        self.estado     = self.ABIERTO

    def actualizar_duty_cycle(self, segundo_en_ciclo: int, duracion_ciclo: int = 60):
        """cierra o abre el contactor según el segundo actual dentro del ciclo (duty cycle)"""
        tiempo_activo = self.duty_cycle * duracion_ciclo
        self.estado   = self.CERRADO if segundo_en_ciclo < tiempo_activo else self.ABIERTO

    def cerrar(self):
        self.estado = self.CERRADO

    def abrir(self):
        self.estado = self.ABIERTO

    @property
    def esta_cerrado(self) -> bool:
        return self.estado == self.CERRADO


# Una torre del lineal: posición (x, y), longitud del tramo al siguiente, velocidad nominal (m/min) y porcentaje de patinaje aleatorio
class Torre:

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0):
        
        self.posicion_x = posicion_x
        self.posicion_y = posicion_y
        self.longitud_tramo = longitud_tramo
        self.velocidad_nominal = velocidad_nominal
        self.porcentaje_patinaje = random.uniform(0.0, 5.0)  # única por torre

    def avanzar(self, segundos: float, direccion: int = 1) -> float:
        """
        Mueve la torre durante "segundos" a velocidad nominal
        direccion =  1: hacia el norte (avance normal)
        direccion = -1: hacia el sur (marcha atrás)
        El patinaje reduce ligeramente la velocidad según el terreno (0-5% aleatorio por torre)
        Devuelve los metros recorridos (positivo siempre, el signo lo da direccion)
        """
        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = self.velocidad_nominal * (segundos / 60.0) * factor_patinaje
        self.posicion_y += metros_avanzados * direccion
        return metros_avanzados

# Torres de los extremos: Cart (izquierda) y End-tower (derecha)
# Las únicas con contactor de duty cycle: su ciclo ON/OFF marca el ritmo de avance
# En modo slow_down abandonan el duty cycle y copian el ON/OFF del motor rápido
class Torre_Guia(Torre):

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 velocidad_porcentaje: float = 50.0,
                 ruido_lateral: float = 0.0):
        
        # RUIDO LATERAL: deriva lateral aleatoria por metro avanzado (0=perfecto, 0.070=loco)
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor = Contactor(velocidad_porcentaje)
        self.ruido_lateral = ruido_lateral

    def avanzar(self, segundos: float, direccion: int = 1) -> float:
        """
        Avanza o retrocede si el contactor está cerrado
        Aplica ruido lateral del terreno
        """
        if self.contactor.esta_cerrado:
            metros = super().avanzar(segundos, direccion)
            if self.ruido_lateral > 0.0 and metros > 0.0:
                self.posicion_x += random.gauss(0.0, self.ruido_lateral * metros)
            return metros
        return 0.0


# Torres intermedias: contactor de alineación ON/OFF (sin duty cycle)
# ON = desalineada, motor activo recuperando posición, y OFF = alineada, motor parado
# La del extremo derecho del tramo rígido tiene motor más rápido (cubre más ángulo en el mismo tiempo)
class Torre_Intermedia(Torre):

    FACTOR_SOBREVELOCIDAD = 1.5 # motor intermedio normal: ×1.5 la velocidad nominal
    FACTOR_SOBREVELOCIDAD_RAPIDA = 2.0 # motor rápido ×2.0
    UMBRAL_ARRANQUE = 0.10 # retraso mínimo para activar motor
    UMBRAL_ADELANTO = 0.10 # adelanto máximo antes de apagar motor

    def __init__(self, posicion_x: float, posicion_y: float,
                 longitud_tramo: float, velocidad_nominal: float = 3.0,
                 es_motor_rapido: bool = False):
        
        # es_motor_rapido: True solo para la torre del extremo derecho del tramo rígido
        super().__init__(posicion_x, posicion_y, longitud_tramo, velocidad_nominal)
        self.contactor = Contactor()   # contactor de alineación (sin duty cycle)
        self.es_motor_rapido = es_motor_rapido

    @property
    def factor_sobrevelocidad(self) -> float:
        return (self.FACTOR_SOBREVELOCIDAD_RAPIDA
                if self.es_motor_rapido
                else self.FACTOR_SOBREVELOCIDAD)

    def seguir(self, y_objetivo: float, segundos: float,
               direccion: int = 1,
               pivot_x: float = None, pivot_y: float = None) -> float:
        """
        Activa cuando está ≥10 cm por detrás del objetivo (y_objetivo)
        Avanza a velocidad nominal completa y para cuando supera el objetivo en ≥10 cm
        Si se pasan pivot_x/pivot_y, la torre avanza sobre el arco de circunferencia centrado en el pivote radio = longitud_tramo
        """
        desviacion = (y_objetivo - self.posicion_y) * direccion  # + atrasada, - adelantada

        if desviacion >= self.UMBRAL_ARRANQUE:
            self.contactor.cerrar()
        elif desviacion <= -self.UMBRAL_ADELANTO:
            self.contactor.abrir()

        if not self.contactor.esta_cerrado:
            return 0.0

        factor_patinaje  = 1.0 - (self.porcentaje_patinaje / 100.0) * random.uniform(0.5, 1.0)
        metros_avanzados = (self.velocidad_nominal * self.factor_sobrevelocidad * (segundos / 60.0) * factor_patinaje)

        if pivot_x is not None and pivot_y is not None:
            # Lado izquierdo: torre a la DERECHA del pivote = antihorario = norte = distancia positiva
            # Lado derecho: torre a la IZQUIERDA del pivote = horario = norte = distancia negativa
            signo_avance   = 1 if self.posicion_x > pivot_x else -1
            distancia_arco = metros_avanzados * direccion * signo_avance
            self.posicion_x, self.posicion_y = avanzar_en_circunferencia(
                pivot_x, pivot_y, self.longitud_tramo,
                self.posicion_x, self.posicion_y, distancia_arco
            )
        else:
            self.posicion_y += metros_avanzados * direccion

        return metros_avanzados


# Segmento entre dos torres
# Mide su ángulo e inclinación (0° = perfectamente alineado)
# El tramo rígido central (Free Standing Span) no puede doblarse, sus torres se mueven como un bloque
class Tramo:

    TOLERANCIA_ALINEACION = 0.05  # diferencia máxima para considerarse alineado (metros)

    def __init__(self, torre_izquierda: Torre, torre_derecha: Torre,
                 es_rigido: bool = False):
        
        self.torre_izquierda = torre_izquierda
        self.torre_derecha = torre_derecha
        self.es_rigido = es_rigido

    @property
    def longitud_horizontal(self) -> float:
        """Distancia fija en X entre las dos torres del tramo"""
        return abs(self.torre_derecha.posicion_x - self.torre_izquierda.posicion_x)

    @property
    def desviacion_norte(self) -> float:
        """Diferencia en Y entre torre derecha e izquierda (0 = alineado)"""
        return self.torre_derecha.posicion_y - self.torre_izquierda.posicion_y

    @property
    def angulo_grados(self) -> float:
        """Ángulo de inclinación del tramo respecto al eje horizontal"""
        if self.longitud_horizontal == 0:
            return 0.0
        return math.degrees(math.atan2(self.desviacion_norte, self.longitud_horizontal))

    @property
    def esta_alineado(self) -> bool:
        """True si la desviación está dentro de la tolerancia para considerarse alineado"""
        return abs(self.desviacion_norte) < self.TOLERANCIA_ALINEACION


# GPS virtual asignado a una Torre_Intermedia
# Convierte X/Y (metros) a lat/lon reales usando el Cart como origen geográfico
# Emite coordenadas como enteros ×10⁷ por puerto serie cada segundo
# Sin puerto configurado puede imprimir por consola para depuración
class GPS:

    def __init__(self,
                 torre: "Torre_Intermedia",
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
            mensaje = f"LAT:{self.lat_e7},LON:{self.lon_e7}\n"
            if conexion is not None:
                try:
                    conexion.write(mensaje.encode("utf-8"))
                    conexion.flush()
                except Exception as e:
                    print(f"Error en transmisión: {e}")
                    break
            if self.verbose_consola:
                print(f"GPS {mensaje.strip()}  ({self.latitud:.7f}°, {self.longitud:.7f}°)")
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
                 torre,
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
        self._hilo   = threading.Thread(target=self._bucle, daemon=True)
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
                trama = f"Lat {self.lat_e7} Lon {self.lon_e7} Carr {self.carr}\n"
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


# Orquestador del lineal con Free Standing Span
# Gestiona guías (duty cycle o slow_down), intermedias (alineación) y tramo rígido central
class Lineal:
    DURACION_CICLO = 60  # segundos por ciclo de duty cycle de las torres guía

    def __init__(self,
                 numero_tramos: int = 5,
                 longitud_tramo: float = 50.0,
                 velocidad_porcentaje: float = 50.0,
                 velocidad_nominal: float = 3.0,
                 ruido_lateral: float = 0.0):
        
        if numero_tramos < 3:
            raise ValueError(
                "El lineal Free Standing Span necesita mínimo 3 tramos"
            )

        self.numero_tramos = numero_tramos
        self.longitud_tramo = longitud_tramo       
        self.velocidad_porcentaje = velocidad_porcentaje
        self.velocidad_nominal = velocidad_nominal

        # Tramo rígido es el tramo central del lineal
        self.indice_tramo_rigido = numero_tramos // 2

        # Torre más rápida: extremo derecho del tramo rígido
        self.indice_torre_motor_rapido = self.indice_tramo_rigido + 1

        self.torres = []

        self.torres.append(Torre_Guia(
            posicion_x = 0.0,
            posicion_y = 0.0,
            longitud_tramo = longitud_tramo,
            velocidad_nominal = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral = ruido_lateral,
        ))

        for i in range(1, numero_tramos):
            es_rapida = (i == self.indice_torre_motor_rapido)
            self.torres.append(Torre_Intermedia(
                posicion_x = longitud_tramo * i,
                posicion_y = 0.0,
                longitud_tramo = longitud_tramo,
                velocidad_nominal = velocidad_nominal,
                es_motor_rapido = es_rapida
            ))

        self.torres.append(Torre_Guia(
            posicion_x = longitud_tramo * numero_tramos,
            posicion_y = 0.0,
            longitud_tramo = longitud_tramo,
            velocidad_nominal = velocidad_nominal,
            velocidad_porcentaje = velocidad_porcentaje,
            ruido_lateral = ruido_lateral,
        ))

        # Crear tramos
        self.tramos = []
        for i in range(numero_tramos):
            es_rigido = (i == self.indice_tramo_rigido)
            self.tramos.append(Tramo(self.torres[i], self.torres[i + 1], es_rigido=es_rigido))

        self.guia_izquierda = self.torres[0] # Cart: extremo izquierdo
        self.guia_derecha = self.torres[-1] # End-tower: extremo derecho

        # Contadores de tiempo y ciclos para simular el duty cycle de las torres guía
        self.tiempo_total_segundos = 0
        self.ciclo_actual = 0
        self._segundo_en_ciclo = 0
        self._en_marcha = False # el lineal comienza parado

        self._segundos_motor_rapido_on = 0 # segundos ON del motor rápido en el ciclo actual
        self.motor_rapido_pct_on = 0.0 # % ON del motor rápido en el último ciclo completo

        # Dirección de marcha:  1 = avance (norte), -1 = marcha atrás (sur)
        self.direccion: int = 1

        # Ralentización activa: True = ese extremo sigue al motor rápido en vez de su duty cycle
        self.slow_down_cart: bool = False
        self.slow_down_end_tower: bool = False

        # GPS y caja de interfaz (se asignan después con asignar_gps() / asignar_caja())
        self.gps: GPS | None = None
        self.caja_interfaz: CajaInterfaz | None = None


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
            torre = self.torres[indice_torre],
            lat_origen = lat_origen,
            lon_origen = lon_origen,
            puerto_serial = puerto_serial,
            carr = carr,
        )

    def start(self):
        """Pone el lineal en marcha"""
        self._en_marcha = True

    def stop(self):
        """Detiene el lineal. El tiempo sigue corriendo pero ninguna torre avanza"""
        self._en_marcha = False
        self.guia_izquierda.contactor.abrir()
        self.guia_derecha.contactor.abrir()

    def invertir_direccion(self):
        """Alterna entre avance (norte) y marcha atrás (sur)"""
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

    def avanza(self, segundos: int = 1):
        """Avanza la simulación el número de segundos indicado"""
        for _ in range(segundos):
            self.tiempo_total_segundos += 1
            self._segundo_en_ciclo = self.tiempo_total_segundos % self.DURACION_CICLO

            if self._segundo_en_ciclo == 0:
                self.ciclo_actual += 1
                self.motor_rapido_pct_on = self._segundos_motor_rapido_on / self.DURACION_CICLO * 100.0
                self._segundos_motor_rapido_on = 0

            if not self._en_marcha:
                continue # el tiempo pasa pero las torres no se mueven

            # Leer estado de ralentización
            _slow_cart = self.slow_down_cart
            _slow_end  = self.slow_down_end_tower

            # Duty cycle normal para las guías
            self.guia_izquierda.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)
            self.guia_derecha.contactor.actualizar_duty_cycle(
                self._segundo_en_ciclo, self.DURACION_CICLO)

            # Torre rápida: su contactor marca el ritmo del motor en modo slow_down
            torre_rapida = self.torres[self.indice_torre_motor_rapido]

            if _slow_cart and not _slow_end:
                # SLOW_DOWN_CART: Cart copia el ON/OFF del motor rápido
                if torre_rapida.contactor.esta_cerrado:
                    self.guia_izquierda.contactor.cerrar()
                else:
                    self.guia_izquierda.contactor.abrir()
                self.guia_izquierda.avanzar(1, self.direccion)
                self.guia_derecha.avanzar(1, self.direccion)

            elif _slow_end and not _slow_cart:
                # SLOW_DOWN_END_TOWER: End-tower copia el ON/OFF del motor rápido
                if torre_rapida.contactor.esta_cerrado:
                    self.guia_derecha.contactor.cerrar()
                else:
                    self.guia_derecha.contactor.abrir()
                self.guia_derecha.avanzar(1, self.direccion)
                self.guia_izquierda.avanzar(1, self.direccion)

            else:
                # Sin slow_down activo: avance normal por duty cycle
                self.guia_izquierda.avanzar(1, self.direccion)
                self.guia_derecha.avanzar(1, self.direccion)

            # Cada intermedia sigue su posición ideal en la diagonal Cart→End-tower
            # (interpolación lineal) avanzando sobre un arco de circunferencia centrado
            # en la torre vecina ya actualizada → posición (x, y) físicamente correcta.
            y_cart = self.torres[0].posicion_y
            y_end = self.torres[-1].posicion_y
            numero_intervalos = len(self.torres) - 1
            indice_rigido = self.indice_tramo_rigido

            # Lado izquierdo: torres 1..indice_rigido, pivote = vecino izquierdo ya actualizado
            for i in range(1, indice_rigido + 1):
                torre_pivote = self.torres[i - 1]
                y_objetivo   = y_cart + (y_end - y_cart) * i / numero_intervalos
                self.torres[i].seguir(y_objetivo, 1, self.direccion, torre_pivote.posicion_x, torre_pivote.posicion_y)

            # Lado derecho: torres (N-1)..indice_rigido+1, pivote = vecino derecho ya actualizado
            for i in range(numero_intervalos - 1, indice_rigido, -1):
                torre_pivote = self.torres[i + 1]
                y_objetivo   = y_cart + (y_end - y_cart) * i / numero_intervalos
                self.torres[i].seguir(y_objetivo, 1, self.direccion, torre_pivote.posicion_x, torre_pivote.posicion_y)

            self._actualizar_fss()

            if self.torres[self.indice_torre_motor_rapido].contactor.esta_cerrado:
                self._segundos_motor_rapido_on += 1


    # Propiedades de estado
    @property
    def posicion_norte(self) -> float:
        """Posición media del lineal en el eje norte"""
        return sum(t.posicion_y for t in self.torres) / len(self.torres)

    @property
    def longitud_total(self) -> float:
        """Longitud total del lineal de extremo a extremo"""
        return self.numero_tramos * self.longitud_tramo

    @property
    def esta_alineado(self) -> bool:
        """True si todos los tramos están dentro de la tolerancia de alineación"""
        return all(t.esta_alineado for t in self.tramos)


    def _actualizar_fss(self):
        """
        Corrige el tramo rígido central (FSS):
        promedia las posiciones que fijaron los dos lados y recoloca ambas torres del FSS de forma horizontal (dy=0),
        manteniendo la distancia = longitud_tramo
        """
        indice_rigido      = self.indice_tramo_rigido
        torre_izquierda_fss = self.torres[indice_rigido]
        torre_derecha_fss   = self.torres[indice_rigido + 1]

        x_centro = (torre_izquierda_fss.posicion_x + torre_derecha_fss.posicion_x) / 2.0
        y_centro = (torre_izquierda_fss.posicion_y + torre_derecha_fss.posicion_y) / 2.0

        torre_izquierda_fss.posicion_x = x_centro - self.longitud_tramo / 2.0
        torre_derecha_fss.posicion_x   = x_centro + self.longitud_tramo / 2.0
        torre_izquierda_fss.posicion_y = y_centro
        torre_derecha_fss.posicion_y   = y_centro

    def _tiempo_formateado(self) -> str:
        """Devuelve el tiempo total transcurrido en formato Hh Mm Ss"""
        h = self.tiempo_total_segundos // 3600
        m = (self.tiempo_total_segundos % 3600) // 60
        s = self.tiempo_total_segundos % 60
        return f"{h:02d}h {m:02d}m {s:02d}s"
    