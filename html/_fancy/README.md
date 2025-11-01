# Fancy Index Headers

This folder contains HTML fragments intended for use with the nginx `fancyindex` module. Each fragment summarises the contents of a directory underneath `satellite_raw/` so visitors understand what the files represent.

| Fragment | Intended location | Notes |
| --- | --- | --- |
| `satellite_raw-header.html` | `location /satellite_raw/` | Top-level overview of all product families. |
| `EMWIN-header.html` | `location /satellite_raw/EMWIN/` | Text/graphic bulletin guidance. |
| `IMAGES-header.html` | `location /satellite_raw/IMAGES/` | GOES imagery summary (links to NWS sub-header). |
| `IMAGES-NWS-header.html` | `location /satellite_raw/IMAGES/NWS/` | LRIT forecast chart overview. |
| `L2-header.html` | `location /satellite_raw/L2/` | Level-2 product description. |
| `AdminMessages-header.html` | `location /satellite_raw/Admin%20Messages/` | Administrative notice notes (URL-encode the space). |
