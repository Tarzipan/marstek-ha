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
CMD_EM_STATUS = "EM.GetStatus"
CMD_DOD_SET = "DOD.SET"
CMD_BLE_ADV = "Ble.Adv"
CMD_LED_CTRL = "Led.Ctrl"

# ES Modes (based on API Rev 2.0)
ES_MODE_AUTO = "Auto"
ES_MODE_AI = "AI"
ES_MODE_MANUAL = "Manual"
ES_MODE_PASSIVE = "Passive"
ES_MODE_UPS = "UPS"

ES_MODES = [
    ES_MODE_AUTO,
    ES_MODE_AI,
    ES_MODE_MANUAL,
    ES_MODE_PASSIVE,
    ES_MODE_UPS,
]

# DOD (Depth of Discharge) limits
DOD_MIN = 30
DOD_MAX = 88
DOD_DEFAULT = 88
