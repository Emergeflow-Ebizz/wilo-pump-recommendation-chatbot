"""Static marketing/feature bullet points per pump model family.

Keyed by json_new filename (the same string passed to catalog_loader.load_sheet),
since that's the identifier every use case's rules.py already has on hand when
building a PumpRecommendation.
"""

_WBW_FEATURES = [
    "Wide voltage range available in single and three phase.",
    "High quality winding wires to ensure reliability & capability to withstand wide voltage fluctuation.",
    "Adequate bearing supports are provided at top, bottom and middle for better stability.",
    "Top & Suction bush are protected by proper sand guard arrangement.",
    "Non return valve designed for minimum friction loss.",
    "Water lubricated and fully rewindable motor with 2.75 m, 3 core, PVC flat cable along with earthing provision.",
    "Casings are provided with wear rings (SS) for longer life and ease of maintenance.",
]

_WPO_FEATURES = [
    "Highly durable rewindable motor.",
    "Dynamically balanced rotating parts to ensure minimum vibration, noise free operation & long bearing life.",
    "Compact mechanical design.",
    "Designed for wide voltage fluctuations.",
    "Pumps are CED coated to protect from corrosion.",
    "All internal parts are specially coated to prevent internal rusting.",
    "High operating efficiencies resulting in low power consumption & electric bills.",
]

_HMHIL_FMHIL_FEATURES = [
    "Stainless steel impeller.",
    "Wetted parts made up of stainless steel.",
    "Available with hydro pneumatic tank / electronic control for automatic operation.",
    "Highly efficient motor suitable for wide voltage fluctuations.",
    "Silent in operation.",
    "Dry run protection.",
]

FEATURES: dict[str, list[str]] = {
    "WBW-3.json": _WBW_FEATURES,
    "WBW-4 Prathak.json": _WBW_FEATURES,
    "WBW-6.json": _WBW_FEATURES,
    "WBW-7.json": _WBW_FEATURES,
    "WBW-8.json": _WBW_FEATURES,
    "WPO.json": _WPO_FEATURES,
    "WPOV.json": _WPO_FEATURES,
    "Kushal.json": [
        "High performance TEFC with capacitor.",
        "Dynamically balanced rotating parts to ensure minimum vibration, noise free operation & long bearing life.",
        "Built in thermal over-load protection.",
        "Safety feature - Earthing provision.",
        "Lifelong permanent lubricated (ZZ) bearings.",
        "Low life cycle cost with low maintenance, low power consumption and easy motor rewinding.",
        "Dynamically balanced aluminum rotor for precision.",
    ],
    "MPM.json": [
        "Dynamically balanced rotating parts to ensure minimum vibration, noise free operation & long bearing life.",
        "Designed for wide voltage fluctuations.",
    ],
    "Crown-Royal-Emperor.json": [
        "High suction lift up to 7.3 m.",
        "Life long permanent lubricated bearings.",
        "Built in thermal over-load protection.",
        "High quality aluminium extruded motor body.",
        "Low life cycle cost with low maintenance, low power consumption and easy motor rewinding.",
        "Dynamically balanced aluminum rotor for precision.",
        "TEFC capacitor start & run motor with Class B insulation.",
    ],
    "WHS.json": [
        "Single shaft for pump & motor to ensure permanent correct alignment.",
        "Mechanical seal arrangement.",
        "Safety feature with earthing provision.",
        "Brass impeller to avoid clogging and increase durability.",
        "Dynamically balanced aluminum rotor for precision.",
        "High performance TEFC capacitor start & run motor.",
        "Class B insulation.",
        "High suction lift up to 6 m.",
    ],
    "PB.json": [
        "Automatic/manual operation.",
        "Easy to carry, install and operate.",
        "Motor built with thermal protector for safety.",
        "Rust-proof casting by electric coating.",
        "Inline installation requires less space.",
    ],
    "PW.json": [
        "Self priming function.",
        "Automatic operation.",
        "Thermal protector to avoid motor burn out.",
        "Efficient cooling through specially designed cooling fan.",
        "Easy to carry, install and operate.",
        "Silent in operation.",
        "Brass inserts for longer durability.",
    ],
    "HWJ-FWJ.json": [
        "Stainless steel pump body and impeller.",
        "Available with hydro pneumatic tank / electronic control for automatic operation.",
        "Highly efficient motor suitable for wide voltage fluctuations.",
        "Anti-rust material.",
        "Silent operation.",
        "Easy to carry, install and operate.",
        "Dry run protection.",
    ],
    "HMHIL.json": _HMHIL_FMHIL_FEATURES,
    "FMHIL.json": _HMHIL_FMHIL_FEATURES,
    "MNC.json": [
        "Self priming and back pull out design for easy maintenance.",
        "Non clog semi open impeller handles solids up to 40 mm.",
        "Non asbestos PTFE gland packing with stuffing box arrangement.",
        "High efficiency motor suitable for wide voltage fluctuations.",
        "Replaceable wearing parts and rewindable motor.",
        "Stator and rotor coated with rust proof solution for better corrosion resistance.",
    ],
    "Initial_Waste.json": [
        "Pump installation in vertical position with horizontal delivery port.",
        "10 m cable length.",
        "IP68 protection class (up to 5 m immersion).",
        "Operating temperature range +5°C to +35°C.",
        "Suitable for fluid density from 1 to 1.06 kg/dm3.",
        "Suitable for fluid pH from 6 to 8.",
    ],
}


def get_features(filename: str | None) -> list[str] | None:
    if filename is None:
        return None
    return FEATURES.get(filename)
