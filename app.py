import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, unquote_plus
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

NOMINATIM_URL  = "https://nominatim.openstreetmap.org"
OSRM_URL       = "http://router.project-osrm.org"
VALHALLA_URL   = "https://valhalla1.openstreetmap.de"
OPEN_METEO_URL = "https://api.open-meteo.com/v1"
TOMTOM_ROUTING = "https://api.tomtom.com/routing/1/calculateRoute"
TOMTOM_MODES   = {"driving": "car", "motorcycle": "motorcycle", "cycling": "bicycle", "walking": "pedestrian"}
OCM_URL        = "https://api.openchargemap.io/v3/poi/"
OCM_API_KEY    = os.environ.get("OCM_API_KEY", "")
OVERPASS_URL   = "https://overpass-api.de/api/interpreter"
HEADERS        = {"User-Agent": "TravelPlannerApp/1.0 (educational project)"}

# ===== EV VEHICLE DATABASE =====
EV_VEHICLES = [
    {"id": "tesla-m3-lr",    "brand": "Tesla",    "model": "Model 3 Long Range AWD",   "range_km": 568, "consumption": 14.3, "battery_kwh": 75.0,  "max_dc_kw": 250},
    {"id": "tesla-m3-sr",    "brand": "Tesla",    "model": "Model 3 Standard Range",   "range_km": 438, "consumption": 14.0, "battery_kwh": 57.5,  "max_dc_kw": 170},
    {"id": "tesla-my-lr",    "brand": "Tesla",    "model": "Model Y Long Range AWD",   "range_km": 533, "consumption": 16.0, "battery_kwh": 75.0,  "max_dc_kw": 250},
    {"id": "tesla-ms-lr",    "brand": "Tesla",    "model": "Model S Long Range",       "range_km": 652, "consumption": 16.5, "battery_kwh": 100.0, "max_dc_kw": 250},
    {"id": "vw-id4-pro",     "brand": "VW",       "model": "ID.4 Pro Performance",     "range_km": 522, "consumption": 16.5, "battery_kwh": 77.0,  "max_dc_kw": 135},
    {"id": "vw-id3-pro",     "brand": "VW",       "model": "ID.3 Pro Performance",     "range_km": 426, "consumption": 15.4, "battery_kwh": 58.0,  "max_dc_kw": 100},
    {"id": "bmw-ix3",        "brand": "BMW",      "model": "iX3",                      "range_km": 459, "consumption": 17.5, "battery_kwh": 74.0,  "max_dc_kw": 150},
    {"id": "bmw-i4-m50",     "brand": "BMW",      "model": "i4 M50",                   "range_km": 521, "consumption": 16.0, "battery_kwh": 80.7,  "max_dc_kw": 205},
    {"id": "hyundai-i5-lr",  "brand": "Hyundai",  "model": "IONIQ 5 Long Range AWD",   "range_km": 481, "consumption": 18.0, "battery_kwh": 77.4,  "max_dc_kw": 220},
    {"id": "hyundai-i6-lr",  "brand": "Hyundai",  "model": "IONIQ 6 Long Range RWD",   "range_km": 614, "consumption": 14.0, "battery_kwh": 77.4,  "max_dc_kw": 220},
    {"id": "kia-ev6-lr",     "brand": "Kia",      "model": "EV6 Long Range AWD",       "range_km": 506, "consumption": 18.0, "battery_kwh": 77.4,  "max_dc_kw": 220},
    {"id": "kia-ev9-lr",     "brand": "Kia",      "model": "EV9 Long Range AWD",       "range_km": 512, "consumption": 21.0, "battery_kwh": 99.8,  "max_dc_kw": 240},
    {"id": "audi-q4-50",     "brand": "Audi",     "model": "Q4 e-tron 50 quattro",     "range_km": 490, "consumption": 18.0, "battery_kwh": 77.0,  "max_dc_kw": 135},
    {"id": "audi-et-55",     "brand": "Audi",     "model": "e-tron 55 quattro",        "range_km": 446, "consumption": 24.0, "battery_kwh": 95.0,  "max_dc_kw": 150},
    {"id": "merc-eqs",       "brand": "Mercedes", "model": "EQS 450+",                 "range_km": 770, "consumption": 15.7, "battery_kwh": 107.8, "max_dc_kw": 200},
    {"id": "merc-eqa",       "brand": "Mercedes", "model": "EQA 300 4MATIC",           "range_km": 462, "consumption": 17.7, "battery_kwh": 66.5,  "max_dc_kw": 100},
    {"id": "peugeot-e208",   "brand": "Peugeot",  "model": "e-208 50 kWh",             "range_km": 362, "consumption": 14.6, "battery_kwh": 50.0,  "max_dc_kw": 100},
    {"id": "renault-meg",    "brand": "Renault",  "model": "Mégane E-Tech EV60",  "range_km": 450, "consumption": 14.5, "battery_kwh": 60.0,  "max_dc_kw": 130},
    {"id": "renault-zoe",    "brand": "Renault",  "model": "Zoe R135 Z.E. 50",         "range_km": 395, "consumption": 17.2, "battery_kwh": 52.0,  "max_dc_kw": 50},
    {"id": "fiat-500e",      "brand": "Fiat",     "model": "500e 42 kWh",              "range_km": 320, "consumption": 14.0, "battery_kwh": 37.3,  "max_dc_kw": 85},
    {"id": "opel-mokka-e",   "brand": "Opel",     "model": "Mokka-e 50 kWh",           "range_km": 338, "consumption": 16.5, "battery_kwh": 50.0,  "max_dc_kw": 100},
    {"id": "nissan-leaf+",   "brand": "Nissan",   "model": "Leaf e+ 62 kWh",           "range_km": 385, "consumption": 18.0, "battery_kwh": 59.0,  "max_dc_kw": 50},
    {"id": "volvo-xc40",     "brand": "Volvo",    "model": "XC40 Recharge Single",     "range_km": 423, "consumption": 21.0, "battery_kwh": 69.0,  "max_dc_kw": 150},
    {"id": "volvo-c40",      "brand": "Volvo",    "model": "C40 Recharge AWD",         "range_km": 510, "consumption": 19.0, "battery_kwh": 82.0,  "max_dc_kw": 150},
    {"id": "skoda-enyaq",    "brand": "Škoda", "model": "ENYAQ iV 80",            "range_km": 530, "consumption": 16.5, "battery_kwh": 77.0,  "max_dc_kw": 125},
    {"id": "ford-mach-e",    "brand": "Ford",     "model": "Mustang Mach-E AWD Ext.",  "range_km": 490, "consumption": 21.5, "battery_kwh": 91.0,  "max_dc_kw": 150},
    {"id": "polestar-2-lr",  "brand": "Polestar", "model": "2 Long Range Dual Motor",  "range_km": 476, "consumption": 19.0, "battery_kwh": 78.0,  "max_dc_kw": 205},
    {"id": "byd-atto3",      "brand": "BYD",      "model": "ATTO 3 Long Range",        "range_km": 420, "consumption": 15.7, "battery_kwh": 60.5,  "max_dc_kw": 80},
    {"id": "byd-seal",       "brand": "BYD",      "model": "Seal 82.5 kWh AWD",        "range_km": 570, "consumption": 16.5, "battery_kwh": 82.5,  "max_dc_kw": 150},
    {"id": "mg4-64",         "brand": "MG",       "model": "MG4 Electric 64 kWh",      "range_km": 450, "consumption": 15.5, "battery_kwh": 61.7,  "max_dc_kw": 135},
    {"id": "cupra-born",     "brand": "Cupra",    "model": "Born 170hp 58 kWh",        "range_km": 424, "consumption": 15.4, "battery_kwh": 58.0,  "max_dc_kw": 100},
]

WMO_DESCRIPTIONS = {
    0: "Cielo sereno", 1: "Prevalentemente sereno", 2: "Parzialmente nuvoloso", 3: "Nuvoloso",
    45: "Nebbia", 48: "Nebbia con brina",
    51: "Pioggerellina leggera", 53: "Pioggerellina moderata", 55: "Pioggerellina intensa",
    56: "Pioggerellina gelata leggera", 57: "Pioggerellina gelata intensa",
    61: "Pioggia leggera", 63: "Pioggia moderata", 65: "Pioggia intensa",
    66: "Pioggia gelata leggera", 67: "Pioggia gelata intensa",
    71: "Neve leggera", 73: "Neve moderata", 75: "Neve intensa", 77: "Neve granulare",
    80: "Rovesci leggeri", 81: "Rovesci moderati", 82: "Rovesci violenti",
    85: "Rovesci di neve", 86: "Rovesci di neve intensi",
    95: "Temporale", 96: "Temporale con grandine", 99: "Temporale con grandine intensa",
}

WMO_ICONS = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌨️", 67: "🌨️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "🌨️",
    80: "🌧️", 81: "🌧️", 82: "⛈️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

TRAFFIC_LABELS = {1: "Libero", 2: "Scorrevole", 3: "Moderato", 4: "Intenso", 5: "Molto intenso"}
TRAFFIC_COLORS = {1: "#27ae60", 2: "#f1c40f", 3: "#e67e22", 4: "#e74c3c", 5: "#8e44ad"}
TRAFFIC_ICONS  = {1: "🟢", 2: "🟡", 3: "🟠", 4: "🔴", 5: "🚨"}
TRAFFIC_DELAY  = {1: 0, 2: 10, 3: 30, 4: 60, 5: 100}
WEEKDAY_IT     = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

# Mapping curva 1-5 → parametri Valhalla moto
CURVE_SETTINGS = {
    1: {"use_highways": 1.0, "use_tolls": 0.5, "use_trails": 0.0},
    2: {"use_highways": 0.7, "use_tolls": 0.5, "use_trails": 0.15},
    3: {"use_highways": 0.5, "use_tolls": 0.5, "use_trails": 0.25},
    4: {"use_highways": 0.2, "use_tolls": 0.5, "use_trails": 0.4},
    5: {"use_highways": 0.0, "use_tolls": 0.5, "use_trails": 0.5},
}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/geocode", methods=["POST"])
def geocode():
    query = (request.get_json() or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "Query vuota"}), 400
    try:
        r = requests.get(
            f"{NOMINATIM_URL}/search",
            params={"q": query, "format": "json", "limit": 6, "addressdetails": 1},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        return jsonify(r.json())
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reverse-geocode", methods=["POST"])
def reverse_geocode():
    data = request.get_json() or {}
    try:
        r = requests.get(
            f"{NOMINATIM_URL}/reverse",
            params={"lat": data["lat"], "lon": data["lon"], "format": "json"},
            headers=HEADERS, timeout=10,
        )
        r.raise_for_status()
        return jsonify(r.json())
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/route", methods=["POST"])
def calculate_route():
    data           = request.get_json() or {}
    waypoints      = data.get("waypoints", [])
    profile        = data.get("profile", "driving")
    curves         = int(data.get("curves", 1))
    curves_per_leg = data.get("curves_per_leg", [])   # list of int, one per leg

    if len(waypoints) < 2:
        return jsonify({"error": "Servono almeno 2 tappe"}), 400

    try:
        if profile == "motorcycle":
            if curves_per_leg and len(curves_per_leg) == len(waypoints) - 1:
                result = _call_valhalla_per_leg(waypoints, curves_per_leg)
            else:
                result = _call_valhalla(waypoints, curves)
        elif profile == "electric":
            result = _call_osrm(waypoints, "driving")
        else:
            result = _call_osrm(waypoints, profile)
        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/weather-segment", methods=["POST"])
def weather_segment():
    """
    Recupera meteo ogni 20 km lungo un tratto.
    Per ogni punto calcola l'orario stimato di passaggio in base alla partenza
    e alla durata totale del tratto (proporzione lineare sulla distanza).
    """
    data = request.get_json() or {}
    geometry = data.get("geometry")
    date_str = data.get("date")
    time_str = data.get("time", "09:00")
    duration_sec = float(data.get("duration_sec", 0))
    distance_km = float(data.get("distance_km", 1))  # evita divisione per zero

    if not geometry or not date_str:
        return jsonify({"error": "geometry e date sono obbligatori"}), 400

    interval_km = max(5, min(50, int(data.get("interval_km", 20))))

    coords = geometry.get("coordinates", [])
    if len(coords) < 2:
        return jsonify({"error": "Geometria non valida"}), 400

    try:
        departure = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"error": "Formato data/ora non valido (YYYY-MM-DD HH:MM)"}), 400

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if departure.date() < today.date():
        return jsonify({"error": "Data nel passato"}), 400

    end_dt = departure + timedelta(seconds=max(duration_sec, 0))
    end_days = (end_dt.replace(hour=0, minute=0, second=0, microsecond=0) - today).days
    if end_days > 16:
        return jsonify({"error": "Il viaggio supera il limite di previsioni di 16 giorni"}), 400

    points = _sample_route_points(coords, interval_km=interval_km)

    def fetch(pt):
        fraction = min(pt["dist_km"] / distance_km, 1.0) if distance_km > 0 else 0.0
        offset = timedelta(seconds=fraction * duration_sec)
        point_dt = departure + offset
        pt_date = point_dt.strftime("%Y-%m-%d")
        pt_hour = point_dt.hour

        try:
            r = requests.get(
                f"{OPEN_METEO_URL}/forecast",
                params={
                    "latitude": pt["lat"], "longitude": pt["lon"],
                    "hourly": ("temperature_2m,apparent_temperature,precipitation_probability,"
                               "precipitation,weathercode,windspeed_10m,winddirection_10m,cloudcover"),
                    "start_date": pt_date, "end_date": pt_date,
                    "timezone": "auto", "wind_speed_unit": "kmh",
                },
                timeout=12,
            )
            r.raise_for_status()
            h = r.json().get("hourly", {})
            if pt_hour >= len(h.get("temperature_2m", [])):
                return None
            code = h["weathercode"][pt_hour]
            return {
                "lat": pt["lat"], "lon": pt["lon"], "dist_km": pt["dist_km"],
                "estimated_time": point_dt.strftime("%H:%M"),
                "estimated_date": pt_date,
                "temperature": round(h["temperature_2m"][pt_hour], 1),
                "apparent_temperature": round(h["apparent_temperature"][pt_hour], 1),
                "precipitation_probability": h["precipitation_probability"][pt_hour],
                "precipitation": h["precipitation"][pt_hour],
                "weathercode": code,
                "weather_description": WMO_DESCRIPTIONS.get(code, f"Codice {code}"),
                "weather_icon": WMO_ICONS.get(code, "🌡️"),
                "windspeed": round(h["windspeed_10m"][pt_hour], 1),
                "winddirection": h["winddirection_10m"][pt_hour],
                "cloudcover": h["cloudcover"][pt_hour],
            }
        except Exception as exc:
            return {"lat": pt["lat"], "lon": pt["lon"], "dist_km": pt["dist_km"], "error": str(exc)}

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(fetch, points))

    return jsonify([r for r in results if r is not None])


@app.route("/api/traffic-segment", methods=["POST"])
def traffic_segment():
    """
    Traffico ogni 20 km con orario stimato di passaggio.
    Se TOMTOM_API_KEY è impostata usa TomTom Routing API con departAt
    (dati storici per quel giorno/ora specifici).
    Altrimenti usa stima euristica giorno+ora.
    """
    data = request.get_json() or {}
    geometry     = data.get("geometry")
    date_str     = data.get("date")
    time_str     = data.get("time", "09:00")
    duration_sec = float(data.get("duration_sec", 0))
    distance_km  = float(data.get("distance_km", 1))
    profile      = data.get("profile", "driving")
    interval_km  = max(5, min(50, int(data.get("interval_km", 20))))

    if not geometry or not date_str:
        return jsonify({"error": "geometry e date sono obbligatori"}), 400

    coords = geometry.get("coordinates", [])
    if len(coords) < 2:
        return jsonify({"error": "Geometria non valida"}), 400

    try:
        departure = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return jsonify({"error": "Formato data/ora non valido (YYYY-MM-DD HH:MM)"}), 400

    api_key     = os.environ.get("TOMTOM_API_KEY", "").strip()
    tomtom_data = None
    source      = "heuristic"

    if api_key:
        try:
            tomtom_data = _tomtom_route_traffic(coords[0], coords[-1], departure, api_key, profile)
            source = "tomtom_historical"
        except Exception:
            pass

    points  = _sample_route_points(coords, interval_km=interval_km)
    results = []

    for pt in points:
        fraction = min(pt["dist_km"] / distance_km, 1.0) if distance_km > 0 else 0.0
        point_dt = departure + timedelta(seconds=fraction * duration_sec)
        weekday  = point_dt.weekday()

        h_level = _estimate_traffic_level(weekday, point_dt.hour, point_dt.minute)
        level   = _blend_traffic(tomtom_data["level"], h_level) if tomtom_data else h_level

        results.append({
            "lat": pt["lat"], "lon": pt["lon"], "dist_km": pt["dist_km"],
            "estimated_time": point_dt.strftime("%H:%M"),
            "estimated_date": point_dt.strftime("%Y-%m-%d"),
            "weekday_name":   WEEKDAY_IT[weekday],
            "traffic_level":  level,
            "traffic_label":  TRAFFIC_LABELS[level],
            "traffic_color":  TRAFFIC_COLORS[level],
            "traffic_icon":   TRAFFIC_ICONS[level],
            "delay_percent":  TRAFFIC_DELAY[level],
            "source":         source,
        })

    return jsonify({
        "source":         source,
        "leg_delay_min":  tomtom_data["delay_min"]  if tomtom_data else None,
        "leg_flow_ratio": tomtom_data["flow_ratio"] if tomtom_data else None,
        "points":         results,
    })


# ───── routing helpers ──────────────────────────────────────────────────────

def _call_osrm(waypoints, profile):
    coords = ";".join(f"{w['lon']},{w['lat']}" for w in waypoints)
    r = requests.get(
        f"{OSRM_URL}/route/v1/{profile}/{coords}",
        params={"overview": "full", "geometries": "geojson", "steps": "true"},
        timeout=30,
    )
    r.raise_for_status()
    result = r.json()

    if result.get("code") != "Ok":
        raise ValueError("Impossibile calcolare il percorso")

    route = result["routes"][0]
    legs = []
    for leg in route["legs"]:
        leg_coords = []
        for step in leg.get("steps", []):
            sc = step["geometry"]["coordinates"]
            if not sc:
                continue
            if leg_coords and sc[0] == leg_coords[-1]:
                leg_coords.extend(sc[1:])
            else:
                leg_coords.extend(sc)
        c_score, c_stars, c_label = _calculate_curvature(leg_coords)
        legs.append({
            "distance_km": round(leg["distance"] / 1000, 1),
            "duration_sec": round(leg["duration"]),
            "duration_formatted": _fmt_duration(leg["duration"]),
            "geometry": {"type": "LineString", "coordinates": leg_coords},
            "curvature_score": round(c_score, 1),
            "curvature_stars": c_stars,
            "curvature_label": c_label,
        })
    return {
        "legs": legs,
        "total_distance_km": round(route["distance"] / 1000, 1),
        "total_duration_formatted": _fmt_duration(route["duration"]),
    }


def _call_valhalla_per_leg(waypoints, curves_per_leg):
    """Routing moto tratto per tratto con preferenza curve diversa per ognuno."""
    all_legs   = []
    total_dist = 0.0
    total_dur  = 0.0
    for i in range(len(waypoints) - 1):
        res = _call_valhalla([waypoints[i], waypoints[i + 1]], int(curves_per_leg[i]))
        leg = res["legs"][0]
        all_legs.append(leg)
        total_dist += leg["distance_km"]
        total_dur  += leg["duration_sec"]
    return {
        "legs": all_legs,
        "total_distance_km": round(total_dist, 1),
        "total_duration_formatted": _fmt_duration(total_dur),
    }


def _call_valhalla(waypoints, curves):
    """Routing moto via Valhalla con preferenza curve 1-5."""
    curves = max(1, min(5, int(curves)))
    body = {
        "locations": [{"lon": w["lon"], "lat": w["lat"]} for w in waypoints],
        "costing": "motorcycle",
        "costing_options": {"motorcycle": CURVE_SETTINGS[curves]},
        "units": "km",
    }
    r = requests.post(
        f"{VALHALLA_URL}/route",
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()

    trip = data.get("trip", {})
    if trip.get("status", 0) != 0 or "error" in data:
        raise ValueError(data.get("error", "Errore Valhalla sconosciuto"))

    legs = []
    for leg in trip["legs"]:
        coords = _decode_polyline6(leg["shape"])
        c_score, c_stars, c_label = _calculate_curvature(coords)
        legs.append({
            "distance_km": round(leg["summary"]["length"], 1),
            "duration_sec": round(leg["summary"]["time"]),
            "duration_formatted": _fmt_duration(leg["summary"]["time"]),
            "geometry": {"type": "LineString", "coordinates": coords},
            "curvature_score": round(c_score, 1),
            "curvature_stars": c_stars,
            "curvature_label": c_label,
        })
    return {
        "legs": legs,
        "total_distance_km": round(trip["summary"]["length"], 1),
        "total_duration_formatted": _fmt_duration(trip["summary"]["time"]),
    }


def _decode_polyline6(encoded):
    """Decodifica polyline Valhalla (precision 6) → lista [lon, lat] (GeoJSON)."""
    coords = []
    index = lat = lng = 0
    while index < len(encoded):
        for is_lat in (True, False):
            result = shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 32:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lat:
                lat += delta
            else:
                lng += delta
        coords.append([lng / 1e6, lat / 1e6])
    return coords


# ───── geometry helpers ─────────────────────────────────────────────────────

def _bearing(lon1, lat1, lon2, lat2):
    """Angolo di rotta da punto 1 a punto 2 in gradi [0-360]."""
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _calculate_curvature(coords):
    """
    Misura la sinuosità reale del percorso come cambio totale di direzione (gradi) per km.
    Restituisce (score, stelle 1-5, etichetta).
    """
    if len(coords) < 3:
        return 0.0, 1, "Rettilineo"

    total_angle = 0.0
    total_dist = 0.0

    for i in range(1, len(coords) - 1):
        p0, p1, p2 = coords[i - 1], coords[i], coords[i + 1]
        seg = _haversine(p0[0], p0[1], p1[0], p1[1])
        if seg < 0.005:          # ignora segmenti < 5 m (evita noise GPS)
            continue
        b1 = _bearing(p0[0], p0[1], p1[0], p1[1])
        b2 = _bearing(p1[0], p1[1], p2[0], p2[1])
        delta = abs(b2 - b1)
        if delta > 180:
            delta = 360 - delta
        total_angle += delta
        total_dist += seg

    if total_dist < 0.1:
        return 0.0, 1, "Rettilineo"

    score = total_angle / total_dist   # gradi / km

    if score < 5:
        return score, 1, "Quasi rettilineo"
    elif score < 15:
        return score, 2, "Poco curvato"
    elif score < 35:
        return score, 3, "Moderatamente curvato"
    elif score < 70:
        return score, 4, "Molto curvato"
    else:
        return score, 5, "Estremamente curvato"


def _haversine(lon1, lat1, lon2, lat2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(min(a, 1.0)))


def _sample_route_points(coords, interval_km=20):
    """Campiona punti ogni interval_km lungo la polilinea → lista {lat, lon, dist_km}."""
    if len(coords) < 2:
        return [{"lat": coords[0][1], "lon": coords[0][0], "dist_km": 0.0}]

    result = [{"lat": coords[0][1], "lon": coords[0][0], "dist_km": 0.0}]
    accumulated = 0.0
    next_target = float(interval_km)

    for i in range(1, len(coords)):
        p0, p1 = coords[i - 1], coords[i]
        seg_km = _haversine(p0[0], p0[1], p1[0], p1[1])

        while seg_km > 0 and next_target <= accumulated + seg_km:
            frac = (next_target - accumulated) / seg_km
            lon = p0[0] + frac * (p1[0] - p0[0])
            lat = p0[1] + frac * (p1[1] - p0[1])
            result.append({"lat": lat, "lon": lon, "dist_km": round(next_target, 1)})
            next_target += interval_km

        accumulated += seg_km

    last = {"lat": coords[-1][1], "lon": coords[-1][0], "dist_km": round(accumulated, 1)}
    prev = result[-1]
    if abs(prev["lat"] - last["lat"]) > 1e-6 or abs(prev["lon"] - last["lon"]) > 1e-6:
        result.append(last)

    return result


def _fmt_duration(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m}min" if h > 0 else f"{m}min"


def _estimate_traffic_level(weekday, hour, minute):
    """Stima livello traffico 1-5 in base a giorno (0=lun) e ora."""
    t = hour + minute / 60.0
    if weekday < 5:  # Lunedì–Venerdì
        if   8.0 <= t <  9.5:  return 5
        if  17.0 <= t < 18.5:  return 5
        if   7.0 <= t <  8.0:  return 4
        if  18.5 <= t < 19.5:  return 4
        if   9.5 <= t < 11.0:  return 3
        if  12.0 <= t < 14.0:  return 3
        if  16.0 <= t < 17.0:  return 3
        if   6.0 <= t <  7.0:  return 2
        if  11.0 <= t < 12.0:  return 2
        if  14.0 <= t < 16.0:  return 2
        if  19.5 <= t < 21.0:  return 2
        return 1
    else:  # Sabato–Domenica
        if  10.0 <= t < 13.0:  return 3
        if  16.0 <= t < 19.0:  return 3
        if   8.0 <= t < 10.0:  return 2
        if  13.0 <= t < 16.0:  return 2
        if  19.0 <= t < 22.0:  return 2
        return 1


def _tomtom_route_traffic(start_coord, end_coord, depart_dt, api_key, profile="driving"):
    """
    Chiama TomTom Routing API con departAt per ottenere la stima storica del traffico
    per quel giorno/ora specifici. start_coord e end_coord sono [lon, lat] (GeoJSON).
    Restituisce level 1-5, delay_min e flow_ratio.
    """
    lat1, lon1 = start_coord[1], start_coord[0]
    lat2, lon2 = end_coord[1],   end_coord[0]
    mode       = TOMTOM_MODES.get(profile, "car")
    depart_str = depart_dt.strftime("%Y-%m-%dT%H:%M:%S")

    r = requests.get(
        f"{TOMTOM_ROUTING}/{lat1},{lon1}:{lat2},{lon2}/json",
        params={
            "departAt":   depart_str,
            "traffic":    "true",
            "travelMode": mode,
            "key":        api_key,
        },
        timeout=12,
    )
    r.raise_for_status()
    summary = r.json()["routes"][0]["summary"]

    travel_time  = summary.get("travelTimeInSeconds", 0)
    no_traffic   = summary.get("noTrafficTravelTimeInSeconds", 0)
    historic     = summary.get("historicTrafficTravelTimeInSeconds", 0) or travel_time
    delay        = summary.get("trafficDelayInSeconds", 0)

    # Preferisci noTraffic vs historic se disponibili, altrimenti travelTime - delay
    if no_traffic > 0 and historic > 0:
        ratio = no_traffic / historic
    elif travel_time > 0:
        ratio = max(0.0, (travel_time - delay) / travel_time)
    else:
        ratio = 1.0

    if   ratio > 0.93: level = 1
    elif ratio > 0.80: level = 2
    elif ratio > 0.65: level = 3
    elif ratio > 0.50: level = 4
    else:              level = 5

    return {
        "level":      level,
        "delay_min":  round(delay / 60),
        "flow_ratio": round(ratio, 2),
    }


def _blend_traffic(tomtom_level, heuristic_level):
    """
    Combina il livello TomTom storico (del tratto, 70%) con la variazione
    euristica per orario (30%) per ottenere la stima punto per punto.
    """
    return max(1, min(5, round(0.70 * tomtom_level + 0.30 * heuristic_level)))


@app.route("/api/ev/vehicles")
def ev_vehicles():
    return jsonify(EV_VEHICLES)


@app.route("/api/ev/charging-stops", methods=["POST"])
def ev_charging_stops():
    data          = request.get_json() or {}
    geometry      = data.get("geometry")
    ev            = data.get("ev", {})
    battery       = data.get("battery", {})
    connector_ids = data.get("connector_ids", [33])
    min_kw        = int(data.get("min_kw", 50))
    interval_km   = max(5, min(50, int(data.get("interval_km", 20))))

    if not geometry or not ev or not battery:
        return jsonify({"error": "Parametri mancanti"}), 400
    try:
        stops = _find_ev_stops(geometry, ev, battery, connector_ids, min_kw, interval_km)
        return jsonify(stops)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _find_ev_stops(geometry, ev, battery, connector_ids, min_kw, interval_km=20):
    coords         = geometry.get("coordinates", [])
    consumption_km = ev["consumption"] / 100
    battery_kwh    = float(ev["battery_kwh"])
    max_dc_kw      = float(ev["max_dc_kw"])
    current_kwh    = battery["start_pct"] / 100 * battery_kwh
    min_kwh        = battery["min_pct"]   / 100 * battery_kwh
    max_kwh        = battery["max_pct"]   / 100 * battery_kwh
    alert_kwh      = min_kwh + battery_kwh * 0.15

    # Corridor width: half the sampling interval, capped between 3 and 10 km
    corridor_km  = min(max(interval_km / 2.0, 3.0), 10.0)
    # Search window before alert: 3 sample intervals or 15% of full range
    full_range_km = battery_kwh / consumption_km
    window_km     = max(interval_km * 3, full_range_km * 0.15)

    # Phase 1 – walk geometry, collecting per-stop:
    #   · primary window: last window_km before alert (optimal zone)
    #   · full safe zone: from last charge point to alert (anticipate/posticipate fallback)
    #   · raw route coords (dense OSRM geometry) for accurate distance-to-road
    stops_cands      = []   # primary window sample points
    stops_window_pts = []   # primary window raw route coords
    stops_zone_cands = []   # full safe zone sample points (for expanded search)
    stops_zone_pts   = []   # full safe zone raw route coords

    candidates  = []   # sample points since last charge
    zone_pts    = []   # route coords since last charge (lat, lon, km)
    cumulative  = 0.0
    next_sample = float(interval_km)
    alert_fired = False   # True once current_kwh <= alert_kwh
    alert_km    = 0.0     # cumulative km when alert fired

    def _finalize_stop(cur_lat, cur_lon):
        """Append one charging stop from accumulated candidates/zone_pts."""
        # Primary window: last window_km before alert point
        window_start = alert_km - window_km
        w_cands = [c for c in candidates if window_start <= c[3] <= alert_km]
        w_pts   = [(z[0], z[1]) for z in zone_pts if window_start <= z[2] <= alert_km]

        # Full safe zone: from last charge → current position (includes posticipate)
        z_cands = list(candidates)
        z_pts   = [(z[0], z[1]) for z in zone_pts]
        if len(z_pts) > 600:
            step  = len(z_pts) // 600 + 1
            z_pts = z_pts[::step]

        if not w_cands:
            w_cands = [(cur_lat, cur_lon, 0.0, round(alert_km, 1))]
        if not w_pts:
            w_pts = z_pts or [(cur_lat, cur_lon)]
        if not z_cands:
            z_cands = w_cands
        if not z_pts:
            z_pts = [(cur_lat, cur_lon)]

        stops_cands.append(w_cands[-10:])
        stops_window_pts.append(w_pts)
        stops_zone_cands.append(z_cands)
        stops_zone_pts.append(z_pts)

    for i in range(1, len(coords)):
        p0  = coords[i - 1]
        p1  = coords[i]
        seg = _haversine(p0[0], p0[1], p1[0], p1[1])
        if seg == 0:
            continue
        prev_cum = cumulative
        prev_kwh = current_kwh
        cumulative  += seg
        current_kwh -= seg * consumption_km

        zone_pts.append((p1[1], p1[0], cumulative))

        while next_sample <= cumulative:
            frac  = (next_sample - prev_cum) / seg
            s_lon = p0[0] + frac * (p1[0] - p0[0])
            s_lat = p0[1] + frac * (p1[1] - p0[1])
            s_kwh = max(prev_kwh - frac * seg * consumption_km, 0.0)
            candidates.append((s_lat, s_lon, s_kwh, round(next_sample, 1)))
            next_sample += interval_km

        # Mark when we enter the alert zone (optimal charge window begins)
        if not alert_fired and current_kwh <= alert_kwh:
            alert_fired = True
            alert_km    = cumulative

        # Finalize stop only when we reach the true minimum (full posticipate zone)
        if alert_fired and current_kwh <= min_kwh:
            _finalize_stop(p1[1], p1[0])
            candidates  = []
            zone_pts    = []
            next_sample = cumulative + interval_km
            current_kwh = max_kwh
            alert_fired = False
            alert_km    = 0.0

    # End of route: if alert fired but min_kwh never reached, still add the stop
    if alert_fired and candidates:
        _finalize_stop(coords[-1][1], coords[-1][0])

    if not stops_cands:
        return []

    # Phase 2 – resolve each stop via corridor search along the route
    def _build_result(station, loc, fallback=False, fallback_nofilter=False):
        lat, lon, arr_kwh, km = loc
        kw     = min(max_dc_kw, station.get("max_kw") or max_dc_kw)
        slat   = station.get("lat") or lat
        slon   = station.get("lon") or lon
        detour = round(_haversine(lon, lat, slon, slat), 1)
        result = {**station,
                  "battery_arrival_pct": round(arr_kwh / battery_kwh * 100, 1),
                  "battery_after_pct":   round(max_kwh  / battery_kwh * 100, 1),
                  "charge_time_min":     _calc_charge_time(arr_kwh, max_kwh, battery_kwh, kw),
                  "route_km":            km,
                  "detour_km":           detour}
        if fallback:          result["fallback"]          = True
        if fallback_nofilter: result["fallback_nofilter"] = True
        return result

    def _score_stations(stations, cands, window_pts, fallback=False, fallback_nofilter=False):
        """
        Score each station by its true detour from the route:
        - best_d = min distance from station to any raw route coord in the window
          (uses the dense OSRM geometry, not just the coarse sample points)
        - detour_km = best_d * 2  (round trip)
        - battery check uses nearest sample point for energy estimation
        - Sort: min detour first, then earliest position on route
        """
        results = []
        for st in stations:
            slat = st.get("lat")
            slon = st.get("lon")
            if slat is None or slon is None:
                continue

            # True distance from station to the road (dense geometry)
            if not window_pts:
                best_d = _haversine(cands[-1][1], cands[-1][0], slon, slat)
            else:
                best_d = min(_haversine(wlat, wlon, slon, slat)
                             for wlat, wlon in window_pts)

            # Nearest sample point → battery estimation + route_km
            best_cand_d = float("inf")
            best_loc    = None
            for loc in cands:
                d = _haversine(loc[1], loc[0], slon, slat)
                if d < best_cand_d:
                    best_cand_d = d
                    best_loc    = loc
            lat_r, lon_r, arr_kwh, km = best_loc
            bat_at_station = arr_kwh - best_d * consumption_km
            if bat_at_station < min_kwh:
                continue                       # unreachable with available charge

            kw    = min(max_dc_kw, st.get("max_kw") or max_dc_kw)
            entry = {
                **st,
                "battery_arrival_pct": round(bat_at_station / battery_kwh * 100, 1),
                "battery_after_pct":   round(max_kwh / battery_kwh * 100, 1),
                "charge_time_min":     _calc_charge_time(bat_at_station, max_kwh, battery_kwh, kw),
                "route_km":            km,
                "detour_km":           round(best_d * 2, 1),
            }
            if fallback:          entry["fallback"]          = True
            if fallback_nofilter: entry["fallback_nofilter"] = True
            results.append(entry)

        results.sort(key=lambda c: (c["detour_km"], c["route_km"]))
        return results

    def _ocm_scored(bbox, conn_ids, pw, cands, pts, fallback=False, nf=False):
        """Query OCM with bbox and score results. Returns sorted list."""
        sts = _find_ocm_bbox(bbox, conn_ids, pw)
        return _score_stations(sts, cands, pts, fallback=fallback, fallback_nofilter=nf)

    def _make_bbox(cands_or_pts, buf_deg):
        lats = [c[0] for c in cands_or_pts]
        lons = [c[1] for c in cands_or_pts]
        return (min(lats) - buf_deg, min(lons) - buf_deg,
                max(lats) + buf_deg, max(lons) + buf_deg)

    def resolve_stop(cands, window_pts, zone_cands, zone_pts):
        buf  = corridor_km / 111.0
        w_bbox = _make_bbox(cands, buf)
        z_bbox = _make_bbox(zone_cands, buf)

        # ── Primary search: optimal window (last window_km before alert) ──────
        # Tier 1: with connector/power filters
        scored = _ocm_scored(w_bbox, connector_ids, min_kw, cands, window_pts)
        # Tier 2: same stations, no reachability restriction (fallback badge)
        if not scored:
            scored = _ocm_scored(w_bbox, connector_ids, min_kw,
                                 cands, window_pts, fallback=True)
        # Tier 3: no connector/power filters
        if not scored:
            scored = _ocm_scored(w_bbox, [], 0, cands, window_pts,
                                 fallback=True, nf=True)

        if scored:
            top3 = scored[:3]
            return {**top3[0], "candidates": top3}

        # ── Extended search: full safe zone (anticipate or posticipate) ───────
        # Tier 4: full zone, with filters
        scored = _ocm_scored(z_bbox, connector_ids, min_kw,
                             zone_cands, zone_pts, fallback=True)
        # Tier 5: full zone, no filters
        if not scored:
            scored = _ocm_scored(z_bbox, [], 0, zone_cands, zone_pts,
                                 fallback=True, nf=True)

        if scored:
            top3 = scored[:3]
            return {**top3[0], "candidates": top3, "extended_search": True}

        # ── Last resort: Overpass/OSM + single-point OCM ──────────────────────
        last = zone_cands[-1]
        for st in [
            _find_overpass_station(last[0], last[1], radius_m=50000),
            _find_ocm_station(last[0], last[1], [], 0, radius_km=50),
        ]:
            if st:
                scored = _score_stations([st], zone_cands, zone_pts,
                                         fallback=True, fallback_nofilter=True)
                if scored:
                    top3 = scored[:3]
                    return {**top3[0], "candidates": top3, "extended_search": True}

        lat, lon, arr_kwh, km = zone_cands[-1]
        return {"error": True, "lat": lat, "lon": lon,
                "battery_arrival_pct": round(arr_kwh / battery_kwh * 100, 1),
                "route_km": km, "message": "Nessuna stazione di ricarica trovata"}

    with ThreadPoolExecutor(max_workers=min(len(stops_cands), 5)) as ex:
        return list(ex.map(
            lambda p: resolve_stop(*p),
            zip(stops_cands, stops_window_pts, stops_zone_cands, stops_zone_pts),
        ))


def _calc_charge_time(current_kwh, target_kwh, battery_kwh, charger_kw):
    energy  = target_kwh - current_kwh
    if energy <= 0:
        return 0
    p80     = 0.80 * battery_kwh
    kw      = max(charger_kw, 1)
    if target_kwh <= p80:
        return round(energy / kw * 60)
    if current_kwh >= p80:
        return round(energy / (kw * 0.5) * 60)
    to_80   = p80 - current_kwh
    above80 = target_kwh - p80
    return round((to_80 / kw + above80 / (kw * 0.5)) * 60)


def _find_ocm_station(lat, lon, connector_ids, min_kw, radius_km=20):
    params = {
        "output":       "json",
        "latitude":     lat,
        "longitude":    lon,
        "distance":     radius_km,
        "distanceunit": "km",
        "maxresults":   5,
        "compact":      "true",
        "verbose":      "false",
    }
    if OCM_API_KEY:
        params["key"] = OCM_API_KEY
    if connector_ids:
        params["connectiontypeid"] = ",".join(str(c) for c in connector_ids)
    if min_kw and min_kw > 0:
        params["minpowerkw"] = min_kw
    try:
        resp = requests.get(OCM_URL, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
    except Exception:
        return None

    if not data or not isinstance(data, list):
        return None

    best  = data[0]
    addr  = best.get("AddressInfo", {})
    conns = best.get("Connections") or []
    max_kw = max((c.get("PowerKW") or 0) for c in conns) if conns else 0
    conn_names = list({c.get("ConnectionType", {}).get("Title", "")
                       for c in conns if c.get("ConnectionType")})

    return {
        "lat":        addr.get("Latitude"),
        "lon":        addr.get("Longitude"),
        "name":       addr.get("Title", "Stazione di ricarica"),
        "address":    f"{addr.get('AddressLine1', '')}, {addr.get('Town', '')}".strip(", "),
        "max_kw":     round(float(max_kw), 1),
        "connectors": conn_names[:3],
        "ocm_id":     best.get("ID"),
    }


def _parse_ocm_item(item):
    addr  = item.get("AddressInfo", {})
    conns = item.get("Connections") or []
    max_kw = max((c.get("PowerKW") or 0) for c in conns) if conns else 0
    conn_names = list({c.get("ConnectionType", {}).get("Title", "")
                       for c in conns if c.get("ConnectionType")})
    return {
        "lat":        addr.get("Latitude"),
        "lon":        addr.get("Longitude"),
        "name":       addr.get("Title", "Stazione di ricarica"),
        "address":    f"{addr.get('AddressLine1', '')}, {addr.get('Town', '')}".strip(", "),
        "max_kw":     round(float(max_kw), 1),
        "connectors": conn_names[:3],
        "ocm_id":     item.get("ID"),
    }


def _find_ocm_bbox(bbox, connector_ids, min_kw, maxresults=50):
    """Query OCM with a bounding box — returns all stations in the zone at once."""
    lat_min, lon_min, lat_max, lon_max = bbox
    params = {
        "output":      "json",
        "boundingbox": f"({lat_min},{lon_min}),({lat_max},{lon_max})",
        "maxresults":  maxresults,
        "compact":     "true",
        "verbose":     "false",
    }
    if OCM_API_KEY:
        params["key"] = OCM_API_KEY
    if connector_ids:
        params["connectiontypeid"] = ",".join(str(c) for c in connector_ids)
    if min_kw and min_kw > 0:
        params["minpowerkw"] = min_kw
    try:
        resp = requests.get(OCM_URL, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        if not isinstance(data, list):
            return []
        return [_parse_ocm_item(s) for s in data
                if s.get("AddressInfo", {}).get("Latitude")]
    except Exception:
        return []


def _closest_on_route(stations, cands, max_dist_km):
    """Return (station, nearest_candidate_loc) for the station closest to any route candidate."""
    best_dist    = max_dist_km
    best_station = None
    best_loc     = None
    for station in stations:
        slat = station.get("lat")
        slon = station.get("lon")
        if slat is None or slon is None:
            continue
        for loc in cands:
            d = _haversine(loc[1], loc[0], slon, slat)
            if d < best_dist:
                best_dist    = d
                best_station = station
                best_loc     = loc
    return best_station, best_loc


def _find_overpass_station(lat, lon, radius_m=50000):
    """Query OSM via Overpass for the nearest EV charging station — no API key needed."""
    query = (
        f"[out:json][timeout:25];"
        f"("
        f'node["amenity"="charging_station"](around:{radius_m},{lat},{lon});'
        f'way["amenity"="charging_station"](around:{radius_m},{lat},{lon});'
        f");"
        f"out center 5;"
    )
    try:
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers=HEADERS,
            timeout=30,
        )
        data = resp.json()
    except Exception:
        return None

    elements = data.get("elements", [])
    if not elements:
        return None

    best = elements[0]
    if best.get("type") == "way":
        elt_lat = best.get("center", {}).get("lat", lat)
        elt_lon = best.get("center", {}).get("lon", lon)
    else:
        elt_lat = best.get("lat", lat)
        elt_lon = best.get("lon", lon)

    tags    = best.get("tags", {})
    name    = tags.get("name") or tags.get("operator") or "Stazione di ricarica (OSM)"
    address = ", ".join(p for p in [tags.get("addr:street", ""), tags.get("addr:city", "")] if p)

    max_kw = 0.0
    for key in ("maxpower", "socket:type2_combo:output", "socket:chademo:output", "socket:type2:output"):
        raw = tags.get(key, "")
        if raw:
            try:
                val = float(re.sub(r"[^\d.]", "", raw))
                if "W" in raw and "kW" not in raw:
                    val /= 1000
                max_kw = max(max_kw, val)
            except (ValueError, TypeError):
                pass

    connectors = []
    for sock_key, label in [("socket:type2_combo", "CCS"), ("socket:chademo", "CHAdeMO"), ("socket:type2", "Type 2")]:
        if tags.get(sock_key):
            connectors.append(label)

    return {
        "lat":        elt_lat,
        "lon":        elt_lon,
        "name":       name,
        "address":    address or "Indirizzo non disponibile",
        "max_kw":     round(max_kw, 1),
        "connectors": connectors or ["Tipo non specificato"],
        "ocm_id":     None,
    }


@app.route("/api/import-gmaps", methods=["POST"])
def import_gmaps():
    """
    Riceve un link Google Maps (anche short URL maps.app.goo.gl / Firebase Dynamic Link),
    segue redirect HTTP e JS, bypassa la pagina consenso GDPR,
    estrae le tappe e le geocodifica.
    """
    data = request.get_json() or {}
    url  = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL non fornito"}), 400
    if not url.startswith("http"):
        return jsonify({"error": "Inserisci un URL valido (inizia con http)"}), 400

    browser_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        # Cookie che pre-accetta il consenso GDPR di Google (evita il redirect a consent.google.com)
        session = requests.Session()
        session.cookies.set("SOCS",    "CAI",       domain=".google.com")
        session.cookies.set("CONSENT", "YES+cb.it", domain=".google.com")

        r         = session.get(url, allow_redirects=True, timeout=14, headers=browser_headers)
        final_url = r.url

        # Se finiti su pagina consenso, estrai il vero URL dal parametro continue=
        if "consent.google.com" in final_url or "accounts.google.com" in final_url:
            m = re.search(r'[?&]continue=([^&"\']+)', r.text + "?" + r.url)
            if m:
                final_url = unquote_plus(m.group(1))

        # Se ancora niente Google Maps, cerca nell'HTML (Firebase Dynamic Link / JS redirect)
        if "google.com/maps" not in final_url and "maps.google.com" not in final_url:
            final_url = _extract_maps_url_from_html(r.text) or final_url

    except requests.RequestException as e:
        return jsonify({"error": f"Impossibile aprire il link: {e}"}), 400

    raw_wps = _parse_gmaps_url(final_url)
    if not raw_wps:
        return jsonify({
            "error": (
                "Nessuna tappa trovata nel link. "
                "Condividi un percorso con Indicazioni stradali da Google Maps "
                "(non solo un luogo). "
                f"URL risolto: {final_url[:150]}"
            )
        }), 400

    # Geocodifica le tappe che non hanno già coordinate
    def resolve(wp):
        if wp.get("lat") is not None:
            try:
                rev = requests.get(
                    f"{NOMINATIM_URL}/reverse",
                    params={"lat": wp["lat"], "lon": wp["lon"], "format": "json"},
                    headers=HEADERS, timeout=8,
                )
                rev.raise_for_status()
                d    = rev.json()
                name = ", ".join(d.get("display_name", "").split(",")[:2]).strip()
            except Exception:
                name = f"{wp['lat']:.5f}, {wp['lon']:.5f}"
            return {"name": name, "lat": wp["lat"], "lon": wp["lon"]}
        else:
            name = wp.get("name", "")
            try:
                geo = requests.get(
                    f"{NOMINATIM_URL}/search",
                    params={"q": name, "format": "json", "limit": 1},
                    headers=HEADERS, timeout=8,
                )
                geo.raise_for_status()
                places = geo.json()
                if places:
                    return {
                        "name":  name,
                        "lat":   float(places[0]["lat"]),
                        "lon":   float(places[0]["lon"]),
                    }
            except Exception:
                pass
            return {"name": name, "lat": None, "lon": None, "error": "Non trovato"}

    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(resolve, raw_wps))

    return jsonify(results)


# ─── helpers per parsing URL Google Maps ────────────────────────────────────

def _extract_maps_url_from_html(html):
    """
    Cerca l'URL Google Maps nell'HTML di una pagina intermedia
    (Firebase Dynamic Link, pagina consenso, redirect JS).
    """
    patterns = [
        # Link diretto /maps/dir/ — formato più specifico prima
        r'(https://(?:www\.)?google\.com/maps/dir/[^"\'<>\s]{10,})',
        # Qualsiasi URL Google Maps
        r'(https://(?:www\.)?google\.com/maps/[^"\'<>\s]{10,})',
        # JSON embedded: "link":"..."
        r'"link"\s*:\s*"(https://[^"]*google[^"]*maps[^"]*)"',
        # Firebase fallback_link
        r'fallback_link["\s:=]+["\']?(https://[^"\'<>\s]+)',
        # Meta refresh
        r'content=["\']0;\s*url=(https://[^"\'<>\s]+)',
        # deep_link_value nei Firebase Dynamic Links
        r'deep_link_value=([^&"\'<>\s]+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            candidate = unquote_plus(m.group(1))
            if "google.com/maps" in candidate or "maps.google.com" in candidate:
                return candidate
    return None


def _parse_gmaps_url(url):
    """Estrae waypoints da un URL Google Maps in tutti i formati noti."""
    parsed = urlparse(url)
    path   = parsed.path
    params = parse_qs(parsed.query)

    # ── Formato /maps/dir/Partenza/Tappa/Arrivo ──────────────────────────────
    if "/maps/dir/" in path:
        dir_part = path.split("/maps/dir/", 1)[1].rstrip("/")
        if "/@" in dir_part:
            dir_part = dir_part.split("/@")[0]
        parts = [unquote_plus(p).strip() for p in dir_part.split("/") if p.strip()]
        waypoints = []
        for part in parts:
            if part.startswith("data=") or part.startswith("!"):
                break
            wp = _parse_gmaps_waypoint(part)
            if wp:
                waypoints.append(wp)
        if waypoints:
            return waypoints

    # ── Formato ?api=1&origin=A&destination=B&waypoints=C|D ─────────────────
    if "origin" in params or "destination" in params:
        origin  = unquote_plus(params.get("origin",      [""])[0])
        dest    = unquote_plus(params.get("destination", [""])[0])
        wps_raw = unquote_plus(params.get("waypoints",   [""])[0])
        mid     = [w for w in wps_raw.split("|") if w] if wps_raw else []
        waypoints = []
        for loc in [origin] + mid + [dest]:
            if loc:
                wp = _parse_gmaps_waypoint(loc)
                if wp:
                    waypoints.append(wp)
        if waypoints:
            return waypoints

    # ── Formato vecchio: ?saddr=A&daddr=B ───────────────────────────────────
    if "saddr" in params or "daddr" in params:
        origin = unquote_plus(params.get("saddr", [""])[0])
        dest   = unquote_plus(params.get("daddr", [""])[0])
        waypoints = []
        for loc in [origin, dest]:
            if loc:
                wp = _parse_gmaps_waypoint(loc)
                if wp:
                    waypoints.append(wp)
        if waypoints:
            return waypoints

    # ── Formato ?q=LUOGO (singolo luogo) ─────────────────────────────────────
    if "q" in params:
        q  = unquote_plus(params["q"][0])
        wp = _parse_gmaps_waypoint(q)
        if wp:
            return [wp]

    # ── Formato /maps/place/NOME/@lat,lon ────────────────────────────────────
    if "/maps/place/" in path:
        place_raw = path.split("/maps/place/", 1)[1].split("/")[0]
        name      = unquote_plus(place_raw).replace("+", " ")
        coord_m   = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", path)
        if coord_m:
            return [{"lat": float(coord_m.group(1)), "lon": float(coord_m.group(2))}]
        if name:
            return [{"name": name}]

    # ── Ultime speranze: coordinate nella parte @ dell'URL ───────────────────
    coord_m = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if coord_m:
        return [{"lat": float(coord_m.group(1)), "lon": float(coord_m.group(2))}]

    return []


def _parse_gmaps_waypoint(text):
    """Parsa una singola stringa waypoint: lat,lon oppure nome luogo."""
    text = text.strip()
    if not text:
        return None
    m = re.match(r"^(-?\d{1,3}(?:\.\d+)?),\s*(-?\d{1,3}(?:\.\d+)?)$", text)
    if m:
        return {"lat": float(m.group(1)), "lon": float(m.group(2))}
    return {"name": text}


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
