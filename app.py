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
HEADERS        = {"User-Agent": "TravelPlannerApp/1.0 (educational project)"}

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
    data = request.get_json() or {}
    waypoints = data.get("waypoints", [])
    profile = data.get("profile", "driving")
    curves = int(data.get("curves", 3))

    if len(waypoints) < 2:
        return jsonify({"error": "Servono almeno 2 tappe"}), 400

    try:
        if profile == "motorcycle":
            result = _call_valhalla(waypoints, curves)
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
