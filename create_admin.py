#!/usr/bin/env python3
"""
create_admin.py
Creates a new admin user in sahayak.db using the same salt/hash
scheme as login.py's authenticate() function.

Usage:
    python3 create_admin.py
"""

import sqlite3
import hashlib
import base64
import os
import getpass

DB_PATH = "sahayak.db"  # run this script from ~/IEAS/login


def _make_salt() -> str:
    return base64.b64encode(os.urandom(16)).decode()


def hash_password(password: str, salt: str = "") -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def create_admin(username: str, password: str, full_name: str):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        existing = c.execute(
            "SELECT 1 FROM users WHERE username=?", (username,)
        ).fetchone()
        if existing:
            print(f"ERROR: username '{username}' already exists.")
            return False

        salt = _make_salt()
        pw_hash = hash_password(password, salt)

        try:
            c.execute(
                "INSERT INTO users (username, password_hash, salt, role, full_name) "
                "VALUES (?, ?, ?, 'admin', ?)",
                (username, pw_hash, salt, full_name)
            )
            conn.commit()
            print(f"Admin '{username}' created successfully (user id: {c.lastrowid}).")
            return True
        except Exception as e:
            print(f"ERROR: {e}")
            return False


if __name__ == "__main__":
    print("=== Create new AIEdS admin account ===")
    username = input("Admin username: ").strip()
    full_name = input("Full name: ").strip()
    password = getpass.getpass("Password (min 6 chars): ")
    confirm = getpass.getpass("Confirm password: ")

    if password != confirm:
        print("Passwords do not match. Aborting.")
    elif len(password) < 6:
        print("Password must be at least 6 characters. Aborting.")
    elif not username or not full_name:
        print("Username and full name are required. Aborting.")
    else:
        create_admin(username, password, full_name)
