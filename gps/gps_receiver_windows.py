"""
Monitor serie para Windows.

Sirve para dos setups distintos:

  SETUP A — GPS directo (sin Arduino, cable USB cruzado a otro PC):
      python gps_receiver_windows.py COM4 9600
      Formato recibido: LAT:415191807,LON:-47151090

  SETUP B — Caja de interfaz Arduino:
      python gps_receiver_windows.py COM4 115200
      Formato recibido: Lat 415191807 Lon -47151090 Carr 2   (PC → Arduino)
                        SLOW_DOWN_CART_ON / SAFETY_OK / ...  (Arduino → PC)

Para listar los puertos:
    python -c "import serial.tools.list_ports; [print(p) for p in serial.tools.list_ports.comports()]"

Requisito:
    pip install pyserial
"""

import serial
import sys

PUERTO   = sys.argv[1] if len(sys.argv) > 1 else "COM4"
BAUDRATE = int(sys.argv[2]) if len(sys.argv) > 2 else 9600


def parsear(linea: str):
    """
    Intenta interpretar la línea como trama GPS.
    Soporta dos formatos:
      - "LAT:415191807,LON:-47151090"        (GPS class, Setup A)
      - "Lat 415191807 Lon -47151090 Carr 2" (CajaInterfaz, Setup B)
    Devuelve (lat, lon, carr_o_None) o None si no es GPS.
    """
    linea = linea.strip()

    # Formato nuevo: "Lat xxx Lon xxx Carr x"
    partes = linea.split()
    if len(partes) == 6 and partes[0] == "Lat" and partes[2] == "Lon" and partes[4] == "Carr":
        try:
            return int(partes[1]) / 1e7, int(partes[3]) / 1e7, int(partes[5])
        except ValueError:
            pass

    # Formato antiguo: "LAT:xxx,LON:xxx"
    if "LAT:" in linea and "LON:" in linea:
        try:
            campos = dict(p.split(":") for p in linea.split(","))
            return int(campos["LAT"]) / 1e7, int(campos["LON"]) / 1e7, None
        except Exception:
            pass

    return None


_CARR_DESC = {0: "sin RTK", 1: "RTK float", 2: "RTK FIX"}


def main():
    print(f"Abriendo {PUERTO} a {BAUDRATE} baudios...")
    try:
        ser = serial.Serial(PUERTO, BAUDRATE, timeout=2,
                            rtscts=False, dsrdtr=False, xonxoff=False)
    except serial.SerialException as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Conectado. Esperando datos...\n")
    print(f"{'Tipo':<12}  {'Contenido'}")
    print("-" * 70)

    try:
        while True:
            linea = ser.readline().decode("utf-8", errors="replace").strip()
            if not linea:
                continue

            gps = parsear(linea)
            if gps:
                lat, lon, carr = gps
                carr_txt = f"  [{_CARR_DESC[carr]}]" if carr is not None else ""
                print(f"{'GPS':<12}  {lat:>13.7f}°  {lon:>13.7f}°{carr_txt}")
            else:
                print(f"{'Arduino →':<12}  {linea}")
    except KeyboardInterrupt:
        print("\nDetenido.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
