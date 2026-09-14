"""API constants for the Mercedes-Benz mobile SDK (unofficial, read-only).

Facts verified against ReneNulschDE/mbapi2020 (MIT) as of 2026-09:
- OAuth2: id.mercedes-benz.com (EU/NA/APAC), ciam-1.mercedes-benz.com.cn (CN)
- Token endpoint /as/token.oauth2, refresh_token grant supported
- REST BFF: bff.<env>-prod.mobilesdk.mercedes-benz.com  (v2/vehicles etc.)
- Widget (protobuf VEPUpdate): widget.<env>-prod.mobilesdk.mercedes-benz.com
- Attributes map keys: stateofcharge, rangeelectric, chargingactive, ...
"""

from __future__ import annotations

REGIONS = ("eu", "na", "apac", "cn")

LOGIN_APP_ID = {
    "eu": "62778dc4-1de3-44f4-af95-115f06a3a008",
    "na": "62778dc4-1de3-44f4-af95-115f06a3a008",
    "apac": "62778dc4-1de3-44f4-af95-115f06a3a008",
    "cn": "3f36efb1-f84b-4402-b5a2-68a118fec33e",
}

LOGIN_BASE_URL = {
    "eu": "https://id.mercedes-benz.com",
    "na": "https://id.mercedes-benz.com",
    "apac": "https://id.mercedes-benz.com",
    "cn": "https://ciam-1.mercedes-benz.com.cn",
}

REST_API_BASE = {
    "eu": "https://bff.emea-prod.mobilesdk.mercedes-benz.com",
    "na": "https://bff.amap-prod.mobilesdk.mercedes-benz.com",
    "apac": "https://bff.amap-prod.mobilesdk.mercedes-benz.com",
    "cn": "https://bff.cn-prod.mobilesdk.mercedes-benz.com",
}

WIDGET_API_BASE = {
    "eu": "https://widget.emea-prod.mobilesdk.mercedes-benz.com",
    "na": "https://widget.amap-prod.mobilesdk.mercedes-benz.com",
    "apac": "https://widget.amap-prod.mobilesdk.mercedes-benz.com",
    "cn": "https://widget.cn-prod.mobilesdk.mercedes-benz.com",
}

OAUTH_SCOPE = "email profile ciam-uid phone openid offline_access"
OAUTH_REDIRECT_URI = "rismycar://login-callback"

# Mirrors mbapi2020 as of 2026-09 (Ris headers keep the BFF happy)
RIS_APPLICATION_VERSION = "1.68.0 (3060)"
RIS_APPLICATION_VERSION_NA = "3.67.0"
RIS_SDK_VERSION = "4.10.0"
RIS_OS_NAME = "ios"
RIS_OS_VERSION = "26.3"
APPLICATION_NAME = "mycar-store-ece"  # eu; us/ap variants exist upstream

# Vehicle attribute keys we read (all read-only).
# Names follow the VehicleStatusUpdate fields observed live on the EU
# widget endpoint (2026-09); first entry of each tuple is the current
# field name, later ones are fallbacks from older mbapi2020 shapes.
ATTR_STATE_OF_CHARGE = ("soc", "stateofcharge")
ATTR_RANGE_ELECTRIC = ("rangeelectric", "range_electric")
ATTR_CHARGING_ACTIVE = ("chargingactive",)
ATTR_CHARGING_STATUS = ("chargingstatus",)
ATTR_CHARGING_POWER = ("chargingpower",)
ATTR_END_OF_CHARGE_TIME = ("endofchargetime",)
ATTR_ODOMETER = ("odometer",)
ATTR_OUTSIDE_TEMP = ("outsideTemperature",)
ATTR_TCU_CONNECTION = ("tcu_connection_state_low_channel",)

# Fallback if widget/app returns no unit info
DEFAULT_RANGE_UNIT = "km"
