import csv
import io
import os
import sqlite3
import uuid
import base64
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    render_template_string,
    request,
    send_file,
    url_for,
    Response,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import qrcode

BASE_DIR = os.path.abspath(os.path.dirname(file))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "maintenance")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(name)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ROLES = ["ADMIN", "MANAGER", "MAINTENANCE STAFF", "EMPLOYEE"]
ROOM_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance", "Out of Service"]
REQUEST_STATUSES = [
    "Pending",
    "Approved",
    "Assigned",
    "In Progress",
    "Completed",
    "Verified",
    "Closed",
    "Cancelled",
    "Overdue",
]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx", "csv"}


# --------------------------------------------------------------
# MODELS
# --------------------------------------------------------------
class User(UserMixin, db.Model):
    tablename = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Floor(db.Model):
    tablename = "floors"
    id = db.Column(db.Integer, primary_key=True)
    floor_number = db.Column(db.Integer, unique=True, nullable=False)


class Room(db.Model):
    tablename = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(30), default="Available")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Area(db.Model):
    tablename = "areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Category(db.Model):
    tablename = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)