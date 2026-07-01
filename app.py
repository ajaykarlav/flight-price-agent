import os
import json
import smtplib
import requests
from email.message import EmailMessage

TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
ALERT_TO_EMAIL = os.getenv("ALERT_TO_EMAIL")

STATE_FILE = "price_state.json"

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


def get_price(origin, destination, departure_date):
    print("Calling Travelpayouts API...", flush=True)

    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": departure_date,
        "one_way": "true",
        "currency": "usd",
        "market": "us",
        "sorting": "price",
        "limit": 1,
        "token": TOKEN
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    print("Travelpayouts API responded.", flush=True)

    data = response.json()

    if not data.get("data"):
        return None

    flight = data["data"][0]

    return {
        "price": float(flight["price"]),
        "actual_date": flight.get("departure_at", "")[:10],
        "airline": flight.get("airline", "N/A"),
        "flight_number": flight.get("flight_number", "N/A")
    }


def send_email(origin, destination, search_month, actual_date, airline, flight_number, old_price, new_price):
    print("Preparing email...", flush=True)

    savings = old_price - new_price

    msg = EmailMessage()
    msg["Subject"] = "Flight Price Drop Alert"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

Your tracked flight price dropped.

Route: {origin} to {destination}
Search Month: {search_month}
Cheapest Travel Date: {actual_date}

Airline: {airline}
Flight Number: {flight_number}

Previous Lowest Price: ${old_price}
Current Lowest Price: ${new_price}
You Save: ${savings}

Book soon because prices can change quickly.
""")

    print("Connecting to Gmail SMTP...", flush=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        print("Logging into Gmail...", flush=True)
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)

        print("Sending email...", flush=True)
        smtp.send_message(msg)

    print("Email sent successfully.", flush=True)


def check_prices():
    print("Checking flight prices...", flush=True)

    state = load_state()

    for flight in FLIGHTS:
        origin = flight["origin"]
        destination = flight["destination"]
        search_month = flight["departure_date"]

        key = f"{origin}-{destination}-{search_month}"

        try:
            result = get_price(origin, destination, search_month)

            if result is None:
                print(f"No price found for {origin} to {destination}", flush=True)
                continue

            current_price = result["price"]
            actual_date = result["actual_date"]
            airline = result["airline"]
            flight_number = result["flight_number"]

            print(
                f"{origin} to {destination}: ${current_price} "
                f"(Travel Date: {actual_date}, Airline: {airline}, Flight: {flight_number})",
                flush=True
            )

            old_price = state.get(key)

            if old_price is None:
                state[key] = current_price
                print("Initial price saved.", flush=True)

            elif current_price < old_price:
                send_email(
                    origin,
                    destination,
                    search_month,
                    actual_date,
                    airline,
                    flight_number,
                    old_price,
                    current_price
                )

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
