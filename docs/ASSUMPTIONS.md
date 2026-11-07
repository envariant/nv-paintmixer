# Assumptions and interpretations

Decisions taken without asking, so they can be reviewed. Each is tagged with the milestone that
introduced it.

- **M0** Python is pinned to 3.12 through uv (`requires-python >=3.12`). The container ships 3.13 as
  `python3`; uv provisions 3.12 for the venv.
- **M0** The colour-maths package is named `paintmixer.colorsci` so it never shadows the
  third-party `colour` package from colour-science.
- **M0** TypeScript is pinned to 5.9 because `openapi-typescript` 7 has a TypeScript 5 peer
  dependency.
