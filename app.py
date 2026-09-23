import csv
import io
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from functools import wraps
import traceback

from sqlalchemy import inspect, text  # ✅ አዲስ ተጨምሯል

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
import qrcode.image.svg

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
REQUEST_STATUSES = [
    "Pending", "Approved", "Assigned", "In Progress", "Completed",
    "Verified", "Closed", "Rejected", "Overdue",
]
PRIORITIES = {"URGENT": 1, "HIGH": 4, "MEDIUM": 24, "LOW": 72}
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx", "csv"}


# --------------------------------------------------------------
# MODELS
# --------------------------------------------------------------
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
    request_id = db.Column(db.Integer)
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
    address = db.Column(db.Text)
    supplied_items = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)


class Contractor(db.Model):
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    rate = db.Column(db.Float)
    status = db.Column(db.String(20), default="Active")
    notes = db.Column(db.Text)


class PreventiveMaintenance(db.Model):
    __tablename__ = "preventive_maintenance"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    location_type = db.Column(db.String(20), default="Room")
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    task = db.Column(db.Text)
    frequency = db.Column(db.String(20), default="Monthly")
    priority = db.Column(db.String(20), default="MEDIUM")
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    next_due_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="Scheduled")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])


class ChecklistTemplate(db.Model):
    __tablename__ = "checklist_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship("ChecklistTemplateItem", back_populates="template", cascade="all, delete-orphan")


class ChecklistTemplateItem(db.Model):
    __tablename__ = "checklist_template_items"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    order = db.Column(db.Integer, default=0)

    template = db.relationship("ChecklistTemplate", back_populates="items")


class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    photo_type = db.Column(db.String(20), default="Before")
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    file_size = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploaded_by = db.relationship("User")


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

    user = db.relationship("User", foreign_keys=[user_id])
    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(100), nullable=False)
    object_type = db.Column(db.String(100))
    object_id = db.Column(db.String(50))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    ip_address = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


class StatusHistory(db.Model):
    __tablename__ = "status_history"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    user = db.relationship("User", foreign_keys=[user_id])


class Setting(db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.Text)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# --------------------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------------------
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


def log_audit(action, object_type=None, object_id=None, old_value=None, new_value=None):
    log = AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id is not None else None,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
    )
    db.session.add(log)


def create_notification(user_id, request_id, title, message, notification_type="General", link=None):
    if not user_id:
        return
    if not link:
        link = url_for("request_detail", req_id=request_id)
    notif = Notification(
        user_id=user_id,
        request_id=request_id,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link
    )
    db.session.add(notif)


def notify_users(user_ids, request_id, title, message, notification_type="General", link=None):
    for uid in user_ids:
        if uid:
            create_notification(uid, request_id, title, message, notification_type, link)


def log_status_change(request_id, status, user_id=None, notes=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    hist = StatusHistory(
        request_id=request_id,
        status=status,
        user_id=user_id,
        notes=notes
    )
    db.session.add(hist)


def request_no_generator():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def work_order_no_generator():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ✅ የተስተካከለው ተግባር
def ensure_database_schema():
    """Safely add missing columns to maintenance_requests using PRAGMA for SQLite."""
    with app.app_context():
        try:
            # ✅ Fix: Use inspect() instead of dialect.has_table()
            inspector = inspect(db.engine)
            if not inspector.has_table('departments'):
                db.create_all()
                print("✅ Created all tables")

            # ያሉትን አምዶች ማግኘት
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(maintenance_requests)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            conn.close()

            required_columns = {
                'department_id': 'ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER REFERENCES departments(id)',
                'manager_id': 'ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER REFERENCES users(id)',
                'completion_note': 'ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT',
                'completed_date': 'ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME'
            }

            for col, sql in required_columns.items():
                if col not in existing_columns:
                    # ✅ Fix: Use db.engine.begin() with text()
                    with db.engine.begin() as connection:
                        connection.execute(text(sql))
                    print(f"✅ Added column {col} to maintenance_requests")

            print("✅ Schema check complete - no errors")

        except Exception as e:
            print(f"⚠️ Schema migration error: {e}")


# --------------------------------------------------------------
# PAGE FUNCTION WITH LUXURY THEME
# --------------------------------------------------------------
def page(title, content):
    nav_items = []
    if current_user.is_authenticated:
        if current_user.role == "DEPARTMENT":
            nav_items.append(('<i class="fas fa-home"></i> Dashboard', url_for('department_dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        elif current_user.role == "EMPLOYEE":
            nav_items.append(('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        elif current_user.role in ["TECHNICIAN", "MAINTENANCE STAFF", "SUPERVISOR"]:
            nav_items.append(('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        else:
            nav_items.append(('<i class="fas fa-home"></i> Dashboard', url_for('dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-tasks"></i> All Requests', url_for('requests_list')))
            nav_items.append(('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')))
            if current_user.role in ["ADMIN", "MANAGER"]:
                nav_items.append(('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')))
                nav_items.append(('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')))
                nav_items.append(('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')))
                nav_items.append(('<i class="fas fa-users"></i> Employees', url_for('employees_list')))
            if current_user.role == "ADMIN":
                nav_items.append(('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')))
                nav_items.append(('<i class="fas fa-history"></i> Audit Log', url_for('audit_logs')))
                nav_items.append(('<i class="fas fa-archive"></i> Backup', url_for('backup_page')))
            nav_items.append(('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
    else:
        nav_items.append(('<i class="fas fa-sign-in-alt"></i> Login', url_for('login')))

    nav_html = ""
    for label, url in nav_items:
        nav_html += f'<a class="nav-link" href="{url}">{label}</a>'

    bell_html = ""
    if current_user.is_authenticated:
        unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        bell_html = f"""
        <a class="nav-link" href="{url_for('notifications')}" style="position:relative;">
            <i class="fas fa-bell"></i>
            {f'<span class="badge bg-danger" style="position:absolute; top:-5px; right:-5px; font-size:0.7rem;">{unread_count}</span>' if unread_count > 0 else ''}
        </a>
        """

    flash_html = "".join(
        f'<div class="alert alert-{cat} alert-dismissible fade show">{msg}</div>'
        for cat, msg in get_flashed_messages(with_categories=True)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Rori Hotel Maintenance</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link rel="manifest" href="/manifest.json">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Inter', sans-serif;
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        min-height: 100vh;
        color: #e2e8f0;
        padding-top: 70px;
    }}
    .navbar {{
        background: rgba(15, 23, 42, 0.85) !important;
        backdrop-filter: blur(20px) saturate(180%);
        border-bottom: 1px solid rgba(245, 158, 11, 0.2);
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        padding: 0.75rem 1.5rem;
    }}
    .navbar-brand {{
        font-weight: 800;
        font-size: 1.4rem;
        color: #f59e0b !important;
        letter-spacing: -0.5px;
    }}
    .navbar-brand img {{
        height: 38px;
        vertical-align: middle;
        margin-right: 10px;
        filter: drop-shadow(0 2px 6px rgba(245,158,11,0.3));
    }}
    .nav-link {{
        color: #cbd5e1 !important;
        font-weight: 500;
        padding: 0.5rem 1rem !important;
        border-radius: 40px;
        transition: all 0.25s ease;
        margin: 0 0.1rem;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 0.9rem;
    }}
    .nav-link i {{ color: #f59e0b; }}
    .nav-link:hover {{
        background: rgba(245, 158, 11, 0.12);
        color: #f59e0b !important;
        transform: translateY(-1px);
    }}
    .container {{ max-width: 1280px; padding: 1.5rem; }}
    .card {{
        background: rgba(30, 41, 59, 0.7) !important;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 20px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        color: #e2e8f0;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        transition: all 0.3s ease;
    }}
    .card:hover {{
        transform: translateY(-3px);
        border-color: rgba(245, 158, 11, 0.3);
        box-shadow: 0 16px 48px rgba(0,0,0,0.4);
    }}
    .card-title {{ color: #f59e0b; font-weight: 700; }}
    .metric-card {{
        background: rgba(30, 41, 59, 0.6);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 20px;
        padding: 1.5rem 1rem;
        text-align: center;
        transition: all 0.3s ease;
        height: 100%;
    }}
    .metric-card:hover {{
        transform: translateY(-5px);
        border-color: #f59e0b;
        box-shadow: 0 12px 40px rgba(245,158,11,0.2);
    }}
    .metric-icon {{ font-size: 2.2rem; color: #f59e0b; margin-bottom: 0.75rem; }}
    .metric-value {{ font-size: 2rem; font-weight: 800; color: #f8fafc; line-height: 1.2; }}
    .metric-label {{ font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-top: 0.5rem; }}
    .table {{ color: #e2e8f0; border-color: rgba(245, 158, 11, 0.1); }}
    .table thead th {{
        border-bottom: 2px solid rgba(245, 158, 11, 0.3);
        color: #f59e0b;
        font-weight: 700;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 1px;
        padding: 12px;
        background: rgba(15, 23, 42, 0.4);
    }}
    .table td {{ padding: 12px; vertical-align: middle; border-color: rgba(245, 158, 11, 0.08); }}
    .table-striped tbody tr:nth-of-type(odd) {{ background-color: rgba(30, 41, 59, 0.3); }}
    .table-hover tbody tr:hover {{ background-color: rgba(245, 158, 11, 0.08); }}
    .btn {{
        border-radius: 12px;
        font-weight: 600;
        padding: 0.7rem 1.8rem;
        transition: all 0.25s ease;
        border: none;
        letter-spacing: 0.3px;
    }}
    .btn-primary {{
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #0f172a;
        box-shadow: 0 4px 16px rgba(245, 158, 11, 0.3);
    }}
    .btn-primary:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 28px rgba(245, 158, 11, 0.5);
        background: linear-gradient(135deg, #fbbf24, #f59e0b);
        color: #0f172a;
    }}
    .btn-success {{
        background: linear-gradient(135deg, #22c55e, #16a34a);
        color: white;
        box-shadow: 0 4px 16px rgba(34, 197, 94, 0.3);
    }}
    .btn-success:hover {{ transform: translateY(-2px); color: white; }}
    .btn-warning {{ background: linear-gradient(135deg, #eab308, #ca8a04); color: #0f172a; }}
    .btn-warning:hover {{ transform: translateY(-2px); color: #0f172a; }}
    .btn-danger {{ background: linear-gradient(135deg, #ef4444, #dc2626); color: white; }}
    .btn-danger:hover {{ transform: translateY(-2px); color: white; }}
    .btn-info {{ background: linear-gradient(135deg, #06b6d4, #0891b2); color: white; }}
    .btn-info:hover {{ transform: translateY(-2px); color: white; }}
    .form-control, .form-select {{
        background: rgba(15, 23, 42, 0.7);
        border: 1.5px solid rgba(245, 158, 11, 0.25);
        border-radius: 12px;
        color: #e2e8f0;
        padding: 0.75rem 1rem;
        transition: all 0.2s;
    }}
    .form-control:focus, .form-select:focus {{
        border-color: #f59e0b;
        box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.15);
        background: rgba(15, 23, 42, 0.9);
        color: #f8fafc;
    }}
    .form-control::placeholder {{ color: #64748b; }}
    .form-label {{ font-weight: 600; color: #cbd5e1; margin-bottom: 0.5rem; }}
    .alert {{
        border-radius: 16px;
        border: none;
        background: rgba(30, 41, 59, 0.9);
        backdrop-filter: blur(10px);
        color: #e2e8f0;
        padding: 1rem 1.5rem;
        margin-bottom: 1.5rem;
    }}
    .alert-success {{ border-left: 4px solid #22c55e; }}
    .alert-danger {{ border-left: 4px solid #ef4444; }}
    .alert-warning {{ border-left: 4px solid #f59e0b; }}
    .alert-info {{ border-left: 4px solid #06b6d4; }}
    .login-card {{
        background: rgba(30, 41, 59, 0.7) !important;
        backdrop-filter: blur(24px);
        border: 1px solid rgba(245, 158, 11, 0.25);
        border-radius: 32px !important;
        padding: 2.5rem;
        box-shadow: 0 24px 80px rgba(0,0,0,0.6);
        max-width: 440px;
        margin: 0 auto;
    }}
    .badge {{ padding: 0.4rem 0.9rem; border-radius: 40px; font-weight: 600; font-size: 0.75rem; }}
    @media (max-width: 768px) {{
        .nav-link {{ padding: 0.5rem 0.8rem !important; font-size: 0.85rem; }}
        .metric-value {{ font-size: 1.5rem; }}
        .login-card {{ padding: 1.75rem; margin: 1rem; }}
        .container {{ padding: 1rem; }}
        .card {{ padding: 1.25rem; }}
    }}
    ::-webkit-scrollbar {{ width: 8px; background: #0f172a; }}
    ::-webkit-scrollbar-thumb {{ background: #f59e0b; border-radius: 10px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #d97706; }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{url_for('dashboard') if current_user.is_authenticated else url_for('login')}">
      <img src="/logo.png" alt="Rori Hotel Logo"> Rori Hotel
    </a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nav">
      <div class="navbar-nav ms-auto">
        {nav_html}
        {bell_html}
      </div>
    </div>
  </div>
</nav>
<div class="container mt-4">
  {flash_html}
  {content}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
</script>
</body>
</html>"""


# --------------------------------------------------------------
# SEED DATA
# --------------------------------------------------------------
def seed_data():
    departments = [
        "Housekeeping", "Front Office", "Engineering", "Food & Beverage",
        "Administration", "Security", "Maintenance", "Other"
    ]
    for dept_name in departments:
        if not Department.query.filter_by(name=dept_name).first():
            db.session.add(Department(name=dept_name))

    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))

    initial_areas = [
        ("Buduchalley", "F&B"),
        ("Sillanto", "Unknown"),
        ("Fura", "Unknown"),
        ("Executive", "Unknown"),
        ("Mitima", "Unknown"),
        ("Odako", "Unknown"),
        ("Gudumale", "Unknown"),
        ("Bubble", "Unknown"),
        ("Bubbles", "Unknown"),
        ("Fura Corridor", "Unknown"),
        ("Executive Meeting Room", "Unknown"),
        ("Counter", "Unknown"),
    ]
    for name, dept in initial_areas:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    categories = ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry", "Civil", "Safety", "General", "Other"]
    for c in categories:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    items = [
        "Light", "Switch", "Window", "Door Key", "Door Lock", "Paint", "Mirror",
        "Drainage Cover", "Frame", "Background Frame", "Spot Light", "Plumbing",
        "AC", "Electrical", "Other",
    ]
    for i in items:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    engineering_staff = [
        (1, "ተስፋሁን ነከረ", "General Mechanic"),
        (2, "ቸርነት አሞና", "General Mechanic"),
        (3, "ስምዖን ዮሐንስ", "General Mechanic"),
        (4, "አበባየሁ ክፍሌ", "Supervisor"),
        (5, "አሚር አወል", "Manager"),
    ]
    for emp_id, name, title in engineering_staff:
        if not Employee.query.get(emp_id):
            db.session.add(Employee(id=emp_id, name=name, job_title=title, department="Engineering"))

    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        admin.set_password("admin123")
        db.session.add(admin)

    staff_list = [
        {"username": "amir", "full_name": "አሚር አወል", "role": "MANAGER"},
        {"username": "abebayhu", "full_name": "አበባየሁ ክፍሌ", "role": "SUPERVISOR"},
        {"username": "tesfahun", "full_name": "ተስፋሁን ነከረ", "role": "TECHNICIAN"},
        {"username": "simon", "full_name": "ስምዖን ዮሐንስ", "role": "TECHNICIAN"},
        {"username": "chernet", "full_name": "ቸርነት አሞና", "role": "TECHNICIAN"},
        {"username": "wale", "full_name": "ዋሌ", "role": "TECHNICIAN"},
        {"username": "tsadiku", "full_name": "ፃዲቁ", "role": "TECHNICIAN"},
        {"username": "housekeeping", "full_name": "Housekeeping Dept", "role": "DEPARTMENT"},
        {"username": "employee1", "full_name": "Test Employee", "role": "EMPLOYEE"},
    ]
    for s in staff_list:
        if not User.query.filter_by(username=s["username"]).first():
            user = User(
                username=s["username"],
                full_name=s["full_name"],
                role=s["role"],
                email="",
                phone="",
                profile_pic=None
            )
            user.set_password("123456")
            db.session.add(user)

    db.session.commit()
    print("✅ Seed data loaded")


# --------------------------------------------------------------
# ROUTES
# --------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN", "MANAGER"]:
            return redirect(url_for("dashboard"))
        elif current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        elif current_user.role == "EMPLOYEE":
            return redirect(url_for("employee_dashboard"))
        else:
            return redirect(url_for("workorders_list"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.active:
            login_user(user)
            log_audit("Login", "User", user.id)
            db.session.commit()
            return redirect(url_for("index"))

        flash("የተሳሳተ መለያ ስም ወይም የይለፍ ቃል", "danger")

    login_html = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-11 col-md-5 col-lg-4">
            <div class="login-card">
                <div class="text-center mb-4">
                    <img src="/logo.png" alt="Rori Hotel Logo" style="height: 60px; margin-bottom: 15px;">
                    <h3 class="fw-bold" style="color: #f59e0b;">Rori Hotel</h3>
                    <p style="color: #94a3b8;">የጥገና ክፍል መግቢያ</p>
                </div>
                <form method="post">
                    <div class="mb-3">
                        <label class="form-label">መለያ ስም (Username)</label>
                        <input type="text" class="form-control form-control-lg" name="username" placeholder="ስም ያስገቡ..." required autocomplete="username">
                    </div>
                    <div class="mb-4">
                        <label class="form-label">የይለፍ ቃል (Password)</label>
                        <input type="password" class="form-control form-control-lg" name="password" placeholder="********" required autocomplete="current-password">
                    </div>
                    <button class="btn btn-primary btn-lg w-100"><i class="fas fa-sign-in-alt"></i> ግባ / Login</button>
                </form>
                <hr class="my-4" style="border-color: rgba(245,158,11,0.2);">
                <div class="text-center small" style="color: #94a3b8;">
                    <p class="mb-1"><b>Admin:</b> admin | admin123</p>
                    <p class="mb-0"><b>Staff:</b> amir | 123456</p>
                </div>
            </div>
        </div>
    </div>
    """
    return page("Login", login_html)


@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        user.email = email
        user.phone = phone

        new_password = request.form.get("new_password", "").strip()
        if new_password:
            user.set_password(new_password)

        file = request.files.get("profile_pic")
        if file and file.filename != "" and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[-1].lower()
            filename = secure_filename(f"{user.id}_{uuid.uuid4().hex}.{ext}")
            file.save(os.path.join(app.config["PROFILE_PIC_FOLDER"], filename))
            user.profile_pic = filename

        db.session.commit()
        flash("መረጃዎ ተዘምኗል", "success")
        return redirect(url_for("profile"))

    pic_url = url_for('static', filename=f'profile_pics/{user.profile_pic}') if user.profile_pic else url_for('static', filename='profile_pics/default.png')
    content = f"""
    <div class="row">
        <div class="col-md-4 text-center">
            <img src="{pic_url}" class="img-thumbnail rounded-circle mb-3" style="width: 150px; height: 150px; object-fit: cover; border: 3px solid #f59e0b;">
            <h4 style="color: #f8fafc;">{user.full_name or user.username}</h4>
            <p style="color: #94a3b8;">@{user.username} · {user.role}</p>
        </div>
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title"><i class="fas fa-user-edit"></i> አርትዕ መገለጫ</h5>
                    <form method="post" enctype="multipart/form-data">
                        <div class="mb-3">
                            <label class="form-label">ኢሜል</label>
                            <input type="email" class="form-control" name="email" value="{user.email or ''}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">ስልክ</label>
                            <input type="text" class="form-control" name="phone" value="{user.phone or ''}">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">የመገለጫ ሥዕል</label>
                            <input type="file" class="form-control" name="profile_pic" accept="image/*">
                        </div>
                        <div class="mb-3">
                            <label class="form-label">አዲስ የይለፍ ቃል</label>
                            <input type="password" class="form-control" name="new_password" placeholder="ባዶ ሆኖ ከቀረ አይለወጥም">
                        </div>
                        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button>
                        <a href="/logout" class="btn btn-danger"><i class="fas fa-sign-out-alt"></i> ውጣ</a>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """
    return page("መገለጫ", content)


@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role not in ["ADMIN", "MANAGER"]:
        if current_user.role == "EMPLOYEE":
            return redirect(url_for("employee_dashboard"))
        elif current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        else:
            return redirect(url_for("workorders_list"))

    total_requests = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-crown"></i> የአስተዳዳሪ ዳሽቦርድ</h2>
    <p class="text-muted mb-4">እንኳን ደህና መጡ፣ {current_user.full_name or current_user.username}!</p>

    <div class="row g-4 mb-4">
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-tasks"></i></div><div class="metric-value">{total_requests}</div><div class="metric-label">ጠቅላላ ጥያቄዎች</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clock"></i></div><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-spinner"></i></div><div class="metric-value">{in_progress}</div><div class="metric-label">በሂደት ላይ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-circle"></i></div><div class="metric-value">{completed}</div><div class="metric-label">የተጠናቀቁ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card" style="border-color: rgba(239, 68, 68, 0.4);"><div class="metric-icon" style="color: #ef4444;"><i class="fas fa-exclamation-triangle"></i></div><div class="metric-value">{urgent}</div><div class="metric-label">አስቸኳይ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card" style="border-color: rgba(239, 68, 68, 0.4);"><div class="metric-icon" style="color: #ef4444;"><i class="fas fa-clock"></i></div><div class="metric-value">{overdue}</div><div class="metric-label">ያለፉ</div></div></div>
    </div>

    <div class="row g-3">
        <div class="col-md-4"><a class="btn btn-primary w-100 py-3" href="{url_for('requests_list')}"><i class="fas fa-list"></i> ጥያቄዎችን ይመልከቱ</a></div>
        <div class="col-md-4"><a class="btn btn-success w-100 py-3" href="{url_for('workorders_list')}"><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዞች</a></div>
        <div class="col-md-4"><a class="btn btn-info w-100 py-3" href="{url_for('reports')}"><i class="fas fa-chart-bar"></i> ሪፖርቶች</a></div>
    </div>
    """
    return page("Dashboard", content)


@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()

    rows = ""
    for r in requests:
        rows += f"""
        <tr>
        <td><a href="{url_for('request_detail', req_id=r.id)}" style="color: #f59e0b;">{r.request_no}</a></td>
        <td>{r.description[:50] if r.description else 'N/A'}</td>
        <td>{r.location_name}</td>
        <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info'}">{r.priority}</span></td>
        <td><span class="badge bg-{'success' if r.status in ['Completed','Closed'] else 'warning' if r.status=='Pending' else 'info'}">{r.status}</span></td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>"""

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-user-circle"></i> My Dashboard</h2>
    <p class="text-muted mb-4">እንኳን ደህና መጡ፣ {current_user.full_name or current_user.username}!</p>
    <a class="btn btn-primary mb-3" href="{url_for('request_create')}"><i class="fas fa-plus-circle"></i> አዲስ ጥያቄ</a>
    <div class="card">
        <div class="card-body">
            <h5 class="card-title mb-3"><i class="fas fa-list"></i> የእኔ ጥያቄዎች</h5>
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead><tr><th>ጥያቄ #</th><th>ዝርዝር</th><th>ቦታ</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
                    <tbody>{rows or '<tr><td colspan="6" class="text-center text-muted">እስካሁን ጥያቄ የለም</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return page("My Dashboard", content)


@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()

    rows = ""
    for r in requests:
        rows += f"""
        <tr>
        <td><a href="{url_for('request_detail', req_id=r.id)}" style="color: #f59e0b;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.priority}</td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>"""

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-building"></i> የዲፓርትመንት ዳሽቦርድ</h2>
    <a class="btn btn-primary mb-3" href="{url_for('request_create')}"><i class="fas fa-plus-circle"></i> አዲስ ጥያቄ</a>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
                <tbody>{rows or '<tr><td colspan="5" class="text-center">ጥያቄ የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Department Dashboard", content)


@app.route("/requests")
@login_required
def requests_list():
    if current_user.role == "DEPARTMENT":
        return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE":
        return redirect(url_for("employee_dashboard"))
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        reqs = MaintenanceRequest.query.filter_by(assigned_to_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()

    rows = ""
    for r in reqs:
        cls = "table-danger" if r.is_overdue else ""
        rows += f"""
        <tr class="{cls}">
        <td><a href="{url_for('request_detail', req_id=r.id)}" style="color: #f59e0b;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else 'N/A'}</td>
        <td>{r.department.name if r.department else 'N/A'}</td>
        <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info'}">{r.priority}</span></td>
        <td><span class="badge bg-{'success' if r.status in ['Completed','Closed'] else 'warning' if r.status=='Pending' else 'info'}">{r.status}</span></td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>"""

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-tasks"></i> የጥገና ጥያቄዎች</h2>
    <a class="btn btn-primary mb-3" href="{url_for('request_create')}"><i class="fas fa-plus-circle"></i> አዲስ ጥያቄ</a>
    <div class="card">
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>እቃ</th><th>ዲፓርትመንት</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
                    <tbody>{rows or '<tr><td colspan="7" class="text-center">ጥያቄ የለም</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return page("Requests", content)


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_create():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    departments = Department.query.order_by(Department.name).all()

    if request.method == "POST":
        location_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        item_id = request.form.get("working_item_id", type=int)
        category_id = request.form.get("category_id", type=int)
        department_id = request.form.get("department_id", type=int)
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "MEDIUM")
        due_date = request.form.get("due_date")

        if location_type not in ["Room", "Hotel Area"]:
            flash("የቦታ አይነት ልክ አይደለም", "danger")
            return redirect(url_for("request_create"))

        if location_type == "Room":
            room = Room.query.get(room_id)
            if not room or not (201 <= int(room.room_number) <= 300):
                flash("ልክ ያልሆነ ክፍል። ክፍሉ ከ201-300 መሆን አለበት።", "danger")
                return redirect(url_for("request_create"))
            floor = room.floor
            area_id = None
        else:
            area = Area.query.get(area_id)
            if not area:
                flash("ልክ ያልሆነ ቦታ", "danger")
                return redirect(url_for("request_create"))
            floor = None
            room_id = None

        if not description:
            flash("የችግሩ መግለጫ ያስፈልጋል", "danger")
            return redirect(url_for("request_create"))

        due = datetime.strptime(due_date, "%Y-%m-%dT%H:%M") if due_date else datetime.utcnow() + timedelta(hours=PRIORITIES.get(priority, 24))

        req = MaintenanceRequest(
            request_no=request_no_generator(),
            location_type=location_type,
            floor=floor,
            room_id=room_id,
            area_id=area_id,
            working_item_id=item_id,
            category_id=category_id,
            department_id=department_id,
            description=description,
            priority=priority,
            status="Pending",
            requested_by_id=current_user.id,
            due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_audit("Create", "MaintenanceRequest", req.id, new_value=f"{req.request_no} - {req.priority}")
        log_status_change(req.id, "Pending", notes="Request submitted")

        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify_users([u.id for u in managers], req.id, "New Maintenance Request",
                     f"A new request {req.request_no} has been submitted.",
                     "New Request")
        notify_users([current_user.id], req.id, "Request Submitted",
                     f"Your request {req.request_no} has been submitted successfully.", "Request Submitted")

        db.session.commit()
        flash("✅ ጥያቄዎ በተሳካ ሁኔታ ተልኳል!", "success")
        return redirect(url_for("index"))

    room_options = "".join(f'<option value="{r.id}">ክፍል {r.room_number} (ፎቅ {r.floor})</option>' for r in rooms)
    area_options = "".join(f'<option value="{a.id}">{a.name}</option>' for a in areas)
    item_options = "".join(f'<option value="{i.id}">{i.name}</option>' for i in items)
    category_options = "".join(f'<option value="{c.id}">{c.name}</option>' for c in categories)
    dept_options = "".join(f'<option value="{d.id}">{d.name}</option>' for d in departments)

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-plus-circle"></i> አዲስ የጥገና ጥያቄ</h2>
    <div class="card">
        <div class="card-body">
            <form method="post">
                <div class="row">
                    <div class="col-md-6 mb-3">
                        <label class="form-label">የቦታ አይነት *</label>
                        <select class="form-select" name="location_type" id="loc_type" onchange="toggleLocation()" required>
                            <option value="">-- ይምረጡ --</option>
                            <option value="Room">🏨 ክፍል</option>
                            <option value="Hotel Area">📍 የሆቴል ቦታ</option>
                        </select>
                    </div>
                    <div class="col-md-6 mb-3" id="room_div" style="display:none">
                        <label class="form-label">ክፍል *</label>
                        <select class="form-select" name="room_id">
                            <option value="">-- ክፍል ይምረጡ (201-300) --</option>
                            {room_options}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3" id="area_div" style="display:none">
                        <label class="form-label">ቦታ *</label>
                        <select class="form-select" name="area_id">
                            <option value="">-- ቦታ ይምረጡ --</option>
                            {area_options}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">የስራ እቃ *</label>
                        <select class="form-select" name="working_item_id" required>
                            <option value="">-- እቃ ይምረጡ --</option>
                            {item_options}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">ምድብ *</label>
                        <select class="form-select" name="category_id" required>
                            <option value="">-- ምድብ ይምረጡ --</option>
                            {category_options}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">ዲፓርትመንት *</label>
                        <select class="form-select" name="department_id" required>
                            <option value="">-- ዲፓርትመንት ይምረጡ --</option>
                            {dept_options}
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">ቅድሚያ *</label>
                        <select class="form-select" name="priority" required>
                            <option value="LOW">🟢 ዝቅተኛ - 72 ሰዓት</option>
                            <option value="MEDIUM" selected>🟡 መካከለኛ - 24 ሰዓት</option>
                            <option value="HIGH">🟠 ከፍተኛ - 4 ሰዓት</option>
                            <option value="URGENT">🔴 አስቸኳይ - 1 ሰዓት</option>
                        </select>
                    </div>
                    <div class="col-md-6 mb-3">
                        <label class="form-label">የመጨረሻ ቀን (አማራጭ)</label>
                        <input type="datetime-local" class="form-control" name="due_date">
                    </div>
                    <div class="col-12 mb-3">
                        <label class="form-label">የችግሩ መግለጫ *</label>
                        <textarea class="form-control" name="description" required rows="4" placeholder="ችግሩን በዝርዝር ይግለጹ..."></textarea>
                    </div>
                    <div class="col-12 mb-3">
                        <label class="form-label">ፎቶ (አማራጭ)</label>
                        <input type="file" class="form-control" name="photo" accept="image/*">
                    </div>
                    <div class="col-12">
                        <button type="submit" class="btn btn-primary btn-lg w-100"><i class="fas fa-paper-plane"></i> ጥያቄ ያስገቡ</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    <script>
    function toggleLocation() {{
        var type = document.getElementById('loc_type').value;
        document.getElementById('room_div').style.display = type === 'Room' ? 'block' : 'none';
        document.getElementById('area_div').style.display = type === 'Hotel Area' ? 'block' : 'none';
    }}
    </script>
    """
    return page("New Request", content)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    photos = Photo.query.filter_by(object_type="request", object_id=req.id).all()
    history = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.desc()).all()

    photo_html = "".join(f'<img src="/static/uploads/maintenance/{p.filename}" style="max-height: 200px; border-radius: 8px; margin: 5px; border: 2px solid rgba(245,158,11,0.3);">' for p in photos)
    history_html = "".join(f'<li style="color: #cbd5e1; padding: 5px 0;"><b>{h.status}</b> - {h.timestamp.strftime("%Y-%m-%d %H:%M") if h.timestamp else ""} {f"({h.notes})" if h.notes else ""}</li>' for h in history)

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-file-invoice"></i> ጥያቄ {req.request_no}</h2>
    <div class="row">
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <table class="table">
                        <tr><th style="color: #94a3b8; width: 150px;">ሁኔታ</th><td><span class="badge bg-{'success' if req.status in ['Completed','Closed'] else 'warning' if req.status=='Pending' else 'info'}">{req.status}</span></td></tr>
                        <tr><th style="color: #94a3b8;">ቦታ</th><td>{req.location_name}</td></tr>
                        <tr><th style="color: #94a3b8;">እቃ</th><td>{req.working_item.name if req.working_item else 'N/A'}</td></tr>
                        <tr><th style="color: #94a3b8;">ምድብ</th><td>{req.category.name if req.category else 'N/A'}</td></tr>
                        <tr><th style="color: #94a3b8;">ዲፓርትመንት</th><td>{req.department.name if req.department else 'N/A'}</td></tr>
                        <tr><th style="color: #94a3b8;">ቅድሚያ</th><td><span class="badge bg-{'danger' if req.priority=='URGENT' else 'warning' if req.priority=='HIGH' else 'info'}">{req.priority}</span></td></tr>
                        <tr><th style="color: #94a3b8;">የመጨረሻ ቀን</th><td>{req.due_date.strftime('%Y-%m-%d %H:%M') if req.due_date else ''}</td></tr>
                        <tr><th style="color: #94a3b8;">የጠየቀው</th><td>{req.requested_by.full_name if req.requested_by else 'N/A'}</td></tr>
                        <tr><th style="color: #94a3b8;">የተመደበ</th><td>{req.assigned_to.full_name if req.assigned_to else 'አልተመደበም'}</td></tr>
                        <tr><th style="color: #94a3b8;">መግለጫ</th><td>{req.description}</td></tr>
                    </table>
                </div>
            </div>

            <h5 class="mt-4 mb-3" style="color: #f59e0b;"><i class="fas fa-clock"></i> የሁኔታ ታሪክ</h5>
            <ul style="list-style: none; padding-left: 0;">{history_html or '<li style="color: #94a3b8;">ታሪክ የለም</li>'}</ul>
        </div>

        <div class="col-md-4">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title mb-3"><i class="fas fa-images"></i> ፎቶዎች</h5>
                    {photo_html or '<p style="color: #94a3b8;">ፎቶ የለም</p>'}
                </div>
            </div>

            {"" if current_user.role not in ["MANAGER", "ADMIN"] else f'''
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title mb-3">እርምጃዎች</h5>
                    {f'<a class="btn btn-success w-100 mb-2" href="{url_for("request_approve", req_id=req.id)}"><i class="fas fa-check"></i> አጽድቅ</a>' if req.status == "Pending" else ''}
                    {f'<a class="btn btn-warning w-100 mb-2" href="{url_for("workorder_create")}?request_id={req.id}"><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዝ</a>' if req.status in ["Approved", "Assigned"] else ''}
                    {f'<a class="btn btn-info w-100 mb-2" href="{url_for("request_verify", req_id=req.id)}"><i class="fas fa-check-double"></i> አረጋግጥ</a>' if req.status == "Completed" else ''}
                </div>
            </div>
            '''}
        </div>
    </div>
    """
    return page("Request Detail", content)


@app.route("/requests/<int:req_id>/approve")
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Pending":
        req.status = "Approved"
        log_status_change(req.id, "Approved", notes=f"Approved by {current_user.full_name}")
        notify_users([req.requested_by_id], req.id, "Request Approved", f"Your request {req.request_no} has been approved.", "Approved")
        db.session.commit()
        flash("ጥያቄው ጸድቋል", "success")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/verify")
@role_required("MANAGER", "ADMIN")
def request_verify(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Completed":
        req.status = "Verified"
        log_status_change(req.id, "Verified", notes=f"Verified by {current_user.full_name}")
        db.session.commit()
        flash("ስራው ተረጋግጧል", "success")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()

    rows = ""
    for wo in wos:
        rows += f"""
        <tr>
        <td><a href="{url_for('workorder_detail', wo_id=wo.id)}" style="color: #f59e0b;">{wo.work_order_no}</a></td>
        <td>{wo.request.location_name if wo.request else 'N/A'}</td>
        <td>{wo.assigned_to.full_name if wo.assigned_to else 'N/A'}</td>
        <td><span class="badge bg-{'success' if wo.status=='Completed' else 'warning' if wo.status=='Assigned' else 'info'}">{wo.status}</span></td>
        <td>{wo.created_at.strftime('%Y-%m-%d %H:%M') if wo.created_at else ''}</td>
        </tr>"""

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዞች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ትዕዛዝ #</th><th>ቦታ</th><th>የተመደበ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
                <tbody>{rows or '<tr><td colspan="5" class="text-center">ትዕዛዝ የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Work Orders", content)


@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = MaintenanceRequest.query.get(req_id) if req_id else None
    users = User.query.filter(User.role.in_(["TECHNICIAN", "MAINTENANCE STAFF", "SUPERVISOR"])).all()

    if request.method == "POST":
        request_id = request.form.get("request_id", type=int)
        assigned_to_id = request.form.get("assigned_to_id", type=int)
        req = MaintenanceRequest.query.get_or_404(request_id)
        req.status = "Assigned"
        req.assigned_to_id = assigned_to_id

        wo = WorkOrder(
            work_order_no=work_order_no_generator(),
            request_id=req.id,
            assigned_to_id=assigned_to_id,
            status="Assigned",
        )
        db.session.add(wo)
        log_status_change(req.id, "Assigned")
        notify_users([assigned_to_id], req.id, "Work Assigned", f"You have been assigned to {wo.work_order_no}", "Assigned")
        db.session.commit()
        flash("የስራ ትዕዛዝ ተፈጥሯል", "success")
        return redirect(url_for("workorders_list"))

    user_options = "".join(f'<option value="{u.id}">{u.full_name}</option>' for u in users)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-plus-circle"></i> የስራ ትዕዛዝ ፍጠር</h2>
    <div class="card">
        <div class="card-body">
            <form method="post">
                <input type="hidden" name="request_id" value="{req.id if req else ''}">
                <div class="mb-3">
                    <label class="form-label">ጥያቄ</label>
                    <input class="form-control" value="{req.request_no if req else ''}" disabled>
                </div>
                <div class="mb-3">
                    <label class="form-label">የተመደበ ሰራተኛ *</label>
                    <select class="form-select" name="assigned_to_id" required>
                        <option value="">-- ይምረጡ --</option>
                        {user_options}
                    </select>
                </div>
                <button class="btn btn-primary w-100"><i class="fas fa-save"></i> ፍጠር</button>
            </form>
        </div>
    </div>
    """
    return page("New Work Order", content)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-file-signature"></i> {wo.work_order_no}</h2>
    <div class="card">
        <div class="card-body">
            <table class="table">
                <tr><th style="color: #94a3b8;">ጥያቄ</th><td>{wo.request.request_no if wo.request else 'N/A'}</td></tr>
                <tr><th style="color: #94a3b8;">ቦታ</th><td>{wo.request.location_name if wo.request else 'N/A'}</td></tr>
                <tr><th style="color: #94a3b8;">ሁኔታ</th><td><span class="badge bg-info">{wo.status}</span></td></tr>
                <tr><th style="color: #94a3b8;">የተመደበ</th><td>{wo.assigned_to.full_name if wo.assigned_to else 'N/A'}</td></tr>
            </table>
        </div>
    </div>
    """
    return page("Work Order Detail", content)


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    rows = ""
    for n in notifs:
        rows += f"""
        <tr class="{'table-info' if not n.is_read else ''}">
        <td>{n.title}</td>
        <td>{n.message}</td>
        <td>{n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else ''}</td>
        <td>{'<a href="' + url_for("notification_mark_read", n_id=n.id) + '" class="btn btn-sm btn-primary">አንብብ</a>' if not n.is_read else '✓'}</td>
        </tr>"""

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-bell"></i> ማሳወቂያዎች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ርዕስ</th><th>መልእክት</th><th>ቀን</th><th></th></tr></thead>
                <tbody>{rows or '<tr><td colspan="4" class="text-center">ማሳወቂያ የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Notifications", content)


@app.route("/notifications/mark-read/<int:n_id>")
@login_required
def notification_mark_read(n_id):
    n = Notification.query.get_or_404(n_id)
    if n.user_id == current_user.id:
        n.is_read = True
        db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/rooms")
@login_required
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = "".join(f'<tr><td>{r.room_number}</td><td>{r.floor}</td><td>{r.status}</td></tr>' for r in rooms)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-door-open"></i> ክፍሎች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ክፍል</th><th>ፎቅ</th><th>ሁኔታ</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Rooms", content)


@app.route("/areas")
@login_required
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join(f'<tr><td>{a.name}</td><td>{a.department}</td><td>{a.status}</td></tr>' for a in areas)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-map-marked-alt"></i> ቦታዎች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ስም</th><th>ዲፓርትመንት</th><th>ሁኔታ</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Areas", content)


@app.route("/inventory")
@login_required
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = "".join(f'<tr><td>{p.part_name}</td><td>{p.quantity}</td><td>{p.unit}</td><td>{p.minimum_stock}</td></tr>' for p in parts)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-boxes"></i> ክምችት</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ስም</th><th>ብዛት</th><th>አሃድ</th><th>ዝቅተኛ</th></tr></thead>
                <tbody>{rows or '<tr><td colspan="4" class="text-center">እቃ የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Inventory", content)


@app.route("/employees")
@login_required
@role_required("ADMIN", "MANAGER")
def employees_list():
    employees = Employee.query.all()
    rows = "".join(f'<tr><td>{e.id}</td><td>{e.name}</td><td>{e.job_title}</td><td>{e.department}</td></tr>' for e in employees)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-users"></i> ሰራተኞች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ID</th><th>ስም</th><th>የስራ ድርሻ</th><th>ክፍል</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Employees", content)


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows = "".join(f'<tr><td>{u.username}</td><td>{u.full_name}</td><td>{u.role}</td><td>{"✓" if u.active else "✗"}</td></tr>' for u in users)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-user-cog"></i> ተጠቃሚዎች</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>Username</th><th>ስም</th><th>ሚና</th><th>ንቁ</th></tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Users", content)


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()
    rows = "".join(f'<tr><td>{a.user.full_name if a.user else "System"}</td><td>{a.action}</td><td>{a.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for a in logs)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-history"></i> Audit Log</h2>
    <div class="card">
        <div class="card-body">
            <table class="table table-hover">
                <thead><tr><th>ተጠቃሚ</th><th>እርምጃ</th><th>ቀን</th></tr></thead>
                <tbody>{rows or '<tr><td colspan="3" class="text-center">Log የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Audit Log", content)


@app.route("/reports")
@login_required
def reports():
    total = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()

    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-chart-bar"></i> ሪፖርቶች</h2>
    <div class="row g-4 mb-4">
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">ጠቅላላ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{in_progress}</div><div class="metric-label">በሂደት</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{completed}</div><div class="metric-label">ተጠናቅቋል</div></div></div>
    </div>
    <div class="card">
        <div class="card-body">
            <h5 class="card-title mb-3">CSV ላክ</h5>
            <a href="{url_for('reports_export', report_type='requests')}" class="btn btn-primary mb-2 w-100">ጥያቄዎችን ላክ</a>
            <a href="{url_for('reports_export', report_type='workorders')}" class="btn btn-primary mb-2 w-100">የስራ ትዕዛዞችን ላክ</a>
            <a href="{url_for('reports_export', report_type='inventory')}" class="btn btn-primary w-100">ክምችት ላክ</a>
        </div>
    </div>
    """
    return page("Reports", content)


@app.route("/reports/export/<report_type>")
@login_required
def reports_export(report_type):
    output = io.StringIO()
    writer = csv.writer(output)
    if report_type == "requests":
        writer.writerow(["Request No", "Location", "Status", "Priority", "Created"])
        for r in MaintenanceRequest.query.all():
            writer.writerow([r.request_no, r.location_name, r.status, r.priority, r.created_at])
    elif report_type == "workorders":
        writer.writerow(["WO No", "Request", "Status", "Assigned To"])
        for wo in WorkOrder.query.all():
            writer.writerow([wo.work_order_no, wo.request.request_no if wo.request else "", wo.status, wo.assigned_to.full_name if wo.assigned_to else ""])
    elif report_type == "inventory":
        writer.writerow(["Part Name", "Quantity", "Unit", "Min Stock"])
        for p in InventoryPart.query.all():
            writer.writerow([p.part_name, p.quantity, p.unit, p.minimum_stock])
    else:
        abort(404)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={report_type}.csv"})


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join(f'<tr><td>{b}</td><td><a href="{url_for("restore_backup", filename=b)}" class="btn btn-sm btn-warning">Restore</a></td></tr>' for b in backups)
    content = f"""
    <h2 class="fw-bold mb-4" style="color: #f59e0b;"><i class="fas fa-archive"></i> Backup</h2>
    <form method="post" action="/admin/backup/now" class="mb-4"><button class="btn btn-primary">Backup Now</button></form>
    <div class="card">
        <div class="card-body">
            <table class="table">
                <thead><tr><th>File</th><th></th></tr></thead>
                <tbody>{rows or '<tr><td colspan="2">Backup የለም</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    return page("Backup", content)


@app.route("/admin/backup/now", methods=["POST"])
@role_required("ADMIN")
def backup_now():
    filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    filepath = os.path.join(BACKUP_FOLDER, filename)
    src = sqlite3.connect(get_db_path())
    dst = sqlite3.connect(filepath)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    flash(f"Backup ተፈጥሯል: {filename}", "success")
    return redirect(url_for("backup_page"))


@app.route("/admin/restore/<filename>")
@role_required("ADMIN")
def restore_backup(filename):
    if not filename.endswith(".db"):
        abort(400)
    filepath = os.path.join(BACKUP_FOLDER, filename)
    if not os.path.exists(filepath):
        flash("Backup አልተገኘም", "danger")
        return redirect(url_for("backup_page"))
    src = sqlite3.connect(filepath)
    dst = sqlite3.connect(get_db_path())
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    db.session.remove()
    flash("Database ተመልሷል", "success")
    return redirect(url_for("backup_page"))


def get_db_path():
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return os.path.join(BASE_DIR, "hotel_maintenance.db")


# --------------------------------------------------------------
# PWA
# --------------------------------------------------------------
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Rori Hotel Maintenance",
        "short_name": "RoriMaint",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#f59e0b",
        "icons": []
    })


@app.route("/sw.js")
def service_worker():
    return Response("""self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {});""", mimetype="application/javascript")


@app.route('/logo.png')
def serve_logo():
    logo_path = os.path.join(app.root_path, 'file_00000000d93c821094a2e3f7dced7c77.png')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/png')
    return Response("", mimetype="image/png")


# --------------------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return page("Forbidden", '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> ፍቃድ የለዎትም</div>'), 403


@app.errorhandler(404)
def not_found(e):
    return page("Not Found", '<div class="alert alert-warning"><i class="fas fa-search"></i> ገጹ አልተገኘም</div>'), 404


@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    print("500 ERROR:", tb)
    return page("Server Error", f'''
    <div class="alert alert-danger">
        <h4><i class="fas fa-exclamation-triangle"></i> የስርዓት ስህተት</h4>
        <p>እባክዎ ቆየት ብለው እንደገና ይሞክሩ።</p>
        <details style="color: #94a3b8; font-size: 0.8rem;">
            <summary>Debug info</summary>
            <pre style="background: #0f172a; padding: 10px; border-radius: 8px; color: #cbd5e1; overflow: auto;">{tb[:1000]}</pre>
        </details>
    </div>
    '''), 500


# --------------------------------------------------------------
# INIT
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    ensure_database_schema()
    seed_data()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)