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
    total_days = calendar.monthrange(year, month_num)[1]

    return [
        date(year, month_num, day).isoformat()
        for day in range(1, total_days + 1)
    ]


def format_duration(minutes):
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def parse_nonstop_flights(data, origin, destination, departure_date):
    google_flights_url = data.get("search_metadata", {}).get("google_flights_url", "N/A")
    price_insights = data.get("price_insights", {})

    all_results = data.get("best_flights", []) + data.get("other_flights", [])
    nonstop_results = []

    for option in all_results:
        legs = option.get("flights", [])
        price = option.get("price")

        if price is None or len(legs) != 1:
            continue

        leg = legs[0]

        nonstop_results.append({
            "price": float(price),
            "travel_date": departure_date,
            "airline": leg.get("airline", "N/A"),
            "flight_number": leg.get("flight_number", "N/A"),
            "total_duration": format_duration(option.get("total_duration", leg.get("duration", 0))),
            "departure_airport": leg.get("departure_airport", {}).get("name", origin),
            "departure_time": leg.get("departure_airport", {}).get("time", "N/A"),
            "arrival_airport": leg.get("arrival_airport", {}).get("name", destination),
            "arrival_time": leg.get("arrival_airport", {}).get("time", "N/A"),
            "stops": 0,
            "price_level": price_insights.get("price_level", "N/A"),
            "typical_price_range": price_insights.get("typical_price_range", []),
            "google_flights_url": google_flights_url
        })

    return nonstop_results


def get_nonstop_flights_for_date(origin, destination, departure_date):
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

    response = requests.get("https://serpapi.com/search", params=params, timeout=60)
    response.raise_for_status()

    return parse_nonstop_flights(response.json(), origin, destination, departure_date)


def get_cheapest_nonstop_for_month(origin, destination, month):
    print(f"Searching cheapest nonstop flight for {origin} to {destination} in {month}...", flush=True)

    cheapest = None
    dates_checked = 0
    nonstop_options_found = 0

    for departure_date in get_dates_in_month(month):
        try:
            dates_checked += 1
            nonstop_flights = get_nonstop_flights_for_date(origin, destination, departure_date)
            nonstop_options_found += len(nonstop_flights)

            for flight in nonstop_flights:
                if cheapest is None or flight["price"] < cheapest["price"]:
                    cheapest = flight

        except Exception as e:
            print(f"Error checking {departure_date}: {e}", flush=True)

    print(
        f"Completed {origin}-{destination} {month}. "
        f"Dates checked: {dates_checked}, nonstop options found: {nonstop_options_found}",
        flush=True
    )

    return cheapest


def send_email(origin, destination, month, old_price, flight):
    new_price = flight["price"]
    savings = old_price - new_price

    typical_range = flight.get("typical_price_range", [])
    typical_range_text = (
        f"${typical_range[0]} - ${typical_range[1]}"
        if len(typical_range) == 2
        else "N/A"
    )

    msg = EmailMessage()
    msg["Subject"] = f"Flight Price Drop: {origin} to {destination}"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

A cheaper nonstop flight was found.

Route: {origin} to {destination}
Search Month: {month}

Cheapest Travel Date: {flight["travel_date"]}
Current Cheapest Price: ${new_price}
Previous Saved Price: ${old_price}
You Save: ${savings}

Airline: {flight["airline"]}
Flight Number: {flight["flight_number"]}
Stops: 0
Duration: {flight["total_duration"]}

Departure Airport: {flight["departure_airport"]}
Departure Time: {flight["departure_time"]}

Arrival Airport: {flight["arrival_airport"]}
Arrival Time: {flight["arrival_time"]}

Google Price Insight: {flight["price_level"]}
Typical Price Range: {typical_range_text}

Google Flights Link:
{flight["google_flights_url"]}

Please verify final price and availability before booking.
""")

    print("Sending email...", flush=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print("Email sent successfully.", flush=True)


def check_prices():
    print("Checking monthly cheapest nonstop flight prices...", flush=True)

    state = load_json_file(STATE_FILE, {})
    tracked_flights = load_json_file(FLIGHTS_FILE, [])

    if not tracked_flights:
        print("No flights found in flights.json", flush=True)
        return

    for tracked in tracked_flights:
        origin = tracked["origin"]
        destination = tracked["destination"]
        month = tracked["month"]

        key = f"{origin}-{destination}-{month}-CHEAPEST-NONSTOP"

        cheapest = get_cheapest_nonstop_for_month(origin, destination, month)

        if cheapest is None:
            print(f"No nonstop flights found for {origin} to {destination} in {month}", flush=True)
            continue

        current_price = cheapest["price"]
        old_price = state.get(key)

        print(
            f"Cheapest nonstop for {origin}-{destination} {month}: "
            f"${current_price} on {cheapest['travel_date']} via {cheapest['airline']} {cheapest['flight_number']}",
            flush=True
        )

        if old_price is None:
            state[key] = current_price
            print("Initial price saved.", flush=True)

        elif current_price < old_price:
            send_email(origin, destination, month, old_price, cheapest)
            state[key] = current_price
            print("Price dropped. Email sent.", flush=True)

        else:
            print("No price drop.", flush=True)

    save_state(state)


if __name__ == "__main__":
    print("Program started", flush=True)
    check_prices()
    print("Program finished", flush=True)
