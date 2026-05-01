# Autish Versioning Conventions

## Version Numbering (Semantic Versioning)
```
MAJOR.MINOR.PATCH
```
- PATCH: Bug fixes only, backward compatible
- MINOR: New features, backward compatible  
- MAJOR: Breaking changes, incompatible API

## Stage Markers
- **Pre-Alpha** (0.x.y): Very early, unstable, internal testing
- **Alpha** (0.x.y): First external testing, many bugs expected
- **Beta** (1.x.y): Feature complete, testing for bugs
- **Release Candidate (RC)**: Likely final release
- **Release/GA**: Production ready

## Current State
- autish is at **0.0.2** (Pre-Alpha)
- Classifier in pyproject.toml: "Development Status :: 2 - Pre-Alpha"
- Will move to Alpha at 0.1.0, Beta at 1.0.0 (or 0.x with feature freeze)