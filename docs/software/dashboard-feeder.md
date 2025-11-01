# Dashboard Feeder

## Purpose
Provide live data feeds and APIs backing the public/operational dashboard that refreshes roughly every minute.

## Responsibilities
- Read monitor manifests or scan directories to determine the freshest imagery, Level-2 products, and EMWIN bulletins.
- Serve map-ready data (links to PNG/CBOR files, decoded textual bulletins) via REST and/or websocket endpoints.
- Maintain a cache of recent assets to minimise disk lookups.
- Support hover tooltips by exposing geocoded metadata (airport codes, forecast zones).
- Trigger alert hooks (websocket messages, push notifications) when critical AWIPS IDs arrive.

## Inputs
- Filesystem monitor manifests and direct filesystem reads.
- Reference datasets for geocoding (airport locations, forecast zone shapefiles).

## Outputs
- JSON/GeoJSON payloads for web clients.
- Websocket updates pushing per-minute changes.
- Static manifests for front-end consumption (e.g., latest timestamps by product).

## Implementation Notes
- Start with a lightweight Python FastAPI or Node server; design for horizontal scaling later.
- Integrate rate limiting and caching (Redis) to keep latency low.
- Provide health and metrics endpoints for observability.
- Coordinate with the timelapse generator so dashboard menus can link to available animations.
