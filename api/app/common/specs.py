"""Static technical overview (flow/head/fluid temperature/connection) per pump
model, for use cases with no json_new catalog sheet to read these values from.

Keyed by model name, since that's the identifier heat_circulation's and
domestic_hot_water's rules.py already have on hand when building a
PumpRecommendation.
"""

SPECS: dict[str, dict[str, str]] = {
    "Yonos PICO": {
        "flow": "Up to 4 m3/hr",
        "head": "Up to 7 meter",
        "fluid_temp": "-10 °C to +95 °C",
        "connection": "1~230 V, 50 Hz",
    },
    "Yonos MAXO": {
        "flow": "Up to 50 m3/hr",
        "head": "Up to 16 meter",
        "fluid_temp": "-20 °C to +110 °C",
        "connection": "1~230 V, 50/60 Hz",
    },
    "Stratos PICO": {
        "flow": "Up to 4 m3/hr",
        "head": "Up to 7 meter",
        "fluid_temp": "-10 °C to +110 °C",
        "connection": "1~230 V, 50 Hz",
    },
    "Stratos MAXO": {
        "flow": "Up to 70 m3/hr",
        "head": "Up to 16 meter",
        "fluid_temp": "-10 °C to +110 °C",
        "connection": "1~230 V, 50/60 Hz",
    },
    "PARA": {
        "flow": "Up to 2.6 m3/hr",
        "head": "Up to 6.3 meter",
        "fluid_temp": "-10 °C to +100 °C",
        "connection": "1~230 V, 50/60 Hz",
    },
    "PARA MAXO": {
        "flow": "Up to 9.5 m3/hr",
        "head": "Up to 8.2 meter",
        "fluid_temp": "-20 °C to +110 °C",
        "connection": "1~230 V, 50/60 Hz",
    },
    "Star-Z NOVA": {
        "flow": "Up to 0.4 m3/hr",
        "head": "Up to 1 meter",
        "fluid_temp": "2 °C to +95 °C",
        "connection": "1~230 V, 50 Hz",
    },
    "Star-Z NOVA A": {
        "flow": "Up to 0.4 m3/hr",
        "head": "Up to 1 meter",
        "fluid_temp": "2 °C to +95 °C",
        "connection": "1~230 V, 50 Hz",
    },
    "Star-Z NOVA T": {
        "flow": "Up to 0.4 m3/hr",
        "head": "Up to 1 meter",
        "fluid_temp": "2 °C to +95 °C",
        "connection": "1~230 V, 50 Hz",
    },
}


def get_specs(model_name: str | None) -> dict[str, str] | None:
    if model_name is None:
        return None
    return SPECS.get(model_name)
