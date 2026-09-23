import csv
import io
import os
import sqlite3
import uuid
import traceback
from datetime import datetime, timedelta
from functools import wraps

from sqlalchemy import inspect, text

from flask import (
    Flask, abort, flash, get_flashed_messages, jsonify, redirect,
    request, send_file, url_for, Response,
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import qrcode

# ─── Configuration ───
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads", "maintenance")
PROFILE_PIC_FOLDER = os.path.join(BASE_DIR, "static", "profile_pics")
BACKUP_FOLDER = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_PIC_FOLDER, exist_ok=True)
os.makedirs(BACKUP_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db")
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROFILE_PIC_FOLDER"] = PROFILE_PIC_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ROLES = ["ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "MAINTENANCE STAFF", "EMPLOYEE", "DEPARTMENT"]
ROOM_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance", "Out of Service"]
REQUEST_STATUSES = ["Pending", "Approved", "Assigned", "In Progress", "Completed", "Verified", "Closed", "Rejected", "Overdue"]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx", "csv"}


# ══════════════════════════════════════════════════════════════
# MODELS
# ══════════════════════════════════════════════════════════════
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(120))
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    profile_pic = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Floor(db.Model):
    __tablename__ = "floors"
    id = db.Column(db.Integer, primary_key=True)
    floor_number = db.Column(db.Integer, unique=True, nullable=False)


class Room(db.Model):
    __tablename__ = "rooms"
    id = db.Column(db.Integer, primary_key=True)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(30), default="Available")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Area(db.Model):
    __tablename__ = "areas"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    department = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class WorkingItem(db.Model):
    __tablename__ = "working_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)


class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(120))
    department = db.Column(db.String(80), default="Engineering")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MaintenanceRequest(db.Model):
    __tablename__ = "maintenance_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(30), unique=True, nullable=False)
    location_type = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    working_item_id = db.Column(db.Integer, db.ForeignKey("working_items.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="MEDIUM")
    status = db.Column(db.String(30), default="Pending")
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    due_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    completion_note = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    working_item = db.relationship("WorkingItem", foreign_keys=[working_item_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department", foreign_keys=[department_id])

    @property
    def location_name(self):
        if self.location_type == "Room" and self.room:
            return f"Room {self.room.room_number}"
        if self.area:
            return self.area.name
        return "Unknown"

    @property
    def is_overdue(self):
        if self.status in ["Completed", "Verified", "Closed", "Cancelled"]:
            return False
        if self.due_date and datetime.utcnow() > self.due_date:
            return True
        return False


class WorkOrder(db.Model):
    __tablename__ = "work_orders"
    id = db.Column(db.Integer, primary_key=True)
    work_order_no = db.Column(db.String(30), unique=True, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    status = db.Column(db.String(30), default="Assigned")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])
    parts_used = db.relationship("WorkOrderPart", back_populates="work_order", cascade="all, delete-orphan")


class WorkOrderPart(db.Model):
    __tablename__ = "work_order_parts"
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_cost = db.Column(db.Float, default=0)

    work_order = db.relationship("WorkOrder", back_populates="parts_used")
    part = db.relationship("InventoryPart")


class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")
    unit_cost = db.Column(db.Float, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    storage_location = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])

    @property
    def is_low(self):
        return self.quantity <= self.minimum_stock


class StockMovement(db.Model):
    __tablename__ = "stock_movements"
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"))
    movement_type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(200))
    work_order_id = db.Column(db.Integer)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    part = db.relationship("InventoryPart")
    user = db.relationship("User")


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), unique=True, nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")


class Contractor(db.Model):
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    status = db.Column(db.String(20), default="Active")


class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default="General")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(200))


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.String(100))
    object_id = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def log_audit(action, object_type=None, object_id=None):
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action, object_type=object_type,
        object_id=str(object_id) if object_id else None,
    )
    db.session.add(log)


def notify(user_ids, title, message, request_id=None, type="General"):
    for uid in set(user_ids):
        if uid:
            db.session.add(Notification(
                user_id=uid, title=title, message=message,
                notification_type=type, request_id=request_id,
            ))


def log_status(request_id, status, notes=None):
    db.session.add(StatusHistory(
        request_id=request_id, status=status,
        user_id=current_user.id if current_user.is_authenticated else None,
        notes=notes,
    ))


def request_no():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def wo_no():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_page(title, body):
    """Simple HTML wrapper"""
    flash_html = "".join(
        f'<div class="alert alert-{c} alert-dismissible fade show">{m}<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
        for c, m in get_flashed_messages(with_categories=True)
    )
    nav = ""
    if current_user.is_authenticated:
        nav = f'''
        <a class="nav-link" href="{url_for('dashboard')}">🏠 Dashboard</a>
        <a class="nav-link" href="{url_for('requests_list')}">📋 Requests</a>
        <a class="nav-link" href="{url_for('workorders_list')}">🔧 Work Orders</a>
        <a class="nav-link" href="{url_for('new_request')}">➕ New</a>
        <a class="nav-link" href="{url_for('notifications')}">🔔</a>
        <a class="nav-link" href="{url_for('profile')}">👤</a>
        <a class="nav-link" href="{url_for('logout')}">🚪 Logout</a>
        '''
    else:
        nav = f'<a class="nav-link" href="{url_for("login")}">🔑 Login</a>'

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body {{ background: #0f172a; color: #e2e8f0; font-family: system-ui, -apple-system, sans-serif; padding-top: 70px; }}
.navbar {{ background: rgba(15,23,42,0.95) !important; backdrop-filter: blur(10px); }}
.navbar-brand {{ color: #f59e0b !important; font-weight: 700; }}
.nav-link {{ color: #cbd5e1 !important; padding: 0.5rem 1rem !important; border-radius: 8px; }}
.nav-link:hover {{ background: rgba(245,158,11,0.1); color: #f59e0b !important; }}
.card {{ background: #1e293b; border: 1px solid rgba(245,158,11,0.15); border-radius: 16px; padding: 1.5rem; margin-bottom: 1.5rem; color: #e2e8f0; }}
.card-title {{ color: #f59e0b; font-weight: 700; }}
.metric {{ background: #1e293b; border: 1px solid rgba(245,158,11,0.15); border-radius: 16px; padding: 1.5rem; text-align: center; }}
.metric-value {{ font-size: 2rem; font-weight: 800; color: #f8fafc; }}
.metric-label {{ color: #94a3b8; font-size: 0.8rem; text-transform: uppercase; margin-top: 0.5rem; }}
.btn-primary {{ background: linear-gradient(135deg,#f59e0b,#d97706); border: none; color: #0f172a; font-weight: 600; border-radius: 10px; }}
.btn-primary:hover {{ background: linear-gradient(135deg,#fbbf24,#f59e0b); color: #0f172a; }}
.btn-success {{ background: linear-gradient(135deg,#22c55e,#16a34a); border: none; border-radius: 10px; }}
.btn-warning {{ background: linear-gradient(135deg,#eab308,#ca8a04); border: none; color: #0f172a; border-radius: 10px; }}
.btn-danger {{ background: linear-gradient(135deg,#ef4444,#dc2626); border: none; border-radius: 10px; }}
.btn-info {{ background: linear-gradient(135deg,#06b6d4,#0891b2); border: none; color: white; border-radius: 10px; }}
.table {{ color: #e2e8f0; }}
.table thead th {{ color: #f59e0b; border-bottom: 2px solid rgba(245,158,11,0.3); }}
.form-control, .form-select {{ background: #0f172a; border: 1px solid rgba(245,158,11,0.25); color: #e2e8f0; border-radius: 10px; padding: 0.7rem 1rem; }}
.form-control:focus, .form-select:focus {{ background: #0f172a; color: #f8fafc; border-color: #f59e0b; box-shadow: 0 0 0 3px rgba(245,158,11,0.15); }}
.form-label {{ color: #cbd5e1; font-weight: 600; margin-bottom: 0.5rem; }}
.alert {{ border-radius: 12px; border: none; background: #1e293b; color: #e2e8f0; }}
.badge {{ padding: 0.4rem 0.8rem; border-radius: 20px; font-weight: 600; font-size: 0.75rem; }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{url_for('index')}">🏨 Rori Hotel</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nav">
      <div class="navbar-nav ms-auto">{nav}</div>
    </div>
  </div>
</nav>
<div class="container mt-4">
  {flash_html}
  {body}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>'''


# ══════════════════════════════════════════════════════════════
# DATABASE SCHEMA FIX  (ዋናው ማስተካከያ)
# ══════════════════════════════════════════════════════════════
def ensure_database_schema():
    """Add missing columns safely using the modern SQLAlchemy API."""
    with app.app_context():
        try:
            # Create all tables if they don't exist
            db.create_all()

            # Use inspect() instead of dialect.has_table()
            inspector = inspect(db.engine)
            if "maintenance_requests" not in inspector.get_table_names():
                print("⚠️ maintenance_requests table missing")
                return

            # Read existing columns via PRAGMA (SQLite)
            existing = {c["name"] for c in inspector.get_columns("maintenance_requests")}

            additions = {
                "department_id":  "ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER",
                "manager_id":     "ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER",
                "completion_note":"ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT",
                "completed_date": "ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME",
            }

            for col, sql in additions.items():
                if col not in existing:
                    with db.engine.begin() as conn:
                        conn.execute(text(sql))
                    print(f"✅ Added column: {col}")

            print("✅ Schema OK")

        except Exception as e:
            print(f"⚠️ Schema error: {e}")


# ══════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════
def seed_data():
    # Departments
    for name in ["Housekeeping", "Front Office", "Engineering", "Food & Beverage",
                 "Administration", "Security", "Maintenance", "Other"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))

    # Floors
    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    # Rooms 201-300
    if Room.query.count() == 0:
        for n in range(201, 301):
            fl = 2 if n <= 225 else 3 if n <= 250 else 4 if n <= 275 else 5
            db.session.add(Room(floor=fl, room_number=str(n), status="Available"))

    # Areas
    for name, dept in [("Buduchalley", "F&B"), ("Sillanto", "N/A"), ("Fura", "N/A"),
                       ("Executive", "N/A"), ("Mitima", "N/A"), ("Odako", "N/A"),
                       ("Gudumale", "N/A"), ("Bubble", "N/A"), ("Bubbles", "N/A"),
                       ("Fura Corridor", "N/A"), ("Executive Meeting Room", "N/A"),
                       ("Counter", "N/A")]:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    # Categories
    for c in ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry",
              "Civil", "Safety", "General", "Other"]:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    # Working items
    for i in ["Light", "Switch", "Window", "Door Key", "Door Lock", "Paint",
              "Mirror", "Drainage Cover", "Frame", "Background Frame",
              "Spot Light", "Plumbing", "AC", "Electrical", "Other"]:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    # Employees
    staff = [
        (1, "ተስፋሁን ነከረ", "General Mechanic"),
        (2, "ቸርነት አሞና", "General Mechanic"),
        (3, "ስምዖን ዮሐንስ", "General Mechanic"),
        (4, "አበባየሁ ክፍሌ", "Supervisor"),
        (5, "አሚር አወል", "Manager"),
    ]
    for eid, name, title in staff:
        if not Employee.query.get(eid):
            db.session.add(Employee(id=eid, name=name, job_title=title, department="Engineering"))

    # Users
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN",
                 email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)

    for s in [
        {"u": "amir", "n": "አሚር አወል", "r": "MANAGER"},
        {"u": "abebayhu", "n": "አበባየሁ ክፍሌ", "r": "SUPERVISOR"},
        {"u": "tesfahun", "n": "ተስፋሁን ነከረ", "r": "TECHNICIAN"},
        {"u": "simon", "n": "ስምዖን ዮሐንስ", "r": "TECHNICIAN"},
        {"u": "chernet", "n": "ቸርነት አሞና", "r": "TECHNICIAN"},
        {"u": "wale", "n": "ዋሌ", "r": "TECHNICIAN"},
        {"u": "tsadiku", "n": "ፃዲቁ", "r": "TECHNICIAN"},
        {"u": "housekeeping", "n": "Housekeeping Dept", "r": "DEPARTMENT"},
        {"u": "employee1", "n": "Test Employee", "r": "EMPLOYEE"},
    ]:
        if not User.query.filter_by(username=s["u"]).first():
            usr = User(username=s["u"], full_name=s["n"], role=s["r"])
            usr.set_password("123456")
            db.session.add(usr)

    db.session.commit()
    print("✅ Seed data loaded")


# ══════════════════════════════════════════════════════════════
# AUTHENTICATION
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.active:
            login_user(user)
            log_audit("Login", "User", user.id)
            db.session.commit()
            return redirect(url_for("dashboard"))

        flash("የተሳሳተ መለያ ስም ወይም የይለፍ ቃል", "danger")

    return safe_page("Login", f'''
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
      <div class="col-11 col-md-5 col-lg-4">
        <div class="card" style="border-radius: 24px; padding: 2.5rem;">
          <div class="text-center mb-4">
            <h2 style="color: #f59e0b;">🏨 Rori Hotel</h2>
            <p style="color: #94a3b8;">የጥገና ክፍል መግቢያ</p>
          </div>
          <form method="post">
            <div class="mb-3">
              <label class="form-label">መለያ ስም</label>
              <input type="text" class="form-control" name="username" required>
            </div>
            <div class="mb-4">
              <label class="form-label">የይለፍ ቃል</label>
              <input type="password" class="form-control" name="password" required>
            </div>
            <button class="btn btn-primary w-100 py-3">ግባ / Login</button>
          </form>
          <hr style="border-color: rgba(245,158,11,0.2); margin: 1.5rem 0;">
          <div class="text-center small" style="color: #94a3b8;">
            <p class="mb-1">Admin: <b>admin / admin123</b></p>
            <p class="mb-0">Staff: <b>amir / 123456</b></p>
          </div>
        </div>
      </div>
    </div>
    ''')


@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile")
@login_required
def profile():
    u = current_user
    return safe_page("Profile", f'''
    <h2 style="color:#f59e0b;">👤 መገለጫ</h2>
    <div class="card">
      <h4>{u.full_name or u.username}</h4>
      <p>@{u.username} · <span class="badge bg-warning text-dark">{u.role}</span></p>
      <p>📧 {u.email or "—"}</p>
      <p>📱 {u.phone or "—"}</p>
    </div>
    ''')


# ══════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    total = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()

    return safe_page("Dashboard", f'''
    <h2 style="color:#f59e0b;">🏨 ዳሽቦርድ</h2>
    <p style="color:#94a3b8;">እንኳን ደህና መጡ፣ {current_user.full_name or current_user.username}!</p>
    <div class="row g-3 mb-4">
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value">{total}</div><div class="metric-label">ጠቅላላ</div></div></div>
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value">{in_progress}</div><div class="metric-label">በሂደት</div></div></div>
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value">{completed}</div><div class="metric-label">ተጠናቅቋል</div></div></div>
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value" style="color:#ef4444;">{urgent}</div><div class="metric-label">አስቸኳይ</div></div></div>
      <div class="col-6 col-md-4 col-lg-2"><div class="metric"><div class="metric-value" style="color:#ef4444;">{overdue}</div><div class="metric-label">ያለፉ</div></div></div>
    </div>
    <div class="row g-3">
      <div class="col-md-4"><a class="btn btn-primary w-100 py-3" href="{url_for('requests_list')}">📋 ጥያቄዎች</a></div>
      <div class="col-md-4"><a class="btn btn-success w-100 py-3" href="{url_for('workorders_list')}">🔧 የስራ ትዕዛዞች</a></div>
      <div class="col-md-4"><a class="btn btn-info w-100 py-3" href="{url_for('reports')}">📊 ሪፖርቶች</a></div>
    </div>
    ''')


# ══════════════════════════════════════════════════════════════
# REQUESTS
# ══════════════════════════════════════════════════════════════
@app.route("/requests")
@login_required
def requests_list():
    reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    rows = ""
    for r in reqs:
        badge = "danger" if r.priority == "URGENT" else "warning" if r.priority == "HIGH" else "info"
        rows += f'''<tr>
          <td><a href="{url_for('request_detail', req_id=r.id)}" style="color:#f59e0b;">{r.request_no}</a></td>
          <td>{r.location_name}</td>
          <td>{r.working_item.name if r.working_item else "—"}</td>
          <td><span class="badge bg-{badge}">{r.priority}</span></td>
          <td>{r.status}</td>
          <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''

    return safe_page("Requests", f'''
    <div class="d-flex justify-content-between mb-3">
      <h2 style="color:#f59e0b;">📋 ጥያቄዎች</h2>
      <a class="btn btn-primary" href="{url_for('new_request')}">➕ አዲስ</a>
    </div>
    <div class="card">
      <table class="table table-hover">
        <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>እቃ</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="text-center">ጥያቄ የለም</td></tr>'}</tbody>
      </table>
    </div>
    ''')


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def new_request():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    cats = Category.query.order_by(Category.name).all()
    depts = Department.query.order_by(Department.name).all()

    if request.method == "POST":
        loc_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        item_id = request.form.get("working_item_id", type=int)
        cat_id = request.form.get("category_id", type=int)
        dept_id = request.form.get("department_id", type=int)
        desc = request.form.get("description", "").strip()
        prio = request.form.get("priority", "MEDIUM")

        if loc_type == "Room":
            rm = Room.query.get(room_id)
            if not rm or not (201 <= int(rm.room_number) <= 300):
                flash("ልክ ያልሆነ ክፍል", "danger")
                return redirect(url_for("new_request"))
            floor = rm.floor
            area_id = None
        else:
            ar = Area.query.get(area_id)
            if not ar:
                flash("ልክ ያልሆነ ቦታ", "danger")
                return redirect(url_for("new_request"))
            floor = None
            room_id = None

        if not desc:
            flash("መግለጫ ያስፈልጋል", "danger")
            return redirect(url_for("new_request"))

        due = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio, 24))
        req = MaintenanceRequest(
            request_no=request_no(), location_type=loc_type, floor=floor,
            room_id=room_id, area_id=area_id, working_item_id=item_id,
            category_id=cat_id, department_id=dept_id, description=desc,
            priority=prio, status="Pending", requested_by_id=current_user.id,
            due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_status(req.id, "Pending", "Request submitted")
        log_audit("Create", "MaintenanceRequest", req.id)

        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify([u.id for u in managers], "አዲስ ጥያቄ",
               f"ጥያቄ {req.request_no} በ {req.location_name}", req.id)
        db.session.commit()
        flash("✅ ጥያቄዎ ተልኳል!", "success")
        return redirect(url_for("requests_list"))

    room_opts = "".join(f'<option value="{r.id}">ክፍል {r.room_number} (ፎቅ {r.floor})</option>' for r in rooms)
    area_opts = "".join(f'<option value="{a.id}">{a.name}</option>' for a in areas)
    item_opts = "".join(f'<option value="{i.id}">{i.name}</option>' for i in items)
    cat_opts = "".join(f'<option value="{c.id}">{c.name}</option>' for c in cats)
    dept_opts = "".join(f'<option value="{d.id}">{d.name}</option>' for d in depts)

    return safe_page("New Request", f'''
    <h2 style="color:#f59e0b;">➕ አዲስ ጥያቄ</h2>
    <div class="card">
      <form method="post">
        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label">የቦታ አይነት *</label>
            <select class="form-select" name="location_type" id="loc" onchange="tog()" required>
              <option value="Room">🏨 ክፍል</option>
              <option value="Hotel Area">📍 ቦታ</option>
            </select>
          </div>
          <div class="col-md-6 mb-3" id="roomD">
            <label class="form-label">ክፍል *</label>
            <select class="form-select" name="room_id">{room_opts}</select>
          </div>
          <div class="col-md-6 mb-3" id="areaD" style="display:none">
            <label class="form-label">ቦታ *</label>
            <select class="form-select" name="area_id"><option value="">-- ይምረጡ --</option>{area_opts}</select>
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">እቃ *</label>
            <select class="form-select" name="working_item_id" required>
              <option value="">-- ይምረጡ --</option>{item_opts}
            </select>
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">ምድብ *</label>
            <select class="form-select" name="category_id" required>
              <option value="">-- ይምረጡ --</option>{cat_opts}
            </select>
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">ዲፓርትመንት *</label>
            <select class="form-select" name="department_id" required>
              <option value="">-- ይምረጡ --</option>{dept_opts}
            </select>
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label">ቅድሚያ *</label>
            <select class="form-select" name="priority">
              <option value="LOW">🟢 ዝቅተኛ - 72h</option>
              <option value="MEDIUM" selected>🟡 መካከለኛ - 24h</option>
              <option value="HIGH">🟠 ከፍተኛ - 4h</option>
              <option value="URGENT">🔴 አስቸኳይ - 1h</option>
            </select>
          </div>
          <div class="col-12 mb-3">
            <label class="form-label">መግለጫ *</label>
            <textarea class="form-control" name="description" rows="4" required></textarea>
          </div>
          <div class="col-12">
            <button class="btn btn-primary w-100 py-3">📤 ጥያቄ ያስገቡ</button>
          </div>
        </div>
      </form>
    </div>
    <script>
      function tog() {{
        var t = document.getElementById('loc').value;
        document.getElementById('roomD').style.display = t === 'Room' ? 'block' : 'none';
        document.getElementById('areaD').style.display = t === 'Hotel Area' ? 'block' : 'none';
      }}
    </script>
    ''')


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    r = MaintenanceRequest.query.get_or_404(req_id)
    history = StatusHistory.query.filter_by(request_id=r.id).order_by(StatusHistory.timestamp.desc()).all()
    hist_html = "".join(f'<li>{h.status} — {h.timestamp.strftime("%Y-%m-%d %H:%M") if h.timestamp else ""} {f"({h.notes})" if h.notes else ""}</li>' for h in history)

    return safe_page(f"Request {r.request_no}", f'''
    <h2 style="color:#f59e0b;">📄 {r.request_no}</h2>
    <div class="card">
      <table class="table">
        <tr><th style="color:#94a3b8;">ሁኔታ</th><td>{r.status}</td></tr>
        <tr><th style="color:#94a3b8;">ቦታ</th><td>{r.location_name}</td></tr>
        <tr><th style="color:#94a3b8;">እቃ</th><td>{r.working_item.name if r.working_item else "—"}</td></tr>
        <tr><th style="color:#94a3b8;">ምድብ</th><td>{r.category.name if r.category else "—"}</td></tr>
        <tr><th style="color:#94a3b8;">ዲፓርትመንት</th><td>{r.department.name if r.department else "—"}</td></tr>
        <tr><th style="color:#94a3b8;">ቅድሚያ</th><td>{r.priority}</td></tr>
        <tr><th style="color:#94a3b8;">መግለጫ</th><td>{r.description}</td></tr>
        <tr><th style="color:#94a3b8;">የጠየቀው</th><td>{r.requested_by.full_name if r.requested_by else "—"}</td></tr>
      </table>
    </div>
    <div class="card">
      <h5 style="color:#f59e0b;">📜 ታሪክ</h5>
      <ul>{hist_html or "<li>ታሪክ የለም</li>"}</ul>
    </div>
    ''')


@app.route("/requests/<int:req_id>/approve")
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    r = MaintenanceRequest.query.get_or_404(req_id)
    if r.status == "Pending":
        r.status = "Approved"
        log_status(r.id, "Approved")
        notify([r.requested_by_id], "ጸድቋል", f"ጥያቄ {r.request_no}", r.id)
        db.session.commit()
        flash("ጥያቄው ጸድቋል", "success")
    return redirect(url_for("request_detail", req_id=req_id))


# ══════════════════════════════════════════════════════════════
# WORK ORDERS
# ══════════════════════════════════════════════════════════════
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()

    rows = "".join(f'''<tr>
      <td><a href="{url_for('workorder_detail', wo_id=wo.id)}" style="color:#f59e0b;">{wo.work_order_no}</a></td>
      <td>{wo.request.location_name if wo.request else "—"}</td>
      <td>{wo.assigned_to.full_name if wo.assigned_to else "—"}</td>
      <td>{wo.status}</td>
    </tr>''' for wo in wos)

    return safe_page("Work Orders", f'''
    <h2 style="color:#f59e0b;">🔧 የስራ ትዕዛዞች</h2>
    <div class="card">
      <table class="table">
        <thead><tr><th>ትዕዛዝ #</th><th>ቦታ</th><th>የተመደበ</th><th>ሁኔታ</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="4" class="text-center">ትዕዛዝ የለም</td></tr>'}</tbody>
      </table>
    </div>
    ''')


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    return safe_page(f"WO {wo.work_order_no}", f'''
    <h2 style="color:#f59e0b;">🔧 {wo.work_order_no}</h2>
    <div class="card">
      <table class="table">
        <tr><th>ጥያቄ</th><td>{wo.request.request_no if wo.request else "—"}</td></tr>
        <tr><th>ቦታ</th><td>{wo.request.location_name if wo.request else "—"}</td></tr>
        <tr><th>ሁኔታ</th><td>{wo.status}</td></tr>
        <tr><th>የተመደበ</th><td>{wo.assigned_to.full_name if wo.assigned_to else "—"}</td></tr>
      </table>
    </div>
    ''')


# ══════════════════════════════════════════════════════════════
# OTHER PAGES
# ══════════════════════════════════════════════════════════════
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = "".join(f'<tr><td>{r.room_number}</td><td>{r.floor}</td><td>{r.status}</td></tr>' for r in rooms)
    return safe_page("Rooms", f'<h2 style="color:#f59e0b;">🚪 ክፍሎች</h2><div class="card"><table class="table"><thead><tr><th>ክፍል</th><th>ፎቅ</th><th>ሁኔታ</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join(f'<tr><td>{a.name}</td><td>{a.department}</td></tr>' for a in areas)
    return safe_page("Areas", f'<h2 style="color:#f59e0b;">📍 ቦታዎች</h2><div class="card"><table class="table"><thead><tr><th>ስም</th><th>ዲፓርትመንት</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = "".join(f'<tr><td>{p.part_name}</td><td>{p.quantity}</td><td>{p.unit}</td></tr>' for p in parts)
    return safe_page("Inventory", f'<h2 style="color:#f59e0b;">📦 ክምችት</h2><div class="card"><table class="table"><thead><tr><th>ስም</th><th>ብዛት</th><th>አሃድ</th></tr></thead><tbody>{rows or "<tr><td colspan=3>እቃ የለም</td></tr>"}</tbody></table></div>')


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    emps = Employee.query.all()
    rows = "".join(f'<tr><td>{e.id}</td><td>{e.name}</td><td>{e.job_title}</td></tr>' for e in emps)
    return safe_page("Employees", f'<h2 style="color:#f59e0b;">👥 ሰራተኞች</h2><div class="card"><table class="table"><thead><tr><th>ID</th><th>ስም</th><th>ድርሻ</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    rows = "".join(f'<tr><td>{n.title}</td><td>{n.message}</td><td>{n.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for n in notifs)
    return safe_page("Notifications", f'<h2 style="color:#f59e0b;">🔔 ማሳወቂያዎች</h2><div class="card"><table class="table"><thead><tr><th>ርዕስ</th><th>መልእክት</th><th>ቀን</th></tr></thead><tbody>{rows or "<tr><td colspan=3>ማሳወቂያ የለም</td></tr>"}</tbody></table></div>')


@app.route("/reports")
@login_required
def reports():
    total = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    done = MaintenanceRequest.query.filter_by(status="Completed").count()
    return safe_page("Reports", f'''
    <h2 style="color:#f59e0b;">📊 ሪፖርቶች</h2>
    <div class="row g-3 mb-4">
      <div class="col-4"><div class="metric"><div class="metric-value">{total}</div><div class="metric-label">ጠቅላላ</div></div></div>
      <div class="col-4"><div class="metric"><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
      <div class="col-4"><div class="metric"><div class="metric-value">{done}</div><div class="metric-label">ተጠናቅቋል</div></div></div>
    </div>
    <div class="card">
      <a href="{url_for('export_csv', kind='requests')}" class="btn btn-primary w-100 mb-2">📥 ጥያቄዎችን ላክ (CSV)</a>
      <a href="{url_for('export_csv', kind='workorders')}" class="btn btn-primary w-100">📥 የስራ ትዕዛዞችን ላክ (CSV)</a>
    </div>
    ''')


@app.route("/reports/export/<kind>")
@login_required
def export_csv(kind):
    out = io.StringIO()
    w = csv.writer(out)
    if kind == "requests":
        w.writerow(["Request No", "Location", "Status", "Priority", "Created"])
        for r in MaintenanceRequest.query.all():
            w.writerow([r.request_no, r.location_name, r.status, r.priority, r.created_at])
    elif kind == "workorders":
        w.writerow(["WO No", "Status", "Assigned"])
        for wo in WorkOrder.query.all():
            w.writerow([wo.work_order_no, wo.status, wo.assigned_to.full_name if wo.assigned_to else ""])
    else:
        abort(404)
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={kind}.csv"})


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows = "".join(f'<tr><td>{u.username}</td><td>{u.full_name}</td><td>{u.role}</td></tr>' for u in users)
    return safe_page("Users", f'<h2 style="color:#f59e0b;">👤 ተጠቃሚዎች</h2><div class="card"><table class="table"><thead><tr><th>Username</th><th>ስም</th><th>ሚና</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel", "short_name": "RoriMaint", "start_url": "/"})


@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());", mimetype="application/javascript")


@app.route("/logo.png")
def logo():
    p = os.path.join(app.root_path, "file_00000000d93c821094a2e3f7dced7c77.png")
    if os.path.exists(p):
        return send_file(p, mimetype="image/png")
    return Response("", mimetype="image/png")


@app.errorhandler(403)
def e403(e):
    return safe_page("Forbidden", '<div class="alert alert-danger">ፍቃድ የለዎትም</div>'), 403


@app.errorhandler(404)
def e404(e):
    return safe_page("Not Found", '<div class="alert alert-warning">ገጹ አልተገኘም</div>'), 404


@app.errorhandler(500)
def e500(e):
    tb = traceback.format_exc()
    print("❌ 500 ERROR:", tb)
    return safe_page("Error", f'<div class="alert alert-danger"><h4>ስህተት</h4><p>ቆየት ብለው ይሞክሩ።</p><details><summary>Debug</summary><pre>{tb[:800]}</pre></details></div>'), 500


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)