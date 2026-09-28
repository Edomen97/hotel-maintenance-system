# app.py - Rori Hotel Premium Dark Dashboard
import csv, io, json, os, re, sqlite3, uuid, traceback
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect
from flask import (Flask, abort, flash, get_flashed_messages, jsonify, redirect,
                   render_template, render_template_string, request, send_file, url_for, Response, make_response)
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

# ══════════════════════════════════════════ MODELS (UNCHANGED)
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

# ══════════════════════════════════════════ HELPERS (UNCHANGED)
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
    title = " Assigned to you: " + str(wo.work_order_no)
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
        except Exception as e: print("️ Schema error: " + str(e))

# ══════════════════════════════════════════ PREMIUM DARK PAGE TEMPLATE
def page(title, content):
    nav = []
    if current_user.is_authenticated:
        r = current_user.role
        if r == "DEPARTMENT":
            nav = [
                ('<i class="fas fa-home"></i> Dashboard', url_for('department_dashboard')),
                ('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')),
                ('<i class="fas fa-clipboard-list"></i> My Requests', url_for('requests_list')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))
            ]
        elif r == "EMPLOYEE":
            nav = [
                ('<i class="fas fa-home"></i> My Dashboard', url_for('employee_dashboard')),
                ('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')),
                ('<i class="fas fa-clipboard-list"></i> My Requests', url_for('requests_list')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))
            ]
        elif r in STAFF_ROLES:
            nav = [
                ('<i class="fas fa-tools"></i> My Tasks', url_for('workorders_list')),
                ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))
            ]
        else:
            nav = [
                ('<i class="fas fa-tachometer-alt"></i> Dashboard', url_for('dashboard')),
                ('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')),
                ('<i class="fas fa-clipboard-list"></i> Requests', url_for('requests_list')),
                ('<i class="fas fa-tasks"></i> Work Orders', url_for('workorders_list')),
                ('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')),
                ('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')),
                ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                ('<i class="fas fa-truck"></i> Suppliers', url_for('suppliers_list')),
                ('<i class="fas fa-users"></i> Employees', url_for('employees_list'))
            ]
        if r == "ADMIN":
            nav += [
                ('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')),
                ('<i class="fas fa-history"></i> Audit Log', url_for('audit_logs')),
                ('<i class="fas fa-archive"></i> Archived', url_for('deleted_requests')),
                ('<i class="fas fa-database"></i> Backup', url_for('backup_page')),
                ('<i class="fas fa-chart-line"></i> Management Reports', url_for('management_reports'))
            ]
        elif r == "MANAGER":
            nav += [
                ('<i class="fas fa-chart-line"></i> Management Reports', url_for('management_reports'))
            ]
        nav += [
            ('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')),
            ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
            ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
            ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))
        ]
    else:
        nav = [('<i class="fas fa-sign-in-alt"></i> Login', url_for('login'))]
    
    nav_html = "".join('<li><a class="nav-link" href="' + str(u) + '">' + str(l) + '</a></li>' for l, u in nav)
    
    bell_html = ""
    sound_toggle = ""
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        badge = '<span class="notif-badge">' + str(unread) + '</span>' if unread > 0 else ""
        bell_html = '<a class="header-icon" href="' + url_for('notifications') + '" style="position:relative;"><i class="fas fa-bell"></i>' + badge + '</a>'
        
        if current_user.role in ["ADMIN", "MANAGER"]:
            sound_toggle = '''
            <div class="sound-control">
                <button class="btn-icon" onclick="roriToggleSound(true)" title="Sound ON"><i class="fas fa-volume-up"></i></button>
                <button class="btn-icon" onclick="roriToggleSound(false)" title="Sound OFF"><i class="fas fa-volume-mute"></i></button>
                <button class="btn-icon" onclick="roriTestSound()" title="Test Sound"><i class="fas fa-play"></i></button>
            </div>
            '''
    
    flash_html = "".join('<div class="alert alert-' + str(c) + ' alert-dismissible fade show">' + str(m) + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>' for c, m in get_flashed_messages(with_categories=True))
    
    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>""" + str(title) + """ | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root {
    --rori-gold: #C5A059;
    --rori-gold-dark: #A8873F;
    --bg-primary: #0B0B12;
    --bg-secondary: #11111B;
    --bg-card: #151522;
    --bg-card-hover: #1B1B2A;
    --border-color: rgba(197,160,89,0.20);
    --text-primary: #FFFFFF;
    --text-secondary: #A7A7B3;
    --success: #22C55E;
    --warning: #F59E0B;
    --danger: #EF4444;
    --info: #38BDF8;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'Plus Jakarta Sans', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    padding-top: 70px;
}

/* HEADER */
.header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 70px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 2rem;
    z-index: 1000;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}

.header-left {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.logo {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--rori-gold);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.logo i { font-size: 1.8rem; }

.header-right {
    display: flex;
    align-items: center;
    gap: 1.5rem;
}

.header-icon {
    color: var(--text-secondary);
    font-size: 1.2rem;
    text-decoration: none;
    position: relative;
    transition: color 0.3s;
}

.header-icon:hover { color: var(--rori-gold); }

.notif-badge {
    position: absolute;
    top: -8px;
    right: -8px;
    background: var(--danger);
    color: white;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 10px;
    min-width: 18px;
    text-align: center;
}

.user-profile {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    cursor: pointer;
}

.user-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--rori-gold), var(--rori-gold-dark));
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    color: white;
}

.user-info {
    display: flex;
    flex-direction: column;
}

.user-name {
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--text-primary);
}

.user-role {
    font-size: 0.75rem;
    color: var(--text-secondary);
}

.sound-control {
    display: flex;
    gap: 0.5rem;
}

.btn-icon {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    width: 36px;
    height: 36px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.3s;
}

.btn-icon:hover {
    background: var(--bg-card-hover);
    color: var(--rori-gold);
    border-color: var(--rori-gold);
}

/* SIDEBAR */
.sidebar {
    position: fixed;
    left: 0;
    top: 70px;
    bottom: 0;
    width: 260px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    padding: 1.5rem 0;
    overflow-y: auto;
    z-index: 999;
    transition: transform 0.3s;
}

.sidebar-nav {
    list-style: none;
}

.sidebar-nav li {
    margin: 0.25rem 0;
}

.sidebar-nav .nav-link {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1.5rem;
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
    transition: all 0.3s;
    border-left: 3px solid transparent;
}

.sidebar-nav .nav-link:hover {
    background: var(--bg-card);
    color: var(--text-primary);
    border-left-color: var(--rori-gold);
}

.sidebar-nav .nav-link.active {
    background: rgba(197,160,89,0.1);
    color: var(--rori-gold);
    border-left-color: var(--rori-gold);
}

.sidebar-nav .nav-link i {
    width: 20px;
    text-align: center;
}

/* MAIN CONTENT */
.main-content {
    margin-left: 260px;
    padding: 2rem;
    min-height: calc(100vh - 70px);
}

/* PAGE TITLE */
.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    flex-wrap: wrap;
    gap: 1rem;
}

.page-title h1 {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--text-primary);
    margin-bottom: 0.25rem;
}

.page-title h1 span {
    color: var(--rori-gold);
}

.page-title p {
    font-size: 0.9rem;
    color: var(--text-secondary);
}

.btn-primary {
    background: linear-gradient(135deg, var(--rori-gold), var(--rori-gold-dark));
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.3s;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(197,160,89,0.3);
}

/* KPI CARDS */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.kpi-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 1.5rem;
    transition: all 0.3s;
    position: relative;
    overflow: hidden;
}

.kpi-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--rori-gold);
    transform: translateY(-4px);
    box-shadow: 0 12px 30px rgba(0,0,0,0.4);
}

.kpi-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--rori-gold), transparent);
}

.kpi-icon {
    font-size: 2rem;
    color: var(--rori-gold);
    margin-bottom: 1rem;
}

.kpi-value {
    font-size: 2.5rem;
    font-weight: 800;
    color: var(--text-primary);
    margin-bottom: 0.5rem;
}

.kpi-label {
    font-size: 0.85rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 600;
}

.kpi-trend {
    font-size: 0.8rem;
    margin-top: 0.5rem;
    color: var(--success);
}

.kpi-trend.negative { color: var(--danger); }

/* CARDS */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.card-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.card-title i { color: var(--rori-gold); }

/* CHART CONTAINERS */
.chart-container {
    position: relative;
    height: 300px;
}

.chart-container.tall { height: 400px; }

/* TABLES */
.table {
    width: 100%;
    border-collapse: collapse;
}

.table thead th {
    background: var(--bg-secondary);
    color: var(--rori-gold);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 1rem;
    text-align: left;
    border-bottom: 2px solid var(--border-color);
}

.table tbody td {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-primary);
    font-size: 0.9rem;
}

.table tbody tr:hover {
    background: var(--bg-card-hover);
}

/* BADGES */
.badge {
    padding: 0.4rem 0.8rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    display: inline-block;
}

.badge-success { background: rgba(34,197,94,0.2); color: var(--success); }
.badge-warning { background: rgba(245,158,11,0.2); color: var(--warning); }
.badge-danger { background: rgba(239,68,68,0.2); color: var(--danger); }
.badge-info { background: rgba(56,189,248,0.2); color: var(--info); }
.badge-secondary { background: rgba(167,167,179,0.2); color: var(--text-secondary); }

/* ALERTS */
.alert {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin-bottom: 1rem;
    color: var(--text-primary);
}

.alert-success { border-left: 4px solid var(--success); }
.alert-danger { border-left: 4px solid var(--danger); }
.alert-warning { border-left: 4px solid var(--warning); }
.alert-info { border-left: 4px solid var(--info); }

/* FORMS */
.form-control, .form-select {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    color: var(--text-primary);
    padding: 0.75rem 1rem;
    font-size: 0.9rem;
}

.form-control:focus, .form-select:focus {
    background: var(--bg-card-hover);
    border-color: var(--rori-gold);
    box-shadow: 0 0 0 3px rgba(197,160,89,0.15);
    color: var(--text-primary);
}

.form-label {
    color: var(--text-secondary);
    font-weight: 500;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
}

/* MOBILE MENU TOGGLE */
.menu-toggle {
    display: none;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 1.5rem;
    cursor: pointer;
}

/* RESPONSIVE */
@media (max-width: 1024px) {
    .sidebar {
        transform: translateX(-100%);
    }
    
    .sidebar.active {
        transform: translateX(0);
    }
    
    .main-content {
        margin-left: 0;
    }
    
    .menu-toggle {
        display: block;
    }
}

@media (max-width: 768px) {
    .header {
        padding: 0 1rem;
    }
    
    .user-info {
        display: none;
    }
    
    .main-content {
        padding: 1rem;
    }
    
    .kpi-grid {
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 1rem;
    }
    
    .kpi-value {
        font-size: 2rem;
    }
    
    .page-header {
        flex-direction: column;
        align-items: flex-start;
    }
}

/* ANIMATIONS */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.pulse {
    animation: pulse 2s infinite;
}

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.card {
    animation: slideIn 0.5s ease-out;
}

/* SCROLLBAR */
::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--bg-secondary);
}

::-webkit-scrollbar-thumb {
    background: var(--rori-gold);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--rori-gold-dark);
}
</style></head><body>

<!-- HEADER -->
<header class="header">
    <div class="header-left">
        <button class="menu-toggle" onclick="toggleSidebar()">
            <i class="fas fa-bars"></i>
        </button>
        <a href="/" class="logo">
            <i class="fas fa-hotel"></i>
            <span>RORI HOTEL</span>
        </a>
    </div>
    <div class="header-right">
        """ + sound_toggle + bell_html + """
        <div class="user-profile">
            <div class="user-avatar">""" + (current_user.full_name[0].upper() if current_user.full_name else current_user.username[0].upper()) + """</div>
            <div class="user-info">
                <div class="user-name">""" + str(current_user.full_name or current_user.username) + """</div>
                <div class="user-role">""" + str(current_user.role) + """</div>
            </div>
        </div>
    </div>
</header>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
    <ul class="sidebar-nav">
        """ + nav_html + """
    </ul>
</aside>

<!-- MAIN CONTENT -->
<main class="main-content">
    """ + flash_html + content + """
</main>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('active');
}

// Notification Sound System
let roriAudioCtx = null;
let roriSoundEnabled = localStorage.getItem('rori_sound_enabled') === 'true';
let roriAlertedRequests = JSON.parse(sessionStorage.getItem('rori_alerted_requests') || '[]');

function roriInitAudio() {
    if (!roriAudioCtx) {
        roriAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (roriAudioCtx.state === 'suspended') {
        roriAudioCtx.resume();
    }
}

function roriPlayAlert(priority) {
    if (!roriSoundEnabled || !roriAudioCtx) return;
    const osc = roriAudioCtx.createOscillator();
    const gain = roriAudioCtx.createGain();
    osc.connect(gain);
    gain.connect(roriAudioCtx.destination);
    
    if (priority === 'URGENT') {
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime);
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime + 0.15);
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime + 0.3);
    } else {
        osc.frequency.setValueAtTime(660, roriAudioCtx.currentTime);
    }
    
    gain.gain.setValueAtTime(0.1, roriAudioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, roriAudioCtx.currentTime + 0.5);
    
    osc.start(roriAudioCtx.currentTime);
    osc.stop(roriAudioCtx.currentTime + 0.5);
}

window.roriToggleSound = function(enable) {
    roriSoundEnabled = enable;
    localStorage.setItem('rori_sound_enabled', roriSoundEnabled);
    if (enable) roriInitAudio();
    alert('Notification sound ' + (enable ? 'ENABLED' : 'DISABLED'));
};

window.roriTestSound = function() {
    roriInitAudio();
    roriSoundEnabled = true;
    roriPlayAlert('HIGH');
};

// Poll for notifications
function pollNotifications() {
    fetch('/api/notifications/unread', {credentials: 'same-origin', cache: 'no-store'})
    .then(r => r.ok ? r.json() : null)
    .then(d => {
        if (!d) return;
        if (d.latest_title && d.latest_title.includes('NEW MAINTENANCE REQUEST')) {
            let priority = 'MEDIUM';
            if (d.latest_title.includes('URGENT')) priority = 'URGENT';
            else if (d.latest_title.includes('HIGH')) priority = 'HIGH';
            
            if (!roriAlertedRequests.includes(d.latest_id)) {
                roriInitAudio();
                roriPlayAlert(priority);
                roriAlertedRequests.push(d.latest_id);
                sessionStorage.setItem('rori_alerted_requests', JSON.stringify(roriAlertedRequests));
                
                // Visual notification
                const badge = document.querySelector('.notif-badge');
                if (badge) {
                    badge.classList.add('pulse');
                    setTimeout(() => badge.classList.remove('pulse'), 2000);
                }
            }
        }
    })
    .catch(() => {});
}

if (document.querySelector('.header-icon')) {
    pollNotifications();
    setInterval(pollNotifications, 10000);
}
</script>
</body></html>"""

# ══════════════════════════════════════════ SEED DATA (UNCHANGED)
def seed_data():
    for name in ["Housekeeping","Front Office","Engineering","Food & Beverage","Kitchen","Finance","HR","Security","IT","Sales & Marketing","Administration","Maintenance","Other","SPA","GM"]:
        if not Department.query.filter_by(name=name).first():
            db.session.add(Department(name=name))
    db.session.commit()
    for f in [2,3,4,5]:
        if not Floor.query.filter_by(floor_number=f).first():
            db.session.add(Floor(floor_number=f))
    if Room.query.count() == 0:
        for num in range(201, 301):
            floor = 2 if num <= 225 else 3 if num <= 250 else 4 if num <= 275 else 5
            db.session.add(Room(floor=floor, room_number=str(num), status="Available"))
    for n, d in [("Buduchalley","F&B"),("Sillanto","Unknown"),("Fura","Unknown"),("Executive","Unknown"),("Mitima","Unknown"),("Odako","Unknown"),("Gudumale","Unknown"),("Bubble","Unknown"),("Bubbles","Unknown"),("Fura Corridor","Unknown"),("Executive Meeting Room","Unknown"),("Counter","Unknown")]:
        if not Area.query.filter_by(name=n).first(): db.session.add(Area(name=n, department=d))
    for c in ["Electrical","Plumbing","HVAC","Painting","Carpentry","Civil","Safety","General","Other"]:
        if not Category.query.filter_by(name=c).first(): db.session.add(Category(name=c))
    for i in ["Light","Switch","Window","Door Key","Door Lock","Paint","Mirror","Drainage Cover","Frame","Background Frame","Spot Light","Plumbing","AC","Electrical","Other"]:
        if not WorkingItem.query.filter_by(name=i).first(): db.session.add(WorkingItem(name=i))
    for eid, n, t in [(1,"Mechanic 1","General Mechanic"),(2,"Mechanic 2","General Mechanic"),(3,"Mechanic 3","General Mechanic"),(4,"Supervisor 1","Supervisor"),(5,"Amir Awel","Manager")]:
        if not db.session.get(Employee, eid): db.session.add(Employee(id=eid, name=n, job_title=t, department="Engineering"))
    if Supplier.query.count() == 0:
        for s in ["ABC Maintenance Supply","Hawassa Engineering Supply","Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=s, contact_person="", phone="", status="Active", is_active=True))
    hk = Department.query.filter_by(name="Housekeeping").first()
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        u.set_password("admin123")
        db.session.add(u)
    for s in [
        {"u":"amir","n":"Amir Awel","r":"MANAGER","d":None},
        {"u":"kasahun","n":"Kasahun Girma","r":"MANAGER","d":hk.id if hk else None},
        {"u":"abebayhu","n":"Abebaw","r":"SUPERVISOR","d":None},
        {"u":"tesfahun","n":"Tesfahun","r":"TECHNICIAN","d":None},
        {"u":"simon","n":"Simon","r":"TECHNICIAN","d":None},
        {"u":"chernet","n":"Chernet","r":"TECHNICIAN","d":None},
        {"u":"wale","n":"Wale","r":"TECHNICIAN","d":None},
        {"u":"tsadiku","n":"Tsadiku","r":"TECHNICIAN","d":None},
        {"u":"employee1","n":"Test Employee","r":"EMPLOYEE","d":None},
        {"u":"housekeeping","n":"Kassahun Girma","r":"DEPARTMENT","d":hk.id if hk else None},
    ]:
        ex = User.query.filter_by(username=s["u"]).first()
        if not ex:
            u = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=s["d"])
            u.set_password("123456")
            db.session.add(u)
        else:
            ex.full_name = s["n"]; ex.role = s["r"]; ex.department_id = s["d"]
    dept_map = {
        "it": {"n": "To be configured later", "dept": "IT"},
        "fnb": {"n": "Bahilu Boja", "dept": "Food & Beverage"},
        "security": {"n": "Tariku Bekele", "dept": "Security"},
        "kitchen": {"n": "Biruk Haile", "dept": "Kitchen"},
        "spa": {"n": "Tesfaye Yohanes", "dept": "SPA"},
        "finance": {"n": "Abel Yemane", "dept": "Finance"},
        "gm": {"n": "Muluken Gedafew", "dept": "GM"},
    }
    for uname, info in dept_map.items():
        dept = Department.query.filter_by(name=info["dept"]).first()
        if not dept: continue
        ex = User.query.filter_by(username=uname).first()
        if not ex:
            u = User(username=uname, full_name=info["n"], role="DEPARTMENT", department_id=dept.id, email=uname + "@rorihotel.local")
            u.set_password("123456")
            db.session.add(u)
        else:
            ex.full_name = info["n"]; ex.role = "DEPARTMENT"; ex.department_id = dept.id
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
            db.session.add(DepartmentSignature(department_id=dept.id, authorized_name=cfg["name"], is_active=True))
        else:
            existing.authorized_name = cfg["name"]; existing.is_active = True
    db.session.commit()
    print("✅ Seed data loaded")

# ══════════════════════════════════════════ ROUTES (UNCHANGED - keeping all existing routes)
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
    lh = """<div class="login-container">
<div class="login-card">
<div class="text-center mb-4">
<i class="fas fa-hotel" style="font-size:3rem;color:var(--rori-gold);margin-bottom:1rem;"></i>
<h3 class="fw-bold" style="color:var(--rori-gold)">RORI HOTEL</h3>
<p style="color:var(--text-secondary)">Maintenance Management System</p>
</div>
<form method="post">
<div class="mb-3">
<label class="form-label">Username</label>
<input type="text" class="form-control" name="username" required autofocus>
</div>
<div class="mb-4">
<label class="form-label">Password</label>
<input type="password" class="form-control" name="password" required>
</div>
<button class="btn-primary w-100"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<hr style="border-color:var(--border-color);margin:1.5rem 0">
<div class="text-center small" style="color:var(--text-secondary)">
<p class="mb-1">Manager: <b style="color:var(--rori-gold)">amir / 123456</b></p>
<p class="mb-1">F&B: <b style="color:var(--rori-gold)">fnb / 123456</b></p>
<p class="mb-0">Admin: <b style="color:var(--rori-gold)">admin / admin123</b></p>
</div>
</div>
</div>
<style>
.login-container {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: calc(100vh - 70px);
    padding: 2rem;
}
.login-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 20px;
    padding: 2.5rem;
    max-width: 440px;
    width: 100%;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
</style>"""
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
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-user-circle"></i> Profile</h1></div></div>'
         '<div class="card"><h4 style="color:var(--rori-gold);margin-bottom:1rem;">' + str(u.full_name) + '</h4>'
         '<p>@' + str(u.username) + ' · <span class="badge badge-warning">' + str(u.role) + '</span></p>'
         '<p style="color:var(--text-secondary);">📧 ' + str(u.email or "—") + ' | 📱 ' + str(u.phone or "—") + '</p>'
         '<p style="color:var(--text-secondary);">🏢 Department: <strong style="color:var(--text-primary);">' + str(u.department.name if u.department else "Not assigned") + '</strong></p><hr style="border-color:var(--border-color);">'
         '<form method="post"><div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + str(u.email or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + str(u.phone or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">New Password</label><input type="password" class="form-control" name="new_password" placeholder="Leave blank to keep current"></div>'
         '<button class="btn-primary"><i class="fas fa-save"></i> Save</button></form></div>')
    return page("Profile", c)

# ══════════════════════════════════════════ DASHBOARD (PREMIUM REDESIGN)
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role in STAFF_ROLES: return redirect(url_for("workorders_list"))
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    
    # Get real data from database
    total_requests = MaintenanceRequest.query.filter_by(is_deleted=False).count()
    pending = MaintenanceRequest.query.filter_by(is_deleted=False, status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(is_deleted=False, status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(is_deleted=False, status="Completed").count()
    verified = MaintenanceRequest.query.filter_by(is_deleted=False, status="Verified").count()
    urgent = MaintenanceRequest.query.filter_by(is_deleted=False, priority="URGENT").count()
    
    # Calculate work hours
    work_orders = WorkOrder.query.all()
    total_hours = sum(wo.labor_hours or 0 for wo in work_orders)
    
    # Active staff
    active_staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).count()
    
    # Get recent requests for alert
    recent_requests = MaintenanceRequest.query.filter_by(is_deleted=False).order_by(MaintenanceRequest.created_at.desc()).limit(5).all()
    
    # Get chart data
    from_date = datetime.utcnow() - timedelta(days=30)
    daily_data = db.session.query(
        db.func.date(MaintenanceRequest.created_at).label('date'),
        db.func.count(MaintenanceRequest.id).label('count')
    ).filter(
        MaintenanceRequest.created_at >= from_date,
        MaintenanceRequest.is_deleted == False
    ).group_by(db.func.date(MaintenanceRequest.created_at)).all()
    
    chart_labels = [d.date for d in daily_data]
    chart_values = [d.count for d in daily_data]
    
    # Department distribution
    dept_stats = db.session.query(
        Department.name,
        db.func.count(MaintenanceRequest.id).label('count')
    ).join(
        MaintenanceRequest, Department.id == MaintenanceRequest.department_id
    ).filter(
        MaintenanceRequest.is_deleted == False
    ).group_by(Department.name).all()
    
    dept_labels = [d.name for d in dept_stats]
    dept_values = [d.count for d in dept_stats]
    
    # Status distribution
    status_stats = db.session.query(
        MaintenanceRequest.status,
        db.func.count(MaintenanceRequest.id).label('count')
    ).filter(
        MaintenanceRequest.is_deleted == False
    ).group_by(MaintenanceRequest.status).all()
    
    status_labels = [s.status for s in status_stats]
    status_values = [s.count for s in status_stats]
    
    # Staff workload
    staff_workload = db.session.query(
        User.full_name,
        db.func.count(WorkOrder.id).label('assigned'),
        db.func.sum(db.case((WorkOrder.status == 'In Progress', 1), else_=0)).label('in_progress'),
        db.func.sum(db.case((WorkOrder.status.in_(['Completed', 'Verified']), 1), else_=0)).label('completed')
    ).join(
        WorkOrder, User.id == WorkOrder.assigned_to_id
    ).filter(
        User.role.in_(STAFF_ROLES),
        User.active == True
    ).group_by(User.full_name).all()
    
    chart_data = {
        "daily": {"labels": chart_labels, "values": chart_values},
        "departments": {"labels": dept_labels, "values": dept_values},
        "status": {"labels": status_labels, "values": status_values},
        "staff": [{"name": s.full_name, "assigned": s.assigned, "in_progress": s.in_progress or 0, "completed": s.completed or 0} for s in staff_workload]
    }
    
    return render_template_string(DASHBOARD_TEMPLATE,
        total_requests=total_requests,
        pending=pending,
        in_progress=in_progress,
        completed=completed,
        verified=verified,
        urgent=urgent,
        total_hours=total_hours,
        active_staff=active_staff,
        recent_requests=recent_requests,
        chart_data=chart_data,
        current_user=current_user
    )

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rori Hotel Command Center</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {
    --rori-gold: #C5A059;
    --rori-gold-dark: #A8873F;
    --bg-primary: #0B0B12;
    --bg-secondary: #11111B;
    --bg-card: #151522;
    --bg-card-hover: #1B1B2A;
    --border-color: rgba(197,160,89,0.20);
    --text-primary: #FFFFFF;
    --text-secondary: #A7A7B3;
    --success: #22C55E;
    --warning: #F59E0B;
    --danger: #EF4444;
    --info: #38BDF8;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'Plus Jakarta Sans', sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    padding-top: 70px;
}

/* HEADER */
.header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 70px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 2rem;
    z-index: 1000;
    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
}

.header-left { display: flex; align-items: center; gap: 1rem; }

.logo {
    font-size: 1.5rem;
    font-weight: 800;
    color: var(--rori-gold);
    text-decoration: none;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.logo i { font-size: 1.8rem; }

.header-right { display: flex; align-items: center; gap: 1.5rem; }

.header-icon {
    color: var(--text-secondary);
    font-size: 1.2rem;
    text-decoration: none;
    position: relative;
    transition: color 0.3s;
}

.header-icon:hover { color: var(--rori-gold); }

.notif-badge {
    position: absolute;
    top: -8px;
    right: -8px;
    background: var(--danger);
    color: white;
    font-size: 0.7rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 10px;
    min-width: 18px;
    text-align: center;
}

.user-profile { display: flex; align-items: center; gap: 0.75rem; cursor: pointer; }

.user-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: linear-gradient(135deg, var(--rori-gold), var(--rori-gold-dark));
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    color: white;
}

.user-info { display: flex; flex-direction: column; }

.user-name { font-weight: 600; font-size: 0.9rem; color: var(--text-primary); }
.user-role { font-size: 0.75rem; color: var(--text-secondary); }

.sound-control { display: flex; gap: 0.5rem; }

.btn-icon {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    color: var(--text-secondary);
    width: 36px;
    height: 36px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.3s;
}

.btn-icon:hover {
    background: var(--bg-card-hover);
    color: var(--rori-gold);
    border-color: var(--rori-gold);
}

/* SIDEBAR */
.sidebar {
    position: fixed;
    left: 0;
    top: 70px;
    bottom: 0;
    width: 260px;
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    padding: 1.5rem 0;
    overflow-y: auto;
    z-index: 999;
    transition: transform 0.3s;
}

.sidebar-nav { list-style: none; }
.sidebar-nav li { margin: 0.25rem 0; }

.sidebar-nav .nav-link {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.85rem 1.5rem;
    color: var(--text-secondary);
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
    transition: all 0.3s;
    border-left: 3px solid transparent;
}

.sidebar-nav .nav-link:hover {
    background: var(--bg-card);
    color: var(--text-primary);
    border-left-color: var(--rori-gold);
}

.sidebar-nav .nav-link.active {
    background: rgba(197,160,89,0.1);
    color: var(--rori-gold);
    border-left-color: var(--rori-gold);
}

.sidebar-nav .nav-link i { width: 20px; text-align: center; }

/* MAIN CONTENT */
.main-content {
    margin-left: 260px;
    padding: 2rem;
    min-height: calc(100vh - 70px);
}

/* PAGE TITLE */
.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
    flex-wrap: wrap;
    gap: 1rem;
}

.page-title h1 {
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--text-primary);
    margin-bottom: 0.25rem;
}

.page-title h1 span { color: var(--rori-gold); }

.page-title p { font-size: 0.9rem; color: var(--text-secondary); }

.btn-primary {
    background: linear-gradient(135deg, var(--rori-gold), var(--rori-gold-dark));
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.3s;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
}

.btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(197,160,89,0.3);
}

/* KPI CARDS */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
}

.kpi-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 1.5rem;
    transition: all 0.3s;
    position: relative;
    overflow: hidden;
}

.kpi-card:hover {
    background: var(--bg-card-hover);
    border-color: var(--rori-gold);
    transform: translateY(-4px);
    box-shadow: 0 12px 30px rgba(0,0,0,0.4);
}

.kpi-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--rori-gold), transparent);
}

.kpi-icon { font-size: 2rem; color: var(--rori-gold); margin-bottom: 1rem; }
.kpi-value { font-size: 2.5rem; font-weight: 800; color: var(--text-primary); margin-bottom: 0.5rem; }
.kpi-label { font-size: 0.85rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
.kpi-trend { font-size: 0.8rem; margin-top: 0.5rem; color: var(--success); }
.kpi-trend.negative { color: var(--danger); }

/* CARDS */
.card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }

.card-title {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.card-title i { color: var(--rori-gold); }

/* CHART CONTAINERS */
.chart-container { position: relative; height: 300px; }
.chart-container.tall { height: 400px; }

/* TABLES */
.table { width: 100%; border-collapse: collapse; }

.table thead th {
    background: var(--bg-secondary);
    color: var(--rori-gold);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 1rem;
    text-align: left;
    border-bottom: 2px solid var(--border-color);
}

.table tbody td {
    padding: 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-primary);
    font-size: 0.9rem;
}

.table tbody tr:hover { background: var(--bg-card-hover); }

/* BADGES */
.badge {
    padding: 0.4rem 0.8rem;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    display: inline-block;
}

.badge-success { background: rgba(34,197,94,0.2); color: var(--success); }
.badge-warning { background: rgba(245,158,11,0.2); color: var(--warning); }
.badge-danger { background: rgba(239,68,68,0.2); color: var(--danger); }
.badge-info { background: rgba(56,189,248,0.2); color: var(--info); }
.badge-secondary { background: rgba(167,167,179,0.2); color: var(--text-secondary); }

/* ALERTS */
.alert {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin-bottom: 1rem;
    color: var(--text-primary);
}

.alert-success { border-left: 4px solid var(--success); }
.alert-danger { border-left: 4px solid var(--danger); }
.alert-warning { border-left: 4px solid var(--warning); }
.alert-info { border-left: 4px solid var(--info); }

/* NEW REQUEST ALERT */
.new-request-alert {
    background: linear-gradient(135deg, rgba(197,160,89,0.1), rgba(197,160,89,0.05));
    border: 2px solid var(--rori-gold);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 2rem;
    animation: slideIn 0.5s ease-out;
}

.new-request-alert h3 {
    color: var(--rori-gold);
    font-size: 1.3rem;
    font-weight: 700;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.new-request-item {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 0.75rem;
    transition: all 0.3s;
}

.new-request-item:hover {
    border-color: var(--rori-gold);
    transform: translateX(4px);
}

/* MOBILE MENU TOGGLE */
.menu-toggle {
    display: none;
    background: none;
    border: none;
    color: var(--text-primary);
    font-size: 1.5rem;
    cursor: pointer;
}

/* RESPONSIVE */
@media (max-width: 1024px) {
    .sidebar { transform: translateX(-100%); }
    .sidebar.active { transform: translateX(0); }
    .main-content { margin-left: 0; }
    .menu-toggle { display: block; }
}

@media (max-width: 768px) {
    .header { padding: 0 1rem; }
    .user-info { display: none; }
    .main-content { padding: 1rem; }
    .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }
    .kpi-value { font-size: 2rem; }
    .page-header { flex-direction: column; align-items: flex-start; }
}

/* ANIMATIONS */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
}

.pulse { animation: pulse 2s infinite; }

@keyframes slideIn {
    from { opacity: 0; transform: translateY(20px); }
    to { opacity: 1; transform: translateY(0); }
}

.card { animation: slideIn 0.5s ease-out; }

/* SCROLLBAR */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-secondary); }
::-webkit-scrollbar-thumb { background: var(--rori-gold); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--rori-gold-dark); }
</style>
</head>
<body>

<!-- HEADER -->
<header class="header">
    <div class="header-left">
        <button class="menu-toggle" onclick="toggleSidebar()"><i class="fas fa-bars"></i></button>
        <a href="/" class="logo"><i class="fas fa-hotel"></i><span>RORI HOTEL</span></a>
    </div>
    <div class="header-right">
        <div class="sound-control">
            <button class="btn-icon" onclick="roriToggleSound(true)" title="Sound ON"><i class="fas fa-volume-up"></i></button>
            <button class="btn-icon" onclick="roriToggleSound(false)" title="Sound OFF"><i class="fas fa-volume-mute"></i></button>
            <button class="btn-icon" onclick="roriTestSound()" title="Test Sound"><i class="fas fa-play"></i></button>
        </div>
        <a class="header-icon" href="/notifications" style="position:relative;">
            <i class="fas fa-bell"></i>
            <span class="notif-badge">3</span>
        </a>
        <div class="user-profile">
            <div class="user-avatar">{{ current_user.full_name[0].upper() if current_user.full_name else current_user.username[0].upper() }}</div>
            <div class="user-info">
                <div class="user-name">{{ current_user.full_name or current_user.username }}</div>
                <div class="user-role">{{ current_user.role }}</div>
            </div>
        </div>
    </div>
</header>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
    <ul class="sidebar-nav">
        <li><a class="nav-link active" href="/dashboard"><i class="fas fa-tachometer-alt"></i> Dashboard</a></li>
        <li><a class="nav-link" href="/requests"><i class="fas fa-clipboard-list"></i> Requests</a></li>
        <li><a class="nav-link" href="/workorders"><i class="fas fa-tasks"></i> Work Orders</a></li>
        <li><a class="nav-link" href="/requests/new"><i class="fas fa-plus-circle"></i> New Request</a></li>
        <li><a class="nav-link" href="/inventory"><i class="fas fa-boxes"></i> Inventory</a></li>
        <li><a class="nav-link" href="/notifications"><i class="fas fa-bell"></i> Notifications</a></li>
        <li><a class="nav-link" href="/reports"><i class="fas fa-chart-bar"></i> Reports</a></li>
        <li><a class="nav-link" href="/management/reports"><i class="fas fa-chart-line"></i> Management</a></li>
        <li><a class="nav-link" href="/profile"><i class="fas fa-user-circle"></i> Profile</a></li>
        <li><a class="nav-link" href="/logout"><i class="fas fa-sign-out-alt"></i> Logout</a></li>
    </ul>
</aside>

<!-- MAIN CONTENT -->
<main class="main-content">
    <div class="page-header">
        <div class="page-title">
            <h1><span>Rori Hotel</span> Maintenance Command Center</h1>
            <p>Real-time maintenance operations and hotel service monitoring</p>
        </div>
        <a href="/requests/new" class="btn-primary"><i class="fas fa-plus"></i> New Request</a>
    </div>

    <!-- KPI CARDS -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div>
            <div class="kpi-value">{{ total_requests }}</div>
            <div class="kpi-label">Total Requests</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div>
            <div class="kpi-value">{{ pending }}</div>
            <div class="kpi-label">Pending</div>
            <div class="kpi-trend negative">Requires attention</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon" style="color:var(--info);"><i class="fas fa-spinner"></i></div>
            <div class="kpi-value">{{ in_progress }}</div>
            <div class="kpi-label">In Progress</div>
            <div class="kpi-trend">Currently being handled</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div>
            <div class="kpi-value">{{ completed }}</div>
            <div class="kpi-label">Completed</div>
            <div class="kpi-trend">This reporting period</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-double"></i></div>
            <div class="kpi-value">{{ verified }}</div>
            <div class="kpi-label">Verified</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon" style="color:var(--danger);"><i class="fas fa-exclamation-triangle"></i></div>
            <div class="kpi-value">{{ urgent }}</div>
            <div class="kpi-label">Urgent</div>
            <div class="kpi-trend negative">High priority</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon"><i class="fas fa-clock"></i></div>
            <div class="kpi-value">{{ "%.1f"|format(total_hours) }}</div>
            <div class="kpi-label">Work Hours</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-icon"><i class="fas fa-users"></i></div>
            <div class="kpi-value">{{ active_staff }}</div>
            <div class="kpi-label">Active Staff</div>
        </div>
    </div>

    <!-- NEW REQUEST ALERTS -->
    {% if recent_requests %}
    <div class="new-request-alert">
        <h3><i class="fas fa-bell"></i> Recent Requests</h3>
        {% for req in recent_requests[:3] %}
        <div class="new-request-item">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:1rem;">
                <div>
                    <strong style="color:var(--rori-gold);">{{ req.request_no }}</strong>
                    <span class="badge badge-{{ 'danger' if req.priority == 'URGENT' else 'warning' if req.priority == 'HIGH' else 'info' }}" style="margin-left:0.5rem;">{{ req.priority }}</span>
                </div>
                <div style="color:var(--text-secondary);font-size:0.85rem;">
                    <i class="fas fa-building"></i> {{ req.department.name if req.department else 'N/A' }}
                    <i class="fas fa-map-marker-alt" style="margin-left:1rem;"></i> {{ req.location_name }}
                </div>
                <a href="/requests/{{ req.id }}" class="btn-primary" style="padding:0.5rem 1rem;font-size:0.85rem;">View</a>
            </div>
        </div>
        {% endfor %}
    </div>
    {% endif %}

    <!-- CHARTS ROW 1 -->
    <div class="row" style="margin-bottom:2rem;">
        <div class="col-lg-8">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fas fa-chart-line"></i> Maintenance Activity</div>
                </div>
                <div class="chart-container tall">
                    <canvas id="activityChart"></canvas>
                </div>
            </div>
        </div>
        <div class="col-lg-4">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fas fa-chart-pie"></i> By Department</div>
                </div>
                <div class="chart-container">
                    <canvas id="deptChart"></canvas>
                </div>
            </div>
        </div>
    </div>

    <!-- CHARTS ROW 2 -->
    <div class="row" style="margin-bottom:2rem;">
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fas fa-tasks"></i> Work Status</div>
                </div>
                <div class="chart-container">
                    <canvas id="statusChart"></canvas>
                </div>
            </div>
        </div>
        <div class="col-lg-6">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fas fa-users"></i> Staff Workload</div>
                </div>
                <div style="overflow-x:auto;">
                    <table class="table">
                        <thead>
                            <tr>
                                <th>Staff</th>
                                <th>Assigned</th>
                                <th>In Progress</th>
                                <th>Completed</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for staff in chart_data.staff %}
                            <tr>
                                <td><strong>{{ staff.name }}</strong></td>
                                <td><span class="badge badge-info">{{ staff.assigned }}</span></td>
                                <td><span class="badge badge-warning">{{ staff.in_progress }}</span></td>
                                <td><span class="badge badge-success">{{ staff.completed }}</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- RECENT REQUESTS TABLE -->
    <div class="card">
        <div class="card-header">
            <div class="card-title"><i class="fas fa-clock"></i> Recent Requests</div>
            <a href="/requests" class="btn-primary" style="padding:0.5rem 1rem;font-size:0.85rem;">View All</a>
        </div>
        <div style="overflow-x:auto;">
            <table class="table">
                <thead>
                    <tr>
                        <th>Request ID</th>
                        <th>Department</th>
                        <th>Location</th>
                        <th>Priority</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for req in recent_requests %}
                    <tr>
                        <td><strong style="color:var(--rori-gold);">{{ req.request_no[:20] }}...</strong></td>
                        <td>{{ req.department.name if req.department else 'N/A' }}</td>
                        <td>{{ req.location_name }}</td>
                        <td><span class="badge badge-{{ 'danger' if req.priority == 'URGENT' else 'warning' if req.priority == 'HIGH' else 'info' }}">{{ req.priority }}</span></td>
                        <td><span class="badge badge-{{ 'success' if req.status in ['Completed','Verified'] else 'warning' if req.status == 'Pending' else 'info' }}">{{ req.status }}</span></td>
                        <td style="color:var(--text-secondary);font-size:0.85rem;">{{ req.created_at.strftime('%Y-%m-%d %H:%M') if req.created_at else 'N/A' }}</td>
                        <td><a href="/requests/{{ req.id }}" class="btn-primary" style="padding:0.4rem 0.8rem;font-size:0.8rem;">View</a></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</main>

<script>
// Chart Configuration
Chart.defaults.color = '#A7A7B3';
Chart.defaults.borderColor = 'rgba(197,160,89,0.1)';
Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";

const chartData = {{ chart_data|tojson }};

// Activity Chart
const activityCtx = document.getElementById('activityChart').getContext('2d');
new Chart(activityCtx, {
    type: 'line',
    data: {
        labels: chartData.daily.labels,
        datasets: [{
            label: 'Requests',
            data: chartData.daily.values,
            borderColor: '#C5A059',
            backgroundColor: 'rgba(197,160,89,0.1)',
            borderWidth: 3,
            fill: true,
            tension: 0.4,
            pointRadius: 4,
            pointBackgroundColor: '#C5A059'
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false }
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(197,160,89,0.05)' }
            },
            x: {
                grid: { display: false }
            }
        }
    }
});

// Department Chart
const deptCtx = document.getElementById('deptChart').getContext('2d');
new Chart(deptCtx, {
    type: 'doughnut',
    data: {
        labels: chartData.departments.labels,
        datasets: [{
            data: chartData.departments.values,
            backgroundColor: [
                '#C5A059', '#22C55E', '#38BDF8', '#F59E0B',
                '#EF4444', '#8B5CF6', '#EC4899', '#10B981'
            ],
            borderWidth: 0
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '70%',
        plugins: {
            legend: {
                position: 'bottom',
                labels: {
                    color: '#A7A7B3',
                    padding: 15,
                    usePointStyle: true
                }
            }
        }
    }
});

// Status Chart
const statusCtx = document.getElementById('statusChart').getContext('2d');
new Chart(statusCtx, {
    type: 'bar',
    data: {
        labels: chartData.status.labels,
        datasets: [{
            label: 'Count',
            data: chartData.status.values,
            backgroundColor: [
                'rgba(245,158,11,0.8)',
                'rgba(56,189,248,0.8)',
                'rgba(139,92,246,0.8)',
                'rgba(34,197,94,0.8)',
                'rgba(197,160,89,0.8)'
            ],
            borderRadius: 8
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false }
        },
        scales: {
            y: {
                beginAtZero: true,
                grid: { color: 'rgba(197,160,89,0.05)' }
            },
            x: {
                grid: { display: false }
            }
        }
    }
});

// Sidebar Toggle
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('active');
}

// Notification Sound System
let roriAudioCtx = null;
let roriSoundEnabled = localStorage.getItem('rori_sound_enabled') === 'true';
let roriAlertedRequests = JSON.parse(sessionStorage.getItem('rori_alerted_requests') || '[]');

function roriInitAudio() {
    if (!roriAudioCtx) {
        roriAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (roriAudioCtx.state === 'suspended') {
        roriAudioCtx.resume();
    }
}

function roriPlayAlert(priority) {
    if (!roriSoundEnabled || !roriAudioCtx) return;
    const osc = roriAudioCtx.createOscillator();
    const gain = roriAudioCtx.createGain();
    osc.connect(gain);
    gain.connect(roriAudioCtx.destination);
    
    if (priority === 'URGENT') {
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime);
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime + 0.15);
        osc.frequency.setValueAtTime(880, roriAudioCtx.currentTime + 0.3);
    } else {
        osc.frequency.setValueAtTime(660, roriAudioCtx.currentTime);
    }
    
    gain.gain.setValueAtTime(0.1, roriAudioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, roriAudioCtx.currentTime + 0.5);
    
    osc.start(roriAudioCtx.currentTime);
    osc.stop(roriAudioCtx.currentTime + 0.5);
}

window.roriToggleSound = function(enable) {
    roriSoundEnabled = enable;
    localStorage.setItem('rori_sound_enabled', roriSoundEnabled);
    if (enable) roriInitAudio();
};

window.roriTestSound = function() {
    roriInitAudio();
    roriSoundEnabled = true;
    roriPlayAlert('HIGH');
};

// Poll for notifications
function pollNotifications() {
    fetch('/api/notifications/unread', {credentials: 'same-origin', cache: 'no-store'})
    .then(r => r.ok ? r.json() : null)
    .then(d => {
        if (!d) return;
        if (d.latest_title && d.latest_title.includes('NEW MAINTENANCE REQUEST')) {
            let priority = 'MEDIUM';
            if (d.latest_title.includes('URGENT')) priority = 'URGENT';
            else if (d.latest_title.includes('HIGH')) priority = 'HIGH';
            
            if (!roriAlertedRequests.includes(d.latest_id)) {
                roriInitAudio();
                roriPlayAlert(priority);
                roriAlertedRequests.push(d.latest_id);
                sessionStorage.setItem('rori_alerted_requests', JSON.stringify(roriAlertedRequests));
                
                const badge = document.querySelector('.notif-badge');
                if (badge) {
                    badge.classList.add('pulse');
                    setTimeout(() => badge.classList.remove('pulse'), 2000);
                }
            }
        }
    })
    .catch(() => {});
}

pollNotifications();
setInterval(pollNotifications, 10000);
</script>
</body>
</html>"""

# ══════════════════════════════════════════ MANAGEMENT REPORTS
@app.route("/management/reports")
@role_required("ADMIN", "MANAGER")
def management_reports():
    period = request.args.get("period", "daily")
    dept_filter = request.args.get("department", "")
    
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_filter:
        dept = Department.query.filter_by(name=dept_filter).first()
        if dept: q = q.filter_by(department_id=dept.id)
    
    now = datetime.utcnow()
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "weekly":
        start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    
    reqs = q.all()
    total = len(reqs)
    completed = sum(1 for r in reqs if r.status in ["Completed","Verified","Closed"])
    pending = sum(1 for r in reqs if r.status in ["Pending","Approved"])
    
    work_orders = WorkOrder.query.filter(WorkOrder.request_id.in_([r.id for r in reqs])).all()
    total_hours = sum(wo.labor_hours or 0 for wo in work_orders)
    
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-chart-line"></i> <span>Management</span> Reports</h1>'
         '<p>Detailed analytics and performance metrics</p></div>'
         '<div style="display:flex;gap:1rem;"><a href="/management/reports/export?period=' + period + '" class="btn-primary"><i class="fas fa-file-excel"></i> Export</a>'
         '<button onclick="window.print()" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-print"></i> Print</button></div></div>'
         
         '<div class="card" style="margin-bottom:2rem;"><form method="get" class="row g-3 align-items-end">'
         '<div class="col-md-4"><label class="form-label">Period</label><select name="period" class="form-select"><option value="daily" ' + ('selected' if period=="daily" else '') + '>Daily</option><option value="weekly" ' + ('selected' if period=="weekly" else '') + '>Weekly</option><option value="monthly" ' + ('selected' if period=="monthly" else '') + '>Monthly</option></select></div>'
         '<div class="col-md-4"><label class="form-label">Department</label><select name="department" class="form-select"><option value="">All Departments</option>' + "".join('<option value="' + d.name + '"' + (' selected' if dept_filter==d.name else '') + '>' + d.name + '</option>' for d in Department.query.all()) + '</select></div>'
         '<div class="col-md-4"><button type="submit" class="btn-primary w-100"><i class="fas fa-filter"></i> Apply</button></div></form></div>'
         
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total Requests</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Completed</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div>'
         '<div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(total_hours) + ' hrs</div><div class="kpi-label">Work Hours</div></div></div>')
    
    return page("Management Reports", c)

@app.route("/management/reports/export")
@role_required("ADMIN", "MANAGER")
def export_report():
    period = request.args.get("period", "daily")
    dept_filter = request.args.get("department", "")
    
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_filter:
        dept = Department.query.filter_by(name=dept_filter).first()
        if dept: q = q.filter_by(department_id=dept.id)
    
    now = datetime.utcnow()
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "weekly":
        start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(MaintenanceRequest.created_at >= start_date)
    
    reqs = q.all()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["Rori Hotel Maintenance Report"])
    cw.writerow(["Period", period, "Generated", now.strftime("%Y-%m-%d %H:%M")])
    cw.writerow([])
    cw.writerow(["Request No", "Department", "Location", "Priority", "Status", "Completed Date", "Work Hours"])
    
    for r in reqs:
        wo = WorkOrder.query.filter_by(request_id=r.id).first()
        cw.writerow([r.request_no, r.department.name if r.department else "N/A", r.location_name, r.priority, r.status, 
                    r.completed_date.strftime("%Y-%m-%d") if r.completed_date else "N/A", wo.labor_hours if wo else 0])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=maintenance_report.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# ══════════════════════════════════════════ REMAINING ROUTES (UNCHANGED)
@app.route("/requests")
@login_required
def requests_list():
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if current_user.role in ["MANAGER","ADMIN"]: pass
    elif current_user.role == "DEPARTMENT":
        if current_user.department_id: q = q.filter(db.or_(MaintenanceRequest.department_id == current_user.department_id, MaintenanceRequest.requested_by_id == current_user.id))
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
            del_html = ('<form method="post" action="' + url_for("request_delete", req_id=r.id) + '" style="display:inline" onsubmit="return confirm(\'Archive?\');">'
                        '<input type="hidden" name="reason" value="Archived"><button type="submit" class="btn-icon" style="width:32px;height:32px;"><i class="fas fa-archive"></i></button></form>')
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);font-weight:600;">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.department.name if r.department else "—") + '</td><td><span class="badge badge-secondary">' + str(r.priority) + '</span></td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>' + ('<td>' + del_html + '</td>' if is_mgr else '') + '</tr>')
    header = '<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Created</th>' + ('<th></th>' if is_mgr else '') + '</tr></thead>'
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-clipboard-list"></i> <span>Maintenance</span> Requests</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New Request</a></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table">' + header + '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="' + ('8' if is_mgr else '7') + '" style="text-align:center;color:var(--text-secondary);">No requests found</td></tr>') + '</tbody></table></div></div>')
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
            did = current_user.department_id if current_user.department_id else None
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
            if sig_profile and sig_name_from_form:
                if sig_name_from_form != sig_profile.authorized_name:
                    flash("Signature name mismatch.", "danger")
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
            notify_users([u.id for u in managers], req.id, f"🔔 NEW MAINTENANCE REQUEST: {req.request_no}",
                         f"Department: {user_dept_name or 'N/A'} | Priority: {prio} | Location: {req.location_name}",
                         "New Request", link=url_for("request_detail", req_id=req.id))
            create_notification(current_user.id, req.id, "Request Submitted", f"Your request {req.request_no} has been submitted successfully.", "Success", link=url_for("request_detail", req_id=req.id))
            db.session.commit()
            flash("✅ Request created successfully!","success")
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
    sig_warning = "" if sig_profile else '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> No authorized signature configured for your department.</div>'
    sig_configured_class = "border-success" if sig_profile else "border-danger"
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-plus-circle"></i> <span>New</span> Maintenance Request</h1></div></div>' + sig_warning +
         '<div class="card"><form method="post" id="requestForm"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Location Type *</label><select class="form-select" name="location_type" id="locationType" required><option value="Room" selected>Room</option><option value="Area">Area</option></select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Department (Auto-detected)</label><input type="text" class="form-control" value="' + str(sig_dept_display) + '" readonly style="background:rgba(34,197,94,0.1);border-color:var(--success);color:var(--success);font-weight:600"><input type="hidden" name="department_id" value="' + str(user_dept_id or "") + '"></div>'
         '<div class="col-md-6 mb-3" id="roomWrap"><label class="form-label">Room</label><select class="form-select" name="room_id"><option value="">-- Select Room --</option>' + ro + '</select></div>'
         '<div class="col-md-6 mb-3" id="floorWrap" style="display:none"><label class="form-label">Floor</label><select class="form-select" name="floor"><option value="">-- Floor --</option>' + fo + '</select></div>'
         '<div class="col-md-6 mb-3" id="areaWrap" style="display:none"><label class="form-label">Area</label><select class="form-select" name="area_id"><option value="">-- Select Area --</option>' + ao + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Working Item</label><select class="form-select" name="working_item_id"><option value="">-- Select Item --</option>' + io_ + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Category</label><select class="form-select" name="category_id"><option value="">-- Select Category --</option>' + co + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Priority *</label><select class="form-select" name="priority">' + po + '</select></div>'
         '<div class="col-12 mb-3"><label class="form-label">Description *</label><textarea class="form-control" name="description" rows="4" required placeholder="Describe the issue…"></textarea></div>'
         '<div class="col-12 mb-3"><div class="card ' + sig_configured_class + '" style="background:rgba(34,197,94,0.05);border-width:2px">'
         '<h5 style="color:var(--success);margin-bottom:1rem"><i class="fas fa-signature"></i> Authorized Digital Signature</h5>'
         '<div class="row g-3">'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Signed By (Authorized)</div><div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_authorized_name) + '</div><input type="hidden" name="signature_name" value="' + str(sig_authorized_name) + '"></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Department</div><div style="font-size:1.1rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_dept_display) + '</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:rgba(34,197,94,0.1);border-radius:10px;border:1px solid var(--success)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Signature Status</div><div id="sigStatusText" style="font-size:1rem;font-weight:700;color:var(--rori-gold);margin-top:.25rem"><i class="fas fa-hourglass-half"></i> Awaiting Signature</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Requester</div><div style="font-size:1rem;font-weight:600;color:var(--text-primary);margin-top:.25rem">' + str(current_user.full_name or current_user.username) + ' (@' + str(current_user.username) + ')</div></div></div>'
         '</div><hr style="border-color:var(--success);margin:1rem 0">'
         '<label class="form-label" style="color:var(--success);font-weight:600"><i class="fas fa-pen-nib"></i> Draw Your Signature Below *</label>'
         '<div style="border: 2px dashed rgba(197,160,89,0.4); border-radius: 12px; padding: 10px; background: #fff;">'
         '<canvas id="signature-pad" width="400" height="150" style="width: 100%; height: 150px; cursor: crosshair; touch-action: none;"></canvas>'
         '</div>'
         '<div class="mt-2 d-flex gap-2"><button type="button" class="btn-icon" id="clear-signature"><i class="fas fa-eraser"></i> Clear</button><span id="sigHint" style="color:var(--text-secondary);font-size:.85rem;margin-left:.5rem">Please draw your signature above</span></div>'
         '<input type="hidden" name="signature_data" id="signature-data">'
         '</div></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("index") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn-primary" id="submitBtn" disabled><i class="fas fa-paper-plane"></i> Submit Request</button></div></div></form></div>'
         '<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>'
         '<script>(function(){var canvas = document.getElementById("signature-pad");var signaturePad = new SignaturePad(canvas, { backgroundColor: "rgb(255, 255, 255)", penColor: "rgb(0, 0, 0)" });var submitBtn = document.getElementById("submitBtn");var sigStatusText = document.getElementById("sigStatusText");var sigHint = document.getElementById("sigHint");function resizeCanvas(){var ratio = Math.max(window.devicePixelRatio || 1, 1);canvas.width = canvas.offsetWidth * ratio;canvas.height = canvas.offsetHeight * ratio;canvas.getContext("2d").scale(ratio, ratio);signaturePad.clear();}window.addEventListener("resize", resizeCanvas);resizeCanvas();document.getElementById("clear-signature").addEventListener("click", function(){ signaturePad.clear(); updateSigStatus(); });signaturePad.addEventListener("endStroke", updateSigStatus);function updateSigStatus(){if (signaturePad.isEmpty()){sigStatusText.innerHTML = \'<i class="fas fa-hourglass-half"></i> Awaiting Signature\';sigStatusText.style.color = "var(--rori-gold)";sigHint.textContent = "Please draw your signature above";submitBtn.disabled = true;} else {sigStatusText.innerHTML = \'<i class="fas fa-check-circle"></i> Signature Verified\';sigStatusText.style.color = "var(--success)";sigHint.textContent = "✓ Signature captured - ready to submit";submitBtn.disabled = false;}}document.querySelector("#requestForm").addEventListener("submit", function(e){if (signaturePad.isEmpty()){e.preventDefault();alert("⚠️ Digital signature is required.");return false;}document.getElementById("signature-data").value = signaturePad.toDataURL("image/png");});})();</script>'
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
        hist_html += ('<div style="padding:.75rem 1rem;border-left:3px solid var(--rori-gold);background:var(--bg-card);border-radius:10px;margin-bottom:.5rem;border:1px solid var(--border-color);border-left-width:3px;">'
                      '<strong style="color:var(--rori-gold)">' + str(h.status) + '</strong> '
                      '<span style="color:var(--text-secondary);font-size:.85rem">by ' + str(who) + ' · ' + str(when) + note + '</span></div>')
    if not hist_html: hist_html = '<p style="color:var(--text-secondary)">No status history yet.</p>'
    wo_html = ""
    for wo in wos:
        wo_html += ('<div style="padding:.75rem 1rem;background:var(--bg-card);border-radius:10px;margin-bottom:.5rem;border:1px solid var(--border-color);">'
                    '<a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:var(--rori-gold);font-weight:600;">' + str(wo.work_order_no) + '</a> '
                    '<span class="badge badge-info">' + str(wo.status) + '</span> '
                    '<span style="color:var(--text-secondary);font-size:.85rem;">· ' + str(wo.assigned_to.full_name if wo.assigned_to else "Unassigned") + '</span></div>')
    if not wo_html: wo_html = '<p style="color:var(--text-secondary)">No work orders yet.</p>'
    sig_html = ""
    if req.signature_status == "SIGNED":
        sig_time = req.signature_signed_at.strftime("%d %b %Y, %I:%M %p") if req.signature_signed_at else "N/A"
        sig_image_html = '<div style="margin-top:10px; background:#fff; padding:10px; border-radius:8px; display:inline-block; border:1px solid var(--border-color);"><img src="' + str(req.signature_data) + '" style="max-width:250px; max-height:100px;" alt="Signature"></div>' if req.signature_data else '<div style="margin-top:10px; color:var(--text-secondary);">(No signature image stored)</div>'
        verified_badge = '<span class="badge badge-success" style="margin-left:.5rem"><i class="fas fa-check-circle"></i> Verified</span>' if req.signature_verified else '<span class="badge badge-warning" style="margin-left:.5rem"><i class="fas fa-exclamation"></i> Unverified</span>'
        sig_html = ('<div class="card" style="border: 1px solid rgba(34, 197, 94, 0.3); background: rgba(34, 197, 94, 0.05); margin-top:1rem;">'
                    '<h6 style="color:var(--success); margin-bottom:1rem;"><i class="fas fa-signature"></i> DIGITAL SIGNATURE ' + verified_badge + '</h6>'
                    '<div class="row g-3">'
                    '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:8px;border:1px solid var(--border-color)"><div style="font-size:.7rem;color:var(--text-secondary);text-transform:uppercase">Signed By</div><div style="font-size:1rem;font-weight:700;color:var(--text-primary)">' + str(req.signature_name or "Unknown") + '</div></div></div>'
                    '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:8px;border:1px solid var(--border-color)"><div style="font-size:.7rem;color:var(--text-secondary);text-transform:uppercase">Department</div><div style="font-size:1rem;font-weight:700;color:var(--text-primary)">' + str(req.signature_department or req.department.name if req.department else "N/A") + '</div></div></div>'
                    '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:8px;border:1px solid var(--border-color)"><div style="font-size:.7rem;color:var(--text-secondary);text-transform:uppercase">Signed At</div><div style="font-size:.95rem;font-weight:600;color:var(--text-primary)">' + sig_time + '</div></div></div>'
                    '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:8px;border:1px solid var(--border-color)"><div style="font-size:.7rem;color:var(--text-secondary);text-transform:uppercase">Verification Status</div><div style="font-size:.95rem;font-weight:600;color:' + ('var(--success)' if req.signature_verified else 'var(--warning)') + '">' + ('✓ Verified' if req.signature_verified else ' Unverified') + '</div></div></div>'
                    '</div>' + sig_image_html + '</div>')
    actions = []
    if current_user.role in ["ADMIN","MANAGER"]:
        if req.status in ["Pending","Approved","Assigned"] and req.assigned_to_id is None:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn-primary"><i class="fas fa-user-plus"></i> Assign Staff</a>')
        elif req.status in ["Approved","Assigned"]:
            actions.append('<a href="' + url_for("workorder_create", request_id=req.id) + '" class="btn-primary"><i class="fas fa-user-edit"></i> Reassign</a>')
        if req.status == "Pending":
            actions.append('<form method="post" action="' + url_for("request_approve", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--success);"><i class="fas fa-check"></i> Approve</button></form>')
        if req.status == "Completed":
            actions.append('<form method="post" action="' + url_for("request_verify", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--info);"><i class="fas fa-check-double"></i> Verify</button></form>')
        if req.status == "Verified":
            actions.append('<form method="post" action="' + url_for("request_close", req_id=req.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-lock"></i> Close</button></form>')
        if not req.is_deleted:
            actions.append('<form method="post" action="' + url_for("request_delete", req_id=req.id) + '" style="display:inline" onsubmit="return confirm(\'Archive?\')"><input type="hidden" name="reason" value="Archived"><button type="submit" class="btn-primary" style="background:var(--danger);"><i class="fas fa-archive"></i> Archive</button></form>')
    actions_html = " ".join(actions) if actions else ""
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-clipboard-list"></i> <span>Request</span> ' + str(req.request_no) + '</h1></div><div>' + actions_html + '</div></div>'
         '<div class="row"><div class="col-md-8"><div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;">Request Details</h5>'
         '<table class="table"><tbody>'
         '<tr><th style="width:180px;color:var(--text-secondary);">Status</th><td><span class="badge badge-' + bd(req.status) + '">' + str(req.status) + '</span></td></tr>'
         '<tr><th style="color:var(--text-secondary);">Priority</th><td>' + str(req.priority) + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Department</th><td>' + str(req.department.name if req.department else "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Location</th><td>' + str(req.location_name) + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Item</th><td>' + str(req.working_item.name if req.working_item else "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Category</th><td>' + str(req.category.name if req.category else "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Requested By</th><td><strong>' + str(req.requested_by.full_name if req.requested_by else "—") + '</strong></td></tr>'
         '<tr><th style="color:var(--text-secondary);">Assigned To</th><td>' + str(req.assigned_to.full_name if req.assigned_to else "Not Assigned") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Description</th><td>' + str(req.description or "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Due Date</th><td>' + (req.due_date.strftime("%Y-%m-%d %H:%M") if req.due_date else "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Completed</th><td>' + (req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Completion Note</th><td>' + str(req.completion_note or "—") + '</td></tr>'
         '<tr><th style="color:var(--text-secondary);">Created</th><td>' + (req.created_at.strftime("%Y-%m-%d %H:%M") if req.created_at else "—") + '</td></tr>'
         '</tbody></table>' + sig_html + '</div>'
         '<div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-clipboard-list"></i> Work Orders</h5>' + wo_html + '</div>'
         '</div><div class="col-md-4"><div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-history"></i> Status History</h5>' + hist_html + '</div></div></div>')
    return page("Request " + str(req.request_no), c)

# ══════════════════════════════════════════ REMAINING ROUTES (UNCHANGED)
@app.route("/requests/<int:req_id>/approve", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_approve(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Pending": flash("Not pending","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Approved"; req.manager_id = current_user.id
        log_status_change(req.id,"Approved",notes="Approved by " + str(current_user.full_name))
        log_audit("Approve","MaintenanceRequest",req.id,"Pending","Approved")
        notify_users([req.requested_by_id], req.id, "Request Approved", "Your request " + str(req.request_no) + " has been approved", "Approved", link=url_for("request_detail", req_id=req.id))
        db.session.commit(); flash("✅ Request approved!","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/verify", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_verify(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Completed": flash("Only completed can be verified","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Verified"; req.manager_id = current_user.id
        if not req.completed_date: req.completed_date = datetime.utcnow()
        wo = WorkOrder.query.filter_by(request_id=req.id).first()
        if wo: wo.status = "Verified"; wo.verified_by_id = current_user.id; wo.verified_date = datetime.utcnow()
        log_status_change(req.id,"Verified",notes="Verified by " + str(current_user.full_name))
        log_audit("Verify","MaintenanceRequest",req.id,"Completed","Verified")
        notify_users([req.requested_by_id], req.id, "✅ Work Verified", "Request " + str(req.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=req.id))
        db.session.commit(); flash("✅ Work verified!","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/close", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_close(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.status != "Verified": flash("Only verified can be closed","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.status = "Closed"
        log_status_change(req.id,"Closed",notes="Closed by " + str(current_user.full_name))
        log_audit("Close","MaintenanceRequest",req.id,"Verified","Closed")
        notify_users([req.requested_by_id], req.id, "Request Closed", "Request " + str(req.request_no) + " closed", "Closed")
        db.session.commit(); flash("Request closed","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("request_detail", req_id=req_id))

@app.route("/requests/<int:req_id>/delete", methods=["POST"])
@role_required("MANAGER","ADMIN")
def request_delete(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        if req.is_deleted: flash("Already archived","warning"); return redirect(url_for("request_detail", req_id=req_id))
        req.is_deleted = True; req.deleted_at = datetime.utcnow(); req.deleted_by_id = current_user.id
        req.deletion_reason = request.form.get("reason","Archived by manager")
        log_audit("Archive","MaintenanceRequest",req.id,"active","archived",new_value=req.deletion_reason)
        db.session.commit(); flash("✅ Request archived successfully","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("requests_list"))

@app.route("/admin/deleted")
@role_required("ADMIN")
def deleted_requests():
    ds = MaintenanceRequest.query.filter_by(is_deleted=True).order_by(MaintenanceRequest.deleted_at.desc()).all()
    rows = []
    for r in ds:
        rows.append('<tr><td>' + str(r.request_no) + '</td><td>' + str(r.location_name) + '</td><td>' + str(r.status) + '</td><td>' + (r.deleted_at.strftime("%Y-%m-%d %H:%M") if r.deleted_at else "") + '</td><td>' + str(r.deleted_by.full_name if r.deleted_by else "—") + '</td><td>' + str(r.deletion_reason or "—") + '</td><td><form method="post" action="' + url_for("request_restore", req_id=r.id) + '"><button type="submit" class="btn-primary" style="background:var(--success);padding:0.4rem 0.8rem;font-size:0.8rem;"><i class="fas fa-undo"></i> Restore</button></form></td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-archive"></i> <span>Archived</span> Requests</h1></div></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Status</th><th>Archived At</th><th>Archived By</th><th>Reason</th><th></th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);">No archived requests</td></tr>') + '</tbody></table></div></div>')
    return page("Archived", c)

@app.route("/admin/restore/<int:req_id>", methods=["POST"])
@role_required("ADMIN")
def request_restore(req_id):
    try:
        req = get_or_404(MaintenanceRequest, req_id)
        req.is_deleted = False; req.deleted_at = None; req.deleted_by_id = None; req.deletion_reason = None
        log_audit("Restore","MaintenanceRequest",req.id,"archived","active")
        db.session.commit(); flash("✅ Request restored","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("deleted_requests"))

# ══════════════════════════════════════════ ANALYTICS HELPERS
COMPLETED_STATES = ["Completed","Verified","Closed"]
PENDING_STATES = ["Pending","Approved"]
INPROGRESS_STATES = ["Assigned","In Progress"]

def _parse_date(v):
    if not v: return None
    try: return datetime.strptime(v,"%Y-%m-%d")
    except (ValueError, TypeError): return None

def build_filtered_query(args):
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    d_from = _parse_date(args.get("date_from"))
    if d_from: q = q.filter(MaintenanceRequest.created_at >= d_from)
    d_to = _parse_date(args.get("date_to"))
    if d_to: q = q.filter(MaintenanceRequest.created_at < d_to + timedelta(days=1))
    if args.get("department"):
        try: q = q.filter(MaintenanceRequest.department_id == int(args["department"]))
        except (ValueError, TypeError): pass
    if args.get("category"):
        try: q = q.filter(MaintenanceRequest.category_id == int(args["category"]))
        except (ValueError, TypeError): pass
    if args.get("status"): q = q.filter(MaintenanceRequest.status == args["status"])
    if args.get("floor"):
        try: q = q.filter(MaintenanceRequest.floor == int(args["floor"]))
        except (ValueError, TypeError): pass
    if args.get("room_id"):
        try: q = q.filter(MaintenanceRequest.room_id == int(args["room_id"]))
        except (ValueError, TypeError): pass
    if args.get("area_id"):
        try: q = q.filter(MaintenanceRequest.area_id == int(args["area_id"]))
        except (ValueError, TypeError): pass
    return q

def format_duration(s):
    if s is None: return "N/A"
    if s < 60: return f"{int(s)}s"
    if s < 3600: return f"{int(s/60)}m"
    if s < 86400: return f"{s/3600:.1f} hrs"
    d = int(s // 86400); h = int((s % 86400) // 3600)
    return f"{d}d {h}h" if h else f"{d}d"

def _avg_sec(reqs):
    comp = [r for r in reqs if r.completed_date and r.created_at]
    if not comp: return None
    return sum((r.completed_date - r.created_at).total_seconds() for r in comp) / len(comp)

def get_kpis(args):
    reqs = build_filtered_query(args).all()
    total = len(reqs)
    pending = sum(1 for r in reqs if r.status in PENDING_STATES)
    completed = sum(1 for r in reqs if r.status in COMPLETED_STATES)
    avg = _avg_sec([r for r in reqs if r.status in COMPLETED_STATES])
    rate = (completed / total * 100) if total else 0.0
    return {"total": total, "pending": pending, "completed": completed, "completion_rate": round(rate,1), "avg_resolution": format_duration(avg)}

def get_trends(args):
    reqs = build_filtered_query(args).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))
    if d_from and d_to: start, end = d_from, d_to
    else:
        dates = [r.created_at for r in reqs if r.created_at]
        if not dates: return {"labels":[],"total":[],"completed":[],"pending":[],"in_progress":[]}
        start = min(dates).replace(hour=0,minute=0,second=0,microsecond=0)
        end = max(dates).replace(hour=0,minute=0,second=0,microsecond=0)
    span = (end-start).days + 1
    gran = "day" if span <= 31 else "week" if span <= 180 else "month"
    keys, labels = [], []
    if gran == "day":
        cur = start
        while cur <= end: keys.append(cur.strftime("%Y-%m-%d")); labels.append(cur.strftime("%b %d")); cur += timedelta(days=1)
    elif gran == "week":
        cur = start - timedelta(days=start.weekday())
        while cur <= end: keys.append(cur.strftime("%Y-%m-%d")); labels.append("Wk " + cur.strftime("%b %d")); cur += timedelta(days=7)
    else:
        cur = start.replace(day=1)
        while cur <= end: keys.append(cur.strftime("%Y-%m")); labels.append(cur.strftime("%b %Y")); cur = cur.replace(year=cur.year+1,month=1) if cur.month == 12 else cur.replace(month=cur.month+1)
    counts = {k:{"total":0,"completed":0,"pending":0,"in_progress":0} for k in keys}
    for r in reqs:
        if not r.created_at: continue
        if gran == "day": k = r.created_at.strftime("%Y-%m-%d")
        elif gran == "week": m = r.created_at - timedelta(days=r.created_at.weekday()); k = m.strftime("%Y-%m-%d")
        else: k = r.created_at.strftime("%Y-%m")
        if k in counts:
            counts[k]["total"] += 1
            if r.status in COMPLETED_STATES: counts[k]["completed"] += 1
            elif r.status in PENDING_STATES: counts[k]["pending"] += 1
            elif r.status in INPROGRESS_STATES: counts[k]["in_progress"] += 1
    return {"labels": labels, "total": [counts[k]["total"] for k in keys], "completed": [counts[k]["completed"] for k in keys], "pending": [counts[k]["pending"] for k in keys], "in_progress": [counts[k]["in_progress"] for k in keys], "granularity": gran}

def get_status_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.status] += 1
    order = ["Pending","Approved","Assigned","In Progress","Completed","Verified","Closed","Rejected","Overdue"]
    total = sum(counts.values())
    items = [(s, counts[s]) for s in order if counts.get(s,0) > 0]
    for s, c in counts.items():
        if s not in order and c > 0: items.append((s, c))
    return {"labels": [k for k,_ in items], "values": [v for _,v in items], "percentages": [round(v/total*100,1) if total else 0 for _,v in items], "total": total}

def get_dept_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.department.name if r.department else "Unspecified"] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    total = sum(counts.values())
    return {"labels": [k for k,_ in items], "values": [v for _,v in items], "percentages": [round(v/total*100,1) if total else 0 for _,v in items], "total": total}

def get_dept_completion(args):
    reqs = build_filtered_query(args).all()
    depts = {}
    for r in reqs:
        name = r.department.name if r.department else "Unspecified"
        if name not in depts: depts[name] = {"total": 0, "completed": 0}
        depts[name]["total"] += 1
        if r.status in COMPLETED_STATES: depts[name]["completed"] += 1
    items = sorted(depts.items(), key=lambda x: -x[1]["total"])
    return {"labels": [k for k,_ in items], "totals": [v["total"] for _,v in items], "completed": [v["completed"] for _,v in items], "percentages": [round(v["completed"]/v["total"]*100,1) if v["total"] else 0 for _,v in items]}

def get_priority_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.priority or "MEDIUM"] += 1
    order = ["URGENT","HIGH","MEDIUM","LOW"]
    total = sum(counts.values())
    items = [(p, counts[p]) for p in order if counts.get(p,0) > 0]
    return {"labels": [k for k,_ in items], "values": [v for _,v in items], "percentages": [round(v/total*100,1) if total else 0 for _,v in items]}

def get_category_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs: counts[r.category.name if r.category else "Uncategorized"] += 1
    items = sorted(counts.items(), key=lambda x: -x[1])
    total = sum(counts.values())
    return {"labels": [k for k,_ in items], "values": [v for _,v in items], "percentages": [round(v/total*100,1) if total else 0 for _,v in items]}

def get_floor_stats(args):
    reqs = build_filtered_query(args).all()
    counts = defaultdict(int)
    for r in reqs:
        if r.floor: counts[r.floor] += 1
    items = sorted(counts.items())
    return {"labels": ["Floor " + str(k) for k,_ in items], "values": [v for _,v in items]}

def get_technician_workload(args):
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    d_from = _parse_date(args.get("date_from"))
    d_to = _parse_date(args.get("date_to"))
    result = []
    for s in staff:
        q = WorkOrder.query.filter_by(assigned_to_id=s.id)
        if d_from: q = q.filter(WorkOrder.created_at >= d_from)
        if d_to: q = q.filter(WorkOrder.created_at < d_to + timedelta(days=1))
        wos = q.all()
        comp = [w for w in wos if w.status in COMPLETED_STATES and w.completed_date and w.created_at]
        avg = None
        if comp: avg = sum((w.completed_date - w.created_at).total_seconds() for w in comp) / len(comp)
        result.append({"name": s.full_name or s.username, "role": s.role, "assigned": len(wos), "in_progress": sum(1 for w in wos if w.status == "In Progress"), "completed": sum(1 for w in wos if w.status in COMPLETED_STATES), "avg_resolution": format_duration(avg)})
    result.sort(key=lambda x: -x["assigned"])
    return result[:15]

def get_recent_activity(limit=10):
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [{"user": l.user.full_name if l.user else "System", "action": l.action or "", "object_type": l.object_type or "", "object_id": l.object_id or "", "time": l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""} for l in logs]

def get_inventory_summary():
    parts = InventoryPart.query.filter_by(status="Active").all()
    total = len(parts)
    low = sum(1 for p in parts if 0 < (p.quantity or 0) <= (p.minimum_stock or 0))
    out = sum(1 for p in parts if (p.quantity or 0) <= 0)
    val = sum((p.quantity or 0) * (p.unit_cost or 0) for p in parts)
    return {"total_parts": total, "low_stock": low, "out_of_stock": out, "total_value": round(val,2)}

# ══════════════════════════════════════════ DEPARTMENT DASHBOARD
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    dept_id = current_user.department_id
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_id: q = q.filter(db.or_(MaintenanceRequest.department_id == dept_id, MaintenanceRequest.requested_by_id == current_user.id))
    else: q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    total = len(reqs)
    pending = sum(1 for r in reqs if r.status == "Pending")
    in_progress = sum(1 for r in reqs if r.status == "In Progress")
    completed = sum(1 for r in reqs if r.status in ["Completed","Verified","Closed"])
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    rows = []
    for r in reqs[:30]:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.priority) + '</td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d") if r.created_at else "—") + '</td></tr>')
    dept_name = current_user.department.name if current_user.department else "My Department"
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-building"></i> <span>' + str(dept_name) + '</span> Dashboard</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New Request</a></div>'
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--info);"><i class="fas fa-spinner"></i></div><div class="kpi-value">' + str(in_progress) + '</div><div class="kpi-label">In Progress</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Done</div></div></div>'
         '<div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-tasks"></i> My Requests</h5><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);">No requests yet.</td></tr>') + '</tbody></table></div></div>')
    return page("Department Dashboard", c)

@app.route("/employee/dashboard")
@login_required
@role_required("EMPLOYEE")
def employee_dashboard():
    reqs = MaintenanceRequest.query.filter_by(is_deleted=False, requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    rows = []
    for r in reqs[:30]:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.priority) + '</td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d") if r.created_at else "—") + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-home"></i> <span>My</span> Dashboard</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New Request</a></div>'
         '<div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-tasks"></i> My Requests</h5><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);">No requests yet</td></tr>') + '</tbody></table></div></div>')
    return page("Employee Dashboard", c)

@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    if current_user.role in STAFF_ROLES: wos = WorkOrder.query.filter(db.or_(WorkOrder.assigned_to_id == current_user.id, WorkOrder.assigned_to_id.is_(None))).order_by(WorkOrder.created_at.desc()).all()
    else: wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    rows = []
    for wo in wos:
        assigned = wo.assigned_to.full_name if wo.assigned_to else "🔴 Unassigned"
        badge = "success" if wo.status in ["Completed","Verified"] else "warning" if wo.status in ["Pending","Assigned"] else "info"
        rows.append('<tr><td><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:var(--rori-gold);">' + str(wo.work_order_no) + '</a></td><td>' + str(wo.request.location_name if wo.request else "—") + '</td><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td><td>' + str(wo.request.department.name if wo.request and wo.request.department else "—") + '</td><td>' + str(wo.request.priority if wo.request else "—") + '</td><td><span class="badge badge-' + badge + '">' + str(wo.status) + '</span></td><td>' + str(assigned) + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-tasks"></i> <span>Work</span> Orders</h1></div></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Order #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Assigned</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);">No work orders</td></tr>') + '</tbody></table></div></div>')
    return page("Work Orders", c)

@app.route("/workorders/new", methods=["GET","POST"])
@role_required("MANAGER","ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = get_one(MaintenanceRequest, req_id) if req_id else None
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    uo = "".join('<option value="' + str(u.id) + '">' + str(u.full_name or u.username) + ' — ' + str(u.role) + '</option>' for u in staff)
    if request.method == "POST":
        try:
            request_id = request.form.get("request_id", type=int)
            assigned_to_id = request.form.get("assigned_to_id", type=int)
            wp = request.form.get("work_performed","")
            if not assigned_to_id: flash("Please select a technician","danger"); return redirect(url_for("workorder_create", request_id=request_id))
            req = get_or_404(MaintenanceRequest, request_id)
            assigned_user = get_one(User, assigned_to_id)
            existing = WorkOrder.query.filter_by(request_id=req.id).filter(WorkOrder.status != "Completed").first()
            if existing: wo = existing; wo.assigned_to_id = assigned_to_id; wo.status = "Assigned"; wo.work_performed = wp if wp else wo.work_performed
            else: wo = WorkOrder(work_order_no=work_order_no_generator(), request_id=req.id, assigned_to_id=assigned_to_id, status="Assigned", work_performed=wp); db.session.add(wo); db.session.flush()
            log_audit("Create","WorkOrder",wo.id,new_value=wo.work_order_no)
            req.status = "Assigned"; req.assigned_to_id = assigned_to_id
            log_status_change(req.id,"Assigned",notes="Assigned to " + str(assigned_user.full_name if assigned_user else "?"))
            if assigned_user: notify_assigned_staff(req, wo, assigned_user)
            if req.requested_by_id: notify_users([req.requested_by_id], req.id, "Work Assigned", "Staff assigned to " + str(req.request_no), "Assigned", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Assigned!","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_create", request_id=request_id))
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-user-plus"></i> <span>Assign</span> Staff</h1></div></div>'
         '<div class="card"><form method="post"><input type="hidden" name="request_id" value="' + str(req.id if req else "") + '">'
         '<div class="mb-3"><label class="form-label">Request</label><input class="form-control" value="' + str(req.request_no if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Department</label><input class="form-control" value="' + str(req.department.name if req and req.department else "—") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Location</label><input class="form-control" value="' + str(req.location_name if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Assign To *</label><select class="form-select" name="assigned_to_id" required><option value="">-- Select Technician --</option>' + uo + '</select></div>'
         '<div class="mb-3"><label class="form-label">Instructions</label><textarea class="form-control" name="work_performed" rows="3"></textarea></div>'
         '<button class="btn-primary"><i class="fas fa-save"></i> Assign</button></form></div>')
    return page("Assign Work Order", c)

@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    can_parts = (current_user.role in ["MANAGER","ADMIN"] or (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))
    pr, pt = [], 0
    for p in parts:
        pname = p.part.part_name if p.part else "Part #" + str(p.part_id)
        psupp = p.part.supplier.company_name if p.part and p.part.supplier else "—"
        pun = p.part.unit if p.part else "pcs"
        lt = (p.quantity or 0) * (p.unit_cost or 0); pt += lt
        rem = '<form method="post" action="' + url_for("workorder_part_remove", wo_id=wo.id, part_id=p.id) + '" style="display:inline" onsubmit="return confirm(\'Remove?\')"><button type="submit" class="btn-icon" style="width:32px;height:32px;background:var(--danger);"><i class="fas fa-times"></i></button></form>' if can_parts and wo.status in ["Assigned","In Progress"] else ""
        pr.append('<tr><td>' + str(pname) + '</td><td>' + str(psupp) + '</td><td>' + str(p.quantity) + '</td><td>' + str(pun) + '</td><td>' + str(p.unit_cost or 0) + '</td><td>' + str(lt) + '</td><td>' + rem + '</td></tr>')
    apb = '<a class="btn-primary" href="' + url_for("workorder_part_add", wo_id=wo.id) + '" style="padding:0.5rem 1rem;font-size:0.85rem;"><i class="fas fa-plus"></i> Add Part</a>' if can_parts and wo.status in ["Assigned","In Progress"] else ""
    parts_card = ('<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-boxes"></i> Parts</div>' + apb + '</div>'
                  '<div style="overflow-x:auto;"><table class="table"><thead><tr><th>Part</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Cost</th><th>Total</th><th></th></tr></thead><tbody>' + ("".join(pr) if pr else '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);">No parts</td></tr>') + '</tbody></table></div><p style="text-align:right;margin-top:1rem;font-weight:700;color:var(--rori-gold);">Total: ' + str(pt) + '</p></div>')
    ch = '<div style="margin-top:1rem;"><h6 style="color:var(--rori-gold);">Completion Photo:</h6><a href="/static/uploads/maintenance/' + str(wo.completion_photo) + '" target="_blank"><img src="/static/uploads/maintenance/' + str(wo.completion_photo) + '" style="max-width:100%;max-height:250px;border-radius:12px;border:1px solid var(--border-color);"></a></div>' if wo.completion_photo else ""
    actions = ""
    if current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id:
        if wo.status == "Assigned": actions += '<form method="post" action="' + url_for("workorder_start", wo_id=wo.id) + '"><button type="submit" class="btn-primary w-100" style="background:var(--warning);margin-bottom:0.75rem;"><i class="fas fa-play"></i> Start Work</button></form>'
        if wo.status == "In Progress": actions += '<a href="' + url_for("workorder_complete", wo_id=wo.id) + '" class="btn-primary w-100" style="background:var(--success);margin-bottom:0.75rem;display:block;text-align:center;"><i class="fas fa-check"></i> Complete Work</a>'
    if (current_user.role == "ADMIN" or current_user.role == "MANAGER") and wo.status == "Completed":
        actions += '<form method="post" action="' + url_for("workorder_verify", wo_id=wo.id) + '"><button type="submit" class="btn-primary w-100" style="background:var(--info);margin-bottom:0.75rem;"><i class="fas fa-check-double"></i> Verify</button></form>'
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-tasks"></i> Work Order <span>' + str(wo.work_order_no) + '</span></h1></div><a href="' + url_for("workorders_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-arrow-left"></i> Back</a></div>'
         '<div class="row"><div class="col-md-8"><div class="card"><table class="table"><tr><th style="width:150px;color:var(--text-secondary);">Request</th><td>' + str(wo.request.request_no if wo.request else "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Department</th><td>' + str(wo.request.department.name if wo.request and wo.request.department else "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Location</th><td>' + str(wo.request.location_name if wo.request else "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Item</th><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Priority</th><td>' + str(wo.request.priority if wo.request else "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Status</th><td><span class="badge badge-info">' + str(wo.status) + '</span></td></tr><tr><th style="color:var(--text-secondary);">Assigned To</th><td>' + str(wo.assigned_to.full_name if wo.assigned_to else "Unassigned") + '</td></tr><tr><th style="color:var(--text-secondary);">Instructions</th><td>' + str(wo.work_performed or "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Completion Notes</th><td>' + str(wo.completion_notes or "—") + '</td></tr><tr><th style="color:var(--text-secondary);">Labor Hours</th><td>' + str(wo.labor_hours) + '</td></tr></table>' + ch + '</div>' + parts_card + '</div><div class="col-md-4"><div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;">Actions</h5>' + (actions if actions else "<p style='color:var(--text-secondary);'>No actions available</p>") + '</div></div></div>')
    return page("Work Order Detail", c)

@app.route("/workorders/<int:wo_id>/start", methods=["POST"])
@login_required
def workorder_start(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if current_user.id != wo.assigned_to_id: flash("Not authorized","danger"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        if wo.status != "Assigned": flash("Cannot start","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "In Progress"
        if wo.request: wo.request.status = "In Progress"
        log_status_change(wo.request_id,"In Progress",notes="Started by " + str(current_user.full_name))
        log_audit("Start","WorkOrder",wo.id,"Assigned","In Progress")
        db.session.commit(); flash("Work started","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))

@app.route("/workorders/<int:wo_id>/complete", methods=["GET","POST"])
@role_required(*STAFF_ROLES)
def workorder_complete(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if current_user.id != wo.assigned_to_id: flash("Not authorized","danger"); return redirect(url_for("workorder_detail", wo_id=wo_id))
    if wo.status != "In Progress": flash("Not in progress","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
    if request.method == "POST":
        try:
            note = request.form.get("completion_note","").strip()
            try: hours = float(request.form.get("labor_hours","0") or "0")
            except: hours = 0.0
            if not note: flash("Completion note required","danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
            fname = None
            f = request.files.get("photo")
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit(".",1)[-1].lower()
                fname = secure_filename("wo_" + str(wo.id) + "_done_" + datetime.now().strftime("%Y%m%d%H%M%S") + "." + ext)
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            wo.completion_notes = note; wo.labor_hours = hours; wo.status = "Completed"
            wo.completed_by_id = current_user.id; wo.completed_date = datetime.utcnow()
            if fname: wo.completion_photo = fname
            if wo.request: wo.request.status = "Completed"; wo.request.completed_date = datetime.utcnow(); wo.request.completion_note = note
            log_status_change(wo.request_id,"Completed",notes="Completed by " + str(current_user.full_name))
            log_audit("Complete","WorkOrder",wo.id,"In Progress","Completed")
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"])).all()
            notify_users([u.id for u in managers], wo.request_id, "🔔 Work Completed", "WO " + str(wo.work_order_no) + " ready for verification", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            if wo.request and wo.request.requested_by_id: notify_users([wo.request.requested_by_id], wo.request_id, "Work Completed", "Request " + str(wo.request.request_no) + " completed", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Completed! Waiting for verification.","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-check-circle"></i> <span>Complete</span> Work Order ' + str(wo.work_order_no) + '</h1></div></div>'
         '<div class="card"><form method="post" enctype="multipart/form-data">'
         '<div class="mb-3"><label class="form-label">Completion Note *</label><textarea name="completion_note" class="form-control" rows="4" required></textarea></div>'
         '<div class="mb-3"><label class="form-label">Photo</label><input type="file" name="photo" accept="image/*" class="form-control"></div>'
         '<div class="mb-3"><label class="form-label">Labor Hours</label><input type="number" step="0.5" name="labor_hours" class="form-control" value="0"></div>'
         '<button class="btn-primary w-100" style="background:var(--success);"><i class="fas fa-check-circle"></i> Complete</button></form></div>')
    return page("Complete Work Order", c)

@app.route("/workorders/<int:wo_id>/verify", methods=["POST"])
@role_required("MANAGER","ADMIN")
def workorder_verify(wo_id):
    try:
        wo = get_or_404(WorkOrder, wo_id)
        if wo.status != "Completed": flash("Only completed can be verified","warning"); return redirect(url_for("workorder_detail", wo_id=wo_id))
        wo.status = "Verified"; wo.verified_by_id = current_user.id; wo.verified_date = datetime.utcnow()
        if wo.request: wo.request.status = "Verified"; wo.request.manager_id = current_user.id; 
        if not wo.request.completed_date: wo.request.completed_date = datetime.utcnow()
        log_status_change(wo.request_id,"Verified",notes="Verified by " + str(current_user.full_name))
        log_audit("Verify","WorkOrder",wo.id,"Completed","Verified")
        if wo.request: notify_users([wo.request.requested_by_id], wo.request_id, "✅ Verified", "Request " + str(wo.request.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=wo.request_id))
        db.session.commit(); flash("✅ Verified!","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))

def supplier_active(s):
    if s is None: return True
    if s.is_active is not None: return s.is_active
    return s.status == "Active"

def supplier_form(s, action, edit):
    def v(f): return str(getattr(s, f) or "") if s else ""
    act = supplier_active(s)
    a1 = " selected" if act else ""
    a2 = "" if act else " selected"
    return ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-truck"></i> <span>' + ("Edit" if edit else "Add") + '</span> Supplier</h1></div></div>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier Name *</label><input type="text" class="form-control" name="company_name" value="' + v("company_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Contact</label><input type="text" class="form-control" name="contact_person" value="' + v("contact_person") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + v("phone") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + v("email") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Address</label><input type="text" class="form-control" name="address" value="' + v("address") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Tax Number</label><input type="text" class="form-control" name="tax_number" value="' + v("tax_number") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + a1 + '>Active</option><option value="Inactive"' + a2 + '>Inactive</option></select></div>'
            '<div class="col-12 mb-3"><label class="form-label">Notes</label><textarea class="form-control" name="notes" rows="3">' + v("notes") + '</textarea></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("suppliers_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save</button></div></div></form></div>')

@app.route("/suppliers")
@role_required("ADMIN","MANAGER")
def suppliers_list():
    ss = Supplier.query.order_by(Supplier.company_name).all()
    rows = []
    for s in ss:
        act = supplier_active(s)
        bg = '<span class="badge badge-success">Active</span>' if act else '<span class="badge badge-secondary">Inactive</span>'
        ac = '<a class="btn-primary" href="' + url_for("supplier_edit", supplier_id=s.id) + '" style="padding:0.4rem 0.8rem;font-size:0.8rem;"><i class="fas fa-edit"></i> Edit</a> '
        if act: ac += '<form method="post" action="' + url_for("supplier_deactivate", supplier_id=s.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate?\')"><button type="submit" class="btn-primary" style="background:var(--warning);padding:0.4rem 0.8rem;font-size:0.8rem;"><i class="fas fa-ban"></i></button></form>'
        rows.append('<tr><td>' + str(s.id) + '</td><td>' + str(s.company_name) + '</td><td>' + str(s.contact_person or "—") + '</td><td>' + str(s.phone or "—") + '</td><td>' + str(s.email or "—") + '</td><td>' + bg + '</td><td>' + ac + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-truck"></i> <span>Suppliers</span></h1></div><a class="btn-primary" href="' + url_for("supplier_add") + '"><i class="fas fa-plus"></i> Add</a></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Contact</th><th>Phone</th><th>Email</th><th>Status</th><th>Actions</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" style="text-align:center;color:var(--text-secondary);">None</td></tr>') + '</tbody></table></div></div>')
    return page("Suppliers", c)

@app.route("/suppliers/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def supplier_add():
    if request.method == "POST":
        name = request.form.get("company_name","").strip(); email = request.form.get("email","").strip()
        if not name: flash("Name required","danger"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        if email and not valid_email(email): flash("Invalid email","danger"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        if Supplier.query.filter_by(company_name=name).first(): flash("Exists","warning"); return page("Add", supplier_form(None, url_for("supplier_add"), False))
        try:
            st = request.form.get("status","Active")
            s = Supplier(company_name=name, contact_person=request.form.get("contact_person","").strip(), phone=request.form.get("phone","").strip(), email=email, address=request.form.get("address","").strip(), tax_number=request.form.get("tax_number","").strip(), notes=request.form.get("notes","").strip(), status=st, is_active=(st=="Active"))
            db.session.add(s); db.session.flush()
            log_audit("Supplier Created","Supplier",s.id,new_value=name)
            db.session.commit(); flash("✅ Saved","success"); return redirect(url_for("suppliers_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Add Supplier", supplier_form(None, url_for("supplier_add"), False))

@app.route("/suppliers/<int:supplier_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def supplier_edit(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    if request.method == "POST":
        name = request.form.get("company_name","").strip(); email = request.form.get("email","").strip()
        if not name: flash("Name required","danger"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        if email and not valid_email(email): flash("Invalid email","danger"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        dup = Supplier.query.filter(Supplier.company_name == name, Supplier.id != s.id).first()
        if dup: flash("Exists","warning"); return page("Edit", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))
        try:
            st = request.form.get("status","Active")
            s.company_name = name; s.contact_person = request.form.get("contact_person","").strip(); s.phone = request.form.get("phone","").strip(); s.email = email; s.address = request.form.get("address","").strip(); s.tax_number = request.form.get("tax_number","").strip(); s.notes = request.form.get("notes","").strip(); s.status = st; s.is_active = (st=="Active")
            log_audit("Supplier Updated","Supplier",s.id,new_value=name)
            db.session.commit(); flash("✅ Updated","success"); return redirect(url_for("suppliers_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Supplier", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))

@app.route("/suppliers/<int:supplier_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER")
def supplier_deactivate(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    try: s.is_active = False; s.status = "Inactive"; log_audit("Supplier Deactivated","Supplier",s.id,old_value="active",new_value="inactive"); db.session.commit(); flash("Deactivated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("suppliers_list"))

def part_form(p, action):
    def v(f, d=""): return str(getattr(p, f) if p and getattr(p, f) is not None else d)
    sups = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    so = '<option value="">-- Select --</option>'
    for s in sups: so += '<option value="' + str(s.id) + '"' + (' selected' if p and p.supplier_id == s.id else '') + '>' + str(s.company_name) + '</option>'
    return ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-box"></i> <span>' + ("Edit" if p else "Add") + '</span> Part</h1></div></div>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Part Name *</label><input type="text" class="form-control" name="part_name" value="' + v("part_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Category</label><input type="text" class="form-control" name="category" value="' + v("category") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Quantity</label><input type="number" step="0.01" class="form-control" name="quantity" value="' + v("quantity","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Min Stock</label><input type="number" step="0.01" class="form-control" name="minimum_stock" value="' + v("minimum_stock","5") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit</label><input type="text" class="form-control" name="unit" value="' + v("unit","pcs") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" class="form-control" name="unit_cost" value="' + v("unit_cost","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Storage</label><input type="text" class="form-control" name="storage_location" value="' + v("storage_location") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier</label><select class="form-select" name="supplier_id">' + so + '</select></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("inventory_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save</button></div></div></form></div>')

@app.route("/inventory/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def inventory_add():
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_add"))
        if InventoryPart.query.filter_by(part_name=name).first(): flash("Exists","warning"); return redirect(url_for("inventory_add"))
        try:
            p = InventoryPart(part_name=name, category=request.form.get("category","").strip(), quantity=request.form.get("quantity", type=float) or 0, minimum_stock=request.form.get("minimum_stock", type=float) or 5, unit=request.form.get("unit","pcs").strip() or "pcs", unit_cost=request.form.get("unit_cost", type=float) or 0, storage_location=request.form.get("storage_location","").strip(), status="Active", supplier_id=request.form.get("supplier_id", type=int))
            db.session.add(p); db.session.flush()
            log_audit("Inventory Part Created","InventoryPart",p.id,new_value=name)
            db.session.commit(); flash("✅ Saved","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("inventory_add"))
    return page("Add Part", part_form(None, url_for("inventory_add")))

@app.route("/inventory/<int:part_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def inventory_edit(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_edit", part_id=p.id))
        dup = InventoryPart.query.filter(InventoryPart.part_name == name, InventoryPart.id != p.id).first()
        if dup: flash("Exists","warning"); return redirect(url_for("inventory_edit", part_id=p.id))
        try:
            p.part_name = name; p.category = request.form.get("category","").strip(); p.quantity = request.form.get("quantity", type=float) or 0; p.minimum_stock = request.form.get("minimum_stock", type=float) or 5; p.unit = request.form.get("unit","pcs").strip() or "pcs"; p.unit_cost = request.form.get("unit_cost", type=float) or 0; p.storage_location = request.form.get("storage_location","").strip(); p.supplier_id = request.form.get("supplier_id", type=int)
            log_audit("Inventory Part Updated","InventoryPart",p.id,new_value=name)
            db.session.commit(); flash("✅ Updated","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Part", part_form(p, url_for("inventory_edit", part_id=p.id)))

def can_parts(wo): return (current_user.role in ["MANAGER","ADMIN"] or (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))

@app.route("/workorders/<int:wo_id>/parts/add", methods=["GET","POST"])
@login_required
def workorder_part_add(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_parts(wo): abort(403)
    if wo.status not in ["Assigned","In Progress"]: flash("Cannot add parts at this stage","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
    if request.method == "POST":
        try:
            pid = request.form.get("part_id", type=int); qty = request.form.get("quantity", type=float); uc = request.form.get("unit_cost", type=float)
            part = get_one(InventoryPart, pid)
            if not part: flash("Select valid part","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if not qty or qty <= 0: flash("Qty > 0","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if qty > part.quantity: flash("Only " + str(part.quantity) + " available","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if uc is None or uc < 0: uc = part.unit_cost or 0
            wop = WorkOrderPart(work_order_id=wo.id, part_id=part.id, quantity=qty, unit_cost=uc)
            part.quantity = (part.quantity or 0) - qty
            db.session.add(wop)
            log_audit("Part Added","WorkOrder",wo.id,new_value=str(part.part_name) + " x " + str(qty))
            db.session.commit(); flash("✅ Part added","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
    parts = InventoryPart.query.filter(InventoryPart.status == "Active", InventoryPart.quantity > 0).order_by(InventoryPart.part_name).all()
    po = "".join('<option value="' + str(p.id) + '">' + str(p.part_name) + ' (stock: ' + str(p.quantity) + ')</option>' for p in parts)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-plus"></i> <span>Add Part</span> — WO ' + str(wo.work_order_no) + '</h1></div></div>'
         '<div class="card"><form method="post"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Part *</label><select class="form-select" name="part_id" required><option value="">-- Select --</option>' + po + '</select></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Qty *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" min="0" class="form-control" name="unit_cost"></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);">Cancel</a><button type="submit" class="btn-primary"><i class="fas fa-plus"></i> Add</button></div></div></form></div>')
    return page("Add Part", c)

@app.route("/workorders/<int:wo_id>/parts/<int:part_id>/remove", methods=["POST"])
@login_required
def workorder_part_remove(wo_id, part_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_parts(wo): abort(403)
    if wo.status not in ["Assigned","In Progress"]: flash("Cannot remove","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
    try:
        wop = WorkOrderPart.query.filter_by(work_order_id=wo.id, id=part_id).first()
        if not wop: flash("Not found","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        part = get_one(InventoryPart, wop.part_id)
        if part: part.quantity = (part.quantity or 0) + (wop.quantity or 0)
        db.session.delete(wop)
        log_audit("Part Removed","WorkOrder",wo.id,old_value=str(part.part_name if part else "?"))
        db.session.commit(); flash("Part removed","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo.id))

@app.route("/api/notifications/unread")
@login_required
def api_unread():
    c = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    latest = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).first()
    return jsonify({"unread": c, "latest_id": latest.id if latest else None, "latest_title": latest.title if latest else None, "server_time": datetime.utcnow().isoformat()})

@app.route("/notifications")
@login_required
def notifications():
    ns = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    rows = []
    for n in ns:
        cls = "" if n.is_read else "table-warning"
        link = n.link or "#"
        ra = '<span style="color:var(--success);">✓</span>' if n.is_read else '<a class="btn-primary" href="/notifications/mark-read/' + str(n.id) + '" style="padding:0.4rem 0.8rem;font-size:0.8rem;">Read</a>'
        rows.append('<tr class="' + cls + '"><td><a href="' + link + '" style="color:var(--rori-gold);font-weight:600;">' + str(n.title) + '</a></td><td>' + str(n.message) + '</td><td>' + str(n.notification_type) + '</td><td>' + (n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "") + '</td><td>' + ra + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-bell"></i> <span>Notifications</span></h1></div></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Title</th><th>Message</th><th>Type</th><th>Date</th><th>Action</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" style="text-align:center;color:var(--text-secondary);">None</td></tr>') + '</tbody></table></div></div>')
    return page("Notifications", c)

@app.route("/notifications/mark-read/<int:n_id>", methods=["GET","POST"])
@login_required
def notification_mark_read(n_id):
    try:
        n = get_or_404(Notification, n_id)
        if n.user_id == current_user.id: n.is_read = True; db.session.commit()
        if n.link: return redirect(n.link)
        if n.work_order_id: return redirect(url_for("workorder_detail", wo_id=n.work_order_id))
        if n.request_id: return redirect(url_for("request_detail", req_id=n.request_id))
    except Exception as e: flash("Error: " + str(e),"danger")
    return redirect(url_for("notifications"))

@app.route("/rooms")
@role_required("ADMIN","MANAGER")
def rooms_list():
    rs = Room.query.order_by(Room.room_number).all()
    rows = "".join('<tr><td>' + str(r.room_number) + '</td><td>' + str(r.floor) + '</td><td>' + str(r.status) + '</td></tr>' for r in rs)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-door-open"></i> <span>Rooms</span></h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>Room</th><th>Floor</th><th>Status</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Rooms", c)

@app.route("/areas")
@role_required("ADMIN","MANAGER")
def areas_list():
    ar = Area.query.order_by(Area.name).all()
    rows = "".join('<tr><td>' + str(a.name) + '</td><td>' + str(a.department or "—") + '</td></tr>' for a in ar)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-map-marked-alt"></i> <span>Areas</span></h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>Name</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Areas", c)

@app.route("/inventory")
@role_required("ADMIN","MANAGER")
def inventory_list():
    ps = InventoryPart.query.order_by(InventoryPart.part_name).all()
    rows = []
    for p in ps:
        bg = 'badge-danger' if p.quantity <= 0 else 'badge-warning' if p.is_low else 'badge-success'
        label = "Out" if p.quantity <= 0 else "Low" if p.is_low else "OK"
        sn = p.supplier.company_name if p.supplier else "—"
        rows.append('<tr><td>' + str(p.part_name) + '</td><td>' + str(p.category or "—") + '</td><td>' + str(sn) + '</td><td>' + str(p.quantity) + '</td><td>' + str(p.unit or "pcs") + '</td><td>' + str(p.unit_cost or 0) + '</td><td><span class="badge ' + bg + '">' + label + '</span></td><td><a class="btn-primary" href="' + url_for("inventory_edit", part_id=p.id) + '" style="padding:0.4rem 0.8rem;font-size:0.8rem;"><i class="fas fa-edit"></i></a></td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-boxes"></i> <span>Inventory</span></h1></div><a class="btn-primary" href="' + url_for("inventory_add") + '"><i class="fas fa-plus"></i> Add Part</a></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Part</th><th>Category</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Cost</th><th>Status</th><th></th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="8" style="text-align:center;color:var(--text-secondary);">No parts</td></tr>') + '</tbody></table></div></div>')
    return page("Inventory", c)

@app.route("/employees")
@role_required("ADMIN","MANAGER")
def employees_list():
    es = Employee.query.all()
    rows = "".join('<tr><td>' + str(e.id) + '</td><td>' + str(e.name) + '</td><td>' + str(e.job_title) + '</td><td>' + str(e.department or "—") + '</td></tr>' for e in es)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-users"></i> <span>Employees</span></h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Title</th><th>Department</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Employees", c)

@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    us = User.query.all()
    rows = "".join('<tr><td>' + str(u.username) + '</td><td>' + str(u.full_name) + '</td><td>' + str(u.role) + '</td><td>' + str(u.department.name if u.department else "—") + '</td></tr>' for u in us)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-user-cog"></i> <span>Users</span></h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Users", c)

@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join('<tr><td>' + str(l.user.full_name if l.user else "System") + '</td><td>' + str(l.action) + '</td><td>' + str(l.object_type or "") + '</td><td>' + (l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else "") + '</td></tr>' for l in logs)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-history"></i> <span>Audit</span> Log</h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>User</th><th>Action</th><th>Object</th><th>Date</th></tr></thead><tbody>' + (rows if rows else '<tr><td colspan="4" style="text-align:center;color:var(--text-secondary);">No logs</td></tr>') + '</tbody></table></div>')
    return page("Audit", c)

@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    bs = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join('<tr><td>' + str(b) + '</td></tr>' for b in bs)
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-database"></i> <span>Backups</span></h1></div></div>'
         '<form method="post" action="/admin/backup/now" style="margin-bottom:1.5rem;"><button class="btn-primary">Backup Now</button></form>'
         '<div class="card"><table class="table"><thead><tr><th>File</th></tr></thead><tbody>' + (rows if rows else '<tr><td style="text-align:center;color:var(--text-secondary);">None</td></tr>') + '</tbody></table></div>')
    return page("Backups", c)

@app.route("/admin/backup/now", methods=["GET","POST"])
@role_required("ADMIN")
def backup_now():
    try:
        fn = "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db"
        src = sqlite3.connect(os.path.join(BASE_DIR, "hotel_maintenance.db"))
        dst = sqlite3.connect(os.path.join(BACKUP_FOLDER, fn))
        with dst: src.backup(dst)
        src.close(); dst.close()
        flash("Backup created: " + fn,"success")
    except Exception as e: flash("Error: " + str(e),"danger")
    return redirect(url_for("backup_page"))

@app.route("/reports")
@login_required
def reports():
    base = MaintenanceRequest.query.filter_by(is_deleted=False)
    total = base.count(); pending = base.filter_by(status="Pending").count()
    completed = base.filter_by(status="Completed").count(); verified = base.filter_by(status="Verified").count()
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-chart-bar"></i> <span>Reports</span></h1></div></div>'
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Completed</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-double"></i></div><div class="kpi-value">' + str(verified) + '</div><div class="kpi-label">Verified</div></div></div>')
    return page("Reports", c)

@app.route("/debug")
def debug():
    return jsonify({"users": User.query.count(), "departments": Department.query.count(), "requests": MaintenanceRequest.query.filter_by(is_deleted=False).count(), "work_orders": WorkOrder.query.count(), "notifications": Notification.query.count(), "department_signatures": DepartmentSignature.query.count()})

@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel Maintenance","short_name": "RoriMaint","start_url": "/dashboard","display": "standalone","background_color": "#0B0B12","theme_color": "#C5A059","icons": []})

@app.route("/sw.js")
def sw():
    return Response("self.addEventListener('install',e=>self.skipWaiting());", mimetype="application/javascript")

@app.route("/logo.png")
def logo():
    p = os.path.join(app.root_path, "file_00000000d93c821094a2e3f7dced7c77.png")
    if os.path.exists(p): return send_file(p, mimetype="image/png")
    return Response("", mimetype="image/png")

@app.errorhandler(403)
def e403(e): return page("Forbidden",'<div class="alert alert-danger">Access denied.</div>'), 403
@app.errorhandler(404)
def e404(e): return page("Not Found",'<div class="alert alert-warning">Page not found.</div>'), 404
@app.errorhandler(405)
def e405(e): return page("Method Not Allowed",'<div class="alert alert-danger">Method not allowed.</div>'), 405
@app.errorhandler(500)
def e500(e):
    tb = traceback.format_exc(); print("500 ERROR: " + tb)
    return "<h1>500 Error</h1><pre>" + tb + "</pre>", 500

with app.app_context():
    ensure_database_schema()
    seed_data()
    print("🚀 App initialized with Premium Dark Dashboard")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)