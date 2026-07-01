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

FLIGHTS = [
    {
        "origin": "DFW",
        "destination": "JFK",
        "departure_date": "2026-08-01"
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
    import json

    print(json.dumps(data, indent=2))

    flights = []
    flights.extend(data.get("best_flights", []))
    flights.extend(data.get("other_flights", []))

    if not flights:
        return None

    cheapest = min(flights, key=lambda f: f.get("price", float("inf")))

    first_leg = cheapest.get("flights", [{}])[0]
    last_leg = cheapest.get("flights", [{}])[-1]

    return {
        "price": float(cheapest.get("price")),
        "airline": first_leg.get("airline", "N/A"),
        "flight_number": first_leg.get("flight_number", "N/A"),
        "departure_airport": first_leg.get("departure_airport", {}).get("name", origin),
        "departure_time": first_leg.get("departure_airport", {}).get("time", "N/A"),
        "arrival_airport": last_leg.get("arrival_airport", {}).get("name", destination),
        "arrival_time": last_leg.get("arrival_airport", {}).get("time", "N/A"),
        "stops": len(cheapest.get("flights", [])) - 1,
        "booking_source": "Google Flights / SerpAPI",
        "search_link": f"https://www.google.com/travel/flights?q=Flights%20from%20{origin}%20to%20{destination}%20on%20{departure_date}"
    }


def send_email(origin, destination, departure_date, old_price, flight):
    new_price = flight["price"]
    savings = old_price - new_price

    msg = EmailMessage()
    msg["Subject"] = "Live Flight Price Drop Alert"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

A live Google Flights price drop was found.

Route: {origin} to {destination}
Travel Date: {departure_date}

Current Price: ${new_price}
Previous Lowest Price: ${old_price}
You Save: ${savings}

Airline: {flight["airline"]}
Flight Number: {flight["flight_number"]}
Stops: {flight["stops"]}

Departure Airport: {flight["departure_airport"]}
Departure Time: {flight["departure_time"]}

Arrival Airport: {flight["arrival_airport"]}
Arrival Time: {flight["arrival_time"]}

Booking Source: {flight["booking_source"]}

Search Link:
{flight["search_link"]}

Please verify final price before booking because fares can change quickly.
""")

    print("Sending email...", flush=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print("Email sent successfully.", flush=True)


def check_prices():
    print("Checking flight prices...", flush=True)

    state = load_state()

    for tracked in FLIGHTS:
        origin = tracked["origin"]
        destination = tracked["destination"]
        departure_date = tracked["departure_date"]

        key = f"{origin}-{destination}-{departure_date}"

        try:
            flight = get_cheapest_flight(origin, destination, departure_date)

            if flight is None:
                print(f"No live flight found for {origin} to {destination}", flush=True)
                continue

            current_price = flight["price"]
            old_price = state.get(key)

            print(
                f"{origin} to {destination} on {departure_date}: ${current_price}",
                flush=True
            )

            if old_price is None:
                state[key] = current_price
                print("Initial live price saved.", flush=True)

            elif current_price < old_price:
                send_email(origin, destination, departure_date, old_price, flight)
                state[key] = current_price
                print("Price dropped. Email sent.", flush=True)

            else:
                print("No price drop.", flush=True)

        except Exception as e:
            print(f"Error checking {origin} to {destination}: {e}", flush=True)

    save_state(state)


if __name__ == "__main__":
    print("Program started", flush=True)
    check_prices()
    print("Program finished", flush=True)
