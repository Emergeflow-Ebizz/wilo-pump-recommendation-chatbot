"""Product photo URLs per pump model family, sourced from Google Drive.

Keyed by json_new filename (the same string passed to catalog_loader.load_sheet),
mirroring api/app/common/features.py, since that's the identifier every use
case's rules.py already has on hand when building a PumpRecommendation.

Links are converted to Drive's thumbnail endpoint so they load directly in an
<img src>. This requires each source file to be shared as "Anyone with the
link - Viewer" in Drive.
"""


def _thumbnail(file_id: str) -> str:
    return f"https://drive.google.com/thumbnail?id={file_id}&sz=w1000"


IMAGE_URLS: dict[str, str] = {
    "WBW-3.json": _thumbnail("1QSrXLvWksr-pzh554dLroxtK-k0rVuef"),
    "WBW-4 Prathak.json": _thumbnail("1QSrXLvWksr-pzh554dLroxtK-k0rVuef"),
    "WBW-6.json": _thumbnail("11EYGgwt-782h9NYCWjdLTPGWp4n5zPin"),
    "WBW-7.json": _thumbnail("11EYGgwt-782h9NYCWjdLTPGWp4n5zPin"),
    "WBW-8.json": _thumbnail("11EYGgwt-782h9NYCWjdLTPGWp4n5zPin"),
    "WPO.json": _thumbnail("1EzbQKslbvM6_x5xWhhhS6p5fD55uOAAx"),
    "WPOV.json": _thumbnail("1zlfCEv5MFK0WB3HrW63dlVKhi5l_F9Vm"),
    "Kushal.json": _thumbnail("1dYh9HEY8tfLcm7vVHYA4oOZhwLYGDW8v"),
    "MPM.json": _thumbnail("18XwrpMEPiTeefnKajqOzgChdzqKXmNw_"),
    "Crown-Royal-Emperor.json": _thumbnail("1920w-IwVYY330rbxOkpdH1rCq8R4bjDZ"),
    "WHS.json": _thumbnail("1l-CyQkjr-4rlkrErV-5QQDul1np95YhU"),
    "PB.json": _thumbnail("1BV6wPGUOOBS_n_Tnj_iC7sw6_Xu4MOzL"),
    "PW.json": _thumbnail("1L0P6iabb89XnKO3mH0tYfuJUzgvvb5zV"),
    "HWJ-FWJ.json": _thumbnail("1_6y-dsYUVg8zvcUI9oGTnNyWv8ZEdtZm"),
    "FMHIL.json": _thumbnail("1l5n-afzqO0_W_ljCjB7SGppJEKOOpQLQ"),
    "HMHIL.json": _thumbnail("1BoCZSpc_MSchkBl0VxxWmo2pIGil7VhY"),
    "MNC.json": _thumbnail("1_nifdbDZXQru3yEQowHe-X42ZuH98g50"),
    "Challenger.json": _thumbnail("1s4WmE7F3PxawfCVXFY91ay-i_eb_-M56"),
    "Initial_Waste.json": _thumbnail("1y9FxmwGiS75tsGeT9KY9Bm5tLmV1CWP0"),
    # Catalog files that exist but aren't consumed by any use case's rules.py yet
    # (see api/tests/test_catalog_parity.py and test_catalog_validation.py) -
    # image wired now so nothing else changes if they get plugged into a use
    # case later.
    "Rexa.json": _thumbnail("1y3dqADkkpu35FLGm7R184CRVHwRlAraa"),
    "Star.json": _thumbnail("1WVWRLodfnb1Cfvd3rBWlZ-9Suoo9-cn-"),
    "PUN.json": _thumbnail("1-IWeWJlXG1HaCQiLgj1Z8Gr3ZOUp8iOG"),
    "MHIL.json": _thumbnail("1HDsGusw4CHL5XRtrheyIj0YNZLB2eEpp"),
}

# Families with a supplied Drive link but no corresponding json_new catalog
# file at all - kept for traceability only, not looked up by get_image_url().
UNMAPPED_IMAGE_URLS: dict[str, str] = {
    "VMHIL": _thumbnail("1ere7OivLsTcnMEJmIx9hC9U-w4lj5_pV"),
    "TWIN CO2BC, SV, MV": _thumbnail("13jh_usERG_mf4EfkjeTrrNusMpuCdED4"),
    "CIFAC": _thumbnail("14qEHMKeG393BZevl7tvWsloFZXpIryK-"),
    "FAS, FAC": _thumbnail("1_r2OUBrPOONYiXlvrm1PikRDjzwxcwgn"),
    "Panel (RLTC, DTC)": _thumbnail("1irI00g0PIZIVKKrnQVo6l2wvh5RDVPjV"),
    "High-Peri": _thumbnail("1MavLMGj8l2YVzgfQt91oFQQcsybpch3j"),
}


def get_image_url(filename: str | None) -> str | None:
    if filename is None:
        return None
    return IMAGE_URLS.get(filename)
