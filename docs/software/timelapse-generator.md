# Timelapse Generator

## Purpose
Automate creation of rolling timelapse videos (MP4/WEBM/GIF) from GOES imagery sequences for publication alongside the raw data.

## Responsibilities
- Watch filesystem changes or read monitor manifests for imagery additions (e.g., GOES-19 Full Disk/Mesoscale).
- Maintain queues of frame paths per product/band and window (e.g., last 6 hours, last day).
- Invoke encoding pipelines (ffmpeg) to produce timelapse files.
- Store outputs in a dedicated directory (e.g., `satellite_raw/derivatives/timelapses/`) with consistent naming conventions.
- Publish lightweight manifests describing available timelapses (time span, band, resolution).

## Inputs
- Filesystem monitor manifests or directory scans.
- Encoding templates (resolution, bitrate, frame rate).

## Outputs
- Timelapse media files ready for web serving.
- Manifest JSON for dashboard consumption.
- Logs and metrics (jobs processed, encoding duration, errors).

## Implementation Notes
- Support parallel encoding workers to keep up with Mesoscale cadence.
- Handle missing frames gracefully (interpolate or skip).
- Provide CLI hooks to regenerate historical timelapses on demand.
- Evaluate hardware-accelerated encoding (e.g., VAAPI) if CPU load becomes critical.
