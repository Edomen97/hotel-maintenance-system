import csv
import io
import os
import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask,
    abort,
    flash,
    get_flashed_messages,
    jsonify,
    redirect,
    request,
    send_file,
    url_for,
    Response,
    render_template,
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

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
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

ROLES = ["ADMIN", "MANAGER", "MAINTENANCE STAFF", "EMPLOYEE"]
ROOM_STATUSES = ["Available", "Occupied", "Reserved", "Maintenance", "Out of Service"]
REQUEST_STATUSES = [
    "Pending", "Approved", "Assigned", "In Progress", "Completed",
    "Verified", "Closed", "Cancelled", "Overdue",
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
    full_name = db.Column(db.String(120), default="")
    role = db.Column(db.String(30), default="EMPLOYEE", nullable=False)
    phone = db.Column(db.String(30), default="")
    email = db.Column(db.String(120), default="")
    photo_url = db.Column(db.String(255), nullable=True)
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
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))  # ✅ የተጨመረ
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
    department = db.relationship("Department", foreign_keys=[department_id])
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


def seed_data():
    if User.query.first():
        logger.info("Users already exist, skipping seed.")
        return

    # Departments
    departments = [
        "Front Office", "F&B", "Kitchen", "Housekeeping", "Security",
        "Spa & Wellness", "Finance & Accounting", "Marketing & Sales"
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
        (2, "ቸርነት አምና", "Electrical"),
        (3, "ስሞን", "Welding / ብየዳ"),
        (4, "አበባየሁ ክፍሌ", "Maintenance & Plumbing"),
        (5, "አሚር አወል", "Engineering Manager"),
    ]
    for emp_id, name, title in engineering_staff:
        if not Employee.query.get(emp_id):
            db.session.add(Employee(id=emp_id, name=name, job_title=title, department="Engineering"))

    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        admin.set_password("admin123")
        db.session.add(admin)

    if not User.query.filter_by(username="manager").first():
        mgr = User(username="manager", full_name="Maintenance Manager", role="MANAGER", email="manager@rorihotel.local")
        mgr.set_password("manager123")
        db.session.add(mgr)

    if not User.query.filter_by(username="staff").first():
        staff = User(username="staff", full_name="Maintenance Staff", role="MAINTENANCE STAFF", email="staff@rorihotel.local")
        staff.set_password("staff123")
        db.session.add(staff)

    if not User.query.filter_by(username="employee").first():
        emp = User(username="employee", full_name="Hotel Employee", role="EMPLOYEE", email="employee@rorihotel.local")
        emp.set_password("employee123")
        db.session.add(emp)

    db.session.commit()

    if MaintenanceRequest.query.count() == 0:
        admin = User.query.filter_by(username="admin").first()
        general_cat = Category.query.filter_by(name="General").first()
        dept = Department.query.first()
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
                    department_id=dept.id if dept else None,
                    description=f"Initial maintenance note: {item_name} at {area_name}",
                    priority="MEDIUM",
                    status="Pending",
                    requested_by_id=admin.id if admin else None,
                    due_date=datetime.utcnow() + timedelta(hours=24),
                )
                db.session.add(req)
        db.session.commit()
    logger.info("Seed data loaded successfully.")
    logger.warning("Default passwords are used. Please change them immediately!")


# --------------------------------------------------------------
# AUTH
# --------------------------------------------------------------
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

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    log_audit("Logout", "User", current_user.id)
    db.session.commit()
    logout_user()
    return redirect(url_for("login"))


# --------------------------------------------------------------
# PROFILE
# --------------------------------------------------------------
@app.route("/profile")
@login_required
def profile():
    return render_template("profile.html", user=current_user)


@app.route("/profile/update", methods=["POST"])
@login_required
def profile_update():
    user = current_user
    user.full_name = request.form.get("full_name", "").strip()
    user.email = request.form.get("email", "").strip()
    user.phone = request.form.get("phone", "").strip()

    photo = request.files.get("profile_photo")
    if photo and photo.filename != "":
        if allowed_file(photo.filename):
            if user.photo_url:
                old_path = os.path.join(app.config['PROFILE_PIC_FOLDER'], user.photo_url)
                if os.path.exists(old_path):
                    os.remove(old_path)
            ext = photo.filename.rsplit('.', 1)[1].lower()
            filename = secure_filename(f"profile_{user.id}_{uuid.uuid4().hex}.{ext}")
            file_path = os.path.join(app.config['PROFILE_PIC_FOLDER'], filename)
            photo.save(file_path)
            user.photo_url = filename
            log_audit("Profile Photo Update", "User", user.id, new_value=filename)
        else:
            flash("ልክ ያልሆነ የፋይል አይነት።", "danger")
            return redirect(url_for("profile"))

    db.session.commit()
    log_audit("Profile Update", "User", user.id)
    flash("መረጃዎ በተሳካ ሁኔታ ተዘምኗል!", "success")
    return redirect(url_for("profile"))


@app.route("/profile/photo/<filename>")
@login_required
def profile_photo(filename):
    return send_file(os.path.join(app.config['PROFILE_PIC_FOLDER'], filename))


@app.route("/profile/photo/delete", methods=["POST"])
@login_required
def profile_photo_delete():
    user = current_user
    if user.photo_url:
        old_path = os.path.join(app.config['PROFILE_PIC_FOLDER'], user.photo_url)
        if os.path.exists(old_path):
            os.remove(old_path)
        user.photo_url = None
        db.session.commit()
        flash("ፎቶዎ ተሰርዟል", "success")
    return redirect(url_for("profile"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not current_user.check_password(old_password):
            flash("የድሮ የይለፍ ቃል ተሳስቷል", "danger")
            return redirect(url_for("change_password"))

        if len(new_password) < 6:
            flash("አዲስ የይለፍ ቃል ቢያንስ 6 ፊደላት ሊኖረው ይገባል", "danger")
            return redirect(url_for("change_password"))

        if new_password != confirm_password:
            flash("አዲስ የይለፍ ቃል እና ማረጋገጫው አይመሳሰሉም", "danger")
            return redirect(url_for("change_password"))

        current_user.set_password(new_password)
        db.session.commit()
        log_audit("Password Change", "User", current_user.id)
        flash("የይለፍ ቃልዎ በተሳካ ሁኔታ ተቀይሯል!", "success")
        return redirect(url_for("profile"))

    return render_template("change_password.html")


# --------------------------------------------------------------
# DASHBOARD
# --------------------------------------------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    role = current_user.role
    total_requests = MaintenanceRequest.query.count()
    pending = MaintenanceRequest.query.filter_by(status="Pending").count()
    in_progress = MaintenanceRequest.query.filter_by(status="In Progress").count()
    completed = MaintenanceRequest.query.filter_by(status="Completed").count()
    overdue = sum(1 for r in MaintenanceRequest.query.all() if r.is_overdue)
    urgent = MaintenanceRequest.query.filter_by(priority="URGENT").count()
    low_stock = sum(1 for p in InventoryPart.query.all() if p.is_low)
    out_rooms = Room.query.filter(Room.status.in_(["Maintenance", "Out of Service"])).count()
    total_employees = Employee.query.count()

    return render_template("dashboard.html",
        role=role,
        total_requests=total_requests,
        pending=pending,
        in_progress=in_progress,
        completed=completed,
        overdue=overdue,
        urgent=urgent,
        low_stock=low_stock,
        out_rooms=out_rooms,
        total_employees=total_employees
    )


# --------------------------------------------------------------
# SERVICE REQUEST (NEW REQUEST)
# --------------------------------------------------------------
@app.route("/request/new")
@login_required
def new_request():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    categories = Category.query.order_by(Category.name).all()
    departments = Department.query.order_by(Department.name).all()
    return render_template("new_request.html", rooms=rooms, areas=areas, items=items,
                           categories=categories, departments=departments)


@app.route("/request/create", methods=["POST"])
@login_required
def create_request():
    try:
        # Get form data
        location_type = request.form.get("location_type")
        room_id = request.form.get("room_id", type=int)
        area_id = request.form.get("area_id", type=int)
        working_item_id = request.form.get("working_item_id", type=int)
        category_id = request.form.get("category_id", type=int)
        department_id = request.form.get("department_id", type=int)
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "MEDIUM")
        due_date = request.form.get("due_date")

        # Validation
        if location_type not in ["Room", "Hotel Area"]:
            flash("የቦታ አይነት ልክ አይደለም", "danger")
            return redirect(url_for("new_request"))

        if location_type == "Room":
            room = Room.query.get(room_id)
            if not room or not (201 <= int(room.room_number) <= 300):
                flash("ልክ ያልሆነ ክፍል። ክፍሉ ከ201-300 መሆን አለበት።", "danger")
                return redirect(url_for("new_request"))
            floor = room.floor
            area_id = None
        else:
            area = Area.query.get(area_id)
            if not area:
                flash("ልክ ያልሆነ ቦታ", "danger")
                return redirect(url_for("new_request"))
            floor = None
            room_id = None

        if not description:
            flash("የችግሩ መግለጫ ያስፈልጋል", "danger")
            return redirect(url_for("new_request"))

        # Due date
        due = datetime.strptime(due_date, "%Y-%m-%dT%H:%M") if due_date else datetime.utcnow() + timedelta(hours=PRIORITIES.get(priority, 24))

        # Create new request
        new_request = MaintenanceRequest(
            request_no=request_no_generator(),
            location_type=location_type,
            floor=floor,
            room_id=room_id,
            area_id=area_id,
            working_item_id=working_item_id,
            category_id=category_id,
            department_id=department_id,
            description=description,
            priority=priority,
            status="Pending",
            requested_by_id=current_user.id,
            due_date=due,
        )
        db.session.add(new_request)
        db.session.flush()  # to get ID

        # Handle photo
        photo = request.files.get("photo")
        if photo and photo.filename != "" and allowed_file(photo.filename):
            ext = photo.filename.rsplit('.', 1)[1].lower()
            filename = secure_filename(f"req_{new_request.id}_{uuid.uuid4().hex}.{ext}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(file_path)

            photo_record = Photo(
                filename=filename,
                object_type="request",
                object_id=new_request.id,
                photo_type="Before",
                uploaded_by_id=current_user.id,
                file_size=os.path.getsize(file_path)
            )
            db.session.add(photo_record)

        # Status history
        hist = StatusHistory(
            request_id=new_request.id,
            status="Pending",
            user_id=current_user.id,
            notes="Request submitted"
        )
        db.session.add(hist)

        # Audit log
        log_audit("Create", "MaintenanceRequest", new_request.id, new_value=f"{new_request.request_no} - {new_request.priority}")

        # Notify managers
        managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
        notify([u.id for u in managers],
               f"አዲስ ጥያቄ {new_request.request_no} በ {new_request.location_name} ተልኳል",
               "New Request",
               new_request.id)

        if new_request.priority == "URGENT":
            notify([u.id for u in managers],
                   f"አስቸኳይ ጥያቄ {new_request.request_no}",
                   "Urgent",
                   new_request.id)

        db.session.commit()
        flash("✅ የጥገና ጥያቄዎ በተሳካ ሁኔታ ተልኳል!", "success")
        return redirect(url_for("requests_list"))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Request creation error: {e}")
        flash(f"ጥያቄው ሊላክ አልቻለም: {str(e)}", "danger")
        return redirect(url_for("new_request"))


# --------------------------------------------------------------
# REQUESTS LIST & DETAIL
# --------------------------------------------------------------
@app.route("/requests")
@login_required
def requests_list():
    if current_user.role == "EMPLOYEE":
        reqs = MaintenanceRequest.query.filter_by(requested_by_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    elif current_user.role == "MAINTENANCE STAFF":
        reqs = MaintenanceRequest.query.filter_by(assigned_to_id=current_user.id).order_by(MaintenanceRequest.created_at.desc()).all()
    else:
        reqs = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    return render_template("requests_list.html", requests=reqs)


@app.route("/requests/<int:req_id>")
@login_required
def request_detail(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    photos = Photo.query.filter_by(object_type="request", object_id=req.id).all()
    history = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.desc()).all()
    return render_template("request_detail.html", request=req, photos=photos, history=history)


@app.route("/requests/<int:req_id>/approve")
@role_required("MANAGER", "ADMIN")
def request_approve(req_id):
    req = MaintenanceRequest.query.get_or_404(req_id)
    if req.status == "Pending":
        old = req.status
        req.status = "Approved"
        hist = StatusHistory(request_id=req.id, status=req.status, user_id=current_user.id)
        db.session.add(hist)
        log_audit("Status Change", "MaintenanceRequest", req.id, old, req.status)
        notify([req.requested_by_id], f"ጥያቄዎ {req.request_no} ጸድቋል", "Status Changed", req.id)
        db.session.commit()
        flash("ጥያቄው ጸድቋል", "success")
    return redirect(url_for("request_detail", req_id=req_id))


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
    return redirect(url_for("request_detail", req_id=req_id))


# --------------------------------------------------------------
# WORK ORDERS
# --------------------------------------------------------------
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "MAINTENANCE STAFF":
        wos = WorkOrder.query.filter_by(assigned_to_id=current_user.id).order_by(WorkOrder.created_at.desc()).all()
    else:
        wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    return render_template("workorders_list.html", workorders=wos)


@app.route("/workorders/new", methods=["GET", "POST"])
@role_required("MANAGER", "ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int)
    req = MaintenanceRequest.query.get(req_id) if req_id else None
    users = User.query.filter(User.role.in_(["MAINTENANCE STAFF", "MANAGER", "ADMIN"])).all()

    if request.method == "POST":
        request_id = request.form.get("request_id", type=int)
        assigned_to_id = request.form.get("assigned_to_id", type=int)
        work_performed = request.form.get("work_performed", "")
        req = MaintenanceRequest.query.get_or_404(request_id)
        if req.status not in ["Approved", "Assigned"]:
            flash("ጥያቄው አልጸደቀም", "danger")
            return redirect(url_for("workorder_create", request_id=request_id))
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

    return render_template("workorder_create.html", request=req, users=users)


@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    photos = Photo.query.filter_by(object_type="workorder", object_id=wo.id).all()
    return render_template("workorder_detail.html", workorder=wo, parts=parts, photos=photos)


@app.route("/workorders/<int:wo_id>/progress")
@role_required("MAINTENANCE STAFF", "MANAGER", "ADMIN")
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
    return redirect(url_for("workorder_detail", wo_id=wo_id))


@app.route("/workorders/<int:wo_id>/complete", methods=["GET", "POST"])
@role_required("MAINTENANCE STAFF", "MANAGER", "ADMIN")
def workorder_complete(wo_id):
    wo = WorkOrder.query.get_or_404(wo_id)
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()

    if request.method == "POST":
        work_done = request.form.get("work_done", "").strip()
        hours_spent = request.form.get("hours_spent", 0)
        notes = request.form.get("notes", "").strip()
        used_item = request.form.get("used_item", type=int)
        item_qty = request.form.get("item_qty", type=float, default=0)

        file = request.files.get("photo")
        filename = None
        if file and file.filename != "" and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = secure_filename(f"wo_{wo.id}_completed_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
        elif not file or file.filename == "":
            flash("እባክዎ የስራውን ውጤት የሚያሳይ ፎቶ ያንሱ ወይም ያስገቡ!", "danger")
            return redirect(url_for("workorder_complete", wo_id=wo_id))

        if not work_done:
            flash("እባክዎ የተሰራውን ስራ ይግለጹ!", "danger")
            return redirect(url_for("workorder_complete", wo_id=wo_id))

        wo.work_performed = work_done
        wo.labor_hours = float(hours_spent or 0)
        wo.completion_notes = notes
        if filename:
            wo.completion_photo = filename
        wo.status = "Completed"
        wo.completed_by_id = current_user.id
        wo.updated_at = datetime.utcnow()

        if wo.request:
            wo.request.status = "Completed"
            wo.request.completed_date = datetime.utcnow()
            wo.request.updated_at = datetime.utcnow()
            wo.request.notes = notes

        hist = StatusHistory(
            request_id=wo.request_id,
            status="Completed",
            user_id=current_user.id,
            notes=f"Work completed by {current_user.full_name}. Hours: {hours_spent}"
        )
        db.session.add(hist)

        if used_item and item_qty and item_qty > 0:
            part = InventoryPart.query.get(used_item)
            if part and part.quantity >= item_qty:
                part.quantity -= item_qty
                wo_part = WorkOrderPart(
                    work_order_id=wo.id,
                    part_id=part.id,
                    quantity=item_qty,
                    unit_cost=part.unit_cost
                )
                db.session.add(wo_part)
                mov = StockMovement(
                    part_id=part.id,
                    movement_type="OUT",
                    quantity=item_qty,
                    reason=f"Work Order {wo.work_order_no}",
                    work_order_id=wo.id,
                    user_id=current_user.id
                )
                db.session.add(mov)
                if part.quantity <= 0:
                    managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
                    notify([u.id for u in managers], f"{part.part_name} ክምችት አልቋል", "Out of Stock", work_order_id=wo.id)
                elif part.quantity <= part.minimum_stock:
                    managers = User.query.filter(User.role.in_(["MANAGER", "ADMIN"])).all()
                    notify([u.id for u in managers], f"{part.part_name} ዝቅተኛ ክምችት", "Low Stock", work_order_id=wo.id)
            elif part:
                flash(f"በቂ ክምችት የለም! {part.part_name} የሚፈለገው: {item_qty}, ያለው: {part.quantity}", "danger")
                db.session.rollback()
                return redirect(url_for("workorder_complete", wo_id=wo_id))

        log_audit("Completion", "WorkOrder", wo.id, old_value="In Progress", new_value="Completed")
        if wo.request and wo.request.requested_by_id:
            notify([wo.request.requested_by_id], f"የስራ ትዕዛዝ {wo.work_order_no} ተጠናቋል", "Status Changed", wo.request_id, wo.id)

        db.session.commit()
        flash("✅ የጥገና ሪፖርቱ እና ፎቶው በተሳካ ሁኔታ ተልኳል!", "success")
        return redirect(url_for("workorder_detail", wo_id=wo_id))

    return render_template("workorder_complete.html", wo_id=wo.id, parts=parts)


# --------------------------------------------------------------
# ROOMS, AREAS, INVENTORY, ETC. (መሰረታዊ CRUD)
# --------------------------------------------------------------
@app.route("/rooms")
@role_required("ADMIN", "MANAGER")
def rooms_list():
    rooms = Room.query.order_by(Room.room_number).all()
    return render_template("rooms_list.html", rooms=rooms)


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
    return render_template("room_edit.html", room=room)


@app.route("/areas")
@role_required("ADMIN", "MANAGER")
def areas_list():
    areas = Area.query.order_by(Area.name).all()
    return render_template("areas_list.html", areas=areas)


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
    return render_template("area_create.html")


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
    return render_template("area_edit.html", area=area)


@app.route("/inventory")
@role_required("ADMIN", "MANAGER")
def inventory_list():
    parts = InventoryPart.query.order_by(InventoryPart.part_name).all()
    return render_template("inventory_list.html", parts=parts)


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
    return render_template("inventory_create.html")


# --------------------------------------------------------------
# OTHER ROUTES (በአጭሩ)
# --------------------------------------------------------------
@app.route("/preventive")
@role_required("ADMIN", "MANAGER")
def preventive_list():
    tasks = PreventiveMaintenance.query.order_by(PreventiveMaintenance.next_due_date).all()
    return render_template("preventive_list.html", tasks=tasks)


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
    return render_template("preventive_create.html")


@app.route("/checklists")
@role_required("ADMIN", "MANAGER")
def checklists_list():
    templates = ChecklistTemplate.query.all()
    return render_template("checklists_list.html", templates=templates)


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
    return render_template("checklist_create.html")


@app.route("/suppliers")
@role_required("ADMIN", "MANAGER")
def suppliers_list():
    suppliers = Supplier.query.all()
    return render_template("suppliers_list.html", suppliers=suppliers)


@app.route("/suppliers/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def supplier_create():
    if request.method == "POST":
        s = Supplier(
            company_name=request.form.get("company_name"),
            contact_person=request.form.get("contact_person"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            address=request.form.get("address"),
            supplied_items=request.form.get("supplied_items"),
            status="Active"
        )
        db.session.add(s)
        log_audit("Create", "Supplier", s.id, new_value=s.company_name)
        db.session.commit()
        flash("አቅራቢ ተጨምሯል", "success")
        return redirect(url_for("suppliers_list"))
    return render_template("supplier_create.html")


@app.route("/contractors")
@role_required("ADMIN", "MANAGER")
def contractors_list():
    contractors = Contractor.query.all()
    return render_template("contractors_list.html", contractors=contractors)


@app.route("/contractors/new", methods=["GET", "POST"])
@role_required("ADMIN", "MANAGER")
def contractor_create():
    if request.method == "POST":
        c = Contractor(
            name=request.form.get("name"),
            service_type=request.form.get("service_type"),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            rate=float(request.form.get("rate", 0) or 0),
            status="Active"
        )
        db.session.add(c)
        log_audit("Create", "Contractor", c.id, new_value=c.name)
        db.session.commit()
        flash("ተቋራጭ ተጨምሯል", "success")
        return redirect(url_for("contractors_list"))
    return render_template("contractor_create.html")


@app.route("/employees")
@role_required("ADMIN", "MANAGER")
def employees_list():
    employees = Employee.query.order_by(Employee.id).all()
    return render_template("employees_list.html", employees=employees)


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
    return render_template("employee_create.html")


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
    return render_template("employee_edit.html", employee=emp)


@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    users = User.query.all()
    return render_template("admin_users.html", users=users)


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
    return render_template("admin_user_create.html")


@app.route("/admin/masterdata")
@role_required("ADMIN")
def master_data():
    categories = Category.query.order_by(Category.name).all()
    items = WorkingItem.query.order_by(WorkingItem.name).all()
    return render_template("master_data.html", categories=categories, items=items)


@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("audit_logs.html", logs=logs)


# --------------------------------------------------------------
# BACKUP & RESTORE
# --------------------------------------------------------------
def get_db_path():
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return os.path.join(BASE_DIR, "hotel_maintenance.db")


@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    return render_template("backup.html", backups=backups)


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


# --------------------------------------------------------------
# REPORTS & NOTIFICATIONS
# --------------------------------------------------------------
@app.route("/reports")
@login_required
def reports():
    return render_template("reports.html")


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


@app.route("/notifications")
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return render_template("notifications.html", notifications=notifs)


@app.route("/notifications/<int:n_id>/read")
@login_required
def notification_read(n_id):
    n = Notification.query.get_or_404(n_id)
    if n.user_id == current_user.id:
        n.read = True
        db.session.commit()
    return redirect(url_for("notifications"))


@app.route("/qr")
@login_required
def qr_index():
    rooms = Room.query.order_by(Room.room_number).all()
    areas = Area.query.order_by(Area.name).all()
    return render_template("qr_index.html", rooms=rooms, areas=areas)


@app.route("/qr/<string:loc_type>/<int:id>")
@login_required
def qr_code(loc_type, id):
    if loc_type == "room":
        obj = Room.query.get_or_404(id)
        url = url_for("new_request", _external=True) + f"?room_id={obj.id}"
        label = f"Room {obj.room_number}"
    elif loc_type == "area":
        obj = Area.query.get_or_404(id)
        url = url_for("new_request", _external=True) + f"?area_id={obj.id}"
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


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/backups")
def backups():
    try:
        backups = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
        return render_template("backup.html", backups=backups)
    except Exception as e:
        flash(f"Error loading backups: {str(e)}", "danger")
        return redirect(url_for("index"))


# --------------------------------------------------------------
# PWA
# --------------------------------------------------------------
@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "Rori Hotel Maintenance",
        "short_name": "RoriMaint",
        "start_url": "/dashboard",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1a1a2e",
        "icons": []
    })


@app.route("/sw.js")
def service_worker():
    return Response("""self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('fetch', e => {});""", mimetype="application/javascript")


@app.route('/logo.png')
def serve_logo():
    logo_path = os.path.join(app.root_path, 'static', 'logo.png')
    if os.path.exists(logo_path):
        return send_file(logo_path, mimetype='image/png')
    else:
        return send_file(io.BytesIO(b''), mimetype='image/png')


# --------------------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------------------
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", error="403", message="ይህን ገጽ ለማየት ፍቃድ የለዎትም።"), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", error="404", message="ገጹ አልተገኘም።"), 404


@app.errorhandler(500)
def internal_error(e):
    if app.config.get("DEBUG", False):
        import traceback
        return f"<pre>{traceback.format_exc()}</pre>", 500
    return render_template("error.html", error="500", message="የስርዓት ስህተት ተከስቷል። እባክዎ ቆየት ብለው ይሞክሩ።"), 500


# --------------------------------------------------------------
# INIT
# --------------------------------------------------------------
with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)