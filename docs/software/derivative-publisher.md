# Derivative Publisher

## Purpose
Manage other derivative outputs beyond timelapses (e.g., composite mosaics, statistical summaries, downsampled imagery) and publish them under web-accessible directories.

## Responsibilities
- Watch monitor manifests or scan directories to identify products requiring post-processing.
- Execute transformation pipelines (e.g., generate combined RGB overlays, thumbnails, ASCII summaries).
- Place results into structured directories (e.g., `satellite_raw/derivatives/composites/`).
- Update manifests so public pages and dashboards can link to new derivatives.

## Inputs
- Filesystem monitor manifests describing source file paths and metadata.
- Transformation configuration describing which derivatives to create per product type.

## Outputs
- Derived files stored alongside raw data.
- Metadata entries or manifests describing derivative provenance.

## Implementation Notes
- Start with a simple job queue shared with the timelapse generator.
- Record lineage (source timestamps, processing steps) for reproducibility.
- Keep derivatives optional; enable per-product toggles in configuration.
