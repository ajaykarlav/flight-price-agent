import os
import json
import smtplib
import requests
import calendar
from datetime import date
from email.message import EmailMessage

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
ALERT_TO_EMAIL = os.getenv("ALERT_TO_EMAIL")

STATE_FILE = "price_state.json"
FLIGHTS_FILE = "flights.json"


def load_json_file(filename, default):
    if not os.path.exists(filename):
        return default
    with open(filename, "r") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=2)


def get_dates_in_month(month):
    year, month_num = map(int, month.split("-"))
    days = calendar.monthrange(year, month_num)[1]
    return [date(year, month_num, day).isoformat() for day in range(1, days + 1)]


def format_duration(minutes):
    return f"{minutes // 60}h {minutes % 60}m"


def build_search_dates(tracked):
    if tracked["trip_type"] == "oneway":
        if "date" in tracked:
            return [{"departure_date": tracked["date"], "return_date": None}]
        if "month" in tracked:
            return [{"departure_date": d, "return_date": None} for d in get_dates_in_month(tracked["month"])]

    if tracked["trip_type"] == "roundtrip":
        return [{
            "departure_date": tracked["departure_date"],
            "return_date": tracked["return_date"]
        }]

    raise ValueError("Invalid trip_type. Use 'oneway' or 'roundtrip'.")


def search_google_flights(origin, destination, trip_type, departure_date, return_date=None):
    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "type": "1" if trip_type == "roundtrip" else "2",
        "adults": "1",
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": SERPAPI_KEY
    }

    if trip_type == "roundtrip":
        params["return_date"] = return_date

    response = requests.get("https://serpapi.com/search", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def parse_nonstop_results(data, origin, destination, departure_date, return_date, trip_type):
    google_flights_url = data.get("search_metadata", {}).get("google_flights_url", "N/A")
    price_insights = data.get("price_insights", {})

    all_results = data.get("best_flights", []) + data.get("other_flights", [])
    results = []

    for option in all_results:
        price = option.get("price")
        legs = option.get("flights", [])

        if price is None or not legs:
            continue

        # Nonstop only: one leg for one-way; for roundtrip SerpAPI may still return the combined itinerary.
        # This keeps only simple nonstop-looking itineraries.
        if trip_type == "oneway" and len(legs) != 1:
            continue

        first_leg = legs[0]
        last_leg = legs[-1]

        if len(legs) > 2:
            continue

        results.append({
            "price": float(price),
            "trip_type": trip_type,
            "departure_date": departure_date,
            "return_date": return_date,
            "airline": first_leg.get("airline", "N/A"),
            "flight_number": " + ".join(leg.get("flight_number", "N/A") for leg in legs),
            "duration": format_duration(option.get("total_duration", first_leg.get("duration", 0))),
            "departure_airport": first_leg.get("departure_airport", {}).get("name", origin),
            "departure_time": first_leg.get("departure_airport", {}).get("time", "N/A"),
            "arrival_airport": last_leg.get("arrival_airport", {}).get("name", destination),
            "arrival_time": last_leg.get("arrival_airport", {}).get("time", "N/A"),
            "price_level": price_insights.get("price_level", "N/A"),
            "typical_price_range": price_insights.get("typical_price_range", []),
            "google_flights_url": google_flights_url
        })

    return results


def find_cheapest_flight(tracked):
    origin = tracked["origin"]
    destination = tracked["destination"]
    trip_type = tracked["trip_type"]

    cheapest = None
    searches = build_search_dates(tracked)

    for search in searches:
        departure_date = search["departure_date"]
        return_date = search["return_date"]

        print(f"Checking {origin}-{destination}: {departure_date} {return_date or ''}", flush=True)

        try:
            data = search_google_flights(origin, destination, trip_type, departure_date, return_date)
            flights = parse_nonstop_results(data, origin, destination, departure_date, return_date, trip_type)

            for flight in flights:
                if cheapest is None or flight["price"] < cheapest["price"]:
                    cheapest = flight

        except Exception as e:
            print(f"Error checking {departure_date}: {e}", flush=True)

    return cheapest


def make_state_key(tracked):
    origin = tracked["origin"]
    destination = tracked["destination"]
    trip_type = tracked["trip_type"]

    if trip_type == "oneway":
        period = tracked.get("date") or tracked.get("month")
        return f"{origin}-{destination}-{period}-ONEWAY-NONSTOP"

    return f"{origin}-{destination}-{tracked['departure_date']}-{tracked['return_date']}-ROUNDTRIP-NONSTOP"


def send_email(tracked, old_price, flight):
    new_price = flight["price"]
    savings = old_price - new_price

    typical_range = flight.get("typical_price_range", [])
    typical_range_text = f"${typical_range[0]} - ${typical_range[1]}" if len(typical_range) == 2 else "N/A"

    msg = EmailMessage()
    msg["Subject"] = f"Flight Price Drop: {tracked['origin']} to {tracked['destination']}"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

A cheaper flight was found.

Route: {tracked['origin']} to {tracked['destination']}
Trip Type: {flight['trip_type']}

Departure Date: {flight['departure_date']}
Return Date: {flight['return_date'] or 'N/A'}

Current Price: ${new_price}
Previous Saved Price: ${old_price}
You Save: ${savings}

Airline: {flight['airline']}
Flight Number(s): {flight['flight_number']}
Duration: {flight['duration']}

Departure Airport: {flight['departure_airport']}
Departure Time: {flight['departure_time']}

Arrival Airport: {flight['arrival_airport']}
Arrival Time: {flight['arrival_time']}

Google Price Insight: {flight['price_level']}
Typical Price Range: {typical_range_text}

Google Flights Link:
{flight['google_flights_url']}

Please verify final price and availability before booking.
""")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print("Email sent successfully.", flush=True)


def check_prices():
    print("Checking flight prices...", flush=True)

    state = load_json_file(STATE_FILE, {})
    tracked_flights = load_json_file(FLIGHTS_FILE, [])

    for tracked in tracked_flights:
        key = make_state_key(tracked)
        cheapest = find_cheapest_flight(tracked)

        if cheapest is None:
            print(f"No flight found for {tracked['origin']} to {tracked['destination']}", flush=True)
            continue

        current_price = cheapest["price"]
        old_price = state.get(key)

        print(f"Cheapest found for {key}: ${current_price}", flush=True)

        if old_price is None:
            state[key] = current_price
            print("Initial price saved.", flush=True)

        elif current_price < old_price:
            send_email(tracked, old_price, cheapest)
            state[key] = current_price
            print("Price dropped. Email sent.", flush=True)

        else:
            print("No price drop.", flush=True)

    save_state(state)


if __name__ == "__main__":
    print("Program started", flush=True)
    check_prices()
    print("Program finished", flush=True)
