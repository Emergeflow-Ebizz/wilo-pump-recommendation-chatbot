"""Always-on safety net: every json_new/*.json file actually referenced by
a use case's sheet_map.py must
load and validate cleanly, so a bad manual edit is caught by `pytest` -
locally or in CI - before it ever reaches production, instead of silently
producing a wrong pump recommendation.

Scoped to files actually wired into a use case (rather than "every file in
json_new/ minus known-bad ones"), because json_new/ also holds several
orphaned files nobody currently reads: MHIL.json and Star.json have known
structurally different shapes, and WPO-3_Horizontal.json has a model with
an empty performance_curves list -
none of the three are used by any rules.py today, so they're a pre-existing
data-quality issue to fix later, not a live production bug. PUN.json,
Rexa.json, and WPO-1_Horizontal.json are also currently unused but do
validate cleanly.

If a currently-unused file gets wired into a use case later, add its
filename below so this test starts covering it too.
"""

import pytest

from app.common import catalog_loader

HEALTHY_FILES = sorted(
    [
        "Challenger.json",
        "Crown-Royal-Emperor.json",
        "FMHIL.json",
        "HMHIL.json",
        "HWJ-FWJ.json",
        "Initial_Waste.json",
        "Kushal.json",
        "MNC.json",
        "MPM.json",
        "PB.json",
        "PW.json",
        "WBW-3.json",
        "WBW-4 Prathak.json",
        "WBW-6.json",
        "WBW-7.json",
        "WBW-8.json",
        "WHS.json",
        "WPO.json",
        "WPOV.json",
    ]
)


@pytest.mark.parametrize("filename", HEALTHY_FILES)
def test_sheet_validates(filename):
    # load_sheet() itself raises CatalogValidationError on any
    # malformed model - a clean call here is the pass condition.
    catalog = catalog_loader.load_sheet(filename)
    assert catalog, f"{filename} loaded zero models"
