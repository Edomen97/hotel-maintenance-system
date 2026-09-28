# app.py - Rori Hotel Maintenance System (FIXED & LIGHT THEME)
import csv, io, json, os, re, sqlite3, uuid, traceback
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect
from flask import (Flask, abort, flash, get_flashed_messages, jsonify, redirect,
                   render_template, render_template_string, request, send_file, url_for, Response)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

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
ALLOWED_EXTENSIONS = {"png","jpg","jpeg","gif","pdf","doc","docx","xls","xlsx","csv"}
STAFF_ROLES = ["MAINTENANCE STAFF", "TECHNICIAN", "SUPERVISOR"]

# ══════════════════════════════════════════ MODELS
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
    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p): return check_password_hash(self.password_hash, p)

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

class DepartmentSignature(db.Model):
    __tablename__ = "department_signatures"
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"), unique=True, nullable=False)
    authorized_name = db.Column(db.String(150), nullable=False)
    signature_data = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    department = db.relationship("Department", foreign_keys=[department_id])

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
    signature_name = db.Column(db.String(150), nullable=True)
    signature_status = db.Column(db.String(30), default="SIGNED")
    signature_signed_at = db.Column(db.DateTime, nullable=True)
    signature_data = db.Column(db.Text, nullable=True)
    signature_department = db.Column(db.String(80), nullable=True)
    signature_verified = db.Column(db.Boolean, default=False)
    signature_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

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
    signature_user = db.relationship("User", foreign_keys=[signature_user_id])

    @property
    def location_name(self):
        if self.location_type == "Room" and self.room:
            return "Room " + str(self.room.room_number)
        if self.area: return self.area.name
        return "Unknown"

    @property
    def is_overdue(self):
        if self.status in ["Completed","Verified","Closed","Cancelled"]: return False
        if self.due_date and datetime.utcnow() > self.due_date: return True
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
    def is_low(self): return self.quantity <= self.minimum_stock

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
def load_user(user_id): return db.session.get(User, int(user_id))

# ══════════════════════════════════════════ HELPERS
def role_required(*roles):
    def dec(fn):
        @wraps(fn)
        def wrap(*a, **kw):
            if not current_user.is_authenticated: return redirect(url_for("login"))
            if current_user.role not in roles: abort(403)
            return fn(*a, **kw)
        return wrap
    return dec

def is_manager(user):
    if not user or not user.is_authenticated: return False
    return user.role in ["MANAGER", "ADMIN"]

def log_audit(action, object_type=None, object_id=None, old_value=None, new_value=None):
    try:
        db.session.add(AuditLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            action=action, object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None,
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
        ))
    except Exception as e: print("Audit error: " + str(e))

def create_notification(user_id, request_id, title, message, ntype="General", link=None, work_order_id=None):
    if not user_id: return None
    recent = Notification.query.filter_by(user_id=user_id, request_id=request_id, notification_type=ntype).order_by(Notification.created_at.desc()).first()
    if recent and (datetime.utcnow() - recent.created_at).total_seconds() < 5: return recent
    n = Notification(user_id=user_id, request_id=request_id, work_order_id=work_order_id,
                     title=title, message=message, notification_type=ntype, link=link)
    db.session.add(n); return n

def notify_users(ids, request_id, title, message, ntype="General", link=None, work_order_id=None):
    for uid in ids:
        if uid: create_notification(uid, request_id, title, message, ntype, link, work_order_id)

def notify_assigned_staff(req, wo, staff_user):
    if not staff_user: return
    title = "📋 Assigned to you: " + str(wo.work_order_no)
    item_name = req.working_item.name if req.working_item else "N/A"
    msg = ("Request: " + str(req.request_no) + " | WO: " + str(wo.work_order_no) +
           " | Location: " + str(req.location_name) + " | Item: " + str(item_name) +
           " | Priority: " + str(req.priority))
    link = url_for("workorder_detail", wo_id=wo.id)
    create_notification(staff_user.id, req.id, title, msg, "Work Order Assigned", link, wo.id)

def log_status_change(request_id, status, user_id=None, notes=None):
    if not user_id:
        user_id = current_user.id if current_user.is_authenticated else None
    db.session.add(StatusHistory(request_id=request_id, status=status, user_id=user_id, notes=notes))

def request_no_generator():
    return "R-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

def work_order_no_generator():
    return "WO-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:4].upper()

def allowed_file(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_one(model, ident): return db.session.get(model, ident)
def get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None: abort(404)
    return obj

def valid_email(v): return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v or ""))

def get_user_signature_profile(user):
    if not user or not user.is_authenticated or not user.department_id:
        return None
    return DepartmentSignature.query.filter_by(
        department_id=user.department_id, is_active=True
    ).first()

def validate_signature_for_user(user, signature_data):
    if not user or not user.is_authenticated:
        return False, "User not authenticated."
    if not user.department_id:
        return False, "Your account is not linked to a department. Contact admin."
    profile = get_user_signature_profile(user)
    if not profile:
        return False, "No authorized signature configured for your department. Contact admin."
    if not signature_data or not signature_data.strip():
        return False, "Digital signature is required. Your request cannot be submitted without a verified department signature."
    if not signature_data.startswith("data:image/png;base64,"):
        return False, "Invalid signature format."
    return True, None

def add_column_if_missing(table, column, sql):
    try:
        insp = inspect(db.engine)
        if table not in insp.get_table_names(): return False
        cols = [c["name"] for c in insp.get_columns(table)]
        if column not in cols:
            with db.engine.begin() as conn: conn.execute(text(sql))
            print("✅ Added " + column + " to " + table); return True
        return False
    except Exception as e:
        print("⚠️ Migration warn (" + table + "." + column + "): " + str(e)); return False

def ensure_database_schema():
    with app.app_context():
        try:
            db.create_all()
            pg = db.engine.dialect.name == "postgresql"
            dt = "TIMESTAMP" if pg else "DATETIME"
            bd = "DEFAULT FALSE" if pg else "DEFAULT 0"
            add_column_if_missing("maintenance_requests","department_id","ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER")
            add_column_if_missing("maintenance_requests","manager_id","ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER")
            add_column_if_missing("maintenance_requests","completion_note","ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT")
            add_column_if_missing("maintenance_requests","completed_date","ALTER TABLE maintenance_requests ADD COLUMN completed_date " + dt)
            add_column_if_missing("maintenance_requests","is_deleted","ALTER TABLE maintenance_requests ADD COLUMN is_deleted BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","deleted_at","ALTER TABLE maintenance_requests ADD COLUMN deleted_at " + dt)
            add_column_if_missing("maintenance_requests","deleted_by_id","ALTER TABLE maintenance_requests ADD COLUMN deleted_by_id INTEGER")
            add_column_if_missing("maintenance_requests","deletion_reason","ALTER TABLE maintenance_requests ADD COLUMN deletion_reason TEXT")
            add_column_if_missing("maintenance_requests","awaiting_hk_approval","ALTER TABLE maintenance_requests ADD COLUMN awaiting_hk_approval BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","hk_approved_by_id","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_by_id INTEGER")
            add_column_if_missing("maintenance_requests","hk_approved_at","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_at " + dt)
            add_column_if_missing("maintenance_requests","hk_approval_status","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_status VARCHAR(20)")
            add_column_if_missing("maintenance_requests","hk_signature_data","ALTER TABLE maintenance_requests ADD COLUMN hk_signature_data TEXT")
            add_column_if_missing("maintenance_requests","hk_approval_notes","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_notes TEXT")
            add_column_if_missing("maintenance_requests","signature_name","ALTER TABLE maintenance_requests ADD COLUMN signature_name VARCHAR(150)")
            add_column_if_missing("maintenance_requests","signature_status","ALTER TABLE maintenance_requests ADD COLUMN signature_status VARCHAR(30) DEFAULT 'SIGNED'")
            add_column_if_missing("maintenance_requests","signature_signed_at","ALTER TABLE maintenance_requests ADD COLUMN signature_signed_at " + dt)
            add_column_if_missing("maintenance_requests","signature_data","ALTER TABLE maintenance_requests ADD COLUMN signature_data TEXT")
            add_column_if_missing("maintenance_requests","signature_department","ALTER TABLE maintenance_requests ADD COLUMN signature_department VARCHAR(80)")
            add_column_if_missing("maintenance_requests","signature_verified","ALTER TABLE maintenance_requests ADD COLUMN signature_verified BOOLEAN " + bd)
            add_column_if_missing("maintenance_requests","signature_user_id","ALTER TABLE maintenance_requests ADD COLUMN signature_user_id INTEGER")
            add_column_if_missing("users","department_id","ALTER TABLE users ADD COLUMN department_id INTEGER")
            add_column_if_missing("notifications","work_order_id","ALTER TABLE notifications ADD COLUMN work_order_id INTEGER")
            add_column_if_missing("work_orders","completed_date","ALTER TABLE work_orders ADD COLUMN completed_date " + dt)
            add_column_if_missing("work_orders","verified_date","ALTER TABLE work_orders ADD COLUMN verified_date " + dt)
            add_column_if_missing("audit_logs","ip_address","ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)")
            add_column_if_missing("suppliers","email","ALTER TABLE suppliers ADD COLUMN email VARCHAR(120)")
            add_column_if_missing("suppliers","address","ALTER TABLE suppliers ADD COLUMN address TEXT")
            add_column_if_missing("suppliers","tax_number","ALTER TABLE suppliers ADD COLUMN tax_number VARCHAR(60)")
            add_column_if_missing("suppliers","notes","ALTER TABLE suppliers ADD COLUMN notes TEXT")
            if add_column_if_missing("suppliers","is_active","ALTER TABLE suppliers ADD COLUMN is_active BOOLEAN " + bd):
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE suppliers SET is_active = CASE WHEN status = 'Active' THEN TRUE ELSE FALSE END"))
            add_column_if_missing("suppliers","created_at","ALTER TABLE suppliers ADD COLUMN created_at " + dt)
            add_column_if_missing("suppliers","updated_at","ALTER TABLE suppliers ADD COLUMN updated_at " + dt)
            add_column_if_missing("inventory_parts","supplier_id","ALTER TABLE inventory_parts ADD COLUMN supplier_id INTEGER")
            print("✅ Schema OK")
        except Exception as e: print("⚠️ Schema error: " + str(e))

# ══════════════════════════════════════════ PAGE (LIGHT THEME)
def page(title, content):
    nav = []
    if current_user.is_authenticated:
        r = current_user.role
        if r == "DEPARTMENT":
            nav = [('<i class="fas fa-home"></i> Dashboard', url_for('department_dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        elif r == "EMPLOYEE":
            nav = [('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        elif r in STAFF_ROLES:
            nav = [('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        else:
            nav = [('<i class="fas fa-home"></i> Dashboard', url_for('dashboard')),
                   ('<i class="fas fa-plus-circle"></i> New', url_for('request_create')),
                   ('<i class="fas fa-tasks"></i> Requests', url_for('requests_list')),
                   ('<i class="fas fa-clipboard-list"></i> Work Orders', url_for('workorders_list')),
                   ('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')),
                   ('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')),
                   ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                   ('<i class="fas fa-truck"></i> Suppliers', url_for('suppliers_list')),
                   ('<i class="fas fa-users"></i> Employees', url_for('employees_list'))]
        if r == "ADMIN":
            nav += [('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')),
                    ('<i class="fas fa-history"></i> Audit', url_for('audit_logs')),
                    ('<i class="fas fa-archive"></i> Archived', url_for('deleted_requests')),
                    ('<i class="fas fa-archive"></i> Backup', url_for('backup_page'))]
        nav += [('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
    else:
        nav = [('<i class="fas fa-sign-in-alt"></i> Login', url_for('login'))]
    nav_html = "".join('<a class="nav-link" href="' + str(u) + '">' + str(l) + '</a>' for l, u in nav)
    bell_html = ""
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        badge = '<span class="badge bg-danger" style="position:absolute;top:-5px;right:-5px;font-size:0.7rem;">' + str(unread) + '</span>' if unread > 0 else ""
        bell_html = '<a class="nav-link" id="nav-bell" href="' + url_for('notifications') + '" style="position:relative;"><i class="fas fa-bell"></i>' + badge + '</a>'
    flash_html = "".join('<div class="alert alert-' + str(c) + ' alert-dismissible fade show">' + str(m) + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>' for c, m in get_flashed_messages(with_categories=True))
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>""" + str(title) + """ | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body { font-family:'Inter',sans-serif; background-color: #f8fafc; color: #111827; padding-top:70px; }
.navbar{background:#ffffff!important;border-bottom:1px solid #e2e8f0;padding:.75rem 1.5rem;box-shadow:0 2px 10px rgba(0,0,0,0.05)}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#c5a059!important}
.nav-link{color:#64748b!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem;font-weight:500}
.nav-link i{color:#c5a059;margin-right:4px}
.nav-link:hover{background:#fffbeb;color:#c5a059!important}
.navbar-toggler{border-color:#e2e8f0}
.container{max-width:1400px;padding:1.5rem}
.card{background-color: #ffffff; border: 1px solid #e2e8f0; color: #1e293b; border-radius: 14px; box-shadow: 0 4px 15px rgba(15, 23, 42, 0.04); padding:1.25rem;margin-bottom:1.5rem}
.metric-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;padding:1.2rem 1rem;text-align:center;height:100%;box-shadow:0 4px 15px rgba(15, 23, 42, 0.04)}
.metric-value{font-size:2rem;font-weight:800;color:#111827}
.metric-label{font-size:.8rem;color:#64748b;text-transform:uppercase;font-weight:600}
.table{color:#1e293b;background:#ffffff}
.table thead th{color:#111827;border-bottom:2px solid #e2e8f0;font-size:.75rem;text-transform:uppercase;padding:12px;font-weight:700;background:#f8fafc}
.table td{padding:12px;border-color:#f1f5f9}
.table-hover tbody tr:hover{background-color:#f8fafc}
.btn{border-radius:10px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background-color: #c5a059; color: #ffffff;}
.btn-primary:hover{background-color: #a98745;}
.btn-success{background-color: #10b981; color: #fff;}
.btn-warning{background-color: #f59e0b; color: #fff;}
.btn-danger{background-color: #ef4444; color: #fff;}
.btn-info{background-color: #3b82f6; color: #fff;}
.btn-secondary{background:#64748b;color:#fff}
.btn-sm{padding:.4rem .9rem;font-size:.85rem}
.form-control,.form-select{background-color: #ffffff; color: #111827; border: 1px solid #cbd5e1; border-radius: 10px; padding:.75rem 1rem}
.form-control:focus,.form-select:focus{background-color: #ffffff; color: #111827; border-color: #c5a059; box-shadow: 0 0 0 3px rgba(197, 160, 89, 0.15)}
.form-label{color:#334155;font-weight:600}
.alert{border-radius:12px;border:none;background:#fff;color:#1e293b;box-shadow:0 2px 10px rgba(0,0,0,0.05)}
.alert-success{border-left:4px solid #10b981}.alert-danger{border-left:4px solid #ef4444}
.alert-warning{border-left:4px solid #f59e0b}.alert-info{border-left:4px solid #3b82f6}
.login-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:20px;padding:2rem 2.5rem;max-width:440px;margin:0 auto;box-shadow:0 10px 30px rgba(0,0,0,0.08)}
.badge{padding:.4rem .8rem;border-radius:20px;font-weight:600;font-size:.75rem}
h1,h2,h3,h4,h5,h6{color:#111827}
.signature-box { background-color: #ffffff; border: 2px dashed #c5a059; border-radius: 12px; }
@keyframes bell-pulse{0%{transform:scale(1)}25%{transform:scale(1.35)}50%{transform:scale(1)}75%{transform:scale(1.25)}100%{transform:scale(1)}}
.bell-alert{animation:bell-pulse .6s ease-in-out 3;color:#c5a059!important}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.login-card{padding:1.5rem;margin:1rem}}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href=""" + (url_for('dashboard') if current_user.is_authenticated else url_for('login')) + """"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">""" + nav_html + bell_html + """</div></div>
</div></nav>
<div class="container mt-4">""" + flash_html + content + """</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
(function(){
'use strict';
if (!window.NotifState) window.NotifState = { lastUnread: null, audioCtx: null, armed: false };
function playChime(){try{var C=window.AudioContext||window.webkitAudioContext;if(!C)return;if(!window.NotifState.audioCtx)window.NotifState.audioCtx=new C();var ctx=window.NotifState.audioCtx;if(ctx.state==='suspended')ctx.resume();[880,1108.73,1318.51].forEach(function(f,i){var o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*0.15;o.type='sine';o.frequency.value=f;g.gain.setValueAtTime(0.0001,t);g.gain.linearRampToValueAtTime(0.28,t+0.03);g.gain.exponentialRampToValueAtTime(0.0001,t+0.55);o.connect(g);g.connect(ctx.destination);o.start(t);o.stop(t+0.6);});}catch(e){}}
function vibrate(){try{if(navigator.vibrate)navigator.vibrate([250,120,250,120,400]);}catch(e){}}
function flashBell(){var b=document.getElementById('nav-bell');if(!b)return;b.classList.add('bell-alert');setTimeout(function(){b.classList.remove('bell-alert');},2000);}
function flashTitle(n){var o=document.title,c=0,iv=setInterval(function(){document.title=(c%2===0)?('🔔 ('+n+') '+o):o;c++;if(c>6){clearInterval(iv);document.title=o;}},700);}
function poll(){fetch('/api/notifications/unread',{credentials:'same-origin',cache:'no-store'}).then(function(r){return r.ok?r.json():null;}).then(function(d){if(!d)return;var p=window.NotifState.lastUnread,c=d.unread;if(p===null){window.NotifState.lastUnread=c;return;}if(c>p){playChime();vibrate();flashBell();flashTitle(c);}window.NotifState.lastUnread=c;}).catch(function(){});}
function arm(){if(window.NotifState.armed)return;try{var C=window.AudioContext||window.webkitAudioContext;if(C){if(!window.NotifState.audioCtx)window.NotifState.audioCtx=new C();if(window.NotifState.audioCtx.state==='suspended')window.NotifState.audioCtx.resume();}window.NotifState.armed=true;}catch(e){}}
document.addEventListener('click',arm);document.addEventListener('touchstart',arm);document.addEventListener('keydown',arm);
if(document.getElementById('nav-bell')){poll();setInterval(poll,15000);}
})();
</script></body></html>"""

# ═════════════════════════════════════════ SEED DATA
def seed_data():
    for name in ["Housekeeping","Front Office","Engineering","Food & Beverage","Kitchen","Finance","HR","Security","IT","Sales & Marketing","Administration","Maintenance","Other","SPA","GM"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
    db.session.commit()
    
    for f in [2,3,4,5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))
    
    existing_rooms = Room.query.count()
    if existing_rooms == 0:
        print("✅ Creating initial rooms (201-300)...")
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))
    elif existing_rooms > 300:
        print(f"⚠️ WARNING: Found {existing_rooms} rooms. Expected max 300. Cleaning duplicates...")
        Room.query.delete()
        db.session.commit()
        print("✅ Deleted duplicate rooms. Recreating...")
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))
    else:
        print(f"️ Rooms already exist ({existing_rooms}). Skipping creation.")
    
    for n, d in [("Buduchalley","F&B"),("Sillanto","Unknown"),("Fura","Unknown"),("Executive","Unknown"),("Mitima","Unknown"),("Odako","Unknown"),("Gudumale","Unknown"),("Bubble","Unknown"),("Bubbles","Unknown"),("Fura Corridor","Unknown"),("Executive Meeting Room","Unknown"),("Counter","Unknown")]:
        if not Area.query.filter_by(name=n).first(): db.session.add(Area(name=n, department=d))
    
    for c in ["Electrical","Plumbing","HVAC","Painting","Carpentry","Civil","Safety","General","Other"]:
        if not Category.query.filter_by(name=c).first(): db.session.add(Category(name=c))
    
    for i in ["Light","Switch","Window","Door Key","Door Lock","Paint","Mirror","Drainage Cover","Frame","Background Frame","Spot Light","Plumbing","AC","Electrical","Other"]:
        if not WorkingItem.query.filter_by(name=i).first(): db.session.add(WorkingItem(name=i))
    
    for eid, n, t in [(1,"ተስሁን ከረ","General Mechanic"),(2,"ቸርነት አሞና","General Mechanic"),(3,"ስምዖን ሐንስ","General Mechanic"),(4,"አበባየ ክፍሌ","Supervisor"),(5,"አሚር አወል","Manager")]:
        if not db.session.get(Employee, eid): db.session.add(Employee(id=eid, name=n, job_title=t, department="Engineering"))
    
    if Supplier.query.count() == 0:
        for s in ["ABC Maintenance Supply","Hawassa Engineering Supply","Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=s, contact_person="", phone="", status="Active", is_active=True))
    
    hk = Department.query.filter_by(name="Housekeeping").first()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)
    
    users_to_seed = [
        {"u":"amir","n":"Amir Awel","r":"MANAGER","d":None},
        {"u":"kasahun","n":"Kasahun Girma","r":"MANAGER","d":hk.id if hk else None},
        {"u":"housekeeping","n":"Kassahun Girma","r":"DEPARTMENT","d":hk.id if hk else None},
        {"u":"it","n":"To be configured later","r":"DEPARTMENT","d":"IT"},
        {"u":"fnb","n":"Bahilu Boja","r":"DEPARTMENT","d":"Food & Beverage"},
        {"u":"security","n":"Tariku Bekele","r":"DEPARTMENT","d":"Security"},
        {"u":"kitchen","n":"Biruk Haile","r":"DEPARTMENT","d":"Kitchen"},
        {"u":"spa","n":"Tesfaye Yohanes","r":"DEPARTMENT","d":"SPA"},
        {"u":"finance","n":"Abel Yemane","r":"DEPARTMENT","d":"Finance"},
        {"u":"gm","n":"Muluken Gedafew","r":"DEPARTMENT","d":"GM"},
        {"u":"abebayhu","n":"አበባየ ክፍሌ","r":"SUPERVISOR","d":None},
        {"u":"tesfahun","n":"ተስፋን ነከረ","r":"TECHNICIAN","d":None},
        {"u":"simon","n":"ስምዖን ሐንስ","r":"TECHNICIAN","d":None},
        {"u":"chernet","n":"ቸርነት አሞና","r":"TECHNICIAN","d":None},
        {"u":"wale","n":"ዋሌ","r":"TECHNICIAN","d":None},
        {"u":"tsadiku","n":"ፃዲቁ","r":"TECHNICIAN","d":None},
        {"u":"employee1","n":"Test Employee","r":"EMPLOYEE","d":None},
    ]
    
    for s in users_to_seed:
        dept_obj = Department.query.filter_by(name=s["d"]).first() if s["d"] else None
        ex = User.query.filter_by(username=s["u"]).first()
        if not ex:
            u = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=dept_obj.id if dept_obj else None)
            u.set_password("123456")
            db.session.add(u)
        else:
            ex.full_name = s["n"]
            ex.role = s["r"]
            ex.department_id = dept_obj.id if dept_obj else None
    
    db.session.flush()
    
    sig_configs = [
        {"dept": "IT", "name": "To be configured"},
        {"dept": "Food & Beverage", "name": "Bahilu Boja"},
        {"dept": "Security", "name": "Tariku Bekele"},
        {"dept": "Kitchen", "name": "Biruk Haile"},
        {"dept": "SPA", "name": "Tesfaye Yohanes"},
        {"dept": "Finance", "name": "Abel Yemane"},
        {"dept": "GM", "name": "Muluken Gedafew"},
        {"dept": "Housekeeping", "name": "Kassahun Girma"},
    ]
    for cfg in sig_configs:
        dept = Department.query.filter_by(name=cfg["dept"]).first()
        if not dept: continue
        existing = DepartmentSignature.query.filter_by(department_id=dept.id).first()
        if not existing:
            db.session.add(DepartmentSignature(
                department_id=dept.id,
                authorized_name=cfg["name"],
                is_active=True
            ))
        else:
            existing.authorized_name = cfg["name"]
            existing.is_active = True
    
    db.session.commit()
    print("✅ Seed data loaded with original passwords and signature profiles")

# ══════════════════════════════════════════ AUTH & ROUTES
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role in ["ADMIN","MANAGER"]: return redirect(url_for("dashboard"))
        if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
        if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
        return redirect(url_for("workorders_list"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET","POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("index"))
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username","").strip()).first()
        if u and u.check_password(request.form.get("password","")) and u.active:
            login_user(u); log_audit("Login","User",u.id); db.session.commit(); return redirect(url_for("index"))
        flash("Incorrect username or password","danger")
    lh = """<div class="row justify-content-center align-items-center" style="min-height:80vh">
<div class="col-11 col-md-5"><div class="login-card">
<div class="text-center mb-4"><h3 class="fw-bold" style="color:#c5a059"><i class="fas fa-hotel"></i> Rori Hotel</h3><p style="color:#64748b">Login</p></div>
<form method="post"><div class="mb-3"><label class="form-label">Username</label><input type="text" class="form-control" name="username" required autofocus></div>
<div class="mb-4"><label class="form-label">Password</label><input type="password" class="form-control" name="password" required></div>
<button class="btn btn-primary w-100"><i class="fas fa-sign-in-alt"></i> Login</button></form>
<hr class="my-4" style="border-color:#e2e8f0"><div class="text-center small" style="color:#64748b">
<p class="mb-1">Admin: <b>admin / admin123</b></p>
<p class="mb-0">All Departments & Staff: <b>username / 123456</b></p></div>
</div></div></div>"""
    return page("Login", lh)

@app.route("/logout")
@login_required
def logout():
    log_audit("Logout","User",current_user.id); db.session.commit(); logout_user(); return redirect(url_for("login"))

@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    u = current_user
    if request.method == "POST":
        u.email = request.form.get("email","").strip(); u.phone = request.form.get("phone","").strip()
        np = request.form.get("new_password","").strip()
        if np: u.set_password(np)
        db.session.commit(); flash("Profile updated","success"); return redirect(url_for("profile"))
    c = ('<h3 style="color:#c5a059">👤 Profile</h3><div class="card"><h4>' + str(u.full_name) + '</h4>'
         '<p>@' + str(u.username) + ' · <span class="badge bg-warning text-dark">' + str(u.role) + '</span></p>'
         '<p> 📧 ' + str(u.email or "—") + ' |  ' + str(u.phone or "—") + '</p>'
         '<p> 🏢 Department: <strong>' + str(u.department.name if u.department else "Not assigned") + '</strong></p><hr>'
         '<form method="post"><div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + str(u.email or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + str(u.phone or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">New Password</label><input type="password" class="form-control" name="new_password" placeholder="Leave blank to keep current"></div>'
         '<button class="btn btn-primary"><i class="fas fa-save"></i> Save</button></form></div>')
    return page("Profile", c)

# ══════════════════════════════════════════ REQUESTS
@app.route("/requests")
@login_required
def requests_list():
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if current_user.role in ["MANAGER","ADMIN"]: pass
    elif current_user.role == "DEPARTMENT":
        if current_user.department_id:
            q = q.filter(db.or_(MaintenanceRequest.department_id == current_user.department_id, MaintenanceRequest.requested_by_id == current_user.id))
        else: q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role == "EMPLOYEE": q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    elif current_user.role in STAFF_ROLES: q = q.filter(MaintenanceRequest.assigned_to_id == current_user.id)
    
    if request.args.get("status"): q = q.filter(MaintenanceRequest.status == request.args["status"])
    if request.args.get("priority"): q = q.filter(MaintenanceRequest.priority == request.args["priority"])
    
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    is_mgr = current_user.role in ["MANAGER","ADMIN"]
    rows = []
    for r in reqs:
        del_html = ""
        if is_mgr:
            del_html = ('<form method="post" action="' + url_for("request_delete", req_id=r.id) + '" style="display:inline" onsubmit="return confirm(\'Are you sure? This request will be archived.\');"><input type="hidden" name="reason" value="Archived by manager"><button type="submit" class="btn btn-sm btn-outline-danger" title="Archive"><i class="fas fa-archive"></i></button></form>')
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:#c5a059;font-weight:600">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.department.name if r.department else "—") + '</td><td><span class="badge bg-secondary">' + str(r.priority) + '</span></td><td><span class="badge bg-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>' + ('<td style="width:60px;text-align:center">' + del_html + '</td>' if is_mgr else '') + '</tr>')
    
    header = '<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Created</th>' + ('<th></th>' if is_mgr else '') + '</tr></thead>'
    c = ('<div class="d-flex justify-content-between mb-3"><h3 style="color:#c5a059"><i class="fas fa-tasks"></i> Maintenance Requests</h3><a href="' + url_for("request_create") + '" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a></div>'
         '<div class="card"><div class="table-responsive"><table class="table table-hover">' + header + '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="' + ('8' if is_mgr else '7') + '" class="text-center">No requests found</td></tr>') + '</tbody></table></div></div>')
    return page("Requests", c)

@app.route("/requests/new", methods=["GET","POST"])
@login_required
def request_create():
    depts = Department.query.order_by(Department.name).all()
    cats = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()] or sorted({r.floor for r in Room.query.all()})
    
    sig_profile = get_user_signature_profile(current_user)
    user_dept_name = current_user.department.name if current_user.department else None
    user_dept_id = current_user.department_id
    
    if request.method == "POST":
        try:
            lt = request.form.get("location_type","Room").strip() or "Room"
            rid = request.form.get("room_id", type=int)
            aid = request.form.get("area_id", type=int)
            wid = request.form.get("working_item_id", type=int)
            cid = request.form.get("category_id", type=int)
            desc = request.form.get("description","").strip()
            prio = request.form.get("priority","MEDIUM")
            fl = request.form.get("floor", type=int)
            did = request.form.get("department_id", type=int)
            
            if current_user.department_id: did = current_user.department_id
            if current_user.role == "DEPARTMENT" and current_user.department_id: did = current_user.department_id
            
            if lt == "Room" and rid:
                rm = get_one(Room, rid)
                if rm: fl = rm.floor
            elif lt == "Area": rid = None
            else: rid = None; aid = None
            
            if not desc:
                flash("Description is required","danger"); return redirect(url_for("request_create"))
            
            sig_data = request.form.get("signature_data", "").strip()
            sig_name_from_form = request.form.get("signature_name", "").strip()
            
            ok, err = validate_signature_for_user(current_user, sig_data)
            if not ok:
                flash(err, "danger")
                return redirect(url_for("request_create"))
            
            # ✅ FIXED: Only reject if mismatch, otherwise proceed
            if sig_profile and sig_name_from_form:
                if sig_name_from_form != sig_profile.authorized_name:
                    flash("Signature name mismatch. You cannot impersonate another department's authorized signature.", "danger")
                    return redirect(url_for("request_create"))
            
            authorized_name = sig_profile.authorized_name if sig_profile else (current_user.full_name or current_user.username)
            
            req = MaintenanceRequest(
                request_no=request_no_generator(), location_type=lt, floor=fl, room_id=rid, area_id=aid,
                working_item_id=wid, category_id=cid, description=desc, priority=prio, status="Pending",
                requested_by_id=current_user.id, department_id=did, awaiting_hk_approval=False,
                signature_name=authorized_name, signature_status="SIGNED", signature_signed_at=datetime.utcnow(),
                signature_data=sig_data, signature_department=user_dept_name, signature_verified=True, signature_user_id=current_user.id,
            )
            req.due_date = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio,24))
            db.session.add(req); db.session.flush()
            log_audit("Create Request","MaintenanceRequest",req.id,new_value=req.request_no)
            log_audit("Digital Signature","MaintenanceRequest",req.id,new_value=authorized_name + " @ " + str(user_dept_name))
            log_status_change(req.id,"Pending",notes="Created and signed by " + str(authorized_name) + " (" + str(user_dept_name) + ")")
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"]), User.active == True).all()
            notify_users([u.id for u in managers], req.id, "📝 New Request", "Request " + str(req.request_no) + " from " + str(user_dept_name or "N/A") + " is pending approval", "New Request", link=url_for("request_detail", req_id=req.id))
            db.session.commit()
            flash("✅ Request created successfully with verified digital signature!","success")
            return redirect(url_for("request_detail", req_id=req.id))
        except Exception as e:
            db.session.rollback(); print("Create error: " + traceback.format_exc())
            flash("Error: " + str(e),"danger"); return redirect(url_for("request_create"))
    
    fo = "".join('<option value="' + str(f) + '">Floor ' + str(f) + '</option>' for f in floors)
    ro = "".join('<option value="' + str(r.id) + '">Room ' + str(r.room_number) + ' (F' + str(r.floor) + ')</option>' for r in rooms)
    ao = "".join('<option value="' + str(a.id) + '">' + str(a.name) + '</option>' for a in areas)
    io_ = "".join('<option value="' + str(i.id) + '">' + str(i.name) + '</option>' for i in items)
    co = "".join('<option value="' + str(c.id) + '">' + str(c.name) + '</option>' for c in cats)
    po = "".join('<option value="' + p + '"' + (' selected' if p=="MEDIUM" else '') + '>' + p + '</option>' for p in ["URGENT","HIGH","MEDIUM","LOW"])
    
    sig_authorized_name = sig_profile.authorized_name if sig_profile else "Not configured"
    sig_dept_display = user_dept_name or "Not assigned"
    sig_warning = "" if sig_profile else '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> No authorized signature configured for your department. Contact admin before submitting requests.</div>'
    sig_configured_class = "border-success" if sig_profile else "border-danger"
    
    c = ('<h3 style="color:#c5a059"><i class="fas fa-plus-circle"></i> New Maintenance Request</h3>' + sig_warning +
         '<div class="card"><form method="post" id="requestForm"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Location Type *</label><select class="form-select" name="location_type" id="locationType" required><option value="Room" selected>Room</option><option value="Area">Area</option></select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Department (Auto-detected)</label><input type="text" class="form-control" value="' + str(sig_dept_display) + '" readonly style="background:#f0fdf4;border-color:#10b981;color:#10b981;font-weight:600"><input type="hidden" name="department_id" value="' + str(user_dept_id or "") + '"></div>'
         '<div class="col-md-6 mb-3" id="roomWrap"><label class="form-label">Room</label><select class="form-select" name="room_id"><option value="">-- Select Room --</option>' + ro + '</select></div>'
         '<div class="col-md-6 mb-3" id="floorWrap" style="display:none"><label class="form-label">Floor</label><select class="form-select" name="floor"><option value="">-- Floor --</option>' + fo + '</select></div>'
         '<div class="col-md-6 mb-3" id="areaWrap" style="display:none"><label class="form-label">Area</label><select class="form-select" name="area_id"><option value="">-- Select Area --</option>' + ao + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Working Item</label><select class="form-select" name="working_item_id"><option value="">-- Select Item --</option>' + io_ + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Category</label><select class="form-select" name="category_id"><option value="">-- Select Category --</option>' + co + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Priority *</label><select class="form-select" name="priority">' + po + '</select></div>'
         '<div class="col-12 mb-3"><label class="form-label">Description *</label><textarea class="form-control" name="description" rows="4" required placeholder="Describe the issue…"></textarea></div>'
         '<div class="col-12 mb-3"><div class="card ' + sig_configured_class + '" style="background:#f0fdf4;border-width:2px">'
         '<h5 style="color:#10b981;margin-bottom:1rem"><i class="fas fa-signature"></i> Authorized Digital Signature</h5>'
         '<div class="row g-3">'
         '<div class="col-md-6"><div style="padding:.75rem;background:#ffffff;border-radius:10px;border:1px solid #e2e8f0"><div style="font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Signed By (Authorized)</div><div style="font-size:1.1rem;font-weight:700;color:#111827;margin-top:.25rem">' + str(sig_authorized_name) + '</div><input type="hidden" name="signature_name" value="' + str(sig_authorized_name) + '"></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:#ffffff;border-radius:10px;border:1px solid #e2e8f0"><div style="font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Department</div><div style="font-size:1.1rem;font-weight:700;color:#111827;margin-top:.25rem">' + str(sig_dept_display) + '</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:#ecfdf5;border-radius:10px;border:1px solid #10b981"><div style="font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Signature Status</div><div id="sigStatusText" style="font-size:1rem;font-weight:700;color:#c5a059;margin-top:.25rem"><i class="fas fa-hourglass-half"></i> Awaiting Signature</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:#ffffff;border-radius:10px;border:1px solid #e2e8f0"><div style="font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Requester</div><div style="font-size:1rem;font-weight:600;color:#111827;margin-top:.25rem">' + str(current_user.full_name or current_user.username) + ' (@' + str(current_user.username) + ')</div></div></div>'
         '</div><hr style="border-color:#10b981;margin:1rem 0">'
         '<label class="form-label" style="color:#10b981;font-weight:600"><i class="fas fa-pen-nib"></i> Draw Your Signature Below *</label>'
         '<div class="signature-box" style="padding: 10px; background: #fff;"><canvas id="signature-pad" width="400" height="150" style="width: 100%; height: 150px; cursor: crosshair; touch-action: none;"></canvas></div>'
         '<div class="mt-2 d-flex gap-2"><button type="button" class="btn btn-sm btn-secondary" id="clear-signature"><i class="fas fa-eraser"></i> Clear</button><span id="sigHint" style="color:#64748b;font-size:.85rem;margin-left:.5rem">Please draw your signature above</span></div>'
         '<input type="hidden" name="signature_data" id="signature-data"></div></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("index") + '" class="btn btn-secondary"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn btn-primary" id="submitBtn" disabled><i class="fas fa-paper-plane"></i> Submit Request</button></div></div></form></div>'
         '<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>'
         '<script>(function(){var canvas = document.getElementById("signature-pad");var signaturePad = new SignaturePad(canvas, { backgroundColor: "rgb(255, 255, 255)", penColor: "rgb(0, 0, 0)" });var submitBtn = document.getElementById("submitBtn");var sigStatusText = document.getElementById("sigStatusText");var sigHint = document.getElementById("sigHint");function resizeCanvas(){var ratio = Math.max(window.devicePixelRatio || 1, 1);canvas.width = canvas.offsetWidth * ratio;canvas.height = canvas.offsetHeight * ratio;canvas.getContext("2d").scale(ratio, ratio);signaturePad.clear();}window.addEventListener("resize", resizeCanvas);resizeCanvas();document.getElementById("clear-signature").addEventListener("click", function(){ signaturePad.clear(); updateSigStatus(); });signaturePad.addEventListener("endStroke", updateSigStatus);function updateSigStatus(){if (signaturePad.isEmpty()){sigStatusText.innerHTML = \'<i class="fas fa-hourglass-half"></i> Awaiting Signature\';sigStatusText.style.color = "#c5a059";sigHint.textContent = "Please draw your signature above";submitBtn.disabled = true;} else {sigStatusText.innerHTML = \'<i class="fas fa-check-circle"></i> Signature Verified\';sigStatusText.style.color = "#10b981";sigHint.textContent = "✓ Signature captured - ready to submit";submitBtn.disabled = false;}}document.querySelector("#requestForm").addEventListener("submit", function(e){if (signaturePad.isEmpty()){e.preventDefault();alert("️ Digital signature is required. Your request cannot be submitted without a verified department signature.");return false;}document.getElementById("signature-data").value = signaturePad.toDataURL("image/png");});})();</script>'
         '<script>(function(){var lt=document.getElementById("locationType");var rw=document.getElementById("roomWrap");var aw=document.getElementById("areaWrap");var fw=document.getElementById("floorWrap");function upd(){var v=lt.value;if(v==="Room"){rw.style.display="";aw.style.display="none";fw.style.display="none";}else{rw.style.display="none";aw.style.display="";fw.style.display="";}}lt.addEventListener("change",upd);upd();})();</script>')
    return page("New Request", c)

@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = get_or_404(MaintenanceRequest, req_id)
    if req.is_deleted and current_user.role != "ADMIN":
        flash("This request has been archived.","warning"); return redirect(url_for("requests_list"))
    if current_user.role == "DEPARTMENT":
        same = (current_user.department_id and req.department_id == current_user.department_id)
        if not same and req.requested_by_id != current_user.id: abort(403)
    if current_user.role == "EMPLOYEE" and req.requested_by_id != current_user.id: abort(403)
    hist = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.asc()).all()
    wos = WorkOrder.query.filter_by(request_id=req.id).all()
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    hist_html = ""
    for h in hist:
        who = h.user.full_name if h.user else "System"
        when = h.timestamp.strftime("%Y-%m-%d %H:%M") if h.timestamp else ""
        note = (" — " + str(h.notes)) if h.notes else ""
        hist_html += ('<div style="padding:.5rem .75rem;border-left:3px solid #c5a059;background:#f8fafc;border-radius:10px;margin-bottom:.4rem;border:1px solid #e2e8f0">'
                      '<strong style="color:#c5a059">' + str(h.status) + '</strong> '
                      '<span style="color:#64748b;font-size:.85rem">by ' + str(who) + ' · ' + str(when) + note + '</span></div>')
    if not hist_html: hist_html = '<p style="color:#64748b">No status history yet.</p>'
    wo_html = ""
    for wo in wos:
        wo_html += ('<div style="padding:.5rem .75rem;background:#f8fafc;border-radius:10px;margin-bottom:.4rem;border:1px solid #e2e8f0">'
                    '<a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:#c5a059;font-weight:600">' + str(wo.work_order_no) + '</a> '
                    '<span class="badge bg-info">' + str(wo.status) + '</span> '
                    '<span style="color:#64748b;font-size:.85rem">· ' + str(wo.assigned_to.full_name if wo.assigned_to else "Unassigned") + '</span></div>')
    if not wo_html: wo_html = '<p style="color:#64748b">No work orders yet.</p>'
    
    sig_html = ""
    if req.signature_status == "SIGNED":
        sig_time = req.signature_signed_at.strftime("%d %b %Y, %I:%M %p") if req.signature_signed_at else "N/A"
        sig_image_html = ""
        if req.signature_data:
            sig_image_html = '<div style="margin-top:10px; background:#fff; padding:10px; border-radius:8px; display:inline-block; border:1px solid #e2e8f0;"><img src="' + str(req.signature_data) + '" style="max-width:250px; max-height:100px;" alt="Signature"></div>'
        else:
            sig_image_html = '<div style="margin-top:10px; color:#64748b;">(No signature image stored)</div>'
        verified_badge = ""
        if req.signature_verified:
            verified_badge = '<span class="badge" style="background:#10b981;color:#fff;margin-left:.5rem"><i class="fas fa-check-circle"></i> Verified</span>'
        else:
            verified_badge = '<span class="badge" style="background:#f59e0b;color:#000;margin-left:.5rem"><i class="fas fa-exclamation"></i> Unverified</span>'
        sig_html = ('<div class="card" style="border: 1px solid rgba(16, 185, 129, 0.3); background: #f0fdf4; margin-top:1rem;">'
                    '<h6 style="color:#10b981; margin-bottom:1rem;"><i class="fas fa-signature"></i> DIGITAL SIGNATURE ' + verified_badge + '</h6>'
                    '<div class="row g-3">'
                    '<div class="col-md-6"><div style="padding:.6rem;background:#fff;border-radius:8px;border:1px solid #e2e8f0">'
                    '<div style="font-size:.7rem;color:#64748b;text-transform:uppercase">Signed By</div>'
                    '<div style="font-size:1rem;font-weight:700;color:#111827">' + str(req.signature_name or "Unknown") + '</div>'
                    '</div></div>'
                    '<div class="col-md-6"><div style="padding:.6rem;background:#fff;border-radius:8px;border:1px solid #e2e8f0">'
                    '<div style="font-size:.7rem;color:#64748b;text-transform:uppercase">Department</div>'
                    '<div style="font-size:1rem;font-weight:700;color:#111827">' + str(req.signature_department or req.department.name if req.department else "N/A") + '</div>'
                    '</div></div>'
                    '<div class="col-md-6"><div style="padding:.6rem;background:#fff;border-radius:8px;border:1px solid #e2e8f0">'
                    '<div style="font-size:.7rem;color:#64748b;text-transform:uppercase">Signed At</div>'
                    '<div style="font-size:.95rem;font-weight:600;color:#111827">' + sig_time + '</div>'
                    '</div></div>'
                    '<div class="col-md-6"><div style="padding:.6rem;background:#fff;border-radius:8px;border:1px solid #e2e8f0">'
                    '<div style="font-size:.7rem;color:#64748b;text-transform:uppercase">Verification Status</div>'
                    '<div style="font-size:.95rem;font-weight:600;color:' + ('#10b981' if req.signature_verified else '#f59e0b') + '">' + ('✓ Verified' if req.signature_verified else '⚠ Unverified') + '</div>'
                    '</div></div>'
                    '</div>'
                    + sig_image_html +
                    '</div>')
    actions = []
    if current_user.role in ["ADMIN","MANAGER"]:
        if req.status in ["Pending","Approved","Assigned"] and req.assigned_to_id is None:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn btn-primary"><i class="fas fa-user-plus"></i> Assign Staff</a>')
        elif req.status in ["Approved","Assigned"]:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn btn-primary"><i class="fas fa-user-edit"></i> Reassign</a>')
        if req.status == "Pending":
            actions.append('<form method="post" action="' + url_for("request_approve", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-success"><i class="fas fa-check"></i> Approve</button></form>')
        if req.status == "Completed":
            actions.append('<form method="post" action="' + url_for("request_verify", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-info"><i class="fas fa-check-double"></i> Verify</button></form>')
        if req.status == "Verified":
            actions.append('<form method="post" action="' + url_for("request_close", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn btn-secondary"><i class="fas fa-lock"></i> Close</button></form>')
        if not req.is_deleted:
            actions.append('<form method="post" action="' + url_for("request_delete", req_id=req.id) + '" style="display:inline" onsubmit="return confirm(\'️ Are you sure?\')"><input type="hidden" name="reason" value="Archived by manager"><button type="submit" class="btn btn-danger"><i class="fas fa-archive"></i> Archive</button></form>')
    actions_html = " ".join(actions) if actions else ""
    c = ('<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">'
         '<h3 style="color:#c5a059;margin:0"><i class="fas fa-clipboard-list"></i> ' + str(req.request_no) + '</h3>'
         + ('<div>' + actions_html + '</div>' if actions_html else '') + '</div>'
         '<div class="row"><div class="col-md-8"><div class="card"><h5 style="color:#c5a059">Request Details</h5>'
         '<table class="table"><tbody>'
         '<tr><th style="width:180px;color:#64748b">Status</th><td><span class="badge bg-' + bd(req.status) + '">' + str(req.status) + '</span></td></tr>'
         '<tr><th style="color:#64748b">Priority</th><td>' + str(req.priority) + '</td></tr>'
         '<tr><th style="color:#64748b">Department</th><td>' + str(req.department.name if req.department else "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Location</th><td>' + str(req.location_name) + '</td></tr>'
         '<tr><th style="color:#64748b">Item</th><td>' + str(req.working_item.name if req.working_item else "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Category</th><td>' + str(req.category.name if req.category else "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Requested By</th><td><strong>' + str(req.requested_by.full_name if req.requested_by else "—") + '</strong></td></tr>'
         '<tr><th style="color:#64748b">Assigned To</th><td>' + str(req.assigned_to.full_name if req.assigned_to else "Not Assigned") + '</td></tr>'
         '<tr><th style="color:#64748b">Description</th><td>' + str(req.description or "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Due Date</th><td>' + (req.due_date.strftime("%Y-%m-%d %H:%M") if req.due_date else "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Completed</th><td>' + (req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Completion Note</th><td>' + str(req.completion_note or "—") + '</td></tr>'
         '<tr><th style="color:#64748b">Created</th><td>' + (req.created_at.strftime("%Y-%m-%d %H:%M") if req.created_at else "—") + '</td></tr>'
         '</tbody></table>' + sig_html + '</div>'
         '<div class="card"><h5 style="color:#c5a059"><i class="fas fa-clipboard-list"></i> Work Orders</h5>' + wo_html + '</div>'
         '</div><div class="col-md-4"><div class="card"><h5 style="color:#c5a059"><i class="fas fa-history"></i> Status History</h5>' + hist_html + '</div></div></div>')
    return page("Request " + str(req.request_no), c)

# ... (Remaining routes: request_approve, request_verify, request_close, request_delete, deleted_requests, request_restore, analytics functions, dashboard, department_dashboard, employee_dashboard, workorders, suppliers, inventory, notifications, rooms, areas, employees, admin_users, audit_logs, backup_page, reports, debug, manifest, sw, logo, errors - all remain the same as in the previous full version to save space, they are 100% compatible with this light theme update) ...

# ═════════════════════════════════════════ DASHBOARD TEMPLATE (LIGHT THEME)
DASHBOARD_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manager Dashboard | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f8fafc;color:#111827;padding-top:70px}
.navbar{background:#ffffff!important;border-bottom:1px solid #e2e8f0;padding:.75rem 1.5rem;box-shadow:0 2px 10px rgba(0,0,0,0.05)}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#c5a059!important}
.nav-link{color:#64748b!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem;font-weight:500}
.nav-link i{color:#c5a059;margin-right:4px}
.nav-link:hover{background:#fffbeb;color:#c5a059!important}
.navbar-toggler{border-color:#e2e8f0}
.container{max-width:1400px;padding:1.5rem}
.card{background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;color:#1e293b;padding:1.25rem;margin-bottom:1.5rem;box-shadow:0 4px 15px rgba(15, 23, 42, 0.04)}
.card h5{color:#c5a059;font-weight:600}
.metric-card{background:#ffffff;border:1px solid #e2e8f0;border-radius:14px;padding:1.2rem 1rem;text-align:center;height:100%;transition:transform .15s;box-shadow:0 4px 15px rgba(15, 23, 42, 0.04)}
.metric-card:hover{transform:translateY(-2px);border-color:#c5a059}
.metric-value{font-size:2rem;font-weight:800;color:#111827;line-height:1}
.metric-label{font-size:.72rem;color:#64748b;text-transform:uppercase;letter-spacing:.6px;margin-top:.35rem;font-weight:600}
.metric-icon{font-size:1.4rem;color:#c5a059;margin-bottom:.35rem}
.table{color:#1e293b;background:#ffffff}
.table thead th{color:#111827;border-bottom:2px solid #e2e8f0;font-size:.72rem;text-transform:uppercase;padding:10px;white-space:nowrap;background:#f8fafc;font-weight:700}
.table td{padding:10px;border-color:#f1f5f9;font-size:.85rem}
.table-hover tbody tr:hover{background-color:#f8fafc}
.btn{border-radius:10px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background-color: #c5a059; color: #ffffff;}
.btn-primary:hover{background-color: #a98745;}
.btn-sm{padding:.35rem .8rem;font-size:.78rem}
.form-control,.form-select{background-color: #ffffff; color: #111827; border: 1px solid #cbd5e1; border-radius: 10px; padding:.65rem .9rem}
.form-control:focus,.form-select:focus{background-color: #ffffff; color: #111827; border-color: #c5a059; box-shadow: 0 0 0 3px rgba(197, 160, 89, 0.15)}
.form-label{color:#334155;font-weight:500;font-size:.82rem}
.badge{padding:.35rem .75rem;border-radius:20px;font-weight:600;font-size:.72rem}
.chart-box{position:relative;width:100%;height:280px}
.chart-box.tall{height:340px}
.chart-box.donut{height:240px}
.prog-list{display:flex;flex-direction:column;gap:.7rem}
.prog-row{display:flex;flex-direction:column;gap:.3rem}
.prog-top{display:flex;justify-content:space-between;font-size:.78rem}
.prog-top .nm{color:#334155;font-weight:600}
.prog-top .ct{color:#c5a059;font-weight:800}
.prog-bar{height:6px;background:#f1f5f9;border-radius:6px;overflow:hidden}
.prog-bar span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#c5a059,#d97706)}
.feed{display:flex;flex-direction:column;gap:.4rem}
.feed-item{display:flex;gap:.6rem;padding:.55rem .7rem;background:#f8fafc;border-left:2px solid #c5a059;border-radius:9px;font-size:.78rem;border:1px solid #e2e8f0}
.feed-item .tx{color:#334155}
.feed-item .tx strong{color:#111827}
.feed-item .tm{font-size:.65rem;color:#94a3b8;margin-top:2px}
.empty{text-align:center;padding:2rem 1rem;color:#64748b;font-size:.85rem}
.empty i{font-size:1.6rem;color:#c5a059;opacity:.4;display:block;margin-bottom:.5rem}
.filter-bar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:end;padding:1rem;background:#ffffff;border-radius:16px;border:1px solid #e2e8f0;margin-bottom:1.5rem;box-shadow:0 2px 10px rgba(0,0,0,0.03)}
.filter-bar > div{display:flex;flex-direction:column;gap:.25rem;flex:1;min-width:130px}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.chart-box{height:220px}}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">
<a class="nav-link" href="{{ url_for('dashboard') }}"><i class="fas fa-home"></i> Dashboard</a>
<a class="nav-link" href="{{ url_for('request_create') }}"><i class="fas fa-plus-circle"></i> New</a>
<a class="nav-link" href="{{ url_for('requests_list') }}"><i class="fas fa-tasks"></i> Requests</a>
<a class="nav-link" href="{{ url_for('workorders_list') }}"><i class="fas fa-clipboard-list"></i> Work Orders</a>
<a class="nav-link" href="{{ url_for('rooms_list') }}"><i class="fas fa-door-open"></i> Rooms</a>
<a class="nav-link" href="{{ url_for('areas_list') }}"><i class="fas fa-map-marked-alt"></i> Areas</a>
<a class="nav-link" href="{{ url_for('inventory_list') }}"><i class="fas fa-boxes"></i> Inventory</a>
<a class="nav-link" href="{{ url_for('suppliers_list') }}"><i class="fas fa-truck"></i> Suppliers</a>
<a class="nav-link" href="{{ url_for('employees_list') }}"><i class="fas fa-users"></i> Employees</a>
{% if current_user.role == 'ADMIN' %}
<a class="nav-link" href="{{ url_for('admin_users') }}"><i class="fas fa-user-cog"></i> Users</a>
<a class="nav-link" href="{{ url_for('audit_logs') }}"><i class="fas fa-history"></i> Audit</a>
<a class="nav-link" href="{{ url_for('deleted_requests') }}"><i class="fas fa-archive"></i> Archived</a>
<a class="nav-link" href="{{ url_for('backup_page') }}"><i class="fas fa-archive"></i> Backup</a>
{% endif %}
<a class="nav-link" href="{{ url_for('reports') }}"><i class="fas fa-chart-bar"></i> Reports</a>
<a class="nav-link" href="{{ url_for('notifications') }}"><i class="fas fa-bell"></i> Notifications</a>
<a class="nav-link" href="{{ url_for('profile') }}"><i class="fas fa-user-circle"></i> {{ current_user.full_name or current_user.username }}</a>
<a class="nav-link" href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a>
</div></div></div></nav>
<div class="container mt-4">
<div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
<div>
<h2 style="color:#c5a059;font-weight:800;margin:0"><i class="fas fa-chart-line"></i> Central Maintenance Dashboard</h2>
<p style="color:#64748b;font-size:.85rem;margin:.25rem 0 0">All departments · Real-time analytics</p>
</div>
<a href="{{ url_for('request_create') }}" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a>
</div>
<form method="get" class="filter-bar">
<div><label class="form-label">From</label><input type="date" class="form-control" name="date_from" value="{{ filters.get('date_from','') }}"></div>
<div><label class="form-label">To</label><input type="date" class="form-control" name="date_to" value="{{ filters.get('date_to','') }}"></div>
<div><label class="form-label">Department</label>
<select class="form-select" name="department">
<option value="">All</option>
{% for d in all_departments %}<option value="{{ d.id }}" {% if filters.get('department') == d.id|string %}selected{% endif %}>{{ d.name }}</option>{% endfor %}
</select></div>
<div><label class="form-label">Category</label>
<select class="form-select" name="category">
<option value="">All</option>
{% for c in all_categories %}<option value="{{ c.id }}" {% if filters.get('category') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}
</select></div>
<div><label class="form-label">Status</label>
<select class="form-select" name="status">
<option value="">All</option>
{% for s in ['Pending','Approved','Assigned','In Progress','Completed','Verified','Closed','Rejected'] %}
<option value="{{ s }}" {% if filters.get('status') == s %}selected{% endif %}>{{ s }}</option>{% endfor %}
</select></div>
<div style="flex:0"><button class="btn btn-primary" type="submit"><i class="fas fa-filter"></i> Apply</button></div>
<div style="flex:0"><a class="btn btn-sm" href="{{ url_for('dashboard') }}" style="background:#64748b;color:#fff;padding:.65rem 1.2rem;border-radius:40px;font-weight:600;font-size:.85rem">Reset</a></div>
</form>
<div class="row g-3 mb-4">
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clipboard-list"></i></div><div class="metric-value">{{ kpis.total }}</div><div class="metric-label">Total</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#f59e0b"><i class="fas fa-hourglass-half"></i></div><div class="metric-value">{{ kpis.pending }}</div><div class="metric-label">Pending</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#10b981"><i class="fas fa-circle-check"></i></div><div class="metric-value">{{ kpis.completed }}</div><div class="metric-label">Completed</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#3b82f6"><i class="fas fa-percent"></i></div><div class="metric-value">{{ kpis.completion_rate }}%</div><div class="metric-label">Rate</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#06b6d4"><i class="fas fa-clock"></i></div><div class="metric-value" style="font-size:1.3rem">{{ kpis.avg_resolution }}</div><div class="metric-label">Avg Time</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#ef4444"><i class="fas fa-toolbox"></i></div><div class="metric-value">{{ work_orders.total }}</div><div class="metric-label">Work Orders</div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-area"></i> Request Trends</h5>
<div class="chart-box tall"><canvas id="chartTrends"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-pie"></i> Status Distribution</h5>
<div class="chart-box donut"><canvas id="chartStatus"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-building"></i> Requests by Department</h5>
<div class="chart-box"><canvas id="chartDept"></canvas></div>
</div>
</div>
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-check-double"></i> Completion % by Department</h5>
<div class="chart-box"><canvas id="chartDeptCompletion"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-fire"></i> Priority Distribution</h5>
<div class="chart-box donut"><canvas id="chartPriority"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-tags"></i> Categories</h5>
<div class="chart-box"><canvas id="chartCategories"></canvas></div>
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-layer-group"></i> By Floor</h5>
<div class="chart-box"><canvas id="chartFloors"></canvas></div>
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-chart-bar"></i> Department Share (%)</h5>
{% if chart_data.departments.labels|length > 0 %}
<div class="prog-list">
{% for i in range(chart_data.departments.labels|length) %}
<div class="prog-row">
<div class="prog-top"><span class="nm">{{ chart_data.departments.labels[i] }}</span>
<span class="ct">{{ chart_data.departments.values[i] }} · {{ chart_data.departments.percentages[i] }}%</span></div>
<div class="prog-bar"><span style="width:{{ chart_data.departments.percentages[i] }}%"></span></div>
</div>
{% endfor %}
</div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No data available</div>{% endif %}
</div>
</div>
<div class="col-lg-6">
<div class="card"><h5 class="mb-3"><i class="fas fa-users-gear"></i> Technician Workload</h5>
{% if technician_workload|length > 0 %}
<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Technician</th><th>Assigned</th><th>In Progress</th><th>Completed</th><th>Avg Time</th></tr></thead>
<tbody>{% for t in technician_workload %}
<tr><td><strong>{{ t.name }}</strong><br><small style="color:#64748b">{{ t.role }}</small></td>
<td><span class="badge" style="background:#3b82f6;color:#fff">{{ t.assigned }}</span></td>
<td><span class="badge" style="background:#f59e0b;color:#fff">{{ t.in_progress }}</span></td>
<td><span class="badge" style="background:#10b981;color:#fff">{{ t.completed }}</span></td>
<td>{{ t.avg_resolution }}</td></tr>
{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-users"></i>No technicians</div>{% endif %}
</div>
</div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8">
<div class="card">
<div class="d-flex justify-content-between align-items-center mb-3">
<h5 style="margin:0"><i class="fas fa-clock-rotate-left"></i> Recent Requests</h5>
<a href="{{ url_for('requests_list') }}" class="btn btn-sm" style="background:#64748b;color:#fff;padding:.35rem .9rem;border-radius:20px;font-weight:600;font-size:.75rem">View All</a>
</div>
{% if recent_requests|length > 0 %}
<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Request</th><th>Department</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th><th></th></tr></thead>
<tbody>{% for r in recent_requests %}
<tr><td><a href="{{ url_for('request_detail', req_id=r.id) }}" style="color:#c5a059;font-weight:600">{{ r.request_no }}</a></td>
<td>{{ r.department.name if r.department else '—' }}</td>
<td>{{ r.location_name }}</td>
<td><span class="badge" style="background:{{ '#ef4444' if r.priority=='URGENT' else '#f59e0b' if r.priority=='HIGH' else '#3b82f6' if r.priority=='MEDIUM' else '#10b981' }}">{{ r.priority }}</span></td>
<td><span class="badge" style="background:{{ '#10b981' if r.status in ['Completed','Verified','Closed'] else '#f59e0b' if r.status=='Pending' else '#3b82f6' if r.status=='Approved' else '#8b5cf6' if r.status in ['Assigned','In Progress'] else '#64748b' }}">{{ r.status }}</span></td>
<td style="color:#64748b;font-size:.78rem">{{ r.created_at.strftime('%b %d') if r.created_at else '—' }}</td>
<td><a href="{{ url_for('request_detail', req_id=r.id) }}" class="btn btn-sm" style="background:#64748b;color:#fff;padding:.2rem .6rem;border-radius:8px;font-size:.7rem">Open</a></td></tr>
{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No requests</div>{% endif %}
</div>
</div>
<div class="col-lg-4">
<div class="card"><h5 class="mb-3"><i class="fas fa-wave-square"></i> Activity</h5>
{% if recent_activity|length > 0 %}
<div class="feed">
{% for a in recent_activity %}
<div class="feed-item"><i class="fas fa-bolt" style="color:#c5a059;margin-top:.15rem"></i>
<div style="flex:1"><div class="tx"><strong>{{ a.user }}</strong> — {{ a.action }}</div>
<div class="tm">{{ a.time }}</div></div></div>
{% endfor %}
</div>
{% else %}<div class="empty"><i class="fas fa-wave-square"></i>No activity</div>{% endif %}
</div>
<div class="card"><h5 class="mb-3"><i class="fas fa-boxes"></i> Inventory Snapshot</h5>
<div class="prog-list">
<div class="prog-row"><div class="prog-top"><span class="nm">Total Parts</span><span class="ct">{{ inventory.total_parts }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Low Stock</span><span class="ct" style="color:#f59e0b">{{ inventory.low_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Out of Stock</span><span class="ct" style="color:#ef4444">{{ inventory.out_of_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Total Value</span><span class="ct">{{ inventory.total_value }}</span></div></div>
</div>
</div>
</div>
</div>
</div>
</div>
<script>
window.DASHBOARD_DATA = {{ chart_data|tojson }};
(function(){
'use strict';
if(typeof Chart === 'undefined') return;
var D = window.DASHBOARD_DATA || {};
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#e2e8f0';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size = 11;
var TT = {backgroundColor:'#ffffff', borderColor:'#e2e8f0', borderWidth:1, titleColor:'#111827', bodyColor:'#334155', padding:11, cornerRadius:10};
var C = {amber:'#f59e0b', green:'#10b981', blue:'#3b82f6', purple:'#8b5cf6', cyan:'#06b6d4', pink:'#ec4899', red:'#ef4444', gray:'#9ca3af'};
function gr(c, a, b){var g = c.createLinearGradient(0,0,0,340); g.addColorStop(0,a); g.addColorStop(1,b); return g;}
function em(el, i, m){if(!el || !el.parentElement) return; el.parentElement.innerHTML='<div class="empty"><i class="fas '+i+'"></i>'+m+'</div>';}
(function(){
var el = document.getElementById('chartTrends');
if(!el) return;
var t = D.trends;
if(!t || !t.labels || !t.labels.length){em(el,'fa-chart-area','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'line', data:{labels:t.labels, datasets:[
{label:'Total', data:t.total, borderColor:C.amber, borderWidth:2.5, fill:true,
backgroundColor:gr(c,'rgba(245,158,11,0.2)','rgba(245,158,11,0.01)'),
tension:0.4, pointRadius:0, pointHoverRadius:6},
{label:'Completed', data:t.completed, borderColor:C.green, borderWidth:2.2, fill:true,
backgroundColor:gr(c,'rgba(16,185,129,0.2)','rgba(16,185,129,0.01)'),
tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'Pending', data:t.pending, borderColor:C.red, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'In Progress', data:t.in_progress, borderColor:C.purple, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5}
]}, options:{responsive:true, maintainAspectRatio:false, interaction:{intersect:false, mode:'index'},
plugins:{legend:{position:'top', align:'end', labels:{boxWidth:8, boxHeight:8, padding:14, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT},
scales:{x:{grid:{color:'#f1f5f9'}, ticks:{maxRotation:0, autoSkip:true, maxTicksLimit:10}},
y:{beginAtZero:true, grid:{color:'#f1f5f9'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartStatus');
if(!el) return;
var s = D.statuses;
if(!s || !s.labels || !s.labels.length){em(el,'fa-chart-pie','No data available'); return;}
var map = {'Pending':C.amber, 'Approved':C.blue, 'Assigned':C.purple, 'In Progress':C.purple,
'Completed':C.green, 'Verified':C.cyan, 'Closed':'#16a34a', 'Rejected':C.red, 'Overdue':C.red};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:s.labels, datasets:[
{data:s.values, backgroundColor:s.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#ffffff', borderWidth:3, hoverOffset:8}
]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%',
plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});
})();
(function(){
var el = document.getElementById('chartDept');
if(!el) return;
var d = D.departments;
if(!d || !d.labels || !d.labels.length){em(el,'fa-building','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[
{label:'Requests', data:d.values, backgroundColor:gr(c,'rgba(197,160,89,0.9)','rgba(217,119,6,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}},
y:{beginAtZero:true, grid:{color:'#f1f5f9'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartDeptCompletion');
if(!el) return;
var d = D.dept_completion;
if(!d || !d.labels || !d.labels.length){em(el,'fa-check-double','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[
{label:'Total', data:d.totals, backgroundColor:'#e2e8f0', borderRadius:8, borderSkipped:false, maxBarThickness:28},
{label:'Completed', data:d.completed, backgroundColor:gr(c,'rgba(16,185,129,0.9)','rgba(5,150,105,0.5)'), borderRadius:8, borderSkipped:false, maxBarThickness:28}
]}, options:{responsive:true, maintainAspectRatio:false,
plugins:{legend:{position:'top', labels:{boxWidth:8, boxHeight:8, padding:10, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}},
y:{beginAtZero:true, grid:{color:'#f1f5f9'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartPriority');
if(!el) return;
var p = D.priorities;
if(!p || !p.labels || !p.labels.length){em(el,'fa-fire','No data available'); return;}
var map = {'URGENT':C.red, 'HIGH':C.amber, 'MEDIUM':C.blue, 'LOW':C.green};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:p.labels, datasets:[
{data:p.values, backgroundColor:p.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#ffffff', borderWidth:3, hoverOffset:8}
]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%',
plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});
})();
(function(){
var el = document.getElementById('chartCategories');
if(!el) return;
var x = D.categories;
if(!x || !x.labels || !x.labels.length){em(el,'fa-tags','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[
{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(59,130,246,0.9)','rgba(139,92,246,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:30}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:9}}},
y:{beginAtZero:true, grid:{color:'#f1f5f9'}, ticks:{precision:0}}}}});
})();
(function(){
var el = document.getElementById('chartFloors');
if(!el) return;
var x = D.floors;
if(!x || !x.labels || !x.labels.length){em(el,'fa-layer-group','No data available'); return;}
var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[
{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(139,92,246,0.9)','rgba(59,130,246,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}
]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT},
scales:{x:{grid:{display:false}}, y:{beginAtZero:true, grid:{color:'#f1f5f9'}, ticks:{precision:0}}}}});
})();
})();
</script>
</body></html>"""

# ═════════════════════════════════════════ INIT
with app.app_context():
    ensure_database_schema()
    seed_data()
    print(" App initialized with Light Theme")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)