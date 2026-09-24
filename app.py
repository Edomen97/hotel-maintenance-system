import csv
import io
import json
import os
import re
import sqlite3
import uuid
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect

from flask import (
    Flask, abort, flash, get_flashed_messages, jsonify, redirect,
    render_template, render_template_string,
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
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db"))
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
STAFF_ROLES = ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]
HK_APPROVER_ROLES = ["SUPERVISOR", "MANAGER", "ADMIN"]


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
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    profile_pic = db.Column(db.String(255), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    department = db.relationship("Department", foreign_keys=[department_id])

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
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    deletion_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    awaiting_hk_approval = db.Column(db.Boolean, default=False)
    hk_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    hk_approved_at = db.Column(db.DateTime)
    hk_approval_status = db.Column(db.String(20))
    hk_signature_data = db.Column(db.Text)
    hk_approval_notes = db.Column(db.Text)

    room = db.relationship("Room", foreign_keys=[room_id])
    area = db.relationship("Area", foreign_keys=[area_id])
    working_item = db.relationship("WorkingItem", foreign_keys=[working_item_id])
    category = db.relationship("Category", foreign_keys=[category_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department", foreign_keys=[department_id])
    deleted_by = db.relationship("User", foreign_keys=[deleted_by_id])
    hk_approved_by = db.relationship("User", foreign_keys=[hk_approved_by_id])

    @property
    def location_name(self):
        if self.location_type == "Room" and self.room:
            return "Room " + str(self.room.room_number)
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
    status = db.Column(db.String(30), default="Pending")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    completed_date = db.Column(db.DateTime)
    verified_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    completed_by = db.relationship("User", foreign_keys=[completed_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])


class WorkOrderPart(db.Model):
    __tablename__ = "work_order_parts"
    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    quantity = db.Column(db.Float, default=1)
    unit_cost = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    part = db.relationship("InventoryPart", foreign_keys=[part_id])


class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(120), unique=True, nullable=False)
    category = db.Column(db.String(80))
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")
    unit_cost = db.Column(db.Float, default=0)
    storage_location = db.Column(db.String(120))
    status = db.Column(db.String(20), default="Active")
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])

    @property
    def is_low(self):
        return self.quantity <= self.minimum_stock


class Photo(db.Model):
    __tablename__ = "photos"
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(20), nullable=False)
    object_id = db.Column(db.Integer, nullable=False)
    photo_type = db.Column(db.String(20), default="Before")
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("maintenance_requests.id"))
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"))
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default="General")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(250))
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
    user = db.relationship("User")


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(120), unique=True, nullable=False)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    tax_number = db.Column(db.String(60))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Contractor(db.Model):
    __tablename__ = "contractors"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    service_type = db.Column(db.String(80))
    phone = db.Column(db.String(30))
    status = db.Column(db.String(20), default="Active")


class PreventiveMaintenance(db.Model):
    __tablename__ = "preventive_maintenance"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    task = db.Column(db.Text)
    frequency = db.Column(db.String(20), default="Monthly")
    priority = db.Column(db.String(20), default="MEDIUM")
    next_due_date = db.Column(db.DateTime)
    status = db.Column(db.String(30), default="Scheduled")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ChecklistTemplate(db.Model):
    __tablename__ = "checklist_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


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


def is_housekeeping_approver(user):
    if not user or not user.is_authenticated:
        return False
    return user.role in HK_APPROVER_ROLES


def is_housekeeping_request(user):
    if not user or not user.is_authenticated:
        return False
    if user.role != "DEPARTMENT":
        return False
    dept = user.department
    return bool(dept and (dept.name or "").strip().lower() == "housekeeping")


def log_audit(action, object_type=None, object_id=None, old_value=None, new_value=None):
    try:
        db.session.add(AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        ))
    except Exception as e:
        print("Audit error: " + str(e))


def create_notification(user_id, request_id, title, message, notification_type="General", link=None, work_order_id=None):
    if not user_id:
        return None
    recent = Notification.query.filter_by(user_id=user_id, request_id=request_id, notification_type=notification_type).order_by(Notification.created_at.desc()).first()
    if recent and (datetime.utcnow() - recent.created_at).total_seconds() < 5:
        return recent
    notif = Notification(user_id=user_id, request_id=request_id, work_order_id=work_order_id, title=title, message=message, notification_type=notification_type, link=link)
    db.session.add(notif)
    return notif


def notify_users(user_ids, request_id, title, message, notification_type="General", link=None, work_order_id=None):
    for uid in user_ids:
        if uid:
            create_notification(uid, request_id, title, message, notification_type, link, work_order_id)


def notify_maintenance_staff(req, wo):
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    if not staff:
        return 0
    title = "🔧 New Work Order: " + str(wo.work_order_no)
    item_name = req.working_item.name if req.working_item else "N/A"
    dept_name = req.department.name if req.department else "N/A"
    message = ("Request: " + str(req.request_no) + " | WO: " + str(wo.work_order_no) +
               " | Location: " + str(req.location_name) +
               " | Item: " + str(item_name) +
               " | Priority: " + str(req.priority) +
               " | Dept: " + str(dept_name))
    link = url_for("workorder_detail", wo_id=wo.id)
    count = 0
    for s in staff:
        if create_notification(s.id, req.id, title, message, "Work Order Assigned", link, wo.id):
            count += 1
    return count


def notify_assigned_staff(req, wo, staff_user):
    if not staff_user:
        return
    title = "📋 Assigned to you: " + str(wo.work_order_no)
    item_name = req.working_item.name if req.working_item else "N/A"
    message = ("Request: " + str(req.request_no) + " | WO: " + str(wo.work_order_no) +
               " | Location: " + str(req.location_name) +
               " | Item: " + str(item_name) +
               " | Priority: " + str(req.priority))
    link = url_for("workorder_detail", wo_id=wo.id)
    create_notification(staff_user.id, req.id, title, message, "Work Order Assigned", link, wo.id)


def log_status_change(request_id, status, user_id=None, notes=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    db.session.add(StatusHistory(request_id=request_id, status=status, user_id=user_id, notes=notes))


def request_no_generator():
    return "R-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()


def work_order_no_generator():
    return "WO-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_one(model, ident):
    return db.session.get(model, ident)


def get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404)
    return obj


def valid_email(value):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value or ""))


def add_column_if_missing(table, column, sql):
    try:
        insp = inspect(db.engine)
        if table not in insp.get_table_names():
            return False
        cols = [c["name"] for c in insp.get_columns(table)]
        if column not in cols:
            with db.engine.begin() as conn:
                conn.execute(text(sql))
            print("✅ Added " + column + " to " + table)
            return True
        return False
    except Exception as e:
        print("⚠️ Migration warn (" + table + "." + column + "): " + str(e))
        return False


def ensure_database_schema():
    with app.app_context():
        try:
            db.create_all()
            pg = db.engine.dialect.name == "postgresql"
            dt_type = "TIMESTAMP" if pg else "DATETIME"
            bool_default = "DEFAULT FALSE" if pg else "DEFAULT 0"
            add_column_if_missing("maintenance_requests", "department_id", "ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER")
            add_column_if_missing("maintenance_requests", "manager_id", "ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER")
            add_column_if_missing("maintenance_requests", "completion_note", "ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT")
            add_column_if_missing("maintenance_requests", "completed_date", "ALTER TABLE maintenance_requests ADD COLUMN completed_date " + dt_type)
            add_column_if_missing("maintenance_requests", "is_deleted", "ALTER TABLE maintenance_requests ADD COLUMN is_deleted BOOLEAN " + bool_default)
            add_column_if_missing("maintenance_requests", "deleted_at", "ALTER TABLE maintenance_requests ADD COLUMN deleted_at " + dt_type)
            add_column_if_missing("maintenance_requests", "deleted_by_id", "ALTER TABLE maintenance_requests ADD COLUMN deleted_by_id INTEGER")
            add_column_if_missing("maintenance_requests", "deletion_reason", "ALTER TABLE maintenance_requests ADD COLUMN deletion_reason TEXT")
            add_column_if_missing("maintenance_requests", "awaiting_hk_approval", "ALTER TABLE maintenance_requests ADD COLUMN awaiting_hk_approval BOOLEAN " + bool_default)
            add_column_if_missing("maintenance_requests", "hk_approved_by_id", "ALTER TABLE maintenance_requests ADD COLUMN hk_approved_by_id INTEGER")
            add_column_if_missing("maintenance_requests", "hk_approved_at", "ALTER TABLE maintenance_requests ADD COLUMN hk_approved_at " + dt_type)
            add_column_if_missing("maintenance_requests", "hk_approval_status", "ALTER TABLE maintenance_requests ADD COLUMN hk_approval_status VARCHAR(20)")
            add_column_if_missing("maintenance_requests", "hk_signature_data", "ALTER TABLE maintenance_requests ADD COLUMN hk_signature_data TEXT")
            add_column_if_missing("maintenance_requests", "hk_approval_notes", "ALTER TABLE maintenance_requests ADD COLUMN hk_approval_notes TEXT")
            add_column_if_missing("users", "department_id", "ALTER TABLE users ADD COLUMN department_id INTEGER")
            add_column_if_missing("notifications", "work_order_id", "ALTER TABLE notifications ADD COLUMN work_order_id INTEGER")
            add_column_if_missing("work_orders", "completed_date", "ALTER TABLE work_orders ADD COLUMN completed_date " + dt_type)
            add_column_if_missing("work_orders", "verified_date", "ALTER TABLE work_orders ADD COLUMN verified_date " + dt_type)
            add_column_if_missing("audit_logs", "ip_address", "ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)")
            add_column_if_missing("suppliers", "email", "ALTER TABLE suppliers ADD COLUMN email VARCHAR(120)")
            add_column_if_missing("suppliers", "address", "ALTER TABLE suppliers ADD COLUMN address TEXT")
            add_column_if_missing("suppliers", "tax_number", "ALTER TABLE suppliers ADD COLUMN tax_number VARCHAR(60)")
            add_column_if_missing("suppliers", "notes", "ALTER TABLE suppliers ADD COLUMN notes TEXT")
            if add_column_if_missing("suppliers", "is_active", "ALTER TABLE suppliers ADD COLUMN is_active BOOLEAN " + bool_default):
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE suppliers SET is_active = CASE WHEN status = 'Active' THEN TRUE ELSE FALSE END"))
            add_column_if_missing("suppliers", "created_at", "ALTER TABLE suppliers ADD COLUMN created_at " + dt_type)
            add_column_if_missing("suppliers", "updated_at", "ALTER TABLE suppliers ADD COLUMN updated_at " + dt_type)
            add_column_if_missing("inventory_parts", "supplier_id", "ALTER TABLE inventory_parts ADD COLUMN supplier_id INTEGER")
            print("✅ Schema OK")
        except Exception as e:
            print("⚠️ Schema error: " + str(e))


# ══════════════════════════════════════════════════════════════
# PAGE FUNCTION
# ══════════════════════════════════════════════════════════════
def page(title, content):
    nav_items = []
    if current_user.is_authenticated:
        role = current_user.role
        if role == "DEPARTMENT":
            nav_items = [
                ('<i class="fas fa-home"></i> Dashboard', url_for('department_dashboard')),
                ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')),
            ]
        elif role == "EMPLOYEE":
            nav_items = [
                ('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')),
                ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')),
            ]
        elif role in STAFF_ROLES:
            nav_items = [
                ('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')),
                ('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')),
            ]
        else:
            nav_items = [
                ('<i class="fas fa-home"></i> Dashboard', url_for('dashboard')),
                ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                ('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')),
                ('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')),
            ]
            if role in ["ADMIN", "MANAGER"]:
                nav_items += [
                    ('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')),
                    ('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')),
                    ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                    ('<i class="fas fa-truck"></i> Suppliers', url_for('suppliers_list')),
                    ('<i class="fas fa-users"></i> Employees', url_for('employees_list')),
                ]
            if role == "ADMIN":
                nav_items += [
                    ('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')),
                    ('<i class="fas fa-history"></i> Audit', url_for('audit_logs')),
                    ('<i class="fas fa-trash"></i> Deleted', url_for('deleted_requests')),
                    ('<i class="fas fa-archive"></i> Backup', url_for('backup_page')),
                ]
            nav_items += [
                ('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')),
            ]
    else:
        nav_items = [('<i class="fas fa-sign-in-alt"></i> Login', url_for('login'))]

    nav_html = "".join('<a class="nav-link" href="' + str(u) + '">' + str(l) + '</a>' for l, u in nav_items)

    bell_html = ""
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        badge = ""
        if unread > 0:
            badge = '<span class="badge bg-danger" style="position:absolute;top:-5px;right:-5px;font-size:0.7rem;">' + str(unread) + '</span>'
        bell_html = '<a class="nav-link" href="' + url_for('notifications') + '" style="position:relative;"><i class="fas fa-bell"></i>' + badge + '</a>'

    flash_html = "".join(
        '<div class="alert alert-' + str(c) + ' alert-dismissible fade show">' + str(m) + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>'
        for c, m in get_flashed_messages(with_categories=True)
    )

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>""" + str(title) + """ | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);min-height:100vh;color:#e2e8f0;padding-top:70px}
.navbar{background:rgba(15,23,42,0.95)!important;backdrop-filter:blur(16px);border-bottom:1px solid rgba(245,158,11,0.25);padding:.75rem 1.5rem}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#f59e0b!important}
.nav-link{color:#cbd5e1!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem}
.nav-link i{color:#f59e0b;margin-right:4px}
.nav-link:hover{background:rgba(245,158,11,0.12);color:#f59e0b!important}
.navbar-toggler{border-color:rgba(245,158,11,0.4)}
.container{max-width:1280px;padding:1.5rem}
.card{background:rgba(30,41,59,0.7);border:1px solid rgba(245,158,11,0.15);border-radius:20px;color:#e2e8f0;padding:1.25rem;margin-bottom:1.5rem}
.card-title{color:#f59e0b;font-weight:600}
.metric-card{background:rgba(30,41,59,0.5);border:1px solid rgba(245,158,11,0.12);border-radius:20px;padding:1.2rem 1rem;text-align:center;height:100%}
.metric-icon{font-size:2rem;color:#f59e0b}
.metric-value{font-size:2rem;font-weight:700;color:#f8fafc}
.metric-label{font-size:.8rem;color:#94a3b8;text-transform:uppercase}
.table{color:#e2e8f0}
.table thead th{color:#f59e0b;border-bottom:2px solid rgba(245,158,11,0.2);font-size:.75rem;text-transform:uppercase;padding:10px}
.table td{padding:10px;border-color:rgba(245,158,11,0.08)}
.table-striped tbody tr:nth-of-type(odd){background-color:rgba(30,41,59,0.3)}
.table-hover tbody tr:hover{background-color:rgba(245,158,11,0.06)}
.btn{border-radius:40px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background:linear-gradient(135deg,#f59e0b,#d97706);color:#0f172a}
.btn-primary:hover{background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#0f172a}
.btn-success{background:linear-gradient(135deg,#22c55e,#16a34a);color:#fff}
.btn-success:hover{background:linear-gradient(135deg,#4ade80,#22c55e);color:#fff}
.btn-warning{background:linear-gradient(135deg,#eab308,#ca8a04);color:#0f172a}
.btn-warning:hover{background:linear-gradient(135deg,#facc15,#eab308);color:#0f172a}
.btn-danger{background:linear-gradient(135deg,#ef4444,#dc2626);color:#fff}
.btn-danger:hover{background:linear-gradient(135deg,#f87171,#ef4444);color:#fff}
.btn-info{background:linear-gradient(135deg,#06b6d4,#0891b2);color:#fff}
.btn-info:hover{background:linear-gradient(135deg,#22d3ee,#06b6d4);color:#fff}
.btn-secondary{background:#475569;color:#fff}
.btn-sm{padding:.4rem .9rem;font-size:.85rem}
.form-control,.form-select{background:rgba(15,23,42,0.6);border:1px solid rgba(245,158,11,0.2);border-radius:12px;color:#e2e8f0;padding:.75rem 1rem}
.form-control:focus,.form-select:focus{background:rgba(15,23,42,0.9);color:#f8fafc;border-color:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,0.15)}
.form-label{color:#cbd5e1;font-weight:500}
.alert{border-radius:16px;border:none;background:rgba(30,41,59,0.7);color:#e2e8f0}
.alert-success{border-left:4px solid #22c55e}
.alert-danger{border-left:4px solid #ef4444}
.alert-warning{border-left:4px solid #f59e0b}
.alert-info{border-left:4px solid #06b6d4}
.login-card{background:rgba(30,41,59,0.5);backdrop-filter:blur(20px);border:1px solid rgba(245,158,11,0.2);border-radius:32px;padding:2rem 2.5rem;max-width:440px;margin:0 auto}
.badge{padding:.4rem .8rem;border-radius:20px;font-weight:600;font-size:.75rem}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.login-card{padding:1.5rem;margin:1rem}}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href=""" + (url_for('dashboard') if current_user.is_authenticated else url_for('login')) + """"><i class="fas fa-hotel"></i> Rori Hotel</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
    <div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">""" + nav_html + bell_html + """</div></div>
  </div>
</nav>
<div class="container mt-4">""" + flash_html + content + """</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════
# SEED DATA
# ══════════════════════════════════════════════════════════════
def seed_data():
    for name in ["Housekeeping", "Front Office", "Engineering", "Food & Beverage", "Administration", "Security", "Maintenance", "Other"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
    db.session.commit()

    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))

    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))

    for name, dept in [("Buduchalley", "F&B"), ("Sillanto", "Unknown"), ("Fura", "Unknown"), ("Executive", "Unknown"), ("Mitima", "Unknown"), ("Odako", "Unknown"), ("Gudumale", "Unknown"), ("Bubble", "Unknown"), ("Bubbles", "Unknown"), ("Fura Corridor", "Unknown"), ("Executive Meeting Room", "Unknown"), ("Counter", "Unknown")]:
        if not Area.query.filter_by(name=name).first():
            db.session.add(Area(name=name, department=dept))

    for c in ["Electrical", "Plumbing", "HVAC", "Painting", "Carpentry", "Civil", "Safety", "General", "Other"]:
        if not Category.query.filter_by(name=c).first():
            db.session.add(Category(name=c))

    for i in ["Light", "Switch", "Window", "Door Key", "Door Lock", "Paint", "Mirror", "Drainage Cover", "Frame", "Background Frame", "Spot Light", "Plumbing", "AC", "Electrical", "Other"]:
        if not WorkingItem.query.filter_by(name=i).first():
            db.session.add(WorkingItem(name=i))

    for eid, name, title in [(1, "ተስፋሁን ነከረ", "General Mechanic"), (2, "ቸርነት አሞና", "General Mechanic"), (3, "ስምዖን ዮሐንስ", "General Mechanic"), (4, "አበባየሁ ክፍሌ", "Supervisor"), (5, "አሚር አወል", "Manager")]:
        if not db.session.get(Employee, eid):
            db.session.add(Employee(id=eid, name=name, job_title=title, department="Engineering"))

    if Supplier.query.count() == 0:
        for sname in ["ABC Maintenance Supply", "Hawassa Engineering Supply", "Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=sname, contact_person="", phone="", status="Active", is_active=True))

    hk_dept = Department.query.filter_by(name="Housekeeping").first()

    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)

    for s in [
        {"u": "amir", "n": "አሚር አወል", "r": "MANAGER", "d": None},
        {"u": "abebayhu", "n": "አበባየሁ ክፍሌ", "r": "SUPERVISOR", "d": None},
        {"u": "tesfahun", "n": "ተስፋሁን ነከረ", "r": "TECHNICIAN", "d": None},
        {"u": "simon", "n": "ስምዖን ዮሐንስ", "r": "TECHNICIAN", "d": None},
        {"u": "chernet", "n": "ቸርነት አሞና", "r": "TECHNICIAN", "d": None},
        {"u": "wale", "n": "ዋሌ", "r": "TECHNICIAN", "d": None},
        {"u": "tsadiku", "n": "ፃዲቁ", "r": "TECHNICIAN", "d": None},
        {"u": "housekeeping", "n": "Housekeeping Dept", "r": "DEPARTMENT", "d": hk_dept.id if hk_dept else None},
        {"u": "employee1", "n": "Test Employee", "r": "EMPLOYEE", "d": None},
    ]:
        existing = User.query.filter_by(username=s["u"]).first()
        if not existing:
            user = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=s["d"])
            user.set_password("123456")
            db.session.add(user)
        else:
            existing.department_id = s["d"]

    db.session.commit()
    print("✅ Seed data loaded")


# ══════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN", "MANAGER"]:
            return redirect(url_for("dashboard"))
        if current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        if current_user.role == "EMPLOYEE":
            return redirect(url_for("employee_dashboard"))
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

    login_html = """<div class="row justify-content-center align-items-center" style="min-height:80vh">
      <div class="col-11 col-md-5"><div class="login-card">
        <div class="text-center mb-4"><h3 class="fw-bold" style="color:#f59e0b"><i class="fas fa-hotel"></i> Rori Hotel</h3><p style="color:#94a3b8">የጥገና ክፍል መግቢያ</p></div>
        <form method="post">
          <div class="mb-3"><label class="form-label">መለያ ስም</label><input type="text" class="form-control" name="username" required autofocus></div>
          <div class="mb-4"><label class="form-label">የይለፍ ቃል</label><input type="password" class="form-control" name="password" required></div>
          <button class="btn btn-primary w-100"><i class="fas fa-sign-in-alt"></i> ግባ</button>
        </form>
        <hr class="my-4" style="border-color:rgba(245,158,11,0.2)">
        <div class="text-center small" style="color:#94a3b8"><p class="mb-1">Admin: <b>admin / admin123</b></p><p class="mb-0">Staff: <b>tesfahun / 123456</b></p></div>
      </div></div>
    </div>"""
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
        new_pass = request.form.get("new_password", "").strip()
        if new_pass:
            user.set_password(new_pass)
        db.session.commit()
        flash("መረጃዎ ተዘምኗል", "success")
        return redirect(url_for("profile"))
    content = ('<h3 style="color:#f59e0b">👤 መገለጫ</h3>'
        '<div class="card"><h4>' + str(user.full_name) + '</h4>'
        '<p>@' + str(user.username) + ' · <span class="badge bg-warning text-dark">' + str(user.role) + '</span></p>'
        '<p>📧 ' + str(user.email or "—") + ' | 📱 ' + str(user.phone or "—") + '</p><hr>'
        '<form method="post">'
        '<div class="mb-3"><label class="form-label">ኢሜል</label><input type="email" class="form-control" name="email" value="' + str(user.email or "") + '"></div>'
        '<div class="mb-3"><label class="form-label">ስልክ</label><input type="text" class="form-control" name="phone" value="' + str(user.phone or "") + '"></div>'
        '<div class="mb-3"><label class="form-label">አዲስ የይለፍ ቃል</label><input type="password" class="form-control" name="new_password" placeholder="ባዶ ከሆነ አይለወጥም"></div>'
        '<button class="btn btn-primary"><i class="fas fa-save"></i> አስቀምጥ</button>'
        '</form></div>')
    return page("Profile", content)


# ══════════════════════════════════════════════════════════════
# DASHBOARD ANALYTICS HELPERS
# ══════════════════════════════════════════════════════════════
COMPLETED_STATES = ["Completed", "Verified", "Closed"]
PENDING_STATES = ["Pending", "Approved"]
INPROGRESS_STATES = ["Assigned", "In Progress"]


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def build_filtered_query(args):
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    try:
        if current_user.is_authenticated and current_user.role in ["MANAGER", "ADMIN"]:
            q = q.filter(db.or_(
                MaintenanceRequest.awaiting_hk_approval == False,
                MaintenanceRequest.awaiting_hk_approval.is_(None),
            ))
    except Exception:
        pass
    d_from = _parse_date(args.get("date_from"))
    if d_from:
        q = q.filter(MaintenanceRequest.created_at >= d_from)
    d_to = _parse_date(args.get("date_to"))
    if d_to:
        q = q.filter(MaintenanceRequest.created_at < d_to + timedelta(days=1))
    if args.get("department"):
        try:
            q = q.filter(MaintenanceRequest.department_id == int(args["department"]))
        except (ValueError, TypeError):
            pass
    if args.get("category"):
        try:
            q = q.filter(MaintenanceRequest.category_id == int(args["category"]))
        except (ValueError, TypeError):
            pass
    if args.get("status"):
        q = q.filter(MaintenanceRequest.status == args["status"])
    if args.get("floor"):
        try:
            q = q.filter(MaintenanceRequest.floor == int(args["floor"]))
        except (ValueError, TypeError):
            pass
    if args.get("room_id"):
        try:
            q = q.filter(MaintenanceRequest.room_id == int(args["room_id"]))
        except (ValueError, TypeError):
            pass
    if args.get("area_id"):
        try:
            q = q.filter(MaintenanceRequest.area_id == int(args["area_id"]))
        except (ValueError, TypeError):
            pass
    return q


def format_duration(seconds):
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f} hrs"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    return f"{days}d {hours}h" if hours else f"{days}d"


def humanize_ago(dt):
    if not dt:
        return ""
    delta = datetime.utcnow() - dt
    s = delta.total_seconds()
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s / 60)} minutes ago"
    if s < 86400:
        return f"{int(s / 3600)} hours ago"
    if s < 604800:
        return f"{int(s / 86400)} days ago"
    return dt.strftime("%Y-%m-%d")


def _avg_resolution_seconds(reqs):
    completed = [r for r in reqs if r.completed_date and r.created_at]
    if not completed:
        return None
    total = sum((r.completed_date - r.created_at).total_seconds() for r in completed)
    return total / len(completed)


def _previous_period(date_from_str, date_to_str):
    if not date_from_str or not date_to_str:
        return None, None
    df = _parse_date(date_from_str)
    dt = _parse_date(date_to_str)
    if not df or not dt:
        return None, None
    span = (dt + timedelta(days=1)) - df
    return df - span, df


def get_dashboard_kpis(args):
    base = build_filtered_query(args)
    reqs = base.all()
    total = len(reqs)
    pending = sum(1 for r in reqs if r.status in PENDING_STATES)
    completed = sum(1 for r in reqs if r.status in COMPLETED_STATES)
    avg_seconds = _avg_resolution_seconds([r for r in reqs if r.status in COMPLETED_STATES])

    prev_total = prev_completed = None
    prev_avg_seconds = None
    prev_from, prev_to = _previous_period(args.get("date_from"), args.get("date_to"))
    if prev_from and prev_to:
        pq = MaintenanceRequest.query.filter(
            MaintenanceRequest.is_deleted == False,
            MaintenanceRequest.created_at >= prev_from,
            MaintenanceRequest.created_at < prev_to,
        )
        if args.get("department"):
            try:
                pq = pq.filter(MaintenanceRequest.department_id == int(args["department"]))
            except (ValueError, TypeError):
                pass
        if args.get("category"):
            try:
                pq = pq.filter(MaintenanceRequest.category_id == int(args["category"]))
            except (ValueError, TypeError):
                pass
        prev_reqs = pq.all()
        prev_total = len(prev_reqs)
        prev_completed = sum(1 for r in prev_reqs if r.status in COMPLETED_STATES)
        prev_avg_seconds = _avg_resolution_seconds(
            [r for r in prev_reqs if r.status in COMPLETED_STATES]
        )

    total_delta = None
    if prev_total and prev_total > 0:
        total_delta = ((total - prev_total) / prev_total) * 100

    completion_rate = (completed / total * 100) if total else 0.0
    avg_delta = None
    if prev_avg_seconds is not None and avg_seconds is not None:
        avg_delta = prev_avg_seconds - avg_seconds

    return {
        "total": total,
        "pending": pending,
        "completed": completed,
        "completion_rate": round(completion_rate, 1),
        "avg_resolution": format_duration(avg_seconds),
        "avg_delta_seconds": avg_delta,
        "total_delta": round(total_delta, 1) if total_delta is not None else None,
        "has_prev": prev_total is not None and prev_total > 0,
    }


def get_request_trends(args):
    reqs = build_filtered_query(args).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))
    if d_from and d_to:
        start, end = d_from, d_to
    else:
        dates = [r.created_at for r in reqs if r.created_at]
        if not dates:
            return {"labels": [], "total": [], "completed": [],
                    "pending": [], "in_progress": [], "granularity": "day"}
        start = min(dates).replace(hour=0, minute=0, second=0, microsecond=0)
        end = max(dates).replace(hour=0, minute=0, second=0, microsecond=0)

    span_days = (end - start).days + 1
    if span_days <= 31:
        gran = "day"
    elif span_days <= 180:
        gran = "week"
    else:
        gran = "month"

    ordered_keys, labels = [], []
    if gran == "day":
        cur = start
        while cur <= end:
            ordered_keys.append(cur.strftime("%Y-%m-%d"))
            labels.append(cur.strftime("%b %d"))
            cur += timedelta(days=1)
    elif gran == "week":
        cur = start - timedelta(days=start.weekday())
        while cur <= end:
            ordered_keys.append(cur.strftime("%Y-%m-%d"))
            labels.append("Wk " + cur.strftime("%b %d"))
            cur += timedelta(days=7)
    else:
        cur = start.replace(day=1)
        while cur <= end:
            ordered_keys.append(cur.strftime("%Y-%m"))
            labels.append(cur.strftime("%b %Y"))
            cur = cur.replace(year=cur.year + 1, month=1) if cur.month == 12 \
                  else cur.replace(month=cur.month + 1)

    counts = {k: {"total": 0, "completed": 0, "pending": 0, "in_progress": 0}
              for k in ordered_keys}

    for r in reqs:
        if not r.created_at:
            continue
        if gran == "day":
            key = r.created_at.strftime("%Y-%m-%d")
        elif gran == "week":
            mon = r.created_at - timedelta(days=r.created_at.weekday())
            key = mon.strftime("%Y-%m-%d")
        else:
            key = r.created_at.strftime("%Y-%m")

        if key in counts:
            counts[key]["total"] += 1
            if r.status in COMPLETED_STATES:
                counts[key]["completed"] += 1
            elif r.status in PENDING_STATES:
                counts[key]["pending"] += 1
            elif r.status in INPROGRESS_STATES:
                counts[key]["in_progress"] += 1

    return {
        "labels": labels,
        "total": [counts[k]["total"] for k in ordered_keys],
        "completed": [counts[k]["completed"] for k in ordered_keys],
        "pending": [counts[k]["pending"] for k in ordered_keys],
        "in_progress": [counts[k]["in_progress"] for k in ordered_keys],
        "granularity": gran,
    }


def get_category_statistics(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        counts[r.category.name if r.category else "Uncategorized"] += 1
    total = sum(counts.values())
    items = sorted(counts.items(), key=lambda x: -x[1])
    return {
        "labels": [k for k, _ in items],
        "values": [v for _, v in items],
        "percentages": [round(v / total * 100, 1) if total else 0 for _, v in items],
        "total": total,
    }


def get_status_statistics(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        counts[r.status] += 1
    order = ["Pending", "Approved", "Assigned", "In Progress",
             "Completed", "Verified", "Closed", "Rejected", "Overdue"]
    total = sum(counts.values())
    items = [(s, counts[s]) for s in order if counts.get(s, 0) > 0]
    for s, c in counts.items():
        if s not in order and c > 0:
            items.append((s, c))
    return {
        "labels": [k for k, _ in items],
        "values": [v for _, v in items],
        "percentages": [round(v / total * 100, 1) if total else 0 for _, v in items],
        "total": total,
    }


def get_department_statistics(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        counts[r.department.name if r.department else "Unspecified"] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    return {"labels": [k for k, _ in items], "values": [v for _, v in items]}


def get_top_locations(args, limit=10):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        counts[r.location_name] += 1
    return sorted(counts.items(), key=lambda x: -x[1])[:limit]


def get_work_order_statistics(args):
    q = WorkOrder.query
    d_from = _parse_date(args.get("date_from"))
    if d_from:
        q = q.filter(WorkOrder.created_at >= d_from)
    d_to = _parse_date(args.get("date_to"))
    if d_to:
        q = q.filter(WorkOrder.created_at < d_to + timedelta(days=1))

    wos = q.all()
    counts = defaultdict(int)
    for wo in wos:
        counts[wo.status] += 1

    return {
        "total": len(wos),
        "pending": counts.get("Pending", 0),
        "assigned": counts.get("Assigned", 0),
        "in_progress": counts.get("In Progress", 0),
        "completed": counts.get("Completed", 0),
        "verified": counts.get("Verified", 0),
        "closed": counts.get("Closed", 0),
    }


def get_staff_statistics(args, limit=10):
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))

    result = []
    for s in staff:
        q = WorkOrder.query.filter_by(assigned_to_id=s.id)
        if d_from:
            q = q.filter(WorkOrder.created_at >= d_from)
        if d_to:
            q = q.filter(WorkOrder.created_at < d_to + timedelta(days=1))

        wos = q.all()
        completed_wos = [w for w in wos
                         if w.status in ["Completed", "Verified"] and w.completed_date and w.created_at]
        avg_sec = None
        if completed_wos:
            avg_sec = sum((w.completed_date - w.created_at).total_seconds()
                          for w in completed_wos) / len(completed_wos)

        result.append({
            "name": s.full_name or s.username,
            "role": s.role,
            "assigned": len(wos),
            "in_progress": sum(1 for w in wos if w.status == "In Progress"),
            "completed": sum(1 for w in wos if w.status in COMPLETED_STATES),
            "avg_resolution": format_duration(avg_sec),
        })

    result.sort(key=lambda x: -x["assigned"])
    return result[:limit]


def get_inventory_summary(args):
    parts = InventoryPart.query.filter_by(status="Active").all()
    total_parts = len(parts)
    low = sum(1 for p in parts if 0 < (p.quantity or 0) <= (p.minimum_stock or 0))
    out = sum(1 for p in parts if (p.quantity or 0) <= 0)
    value = sum((p.quantity or 0) * (p.unit_cost or 0) for p in parts)

    wq = WorkOrderPart.query
    d_from = _parse_date(args.get("date_from"))
    if d_from:
        wq = wq.filter(WorkOrderPart.created_at >= d_from)
    d_to = _parse_date(args.get("date_to"))
    if d_to:
        wq = wq.filter(WorkOrderPart.created_at < d_to + timedelta(days=1))
    parts_used = sum(w.quantity or 0 for w in wq.all())

    return {
        "total_parts": total_parts,
        "low_stock": low,
        "out_of_stock": out,
        "total_value": round(value, 2),
        "parts_used": parts_used,
    }


def get_recent_activity(limit=10):
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    result = []
    for log in logs:
        result.append({
            "user": log.user.full_name if log.user else "System",
            "action": log.action or "",
            "object_type": log.object_type or "",
            "object_id": log.object_id or "",
            "time": humanize_ago(log.created_at),
            "raw_time": log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
        })
    return result


def get_recent_requests(args, limit=10):
    return build_filtered_query(args) \
        .order_by(MaintenanceRequest.created_at.desc()).limit(limit).all()


def build_dashboard_nav():
    role = current_user.role
    items = []

    def add(label, icon, endpoint, active=False, **kwargs):
        items.append({
            "label": label, "icon": icon,
            "url": url_for(endpoint, **kwargs) if kwargs else url_for(endpoint),
            "active": active,
        })

    if role in ["ADMIN", "MANAGER"]:
        add("Dashboard", "fa-home", "dashboard", active=True)
        add("New Request", "fa-plus-circle", "request_create")
        add("Requests", "fa-tasks", "requests_list")
        add("Work Orders", "fa-clipboard-list", "workorders_list")
        add("Rooms", "fa-door-open", "rooms_list")
        add("Areas", "fa-map-marked-alt", "areas_list")
        add("Inventory", "fa-boxes", "inventory_list")
        add("Suppliers", "fa-truck", "suppliers_list")
        add("Employees", "fa-users", "employees_list")
        if role == "ADMIN":
            add("Users", "fa-user-cog", "admin_users")
            add("Audit Log", "fa-history", "audit_logs")
            add("Archived", "fa-trash", "deleted_requests")
            add("Backup", "fa-archive", "backup_page")
        add("Reports", "fa-chart-bar", "reports")
        add("Notifications", "fa-bell", "notifications")
        add("Profile", "fa-user-circle", "profile")
        add("Logout", "fa-sign-out-alt", "logout")
    return items


def build_department_nav():
    return [
        {"label": "Dashboard",     "icon": "fa-home",         "url": url_for("department_dashboard"), "active": True},
        {"label": "New Request",   "icon": "fa-plus-circle",  "url": url_for("request_create"),       "active": False},
        {"label": "Notifications", "icon": "fa-bell",         "url": url_for("notifications"),        "active": False},
        {"label": "Profile",       "icon": "fa-user-circle",  "url": url_for("profile"),              "active": False},
        {"label": "Logout",        "icon": "fa-sign-out-alt", "url": url_for("logout"),               "active": False},
    ]


def status_badge_class(status):
    return {
        "Pending": "b-pending",
        "Approved": "b-approved",
        "Assigned": "b-assigned",
        "In Progress": "b-inprogress",
        "Completed": "b-completed",
        "Verified": "b-verified",
        "Closed": "b-closed",
        "Rejected": "b-rejected",
        "Overdue": "b-overdue",
    }.get(status, "b-default")


def priority_badge_class(priority):
    return {
        "URGENT": "b-urgent",
        "HIGH": "b-high",
        "MEDIUM": "b-medium",
        "LOW": "b-low",
    }.get(priority, "b-default")


# ══════════════════════════════════════════════════════════════
# DASHBOARDS
# ══════════════════════════════════════════════════════════════
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role in STAFF_ROLES:
        return redirect(url_for("workorders_list"))
    if current_user.role == "DEPARTMENT":
        return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE":
        return redirect(url_for("employee_dashboard"))

    args = request.args

    kpis = get_dashboard_kpis(args)
    trends = get_request_trends(args)
    categories = get_category_statistics(args)
    statuses = get_status_statistics(args)
    departments = get_department_statistics(args)
    top_locations = get_top_locations(args)
    work_orders = get_work_order_statistics(args)
    staff_stats = get_staff_statistics(args)
    inventory = get_inventory_summary(args)
    recent_activity = get_recent_activity(10)
    recent_requests = get_recent_requests(args, 10)

    all_departments = Department.query.order_by(Department.name).all()
    all_categories = Category.query.order_by(Category.name).all()
    all_rooms = Room.query.order_by(Room.room_number).all()
    all_areas = Area.query.order_by(Area.name).all()
    all_floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()]
    if not all_floors:
        all_floors = sorted({r.floor for r in Room.query.all()})

    chart_data = {
        "trends": trends,
        "categories": categories,
        "statuses": statuses,
        "departments": departments,
    }

    return render_template(
        "dashboard.html",
        title="Rori Hotel Maintenance Dashboard",
        kpis=kpis,
        work_orders=work_orders,
        top_locations=top_locations,
        staff_stats=staff_stats,
        inventory=inventory,
        recent_activity=recent_activity,
        recent_requests=recent_requests,
        all_departments=all_departments,
        all_categories=all_categories,
        all_rooms=all_rooms,
        all_areas=all_areas,
        all_floors=all_floors,
        nav_items=build_dashboard_nav(),
        chart_data=chart_data,
        filters={k: v for k, v in args.items()},
        status_badge_class=status_badge_class,
        priority_badge_class=priority_badge_class,
    )


# ══════════════════════════════════════════════════════════════
# HOUSEKEEPING DASHBOARD — embedded template
# ══════════════════════════════════════════════════════════════
HK_DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:#0a0a1a;color:#fff;-webkit-font-smoothing:antialiased;font-size:13px;line-height:1.45;min-height:100vh;padding:1rem;overflow-x:hidden}
a{color:inherit;text-decoration:none}
button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit}
.hk-wrap{max-width:1400px;margin:0 auto}
.hk-top{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap}
.hk-title{display:flex;align-items:center;gap:.7rem}
.hk-logo{width:40px;height:40px;border-radius:11px;background:linear-gradient(135deg,#8B5CF6,#3B82F6);display:flex;align-items:center;justify-content:center;font-size:1.1rem;color:#fff;box-shadow:0 4px 16px rgba(139,92,246,0.5)}
.hk-title h1{font-size:1.1rem;font-weight:800;color:#fff}
.hk-title h1 span{background:linear-gradient(135deg,#A855F7,#38BDF8);-webkit-background-clip:text;background-clip:text;color:transparent}
.hk-title p{font-size:.68rem;color:#9CA3AF;margin-top:1px}
.hk-user{display:flex;align-items:center;gap:.6rem;padding:.4rem .9rem .4rem .4rem;background:#14142a;border:1px solid rgba(139,92,246,0.15);border-radius:40px}
.hk-user-av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#8B5CF6,#EC4899);display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:800;color:#fff}
.hk-user-txt{display:flex;flex-direction:column;line-height:1.1}
.hk-user-txt strong{font-size:.78rem;font-weight:600;color:#fff}
.hk-user-txt small{font-size:.6rem;color:#A855F7;font-weight:700;text-transform:uppercase}
.hk-flash{background:#14142a;border:1px solid rgba(139,92,246,0.2);color:#fff;font-size:.8rem;border-radius:12px;padding:.7rem 1rem;margin-bottom:1rem}
.hk-grid{display:grid;grid-template-columns:repeat(12,1fr);gap:1rem;margin-bottom:1rem}
.hk-c2{grid-column:span 2}
.hk-c4{grid-column:span 4}
.hk-c6{grid-column:span 6}
.hk-c8{grid-column:span 8}
.hk-card{background:#14142a;border:1px solid rgba(139,92,246,0.15);border-radius:18px;padding:1.1rem 1.2rem}
.hk-card-head{display:flex;justify-content:space-between;align-items:center;gap:.5rem;margin-bottom:.9rem;flex-wrap:wrap}
.hk-card-head h3{font-size:.85rem;font-weight:700;color:#fff;display:flex;align-items:center;gap:.5rem}
.hk-card-head h3 i{color:#A855F7;font-size:.8rem}
.hk-hint{font-size:.6rem;color:#9CA3AF;background:rgba(139,92,246,0.1);padding:.2rem .55rem;border-radius:20px;font-weight:700;text-transform:uppercase}
.hk-link{font-size:.68rem;color:#A855F7;font-weight:700}
.hk-kpi{background:#14142a;border:1px solid rgba(139,92,246,0.15);border-radius:18px;padding:1rem 1.1rem;position:relative;overflow:hidden;min-height:110px;display:flex;flex-direction:column;justify-content:space-between}
.hk-kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,#8B5CF6,#A855F7)}
.hk-kpi.b::before{background:linear-gradient(90deg,#38BDF8,#3B82F6)}
.hk-kpi.g::before{background:linear-gradient(90deg,#22C55E,#10B981)}
.hk-kpi.o::before{background:linear-gradient(90deg,#F59E0B,#D97706)}
.hk-kpi.p::before{background:linear-gradient(90deg,#EC4899,#8B5CF6)}
.hk-kpi-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.55rem}
.hk-kpi-lbl{font-size:.6rem;color:#9CA3AF;text-transform:uppercase;letter-spacing:.8px;font-weight:700}
.hk-kpi-val{font-size:1.7rem;font-weight:800;color:#fff;line-height:1;margin-top:.3rem;letter-spacing:-.02em}
.hk-kpi-ico{width:28px;height:28px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:.75rem;background:rgba(139,92,246,0.14);color:#A855F7}
.hk-kpi.b .hk-kpi-ico{background:rgba(56,189,248,0.14);color:#38BDF8}
.hk-kpi.g .hk-kpi-ico{background:rgba(34,197,94,0.14);color:#22C55E}
.hk-kpi.o .hk-kpi-ico{background:rgba(245,158,11,0.14);color:#F59E0B}
.hk-kpi.p .hk-kpi-ico{background:rgba(236,72,153,0.14);color:#EC4899}
.hk-kpi-foot{font-size:.62rem;color:#9CA3AF;display:flex;align-items:center;gap:.3rem;margin-top:.4rem}
.hk-chart{position:relative;width:100%;height:230px}
.hk-chart.tall{height:280px}
.hk-chart.donut{height:230px}
.hk-prog-list{display:flex;flex-direction:column;gap:.7rem}
.hk-prog-row{display:flex;flex-direction:column;gap:.35rem}
.hk-prog-top{display:flex;justify-content:space-between;font-size:.74rem}
.hk-prog-top .nm{color:#e5e7eb;font-weight:600}
.hk-prog-top .ct{color:#A855F7;font-weight:800}
.hk-prog-bar{height:6px;background:rgba(139,92,246,0.1);border-radius:6px;overflow:hidden}
.hk-prog-bar span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#8B5CF6,#EC4899)}
.hk-act{display:flex;flex-direction:column;gap:.55rem}
.hk-act-item{display:flex;align-items:center;gap:.7rem;padding:.6rem .7rem;background:#0f0f22;border:1px solid rgba(139,92,246,0.12);border-radius:12px}
.hk-act-item:hover{border-color:rgba(139,92,246,0.35);background:rgba(139,92,246,0.04)}
.hk-act-av{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.8rem;font-weight:800;color:#fff;background:linear-gradient(135deg,#8B5CF6,#38BDF8);flex-shrink:0}
.hk-act-av.a2{background:linear-gradient(135deg,#38BDF8,#3B82F6)}
.hk-act-av.a3{background:linear-gradient(135deg,#EC4899,#8B5CF6)}
.hk-act-av.a4{background:linear-gradient(135deg,#22C55E,#10B981)}
.hk-act-main{flex:1;min-width:0}
.hk-act-line1{font-size:.76rem;font-weight:700;color:#fff;display:flex;gap:.4rem;align-items:center;flex-wrap:wrap}
.hk-act-line1 a{color:#A855F7}
.hk-act-line2{font-size:.64rem;color:#9CA3AF;margin-top:2px;display:flex;gap:.55rem;flex-wrap:wrap}
.hk-act-line2 i{font-size:.58rem}
.hk-badge{display:inline-flex;align-items:center;padding:.2rem .5rem;border-radius:20px;font-size:.58rem;font-weight:800;text-transform:uppercase;white-space:nowrap}
.hk-badge.b-pending{background:rgba(245,158,11,0.15);color:#F59E0B;border:1px solid rgba(245,158,11,0.3)}
.hk-badge.b-approved{background:rgba(59,130,246,0.15);color:#3B82F6;border:1px solid rgba(59,130,246,0.3)}
.hk-badge.b-assigned{background:rgba(139,92,246,0.15);color:#8B5CF6;border:1px solid rgba(139,92,246,0.3)}
.hk-badge.b-inprogress{background:rgba(56,189,248,0.15);color:#38BDF8;border:1px solid rgba(56,189,248,0.3)}
.hk-badge.b-completed{background:rgba(34,197,94,0.15);color:#22C55E;border:1px solid rgba(34,197,94,0.3)}
.hk-badge.b-verified{background:rgba(16,185,129,0.15);color:#10B981;border:1px solid rgba(16,185,129,0.3)}
.hk-badge.b-closed{background:rgba(34,197,94,0.2);color:#16A34A;border:1px solid rgba(34,197,94,0.4)}
.hk-badge.b-rejected{background:rgba(239,68,68,0.15);color:#EF4444;border:1px solid rgba(239,68,68,0.3)}
.hk-badge.b-overdue{background:rgba(239,68,68,0.2);color:#f87171;border:1px solid rgba(239,68,68,0.4)}
.hk-badge.b-default{background:rgba(156,163,175,0.15);color:#9CA3AF;border:1px solid rgba(156,163,175,0.3)}
.hk-badge.b-urgent{background:rgba(239,68,68,0.15);color:#EF4444;border:1px solid rgba(239,68,68,0.3)}
.hk-badge.b-high{background:rgba(245,158,11,0.15);color:#F59E0B;border:1px solid rgba(245,158,11,0.3)}
.hk-badge.b-medium{background:rgba(59,130,246,0.15);color:#3B82F6;border:1px solid rgba(59,130,246,0.3)}
.hk-badge.b-low{background:rgba(34,197,94,0.15);color:#22C55E;border:1px solid rgba(34,197,94,0.3)}
.hk-table{width:100%;border-collapse:collapse;font-size:.74rem}
.hk-table th{text-align:left;padding:.6rem .5rem;color:#9CA3AF;font-size:.6rem;text-transform:uppercase;border-bottom:1px solid rgba(139,92,246,0.15);font-weight:700;white-space:nowrap}
.hk-table td{padding:.65rem .5rem;border-bottom:1px solid rgba(139,92,246,0.05);color:#e5e7eb;vertical-align:middle}
.hk-table tr:last-child td{border-bottom:none}
.hk-table a{color:#A855F7;font-weight:600}
.hk-feed{display:flex;flex-direction:column;gap:.4rem}
.hk-feed-item{display:flex;gap:.6rem;padding:.55rem .7rem;background:#0f0f22;border-left:2px solid #8B5CF6;border-radius:9px;font-size:.74rem}
.hk-feed-item.unread{border-left-color:#F59E0B}
.hk-feed-ic{width:24px;height:24px;border-radius:7px;background:rgba(139,92,246,0.12);color:#A855F7;display:flex;align-items:center;justify-content:center;font-size:.6rem;flex-shrink:0}
.hk-feed-b{flex:1;min-width:0}
.hk-feed-b .tx{color:#e5e7eb;line-height:1.35}
.hk-feed-b .tx strong{color:#fff}
.hk-feed-b .tm{font-size:.6rem;color:#6B7280;margin-top:2px}
.hk-empty{text-align:center;padding:1.6rem 1rem;color:#9CA3AF;font-size:.76rem}
.hk-empty i{font-size:1.5rem;color:#A855F7;opacity:.4;display:block;margin-bottom:.4rem}
@media (max-width:1200px){.hk-c2{grid-column:span 4}.hk-c4{grid-column:span 6}}
@media (max-width:900px){.hk-c2,.hk-c4,.hk-c6,.hk-c8{grid-column:span 12}.hk-kpi-val{font-size:1.4rem}}
</style>
</head>
<body>
<div class="hk-wrap">

  <div class="hk-top">
    <div class="hk-title">
      <div class="hk-logo"><i class="fas fa-broom"></i></div>
      <div>
        <h1>{{ dept_name }} <span>Dashboard</span></h1>
        <p>Housekeeping &amp; Room Maintenance Overview</p>
      </div>
    </div>
    <div class="hk-user">
      <div class="hk-user-av">{{ (current_user.full_name or current_user.username or 'U')[0]|upper }}</div>
      <div class="hk-user-txt">
        <strong>{{ current_user.full_name or current_user.username }}</strong>
        <small>{{ current_user.role }}</small>
      </div>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}{% for cat, msg in messages %}
      <div class="hk-flash"><strong>{{ cat|upper }}:</strong> {{ msg }}</div>
    {% endfor %}{% endif %}
  {% endwith %}

  <div class="hk-grid">
    <div class="hk-c2">
      <div class="hk-kpi">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">Total</div><div class="hk-kpi-val">{{ kpis.total }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-clipboard-list"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-list"></i> All requests</div>
      </div>
    </div>
    <div class="hk-c2">
      <div class="hk-kpi o">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">Pending</div><div class="hk-kpi-val">{{ kpis.pending }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-hourglass-half"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-circle-exclamation"></i> Awaiting</div>
      </div>
    </div>
    <div class="hk-c2">
      <div class="hk-kpi b">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">Approved</div><div class="hk-kpi-val">{{ kpis.approved }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-check-circle"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-thumbs-up"></i> Ready</div>
      </div>
    </div>
    <div class="hk-c2">
      <div class="hk-kpi p">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">In Progress</div><div class="hk-kpi-val">{{ kpis.in_progress }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-spinner"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-wrench"></i> Working</div>
      </div>
    </div>
    <div class="hk-c2">
      <div class="hk-kpi g">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">Completed</div><div class="hk-kpi-val">{{ kpis.completed }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-circle-check"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-check-double"></i> Finished</div>
      </div>
    </div>
    <div class="hk-c2">
      <div class="hk-kpi">
        <div class="hk-kpi-top">
          <div><div class="hk-kpi-lbl">Closed</div><div class="hk-kpi-val">{{ kpis.closed }}</div></div>
          <div class="hk-kpi-ico"><i class="fas fa-archive"></i></div>
        </div>
        <div class="hk-kpi-foot"><i class="fas fa-lock"></i> Archived</div>
      </div>
    </div>
  </div>

  <div class="hk-grid">
    <div class="hk-c8">
      <div class="hk-card">
        <div class="hk-card-head">
          <h3><i class="fas fa-chart-area"></i> Housekeeping Request Trends</h3>
          <span class="hk-hint">Last 14 Days</span>
        </div>
        <div class="hk-chart tall"><canvas id="chart-trends"></canvas></div>
      </div>
    </div>
    <div class="hk-c4">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-chart-pie"></i> Status Distribution</h3></div>
        <div class="hk-chart donut"><canvas id="chart-status"></canvas></div>
      </div>
    </div>
  </div>

  <div class="hk-grid">
    <div class="hk-c4">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-building"></i> By Floor</h3></div>
        <div class="hk-chart"><canvas id="chart-floors"></canvas></div>
      </div>
    </div>
    <div class="hk-c4">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-chart-bar"></i> By Category</h3></div>
        <div class="hk-chart"><canvas id="chart-categories"></canvas></div>
      </div>
    </div>
    <div class="hk-c4">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-fire"></i> Priority</h3></div>
        <div class="hk-chart donut"><canvas id="chart-priorities"></canvas></div>
      </div>
    </div>
  </div>

  <div class="hk-grid">
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-location-dot"></i> Top Housekeeping Areas</h3></div>
        {% if top_locations and top_locations|length > 0 %}
          {% set max_c = top_locations[0][1] if top_locations[0][1] > 0 else 1 %}
          <div class="hk-prog-list">
            {% for name, count in top_locations %}
              <div class="hk-prog-row">
                <div class="hk-prog-top"><span class="nm">{{ name }}</span><span class="ct">{{ count }}</span></div>
                <div class="hk-prog-bar"><span style="width:{{ (count / max_c * 100)|round|int }}%"></span></div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="hk-empty"><i class="fas fa-location-dot"></i>No data yet.</div>
        {% endif %}
      </div>
    </div>
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head">
          <h3><i class="fas fa-list"></i> My Housekeeping Requests</h3>
          <a href="{{ url_for('request_create') }}" class="hk-link"><i class="fas fa-plus"></i> New</a>
        </div>
        {% if my_requests and my_requests|length > 0 %}
          <div class="hk-act">
            {% for r in my_requests %}
              {% set av_class = 'a2' if loop.index % 4 == 2 else 'a3' if loop.index % 4 == 3 else 'a4' if loop.index % 4 == 0 else '' %}
              <div class="hk-act-item">
                <div class="hk-act-av {{ av_class }}">{{ (r.request_no or 'R')[0]|upper }}</div>
                <div class="hk-act-main">
                  <div class="hk-act-line1">
                    <a href="{{ url_for('request_detail', req_id=r.id) }}">{{ r.request_no }}</a>
                    <span class="hk-badge {{ status_badge_class(r.status) }}">{{ r.status }}</span>
                    <span class="hk-badge {{ priority_badge_class(r.priority) }}">{{ r.priority }}</span>
                  </div>
                  <div class="hk-act-line2">
                    <span><i class="fas fa-location-dot"></i> {{ r.location_name }}</span>
                    <span><i class="fas fa-clock"></i> {{ r.created_at.strftime('%b %d, %H:%M') if r.created_at else '—' }}</span>
                  </div>
                </div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="hk-empty"><i class="fas fa-inbox"></i>No requests yet.</div>
        {% endif %}
      </div>
    </div>
  </div>

  <div class="hk-grid">
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-clock-rotate-left"></i> Latest Requests</h3></div>
        {% if recent_requests and recent_requests|length > 0 %}
          <table class="hk-table">
            <thead><tr><th>Request</th><th>Location</th><th>Status</th><th>Date</th></tr></thead>
            <tbody>
              {% for r in recent_requests %}
                <tr>
                  <td><a href="{{ url_for('request_detail', req_id=r.id) }}">{{ r.request_no }}</a></td>
                  <td>{{ r.location_name }}</td>
                  <td><span class="hk-badge {{ status_badge_class(r.status) }}">{{ r.status }}</span></td>
                  <td style="color:#9CA3AF;font-size:.7rem">{{ r.created_at.strftime('%b %d') if r.created_at else '—' }}</td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        {% else %}
          <div class="hk-empty"><i class="fas fa-inbox"></i>No requests yet.</div>
        {% endif %}
      </div>
    </div>
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-wrench"></i> Maintenance Follow-up</h3></div>
        {% if work_orders and work_orders|length > 0 %}
          <div class="hk-act">
            {% for wo in work_orders %}
              <div class="hk-act-item">
                <div class="hk-act-av a2"><i class="fas fa-tools"></i></div>
                <div class="hk-act-main">
                  <div class="hk-act-line1">
                    <a href="{{ url_for('workorder_detail', wo_id=wo.id) }}">{{ wo.work_order_no }}</a>
                    <span class="hk-badge {{ status_badge_class(wo.status) }}">{{ wo.status }}</span>
                  </div>
                  <div class="hk-act-line2">
                    <span><i class="fas fa-user"></i> {{ wo.assigned_to.full_name if wo.assigned_to else 'Unassigned' }}</span>
                    <span><i class="fas fa-clock"></i> {{ wo.created_at.strftime('%b %d') if wo.created_at else '—' }}</span>
                  </div>
                </div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="hk-empty"><i class="fas fa-wrench"></i>No work orders yet.</div>
        {% endif %}
      </div>
    </div>
  </div>

  <div class="hk-grid">
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head"><h3><i class="fas fa-wave-square"></i> Housekeeping Activity</h3></div>
        {% if activity and activity|length > 0 %}
          <div class="hk-feed">
            {% for a in activity %}
              <div class="hk-feed-item">
                <div class="hk-feed-ic"><i class="fas fa-bolt"></i></div>
                <div class="hk-feed-b">
                  <div class="tx"><strong>{{ a.user }}</strong>{% if a.status %} set <strong>{{ a.status }}</strong>{% endif %}{% if a.notes %} — {{ a.notes }}{% endif %}</div>
                  <div class="tm">{{ a.time }}</div>
                </div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="hk-empty"><i class="fas fa-wave-square"></i>No recent activity.</div>
        {% endif %}
      </div>
    </div>
    <div class="hk-c6">
      <div class="hk-card">
        <div class="hk-card-head">
          <h3><i class="fas fa-bell"></i> Notifications</h3>
          <a href="{{ url_for('notifications') }}" class="hk-link">View all</a>
        </div>
        {% if notifications_list and notifications_list|length > 0 %}
          <div class="hk-feed">
            {% for n in notifications_list %}
              <div class="hk-feed-item {% if not n.is_read %}unread{% endif %}">
                <div class="hk-feed-ic"><i class="fas fa-envelope"></i></div>
                <div class="hk-feed-b">
                  <div class="tx"><strong>{{ n.title }}</strong>{% if n.message %} — {{ n.message }}{% endif %}</div>
                  <div class="tm">{{ n.created_at.strftime('%b %d, %H:%M') if n.created_at else '' }}</div>
                </div>
              </div>
            {% endfor %}
          </div>
        {% else %}
          <div class="hk-empty"><i class="fas fa-bell"></i>No notifications yet.</div>
        {% endif %}
      </div>
    </div>
  </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>window.HK_DATA = {{ chart_data|tojson }};</script>
<script>
(function(){
  'use strict';
  if(typeof Chart==='undefined')return;
  var D=window.HK_DATA||{};
  Chart.defaults.color='#9CA3AF';
  Chart.defaults.borderColor='rgba(139,92,246,0.1)';
  Chart.defaults.font.family="'Inter', system-ui, sans-serif";
  Chart.defaults.font.size=10;
  var TT={backgroundColor:'rgba(10,10,26,0.97)',borderColor:'rgba(139,92,246,0.5)',borderWidth:1,titleColor:'#fff',bodyColor:'#e5e7eb',padding:11,cornerRadius:10};
  var P2='#A855F7',B='#38BDF8',PK='#EC4899',G='#22C55E';
  function gr(c,a,b){var g=c.createLinearGradient(0,0,0,300);g.addColorStop(0,a);g.addColorStop(1,b);return g;}
  function em(el,i,m){if(!el||!el.parentElement)return;el.parentElement.innerHTML='<div class="hk-empty"><i class="fas '+i+'"></i>'+m+'</div>';}

  (function(){var el=document.getElementById('chart-trends');if(!el)return;var x=D.trends;if(!x||!x.labels||!x.labels.length){em(el,'fa-chart-area','No data yet.');return;}
    var c=el.getContext('2d');
    new Chart(c,{type:'line',data:{labels:x.labels,datasets:[
      {label:'Total',data:x.total,borderColor:P2,borderWidth:2.5,fill:true,backgroundColor:gr(c,'rgba(139,92,246,0.35)','rgba(139,92,246,0.01)'),tension:0.45,pointRadius:0,pointHoverRadius:6},
      {label:'Completed',data:x.completed,borderColor:B,borderWidth:2.2,fill:true,backgroundColor:gr(c,'rgba(56,189,248,0.22)','rgba(56,189,248,0.01)'),tension:0.45,pointRadius:0,pointHoverRadius:5},
      {label:'Pending',data:x.pending,borderColor:PK,borderWidth:2,fill:false,tension:0.45,pointRadius:0,pointHoverRadius:5},
      {label:'In Progress',data:x.in_progress,borderColor:G,borderWidth:2,fill:false,tension:0.45,pointRadius:0,pointHoverRadius:5}
    ]},options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},
      plugins:{legend:{position:'top',align:'end',labels:{boxWidth:8,boxHeight:8,padding:14,usePointStyle:true,pointStyle:'circle',font:{size:10,weight:'600'}}},tooltip:TT},
      scales:{x:{grid:{color:'rgba(139,92,246,0.06)'},ticks:{maxRotation:0,autoSkip:true,maxTicksLimit:8}},y:{beginAtZero:true,grid:{color:'rgba(139,92,246,0.07)'},ticks:{precision:0}}}}});
  })();

  (function(){var el=document.getElementById('chart-status');if(!el)return;var x=D.statuses;if(!x||!x.labels||!x.labels.length){em(el,'fa-chart-pie','No status data.');return;}
    var m={'Pending':'#F59E0B','Approved':'#3B82F6','Assigned':'#8B5CF6','In Progress':'#38BDF8','Completed':'#22C55E','Verified':'#10B981','Closed':'#16A34A','Rejected':'#EF4444','Overdue':'#DC2626'};
    new Chart(el.getContext('2d'),{type:'doughnut',data:{labels:x.labels,datasets:[{data:x.values,backgroundColor:x.labels.map(function(l){return m[l]||'#9CA3AF';}),borderColor:'#14142a',borderWidth:3,hoverOffset:8}]},options:{responsive:true,maintainAspectRatio:false,cutout:'68%',plugins:{legend:{position:'bottom',labels:{boxWidth:8,boxHeight:8,padding:8,usePointStyle:true,pointStyle:'circle',font:{size:10,weight:'600'}}},tooltip:TT}}});
  })();

  (function(){var el=document.getElementById('chart-floors');if(!el)return;var x=D.floors;if(!x||!x.labels||!x.labels.length){em(el,'fa-building','No floor data.');return;}
    var c=el.getContext('2d');
    new Chart(c,{type:'bar',data:{labels:x.labels,datasets:[{label:'Requests',data:x.values,backgroundColor:gr(c,'rgba(139,92,246,0.95)','rgba(56,189,248,0.35)'),borderRadius:8,borderSkipped:false,maxBarThickness:32}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:TT},scales:{x:{grid:{display:false}},y:{beginAtZero:true,grid:{color:'rgba(139,92,246,0.07)'},ticks:{precision:0}}}}});
  })();

  (function(){var el=document.getElementById('chart-categories');if(!el)return;var x=D.categories;if(!x||!x.labels||!x.labels.length){em(el,'fa-chart-bar','No category data.');return;}
    var c=el.getContext('2d');
    new Chart(c,{type:'bar',data:{labels:x.labels,datasets:[{label:'Requests',data:x.values,backgroundColor:gr(c,'rgba(56,189,248,0.95)','rgba(139,92,246,0.4)'),borderRadius:8,borderSkipped:false,maxBarThickness:32}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:TT},scales:{x:{grid:{display:false},ticks:{maxRotation:45,font:{size:9}}},y:{beginAtZero:true,grid:{color:'rgba(139,92,246,0.07)'},ticks:{precision:0}}}}});
  })();

  (function(){var el=document.getElementById('chart-priorities');if(!el)return;var x=D.priorities;if(!x||!x.labels||!x.labels.length){em(el,'fa-fire','No priority data.');return;}
    var m={'URGENT':'#EF4444','HIGH':'#F59E0B','MEDIUM':'#38BDF8','LOW':'#22C55E'};
    new Chart(el.getContext('2d'),{type:'doughnut',data:{labels:x.labels,datasets:[{data:x.values,backgroundColor:x.labels.map(function(l){return m[l]||'#9CA3AF';}),borderColor:'#14142a',borderWidth:3,hoverOffset:8}]},options:{responsive:true,maintainAspectRatio:false,cutout:'68%',plugins:{legend:{position:'bottom',labels:{boxWidth:8,boxHeight:8,padding:8,usePointStyle:true,pointStyle:'circle',font:{size:10,weight:'600'}}},tooltip:TT}}});
  })();
})();
</script>
</body>
</html>"""


@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    if current_user.department_id:
        requests = MaintenanceRequest.query.filter(
            MaintenanceRequest.is_deleted == False,
            db.or_(
                MaintenanceRequest.department_id == current_user.department_id,
                MaintenanceRequest.requested_by_id == current_user.id
            )
        ).order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        requests = MaintenanceRequest.query.filter_by(
            is_deleted=False,
            requested_by_id=current_user.id
        ).order_by(MaintenanceRequest.created_at.desc()).all()

    total       = len(requests)
    pending     = sum(1 for r in requests if r.status == "Pending")
    approved    = sum(1 for r in requests if r.status in ["Approved", "Assigned"])
    in_progress = sum(1 for r in requests if r.status == "In Progress")
    completed   = sum(1 for r in requests if r.status == "Completed")
    verified    = sum(1 for r in requests if r.status == "Verified")
    closed      = sum(1 for r in requests if r.status == "Closed")
    rejected    = sum(1 for r in requests if r.status == "Rejected")
    overdue     = sum(1 for r in requests if r.is_overdue)

    flow = [
        ("Pending",     pending),
        ("Approved",    approved),
        ("In Progress", in_progress),
        ("Completed",   completed + verified),
        ("Closed",      closed),
        ("Rejected",    rejected),
    ]
    status_labels = [s[0] for s in flow if s[1] > 0]
    status_values = [s[1] for s in flow if s[1] > 0]

    cat_counts = defaultdict(int)
    for r in requests:
        cat_counts[r.category.name if r.category else "Uncategorized"] += 1
    cat_sorted = sorted(cat_counts.items(), key=lambda x: -x[1])
    category_labels = [k for k, _ in cat_sorted]
    category_values = [v for _, v in cat_sorted]

    floor_counts = defaultdict(int)
    for r in requests:
        floor_counts[r.floor if r.floor else 0] += 1
    floor_sorted = sorted(floor_counts.items())
    floor_labels = [f"Floor {f}" if f else "Unassigned" for f, _ in floor_sorted]
    floor_values = [v for _, v in floor_sorted]

    prio_counts = defaultdict(int)
    for r in requests:
        prio_counts[r.priority or "MEDIUM"] += 1
    prio_order = ["URGENT", "HIGH", "MEDIUM", "LOW"]
    priority_labels = [p for p in prio_order if prio_counts.get(p, 0) > 0]
    priority_values = [prio_counts[p] for p in priority_labels]

    loc_counts = defaultdict(int)
    for r in requests:
        loc_counts[r.location_name] += 1
    top_locations = sorted(loc_counts.items(), key=lambda x: -x[1])[:8]

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    trend_labels, trend_total, trend_completed, trend_pending, trend_inprogress = [], [], [], [], []
    for i in range(13, -1, -1):
        day      = today - timedelta(days=i)
        next_day = day + timedelta(days=1)
        trend_labels.append(day.strftime("%b %d"))
        day_reqs = [r for r in requests if r.created_at and day <= r.created_at < next_day]
        trend_total.append(len(day_reqs))
        trend_completed.append(sum(1 for r in day_reqs if r.status in ["Completed", "Verified", "Closed"]))
        trend_pending.append(sum(1 for r in day_reqs if r.status == "Pending"))
        trend_inprogress.append(sum(1 for r in day_reqs if r.status == "In Progress"))

    req_ids = [r.id for r in requests]
    activity = []
    if req_ids:
        history = StatusHistory.query.filter(
            StatusHistory.request_id.in_(req_ids)
        ).order_by(StatusHistory.timestamp.desc()).limit(8).all()
        for h in history:
            activity.append({
                "status": h.status or "",
                "notes":  h.notes or "",
                "user":   h.user.full_name if h.user else "System",
                "time":   h.timestamp.strftime("%b %d, %H:%M") if h.timestamp else "",
                "req_id": h.request_id,
            })

    work_orders = []
    if req_ids:
        work_orders = WorkOrder.query.filter(
            WorkOrder.request_id.in_(req_ids)
        ).order_by(WorkOrder.created_at.desc()).limit(5).all()

    notifications_list = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).limit(5).all()
    unread_count = Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).count()

    dept_name = current_user.department.name if current_user.department else "Housekeeping"

    chart_data = {
        "trends": {
            "labels":      trend_labels,
            "total":       trend_total,
            "completed":   trend_completed,
            "pending":     trend_pending,
            "in_progress": trend_inprogress,
        },
        "statuses":   {"labels": status_labels, "values": status_values},
        "categories": {"labels": category_labels, "values": category_values},
        "floors":     {"labels": floor_labels, "values": floor_values},
        "priorities": {"labels": priority_labels, "values": priority_values},
    }

    return render_template_string(
        HK_DASHBOARD_TEMPLATE,
        title="Housekeeping Dashboard",
        dept_name=dept_name,
        kpis={
            "total": total, "pending": pending, "approved": approved,
            "in_progress": in_progress, "completed": completed, "verified": verified,
            "closed": closed, "rejected": rejected, "overdue": overdue,
        },
        recent_requests=requests[:6],
        my_requests=requests[:5],
        top_locations=top_locations,
        activity=activity,
        work_orders=work_orders,
        notifications_list=notifications_list,
        unread_count=unread_count,
        chart_data=chart_data,
        nav_items=build_department_nav(),
        status_badge_class=status_badge_class,
        priority_badge_class=priority_badge_class,
    )


# ══════════════════════════════════════════════════════════════
# HOUSEKEEPING APPROVAL — embedded template
# ══════════════════════════════════════════════════════════════
HK_APPROVE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Housekeeping Approval | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:#0a0a1a;color:#fff;-webkit-font-smoothing:antialiased;font-size:13px;line-height:1.5;min-height:100vh;padding:1.25rem}
a{color:inherit;text-decoration:none}
button{font-family:inherit;cursor:pointer;border:none;background:none;color:inherit}
.wrap{max-width:1100px;margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1.25rem;flex-wrap:wrap}
.top h1{font-size:1.25rem;font-weight:800;color:#fff}
.top h1 span{background:linear-gradient(135deg,#A855F7,#38BDF8);-webkit-background-clip:text;background-clip:text;color:transparent}
.top p{font-size:.75rem;color:#9CA3AF;margin-top:.2rem}
.btn-back{padding:.5rem 1rem;border-radius:10px;background:transparent;border:1px solid rgba(139,92,246,0.2);color:#9CA3AF;font-size:.78rem;font-weight:600;display:inline-flex;align-items:center;gap:.4rem}
.btn-back:hover{color:#fff;border-color:#A855F7}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem;margin-bottom:1.25rem}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.card{background:#14142a;border:1px solid rgba(139,92,246,0.15);border-radius:18px;padding:1.25rem}
.card h3{font-size:.9rem;font-weight:700;color:#fff;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
.card h3 i{color:#A855F7}
.card table{width:100%;font-size:.82rem;border-collapse:collapse}
.card table th{text-align:left;color:#9CA3AF;font-weight:600;padding:.45rem .25rem;width:140px;vertical-align:top}
.card table td{padding:.45rem .25rem;color:#e5e7eb;border-bottom:1px solid rgba(139,92,246,0.06)}
.card table tr:last-child td{border-bottom:none}
.alert{padding:.75rem 1rem;border-radius:12px;font-size:.8rem;margin-bottom:1rem;border:1px solid}
.alert-danger{background:rgba(239,68,68,0.08);border-color:rgba(239,68,68,0.4);color:#fca5a5}
.alert-info{background:rgba(56,189,248,0.08);border-color:rgba(56,189,248,0.4);color:#7dd3fc}
.signer{background:rgba(139,92,246,0.06);border:1px solid rgba(139,92,246,0.35);border-radius:12px;padding:.85rem 1rem;margin-bottom:1rem}
.signer .lbl{font-size:.6rem;color:#9CA3AF;text-transform:uppercase;letter-spacing:.7px;font-weight:700}
.signer .val{font-size:.95rem;font-weight:700;color:#fff;margin-top:.2rem}
.signer .role{font-size:.72rem;color:#A855F7;font-weight:600;margin-top:.15rem}
.sig-wrap{position:relative;background:#fff;border-radius:12px;overflow:hidden;margin-bottom:.5rem;border:2px dashed rgba(139,92,246,0.4)}
canvas#signature-pad{display:block;width:100%;height:200px;touch-action:none;background:#fff;cursor:crosshair}
.sig-hint{font-size:.7rem;color:#9CA3AF;text-align:center;margin-bottom:1rem}
textarea{width:100%;background:#0f0f22;border:1px solid rgba(139,92,246,0.2);color:#fff;border-radius:10px;padding:.65rem .85rem;font-size:.82rem;font-family:inherit;resize:vertical;min-height:70px;outline:none}
textarea:focus{border-color:#A855F7;box-shadow:0 0 0 3px rgba(139,92,246,0.12)}
.actions{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:1rem}
.btn{flex:1;padding:.75rem 1.25rem;border-radius:12px;font-size:.85rem;font-weight:700;border:none;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;gap:.4rem;font-family:inherit}
.btn-approve{background:linear-gradient(135deg,#8B5CF6,#A855F7);color:#fff;box-shadow:0 4px 20px rgba(139,92,246,0.4)}
.btn-approve:hover{box-shadow:0 6px 28px rgba(139,92,246,0.6)}
.btn-reject{background:rgba(239,68,68,0.15);color:#EF4444;border:1px solid rgba(239,68,68,0.4)}
.btn-reject:hover{background:rgba(239,68,68,0.25)}
.btn-clear{padding:.5rem .9rem;border-radius:9px;background:transparent;border:1px solid rgba(139,92,246,0.2);color:#9CA3AF;font-size:.75rem;font-weight:600;cursor:pointer}
.btn-clear:hover{color:#fff;border-color:#A855F7}
</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div>
      <h1>Housekeeping <span>Approval</span></h1>
      <p>Review and sign the maintenance request before submitting to Maintenance Manager.</p>
    </div>
    <a href="{{ url_for('request_detail', req_id=req.id) }}" class="btn-back">
      <i class="fas fa-arrow-left"></i> Back to Request
    </a>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'danger' if cat == 'danger' else 'info' }}">{{ msg }}</div>
      {% endfor %}
    {% endif %}
  {% endwith %}

  <div class="grid">

    <div class="card">
      <h3><i class="fas fa-clipboard-list"></i> Request Details</h3>
      <table>
        <tr><th>Request No.</th><td><strong style="color:#A855F7">{{ req.request_no }}</strong></td></tr>
        <tr><th>Department</th><td>{{ req.department.name if req.department else '—' }}</td></tr>
        <tr><th>Location</th><td>{{ req.location_name }}</td></tr>
        <tr><th>Item</th><td>{{ req.working_item.name if req.working_item else '—' }}</td></tr>
        <tr><th>Category</th><td>{{ req.category.name if req.category else '—' }}</td></tr>
        <tr><th>Priority</th><td>{{ req.priority }}</td></tr>
        <tr><th>Requested by</th><td>{{ req.requested_by.full_name if req.requested_by else '—' }}</td></tr>
        <tr><th>Created</th><td>{{ req.created_at.strftime('%b %d, %Y · %H:%M') if req.created_at else '—' }}</td></tr>
        <tr><th>Description</th><td>{{ req.description or '—' }}</td></tr>
      </table>
    </div>

    <div class="card">
      <h3><i class="fas fa-pen-nib"></i> Approval &amp; Signature</h3>

      <div class="signer">
        <div class="lbl">Approver (you)</div>
        <div class="val">{{ current_user.full_name or current_user.username }}</div>
        <div class="role">{{ current_user.role }} · {{ current_user.department.name if current_user.department else 'Housekeeping' }}</div>
      </div>

      <div class="alert alert-info" style="font-size:.75rem">
        <i class="fas fa-info-circle"></i>
        Sign below using your mouse, touchscreen or stylus. Your signature will be attached to this request.
      </div>

      <form method="post" id="approve-form">
        <input type="hidden" name="signature_data" id="signature_data">
        <input type="hidden" name="action" id="action_field" value="approve">

        <label style="font-size:.75rem;color:#9CA3AF;font-weight:600;display:block;margin-bottom:.35rem">
          Digital Signature <span style="color:#EF4444">*</span>
        </label>
        <div class="sig-wrap">
          <canvas id="signature-pad"></canvas>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.85rem">
          <span class="sig-hint">Sign inside the box above.</span>
          <button type="button" class="btn-clear" id="clear-sig"><i class="fas fa-eraser"></i> Clear</button>
        </div>

        <label style="font-size:.75rem;color:#9CA3AF;font-weight:600;display:block;margin-bottom:.35rem">
          Notes (optional)
        </label>
        <textarea name="notes" placeholder="Optional remarks…"></textarea>

        <div class="actions">
          <button type="submit" class="btn btn-approve" id="btn-approve">
            <i class="fas fa-check-circle"></i> Approve &amp; Submit
          </button>
          <button type="submit" class="btn btn-reject" id="btn-reject">
            <i class="fas fa-times-circle"></i> Reject
          </button>
        </div>
      </form>
    </div>

  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.7/dist/signature_pad.umd.min.js"></script>
<script>
(function(){
  'use strict';
  var canvas = document.getElementById('signature-pad');
  if (!canvas || typeof SignaturePad === 'undefined') return;

  var signaturePad = new SignaturePad(canvas, {
    backgroundColor: 'rgb(255,255,255)',
    penColor: 'rgb(0,0,0)',
    minWidth: 1,
    maxWidth: 3
  });

  function resizeCanvas() {
    var ratio = Math.max(window.devicePixelRatio || 1, 1);
    var data = signaturePad.toData();
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    canvas.getContext('2d').scale(ratio, ratio);
    signaturePad.clear();
    if (data && data.length) signaturePad.fromData(data);
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  document.getElementById('clear-sig').addEventListener('click', function(){
    signaturePad.clear();
  });

  var form = document.getElementById('approve-form');
  var sigField = document.getElementById('signature_data');
  var actionField = document.getElementById('action_field');

  document.getElementById('btn-approve').addEventListener('click', function(e){
    actionField.value = 'approve';
    if (signaturePad.isEmpty()) {
      e.preventDefault();
      alert('Please sign before approving.');
      return;
    }
    sigField.value = signaturePad.toDataURL('image/png');
  });

  document.getElementById('btn-reject').addEventListener('click', function(e){
    actionField.value = 'reject';
    var notes = form.querySelector('textarea[name="notes"]').value.trim();
    if (!notes) {
      e.preventDefault();
      alert('Please write a reason for rejection.');
      return;
    }
    sigField.value = signaturePad.isEmpty() ? '' : signaturePad.toDataURL('image/png');
  });

  form.addEventListener('submit', function(e){
    if (actionField.value === 'approve') {
      if (signaturePad.isEmpty()) {
        e.preventDefault();
        alert('Please sign before approving.');
        return false;
      }
      sigField.value = signaturePad.toDataURL('image/png');
    }
  });
})();
</script>
</body>
</html>"""


@app.route("/requests/<int:req_id>/hk-approve", methods=["GET", "POST"])
@login_required
def hk_approve_request(req_id):
    if not is_housekeeping_approver(current_user):
        abort(403)

    req = get_or_404(MaintenanceRequest, req_id)

    if not req.awaiting_hk_approval:
        flash("This request is not awaiting Housekeeping approval.", "warning")
        return redirect(url_for("request_detail", req_id=req_id))

    if request.method == "POST":
        action = request.form.get("action", "approve")
        signature = request.form.get("signature_data", "").strip()
        notes = request.form.get("notes", "").strip()

        if action == "approve":
            if not signature or not signature.startswith("data:image/"):
                flash("A digital signature is required to approve.", "danger")
                return redirect(url_for("hk_approve_request", req_id=req_id))

            req.hk_approved_by_id = current_user.id
            req.hk_approved_at = datetime.utcnow()
            req.hk_approval_status = "Approved"
            req.hk_signature_data = signature
            req.hk_approval_notes = notes or "Approved by Housekeeping"
            req.awaiting_hk_approval = False

            log_status_change(req.id, "HK Approved", notes="Approved by " + str(current_user.full_name))
            log_audit("HK Approve", "MaintenanceRequest", req.id, "awaiting", "approved")
            log_audit("Submitted to Maintenance Manager", "MaintenanceRequest", req.id, new_value=req.request_no)

            managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
            notify_users(
                [u.id for u in managers], req.id,
                "📬 HK Approved Request",
                "Request " + str(req.request_no) + " approved by Housekeeping and sent to Maintenance Manager",
                "New Request",
                link=url_for("request_detail", req_id=req.id)
            )
            notify_users(
                [req.requested_by_id], req.id,
                "✅ Approved by Housekeeping",
                "Your request " + str(req.request_no) + " was approved by Housekeeping",
                "HK Approved",
                link=url_for("request_detail", req_id=req.id)
            )

            db.session.commit()
            flash("✅ Approved and submitted to Maintenance Manager.", "success")
            return redirect(url_for("request_detail", req_id=req_id))

        elif action == "reject":
            req.hk_approved_by_id = current_user.id
            req.hk_approved_at = datetime.utcnow()
            req.hk_approval_status = "Rejected"
            req.hk_approval_notes = notes or "Rejected by Housekeeping"
            req.awaiting_hk_approval = False
            req.status = "Rejected"

            log_status_change(req.id, "HK Rejected",
                              notes="Rejected by " + str(current_user.full_name) + ": " + req.hk_approval_notes)
            log_audit("HK Reject", "MaintenanceRequest", req.id, "awaiting", "rejected")

            notify_users(
                [req.requested_by_id], req.id,
                "❌ Rejected by Housekeeping",
                "Your request " + str(req.request_no) + " was rejected: " + req.hk_approval_notes,
                "HK Rejected",
                link=url_for("request_detail", req_id=req_id)
            )

            db.session.commit()
            flash("Request rejected.", "warning")
            return redirect(url_for("request_detail", req_id=req_id))

    return render_template_string(
        HK_APPROVE_TEMPLATE,
        req=req,
        title="Housekeeping Approval",
    )


@app.route("/requests/<int:req_id>/approve", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.awaiting_hk_approval:
            flash("This request must be approved by Housekeeping first.", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        if req.hk_approval_status == "Rejected":
            flash("This request was rejected by Housekeeping.", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        if req.status != "Pending":
            flash("Not pending", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Approved"
        req.manager_id = current_user.id
        log_status_change(req.id, "Approved", notes="Approved by " + str(current_user.full_name))
        log_audit("Approve", "MaintenanceRequest", req.id, "Pending", "Approved")
        existing = WorkOrder.query.filter_by(request_id=req.id).first()
        if not existing:
            wo = WorkOrder(work_order_no=work_order_no_generator(), request_id=req.id, assigned_to_id=None, status="Pending")
            db.session.add(wo)
            db.session.flush()
            log_audit("Create", "WorkOrder", wo.id, new_value=wo.work_order_no)
            log_status_change(req.id, "WO Created", notes="WO " + str(wo.work_order_no))
            notify_maintenance_staff(req, wo)
        notify_users([req.requested_by_id], req.id, "Request Approved", "Request " + str(req.request_no) + " approved", "Approved", link=url_for("request_detail", req_id=req.id))
        db.session.commit()
        flash("✅ Request approved!", "success")
    except Exception as e:
        db.session.rollback()
        print("Approve error: " + traceback.format_exc())
        flash("Error: " + str(e), "danger")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/verify", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_verify(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Completed":
            flash("Only completed can be verified (current: " + str(req.status) + ")", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Verified"
        req.manager_id = current_user.id
        if not req.completed_date:
            req.completed_date = datetime.utcnow()
        wo = WorkOrder.query.filter_by(request_id=req.id).first()
        if wo:
            wo.status = "Verified"
            wo.verified_by_id = current_user.id
            wo.verified_date = datetime.utcnow()
        log_status_change(req.id, "Verified", notes="Verified by " + str(current_user.full_name))
        log_audit("Verify", "MaintenanceRequest", req.id, "Completed", "Verified")
        notify_users([req.requested_by_id], req.id, "✅ Work Verified", "Request " + str(req.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=req.id))
        if req.department_id:
            dept_users = User.query.filter_by(department_id=req.department_id).all()
            notify_users([u.id for u in dept_users if u.id != req.requested_by_id], req.id, "Department Request Verified", "Request " + str(req.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=req.id))
        db.session.commit()
        flash("✅ Work verified successfully!", "success")
    except Exception as e:
        db.session.rollback()
        print("Verify error: " + traceback.format_exc())
        flash("Error: " + str(e), "danger")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/close", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_close(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Verified":
            flash("Only verified can be closed", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Closed"
        log_status_change(req.id, "Closed", notes="Closed by " + str(current_user.full_name))
        log_audit("Close", "MaintenanceRequest", req.id, "Verified", "Closed")
        notify_users([req.requested_by_id], req.id, "Request Closed", "Request " + str(req.request_no) + " closed", "Closed")
        db.session.commit()
        flash("Request closed", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/delete", methods=["POST"])
@role_required("ADMIN")
def request_delete(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.is_deleted:
            flash("Already deleted", "warning")
            return redirect(url_for("request_detail", req_id=req_id))
        req.is_deleted = True
        req.deleted_at = datetime.utcnow()
        req.deleted_by_id = current_user.id
        req.deletion_reason = request.form.get("reason", "Deleted by admin")
        log_audit("SoftDelete", "MaintenanceRequest", req.id, "active", "deleted")
        db.session.commit()
        flash("Request archived", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("requests_list"))


@app.route("/admin/deleted")
@role_required("ADMIN")
def deleted_requests():
    deleted = MaintenanceRequest.query.filter_by(is_deleted=True).order_by(MaintenanceRequest.deleted_at.desc()).all()
    rows_parts = []
    for r in deleted:
        restore_url = url_for("request_restore", req_id=r.id)
        rows_parts.append(
            '<tr><td>' + str(r.request_no) + '</td><td>' + str(r.location_name) + '</td>'
            '<td>' + str(r.status) + '</td>'
            '<td>' + (r.deleted_at.strftime("%Y-%m-%d %H:%M") if r.deleted_at else "") + '</td>'
            '<td>' + str(r.deleted_by.full_name if r.deleted_by else "—") + '</td>'
            '<td>' + str(r.deletion_reason or "—") + '</td>'
            '<td><form method="post" action="' + restore_url + '"><button type="submit" class="btn btn-sm btn-success"><i class="fas fa-undo"></i> Restore</button></form></td></tr>'
        )
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b">🗑️ Archived Requests</h3>'
        '<p style="color:#94a3b8">Soft-deleted (Admin only)</p>'
        '<div class="card"><div class="table-responsive"><table class="table table-hover">'
        '<thead><tr><th>Request #</th><th>Location</th><th>Status</th><th>Deleted At</th><th>Deleted By</th><th>Reason</th><th></th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="7" class="text-center">No archived requests</td></tr>') + '</tbody>'
        '</table></div></div>')
    return page("Archived Requests", content)


@app.route("/admin/restore/<int:req_id>", methods=["POST"])
@role_required("ADMIN")
def request_restore(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        req.is_deleted = False
        req.deleted_at = None
        req.deleted_by_id = None
        req.deletion_reason = None
        log_audit("Restore", "MaintenanceRequest", req.id, "deleted", "active")
        db.session.commit()
        flash("Request restored", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("deleted_requests"))


# ══════════════════════════════════════════════════════════════
# WORK ORDERS
# ══════════════════════════════════════════════════════════════
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "DEPARTMENT":
        return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE":
        return redirect(url_for("employee_dashboard"))

    if current_user.role in STAFF_ROLES:
        wos = WorkOrder.query.filter(db.or_(WorkOrder.assigned_to_id == current_user.id, WorkOrder.assigned_to_id.is_(None))).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()

    rows_parts = []
    for wo in wos:
        assigned = wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"
        if wo.status in ["Completed", "Verified"]:
            badge = "success"
        elif wo.status in ["Pending", "Assigned"]:
            badge = "warning"
        else:
            badge = "info"
        rows_parts.append(
            '<tr><td><a href="/workorders/' + str(wo.id) + '" style="color:#f59e0b">' + str(wo.work_order_no) + '</a></td>'
            '<td>' + str(wo.request.location_name if wo.request else "—") + '</td>'
            '<td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td>'
            '<td>' + str(wo.request.priority if wo.request else "—") + '</td>'
            '<td><span class="badge bg-' + badge + '">' + str(wo.status) + '</span></td>'
            '<td>' + str(assigned) + '</td></tr>'
        )
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b"><i class="fas fa-clipboard-list"></i> Work Orders</h3>'
        '<div class="card"><div class="table-responsive"><table class="table table-hover">'
        '<thead><tr><th>Order #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Assigned</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="6" class="text-center">No work orders</td></tr>') + '</tbody>'
        '</table></div></div>')
    return page("Work Orders", content)


@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = get_one(MaintenanceRequest, req_id) if req_id else None
    users = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    user_opts = "".join('<option value="' + str(u.id) + '">' + str(u.full_name) + ' (' + str(u.role) + ')</option>' for u in users)

    if request.method == "POST":
        try:
            request_id = request.form.get("request_id", type=int)
            assigned_to_id = request.form.get("assigned_to_id", type=int)
            work_performed = request.form.get("work_performed", "")
            if not assigned_to_id:
                flash("Select staff", "danger")
                return redirect(url_for("workorder_create", request_id=request_id))
            req = get_or_404(MaintenanceRequest, request_id)
            if req.awaiting_hk_approval:
                flash("Awaiting Housekeeping approval first.", "warning")
                return redirect(url_for("request_detail", req_id=request_id))
            if req.status not in ["Approved", "Assigned"]:
                flash("Request must be approved", "danger")
                return redirect(url_for("request_detail", req_id=request_id))
            assigned_user = get_one(User, assigned_to_id)
            existing = WorkOrder.query.filter_by(request_id=req.id).filter(WorkOrder.status != "Completed").first()
            if existing:
                wo = existing
                wo.assigned_to_id = assigned_to_id
                wo.status = "Assigned"
                if work_performed:
                    wo.work_performed = work_performed
            else:
                wo = WorkOrder(work_order_no=work_order_no_generator(), request_id=req.id, assigned_to_id=assigned_to_id, status="Assigned", work_performed=work_performed)
                db.session.add(wo)
                db.session.flush()
                log_audit("Create", "WorkOrder", wo.id, new_value=wo.work_order_no)
            req.status = "Assigned"
            req.assigned_to_id = assigned_to_id
            log_status_change(req.id, "Assigned", notes="Assigned to " + str(assigned_user.full_name if assigned_user else "?"))
            if assigned_user:
                notify_assigned_staff(req, wo, assigned_user)
            if req.requested_by_id:
                notify_users([req.requested_by_id], req.id, "Work Assigned", "Staff assigned to " + str(req.request_no), "Assigned", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit()
            flash("✅ Assigned!", "success")
            return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e:
            db.session.rollback()
            print("WO assign: " + traceback.format_exc())
            flash("Error: " + str(e), "danger")
            return redirect(url_for("workorder_create", request_id=request_id))

    content = ('<h3 style="color:#f59e0b">Assign Staff to Work Order</h3>'
        '<div class="card"><form method="post">'
        '<input type="hidden" name="request_id" value="' + str(req.id if req else "") + '">'
        '<div class="mb-3"><label class="form-label">Request</label><input class="form-control" value="' + str(req.request_no if req else "") + '" disabled></div>'
        '<div class="mb-3"><label class="form-label">Location</label><input class="form-control" value="' + str(req.location_name if req else "") + '" disabled></div>'
        '<div class="mb-3"><label class="form-label">Assign To *</label><select class="form-select" name="assigned_to_id" required><option value="">-- Select --</option>' + user_opts + '</select></div>'
        '<div class="mb-3"><label class="form-label">Instructions</label><textarea class="form-control" name="work_performed" rows="3"></textarea></div>'
        '<button class="btn btn-primary"><i class="fas fa-save"></i> Assign</button>'
        '</form></div>')
    return page("Assign Work Order", content)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    can_manage_parts = (current_user.role in ["MANAGER", "ADMIN"] or
                        (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))
    parts_rows_parts = []
    parts_total = 0
    for p in parts:
        pname = p.part.part_name if p.part else ("Part #" + str(p.part_id))
        psupplier = p.part.supplier.company_name if p.part and p.part.supplier else "\u2014"
        punit = p.part.unit if p.part else "pcs"
        line_total = (p.quantity or 0) * (p.unit_cost or 0)
        parts_total += line_total
        remove_btn = ""
        if can_manage_parts and wo.status in ["Assigned", "In Progress"]:
            remove_btn = ('<form method="post" action="' + url_for("workorder_part_remove", wo_id=wo.id, part_id=p.id) + '" style="display:inline" onsubmit="return confirm(&#39;Remove this part? Stock will be restored.&#39;)">'
                '<button type="submit" class="btn btn-sm btn-danger"><i class="fas fa-times"></i> Remove</button></form>')
        parts_rows_parts.append(
            '<tr><td>' + str(pname) + '</td>'
            '<td>' + str(psupplier) + '</td>'
            '<td>' + str(p.quantity) + '</td>'
            '<td>' + str(punit) + '</td>'
            '<td>' + str(p.unit_cost or 0) + '</td>'
            '<td>' + str(line_total) + '</td>'
            '<td>' + remove_btn + '</td></tr>'
        )
    parts_rows = "".join(parts_rows_parts)
    add_part_btn = ""
    if can_manage_parts and wo.status in ["Assigned", "In Progress"]:
        add_part_btn = '<a class="btn btn-sm btn-primary" href="' + url_for("workorder_part_add", wo_id=wo.id) + '"><i class="fas fa-plus"></i> Add Part</a>'
    parts_card = ('<div class="card"><div class="d-flex justify-content-between align-items-center mb-2">'
        '<h5 style="color:#f59e0b" class="mb-0"><i class="fas fa-boxes"></i> Inventory / Parts</h5>'
        + add_part_btn +
        '</div><div class="table-responsive"><table class="table">'
        '<thead><tr><th>Part</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Unit Cost</th><th>Total</th><th></th></tr></thead>'
        '<tbody>' + (parts_rows if parts_rows else '<tr><td colspan="7" class="text-center" style="color:#94a3b8">No parts</td></tr>') + '</tbody>'
        '</table></div>'
        '<p class="text-end mb-0"><b>Total: ' + str(parts_total) + '</b></p></div>')

    completion_html = ""
    if wo.completion_photo:
        photo_url = "/static/uploads/maintenance/" + str(wo.completion_photo)
        completion_html = ('<div class="mt-3"><h6>📸 Completion Photo:</h6>'
            '<a href="' + photo_url + '" target="_blank">'
            '<img src="' + photo_url + '" class="img-fluid rounded" style="max-height:250px"></a></div>')

    actions = ""
    if current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id:
        if wo.status == "Assigned":
            start_url = url_for("workorder_start", wo_id=wo.id)
            actions += ('<form method="post" action="' + start_url + '">'
                '<button type="submit" class="btn btn-warning mb-2 w-100">'
                '<i class="fas fa-play"></i> Start Work</button></form>')
        if wo.status == "In Progress":
            complete_url = url_for("workorder_complete", wo_id=wo.id)
            actions += ('<a href="' + complete_url + '" class="btn btn-success mb-2 w-100">'
                '<i class="fas fa-check"></i> Complete Work</a>')

    if current_user.role in ["MANAGER", "ADMIN"] and wo.status == "Completed":
        verify_url = url_for("workorder_verify", wo_id=wo.id)
        actions += ('<form method="post" action="' + verify_url + '">'
            '<button type="submit" class="btn btn-info mb-2 w-100">'
            '<i class="fas fa-check-double"></i> ✅ Verify</button></form>')

    back_url = url_for("workorders_list")
    content = ('<div class="d-flex justify-content-between mb-3">'
        '<h3 style="color:#f59e0b">🔧 Work Order ' + str(wo.work_order_no) + '</h3>'
        '<a href="' + back_url + '" class="btn btn-secondary btn-sm">'
        '<i class="fas fa-arrow-left"></i> Back</a></div>'
        '<div class="row"><div class="col-md-8"><div class="card"><table class="table">'
        '<tr><th style="width:150px;color:#94a3b8">Request</th><td>' + str(wo.request.request_no if wo.request else "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Location</th><td>' + str(wo.request.location_name if wo.request else "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Item</th><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Priority</th><td>' + str(wo.request.priority if wo.request else "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Status</th><td><span class="badge bg-info">' + str(wo.status) + '</span></td></tr>'
        '<tr><th style="color:#94a3b8">Assigned To</th><td>' + str(wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Instructions</th><td>' + str(wo.work_performed or "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Completion Notes</th><td>' + str(wo.completion_notes or "—") + '</td></tr>'
        '<tr><th style="color:#94a3b8">Labor Hours</th><td>' + str(wo.labor_hours) + '</td></tr>'
        '</table>' + completion_html + '</div>' + parts_card + '</div>'
        '<div class="col-md-4"><div class="card"><h5 style="color:#f59e0b">Actions</h5>'
        + (actions if actions else "<p style='color:#94a3b8'>No actions</p>") +
        '</div></div></div>')
    return page("Work Order Detail", content)


@app.route("/workorders/<int:wo_id>/start", methods=["POST"])
@login_required
def workorder_start(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if current_user.id != wo.assigned_to_id:
            flash("Not authorized", "danger")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        if wo.status != "Assigned":
            flash("Cannot start", "warning")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "In Progress"
        if wo.request:
            wo.request.status = "In Progress"
        log_status_change(wo.request_id, "In Progress", notes="Started by " + str(current_user.full_name))
        log_audit("Start", "WorkOrder", wo.id, "Assigned", "In Progress")
        db.session.commit()
        flash("Work started", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))


@app.route("/workorders/<int:wo_id>/complete", methods=["GET", "POST"])
@role_required(*STAFF_ROLES)
def workorder_complete(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if current_user.id != wo.assigned_to_id:
        flash("Not authorized", "danger")
        return redirect(url_for("workorder_detail", wo_id=wo_id))
    if wo.status != "In Progress":
        flash("Not in progress", "warning")
        return redirect(url_for("workorder_detail", wo_id=wo_id))

    if request.method == "POST":
        try:
            note = request.form.get("completion_note", "").strip()
            hours_str = request.form.get("labor_hours", "0") or "0"
            try:
                hours = float(hours_str)
            except:
                hours = 0.0
            if not note:
                flash("Completion note required", "danger")
                return redirect(url_for("workorder_complete", wo_id=wo_id))
            filename = None
            file = request.files.get("photo")
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = secure_filename("wo_" + str(wo.id) + "_done_" + datetime.now().strftime("%Y%m%d%H%M%S") + "." + ext)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            wo.completion_notes = note
            wo.labor_hours = hours
            wo.status = "Completed"
            wo.completed_by_id = current_user.id
            wo.completed_date = datetime.utcnow()
            if filename:
                wo.completion_photo = filename
            if wo.request:
                wo.request.status = "Completed"
                wo.request.completed_date = datetime.utcnow()
                wo.request.completion_note = note
            log_status_change(wo.request_id, "Completed", notes="Completed by " + str(current_user.full_name))
            log_audit("Complete", "WorkOrder", wo.id, "In Progress", "Completed")
            managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
            notify_users([u.id for u in managers], wo.request_id, "🔔 Work Completed", "WO " + str(wo.work_order_no) + " ready for verification", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            if wo.request and wo.request.requested_by_id:
                notify_users([wo.request.requested_by_id], wo.request_id, "Work Completed", "Your request " + str(wo.request.request_no) + " completed", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit()
            flash("✅ Work completed! Waiting for verification.", "success")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        except Exception as e:
            db.session.rollback()
            print("Complete: " + traceback.format_exc())
            flash("Error: " + str(e), "danger")
            return redirect(url_for("workorder_complete", wo_id=wo_id))

    content = ('<h3 style="color:#f59e0b">Complete Work Order ' + str(wo.work_order_no) + '</h3>'
        '<div class="card"><form method="post" enctype="multipart/form-data">'
        '<div class="mb-3"><label class="form-label">Completion Note *</label><textarea name="completion_note" class="form-control" rows="4" required></textarea></div>'
        '<div class="mb-3"><label class="form-label">Photo</label><input type="file" name="photo" accept="image/*" capture="environment" class="form-control"></div>'
        '<div class="mb-3"><label class="form-label">Labor Hours</label><input type="number" step="0.5" name="labor_hours" class="form-control" value="0"></div>'
        '<button class="btn btn-success btn-lg w-100"><i class="fas fa-check-circle"></i> Complete</button>'
        '</form></div>')
    return page("Complete Work Order", content)


@app.route("/workorders/<int:wo_id>/verify", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def workorder_verify(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if wo.status != "Completed":
            flash("Only completed can be verified", "warning")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "Verified"
        wo.verified_by_id = current_user.id
        wo.verified_date = datetime.utcnow()
        if wo.request:
            wo.request.status = "Verified"
            wo.request.manager_id = current_user.id
            if not wo.request.completed_date:
                wo.request.completed_date = datetime.utcnow()
        log_status_change(wo.request_id, "Verified", notes="Verified by " + str(current_user.full_name))
        log_audit("Verify", "WorkOrder", wo.id, "Completed", "Verified")
        if wo.request:
            notify_users([wo.request.requested_by_id], wo.request_id, "✅ Verified", str(wo.request.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=wo.request_id))
            if wo.request.department_id:
                dept_users = User.query.filter_by(department_id=wo.request.department_id).all()
                notify_users([u.id for u in dept_users if u.id != wo.request.requested_by_id], wo.request_id, "Dept Verified", str(wo.request.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=wo.request_id))
        db.session.commit()
        flash("✅ Verified!", "success")
    except Exception as e:
        db.session.rollback()
        print("WO verify: " + traceback.format_exc())
        flash("Error: " + str(e), "danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))


# ══════════════════════════════════════════════════════════════
# SUPPLIERS
# ══════════════════════════════════════════════════════════════
def supplier_is_active(s):
    if s is None:
        return True
    if s.is_active is not None:
        return s.is_active
    return s.status == "Active"


def supplier_form_html(supplier, action_url, is_edit):
    def v(field):
        return str(getattr(supplier, field) or "") if supplier else ""
    active = supplier_is_active(supplier)
    active_sel = " selected" if active else ""
    inactive_sel = "" if active else " selected"
    title = "Edit Supplier" if is_edit else "Add Supplier"
    return ('<h3 style="color:#f59e0b"><i class="fas fa-truck"></i> ' + title + '</h3>'
        '<div class="card"><form method="post" action="' + str(action_url) + '"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Supplier Name *</label><input type="text" class="form-control" name="company_name" value="' + v("company_name") + '" required></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Contact Person</label><input type="text" class="form-control" name="contact_person" value="' + v("contact_person") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + v("phone") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + v("email") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Address</label><input type="text" class="form-control" name="address" value="' + v("address") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Tax Number</label><input type="text" class="form-control" name="tax_number" value="' + v("tax_number") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + active_sel + '>Active</option><option value="Inactive"' + inactive_sel + '>Inactive</option></select></div>'
        '<div class="col-12 mb-3"><label class="form-label">Notes</label><textarea class="form-control" name="notes" rows="3">' + v("notes") + '</textarea></div>'
        '<div class="col-12 d-flex gap-2">'
        '<a href="' + url_for("suppliers_list") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
        '<button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Supplier</button>'
        '</div></div></form></div>')


@app.route("/suppliers")
@role_required("ADMIN", "MANAGER")
def suppliers_list():
    suppliers = Supplier.query.order_by(Supplier.company_name).all()
    rows_parts = []
    for s in suppliers:
        active = supplier_is_active(s)
        badge = '<span class="badge bg-success">Active</span>' if active else '<span class="badge bg-secondary">Inactive</span>'
        actions = '<a class="btn btn-sm btn-info" href="' + url_for("supplier_edit", supplier_id=s.id) + '"><i class="fas fa-edit"></i> Edit</a> '
        if active:
            actions += ('<form method="post" action="' + url_for("supplier_deactivate", supplier_id=s.id) + '" style="display:inline" onsubmit="return confirm(&#39;Deactivate this supplier?&#39;)">'
                '<button type="submit" class="btn btn-sm btn-warning"><i class="fas fa-ban"></i> Deactivate</button></form>')
        rows_parts.append(
            '<tr><td>' + str(s.id) + '</td>'
            '<td>' + str(s.company_name) + '</td>'
            '<td>' + str(s.contact_person or "\u2014") + '</td>'
            '<td>' + str(s.phone or "\u2014") + '</td>'
            '<td>' + str(s.email or "\u2014") + '</td>'
            '<td>' + str(s.address or "\u2014") + '</td>'
            '<td>' + badge + '</td>'
            '<td>' + actions + '</td></tr>'
        )
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b"><i class="fas fa-truck"></i> Suppliers</h3>'
        '<a class="btn btn-primary mb-3" href="' + url_for("supplier_add") + '"><i class="fas fa-plus-circle"></i> Add Supplier</a>'
        '<div class="card"><div class="table-responsive"><table class="table table-hover">'
        '<thead><tr><th>ID</th><th>Supplier Name</th><th>Contact Person</th><th>Phone</th><th>Email</th><th>Address</th><th>Status</th><th>Actions</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="8" class="text-center">No suppliers yet</td></tr>') + '</tbody>'
        '</table></div></div>')
    return page("Suppliers", content)


@app.route("/suppliers/add", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def supplier_add():
    if request.method == "POST":
        name = request.form.get("company_name", "").strip()
        email = request.form.get("email", "").strip()
        if not name:
            flash("Supplier name is required", "danger")
            return page("Add Supplier", supplier_form_html(None, url_for("supplier_add"), False))
        if email and not valid_email(email):
            flash("Invalid email address", "danger")
            return page("Add Supplier", supplier_form_html(None, url_for("supplier_add"), False))
        if Supplier.query.filter_by(company_name=name).first():
            flash("A supplier with this name already exists", "warning")
            return page("Add Supplier", supplier_form_html(None, url_for("supplier_add"), False))
        try:
            status = request.form.get("status", "Active")
            s = Supplier(
                company_name=name,
                contact_person=request.form.get("contact_person", "").strip(),
                phone=request.form.get("phone", "").strip(),
                email=email,
                address=request.form.get("address", "").strip(),
                tax_number=request.form.get("tax_number", "").strip(),
                notes=request.form.get("notes", "").strip(),
                status=status,
                is_active=(status == "Active"),
            )
            db.session.add(s)
            db.session.flush()
            log_audit("Supplier Created", "Supplier", s.id, new_value=name)
            db.session.commit()
            flash("\u2705 Supplier saved", "success")
            return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.session.rollback()
            flash("Error: " + str(e), "danger")
    return page("Add Supplier", supplier_form_html(None, url_for("supplier_add"), False))


@app.route("/suppliers/<int:supplier_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def supplier_edit(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    if request.method == "POST":
        name = request.form.get("company_name", "").strip()
        email = request.form.get("email", "").strip()
        if not name:
            flash("Supplier name is required", "danger")
            return page("Edit Supplier", supplier_form_html(s, url_for("supplier_edit", supplier_id=s.id), True))
        if email and not valid_email(email):
            flash("Invalid email address", "danger")
            return page("Edit Supplier", supplier_form_html(s, url_for("supplier_edit", supplier_id=s.id), True))
        dup = Supplier.query.filter(Supplier.company_name == name, Supplier.id != s.id).first()
        if dup:
            flash("Another supplier with this name exists", "warning")
            return page("Edit Supplier", supplier_form_html(s, url_for("supplier_edit", supplier_id=s.id), True))
        try:
            status = request.form.get("status", "Active")
            s.company_name = name
            s.contact_person = request.form.get("contact_person", "").strip()
            s.phone = request.form.get("phone", "").strip()
            s.email = email
            s.address = request.form.get("address", "").strip()
            s.tax_number = request.form.get("tax_number", "").strip()
            s.notes = request.form.get("notes", "").strip()
            s.status = status
            s.is_active = (status == "Active")
            log_audit("Supplier Updated", "Supplier", s.id, new_value=name)
            db.session.commit()
            flash("\u2705 Supplier updated", "success")
            return redirect(url_for("suppliers_list"))
        except Exception as e:
            db.session.rollback()
            flash("Error: " + str(e), "danger")
    return page("Edit Supplier", supplier_form_html(s, url_for("supplier_edit", supplier_id=s.id), True))


@app.route("/suppliers/<int:supplier_id>/deactivate", methods=["POST"])
@role_required("ADMIN", "MANAGER")
def supplier_deactivate(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    try:
        s.is_active = False
        s.status = "Inactive"
        log_audit("Supplier Deactivated", "Supplier", s.id, old_value="active", new_value="inactive")
        db.session.commit()
        flash("Supplier deactivated (existing records preserved)", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("suppliers_list"))


# ══════════════════════════════════════════════════════════════
# INVENTORY PARTS
# ══════════════════════════════════════════════════════════════
def part_form_html(part, action_url):
    def v(field, d=""):
        if part:
            val = getattr(part, field)
            return str(val if val is not None else d)
        return d
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    sup_opts = '<option value="">-- Select Supplier --</option>'
    for s in suppliers:
        sel = ' selected' if part and part.supplier_id == s.id else ''
        sup_opts += '<option value="' + str(s.id) + '"' + sel + '>' + str(s.company_name) + '</option>'
    title = "Edit Part" if part else "Add Part"
    return ('<h3 style="color:#f59e0b"><i class="fas fa-box"></i> ' + title + '</h3>'
        '<div class="card"><form method="post" action="' + str(action_url) + '"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Part Name *</label><input type="text" class="form-control" name="part_name" value="' + v("part_name") + '" required></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Category</label><input type="text" class="form-control" name="category" value="' + v("category") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Quantity</label><input type="number" step="0.01" class="form-control" name="quantity" value="' + v("quantity", "0") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Minimum Stock</label><input type="number" step="0.01" class="form-control" name="minimum_stock" value="' + v("minimum_stock", "5") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Unit</label><input type="text" class="form-control" name="unit" value="' + v("unit", "pcs") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" class="form-control" name="unit_cost" value="' + v("unit_cost", "0") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Storage Location</label><input type="text" class="form-control" name="storage_location" value="' + v("storage_location") + '"></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Supplier</label><select class="form-select" name="supplier_id">' + sup_opts + '</select></div>'
        '<div class="col-12 d-flex gap-2">'
        '<a href="' + url_for("inventory_list") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
        '<button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Save Part</button>'
        '</div></div></form></div>')


@app.route("/inventory/add", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def inventory_add():
    if request.method == "POST":
        name = request.form.get("part_name", "").strip()
        if not name:
            flash("Part name is required", "danger")
            return redirect(url_for("inventory_add"))
        if InventoryPart.query.filter_by(part_name=name).first():
            flash("A part with this name already exists", "warning")
            return redirect(url_for("inventory_add"))
        try:
            p = InventoryPart(
                part_name=name,
                category=request.form.get("category", "").strip(),
                quantity=request.form.get("quantity", type=float) or 0,
                minimum_stock=request.form.get("minimum_stock", type=float) or 5,
                unit=request.form.get("unit", "pcs").strip() or "pcs",
                unit_cost=request.form.get("unit_cost", type=float) or 0,
                storage_location=request.form.get("storage_location", "").strip(),
                status="Active",
                supplier_id=request.form.get("supplier_id", type=int),
            )
            db.session.add(p)
            db.session.flush()
            log_audit("Inventory Part Created", "InventoryPart", p.id, new_value=name)
            db.session.commit()
            flash("\u2705 Part saved", "success")
            return redirect(url_for("inventory_list"))
        except Exception as e:
            db.session.rollback()
            flash("Error: " + str(e), "danger")
            return redirect(url_for("inventory_add"))
    return page("Add Part", part_form_html(None, url_for("inventory_add")))


@app.route("/inventory/<int:part_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def inventory_edit(part_id):
    part = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        name = request.form.get("part_name", "").strip()
        if not name:
            flash("Part name is required", "danger")
            return redirect(url_for("inventory_edit", part_id=part.id))
        dup = InventoryPart.query.filter(InventoryPart.part_name == name, InventoryPart.id != part.id).first()
        if dup:
            flash("Another part with this name exists", "warning")
            return redirect(url_for("inventory_edit", part_id=part.id))
        try:
            part.part_name = name
            part.category = request.form.get("category", "").strip()
            part.quantity = request.form.get("quantity", type=float) or 0
            part.minimum_stock = request.form.get("minimum_stock", type=float) or 5
            part.unit = request.form.get("unit", "pcs").strip() or "pcs"
            part.unit_cost = request.form.get("unit_cost", type=float) or 0
            part.storage_location = request.form.get("storage_location", "").strip()
            part.supplier_id = request.form.get("supplier_id", type=int)
            log_audit("Inventory Part Updated", "InventoryPart", part.id, new_value=name)
            db.session.commit()
            flash("\u2705 Part updated", "success")
            return redirect(url_for("inventory_list"))
        except Exception as e:
            db.session.rollback()
            flash("Error: " + str(e), "danger")
    return page("Edit Part", part_form_html(part, url_for("inventory_edit", part_id=part.id)))


# ══════════════════════════════════════════════════════════════
# WORK ORDER PARTS
# ══════════════════════════════════════════════════════════════
def can_manage_wo_parts(wo):
    return (current_user.role in ["MANAGER", "ADMIN"] or
            (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))


@app.route("/workorders/<int:wo_id>/parts/add", methods=["GET", "POST"])
@login_required
def workorder_part_add(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_manage_wo_parts(wo):
        abort(403)
    if wo.status not in ["Assigned", "In Progress"]:
        flash("Parts can only be added while the work order is Assigned or In Progress", "warning")
        return redirect(url_for("workorder_detail", wo_id=wo.id))
    if request.method == "POST":
        try:
            part_id = request.form.get("part_id", type=int)
            quantity = request.form.get("quantity", type=float)
            unit_cost = request.form.get("unit_cost", type=float)
            part = get_one(InventoryPart, part_id)
            if not part:
                flash("Please select a valid part", "danger")
                return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if not quantity or quantity <= 0:
                flash("Quantity must be greater than 0", "danger")
                return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if quantity > part.quantity:
                flash("Only " + str(part.quantity) + " " + str(part.unit or "pcs") + " of '" + str(part.part_name) + "' available in stock", "danger")
                return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if unit_cost is None or unit_cost < 0:
                unit_cost = part.unit_cost or 0
            wop = WorkOrderPart(work_order_id=wo.id, part_id=part.id, quantity=quantity, unit_cost=unit_cost)
            part.quantity = (part.quantity or 0) - quantity
            db.session.add(wop)
            log_audit("Part Added to Work Order", "WorkOrder", wo.id, new_value=str(part.part_name) + " x " + str(quantity))
            db.session.commit()
            flash("\u2705 Part added & stock updated", "success")
            return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e:
            db.session.rollback()
            print("Part add: " + traceback.format_exc())
            flash("Error: " + str(e), "danger")
            return redirect(url_for("workorder_part_add", wo_id=wo.id))
    parts = InventoryPart.query.filter(InventoryPart.status == "Active", InventoryPart.quantity > 0).order_by(InventoryPart.part_name).all()
    part_opts = "".join('<option value="' + str(p.id) + '">' + str(p.part_name) + ' (stock: ' + str(p.quantity) + ' ' + str(p.unit or "pcs") + ')</option>' for p in parts)
    content = ('<h3 style="color:#f59e0b"><i class="fas fa-box"></i> Add Part \u2014 WO ' + str(wo.work_order_no) + '</h3>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Part *</label>'
        '<select class="form-select" name="part_id" required><option value="">-- Select Inventory Part --</option>' + part_opts + '</select></div>'
        '<div class="col-md-3 mb-3"><label class="form-label">Quantity *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required></div>'
        '<div class="col-md-3 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" min="0" class="form-control" name="unit_cost" placeholder="auto from inventory"></div>'
        '<div class="col-12 d-flex gap-2">'
        '<a href="' + url_for("workorder_detail", wo_id=wo.id) + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a>'
        '<button type="submit" class="btn btn-primary"><i class="fas fa-plus"></i> Add Part</button>'
        '</div></div></form></div>')
    return page("Add Part", content)


@app.route("/workorders/<int:wo_id>/parts/<int:part_id>/remove", methods=["POST"])
@login_required
def workorder_part_remove(wo_id, part_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_manage_wo_parts(wo):
        abort(403)
    if wo.status not in ["Assigned", "In Progress"]:
        flash("Parts cannot be removed at this stage", "warning")
        return redirect(url_for("workorder_detail", wo_id=wo.id))
    try:
        wop = WorkOrderPart.query.filter_by(work_order_id=wo.id, id=part_id).first()
        if not wop:
            flash("Part not found on this work order", "warning")
            return redirect(url_for("workorder_detail", wo_id=wo.id))
        part = get_one(InventoryPart, wop.part_id)
        detail = (part.part_name if part else str(wop.part_id)) + " x " + str(wop.quantity)
        if part:
            part.quantity = (part.quantity or 0) + (wop.quantity or 0)
        db.session.delete(wop)
        log_audit("Part Removed from Work Order", "WorkOrder", wo.id, old_value=detail)
        db.session.commit()
        flash("Part removed & stock restored", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error: " + str(e), "danger")
    return redirect(url_for("workorder_detail", wo_id=wo.id))


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════
@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    rows_parts = []
    for n in notifs:
        cls = "" if n.is_read else "table-warning"
        link = n.link or "#"
        read_action = '<span style="color:#22c55e">✓</span>'
        if not n.is_read:
            read_action = '<a class="btn btn-sm btn-primary" href="/notifications/mark-read/' + str(n.id) + '">Read</a>'
        rows_parts.append(
            '<tr class="' + cls + '">'
            '<td><a href="' + link + '" style="color:#f59e0b;font-weight:600">' + str(n.title) + '</a></td>'
            '<td>' + str(n.message) + '</td>'
            '<td>' + str(n.notification_type) + '</td>'
            '<td>' + (n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "") + '</td>'
            '<td>' + read_action + '</td></tr>'
        )
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b"><i class="fas fa-bell"></i> Notifications</h3>'
        '<div class="card"><div class="table-responsive"><table class="table table-hover">'
        '<thead><tr><th>Title</th><th>Message</th><th>Type</th><th>Date</th><th>Action</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="5" class="text-center">No notifications</td></tr>') + '</tbody>'
        '</table></div></div>')
    return page("Notifications", content)


@app.route("/notifications/mark-read/<int:n_id>", methods=["GET", "POST"])
@login_required
def notification_mark_read(n_id):
    try:
        n = get_or_404(Notification, n_id)
        if n.user_id == current_user.id:
            n.is_read = True
            db.session.commit()
            if n.link:
                return redirect(n.link)
            if n.work_order_id:
                return redirect(url_for("workorder_detail", wo_id=n.work_order_id))
            if n.request_id:
                return redirect(url_for("request_detail", req_id=n.request_id))
    except Exception as e:
        flash("Error: " + str(e), "danger")
    return redirect(url_for("notifications"))


# ══════════════════════════════════════════════════════════════
# OTHER PAGES
# ══════════════════════════════════════════════════════════════
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = "".join('<tr><td>' + str(r.room_number) + '</td><td>' + str(r.floor) + '</td><td>' + str(r.status) + '</td></tr>' for r in rooms)
    content = ('<h3 style="color:#f59e0b">Rooms</h3><div class="card"><table class="table">'
        '<thead><tr><th>Room</th><th>Floor</th><th>Status</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table></div>')
    return page("Rooms", content)


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join('<tr><td>' + str(a.name) + '</td><td>' + str(a.department) + '</td></tr>' for a in areas)
    content = ('<h3 style="color:#f59e0b">Areas</h3><div class="card"><table class="table">'
        '<thead><tr><th>Name</th><th>Dept</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table></div>')
    return page("Areas", content)


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows_parts = []
    for p in parts:
        if p.quantity <= 0:
            stock_badge = '<span class="badge bg-danger">Out of Stock</span>'
        elif p.is_low:
            stock_badge = '<span class="badge bg-warning text-dark">Low Stock</span>'
        else:
            stock_badge = '<span class="badge bg-success">In Stock</span>'
        sup_name = p.supplier.company_name if p.supplier else "\u2014"
        edit_url = url_for("inventory_edit", part_id=p.id)
        rows_parts.append(
            '<tr><td>' + str(p.part_name) + '</td>'
            '<td>' + str(p.category or "\u2014") + '</td>'
            '<td>' + str(sup_name) + '</td>'
            '<td>' + str(p.quantity) + '</td>'
            '<td>' + str(p.unit or "pcs") + '</td>'
            '<td>' + str(p.unit_cost or 0) + '</td>'
            '<td>' + stock_badge + '</td>'
            '<td><a class="btn btn-sm btn-info" href="' + edit_url + '"><i class="fas fa-edit"></i> Edit</a></td></tr>'
        )
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b"><i class="fas fa-boxes"></i> Inventory</h3>'
        '<a class="btn btn-primary mb-3" href="' + url_for("inventory_add") + '"><i class="fas fa-plus-circle"></i> Add Part</a>'
        '<div class="card"><div class="table-responsive"><table class="table table-hover">'
        '<thead><tr><th>Part</th><th>Category</th><th>Supplier</th><th>Quantity</th><th>Unit</th><th>Unit Cost</th><th>Stock Status</th><th>Actions</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="8" class="text-center">No parts</td></tr>') + '</tbody>'
        '</table></div></div>')
    return page("Inventory", content)


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    emps = Employee.query.all()
    rows = "".join('<tr><td>' + str(e.id) + '</td><td>' + str(e.name) + '</td><td>' + str(e.job_title) + '</td></tr>' for e in emps)
    content = ('<h3 style="color:#f59e0b">Employees</h3><div class="card"><table class="table">'
        '<thead><tr><th>ID</th><th>Name</th><th>Title</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table></div>')
    return page("Employees", content)


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows_parts = []
    for u in users:
        dept_name = u.department.name if u.department else "—"
        rows_parts.append('<tr><td>' + str(u.username) + '</td><td>' + str(u.full_name) + '</td><td>' + str(u.role) + '</td><td>' + str(dept_name) + '</td></tr>')
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b">Users</h3><div class="card"><table class="table">'
        '<thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Dept</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table></div>')
    return page("Users", content)


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows_parts = []
    for a in logs:
        user_name = a.user.full_name if a.user else "System"
        obj_type = a.object_type or ""
        date_str = a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else ""
        rows_parts.append('<tr><td>' + str(user_name) + '</td><td>' + str(a.action) + '</td><td>' + str(obj_type) + '</td><td>' + str(date_str) + '</td></tr>')
    rows = "".join(rows_parts)
    content = ('<h3 style="color:#f59e0b">Audit Log</h3><div class="card"><table class="table">'
        '<thead><tr><th>User</th><th>Action</th><th>Object</th><th>Date</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td colspan="4">No logs</td></tr>') + '</tbody></table></div>')
    return page("Audit Log", content)


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join('<tr><td>' + str(b) + '</td></tr>' for b in backups)
    content = ('<h3 style="color:#f59e0b">Backups</h3>'
        '<form method="post" action="/admin/backup/now" class="mb-3"><button class="btn btn-primary">Backup Now</button></form>'
        '<div class="card"><table class="table"><thead><tr><th>File</th></tr></thead>'
        '<tbody>' + (rows if rows else '<tr><td>No backups</td></tr>') + '</tbody></table></div>')
    return page("Backups", content)


@app.route("/admin/backup/now", methods=["GET", "POST"])
@role_required("ADMIN")
def backup_now():
    try:
        filename = "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
        src = sqlite3.connect(os.path.join(BASE_DIR, "hotel_maintenance.db"))
        dst = sqlite3.connect(os.path.join(BACKUP_FOLDER, filename))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        flash("Backup created: " + filename, "success")
    except Exception as e:
        flash("Error: " + str(e), "danger")
    return redirect(url_for("backup_page"))


@app.route("/reports")
@login_required
def reports():
    base = MaintenanceRequest.query.filter_by(is_deleted=False)
    total = base.count()
    pending = base.filter_by(status="Pending").count()
    completed = base.filter_by(status="Completed").count()
    verified = base.filter_by(status="Verified").count()
    content = ('<h3 style="color:#f59e0b">Reports</h3>'
        '<div class="row g-3 mb-4">'
        '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(total) + '</div><div class="metric-label">Total</div></div></div>'
        '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(pending) + '</div><div class="metric-label">Pending</div></div></div>'
        '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(completed) + '</div><div class="metric-label">Completed</div></div></div>'
        '<div class="col-3"><div class="metric-card"><div class="metric-value">' + str(verified) + '</div><div class="metric-label">Verified</div></div></div>'
        '</div>')
    return page("Reports", content)


# ══════════════════════════════════════════════════════════════
# DEBUG
# ══════════════════════════════════════════════════════════════
@app.route("/debug")
def debug():
    return jsonify({
        "users": User.query.count(),
        "dept_users": User.query.filter_by(role="DEPARTMENT").count(),
        "requests": MaintenanceRequest.query.filter_by(is_deleted=False).count(),
        "awaiting_hk": MaintenanceRequest.query.filter_by(awaiting_hk_approval=True).count(),
        "deleted_requests": MaintenanceRequest.query.filter_by(is_deleted=True).count(),
        "work_orders": WorkOrder.query.count(),
        "unassigned_wos": WorkOrder.query.filter(WorkOrder.assigned_to_id.is_(None)).count(),
        "notifications": Notification.query.count(),
    })


@app.route("/debug/routes")
def debug_routes():
    routes = []
    for r in app.url_map.iter_rules():
        if any(k in r.rule for k in ["verify", "approve", "close", "start", "complete", "delete", "restore", "mark-read", "hk-approve"]):
            routes.append({"rule": r.rule, "methods": sorted([m for m in r.methods if m not in ["HEAD", "OPTIONS"]]), "endpoint": r.endpoint})
    return jsonify(routes)


# ══════════════════════════════════════════════════════════════
# PWA / LOGO
# ══════════════════════════════════════════════════════════════
@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel Maintenance", "short_name": "RoriMaint", "start_url": "/dashboard", "display": "standalone", "background_color": "#0f172a", "theme_color": "#f59e0b", "icons": []})


@app.route("/sw.js")
def service_worker():
    return Response("self.addEventListener('install',e=>self.skipWaiting());", mimetype="application/javascript")


@app.route("/logo.png")
def serve_logo():
    logo_path = os.path.join(app.root_path, "file_00000000d93c821094a2e3f7dced7c77.png")
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype="image/png")
    return Response("", mimetype="image/png")


# ══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════
@app.errorhandler(403)
def forbidden(e):
    return page("Forbidden", '<div class="alert alert-danger">Access denied.</div>'), 403


@app.errorhandler(404)
def not_found(e):
    return page("Not Found", '<div class="alert alert-warning">Page not found.</div>'), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return page("Method Not Allowed", '<div class="alert alert-danger"><h4>405</h4><p>Method not allowed.</p><a class="btn btn-primary" href="/">Home</a></div>'), 405


@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    print("500 ERROR: " + tb)
    return "<h1>500 Error</h1><pre>" + tb + "</pre>", 500


# ══════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════
with app.app_context():
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)