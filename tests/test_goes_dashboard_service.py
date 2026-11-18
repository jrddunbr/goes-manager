from pathlib import Path
import io

from PIL import Image

from goes_dashboard.service import (
    StationLocation,
    extract_station_codes,
    render_radar_composite_image,
    select_radar_composite_sources,
    parse_filename,
    parse_lat_lon_centroid,
    parse_product,
)


def test_parse_filename_extracts_core_fields():
    product = parse_filename(
        Path("A_FXUS65KCYS142355_C_KWIN_20260414235559_410534-2-AFDCYSWY.TXT")
    )

    assert product is not None
    assert product.originator == "KCYS"
    assert product.awips_id == "AFDCYSWY"
    assert product.family == "AFD"
    assert product.category == "text"


def test_parse_lat_lon_centroid_for_warning_polygon():
    text = """WFUS53 KMKX 142333
TORMKX
LAT...LON 4303 8790 4300 8789 4301 8807 4319 8806
      4319 8789 4316 8788 4314 8790 4312 8790
      4310 8787 4307 8787
TIME...MOT...LOC 2333Z 268DEG 25KT 4315 8818
"""

    latitude, longitude = parse_lat_lon_centroid(text)

    assert round(latitude, 2) == 43.1
    assert round(longitude, 2) == -87.92


def test_extract_station_codes_uses_known_airports():
    airport_index = {
        "KAXV": StationLocation("KAXV", "Neil Armstrong", "Wapakoneta", "Ohio", "US", 40.49, -84.30, "test"),
        "KWBC": StationLocation("KWBC", "NCEP", "College Park", "Maryland", "US", 38.99, -76.94, "test"),
    }
    product = parse_filename(
        Path("A_SAUS70KWBC150010_C_KWIN_20260415001147_411405-2-SAHOURLY.txt")
    )
    assert product is not None

    text = "SAUS70 KWBC 150010\nMETAR\nKAXV 150005Z AUTO 14006KT 7SM TSRA\n"
    codes = extract_station_codes(text, product, airport_index)

    assert codes == ("KAXV", "KWBC")


def test_parse_product_adds_summary_and_station_codes(tmp_path: Path):
    airport_index = {
        "KAXV": StationLocation("KAXV", "Neil Armstrong", "Wapakoneta", "Ohio", "US", 40.49, -84.30, "test"),
        "KWBC": StationLocation("KWBC", "NCEP", "College Park", "Maryland", "US", 38.99, -76.94, "test"),
    }
    sample = tmp_path / "A_SAUS70KWBC150010_C_KWIN_20260415001147_411405-2-SAHOURLY.txt"
    sample.write_text(
        "SAUS70 KWBC 150010\nMETAR\nKAXV 150005Z AUTO 14006KT 7SM TSRA SCT011 BKN040 OVC100 15/13\n",
        encoding="utf-8",
    )

    product = parse_product(sample, airport_index, tmp_path)

    assert product is not None
    assert product.title == "Hourly METAR roundup: 1 stations"
    assert "KAXV 150005Z" in product.summary
    assert product.station_codes == ("KAXV", "KWBC")


def test_extract_station_codes_ignores_unattached_airport_tokens():
    airport_index = {
        "KAXV": StationLocation("KAXV", "Neil Armstrong", "Wapakoneta", "Ohio", "US", 40.49, -84.30, "test"),
        "KWBC": StationLocation("KWBC", "NCEP", "College Park", "Maryland", "US", 38.99, -76.94, "test"),
    }
    product = parse_filename(
        Path("A_FXUS70KWBC150010_C_KWIN_20260415001147_411405-2-AFDTEST.txt")
    )
    assert product is not None

    text = """FXUS70 KWBC 150010
Area Forecast Discussion
Reference airport KAXV appears in prose only and should not create a marker.
"""
    codes = extract_station_codes(text, product, airport_index)

    assert codes == ("KWBC",)


def test_parse_product_decodes_sahourly_into_human_readable_summary(tmp_path: Path):
    airport_index = {
        "KAXV": StationLocation("KAXV", "Neil Armstrong", "Wapakoneta", "Ohio", "US", 40.49, -84.30, "test"),
        "KWBC": StationLocation("KWBC", "NCEP", "College Park", "Maryland", "US", 38.99, -76.94, "test"),
    }
    sample = tmp_path / "A_SAUS70KWBC150010_C_KWIN_20260415001147_411405-2-SAHOURLY.txt"
    sample.write_text(
        "SAUS70 KWBC 150010\n\nMETAR\n\nKAXV 150005Z AUTO 14006KT 7SM TSRA SCT011 BKN040 OVC100 15/13 A2989 RMK AO2=\n",
        encoding="utf-8",
    )

    product = parse_product(sample, airport_index, tmp_path)

    assert product is not None
    assert product.title == "Hourly METAR roundup: 1 stations"
    assert "KAXV 150005Z" in product.summary
    assert any(label == "Latest decoded" and "140 deg at 6 kt" in value for label, value in product.detail_sections)


def test_parse_product_decodes_tafallus_into_forecast_summary(tmp_path: Path):
    airport_index = {
        "KZZV": StationLocation("KZZV", "Zanesville", "Zanesville", "Ohio", "US", 39.94, -81.89, "test"),
        "KWBC": StationLocation("KWBC", "NCEP", "College Park", "Maryland", "US", 38.99, -76.94, "test"),
    }
    sample = tmp_path / "A_FTUS80KWBC150010_C_KWIN_20260415001147_411405-2-TAFALLUS.txt"
    sample.write_text(
        "FTUS80 KWBC 150010\n\nTAF\n\nKZZV 150000Z 1500/1524 22008KT P6SM SCT060 BKN250 PROB30 1512/1515 6SM -SHRA BKN050\n"
        "FM151500 22013G20KT P6SM SCT040 PROB30 1518/1524 4SM TSRA BKN040CB=\n",
        encoding="utf-8",
    )

    product = parse_product(sample, airport_index, tmp_path)

    assert product is not None
    assert product.title == "Terminal forecasts: 1 stations"
    assert "KZZV valid 1500/1524" in product.summary
    assert any(label == "Changes" and "FM151500" in value for label, value in product.detail_sections)


def test_select_radar_composite_sources_picks_latest_image_for_each_slot(tmp_path: Path):
    airport_index = {}
    created = []
    samples = [
        ("RADPACNW", 0, 10),
        ("RADPACNW", 15, 30),
        ("RADGRTLK", 30, 60),
        ("RADREFUS", 45, 90),
    ]
    for awips_id, minute, color in samples:
        sample = tmp_path / f"Z_QATA00KWBC1512{minute:02d}_C_KWIN_2026041500{minute:02d}52_410800-3-{awips_id}.GIF"
        Image.new("P", (20, 20), color=color).save(sample, format="GIF")
        product = parse_product(sample, airport_index, tmp_path)
        assert product is not None
        created.append(product)

    selected = select_radar_composite_sources(created)

    assert [item.awips_id for item in selected] == ["RADPACNW", "RADGRTLK"]
    assert [item.receipt_time.minute for item in selected] == [15, 30]


def test_render_radar_composite_image_keeps_native_tile_size_and_appends_key(tmp_path: Path):
    airport_index = {}
    products = []
    for awips_id, color, marker_x in [
        ("RADPACNW", (255, 255, 255), 5),
        ("RADGRTLK", (220, 220, 220), 9),
    ]:
        sample = tmp_path / (
            f"Z_QATA00KWBC1512{marker_x:02d}_C_KWIN_2026041500{marker_x:02d}52_41080{marker_x}-3-{awips_id}.GIF"
        )
        image = Image.new("RGB", (32, 32), color)
        image.putpixel((marker_x, 10), (0, 0, 0))
        for x in range(32):
            image.putpixel((x, 31), (marker_x * 10, 0, 255 - (marker_x * 10)))
        image.save(sample, format="GIF")
        product = parse_product(sample, airport_index, tmp_path)
        assert product is not None
        products.append(product)

    payload = render_radar_composite_image(products)

    with Image.open(io.BytesIO(payload)) as rendered:
        assert rendered.size == (32 * 6, (32 - 6) * 4 + 6)
        assert rendered.getpixel((32 + 5, 10)) == (0, 0, 0)
        assert rendered.getpixel((32 * 4 + 9, 10)) == (0, 0, 0)
        assert rendered.getpixel((rendered.width // 2, rendered.height - 1)) == (90, 0, 165)
