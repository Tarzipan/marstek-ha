"""Constants for the Marstek integration."""

DOMAIN = "marstek_ha"

# Configuration
CONF_DEVICE_IP = "device_ip"
CONF_DEVICE_PORT = "device_port"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_MIN_WRITE_INTERVAL = "min_write_interval"
CONF_MODBUS_ENABLED = "modbus_enabled"
CONF_MODBUS_PORT = "modbus_port"
CONF_MODBUS_UNIT_ID = "modbus_unit_id"

# Defaults
DEFAULT_PORT = 30000  # UDP port the device listens on for API requests
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_TIMEOUT = 3.0

# Polling interval bounds (seconds). Below ~5s the device starts dropping
# requests; above 60s the power sensors become useless for load balancing.
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 300

# Minimum seconds between two ES.SetMode writes. The Passive fallback path
# (see MODE_PASSIVE below) re-sends a setpoint every few seconds; this floor
# keeps a misbehaving automation from flooding the device.
DEFAULT_MIN_WRITE_INTERVAL = 5
MIN_WRITE_INTERVAL_MIN = 0
MIN_WRITE_INTERVAL_MAX = 60

# Number of consecutive complete polling failures tolerated before entities are
# marked unavailable. UDP is connectionless: single lost datagrams are normal.
MAX_CONSECUTIVE_FAILURES = 3

# Consecutive polls a binary flag must report the same *new* value before that
# value is published. A flag is a latched summary of hardware state, so it does
# not genuinely toggle between two ten-second polls; a lone deviating reading is
# noise. Measured on a Venus E 3.0 with a CT: ct_state produced 135 spurious
# 0-readings in twelve hours, the overwhelming majority lasting exactly one poll
# cycle, while the CT stayed physically connected throughout.
#
# Deliberately debounces the *value*, not just an unanswered request: the
# coordinator already carries a missing endpoint forward (see
# MarstekDataUpdateCoordinator._async_update_data), so a lost datagram cannot
# flip a flag in the first place -- the spurious readings arrive in otherwise
# valid responses, and only a value-level filter catches them.
BINARY_FLAG_DEBOUNCE = 3

# Per-request retransmissions (UDP has no delivery guarantee).
REQUEST_RETRIES = 2

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

# Keys used for the coordinator data dict.
DATA_DEVICE = "device"
DATA_BATTERY = "battery"
DATA_ES_MODE = "es_mode"
DATA_ES_STATUS = "es_status"
DATA_EM_STATUS = "em_status"
DATA_WIFI = "wifi"

# ES Modes (Open API Rev 3.1)
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

# --- Passive mode ---------------------------------------------------------
#
# SIGN CONVENTION -- NOT YET VERIFIED AGAINST HARDWARE.
#
# The Open API Rev 3.1 document does not state the sign of passive_cfg.power
# unambiguously. This integration assumes, consistently everywhere:
#
#     power > 0  ->  DISCHARGE (battery feeds the house / grid)
#     power < 0  ->  CHARGE    (battery draws from the grid)
#
# which matches the sign of ES.GetStatus.ongrid_power on Venus E v3.
#
# If testing shows the device behaves the opposite way, flip PASSIVE_POWER_SIGN
# to -1 below. That single constant is the only place the convention is applied
# (see MarstekAPI.set_passive_power), so no other code needs to change.
PASSIVE_POWER_SIGN = 1

# Passive setpoint bounds in watts. Venus E 3.0 is rated 2500 W both ways;
# the device clamps out-of-range values itself, these bounds are for the UI.
PASSIVE_POWER_MIN = -2500
PASSIVE_POWER_MAX = 2500
PASSIVE_POWER_DEFAULT = 0

# Countdown in seconds after which the device leaves Passive mode on its own.
# This is the watchdog: if Home Assistant stops sending setpoints, the device
# falls back by itself. Never build a separate heartbeat -- use this instead.
# 0 means "no countdown" per the API, which we deliberately do not default to.
PASSIVE_CD_TIME_MIN = 0
PASSIVE_CD_TIME_MAX = 86400
PASSIVE_CD_TIME_DEFAULT = 300

# DOD (Depth of Discharge) limits
DOD_MIN = 30
DOD_MAX = 88
DOD_DEFAULT = 88

# --- Modbus TCP side channel ---------------------------------------------
#
# The Open API (Rev 3.1) exposes no command for a charge or discharge power
# LIMIT -- ES.SetMode only sets a Passive *setpoint*, which is an operating
# point, not a ceiling, and using it would take the device out of Auto mode and
# thereby disable its own second-by-second CT regulation. The same devices do
# expose the limits over Modbus TCP as holding registers, so the integration
# writes them there and keeps everything else on UDP.
#
# HANDLE WITH CARE. The Venus Modbus server accepts only ONE session and has
# been observed to lock up under frequent access, recoverable only by power
# cycling the device. Everything in modbus.py follows from that:
#
#   * connect -> write -> disconnect, every time; the socket is never held open
#   * no polling; the registers are read exactly once per config entry load
#   * a minimum interval between connections, enforced by rejecting rather than
#     queueing, so a runaway automation cannot build up a backlog
#   * no retry on timeout: re-poking a server that has stopped answering is how
#     it gets wedged
#
# It also means no second Modbus client may talk to the same device. Running
# another Marstek Modbus integration alongside this one will break both.
MODBUS_DEFAULT_PORT = 502
MODBUS_DEFAULT_UNIT_ID = 1
MODBUS_TIMEOUT = 5.0

# Holding registers. Verified against Venus E v3; both are plain uint16 in
# watts with no scaling factor.
MODBUS_REG_MAX_CHARGE_POWER = 44002
MODBUS_REG_MAX_DISCHARGE_POWER = 44003

# Venus E 3.0 is rated 2500 W in both directions. Step 50 mirrors the
# granularity the device's own app offers.
MODBUS_POWER_MIN = 0
MODBUS_POWER_MAX = 2500
MODBUS_POWER_STEP = 50

# Minimum seconds between two Modbus connections to one device. The intended
# usage is a handful of writes per day (for example 0 W overnight, 2500 W once
# PV is producing), so a full minute costs nothing and bounds the load on a
# server that is known to be fragile.
MODBUS_MIN_WRITE_INTERVAL = 60

# Services
SERVICE_SET_PASSIVE_POWER = "set_passive_power"
ATTR_POWER = "power"
ATTR_CD_TIME = "cd_time"
