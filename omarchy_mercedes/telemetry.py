"""Read-only Mercedes-Benz telemetry client (REST BFF + widget protobuf).

Endpoints verified against mbapi2020 (MIT), 2026-09:
- GET {bff}/v2/vehicles                      -> account vehicles (JSON)
- GET {widget}/v1/vehicle/{vin}/vehicleattributes -> protobuf VEPUpdate
The protobuf response is parsed with the vendored vehicle_events_pb2.
"""

from __future__ import annotations

import json
import uuid

from .api_constants import (
    APPLICATION_NAME,
    ATTR_CHARGING_ACTIVE,
    ATTR_CHARGING_POWER,
    ATTR_CHARGING_STATUS,
    ATTR_END_OF_CHARGE_TIME,
    ATTR_ODOMETER,
    ATTR_OUTSIDE_TEMP,
    ATTR_RANGE_ELECTRIC,
    ATTR_STATE_OF_CHARGE,
    ATTR_TCU_CONNECTION,
    RIS_APPLICATION_VERSION,
    RIS_OS_NAME,
    RIS_OS_VERSION,
    RIS_SDK_VERSION,
    REST_API_BASE,
    WIDGET_API_BASE,
)

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class ApiError(RuntimeError):
    """Telemetry API failure (network, HTTP, protobuf decode)."""


class VehicleApi:
    """Read-only vehicle data access."""

    def __init__(self, region: str = "eu", timeout: int = 30, session=None):
        if region not in REST_API_BASE:
            raise ValueError(f"unsupported region {region!r}")
        self.region = region
        self.rest = REST_API_BASE[region].strip()
        self.widget = WIDGET_API_BASE[region].strip()
        self.timeout = timeout
        self._session = session

    def _http(self):
        if self._session is None:
            if requests is None:
                raise ApiError("the 'requests' package is required (pip install requests)")
            self._session = requests.Session()
        return self._session

    def _headers(self) -> dict:
        return {
            "Authorization": "Bearer {token}",  # replaced by caller
            "X-SessionId": str(uuid.uuid4()).upper(),
            "X-TrackingId": str(uuid.uuid4()).upper(),
            "ris-os-name": RIS_OS_NAME,
            "ris-os-version": RIS_OS_VERSION,
            "ris-application-version": RIS_APPLICATION_VERSION,
            "ris-sdk-version": RIS_SDK_VERSION,
            "X-ApplicationName": APPLICATION_NAME,
            "X-Locale": "de-DE",
            "Accept": "application/json",
            "Content-Type": "application/json; charset=UTF-8",
        }

    def _get_json(self, url: str, token: str) -> dict:
        headers = self._headers()
        headers["Authorization"] = f"Bearer {token}"
        try:
            r = self._http().get(url, headers=headers, timeout=self.timeout)
        except Exception as e:
            raise ApiError(f"network error: {type(e).__name__}") from e
        if r.status_code == 401:
            raise ApiError("unauthorized (401) - token expired or revoked")
        if r.status_code == 403:
            raise ApiError("forbidden (403) - account not entitled for this vehicle")
        if r.status_code == 404:
            raise ApiError("not found (404)")
        if r.status_code >= 400:
            raise ApiError(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as e:
            raise ApiError("invalid JSON from API") from e

    def list_vehicles(self, token: str) -> list[dict]:
        data = self._get_json(f"{self.rest}/v2/vehicles", token)
        # possible envelopes: [{"vin": ...}], {"vehicles": [...]},
        # {"assignedVehicles": [...]} (observed on EU accounts, 2026-09)
        for key in ("vehicles", "assignedVehicles"):
            if isinstance(data, dict) and isinstance(data.get(key), list):
                data = data[key]
                break
        if not isinstance(data, list):
            raise ApiError("unexpected /v2/vehicles response shape")
        return data

    def get_vehicle_attributes(self, vin: str, token: str) -> dict:
        """Fetch the widget protobuf and flatten interesting attributes.

        Returns {vin, emit_timestamp_ms, attributes: {key: {value, ts_ms, unit, status}}}
        Raises ApiError on decode failure.
        """
        url = f"{self.widget}/v1/vehicle/{vin}/vehicleattributes"
        headers = self._headers()
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/x-protobuf"
        try:
            r = self._http().get(url, headers=headers, timeout=self.timeout)
        except Exception as e:
            raise ApiError(f"network error: {type(e).__name__}") from e
        if r.status_code == 401:
            raise ApiError("unauthorized (401)")
        if r.status_code >= 400:
            raise ApiError(f"HTTP {r.status_code}")
        return decode_vehicle_attributes(r.content)


def decode_vehicle_attributes(blob: bytes) -> dict:
    """Parse the vehicleattributes protobuf into a flat dict.

    The widget endpoint returns a VehicleStatusUpdate (each attribute is its
    own numbered field, observed live 2026-09), not a VEPUpdate map message.
    We walk the typed fields and emit the same {attributes: {key: {...}}}
    shape the daemon consumes; keys match the mbapi2020 attribute names.
    """
    try:
        from .vendored import vehicle_events_pb2 as vep
    except ImportError as e:
        raise ApiError(f"protobuf support unavailable: {e}") from e

    msg = vep.VehicleStatusUpdate()
    try:
        msg.ParseFromString(blob)
    except Exception as e:
        raise ApiError(f"protobuf decode failed: {type(e).__name__}") from e

    def value_of(attr):
        # typed value in VehicleAttributeStatus oneof
        for field in ("int_value", "bool_value", "string_value", "double_value"):
            try:
                if attr.HasField(field):
                    return getattr(attr, field)
            except (ValueError, AttributeError):
                continue
        return getattr(attr, "display_value", None) or None

    def entry(attr):
        # typed attributes carry metadata (timestamp in SECONDS, status);
        # classic VehicleAttributeStatus has ms fields directly
        md = getattr(attr, "metadata", None)
        ts_ms = getattr(attr, "timestamp_in_ms", 0) or None
        if md is not None and ts_ms is None:
            ts = getattr(md, "timestamp", None)
            if ts is not None and ts.seconds:
                ts_ms = ts.seconds * 1000 + ts.nanos // 1_000_000
        return {
            "value": value_of(attr),
            "ts_ms": ts_ms,
            "display_value": getattr(attr, "display_value", None) or None,
            "status": int(getattr(attr, "status", 0) or (md.status if md is not None else 0)),
        }

    out = {
        "emit_timestamp_ms": None,
        "full_update": True,
        "attributes": {},
    }
    for f in msg.DESCRIPTOR.fields:
        if f.message_type is None:
            continue
        try:
            if not msg.HasField(f.name):
                continue
        except ValueError:
            continue  # repeated/map fields and groups have no presence
        attr = getattr(msg, f.name)
        if hasattr(attr, "timestamp_in_ms"):
            out["attributes"][f.name] = entry(attr)
        elif hasattr(attr, "value"):
            # newer typed attributes (e.g. Int64DistanceAttribute) keep the
            # value at field 1 and metadata (ts/status) in field 2
            ent = entry(attr.metadata) if hasattr(attr, "metadata") else {}
            ent["value"] = attr.value
            if getattr(attr, "display_value", None):
                ent["display_value"] = attr.display_value
            out["attributes"][f.name] = ent
    return out


INTERESTING = (
    ATTR_STATE_OF_CHARGE,
    ATTR_RANGE_ELECTRIC,
    ATTR_CHARGING_ACTIVE,
    ATTR_CHARGING_STATUS,
    ATTR_CHARGING_POWER,
    ATTR_END_OF_CHARGE_TIME,
    ATTR_ODOMETER,
    ATTR_OUTSIDE_TEMP,
    ATTR_TCU_CONNECTION,
)
