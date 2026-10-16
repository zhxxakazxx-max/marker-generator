# Included composition and fabric catalog

The app catalog was extracted from the supplied **敏感词成分.xlsx** on 15 September 2026. The workbook was opened read-only and was not rewritten. Only the requested composition records and 12 reference images are included in the app assets.

Source workbook SHA-256: `6c220d8b44aac7516880068e7f7f945d01df0e6f77f3b74041f870d6d696c8ba`.

## Compositions

`assets/catalog.json` preserves each original label and cell address from `Sheet1!C4:C124`. It contains **119 usable presets and 2 records requiring review**. Source order is preserved. The header at C3 (`成份`) and pivot labels at C125/C126 (`(空白)` and `总计`) are excluded.

The two review records are retained in `errors`, not silently simplified:

| Source | Original value | Reason |
| --- | --- | --- |
| Sheet1!C48 | 棉5%聚酯纤维95%PU皮革 | `PU皮革` has no percentage or separate-layer explanation. |
| Sheet1!C107 | 棉90%氨纶10%PU皮革 | `PU皮革` has no percentage or separate-layer explanation. |

`纯金属` at C72 is mapped literally to `Metallic fiber`; no more specific metal is inferred. Other material translations use the shared app parser. All 119 accepted compositions total 100%, including decimal values.

## Default fabric references

Each image was resolved from the exact cell's WPS `DISPIMG` ID through `xl/cellimages.xml` and its internal relationship target. The original embedded bytes were copied without cropping, recoloring, resizing, or re-encoding. No external image links were fetched.

| App ID | Source | Embedded original | Reference use |
| --- | --- | --- | --- |
| light_blue | Sheet1!D11 | xl/media/image1.png | Fabric color and texture |
| royal_blue | Sheet1!E11 | xl/media/image3.png | Fabric color and texture |
| ivory | Sheet1!F11 | xl/media/image2.png | Fabric color and texture |
| navy | Sheet1!G11 | xl/media/image4.png | Fabric color and texture |
| teal | Sheet1!H11 | xl/media/image6.png | Fabric color and texture |
| black | Sheet1!I11 | xl/media/image7.png | Fabric color and texture |
| green | Sheet1!J11 | xl/media/image8.png | Fabric color and texture |
| burgundy | Sheet1!K11 | xl/media/image9.png | Fabric color and texture |
| white | Sheet1!L11 | xl/media/image11.png | Color: photograph of a white suit |
| grey | Sheet1!M11 | xl/media/image12.png | Color: gray fabric swatch |
| red | Sheet1!N11 | xl/media/image13.png | Color: red swatch |
| orange | Sheet1!O11 | xl/media/image14.png | Color: orange swatch |

The 12 color names and hex values are descriptive UI choices, not measured textile color standards. The reference photographs remain the source for appearance. Individual image IDs, paths, and SHA-256 hashes are recorded in `catalog.json`.

The requested label format comes from the user's first reference photograph. Existing lettering in other color references is not a new output instruction. Generated labels must omit all size markings, including separate side size tabs present in some originals. The white-suit reference supplies a color only and must not change the label scene into a garment-model photograph.

## Reproduce and verify

From the project directory, run the following with a Python environment containing the app dependencies:

```powershell
python scripts/extract_catalog.py "C:\path\to\敏感词成分.xlsx"
```

The extraction script uses standard-library ZIP/XML parsing and the app's composition parser. It verifies the workbook hash remains unchanged and the image bytes match their originals. It does not execute workbook formulas.

Validation performed for the included catalog:

- Compared all 121 extracted composition labels and addresses against an independent read-only `openpyxl` read: exact match.
- Validated all 119 accepted compositions and independently checked their totals equal 100%.
- Confirmed both unquantified `PU皮革` records are retained as review errors.
- Verified all 12 extracted files match the embedded original image bytes.
- Visually inspected all 12 original images and their left-to-right mapping.
- Verified the source workbook SHA-256 was unchanged after extraction.
