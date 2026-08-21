# Pump Image Mapping Reference

This document maps pump image filenames to their corresponding pump models.

| Image File | Pump Models |
|---|---|
| WBWP3-WBWP4 | WBW-3, WBW-4 Prathak |
| Wilo-WBW6-WBW7-WBW8 | WBW-6, WBW-7, WBW-8 |
| WPO Raptor | WPO-Raptor |
| WPOV | WPO-V Raptor |
| WMB Kushal | Khushal |
| MPM | MPM |
| Mini | Crown AXA, Royal, Emperor |
| WHS | WHS-VN, WHS-MN, WHS-SN |
| PB | PB |
| PW Boost 05 | PW Boost |
| HWJ | HWJ |
| FMHIL | FMHIL |
| HMHIL | HMHIL |
| VMHIL | VMHIL |
| CO 2 MHIL | TWIN CO2BC, SV, MV |
| MNC | MNC |
| Challenger | Challenger |
| Initial Waste | Initial Waste |
| CIFAC | CIFAC |
| FAS,FAC | FAS, FAC |
| Rexa PRO-S | Rexa Cut |
| Star RS | Star |
| PUN | PUN |
| Hi Peri | High-Peri |
| MHIL | MHIL |
| RLTC | Panel (RLTC, DTC) |
| Yonos PICO | Yonos PICO |
| Yonos MAXO | Yonos MAXO |
| Stratos PICO | Stratos PICO |
| Stratos MAXO | Stratos MAXO |
| Para MAXO | Para MAXO |
| Para | Para |
| Star Z | Star-Z |

## Code Implementation

The image mapping is implemented in `static/app.js` in the `getPumpImagePath()` function. The matching algorithm:

1. Takes a pump model name (e.g., "CO 2MHIL505 BC")
2. Converts to uppercase
3. **Sorts all pattern keys by length (longest first)** to ensure specific patterns match before generic substrings
4. Returns the matching image path

### Key Substring Conflicts Resolved

The following pump patterns are substrings of other patterns and require careful ordering:
- `MHIL` appears in: FMHIL, HMHIL, CO 2MHIL, VMHIL
- `PARA` appears in: PARA MAXO
- `WPO` appears in: WPOV
- `FAC` appears in: CIFAC
- `STAR` appears in: STAR-Z

By sorting keys by length (longest first), longer patterns like "CO 2MHIL" are matched before shorter ones like "MHIL".
