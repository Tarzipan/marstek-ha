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
