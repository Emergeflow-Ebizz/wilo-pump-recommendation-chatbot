"""Tank filling use case configuration - constraints and rules for all questions."""

# ===== NUMERIC QUESTION CONFIGS =====

TANK_CAPACITY_CONFIG = {
    "key": "tank_capacity",
    "min_value": None,
    "max_value": None,
    "round_direction": None,
    "requires_integer": False,
    "reject_negative": True,
    "unit": "litres",
}

NUM_FLOORS_CONFIG = {
    "key": "num_floors",
    "min_value": 0,
    "max_value": None,
    "round_direction": None,
    "requires_integer": True,
    "reject_negative": True,
    "unit": None,
}

MOTOR_POWER_HP_CONFIG = {
    "key": "motor_power_hp",
    "min_value": None,
    "max_value": None,
    "round_direction": "down",
    "requires_integer": True,
    "reject_negative": True,
    "unit": "hp",
}

# ===== CATEGORY QUESTION CONFIGS =====

CATEGORY_KEYWORDS = {
    "inside": ["inside", "indoor", "indoors", "submersible"],
    "outside": ["outside", "outdoor", "outdoors", "surface", "ground"],
    "horizontal": ["horizontal"],
    "vertical": ["vertical"],
}

CATEGORY_LABELS = {
    "inside": "Inside (Submersible)",
    "outside": "Outside (Surface pump)",
    "horizontal": "Horizontal",
    "vertical": "Vertical",
}

# ===== QUESTION DEPENDENCIES =====

CONDITIONAL_QUESTIONS = {
    "horizontal_or_vertical": {
        "depends_on": "inside_or_outside",
        "required_value": "inside",
    }
}
