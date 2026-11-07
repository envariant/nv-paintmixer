# Assumptions and interpretations

Decisions taken without asking, so they can be reviewed. Each is tagged with the milestone that
introduced it.

- **M0** Python is pinned to 3.12 through uv (`requires-python >=3.12`). The container ships 3.13 as
  `python3`; uv provisions 3.12 for the venv.
- **M0** The colour-maths package is named `paintmixer.colorsci` so it never shadows the
  third-party `colour` package from colour-science.
- **M0** TypeScript is pinned to 5.9 because `openapi-typescript` 7 has a TypeScript 5 peer
  dependency.
- **M1** XYZ uses ASTM E2022 10 nm weighting factors computed by colour-science; weights outside
  400–700 nm are folded into the end bands (reflectance assumed constant beyond the range).
- **M1** Swatch sRGB is computed via D65 Lab so a perfect reflector is exactly sRGB white even
  though the 10 nm white point differs from the sRGB matrix white by ~0.01.
- **M1** Fluorescent and metallic/pearlescent paints are out of scope: K-M two-constant theory
  with 45/0 UV-cut measurement cannot model fluorescence or goniochromatic effects.
