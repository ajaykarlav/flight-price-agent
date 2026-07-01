import os
import sqlite3
import smtplib
import requests
import schedule
import time
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")
ALERT_TO_EMAIL = os.getenv("ALERT_TO_EMAIL")

DB_NAME = "flight_prices.db"


def setup_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT,
            destination TEXT,
            departure_date TEXT,
            lowest_price REAL
        )
    """)

    conn.commit()
    conn.close()


def add_flight(origin, destination, departure_date):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id FROM tracker
        WHERE origin=? AND destination=? AND departure_date=?
    """, (origin, destination, departure_date))

    if cursor.fetchone() is None:
        cursor.execute("""
            INSERT INTO tracker (origin, destination, departure_date, lowest_price)
            VALUES (?, ?, ?, ?)
        """, (origin, destination, departure_date, None))

    conn.commit()
    conn.close()


def get_price(origin, destination, departure_date):
    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"

    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": departure_date,
        "one_way": "true",
        "currency": "usd",
        "sorting": "price",
        "limit": 1,
        "token": TOKEN
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    data = response.json()

    if not data.get("data"):
        return None

    return float(data["data"][0]["price"])


def send_email(origin, destination, departure_date, old_price, new_price):
    msg = EmailMessage()
    msg["Subject"] = "Flight Price Drop Alert"
    msg["From"] = EMAIL_USER
    msg["To"] = ALERT_TO_EMAIL

    msg.set_content(f"""
Good news!

Your flight price dropped.

Route: {origin} to {destination}
Date: {departure_date}

Old lowest price: ${old_price}
New price: ${new_price}

Book soon because prices can change quickly.
""")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_APP_PASSWORD)
        smtp.send_message(msg)


def check_prices():
    print("Checking flight prices...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT id, origin, destination, departure_date, lowest_price FROM tracker")
    flights = cursor.fetchall()

    for flight in flights:
        flight_id, origin, destination, departure_date, lowest_price = flight

        try:
            current_price = get_price(origin, destination, departure_date)

            if current_price is None:
                print(f"No price found for {origin} to {destination}")
                continue

            print(f"{origin} to {destination}: ${current_price}")

            if lowest_price is None:
                cursor.execute(
                    "UPDATE tracker SET lowest_price=? WHERE id=?",
                    (current_price, flight_id)
                )
                print("Initial price saved.")

            elif current_price < lowest_price:
                send_email(origin, destination, departure_date, lowest_price, current_price)

                cursor.execute(
                    "UPDATE tracker SET lowest_price=? WHERE id=?",
                    (current_price, flight_id)
                )

                print("Price dropped. Email sent.")

            else:
                print("No price drop.")

        except Exception as e:
            print("Error:", e)

    conn.commit()
    conn.close()


setup_db()

# Change this based on your flight
add_flight("DFW", "JFK", "2026-08")

check_prices()
