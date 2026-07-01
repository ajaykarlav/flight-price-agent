import os
import json
import smtplib
import requests
from email.message import EmailMessage

SERPAPI_KEY = os.getenv("SERPAPI_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
ALERT_TO_EMAIL = os.getenv("ALERT_TO_EMAIL")

STATE_FILE = "price_state.json"

MAX_STOPS = 0

FLIGHTS = [
    {
        "origin": "DFW",
        "destination": "JFK",
        "departure_date": "2026-08"
    }
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    with open(STATE_FILE, "r") as file:
        return json.load(file)


def save_state(state):
    with open(STATE_FILE, "w") as file:
        json.dump(state, file, indent=2)


def format_duration(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def get_cheapest_flight(origin, destination, departure_date):
    print("Calling SerpAPI Google Flights...", flush=True)

    url = "https://serpapi.com/search"

    params = {
        "engine": "google_flights",
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": departure_date,
        "type": "2",
        "adults": "1",
        "currency": "USD",
        "hl": "en",
        "gl": "us",
        "api_key": SERPAPI_KEY
    }

    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()

    google_flights_url = data.get("search_metadata", {}).get("google_flights_url", "N/A")
    price_insights = data.get("price_insights", {})

    best_flights = data.get("best_flights", [])
    other_flights = data.get("other_flights", [])

    def is_nonstop(option):
        legs = option.get("flights", [])
        price = option.get("price")

        return price is not None and len(legs) - 1 == MAX_STOPS

    valid_best = [f for f in best_flights if is_nonstop(f)]
    valid_other = [f for f in other_flights if is_nonstop(f)]

    if valid_best:
        selected = min(valid_best, key=lambda f: f["price"])
        selected_group = "Best Flights - Nonstop"
    elif valid_other:
        selected = min(valid_other, key=lambda f: f["price"])
        selected_group = "Other Flights - Nonstop"
    else:
        print("No nonstop flight found.", flush=True)
        return None

    legs = selected.get("flights", [])
    first_leg = legs[0]
    last_leg = legs[-1]

    flight_numbers = " + ".join(
        leg.get("flight_number", "N/A") for leg in legs
    )

    airlines = " + ".join(
        dict.fromkeys(leg.get("airline", "N/A") for leg in legs)
    )

    return {
        "price": float(selected["price"]),
        "selected_group": selected_group,
        "airlines": airlines,
        "flight_numbers": flight_numbers,
        "stops": 0,
        "total_duration": format_duration(selected.get("total_duration", 0)),
        "departure_airport": first_leg.get("departure_airport", {}).get("name", origin),
        "departure_time": first_leg.get("departure_airport", {}).get("time", "N/A"),
        "arrival_airport": last_leg.get("arrival_airport", {}).get("name", destination),
        "arrival_time": last_leg.get("arrival_airport", {}).get("time", "N/A"),
        "layovers": "None",
        "price_level": price_insights.get("price_level", "N/A"),
        "typical_price_range": price_insights.get("typical_price_range", []),
        "google_flights_url": google_flights_url
    }


def send_email(origin, destination, departure_date, old_price, flight):
    new_price = flight["price"]
    savings = old_price - new_price

    typical_range = flight.get("typical_price_range", [])
    if len(typical_range) == 2:
        typical_range_text = f"${typical_range[0]} - ${typical_range[1]}"
    else:
        typical_range_text = "N/A"

    msg = EmailMessage()
    msg["Subject"] = "Nonstop Flight Price Drop Alert"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

A nonstop Google Flights price drop was found.

Route: {origin} to {destination}
Travel Date: {departure_date}

Current Price: ${new_price}
Previous Lowest Price: ${old_price}
You Save: ${savings}

Selected From: {flight["selected_group"]}

Airline(s): {flight["airlines"]}
Flight(s): {flight["flight_numbers"]}
Stops: {flight["stops"]}
Total Duration: {flight["total_duration"]}
Layovers: {flight["layovers"]}

Departure Airport: {flight["departure_airport"]}
Departure Time: {flight["departure_time"]}

Arrival Airport: {flight["arrival_airport"]}
Arrival Time: {flight["arrival_time"]}

Google Price Insight: {flight["price_level"]}
Typical Price Range: {typical_range_text}

Google Flights Link:
{flight["google_flights_url"]}

Please verify final price and availability before booking because fares can change quickly.
""")

    print("Sending email...", flush=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print("Email sent successfully.", flush=True)


def check_prices():
    print("Checking nonstop flight prices...", flush=True)

    state = load_state()

    for tracked in FLIGHTS:
        origin = tracked["origin"]
        destination = tracked["destination"]
        departure_date = tracked["departure_date"]

        key = f"{origin}-{destination}-{departure_date}-NONSTOP"

        try:
            flight = get_cheapest_flight(origin, destination, departure_date)

            if flight is None:
                print(f"No nonstop flight found for {origin} to {destination}", flush=True)
                continue

            current_price = flight["price"]
            old_price = state.get(key)

            print(
                f"{origin} to {destination} on {departure_date}: "
                f"${current_price}, nonstop, {flight['total_duration']}, {flight['selected_group']}",
                flush=True
            )

            if old_price is None:
                state[key] = current_price
                print("Initial nonstop price saved.", flush=True)

            elif current_price < old_price:
                send_email(origin, destination, departure_date, old_price, flight)
                state[key] = current_price
                print("Nonstop price dropped. Email sent.", flush=True)

            else:
                print("No nonstop price drop.", flush=True)

        except Exception as e:
            print(f"Error checking {origin} to {destination}: {e}", flush=True)

    save_state(state)


if __name__ == "__main__":
    print("Program started", flush=True)
    check_prices()
    print("Program finished", flush=True)
