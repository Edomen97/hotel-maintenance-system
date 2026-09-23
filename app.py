import csv
import io
import os
import sqlite3
import uuid
import traceback
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, abort, flash, get_flashed_messages, jsonify, redirect,
    request, send_file, url_for, Response, render_template_string,
)
from flask_login import (
    LoginManager, UserMixin, current_user, login_required,
    login_user, logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import qrcode

# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════
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
    description = db.Column(db.Text)


class WorkingItem(db.Model):
    __tablename__ = "working_items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.Text)


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
    description = db.Column(db.Text)
    priority = db.Column(db.String(20), default="MEDIUM")
    status = db.Column(db.String(30), default="Pending")
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
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
        user_id=user_id, request_id=request_id, title=title,
        message=message, notification_type=notification_type, link=link
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
        request_id=request_id, status=status, user_id=user_id, notes=notes
    )
    db.session.add(hist)


def request_no_generator():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def work_order_no_generator():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_database_schema():
    """Safely add missing columns using PRAGMA for SQLite."""
    with app.app_context():
        try:
            if not db.engine.dialect.has_table(db.engine, 'departments'):
                db.create_all()
                print("Created tables")

            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(maintenance_requests)")
            existing_columns = [row[1] for row in cursor.fetchall()]
            conn.close()

            required_columns = {
                'department_id': 'ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER',
                'manager_id': 'ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER',
                'completion_note': 'ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT',
                'completed_date': 'ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME',
            }

            for col, sql in required_columns.items():
                if col not in existing_columns:
                    db.engine.execute(sql)
                    print(f"Added column {col}")

        except Exception as e:
            print(f"Schema migration error: {e}")


# ══════════════════════════════════════════════════════════════
# PAGE FUNCTION
# ══════════════════════════════════════════════════════════════
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
            nav_items.append(('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')))
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
        bell_html = f'''
        <a class="nav-link" href="{url_for('notifications')}" style="position:relative;">
            <i class="fas fa-bell"></i>
            {f'<span class="badge bg-danger" style="position:absolute; top:-5px; right:-5px; font-size:0.7rem;">{unread_count}</span>' if unread_count > 0 else ''}
        </a>
        '''

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
        background: rgba(15, 23, 42, 0.9) !important;
        backdrop-filter: blur(16px);
        border-bottom: 1px solid rgba(245, 158, 11, 0.25);
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        padding: 0.75rem 1.5rem;
    }}
    .navbar-brand {{
        font-weight: 800;
        font-size: 1.4rem;
        color: #f59e0b !important;
        text-shadow: 0 2px 8px rgba(245,158,11,0.3);
    }}
    .navbar-brand img {{
        height: 38px;
        vertical-align: middle;
        margin-right: 10px;
    }}
    .nav-link {{
        color: #cbd5e1 !important;
        font-weight: 500;
        padding: 0.6rem 1.2rem !important;
        border-radius: 40px;
        transition: all 0.25s ease;
        margin: 0 0.1rem;
        display: flex;
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
    .navbar-toggler {{ border-color: rgba(245,158,11,0.4); }}
    .container {{ max-width: 1280px; padding: 1.5rem; }}
    .card {{
        background: rgba(30, 41, 59, 0.7) !important;
        backdrop-filter: blur(8px);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 20px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.25);
        transition: all 0.3s ease;
        color: #e2e8f0;
        padding: 1.25rem;
        margin-bottom: 1.5rem;
    }}
    .card:hover {{
        transform: translateY(-4px);
        border-color: rgba(245, 158, 11, 0.3);
    }}
    .card-title {{ font-weight: 600; color: #f59e0b; }}
    .metric-card {{
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(245, 158, 11, 0.12);
        border-radius: 20px;
        padding: 1.2rem 1rem;
        text-align: center;
        transition: all 0.3s ease;
        height: 100%;
    }}
    .metric-card:hover {{
        transform: translateY(-6px);
        border-color: #f59e0b;
    }}
    .metric-icon {{ font-size: 2.2rem; color: #f59e0b; margin-bottom: 0.5rem; }}
    .metric-value {{ font-size: 2rem; font-weight: 700; color: #f8fafc; }}
    .metric-label {{ font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
    .table {{ color: #e2e8f0; }}
    .table thead th {{
        border-bottom: 2px solid rgba(245, 158, 11, 0.2);
        color: #f59e0b;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.75rem;
        padding: 8px 10px;
    }}
    .table td {{ padding: 8px 10px; vertical-align: middle; border-color: rgba(245, 158, 11, 0.08); }}
    .table-striped tbody tr:nth-of-type(odd) {{ background-color: rgba(30, 41, 59, 0.3); }}
    .btn {{
        border-radius: 40px;
        font-weight: 600;
        padding: 0.6rem 1.8rem;
        transition: all 0.25s ease;
        border: none;
    }}
    .btn-primary {{
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #0f172a;
        box-shadow: 0 4px 16px rgba(245, 158, 11, 0.25);
    }}
    .btn-primary:hover {{
        transform: translateY(-2px);
        background: linear-gradient(135deg, #fbbf24, #f59e0b);
        color: #0f172a;
    }}
    .btn-success {{ background: linear-gradient(135deg, #22c55e, #16a34a); color: white; }}
    .btn-success:hover {{ transform: translateY(-2px); color: white; }}
    .btn-warning {{ background: linear-gradient(135deg, #eab308, #ca8a04); color: #0f172a; }}
    .btn-warning:hover {{ transform: translateY(-2px); color: #0f172a; }}
    .btn-danger {{ background: linear-gradient(135deg, #ef4444, #dc2626); color: white; }}
    .btn-danger:hover {{ transform: translateY(-2px); color: white; }}
    .btn-info {{ background: linear-gradient(135deg, #06b6d4, #0891b2); color: white; }}
    .btn-info:hover {{ transform: translateY(-2px); color: white; }}
    .form-control, .form-select {{
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(245, 158, 11, 0.2);
        border-radius: 12px;
        color: #e2e8f0;
        padding: 0.75rem 1rem;
    }}
    .form-control:focus, .form-select:focus {{
        border-color: #f59e0b;
        box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.15);
        background: rgba(15, 23, 42, 0.8);
        color: #f8fafc;
    }}
    .form-label {{ font-weight: 500; color: #cbd5e1; margin-bottom: 0.4rem; }}
    .alert {{
        border-radius: 16px;
        border: none;
        background: rgba(30, 41, 59, 0.7);
        color: #e2e8f0;
        padding: 1rem 1.5rem;
        margin-bottom: 1.5rem;
    }}
    .alert-success {{ border-left: 4px solid #22c55e; }}
    .alert-danger {{ border-left: 4px solid #ef4444; }}
    .alert-warning {{ border-left: 4px solid #f59e0b; }}
    .login-card {{
        background: rgba(30, 41, 59, 0.5) !important;
        backdrop-filter: blur(20px);
        border: 1px solid rgba(245, 158, 11, 0.2);
        border-radius: 32px !important;
        padding: 2rem 2.5rem;
        box-shadow: 0 24px 80px rgba(0,0,0,0.5);
        max-width: 440px;
        margin: 0 auto;
    }}
    .profile-pic {{
        width: 150px;
        height: 150px;
        object-fit: cover;
        border-radius: 50%;
        border: 3px solid #f59e0b;
    }}
    @media (max-width: 768px) {{
        .navbar {{ padding: 0.5rem 1rem; }}
        .nav-link {{ padding: 0.5rem 0.8rem !important; font-size: 0.85rem; }}
        .metric-value {{ font-size: 1.5rem; }}
        .login-card {{ padding: 1.5rem; margin: 1rem; }}
    }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{url_for('dashboard')}">
      <img src="/logo.png" alt="Logo"> Rori Hotel
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


# ══════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════
def seed_data():
    for dept_name in ["Housekeeping", "Front Office", "Engineering", "Food & Beverage",
                      "Administration", "Security", "Maintenance", "Other"]:
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
        ("Buduchalley", "F&B"), ("Sillanto", "Unknown"), ("Fura", "Unknown"),
        ("Executive", "Unknown"), ("Mitima", "Unknown"), ("Odako", "Unknown"),
        ("Gudumale", "Unknown"), ("Bubble", "Unknown"), ("Bubbles", "Unknown"),
        ("Fura Corridor", "Unknown"), ("Executive Meeting Room", "Unknown"),
        ("Counter", "Unknown"),
    ]
    for name, dept in initial_areas:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    for c in ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry",
              "Civil", "Safety", "General", "Other"]:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    for i in ["Light", "Switch", "Window", "Door Key", "Door Lock", "Paint",
              "Mirror", "Drainage Cover", "Frame", "Background Frame",
              "Spot Light", "Plumbing", "AC", "Electrical", "Other"]:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    engineering_staff = [
        (1, "ተስፋሁን ነከረ", "General Mechanic"),
        (2, "ቸርነት አሞና", "General Mechanic"),
        (3, "ስምዖን ዮሐንስ", "General Mechanic"),
        (4, "አበባየሁ ክፍሌ", "Supervisor"),
        (5, "አሚር አወል", "Manager"),
        (6, "ዋሌ", "General Mechanic"),
        (7, "ፃዲቁ", "General Mechanic"),
    ]
    for emp_id, name, title in engineering_staff:
        if not Employee.query.get(emp_id):
            db.session.add(Employee(id=emp_id, name=name, job_title=title, department="Engineering"))

    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", full_name="System Administrator", role="ADMIN",
                     email="admin@rorihotel.local", phone="", profile_pic=None)
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
            user = User(username=s["username"], full_name=s["full_name"], role=s["role"],
                        email="", phone="", profile_pic=None)
            user.set_password("123456")
            db.session.add(user)

    db.session.commit()

    if MaintenanceRequest.query.count() == 0:
        admin_user = User.query.filter_by(username="admin").first()
        dept = Department.query.first()
        general_cat = Category.query.filter_by(name="General").first()
        note_records = [
            ("Sling", "Buduchalley"), ("Jemison Frame", "Sillanto"),
            ("Window", "Sillanto"), ("Paint", "Sillanto"), ("Paint", "Fura"),
            ("Paint", "Executive"), ("Background Frame", "Executive"),
            ("Door Key", "Mitima"), ("Corridor Paint", "Fura Corridor"),
            ("Light", "Executive Meeting Room"), ("Light", "Gudumale"),
            ("Light", "Counter"), ("Light", "Bubbles"),
            ("Cracked Mirror", "Executive Meeting Room"),
            ("Cracked Mirror", "Gudumale"), ("Cracked Mirror", "Counter"),
            ("Cracked Mirror", "Bubbles"),
            ("Drainage Line Cover", "Executive Meeting Room"),
            ("Drainage Line Cover", "Gudumale"), ("Drainage Line Cover", "Counter"),
            ("Drainage Line Cover", "Bubbles"), ("Switch Cover", "Odako"),
            ("Stage Light Switch Separation", "Odako"),
            ("Stage Light Switch Separation", "Gudumale"),
            ("Counter Paint / Spot Light", "Bubble"),
        ]
        for item_name, area_name in note_records:
            area = Area.query.filter_by(name=area_name).first()
            item = WorkingItem.query.filter_by(name=item_name.split(" / ")[0]).first()
            if not item:
                item = WorkingItem.query.filter_by(name="Other").first()
            if area and item:
                req = MaintenanceRequest(
                    request_no=request_no_generator(),
                    location_type="Hotel Area",
                    area_id=area.id,
                    working_item_id=item.id,
                    category_id=general_cat.id if general_cat else None,
                    description=f"Initial maintenance note: {item_name} at {area_name}",
                    priority="MEDIUM",
                    status="Pending",
                    requested_by_id=admin_user.id if admin_user else None,
                    department_id=dept.id if dept else None,
                    due_date=datetime.utcnow() + timedelta(hours=24),
                )
                db.session.add(req)
        db.session.commit()
        print(f"✅ Added {len(note_records)} initial requests")
    print("✅ Seed data loaded")


# ══════════════════════════════════════════════════════════════
# ROOT & AUTH
# ══════════════════════════════════════════════════════════════
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

    login_html = '''
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-11 col-md-5">
            <div class="login-card">
                <div class="text-center mb-4">
                    <img src="/logo.png" alt="Logo" style="height: 50px; margin-bottom: 10px;">
                    <h3 class="fw-bold" style="color: #f59e0b;">Rori Hotel</h3>
                    <p style="color: #94a3b8;">የጥገና ክፍል መግቢያ</p>
                </div>
                <form method="post">
                    <div class="mb-3">
                        <label class="form-label">መለያ ስም</label>
                        <input type="text" class="form-control form-control-lg" name="username" required>
                    </div>
                    <div class="mb-4">
                        <label class="form-label">የይለፍ ቃል</label>
                        <input type="password" class="form-control form-control-lg" name="password" required>
                    </div>
                    <button class="btn btn-primary btn-lg w-100"><i class="fas fa-sign-in-alt"></i> ግባ / Login</button>
                </form>
                <hr class="my-4" style="border-color: rgba(245,158,11,0.15);">
                <div class="text-center small" style="color: #94a3b8;">
                    <p class="mb-1">Admin: admin | admin123</p>
                    <p class="mb-0">Staff: amir | 123456</p>
                </div>
            </div>
        </div>
    </div>
    '''
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
        user.email = request.form.get("email", "").strip()
        user.phone = request.form.get("phone", "").strip()
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
    content = f'''
    <div class="row">
        <div class="col-md-4 text-center">
            <img src="{pic_url}" class="profile-pic img-thumbnail mb-3" alt="Profile">
            <h4 style="color: #f8fafc;">{user.full_name}</h4>
            <p style="color: #94a3b8;">@{user.username} · {user.role}</p>
        </div>
        <div class="col-md-8">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title"><i class="fas fa-user-edit"></i> አርትዕ መገለጫ</h5>
                    <form method="post" enctype="multipart/form-data">
                        <div class="mb-3"><label class="form-label">ኢሜል</label>
                            <input type="email" class="form-control" name="email" value="{user.email or ''}"></div>
                        <div class="mb-3"><label class="form-label">ስልክ</label>
                            <input type="text" class="form-control" name="phone" value="{user.phone or ''}"></div>
                        <div class="mb-3"><label class="form-label">የመገለጫ ሥዕል</label>
                            <input type="file" class="form-control" name="profile_pic" accept="image/*"></div>
                        <div class="mb-3"><label class="form-label">አዲስ የይለፍ ቃል</label>
                            <input type="password" class="form-control" name="new_password" placeholder="ባዶ ሆኖ ከቀረ አይለወጥም"></div>
                        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button>
                        <a href="/logout" class="btn btn-danger"><i class="fas fa-sign-out-alt"></i> ውጣ</a>
                    </form>
                </div>
            </div>
        </div>
    </div>
    '''
    return page("መገለጫ", content)


# ══════════════════════════════════════════════════════════════
# DASHBOARDS
# ══════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role not in ["ADMIN", "MANAGER"]:
        flash("ይህ ገጽ ለአስተዳዳሪዎች ብቻ ነው", "danger")
        return redirect(url_for("workorders_list"))

    total_requests = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()
    low_stock = sum(1 for p in InventoryPart.query.all() if p.is_low)
    total_employees = Employee.query.count()
    total_rooms = Room.query.count()

    content = f'''
    <h3 class="fw-bold" style="color: #f59e0b;"><i class="fas fa-crown"></i> የአስተዳዳሪ ዳሽቦርድ</h3>
    <p class="text-muted mb-4">እንኳን ደህና መጡ፣ {current_user.full_name}!</p>

    <div class="row g-4 mb-4">
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-tasks"></i></div><div class="metric-value">{total_requests}</div><div class="metric-label">ጥያቄዎች</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clock"></i></div><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-spinner"></i></div><div class="metric-value">{in_progress}</div><div class="metric-label">በሂደት</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-circle"></i></div><div class="metric-value">{completed}</div><div class="metric-label">የተጠናቀቁ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i></div><div class="metric-value">{urgent}</div><div class="metric-label">አስቸኳይ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color:#ef4444;"><i class="fas fa-clock"></i></div><div class="metric-value">{overdue}</div><div class="metric-label">ያለፉ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-box"></i></div><div class="metric-value">{low_stock}</div><div class="metric-label">ዝቅተኛ ክምችት</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-users"></i></div><div class="metric-value">{total_employees}</div><div class="metric-label">ሰራተኞች</div></div></div>
    </div>

    <div class="row g-3">
        <div class="col-md-4"><a class="btn btn-primary w-100 py-3" href="{url_for('requests_list')}"><i class="fas fa-list"></i> ጥያቄዎች</a></div>
        <div class="col-md-4"><a class="btn btn-success w-100 py-3" href="{url_for('workorders_list')}"><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዞች</a></div>
        <div class="col-md-4"><a class="btn btn-info w-100 py-3" href="{url_for('reports')}"><i class="fas fa-chart-bar"></i> ሪፖርቶች</a></div>
    </div>
    '''
    return page("Dashboard", content)


@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    rows = ""
    for r in requests:
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.priority}</td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''
    content = f'''
    <h3 style="color:#f59e0b;">My Dashboard</h3>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
    <table class="table">
    <thead><tr><th>Request</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="5" class="text-center">No requests</td></tr>'}</tbody>
    </table>
    </div>
    '''
    return page("My Dashboard", content)


@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    rows = ""
    for r in requests:
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.priority}</td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''
    content = f'''
    <h3 style="color:#f59e0b;">Department Dashboard</h3>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
    <table class="table">
    <thead><tr><th>Request</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="5" class="text-center">No requests</td></tr>'}</tbody>
    </table>
    </div>
    '''
    return page("Department", content)


# ══════════════════════════════════════════════════════════════
# REQUESTS
# ══════════════════════════════════════════════════════════════
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
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else 'N/A'}</td>
        <td>{r.priority}</td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''
    content = f'''
    <h3 style="color:#f59e0b;"><i class="fas fa-tasks"></i> Maintenance Requests</h3>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
    <div class="table-responsive">
    <table class="table table-hover">
    <thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="6" class="text-center">No requests</td></tr>'}</tbody>
    </table>
    </div>
    </div>
    '''
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

        if location_type == "Room":
            room = Room.query.get(room_id)
            if not room or not (201 <= int(room.room_number) <= 300):
                flash("ልክ ያልሆነ ክፍል", "danger")
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
            flash("መግለጫ ያስፈልጋል", "danger")
            return redirect(url_for("request_create"))

        due = datetime.strptime(due_date, "%Y-%m-%dT%H:%M") if due_date else datetime.utcnow() + timedelta(hours=PRIORITIES.get(priority, 24))
        req = MaintenanceRequest(
            request_no=request_no_generator(),
            location_type=location_type, floor=floor,
            room_id=room_id, area_id=area_id,
            working_item_id=item_id, category_id=category_id,
            department_id=department_id, description=description,
            priority=priority, status="Pending",
            requested_by_id=current_user.id, due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_audit("Create", "MaintenanceRequest", req.id, new_value=f"{req.request_no}")
        log_status_change(req.id, "Pending", notes="Request submitted")

        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify_users([u.id for u in managers], req.id, "New Maintenance Request",
                     f"A new request {req.request_no} has been submitted.", "New Request")
        notify_users([current_user.id], req.id, "Request Submitted",
                     f"Your request {req.request_no} has been submitted.", "Request Submitted")

        db.session.commit()
        flash("ጥያቄዎ ተልኳል!", "success")
        return redirect(url_for("requests_list"))

    room_options = "".join(f'<option value="{r.id}">Room {r.room_number} (Floor {r.floor})</option>' for r in rooms)
    area_options = "".join(f'<option value="{a.id}">{a.name}</option>' for a in areas)
    item_options = "".join(f'<option value="{i.id}">{i.name}</option>' for i in items)
    category_options = "".join(f'<option value="{c.id}">{c.name}</option>' for c in categories)
    dept_options = "".join(f'<option value="{d.id}">{d.name}</option>' for d in departments)

    content = f'''
    <h3 style="color:#f59e0b;"><i class="fas fa-plus-circle"></i> New Maintenance Request</h3>
    <div class="card">
    <form method="post">
    <div class="row">
    <div class="col-md-6 mb-3">
    <label class="form-label">Location Type</label>
    <select class="form-select" name="location_type" id="loc_type" onchange="toggleLocation()" required>
      <option value="Room">Room</option>
      <option value="Hotel Area">Hotel Area</option>
    </select>
    </div>
    <div class="col-md-6 mb-3" id="room_div">
    <label class="form-label">Room</label>
    <select class="form-select" name="room_id">{room_options}</select>
    </div>
    <div class="col-md-6 mb-3" id="area_div" style="display:none">
    <label class="form-label">Area</label>
    <select class="form-select" name="area_id"><option value="">-- Select --</option>{area_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Working Item</label>
    <select class="form-select" name="working_item_id" required><option value="">-- Select --</option>{item_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Category</label>
    <select class="form-select" name="category_id" required><option value="">-- Select --</option>{category_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Department</label>
    <select class="form-select" name="department_id" required><option value="">-- Select --</option>{dept_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Priority</label>
    <select class="form-select" name="priority">
      <option value="LOW">Low</option><option value="MEDIUM" selected>Medium</option>
      <option value="HIGH">High</option><option value="URGENT">Urgent</option>
    </select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Due Date</label>
    <input type="datetime-local" class="form-control" name="due_date">
    </div>
    <div class="col-12 mb-3">
    <label class="form-label">Description</label>
    <textarea class="form-control" name="description" required rows="4"></textarea>
    </div>
    <button class="btn btn-primary"><i class="fas fa-paper-plane"></i> Submit</button>
    </div>
    </form>
    </div>
    <script>
    function toggleLocation() {{
      var type = document.getElementById('loc_type').value;
      document.getElementById('room_div').style.display = type === 'Room' ? 'block' : 'none';
      document.getElementById('area_div').style.display = type === 'Hotel Area' ? 'block' : 'none';
    }}
    </script>
    '''
    return page("New Request", content)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    history = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.desc()).all()
    timeline = "".join(f'<li>{h.status} — {h.timestamp.strftime("%Y-%m-%d %H:%M") if h.timestamp else ""} {f"({h.notes})" if h.notes else ""}</li>' for h in history)

    content = f'''
    <h3 style="color:#f59e0b;">Request {req.request_no}</h3>
    <div class="card">
    <table class="table">
    <tr><th>Status</th><td>{req.status}</td></tr>
    <tr><th>Location</th><td>{req.location_name}</td></tr>
    <tr><th>Item</th><td>{req.working_item.name if req.working_item else "N/A"}</td></tr>
    <tr><th>Category</th><td>{req.category.name if req.category else "N/A"}</td></tr>
    <tr><th>Priority</th><td>{req.priority}</td></tr>
    <tr><th>Requester</th><td>{req.requested_by.full_name if req.requested_by else "Guest"}</td></tr>
    <tr><th>Description</th><td>{req.description or ""}</td></tr>
    </table>
    </div>
    <h5 style="color:#f59e0b;">Activity Timeline</h5>
    <div class="card">
    <ul>{timeline or "<li>No activity</li>"}</ul>
    </div>
    '''

    if current_user.role in ["MANAGER", "ADMIN"]:
        btns = ""
        if req.status == "Pending":
            btns += f'<a class="btn btn-success" href="/requests/{req.id}/approve">Approve</a> '
        if req.status == "Completed":
            btns += f'<a class="btn btn-success" href="/requests/{req.id}/verify">Verify</a> '
        if btns:
            content += f'<div class="mt-3">{btns}</div>'

    return page("Request Detail", content)


@app.route("/requests/<int:req_id>/approve")
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Pending":
        req.status = "Approved"
        req.manager_id = current_user.id
        log_status_change(req.id, "Approved", notes=f"Approved by {current_user.full_name}")
        notify_users([req.requested_by_id], req.id, "Approved", f"Request {req.request_no} approved", "Approved")
        db.session.commit()
        flash("Request approved", "success")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/verify")
@role_required("MANAGER", "ADMIN")
def request_verify(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Completed":
        req.status = "Verified"
        log_status_change(req.id, "Verified", notes=f"Verified by {current_user.full_name}")
        db.session.commit()
        flash("Work verified", "success")
    return redirect(url_for("request_detail", req_id=req_id))


# ══════════════════════════════════════════════════════════════
# WORK ORDERS
# ══════════════════════════════════════════════════════════════
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()

    rows = ""
    for wo in wos:
        rows += f'''
        <tr>
        <td><a href="/workorders/{wo.id}" style="color:#f59e0b;">{wo.work_order_no}</a></td>
        <td>{wo.request.location_name if wo.request else "N/A"}</td>
        <td>{wo.status}</td>
        <td>{wo.assigned_to.full_name if wo.assigned_to else "N/A"}</td>
        </tr>'''
    content = f'''
    <h3 style="color:#f59e0b;"><i class="fas fa-clipboard-list"></i> Work Orders</h3>
    <div class="card">
    <table class="table">
    <thead><tr><th>Order #</th><th>Location</th><th>Status</th><th>Assigned</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="4" class="text-center">No work orders</td></tr>'}</tbody>
    </table>
    </div>
    '''
    return page("Work Orders", content)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    content = f'''
    <h3 style="color:#f59e0b;">Work Order {wo.work_order_no}</h3>
    <div class="card">
    <table class="table">
    <tr><th>Request</th><td>{wo.request.request_no if wo.request else "N/A"}</td></tr>
    <tr><th>Location</th><td>{wo.request.location_name if wo.request else "N/A"}</td></tr>
    <tr><th>Status</th><td>{wo.status}</td></tr>
    <tr><th>Assigned</th><td>{wo.assigned_to.full_name if wo.assigned_to else "N/A"}</td></tr>
    </table>
    </div>
    '''
    return page("Work Order", content)


# ══════════════════════════════════════════════════════════════
# OTHER PAGES
# ══════════════════════════════════════════════════════════════
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = "".join(f'<tr><td>{r.room_number}</td><td>{r.floor}</td><td>{r.status}</td></tr>' for r in rooms)
    content = f'<h3 style="color:#f59e0b;">Rooms</h3><div class="card"><table class="table"><thead><tr><th>Room</th><th>Floor</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>'
    return page("Rooms", content)


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join(f'<tr><td>{a.name}</td><td>{a.department}</td></tr>' for a in areas)
    content = f'<h3 style="color:#f59e0b;">Areas</h3><div class="card"><table class="table"><thead><tr><th>Name</th><th>Dept</th></tr></thead><tbody>{rows}</tbody></table></div>'
    return page("Areas", content)


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = "".join(f'<tr><td>{p.part_name}</td><td>{p.quantity}</td><td>{p.unit}</td></tr>' for p in parts)
    content = f'<h3 style="color:#f59e0b;">Inventory</h3><div class="card"><table class="table"><thead><tr><th>Part</th><th>Qty</th><th>Unit</th></tr></thead><tbody>{rows or "<tr><td colspan=3>No parts</td></tr>"}</tbody></table></div>'
    return page("Inventory", content)


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    emps = Employee.query.all()
    rows = "".join(f'<tr><td>{e.id}</td><td>{e.name}</td><td>{e.job_title}</td></tr>' for e in emps)
    content = f'<h3 style="color:#f59e0b;">Employees</h3><div class="card"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Title</th></tr></thead><tbody>{rows}</tbody></table></div>'
    return page("Employees", content)


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows = "".join(f'<tr><td>{u.username}</td><td>{u.full_name}</td><td>{u.role}</td></tr>' for u in users)
    content = f'<h3 style="color:#f59e0b;">Users</h3><div class="card"><table class="table"><thead><tr><th>Username</th><th>Name</th><th>Role</th></tr></thead><tbody>{rows}</tbody></table></div>'
    return page("Users", content)


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join(f'<tr><td>{a.user.full_name if a.user else "System"}</td><td>{a.action}</td><td>{a.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for a in logs)
    content = f'<h3 style="color:#f59e0b;">Audit Log</h3><div class="card"><table class="table"><thead><tr><th>User</th><th>Action</th><th>Date</th></tr></thead><tbody>{rows or "<tr><td colspan=3>No logs</td></tr>"}</tbody></table></div>'
    return page("Audit Log", content)


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join(f'<tr><td>{b}</td></tr>' for b in backups)
    content = f'<h3 style="color:#f59e0b;">Backups</h3><div class="card"><table class="table"><thead><tr><th>File</th></tr></thead><tbody>{rows or "<tr><td>No backups</td></tr>"}</tbody></table></div>'
    return page("Backups", content)


@app.route("/reports")
@login_required
def reports():
    total = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    done = MaintenanceRequest.query.filter_by(status="Completed").count()
    content = f'''
    <h3 style="color:#f59e0b;">Reports</h3>
    <div class="row g-3 mb-4">
      <div class="col-4"><div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">Total</div></div></div>
      <div class="col-4"><div class="metric-card"><div class="metric-value">{pending}</div><div class="metric-label">Pending</div></div></div>
      <div class="col-4"><div class="metric-card"><div class="metric-value">{done}</div><div class="metric-label">Completed</div></div></div>
    </div>
    '''
    return page("Reports", content)


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    rows = "".join(f'<tr><td>{n.title}</td><td>{n.message}</td><td>{n.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for n in notifs)
    content = f'<h3 style="color:#f59e0b;">Notifications</h3><div class="card"><table class="table"><thead><tr><th>Title</th><th>Message</th><th>Date</th></tr></thead><tbody>{rows or "<tr><td colspan=3>No notifications</td></tr>"}</tbody></table></div>'
    return page("Notifications", content)


@app.route("/notifications/<int:n_id>/read")
@login_required
def notification_mark_read(n_id):
    n = Notification.query.get_or_404(n_id)
    if n.user_id == current_user.id:
        n.is_read = True
        db.session.commit()
    return redirect(url_for("notifications"))


# ══════════════════════════════════════════════════════════════
# PWA / LOGO
# ══════════════════════════════════════════════════════════════
@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel", "short_name": "RoriMaint", "start_url": "/dashboard", "display": "standalone", "background_color": "#0f172a", "theme_color": "#f59e0b", "icons": []})


@app.route("/sw.js")
def service_worker():
    return Response("self.addEventListener('install',e=>self.skipWaiting());", mimetype="application/javascript")


@app.route("/logo.png")
def serve_logo():
    logo_path = os.path.join(app.root_path, 'file_00000000d93c821094a2e3f7dced7c77.png')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/png')
    return Response("", mimetype="image/png")


# ══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════
@app.errorhandler(403)
def forbidden(e):
    return page("Forbidden", '<div class="alert alert-danger">You are not allowed to view this page.</div>'), 403


@app.errorhandler(404)
def not_found(e):
    return page("Not Found", '<div class="alert alert-warning">The page you requested was not found.</div>'), 404


@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    print("500 ERROR:", tb)
    return f"<h1>500 Error</h1><pre>{tb}</pre>", 500


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