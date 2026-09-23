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

STAFF_ROLES = ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]


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
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))  # ✅ አዲስ
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

    # ✅ NEW: Workflow timestamps
    approved_at = db.Column(db.DateTime)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at = db.Column(db.DateTime)
    rejected_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejection_reason = db.Column(db.Text)
    verified_at = db.Column(db.DateTime)
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verification_note = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)

    # ✅ NEW: Soft delete
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

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
    status = db.Column(db.String(30), default="Pending")
    work_performed = db.Column(db.Text)
    labor_hours = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text)
    completion_photo = db.Column(db.String(255), nullable=True)
    completed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    # ✅ NEW: Workflow timestamps
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    verified_at = db.Column(db.DateTime)
    verification_note = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)

    # ✅ NEW: Soft delete
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

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
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"))
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), default="General")
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    link = db.Column(db.String(250))

    user = db.relationship("User", foreign_keys=[user_id])
    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    work_order = db.relationship("WorkOrder", foreign_keys=[work_order_id])


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
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"))  # ✅ አዲስ
    status = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    notes = db.Column(db.Text)

    request = db.relationship("MaintenanceRequest", foreign_keys=[request_id])
    work_order = db.relationship("WorkOrder", foreign_keys=[work_order_id])
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


def create_notification(user_id, request_id, title, message, notification_type="General",
                        link=None, work_order_id=None):
    """Create a single notification with duplicate prevention (5-second window)."""
    if not user_id:
        return None
    recent = Notification.query.filter_by(
        user_id=user_id,
        request_id=request_id,
        notification_type=notification_type,
    ).order_by(Notification.created_at.desc()).first()
    if recent and (datetime.utcnow() - recent.created_at).total_seconds() < 5:
        return recent
    notif = Notification(
        user_id=user_id,
        request_id=request_id,
        work_order_id=work_order_id,
        title=title,
        message=message,
        notification_type=notification_type,
        link=link,
    )
    db.session.add(notif)
    return notif


def notify_users(user_ids, request_id, title, message, notification_type="General",
                 link=None, work_order_id=None):
    for uid in user_ids:
        if uid:
            create_notification(uid, request_id, title, message, notification_type,
                                link, work_order_id)


def log_status_change(request_id, status, notes=None, work_order_id=None, user_id=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    hist = StatusHistory(
        request_id=request_id,
        work_order_id=work_order_id,
        status=status,
        user_id=user_id,
        notes=notes,
    )
    db.session.add(hist)


# ✅ ዋናው አዲስ helper — Notify Requesting Department
def notify_requesting_department(req, wo, action="completed"):
    """Notify ONLY the requesting department user(s) about the outcome.
    - Department requests: notify the user(s) in the same department
    - Employee requests: notify the requester
    - Otherwise: notify the specific requester
    """
    try:
        recipients = set()

        # Prefer the actual requester
        if req.requested_by_id:
            recipients.add(req.requested_by_id)

        # Additionally notify all DEPARTMENT users in the same department
        if req.department_id:
            dept_users = User.query.filter(
                User.role == "DEPARTMENT",
                User.department_id == req.department_id,
                User.active == True,
            ).all()
            for u in dept_users:
                recipients.add(u.id)

        if not recipients:
            return 0

        location = req.location_name
        item = req.working_item.name if req.working_item else "N/A"
        wo_no = wo.work_order_no if wo else "N/A"
        dept_name = req.department.name if req.department else "N/A"
        completed_when = req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        title = f"✅ Maintenance {action.upper()}: {req.request_no}"
        message = (
            f"Request: {req.request_no} | "
            f"WO: {wo_no} | "
            f"Department: {dept_name} | "
            f"Location: {location} | "
            f"Item: {item} | "
            f"Status: {req.status} | "
            f"Completed: {completed_when}"
        )
        link = url_for("request_detail", req_id=req.id)

        count = 0
        for uid in recipients:
            result = create_notification(
                user_id=uid,
                request_id=req.id,
                title=title,
                message=message,
                notification_type=f"Department {action}",
                link=link,
                work_order_id=wo.id if wo else None,
            )
            if result:
                count += 1
        print(f"✅ Notified {count} department recipients about {req.request_no}")
        return count
    except Exception as e:
        print(f"⚠️ notify_requesting_department error: {e}")
        return 0


def notify_maintenance_staff(req, wo):
    """Notify ALL active maintenance staff about a new work order."""
    staff = User.query.filter(
        User.role.in_(STAFF_ROLES),
        User.active == True,
    ).all()

    if not staff:
        print(f"⚠️ No active staff to notify for WO {wo.work_order_no}")
        return 0

    location = req.location_name
    item = req.working_item.name if req.working_item else "N/A"
    category = req.category.name if req.category else "N/A"
    desc = (req.description or "")[:120]
    dept = req.department.name if req.department else "N/A"

    title = f"🔧 New Work Order: {wo.work_order_no}"
    message = (
        f"Request: {req.request_no} | "
        f"WO: {wo.work_order_no} | "
        f"Department: {dept} | "
        f"Location: {location} | "
        f"Item: {item} | "
        f"Category: {category} | "
        f"Priority: {req.priority} | "
        f"Description: {desc}"
    )
    link = url_for("workorder_detail", wo_id=wo.id)

    count = 0
    for s in staff:
        result = create_notification(
            user_id=s.id,
            request_id=req.id,
            title=title,
            message=message,
            notification_type="Work Order Created",
            link=link,
            work_order_id=wo.id,
        )
        if result:
            count += 1
    print(f"✅ Notified {count} staff about WO {wo.work_order_no}")
    return count


def notify_assigned_staff(req, wo, staff_user):
    """Notify ONLY the assigned staff."""
    if not staff_user:
        return
    location = req.location_name
    item = req.working_item.name if req.working_item else "N/A"
    category = req.category.name if req.category else "N/A"
    desc = (req.description or "")[:120]
    dept = req.department.name if req.department else "N/A"

    title = f"📋 Assigned to you: {wo.work_order_no}"
    message = (
        f"Request: {req.request_no} | "
        f"WO: {wo.work_order_no} | "
        f"Department: {dept} | "
        f"Location: {location} | "
        f"Item: {item} | "
        f"Category: {category} | "
        f"Priority: {req.priority} | "
        f"Description: {desc}"
    )
    link = url_for("workorder_detail", wo_id=wo.id)
    create_notification(
        user_id=staff_user.id,
        request_id=req.id,
        title=title,
        message=message,
        notification_type="Work Order Assigned",
        link=link,
        work_order_id=wo.id,
    )


def request_no_generator():
    return f"R-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def work_order_no_generator():
    return f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_database_schema():
    """Safely add missing columns. Never drops data."""
    with app.app_context():
        try:
            db.create_all()
            conn = db.engine.raw_connection()
            cursor = conn.cursor()

            # ✅ Add columns to maintenance_requests
            cursor.execute("PRAGMA table_info(maintenance_requests)")
            existing = [row[1] for row in cursor.fetchall()]
            mr_cols = {
                'department_id': 'ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER',
                'manager_id': 'ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER',
                'completion_note': 'ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT',
                'completed_date': 'ALTER TABLE maintenance_requests ADD COLUMN completed_date DATETIME',
                'approved_at': 'ALTER TABLE maintenance_requests ADD COLUMN approved_at DATETIME',
                'approved_by_id': 'ALTER TABLE maintenance_requests ADD COLUMN approved_by_id INTEGER',
                'rejected_at': 'ALTER TABLE maintenance_requests ADD COLUMN rejected_at DATETIME',
                'rejected_by_id': 'ALTER TABLE maintenance_requests ADD COLUMN rejected_by_id INTEGER',
                'rejection_reason': 'ALTER TABLE maintenance_requests ADD COLUMN rejection_reason TEXT',
                'verified_at': 'ALTER TABLE maintenance_requests ADD COLUMN verified_at DATETIME',
                'verified_by_id': 'ALTER TABLE maintenance_requests ADD COLUMN verified_by_id INTEGER',
                'verification_note': 'ALTER TABLE maintenance_requests ADD COLUMN verification_note TEXT',
                'closed_at': 'ALTER TABLE maintenance_requests ADD COLUMN closed_at DATETIME',
                'is_deleted': 'ALTER TABLE maintenance_requests ADD COLUMN is_deleted BOOLEAN DEFAULT 0',
                'deleted_at': 'ALTER TABLE maintenance_requests ADD COLUMN deleted_at DATETIME',
                'deleted_by_id': 'ALTER TABLE maintenance_requests ADD COLUMN deleted_by_id INTEGER',
            }
            for col, sql in mr_cols.items():
                if col not in existing:
                    db.engine.execute(sql)
                    print(f"✅ Added {col} to maintenance_requests")

            # ✅ Add columns to work_orders
            cursor.execute("PRAGMA table_info(work_orders)")
            existing = [row[1] for row in cursor.fetchall()]
            wo_cols = {
                'started_at': 'ALTER TABLE work_orders ADD COLUMN started_at DATETIME',
                'completed_at': 'ALTER TABLE work_orders ADD COLUMN completed_at DATETIME',
                'verified_at': 'ALTER TABLE work_orders ADD COLUMN verified_at DATETIME',
                'verification_note': 'ALTER TABLE work_orders ADD COLUMN verification_note TEXT',
                'closed_at': 'ALTER TABLE work_orders ADD COLUMN closed_at DATETIME',
                'is_deleted': 'ALTER TABLE work_orders ADD COLUMN is_deleted BOOLEAN DEFAULT 0',
                'deleted_at': 'ALTER TABLE work_orders ADD COLUMN deleted_at DATETIME',
                'deleted_by_id': 'ALTER TABLE work_orders ADD COLUMN deleted_by_id INTEGER',
            }
            for col, sql in wo_cols.items():
                if col not in existing:
                    db.engine.execute(sql)
                    print(f"✅ Added {col} to work_orders")

            # ✅ Add columns to users
            cursor.execute("PRAGMA table_info(users)")
            existing = [row[1] for row in cursor.fetchall()]
            if 'department_id' not in existing:
                db.engine.execute('ALTER TABLE users ADD COLUMN department_id INTEGER')
                print("✅ Added department_id to users")

            # ✅ Add columns to notifications
            cursor.execute("PRAGMA table_info(notifications)")
            existing = [row[1] for row in cursor.fetchall()]
            if 'work_order_id' not in existing:
                db.engine.execute('ALTER TABLE notifications ADD COLUMN work_order_id INTEGER')
                print("✅ Added work_order_id to notifications")

            # ✅ Add columns to status_history
            cursor.execute("PRAGMA table_info(status_history)")
            existing = [row[1] for row in cursor.fetchall()]
            if 'work_order_id' not in existing:
                db.engine.execute('ALTER TABLE status_history ADD COLUMN work_order_id INTEGER')
                print("✅ Added work_order_id to status_history")

            conn.close()
            print("✅ Schema OK")
        except Exception as e:
            print(f"⚠️ Schema error: {e}")


# ══════════════════════════════════════════════════════════════
# PAGE FUNCTION
# ══════════════════════════════════════════════════════════════
def page(title, content):
    nav_items = []
    if current_user.is_authenticated:
        role = current_user.role
        if role == "DEPARTMENT":
            nav_items.append(('<i class="fas fa-home"></i> My Department', url_for('department_dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        elif role == "EMPLOYEE":
            nav_items.append(('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        elif role in STAFF_ROLES:
            nav_items.append(('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')))
            nav_items.append(('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
        else:
            nav_items.append(('<i class="fas fa-home"></i> Dashboard', url_for('dashboard')))
            nav_items.append(('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')))
            nav_items.append(('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')))
            nav_items.append(('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')))
            if role in ["ADMIN", "MANAGER"]:
                nav_items.append(('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')))
                nav_items.append(('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')))
                nav_items.append(('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')))
                nav_items.append(('<i class="fas fa-users"></i> Employees', url_for('employees_list')))
            if role == "ADMIN":
                nav_items.append(('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')))
                nav_items.append(('<i class="fas fa-history"></i> Audit', url_for('audit_logs')))
                nav_items.append(('<i class="fas fa-trash"></i> Trash', url_for('deleted_records')))
                nav_items.append(('<i class="fas fa-archive"></i> Backup', url_for('backup_page')))
            nav_items.append(('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')))
            nav_items.append(('<i class="fas fa-bell"></i> Notifications', url_for('notifications')))
            nav_items.append(('<i class="fas fa-user-circle"></i> Profile', url_for('profile')))
            nav_items.append(('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout')))
    else:
        nav_items.append(('<i class="fas fa-sign-in-alt"></i> Login', url_for('login')))

    nav_html = "".join(f'<a class="nav-link" href="{url}">{label}</a>' for label, url in nav_items)

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
        min-height: 100vh; color: #e2e8f0; padding-top: 70px;
    }}
    .navbar {{ background: rgba(15,23,42,0.9) !important; backdrop-filter: blur(16px);
        border-bottom: 1px solid rgba(245,158,11,0.25); box-shadow: 0 8px 32px rgba(0,0,0,0.4);
        padding: 0.75rem 1.5rem; }}
    .navbar-brand {{ font-weight: 800; font-size: 1.4rem; color: #f59e0b !important; }}
    .navbar-brand img {{ height: 38px; vertical-align: middle; margin-right: 10px; }}
    .nav-link {{ color: #cbd5e1 !important; font-weight: 500; padding: 0.6rem 1.2rem !important;
        border-radius: 40px; margin: 0 0.1rem; display: flex; align-items: center;
        gap: 8px; font-size: 0.9rem; }}
    .nav-link i {{ color: #f59e0b; }}
    .nav-link:hover {{ background: rgba(245,158,11,0.12); color: #f59e0b !important; }}
    .container {{ max-width: 1280px; padding: 1.5rem; }}
    .card {{ background: rgba(30,41,59,0.7) !important; backdrop-filter: blur(8px);
        border: 1px solid rgba(245,158,11,0.15); border-radius: 20px !important;
        color: #e2e8f0; padding: 1.25rem; margin-bottom: 1.5rem; }}
    .card-title {{ font-weight: 600; color: #f59e0b; }}
    .metric-card {{ background: rgba(30,41,59,0.5); border: 1px solid rgba(245,158,11,0.12);
        border-radius: 20px; padding: 1.2rem 1rem; text-align: center; height: 100%; }}
    .metric-icon {{ font-size: 2.2rem; color: #f59e0b; margin-bottom: 0.5rem; }}
    .metric-value {{ font-size: 2rem; font-weight: 700; color: #f8fafc; }}
    .metric-label {{ font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; }}
    .table {{ color: #e2e8f0; }}
    .table thead th {{ border-bottom: 2px solid rgba(245,158,11,0.2); color: #f59e0b;
        font-weight: 600; text-transform: uppercase; font-size: 0.75rem; padding: 8px 10px; }}
    .table td {{ padding: 8px 10px; vertical-align: middle; border-color: rgba(245,158,11,0.08); }}
    .table-striped tbody tr:nth-of-type(odd) {{ background: rgba(30,41,59,0.3); }}
    .btn {{ border-radius: 40px; font-weight: 600; padding: 0.6rem 1.8rem; border: none; }}
    .btn-primary {{ background: linear-gradient(135deg,#f59e0b,#d97706); color: #0f172a; }}
    .btn-primary:hover {{ background: linear-gradient(135deg,#fbbf24,#f59e0b); color: #0f172a; }}
    .btn-success {{ background: linear-gradient(135deg,#22c55e,#16a34a); color: white; }}
    .btn-warning {{ background: linear-gradient(135deg,#eab308,#ca8a04); color: #0f172a; }}
    .btn-danger {{ background: linear-gradient(135deg,#ef4444,#dc2626); color: white; }}
    .btn-info {{ background: linear-gradient(135deg,#06b6d4,#0891b2); color: white; }}
    .btn-secondary {{ background: #475569; color: white; }}
    .form-control, .form-select {{ background: rgba(15,23,42,0.6);
        border: 1px solid rgba(245,158,11,0.2); border-radius: 12px;
        color: #e2e8f0; padding: 0.75rem 1rem; }}
    .form-control:focus, .form-select:focus {{ border-color: #f59e0b;
        box-shadow: 0 0 0 4px rgba(245,158,11,0.15); background: rgba(15,23,42,0.8); color: #f8fafc; }}
    .form-label {{ font-weight: 500; color: #cbd5e1; margin-bottom: 0.4rem; }}
    .alert {{ border-radius: 16px; border: none; background: rgba(30,41,59,0.7); color: #e2e8f0; }}
    .alert-success {{ border-left: 4px solid #22c55e; }}
    .alert-danger {{ border-left: 4px solid #ef4444; }}
    .alert-warning {{ border-left: 4px solid #f59e0b; }}
    .badge {{ padding: 0.4rem 0.8rem; border-radius: 20px; font-weight: 600; font-size: 0.75rem; }}
    .timeline {{ position: relative; padding-left: 30px; }}
    .timeline::before {{ content: ''; position: absolute; left: 10px; top: 0; bottom: 0;
        width: 2px; background: rgba(245,158,11,0.3); }}
    .timeline-item {{ position: relative; margin-bottom: 20px; }}
    .timeline-item::before {{ content: ''; position: absolute; left: -24px; top: 5px;
        width: 12px; height: 12px; border-radius: 50%; background: #f59e0b; border: 2px solid #0f172a; }}
    .timeline-item .time {{ font-size: 0.8rem; color: #94a3b8; }}
    .timeline-item .content {{ background: rgba(30,41,59,0.4); padding: 10px 15px;
        border-radius: 10px; border-left: 3px solid #f59e0b; }}
    .completion-evidence {{ border: 2px solid rgba(245,158,11,0.2); border-radius: 16px;
        padding: 1.25rem; background: rgba(30,41,59,0.4); margin-top: 1rem; }}
    .login-card {{ background: rgba(30,41,59,0.5) !important; backdrop-filter: blur(20px);
        border: 1px solid rgba(245,158,11,0.2); border-radius: 32px !important;
        padding: 2rem 2.5rem; max-width: 440px; margin: 0 auto; }}
    @media (max-width: 768px) {{
        .nav-link {{ padding: 0.5rem 0.8rem !important; font-size: 0.85rem; }}
        .metric-value {{ font-size: 1.5rem; }}
    }}
</style>
</head>
<body>
<nav class="navbar navbar-expand-lg fixed-top">
  <div class="container-fluid">
    <a class="navbar-brand" href="{url_for('index')}">
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
    # Departments
    dept_list = ["Housekeeping", "Front Office", "Engineering", "Food & Beverage",
                 "Administration", "Security", "Maintenance", "Other"]
    for dept_name in dept_list:
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

    db.session.commit()

    # Link department users to their departments
    hk_dept = Department.query.filter_by(name="Housekeeping").first()
    fo_dept = Department.query.filter_by(name="Front Office").first()
    fb_dept = Department.query.filter_by(name="Food & Beverage").first()

    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", full_name="System Administrator", role="ADMIN",
                     email="admin@rorihotel.local", phone="", profile_pic=None)
        admin.set_password("admin123")
        db.session.add(admin)

    staff_list = [
        {"username": "amir", "full_name": "አሚር አወል", "role": "MANAGER", "dept": None},
        {"username": "abebayhu", "full_name": "አበባየሁ ክፍሌ", "role": "SUPERVISOR", "dept": None},
        {"username": "tesfahun", "full_name": "ተስፋሁን ነከረ", "role": "TECHNICIAN", "dept": None},
        {"username": "simon", "full_name": "ስምዖን ዮሐንስ", "role": "TECHNICIAN", "dept": None},
        {"username": "chernet", "full_name": "ቸርነት አሞና", "role": "TECHNICIAN", "dept": None},
        {"username": "wale", "full_name": "ዋሌ", "role": "TECHNICIAN", "dept": None},
        {"username": "tsadiku", "full_name": "ፃዲቁ", "role": "TECHNICIAN", "dept": None},
        {"username": "housekeeping", "full_name": "Housekeeping User", "role": "DEPARTMENT", "dept": hk_dept},
        {"username": "frontoffice", "full_name": "Front Office User", "role": "DEPARTMENT", "dept": fo_dept},
        {"username": "fb", "full_name": "F&B User", "role": "DEPARTMENT", "dept": fb_dept},
        {"username": "employee1", "full_name": "Test Employee", "role": "EMPLOYEE", "dept": None},
    ]
    for s in staff_list:
        existing = User.query.filter_by(username=s["username"]).first()
        if not existing:
            user = User(username=s["username"], full_name=s["full_name"], role=s["role"],
                        email="", phone="", profile_pic=None,
                        department_id=s["dept"].id if s["dept"] else None)
            user.set_password("123456")
            db.session.add(user)
        else:
            if s["dept"] and not existing.department_id:
                existing.department_id = s["dept"].id

    db.session.commit()

    # Initial seed requests
    if MaintenanceRequest.query.count() == 0:
        admin_user = User.query.filter_by(username="admin").first()
        hk = Department.query.filter_by(name="Housekeeping").first()
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
                    department_id=hk.id if hk else None,
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
                    <p style="color: #94a3b8;">Maintenance Portal</p>
                </div>
                <form method="post">
                    <div class="mb-3"><label class="form-label">Username</label>
                    <input type="text" class="form-control form-control-lg" name="username" required></div>
                    <div class="mb-4"><label class="form-label">Password</label>
                    <input type="password" class="form-control form-control-lg" name="password" required></div>
                    <button class="btn btn-primary btn-lg w-100"><i class="fas fa-sign-in-alt"></i> Login</button>
                </form>
                <hr class="my-4" style="border-color: rgba(245,158,11,0.15);">
                <div class="text-center small" style="color: #94a3b8;">
                    <p class="mb-1">admin/admin123 · amir/123456 · tesfahun/123456</p>
                    <p class="mb-0">housekeeping/123456 · frontoffice/123456</p>
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
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile"))

    content = f'''
    <h3 style="color:#f59e0b;">My Profile</h3>
    <div class="card">
    <p><b>Name:</b> {user.full_name}</p>
    <p><b>Username:</b> {user.username}</p>
    <p><b>Role:</b> {user.role}</p>
    <p><b>Department:</b> {user.department.name if user.department else "—"}</p>
    <form method="post">
    <div class="mb-3"><label class="form-label">Email</label>
    <input type="email" name="email" class="form-control" value="{user.email or ''}"></div>
    <div class="mb-3"><label class="form-label">Phone</label>
    <input type="text" name="phone" class="form-control" value="{user.phone or ''}"></div>
    <div class="mb-3"><label class="form-label">New Password</label>
    <input type="password" name="new_password" class="form-control"></div>
    <button class="btn btn-primary">Save</button>
    </form>
    </div>
    '''
    return page("Profile", content)


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

    active_filter = MaintenanceRequest.is_deleted == False
    total = MaintenanceRequest.query.filter(active_filter).count()
    pending = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.status == "Pending").count()
    in_progress = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.status == "In Progress").count()
    completed = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.status == "Completed").count()
    verified = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.status == "Verified").count()
    closed = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.status == "Closed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.filter(active_filter).all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter(active_filter, MaintenanceRequest.priority == "URGENT").count()

    content = f'''
    <h3 style="color:#f59e0b;">🏨 Admin Dashboard</h3>
    <div class="row g-3 mb-4">
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-tasks"></i></div><div class="metric-value">{total}</div><div class="metric-label">Total</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clock"></i></div><div class="metric-value">{pending}</div><div class="metric-label">Pending</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-spinner"></i></div><div class="metric-value">{in_progress}</div><div class="metric-label">In Progress</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-circle"></i></div><div class="metric-value">{completed}</div><div class="metric-label">Completed</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-check-double"></i></div><div class="metric-value">{verified}</div><div class="metric-label">Verified</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon"><i class="fas fa-archive"></i></div><div class="metric-value">{closed}</div><div class="metric-label">Closed</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color:#ef4444;"><i class="fas fa-exclamation-triangle"></i></div><div class="metric-value">{urgent}</div><div class="metric-label">Urgent</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-icon" style="color:#ef4444;"><i class="fas fa-clock"></i></div><div class="metric-value">{overdue}</div><div class="metric-label">Overdue</div></div></div>
    </div>
    <div class="row g-3">
        <div class="col-md-4"><a class="btn btn-primary w-100 py-3" href="{url_for('requests_list')}"><i class="fas fa-list"></i> Requests</a></div>
        <div class="col-md-4"><a class="btn btn-success w-100 py-3" href="{url_for('workorders_list')}"><i class="fas fa-clipboard-list"></i> Work Orders</a></div>
        <div class="col-md-4"><a class="btn btn-info w-100 py-3" href="{url_for('reports')}"><i class="fas fa-chart-bar"></i> Reports</a></div>
    </div>
    '''
    return page("Dashboard", content)


@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    """Department dashboard — only own department's requests."""
    # Determine which department this user belongs to
    dept_id = current_user.department_id

    if dept_id:
        # All requests from this department (any user)
        base_q = MaintenanceRequest.query.filter(
            MaintenanceRequest.is_deleted == False,
            MaintenanceRequest.department_id == dept_id,
        )
    else:
        # Fallback: only own requests
        base_q = MaintenanceRequest.query.filter(
            MaintenanceRequest.is_deleted == False,
            MaintenanceRequest.requested_by_id == current_user.id,
        )

    all_reqs = base_q.order_by(MaintenanceRequest.created_at.desc()).all()

    # Stats
    total = len(all_reqs)
    pending = sum(1 for r in all_reqs if r.status == "Pending")
    approved = sum(1 for r in all_reqs if r.status == "Approved")
    assigned = sum(1 for r in all_reqs if r.status == "Assigned")
    in_progress = sum(1 for r in all_reqs if r.status == "In Progress")
    completed = sum(1 for r in all_reqs if r.status == "Completed")
    verified = sum(1 for r in all_reqs if r.status == "Verified")
    closed = sum(1 for r in all_reqs if r.status == "Closed")
    rejected = sum(1 for r in all_reqs if r.status == "Rejected")

    unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()

    rows = ""
    for r in all_reqs:
        badge = "danger" if r.priority == "URGENT" else "warning" if r.priority == "HIGH" else "info" if r.priority == "MEDIUM" else "secondary"
        status_badge = "success" if r.status in ["Completed", "Verified", "Closed"] else "warning" if r.status == "Pending" else "info"
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;"><b>{r.request_no}</b></a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else "—"}</td>
        <td><span class="badge bg-{badge}">{r.priority}</span></td>
        <td><span class="badge bg-{status_badge}">{r.status}</span></td>
        <td>{r.requested_by.full_name if r.requested_by else "—"}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''

    dept_name = current_user.department.name if current_user.department else "My"
    content = f'''
    <h3 style="color:#f59e0b;">🏢 {dept_name} Department Dashboard</h3>
    <p style="color:#94a3b8;">Welcome, {current_user.full_name}!</p>

    <div class="card" style="border-color: rgba(6,182,212,0.3);">
        <div class="d-flex justify-content-between align-items-center">
            <div>
                <h5 style="color:#06b6d4; margin:0;"><i class="fas fa-bell"></i> Unread Notifications</h5>
                <p style="margin:5px 0 0; color:#94a3b8;">You have {unread_count} unread notification(s)</p>
            </div>
            <a class="btn btn-info" href="{url_for('notifications')}">View All</a>
        </div>
    </div>

    <div class="row g-3 mb-4">
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">All</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{pending}</div><div class="metric-label">Pending</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{approved}</div><div class="metric-label">Approved</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{assigned}</div><div class="metric-label">Assigned</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{in_progress}</div><div class="metric-label">In Progress</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value" style="color:#22c55e;">{completed}</div><div class="metric-label">Completed</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value" style="color:#22c55e;">{verified}</div><div class="metric-label">Verified</div></div></div>
        <div class="col-6 col-md-3"><div class="metric-card"><div class="metric-value">{closed}</div><div class="metric-label">Closed</div></div></div>
    </div>

    <a class="btn btn-primary mb-3" href="{url_for('request_create')}"><i class="fas fa-plus-circle"></i> New Request</a>

    <div class="card">
        <h5 class="card-title">📋 My Department's Requests</h5>
        <div class="table-responsive">
        <table class="table table-hover">
        <thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Requester</th><th>Created</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="7" class="text-center">No requests yet</td></tr>'}</tbody>
        </table>
        </div>
    </div>
    '''
    return page("Department Dashboard", content)


@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    requests = MaintenanceRequest.query.filter(
        MaintenanceRequest.is_deleted == False,
        MaintenanceRequest.requested_by_id == current_user.id,
    ).order_by(MaintenanceRequest.created_at.desc()).all()

    rows = ""
    for r in requests:
        badge = "danger" if r.priority == "URGENT" else "warning" if r.priority == "HIGH" else "info"
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;"><b>{r.request_no}</b></a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else "—"}</td>
        <td><span class="badge bg-{badge}">{r.priority}</span></td>
        <td>{r.status}</td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''

    content = f'''
    <h3 style="color:#f59e0b;">👤 My Dashboard</h3>
    <a class="btn btn-primary mb-3" href="{url_for('request_create')}"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
    <table class="table table-hover">
    <thead><tr><th>Request</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="6" class="text-center">No requests</td></tr>'}</tbody>
    </table>
    </div>
    '''
    return page("My Dashboard", content)


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

    base = MaintenanceRequest.query.filter(MaintenanceRequest.is_deleted == False)
    if current_user.role in STAFF_ROLES:
        reqs = base.filter(MaintenanceRequest.assigned_to_id == current_user.id)\
            .order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = base.order_by(MaintenanceRequest.created_at.desc()).all()

    rows = ""
    for r in reqs:
        badge = "danger" if r.priority == "URGENT" else "warning" if r.priority == "HIGH" else "info" if r.priority == "MEDIUM" else "secondary"
        status_badge = "success" if r.status in ["Completed", "Verified", "Closed"] else "warning" if r.status == "Pending" else "info"
        rows += f'''
        <tr>
        <td><a href="/requests/{r.id}" style="color:#f59e0b;"><b>{r.request_no}</b></a></td>
        <td>{r.location_name}</td>
        <td>{r.working_item.name if r.working_item else "—"}</td>
        <td>{r.department.name if r.department else "—"}</td>
        <td><span class="badge bg-{badge}">{r.priority}</span></td>
        <td><span class="badge bg-{status_badge}">{r.status}</span></td>
        <td>{r.created_at.strftime('%Y-%m-%d %H:%M') if r.created_at else ''}</td>
        </tr>'''

    content = f'''
    <h3 style="color:#f59e0b;">📋 Maintenance Requests</h3>
    <a class="btn btn-primary mb-3" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a>
    <div class="card">
    <div class="table-responsive">
    <table class="table table-hover">
    <thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Dept</th><th>Priority</th><th>Status</th><th>Created</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="7" class="text-center">No requests</td></tr>'}</tbody>
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
        try:
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
                    flash("Invalid room", "danger")
                    return redirect(url_for("request_create"))
                floor = room.floor
                area_id = None
            else:
                area = Area.query.get(area_id)
                if not area:
                    flash("Invalid area", "danger")
                    return redirect(url_for("request_create"))
                floor = None
                room_id = None

            if not description:
                flash("Description required", "danger")
                return redirect(url_for("request_create"))

            # ✅ Default dept = user's department (if DEPARTMENT role)
            if not department_id and current_user.department_id:
                department_id = current_user.department_id

            due = datetime.strptime(due_date, "%Y-%m-%dT%H:%M") if due_date else \
                  datetime.utcnow() + timedelta(hours=PRIORITIES.get(priority, 24))

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

            log_status_change(req.id, "Pending", notes="Request submitted")
            log_audit("Create", "MaintenanceRequest", req.id, new_value=req.request_no)

            # Notify managers
            managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
            notify_users([u.id for u in managers], req.id,
                         "New Maintenance Request",
                         f"New request {req.request_no} at {req.location_name}",
                         "New Request", link=url_for("request_detail", req_id=req.id))

            db.session.commit()
            flash("✅ Request submitted!", "success")

            if current_user.role == "EMPLOYEE":
                return redirect(url_for("employee_dashboard"))
            if current_user.role == "DEPARTMENT":
                return redirect(url_for("department_dashboard"))
            return redirect(url_for("requests_list"))

        except Exception as e:
            db.session.rollback()
            print("❌ Request create error:", traceback.format_exc())
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("request_create"))

    room_options = "".join(f'<option value="{r.id}">Room {r.room_number} (Floor {r.floor})</option>' for r in rooms)
    area_options = "".join(f'<option value="{a.id}">{a.name}</option>' for a in areas)
    item_options = "".join(f'<option value="{i.id}">{i.name}</option>' for i in items)
    cat_options = "".join(f'<option value="{c.id}">{c.name}</option>' for c in categories)

    # Default department for DEPARTMENT users
    dept_options = ""
    for d in departments:
        selected = "selected" if current_user.department_id == d.id else ""
        dept_options += f'<option value="{d.id}" {selected}>{d.name}</option>'

    content = f'''
    <h3 style="color:#f59e0b;">➕ New Maintenance Request</h3>
    <div class="card">
    <form method="post">
    <div class="row">
    <div class="col-md-6 mb-3">
    <label class="form-label">Location Type</label>
    <select class="form-select" name="location_type" id="loc" onchange="tog()" required>
      <option value="Room">Room</option>
      <option value="Hotel Area">Hotel Area</option>
    </select>
    </div>
    <div class="col-md-6 mb-3" id="roomDiv">
    <label class="form-label">Room</label>
    <select class="form-select" name="room_id">{room_options}</select>
    </div>
    <div class="col-md-6 mb-3" id="areaDiv" style="display:none">
    <label class="form-label">Area</label>
    <select class="form-select" name="area_id"><option value="">-- Select --</option>{area_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Working Item</label>
    <select class="form-select" name="working_item_id" required>
      <option value="">-- Select --</option>{item_options}
    </select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Category</label>
    <select class="form-select" name="category_id" required>
      <option value="">-- Select --</option>{cat_options}
    </select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Department</label>
    <select class="form-select" name="department_id" required>{dept_options}</select>
    </div>
    <div class="col-md-6 mb-3">
    <label class="form-label">Priority</label>
    <select class="form-select" name="priority">
      <option value="LOW">Low (72h)</option>
      <option value="MEDIUM" selected>Medium (24h)</option>
      <option value="HIGH">High (4h)</option>
      <option value="URGENT">Urgent (1h)</option>
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
    function tog() {{
      var t = document.getElementById('loc').value;
      document.getElementById('roomDiv').style.display = t === 'Room' ? 'block' : 'none';
      document.getElementById('areaDiv').style.display = t === 'Hotel Area' ? 'block' : 'none';
    }}
    </script>
    '''
    return page("New Request", content)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    wo = WorkOrder.query.filter_by(request_id=req.id).first()

    history = StatusHistory.query.filter_by(request_id=req.id)\
        .order_by(StatusHistory.timestamp.asc()).all()

    timeline_html = ""
    for h in history:
        user_name = h.user.full_name if h.user else "System"
        timeline_html += f'''
        <div class="timeline-item">
            <span class="time">{h.timestamp.strftime('%Y-%m-%d %H:%M') if h.timestamp else ''} — {user_name}</span>
            <div class="content">
                <b>{h.status}</b>
                {f'<br><span style="color:#94a3b8;">{h.notes}</span>' if h.notes else ''}
            </div>
        </div>'''

    wo_html = ""
    if wo:
        wo_html = f'''
        <div class="card" style="border-color: rgba(34,197,94,0.4);">
            <h5 style="color:#22c55e;">🔧 Work Order</h5>
            <p><b>WO #:</b> <a href="/workorders/{wo.id}" style="color:#f59e0b;">{wo.work_order_no}</a></p>
            <p><b>Status:</b> {wo.status}</p>
            <p><b>Assigned:</b> {wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"}</p>
            {f'<p><b>Started:</b> {wo.started_at.strftime("%Y-%m-%d %H:%M")}</p>' if wo.started_at else ''}
            {f'<p><b>Completed:</b> {wo.completed_at.strftime("%Y-%m-%d %H:%M")}</p>' if wo.completed_at else ''}
            {f'<p><b>Verified:</b> {wo.verified_at.strftime("%Y-%m-%d %H:%M")}</p>' if wo.verified_at else ''}
            {f'<p><b>Notes:</b> {wo.completion_notes}</p>' if wo.completion_notes else ''}
            {f'<p><img src="/static/uploads/maintenance/{wo.completion_photo}" class="img-fluid rounded mt-2" style="max-height:250px;"></p>' if wo.completion_photo else ''}
        </div>'''

    # Actions
    actions = ""
    if current_user.role in ["MANAGER", "ADMIN"]:
        if req.status == "Pending":
            actions += f'''
            <form method="post" action="/requests/{req.id}/approve" class="d-inline">
                <button class="btn btn-success w-100 mb-2"><i class="fas fa-check"></i> Approve & Create WO</button>
            </form>
            <form method="post" action="/requests/{req.id}/reject" class="d-inline">
                <input type="text" name="reason" class="form-control mb-2" placeholder="Rejection reason">
                <button class="btn btn-danger w-100 mb-2"><i class="fas fa-times"></i> Reject</button>
            </form>'''
        if req.status == "Approved" and (not wo or wo.assigned_to_id is None):
            actions += f'<a class="btn btn-warning w-100 mb-2" href="/workorders/new?request_id={req.id}"><i class="fas fa-user-plus"></i> Assign Staff</a>'
        if req.status == "Completed" or (wo and wo.status == "Completed"):
            actions += f'<a class="btn btn-info w-100 mb-2" href="/workorders/{wo.id}/verify"><i class="fas fa-check-double"></i> Verify Work</a>'

    completion_html = ""
    if req.completion_note:
        completion_html = f'''
        <div class="completion-evidence">
            <h6>✅ Completion Evidence</h6>
            <p><b>Work:</b> {req.completion_note}</p>
            {f'<p><b>Completed:</b> {req.completed_date.strftime("%Y-%m-%d %H:%M")}</p>' if req.completed_date else ''}
        </div>'''

    verification_html = ""
    if req.verified_at:
        verification_html = f'''
        <div class="card" style="border-color: rgba(6,182,212,0.4);">
            <h6 style="color:#06b6d4;">✔ Manager Verification</h6>
            <p><b>Verified By:</b> {req.manager.full_name if req.manager else "—"}</p>
            <p><b>Date:</b> {req.verified_at.strftime("%Y-%m-%d %H:%M")}</p>
            {f'<p><b>Note:</b> {req.verification_note}</p>' if req.verification_note else ''}
        </div>'''

    content = f'''
    <h3 style="color:#f59e0b;">📄 Request {req.request_no}</h3>
    <div class="row">
    <div class="col-md-8">
        <div class="card">
            <table class="table">
                <tr><th style="width:150px;">Status</th><td><b>{req.status}</b></td></tr>
                <tr><th>Department</th><td>{req.department.name if req.department else "—"}</td></tr>
                <tr><th>Requester</th><td>{req.requested_by.full_name if req.requested_by else "Guest"}</td></tr>
                <tr><th>Location</th><td>{req.location_name}</td></tr>
                <tr><th>Item</th><td>{req.working_item.name if req.working_item else "—"}</td></tr>
                <tr><th>Category</th><td>{req.category.name if req.category else "—"}</td></tr>
                <tr><th>Priority</th><td>{req.priority}</td></tr>
                <tr><th>Due Date</th><td>{req.due_date.strftime('%Y-%m-%d %H:%M') if req.due_date else "—"}</td></tr>
                <tr><th>Created</th><td>{req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else "—"}</td></tr>
                <tr><th>Description</th><td>{req.description or ""}</td></tr>
            </table>
        </div>
        {wo_html}
        {completion_html}
        {verification_html}
        <div class="card">
            <h5 class="card-title">📜 Activity Timeline</h5>
            <div class="timeline">
                {timeline_html or "<p>No activity</p>"}
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card">
            <h5 class="card-title">Actions</h5>
            {actions or '<p style="color:#94a3b8;">No actions available</p>'}
        </div>
    </div>
    </div>
    '''
    return page("Request Detail", content)


# ══════════════════════════════════════════════════════════════
# APPROVE / REJECT / VERIFY
# ══════════════════════════════════════════════════════════════
@app.route("/requests/<int:req_id>/approve", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)

        if req.status != "Pending":
            flash("Request is not pending", "warning")
            return redirect(url_for("request_detail", req_id=req_id))

        # ✅ Update request
        req.status = "Approved"
        req.manager_id = current_user.id
        req.approved_at = datetime.utcnow()
        req.approved_by_id = current_user.id

        log_status_change(req.id, "Approved",
                          notes=f"Approved by {current_user.full_name}")
        log_audit("Approve", "MaintenanceRequest", req.id, "Pending", "Approved")

        # ✅ Auto-create Work Order (only if none exists)
        existing_wo = WorkOrder.query.filter_by(request_id=req.id).first()
        if not existing_wo:
            wo = WorkOrder(
                work_order_no=work_order_no_generator(),
                request_id=req.id,
                assigned_to_id=None,
                status="Pending",
            )
            db.session.add(wo)
            db.session.flush()
            log_audit("Create", "WorkOrder", wo.id, new_value=wo.work_order_no)
            log_status_change(req.id, "WO Created",
                              notes=f"WO: {wo.work_order_no} (unassigned)",
                              work_order_id=wo.id)
        else:
            wo = existing_wo

        # ✅ Notify all maintenance staff
        notify_maintenance_staff(req, wo)

        # ✅ Notify requester
        notify_users(
            [req.requested_by_id], req.id,
            "Request Approved",
            f"Your request {req.request_no} has been approved.",
            "Approved", link=url_for("request_detail", req_id=req.id),
        )

        db.session.commit()
        flash("✅ Request approved! Work order created and staff notified.", "success")
    except Exception as e:
        db.session.rollback()
        print("❌ Approval error:", traceback.format_exc())
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/reject", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_reject(req_id):
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)
        if req.status != "Pending":
            flash("Request is not pending", "warning")
            return redirect(url_for("request_detail", req_id=req_id))

        reason = request.form.get("reason", "").strip()

        req.status = "Rejected"
        req.rejected_at = datetime.utcnow()
        req.rejected_by_id = current_user.id
        req.rejection_reason = reason
        req.manager_id = current_user.id

        log_status_change(req.id, "Rejected",
                          notes=f"Rejected by {current_user.full_name}: {reason}")
        log_audit("Reject", "MaintenanceRequest", req.id, "Pending", "Rejected")

        notify_users(
            [req.requested_by_id], req.id,
            "Request Rejected",
            f"Your request {req.request_no} was rejected. Reason: {reason or 'N/A'}",
            "Rejected", link=url_for("request_detail", req_id=req.id),
        )

        db.session.commit()
        flash("Request rejected", "warning")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("request_detail", req_id=req_id))


@app.route("/requests/<int:req_id>/verify", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_verify(req_id):
    """Verify the WO. Notify requesting department."""
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)
        wo = WorkOrder.query.filter_by(request_id=req.id).first()

        if not wo:
            flash("No work order found", "warning")
            return redirect(url_for("request_detail", req_id=req_id))

        note = request.form.get("verification_note", "").strip()
        now = datetime.utcnow()

        wo.status = "Verified"
        wo.verified_at = now
        wo.verified_by_id = current_user.id
        wo.verification_note = note

        req.status = "Verified"
        req.verified_at = now
        req.verified_by_id = current_user.id
        req.verification_note = note

        log_status_change(req.id, "Verified",
                          notes=f"Verified by {current_user.full_name}: {note}",
                          work_order_id=wo.id)
        log_audit("Verify", "MaintenanceRequest", req.id, "Completed", "Verified")

        # ✅ NOTIFY REQUESTING DEPARTMENT ⭐
        notify_requesting_department(req, wo, action="verified")

        # Notify assigned staff
        if wo.assigned_to_id:
            notify_users(
                [wo.assigned_to_id], req.id,
                "Work Verified",
                f"WO {wo.work_order_no} verified.",
                "Verified", link=url_for("workorder_detail", wo_id=wo.id),
            )

        db.session.commit()
        flash("✅ Work verified! Requesting department notified.", "success")
    except Exception as e:
        db.session.rollback()
        print("❌ Verify error:", traceback.format_exc())
        flash(f"Error: {str(e)}", "danger")

    return redirect(url_for("request_detail", req_id=req_id))


# ══════════════════════════════════════════════════════════════
# WORK ORDERS
# ══════════════════════════════════════════════════════════════
@app.route("/workorders")
@login_required
def workorders_list():
    try:
        if current_user.role == "DEPARTMENT":
            return redirect(url_for("department_dashboard"))
        if current_user.role == "EMPLOYEE":
            return redirect(url_for("employee_dashboard"))

        base = WorkOrder.query.filter(WorkOrder.is_deleted == False)

        if current_user.role in STAFF_ROLES:
            wos = base.filter(
                db.or_(
                    WorkOrder.assigned_to_id == current_user.id,
                    WorkOrder.assigned_to_id.is_(None),
                )
            ).order_by(WorkOrder.created_at.desc()).all()
        else:
            wos = base.order_by(WorkOrder.created_at.desc()).all()

        rows = ""
        for wo in wos:
            assigned = wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"
            badge = "success" if wo.status in ["Completed", "Verified", "Closed"] else \
                    "warning" if wo.status in ["Pending", "Assigned"] else "info"
            rows += f'''
            <tr>
            <td><a href="/workorders/{wo.id}" style="color:#f59e0b;"><b>{wo.work_order_no}</b></a></td>
            <td>{wo.request.location_name if wo.request else "—"}</td>
            <td>{wo.request.working_item.name if wo.request and wo.request.working_item else "—"}</td>
            <td>{wo.request.priority if wo.request else "—"}</td>
            <td><span class="badge bg-{badge}">{wo.status}</span></td>
            <td>{assigned}</td>
            </tr>'''

        content = f'''
        <h3 style="color:#f59e0b;">🔧 Work Orders</h3>
        <div class="card">
        <div class="table-responsive">
        <table class="table table-hover">
        <thead><tr><th>Order #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Assigned</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="text-center">No work orders</td></tr>'}</tbody>
        </table>
        </div>
        </div>
        '''
        return page("Work Orders", content)
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
        return redirect(url_for("index"))


@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = MaintenanceRequest.query.get(req_id) if req_id else None
    users = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    user_options = "".join(f'<option value="{u.id}">{u.full_name} ({u.role})</option>' for u in users)

    if request.method == "POST":
        try:
            request_id = request.form.get("request_id", type=int)
            assigned_to_id = request.form.get("assigned_to_id", type=int)
            work_performed = request.form.get("work_performed", "").strip()

            if not assigned_to_id:
                flash("Select a staff member", "danger")
                return redirect(url_for("workorder_create", request_id=request_id))

            req = MaintenanceRequest.query.get_or_404(request_id)

            if req.status not in ["Approved", "Assigned"]:
                flash("Request must be approved first", "danger")
                return redirect(url_for("request_detail", req_id=request_id))

            assigned_user = User.query.get(assigned_to_id)

            # ✅ Duplicate prevention
            existing_wo = WorkOrder.query.filter_by(request_id=req.id)\
                .filter(WorkOrder.status != "Completed").first()

            if existing_wo:
                wo = existing_wo
                wo.assigned_to_id = assigned_to_id
                wo.status = "Assigned"
                if work_performed:
                    wo.work_performed = work_performed
                log_audit("Reassign", "WorkOrder", wo.id, new_value=assigned_user.full_name if assigned_user else "")
            else:
                wo = WorkOrder(
                    work_order_no=work_order_no_generator(),
                    request_id=req.id,
                    assigned_to_id=assigned_to_id,
                    status="Assigned",
                    work_performed=work_performed,
                )
                db.session.add(wo)
                db.session.flush()
                log_audit("Create", "WorkOrder", wo.id, new_value=wo.work_order_no)

            req.status = "Assigned"
            req.assigned_to_id = assigned_to_id

            log_status_change(req.id, "Assigned",
                              notes=f"Assigned to {assigned_user.full_name if assigned_user else 'Unknown'}",
                              work_order_id=wo.id)

            # ✅ Notify ONLY assigned staff
            if assigned_user:
                notify_assigned_staff(req, wo, assigned_user)

            # Notify requester
            if req.requested_by_id:
                notify_users(
                    [req.requested_by_id], req.id,
                    "Staff Assigned",
                    f"Staff assigned to your request {req.request_no}.",
                    "Assigned", link=url_for("workorder_detail", wo_id=wo.id),
                )

            db.session.commit()
            flash(f"✅ Assigned to {assigned_user.full_name if assigned_user else 'staff'}!", "success")
            return redirect(url_for("workorder_detail", wo_id=wo.id))

        except Exception as e:
            db.session.rollback()
            print("❌ WO assign error:", traceback.format_exc())
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("workorder_create", request_id=request_id))

    content = f'''
    <h3 style="color:#f59e0b;">📋 Assign Staff to Work Order</h3>
    <div class="card">
    <form method="post">
    <input type="hidden" name="request_id" value="{req.id if req else ''}">
    <div class="mb-3"><label class="form-label">Request</label>
    <input class="form-control" value="{req.request_no if req else ''}" disabled></div>
    <div class="mb-3"><label class="form-label">Location</label>
    <input class="form-control" value="{req.location_name if req else ''}" disabled></div>
    <div class="mb-3"><label class="form-label">Assign To *</label>
    <select class="form-select" name="assigned_to_id" required>
        <option value="">-- Select Staff --</option>{user_options}
    </select></div>
    <div class="mb-3"><label class="form-label">Instructions</label>
    <textarea class="form-control" name="work_performed" rows="3"></textarea></div>
    <button class="btn btn-primary"><i class="fas fa-save"></i> Assign</button>
    </form>
    </div>
    '''
    return page("Assign Work Order", content)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    req = wo.request

    # Timeline
    history = StatusHistory.query.filter(
        db.or_(
            StatusHistory.request_id == req.id if req else False,
            StatusHistory.work_order_id == wo.id,
        )
    ).order_by(StatusHistory.timestamp.asc()).all()

    timeline_html = ""
    for h in history:
        user_name = h.user.full_name if h.user else "System"
        timeline_html += f'''
        <div class="timeline-item">
            <span class="time">{h.timestamp.strftime('%Y-%m-%d %H:%M') if h.timestamp else ''} — {user_name}</span>
            <div class="content">
                <b>{h.status}</b>
                {f'<br><span style="color:#94a3b8;">{h.notes}</span>' if h.notes else ''}
            </div>
        </div>'''

    actions = ""
    if current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id:
        if wo.status == "Assigned":
            actions += f'<a class="btn btn-warning w-100 mb-2" href="/workorders/{wo.id}/start"><i class="fas fa-play"></i> Start Work</a>'
        if wo.status == "In Progress":
            actions += f'<a class="btn btn-success w-100 mb-2" href="/workorders/{wo.id}/complete"><i class="fas fa-check"></i> Complete Work</a>'

    if current_user.role in ["MANAGER", "ADMIN"] and wo.status == "Completed":
        actions += f'''
        <form method="post" action="/workorders/{wo.id}/verify" class="mb-2">
            <input type="text" name="verification_note" class="form-control mb-2" placeholder="Verification note">
            <button class="btn btn-info w-100"><i class="fas fa-check-double"></i> Verify & Notify Department</button>
        </form>'''

    completion_html = ""
    if wo.completion_notes:
        completion_html = f'''
        <div class="completion-evidence">
            <h6>✅ Completion Details</h6>
            <p><b>Work Performed:</b> {wo.completion_notes}</p>
            <p><b>Labor Hours:</b> {wo.labor_hours}</p>
            {f'<p><b>Completed By:</b> {wo.completed_by.full_name}</p>' if wo.completed_by else ''}
            {f'<p><b>Completed:</b> {wo.completed_at.strftime("%Y-%m-%d %H:%M")}</p>' if wo.completed_at else ''}
            {f'<p><img src="/static/uploads/maintenance/{wo.completion_photo}" class="img-fluid rounded mt-2" style="max-height:250px;"></p>' if wo.completion_photo else ''}
        </div>'''

    verification_html = ""
    if wo.verified_at:
        verification_html = f'''
        <div class="card" style="border-color: rgba(6,182,212,0.4);">
            <h6 style="color:#06b6d4;">✔ Manager Verification</h6>
            <p><b>Verified By:</b> {wo.verified_by.full_name if wo.verified_by else "—"}</p>
            <p><b>Date:</b> {wo.verified_at.strftime("%Y-%m-%d %H:%M")}</p>
            {f'<p><b>Note:</b> {wo.verification_note}</p>' if wo.verification_note else ''}
        </div>'''

    content = f'''
    <h3 style="color:#f59e0b;">🔧 Work Order {wo.work_order_no}</h3>
    <div class="row">
    <div class="col-md-8">
        <div class="card">
            <table class="table">
                <tr><th style="width:150px;">Request</th><td><a href="/requests/{req.id}" style="color:#f59e0b;">{req.request_no if req else "—"}</a></td></tr>
                <tr><th>Department</th><td>{req.department.name if req and req.department else "—"}</td></tr>
                <tr><th>Location</th><td>{req.location_name if req else "—"}</td></tr>
                <tr><th>Item</th><td>{req.working_item.name if req and req.working_item else "—"}</td></tr>
                <tr><th>Category</th><td>{req.category.name if req and req.category else "—"}</td></tr>
                <tr><th>Priority</th><td>{req.priority if req else "—"}</td></tr>
                <tr><th>Status</th><td><b>{wo.status}</b></td></tr>
                <tr><th>Assigned To</th><td>{wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"}</td></tr>
                <tr><th>Description</th><td>{req.description if req else ""}</td></tr>
                {f'<tr><th>Started</th><td>{wo.started_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' if wo.started_at else ''}
            </table>
        </div>
        {completion_html}
        {verification_html}
        <div class="card">
            <h5 class="card-title">📜 Activity Timeline</h5>
            <div class="timeline">
                {timeline_html or "<p>No activity</p>"}
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card">
            <h5 class="card-title">Actions</h5>
            {actions or '<p style="color:#94a3b8;">No actions available</p>'}
        </div>
    </div>
    </div>
    '''
    return page("Work Order", content)


@app.route("/workorders/<int:wo_id>/start", methods=["GET", "POST"])
@login_required
def workorder_start(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        if current_user.id != wo.assigned_to_id:
            flash("Not authorized", "danger")
            return redirect(url_for("workorder_detail", wo_id=wo_id))
        if wo.status != "Assigned":
            flash("Cannot start", "warning")
            return redirect(url_for("workorder_detail", wo_id=wo_id))

        wo.status = "In Progress"
        wo.started_at = datetime.utcnow()

        if wo.request:
            wo.request.status = "In Progress"

        log_status_change(wo.request_id, "In Progress",
                          notes=f"Started by {current_user.full_name}",
                          work_order_id=wo.id)
        log_audit("Start", "WorkOrder", wo.id, "Assigned", "In Progress")

        db.session.commit()
        flash("✅ Work started!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))


@app.route("/workorders/<int:wo_id>/complete", methods=["GET", "POST"])
@login_required
def workorder_complete(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    if current_user.id != wo.assigned_to_id:
        flash("Not authorized", "danger")
        return redirect(url_for("workorder_detail", wo_id=wo_id))
    if wo.status != "In Progress":
        flash("Not in progress", "warning")
        return redirect(url_for("workorder_detail", wo_id=wo_id))

    if request.method == "POST":
        try:
            note = request.form.get("completion_note", "").strip()
            hours = float(request.form.get("labor_hours", 0) or 0)

            if not note:
                flash("Completion note required", "danger")
                return redirect(url_for("workorder_complete", wo_id=wo_id))

            filename = None
            file = request.files.get("photo")
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[-1].lower()
                filename = secure_filename(f"wo_{wo.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            now = datetime.utcnow()
            wo.completion_notes = note
            wo.labor_hours = hours
            wo.status = "Completed"
            wo.completed_by_id = current_user.id
            wo.completed_at = now
            if filename:
                wo.completion_photo = filename

            if wo.request:
                wo.request.status = "Completed"
                wo.request.completed_date = now
                wo.request.completion_note = note

            log_status_change(wo.request_id, "Completed",
                              notes=f"Completed by {current_user.full_name}",
                              work_order_id=wo.id)
            log_audit("Complete", "WorkOrder", wo.id, "In Progress", "Completed")

            # ✅ Notify managers
            managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
            notify_users(
                [u.id for u in managers], wo.request_id,
                "Work Completed",
                f"WO {wo.work_order_no} completed by {current_user.full_name}.",
                "Completed", link=url_for("workorder_detail", wo_id=wo.id),
            )

            db.session.commit()
            flash("✅ Work completed! Manager will verify.", "success")
            return redirect(url_for("workorder_detail", wo_id=wo_id))

        except Exception as e:
            db.session.rollback()
            print("❌ Complete error:", traceback.format_exc())
            flash(f"Error: {str(e)}", "danger")
            return redirect(url_for("workorder_complete", wo_id=wo_id))

    content = f'''
    <h3 style="color:#f59e0b;">Complete Work Order {wo.work_order_no}</h3>
    <div class="card">
    <form method="post" enctype="multipart/form-data">
        <div class="mb-3"><label class="form-label">Completion Note *</label>
        <textarea name="completion_note" class="form-control" rows="4" required></textarea></div>
        <div class="mb-3"><label class="form-label">Photo</label>
        <input type="file" name="photo" accept="image/*" capture="environment" class="form-control"></div>
        <div class="mb-3"><label class="form-label">Labor Hours</label>
        <input type="number" step="0.5" name="labor_hours" class="form-control" value="0"></div>
        <button class="btn btn-success btn-lg w-100"><i class="fas fa-check-circle"></i> Mark Completed</button>
    </form>
    </div>
    '''
    return page("Complete Work Order", content)


@app.route("/workorders/<int:wo_id>/verify", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def workorder_verify(wo_id):
    """Verify via WO. Notify department."""
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        req = wo.request
        if not req:
            flash("No request linked", "danger")
            return redirect(url_for("workorder_detail", wo_id=wo_id))

        note = request.form.get("verification_note", "").strip()
        now = datetime.utcnow()

        wo.status = "Verified"
        wo.verified_at = now
        wo.verified_by_id = current_user.id
        wo.verification_note = note

        req.status = "Verified"
        req.verified_at = now
        req.verified_by_id = current_user.id
        req.verification_note = note

        log_status_change(req.id, "Verified",
                          notes=f"Verified by {current_user.full_name}: {note}",
                          work_order_id=wo.id)
        log_audit("Verify", "WorkOrder", wo.id, "Completed", "Verified")

        # ⭐ Notify requesting department
        notify_requesting_department(req, wo, action="verified")

        # Notify assigned staff
        if wo.assigned_to_id:
            notify_users(
                [wo.assigned_to_id], req.id,
                "Work Verified",
                f"WO {wo.work_order_no} verified.",
                "Verified", link=url_for("workorder_detail", wo_id=wo.id),
            )

        db.session.commit()
        flash("✅ Verified! Requesting department notified.", "success")
    except Exception as e:
        db.session.rollback()
        print("❌ Verify error:", traceback.format_exc())
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))


# ══════════════════════════════════════════════════════════════
# SOFT DELETE + ADMIN TRASH
# ══════════════════════════════════════════════════════════════
@app.route("/requests/<int:req_id>/delete", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def request_soft_delete(req_id):
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)
        req.is_deleted = True
        req.deleted_at = datetime.utcnow()
        req.deleted_by_id = current_user.id
        log_audit("SoftDelete", "MaintenanceRequest", req.id, None, "deleted")
        db.session.commit()
        flash("Request moved to trash", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("requests_list"))


@app.route("/workorders/<int:wo_id>/delete", methods=["POST"])
@role_required("MANAGER", "ADMIN")
def workorder_soft_delete(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        wo.is_deleted = True
        wo.deleted_at = datetime.utcnow()
        wo.deleted_by_id = current_user.id
        log_audit("SoftDelete", "WorkOrder", wo.id, None, "deleted")
        db.session.commit()
        flash("Work order moved to trash", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("workorders_list"))


@app.route("/admin/trash")
@role_required("ADMIN")
def deleted_records():
    deleted_reqs = MaintenanceRequest.query.filter_by(is_deleted=True)\
        .order_by(MaintenanceRequest.deleted_at.desc()).all()
    deleted_wos = WorkOrder.query.filter_by(is_deleted=True)\
        .order_by(WorkOrder.deleted_at.desc()).all()

    req_rows = "".join(f'''
    <tr>
    <td>{r.request_no}</td>
    <td>{r.location_name}</td>
    <td>{r.status}</td>
    <td>{r.deleted_at.strftime('%Y-%m-%d %H:%M') if r.deleted_at else ''}</td>
    <td>
        <form method="post" action="/admin/trash/restore/request/{r.id}" class="d-inline">
            <button class="btn btn-sm btn-success">Restore</button>
        </form>
        <form method="post" action="/admin/trash/purge/request/{r.id}" class="d-inline"
              onsubmit="return confirm('Permanently delete?')">
            <button class="btn btn-sm btn-danger">Delete</button>
        </form>
    </td>
    </tr>''' for r in deleted_reqs)

    wo_rows = "".join(f'''
    <tr>
    <td>{w.work_order_no}</td>
    <td>{w.request.request_no if w.request else '—'}</td>
    <td>{w.status}</td>
    <td>{w.deleted_at.strftime('%Y-%m-%d %H:%M') if w.deleted_at else ''}</td>
    <td>
        <form method="post" action="/admin/trash/restore/workorder/{w.id}" class="d-inline">
            <button class="btn btn-sm btn-success">Restore</button>
        </form>
        <form method="post" action="/admin/trash/purge/workorder/{w.id}" class="d-inline"
              onsubmit="return confirm('Permanently delete?')">
            <button class="btn btn-sm btn-danger">Delete</button>
        </form>
    </td>
    </tr>''' for w in deleted_wos)

    content = f'''
    <h3 style="color:#f59e0b;">🗑 Trash / Deleted Records</h3>

    <div class="card">
    <h5 class="card-title">Deleted Requests ({len(deleted_reqs)})</h5>
    <table class="table table-hover">
    <thead><tr><th>Request #</th><th>Location</th><th>Status</th><th>Deleted At</th><th>Actions</th></tr></thead>
    <tbody>{req_rows or '<tr><td colspan="5" class="text-center">Empty</td></tr>'}</tbody>
    </table>
    </div>

    <div class="card">
    <h5 class="card-title">Deleted Work Orders ({len(deleted_wos)})</h5>
    <table class="table table-hover">
    <thead><tr><th>WO #</th><th>Request</th><th>Status</th><th>Deleted At</th><th>Actions</th></tr></thead>
    <tbody>{wo_rows or '<tr><td colspan="5" class="text-center">Empty</td></tr>'}</tbody>
    </table>
    </div>
    '''
    return page("Trash", content)


@app.route("/admin/trash/restore/request/<int:req_id>", methods=["POST"])
@role_required("ADMIN")
def restore_request(req_id):
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)
        req.is_deleted = False
        req.deleted_at = None
        req.deleted_by_id = None
        log_audit("Restore", "MaintenanceRequest", req.id, "deleted", "restored")
        db.session.commit()
        flash("Request restored", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("deleted_records"))


@app.route("/admin/trash/restore/workorder/<int:wo_id>", methods=["POST"])
@role_required("ADMIN")
def restore_workorder(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        wo.is_deleted = False
        wo.deleted_at = None
        wo.deleted_by_id = None
        log_audit("Restore", "WorkOrder", wo.id, "deleted", "restored")
        db.session.commit()
        flash("Work order restored", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("deleted_records"))


@app.route("/admin/trash/purge/request/<int:req_id>", methods=["POST"])
@role_required("ADMIN")
def purge_request(req_id):
    try:
        req = MaintenanceRequest.query.get_or_404(req_id)
        log_audit("PermanentDelete", "MaintenanceRequest", req.id, req.request_no, None)
        # Also delete linked WO
        wo = WorkOrder.query.filter_by(request_id=req.id).first()
        if wo:
            WorkOrderPart.query.filter_by(work_order_id=wo.id).delete()
            db.session.delete(wo)
        db.session.delete(req)
        db.session.commit()
        flash("Request permanently deleted", "warning")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("deleted_records"))


@app.route("/admin/trash/purge/workorder/<int:wo_id>", methods=["POST"])
@role_required("ADMIN")
def purge_workorder(wo_id):
    try:
        wo = WorkOrder.query.get_or_404(wo_id)
        log_audit("PermanentDelete", "WorkOrder", wo.id, wo.work_order_no, None)
        WorkOrderPart.query.filter_by(work_order_id=wo.id).delete()
        db.session.delete(wo)
        db.session.commit()
        flash("Work order permanently deleted", "warning")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("deleted_records"))


# ══════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ══════════════════════════════════════════════════════════════
@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(100).all()

    rows = ""
    for n in notifs:
        cls = "" if n.is_read else "table-warning"
        link = n.link or "#"
        rows += f'''
        <tr class="{cls}">
        <td><a href="{link}" style="color:#f59e0b;"><b>{n.title}</b></a></td>
        <td>{n.message}</td>
        <td>{n.notification_type}</td>
        <td>{n.created_at.strftime('%Y-%m-%d %H:%M') if n.created_at else ''}</td>
        <td>{'<a class="btn btn-sm btn-primary" href="/notifications/mark-read/' + str(n.id) + '">Read</a>' if not n.is_read else "✓"}</td>
        </tr>'''

    content = f'''
    <h3 style="color:#f59e0b;">🔔 Notifications</h3>
    <div class="card">
    <div class="table-responsive">
    <table class="table table-hover">
    <thead><tr><th>Title</th><th>Message</th><th>Type</th><th>Date</th><th>Action</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="5" class="text-center">No notifications</td></tr>'}</tbody>
    </table>
    </div>
    </div>
    '''
    return page("Notifications", content)


@app.route("/notifications/mark-read/<int:n_id>")
@login_required
def notification_mark_read(n_id):
    try:
        n = Notification.query.get_or_404(n_id)
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
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("notifications"))


# ══════════════════════════════════════════════════════════════
# OTHER PAGES
# ══════════════════════════════════════════════════════════════
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    rows = "".join(f'<tr><td>{r.room_number}</td><td>{r.floor}</td><td>{r.status}</td></tr>' for r in rooms)
    return page("Rooms", f'<h3 style="color:#f59e0b;">Rooms</h3><div class="card"><table class="table"><thead><tr><th>Room</th><th>Floor</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    rows = "".join(f'<tr><td>{a.name}</td><td>{a.department}</td></tr>' for a in areas)
    return page("Areas", f'<h3 style="color:#f59e0b;">Areas</h3><div class="card"><table class="table"><thead><tr><th>Name</th><th>Dept</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = "".join(f'<tr><td>{p.part_name}</td><td>{p.quantity}</td><td>{p.unit}</td></tr>' for p in parts)
    return page("Inventory", f'<h3 style="color:#f59e0b;">Inventory</h3><div class="card"><table class="table"><thead><tr><th>Part</th><th>Qty</th><th>Unit</th></tr></thead><tbody>{rows or "<tr><td colspan=3>No parts</td></tr>"}</tbody></table></div>')


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    emps = Employee.query.all()
    rows = "".join(f'<tr><td>{e.id}</td><td>{e.name}</td><td>{e.job_title}</td></tr>' for e in emps)
    return page("Employees", f'<h3 style="color:#f59e0b;">Employees</h3><div class="card"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Title</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    rows = "".join(f'<tr><td>{u.username}</td><td>{u.full_name}</td><td>{u.role}</td><td>{u.department.name if u.department else "—"}</td></tr>' for u in users)
    return page("Users", f'<h3 style="color:#f59e0b;">Users</h3><div class="card"><table class="table"><thead><tr><th>User</th><th>Name</th><th>Role</th><th>Dept</th></tr></thead><tbody>{rows}</tbody></table></div>')


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join(f'<tr><td>{a.user.full_name if a.user else "System"}</td><td>{a.action}</td><td>{a.object_type or ""}</td><td>{a.created_at.strftime("%Y-%m-%d %H:%M")}</td></tr>' for a in logs)
    return page("Audit", f'<h3 style="color:#f59e0b;">Audit Log</h3><div class="card"><table class="table"><thead><tr><th>User</th><th>Action</th><th>Object</th><th>Date</th></tr></thead><tbody>{rows or "<tr><td colspan=4>No logs</td></tr>"}</tbody></table></div>')


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join(f'<tr><td>{b}</td></tr>' for b in backups)
    content = f'<h3 style="color:#f59e0b;">Backups</h3><form method="post" action="/admin/backup/now" class="mb-3"><button class="btn btn-primary">Backup Now</button></form><div class="card"><table class="table"><thead><tr><th>File</th></tr></thead><tbody>{rows or "<tr><td>No backups</td></tr>"}</tbody></table></div>'
    return page("Backups", content)


@app.route("/admin/backup/now", methods=["POST"])
@role_required("ADMIN")
def backup_now():
    try:
        filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        src = sqlite3.connect(os.path.join(BASE_DIR, "hotel_maintenance.db"))
        dst = sqlite3.connect(os.path.join(BACKUP_FOLDER, filename))
        with dst:
            src.backup(dst)
        src.close(); dst.close()
        flash(f"Backup: {filename}", "success")
    except Exception as e:
        flash(f"Error: {str(e)}", "danger")
    return redirect(url_for("backup_page"))


@app.route("/reports")
@login_required
def reports():
    total = MaintenanceRequest.query.filter_by(is_deleted=False).count()
    pending = MaintenanceRequest.query.filter_by(is_deleted=False, status="Pending").count()
    done = MaintenanceRequest.query.filter_by(is_deleted=False, status="Completed").count()
    verified = MaintenanceRequest.query.filter_by(is_deleted=False, status="Verified").count()
    content = f'''
    <h3 style="color:#f59e0b;">Reports</h3>
    <div class="row g-3 mb-4">
      <div class="col-3"><div class="metric-card"><div class="metric-value">{total}</div><div class="metric-label">Total</div></div></div>
      <div class="col-3"><div class="metric-card"><div class="metric-value">{pending}</div><div class="metric-label">Pending</div></div></div>
      <div class="col-3"><div class="metric-card"><div class="metric-value">{done}</div><div class="metric-label">Completed</div></div></div>
      <div class="col-3"><div class="metric-card"><div class="metric-value">{verified}</div><div class="metric-label">Verified</div></div></div>
    </div>
    '''
    return page("Reports", content)


@app.route("/debug")
def debug():
    return jsonify({
        "users": User.query.count(),
        "staff_users": User.query.filter(User.role.in_(STAFF_ROLES)).count(),
        "requests": MaintenanceRequest.query.count(),
        "active_requests": MaintenanceRequest.query.filter_by(is_deleted=False).count(),
        "deleted_requests": MaintenanceRequest.query.filter_by(is_deleted=True).count(),
        "work_orders": WorkOrder.query.count(),
        "unassigned_wos": WorkOrder.query.filter(WorkOrder.assigned_to_id.is_(None)).count(),
        "notifications": Notification.query.count(),
        "status_history": StatusHistory.query.count(),
    })


@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel", "short_name": "RoriMaint", "start_url": "/dashboard", "display": "standalone", "background_color": "#0f172a", "theme_color": "#f59e0b", "icons": []})


@app.route("/sw.js")
def sw():
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


@app.errorhandler(500)
def internal_error(e):
    tb = traceback.format_exc()
    print("❌ 500:", tb)
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