"""Create a login for the Student Information Management System.

Run it from the sims_app folder:   python create_user.py
"""
import getpass

import mysql.connector
from werkzeug.security import generate_password_hash

from app import DB_CONFIG

ROLES = {"1": "Admin", "2": "Registrar", "3": "Lecturer"}

username = input("Username: ").strip()
print("Role:  1 = Admin   2 = Registrar   3 = Lecturer")
role = ROLES.get(input("Choose 1, 2 or 3: ").strip())
if not username or not role:
    raise SystemExit("A username and a valid role are required.")

lecturer_id = None
if role == "Lecturer":
    lecturer_id = int(input("Lecturer ID from the lecturers table (1-10): ").strip())

password = getpass.getpass("Password (at least 8 characters): ")
if len(password) < 8 or password != getpass.getpass("Type the password again: "):
    raise SystemExit("Passwords did not match, or were shorter than 8 characters.")

db = mysql.connector.connect(**DB_CONFIG)
cur = db.cursor()
try:
    cur.execute(
        "INSERT INTO users (username, password_hash, role, lecturer_id) VALUES (%s, %s, %s, %s)",
        (username, generate_password_hash(password), role, lecturer_id),
    )
    db.commit()
    print(f"User '{username}' created as {role}.")
except mysql.connector.Error as err:
    print("Could not create the user:", err.msg)
finally:
    cur.close()
    db.close()
