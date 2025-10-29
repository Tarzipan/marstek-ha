"""Constants for the Marstek integration."""

DOMAIN = "marstek_ha"

# Configuration
CONF_DEVICE_IP = "device_ip"
CONF_DEVICE_PORT = "device_port"

# Defaults
DEFAULT_PORT = 30000  # UDP port for API communication
DEFAULT_SCAN_INTERVAL = 30
DEFAULT_TIMEOUT = 3

# API Commands
CMD_GET_DEVICE = "Marstek.GetDevice"
CMD_WIFI_STATUS = "Wifi.GetStatus"
CMD_BLE_STATUS = "BLE.GetStatus"
CMD_BAT_STATUS = "Bat.GetStatus"
CMD_PV_STATUS = "PV.GetStatus"
CMD_ES_STATUS = "ES.GetStatus"
CMD_ES_SET_MODE = "ES.SetMode"
CMD_ES_GET_MODE = "ES.GetMode"

# ES Modes (based on API documentation)
# Supported modes for ES.SetMode command
ES_MODE_AUTO = "Auto"
ES_MODE_AI = "AI"
ES_MODE_MANUAL = "Manual"
ES_MODE_PASSIVE = "Passive"

ES_MODES = [
    ES_MODE_AUTO,
    ES_MODE_AI,
    ES_MODE_MANUAL,
    ES_MODE_PASSIVE,
]

# Sensor Types
SENSOR_BATTERY_SOC = "battery_soc"
SENSOR_BATTERY_VOLTAGE = "battery_voltage"
SENSOR_BATTERY_CURRENT = "battery_current"
SENSOR_BATTERY_POWER = "battery_power"
SENSOR_BATTERY_TEMP = "battery_temp"
SENSOR_PV_VOLTAGE = "pv_voltage"
SENSOR_PV_CURRENT = "pv_current"
SENSOR_PV_POWER = "pv_power"
SENSOR_ES_POWER = "es_power"
SENSOR_ES_ENERGY_TODAY = "es_energy_today"
SENSOR_ES_ENERGY_TOTAL = "es_energy_total"
SENSOR_GRID_POWER = "grid_power"
SENSOR_LOAD_POWER = "load_power"
SENSOR_WIFI_RSSI = "wifi_rssi"

