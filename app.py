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
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Roles include DEPARTMENT for department portal
ROLES = ["ADMIN", "MANAGER", "SUPERVISOR", "TECHNICIAN", "MAINTENANCE STAFF", "EMPLOYEE", "DEPARTMENT"]
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
    due_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    working_item = db.relationship("WorkingItem", foreign_keys=[working_item_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])

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


class Inspection(db.Model):
    __tablename__ = "inspections"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("checklist_templates.id"))
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    inspector_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    inspection_date = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    template = db.relationship("ChecklistTemplate")
    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    inspector = db.relationship("User", foreign_keys=[inspector_id])
    items = db.relationship("InspectionItem", back_populates="inspection", cascade="all, delete-orphan")

    @property
    def pass_count(self):
        return sum(1 for i in self.items if i.result == "Pass")

    @property
    def fail_count(self):
        return sum(1 for i in self.items if i.result == "Fail")

    @property
    def pass_rate(self):
        total = len(self.items)
        return round(self.pass_count / total * 100, 1) if total else 0


class InspectionItem(db.Model):
    __tablename__ = "inspection_items"
    id = db.Column(db.Integer, primary_key=True)
    inspection_id = db.Column(db.Integer, db.ForeignKey("inspections.id"), nullable=False)
    item_text = db.Column(db.String(200), nullable=False)
    result = db.Column(db.String(10), default="Pass")
    notes = db.Column(db.Text)

    inspection = db.relationship("Inspection", back_populates="items")


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
    message = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), default="General")
    request_id = db.Column(db.Integer)
    work_order_id = db.Column(db.Integer)
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])


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
# HELPERS
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


def notify(user_ids, message, type="General", request_id=None, work_order_id=None):
    user_ids = set(user_ids)
    for uid in user_ids:
        if uid:
            n = Notification(
                user_id=uid,
                message=message,
                type=type,
                request_id=request_id,
                work_order_id=work_order_id,
            )
            db.session.add(n)


def request_no_generator():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def work_order_no_generator():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# --------------------------------------------------------------
# PAGE FUNCTION WITH LUXURY THEME (INLINE CSS)
# --------------------------------------------------------------
def page(title, content):
    nav_items = []
    if current_user.is_authenticated:
        if current_user.role == "DEPARTMENT":
            nav_items.append(('<i class="fas fa-home"></i> Dashboard', '/department'))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', '/requests/new'))
            nav_items.append(('<i class="fas fa-tasks"></i> My Requests', '/department'))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', '/profile'))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', '/logout'))
        else:
            nav_items.append(('<i class="fas fa-home"></i> Dashboard', '/dashboard'))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', '/requests/new'))
            nav_items.append(('<i class="fas fa-tasks"></i> Requests', '/requests'))
            nav_items.append(('<i class="fas fa-clipboard-list"></i> Work Orders', '/workorders'))
            if current_user.role in ["ADMIN", "MANAGER"]:
                nav_items.append(('<i class="fas fa-door-open"></i> Rooms', '/rooms'))
                nav_items.append(('<i class="fas fa-map-marked-alt"></i> Areas', '/areas'))
                nav_items.append(('<i class="fas fa-boxes"></i> Inventory', '/inventory'))
                nav_items.append(('<i class="fas fa-calendar-check"></i> Preventive', '/preventive'))
                nav_items.append(('<i class="fas fa-list-check"></i> Checklists', '/checklists'))
                nav_items.append(('<i class="fas fa-truck"></i> Suppliers', '/suppliers'))
                nav_items.append(('<i class="fas fa-hard-hat"></i> Contractors', '/contractors'))
                nav_items.append(('<i class="fas fa-users"></i> Employees', '/employees'))
            if current_user.role == "ADMIN":
                nav_items.append(('<i class="fas fa-user-cog"></i> Users', '/admin/users'))
                nav_items.append(('<i class="fas fa-database"></i> Master Data', '/admin/masterdata'))
                nav_items.append(('<i class="fas fa-history"></i> Audit Log', '/admin/audit'))
                nav_items.append(('<i class="fas fa-archive"></i> Backup', '/admin/backup'))
            nav_items.append(('<i class="fas fa-chart-bar"></i> Reports', '/reports'))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', '/notifications'))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', '/profile'))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', '/logout'))
    else:
        nav_items.append(('<i class="fas fa-sign-in-alt"></i> Login', '/login'))

    nav_html = "".join(f'<a class="nav-link" href="{url}">{label}</a>' for label, url in nav_items)

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
    /* LUXURY THEME – inline to avoid missing files */
    @import url('https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300;14..32,400;14..32,600;14..32,700&display=swap');
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        font-family: 'Inter', sans-serif;
        background: linear-gradient(145deg, #0f172a 0%, #1e293b 100%);
        min-height: 100vh;
        color: #e2e8f0;
        padding-top: 70px;
    }}
    .navbar {{
        background: rgba(15, 23, 42, 0.75) !important;
        backdrop-filter: blur(16px) saturate(180%);
        -webkit-backdrop-filter: blur(16px) saturate(180%);
        border-bottom: 1px solid rgba(245, 158, 11, 0.25);
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        padding: 0.75rem 1.5rem;
    }}
    .navbar-brand {{
        font-weight: 700;
        font-size: 1.4rem;
        letter-spacing: 0.5px;
        color: #f59e0b !important;
        text-shadow: 0 2px 8px rgba(245,158,11,0.3);
    }}
    .navbar-brand img {{
        height: 38px;
        vertical-align: middle;
        margin-right: 10px;
        filter: drop-shadow(0 2px 6px rgba(245,158,11,0.2));
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
    }}
    .nav-link i {{
        font-size: 1.1rem;
        width: 1.5rem;
        text-align: center;
        color: #f59e0b;
        transition: color 0.2s;
    }}
    .nav-link:hover {{
        background: rgba(245, 158, 11, 0.12);
        color: #f59e0b !important;
        transform: translateY(-1px);
    }}
    .nav-link:hover i {{
        color: #fbbf24;
    }}
    .navbar-nav .active {{
        background: rgba(245, 158, 11, 0.18);
        color: #f59e0b !important;
        box-shadow: 0 0 20px rgba(245,158,11,0.08);
    }}
    .navbar-toggler {{
        border-color: rgba(245,158,11,0.4);
    }}
    .navbar-toggler-icon {{
        background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 30 30'%3e%3cpath stroke='rgba(245,158,11,0.8)' stroke-linecap='round' stroke-miterlimit='10' stroke-width='2' d='M4 7h22M4 15h22M4 23h22'/%3e%3c/svg%3e");
    }}
    .container {{
        max-width: 1280px;
        padding: 1.5rem;
    }}
    .card {{
        background: rgba(30, 41, 59, 0.6) !important;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        border: 1px solid rgba(245, 158, 11, 0.15);
        border-radius: 20px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.25);
        transition: transform 0.25s ease, box-shadow 0.3s ease;
        color: #e2e8f0;
        padding: 1.25rem;
        margin-bottom: 1.5rem;
    }}
    .card:hover {{
        transform: translateY(-4px);
        box-shadow: 0 16px 48px rgba(0,0,0,0.4);
        border-color: rgba(245, 158, 11, 0.3);
    }}
    .card-title {{
        font-weight: 600;
        color: #f59e0b;
        letter-spacing: 0.3px;
    }}
    .metric-card {{
        background: rgba(30, 41, 59, 0.5);
        backdrop-filter: blur(8px);
        border: 1px solid rgba(245, 158, 11, 0.12);
        border-radius: 20px;
        padding: 1.2rem 1rem;
        text-align: center;
        transition: all 0.3s ease;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }}
    .metric-card:hover {{
        transform: translateY(-6px);
        border-color: #f59e0b;
        box-shadow: 0 12px 40px rgba(0,0,0,0.3);
    }}
    .metric-icon {{
        font-size: 2.2rem;
        color: #f59e0b;
        margin-bottom: 0.5rem;
        opacity: 0.9;
    }}
    .metric-value {{
        font-size: 2rem;
        font-weight: 700;
        color: #f8fafc;
        line-height: 1.2;
    }}
    .metric-label {{
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 0.25rem;
    }}
    .table {{
        color: #e2e8f0;
        border-color: rgba(245, 158, 11, 0.1);
    }}
    .table thead th {{
        border-bottom: 2px solid rgba(245, 158, 11, 0.2);
        color: #f59e0b;
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.5px;
    }}
    .table td, .table th {{
        border-color: rgba(245, 158, 11, 0.08);
        padding: 0.75rem;
        vertical-align: middle;
    }}
    .table-striped tbody tr:nth-of-type(odd) {{
        background-color: rgba(30, 41, 59, 0.3);
    }}
    .table-hover tbody tr:hover {{
        background-color: rgba(245, 158, 11, 0.06);
    }}
    .btn {{
        border-radius: 40px;
        font-weight: 600;
        padding: 0.6rem 1.8rem;
        transition: all 0.25s ease;
        border: none;
        letter-spacing: 0.3px;
    }}
    .btn-primary {{
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #0f172a;
        box-shadow: 0 4px 16px rgba(245, 158, 11, 0.25);
    }}
    .btn-primary:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 28px rgba(245, 158, 11, 0.4);
        background: linear-gradient(135deg, #fbbf24, #f59e0b);
        color: #0f172a;
    }}
    .btn-success {{
        background: linear-gradient(135deg, #22c55e, #16a34a);
        box-shadow: 0 4px 16px rgba(34, 197, 94, 0.25);
    }}
    .btn-success:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 28px rgba(34, 197, 94, 0.4);
        background: linear-gradient(135deg, #4ade80, #22c55e);
    }}
    .btn-warning {{
        background: linear-gradient(135deg, #eab308, #ca8a04);
        color: #0f172a;
        box-shadow: 0 4px 16px rgba(234, 179, 8, 0.25);
    }}
    .btn-warning:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 28px rgba(234, 179, 8, 0.4);
        background: linear-gradient(135deg, #facc15, #eab308);
        color: #0f172a;
    }}
    .btn-danger {{
        background: linear-gradient(135deg, #ef4444, #dc2626);
        box-shadow: 0 4px 16px rgba(239, 68, 68, 0.25);
    }}
    .btn-danger:hover {{
        transform: translateY(-2px);
        box-shadow: 0 8px 28px rgba(239, 68, 68, 0.4);
        background: linear-gradient(135deg, #f87171, #ef4444);
    }}
    .form-control, .form-select {{
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(245, 158, 11, 0.2);
        border-radius: 12px;
        color: #e2e8f0;
        padding: 0.75rem 1rem;
        transition: border-color 0.2s, box-shadow 0.2s;
    }}
    .form-control:focus, .form-select:focus {{
        border-color: #f59e0b;
        box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.15);
        background: rgba(15, 23, 42, 0.8);
        color: #f8fafc;
    }}
    .form-label {{
        font-weight: 500;
        color: #cbd5e1;
        margin-bottom: 0.4rem;
    }}
    .alert {{
        border-radius: 16px;
        border: none;
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(8px);
        color: #e2e8f0;
        padding: 1rem 1.5rem;
        margin-bottom: 1.5rem;
    }}
    .alert-success {{
        border-left: 4px solid #22c55e;
    }}
    .alert-danger {{
        border-left: 4px solid #ef4444;
    }}
    .alert-warning {{
        border-left: 4px solid #f59e0b;
    }}
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
        box-shadow: 0 8px 32px rgba(245,158,11,0.15);
    }}
    @media (max-width: 768px) {{
        .navbar {{
            padding: 0.5rem 1rem;
        }}
        .nav-link {{
            padding: 0.5rem 0.8rem !important;
            font-size: 0.9rem;
        }}
        .metric-value {{
            font-size: 1.5rem;
        }}
        .login-card {{
            padding: 1.5rem;
            margin: 1rem;
        }}
    }}
    ::-webkit-scrollbar {{
        width: 8px;
        background: #0f172a;
    }}
    ::-webkit-scrollbar-thumb {{
        background: #f59e0b;
        border-radius: 10px;
    }}
    ::-webkit-scrollbar-thumb:hover {{
        background: #d97706;
    }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="/dashboard">
      <img src="/logo.png" alt="Rori Hotel Logo"> Rori Hotel
    </a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="nav">
      <div class="navbar-nav ms-auto">
        {nav_html}
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
# ROOT ROUTE – prevents 404 on base URL
# --------------------------------------------------------------
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN", "MANAGER"]:
            return redirect(url_for("dashboard"))
        elif current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        else:
            return redirect(url_for("workorders_list"))
    return redirect(url_for("login"))


# --------------------------------------------------------------
# SEED DATA
# --------------------------------------------------------------
def seed_data():
    # Floors
    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    # Rooms
    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))

    # Areas
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

    # Categories
    categories = ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry", "Civil", "Safety", "General", "Other"]
    for c in categories:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    # Working Items
    items = [
        "Light", "Switch", "Window", "Door Key", "Door Lock", "Paint", "Mirror",
        "Drainage Cover", "Frame", "Background Frame", "Spot Light", "Plumbing",
        "AC", "Electrical", "Other",
    ]
    for i in items:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    # Employees
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

    # Users – clear and recreate with exact accounts
    User.query.delete()
    db.session.commit()

    admin = User(
        username="admin",
        full_name="System Administrator",
        role="ADMIN",
        email="admin@rorihotel.local",
        phone="",
        profile_pic=None
    )
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
    ]
    for s in staff_list:
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

    # Sample maintenance requests
    if MaintenanceRequest.query.count() == 0:
        admin_user = User.query.filter_by(username="admin").first()
        note_records = [
            ("Sling", "Buduchalley"),
            ("Jemison Frame", "Sillanto"),
            ("Window", "Sillanto"),
            ("Paint", "Sillanto"),
            ("Paint", "Fura"),
            ("Paint", "Executive"),
            ("Background Frame", "Executive"),
            ("Door Key", "Mitima"),
            ("Corridor Paint", "Fura Corridor"),
            ("Light", "Executive Meeting Room"),
            ("Light", "Gudumale"),
            ("Light", "Counter"),
            ("Light", "Bubbles"),
            ("Cracked Mirror", "Executive Meeting Room"),
            ("Cracked Mirror", "Gudumale"),
            ("Cracked Mirror", "Counter"),
            ("Cracked Mirror", "Bubbles"),
            ("Drainage Line Cover", "Executive Meeting Room"),
            ("Drainage Line Cover", "Gudumale"),
            ("Drainage Line Cover", "Counter"),
            ("Drainage Line Cover", "Bubbles"),
            ("Switch Cover", "Odako"),
            ("Stage Light Switch Separation", "Odako"),
            ("Stage Light Switch Separation", "Gudumale"),
            ("Counter Paint / Spot Light", "Bubble"),
        ]
        for item_name, area_name in note_records:
            area = Area.query.filter_by(name=area_name).first()
            item_name_part = item_name.split(" / ")[0]
            item = WorkingItem.query.filter_by(name=item_name_part).first()
            if not item:
                item = WorkingItem.query.filter_by(name="Other").first()
            if area and item:
                req = MaintenanceRequest(
                    request_no=request_no_generator(),
                    location_type="Hotel Area",
                    area_id=area.id,
                    working_item_id=item.id,
                    category_id=Category.query.filter_by(name="General").first().id if Category.query.filter_by(name="General").first() else None,
                    description=f"Initial maintenance note: {item_name} at {area_name}",
                    priority="MEDIUM",
                    status="Pending",
                    requested_by_id=admin_user.id if admin_user else None,
                    due_date=datetime.utcnow() + timedelta(hours=24),
                )
                db.session.add(req)
        db.session.commit()


# --------------------------------------------------------------
# AUTH
# --------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN", "MANAGER"]:
            return redirect(url_for("dashboard"))
        elif current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        else:
            return redirect(url_for("workorders_list"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.active:
            login_user(user)
            log_audit("Login", "User", user.id)
            db.session.commit()
            if user.role in ["ADMIN", "MANAGER"]:
                return redirect(url_for("dashboard"))
            elif user.role == "DEPARTMENT":
                return redirect(url_for("department_dashboard"))
            else:
                return redirect(url_for("workorders_list"))

        flash("የተሳሳተ መለያ ስም ወይም የይለፍ ቃል", "danger")

    login_html = """
    <div class="row justify-content-center align-items-center" style="min-height: 80vh;">
        <div class="col-11 col-md-5">
            <div class="login-card">
                <div class="text-center mb-4">
                    <img src="/logo.png" alt="Rori Hotel Logo" style="height: 50px; margin-bottom: 10px;">
                    <h3 class="fw-bold" style="color: #f59e0b;">Rori Hotel</h3>
                    <p class="text-muted" style="color: #94a3b8;">የጥገና ክፍል መግቢያ</p>
                </div>
                <form method="post">
                    <div class="mb-3">
                        <label class="form-label">መለያ ስም (Username)</label>
                        <input type="text" class="form-control form-control-lg" name="username" placeholder="ስም ያስገቡ..." required>
                    </div>
                    <div class="mb-4">
                        <label class="form-label">የይለፍ ቃል (Password)</label>
                        <input type="password" class="form-control form-control-lg" name="password" placeholder="********" required>
                    </div>
                    <button class="btn btn-primary btn-lg w-100"><i class="fas fa-sign-in-alt"></i> ግባ / Login</button>
                </form>
                <hr class="my-4" style="border-color: rgba(245,158,11,0.15);">
                <div class="text-center small text-muted" style="color: #94a3b8;">
                    <p class="mb-1">ማናጀር: amir | ሱፐርቫይዘር: abebayhu | ሰራተኛ: tesfahun</p>
                    <p class="mb-0">የይለፍ ቃል: 123456</p>
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


# --------------------------------------------------------------
# PROFILE (email, phone, photo, password)
# --------------------------------------------------------------
@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        if email != user.email or phone != user.phone:
            old_email = user.email
            old_phone = user.phone
            user.email = email
            user.phone = phone
            log_audit("Profile Update", "User", user.id, f"Email: {old_email}, Phone: {old_phone}", f"Email: {email}, Phone: {phone}")

        new_password = request.form.get("new_password", "").strip()
        if new_password:
            user.set_password(new_password)
            flash("የይለፍ ቃል ተቀይሯል", "success")

        file = request.files.get("profile_pic")
        if file and file.filename != "":
            if allowed_file(file.filename):
                if user.profile_pic:
                    old_path = os.path.join(app.config["PROFILE_PIC_FOLDER"], user.profile_pic)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = secure_filename(f"{user.id}_{uuid.uuid4().hex}.{ext}")
                file.save(os.path.join(app.config["PROFILE_PIC_FOLDER"], filename))
                user.profile_pic = filename
                log_audit("Profile Pic Update", "User", user.id, old_value=user.profile_pic, new_value=filename)
                flash("የመገለጫ ሥዕል ተለውጧል", "success")
            else:
                flash("ልክ ያልሆነ የፋይል አይነት", "danger")

        db.session.commit()
        flash("መረጃዎ ተዘምኗል", "success")
        return redirect(url_for("profile"))

    pic_url = url_for('static', filename=f'profile_pics/{user.profile_pic}') if user.profile_pic else url_for('static', filename='profile_pics/default.png')
    content = f"""
    <div class="row">
        <div class="col-md-4 text-center">
            <img src="{pic_url}" class="profile-pic img-thumbnail mb-3" alt="Profile Picture">
            <h4 style="color: #f8fafc;">{user.full_name}</h4>
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
                            <label class="form-label">አዲስ የይለፍ ቃል (ባዶ ሆኖ ከቀረ አይለወጥም)</label>
                            <input type="password" class="form-control" name="new_password" placeholder="********">
                        </div>
                        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ ለውጦች</button>
                        <a href="/logout" class="btn btn-danger"><i class="fas fa-sign-out-alt"></i> ውጣ / Logout</a>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """
    return page("መገለጫ", content)


# --------------------------------------------------------------
# DEPARTMENT DASHBOARD
# --------------------------------------------------------------
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    my_requests = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    rows = []
    for r in my_requests:
        rows.append(f"""
        <tr>
        <td><a href="/requests/{r.id}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else ''}</td>
        <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info' if r.priority=='MEDIUM' else 'secondary'}">{r.priority}</span></td>
        <td><span class="badge bg-{'success' if r.status=='Completed' else 'warning' if r.status=='Pending' else 'info'}">{r.status}</span></td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>""")
    content = f"""
    <h3><i class="fas fa-building"></i> የዲፓርትመንት ዳሽቦርድ</h3>
    <p class="text-muted">እንኳን ደህና መጡ፣ {current_user.full_name}!</p>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> አዲስ የጥገና ጥያቄ</a>
    <div class="card">
        <div class="card-body">
            <h5 class="card-title"><i class="fas fa-list"></i> የእኔ ጥያቄዎች</h5>
            <div class="table-responsive">
                <table class="table table-bordered table-striped table-hover">
                    <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>እቃ</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
                    <tbody>{''.join(rows) or '<tr><td colspan="6" class="text-center">እስካሁን ምንም ጥያቄ አልተላከም</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return page("Department Dashboard", content)


# --------------------------------------------------------------
# MANAGER / ADMIN DASHBOARD (with pending approvals)
# --------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role not in ["ADMIN", "MANAGER"]:
        flash("ይህ ገጽ ለአስተዳዳሪዎች ብቻ ነው", "danger")
        return redirect(url_for("workorders_list"))

    total_rooms = Room.query.count()
    total_requests = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()
    low_stock = sum(1 for p in InventoryPart.query.all() if p.is_low)
    out_rooms = Room.query.filter(Room.status.in_(["Maintenance", "Out of Service"])).count()
    total_employees = Employee.query.count()

    pending_requests = MaintenanceRequest.query.filter_by(status="Pending").order_by(MaintenanceRequest.created_at.desc()).all()
    pending_rows = ""
    for r in pending_requests:
        pending_rows += f"""
        <tr>
        <td>{r.request_no}</td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else ''}</td>
        <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info'}">{r.priority}</span></td>
        <td>{r.requested_by.full_name if r.requested_by else ''}</td>
        <td>
            <a href="/requests/{r.id}/approve" class="btn btn-success btn-sm"><i class="fas fa-check"></i> አጽድቅ</a>
            <a href="/requests/{r.id}" class="btn btn-info btn-sm"><i class="fas fa-eye"></i> ዝርዝር</a>
        </td>
        </tr>
        """

    content = f"""
    <div class="row g-4">
        <div class="col-12">
            <h3 class="fw-bold" style="color: #f59e0b;"><i class="fas fa-crown"></i> የአስተዳዳሪ ዳሽቦርድ</h3>
            <p class="text-muted" style="color: #94a3b8;">እንኳን ደህና መጡ፣ {current_user.full_name}!</p>
        </div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-tasks"></i></div><div class="metric-value">{total_requests}</div><div class="metric-label">ጥያቄዎች</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clock"></i></div><div class="metric-value">{pending}</div><div class="metric-label">በመጠባበቅ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-spinner"></i></div><div class="metric-value">{in_progress}</div><div class="metric-label">በሂደት ላይ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-circle"></i></div><div class="metric-value">{completed}</div><div class="metric-label">የተጠናቀቁ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card" style="border-color: rgba(239, 68, 68, 0.3);"><div class="metric-icon" style="color: #ef4444;"><i class="fas fa-exclamation-triangle"></i></div><div class="metric-value">{urgent}</div><div class="metric-label">አስቸኳይ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card" style="border-color: rgba(239, 68, 68, 0.3);"><div class="metric-icon" style="color: #ef4444;"><i class="fas fa-clock"></i></div><div class="metric-value">{overdue}</div><div class="metric-label">ያለፉ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color: #f59e0b;"><i class="fas fa-box"></i></div><div class="metric-value">{low_stock}</div><div class="metric-label">ዝቅተኛ ክምችት</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color: #3b82f6;"><i class="fas fa-door-open"></i></div><div class="metric-value">{out_rooms}</div><div class="metric-label">ክፍሎች ውጪ</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color: #22c55e;"><i class="fas fa-users"></i></div><div class="metric-value">{total_employees}</div><div class="metric-label">ሰራተኞች</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color: #8b5cf6;"><i class="fas fa-door-closed"></i></div><div class="metric-value">{total_rooms}</div><div class="metric-label">ክፍሎች</div></div></div>
    </div>

    <div class="card mt-4">
        <div class="card-body">
            <h5 class="card-title"><i class="fas fa-check-double"></i> የፀደቀ መጠበቅ ያለባቸው ጥያቄዎች</h5>
            <div class="table-responsive">
                <table class="table table-bordered table-hover">
                    <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>እቃ</th><th>ቅድሚያ</th><th>ጠያቂ</th><th>እርምጃ</th></tr></thead>
                    <tbody>{pending_rows or '<tr><td colspan="6" class="text-center">ምንም ጥያቄ አልተገኘም</td></tr>'}</tbody>
                </table>
            </div>
        </div>
    </div>

    <div class="row mt-4 g-3">
        <div class="col-md-4"><a class="btn btn-primary w-100" href="/requests"><i class="fas fa-list"></i> ጥያቄዎችን ይገምግሙ</a></div>
        <div class="col-md-4"><a class="btn btn-success w-100" href="/workorders"><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዞች</a></div>
        <div class="col-md-4"><a class="btn btn-warning w-100" href="/reports"><i class="fas fa-chart-bar"></i> ሪፖርቶች</a></div>
    </div>
    """
    return page("Dashboard", content)


# --------------------------------------------------------------
# REQUESTS ROUTES
# --------------------------------------------------------------
@app.route("/requests")
@login_required
def requests_list():
    if current_user.role == "DEPARTMENT":
        return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE":
        reqs = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    elif current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        reqs = MaintenanceRequest.query.filter_by(assigned_to_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()

    rows = []
    for r in reqs:
        cls = ""
        if r.is_overdue or r.priority == "URGENT":
            cls = "table-danger" if r.is_overdue else "table-warning"
        rows.append(f"""
        <tr class="{cls}">
        <td><a href="/requests/{r.id}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">{r.request_no}</a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else ''}</td>
        <td><span class="badge bg-{'danger' if r.priority=='URGENT' else 'warning' if r.priority=='HIGH' else 'info' if r.priority=='MEDIUM' else 'secondary'}">{r.priority}</span></td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>""")
    content = f"""
    <h3><i class="fas fa-tasks"></i> የጥገና ጥያቄዎች</h3>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> አዲስ ጥያቄ</a>
    <div class="table-responsive">
    <table class="table table-bordered table-striped table-hover">
    <thead><tr><th>ጥያቄ #</th><th>ቦታ</th><th>እቃ</th><th>ቅድሚያ</th><th>ሁኔታ</th><th>ቀን</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></div>"""
    return page("Requests", content)


@app.route("/requests/new", methods=["GET", "POST"])
@login_required
def request_create():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    room_id = request.args.get("room_id", type=int)
    if request.method == "POST":
        location_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        item_id = request.form.get("working_item_id", type=int)
        category_id = request.form.get("category_id", type=int)
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
            description=description,
            priority=priority,
            status="Pending",
            requested_by_id=current_user.id,
            due_date=due,
        )
        db.session.add(req)
        db.session.flush()
        log_audit("Create", "MaintenanceRequest", req.id, new_value=f"{req.request_no} - {req.priority}")
        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify([u.id for u in managers], f"አዲስ ጥያቄ {req.request_no} በ {req.location_name}", "አዲስ ጥያቄ", req.id)
        if priority == "URGENT":
            notify([u.id for u in managers], f"አስቸኳይ ጥያቄ {req.request_no}", "አስቸኳይ", req.id)
        db.session.commit()
        flash("ጥያቄዎ በተሳካ ሁኔታ ተልኳል", "success")
        return redirect(url_for("requests_list"))

    room_options = "".join(f'<option value="{r.id}">ክፍል {r.room_number} (ፎቅ {r.floor})</option>' for r in rooms)
    area_options = "".join(f'<option value="{a.id}">{a.name}</option>' for a in areas)
    item_options = "".join(f'<option value="{i.id}">{i.name}</option>' for i in items)
    category_options = "".join(f'<option value="{c.id}">{c.name}</option>' for c in categories)
    selected_room = f'<option value="{room_id}" selected>ክፍል {Room.query.get(room_id).room_number if room_id and Room.query.get(room_id) else ""}</option>' if room_id else ""
    content = f"""
    <h3><i class="fas fa-plus-circle"></i> አዲስ የጥገና ጥያቄ</h3>
    <div class="card">
    <div class="card-body">
    <form method="post">
    <div class="row">
    <div class="col-md-6 mb-3">
    <label class="form-label">የቦታ አይነት</label>
    <select class="form-select" name="location_type" id="loc_type" onchange="toggleLocation()" required>
      <option value="Room">ክፍል</option>
      <option value="Hotel Area">የሆቴል ቦታ</option>
    </select>
    </div>
    <div class="col-md-6 mb-3" id="room_div">
    <label class="form-label">ክፍል</label>
    <select class="form-select" name="room_id">{selected_room}{room_options}</select>
    </div>
    <div class="col-md-6 mb-3" id="area_div" style="display:none">
    <label class="form-label">ቦታ</label>
    <select class="form-select" name="area_id"><option value="">-- ቦታ ይምረጡ --</option>{area_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">የስራ እቃ</label>
    <select class="form-select" name="working_item_id" required><option value="">-- እቃ ይምረጡ --</option>{item_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">ምድብ</label>
    <select class="form-select" name="category_id" required><option value="">-- ምድብ ይምረጡ --</option>{category_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">ቅድሚያ</label>
    <select class="form-select" name="priority">
      <option value="LOW">ዝቅተኛ</option><option value="MEDIUM" selected>መካከለኛ</option>
      <option value="HIGH">ከፍተኛ</option><option value="URGENT">አስቸኳይ</option>
    </select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">የመጨረሻ ቀን (አማራጭ)</label>
    <input type="datetime-local" class="form-control" name="due_date">
    </div>
    <div class="col-12 mb-3">
    <label class="form-label">የችግሩ መግለጫ</label>
    <textarea class="form-control" name="description" required rows="4"></textarea>
    </div>
    <button class="btn btn-primary"><i class="fas fa-paper-plane"></i> ጥያቄ ይላኩ</button>
    </div>
    </form>
    </div></div>
    <script>
    function toggleLocation() {{
      var type = document.getElementById('loc_type').value;
      document.getElementById('room_div').style.display = type === 'Room' ? 'block' : 'none';
      document.getElementById('area_div').style.display = type === 'Hotel Area' ? 'block' : 'none';
    }}
    </script>"""
    return page("New Request", content)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    photos = Photo.query.filter_by(object_type="request", object_id=req.id).all()
    history = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.desc()).all()
    photo_html = "".join(f'<a href="/uploads/{p.filename}" target="_blank"><img src="/uploads/{p.filename}" height="100" class="m-1 rounded" style="border: 2px solid rgba(245,158,11,0.3);"></a>' for p in photos)
    history_html = "".join(f"<li class='list-group-item' style='background:transparent; border-color: rgba(245,158,11,0.1); color:#cbd5e1;'>{h.status} በ {h.timestamp.strftime('%Y-%m-%d %H:%M')} በ {h.user.full_name if h.user else 'System'}</li>" for h in history)

    content = f"""
    <h3><i class="fas fa-file-invoice"></i> ጥያቄ {req.request_no}</h3>
    <div class="row">
    <div class="col-md-8">
    <div class="card">
    <div class="card-body">
    <table class="table table-borderless">
    <tr><th style="width:150px; color:#94a3b8;">ሁኔታ</th><td><span class="badge bg-{'success' if req.status=='Completed' else 'warning' if req.status=='Pending' else 'info'}">{req.status}</span></td></tr>
    <tr><th style="color:#94a3b8;">ቦታ</th><td>{req.location_name}</td></tr>
    <tr><th style="color:#94a3b8;">እቃ</th><td>{req.working_item.name if req.working_item else ''}</td></tr>
    <tr><th style="color:#94a3b8;">ምድብ</th><td>{req.category.name if req.category else ''}</td></tr>
    <tr><th style="color:#94a3b8;">ቅድሚያ</th><td><span class="badge bg-{'danger' if req.priority=='URGENT' else 'warning' if req.priority=='HIGH' else 'info' if req.priority=='MEDIUM' else 'secondary'}">{req.priority}</span></td></tr>
    <tr><th style="color:#94a3b8;">የመጨረሻ ቀን</th><td>{req.due_date.strftime('%Y-%m-%d %H:%M') if req.due_date else ''}</td></tr>
    <tr><th style="color:#94a3b8;">የጠየቀው</th><td>{req.requested_by.full_name if req.requested_by else ''}</td></tr>
    <tr><th style="color:#94a3b8;">የተመደበለት</th><td>{req.assigned_to.full_name if req.assigned_to else 'አልተመደበም'}</td></tr>
    <tr><th style="color:#94a3b8;">መግለጫ</th><td>{req.description}</td></tr>
    </table>
    </div></div>
    <h5 class="mt-4" style="color:#f59e0b;"><i class="fas fa-history"></i> የሁኔታ ታሪክ</h5>
    <ul class="list-group">{history_html or '<li class="list-group-item" style="background:transparent; border-color: rgba(245,158,11,0.1); color:#cbd5e1;">እስካሁን ታሪክ የለም</li>'}</ul>
    </div>
    <div class="col-md-4">
    <div class="card">
    <div class="card-body">
    <h5 class="card-title"><i class="fas fa-images"></i> ፎቶዎች</h5>
    {photo_html or '<p class="text-muted">ፎቶ የለም</p>'}
    </div></div>
    </div>
    </div>
    """
    if current_user.role in ["MANAGER", "ADMIN"]:
        action_buttons = ""
        if req.status == "Pending":
            action_buttons += f'<a class="btn btn-success" href="/requests/{req.id}/approve"><i class="fas fa-check"></i> ፈቅድ</a> '
        if req.status in ["Approved", "Assigned"]:
            action_buttons += f'<a class="btn btn-warning" href="/workorders/new?request_id={req.id}"><i class="fas fa-clipboard-list"></i> ስራ አዝዝ</a> '
        if req.status == "Completed":
            action_buttons += f'<a class="btn btn-success" href="/requests/{req.id}/verify"><i class="fas fa-check-double"></i> አረጋግጥ</a>'
        content += f'<div class="mt-3">{action_buttons}</div>'

    wo = WorkOrder.query.filter_by(request_id=req.id).first()
    if wo and wo.completion_photo:
        content += f"""
        <div class="mt-3 card">
            <div class="card-body">
                <h6><i class="fas fa-camera"></i> 📸 የተሰራው ስራ ፎቶ ማረጋገጫ:</h6>
                <a href="/static/uploads/maintenance/{wo.completion_photo}" target="_blank">
                    <img src="/static/uploads/maintenance/{wo.completion_photo}" class="img-fluid rounded shadow-sm" style="max-height: 250px; border: 2px solid rgba(245,158,11,0.2);">
                </a>
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
        hist = StatusHistory(request_id=req.id, status=req.status, user_id=current_user.id)
        db.session.add(hist)
        log_audit("Approve", "MaintenanceRequest", req.id, "Pending", "Approved")
        notify([req.requested_by_id], f"ጥያቄዎ {req.request_no} ጸድቋል", "Status Changed", req.id)
        db.session.commit()
        flash("ጥያቄው ጸድቋል", "success")
    else:
        flash("ይህ ጥያቄ በመጠባበቅ ላይ አይደለም", "warning")
    return redirect(url_for("request_detail", req_id=req.id))


@app.route("/requests/<int:req_id>/verify")
@role_required("MANAGER", "ADMIN")
def request_verify(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Completed":
        old = req.status
        req.status = "Verified"
        req.completed_date = datetime.utcnow()
        hist = StatusHistory(request_id=req.id, status=req.status, user_id=current_user.id)
        db.session.add(hist)
        log_audit("Verification", "MaintenanceRequest", req.id, old, req.status)
        notify([req.requested_by_id], f"ጥያቄዎ {req.request_no} ተረጋግጧል", "Status Changed", req.id)
        db.session.commit()
        flash("ጥያቄው ተረጋግጧል", "success")
    return redirect(url_for("request_detail", req_id=req.id))


# --------------------------------------------------------------
# WORK ORDERS
# --------------------------------------------------------------
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "DEPARTMENT":
        flash("ይህ ገጽ ለዲፓርትመንት ተጠቃሚዎች አይገኝም", "danger")
        return redirect(url_for("department_dashboard"))

    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN"]:
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    rows = []
    for wo in wos:
        rows.append(f"""
        <tr>
        <td><a href="/workorders/{wo.id}" style="color: #f59e0b; text-decoration: none; font-weight: 600;">{wo.work_order_no}</a></td>
        <td>{wo.request.location_name if wo.request else ''}</td>
        <td>{wo.request.working_item.name if wo.request and wo.request.working_item else ''}</td>
        <td><span class="badge bg-{'success' if wo.status=='Completed' else 'warning' if wo.status=='Assigned' else 'info'}">{wo.status}</span></td>
        <td>{wo.assigned_to.full_name if wo.assigned_to else ''}</td>
        </tr>""")
    content = f"""
    <h3><i class="fas fa-clipboard-list"></i> የስራ ትዕዛዞች</h3>
    <div class="table-responsive">
    <table class="table table-bordered table-striped table-hover">
    <thead><tr><th>ትዕዛዝ #</th><th>ቦታ</th><th>እቃ</th><th>ሁኔታ</th><th>የተመደበ</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></div>"""
    return page("Work Orders", content)


@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = MaintenanceRequest.query.get(req_id) if req_id else None
    users = User.query.filter(User.role.in_(["TECHNICIAN", "MAINTENANCE STAFF", "SUPERVISOR"])).all()
    user_options = "".join(f'<option value="{u.id}">{u.full_name}</option>' for u in users)
    if request.method == "POST":
        request_id = request.form.get("request_id", type=int)
        assigned_to_id = request.form.get("assigned_to_id", type=int)
        work_performed = request.form.get("work_performed", "")
        req = MaintenanceRequest.query.get_or_404(request_id)
        if req.status not in ["Approved", "Assigned"]:
            flash("ይህ ጥያቄ እስካሁን አልጸደቀም። በመጀመሪያ ያጽድቁት", "danger")
            return redirect(url_for("request_detail", req_id=request_id))
        wo = WorkOrder(
            work_order_no=work_order_no_generator(),
            request_id=req.id,
            assigned_to_id=assigned_to_id,
            status="Assigned",
            work_performed=work_performed,
        )
        req.status = "Assigned"
        req.assigned_to_id = assigned_to_id
        hist = StatusHistory(request_id=req.id, status=req.status, user_id=current_user.id)
        db.session.add(hist)
        db.session.add(wo)
        db.session.flush()
        log_audit("Create", "WorkOrder", wo.id, new_value=wo.work_order_no)
        notify([assigned_to_id], f"አዲስ የስራ ትዕዛዝ {wo.work_order_no} ተመድቧል", "Work Order Assigned", req.id, wo.id)
        db.session.commit()
        flash("የስራ ትዕዛዝ ተፈጥሯል", "success")
        return redirect(url_for("workorders_list"))
    content = f"""
    <h3><i class="fas fa-plus-circle"></i> የስራ ትዕዛዝ ይፍጠሩ</h3>
    <div class="card">
    <div class="card-body">
    <form method="post">
    <input type="hidden" name="request_id" value="{req.id if req else ''}">
    <div class="mb-3"><label class="form-label">ጥያቄ</label>
    <input class="form-control" value="{req.request_no if req else ''}" disabled></div>
    <div class="mb-3"><label class="form-label">የተመደበ ሰራተኛ</label>
    <select class="form-select" name="assigned_to_id" required><option value="">-- ሰራተኛ ይምረጡ --</option>{user_options}</select></div>
    <div class="mb-3"><label class="form-label">የመጀመሪያ መመሪያ</label>
    <textarea class="form-control" name="work_performed" rows="3"></textarea></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> የስራ ትዕዛዝ ይፍጠሩ</button>
    </form>
    </div></div>"""
    return page("New Work Order", content)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    photos = Photo.query.filter_by(object_type="workorder", object_id=wo.id).all()
    parts_html = "".join(f"<li class='list-group-item' style='background:transparent; border-color:rgba(245,158,11,0.1); color:#cbd5e1;'>{p.part.part_name} x {p.quantity} @ {p.unit_cost} ETB</li>" for p in parts)
    photo_html = "".join(f'<a href="/uploads/{p.filename}" target="_blank"><img src="/uploads/{p.filename}" height="100" class="m-1 rounded" style="border: 2px solid rgba(245,158,11,0.3);"></a>' for p in photos)

    completion_photo_html = ""
    if wo.completion_photo:
        completion_photo_html = f"""
        <div class="mt-3 card">
            <div class="card-body">
                <h6><i class="fas fa-camera"></i> 📸 የተሰራው ስራ ፎቶ ማረጋገጫ፡</h6>
                <a href="/static/uploads/maintenance/{wo.completion_photo}" target="_blank">
                    <img src="/static/uploads/maintenance/{wo.completion_photo}" 
                         class="img-fluid rounded shadow-sm" 
                         style="max-height: 250px; border: 2px solid rgba(245,158,11,0.2);">
                </a>
            </div>
        </div>"""

    content = f"""
    <h3><i class="fas fa-file-signature"></i> የስራ ትዕዛዝ {wo.work_order_no}</h3>
    <div class="card">
    <div class="card-body">
    <table class="table table-borderless">
    <tr><th style="width:150px; color:#94a3b8;">ጥያቄ</th><td>{wo.request.request_no if wo.request else ''}</td></tr>
    <tr><th style="color:#94a3b8;">ቦታ</th><td>{wo.request.location_name if wo.request else ''}</td></tr>
    <tr><th style="color:#94a3b8;">ሁኔታ</th><td><span class="badge bg-{'success' if wo.status=='Completed' else 'warning' if wo.status=='Assigned' else 'info'}">{wo.status}</span></td></tr>
    <tr><th style="color:#94a3b8;">የተመደበ</th><td>{wo.assigned_to.full_name if wo.assigned_to else ''}</td></tr>
    <tr><th style="color:#94a3b8;">የተሰራው ስራ</th><td>{wo.work_performed or ''}</td></tr>
    <tr><th style="color:#94a3b8;">የተጠቀሙ እቃዎች</th><td><ul class="list-group">{parts_html}</ul></td></tr>
    <tr><th style="color:#94a3b8;">የስራ ሰዓት</th><td>{wo.labor_hours}</td></tr>
    <tr><th style="color:#94a3b8;">ፎቶዎች</th><td>{'ተያይዟል' if wo.completion_photo else 'የለም'}</td></tr>
    </table>
    {completion_photo_html}
    </div></div>
    """
    if current_user.role in ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]:
        if wo.status == "Assigned":
            content += f'<a class="btn btn-warning" href="/workorders/{wo.id}/progress"><i class="fas fa-play"></i> ስራ ጀምር</a> '
        if wo.status == "In Progress":
            content += f'<a class="btn btn-success" href="/workorders/{wo.id}/complete"><i class="fas fa-check"></i> ስራውን ጨርስ</a> '
    return page("Work Order Detail", content)


@app.route("/workorders/<int:wo_id>/progress")
@role_required("MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR")
def workorder_progress(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    if wo.status == "Assigned":
        wo.status = "In Progress"
        wo.request.status = "In Progress"
        hist = StatusHistory(request_id=wo.request_id, status=wo.request.status, user_id=current_user.id)
        db.session.add(hist)
        log_audit("Status Change", "WorkOrder", wo.id, "Assigned", "In Progress")
        db.session.commit()
        flash("ስራው ተጀምሯል", "success")
    return redirect(url_for("workorder_detail", wo_id=wo.id))


@app.route("/workorders/<int:wo_id>/complete", methods=["GET", "POST"])
@role_required("MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR")
def workorder_complete(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()

    if request.method == "POST":
        try:
            wo.work_performed = request.form.get("work_performed", "")
            labor_input = request.form.get("labor_hours", 0)
            try:
                wo.labor_hours = float(labor_input) if labor_input else 0.0
            except:
                wo.labor_hours = 0.0

            wo.completion_notes = request.form.get("completion_notes", "")

            file = request.files.get("photo")
            if file and file.filename != "":
                upload_dir = app.config.get('UPLOAD_FOLDER', 'static/uploads/maintenance')
                os.makedirs(upload_dir, exist_ok=True)
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = secure_filename(f"wo_{wo.id}_completed.{ext}")
                file.save(os.path.join(upload_dir, filename))
                wo.completion_photo = filename

            wo.status = "Completed"
            if hasattr(current_user, 'id'):
                wo.completed_by_id = current_user.id

            if getattr(wo, 'request', None):
                wo.request.status = "Completed"

            part_ids = request.form.getlist("part_id")
            quantities = request.form.getlist("quantity")
            for pid, qty in zip(part_ids, quantities):
                if pid and pid.isdigit() and qty:
                    try:
                        q_val = float(qty)
                        if q_val > 0:
                            part = InventoryPart.query.get(int(pid))
                            if part and part.quantity >= q_val:
                                part.quantity -= q_val
                                wo_part = WorkOrderPart(
                                    work_order_id=wo.id,
                                    part_id=part.id,
                                    quantity=q_val,
                                    unit_cost=part.unit_cost
                                )
                                db.session.add(wo_part)
                                mov = StockMovement(
                                    part_id=part.id,
                                    movement_type="OUT",
                                    quantity=q_val,
                                    reason=f"Used in WO {wo.work_order_no}",
                                    work_order_id=wo.id,
                                    user_id=current_user.id
                                )
                                db.session.add(mov)
                    except:
                        pass

            db.session.commit()
            flash("ስራው በስኬት ተጠናቋል!", "success")
            return redirect(url_for("workorder_detail", wo_id=wo.id))

        except Exception as e:
            db.session.rollback()
            import traceback
            error_msg = traceback.format_exc()
            return f"<h3>ስህተት ተገኝቷል:</h3><pre style='color:red;'>{error_msg}</pre>", 500

    parts_options = "".join([f'<option value="{p.id}">{p.part_name} (ካለ: {p.quantity})</option>' for p in parts])
    content = f"""
    <h3><i class="fas fa-check-circle"></i> ስራውን ይጨርሱ {wo.work_order_no}</h3>
    <div class="card">
    <div class="card-body">
    <form method="post" enctype="multipart/form-data">
        <div class="mb-3">
            <label class="form-label">📸 የተሰራበትን የሚያሳይ ፎቶ ያንሱ</label>
            <input type="file" name="photo" accept="image/*" capture="environment" class="form-control" required>
            <div class="form-text">በስልክዎ ካሜራ የጥገናውን ውጤት ፎቶ ያንሱ።</div>
        </div>
        <div class="mb-3">
            <label class="form-label">የተሰራው ስራ</label>
            <textarea name="work_performed" class="form-control" required></textarea>
        </div>
        <div class="mb-3">
            <label class="form-label">የስራ ሰዓት</label>
            <input type="number" step="0.5" name="labor_hours" class="form-control" value="0">
        </div>
        <div class="mb-3">
            <label class="form-label">ማስታወሻ</label>
            <textarea name="completion_notes" class="form-control"></textarea>
        </div>
        <div class="mb-3">
            <label class="form-label">የተጠቀሙ እቃዎች</label>
            <div id="parts-container">
                <div class="d-flex mb-2">
                    <select name="part_id" class="form-select me-2">
                        <option value="">-- እቃ --</option>
                        {parts_options}
                    </select>
                    <input type="number" name="quantity" class="form-control w-25" value="1" min="1">
                    <button type="button" class="btn btn-outline-secondary ms-2" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>
                </div>
            </div>
            <button type="button" class="btn btn-outline-secondary" onclick="addPartRow()"><i class="fas fa-plus"></i> እቃ ጨምር</button>
        </div>
        <button type="submit" class="btn btn-success btn-lg w-100"><i class="fas fa-check-square"></i> ስራውን ጨርስ / Complete Task</button>
    </form>
    </div></div>
    <script>
    function addPartRow() {{
        const container = document.getElementById('parts-container');
        const row = document.createElement('div');
        row.className = 'd-flex mb-2';
        row.innerHTML = `
            <select name="part_id" class="form-select me-2">
                <option value="">-- እቃ --</option>
                {parts_options}
            </select>
            <input type="number" name="quantity" class="form-control w-25" value="1" min="1">
            <button type="button" class="btn btn-outline-secondary ms-2" onclick="this.parentElement.remove()"><i class="fas fa-times"></i></button>
        `;
        container.appendChild(row);
    }}
    </script>
    <script>
    let db;
    const dbRequest = indexedDB.open("RoriMaintenanceOffline", 1);
    dbRequest.onupgradeneeded = (e) => {{
        db = e.target.result;
        if (!db.objectStoreNames.contains("pendingReports")) {{
            db.createObjectStore("pendingReports", {{ keyPath: "id", autoIncrement: true }});
        }}
    }};
    dbRequest.onsuccess = (e) => {{ db = e.target.result; }};
    
    document.querySelector("form").addEventListener("submit", async function(e) {{
        e.preventDefault();
        const form = this;
        const formData = new FormData(form);
        const woId = {wo.id};
        
        if (navigator.onLine) {{
            form.submit();
        }} else {{
            const file = formData.get("photo");
            const reader = new FileReader();
            reader.onload = function() {{
                const tx = db.transaction("pendingReports", "readwrite");
                const store = tx.objectStore("pendingReports");
                store.add({{
                    wo_id: woId,
                    notes: formData.get("completion_notes"),
                    work_performed: formData.get("work_performed"),
                    labor_hours: formData.get("labor_hours"),
                    photoBase64: reader.result,
                    timestamp: new Date().toISOString()
                }});
                alert("⚠️ የዋይፋይ ኮኔክሽን የለም! ሪፖርቱ እና ፎቶው ስልክዎ ላይ ተቀምጧል። ኢንተርኔት ሲያገኙ በራሱ ይላካል።");
                form.reset();
            }};
            if (file) reader.readAsDataURL(file);
        }}
    }});
    
    window.addEventListener("online", syncPendingReports);
    async function syncPendingReports() {{
        if (!db) return;
        const tx = db.transaction("pendingReports", "readwrite");
        const store = tx.objectStore("pendingReports");
        const getAllReq = store.getAll();
        getAllReq.onsuccess = async () => {{
            const reports = getAllReq.result;
            if (reports.length === 0) return;
            for (let report of reports) {{
                const syncData = new FormData();
                syncData.append("wo_id", report.wo_id);
                syncData.append("work_performed", report.work_performed);
                syncData.append("labor_hours", report.labor_hours);
                syncData.append("completion_notes", report.notes);
                const response = await fetch(report.photoBase64);
                const blob = await response.blob();
                syncData.append("photo", blob, `wo_${{report.wo_id}}_offline.jpg`);
                try {{
                    let res = await fetch(`/workorders/${{report.wo_id}}/complete`, {{
                        method: "POST",
                        body: syncData
                    }});
                    if (res.ok) {{
                        const deleteTx = db.transaction("pendingReports", "readwrite");
                        deleteTx.objectStore("pendingReports").delete(report.id);
                    }}
                }} catch (err) {{
                    console.error("Sync failed for WO:", report.wo_id);
                }}
            }}
            alert("✅ ኢንተርኔት ስለተመለሰ ከመስመር ውጭ (Offline) የተሰሩ ሪፖርቶች በሙሉ ተልከዋል!");
        }};
    }}
    </script>
    """
    return page("Complete Work Order", content)


# --------------------------------------------------------------
# UPLOAD PHOTOS
# --------------------------------------------------------------
@app.route("/upload/<string:obj_type>/<int:obj_id>", methods=["POST"])
@login_required
def upload_photo(obj_type, obj_id):
    if obj_type not in ["request", "workorder"]:
        abort(400)
    file = request.files.get("file")
    if not file or file.filename == "":
        flash("ፋይል አልተመረጠም", "danger")
        return redirect(request.referrer or url_for("dashboard"))
    if not allowed_file(file.filename):
        flash("ልክ ያልሆነ የፋይል አይነት", "danger")
        return redirect(request.referrer or url_for("dashboard"))

    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    photo = Photo(
        filename=filename,
        object_type=obj_type,
        object_id=obj_id,
        photo_type=request.form.get("photo_type", "Before"),
        uploaded_by_id=current_user.id,
        file_size=os.path.getsize(os.path.join(UPLOAD_FOLDER, filename)),
    )
    db.session.add(photo)
    log_audit("Upload", "Photo", photo.id, new_value=filename)
    db.session.commit()
    flash("ፋይል ተሰቅሏል", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/static/uploads/maintenance/<filename>")
@login_required
def uploaded_file(filename):
    return send_file(os.path.join(UPLOAD_FOLDER, filename))


# --------------------------------------------------------------
# ROOMS, AREAS, MASTER DATA, INVENTORY, PREVENTIVE, CHECKLISTS,
# SUPPLIERS, CONTRACTORS, EMPLOYEES, NOTIFICATIONS, REPORTS,
# ADMIN USERS, AUDIT LOG, BACKUP, QR CODES, PWA, ERROR HANDLING
# (all are included in the full code – we list them briefly)
# --------------------------------------------------------------
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = []
    for r in rooms:
        cls = "table-warning" if r.status in ["Maintenance", "Out of Service"] else ""
        rows.append(f"""
        <tr class="{cls}">
        <td>{r.room_number}</td><td>{r.floor}</td><td>{r.status}</td>
        <td><a class="btn btn-sm btn-primary" href="/rooms/{r.id}/edit"><i class="fas fa-edit"></i> አርትዕ</a></td>
        </tr>""")
    content = f"""
    <h3><i class="fas fa-door-open"></i> ክፍሎች ({len(rooms)})</h3>
    <div class="table-responsive"><table class="table table-bordered table-hover">
    <thead><tr><th>ክፍል</th><th>ፎቅ</th><th>ሁኔታ</th><th>እርምጃ</th></tr></thead>
    <tbody>{''.join(rows)}</tbody></table></div>"""
    return page("Rooms", content)


@app.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def room_edit(room_id):
    room = Room.query.get_or_404(room_id)
    if request.method == "POST":
        old_status = room.status
        room.floor = int(request.form.get("floor", room.floor))
        room.status = request.form.get("status", room.status)
        room.updated_at = datetime.utcnow()
        log_audit("Room Status Change", "Room", room.id, old_status, room.status)
        db.session.commit()
        flash("ክፍሉ ተዘምኗል", "success")
        return redirect(url_for("rooms_list"))
    content = f"""
    <h3><i class="fas fa-edit"></i> ክፍል አርትዕ {room.room_number}</h3>
    <div class="card"><div class="card-body">
    <form method="post">
    <div class="mb-3"><label class="form-label">ፎቅ</label><input type="number" class="form-control" name="floor" value="{room.floor}" required></div>
    <div class="mb-3"><label class="form-label">ሁኔታ</label><select class="form-select" name="status">{''.join(f'<option {"selected" if s==room.status else ""}>{s}</option>' for s in ROOM_STATUSES)}</select></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button>
    </form>
    </div></div>"""
    return page("Edit Room", content)


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join(f'<tr><td>{a.name}</td><td>{a.department}</td><td>{a.status}</td><td><a class="btn btn-sm btn-primary" href="/areas/{a.id}/edit"><i class="fas fa-edit"></i> አርትዕ</a></td></tr>' for a in areas)
    content = f"""
    <h3><i class="fas fa-map-marked-alt"></i> የሆቴል ቦታዎች</h3>
    <a class="btn btn-primary mb-3" href="/areas/new"><i class="fas fa-plus-circle"></i> ቦታ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ስም</th><th>ክፍል</th><th>ሁኔታ</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Areas", content)


@app.route("/areas/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def area_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("ስም ያስፈልጋል", "danger")
        else:
            area = Area(name=name, department=request.form.get("department", ""), description=request.form.get("description", ""), status="Active")
            db.session.add(area)
            log_audit("Create", "Area", area.id, new_value=name)
            db.session.commit()
            flash("ቦታ ተፈጥሯል", "success")
            return redirect(url_for("areas_list"))
    return page("Add Area", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">ስም</label><input class="form-control" name="name" required></div>
    <div class="mb-3"><label class="form-label">ክፍል</label><input class="form-control" name="department"></div>
    <div class="mb-3"><label class="form-label">መግለጫ</label><textarea class="form-control" name="description"></textarea></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/areas/<int:area_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def area_edit(area_id):
    area = Area.query.get_or_404(area_id)
    if request.method == "POST":
        old = area.name
        area.name = request.form.get("name", area.name)
        area.department = request.form.get("department", area.department)
        area.description = request.form.get("description", area.description)
        area.status = request.form.get("status", area.status)
        log_audit("Update", "Area", area.id, old, area.name)
        db.session.commit()
        flash("ቦታ ተዘምኗል", "success")
        return redirect(url_for("areas_list"))
    content = f"""
    <div class="card"><div class="card-body">
    <form method="post">
    <div class="mb-3"><label class="form-label">ስም</label><input class="form-control" name="name" value="{area.name}" required></div>
    <div class="mb-3"><label class="form-label">ክፍል</label><input class="form-control" name="department" value="{area.department or ''}"></div>
    <div class="mb-3"><label class="form-label">መግለጫ</label><textarea class="form-control" name="description">{area.description or ''}</textarea></div>
    <div class="mb-3"><label class="form-label">ሁኔታ</label><select class="form-select" name="status"><option>Active</option><option>Disabled</option></select></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form>
    </div></div>"""
    return page("Edit Area", content)


@app.route("/admin/masterdata")
@role_required("ADMIN")
def master_data():
    cats = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    content = f"""
    <h3><i class="fas fa-database"></i> ማስተር ዳታ</h3>
    <div class="row">
    <div class="col-md-6">
    <div class="card"><div class="card-body"><h5 class="card-title">ምድቦች</h5><ul class="list-group">{''.join(f'<li class="list-group-item" style="background:transparent; border-color:rgba(245,158,11,0.1); color:#cbd5e1;">{c.name}</li>' for c in cats)}</ul></div></div>
    </div>
    <div class="col-md-6">
    <div class="card"><div class="card-body"><h5 class="card-title">የስራ እቃዎች</h5><ul class="list-group">{''.join(f'<li class="list-group-item" style="background:transparent; border-color:rgba(245,158,11,0.1); color:#cbd5e1;">{i.name}</li>' for i in items)}</ul></div></div>
    </div>
    </div>"""
    return page("Master Data", content)


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = []
    for p in parts:
        cls = "table-danger" if p.quantity <= 0 else "table-warning" if p.quantity <= p.minimum_stock else ""
        rows.append(f'<tr class="{cls}"><td>{p.part_name}</td><td>{p.quantity}</td><td>{p.unit}</td><td>{p.unit_cost}</td><td>{p.minimum_stock}</td><td>{p.status}</td></tr>')
    content = f"""
    <h3><i class="fas fa-boxes"></i> ክምችት እና መለዋወጫ</h3>
    <a class="btn btn-primary mb-3" href="/inventory/new"><i class="fas fa-plus-circle"></i> እቃ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ስም</th><th>ብዛት</th><th>አሃድ</th><th>ዋጋ</th><th>ዝቅተኛ</th><th>ሁኔታ</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""
    return page("Inventory", content)


@app.route("/inventory/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def inventory_create():
    if request.method == "POST":
        part = InventoryPart(
            part_name=request.form.get("part_name"),
            category=request.form.get("category"),
            quantity=float(request.form.get("quantity", 0)),
            minimum_stock=float(request.form.get("minimum_stock", 5)),
            unit=request.form.get("unit", "pcs"),
            unit_cost=float(request.form.get("unit_cost", 0)),
            storage_location=request.form.get("storage_location"),
            status="Active",
        )
        db.session.add(part)
        log_audit("Create", "InventoryPart", part.id, new_value=part.part_name)
        db.session.commit()
        flash("እቃ ተጨምሯል", "success")
        return redirect(url_for("inventory_list"))
    return page("Add Part", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">የእቃ ስም</label><input class="form-control" name="part_name" required></div>
    <div class="mb-3"><label class="form-label">ምድብ</label><input class="form-control" name="category"></div>
    <div class="mb-3"><label class="form-label">ብዛት</label><input type="number" step="0.01" class="form-control" name="quantity" required></div>
    <div class="mb-3"><label class="form-label">ዝቅተኛ ክምችት</label><input type="number" step="0.01" class="form-control" name="minimum_stock" value="5"></div>
    <div class="mb-3"><label class="form-label">አሃድ</label><input class="form-control" name="unit" value="pcs"></div>
    <div class="mb-3"><label class="form-label">ዋጋ</label><input type="number" step="0.01" class="form-control" name="unit_cost"></div>
    <div class="mb-3"><label class="form-label">የማከማቻ ቦታ</label><input class="form-control" name="storage_location"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/preventive")
@role_required("ADMIN", "MANAGER")
def preventive_list():
    tasks = PreventiveMaintenance.query.order_by(PreventiveMaintenance.next_due_date).all()
    rows = "".join(f'<tr><td>{t.title}</td><td>{t.frequency}</td><td>{t.next_due_date.strftime("%Y-%m-%d") if t.next_due_date else ""}</td><td>{t.status}</td></tr>' for t in tasks)
    content = f"""
    <h3><i class="fas fa-calendar-check"></i> የመከላከያ ጥገና</h3>
    <a class="btn btn-primary mb-3" href="/preventive/new"><i class="fas fa-plus-circle"></i> ተግባር መርሐግብር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ርዕስ</th><th>ድግግሞሽ</th><th>ቀጣይ ቀን</th><th>ሁኔታ</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Preventive Maintenance", content)


@app.route("/preventive/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def preventive_create():
    if request.method == "POST":
        task = PreventiveMaintenance(
            title=request.form.get("title"),
            task=request.form.get("task"),
            frequency=request.form.get("frequency", "Monthly"),
            priority=request.form.get("priority", "MEDIUM"),
            next_due_date=datetime.strptime(request.form.get("next_due_date"), "%Y-%m-%d") if request.form.get("next_due_date") else datetime.utcnow() + timedelta(days=30),
            status="Scheduled",
        )
        db.session.add(task)
        log_audit("Create", "PreventiveMaintenance", task.id, new_value=task.title)
        db.session.commit()
        flash("ተግባር መርሐግብር ተይዟል", "success")
        return redirect(url_for("preventive_list"))
    content = """
    <div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">ርዕስ</label><input class="form-control" name="title" required></div>
    <div class="mb-3"><label class="form-label">ዝርዝር</label><textarea class="form-control" name="task"></textarea></div>
    <div class="mb-3"><label class="form-label">ድግግሞሽ</label><select class="form-select" name="frequency"><option>Daily</option><option>Weekly</option><option>Monthly</option><option>Quarterly</option><option>Yearly</option></select></div>
    <div class="mb-3"><label class="form-label">ቅድሚያ</label><select class="form-select" name="priority"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>URGENT</option></select></div>
    <div class="mb-3"><label class="form-label">ቀጣይ ቀን</label><input type="date" class="form-control" name="next_due_date"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>"""
    return page("New Preventive Task", content)


@app.route("/checklists")
@role_required("ADMIN", "MANAGER")
def checklists_list():
    templates = ChecklistTemplate.query.all()
    rows = "".join(f'<tr><td><a href="/checklists/{t.id}" style="color:#f59e0b;">{t.name}</a></td><td>{len(t.items)} እቃዎች</td></tr>' for t in templates)
    content = f"""
    <h3><i class="fas fa-list-check"></i> የጥገና ማረጋገጫ ዝርዝሮች</h3>
    <a class="btn btn-primary mb-3" href="/checklists/new"><i class="fas fa-plus-circle"></i> አዲስ ዝርዝር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ስም</th><th>እቃዎች</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Checklists", content)


@app.route("/checklists/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def checklist_create():
    if request.method == "POST":
        name = request.form.get("name")
        items = request.form.get("items", "").splitlines()
        tpl = ChecklistTemplate(name=name, description=request.form.get("description", ""))
        for i, item in enumerate(items):
            if item.strip():
                tpl.items.append(ChecklistTemplateItem(item_text=item.strip(), order=i))
        db.session.add(tpl)
        log_audit("Create", "ChecklistTemplate", tpl.id, new_value=name)
        db.session.commit()
        flash("ዝርዝር ተፈጥሯል", "success")
        return redirect(url_for("checklists_list"))
    return page("New Checklist", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">ስም</label><input class="form-control" name="name" required></div>
    <div class="mb-3"><label class="form-label">መግለጫ</label><input class="form-control" name="description"></div>
    <div class="mb-3"><label class="form-label">እቃዎች (አንድ በመስመር)</label><textarea class="form-control" name="items" rows="8">Lights
Switches
Door Lock
Water Supply
Toilet
AC
Window
Mirror
Plumbing
Safety Equipment</textarea></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/suppliers")
@role_required("ADMIN", "MANAGER")
def suppliers_list():
    suppliers = Supplier.query.all()
    rows = "".join(f'<tr><td>{s.company_name}</td><td>{s.contact_person}</td><td>{s.phone}</td><td>{s.status}</td></tr>' for s in suppliers)
    content = f"""
    <h3><i class="fas fa-truck"></i> አቅራቢዎች</h3>
    <a class="btn btn-primary mb-3" href="/suppliers/new"><i class="fas fa-plus-circle"></i> አቅራቢ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ኩባንያ</th><th>አድራሻ</th><th>ስልክ</th><th>ሁኔታ</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Suppliers", content)


@app.route("/suppliers/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def supplier_create():
    if request.method == "POST":
        s = Supplier(company_name=request.form.get("company_name"), contact_person=request.form.get("contact_person"), phone=request.form.get("phone"), email=request.form.get("email"), address=request.form.get("address"), supplied_items=request.form.get("supplied_items"), status="Active")
        db.session.add(s)
        log_audit("Create", "Supplier", s.id, new_value=s.company_name)
        db.session.commit()
        flash("አቅራቢ ተጨምሯል", "success")
        return redirect(url_for("suppliers_list"))
    return page("Add Supplier", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">የኩባንያ ስም</label><input class="form-control" name="company_name" required></div>
    <div class="mb-3"><label class="form-label">አድራሻ ሰው</label><input class="form-control" name="contact_person"></div>
    <div class="mb-3"><label class="form-label">ስልክ</label><input class="form-control" name="phone"></div>
    <div class="mb-3"><label class="form-label">ኢሜል</label><input class="form-control" name="email"></div>
    <div class="mb-3"><label class="form-label">አድራሻ</label><textarea class="form-control" name="address"></textarea></div>
    <div class="mb-3"><label class="form-label">የሚያቀርቡት እቃዎች</label><input class="form-control" name="supplied_items"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/contractors")
@role_required("ADMIN", "MANAGER")
def contractors_list():
    contractors = Contractor.query.all()
    rows = "".join(f'<tr><td>{c.name}</td><td>{c.service_type}</td><td>{c.phone}</td><td>{c.status}</td></tr>' for c in contractors)
    content = f"""
    <h3><i class="fas fa-hard-hat"></i> ተቋራጮች</h3>
    <a class="btn btn-primary mb-3" href="/contractors/new"><i class="fas fa-plus-circle"></i> ተቋራጭ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>ስም</th><th>አገልግሎት</th><th>ስልክ</th><th>ሁኔታ</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Contractors", content)


@app.route("/contractors/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def contractor_create():
    if request.method == "POST":
        c = Contractor(name=request.form.get("name"), service_type=request.form.get("service_type"), phone=request.form.get("phone"), email=request.form.get("email"), rate=float(request.form.get("rate", 0) or 0), status="Active")
        db.session.add(c)
        log_audit("Create", "Contractor", c.id, new_value=c.name)
        db.session.commit()
        flash("ተቋራጭ ተጨምሯል", "success")
        return redirect(url_for("contractors_list"))
    return page("Add Contractor", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">ስም/ኩባንያ</label><input class="form-control" name="name" required></div>
    <div class="mb-3"><label class="form-label">የአገልግሎት አይነት</label><input class="form-control" name="service_type"></div>
    <div class="mb-3"><label class="form-label">ስልክ</label><input class="form-control" name="phone"></div>
    <div class="mb-3"><label class="form-label">ኢሜል</label><input class="form-control" name="email"></div>
    <div class="mb-3"><label class="form-label">ዋጋ</label><input type="number" step="0.01" class="form-control" name="rate"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    employees = Employee.query.order_by(Employee.id).all()
    rows = "".join(
        f'<tr><td>{e.id}</td><td>{e.name}</td><td>{e.job_title}</td><td>{e.department}</td>'
        f'<td><a class="btn btn-sm btn-primary" href="/employees/{e.id}/edit"><i class="fas fa-edit"></i> አርትዕ</a></td></tr>'
        for e in employees
    )
    content = f"""
    <h3><i class="fas fa-users"></i> የኢንጂነሪንግ ክፍል ሰራተኞች</h3>
    <a class="btn btn-primary mb-3" href="/employees/new"><i class="fas fa-plus-circle"></i> ሰራተኛ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover">
    <thead><tr><th>ID</th><th>ስም</th><th>የስራ ድርሻ</th><th>ክፍል</th><th>እርምጃ</th></tr></thead>
    <tbody>{rows}</tbody></table></div>"""
    return page("Employees", content)


@app.route("/employees/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def employee_create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        job_title = request.form.get("job_title", "").strip()
        department = request.form.get("department", "Engineering").strip()
        if not name:
            flash("ስም ያስፈልጋል", "danger")
            return redirect(url_for("employee_create"))
        emp = Employee(name=name, job_title=job_title, department=department)
        db.session.add(emp)
        db.session.flush()
        log_audit("Create", "Employee", emp.id, new_value=name)
        db.session.commit()
        flash("ሰራተኛ ተጨምሯል", "success")
        return redirect(url_for("employees_list"))
    return page("Add Employee", """<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">ስም</label><input class="form-control" name="name" required></div>
    <div class="mb-3"><label class="form-label">የስራ ድርሻ</label><input class="form-control" name="job_title"></div>
    <div class="mb-3"><label class="form-label">ክፍል</label><input class="form-control" name="department" value="Engineering"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/employees/<int:emp_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def employee_edit(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    if request.method == "POST":
        old_name = emp.name
        emp.name = request.form.get("name", emp.name).strip()
        emp.job_title = request.form.get("job_title", emp.job_title).strip()
        emp.department = request.form.get("department", emp.department).strip()
        emp.updated_at = datetime.utcnow()
        log_audit("Update", "Employee", emp.id, old_name, emp.name)
        db.session.commit()
        flash("ሰራተኛ ተዘምኗል", "success")
        return redirect(url_for("employees_list"))
    content = f"""
    <div class="card"><div class="card-body">
    <form method="post">
    <div class="mb-3"><label class="form-label">ስም</label><input class="form-control" name="name" value="{emp.name}" required></div>
    <div class="mb-3"><label class="form-label">የስራ ድርሻ</label><input class="form-control" name="job_title" value="{emp.job_title or ''}"></div>
    <div class="mb-3"><label class="form-label">ክፍል</label><input class="form-control" name="department" value="{emp.department or ''}"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form>
    </div></div>"""
    return page("Edit Employee", content)


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    rows = "".join(f'<tr class="{"table-info" if not n.read else ""}"><td>{n.message}</td><td>{n.type}</td><td>{n.created_at.strftime("%Y-%m-%d %H:%M")}</td><td><a href="/notifications/{n.id}/read"><i class="fas fa-check"></i> አንብብ</a></td></tr>' for n in notifs)
    content = f"""
    <h3><i class="fas fa-bell"></i> ማሳወቂያዎች</h3>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>መልእክት</th><th>አይነት</th><th>ቀን</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Notifications", content)


@app.route("/notifications/<int:n_id>/read")
@login_required
def notification_read(n_id):
    n = Notification.query.get_or_404(n_id)
    if n.user_id == current_user.id:
        n.read = True
        db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/reports")
@login_required
def reports():
    content = """
    <h3><i class="fas fa-chart-bar"></i> ሪፖርቶች</h3>
    <div class="list-group">
    <a href="/reports/export/requests" class="list-group-item list-group-item-action" style="background:rgba(30,41,59,0.5); border-color:rgba(245,158,11,0.1); color:#cbd5e1;"><i class="fas fa-file-csv"></i> የጥገና ጥያቄዎችን ወደ CSV ላክ</a>
    <a href="/reports/export/workorders" class="list-group-item list-group-item-action" style="background:rgba(30,41,59,0.5); border-color:rgba(245,158,11,0.1); color:#cbd5e1;"><i class="fas fa-file-csv"></i> የስራ ትዕዛዞችን ወደ CSV ላክ</a>
    <a href="/reports/export/inventory" class="list-group-item list-group-item-action" style="background:rgba(30,41,59,0.5); border-color:rgba(245,158,11,0.1); color:#cbd5e1;"><i class="fas fa-file-csv"></i> ክምችት ወደ CSV ላክ</a>
    <a href="/reports/export/audit" class="list-group-item list-group-item-action" style="background:rgba(30,41,59,0.5); border-color:rgba(245,158,11,0.1); color:#cbd5e1;"><i class="fas fa-file-csv"></i> Audit Log ወደ CSV ላክ</a>
    <a href="/reports/export/employees" class="list-group-item list-group-item-action" style="background:rgba(30,41,59,0.5); border-color:rgba(245,158,11,0.1); color:#cbd5e1;"><i class="fas fa-file-csv"></i> ሰራተኞችን ወደ CSV ላክ</a>
    </div>"""
    return page("Reports", content)


@app.route("/reports/export/<report_type>")
@login_required
def reports_export(report_type):
    output = io.StringIO()
    writer = csv.writer(output)
    if report_type == "requests":
        writer.writerow(["Request No", "Location", "Item", "Category", "Priority", "Status", "Created"])
        for r in MaintenanceRequest.query.order_by(MaintenanceRequest.created_at).all():
            writer.writerow([r.request_no, r.location_name, r.working_item.name if r.working_item else "", r.category.name if r.category else "", r.priority, r.status, r.created_at.strftime("%Y-%m-%d %H:%M")])
    elif report_type == "workorders":
        writer.writerow(["WO No", "Request", "Assigned To", "Status", "Created"])
        for wo in WorkOrder.query.order_by(WorkOrder.created_at).all():
            writer.writerow([wo.work_order_no, wo.request.request_no if wo.request else "", wo.assigned_to.full_name if wo.assigned_to else "", wo.status, wo.created_at.strftime("%Y-%m-%d %H:%M")])
    elif report_type == "inventory":
        writer.writerow(["Part Name", "Quantity", "Min Stock", "Unit Cost", "Status"])
        for p in InventoryPart.query.order_by(InventoryPart.part_name).all():
            writer.writerow([p.part_name, p.quantity, p.minimum_stock, p.unit_cost, p.status])
    elif report_type == "employees":
        writer.writerow(["ID", "Name", "Job Title", "Department"])
        for e in Employee.query.order_by(Employee.id).all():
            writer.writerow([e.id, e.name, e.job_title, e.department])
    elif report_type == "audit":
        writer.writerow(["User", "Action", "Object Type", "Object ID", "Old", "New", "Date"])
        for a in AuditLog.query.order_by(AuditLog.created_at.desc()).limit(1000).all():
            writer.writerow([a.user.full_name if a.user else "", a.action, a.object_type, a.object_id, a.old_value, a.new_value, a.created_at.strftime("%Y-%m-%d %H:%M")])
    else:
        abort(404)
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={report_type}.csv"})


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows = "".join(f'<tr><td>{u.username}</td><td>{u.full_name}</td><td>{u.role}</td><td>{u.active}</td></tr>' for u in users)
    content = f"""
    <h3><i class="fas fa-user-cog"></i> ተጠቃሚዎች</h3>
    <a class="btn btn-primary mb-3" href="/admin/users/new"><i class="fas fa-plus-circle"></i> ተጠቃሚ ጨምር</a>
    <div class="table-responsive"><table class="table table-bordered table-hover"><thead><tr><th>የመለያ ስም</th><th>ስም</th><th>ሚና</th><th>ንቁ</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Users", content)


@app.route("/admin/users/new", methods=["GET", "POST"])
@role_required("ADMIN")
def admin_user_create():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        if User.query.filter_by(username=username).first():
            flash("የመለያ ስም አለ", "danger")
        else:
            u = User(username=username, full_name=request.form.get("full_name"), role=role, email=request.form.get("email"))
            u.set_password(password)
            db.session.add(u)
            log_audit("Create", "User", u.id, new_value=username)
            db.session.commit()
            flash("ተጠቃሚ ተፈጥሯል", "success")
            return redirect(url_for("admin_users"))
    return page("Add User", f"""<div class="card"><div class="card-body"><form method="post">
    <div class="mb-3"><label class="form-label">የመለያ ስም</label><input class="form-control" name="username" required></div>
    <div class="mb-3"><label class="form-label">ሙሉ ስም</label><input class="form-control" name="full_name"></div>
    <div class="mb-3"><label class="form-label">የይለፍ ቃል</label><input type="password" class="form-control" name="password" required></div>
    <div class="mb-3"><label class="form-label">ሚና</label><select class="form-select" name="role">{''.join(f'<option>{r}</option>' for r in ROLES)}</select></div>
    <div class="mb-3"><label class="form-label">ኢሜል</label><input class="form-control" name="email"></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button></form></div></div>""")


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join(f'<tr><td>{a.user.full_name if a.user else "System"}</td><td>{a.action}</td><td>{a.object_type}</td><td>{a.object_id}</td><td>{a.old_value}</td><td>{a.new_value}</td><td>{a.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for a in logs)
    content = f"""
    <h3><i class="fas fa-history"></i> Audit Log</h3>
    <div class="table-responsive"><table class="table table-bordered table-sm table-hover"><thead><tr><th>ተጠቃሚ</th><th>እርምጃ</th><th>ነገር</th><th>ID</th><th>ድሮ</th><th>አዲስ</th><th>ቀን</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    return page("Audit Log", content)


def get_db_path():
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return os.path.join(BASE_DIR, "hotel_maintenance.db")


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join(f'<tr><td>{b}</td><td><a class="btn btn-sm btn-warning" href="/admin/restore/{b}"><i class="fas fa-undo"></i> Restore</a></td></tr>' for b in backups)
    content = f"""
    <h3><i class="fas fa-archive"></i> Backup & Restore</h3>
    <form method="post" action="/admin/backup/now"><button class="btn btn-primary"><i class="fas fa-database"></i> Backup Now</button></form>
    <h5 class="mt-4">Existing Backups</h5>
    <div class="table-responsive"><table class="table table-bordered"><thead><tr><th>File</th><th></th></tr></thead><tbody>{rows or "<tr><td colspan=2>No backups</td></tr>"}</tbody></table></div>"""
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
    log_audit("Backup", "Database", filename)
    db.session.commit()
    flash("Backup created", "success")
    return redirect(url_for("backup_page"))


@app.route("/admin/restore/<filename>")
@role_required("ADMIN")
def restore_backup(filename):
    if not filename.endswith(".db"):
        abort(400)
    filepath = os.path.join(BACKUP_FOLDER, filename)
    if not os.path.exists(filepath):
        flash("Backup not found", "danger")
        return redirect(url_for("backup_page"))
    safety = os.path.join(BACKUP_FOLDER, f"safety_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    src = sqlite3.connect(get_db_path())
    dst = sqlite3.connect(safety)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()

    src = sqlite3.connect(filepath)
    dst = sqlite3.connect(get_db_path())
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    db.session.remove()
    log_audit("Restore", "Database", filename)
    db.session.commit()
    flash("Database restored. Safety backup: " + safety, "success")
    return redirect(url_for("backup_page"))


@app.route("/qr/<string:loc_type>/<int:id>")
@login_required
def qr_code(loc_type, id):
    if loc_type == "room":
        obj = Room.query.get_or_404(id)
        url = url_for("request_create", room_id=obj.id, _external=True)
        label = f"Room {obj.room_number}"
    elif loc_type == "area":
        obj = Area.query.get_or_404(id)
        url = url_for("request_create", _external=True)
        label = obj.name
    else:
        abort(404)
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    log_audit("QR Scan/View", loc_type.capitalize(), id, new_value=url)
    db.session.commit()
    return send_file(buf, mimetype="image/png", download_name=f"{label.replace(' ', '_')}_qr.png")


@app.route("/qr")
@login_required
def qr_index():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    room_cards = "".join(f'<div class="col-4 col-md-2 text-center p-2"><a href="/qr/room/{r.id}"><img src="/qr/room/{r.id}" class="img-fluid" width="100"></a><br><small>Room {r.room_number}</small></div>' for r in rooms)
    area_cards = "".join(f'<div class="col-4 col-md-2 text-center p-2"><a href="/qr/area/{a.id}"><img src="/qr/area/{a.id}" class="img-fluid" width="100"></a><br><small>{a.name}</small></div>' for a in areas)
    content = f"""
    <h3><i class="fas fa-qrcode"></i> QR Codes</h3>
    <h5>Rooms</h5><div class="row">{room_cards}</div>
    <h5>Areas</h5><div class="row">{area_cards}</div>"""
    return page("QR Codes", content)


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Rori Hotel Maintenance",
        "short_name": "RoriMaint",
        "start_url": "/dashboard",
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


@app.errorhandler(403)
def forbidden(e):
    return page("Forbidden", '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> ይህን ገጽ ለማየት ፍቃድ የለዎትም።</div>'), 403


@app.errorhandler(404)
def not_found(e):
    return page("Not Found", '<div class="alert alert-warning"><i class="fas fa-search"></i> ገጹ አልተገኘም።</div>'), 404


# --------------------------------------------------------------
# INIT
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    seed_data()


@app.route('/logo.png')
def serve_logo():
    logo_path = os.path.join(app.root_path, 'file_00000000d93c821094a2e3f7dced7c77.png')
    return send_file(logo_path, mimetype='image/png')


users_data = [
    {"full_name": "አሚር አወል", "username": "amir", "role": "MANAGER"},
    {"full_name": "አበባየሁ ክፍሌ", "username": "abebayhu", "role": "SUPERVISOR"},
    {"full_name": "ተስፋሁን ነከረ", "username": "tesfahun", "role": "TECHNICIAN"},
    {"full_name": "ስምዖን ዮሐንስ", "username": "simon", "role": "TECHNICIAN"},
    {"full_name": "ቸርነት አሞና", "username": "chernet", "role": "TECHNICIAN"},
    {"full_name": "ዋሌ", "username": "wale", "role": "TECHNICIAN"},
    {"full_name": "ፃዲቁ", "username": "tsadiku", "role": "TECHNICIAN"},
]

with app.app_context():
    try:
        db.create_all()
        for user_info in users_data:
            user = User.query.filter_by(username=user_info["username"]).first()
            if not user:
                user = User(username=user_info["username"], role=user_info["role"])
                user.set_password("123456")
                db.session.add(user)
            if hasattr(user, 'full_name'):
                user.full_name = user_info["full_name"]
            user.role = user_info["role"]
        db.session.commit()
    except Exception as e:
        print("Setup error:", e)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
