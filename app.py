# app.py - Rori Hotel Maintenance Management System
# Developer: Edom Adinew
import csv, io, json, os, re, sqlite3, uuid, traceback, calendar, shutil
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import text, inspect, func, case
from flask import (Flask, abort, flash, get_flashed_messages, jsonify, redirect,
                   render_template, render_template_string, request, send_file,
                   url_for, Response, make_response)
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

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    print("✅ Using DATABASE_URL (persistent database)")
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "hotel_maintenance.db")
    print("⚠️ WARNING: Using local SQLite file. On Render, this WILL be wiped on every deploy/restart.")
    print("⚠️ Set DATABASE_URL environment variable to a PostgreSQL database to preserve data.")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True, "pool_recycle": 280}
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

RORI_ROOM_STRUCTURE = {2: list(range(201, 226)), 3: list(range(301, 326)),
                        4: list(range(401, 426)), 5: list(range(501, 526))}

NEW_ITEMS_BY_DEPT = {
    "Food & Beverage": ["🪑 Table, Chair, Sofa", "🚪 Door / Lock / Handle", "💡 Lights / Switch / Socket",
        "❄️ AC / Fan", "🚰 Sink / Tap / Drainage", "🧊 Beverage Refrigerator / Display Cooler",
        "🍹 Bar Equipment", "☕ Coffee Machine", "🪟 Window / Curtain / Blind",
        "🧱 Floor / Wall / Ceiling", "🔌 Electrical Problems", "🚿 Water Leakage",
        "🧯 Fire Extinguisher / Safety Equipment", "🏨 Restaurant / Bar / Dining Area Maintenance"],
    "Kitchen": ["🔥 Gas Stove / Electric Stove", "🍕 Oven", "🍗 Grill", "🍟 Deep Fryer",
        "♨️ Bain-Marie / Food Warmer", "🧊 Refrigerator", "❄️ Freezer",
        "🥩 Meat Slicer / Grinder", "🧼 Dishwasher", "💨 Exhaust Hood / Ventilation",
        "🚰 Kitchen Sink / Tap / Drainage", "🔌 Electrical Equipment", "💡 Kitchen Lights",
        "🪑 Kitchen Tables / Shelves", "🚪 Kitchen Doors", "🧯 Fire & Gas Safety Equipment",
        "💧 Water Leakage", "🧱 Floor / Wall / Ceiling"],
    "Security": ["📹 CCTV Cameras", "🖥️ DVR/NVR", "🔐 Access Control", "🚪 Security Doors & Locks",
        "🚨 Alarm System", "🔥 Fire Alarm", "💡 Security Lighting", "⚡ Electrical",
        "📻 Walkie-Talkie / Communication", "🚧 Gate / Barrier", "🪟 Windows & Security Grills",
        "🔋 UPS / Backup Power", "🧯 Fire/Safety Equipment", "🪑 Security Desk/Chair/Furniture",
        "🏢 Security Office Maintenance", "🅿️ Parking-Area Security Equipment",
        "🔌 Network Cables/Switches for CCTV/Access Control"],
    "SPA": ["🚿 Shower — Tap, Shower Head, Water Leakage", "🛁 Jacuzzi / Hot Tub — Pump, Heater, Water Circulation",
        "♨️ Sauna — Heater, Temperature Control, Door", "💨 Steam Room — Steam Generator, Control, Ventilation",
        "❄️ AC / Air Conditioning", "💡 Lights / Switch / Socket", "🚰 Sink / Tap / Drainage",
        "🚪 Doors / Locks / Handles", "🪞 Mirror", "🪑 Massage Bed / Treatment Bed",
        "🛏️ Furniture / Sofa / Chair", "🧺 Towel Warmer / Laundry Equipment", "🔌 Electrical Equipment",
        "💧 Water Leakage / Plumbing", "🧱 Floor / Wall / Ceiling", "🎵 Sound System",
        "🧯 Fire & Safety Equipment", "🏊 Pool-Related Equipment"],
    "Marketing": ["💡 Lights / Switch / Socket", "🖥️ Computer / Monitor", "🖨️ Printer / Scanner",
        "📺 TV / Display Screen", "📸 Camera / Photography Equipment",
        "🎤 Microphone / Speaker / Sound System", "🌐 Internet / Wi-Fi / Network",
        "🔌 Electrical Equipment", "❄️ AC / Fan", "🚪 Door / Lock / Handle",
        "🪑 Desk / Chair / Office Furniture", "🪧 Signboard / Advertising Board",
        "🖼️ Display / Poster Frames", "🏢 Marketing Office Maintenance"],
    "IT": ["💡 Lights / Switch / Socket", "🚪 Door / Lock / Handle", "🪟 Window / Curtain / Blind",
        "❄️ AC / Air Conditioning", "🌬️ Ventilation / Exhaust Fan", "🔌 Electrical Power / Wiring",
        "⚡ Electrical Panel / Breaker", "🔋 UPS Power Supply Area", "🧱 Floor / Wall / Ceiling",
        "💧 Water Leakage", "🚰 Sink / Tap / Drainage", "🔥 Fire Extinguisher / Safety Equipment",
        "🪑 Desk / Chair / Office Furniture", "🗄️ Cabinet / Shelf",
        "🏢 IT Office / Server Room Maintenance", "🧹 Cleaning / Preventive Maintenance",
        "🌡️ Server Room Cooling / Temperature", "🛠️ General Civil / Plumbing Maintenance"],
}

LAUNDRY_ITEMS = ["Washing Machine", "Dryer", "Ironing Machine / Press", "Sewing Machine",
    "Laundry Extractor / Spinner", "Steam Boiler / Steam System", "Steam Iron",
    "Water Supply / Tap / Pipe", "Drainage / Drain Pipe",
    "Electrical Panel / Socket / Switch", "Laundry Lights",
    "AC / Ventilation / Exhaust Fan", "Doors / Locks / Handles",
    "Laundry Tables / Shelves", "Fire & Safety Equipment",
    "Power Supply / UPS", "Floor / Wall / Ceiling", "Water Leakage"]
LAUNDRY_AREA_NAME = "Laundry Area"

# ══════════════════════════════════════════ COMPLETE HOTEL LOCATIONS (Farm Area included)
HOTEL_AREAS = [
    "Main Hotel Entrance Gate", "VIP Parking Area", "Expansion Building Area",
    "Staff Gate Area", "Customer Restroom", "Fountain Area", "Garden Area",
    "Steward Area", "Water Tank Area", "Wastewater Drainage Area — የፍሳሽ ውሃ መስገጃ",
    "Generator Area", "Motor Parking Area", "New Compound Area",
    "Dukale Compound Area", "X-Ray Gate Area", "Main Site / General Hotel Area",
    "Kalicheral Kitchen Area",
    "Farm Area / የእርሻ አካባቢ", "Cella Coffee", "Lobby Bar", "Guest Room Area",
    "Housekeeping Office", "Housekeeping Store", "Linen Store",
    "Staff Changing Room", "Staff Restroom", "Staff Canteen",
    "Engineering Workshop", "Maintenance Store", "Generator Room",
    "Boiler / Plant Room", "Water Pump Area", "Sewage / Septic Area",
    "Kitchen Area", "Restaurant Area", "Bar Area", "Conference / Meeting Area",
    "Swimming Pool Area", "Pool Changing Room", "Pool Equipment Area", "Gym Area",
    "Reception / Front Desk", "Lobby Area", "Corridor Area", "Staircase Area",
    "Elevator Area", "Basement Area", "Roof / Rooftop Area", "Parking Area",
    "Security Office", "Waste Collection Area",
]

# ══════════════════════════════════════════ HOUSEKEEPING ITEM MASTER LIST (bilingual)
HOUSEKEEPING_DEPT_NAME = "Housekeeping"
HOUSEKEEPING_CATEGORIES = {
    "Beds & Linens": [
        "Mattress / ፍራሽ", "Bedsheet / አልጋ አንሶላ", "Duvet / Comforter / ኮምፎርተር",
        "Pillow & Pillowcase / ትራስ እና የትራስ ጨርቅ", "Mattress Protector / የፍራሽ ልብስ",
        "Curtains / Drapes / መጋረጃ", "Blanket / ብርድ ልብስ",
        "Bed Frame / የአልጋ ፍሬም", "Headboard / የአልጋ ራስ",
    ],
    "Bathroom Items": [
        "Bath Towel / የገላ ፎጣ", "Hand Towel / የእጅ ፎጣ", "Bath Mat / የእግር ፎጣ",
        "Shower Curtain / የሻወር መጋረጃ", "Hairdryer / የፀጉር ማድረቂያ",
        "Trash Can / የቆሻሻ መጣያ", "Soap Dispenser / የሳሙና ማቀፊያ",
        "Toilet Brush / የሽንት ቤት ብሩሽ", "Toilet Paper Holder / የሽንት ቤት ወረቀት መያዣ",
        "Shower Head / የሻወር ራስ", "Bathroom Mirror / የመታጠቢያ ቤት መስታወት",
    ],
    "Furniture & Fixtures": [
        "Wardrobe / Closet / የልብስ ቁምሳጥን", "Clothes Hangers / የልብስ መስቀያ",
        "Writing Desk & Chair / ጠረጴዛ እና ወንበር", "Nightstand / Side Table / የአልጋ ጎን ጠረጴዛ",
        "Luggage Rack / የሻንጣ ማስቀመጫ", "Wall Mirror / የግድግዳ መስታወት",
        "Safe Box / ሴፍ ቦክስ", "Sofa / ሶፋ", "Armchair / የእጅ ወንበር",
    ],
    "Electronics & Appliances": [
        "Television & Remote / ቲቪ እና ሪሞት", "Mini Fridge / ሚኒ ፍሪጅ",
        "Refrigerator / ፍሪጅ", "Electric Kettle / የውሃ ማፍያ",
        "Iron & Ironing Board / ካውያ እና ማደሪያ", "Air Conditioner & Remote / AC እና ሪሞት",
        "Desk Lamp / የጠረጴዛ መብራት", "Room Telephone / የክፍል ስልክ",
    ],
    "Housekeeping Cleaning Tools": [
        "Cleaning Trolley / Cart / የጽዳት ትሮሊ", "Vacuum Cleaner / ቫኪዩም ክሊነር",
        "Mop & Bucket / ሞፕ እና ባልዲ", "Dustbin / Waste Basket / የቆሻሻ ቅርጫት",
        "Broom / መጥረጊያ", "Dustpan / መጣረጊያ", "Cleaning Brush / የጽዳት ብሩሽ",
        "Window Cleaning Tools / የመስኮት ማጽጃ መሣሪያ",
    ],
    "Room & General Fixtures": [
        "Door Lock / የበር መቆለፊያ", "Door Handle / የበር መያዣ", "Window / መስኮት",
        "Light / መብራት", "Light Switch / የመብራት ማብሪያ", "Electrical Socket / ኤሌክትሪክ ሶኬት",
        "Water Tap / የውሃ ቧንቧ", "Sink / ሲንክ", "Toilet / ሽንት ቤት", "Shower / ሻወር",
    ],
}
HOUSEKEEPING_ITEMS_FLAT = [(c, i) for c, items in HOUSEKEEPING_CATEGORIES.items() for i in items]
HOUSEKEEPING_CATEGORY_NAMES = set(HOUSEKEEPING_CATEGORIES.keys())

INVENTORY_CATEGORIES = ["Tools", "Hardware / Fasteners", "Electrical Parts", "Plumbing Parts",
    "AC / HVAC Parts", "Door & Window Parts", "Civil / Building Materials",
    "Welding / Metal Work", "Safety / PPE", "Maintenance Consumables", "General Maintenance Equipment"]

INVENTORY_ITEMS_BY_CATEGORY = {
    "Tools": [("Hammer / መዶሻ", "pcs"), ("Scissors / መቀስ", "pcs"), ("Screwdriver", "pcs"), ("Pliers", "pcs"), ("Spanner", "pcs"), ("Wrench", "pcs"), ("Allen Key", "set"), ("Socket Set", "set"), ("Pipe Wrench", "pcs"), ("Wire Cutter", "pcs"), ("Wire Stripper", "pcs"), ("Measuring Tape", "pcs"), ("Spirit Level", "pcs"), ("Saw", "pcs"), ("Hacksaw", "pcs"), ("Chisel", "pcs"), ("File", "pcs"), ("Drill", "pcs"), ("Drill Bits", "set"), ("Utility Knife", "pcs"), ("Bolt Cutter", "pcs"), ("Crowbar", "pcs")],
    "Hardware / Fasteners": [("Nails / ሚስማር", "kg"), ("Bolts / ብሎን", "pcs"), ("Nuts", "pcs"), ("Washers", "pcs"), ("Screws", "pcs"), ("Wall Plugs", "pcs"), ("Anchors", "pcs"), ("Rivets", "pcs"), ("Threaded Rod", "pcs"), ("U-Bolts", "pcs"), ("Cable Ties", "pcs"), ("Hose Clamps", "pcs"), ("Pipe Clamps", "pcs"), ("Brackets", "pcs")],
    "Electrical Parts": [("LED Bulb", "pcs"), ("Tube Light", "pcs"), ("Light Holder", "pcs"), ("Switch", "pcs"), ("Electrical Socket", "pcs"), ("Plug", "pcs"), ("Electrical Cable / Wire", "m"), ("Fuse", "pcs"), ("MCB", "pcs"), ("RCCB / RCD", "pcs"), ("Contactor", "pcs"), ("Relay", "pcs"), ("Capacitor", "pcs"), ("Terminal Block", "pcs"), ("Junction Box", "pcs"), ("Electrical Tape", "roll"), ("Heat Shrink", "m"), ("PVC Conduit", "m")],
    "Plumbing Parts": [("Water Tap", "pcs"), ("Flexible Hose", "pcs"), ("PVC Pipe", "m"), ("PPR Pipe", "m"), ("Elbow", "pcs"), ("Tee", "pcs"), ("Coupling", "pcs"), ("Union", "pcs"), ("Valve", "pcs"), ("Ball Valve", "pcs"), ("Check Valve", "pcs"), ("Drain Pipe", "m"), ("Drain Trap", "pcs"), ("Gasket", "pcs"), ("O-Ring", "pcs"), ("Teflon Tape", "roll"), ("Silicone", "tube"), ("Pipe Glue", "tube")],
    "AC / HVAC Parts": [("AC Filter", "pcs"), ("Capacitor", "pcs"), ("Relay", "pcs"), ("Contactor", "pcs"), ("Fan Motor", "pcs"), ("Fan Blade", "pcs"), ("Thermostat", "pcs"), ("Drain Hose", "m"), ("Copper Pipe", "m"), ("Copper Fittings", "pcs"), ("Pipe Insulation", "m"), ("Refrigerant", "kg"), ("Exhaust Fan", "pcs"), ("Ventilation Fan", "pcs")],
    "Door & Window Parts": [("Door Lock", "pcs"), ("Door Handle", "pcs"), ("Door Hinge", "pcs"), ("Door Closer", "pcs"), ("Door Stopper", "pcs"), ("Door Bolt", "pcs"), ("Window Handle", "pcs"), ("Window Lock", "pcs"), ("Curtain Rod", "pcs"), ("Curtain Bracket", "pcs"), ("Curtain Hook", "pcs")],
    "Civil / Building Materials": [("Cement", "kg"), ("Sand", "m³"), ("Floor Tile", "pcs"), ("Wall Tile", "pcs"), ("Tile Adhesive", "kg"), ("Grout", "kg"), ("Wall Putty", "kg"), ("Paint", "L"), ("Primer", "L"), ("Paint Brush", "pcs"), ("Paint Roller", "pcs"), ("Paint Scraper", "pcs"), ("Sandpaper", "pcs"), ("Silicone Sealant", "tube")],
    "Welding / Metal Work": [("Welding Electrode", "kg"), ("Welding Wire", "kg"), ("Welding Rod", "kg"), ("Grinding Disc", "pcs"), ("Cutting Disc", "pcs"), ("Metal Sheet", "pcs"), ("Flat Bar", "m"), ("Angle Iron", "m"), ("Steel Pipe", "m"), ("Steel Plate", "pcs"), ("Welding Clamp", "pcs")],
    "Safety / PPE": [("Safety Helmet", "pcs"), ("Safety Shoes", "pair"), ("Safety Gloves", "pair"), ("Welding Gloves", "pair"), ("Safety Goggles", "pcs"), ("Face Shield", "pcs"), ("Ear Protection", "pcs"), ("Dust Mask", "pcs"), ("Reflective Vest", "pcs"), ("Safety Harness", "pcs")],
    "Maintenance Consumables": [("Cleaning Cloth", "pcs"), ("Cotton Waste", "kg"), ("Wire Brush", "pcs"), ("Brush", "pcs"), ("Sponge", "pcs"), ("Degreaser", "L"), ("Lubricating Oil", "L"), ("Grease", "kg"), ("Penetrating Oil", "L"), ("Rust Remover", "L"), ("Contact Cleaner", "L")],
    "General Maintenance Equipment": [("Ladder", "pcs"), ("Extension Ladder", "pcs"), ("Toolbox", "pcs"), ("Tool Bag", "pcs"), ("Wheelbarrow", "pcs"), ("Bucket", "pcs"), ("Flashlight", "pcs"), ("Work Light", "pcs"), ("Extension Cord", "pcs"), ("Maintenance Cart", "pcs")],
}

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
    name = db.Column(db.String(150), unique=True, nullable=False)
    department = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="Active")
    is_active = db.Column(db.Boolean, default=True)
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
    name = db.Column(db.String(150), unique=True, nullable=False)
    description = db.Column(db.Text)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    area_id = db.Column(db.Integer, db.ForeignKey("areas.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    department = db.relationship("Department", foreign_keys=[department_id])
    area = db.relationship("Area", foreign_keys=[area_id])

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
        if self.location_type == "Room" and self.room: return "Room " + str(self.room.room_number)
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
    root_cause = db.Column(db.Text)
    recommendation = db.Column(db.Text)
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
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    part = db.relationship("InventoryPart", foreign_keys=[part_id])

class InventoryPart(db.Model):
    __tablename__ = "inventory_parts"
    id = db.Column(db.Integer, primary_key=True)
    part_name = db.Column(db.String(150), unique=True, nullable=False)
    category = db.Column(db.String(120))
    description = db.Column(db.Text)
    quantity = db.Column(db.Float, default=0)
    minimum_stock = db.Column(db.Float, default=5)
    unit = db.Column(db.String(20), default="pcs")
    unit_cost = db.Column(db.Float, default=0)
    storage_location = db.Column(db.String(150))
    status = db.Column(db.String(20), default="Active")
    is_active = db.Column(db.Boolean, default=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"))
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    @property
    def is_low(self): return (self.quantity or 0) <= (self.minimum_stock or 0)
    @property
    def is_out(self): return (self.quantity or 0) <= 0

class InventoryStockHistory(db.Model):
    __tablename__ = "inventory_stock_history"
    id = db.Column(db.Integer, primary_key=True)
    part_id = db.Column(db.Integer, db.ForeignKey("inventory_parts.id"), nullable=False)
    action = db.Column(db.String(20), nullable=False)
    quantity = db.Column(db.Float, default=0)
    previous_qty = db.Column(db.Float, default=0)
    new_qty = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20))
    unit_cost = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    part = db.relationship("InventoryPart", foreign_keys=[part_id])
    user = db.relationship("User", foreign_keys=[user_id])
    work_order = db.relationship("WorkOrder", foreign_keys=[work_order_id])

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

def log_stock_history(part, action, quantity, prev_qty, new_qty, notes=None, work_order_id=None, unit_cost=None):
    try:
        db.session.add(InventoryStockHistory(
            part_id=part.id, action=action, quantity=quantity,
            previous_qty=prev_qty, new_qty=new_qty,
            unit=(part.unit if part else None),
            unit_cost=(unit_cost if unit_cost is not None else (part.unit_cost if part else 0)),
            notes=notes,
            user_id=current_user.id if current_user.is_authenticated else None,
            work_order_id=work_order_id,
        ))
    except Exception as e: print("Stock history error: " + str(e))

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
    if not user or not user.is_authenticated or not user.department_id: return None
    return DepartmentSignature.query.filter_by(department_id=user.department_id, is_active=True).first()

def validate_signature_for_user(user, signature_data):
    if not user or not user.is_authenticated: return False, "User not authenticated."
    if not user.department_id: return False, "Your account is not linked to a department. Contact admin."
    profile = get_user_signature_profile(user)
    if not profile: return False, "No authorized signature configured for your department. Contact admin."
    if not signature_data or not signature_data.strip(): return False, "Digital signature is required."
    if not signature_data.startswith("data:image/png;base64,"): return False, "Invalid signature format."
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
            bd_t = "DEFAULT TRUE" if pg else "DEFAULT 1"
            for col, sql in [
                ("department_id","ALTER TABLE maintenance_requests ADD COLUMN department_id INTEGER"),
                ("manager_id","ALTER TABLE maintenance_requests ADD COLUMN manager_id INTEGER"),
                ("completion_note","ALTER TABLE maintenance_requests ADD COLUMN completion_note TEXT"),
                ("completed_date","ALTER TABLE maintenance_requests ADD COLUMN completed_date " + dt),
                ("is_deleted","ALTER TABLE maintenance_requests ADD COLUMN is_deleted BOOLEAN " + bd),
                ("deleted_at","ALTER TABLE maintenance_requests ADD COLUMN deleted_at " + dt),
                ("deleted_by_id","ALTER TABLE maintenance_requests ADD COLUMN deleted_by_id INTEGER"),
                ("deletion_reason","ALTER TABLE maintenance_requests ADD COLUMN deletion_reason TEXT"),
                ("awaiting_hk_approval","ALTER TABLE maintenance_requests ADD COLUMN awaiting_hk_approval BOOLEAN " + bd),
                ("hk_approved_by_id","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_by_id INTEGER"),
                ("hk_approved_at","ALTER TABLE maintenance_requests ADD COLUMN hk_approved_at " + dt),
                ("hk_approval_status","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_status VARCHAR(20)"),
                ("hk_signature_data","ALTER TABLE maintenance_requests ADD COLUMN hk_signature_data TEXT"),
                ("hk_approval_notes","ALTER TABLE maintenance_requests ADD COLUMN hk_approval_notes TEXT"),
                ("signature_name","ALTER TABLE maintenance_requests ADD COLUMN signature_name VARCHAR(150)"),
                ("signature_status","ALTER TABLE maintenance_requests ADD COLUMN signature_status VARCHAR(30) DEFAULT 'SIGNED'"),
                ("signature_signed_at","ALTER TABLE maintenance_requests ADD COLUMN signature_signed_at " + dt),
                ("signature_data","ALTER TABLE maintenance_requests ADD COLUMN signature_data TEXT"),
                ("signature_department","ALTER TABLE maintenance_requests ADD COLUMN signature_department VARCHAR(80)"),
                ("signature_verified","ALTER TABLE maintenance_requests ADD COLUMN signature_verified BOOLEAN " + bd),
                ("signature_user_id","ALTER TABLE maintenance_requests ADD COLUMN signature_user_id INTEGER"),
            ]: add_column_if_missing("maintenance_requests", col, sql)
            add_column_if_missing("users","department_id","ALTER TABLE users ADD COLUMN department_id INTEGER")
            add_column_if_missing("notifications","work_order_id","ALTER TABLE notifications ADD COLUMN work_order_id INTEGER")
            add_column_if_missing("work_orders","completed_date","ALTER TABLE work_orders ADD COLUMN completed_date " + dt)
            add_column_if_missing("work_orders","verified_date","ALTER TABLE work_orders ADD COLUMN verified_date " + dt)
            add_column_if_missing("work_orders","root_cause","ALTER TABLE work_orders ADD COLUMN root_cause TEXT")
            add_column_if_missing("work_orders","recommendation","ALTER TABLE work_orders ADD COLUMN recommendation TEXT")
            add_column_if_missing("work_orders","completion_photo","ALTER TABLE work_orders ADD COLUMN completion_photo VARCHAR(255)")
            add_column_if_missing("audit_logs","ip_address","ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR(50)")
            for c, s in [("email","VARCHAR(120)"),("address","TEXT"),("tax_number","VARCHAR(60)"),("notes","TEXT"),
                         ("created_at",dt),("updated_at",dt)]:
                add_column_if_missing("suppliers", c, "ALTER TABLE suppliers ADD COLUMN " + c + " " + s)
            if add_column_if_missing("suppliers","is_active","ALTER TABLE suppliers ADD COLUMN is_active BOOLEAN " + bd):
                with db.engine.begin() as conn:
                    conn.execute(text("UPDATE suppliers SET is_active = CASE WHEN status = 'Active' THEN " + ("TRUE" if pg else "1") + " ELSE " + ("FALSE" if pg else "0") + " END"))
            for c, s in [("supplier_id","INTEGER"),("description","TEXT"),("is_active","BOOLEAN " + bd_t),
                         ("created_at",dt),("updated_at",dt)]:
                add_column_if_missing("inventory_parts", c, "ALTER TABLE inventory_parts ADD COLUMN " + c + " " + s)
            add_column_if_missing("work_order_parts","notes","ALTER TABLE work_order_parts ADD COLUMN notes TEXT")
            add_column_if_missing("working_items","department_id","ALTER TABLE working_items ADD COLUMN department_id INTEGER")
            add_column_if_missing("working_items","area_id","ALTER TABLE working_items ADD COLUMN area_id INTEGER")
            add_column_if_missing("working_items","is_active","ALTER TABLE working_items ADD COLUMN is_active BOOLEAN " + bd_t)
            add_column_if_missing("areas","is_active","ALTER TABLE areas ADD COLUMN is_active BOOLEAN " + bd_t)
            try:
                with db.engine.begin() as conn:
                    t = "TRUE" if pg else "1"
                    conn.execute(text("UPDATE areas SET is_active = " + t + " WHERE is_active IS NULL"))
                    conn.execute(text("UPDATE working_items SET is_active = " + t + " WHERE is_active IS NULL"))
                    conn.execute(text("UPDATE inventory_parts SET is_active = " + t + " WHERE is_active IS NULL"))
            except Exception: pass
            print("✅ Schema OK — no existing rows were modified or deleted")
        except Exception as e: print("⚠️ Schema error: " + str(e))

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
                   ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                   ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                   ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                   ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
        else:
            nav = [('<i class="fas fa-tachometer-alt"></i> Dashboard', url_for('dashboard')),
                   ('<i class="fas fa-fire-extinguisher"></i> Central Maintenance', url_for('central_maintenance')),
                   ('<i class="fas fa-plus-circle"></i> New Request', url_for('request_create')),
                   ('<i class="fas fa-clipboard-list"></i> Requests', url_for('requests_list')),
                   ('<i class="fas fa-tasks"></i> Work Orders', url_for('workorders_list')),
                   ('<i class="fas fa-file-alt"></i> Detailed Report', url_for('detailed_report')),
                   ('<i class="fas fa-door-open"></i> Rooms', url_for('rooms_list')),
                   ('<i class="fas fa-map-marked-alt"></i> Areas', url_for('areas_list')),
                   ('<i class="fas fa-th-list"></i> Maintenance Items', url_for('items_list')),
                   ('<i class="fas fa-boxes"></i> Inventory', url_for('inventory_list')),
                   ('<i class="fas fa-truck"></i> Suppliers', url_for('suppliers_list')),
                   ('<i class="fas fa-users"></i> Employees', url_for('employees_list'))]
        if r == "ADMIN":
            nav += [('<i class="fas fa-user-cog"></i> Users', url_for('admin_users')),
                    ('<i class="fas fa-history"></i> Audit Log', url_for('audit_logs')),
                    ('<i class="fas fa-archive"></i> Archived', url_for('deleted_requests')),
                    ('<i class="fas fa-database"></i> Backup', url_for('backup_page')),
                    ('<i class="fas fa-chart-line"></i> Management Reports', url_for('management_reports'))]
        elif r == "MANAGER":
            nav += [('<i class="fas fa-chart-line"></i> Management Reports', url_for('management_reports'))]
        if r not in ("DEPARTMENT", "EMPLOYEE"):
            nav += [('<i class="fas fa-chart-bar"></i> Reports', url_for('reports')),
                    ('<i class="fas fa-bell"></i> Notifications', url_for('notifications')),
                    ('<i class="fas fa-user-circle"></i> Profile', url_for('profile')),
                    ('<i class="fas fa-sign-out-alt"></i> Logout', url_for('logout'))]
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
            sound_toggle = ('<div class="sound-control">'
                '<button class="btn-icon" onclick="roriEnableAlerts()" title="Enable Alerts"><i class="fas fa-bell"></i></button>'
                '<button class="btn-icon" onclick="roriToggleSound(true)" title="Sound ON"><i class="fas fa-volume-up"></i></button>'
                '<button class="btn-icon" onclick="roriToggleSound(false)" title="Sound OFF"><i class="fas fa-volume-mute"></i></button>'
                '<button class="btn-icon" onclick="roriTestSound()" title="Test Sound"><i class="fas fa-play"></i></button>'
                '</div>')
    flash_html = "".join('<div class="alert alert-' + str(c) + ' alert-dismissible fade show">' + str(m) + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>' for c, m in get_flashed_messages(with_categories=True))
    if current_user.is_authenticated:
        _display_name = current_user.full_name or current_user.username or "User"
        _avatar_letter = _display_name[0].upper() if _display_name else "U"
        _display_role = current_user.role or ""
        user_profile_html = ('<div class="user-profile"><div class="user-avatar">' + _avatar_letter + '</div><div class="user-info"><div class="user-name">' + str(_display_name) + '</div><div class="user-role">' + str(_display_role) + '</div></div></div>')
    else:
        user_profile_html = ''

    return """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>""" + str(title) + """ | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{--rori-gold:#C5A059;--rori-gold-dark:#A8873F;--bg-primary:#0B0B12;--bg-secondary:#11111B;--bg-card:#151522;--bg-card-hover:#1B1B2A;--border-color:rgba(197,160,89,0.20);--text-primary:#FFFFFF;--text-secondary:#A7A7B3;--success:#22C55E;--warning:#F59E0B;--danger:#EF4444;--info:#38BDF8}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Plus Jakarta Sans',sans-serif;background:var(--bg-primary);color:var(--text-primary);min-height:100vh;padding-top:70px}
.header{position:fixed;top:0;left:0;right:0;height:70px;background:var(--bg-secondary);border-bottom:1px solid var(--border-color);display:flex;align-items:center;justify-content:space-between;padding:0 2rem;z-index:1000;box-shadow:0 4px 20px rgba(0,0,0,0.3)}
.header-left{display:flex;align-items:center;gap:1rem}
.logo{font-size:1.5rem;font-weight:800;color:var(--rori-gold);text-decoration:none;display:flex;align-items:center;gap:0.5rem}
.logo i{font-size:1.8rem}
.header-right{display:flex;align-items:center;gap:1.5rem}
.header-icon{color:var(--text-secondary);font-size:1.2rem;text-decoration:none;position:relative;transition:color 0.3s}
.header-icon:hover{color:var(--rori-gold)}
.notif-badge{position:absolute;top:-8px;right:-8px;background:var(--danger);color:white;font-size:0.7rem;font-weight:700;padding:2px 6px;border-radius:10px;min-width:18px;text-align:center}
.user-profile{display:flex;align-items:center;gap:0.75rem;cursor:pointer}
.user-avatar{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--rori-gold),var(--rori-gold-dark));display:flex;align-items:center;justify-content:center;font-weight:700;color:white}
.user-info{display:flex;flex-direction:column}
.user-name{font-weight:600;font-size:0.9rem;color:var(--text-primary)}
.user-role{font-size:0.75rem;color:var(--text-secondary)}
.sound-control{display:flex;gap:0.5rem}
.btn-icon{background:var(--bg-card);border:1px solid var(--border-color);color:var(--text-secondary);width:36px;height:36px;border-radius:8px;cursor:pointer;transition:all 0.3s;display:inline-flex;align-items:center;justify-content:center}
.btn-icon:hover{background:var(--bg-card-hover);color:var(--rori-gold);border-color:var(--rori-gold)}
.sidebar{position:fixed;left:0;top:70px;bottom:0;width:260px;background:var(--bg-secondary);border-right:1px solid var(--border-color);padding:1.5rem 0;overflow-y:auto;z-index:999;transition:transform 0.3s}
.sidebar-nav{list-style:none}
.sidebar-nav li{margin:0.25rem 0}
.sidebar-nav .nav-link{display:flex;align-items:center;gap:0.75rem;padding:0.85rem 1.5rem;color:var(--text-secondary);text-decoration:none;font-size:0.9rem;font-weight:500;transition:all 0.3s;border-left:3px solid transparent}
.sidebar-nav .nav-link:hover{background:var(--bg-card);color:var(--text-primary);border-left-color:var(--rori-gold)}
.sidebar-nav .nav-link.active{background:rgba(197,160,89,0.1);color:var(--rori-gold);border-left-color:var(--rori-gold)}
.sidebar-nav .nav-link i{width:20px;text-align:center}
.main-content{margin-left:260px;padding:2rem;min-height:calc(100vh - 70px);padding-bottom:5rem}
.page-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:2rem;flex-wrap:wrap;gap:1rem}
.page-title h1{font-size:1.8rem;font-weight:800;color:var(--text-primary);margin-bottom:0.25rem}
.page-title h1 span{color:var(--rori-gold)}
.page-title p{font-size:0.9rem;color:var(--text-secondary)}
.btn-primary{background:linear-gradient(135deg,var(--rori-gold),var(--rori-gold-dark));color:white;border:none;padding:0.75rem 1.5rem;border-radius:10px;font-weight:600;font-size:0.9rem;cursor:pointer;transition:all 0.3s;text-decoration:none;display:inline-flex;align-items:center;gap:0.5rem}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(197,160,89,0.3)}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.5rem;margin-bottom:2rem}
.kpi-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.5rem;transition:all 0.3s;position:relative;overflow:hidden}
.kpi-card:hover{background:var(--bg-card-hover);border-color:var(--rori-gold);transform:translateY(-4px);box-shadow:0 12px 30px rgba(0,0,0,0.4)}
.kpi-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--rori-gold),transparent)}
.kpi-icon{font-size:2rem;color:var(--rori-gold);margin-bottom:1rem}
.kpi-value{font-size:2.5rem;font-weight:800;color:var(--text-primary);margin-bottom:0.5rem}
.kpi-label{font-size:0.85rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:0.5px;font-weight:600}
.card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.5rem;margin-bottom:1.5rem}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem}
.card-title{font-size:1.1rem;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:0.5rem}
.card-title i{color:var(--rori-gold)}
.table{--bs-table-color:var(--text-primary)!important;--bs-table-bg:transparent!important;--bs-table-accent-bg:transparent!important;--bs-table-striped-color:var(--text-primary)!important;--bs-table-striped-bg:rgba(197,160,89,0.04)!important;--bs-table-active-color:var(--text-primary)!important;--bs-table-active-bg:rgba(197,160,89,0.08)!important;--bs-table-hover-color:var(--text-primary)!important;--bs-table-hover-bg:rgba(197,160,89,0.10)!important;width:100%;margin-bottom:0;color:var(--text-primary)!important;vertical-align:middle;border-color:var(--border-color)!important;background:transparent!important;border-collapse:collapse}
.table>:not(caption)>*>*{padding:1rem;background-color:transparent!important;box-shadow:none!important;color:var(--text-primary)!important;border-color:var(--border-color)!important}
.table>thead{vertical-align:bottom;background:transparent!important}
.table>thead th{background:var(--bg-secondary)!important;color:var(--rori-gold)!important;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.5px;padding:1rem;text-align:left;border-bottom:2px solid var(--border-color)!important;font-weight:700}
.table>tbody{vertical-align:inherit;background:transparent!important}
.table>tbody td{padding:1rem;border-bottom:1px solid var(--border-color)!important;color:var(--text-primary)!important;font-size:0.9rem;background-color:transparent!important}
.table>tbody tr{background:transparent!important}
.table>tbody tr:hover>*{background-color:rgba(197,160,89,0.10)!important;color:var(--text-primary)!important}
.table-hover>tbody>tr:hover>*{color:var(--text-primary)!important;background-color:rgba(197,160,89,0.10)!important}
.table-responsive{background:transparent;border-radius:12px;overflow-x:auto;overflow-y:hidden}
.table a{color:var(--rori-gold)!important;text-decoration:none;font-weight:600}
.table a:hover{text-decoration:underline}
.badge{padding:0.4rem 0.8rem;border-radius:20px;font-size:0.75rem;font-weight:600;display:inline-block}
.badge-success{background:rgba(34,197,94,0.2);color:var(--success)}
.badge-warning{background:rgba(245,158,11,0.2);color:var(--warning)}
.badge-danger{background:rgba(239,68,68,0.2);color:var(--danger)}
.badge-info{background:rgba(56,189,248,0.2);color:var(--info)}
.badge-secondary{background:rgba(167,167,179,0.2);color:var(--text-secondary)}
.badge-primary{background:rgba(56,189,248,0.2);color:var(--info)}
.alert{background:var(--bg-card);border:1px solid var(--border-color);border-radius:12px;padding:1rem 1.5rem;margin-bottom:1rem;color:var(--text-primary)}
.alert-success{border-left:4px solid var(--success)}
.alert-danger{border-left:4px solid var(--danger)}
.alert-warning{border-left:4px solid var(--warning)}
.alert-info{border-left:4px solid var(--info)}
.form-control,.form-select{background:var(--bg-card);border:1px solid var(--border-color);border-radius:10px;color:var(--text-primary);padding:0.75rem 1rem;font-size:0.9rem}
.form-control:focus,.form-select:focus{background:var(--bg-card-hover);border-color:var(--rori-gold);box-shadow:0 0 0 3px rgba(197,160,89,0.15);color:var(--text-primary)}
.form-control::placeholder{color:var(--text-secondary);opacity:.7}
.form-label{color:var(--text-secondary);font-weight:500;font-size:0.85rem;margin-bottom:0.5rem}
select.form-select option{background:var(--bg-card);color:var(--text-primary)}
.list-group-item{background:var(--bg-card)!important;color:var(--text-primary)!important;border-color:var(--border-color)!important}
.menu-toggle{display:none;background:none;border:none;color:var(--text-primary);font-size:1.5rem;cursor:pointer}
.rori-footer{margin-left:0;margin-top:3rem;padding:1.5rem 2rem;text-align:center;font-size:.8rem;color:var(--text-secondary);border-top:1px solid var(--border-color)}
.rori-footer .dev-name{color:var(--rori-gold);font-weight:700;letter-spacing:.3px}
@media(max-width:1024px){.sidebar{transform:translateX(-100%)}.sidebar.active{transform:translateX(0)}.main-content{margin-left:0}.menu-toggle{display:block}}
@media(max-width:768px){.header{padding:0 1rem}.user-info{display:none}.main-content{padding:1rem;padding-bottom:4rem}.kpi-grid{grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem}.kpi-value{font-size:2rem}.page-header{flex-direction:column;align-items:flex-start}.table>:not(caption)>*>*{padding:.7rem .6rem;font-size:.82rem}.table>thead th{font-size:.68rem;padding:.7rem .6rem}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.5}}
.pulse{animation:pulse 2s infinite}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-track{background:var(--bg-secondary)}
::-webkit-scrollbar-thumb{background:var(--rori-gold);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:var(--rori-gold-dark)}
.rpro-section{margin-bottom:1.5rem}
.rpro-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.25rem 1.5rem;margin-bottom:1rem}
.rpro-card .table{background:transparent!important}
.rpro-card .table>:not(caption)>*>*{background:transparent!important}
.rpro-card-title{font-size:.78rem;font-weight:700;color:var(--rori-gold);text-transform:uppercase;letter-spacing:.8px;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
.rpro-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem}
.rpro-kv-label{font-size:.7rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px;font-weight:600;margin-bottom:.25rem}
.rpro-kv-value{font-size:.95rem;color:var(--text-primary);font-weight:600;word-break:break-word}
.rpro-kv-value.mono{font-family:'Courier New',monospace;color:var(--rori-gold)}
.rpro-timeline{position:relative;padding-left:2rem}
.rpro-timeline::before{content:'';position:absolute;left:.55rem;top:.25rem;bottom:.25rem;width:2px;background:linear-gradient(180deg,var(--rori-gold),var(--border-color))}
.rpro-timeline-item{position:relative;padding-bottom:1.25rem}
.rpro-timeline-item:last-child{padding-bottom:0}
.rpro-timeline-dot{position:absolute;left:-1.75rem;top:.35rem;width:14px;height:14px;border-radius:50%;background:var(--rori-gold);border:3px solid var(--bg-card);box-shadow:0 0 0 2px var(--rori-gold)}
.rpro-timeline-status{font-size:.85rem;font-weight:700;color:var(--rori-gold);text-transform:uppercase;letter-spacing:.4px}
.rpro-timeline-meta{font-size:.75rem;color:var(--text-secondary);margin-top:.15rem}
.rpro-timeline-note{font-size:.85rem;color:var(--text-primary);margin-top:.35rem;padding:.5rem .75rem;background:var(--bg-secondary);border-radius:8px;border-left:2px solid var(--rori-gold)}
.rpro-sig-box{background:#fff;padding:1rem;border-radius:12px;border:2px solid var(--success);display:inline-block;max-width:100%}
.rpro-sig-box img{max-width:280px;max-height:120px;display:block}
.rpro-room-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:.75rem}
.rpro-room-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:14px;padding:1rem;transition:transform .15s,border-color .15s}
.rpro-room-card:hover{transform:translateY(-3px);border-color:var(--rori-gold)}
.rpro-room-num{font-size:1.5rem;font-weight:800;color:var(--rori-gold);line-height:1}
.rpro-room-floor{font-size:.7rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px;margin-top:.15rem}
.rpro-room-stats{display:flex;gap:.5rem;margin-top:.65rem;flex-wrap:wrap}
.rpro-chip{font-size:.68rem;padding:.2rem .55rem;border-radius:20px;font-weight:600;background:var(--bg-secondary);border:1px solid var(--border-color);color:var(--text-secondary)}
.rpro-chip.gold{background:rgba(197,160,89,.15);color:var(--rori-gold);border-color:rgba(197,160,89,.4)}
.rpro-chip.green{background:rgba(34,197,94,.15);color:var(--success);border-color:rgba(34,197,94,.4)}
.rpro-chip.orange{background:rgba(245,158,11,.15);color:var(--warning);border-color:rgba(245,158,11,.4)}
.rpro-chip.red{background:rgba(239,68,68,.15);color:var(--danger);border-color:rgba(239,68,68,.4)}
.rpro-chip.blue{background:rgba(56,189,248,.15);color:var(--info);border-color:rgba(56,189,248,.4)}
.rpro-toolbar{display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;background:var(--bg-card);border:1px solid var(--border-color);border-radius:14px;padding:1rem;margin-bottom:1.5rem}
.rpro-toolbar .form-control,.rpro-toolbar .form-select{min-width:140px;flex:1}
.area-toolbar{display:flex;gap:.75rem;flex-wrap:wrap;align-items:center;margin-bottom:1.5rem;background:var(--bg-card);border:1px solid var(--border-color);border-radius:14px;padding:1rem}
.area-toolbar .form-control,.area-toolbar .form-select{min-width:160px;flex:1}
.area-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1.25rem}
.area-card{position:relative;background:var(--bg-card);border:1px solid var(--border-color);border-radius:18px;padding:1.25rem;transition:transform .18s,border-color .18s,box-shadow .18s;overflow:hidden;display:flex;flex-direction:column;gap:.75rem}
.area-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--rori-gold),transparent)}
.area-card:hover{transform:translateY(-4px);border-color:var(--rori-gold);box-shadow:0 14px 32px rgba(0,0,0,.45)}
.area-card.inactive{opacity:.55;filter:grayscale(.6)}
.area-new-badge{position:absolute;top:12px;right:12px;background:var(--danger);color:#fff;font-size:.68rem;font-weight:700;padding:.25rem .55rem;border-radius:12px;letter-spacing:.4px}
.area-inactive-badge{position:absolute;top:12px;right:12px;background:#6b7280;color:#fff;font-size:.68rem;font-weight:700;padding:.25rem .55rem;border-radius:12px;letter-spacing:.4px}
.area-card-header{padding-right:5rem}
.area-card-name{font-size:1.15rem;font-weight:800;color:var(--text-primary);letter-spacing:.3px;margin-bottom:.15rem}
.area-card-dept{font-size:.78rem;color:var(--rori-gold);font-weight:600;display:flex;align-items:center;gap:.4rem;text-transform:uppercase;letter-spacing:.5px}
.area-stat-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:12px;padding:.65rem}
.area-stat{text-align:center}
.area-stat-val{font-size:1.2rem;font-weight:800;color:var(--text-primary);line-height:1.1}
.area-stat-lbl{font-size:.62rem;color:var(--text-secondary);text-transform:uppercase;letter-spacing:.5px;margin-top:.15rem}
.area-status-row{display:flex;align-items:center;gap:.45rem;font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
.area-last-row{font-size:.72rem;color:var(--text-secondary);display:flex;align-items:center;gap:.35rem}
.area-last-row i{color:var(--rori-gold)}
.area-card-actions{display:flex;gap:.5rem;margin-top:auto;padding-top:.35rem;flex-wrap:wrap}
.area-card-actions .btn-primary{font-size:.78rem;padding:.5rem .8rem}
.empty-state{grid-column:1/-1;text-align:center;color:var(--text-secondary);padding:3rem 1rem;background:var(--bg-card);border:1px dashed var(--border-color);border-radius:16px}
.empty-state i{font-size:2rem;color:var(--rori-gold);opacity:.5;display:block;margin-bottom:.75rem}
.kpi-mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:1.5rem}
.kpi-mini-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:16px;padding:1.1rem 1.25rem;position:relative;overflow:hidden}
.kpi-mini-card::before{content:'';position:absolute;top:0;left:0;bottom:0;width:3px;background:var(--rori-gold)}
.kpi-mini-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--text-secondary);font-weight:600}
.kpi-mini-value{font-size:1.75rem;font-weight:800;color:var(--text-primary);margin-top:.35rem}
#roriAlertBanner{position:fixed;top:80px;right:20px;z-index:9999;background:linear-gradient(135deg,#C5A059,#A8873F);color:#0B0B12;border-radius:14px;padding:1rem 1.25rem;box-shadow:0 14px 40px rgba(0,0,0,.5);display:none;max-width:340px;font-weight:600;font-size:.88rem}
#roriAlertBanner.show{display:block;animation:roriSlideIn .3s ease-out}
#roriAlertBanner .ra-title{font-weight:800;font-size:.95rem;margin-bottom:.35rem}
#roriAlertBanner .ra-btn{margin-top:.6rem;background:#0B0B12;color:#C5A059;border:none;padding:.45rem 1rem;border-radius:8px;font-weight:700;font-size:.8rem;cursor:pointer}
@keyframes roriSlideIn{from{opacity:0;transform:translateX(40px)}to{opacity:1;transform:translateX(0)}}
@media(max-width:640px){.area-grid{grid-template-columns:1fr}.area-stat-grid{grid-template-columns:repeat(2,1fr)}.area-card-header{padding-right:0}}
.report-doc{background:#ffffff;color:#111111;border-radius:16px;padding:2rem;margin-bottom:1.5rem;box-shadow:0 20px 60px rgba(0,0,0,0.5)}
.report-head{border-bottom:3px double #C5A059;padding-bottom:1rem;margin-bottom:1.5rem;text-align:center}
.report-head .brand{font-size:1.9rem;font-weight:900;letter-spacing:2px;color:#8B6F26}
.report-head .dept{font-size:.95rem;letter-spacing:3px;color:#444;text-transform:uppercase;margin-top:.35rem;font-weight:700}
.report-head .doctype{font-size:1.05rem;font-weight:800;color:#0B0B12;margin-top:.6rem;letter-spacing:1px;text-transform:uppercase}
.report-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:.5rem;background:#f7f7f7;border:1px solid #ddd;border-radius:10px;padding:1rem;margin-bottom:1rem;font-size:.82rem;color:#222}
.report-meta b{color:#8B6F26}
.report-section{margin-bottom:1.25rem;page-break-inside:avoid}
.report-section-title{font-size:.8rem;text-transform:uppercase;letter-spacing:1.2px;font-weight:800;color:#0B0B12;background:linear-gradient(90deg,#F5E8C6,#FBF4DC);border-left:4px solid #C5A059;padding:.55rem .85rem;border-radius:6px;margin-bottom:.75rem}
.report-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.6rem 1.25rem}
.report-kv .row{display:flex;flex-direction:column;border-bottom:1px dotted #ddd;padding-bottom:.35rem}
.report-kv .lbl{font-size:.7rem;letter-spacing:.5px;color:#666;text-transform:uppercase;font-weight:700}
.report-kv .val{font-size:.9rem;color:#111;font-weight:600;word-break:break-word;white-space:pre-wrap}
.report-kv .val.mono{font-family:'Courier New',monospace;color:#8B6F26}
.report-longtext{background:#fafafa;border-left:3px solid #C5A059;border-radius:8px;padding:.85rem 1rem;font-size:.9rem;color:#111;line-height:1.55;white-space:pre-wrap;word-break:break-word}
.report-table{width:100%;border-collapse:collapse;font-size:.82rem}
.report-table th{background:#FBF4DC;color:#0B0B12;text-align:left;padding:.55rem .65rem;border:1px solid #e4d5a8;font-size:.72rem;text-transform:uppercase;letter-spacing:.5px}
.report-table td{padding:.55rem .65rem;border:1px solid #e2e2e2;color:#111;vertical-align:top;white-space:pre-wrap;word-break:break-word}
.report-stamp{display:inline-block;padding:.25rem .7rem;border-radius:20px;font-weight:800;font-size:.72rem;letter-spacing:.6px;text-transform:uppercase}
.stamp-Pending{background:#fef3c7;color:#92400e}
.stamp-Approved{background:#dbeafe;color:#1e40af}
.stamp-Assigned{background:#ede9fe;color:#5b21b6}
.stamp-InProgress{background:#ede9fe;color:#5b21b6}
.stamp-Completed{background:#dcfce7;color:#166534}
.stamp-Verified{background:#d1fae5;color:#065f46}
.stamp-Closed{background:#e5e7eb;color:#374151}
.stamp-Rejected{background:#fee2e2;color:#991b1b}
.report-sig{border:2px solid #16a34a;border-radius:10px;padding:.75rem;background:#f0fdf4;display:inline-block;max-width:100%}
.report-sig img{max-width:260px;max-height:110px;display:block}
.report-photo{border:2px solid #C5A059;border-radius:10px;padding:.5rem;background:#fafafa;display:inline-block;max-width:100%}
.report-photo img{max-width:340px;max-height:240px;display:block;border-radius:6px}
.report-footer{margin-top:1.5rem;padding-top:.75rem;border-top:1px solid #ddd;font-size:.72rem;color:#666;text-align:center}
@media print{
    .header,.sidebar,.no-print,.rori-footer{display:none!important}
    body{background:#fff!important;color:#000!important;padding-top:0!important}
    .main-content{margin-left:0!important;padding:0!important}
    .card,.report-doc{box-shadow:none!important;border:1px solid #ccc!important;background:#fff!important;color:#000!important;padding:1rem!important}
    .report-section{page-break-inside:avoid}
    .report-head .brand,.report-head .dept,.report-head .doctype{color:#000!important}
    .report-table th{background:#eee!important;color:#000!important}
    .report-table td,.report-table th{border:1px solid #666!important}
}
</style></head><body>
<header class="header">
    <div class="header-left">
        <button class="menu-toggle" onclick="toggleSidebar()"><i class="fas fa-bars"></i></button>
        <a href="/" class="logo"><i class="fas fa-hotel"></i><span>RORI HOTEL</span></a>
    </div>
    <div class="header-right">""" + sound_toggle + bell_html + user_profile_html + """</div>
</header>
<aside class="sidebar" id="sidebar"><ul class="sidebar-nav">""" + nav_html + """</ul></aside>
<main class="main-content">""" + flash_html + content + """
    <div class="rori-footer">
        <div>Rori Hotel — Maintenance Management System</div>
        <div style="margin-top:.35rem;">Developer: <span class="dev-name">Edom Adinew</span></div>
    </div>
</main>
<div id="roriAlertBanner"><div class="ra-title"></div><div class="ra-body"></div></div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
function toggleSidebar(){document.getElementById('sidebar').classList.toggle('active');}
let roriAudioCtx=null;
let roriSoundEnabled=localStorage.getItem('rori_sound_enabled')==='true';
let roriAlertedRequests=JSON.parse(sessionStorage.getItem('rori_alerted_requests')||'[]');
let roriBrowserNotif=(typeof Notification!=='undefined'&&Notification.permission==='granted');
function roriInitAudio(){if(!roriAudioCtx){try{roriAudioCtx=new(window.AudioContext||window.webkitAudioContext)();}catch(e){return false;}}if(roriAudioCtx.state==='suspended')roriAudioCtx.resume();return true;}
function roriPlayAlert(priority){if(!roriSoundEnabled||!roriInitAudio())return;try{const now=roriAudioCtx.currentTime;const play=(freq,start,dur)=>{const osc=roriAudioCtx.createOscillator();const gain=roriAudioCtx.createGain();osc.connect(gain);gain.connect(roriAudioCtx.destination);osc.frequency.value=freq;osc.type='sine';gain.gain.setValueAtTime(0.0001,now+start);gain.gain.exponentialRampToValueAtTime(0.25,now+start+0.02);gain.gain.exponentialRampToValueAtTime(0.001,now+start+dur);osc.start(now+start);osc.stop(now+start+dur);};if(priority==='URGENT'){play(880,0,0.18);play(880,0.22,0.18);play(880,0.44,0.18);play(1200,0.7,0.35);}else if(priority==='HIGH'){play(660,0,0.2);play(660,0.28,0.2);play(880,0.56,0.3);}else{play(520,0,0.25);play(660,0.3,0.35);}}catch(e){console.warn('Audio alert failed',e);}}
function roriShowBanner(title,body){const b=document.getElementById('roriAlertBanner');if(!b)return;b.querySelector('.ra-title').textContent=title;b.querySelector('.ra-body').textContent=body;b.classList.add('show');clearTimeout(window._roriBannerTimer);window._roriBannerTimer=setTimeout(()=>b.classList.remove('show'),8000);}
window.roriEnableAlerts=function(){roriInitAudio();roriSoundEnabled=true;localStorage.setItem('rori_sound_enabled','true');if(typeof Notification!=='undefined'&&Notification.permission!=='granted'){Notification.requestPermission().then(p=>{roriBrowserNotif=(p==='granted');if(roriBrowserNotif)roriShowBanner('✓ Alerts Enabled','Sound and browser notifications are now active.');else roriShowBanner('✓ Sound Enabled','Browser notifications blocked — sound only.');});}else{roriBrowserNotif=(typeof Notification!=='undefined'&&Notification.permission==='granted');roriShowBanner('✓ Alerts Enabled','You will now hear a sound when new requests arrive.');}roriPlayAlert('HIGH');};
window.roriToggleSound=function(enable){roriSoundEnabled=!!enable;localStorage.setItem('rori_sound_enabled',roriSoundEnabled?'true':'false');if(enable)roriInitAudio();roriShowBanner(enable?'🔊 Sound ON':'🔇 Sound OFF','Preference saved.');};
window.roriTestSound=function(){roriSoundEnabled=true;localStorage.setItem('rori_sound_enabled','true');roriInitAudio();roriPlayAlert('URGENT');roriShowBanner('🔔 Test Alert','This is what a new request sounds like.');};
function roriNotify(title,body,priority){roriShowBanner(title,body);if(roriBrowserNotif){try{const n=new Notification(title,{body:body,icon:'/logo.png',tag:'rori-'+Date.now()});setTimeout(()=>n.close(),7000);}catch(e){}}}
function pollNotifications(){fetch('/api/notifications/unread',{credentials:'same-origin',cache:'no-store'}).then(r=>r.ok?r.json():null).then(d=>{if(!d||!d.latest_id)return;if(roriAlertedRequests.includes(d.latest_id))return;const t=(d.latest_title||'').toUpperCase();if(!t.includes('REQUEST'))return;let prio='MEDIUM';if(t.includes('URGENT'))prio='URGENT';else if(t.includes('HIGH'))prio='HIGH';roriPlayAlert(prio);roriNotify(d.latest_title||'New Maintenance Request',d.latest_message||'A new request has been submitted.',prio);roriAlertedRequests.push(d.latest_id);sessionStorage.setItem('rori_alerted_requests',JSON.stringify(roriAlertedRequests));const badge=document.querySelector('.notif-badge');if(badge){badge.classList.add('pulse');setTimeout(()=>badge.classList.remove('pulse'),2500);}}).catch(()=>{});}
if(document.querySelector('.header-icon')){pollNotifications();setInterval(pollNotifications,10000);}
</script>
</body></html>"""

# ══════════════════════════════════════════ SEED DATA
def seed_data():
    core_depts = ["Housekeeping","Front Office","Engineering","Food & Beverage","Kitchen","Finance","HR","Security","IT","Sales & Marketing","Administration","Maintenance","Other","SPA","GM","Marketing"]
    for name in core_depts:
        if not Department.query.filter_by(name=name).first(): db.session.add(Department(name=name))
    db.session.commit()
    laundry_dept = Department.query.filter_by(name="Laundry").first()
    if laundry_dept:
        has_users = User.query.filter_by(department_id=laundry_dept.id).count()
        has_requests = MaintenanceRequest.query.filter_by(department_id=laundry_dept.id).count()
        if not has_users and not has_requests:
            WorkingItem.query.filter_by(department_id=laundry_dept.id).update({"department_id": None})
            db.session.delete(laundry_dept); db.session.commit()
    for f in [2,3,4,5]:
        if not Floor.query.filter_by(floor_number=f).first(): db.session.add(Floor(floor_number=f))
    if Room.query.count() == 0:
        for floor, nums in RORI_ROOM_STRUCTURE.items():
            for num in nums: db.session.add(Room(floor=floor, room_number=str(num), status="Available"))
    legacy_areas = [("Buduchalley","F&B"),("Sillanto","Unknown"),("Fura","Unknown"),("Executive","Unknown"),("Mitima","Unknown"),("Odako","Unknown"),("Gudumale","Unknown"),("Bubble","Unknown"),("Bubbles","Unknown"),("Fura Corridor","Unknown"),("Executive Meeting Room","Unknown"),("Counter","Unknown")]
    for n, d in legacy_areas:
        if not Area.query.filter_by(name=n).first(): db.session.add(Area(name=n, department=d, is_active=True))
    for n in HOTEL_AREAS:
        if not Area.query.filter_by(name=n).first(): db.session.add(Area(name=n, department=None, is_active=True))
    if not Area.query.filter_by(name=LAUNDRY_AREA_NAME).first():
        db.session.add(Area(name=LAUNDRY_AREA_NAME, department="Housekeeping", description="Laundry operations area (Housekeeping department)", is_active=True))
    else:
        la = Area.query.filter_by(name=LAUNDRY_AREA_NAME).first()
        if not la.department: la.department = "Housekeeping"
    db.session.commit()
    for c in ["Electrical","Plumbing","HVAC","Painting","Carpentry","Civil","Safety","General","Other"]:
        if not Category.query.filter_by(name=c).first(): db.session.add(Category(name=c))
    legacy_items = ["Light","Switch","Window","Door Key","Door Lock","Paint","Mirror","Drainage Cover","Frame","Background Frame","Spot Light","Plumbing","AC","Electrical","Other"]
    for i in legacy_items:
        if not WorkingItem.query.filter_by(name=i).first(): db.session.add(WorkingItem(name=i))
    db.session.commit()
    for dept_name, items in NEW_ITEMS_BY_DEPT.items():
        dept = Department.query.filter_by(name=dept_name).first()
        if not dept: continue
        for item_name in items:
            existing = WorkingItem.query.filter_by(name=item_name).first()
            if not existing: db.session.add(WorkingItem(name=item_name, department_id=dept.id, is_active=True))
            elif existing.department_id is None: existing.department_id = dept.id
    db.session.commit()
    hk_dept = Department.query.filter_by(name="Housekeeping").first()
    laundry_area = Area.query.filter_by(name=LAUNDRY_AREA_NAME).first()
    if hk_dept and laundry_area:
        for item_name in LAUNDRY_ITEMS:
            existing = WorkingItem.query.filter_by(name=item_name).first()
            if not existing: db.session.add(WorkingItem(name=item_name, department_id=hk_dept.id, area_id=laundry_area.id, is_active=True))
            else:
                existing.department_id = hk_dept.id; existing.area_id = laundry_area.id
        db.session.commit()
    # Housekeeping bilingual categories & items
    if hk_dept:
        for cat_name in HOUSEKEEPING_CATEGORIES.keys():
            if not Category.query.filter_by(name=cat_name).first():
                db.session.add(Category(name=cat_name, description="Housekeeping category"))
        db.session.commit()
        for _cat, item_name in HOUSEKEEPING_ITEMS_FLAT:
            existing = WorkingItem.query.filter_by(name=item_name).first()
            if not existing:
                db.session.add(WorkingItem(name=item_name, department_id=hk_dept.id, is_active=True))
            elif existing.department_id is None:
                existing.department_id = hk_dept.id
        db.session.commit()
    inv_added = 0
    for cat_name, items in INVENTORY_ITEMS_BY_CATEGORY.items():
        for item_name, default_unit in items:
            existing = InventoryPart.query.filter(func.lower(InventoryPart.part_name) == item_name.lower()).first()
            if not existing:
                p = InventoryPart(part_name=item_name, category=cat_name, description="", quantity=0, minimum_stock=5, unit=default_unit, unit_cost=0, storage_location="Engineering Store", status="Active", is_active=True)
                db.session.add(p); inv_added += 1
            elif not existing.category: existing.category = cat_name
    db.session.commit()
    for eid, n, t in [(1,"Mechanic 1","General Mechanic"),(2,"Mechanic 2","General Mechanic"),(3,"Mechanic 3","General Mechanic"),(4,"Supervisor 1","Supervisor"),(5,"Amir Awel","Manager")]:
        if not db.session.get(Employee, eid): db.session.add(Employee(id=eid, name=n, job_title=t, department="Engineering"))
    if Supplier.query.count() == 0:
        for s in ["ABC Maintenance Supply","Hawassa Engineering Supply","Rori Hotel Approved Supplier"]:
            db.session.add(Supplier(company_name=s, contact_person="", phone="", status="Active", is_active=True))
    if not User.query.filter_by(username="admin").first():
        u = User(username="admin", full_name="System Administrator", role="ADMIN", email="admin@rorihotel.local")
        u.set_password("admin123"); db.session.add(u)
    for s in [
        {"u":"amir","n":"Amir Awel","r":"MANAGER","d":None},
        {"u":"kasahun","n":"Kasahun Girma","r":"MANAGER","d":hk_dept.id if hk_dept else None},
        {"u":"abebayhu","n":"Abebaw","r":"SUPERVISOR","d":None},
        {"u":"tesfahun","n":"Tesfahun","r":"TECHNICIAN","d":None},
        {"u":"simon","n":"Simon","r":"TECHNICIAN","d":None},
        {"u":"chernet","n":"Chernet","r":"TECHNICIAN","d":None},
        {"u":"wale","n":"Wale","r":"TECHNICIAN","d":None},
        {"u":"tsadiku","n":"Tsadiku","r":"TECHNICIAN","d":None},
        {"u":"employee1","n":"Test Employee","r":"EMPLOYEE","d":None},
        {"u":"housekeeping","n":"Kassahun Girma","r":"DEPARTMENT","d":hk_dept.id if hk_dept else None},
    ]:
        ex = User.query.filter_by(username=s["u"]).first()
        if not ex:
            u = User(username=s["u"], full_name=s["n"], role=s["r"], department_id=s["d"])
            u.set_password("123456"); db.session.add(u)
        else:
            ex.full_name = s["n"]; ex.role = s["r"]; ex.department_id = s["d"]
    mkt_dept = Department.query.filter_by(name="Marketing").first()
    yord = User.query.filter_by(username="yordanose").first()
    if not yord: yord = User.query.filter_by(full_name="Yordanose Tegegn").first()
    if not yord:
        u = User(username="yordanose", full_name="Yordanose Tegegn", role="MANAGER", department_id=mkt_dept.id if mkt_dept else None, email="yordanose@rorihotel.local")
        u.set_password("123456"); db.session.add(u)
    else:
        yord.full_name = "Yordanose Tegegn"; yord.role = "MANAGER"
        if mkt_dept: yord.department_id = mkt_dept.id
    mkt_user = User.query.filter_by(username="marketing").first()
    if not mkt_user:
        u = User(username="marketing", full_name="Marketing User", role="DEPARTMENT", department_id=mkt_dept.id if mkt_dept else None, email="marketing@rorihotel.local")
        u.set_password("123456"); db.session.add(u)
    else:
        if mkt_dept and mkt_user.department_id != mkt_dept.id: mkt_user.department_id = mkt_dept.id
        if mkt_user.role != "DEPARTMENT": mkt_user.role = "DEPARTMENT"
    dept_map = {"fnb":{"n":"Bahilu Boja","dept":"Food & Beverage"},"kitchen":{"n":"Biruk Haile","dept":"Kitchen"},
                "security":{"n":"Tariku Bekele","dept":"Security"},"spa":{"n":"Tesfaye Yohanes","dept":"SPA"},
                "it":{"n":"Hebron Tedrose","dept":"IT"},"finance":{"n":"Abel Yemane","dept":"Finance"},
                "gm":{"n":"Muluken Gedafew","dept":"GM"}}
    for uname, info in dept_map.items():
        dept = Department.query.filter_by(name=info["dept"]).first()
        if not dept: continue
        ex = User.query.filter_by(username=uname).first()
        if not ex:
            u = User(username=uname, full_name=info["n"], role="DEPARTMENT", department_id=dept.id, email=uname + "@rorihotel.local")
            u.set_password("123456"); db.session.add(u)
        else:
            ex.full_name = info["n"]; ex.role = "DEPARTMENT"; ex.department_id = dept.id
    old_laundry_user = User.query.filter_by(username="laundry").first()
    if old_laundry_user and hk_dept: old_laundry_user.department_id = hk_dept.id
    db.session.flush()
    sig_configs = [{"dept":"Food & Beverage","name":"Bahilu Boja"},{"dept":"Kitchen","name":"Biruk Haile"},
                   {"dept":"Security","name":"Tariku Bekele"},{"dept":"SPA","name":"Tesfaye Yohanes"},
                   {"dept":"Marketing","name":"Yordanose Tegegn"},{"dept":"IT","name":"Hebron Tedrose"},
                   {"dept":"Finance","name":"Abel Yemane"},{"dept":"GM","name":"Muluken Gedafew"},
                   {"dept":"Housekeeping","name":"Kasahun Girma"}]
    for cfg in sig_configs:
        dept = Department.query.filter_by(name=cfg["dept"]).first()
        if not dept: continue
        existing = DepartmentSignature.query.filter_by(department_id=dept.id).first()
        if not existing: db.session.add(DepartmentSignature(department_id=dept.id, authorized_name=cfg["name"], is_active=True))
        else:
            existing.authorized_name = cfg["name"]; existing.is_active = True
    db.session.commit()
    print("✅ Seed data loaded (existing records untouched)")

def fix_room_structure():
    valid = {}
    for floor, nums in RORI_ROOM_STRUCTURE.items():
        for n in nums: valid[str(n)] = floor
    changed = False
    for r in Room.query.all():
        if r.room_number not in valid:
            MaintenanceRequest.query.filter_by(room_id=r.id).update({"room_id": None})
            db.session.delete(r); changed = True
    for r in Room.query.all():
        cf = valid.get(r.room_number)
        if cf is not None and r.floor != cf: r.floor = cf; changed = True
    db.session.flush()
    existing = {r.room_number for r in Room.query.all()}
    for num_str, floor in valid.items():
        if num_str not in existing:
            db.session.add(Room(floor=floor, room_number=num_str, status="Available")); changed = True
    for f in [2, 3, 4, 5]:
        if not Floor.query.filter_by(floor_number=f).first(): db.session.add(Floor(floor_number=f)); changed = True
    db.session.commit()
    print(f"✅ Room structure enforced: {Room.query.count()} rooms (expected 100) — historical requests preserved")
    return Room.query.count()

# ══════════════════════════════════════════ AUTH
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
<div class="mb-3"><label class="form-label">Username</label><input type="text" class="form-control" name="username" required autofocus></div>
<div class="mb-4"><label class="form-label">Password</label><input type="password" class="form-control" name="password" required></div>
<button class="btn-primary w-100"><i class="fas fa-sign-in-alt"></i> Login</button>
</form>
<hr style="border-color:var(--border-color);margin:1.5rem 0">
<div class="text-center small" style="color:var(--text-secondary)">
<p class="mb-1">Manager: <b style="color:var(--rori-gold)">amir / 123456</b></p>
<p class="mb-1">Marketing Mgr: <b style="color:var(--rori-gold)">yordanose / 123456</b></p>
<p class="mb-0">Admin: <b style="color:var(--rori-gold)">admin / admin123</b></p>
</div>
</div>
</div>
<style>
.login-container{display:flex;align-items:center;justify-content:center;min-height:calc(100vh - 70px);padding:2rem}
.login-card{background:var(--bg-card);border:1px solid var(--border-color);border-radius:20px;padding:2.5rem;max-width:440px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,0.5)}
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
         '<p style="color:var(--text-secondary);"> Department: <strong style="color:var(--text-primary);">' + str(u.department.name if u.department else "Not assigned") + '</strong></p><hr style="border-color:var(--border-color);">'
         '<form method="post"><div class="mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + str(u.email or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + str(u.phone or "") + '"></div>'
         '<div class="mb-3"><label class="form-label">New Password</label><input type="password" class="form-control" name="new_password" placeholder="Leave blank to keep current"></div>'
         '<button class="btn-primary"><i class="fas fa-save"></i> Save</button></form></div>')
    return page("Profile", c)

# ══════════════════════════════════════════ ITEMS MANAGEMENT
@app.route("/items")
@role_required("ADMIN","MANAGER","SUPERVISOR")
def items_list():
    depts = Department.query.order_by(Department.name).all()
    dept_f = request.args.get("dept", type=int)
    q = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive", "") == "1"
    base = WorkingItem.query
    if dept_f: base = base.filter(WorkingItem.department_id == dept_f)
    if q: base = base.filter(WorkingItem.name.like("%" + q + "%"))
    if not show_inactive: base = base.filter((WorkingItem.is_active == True) | (WorkingItem.is_active == None))
    items = base.order_by(WorkingItem.department_id, WorkingItem.name).all()
    rows = []
    for it in items:
        dname = it.department.name if it.department else "—"
        aname = it.area.name if it.area else "—"
        inactive = (it.is_active is False)
        status_badge = ('<span class="badge badge-secondary">Inactive</span>' if inactive else '<span class="badge badge-success">Active</span>')
        actions = ('<a class="btn-primary" href="' + url_for("items_edit", item_id=it.id) + '" style="padding:.35rem .7rem;font-size:.75rem;"><i class="fas fa-edit"></i> Edit</a> ')
        if inactive: actions += '<form method="post" action="' + url_for("items_activate", item_id=it.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--success);padding:.35rem .7rem;font-size:.75rem;"><i class="fas fa-undo"></i> Activate</button></form>'
        else: actions += '<form method="post" action="' + url_for("items_deactivate", item_id=it.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate this item?\')"><button type="submit" class="btn-primary" style="background:var(--warning);padding:.35rem .7rem;font-size:.75rem;"><i class="fas fa-ban"></i> Deactivate</button></form>'
        rows.append('<tr><td>' + str(it.id) + '</td><td>' + str(it.name) + '</td><td>' + str(dname) + '</td><td>' + str(aname) + '</td><td>' + status_badge + '</td><td>' + actions + '</td></tr>')
    dept_opts = '<option value="">All Departments</option>' + "".join('<option value="' + str(d.id) + '"' + (' selected' if dept_f==d.id else '') + '>' + d.name + '</option>' for d in depts)
    content = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-th-list"></i> <span>Maintenance</span> Items</h1><p>Add, edit or deactivate items per department</p></div>'
        '<a href="' + url_for("items_add") + '" class="btn-primary"><i class="fas fa-plus"></i> Add Item</a></div>'
        '<form method="get" class="rpro-toolbar"><input type="text" class="form-control" name="q" placeholder="Search item name..." value="' + str(q) + '">'
        '<select class="form-select" name="dept">' + dept_opts + '</select>'
        '<label style="display:flex;align-items:center;gap:.4rem;color:var(--text-secondary);font-size:.85rem;"><input type="checkbox" name="show_inactive" value="1"' + (' checked' if show_inactive else '') + '> Show inactive</label>'
        '<button type="submit" class="btn-primary" style="padding:.7rem 1.4rem;"><i class="fas fa-search"></i> Filter</button>'
        '<a href="' + url_for("items_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);padding:.7rem 1.4rem;text-decoration:none;"><i class="fas fa-undo"></i> Reset</a></form>'
        '<div class="card"><div style="overflow-x:auto;"><table class="table">'
        '<thead><tr><th>ID</th><th>Item</th><th>Department</th><th>Area (optional)</th><th>Status</th><th>Actions</th></tr></thead>'
        '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="6" style="text-align:center;color:var(--text-secondary);padding:2rem;">No items found.</td></tr>') + '</tbody></table></div></div>')
    return page("Maintenance Items", content)

@app.route("/items/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def items_add():
    depts = Department.query.order_by(Department.name).all()
    areas = Area.query.filter((Area.is_active == True) | (Area.is_active == None)).order_by(Area.name).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        dept_id = request.form.get("department_id", type=int)
        area_id = request.form.get("area_id", type=int) or None
        desc = (request.form.get("description") or "").strip()
        if not name: flash("Item name is required","danger"); return redirect(url_for("items_add"))
        existing = WorkingItem.query.filter(func.lower(WorkingItem.name) == name.lower()).first()
        if existing: flash("An item with this name already exists.","warning"); return redirect(url_for("items_add"))
        try:
            it = WorkingItem(name=name, description=desc, department_id=dept_id, area_id=area_id, is_active=True)
            db.session.add(it); db.session.flush()
            log_audit("Item Created","WorkingItem",it.id,new_value=name)
            db.session.commit(); flash("✅ Item added successfully","success"); return redirect(url_for("items_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    dept_opts = '<option value="">-- Select Department --</option>' + "".join('<option value="' + str(d.id) + '">' + d.name + '</option>' for d in depts)
    area_opts = '<option value="">-- No specific area (available for all areas) --</option>' + "".join('<option value="' + str(a.id) + '">' + a.name + '</option>' for a in areas)
    content = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-plus-circle"></i> <span>Add</span> Maintenance Item</h1><p>Create a new maintenance item and assign it to a department</p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("items_list") + '"><i class="fas fa-arrow-left"></i> Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Item Name *</label><input type="text" class="form-control" name="name" required autofocus></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Department *</label><select class="form-select" name="department_id" required>' + dept_opts + '</select></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Area (optional)</label><select class="form-select" name="area_id">' + area_opts + '</select></div>'
        '<div class="col-12 mb-3"><label class="form-label">Description (optional)</label><textarea class="form-control" name="description" rows="2"></textarea></div>'
        '<div class="col-12 d-flex gap-2"><a href="' + url_for("items_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);">Cancel</a>'
        '<button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save Item</button></div></div></form></div>')
    return page("Add Item", content)

@app.route("/items/<int:item_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def items_edit(item_id):
    it = get_or_404(WorkingItem, item_id)
    depts = Department.query.order_by(Department.name).all()
    areas = Area.query.filter((Area.is_active == True) | (Area.is_active == None)).order_by(Area.name).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        dept_id = request.form.get("department_id", type=int)
        area_id = request.form.get("area_id", type=int) or None
        desc = (request.form.get("description") or "").strip()
        if not name: flash("Item name is required","danger"); return redirect(url_for("items_edit", item_id=it.id))
        dup = WorkingItem.query.filter(func.lower(WorkingItem.name) == name.lower(), WorkingItem.id != it.id).first()
        if dup: flash("Another item with this name already exists.","warning"); return redirect(url_for("items_edit", item_id=it.id))
        try:
            old = it.name
            it.name = name; it.description = desc; it.department_id = dept_id; it.area_id = area_id
            log_audit("Item Updated","WorkingItem",it.id,old_value=old,new_value=name)
            db.session.commit(); flash("✅ Item updated","success"); return redirect(url_for("items_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    dept_opts = '<option value="">-- Select Department --</option>' + "".join('<option value="' + str(d.id) + '"' + (' selected' if it.department_id==d.id else '') + '>' + d.name + '</option>' for d in depts)
    area_opts = '<option value="">-- No specific area (available for all areas) --</option>' + "".join('<option value="' + str(a.id) + '"' + (' selected' if it.area_id==a.id else '') + '>' + a.name + '</option>' for a in areas)
    content = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-edit"></i> <span>Edit</span> Item</h1><p>' + str(it.name) + '</p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("items_list") + '"><i class="fas fa-arrow-left"></i> Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Item Name *</label><input type="text" class="form-control" name="name" value="' + str(it.name) + '" required></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Department *</label><select class="form-select" name="department_id" required>' + dept_opts + '</select></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Area (optional)</label><select class="form-select" name="area_id">' + area_opts + '</select></div>'
        '<div class="col-12 mb-3"><label class="form-label">Description (optional)</label><textarea class="form-control" name="description" rows="2">' + str(it.description or "") + '</textarea></div>'
        '<div class="col-12 d-flex gap-2"><a href="' + url_for("items_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);">Cancel</a>'
        '<button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save Changes</button></div></div></form></div>')
    return page("Edit Item", content)

@app.route("/items/<int:item_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def items_deactivate(item_id):
    it = get_or_404(WorkingItem, item_id)
    try:
        it.is_active = False
        log_audit("Item Deactivated","WorkingItem",it.id,old_value="active",new_value="inactive")
        db.session.commit(); flash("Item deactivated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("items_list"))

@app.route("/items/<int:item_id>/activate", methods=["POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def items_activate(item_id):
    it = get_or_404(WorkingItem, item_id)
    try:
        it.is_active = True
        log_audit("Item Activated","WorkingItem",it.id,old_value="inactive",new_value="active")
        db.session.commit(); flash("Item activated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("items_list"))

# ══════════════════════════════════════════ REQUESTS
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
    if request.args.get("room_id", type=int): q = q.filter(MaintenanceRequest.room_id == request.args.get("room_id", type=int))
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    is_mgr = current_user.role in ["MANAGER","ADMIN"]
    rows = []
    for r in reqs:
        del_html = ""
        if is_mgr:
            del_html = ('<form method="post" action="' + url_for("request_delete", req_id=r.id) + '" style="display:inline" onsubmit="return confirm(\'Archive?\');"><input type="hidden" name="reason" value="Archived by manager"><button type="submit" class="btn-icon" style="width:32px;height:32px;"><i class="fas fa-archive"></i></button></form>')
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);font-weight:600;text-decoration:none;">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.department.name if r.department else "—") + '</td><td><span class="badge badge-secondary">' + str(r.priority) + '</span></td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>' + ('<td>' + del_html + '</td>' if is_mgr else '') + '</tr>')
    header = '<thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Created</th>' + ('<th></th>' if is_mgr else '') + '</tr></thead>'
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-clipboard-list"></i> <span>Maintenance</span> Requests</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New Request</a></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table">' + header + '<tbody>' + ("".join(rows) if rows else '<tr><td colspan="' + ('8' if is_mgr else '7') + '" style="text-align:center;color:var(--text-secondary);">No requests found</td></tr>') + '</tbody></table></div></div>')
    return page("Requests", c)

@app.route("/requests/new", methods=["GET","POST"])
@login_required
def request_create():
    cats_all = Category.query.order_by(Category.name).all()
    rooms = Room.query.order_by(func.cast(Room.room_number, db.Integer).asc()).all()
    areas = Area.query.filter((Area.is_active == True) | (Area.is_active == None)).order_by(Area.name).all()
    floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()] or sorted({r.floor for r in Room.query.all()})
    all_depts = Department.query.order_by(Department.name).all()
    sig_profile = get_user_signature_profile(current_user)
    user_dept_name = current_user.department.name if current_user.department else None
    user_dept_id = current_user.department_id

    hk_dept = Department.query.filter_by(name=HOUSEKEEPING_DEPT_NAME).first()
    hk_dept_id = hk_dept.id if hk_dept else None
    hk_cats = [c for c in cats_all if c.name in HOUSEKEEPING_CATEGORY_NAMES]
    other_cats = [c for c in cats_all if c.name not in HOUSEKEEPING_CATEGORY_NAMES]

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
            form_dept_id = request.form.get("department_id", type=int)
            if form_dept_id: did = form_dept_id
            if lt == "Room" and rid:
                rm = get_one(Room, rid)
                if rm: fl = rm.floor
            elif lt == "Area": rid = None
            else: rid = None; aid = None
            if not desc: flash("Description is required","danger"); return redirect(url_for("request_create"))
            sig_data = request.form.get("signature_data", "").strip()
            sig_name_from_form = request.form.get("signature_name", "").strip()
            if current_user.role in ["DEPARTMENT", "EMPLOYEE"]:
                ok, err = validate_signature_for_user(current_user, sig_data)
                if not ok: flash(err, "danger"); return redirect(url_for("request_create"))
                if sig_profile and sig_name_from_form and sig_name_from_form != sig_profile.authorized_name:
                    flash("Signature name mismatch.", "danger"); return redirect(url_for("request_create"))
            authorized_name = sig_profile.authorized_name if sig_profile else (current_user.full_name or current_user.username)
            req = MaintenanceRequest(
                request_no=request_no_generator(), location_type=lt, floor=fl, room_id=rid, area_id=aid,
                working_item_id=wid, category_id=cid, description=desc, priority=prio, status="Pending",
                requested_by_id=current_user.id, department_id=did,
                signature_name=authorized_name, signature_status=("SIGNED" if sig_data else "UNSIGNED"),
                signature_signed_at=(datetime.utcnow() if sig_data else None),
                signature_data=sig_data, signature_department=user_dept_name,
                signature_verified=bool(sig_data), signature_user_id=current_user.id,
            )
            req.due_date = datetime.utcnow() + timedelta(hours=PRIORITIES.get(prio,24))
            db.session.add(req); db.session.flush()
            # Optional photo
            f = request.files.get("photo")
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit(".",1)[-1].lower()
                fname = secure_filename("req_" + str(req.id) + "_" + datetime.now().strftime("%Y%m%d%H%M%S") + "." + ext)
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                db.session.add(Photo(filename=fname, object_type="request", object_id=req.id,
                                     photo_type="Problem", uploaded_by_id=current_user.id))
            log_audit("Create Request","MaintenanceRequest",req.id,new_value=req.request_no)
            log_status_change(req.id,"Pending",notes="Created by " + str(current_user.full_name))
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"]), User.active == True).all()
            notify_users([u.id for u in managers], req.id, "📝 NEW MAINTENANCE REQUEST",
                         "Request " + str(req.request_no) + " [" + str(prio) + "] from " + str(user_dept_name or "N/A") + " is pending approval",
                         "New Request", link=url_for("request_detail", req_id=req.id))
            db.session.commit(); flash("✅ Request created successfully!","success"); return redirect(url_for("request_detail", req_id=req.id))
        except Exception as e:
            db.session.rollback(); print("Create error: " + traceback.format_exc())
            flash("Error: " + str(e),"danger"); return redirect(url_for("request_create"))

    dept_opts = "".join('<option value="' + str(d.id) + '"' + (' selected' if d.id == user_dept_id else '') + '>' + str(d.name) + '</option>' for d in all_depts)
    hk_cat_opts = "".join('<option value="' + str(c.id) + '">' + str(c.name) + '</option>' for c in hk_cats)
    other_cat_opts = "".join('<option value="' + str(c.id) + '">' + str(c.name) + '</option>' for c in other_cats)

    items_by_dept = {}
    for d in all_depts:
        items = WorkingItem.query.filter_by(department_id=d.id).filter((WorkingItem.is_active == True) | (WorkingItem.is_active == None)).order_by(WorkingItem.name).all()
        items_by_dept[d.id] = [{"id": w.id, "name": w.name, "area_id": w.area_id} for w in items]

    hk_items_by_category = {}
    if hk_dept_id:
        for cat_name, item_names in HOUSEKEEPING_CATEGORIES.items():
            cat = Category.query.filter_by(name=cat_name).first()
            if not cat: continue
            ids = []
            for iname in item_names:
                w = WorkingItem.query.filter_by(name=iname, department_id=hk_dept_id).first()
                if w: ids.append(w.id)
            hk_items_by_category[cat.id] = ids

    areas_json = [{"id": a.id, "name": a.name, "dept": a.department or ""} for a in areas]
    fo = "".join('<option value="' + str(f) + '">Floor ' + str(f) + '</option>' for f in floors)
    ro = "".join('<option value="' + str(r.id) + '">Room ' + str(r.room_number) + ' (F' + str(r.floor) + ')</option>' for r in rooms)
    po = "".join('<option value="' + p + '"' + (' selected' if p=="MEDIUM" else '') + '>' + p + '</option>' for p in ["URGENT","HIGH","MEDIUM","LOW"])
    sig_authorized_name = sig_profile.authorized_name if sig_profile else (current_user.full_name or current_user.username)
    sig_dept_display = user_dept_name or "Not assigned"
    sig_block_required = current_user.role in ["DEPARTMENT", "EMPLOYEE"]
    sig_warning = "" if (sig_profile or not sig_block_required) else '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> No authorized signature configured for your department.</div>'

    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-plus-circle"></i> <span>New</span> Maintenance Request</h1></div></div>' + sig_warning +
         '<div class="card"><form method="post" id="requestForm" enctype="multipart/form-data"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Department *</label><select class="form-select" name="department_id" id="deptSelect" required>' + dept_opts + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Category *</label><select class="form-select" name="category_id" id="catSelect" required><option value="">-- Select Category --</option>' + other_cat_opts + '</select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Maintenance Item *</label><select class="form-select" name="working_item_id" id="itemSelect" required><option value="">-- Select Item --</option></select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Location Type *</label><select class="form-select" name="location_type" id="locationType" required><option value="Room" selected>Room</option><option value="Area">Area</option></select></div>'
         '<div class="col-md-6 mb-3" id="roomWrap"><label class="form-label">Room</label><select class="form-select" name="room_id" id="roomSelect"><option value="">-- Select Room --</option>' + ro + '</select></div>'
         '<div class="col-md-6 mb-3" id="floorWrap" style="display:none"><label class="form-label">Floor</label><select class="form-select" name="floor"><option value="">-- Floor --</option>' + fo + '</select></div>'
         '<div class="col-md-6 mb-3" id="areaWrap" style="display:none"><label class="form-label">Area / Location</label><select class="form-select" name="area_id" id="areaSelect"><option value="">-- Select Area --</option></select></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Priority *</label><select class="form-select" name="priority">' + po + '</select></div>'
         '<div class="col-12 mb-3"><label class="form-label">Description *</label><textarea class="form-control" name="description" rows="4" required placeholder="Describe the issue…"></textarea></div>'
         '<div class="col-md-6 mb-3"><label class="form-label">Photo (optional)</label><input type="file" class="form-control" name="photo" accept="image/*"></div>'
         '<div class="col-12 mb-3"><div class="card" style="background:rgba(34,197,94,0.05);border:2px solid ' + ("var(--success)" if sig_block_required else "var(--border-color)") + '">'
         '<h5 style="color:var(--success);margin-bottom:1rem"><i class="fas fa-signature"></i> Authorized Digital Signature ' + ("(required)" if sig_block_required else "(optional for manager/admin)") + '</h5>'
         '<div class="row g-3">'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Signed By</div><div style="font-size:1.05rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_authorized_name) + '</div><input type="hidden" name="signature_name" value="' + str(sig_authorized_name) + '"></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Department</div><div style="font-size:1.05rem;font-weight:700;color:var(--text-primary);margin-top:.25rem">' + str(sig_dept_display) + '</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:rgba(34,197,94,0.1);border-radius:10px;border:1px solid var(--success)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Signature Status</div><div id="sigStatusText" style="font-size:1rem;font-weight:700;color:var(--rori-gold);margin-top:.25rem"><i class="fas fa-hourglass-half"></i> Awaiting Signature</div></div></div>'
         '<div class="col-md-6"><div style="padding:.75rem;background:var(--bg-card);border-radius:10px;border:1px solid var(--border-color)"><div style="font-size:.75rem;color:var(--text-secondary);text-transform:uppercase">Requester</div><div style="font-size:1rem;font-weight:600;color:var(--text-primary);margin-top:.25rem">' + str(current_user.full_name or current_user.username) + ' (@' + str(current_user.username) + ')</div></div></div>'
         '</div><hr style="border-color:var(--success);margin:1rem 0">'
         '<label class="form-label" style="color:var(--success);font-weight:600"><i class="fas fa-pen-nib"></i> Draw Your Signature Below</label>'
         '<div style="border: 2px dashed rgba(197,160,89,0.4); border-radius: 12px; padding: 10px; background: #fff;">'
         '<canvas id="signature-pad" width="400" height="150" style="width: 100%; height: 150px; cursor: crosshair; touch-action: none;"></canvas>'
         '</div>'
         '<div class="mt-2 d-flex gap-2"><button type="button" class="btn-icon" id="clear-signature"><i class="fas fa-eraser"></i> Clear</button><span id="sigHint" style="color:var(--text-secondary);font-size:.85rem;margin-left:.5rem">Draw your signature above</span></div>'
         '<input type="hidden" name="signature_data" id="signature-data"></div></div>'
         '<div class="col-12 d-flex gap-2"><a href="' + url_for("index") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-times"></i> Cancel</a><button type="submit" class="btn-primary" id="submitBtn"><i class="fas fa-paper-plane"></i> Submit Request</button></div></div></form></div>'
         '<script>window.RORI_ITEMS_BY_DEPT=' + json.dumps({str(k): v for k, v in items_by_dept.items()}) + ';</script>'
         '<script>window.RORI_AREAS=' + json.dumps(areas_json) + ';</script>'
         '<script>window.RORI_SIG_REQUIRED=' + ("true" if sig_block_required else "false") + ';</script>'
         '<script>window.RORI_HK_DEPT_ID=' + str(hk_dept_id or 0) + ';</script>'
         '<script>window.RORI_HK_CAT_OPTS=' + json.dumps(hk_cat_opts) + ';</script>'
         '<script>window.RORI_OTHER_CAT_OPTS=' + json.dumps(other_cat_opts) + ';</script>'
         '<script>window.RORI_HK_ITEMS_BY_CAT=' + json.dumps({str(k): v for k, v in hk_items_by_category.items()}) + ';</script>'
         '<script src="https://cdn.jsdelivr.net/npm/signature_pad@4.1.5/dist/signature_pad.umd.min.js"></script>'
         '<script>(function(){var canvas=document.getElementById("signature-pad");var signaturePad=new SignaturePad(canvas,{backgroundColor:"rgb(255,255,255)",penColor:"rgb(0,0,0)"});var sigStatusText=document.getElementById("sigStatusText");var sigHint=document.getElementById("sigHint");var sigRequired=window.RORI_SIG_REQUIRED===true;function resizeCanvas(){var ratio=Math.max(window.devicePixelRatio||1,1);canvas.width=canvas.offsetWidth*ratio;canvas.height=canvas.offsetHeight*ratio;canvas.getContext("2d").scale(ratio,ratio);signaturePad.clear();updateSigStatus();}window.addEventListener("resize",resizeCanvas);resizeCanvas();document.getElementById("clear-signature").addEventListener("click",function(){signaturePad.clear();updateSigStatus();});signaturePad.addEventListener("endStroke",updateSigStatus);function updateSigStatus(){if(signaturePad.isEmpty()){sigStatusText.innerHTML=\'<i class="fas fa-hourglass-half"></i> Awaiting Signature\';sigStatusText.style.color="var(--rori-gold)";sigHint.textContent="Draw your signature above";}else{sigStatusText.innerHTML=\'<i class="fas fa-check-circle"></i> Signature Captured\';sigStatusText.style.color="var(--success)";sigHint.textContent="✓ Ready to submit";}}document.querySelector("#requestForm").addEventListener("submit",function(e){if(sigRequired&&signaturePad.isEmpty()){e.preventDefault();alert("⚠️ Digital signature is required.");return false;}if(!signaturePad.isEmpty()){document.getElementById("signature-data").value=signaturePad.toDataURL("image/png");}});updateSigStatus();})();</script>'
         '<script>(function(){'
         'var lt=document.getElementById("locationType");var rw=document.getElementById("roomWrap");var aw=document.getElementById("areaWrap");var fw=document.getElementById("floorWrap");'
         'var deptSel=document.getElementById("deptSelect");var catSel=document.getElementById("catSelect");var itemSel=document.getElementById("itemSelect");var areaSel=document.getElementById("areaSelect");'
         'var itemsByDept=window.RORI_ITEMS_BY_DEPT||{};var allAreas=window.RORI_AREAS||[];var HK_DEPT_ID=String(window.RORI_HK_DEPT_ID||0);'
         'var HK_CAT_OPTS=window.RORI_HK_CAT_OPTS||"";var OTHER_CAT_OPTS=window.RORI_OTHER_CAT_OPTS||"";var HK_ITEMS_BY_CAT=window.RORI_HK_ITEMS_BY_CAT||{};'
         'function updLoc(){var v=lt.value;if(v==="Room"){rw.style.display="";aw.style.display="none";fw.style.display="none";}else{rw.style.display="none";aw.style.display="";fw.style.display="";}}'
         'function renderCats(){var d=String(deptSel.value||"");if(d===HK_DEPT_ID){catSel.innerHTML=\'<option value="">-- Select Category --</option>\'+HK_CAT_OPTS;}else{catSel.innerHTML=\'<option value="">-- Select Category --</option>\'+OTHER_CAT_OPTS;}renderItems();}'
         'function renderItems(){var d=String(deptSel.value||"");var cid=String(catSel.value||"");var list=(itemsByDept[d]||[]).slice();'
         'if(d===HK_DEPT_ID&&cid&&HK_ITEMS_BY_CAT[cid]){var allowed=HK_ITEMS_BY_CAT[cid];list=list.filter(function(it){return allowed.indexOf(it.id)>=0;});}'
         'itemSel.innerHTML=\'<option value="">-- Select Item --</option>\';list.forEach(function(it){var o=document.createElement("option");o.value=it.id;o.textContent=it.name;itemSel.appendChild(o);});}'
         'function renderAreas(){areaSel.innerHTML=\'<option value="">-- Select Area --</option>\';allAreas.forEach(function(a){var o=document.createElement("option");o.value=a.id;o.textContent=a.name;areaSel.appendChild(o);});}'
         'lt.addEventListener("change",updLoc);deptSel.addEventListener("change",renderCats);catSel.addEventListener("change",renderItems);areaSel.addEventListener("change",renderItems);'
         'updLoc();renderAreas();renderCats();'
         '})();</script>')
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
    def badge(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st, "secondary")
    def kv(label, value, mono=False, color=None):
        cs = (' style="color:' + color + '"') if color else ""
        cls = "rpro-kv-value mono" if mono else "rpro-kv-value"
        return ('<div class="rpro-kv-item"><div class="rpro-kv-label">' + label + '</div>'
                '<div class="' + cls + '"' + cs + '>' + (str(value) if value not in (None,"") else "—") + '</div></div>')
    assigned_dt = None; started_dt = None
    for h in hist:
        if h.status == "Assigned" and not assigned_dt: assigned_dt = h.timestamp
        if h.status == "In Progress" and not started_dt: started_dt = h.timestamp
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
            actions.append('<form method="post" action="' + url_for("request_delete", req_id=req.id) + '" style="display:inline" onsubmit="return confirm(\'Archive this request?\')"><input type="hidden" name="reason" value="Archived by manager"><button type="submit" class="btn-primary" style="background:var(--danger);"><i class="fas fa-archive"></i> Archive</button></form>')
    actions.append('<a href="' + url_for("detailed_report_request", req_id=req.id) + '" class="btn-primary" style="background:var(--info);"><i class="fas fa-file-alt"></i> Detailed Report</a>')
    actions_html = " ".join(actions)
    info_card = ('<div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-info-circle"></i> Request Information</div>'
        '<div class="rpro-kv">'
        + kv("Request ID", req.request_no, mono=True)
        + kv("Status", '<span class="badge badge-' + badge(req.status) + '">' + str(req.status) + '</span>')
        + kv("Priority", '<span class="badge badge-' + ("danger" if req.priority=="URGENT" else "warning" if req.priority=="HIGH" else "info" if req.priority=="MEDIUM" else "secondary") + '">' + str(req.priority or "MEDIUM") + '</span>')
        + kv("Created", req.created_at.strftime("%Y-%m-%d %H:%M") if req.created_at else None)
        + kv("Department", req.department.name if req.department else "Not Assigned")
        + kv("Location Type", req.location_type)
        + kv("Location", req.location_name)
        + kv("Floor", req.floor if req.floor else None)
        + kv("Working Item", req.working_item.name if req.working_item else None)
        + kv("Category", req.category.name if req.category else None)
        + kv("Requested By", (req.requested_by.full_name or req.requested_by.username) if req.requested_by else None)
        + kv("Assigned To", (req.assigned_to.full_name or req.assigned_to.username) if req.assigned_to else "Not Assigned")
        + kv("Assigned Date", assigned_dt.strftime("%Y-%m-%d %H:%M") if assigned_dt else None)
        + kv("Started Date", started_dt.strftime("%Y-%m-%d %H:%M") if started_dt else None)
        + kv("Due Date", req.due_date.strftime("%Y-%m-%d %H:%M") if req.due_date else None)
        + kv("Completed", req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else None)
        + '</div>'
        + ('<div style="margin-top:1.25rem;"><div class="rpro-kv-label">Description</div><div style="margin-top:.4rem;padding:.85rem 1rem;background:var(--bg-secondary);border-radius:10px;border-left:3px solid var(--rori-gold);color:var(--text-primary);font-size:.9rem;line-height:1.5;white-space:pre-wrap;">' + str(req.description or "No description provided.") + '</div></div>')
        + ('<div style="margin-top:1rem;"><div class="rpro-kv-label">Completion Note</div><div style="margin-top:.4rem;padding:.85rem 1rem;background:rgba(34,197,94,.08);border-radius:10px;border-left:3px solid var(--success);color:var(--text-primary);font-size:.9rem;line-height:1.5;white-space:pre-wrap;">' + str(req.completion_note or "—") + '</div></div>' if req.completion_note else "")
        + '</div>')
    # Photos
    photos = Photo.query.filter_by(object_type="request", object_id=req.id).order_by(Photo.created_at.asc()).all()
    photo_html = ""
    if photos:
        for p in photos:
            photo_html += ('<div style="display:inline-block;margin:.35rem .5rem .35rem 0;border:2px solid var(--rori-gold);border-radius:10px;padding:.5rem;background:var(--bg-secondary);">'
                '<a href="/static/uploads/maintenance/' + str(p.filename) + '" target="_blank">'
                '<img src="/static/uploads/maintenance/' + str(p.filename) + '" style="max-width:220px;max-height:180px;border-radius:6px;" onerror="this.parentElement.parentElement.style.display=\'none\'"></a>'
                '<div style="font-size:.72rem;color:var(--text-secondary);margin-top:.3rem;"><b>' + str(p.photo_type) + '</b> · ' + (p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "") + '</div></div>')
    photo_card = ('<div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-camera"></i> Attached Photos</div>'
                  + (photo_html if photo_html else '<p style="color:var(--text-secondary);font-size:.88rem;margin:0;">No photos attached.</p>') + '</div>')
    sig_card = ""
    if req.signature_status == "SIGNED" and req.signature_data:
        sig_time = req.signature_signed_at.strftime("%d %b %Y, %I:%M %p") if req.signature_signed_at else "—"
        ver_badge = ('<span class="badge badge-success"><i class="fas fa-check-circle"></i> Verified</span>' if req.signature_verified else '<span class="badge badge-warning"><i class="fas fa-exclamation"></i> Unverified</span>')
        sig_card = ('<div class="rpro-card" style="border-color:rgba(34,197,94,.4);background:linear-gradient(180deg,rgba(34,197,94,.05),var(--bg-card));">'
            '<div class="rpro-card-title"><i class="fas fa-signature"></i> Digital Signature ' + ver_badge + '</div>'
            '<div class="rpro-kv" style="margin-bottom:1rem;">'
            + kv("Signed By", req.signature_name or "Unknown")
            + kv("Department", req.signature_department or (req.department.name if req.department else "—"))
            + kv("Signed At", sig_time)
            + kv("Verification", "✓ Verified" if req.signature_verified else "⚠ Unverified", color="var(--success)" if req.signature_verified else "var(--warning)")
            + '</div><div class="rpro-sig-box"><img src="' + str(req.signature_data) + '" alt="Signature"></div></div>')
    wo_rows = []
    for wo in wos:
        wo_rows.append('<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:.85rem 1rem;background:var(--bg-secondary);border-radius:10px;border:1px solid var(--border-color);margin-bottom:.5rem;flex-wrap:wrap;">'
            '<div style="flex:1;min-width:180px;"><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:var(--rori-gold);font-weight:700;text-decoration:none;">' + str(wo.work_order_no) + '</a>'
            '<div style="font-size:.78rem;color:var(--text-secondary);margin-top:.15rem;"><i class="fas fa-user"></i> ' + ((wo.assigned_to.full_name or wo.assigned_to.username) if wo.assigned_to else "Unassigned") + ' · <i class="fas fa-clock"></i> ' + str(round(wo.labor_hours or 0, 1)) + ' hrs</div></div>'
            '<div><span class="badge badge-' + badge(wo.status) + '">' + str(wo.status) + '</span></div></div>')
    wo_card = ('<div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-tasks"></i> Work Orders</div>'
        + ("".join(wo_rows) if wo_rows else '<p style="color:var(--text-secondary);font-size:.88rem;margin:0;">No work orders created yet.</p>') + '</div>')
    tl_items = []
    for h in hist:
        who = (h.user.full_name or h.user.username) if h.user else "System"
        when = h.timestamp.strftime("%d %b %Y · %H:%M") if h.timestamp else ""
        note_html = ('<div class="rpro-timeline-note">' + str(h.notes) + '</div>') if h.notes else ""
        tl_items.append('<div class="rpro-timeline-item"><div class="rpro-timeline-dot"></div><div class="rpro-timeline-status">' + str(h.status) + '</div><div class="rpro-timeline-meta">' + str(who) + ' · ' + when + '</div>' + note_html + '</div>')
    timeline_card = ('<div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-history"></i> Status Timeline</div><div class="rpro-timeline">' + ("".join(tl_items) if tl_items else '<p style="color:var(--text-secondary);font-size:.88rem;margin:0;">No status changes recorded.</p>') + '</div></div>')
    verify_card = ""
    if req.status in ("Verified","Closed"):
        wo_verifier = wos[0].verified_by if wos and wos[0].verified_by else req.manager
        verify_card = ('<div class="rpro-card" style="border-color:rgba(56,189,248,.4);"><div class="rpro-card-title"><i class="fas fa-shield-alt"></i> Verification</div><div class="rpro-kv">'
            + kv("Verified By", (wo_verifier.full_name or wo_verifier.username) if wo_verifier else "—")
            + kv("Verified Date", wos[0].verified_date.strftime("%Y-%m-%d %H:%M") if wos and wos[0].verified_date else (req.completed_date.strftime("%Y-%m-%d %H:%M") if req.completed_date else "—"))
            + '</div></div>')
    content = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-clipboard-list"></i> <span>Request</span> ' + str(req.request_no) + '</h1><p>' + str(req.location_name) + ' · ' + (req.department.name if req.department else "No Department") + '</p></div>'
        '<div style="display:flex;gap:.5rem;flex-wrap:wrap;">' + actions_html + '</div></div>'
        '<div class="row g-3"><div class="col-lg-8">' + info_card + photo_card + sig_card + wo_card + '</div>'
        '<div class="col-lg-4">' + timeline_card + verify_card + '</div></div>')
    return page("Request " + str(req.request_no), content)

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
        db.session.commit(); flash("✅ Request archived successfully (soft-delete only — no data destroyed)","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("requests_list"))

@app.route("/admin/deleted")
@role_required("ADMIN")
def deleted_requests():
    ds = MaintenanceRequest.query.filter_by(is_deleted=True).order_by(MaintenanceRequest.deleted_at.desc()).all()
    rows = []
    for r in ds:
        rows.append('<tr><td>' + str(r.request_no) + '</td><td>' + str(r.location_name) + '</td><td>' + str(r.status) + '</td><td>' + (r.deleted_at.strftime("%Y-%m-%d %H:%M") if r.deleted_at else "") + '</td><td>' + str(r.deleted_by.full_name if r.deleted_by else "—") + '</td><td>' + str(r.deletion_reason or "—") + '</td><td><form method="post" action="' + url_for("request_restore", req_id=r.id) + '"><button type="submit" class="btn-primary" style="background:var(--success);padding:0.4rem 0.8rem;font-size:0.8rem;"><i class="fas fa-undo"></i> Restore</button></form></td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-archive"></i> <span>Archived</span> Requests</h1><p>Soft-deleted only — no data destroyed</p></div></div>'
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

# ══════════════════════════════════════════ ANALYTICS
COMPLETED_STATES = ["Completed","Verified","Closed"]
PENDING_STATES = ["Pending","Approved"]
INPROGRESS_STATES = ["Assigned","In Progress"]

def _parse_date(v):
    if not v: return None
    try: return datetime.strptime(v,"%Y-%m-%d")
    except (ValueError, TypeError): return None

def build_filtered_query(args, include_deleted=False):
    q = MaintenanceRequest.query if include_deleted else MaintenanceRequest.query.filter_by(is_deleted=False)
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
    if args.get("location_type"): q = q.filter(MaintenanceRequest.location_type == args["location_type"])
    return q

def format_duration(s):
    if s is None: return "N/A"
    if s < 60: return str(int(s)) + "s"
    if s < 3600: return str(int(s/60)) + "m"
    if s < 86400: return str(round(s/3600,1)) + " hrs"
    d = int(s // 86400); h = int((s % 86400) // 3600)
    return str(d) + "d " + str(h) + "h" if h else str(d) + "d"

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
    d_from = _parse_date(args.get("date_from")); d_to = _parse_date(args.get("date_to"))
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
    d_from = _parse_date(args.get("date_from")); d_to = _parse_date(args.get("date_to"))
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

# ══════════════════════════════════════════ DETAILED REPORT BUILDERS
def _build_detailed_report_pack(req):
    wo = WorkOrder.query.filter_by(request_id=req.id).order_by(WorkOrder.created_at.asc()).first()
    hist = StatusHistory.query.filter_by(request_id=req.id).order_by(StatusHistory.timestamp.asc()).all()
    def _dt_first(statuses):
        for h in hist:
            if h.status in statuses: return h.timestamp
        return None
    accepted_dt = _dt_first(["Approved"]); assigned_dt = _dt_first(["Assigned"])
    started_dt = _dt_first(["In Progress"]); completed_dt = _dt_first(["Completed"])
    verified_dt = _dt_first(["Verified"]); closed_dt = _dt_first(["Closed"])
    assigned_by = None
    if assigned_dt:
        for h in hist:
            if h.status == "Assigned" and h.timestamp == assigned_dt: assigned_by = h.user; break
    verifier = None
    if verified_dt:
        for h in hist:
            if h.status == "Verified" and h.timestamp == verified_dt: verifier = h.user; break
    if not verifier and wo and wo.verified_by: verifier = wo.verified_by
    closer = None
    if closed_dt:
        for h in hist:
            if h.status == "Closed" and h.timestamp == closed_dt: closer = h.user; break
    if not closer and req.manager: closer = req.manager
    parts_used = []; total_cost = 0.0
    if wo:
        for wp in WorkOrderPart.query.filter_by(work_order_id=wo.id).all():
            cat = wp.part.category if wp.part else "—"
            unit = wp.part.unit if wp.part else "pcs"
            lt = (wp.quantity or 0) * (wp.unit_cost or 0); total_cost += lt
            parts_used.append({"name": wp.part.part_name if wp.part else ("Part #" + str(wp.part_id)), "category": cat, "quantity": wp.quantity, "unit": unit, "unit_cost": wp.unit_cost or 0, "line_total": lt, "notes": wp.notes or ""})
    photos = []
    try:
        objs = Photo.query.filter_by(object_type="request", object_id=req.id).order_by(Photo.created_at.asc()).all()
        for p in objs: photos.append({"filename": p.filename, "type": p.photo_type, "created": p.created_at})
    except Exception: pass
    if wo and wo.completion_photo: photos.append({"filename": wo.completion_photo, "type": "Completion", "created": wo.completed_date})
    return {
        "req": req, "wo": wo, "history": hist,
        "accepted_dt": accepted_dt, "assigned_dt": assigned_dt, "started_dt": started_dt,
        "completed_dt": completed_dt, "verified_dt": verified_dt, "closed_dt": closed_dt,
        "assigned_by": assigned_by, "verifier": verifier, "closer": closer,
        "parts_used": parts_used, "total_cost": total_cost,
        "technician": wo.assigned_to if wo and wo.assigned_to else req.assigned_to,
        "labor_hours": (wo.labor_hours if wo else 0) or 0,
        "work_performed": (wo.work_performed if wo else None),
        "root_cause": (wo.root_cause if wo else None),
        "recommendation": (wo.recommendation if wo else None),
        "completion_notes": (wo.completion_notes if wo else req.completion_note),
        "photos": photos,
    }

def _render_detailed_report_block(p, seq=None):
    req = p["req"]; wo = p["wo"]
    def fmt(dt): return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"
    def dt_date(dt): return dt.strftime("%Y-%m-%d") if dt else "—"
    def dt_time(dt): return dt.strftime("%H:%M") if dt else "—"
    tech = p["technician"]
    status_cls = "stamp-" + str(req.status or "Pending").replace(" ", "")
    loc_type = req.location_type or "—"
    if loc_type == "Room" and req.room:
        loc_line = "Room " + str(req.room.room_number)
        floor_line = "Floor " + str(req.floor) if req.floor else "—"
        room_line = str(req.room.room_number)
    elif loc_type == "Area" and req.area:
        loc_line = req.area.name; floor_line = req.floor if req.floor else "—"; room_line = "N/A (Area based)"
    else:
        loc_line = req.location_name; floor_line = req.floor if req.floor else "—"; room_line = "—"
    sig_html = ""
    if req.signature_status == "SIGNED" and req.signature_data:
        sig_html = ('<div class="report-sig"><img src="' + str(req.signature_data) + '" alt="Signature"></div>'
                    '<div style="font-size:.75rem;color:#444;margin-top:.35rem;">Signed by <b>' + str(req.signature_name or "—") + '</b>'
                    + (' · Department: ' + str(req.signature_department) if req.signature_department else '')
                    + ' · At ' + (req.signature_signed_at.strftime("%Y-%m-%d %H:%M") if req.signature_signed_at else "—") + '</div>')
    else:
        sig_html = '<div style="font-size:.85rem;color:#666;">No digital signature on record.</div>'
    parts_rows = ""
    if p["parts_used"]:
        for i, it in enumerate(p["parts_used"], 1):
            parts_rows += ('<tr><td>' + str(i) + '</td><td>' + str(it["name"]) + '</td><td>' + str(it["category"]) + '</td>'
                '<td>' + str(it["quantity"]) + '</td><td>' + str(it["unit"]) + '</td>'
                '<td>' + str(round(it["unit_cost"], 2)) + '</td><td>' + str(round(it["line_total"], 2)) + '</td>'
                '<td>' + (str(it["notes"]) if it["notes"] else "—") + '</td></tr>')
        parts_rows += '<tr style="background:#fafafa;font-weight:800;"><td colspan="6" style="text-align:right;">Total Materials Cost</td><td colspan="2">' + str(round(p["total_cost"], 2)) + '</td></tr>'
    else:
        parts_rows = '<tr><td colspan="8" style="text-align:center;color:#666;">No materials / spare parts recorded.</td></tr>'
    photos_html = ""
    if p["photos"]:
        for ph in p["photos"]:
            photos_html += ('<div class="report-photo" style="margin:.35rem .5rem .35rem 0;">'
                '<img src="/static/uploads/maintenance/' + str(ph["filename"]) + '" alt="Photo" onerror="this.style.display=\'none\'">'
                '<div style="font-size:.72rem;color:#444;margin-top:.3rem;"><b>' + str(ph["type"] or "Photo") + '</b>'
                + (' · ' + ph["created"].strftime("%Y-%m-%d %H:%M") if ph["created"] else '')
                + '<br><a href="/static/uploads/maintenance/' + str(ph["filename"]) + '" target="_blank" style="color:#8B6F26;">Open file</a></div></div>')
    else:
        photos_html = '<div style="font-size:.85rem;color:#666;">No photos / attachments on record.</div>'
    seq_badge = ('<div style="font-size:.72rem;color:#666;letter-spacing:1px;font-weight:700;">ENTRY #' + str(seq) + '</div>') if seq else ''
    return (seq_badge +
    '<div class="report-section"><div class="report-section-title">1. Request Information</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Request Number</span><span class="val mono">' + str(req.request_no) + '</span></div>'
    + '<div class="row"><span class="lbl">Work Order Number</span><span class="val mono">' + str(wo.work_order_no if wo else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Order Number (Internal ID)</span><span class="val">' + str(req.id) + ((' / WO #' + str(wo.id)) if wo else '') + '</span></div>'
    + '<div class="row"><span class="lbl">Request Date</span><span class="val">' + dt_date(req.created_at) + '</span></div>'
    + '<div class="row"><span class="lbl">Request Time</span><span class="val">' + dt_time(req.created_at) + '</span></div>'
    + '<div class="row"><span class="lbl">Department</span><span class="val">' + str(req.department.name if req.department else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Requester Name</span><span class="val">' + ((req.requested_by.full_name or req.requested_by.username) if req.requested_by else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Requester Role</span><span class="val">' + (req.requested_by.role if req.requested_by else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Priority</span><span class="val">' + str(req.priority or "MEDIUM") + '</span></div>'
    + '<div class="row"><span class="lbl">Current Status</span><span class="val"><span class="report-stamp ' + status_cls + '">' + str(req.status) + '</span></span></div>'
    + '</div></div>'
    + '<div class="report-section"><div class="report-section-title">2. Location Information</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Location Type</span><span class="val">' + str(loc_type) + '</span></div>'
    + '<div class="row"><span class="lbl">Floor</span><span class="val">' + str(floor_line) + '</span></div>'
    + '<div class="row"><span class="lbl">Room Number</span><span class="val">' + str(room_line) + '</span></div>'
    + '<div class="row"><span class="lbl">Area / Location</span><span class="val">' + str(req.area.name if req.area else "—") + '</span></div>'
    + '<div class="row" style="grid-column:1/-1;"><span class="lbl">Full Location</span><span class="val">' + str(loc_line) + '</span></div>'
    + '</div></div>'
    + '<div class="report-section"><div class="report-section-title">3. Maintenance Problem</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Maintenance Item</span><span class="val">' + str(req.working_item.name if req.working_item else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Category</span><span class="val">' + str(req.category.name if req.category else "—") + '</span></div>'
    + '</div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Problem / Fault Description (Full)</div>'
    + '<div class="report-longtext">' + (str(req.description) if req.description else "No description provided.") + '</div></div>'
    + ('<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Work Instructions / Notes</div>'
       + '<div class="report-longtext">' + str(wo.work_performed) + '</div></div>' if wo and wo.work_performed else "")
    + '</div>'
    + '<div class="report-section"><div class="report-section-title">4. Assignment Information</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Assigned Technician</span><span class="val">' + ((tech.full_name or tech.username) if tech else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Technician Role</span><span class="val">' + (tech.role if tech else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Assigned By</span><span class="val">' + ((p["assigned_by"].full_name or p["assigned_by"].username) if p["assigned_by"] else ((req.manager.full_name or req.manager.username) if req.manager else "—")) + '</span></div>'
    + '<div class="row"><span class="lbl">Assignment Date</span><span class="val">' + dt_date(p["assigned_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Assignment Time</span><span class="val">' + dt_time(p["assigned_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Due Date</span><span class="val">' + dt_date(req.due_date) + '</span></div>'
    + '<div class="row"><span class="lbl">Due Time</span><span class="val">' + dt_time(req.due_date) + '</span></div>'
    + '</div></div>'
    + '<div class="report-section"><div class="report-section-title">5. Work Progress</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Work Accepted Date/Time</span><span class="val">' + fmt(p["accepted_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Work Started Date/Time</span><span class="val">' + fmt(p["started_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Work Completed Date/Time</span><span class="val">' + fmt(p["completed_dt"] or req.completed_date) + '</span></div>'
    + '<div class="row"><span class="lbl">Labor Hours</span><span class="val">' + str(p["labor_hours"]) + ' hrs</span></div>'
    + '<div class="row"><span class="lbl">Final Work Status</span><span class="val"><span class="report-stamp ' + status_cls + '">' + str(req.status) + '</span></span></div>'
    + '</div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Work Performed / Action Taken</div>'
    + '<div class="report-longtext">' + (str(p["work_performed"]) if p["work_performed"] else "—") + '</div></div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Completion Note</div>'
    + '<div class="report-longtext">' + (str(p["completion_notes"]) if p["completion_notes"] else "—") + '</div></div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Root Cause</div>'
    + '<div class="report-longtext">' + (str(p["root_cause"]) if p["root_cause"] else "—") + '</div></div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Recommendation</div>'
    + '<div class="report-longtext">' + (str(p["recommendation"]) if p["recommendation"] else "—") + '</div></div>'
    + '</div>'
    + '<div class="report-section"><div class="report-section-title">6. Materials / Spare Parts Used</div>'
    + '<table class="report-table"><thead><tr><th>#</th><th>Item</th><th>Category</th><th>Qty</th><th>Unit</th><th>Unit Cost</th><th>Total</th><th>Notes</th></tr></thead><tbody>'
    + parts_rows + '</tbody></table></div>'
    + '<div class="report-section"><div class="report-section-title">7. Verification</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Verified By</span><span class="val">' + ((p["verifier"].full_name or p["verifier"].username) if p["verifier"] else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Verification Date</span><span class="val">' + dt_date(p["verified_dt"] or (wo.verified_date if wo else None)) + '</span></div>'
    + '<div class="row"><span class="lbl">Verification Time</span><span class="val">' + dt_time(p["verified_dt"] or (wo.verified_date if wo else None)) + '</span></div>'
    + '<div class="row"><span class="lbl">Verification Status</span><span class="val">' + ("✔ Verified" if (req.status in ("Verified","Closed") or (wo and wo.verified_by_id)) else "Pending Verification") + '</span></div>'
    + '</div>'
    + '<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Verification Note</div>'
    + '<div class="report-longtext">' + (str(p["completion_notes"]) if p["completion_notes"] else "—") + '</div></div>'
    + '</div>'
    + '<div class="report-section"><div class="report-section-title">8. Closure</div><div class="report-kv">'
    + '<div class="row"><span class="lbl">Closed By</span><span class="val">' + ((p["closer"].full_name or p["closer"].username) if p["closer"] and req.status == "Closed" else "—") + '</span></div>'
    + '<div class="row"><span class="lbl">Closed Date</span><span class="val">' + dt_date(p["closed_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Closed Time</span><span class="val">' + dt_time(p["closed_dt"]) + '</span></div>'
    + '<div class="row"><span class="lbl">Final Status</span><span class="val"><span class="report-stamp ' + status_cls + '">' + str(req.status) + '</span></span></div>'
    + '</div>'
    + ('<div style="margin-top:.6rem;"><div class="lbl" style="font-size:.7rem;color:#666;text-transform:uppercase;font-weight:700;">Closure Note / Completion Note</div>'
       + '<div class="report-longtext">' + (str(req.completion_note) if req.completion_note else "—") + '</div></div>' if req.completion_note else "")
    + '</div>'
    + '<div class="report-section"><div class="report-section-title">Digital Signature (Requester Department)</div>' + sig_html + '</div>'
    + '<div class="report-section"><div class="report-section-title">Photos / Attachments</div>' + photos_html + '</div>')

def _detailed_report_header(title, filters, kpis):
    return ('<div class="report-head">'
        '<div class="brand">RORI HOTEL</div>'
        '<div class="dept">Engineering &amp; Maintenance Department</div>'
        '<div class="doctype">' + str(title) + '</div>'
        '</div>'
        '<div class="report-meta">'
        '<div><b>Report Generated:</b> ' + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC") + '</div>'
        '<div><b>Generated By:</b> ' + ((current_user.full_name or current_user.username) if current_user.is_authenticated else "—") + '</div>'
        '<div><b>Report Period From:</b> ' + (str(filters.get("date_from") or "All time")) + '</div>'
        '<div><b>Report Period To:</b> ' + (str(filters.get("date_to") or "All time")) + '</div>'
        '<div><b>Department Filter:</b> ' + (str(filters.get("department_name") or "All Departments")) + '</div>'
        '<div><b>Status Filter:</b> ' + (str(filters.get("status") or "All")) + '</div>'
        '</div>'
        '<div class="report-section"><div class="report-section-title">Report Summary</div>'
        '<div class="report-kv">'
        '<div class="row"><span class="lbl">Total Requests</span><span class="val">' + str(kpis["total"]) + '</span></div>'
        '<div class="row"><span class="lbl">Completed</span><span class="val">' + str(kpis["completed"]) + '</span></div>'
        '<div class="row"><span class="lbl">In Progress</span><span class="val">' + str(kpis["in_progress"]) + '</span></div>'
        '<div class="row"><span class="lbl">Pending</span><span class="val">' + str(kpis["pending"]) + '</span></div>'
        '<div class="row"><span class="lbl">Verified</span><span class="val">' + str(kpis["verified"]) + '</span></div>'
        '<div class="row"><span class="lbl">Closed</span><span class="val">' + str(kpis["closed"]) + '</span></div>'
        '</div></div>')

def _compute_report_kpis(reqs):
    return {
        "total": len(reqs),
        "completed": sum(1 for r in reqs if r.status == "Completed"),
        "in_progress": sum(1 for r in reqs if r.status in ("Assigned","In Progress")),
        "pending": sum(1 for r in reqs if r.status in ("Pending","Approved")),
        "verified": sum(1 for r in reqs if r.status == "Verified"),
        "closed": sum(1 for r in reqs if r.status == "Closed"),
    }

# ══════════════════════════════════════════ DETAILED REPORT ROUTES
@app.route("/reports/detailed")
@login_required
def detailed_report():
    if current_user.role not in ["ADMIN","MANAGER","SUPERVISOR"]: abort(403)
    args = request.args
    reqs = build_filtered_query(args, include_deleted=True).order_by(MaintenanceRequest.created_at.desc()).all()
    if current_user.role == "SUPERVISOR": reqs = [r for r in reqs if not r.is_deleted]
    kpis = _compute_report_kpis(reqs)
    dept_filter_name = None
    if args.get("department"):
        try:
            d = db.session.get(Department, int(args["department"]))
            if d: dept_filter_name = d.name
        except Exception: pass
    filters = dict(args); filters["department_name"] = dept_filter_name
    all_depts = Department.query.order_by(Department.name).all()
    dept_opts = '<option value="">All Departments</option>' + "".join('<option value="' + str(d.id) + '"' + (' selected' if args.get("department")==str(d.id) else '') + '>' + d.name + '</option>' for d in all_depts)
    st_opts = '<option value="">All Statuses</option>' + "".join('<option value="' + s + '"' + (' selected' if args.get("status")==s else '') + '>' + s + '</option>' for s in REQUEST_STATUSES)
    lt_opts = ('<option value="">All Locations</option><option value="Room"' + (' selected' if args.get("location_type")=="Room" else '') + '>Room only</option><option value="Area"' + (' selected' if args.get("location_type")=="Area" else '') + '>Area only</option>')
    body = _detailed_report_header("DETAILED MAINTENANCE WORK ORDER REPORT", filters, kpis)
    if not reqs: body += '<div class="report-section"><div class="report-longtext">No records match the selected filters.</div></div>'
    for idx, req in enumerate(reqs, 1):
        try:
            pack = _build_detailed_report_pack(req)
            body += '<div style="page-break-before:always;"></div>' + _render_detailed_report_block(pack, seq=idx)
        except Exception as e:
            body += '<div class="report-section"><div class="report-longtext">Could not build report for ' + str(req.request_no) + ': ' + str(e) + '</div></div>'
    body += '<div class="report-footer">Rori Hotel — Engineering &amp; Maintenance Department · Detailed Report · Generated by ' + ((current_user.full_name or current_user.username) if current_user.is_authenticated else "—") + ' on ' + datetime.utcnow().strftime("%Y-%m-%d %H:%M") + '<br>Developer: Edom Adinew</div>'
    filter_form = ('<div class="card no-print" style="margin-bottom:1rem;"><form method="get" class="row g-3 align-items-end">'
        '<div class="col-md-3"><label class="form-label">From</label><input type="date" class="form-control" name="date_from" value="' + str(args.get("date_from") or "") + '"></div>'
        '<div class="col-md-3"><label class="form-label">To</label><input type="date" class="form-control" name="date_to" value="' + str(args.get("date_to") or "") + '"></div>'
        '<div class="col-md-3"><label class="form-label">Department</label><select class="form-select" name="department">' + dept_opts + '</select></div>'
        '<div class="col-md-3"><label class="form-label">Status</label><select class="form-select" name="status">' + st_opts + '</select></div>'
        '<div class="col-md-3"><label class="form-label">Location Type</label><select class="form-select" name="location_type">' + lt_opts + '</select></div>'
        '<div class="col-md-3"><button type="submit" class="btn-primary"><i class="fas fa-filter"></i> Apply Filters</button></div>'
        '<div class="col-md-6 d-flex gap-2 justify-content-end">'
        '<button type="button" onclick="window.print()" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-print"></i> Print / Save as PDF</button>'
        '<a href="' + url_for("detailed_report_export", **{k: v for k, v in args.items() if k != "department_name"}) + '" class="btn-primary"><i class="fas fa-file-excel"></i> Download CSV</a>'
        '<a href="' + url_for("detailed_report") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-undo"></i> Reset</a></div></form></div>')
    content = ('<div class="page-header no-print"><div class="page-title"><h1><i class="fas fa-file-alt"></i> <span>Detailed</span> Maintenance Report</h1><p>Full workflow — all historical records from live database</p></div>'
        '<div style="display:flex;gap:.6rem;"><a href="' + url_for("management_reports") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-chart-line"></i> Management Reports</a></div></div>'
        + filter_form + '<div class="report-doc">' + body + '</div>')
    return page("Detailed Report", content)

@app.route("/reports/detailed/export")
@login_required
def detailed_report_export():
    if current_user.role not in ["ADMIN","MANAGER","SUPERVISOR"]: abort(403)
    args = request.args
    reqs = build_filtered_query(args, include_deleted=True).order_by(MaintenanceRequest.created_at.desc()).all()
    if current_user.role == "SUPERVISOR": reqs = [r for r in reqs if not r.is_deleted]
    si = io.StringIO(); cw = csv.writer(si)
    cw.writerow(["RORI HOTEL"]); cw.writerow(["ENGINEERING & MAINTENANCE DEPARTMENT"]); cw.writerow(["DETAILED MAINTENANCE WORK ORDER REPORT"]); cw.writerow([])
    cw.writerow(["Report Generated", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")])
    cw.writerow(["Generated By", (current_user.full_name or current_user.username) if current_user.is_authenticated else "—"])
    cw.writerow(["Period From", args.get("date_from") or "All time"]); cw.writerow(["Period To", args.get("date_to") or "All time"]); cw.writerow([])
    kpis = _compute_report_kpis(reqs)
    cw.writerow(["REPORT SUMMARY"]); cw.writerow(["Total", kpis["total"], "Completed", kpis["completed"], "In Progress", kpis["in_progress"], "Pending", kpis["pending"], "Verified", kpis["verified"], "Closed", kpis["closed"]]); cw.writerow([])
    headers = ["Request No","Work Order No","Internal Request ID","Internal WO ID","Request Date","Request Time","Department","Requester","Requester Role","Priority","Current Status","Location Type","Floor","Room Number","Area / Location","Full Location","Maintenance Item","Category","Problem Description (Full)","Work Instructions / Notes","Assigned Technician","Technician Role","Assigned By","Assignment Date","Assignment Time","Due Date","Due Time","Accepted Date/Time","Started Date/Time","Completed Date/Time","Labor Hours","Work Performed / Action Taken","Completion Note","Root Cause","Recommendation","Materials Used (detail)","Total Materials Cost","Verified By","Verification Date/Time","Verification Status","Verification Note","Closed By","Closed Date/Time","Closure / Completion Note","Digital Signature (Signed By)","Signature Department","Signature Signed At","Signature Verified","Photos / Attachments"]
    cw.writerow(headers)
    for req in reqs:
        pack = _build_detailed_report_pack(req); wo = pack["wo"]; tech = pack["technician"]
        def fmt(dt): return dt.strftime("%Y-%m-%d %H:%M") if dt else ""
        def dt_date(dt): return dt.strftime("%Y-%m-%d") if dt else ""
        def dt_time(dt): return dt.strftime("%H:%M") if dt else ""
        mats = "; ".join((m["name"] + " [" + str(m["category"]) + "] - " + str(m["quantity"]) + " " + str(m["unit"]) + (" (" + m["notes"] + ")" if m["notes"] else "")) for m in pack["parts_used"])
        photos_str = "; ".join((ph["type"] or "Photo") + ": " + ph["filename"] for ph in pack["photos"])
        cw.writerow([req.request_no, wo.work_order_no if wo else "", req.id, wo.id if wo else "", dt_date(req.created_at), dt_time(req.created_at), req.department.name if req.department else "", (req.requested_by.full_name or req.requested_by.username) if req.requested_by else "", req.requested_by.role if req.requested_by else "", req.priority or "MEDIUM", req.status, req.location_type or "", req.floor if req.floor else "", req.room.room_number if req.room else "", req.area.name if req.area else "", req.location_name, req.working_item.name if req.working_item else "", req.category.name if req.category else "", str(req.description or ""), (pack["work_performed"] or ""), (tech.full_name or tech.username) if tech else "", tech.role if tech else "", (pack["assigned_by"].full_name or pack["assigned_by"].username) if pack["assigned_by"] else ((req.manager.full_name or req.manager.username) if req.manager else ""), dt_date(pack["assigned_dt"]), dt_time(pack["assigned_dt"]), dt_date(req.due_date), dt_time(req.due_date), fmt(pack["accepted_dt"]), fmt(pack["started_dt"]), fmt(pack["completed_dt"] or req.completed_date), pack["labor_hours"], (pack["work_performed"] or ""), (pack["completion_notes"] or ""), (pack["root_cause"] or ""), (pack["recommendation"] or ""), mats, round(pack["total_cost"], 2), (pack["verifier"].full_name or pack["verifier"].username) if pack["verifier"] else "", fmt(pack["verified_dt"] or (wo.verified_date if wo else None)), "Verified" if (req.status in ("Verified","Closed") or (wo and wo.verified_by_id)) else "Pending", (pack["completion_notes"] or ""), (pack["closer"].full_name or pack["closer"].username) if (pack["closer"] and req.status == "Closed") else "", fmt(pack["closed_dt"]), (req.completion_note or ""), req.signature_name or "", req.signature_department or "", fmt(req.signature_signed_at), "Yes" if req.signature_verified else "No", photos_str])
    output = make_response(si.getvalue())
    fn = "detailed_report_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S") + ".csv"
    output.headers["Content-Disposition"] = "attachment; filename=" + fn
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@app.route("/reports/workorder/<int:wo_id>")
@login_required
def detailed_report_single_wo(wo_id):
    wo = get_or_404(WorkOrder, wo_id); req = wo.request
    if not req: abort(404)
    if current_user.role == "DEPARTMENT":
        same = (current_user.department_id and req.department_id == current_user.department_id)
        if not same and req.requested_by_id != current_user.id: abort(403)
    if current_user.role == "EMPLOYEE" and req.requested_by_id != current_user.id: abort(403)
    pack = _build_detailed_report_pack(req); kpis = _compute_report_kpis([req])
    filters = {"date_from": req.created_at.strftime("%Y-%m-%d") if req.created_at else "", "date_to": "", "department_name": req.department.name if req.department else ""}
    body = _detailed_report_header("DETAILED WORK ORDER REPORT — " + str(wo.work_order_no), filters, kpis)
    body += _render_detailed_report_block(pack)
    body += '<div class="report-footer">Rori Hotel — Engineering &amp; Maintenance Department · Work Order Report · Generated on ' + datetime.utcnow().strftime("%Y-%m-%d %H:%M") + '<br>Developer: Edom Adinew</div>'
    content = ('<div class="page-header no-print"><div class="page-title"><h1><i class="fas fa-file-alt"></i> <span>Detailed</span> Work Order Report</h1><p>' + str(wo.work_order_no) + ' · ' + str(req.request_no) + '</p></div>'
        '<div style="display:flex;gap:.6rem;flex-wrap:wrap;"><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-arrow-left"></i> Back</a>'
        '<button type="button" onclick="window.print()" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-print"></i> Print / Save as PDF</button>'
        '<a href="' + url_for("detailed_report_single_wo_export", wo_id=wo.id) + '" class="btn-primary"><i class="fas fa-file-excel"></i> Download CSV</a></div></div>'
        + '<div class="report-doc">' + body + '</div>')
    return page("WO Report", content)

@app.route("/reports/workorder/<int:wo_id>/export")
@login_required
def detailed_report_single_wo_export(wo_id):
    wo = get_or_404(WorkOrder, wo_id); req = wo.request
    if not req: abort(404)
    if current_user.role == "DEPARTMENT":
        same = (current_user.department_id and req.department_id == current_user.department_id)
        if not same and req.requested_by_id != current_user.id: abort(403)
    if current_user.role == "EMPLOYEE" and req.requested_by_id != current_user.id: abort(403)
    pack = _build_detailed_report_pack(req); tech = pack["technician"]
    si = io.StringIO(); cw = csv.writer(si)
    cw.writerow(["RORI HOTEL"]); cw.writerow(["ENGINEERING & MAINTENANCE DEPARTMENT"]); cw.writerow(["DETAILED WORK ORDER REPORT — " + str(wo.work_order_no)]); cw.writerow([])
    def row(k, v): cw.writerow([k, v])
    row("Request No", req.request_no); row("Work Order No", wo.work_order_no)
    row("Internal Request ID", req.id); row("Internal WO ID", wo.id)
    row("Department", req.department.name if req.department else "")
    row("Requester", (req.requested_by.full_name or req.requested_by.username) if req.requested_by else ""); row("Requester Role", req.requested_by.role if req.requested_by else "")
    row("Priority", req.priority or ""); row("Current Status", req.status); row("Location Type", req.location_type or "")
    row("Floor", req.floor if req.floor else ""); row("Room", req.room.room_number if req.room else ""); row("Area", req.area.name if req.area else ""); row("Full Location", req.location_name)
    row("Maintenance Item", req.working_item.name if req.working_item else ""); row("Category", req.category.name if req.category else "")
    row("Problem Description", req.description or ""); row("Work Instructions", pack["work_performed"] or "")
    row("Assigned Technician", (tech.full_name or tech.username) if tech else ""); row("Technician Role", tech.role if tech else "")
    row("Assigned By", (pack["assigned_by"].full_name or pack["assigned_by"].username) if pack["assigned_by"] else "")
    row("Assignment Date/Time", pack["assigned_dt"].strftime("%Y-%m-%d %H:%M") if pack["assigned_dt"] else "")
    row("Due Date/Time", req.due_date.strftime("%Y-%m-%d %H:%M") if req.due_date else "")
    row("Accepted Date/Time", pack["accepted_dt"].strftime("%Y-%m-%d %H:%M") if pack["accepted_dt"] else "")
    row("Started Date/Time", pack["started_dt"].strftime("%Y-%m-%d %H:%M") if pack["started_dt"] else "")
    row("Completed Date/Time", (pack["completed_dt"] or req.completed_date).strftime("%Y-%m-%d %H:%M") if (pack["completed_dt"] or req.completed_date) else "")
    row("Labor Hours", pack["labor_hours"]); row("Completion Note", pack["completion_notes"] or "")
    row("Root Cause", pack["root_cause"] or ""); row("Recommendation", pack["recommendation"] or "")
    cw.writerow([]); cw.writerow(["MATERIALS / SPARE PARTS USED"]); cw.writerow(["Item","Category","Qty","Unit","Unit Cost","Total","Notes"])
    for m in pack["parts_used"]: cw.writerow([m["name"], m["category"], m["quantity"], m["unit"], round(m["unit_cost"],2), round(m["line_total"],2), m["notes"]])
    cw.writerow(["TOTAL","","","","","" + str(round(pack["total_cost"],2)),""]); cw.writerow([])
    cw.writerow(["VERIFICATION"]); row("Verified By", (pack["verifier"].full_name or pack["verifier"].username) if pack["verifier"] else ""); row("Verified Date/Time", (pack["verified_dt"] or (wo.verified_date if wo else None)).strftime("%Y-%m-%d %H:%M") if (pack["verified_dt"] or (wo and wo.verified_date)) else ""); row("Verification Status", "Verified" if (req.status in ("Verified","Closed") or wo.verified_by_id) else "Pending"); row("Verification Note", pack["completion_notes"] or "")
    cw.writerow([]); cw.writerow(["CLOSURE"]); row("Closed By", (pack["closer"].full_name or pack["closer"].username) if (pack["closer"] and req.status=="Closed") else ""); row("Closed Date/Time", pack["closed_dt"].strftime("%Y-%m-%d %H:%M") if pack["closed_dt"] else ""); row("Final Status", req.status); row("Closure / Completion Note", req.completion_note or "")
    cw.writerow([]); cw.writerow(["DIGITAL SIGNATURE"]); row("Signed By", req.signature_name or ""); row("Signature Dept", req.signature_department or ""); row("Signed At", req.signature_signed_at.strftime("%Y-%m-%d %H:%M") if req.signature_signed_at else ""); row("Signature Verified", "Yes" if req.signature_verified else "No")
    cw.writerow([]); cw.writerow(["PHOTOS / ATTACHMENTS"]); cw.writerow(["Type","Filename"])
    if pack["photos"]:
        for ph in pack["photos"]: cw.writerow([ph["type"] or "Photo", ph["filename"]])
    else: cw.writerow(["","(none)"])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=WO_" + str(wo.work_order_no) + ".csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@app.route("/reports/request/<int:req_id>")
@login_required
def detailed_report_request(req_id):
    req = get_or_404(MaintenanceRequest, req_id)
    wo = WorkOrder.query.filter_by(request_id=req.id).order_by(WorkOrder.created_at.asc()).first()
    if wo: return redirect(url_for("detailed_report_single_wo", wo_id=wo.id))
    if current_user.role == "DEPARTMENT":
        same = (current_user.department_id and req.department_id == current_user.department_id)
        if not same and req.requested_by_id != current_user.id: abort(403)
    if current_user.role == "EMPLOYEE" and req.requested_by_id != current_user.id: abort(403)
    pack = _build_detailed_report_pack(req); kpis = _compute_report_kpis([req])
    filters = {"date_from": req.created_at.strftime("%Y-%m-%d") if req.created_at else "", "date_to": "", "department_name": req.department.name if req.department else ""}
    body = _detailed_report_header("DETAILED MAINTENANCE REQUEST REPORT — " + str(req.request_no), filters, kpis)
    body += _render_detailed_report_block(pack)
    body += '<div class="report-footer">Rori Hotel — Engineering &amp; Maintenance Department · Request Report<br>Developer: Edom Adinew</div>'
    content = ('<div class="page-header no-print"><div class="page-title"><h1><i class="fas fa-file-alt"></i> <span>Detailed</span> Request Report</h1><p>' + str(req.request_no) + '</p></div>'
        '<div style="display:flex;gap:.6rem;flex-wrap:wrap;"><a href="' + url_for("request_detail", req_id=req.id) + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-arrow-left"></i> Back</a>'
        '<button type="button" onclick="window.print()" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-print"></i> Print / Save as PDF</button></div></div>'
        '<div class="report-doc">' + body + '</div>')
    return page("Request Report", content)

# ══════════════════════════════════════════ DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():
    if current_user.role in STAFF_ROLES: return redirect(url_for("workorders_list"))
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    args = request.args
    kpis = get_kpis(args); trends = get_trends(args); statuses = get_status_stats(args)
    departments = get_dept_stats(args); dept_completion = get_dept_completion(args)
    priorities = get_priority_stats(args); categories = get_category_stats(args); floors = get_floor_stats(args)
    tech_workload = get_technician_workload(args); activity = get_recent_activity(10); inventory = get_inventory_summary()
    recent_reqs = build_filtered_query(args).order_by(MaintenanceRequest.created_at.desc()).limit(15).all()
    all_depts = Department.query.order_by(Department.name).all()
    all_cats = Category.query.order_by(Category.name).all()
    all_rooms = Room.query.order_by(func.cast(Room.room_number, db.Integer).asc()).all()
    all_areas = Area.query.order_by(Area.name).all()
    all_floors = [f.floor_number for f in Floor.query.order_by(Floor.floor_number).all()]
    if not all_floors: all_floors = sorted({r.floor for r in Room.query.all()})
    chart_data = {"trends": trends, "statuses": statuses, "departments": departments, "dept_completion": dept_completion, "priorities": priorities, "categories": categories, "floors": floors}
    return render_template_string(DASHBOARD_TEMPLATE, kpis=kpis, work_orders={"total": WorkOrder.query.count()}, top_locations=[], staff_stats=tech_workload, inventory=inventory, recent_activity=activity, recent_requests=recent_reqs, all_departments=all_depts, all_categories=all_cats, all_rooms=all_rooms, all_areas=all_areas, all_floors=all_floors, chart_data=chart_data, filters={k: v for k, v in args.items()}, technician_workload=tech_workload, dept_completion=dept_completion, current_user=current_user)

DASHBOARD_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Manager Dashboard | Rori Hotel</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:linear-gradient(135deg,rgba(15,23,42,0.88),rgba(30,41,59,0.88)),url('/static/rori_hotel_bg.jpg') center center/cover no-repeat fixed;min-height:100vh;color:#e2e8f0;padding-top:70px}
.navbar{background:rgba(15,23,42,0.95)!important;backdrop-filter:blur(16px);border-bottom:1px solid rgba(245,158,11,0.25);padding:.75rem 1.5rem}
.navbar-brand{font-weight:800;font-size:1.3rem;color:#f59e0b!important}
.nav-link{color:#cbd5e1!important;padding:.5rem 1rem!important;border-radius:40px;font-size:.9rem}
.nav-link i{color:#f59e0b;margin-right:4px}
.nav-link:hover{background:rgba(245,158,11,0.12);color:#f59e0b!important}
.navbar-toggler{border-color:rgba(245,158,11,0.4)}
.container{max-width:1400px;padding:1.5rem}
.card{background:rgba(15,23,42,0.75);backdrop-filter:blur(12px);border:1px solid rgba(245,158,11,0.2);border-radius:20px;color:#e2e8f0;padding:1.25rem;margin-bottom:1.5rem}
.card h5{color:#f59e0b;font-weight:600}
.metric-card{background:rgba(15,23,42,0.7);backdrop-filter:blur(10px);border:1px solid rgba(245,158,11,0.15);border-radius:20px;padding:1.2rem 1rem;text-align:center;height:100%;transition:transform .15s}
.metric-card:hover{transform:translateY(-2px);border-color:rgba(245,158,11,0.3)}
.metric-value{font-size:2rem;font-weight:800;color:#f8fafc;line-height:1}
.metric-label{font-size:.72rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.6px;margin-top:.35rem}
.metric-icon{font-size:1.4rem;color:#f59e0b;margin-bottom:.35rem}
.table{--bs-table-color:#e2e8f0!important;--bs-table-bg:transparent!important;--bs-table-accent-bg:transparent!important;--bs-table-hover-color:#f8fafc!important;--bs-table-hover-bg:rgba(245,158,11,0.08)!important;color:#e2e8f0!important;background:transparent!important;width:100%;margin-bottom:0;border-color:rgba(245,158,11,0.1)!important}
.table>:not(caption)>*>*{background-color:transparent!important;color:#e2e8f0!important;border-color:rgba(245,158,11,0.08)!important;box-shadow:none!important;padding:10px;font-size:.85rem}
.table thead th{color:#f59e0b!important;border-bottom:2px solid rgba(245,158,11,0.2)!important;font-size:.72rem;text-transform:uppercase;padding:10px;white-space:nowrap;background:transparent!important;font-weight:700}
.table-hover tbody tr:hover>*{background-color:rgba(245,158,11,0.08)!important;color:#f8fafc!important}
.btn{border-radius:40px;font-weight:600;padding:.6rem 1.6rem;border:none}
.btn-primary{background:linear-gradient(135deg,#f59e0b,#d97706);color:#0f172a}
.btn-sm{padding:.35rem .8rem;font-size:.78rem}
.form-control,.form-select{background:rgba(15,23,42,0.6);border:1px solid rgba(245,158,11,0.2);border-radius:12px;color:#e2e8f0;padding:.65rem .9rem}
.form-control:focus,.form-select:focus{background:rgba(15,23,42,0.9);color:#f8fafc;border-color:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,0.15)}
.form-control::placeholder{color:#94a3b8;opacity:.7}
.form-label{color:#cbd5e1;font-weight:500;font-size:.82rem}
.badge{padding:.35rem .75rem;border-radius:20px;font-weight:600;font-size:.72rem}
.chart-box{position:relative;width:100%;height:280px}
.chart-box.tall{height:340px}
.chart-box.donut{height:240px}
.prog-list{display:flex;flex-direction:column;gap:.7rem}
.prog-row{display:flex;flex-direction:column;gap:.3rem}
.prog-top{display:flex;justify-content:space-between;font-size:.78rem}
.prog-top .nm{color:#e5e7eb;font-weight:600}
.prog-top .ct{color:#f59e0b;font-weight:800}
.prog-bar{height:6px;background:rgba(245,158,11,0.1);border-radius:6px;overflow:hidden}
.prog-bar span{display:block;height:100%;border-radius:6px;background:linear-gradient(90deg,#f59e0b,#ec4899)}
.feed{display:flex;flex-direction:column;gap:.4rem}
.feed-item{display:flex;gap:.6rem;padding:.55rem .7rem;background:rgba(15,23,42,0.4);border-left:2px solid #f59e0b;border-radius:9px;font-size:.78rem}
.feed-item .tx{color:#e5e7eb}
.feed-item .tx strong{color:#fff}
.feed-item .tm{font-size:.65rem;color:#6b7280;margin-top:2px}
.empty{text-align:center;padding:2rem 1rem;color:#94a3b8;font-size:.85rem}
.empty i{font-size:1.6rem;color:#f59e0b;opacity:.4;display:block;margin-bottom:.5rem}
.filter-bar{display:flex;gap:.6rem;flex-wrap:wrap;align-items:end;padding:1rem;background:rgba(15,23,42,0.75);backdrop-filter:blur(10px);border-radius:16px;border:1px solid rgba(245,158,11,0.2);margin-bottom:1.5rem}
.filter-bar > div{display:flex;flex-direction:column;gap:.25rem;flex:1;min-width:130px}
.rori-footer{margin-top:3rem;padding:1.5rem 2rem;text-align:center;font-size:.8rem;color:#94a3b8;border-top:1px solid rgba(245,158,11,0.2)}
.rori-footer .dev-name{color:#f59e0b;font-weight:700;letter-spacing:.3px}
@media(max-width:768px){.nav-link{padding:.5rem .8rem!important;font-size:.85rem}.metric-value{font-size:1.5rem}.chart-box{height:220px}.table>:not(caption)>*>*{padding:.6rem .5rem;font-size:.78rem}.table thead th{font-size:.65rem;padding:.6rem .5rem}}
</style></head><body>
<nav class="navbar navbar-expand-lg fixed-top"><div class="container-fluid">
<a class="navbar-brand" href="{{ url_for('dashboard') }}"><i class="fas fa-hotel"></i> Rori Hotel</a>
<button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav"><span class="navbar-toggler-icon"></span></button>
<div class="collapse navbar-collapse" id="nav"><div class="navbar-nav ms-auto">
<a class="nav-link" href="{{ url_for('dashboard') }}"><i class="fas fa-home"></i> Dashboard</a>
<a class="nav-link" href="{{ url_for('central_maintenance') }}"><i class="fas fa-fire-extinguisher"></i> Central</a>
<a class="nav-link" href="{{ url_for('request_create') }}"><i class="fas fa-plus-circle"></i> New</a>
<a class="nav-link" href="{{ url_for('requests_list') }}"><i class="fas fa-tasks"></i> Requests</a>
<a class="nav-link" href="{{ url_for('workorders_list') }}"><i class="fas fa-clipboard-list"></i> Work Orders</a>
<a class="nav-link" href="{{ url_for('detailed_report') }}"><i class="fas fa-file-alt"></i> Detailed Report</a>
<a class="nav-link" href="{{ url_for('rooms_list') }}"><i class="fas fa-door-open"></i> Rooms</a>
<a class="nav-link" href="{{ url_for('areas_list') }}"><i class="fas fa-map-marked-alt"></i> Areas</a>
<a class="nav-link" href="{{ url_for('items_list') }}"><i class="fas fa-th-list"></i> Items</a>
<a class="nav-link" href="{{ url_for('inventory_list') }}"><i class="fas fa-boxes"></i> Inventory</a>
<a class="nav-link" href="{{ url_for('suppliers_list') }}"><i class="fas fa-truck"></i> Suppliers</a>
<a class="nav-link" href="{{ url_for('employees_list') }}"><i class="fas fa-users"></i> Employees</a>
{% if current_user.role == 'ADMIN' %}
<a class="nav-link" href="{{ url_for('admin_users') }}"><i class="fas fa-user-cog"></i> Users</a>
<a class="nav-link" href="{{ url_for('audit_logs') }}"><i class="fas fa-history"></i> Audit</a>
<a class="nav-link" href="{{ url_for('deleted_requests') }}"><i class="fas fa-archive"></i> Archived</a>
<a class="nav-link" href="{{ url_for('backup_page') }}"><i class="fas fa-archive"></i> Backup</a>
{% endif %}
<a class="nav-link" href="{{ url_for('management_reports') }}"><i class="fas fa-chart-line"></i> Mgmt Reports</a>
<a class="nav-link" href="{{ url_for('reports') }}"><i class="fas fa-chart-bar"></i> Reports</a>
<a class="nav-link" href="{{ url_for('notifications') }}"><i class="fas fa-bell"></i> Notifications</a>
<a class="nav-link" href="{{ url_for('profile') }}"><i class="fas fa-user-circle"></i> {{ current_user.full_name or current_user.username }}</a>
<a class="nav-link" href="{{ url_for('logout') }}"><i class="fas fa-sign-out-alt"></i> Logout</a>
</div></div></div></nav>
<div class="container mt-4">
<div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
<div><h2 style="color:#f59e0b;font-weight:800;margin:0"><i class="fas fa-chart-line"></i> Central Maintenance Dashboard</h2>
<p style="color:#94a3b8;font-size:.85rem;margin:.25rem 0 0">All departments - Real-time analytics</p></div>
<a href="{{ url_for('request_create') }}" class="btn btn-primary"><i class="fas fa-plus-circle"></i> New Request</a>
</div>
<form method="get" class="filter-bar">
<div><label class="form-label">From</label><input type="date" class="form-control" name="date_from" value="{{ filters.get('date_from','') }}"></div>
<div><label class="form-label">To</label><input type="date" class="form-control" name="date_to" value="{{ filters.get('date_to','') }}"></div>
<div><label class="form-label">Department</label><select class="form-select" name="department"><option value="">All</option>{% for d in all_departments %}<option value="{{ d.id }}" {% if filters.get('department') == d.id|string %}selected{% endif %}>{{ d.name }}</option>{% endfor %}</select></div>
<div><label class="form-label">Category</label><select class="form-select" name="category"><option value="">All</option>{% for c in all_categories %}<option value="{{ c.id }}" {% if filters.get('category') == c.id|string %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></div>
<div><label class="form-label">Status</label><select class="form-select" name="status"><option value="">All</option>{% for s in ['Pending','Approved','Assigned','In Progress','Completed','Verified','Closed','Rejected'] %}<option value="{{ s }}" {% if filters.get('status') == s %}selected{% endif %}>{{ s }}</option>{% endfor %}</select></div>
<div style="flex:0"><button class="btn btn-primary" type="submit"><i class="fas fa-filter"></i> Apply</button></div>
<div style="flex:0"><a class="btn btn-sm" href="{{ url_for('dashboard') }}" style="background:#475569;color:#fff;padding:.65rem 1.2rem;border-radius:40px;font-weight:600;font-size:.85rem">Reset</a></div>
</form>
<div class="row g-3 mb-4">
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon"><i class="fas fa-clipboard-list"></i></div><div class="metric-value">{{ kpis.total }}</div><div class="metric-label">Total</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#f59e0b"><i class="fas fa-hourglass-half"></i></div><div class="metric-value">{{ kpis.pending }}</div><div class="metric-label">Pending</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#22c55e"><i class="fas fa-circle-check"></i></div><div class="metric-value">{{ kpis.completed }}</div><div class="metric-label">Completed</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#3b82f6"><i class="fas fa-percent"></i></div><div class="metric-value">{{ kpis.completion_rate }}%</div><div class="metric-label">Rate</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#06b6d4"><i class="fas fa-clock"></i></div><div class="metric-value" style="font-size:1.3rem">{{ kpis.avg_resolution }}</div><div class="metric-label">Avg Time</div></div></div>
<div class="col-6 col-md-2"><div class="metric-card"><div class="metric-icon" style="color:#ef4444"><i class="fas fa-toolbox"></i></div><div class="metric-value">{{ work_orders.total }}</div><div class="metric-label">Work Orders</div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8"><div class="card"><h5 class="mb-3"><i class="fas fa-chart-area"></i> Request Trends</h5><div class="chart-box tall"><canvas id="chartTrends"></canvas></div></div></div>
<div class="col-lg-4"><div class="card"><h5 class="mb-3"><i class="fas fa-chart-pie"></i> Status Distribution</h5><div class="chart-box donut"><canvas id="chartStatus"></canvas></div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6"><div class="card"><h5 class="mb-3"><i class="fas fa-building"></i> Requests by Department</h5><div class="chart-box"><canvas id="chartDept"></canvas></div></div></div>
<div class="col-lg-6"><div class="card"><h5 class="mb-3"><i class="fas fa-check-double"></i> Completion % by Department</h5><div class="chart-box"><canvas id="chartDeptCompletion"></canvas></div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-4"><div class="card"><h5 class="mb-3"><i class="fas fa-fire"></i> Priority Distribution</h5><div class="chart-box donut"><canvas id="chartPriority"></canvas></div></div></div>
<div class="col-lg-4"><div class="card"><h5 class="mb-3"><i class="fas fa-tags"></i> Categories</h5><div class="chart-box"><canvas id="chartCategories"></canvas></div></div></div>
<div class="col-lg-4"><div class="card"><h5 class="mb-3"><i class="fas fa-layer-group"></i> By Floor</h5><div class="chart-box"><canvas id="chartFloors"></canvas></div></div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-6"><div class="card"><h5 class="mb-3"><i class="fas fa-chart-bar"></i> Department Share (%)</h5>
{% if chart_data.departments.labels|length > 0 %}<div class="prog-list">{% for i in range(chart_data.departments.labels|length) %}
<div class="prog-row"><div class="prog-top"><span class="nm">{{ chart_data.departments.labels[i] }}</span><span class="ct">{{ chart_data.departments.values[i] }} - {{ chart_data.departments.percentages[i] }}%</span></div>
<div class="prog-bar"><span style="width:{{ chart_data.departments.percentages[i] }}%"></span></div></div>{% endfor %}</div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No data available</div>{% endif %}</div></div>
<div class="col-lg-6"><div class="card"><h5 class="mb-3"><i class="fas fa-users-gear"></i> Technician Workload</h5>
{% if technician_workload|length > 0 %}<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Technician</th><th>Assigned</th><th>In Progress</th><th>Completed</th><th>Avg Time</th></tr></thead>
<tbody>{% for t in technician_workload %}<tr><td><strong>{{ t.name }}</strong><br><small style="color:#94a3b8">{{ t.role }}</small></td>
<td><span class="badge" style="background:#3b82f6">{{ t.assigned }}</span></td>
<td><span class="badge" style="background:#f59e0b">{{ t.in_progress }}</span></td>
<td><span class="badge" style="background:#22c55e">{{ t.completed }}</span></td>
<td>{{ t.avg_resolution }}</td></tr>{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-users"></i>No technicians</div>{% endif %}</div></div>
</div>
<div class="row g-3 mb-4">
<div class="col-lg-8"><div class="card"><div class="d-flex justify-content-between align-items-center mb-3">
<h5 style="margin:0"><i class="fas fa-clock-rotate-left"></i> Recent Requests</h5>
<a href="{{ url_for('requests_list') }}" class="btn btn-sm" style="background:#475569;color:#fff;padding:.35rem .9rem;border-radius:20px;font-weight:600;font-size:.75rem">View All</a></div>
{% if recent_requests|length > 0 %}<div class="table-responsive"><table class="table table-hover">
<thead><tr><th>Request</th><th>Department</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th><th>Detail</th></tr></thead>
<tbody>{% for r in recent_requests %}<tr><td><a href="{{ url_for('request_detail', req_id=r.id) }}" style="color:#f59e0b;font-weight:600">{{ r.request_no }}</a></td>
<td>{{ r.department.name if r.department else '-' }}</td><td>{{ r.location_name }}</td>
<td><span class="badge" style="background:{{ '#ef4444' if r.priority=='URGENT' else '#f59e0b' if r.priority=='HIGH' else '#3b82f6' if r.priority=='MEDIUM' else '#22c55e' }}">{{ r.priority }}</span></td>
<td><span class="badge" style="background:{{ '#22c55e' if r.status in ['Completed','Verified','Closed'] else '#f59e0b' if r.status=='Pending' else '#3b82f6' if r.status=='Approved' else '#8b5cf6' if r.status in ['Assigned','In Progress'] else '#6b7280' }}">{{ r.status }}</span></td>
<td style="color:#94a3b8;font-size:.78rem">{{ r.created_at.strftime('%b %d') if r.created_at else '-' }}</td>
<td><a href="{{ url_for('detailed_report_request', req_id=r.id) }}" class="btn btn-sm" style="background:#C5A059;color:#0f172a;padding:.2rem .6rem;border-radius:8px;font-size:.7rem;font-weight:700">Report</a></td></tr>{% endfor %}</tbody></table></div>
{% else %}<div class="empty"><i class="fas fa-inbox"></i>No requests</div>{% endif %}</div></div>
<div class="col-lg-4"><div class="card"><h5 class="mb-3"><i class="fas fa-wave-square"></i> Activity</h5>
{% if recent_activity|length > 0 %}<div class="feed">{% for a in recent_activity %}
<div class="feed-item"><i class="fas fa-bolt" style="color:#f59e0b;margin-top:.15rem"></i><div style="flex:1"><div class="tx"><strong>{{ a.user }}</strong> - {{ a.action }}</div><div class="tm">{{ a.time }}</div></div></div>{% endfor %}</div>
{% else %}<div class="empty"><i class="fas fa-wave-square"></i>No activity</div>{% endif %}</div>
<div class="card"><h5 class="mb-3"><i class="fas fa-boxes"></i> Inventory Snapshot</h5><div class="prog-list">
<div class="prog-row"><div class="prog-top"><span class="nm">Total Parts</span><span class="ct">{{ inventory.total_parts }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Low Stock</span><span class="ct" style="color:#f59e0b">{{ inventory.low_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Out of Stock</span><span class="ct" style="color:#ef4444">{{ inventory.out_of_stock }}</span></div></div>
<div class="prog-row"><div class="prog-top"><span class="nm">Total Value</span><span class="ct">${{ inventory.total_value }}</span></div></div></div></div></div></div></div>
<div class="rori-footer"><div>Rori Hotel — Maintenance Management System</div><div style="margin-top:.35rem;">Developer: <span class="dev-name">Edom Adinew</span></div></div>
</div>
<script>
window.DASHBOARD_DATA = {{ chart_data|tojson }};
(function(){
'use strict';
if(typeof Chart === 'undefined') return;
var D = window.DASHBOARD_DATA || {};
Chart.defaults.color = '#94a3b8'; Chart.defaults.borderColor = 'rgba(245,158,11,0.1)'; Chart.defaults.font.family = "'Inter', system-ui, sans-serif"; Chart.defaults.font.size = 11;
var TT = {backgroundColor:'rgba(15,23,42,0.97)', borderColor:'rgba(245,158,11,0.5)', borderWidth:1, titleColor:'#fff', bodyColor:'#e5e7eb', padding:11, cornerRadius:10};
var C = {amber:'#f59e0b', green:'#22c55e', blue:'#3b82f6', purple:'#8b5cf6', cyan:'#06b6d4', pink:'#ec4899', red:'#ef4444', gray:'#9ca3af'};
function gr(c, a, b){var g = c.createLinearGradient(0,0,0,340); g.addColorStop(0,a); g.addColorStop(1,b); return g;}
function em(el, i, m){if(!el || !el.parentElement) return; el.parentElement.innerHTML='<div class="empty"><i class="fas '+i+'"></i>'+m+'</div>';}
(function(){var el = document.getElementById('chartTrends'); if(!el) return; var t = D.trends; if(!t || !t.labels || !t.labels.length){em(el,'fa-chart-area','No data available'); return;} var c = el.getContext('2d');
new Chart(c, {type:'line', data:{labels:t.labels, datasets:[
{label:'Total', data:t.total, borderColor:C.amber, borderWidth:2.5, fill:true, backgroundColor:gr(c,'rgba(245,158,11,0.35)','rgba(245,158,11,0.01)'), tension:0.4, pointRadius:0, pointHoverRadius:6},
{label:'Completed', data:t.completed, borderColor:C.green, borderWidth:2.2, fill:true, backgroundColor:gr(c,'rgba(34,197,94,0.2)','rgba(34,197,94,0.01)'), tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'Pending', data:t.pending, borderColor:C.red, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5},
{label:'In Progress', data:t.in_progress, borderColor:C.purple, borderWidth:2, fill:false, tension:0.4, pointRadius:0, pointHoverRadius:5}
]}, options:{responsive:true, maintainAspectRatio:false, interaction:{intersect:false, mode:'index'}, plugins:{legend:{position:'top', align:'end', labels:{boxWidth:8, boxHeight:8, padding:14, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}, scales:{x:{grid:{color:'rgba(245,158,11,0.05)'}, ticks:{maxRotation:0, autoSkip:true, maxTicksLimit:10}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});})();
(function(){var el = document.getElementById('chartStatus'); if(!el) return; var s = D.statuses; if(!s || !s.labels || !s.labels.length){em(el,'fa-chart-pie','No data available'); return;} var map = {'Pending':C.amber, 'Approved':C.blue, 'Assigned':C.purple, 'In Progress':C.purple, 'Completed':C.green, 'Verified':C.cyan, 'Closed':'#16a34a', 'Rejected':C.red, 'Overdue':C.red};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:s.labels, datasets:[{data:s.values, backgroundColor:s.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#1e293b', borderWidth:3, hoverOffset:8}]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%', plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});})();
(function(){var el = document.getElementById('chartDept'); if(!el) return; var d = D.departments; if(!d || !d.labels || !d.labels.length){em(el,'fa-building','No data available'); return;} var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[{label:'Requests', data:d.values, backgroundColor:gr(c,'rgba(245,158,11,0.95)','rgba(236,72,153,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT}, scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});})();
(function(){var el = document.getElementById('chartDeptCompletion'); if(!el) return; var d = D.dept_completion; if(!d || !d.labels || !d.labels.length){em(el,'fa-check-double','No data available'); return;} var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:d.labels, datasets:[{label:'Total', data:d.totals, backgroundColor:'rgba(148,163,184,0.35)', borderRadius:8, borderSkipped:false, maxBarThickness:28}, {label:'Completed', data:d.completed, backgroundColor:gr(c,'rgba(34,197,94,0.95)','rgba(16,185,129,0.5)'), borderRadius:8, borderSkipped:false, maxBarThickness:28}]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{position:'top', labels:{boxWidth:8, boxHeight:8, padding:10, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}, scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:10}}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});})();
(function(){var el = document.getElementById('chartPriority'); if(!el) return; var p = D.priorities; if(!p || !p.labels || !p.labels.length){em(el,'fa-fire','No data available'); return;} var map = {'URGENT':C.red, 'HIGH':C.amber, 'MEDIUM':C.blue, 'LOW':C.green};
new Chart(el.getContext('2d'), {type:'doughnut', data:{labels:p.labels, datasets:[{data:p.values, backgroundColor:p.labels.map(function(l){return map[l] || C.gray;}), borderColor:'#1e293b', borderWidth:3, hoverOffset:8}]}, options:{responsive:true, maintainAspectRatio:false, cutout:'68%', plugins:{legend:{position:'bottom', labels:{boxWidth:8, boxHeight:8, padding:8, usePointStyle:true, pointStyle:'circle', font:{size:10, weight:'600'}}}, tooltip:TT}}});})();
(function(){var el = document.getElementById('chartCategories'); if(!el) return; var x = D.categories; if(!x || !x.labels || !x.labels.length){em(el,'fa-tags','No data available'); return;} var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(56,189,248,0.95)','rgba(139,92,246,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:30}]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT}, scales:{x:{grid:{display:false}, ticks:{maxRotation:45, font:{size:9}}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});})();
(function(){var el = document.getElementById('chartFloors'); if(!el) return; var x = D.floors; if(!x || !x.labels || !x.labels.length){em(el,'fa-layer-group','No data available'); return;} var c = el.getContext('2d');
new Chart(c, {type:'bar', data:{labels:x.labels, datasets:[{label:'Requests', data:x.values, backgroundColor:gr(c,'rgba(139,92,246,0.95)','rgba(56,189,248,0.4)'), borderRadius:8, borderSkipped:false, maxBarThickness:36}]}, options:{responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}, tooltip:TT}, scales:{x:{grid:{display:false}}, y:{beginAtZero:true, grid:{color:'rgba(245,158,11,0.07)'}, ticks:{precision:0}}}}});})();
})();
</script></body></html>"""

# ══════════════════════════════════════════ MANAGEMENT REPORTS
@app.route("/management/reports")
@role_required("ADMIN", "MANAGER")
def management_reports():
    period = request.args.get("period", "daily"); dept_filter = request.args.get("department", "")
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_filter:
        dept = Department.query.filter_by(name=dept_filter).first()
        if dept: q = q.filter_by(department_id=dept.id)
    now = datetime.utcnow()
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date + timedelta(days=1)
        q = q.filter(MaintenanceRequest.created_at >= start_date, MaintenanceRequest.created_at < end_date)
    elif period == "weekly":
        start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0); end_date = start_date + timedelta(days=7)
        q = q.filter(MaintenanceRequest.created_at >= start_date, MaintenanceRequest.created_at < end_date)
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = start_date.replace(day=28) + timedelta(days=4); end_date = next_month.replace(day=1)
        q = q.filter(MaintenanceRequest.created_at >= start_date, MaintenanceRequest.created_at < end_date)
    else:
        start_date = now - timedelta(days=30); end_date = now
        q = q.filter(MaintenanceRequest.created_at >= start_date, MaintenanceRequest.created_at <= end_date)
    reqs = q.all(); total = len(reqs)
    completed = sum(1 for r in reqs if r.status in ["Completed","Verified","Closed"])
    pending = sum(1 for r in reqs if r.status in ["Pending","Approved"]); in_progress = sum(1 for r in reqs if r.status in ["Assigned","In Progress"])
    work_orders = WorkOrder.query.filter(WorkOrder.request_id.in_([r.id for r in reqs])).all()
    total_hours = sum(wo.labor_hours or 0 for wo in work_orders)
    dept_counts = defaultdict(int)
    for r in reqs: dept_counts[r.department.name if r.department else "Unspecified"] += 1
    staff_work = defaultdict(lambda: {"assigned": 0, "completed": 0, "hours": 0})
    for wo in work_orders:
        if wo.assigned_to:
            name = wo.assigned_to.full_name or wo.assigned_to.username
            staff_work[name]["assigned"] += 1
            if wo.status in ["Completed","Verified","Closed"]: staff_work[name]["completed"] += 1
            staff_work[name]["hours"] += wo.labor_hours or 0
    daily_breakdown = []
    if period == "weekly":
        for i in range(7):
            day_date = start_date + timedelta(days=i)
            day_reqs = [r for r in reqs if r.created_at.date() == day_date.date()]
            daily_breakdown.append({"day": day_date.strftime("%A"), "date": day_date.strftime("%Y-%m-%d"), "total": len(day_reqs), "completed": sum(1 for r in day_reqs if r.status in ["Completed","Verified","Closed"])})
    recent_detailed = q.order_by(MaintenanceRequest.created_at.desc()).limit(50).all()
    detail_rows = []
    for r in recent_detailed:
        wo = WorkOrder.query.filter_by(request_id=r.id).order_by(WorkOrder.created_at.asc()).first()
        tech = (wo.assigned_to.full_name or wo.assigned_to.username) if (wo and wo.assigned_to) else ((r.assigned_to.full_name or r.assigned_to.username) if r.assigned_to else "—")
        detail_rows.append('<tr>'
            '<td><a href="' + url_for("request_detail", req_id=r.id) + '">' + str(r.request_no) + '</a>' + (('<br><small style="color:var(--rori-gold)">' + str(wo.work_order_no) + '</small>') if wo else '') + '</td>'
            '<td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td>'
            '<td>' + str(r.department.name if r.department else "—") + '</td>'
            '<td>' + str(r.location_name) + '</td>'
            '<td>' + str(r.working_item.name if r.working_item else "—") + '</td>'
            '<td>' + str(tech) + '</td>'
            '<td><span class="badge badge-' + ({"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger"}.get(r.status,"secondary")) + '">' + str(r.status) + '</span></td>'
            '<td style="white-space:nowrap;"><a class="btn-primary" href="' + url_for("detailed_report_request", req_id=r.id) + '" style="padding:.35rem .7rem;font-size:.75rem;"><i class="fas fa-file-alt"></i> Detail</a></td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-chart-line"></i> <span>Management</span> Reports</h1><p>Detailed analytics and performance metrics</p></div>'
         '<div style="display:flex;gap:1rem;flex-wrap:wrap;" class="no-print">'
         '<a href="' + url_for("detailed_report") + '" class="btn-primary"><i class="fas fa-file-alt"></i> Full Detailed Report</a>'
         '<a href="' + url_for("management_reports_export", period=period, department=dept_filter) + '" class="btn-primary"><i class="fas fa-file-excel"></i> Download Summary CSV</a>'
         '<button onclick="window.print()" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-print"></i> Print / PDF</button></div></div>'
         '<div class="card" style="margin-bottom:2rem;"><form method="get" class="row g-3 align-items-end">'
         '<div class="col-md-3"><label class="form-label">Period</label><select name="period" class="form-select"><option value="daily" ' + ('selected' if period=="daily" else '') + '>Daily</option><option value="weekly" ' + ('selected' if period=="weekly" else '') + '>Weekly</option><option value="monthly" ' + ('selected' if period=="monthly" else '') + '>Monthly</option><option value="custom" ' + ('selected' if period=="custom" else '') + '>Custom (Last 30 Days)</option></select></div>'
         '<div class="col-md-3"><label class="form-label">Department</label><select name="department" class="form-select"><option value="">All Departments</option>' + "".join('<option value="' + d.name + '"' + (' selected' if dept_filter==d.name else '') + '>' + d.name + '</option>' for d in Department.query.all()) + '</select></div>'
         '<div class="col-md-3"><button type="submit" class="btn-primary w-100"><i class="fas fa-filter"></i> Apply Filters</button></div></form></div>'
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total Requests</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Completed</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--info);"><i class="fas fa-spinner"></i></div><div class="kpi-value">' + str(in_progress) + '</div><div class="kpi-label">In Progress</div></div>'
         '<div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(total_hours) + ' hrs</div><div class="kpi-label">Work Hours</div></div></div>'
         '<div class="row g-3"><div class="col-md-6"><div class="card"><h5>Department Workload</h5><ul class="list-group list-group-flush" style="background:transparent;">' + "".join('<li class="list-group-item d-flex justify-content-between align-items-center"><span>' + k + '</span><span class="badge badge-info rounded-pill">' + str(v) + '</span></li>' for k, v in sorted(dept_counts.items(), key=lambda x: -x[1])) + '</ul></div></div>'
         '<div class="col-md-6"><div class="card"><h5>Staff Performance</h5><div class="table-responsive"><table class="table"><thead><tr><th>Staff</th><th>Assigned</th><th>Completed</th><th>Hours</th></tr></thead><tbody>' + "".join('<tr><td>' + k + '</td><td><span class="badge badge-info">' + str(v["assigned"]) + '</span></td><td><span class="badge badge-success">' + str(v["completed"]) + '</span></td><td>' + str(round(v["hours"],1)) + ' hrs</td></tr>' for k, v in sorted(staff_work.items(), key=lambda x: -x[1]["hours"])) + '</tbody></table></div></div></div></div>')
    if period == "weekly" and daily_breakdown:
        c += '<div class="card mt-4"><h5>Daily Breakdown (This Week)</h5><div class="table-responsive"><table class="table"><thead><tr><th>Day</th><th>Date</th><th>Total Requests</th><th>Completed</th></tr></thead><tbody>' + "".join('<tr><td>' + d["day"] + '</td><td>' + d["date"] + '</td><td>' + str(d["total"]) + '</td><td>' + str(d["completed"]) + '</td></tr>' for d in daily_breakdown) + '</tbody></table></div></div>'
    c += ('<div class="card mt-4"><div class="d-flex justify-content-between align-items-center mb-3"><h5 style="margin:0;color:var(--rori-gold);"><i class="fas fa-list"></i> Detailed Recent Records</h5><a href="' + url_for("detailed_report") + '" class="btn-primary" style="padding:.55rem 1.2rem;font-size:.85rem;"><i class="fas fa-external-link-alt"></i> Open Full Detailed Report</a></div><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request / WO</th><th>Created</th><th>Department</th><th>Location</th><th>Item</th><th>Technician</th><th>Status</th><th>Report</th></tr></thead><tbody>' + ("".join(detail_rows) if detail_rows else '<tr><td colspan="8" style="text-align:center;color:var(--text-secondary);">No records found.</td></tr>') + '</tbody></table></div></div>')
    if total == 0: c += '<div class="alert alert-warning mt-4"><i class="fas fa-info-circle"></i> No maintenance records found for the selected period.</div>'
    return page("Management Reports", c)

@app.route("/management/reports/export")
@role_required("ADMIN", "MANAGER")
def management_reports_export():
    period = request.args.get("period", "daily"); dept_filter = request.args.get("department", "")
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_filter:
        dept = Department.query.filter_by(name=dept_filter).first()
        if dept: q = q.filter_by(department_id=dept.id)
    now = datetime.utcnow()
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0); q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "weekly":
        start_date = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0); q = q.filter(MaintenanceRequest.created_at >= start_date)
    elif period == "monthly":
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0); q = q.filter(MaintenanceRequest.created_at >= start_date)
    reqs = q.all()
    si = io.StringIO(); cw = csv.writer(si)
    cw.writerow(["Rori Hotel Maintenance Management Summary Report"]); cw.writerow(["Period", period, "Generated By", current_user.full_name or current_user.username, "Date", now.strftime("%Y-%m-%d %H:%M")]); cw.writerow([])
    cw.writerow(["Request No","Work Order No","Department","Location","Item","Priority","Status","Technician","Completed Date","Labor Hours","Materials Used","Total Materials Cost"])
    for r in reqs:
        wo = WorkOrder.query.filter_by(request_id=r.id).first()
        tech_name = ""
        if wo and wo.assigned_to: tech_name = wo.assigned_to.full_name or wo.assigned_to.username
        elif r.assigned_to: tech_name = r.assigned_to.full_name or r.assigned_to.username
        mats = ""; total_cost = 0
        if wo:
            parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
            mats = "; ".join((p.part.part_name if p.part else ("Part#" + str(p.part_id))) + " x" + str(p.quantity) for p in parts)
            total_cost = sum((p.quantity or 0) * (p.unit_cost or 0) for p in parts)
        cw.writerow([r.request_no, wo.work_order_no if wo else "", r.department.name if r.department else "N/A", r.location_name, r.working_item.name if r.working_item else "", r.priority, r.status, tech_name, r.completed_date.strftime("%Y-%m-%d %H:%M") if r.completed_date else "", wo.labor_hours if wo else 0, mats, round(total_cost,2)])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=summary_" + period + "_" + now.strftime("%Y%m%d") + ".csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

# ══════════════════════════════════════════ CENTRAL MAINTENANCE
@app.route("/maintenance")
@role_required("ADMIN","MANAGER","SUPERVISOR")
def central_maintenance():
    base = MaintenanceRequest.query.filter_by(is_deleted=False)
    counts = {s: base.filter_by(status=s).count() for s in REQUEST_STATUSES}
    total = base.count()
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    tech_rows = []
    for u in staff:
        wos = WorkOrder.query.filter_by(assigned_to_id=u.id).all()
        tech_rows.append({"user": u, "assigned": len(wos), "in_progress": sum(1 for w in wos if w.status == "In Progress"), "completed": sum(1 for w in wos if w.status in ("Completed","Verified","Closed")), "pending": sum(1 for w in wos if w.status in ("Pending","Assigned"))})
    tech_rows.sort(key=lambda x: -x["assigned"])
    rooms_total = Room.query.count()
    room_reqs = (MaintenanceRequest.query.filter(MaintenanceRequest.room_id.isnot(None), MaintenanceRequest.is_deleted == False).count())
    room_open = (MaintenanceRequest.query.filter(MaintenanceRequest.room_id.isnot(None), MaintenanceRequest.is_deleted == False).filter(MaintenanceRequest.status.in_(["Pending","Approved","Assigned","In Progress","Overdue"])).count())
    areas_total = Area.query.filter_by(is_active=True).count()
    area_reqs = (MaintenanceRequest.query.filter(MaintenanceRequest.area_id.isnot(None), MaintenanceRequest.is_deleted == False).count())
    area_open = (MaintenanceRequest.query.filter(MaintenanceRequest.area_id.isnot(None), MaintenanceRequest.is_deleted == False).filter(MaintenanceRequest.status.in_(["Pending","Approved","Assigned","In Progress","Overdue"])).count())
    recent = base.order_by(MaintenanceRequest.created_at.desc()).limit(10).all()
    recent_rows = []
    for r in recent:
        bc = {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(r.status, "secondary")
        recent_rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);font-weight:600;text-decoration:none;">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.department.name if r.department else "—") + '</td><td><span class="badge badge-' + bc + '">' + str(r.status) + '</span></td><td>' + str(r.priority) + '</td><td>' + ((r.assigned_to.full_name or r.assigned_to.username) if r.assigned_to else "—") + '</td><td><a class="btn-primary" href="' + url_for("detailed_report_request", req_id=r.id) + '" style="padding:.25rem .6rem;font-size:.72rem;"><i class="fas fa-file-alt"></i></a></td></tr>')
    tech_rows_html = "".join('<tr><td><strong>' + ((t["user"].full_name or t["user"].username)) + '</strong><br><small style="color:var(--text-secondary)">' + str(t["user"].role) + '</small></td><td><span class="rpro-chip gold">' + str(t["assigned"]) + '</span></td><td><span class="rpro-chip orange">' + str(t["pending"]) + '</span></td><td><span class="rpro-chip blue">' + str(t["in_progress"]) + '</span></td><td><span class="rpro-chip green">' + str(t["completed"]) + '</span></td></tr>' for t in tech_rows)
    def status_tile(label, value, color):
        return ('<div class="kpi-card" style="padding:1rem .75rem;text-align:center;"><div class="kpi-value" style="font-size:1.6rem;color:' + color + ';">' + str(value) + '</div><div class="kpi-label" style="font-size:.68rem;">' + label + '</div></div>')
    content = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-fire-extinguisher"></i> <span>Central</span> Maintenance</h1><p>Unified view</p></div></div>'
        '<div class="kpi-grid" style="margin-bottom:1.5rem;">'
        + status_tile("Total", total, "var(--text-primary)") + status_tile("Pending", counts.get("Pending",0), "var(--warning)") + status_tile("Approved", counts.get("Approved",0), "var(--info)") + status_tile("Assigned", counts.get("Assigned",0), "var(--info)") + status_tile("In Progress", counts.get("In Progress",0), "var(--info)") + status_tile("Completed", counts.get("Completed",0), "var(--success)") + status_tile("Verified", counts.get("Verified",0), "var(--success)") + status_tile("Closed", counts.get("Closed",0), "var(--text-secondary)")
        + '</div>'
        '<div class="row g-3 mb-3">'
        '<div class="col-lg-4"><div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-door-open"></i> Rooms</div><div style="display:flex;justify-content:space-between;"><span>Total</span><strong>' + str(rooms_total) + '</strong></div><div style="display:flex;justify-content:space-between;"><span>Open</span><strong>' + str(room_open) + '</strong></div></div></div>'
        '<div class="col-lg-4"><div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-map-marked-alt"></i> Areas</div><div style="display:flex;justify-content:space-between;"><span>Total</span><strong>' + str(areas_total) + '</strong></div><div style="display:flex;justify-content:space-between;"><span>Open</span><strong>' + str(area_open) + '</strong></div></div></div>'
        '<div class="col-lg-4"><div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-clipboard-list"></i> Work Orders</div><div style="display:flex;justify-content:space-between;"><span>Total</span><strong>' + str(WorkOrder.query.count()) + '</strong></div></div></div>'
        '</div>'
        '<div class="rpro-card"><div class="rpro-card-title"><i class="fas fa-clock-rotate-left"></i> Recent Requests</div><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Dept</th><th>Status</th><th>Priority</th><th>Assigned</th><th>Report</th></tr></thead><tbody>' + ("".join(recent_rows) if recent_rows else '<tr><td colspan="7" style="text-align:center;">No requests.</td></tr>') + '</tbody></table></div></div>')
    return page("Central Maintenance", content)

# ══════════════════════════════════════════ DEPT / EMPLOYEE DASHBOARDS
@app.route("/department")
@login_required
@role_required("DEPARTMENT")
def department_dashboard():
    dept_id = current_user.department_id
    q = MaintenanceRequest.query.filter_by(is_deleted=False)
    if dept_id: q = q.filter(db.or_(MaintenanceRequest.department_id == dept_id, MaintenanceRequest.requested_by_id == current_user.id))
    else: q = q.filter(MaintenanceRequest.requested_by_id == current_user.id)
    reqs = q.order_by(MaintenanceRequest.created_at.desc()).all()
    total = len(reqs); pending = sum(1 for r in reqs if r.status == "Pending"); in_progress = sum(1 for r in reqs if r.status == "In Progress"); completed = sum(1 for r in reqs if r.status in ["Completed","Verified","Closed"])
    def bd(st): return {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(st,"secondary")
    rows = []
    for r in reqs[:30]:
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);">' + str(r.request_no) + '</a></td><td>' + str(r.location_name) + '</td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.priority) + '</td><td><span class="badge badge-' + bd(r.status) + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d") if r.created_at else "—") + '</td><td><a class="btn-primary" href="' + url_for("detailed_report_request", req_id=r.id) + '" style="padding:.25rem .6rem;font-size:.72rem;"><i class="fas fa-file-alt"></i></a></td></tr>')
    dept_name = current_user.department.name if current_user.department else "My Department"
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-building"></i> <span>' + str(dept_name) + '</span> Dashboard</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New</a></div>'
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total</div></div><div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div><div class="kpi-card"><div class="kpi-icon" style="color:var(--info);"><i class="fas fa-spinner"></i></div><div class="kpi-value">' + str(in_progress) + '</div><div class="kpi-label">In Progress</div></div><div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Done</div></div></div>'
         '<div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-tasks"></i> My Requests</h5><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Item</th><th>Priority</th><th>Status</th><th>Date</th><th>Report</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" style="text-align:center;">No requests yet.</td></tr>') + '</tbody></table></div></div>')
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
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-home"></i> <span>My</span> Dashboard</h1></div><a href="' + url_for("request_create") + '" class="btn-primary"><i class="fas fa-plus"></i> New</a></div>'
         '<div class="card"><h5 style="color:var(--rori-gold);margin-bottom:1rem;"><i class="fas fa-tasks"></i> My Requests</h5><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Request #</th><th>Location</th><th>Priority</th><th>Status</th><th>Date</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" style="text-align:center;">No requests yet</td></tr>') + '</tbody></table></div></div>')
    return page("Employee Dashboard", c)

# ══════════════════════════════════════════ WORK ORDERS
@app.route("/workorders")
@login_required
def workorders_list():
    if current_user.role == "DEPARTMENT": return redirect(url_for("department_dashboard"))
    if current_user.role == "EMPLOYEE": return redirect(url_for("employee_dashboard"))
    if current_user.role in STAFF_ROLES: wos = WorkOrder.query.filter(db.or_(WorkOrder.assigned_to_id == current_user.id, WorkOrder.assigned_to_id.is_(None))).order_by(WorkOrder.created_at.desc()).all()
    else: wos = WorkOrder.query.order_by(WorkOrder.created_at.desc()).all()
    rows = []
    for wo in wos:
        assigned = (wo.assigned_to.full_name or wo.assigned_to.username) if wo.assigned_to else "Unassigned"
        badge = "success" if wo.status in ["Completed","Verified"] else "warning" if wo.status in ["Pending","Assigned"] else "info"
        rows.append('<tr><td><a href="' + url_for("workorder_detail", wo_id=wo.id) + '" style="color:var(--rori-gold);">' + str(wo.work_order_no) + '</a></td><td>' + str(wo.request.location_name if wo.request else "—") + '</td><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td><td>' + str(wo.request.department.name if wo.request and wo.request.department else "—") + '</td><td>' + str(wo.request.priority if wo.request else "—") + '</td><td><span class="badge badge-' + badge + '">' + str(wo.status) + '</span></td><td>' + str(assigned) + '</td><td><a class="btn-primary" href="' + url_for("detailed_report_single_wo", wo_id=wo.id) + '" style="padding:.25rem .6rem;font-size:.72rem;"><i class="fas fa-file-alt"></i> Detail</a></td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-tasks"></i> <span>Work</span> Orders</h1></div></div>'
         '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Order #</th><th>Location</th><th>Item</th><th>Department</th><th>Priority</th><th>Status</th><th>Assigned</th><th>Report</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="8" style="text-align:center;">No work orders</td></tr>') + '</tbody></table></div></div>')
    return page("Work Orders", c)

@app.route("/workorders/new", methods=["GET","POST"])
@role_required("MANAGER","ADMIN")
def workorder_create():
    req_id = request.args.get("request_id", type=int); req = get_one(MaintenanceRequest, req_id) if req_id else None
    staff = User.query.filter(User.role.in_(STAFF_ROLES), User.active == True).all()
    uo = "".join('<option value="' + str(u.id) + '">' + str(u.full_name or u.username) + ' — ' + str(u.role) + '</option>' for u in staff)
    if request.method == "POST":
        try:
            request_id = request.form.get("request_id", type=int); assigned_to_id = request.form.get("assigned_to_id", type=int); wp = request.form.get("work_performed","")
            if not assigned_to_id: flash("Please select a technician","danger"); return redirect(url_for("workorder_create", request_id=request_id))
            req = get_or_404(MaintenanceRequest, request_id); assigned_user = get_one(User, assigned_to_id)
            existing = WorkOrder.query.filter_by(request_id=req.id).filter(WorkOrder.status != "Completed").first()
            if existing: wo = existing; wo.assigned_to_id = assigned_to_id; wo.status = "Assigned"; wo.work_performed = wp if wp else wo.work_performed
            else: wo = WorkOrder(work_order_no=work_order_no_generator(), request_id=req.id, assigned_to_id=assigned_to_id, status="Assigned", work_performed=wp); db.session.add(wo); db.session.flush()
            log_audit("Create","WorkOrder",wo.id,new_value=wo.work_order_no); req.status = "Assigned"; req.assigned_to_id = assigned_to_id
            log_status_change(req.id,"Assigned",notes="Assigned to " + str(assigned_user.full_name if assigned_user else "?"))
            if assigned_user: notify_assigned_staff(req, wo, assigned_user)
            if req.requested_by_id: notify_users([req.requested_by_id], req.id, "Work Assigned", "Staff assigned to " + str(req.request_no), "Assigned", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Assigned!","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_create", request_id=request_id))
    c = ('<div class="page-header"><div class="page-title"><h1><i class="fas fa-user-plus"></i> Assign Staff</h1></div></div>'
         '<div class="card"><form method="post"><input type="hidden" name="request_id" value="' + str(req.id if req else "") + '">'
         '<div class="mb-3"><label class="form-label">Request</label><input class="form-control" value="' + str(req.request_no if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Location</label><input class="form-control" value="' + str(req.location_name if req else "") + '" disabled></div>'
         '<div class="mb-3"><label class="form-label">Assign To *</label><select class="form-select" name="assigned_to_id" required><option value="">-- Select --</option>' + uo + '</select></div>'
         '<div class="mb-3"><label class="form-label">Instructions</label><textarea class="form-control" name="work_performed" rows="3"></textarea></div>'
         '<button class="btn-primary"><i class="fas fa-save"></i> Assign</button></form></div>')
    return page("Assign Work Order", c)

@app.route("/workorders/<int:wo_id>")
@login_required
def workorder_detail(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    parts = WorkOrderPart.query.filter_by(work_order_id=wo.id).all()
    can_parts_flag = (current_user.role in ["MANAGER","ADMIN"] or (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))
    pr, pt = [], 0
    for p in parts:
        pname = p.part.part_name if p.part else "Part #" + str(p.part_id); psupp = p.part.supplier.company_name if p.part and p.part.supplier else "—"; pun = p.part.unit if p.part else "pcs"
        lt = (p.quantity or 0) * (p.unit_cost or 0); pt += lt
        rem = '<form method="post" action="' + url_for("workorder_part_remove", wo_id=wo.id, part_id=p.id) + '" style="display:inline" onsubmit="return confirm(\'Remove?\')"><button type="submit" class="btn-icon" style="width:32px;height:32px;background:var(--danger);"><i class="fas fa-times"></i></button></form>' if can_parts_flag and wo.status in ["Assigned","In Progress"] else ""
        pr.append('<tr><td>' + str(pname) + '</td><td>' + str(psupp) + '</td><td>' + str(p.quantity) + '</td><td>' + str(pun) + '</td><td>' + str(p.unit_cost or 0) + '</td><td>' + str(lt) + '</td><td>' + str(p.notes or "") + '</td><td>' + rem + '</td></tr>')
    apb = '<a class="btn-primary" href="' + url_for("workorder_part_add", wo_id=wo.id) + '" style="padding:0.5rem 1rem;font-size:0.85rem;"><i class="fas fa-plus"></i> Add Part</a>' if can_parts_flag and wo.status in ["Assigned","In Progress"] else ""
    parts_card = ('<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-boxes"></i> Parts &amp; Materials Used</div>' + apb + '</div>'
                  '<div style="overflow-x:auto;"><table class="table"><thead><tr><th>Part</th><th>Supplier</th><th>Qty</th><th>Unit</th><th>Cost</th><th>Total</th><th>Notes</th><th></th></tr></thead><tbody>' + ("".join(pr) if pr else '<tr><td colspan="8" style="text-align:center;">No parts</td></tr>') + '</tbody></table></div><p style="text-align:right;margin-top:1rem;font-weight:700;color:var(--rori-gold);">Total: ' + str(pt) + '</p></div>')
    ch = '<div style="margin-top:1rem;"><h6 style="color:var(--rori-gold);">Completion Photo:</h6><a href="/static/uploads/maintenance/' + str(wo.completion_photo) + '" target="_blank"><img src="/static/uploads/maintenance/' + str(wo.completion_photo) + '" style="max-width:100%;max-height:250px;border-radius:12px;border:1px solid var(--border-color);"></a></div>' if wo.completion_photo else ""
    actions = '<a href="' + url_for("detailed_report_single_wo", wo_id=wo.id) + '" class="btn-primary w-100" style="background:var(--info);margin-bottom:0.75rem;display:block;text-align:center;"><i class="fas fa-file-alt"></i> Detailed Report</a>'
    if current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id:
        if wo.status == "Assigned": actions += '<form method="post" action="' + url_for("workorder_start", wo_id=wo.id) + '"><button type="submit" class="btn-primary w-100" style="background:var(--warning);margin-bottom:0.75rem;"><i class="fas fa-play"></i> Start Work</button></form>'
        if wo.status == "In Progress": actions += '<a href="' + url_for("workorder_complete", wo_id=wo.id) + '" class="btn-primary w-100" style="background:var(--success);margin-bottom:0.75rem;display:block;text-align:center;"><i class="fas fa-check"></i> Complete</a>'
    if (current_user.role == "ADMIN" or current_user.role == "MANAGER") and wo.status == "Completed":
        actions += '<form method="post" action="' + url_for("workorder_verify", wo_id=wo.id) + '"><button type="submit" class="btn-primary w-100" style="background:var(--info);margin-bottom:0.75rem;"><i class="fas fa-check-double"></i> Verify</button></form>'
    c = ('<div class="page-header"><div class="page-title"><h1>Work Order <span>' + str(wo.work_order_no) + '</span></h1></div>'
        '<div style="display:flex;gap:.5rem;flex-wrap:wrap;"><a href="' + url_for("detailed_report_single_wo", wo_id=wo.id) + '" class="btn-primary"><i class="fas fa-file-alt"></i> Report</a>'
        '<a href="' + url_for("workorders_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);"><i class="fas fa-arrow-left"></i> Back</a></div></div>'
        '<div class="row"><div class="col-md-8"><div class="card"><table class="table"><tr><th>Request</th><td>' + str(wo.request.request_no if wo.request else "—") + '</td></tr><tr><th>Location</th><td>' + str(wo.request.location_name if wo.request else "—") + '</td></tr><tr><th>Item</th><td>' + str(wo.request.working_item.name if wo.request and wo.request.working_item else "—") + '</td></tr><tr><th>Status</th><td>' + str(wo.status) + '</td></tr><tr><th>Assigned</th><td>' + str(wo.assigned_to.full_name if wo.assigned_to else "Unassigned") + '</td></tr><tr><th>Instructions</th><td>' + str(wo.work_performed or "—") + '</td></tr><tr><th>Completion</th><td>' + str(wo.completion_notes or "—") + '</td></tr><tr><th>Root Cause</th><td>' + str(wo.root_cause or "—") + '</td></tr><tr><th>Recommendation</th><td>' + str(wo.recommendation or "—") + '</td></tr></table>' + ch + '</div>' + parts_card + '</div><div class="col-md-4"><div class="card"><h5 style="color:var(--rori-gold);">Actions</h5>' + actions + '</div></div></div>')
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
        log_status_change(wo.request_id,"In Progress",notes="Started by " + str(current_user.full_name)); log_audit("Start","WorkOrder",wo.id,"Assigned","In Progress")
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
            note = request.form.get("completion_note","").strip(); root_cause = request.form.get("root_cause","").strip(); recommendation = request.form.get("recommendation","").strip()
            try: hours = float(request.form.get("labor_hours","0") or "0")
            except: hours = 0.0
            if not note: flash("Completion note required","danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
            fname = None; f = request.files.get("photo")
            if f and f.filename and allowed_file(f.filename):
                ext = f.filename.rsplit(".",1)[-1].lower(); fname = secure_filename("wo_" + str(wo.id) + "_done_" + datetime.now().strftime("%Y%m%d%H%M%S") + "." + ext); f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            wo.completion_notes = note; wo.labor_hours = hours; wo.status = "Completed"; wo.root_cause = root_cause or wo.root_cause; wo.recommendation = recommendation or wo.recommendation
            wo.completed_by_id = current_user.id; wo.completed_date = datetime.utcnow()
            if fname: wo.completion_photo = fname
            if wo.request: wo.request.status = "Completed"; wo.request.completed_date = datetime.utcnow(); wo.request.completion_note = note
            log_status_change(wo.request_id,"Completed",notes="Completed by " + str(current_user.full_name)); log_audit("Complete","WorkOrder",wo.id,"In Progress","Completed")
            managers = User.query.filter(User.role.in_(["MANAGER","ADMIN"])).all()
            notify_users([u.id for u in managers], wo.request_id, "🔔 Work Completed", "WO " + str(wo.work_order_no) + " ready for verification", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            if wo.request and wo.request.requested_by_id: notify_users([wo.request.requested_by_id], wo.request_id, "Work Completed", "Request " + str(wo.request.request_no) + " completed", "Completed", link=url_for("workorder_detail", wo_id=wo.id))
            db.session.commit(); flash("✅ Completed! Waiting for verification.","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_complete", wo_id=wo_id))
    c = ('<div class="page-header"><div class="page-title"><h1>Complete Work Order ' + str(wo.work_order_no) + '</h1></div></div>'
         '<div class="card"><form method="post" enctype="multipart/form-data">'
         '<div class="mb-3"><label class="form-label">Completion Note *</label><textarea name="completion_note" class="form-control" rows="4" required></textarea></div>'
         '<div class="mb-3"><label class="form-label">Root Cause (optional)</label><textarea name="root_cause" class="form-control" rows="2"></textarea></div>'
         '<div class="mb-3"><label class="form-label">Recommendation (optional)</label><textarea name="recommendation" class="form-control" rows="2"></textarea></div>'
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
        if wo.request: wo.request.status = "Verified"; wo.request.manager_id = current_user.id
        if not wo.request.completed_date: wo.request.completed_date = datetime.utcnow()
        log_status_change(wo.request_id,"Verified",notes="Verified by " + str(current_user.full_name)); log_audit("Verify","WorkOrder",wo.id,"Completed","Verified")
        if wo.request: notify_users([wo.request.requested_by_id], wo.request_id, "✅ Verified", "Request " + str(wo.request.request_no) + " verified", "Verified", link=url_for("request_detail", req_id=wo.request_id))
        db.session.commit(); flash("✅ Verified!","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo_id))

# ══════════════════════════════════════════ SUPPLIERS
def supplier_active(s):
    if s is None: return True
    if s.is_active is not None: return s.is_active
    return s.status == "Active"

def supplier_form(s, action, edit):
    def v(f): return str(getattr(s, f) or "") if s else ""
    act = supplier_active(s); a1 = " selected" if act else ""; a2 = "" if act else " selected"
    return ('<div class="page-header"><div class="page-title"><h1>' + ("Edit" if edit else "Add") + ' Supplier</h1></div></div>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier Name *</label><input type="text" class="form-control" name="company_name" value="' + v("company_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Contact</label><input type="text" class="form-control" name="contact_person" value="' + v("contact_person") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Phone</label><input type="text" class="form-control" name="phone" value="' + v("phone") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Email</label><input type="email" class="form-control" name="email" value="' + v("email") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Address</label><input type="text" class="form-control" name="address" value="' + v("address") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Tax Number</label><input type="text" class="form-control" name="tax_number" value="' + v("tax_number") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + a1 + '>Active</option><option value="Inactive"' + a2 + '>Inactive</option></select></div>'
            '<div class="col-12 mb-3"><label class="form-label">Notes</label><textarea class="form-control" name="notes" rows="3">' + v("notes") + '</textarea></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("suppliers_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);">Cancel</a><button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save</button></div></div></form></div>')

@app.route("/suppliers")
@role_required("ADMIN","MANAGER")
def suppliers_list():
    ss = Supplier.query.order_by(Supplier.company_name).all(); rows = []
    for s in ss:
        act = supplier_active(s); bg = '<span class="badge badge-success">Active</span>' if act else '<span class="badge badge-secondary">Inactive</span>'
        ac = '<a class="btn-primary" href="' + url_for("supplier_edit", supplier_id=s.id) + '" style="padding:0.4rem 0.8rem;font-size:0.8rem;">Edit</a> '
        if act: ac += '<form method="post" action="' + url_for("supplier_deactivate", supplier_id=s.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate?\')"><button type="submit" class="btn-primary" style="background:var(--warning);padding:0.4rem 0.8rem;font-size:0.8rem;">Ban</button></form>'
        rows.append('<tr><td>' + str(s.id) + '</td><td>' + str(s.company_name) + '</td><td>' + str(s.contact_person or "—") + '</td><td>' + str(s.phone or "—") + '</td><td>' + str(s.email or "—") + '</td><td>' + bg + '</td><td>' + ac + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1>Suppliers</h1></div><a class="btn-primary" href="' + url_for("supplier_add") + '">Add</a></div>'
         '<div class="card"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Contact</th><th>Phone</th><th>Email</th><th>Status</th><th>Actions</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="7" style="text-align:center;">None</td></tr>') + '</tbody></table></div>')
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
            db.session.add(s); db.session.flush(); log_audit("Supplier Created","Supplier",s.id,new_value=name); db.session.commit()
            flash("✅ Saved","success"); return redirect(url_for("suppliers_list"))
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
            log_audit("Supplier Updated","Supplier",s.id,new_value=name); db.session.commit(); flash("✅ Updated","success"); return redirect(url_for("suppliers_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Supplier", supplier_form(s, url_for("supplier_edit", supplier_id=s.id), True))

@app.route("/suppliers/<int:supplier_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER")
def supplier_deactivate(supplier_id):
    s = get_or_404(Supplier, supplier_id)
    try: s.is_active = False; s.status = "Inactive"; log_audit("Supplier Deactivated","Supplier",s.id,old_value="active",new_value="inactive"); db.session.commit(); flash("Deactivated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("suppliers_list"))

# ══════════════════════════════════════════ INVENTORY
def part_form(p, action):
    def v(f, d=""):
        if p: val = getattr(p, f); return str(val if val is not None else d)
        return d
    sups = Supplier.query.filter_by(is_active=True).order_by(Supplier.company_name).all()
    so = '<option value="">-- Select --</option>'
    for s in sups: so += '<option value="' + str(s.id) + '"' + (' selected' if p and p.supplier_id == s.id else '') + '>' + str(s.company_name) + '</option>'
    cat_opts = '<option value="">-- Select Category --</option>'
    for c in INVENTORY_CATEGORIES: cat_opts += '<option value="' + c + '"' + (' selected' if p and (p.category or "") == c else '') + '>' + c + '</option>'
    return ('<div class="page-header"><div class="page-title"><h1>' + ("Edit" if p else "Add") + ' Inventory Item</h1></div></div>'
            '<div class="card"><form method="post" action="' + str(action) + '"><div class="row">'
            '<div class="col-md-6 mb-3"><label class="form-label">Item Name *</label><input type="text" class="form-control" name="part_name" value="' + v("part_name") + '" required></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Category *</label><select class="form-select" name="category" required>' + cat_opts + '</select></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Quantity</label><input type="number" step="0.01" class="form-control" name="quantity" value="' + v("quantity","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Minimum Stock Level</label><input type="number" step="0.01" class="form-control" name="minimum_stock" value="' + v("minimum_stock","5") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit</label><input type="text" class="form-control" name="unit" value="' + v("unit","pcs") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" class="form-control" name="unit_cost" value="' + v("unit_cost","0") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Location / Store</label><input type="text" class="form-control" name="storage_location" value="' + v("storage_location") + '"></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Supplier</label><select class="form-select" name="supplier_id">' + so + '</select></div>'
            '<div class="col-12 mb-3"><label class="form-label">Description</label><textarea class="form-control" name="description" rows="2">' + v("description") + '</textarea></div>'
            '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + (' selected' if (p and (p.status or "Active")=="Active") or not p else '') + '>Active</option><option value="Inactive"' + (' selected' if p and (p.status or "")=="Inactive" else '') + '>Inactive</option></select></div>'
            '<div class="col-12 d-flex gap-2"><a href="' + url_for("inventory_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);">Cancel</a><button type="submit" class="btn-primary"><i class="fas fa-save"></i> Save</button></div></div></form></div>')

@app.route("/inventory")
@role_required("ADMIN","MANAGER","SUPERVISOR","TECHNICIAN","MAINTENANCE STAFF")
def inventory_list():
    q = request.args.get("q", "").strip(); cat_f = request.args.get("category", "").strip(); status_f = request.args.get("status", "").strip(); low_f = request.args.get("low", "") == "1"; show_inactive = request.args.get("show_inactive", "") == "1"
    base = InventoryPart.query
    if q: base = base.filter(InventoryPart.part_name.like("%" + q + "%"))
    if cat_f: base = base.filter(InventoryPart.category == cat_f)
    if status_f: base = base.filter(InventoryPart.status == status_f)
    if not show_inactive: base = base.filter((InventoryPart.is_active == True) | (InventoryPart.is_active == None))
    all_items = base.order_by(InventoryPart.category, InventoryPart.part_name).all()
    if low_f: all_items = [p for p in all_items if (p.quantity or 0) <= (p.minimum_stock or 0)]
    rows = []
    for p in all_items:
        if (p.quantity or 0) <= 0: bg, label = 'badge-danger', 'Out'
        elif p.is_low: bg, label = 'badge-warning', 'Low'
        else: bg, label = 'badge-success', 'OK'
        sn = p.supplier.company_name if p.supplier else "—"; inactive = (p.is_active is False)
        st_badge = '<span class="badge badge-secondary">Inactive</span>' if inactive else '<span class="badge badge-success">Active</span>'
        actions = ('<a class="btn-primary" href="' + url_for("inventory_edit", part_id=p.id) + '" style="padding:.35rem .6rem;font-size:.75rem;">Edit</a> '
                   '<a class="btn-primary" href="' + url_for("inventory_history", part_id=p.id) + '" style="background:var(--bg-secondary);border:1px solid var(--border-color);padding:.35rem .6rem;font-size:.75rem;">Hist</a> '
                   '<a class="btn-primary" href="' + url_for("inventory_stock_in", part_id=p.id) + '" style="background:var(--success);padding:.35rem .6rem;font-size:.75rem;">In</a> '
                   '<a class="btn-primary" href="' + url_for("inventory_stock_out", part_id=p.id) + '" style="background:var(--warning);padding:.35rem .6rem;font-size:.75rem;">Out</a> '
                   '<a class="btn-primary" href="' + url_for("inventory_adjust", part_id=p.id) + '" style="background:var(--info);padding:.35rem .6rem;font-size:.75rem;">Adj</a> ')
        if inactive: actions += '<form method="post" action="' + url_for("inventory_activate", part_id=p.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--success);padding:.35rem .6rem;font-size:.75rem;">On</button></form>'
        else: actions += '<form method="post" action="' + url_for("inventory_deactivate", part_id=p.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate?\')"><button type="submit" class="btn-primary" style="background:var(--danger);padding:.35rem .6rem;font-size:.75rem;">Off</button></form>'
        rows.append('<tr><td>' + str(p.part_name) + '</td><td>' + str(p.category or "—") + '</td><td>' + str(sn) + '</td><td><strong>' + str(p.quantity) + '</strong></td><td>' + str(p.minimum_stock) + '</td><td>' + str(p.unit or "pcs") + '</td><td>' + str(p.storage_location or "—") + '</td><td><span class="badge ' + bg + '">' + label + '</span></td><td>' + st_badge + '</td><td style="white-space:nowrap;">' + actions + '</td></tr>')
    total_items = InventoryPart.query.count(); active_items = InventoryPart.query.filter((InventoryPart.is_active == True) | (InventoryPart.is_active == None)).count()
    low_items = len([p for p in InventoryPart.query.all() if 0 < (p.quantity or 0) <= (p.minimum_stock or 0)]); out_items = len([p for p in InventoryPart.query.all() if (p.quantity or 0) <= 0])
    cat_opts = '<option value="">All Categories</option>' + "".join('<option value="' + c + '"' + (' selected' if cat_f == c else '') + '>' + c + '</option>' for c in INVENTORY_CATEGORIES)
    content = ('<div class="page-header"><div class="page-title"><h1>Engineering / Maintenance Inventory</h1></div><a class="btn-primary" href="' + url_for("inventory_add") + '">Add Item</a></div>'
        '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-boxes"></i></div><div class="kpi-value">' + str(total_items) + '</div><div class="kpi-label">Total</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success)"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(active_items) + '</div><div class="kpi-label">Active</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning)"><i class="fas fa-exclamation-triangle"></i></div><div class="kpi-value">' + str(low_items) + '</div><div class="kpi-label">Low</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--danger)"><i class="fas fa-times-circle"></i></div><div class="kpi-value">' + str(out_items) + '</div><div class="kpi-label">Out</div></div></div>'
        '<form method="get" class="rpro-toolbar"><input type="text" class="form-control" name="q" placeholder="Search..." value="' + str(q) + '">'
        '<select class="form-select" name="category">' + cat_opts + '</select>'
        '<select class="form-select" name="status"><option value="">All Status</option><option value="Active"' + (' selected' if status_f=="Active" else '') + '>Active</option><option value="Inactive"' + (' selected' if status_f=="Inactive" else '') + '>Inactive</option></select>'
        '<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem;"><input type="checkbox" name="low" value="1"' + (' checked' if low_f else '') + '> Low only</label>'
        '<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem;"><input type="checkbox" name="show_inactive" value="1"' + (' checked' if show_inactive else '') + '> Show inactive</label>'
        '<button type="submit" class="btn-primary" style="padding:.7rem 1.4rem;"><i class="fas fa-search"></i> Filter</button>'
        '<a href="' + url_for("inventory_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);padding:.7rem 1.4rem;text-decoration:none;">Reset</a></form>'
        '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Item</th><th>Category</th><th>Supplier</th><th>Qty</th><th>Min</th><th>Unit</th><th>Location</th><th>Stock</th><th>Status</th><th>Actions</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="10" style="text-align:center;padding:2rem;">No items.</td></tr>') + '</tbody></table></div></div>')
    return page("Engineering Inventory", content)

@app.route("/inventory/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def inventory_add():
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_add"))
        if InventoryPart.query.filter(func.lower(InventoryPart.part_name) == name.lower()).first(): flash("Exists","warning"); return redirect(url_for("inventory_add"))
        try:
            st = request.form.get("status","Active")
            p = InventoryPart(part_name=name, category=request.form.get("category","").strip(), description=request.form.get("description","").strip(), quantity=request.form.get("quantity", type=float) or 0, minimum_stock=request.form.get("minimum_stock", type=float) or 5, unit=request.form.get("unit","pcs").strip() or "pcs", unit_cost=request.form.get("unit_cost", type=float) or 0, storage_location=request.form.get("storage_location","").strip(), status=st, is_active=(st=="Active"), supplier_id=request.form.get("supplier_id", type=int))
            db.session.add(p); db.session.flush()
            if (p.quantity or 0) > 0: log_stock_history(p, "IN", p.quantity, 0, p.quantity, notes="Initial stock")
            log_audit("Inventory Item Created","InventoryPart",p.id,new_value=name); db.session.commit()
            flash("✅ Saved","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("inventory_add"))
    return page("Add Inventory Item", part_form(None, url_for("inventory_add")))

@app.route("/inventory/<int:part_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def inventory_edit(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        name = request.form.get("part_name","").strip()
        if not name: flash("Name required","danger"); return redirect(url_for("inventory_edit", part_id=p.id))
        dup = InventoryPart.query.filter(func.lower(InventoryPart.part_name) == name.lower(), InventoryPart.id != p.id).first()
        if dup: flash("Exists","warning"); return redirect(url_for("inventory_edit", part_id=p.id))
        try:
            old_qty = p.quantity or 0; new_qty = request.form.get("quantity", type=float) or 0; st = request.form.get("status","Active")
            p.part_name = name; p.category = request.form.get("category","").strip(); p.description = request.form.get("description","").strip(); p.quantity = new_qty; p.minimum_stock = request.form.get("minimum_stock", type=float) or 5; p.unit = request.form.get("unit","pcs").strip() or "pcs"; p.unit_cost = request.form.get("unit_cost", type=float) or 0; p.storage_location = request.form.get("storage_location","").strip(); p.status = st; p.is_active = (st=="Active"); p.supplier_id = request.form.get("supplier_id", type=int)
            if new_qty != old_qty: log_stock_history(p, "ADJUST", new_qty - old_qty, old_qty, new_qty, notes="Edited")
            log_audit("Inventory Item Updated","InventoryPart",p.id,new_value=name); db.session.commit()
            flash("✅ Updated","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return page("Edit Inventory Item", part_form(p, url_for("inventory_edit", part_id=p.id)))

@app.route("/inventory/<int:part_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def inventory_deactivate(part_id):
    p = get_or_404(InventoryPart, part_id)
    try: p.is_active = False; p.status = "Inactive"; log_audit("Deactivated","InventoryPart",p.id); db.session.commit(); flash("Deactivated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("inventory_list"))

@app.route("/inventory/<int:part_id>/activate", methods=["POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def inventory_activate(part_id):
    p = get_or_404(InventoryPart, part_id)
    try: p.is_active = True; p.status = "Active"; log_audit("Activated","InventoryPart",p.id); db.session.commit(); flash("Activated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("inventory_list"))

@app.route("/inventory/<int:part_id>/stock-in", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR","TECHNICIAN","MAINTENANCE STAFF")
def inventory_stock_in(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        try:
            qty = request.form.get("quantity", type=float) or 0; notes = (request.form.get("notes") or "").strip(); uc = request.form.get("unit_cost", type=float)
            if qty <= 0: flash("Qty > 0","danger"); return redirect(url_for("inventory_stock_in", part_id=p.id))
            prev = p.quantity or 0; new_qty = prev + qty; p.quantity = new_qty
            if uc is not None and uc > 0: p.unit_cost = uc
            log_stock_history(p, "IN", qty, prev, new_qty, notes=notes or "Stock In", unit_cost=uc); log_audit("Stock In","InventoryPart",p.id,old_value=str(prev),new_value=str(new_qty))
            db.session.commit(); flash("✅ Stock added","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    c = ('<div class="page-header"><div class="page-title"><h1>Stock In — ' + str(p.part_name) + '</h1><p>Current: <strong style="color:var(--rori-gold)">' + str(p.quantity) + ' ' + str(p.unit or "pcs") + '</strong></p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("inventory_list") + '">Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-4 mb-3"><label class="form-label">Qty to Add *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required autofocus></div>'
        '<div class="col-md-4 mb-3"><label class="form-label">Unit Cost (optional)</label><input type="number" step="0.01" min="0" class="form-control" name="unit_cost" value="' + str(p.unit_cost or "") + '"></div>'
        '<div class="col-md-4 mb-3"><label class="form-label">Notes</label><input type="text" class="form-control" name="notes"></div>'
        '<div class="col-12"><button type="submit" class="btn-primary" style="background:var(--success);">Add Stock</button></div></div></form></div>')
    return page("Stock In", c)

@app.route("/inventory/<int:part_id>/stock-out", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR","TECHNICIAN","MAINTENANCE STAFF")
def inventory_stock_out(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        try:
            qty = request.form.get("quantity", type=float) or 0; notes = (request.form.get("notes") or "").strip()
            if qty <= 0: flash("Qty > 0","danger"); return redirect(url_for("inventory_stock_out", part_id=p.id))
            prev = p.quantity or 0
            if qty > prev: flash("Only " + str(prev) + " available","danger"); return redirect(url_for("inventory_stock_out", part_id=p.id))
            new_qty = prev - qty; p.quantity = new_qty
            log_stock_history(p, "OUT", qty, prev, new_qty, notes=notes or "Stock Out"); log_audit("Stock Out","InventoryPart",p.id,old_value=str(prev),new_value=str(new_qty))
            db.session.commit(); flash("✅ Stock removed","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    c = ('<div class="page-header"><div class="page-title"><h1>Stock Out — ' + str(p.part_name) + '</h1><p>Current: <strong style="color:var(--rori-gold)">' + str(p.quantity) + ' ' + str(p.unit or "pcs") + '</strong></p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("inventory_list") + '">Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-4 mb-3"><label class="form-label">Qty to Remove *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required autofocus></div>'
        '<div class="col-md-8 mb-3"><label class="form-label">Notes / Reason</label><input type="text" class="form-control" name="notes"></div>'
        '<div class="col-12"><button type="submit" class="btn-primary" style="background:var(--warning);">Remove Stock</button></div></div></form></div>')
    return page("Stock Out", c)

@app.route("/inventory/<int:part_id>/adjust", methods=["GET","POST"])
@role_required("ADMIN","MANAGER","SUPERVISOR")
def inventory_adjust(part_id):
    p = get_or_404(InventoryPart, part_id)
    if request.method == "POST":
        try:
            new_qty = request.form.get("new_quantity", type=float); notes = (request.form.get("notes") or "").strip()
            if new_qty is None or new_qty < 0: flash("New qty must be >= 0","danger"); return redirect(url_for("inventory_adjust", part_id=p.id))
            prev = p.quantity or 0
            if new_qty == prev: flash("No change","info"); return redirect(url_for("inventory_list"))
            p.quantity = new_qty
            log_stock_history(p, "ADJUST", new_qty - prev, prev, new_qty, notes=notes or "Adjustment"); log_audit("Adjust","InventoryPart",p.id,old_value=str(prev),new_value=str(new_qty))
            db.session.commit(); flash("✅ Adjusted","success"); return redirect(url_for("inventory_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    c = ('<div class="page-header"><div class="page-title"><h1>Adjust Stock — ' + str(p.part_name) + '</h1><p>Current: <strong style="color:var(--rori-gold)">' + str(p.quantity) + ' ' + str(p.unit or "pcs") + '</strong></p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("inventory_list") + '">Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-4 mb-3"><label class="form-label">New Quantity *</label><input type="number" step="0.01" min="0" class="form-control" name="new_quantity" value="' + str(p.quantity or 0) + '" required autofocus></div>'
        '<div class="col-md-8 mb-3"><label class="form-label">Reason</label><input type="text" class="form-control" name="notes"></div>'
        '<div class="col-12"><button type="submit" class="btn-primary" style="background:var(--info);">Save</button></div></div></form></div>')
    return page("Adjust Stock", c)

@app.route("/inventory/<int:part_id>/history")
@role_required("ADMIN","MANAGER","SUPERVISOR","TECHNICIAN","MAINTENANCE STAFF")
def inventory_history(part_id):
    p = get_or_404(InventoryPart, part_id)
    hist = InventoryStockHistory.query.filter_by(part_id=p.id).order_by(InventoryStockHistory.created_at.desc()).limit(500).all()
    rows = []
    for h in hist:
        act_color = {"IN":"success","OUT":"warning","ADJUST":"info","USE":"danger","RETURN":"success"}.get(h.action, "secondary")
        wo_link = ' <a href="' + url_for("workorder_detail", wo_id=h.work_order_id) + '" style="color:var(--rori-gold);font-size:.8rem;">WO#' + str(h.work_order_id) + '</a>' if h.work_order_id else ""
        rows.append('<tr><td>' + (h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else "—") + '</td>'
            '<td><span class="badge badge-' + act_color + '">' + str(h.action) + '</span>' + wo_link + '</td>'
            '<td>' + str(h.quantity) + '</td><td>' + str(h.previous_qty) + '</td><td>' + str(h.new_qty) + '</td><td>' + str(h.unit or "") + '</td>'
            '<td>' + str((h.user.full_name or h.user.username) if h.user else "System") + '</td><td>' + str(h.notes or "") + '</td></tr>')
    content = ('<div class="page-header"><div class="page-title"><h1>Stock History — ' + str(p.part_name) + '</h1><p>Current: <strong style="color:var(--rori-gold)">' + str(p.quantity) + ' ' + str(p.unit or "pcs") + '</strong></p></div>'
        '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("inventory_list") + '">Back</a></div>'
        '<div class="card"><div style="overflow-x:auto;"><table class="table"><thead><tr><th>Date</th><th>Action</th><th>Qty</th><th>Prev</th><th>New</th><th>Unit</th><th>By</th><th>Notes</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="8" style="text-align:center;padding:2rem;">No history.</td></tr>') + '</tbody></table></div></div>')
    return page("Stock History", content)

def can_parts(wo): return (current_user.role in ["MANAGER","ADMIN"] or (current_user.role in STAFF_ROLES and current_user.id == wo.assigned_to_id))

@app.route("/workorders/<int:wo_id>/parts/add", methods=["GET","POST"])
@login_required
def workorder_part_add(wo_id):
    wo = get_or_404(WorkOrder, wo_id)
    if not can_parts(wo): abort(403)
    if wo.status not in ["Assigned","In Progress"]: flash("Cannot add parts at this stage","warning"); return redirect(url_for("workorder_detail", wo_id=wo.id))
    if request.method == "POST":
        try:
            pid = request.form.get("part_id", type=int); qty = request.form.get("quantity", type=float); uc = request.form.get("unit_cost", type=float); notes = (request.form.get("notes") or "").strip()
            part = get_one(InventoryPart, pid)
            if not part: flash("Select valid part","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if not qty or qty <= 0: flash("Qty > 0","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if qty > (part.quantity or 0): flash("Only " + str(part.quantity) + " available","danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
            if uc is None or uc < 0: uc = part.unit_cost or 0
            prev = part.quantity or 0; new_qty = prev - qty
            wop = WorkOrderPart(work_order_id=wo.id, part_id=part.id, quantity=qty, unit_cost=uc, notes=notes)
            part.quantity = new_qty; db.session.add(wop)
            log_stock_history(part, "USE", qty, prev, new_qty, notes=notes or ("Used on WO " + str(wo.work_order_no)), work_order_id=wo.id)
            log_audit("Part Used","WorkOrder",wo.id,new_value=str(part.part_name) + " x " + str(qty))
            db.session.commit(); flash("✅ Part recorded","success"); return redirect(url_for("workorder_detail", wo_id=wo.id))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger"); return redirect(url_for("workorder_part_add", wo_id=wo.id))
    parts = InventoryPart.query.filter((InventoryPart.is_active == True) | (InventoryPart.is_active == None), InventoryPart.quantity > 0).order_by(InventoryPart.category, InventoryPart.part_name).all()
    by_cat = defaultdict(list)
    for p in parts: by_cat[p.category or "Uncategorized"].append(p)
    po = '<option value="">-- Select Item --</option>'
    for cat in sorted(by_cat.keys()):
        po += '<optgroup label="' + cat + '">'
        for p in by_cat[cat]: po += '<option value="' + str(p.id) + '">' + str(p.part_name) + ' (stock: ' + str(p.quantity) + ' ' + str(p.unit or "pcs") + ')</option>'
        po += '</optgroup>'
    c = ('<div class="page-header"><div class="page-title"><h1>Add Part — WO ' + str(wo.work_order_no) + '</h1></div>'
         '<a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("workorder_detail", wo_id=wo.id) + '">Back</a></div>'
         '<div class="card"><form method="post"><div class="row">'
         '<div class="col-md-6 mb-3"><label class="form-label">Item *</label><select class="form-select" name="part_id" required>' + po + '</select></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Quantity *</label><input type="number" step="0.01" min="0.01" class="form-control" name="quantity" required></div>'
         '<div class="col-md-3 mb-3"><label class="form-label">Unit Cost</label><input type="number" step="0.01" min="0" class="form-control" name="unit_cost"></div>'
         '<div class="col-12 mb-3"><label class="form-label">Notes</label><textarea class="form-control" name="notes" rows="2"></textarea></div>'
         '<div class="col-12"><button type="submit" class="btn-primary">Add &amp; Deduct</button></div></div></form></div>')
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
        if part:
            prev = part.quantity or 0; new_qty = prev + (wop.quantity or 0); part.quantity = new_qty
            log_stock_history(part, "RETURN", wop.quantity or 0, prev, new_qty, notes="Returned from WO " + str(wo.work_order_no), work_order_id=wo.id)
        db.session.delete(wop); log_audit("Part Removed","WorkOrder",wo.id)
        db.session.commit(); flash("Returned to stock","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("workorder_detail", wo_id=wo.id))

# ══════════════════════════════════════════ NOTIFICATIONS
@app.route("/api/notifications/unread")
@login_required
def api_unread():
    c = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    latest = Notification.query.filter_by(user_id=current_user.id, is_read=False).order_by(Notification.created_at.desc()).first()
    return jsonify({"unread": c, "latest_id": latest.id if latest else None, "latest_title": latest.title if latest else None, "latest_message": latest.message if latest else None, "server_time": datetime.utcnow().isoformat()})

@app.route("/notifications")
@login_required
def notifications():
    ns = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all(); rows = []
    for n in ns:
        cls = "" if n.is_read else "table-warning"; link = n.link or "#"
        ra = '<span style="color:var(--success);">✓</span>' if n.is_read else '<a class="btn-primary" href="/notifications/mark-read/' + str(n.id) + '" style="padding:0.4rem 0.8rem;font-size:0.8rem;">Read</a>'
        rows.append('<tr class="' + cls + '"><td><a href="' + link + '" style="color:var(--rori-gold);font-weight:600;">' + str(n.title) + '</a></td><td>' + str(n.message) + '</td><td>' + str(n.notification_type) + '</td><td>' + (n.created_at.strftime("%Y-%m-%d %H:%M") if n.created_at else "") + '</td><td>' + ra + '</td></tr>')
    c = ('<div class="page-header"><div class="page-title"><h1>Notifications</h1></div></div>'
         '<div class="card"><table class="table"><thead><tr><th>Title</th><th>Message</th><th>Type</th><th>Date</th><th>Action</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="5" style="text-align:center;">None</td></tr>') + '</tbody></table></div>')
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

# ══════════════════════════════════════════ AREAS / ROOMS / OTHER
def _area_dept_label(a):
    d = (a.department or "").strip() if a.department else ""
    if not d or d.lower() in ("unknown", "n/a", "none", "-"): return "Not Assigned"
    if d.lower() == "f&b": return "Food & Beverage"
    return d

def _area_req_stats():
    stats = defaultdict(lambda: {"total":0,"pending":0,"approved":0,"assigned":0,"in_progress":0,"completed":0,"verified":0,"closed":0,"rejected":0,"overdue":0,"open":0,"last_date":None,"new_24h":0,"staff":set()})
    reqs = (MaintenanceRequest.query.filter_by(is_deleted=False).filter(MaintenanceRequest.area_id.isnot(None)).all())
    cutoff = datetime.utcnow() - timedelta(hours=24)
    for r in reqs:
        s = stats[r.area_id]; s["total"] += 1
        st = (r.status or "").strip(); key = st.lower().replace(" ", "_")
        if key in s: s[key] += 1
        if st in ("Pending","Approved","Assigned","In Progress","Overdue"): s["open"] += 1
        if r.assigned_to: s["staff"].add(r.assigned_to.full_name or r.assigned_to.username)
        if r.created_at:
            if s["last_date"] is None or r.created_at > s["last_date"]: s["last_date"] = r.created_at
            if r.created_at >= cutoff: s["new_24h"] += 1
    return stats

def _area_status(a, s):
    if not s or s.get("total", 0) == 0: return ("No Active Requests", "secondary")
    if s.get("in_progress", 0) > 0: return ("Work In Progress", "info")
    if s.get("open", 0) > 0: return ("Maintenance Required", "warning")
    return ("All Requests Completed", "success")

def _area_search(a, q):
    if not q: return True
    ql = q.lower()
    if ql in (a.name or "").lower(): return True
    if ql in (a.department or "").lower(): return True
    for r in MaintenanceRequest.query.filter_by(area_id=a.id, is_deleted=False).all():
        if ql in (r.request_no or "").lower(): return True
        if r.working_item and ql in (r.working_item.name or "").lower(): return True
    return False

@app.route("/areas")
@role_required("ADMIN","MANAGER")
def areas_list():
    q = (request.args.get("q") or "").strip(); mode = (request.args.get("filter") or "all").strip(); dept_filter = (request.args.get("dept") or "").strip(); show_inactive = (request.args.get("show_inactive") or "").strip() == "1"
    base_q = Area.query
    if not show_inactive: base_q = base_q.filter((Area.is_active == True) | (Area.is_active == None))
    all_areas = base_q.order_by(Area.name).all(); stats = _area_req_stats()
    dept_set = sorted({_area_dept_label(a) for a in Area.query.all()})
    total_areas = len(all_areas); areas_with_active = 0; total_requests = 0; total_completed = 0
    for a in all_areas:
        s = stats.get(a.id)
        if s and s["open"] > 0: areas_with_active += 1
        if s: total_requests += s["total"]; total_completed += s["completed"]
    areas_without_active = total_areas - areas_with_active
    visible = []
    for a in all_areas:
        s = stats.get(a.id)
        if dept_filter and _area_dept_label(a) != dept_filter: continue
        if mode == "active" and not (s and s["open"] > 0): continue
        if mode == "no_active" and (s and s["open"] > 0): continue
        if mode == "in_progress" and not (s and s["in_progress"] > 0): continue
        if mode == "completed" and not (s and s["total"] > 0 and s["open"] == 0): continue
        if q and not _area_search(a, q): continue
        visible.append((a, s))
    cards = []
    for a, s in visible:
        s = s or {"total":0,"open":0,"in_progress":0,"completed":0,"new_24h":0,"last_date":None}
        dept = _area_dept_label(a); st_label, st_class = _area_status(a, s)
        st_color = {"success":"var(--success)","warning":"var(--warning)","info":"var(--info)","secondary":"var(--text-secondary)"}.get(st_class, "var(--text-secondary)")
        is_active = (a.is_active is not False)
        new_badge = '<div class="area-inactive-badge">INACTIVE</div>' if not is_active else ('<div class="area-new-badge"><i class="fas fa-bell"></i> NEW (' + str(s.get("new_24h",0)) + ')</div>' if s.get("new_24h", 0) > 0 else "")
        last_dt = s.get("last_date"); last_str = last_dt.strftime("%Y-%m-%d %H:%M") if last_dt else "—"
        cards.append('<div class="area-card' + ("" if is_active else " inactive") + '">' + new_badge + '<div class="area-card-header"><div class="area-card-name">' + str(a.name) + '</div><div class="area-card-dept"><i class="fas fa-building"></i> ' + str(dept) + '</div></div>'
            + '<div class="area-stat-grid"><div class="area-stat"><div class="area-stat-val">' + str(s["total"]) + '</div><div class="area-stat-lbl">Total</div></div><div class="area-stat"><div class="area-stat-val" style="color:var(--warning)">' + str(s["open"]) + '</div><div class="area-stat-lbl">Open</div></div><div class="area-stat"><div class="area-stat-val" style="color:var(--info)">' + str(s["in_progress"]) + '</div><div class="area-stat-lbl">In Prog</div></div><div class="area-stat"><div class="area-stat-val" style="color:var(--success)">' + str(s["completed"]) + '</div><div class="area-stat-lbl">Done</div></div></div>'
            + '<div class="area-status-row" style="color:' + st_color + '"><i class="fas fa-circle" style="font-size:.55rem"></i> <span>' + st_label + '</span></div>'
            + '<div class="area-last-row"><i class="fas fa-clock"></i> Last: ' + last_str + '</div>'
            + '<div class="area-card-actions"><a class="btn-primary" style="padding:.5rem 1rem;font-size:.82rem;flex:1;justify-content:center;" href="' + url_for("area_detail", area_id=a.id) + '">View</a>'
            + '<a class="btn-primary" style="background:var(--bg-secondary);border:1px solid var(--border-color);padding:.5rem .85rem;font-size:.82rem;" href="' + url_for("area_edit", area_id=a.id) + '">Edit</a>'
            + ('<form method="post" action="' + url_for("area_deactivate", area_id=a.id) + '" style="display:inline" onsubmit="return confirm(\'Deactivate?\');"><button type="submit" class="btn-primary" style="background:var(--warning);padding:.5rem .85rem;font-size:.82rem;">Off</button></form>' if is_active else '<form method="post" action="' + url_for("area_activate", area_id=a.id) + '" style="display:inline"><button type="submit" class="btn-primary" style="background:var(--success);padding:.5rem .85rem;font-size:.82rem;">On</button></form>')
            + '</div></div>')
    cards_html = "".join(cards) if cards else '<div class="empty-state"><i class="fas fa-map-marked-alt"></i><p>No areas match.</p></div>'
    dept_options = '<option value="">All Departments</option>' + "".join('<option value="' + d + '"' + (' selected' if dept_filter == d else '') + '>' + d + '</option>' for d in dept_set)
    def _sel(m): return ' selected' if mode == m else ''
    filter_options = ('<option value="all"' + _sel("all") + '>All Areas</option><option value="active"' + _sel("active") + '>Has Active</option><option value="no_active"' + _sel("no_active") + '>No Active</option><option value="in_progress"' + _sel("in_progress") + '>In Progress</option><option value="completed"' + _sel("completed") + '>All Completed</option>')
    content = ('<div class="page-header"><div class="page-title"><h1>Areas &amp; Maintenance</h1></div><div style="display:flex;gap:.6rem;flex-wrap:wrap;"><a href="' + url_for("area_add") + '" class="btn-primary">Add Area</a></div></div>'
        '<div class="kpi-mini"><div class="kpi-mini-card"><div class="kpi-mini-label">Total Areas</div><div class="kpi-mini-value">' + str(total_areas) + '</div></div>'
        + '<div class="kpi-mini-card"><div class="kpi-mini-label">With Active</div><div class="kpi-mini-value" style="color:var(--warning)">' + str(areas_with_active) + '</div></div>'
        + '<div class="kpi-mini-card"><div class="kpi-mini-label">Without Active</div><div class="kpi-mini-value" style="color:var(--success)">' + str(areas_without_active) + '</div></div>'
        + '<div class="kpi-mini-card"><div class="kpi-mini-label">Total Requests</div><div class="kpi-mini-value">' + str(total_requests) + '</div></div>'
        + '<div class="kpi-mini-card"><div class="kpi-mini-label">Completed</div><div class="kpi-mini-value" style="color:var(--success)">' + str(total_completed) + '</div></div></div>'
        + '<form method="get" class="area-toolbar"><input type="text" class="form-control" name="q" placeholder="Search..." value="' + str(q) + '">'
        + '<select class="form-select" name="filter">' + filter_options + '</select><select class="form-select" name="dept">' + dept_options + '</select>'
        + '<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem;"><input type="checkbox" name="show_inactive" value="1"' + (' checked' if show_inactive else '') + '> Show inactive</label>'
        + '<button type="submit" class="btn-primary" style="padding:.7rem 1.4rem;">Apply</button>'
        + '<a href="' + url_for("areas_list") + '" class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);padding:.7rem 1.4rem;text-decoration:none;">Reset</a></form>'
        + '<div class="area-grid">' + cards_html + '</div>')
    return page("Areas", content)

@app.route("/areas/add", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def area_add():
    depts = Department.query.order_by(Department.name).all()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip(); dept = (request.form.get("department") or "").strip(); desc = (request.form.get("description") or "").strip()
        if not name: flash("Area name required","danger"); return redirect(url_for("area_add"))
        if Area.query.filter(func.lower(Area.name) == name.lower()).first(): flash("Exists","warning"); return redirect(url_for("area_add"))
        try:
            a = Area(name=name, department=(None if dept in ("", "Not Assigned") else dept), description=desc, status="Active", is_active=True)
            db.session.add(a); db.session.flush(); log_audit("Area Created","Area",a.id,new_value=name); db.session.commit()
            flash("✅ Area added","success"); return redirect(url_for("areas_list"))
        except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    dept_opts = '<option value="">Not Assigned</option>' + "".join('<option value="' + d.name + '">' + d.name + '</option>' for d in depts)
    content = ('<div class="page-header"><div class="page-title"><h1>Add Area</h1></div><a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("areas_list") + '">Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Area Name *</label><input type="text" class="form-control" name="name" required autofocus></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Department</label><select class="form-select" name="department">' + dept_opts + '</select></div>'
        '<div class="col-12 mb-3"><label class="form-label">Description</label><textarea class="form-control" name="description" rows="3"></textarea></div>'
        '<div class="col-12"><button type="submit" class="btn-primary">Save Area</button></div></div></form></div>')
    return page("Add Area", content)

@app.route("/areas/<int:area_id>")
@role_required("ADMIN","MANAGER")
def area_detail(area_id):
    a = get_or_404(Area, area_id)
    reqs = MaintenanceRequest.query.filter_by(area_id=a.id, is_deleted=False).order_by(MaintenanceRequest.created_at.desc()).all()
    counts = {"total":0,"pending":0,"approved":0,"assigned":0,"in_progress":0,"completed":0,"verified":0,"closed":0,"rejected":0,"overdue":0,"open":0}
    staff_set = set()
    for r in reqs:
        counts["total"] += 1
        st = (r.status or "").strip(); key = st.lower().replace(" ", "_")
        if key in counts: counts[key] += 1
        if st in ("Pending","Approved","Assigned","In Progress","Overdue"): counts["open"] += 1
        if r.assigned_to: staff_set.add(r.assigned_to.full_name or r.assigned_to.username)
    st_label, st_class = _area_status(a, {"total": counts["total"], "open": counts["open"], "in_progress": counts["in_progress"], "completed": counts["completed"]})
    st_color = {"success":"var(--success)","warning":"var(--warning)","info":"var(--info)","secondary":"var(--text-secondary)"}.get(st_class, "var(--text-secondary)")
    dept_label = _area_dept_label(a); rows = []
    for r in reqs:
        bc = {"Pending":"warning","Approved":"primary","Assigned":"info","In Progress":"info","Completed":"success","Verified":"success","Closed":"secondary","Rejected":"danger","Overdue":"danger"}.get(r.status, "secondary")
        rows.append('<tr><td><a href="' + url_for("request_detail", req_id=r.id) + '" style="color:var(--rori-gold);">' + str(r.request_no) + '</a></td><td>' + str(r.working_item.name if r.working_item else "—") + '</td><td>' + str(r.requested_by.full_name if r.requested_by else "—") + '</td><td>' + str(r.assigned_to.full_name if r.assigned_to else "Unassigned") + '</td><td><span class="badge badge-' + bc + '">' + str(r.status) + '</span></td><td>' + (r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "—") + '</td></tr>')
    content = ('<div class="page-header"><div class="page-title"><h1>' + str(a.name) + '</h1><p>' + str(dept_label) + '</p></div><div style="display:flex;gap:.6rem;"><a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("areas_list") + '">Back</a><a class="btn-primary" href="' + url_for("area_edit", area_id=a.id) + '">Edit</a></div></div>'
        + '<div class="card" style="border-left:3px solid ' + st_color + ';"><div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:1rem;"><div><div style="font-size:.72rem;color:var(--text-secondary);text-transform:uppercase;">Status</div><div style="font-size:1.15rem;font-weight:800;color:' + st_color + ';">● ' + st_label + '</div></div><div><div style="font-size:.72rem;color:var(--text-secondary);text-transform:uppercase;">Dept</div><div style="font-size:1.15rem;font-weight:800;color:var(--rori-gold);">' + str(dept_label) + '</div></div><div><div style="font-size:.72rem;color:var(--text-secondary);text-transform:uppercase;">Staff</div><div style="font-size:1.15rem;font-weight:800;">' + (", ".join(sorted(staff_set)) if staff_set else "—") + '</div></div></div></div>'
        + '<div class="card"><h5 style="color:var(--rori-gold);">Recent Requests</h5><table class="table"><thead><tr><th>Request #</th><th>Item</th><th>Requested</th><th>Assigned</th><th>Status</th><th>Created</th></tr></thead><tbody>' + ("".join(rows) if rows else '<tr><td colspan="6" style="text-align:center;">No requests.</td></tr>') + '</tbody></table></div>')
    return page("Area: " + str(a.name), content)

@app.route("/areas/<int:area_id>/edit", methods=["GET","POST"])
@role_required("ADMIN","MANAGER")
def area_edit(area_id):
    a = get_or_404(Area, area_id)
    if request.method == "POST":
        old_name = a.name; old_dept = a.department
        new_name = (request.form.get("name") or "").strip(); new_dept = (request.form.get("department") or "").strip()
        if not new_name: flash("Area name required","danger"); return redirect(url_for("area_edit", area_id=a.id))
        dup = Area.query.filter(func.lower(Area.name) == new_name.lower(), Area.id != a.id).first()
        if dup: flash("Exists","warning"); return redirect(url_for("area_edit", area_id=a.id))
        a.name = new_name; a.department = None if new_dept in ("", "Not Assigned", "Unknown") else new_dept
        a.status = (request.form.get("status") or a.status or "Active").strip(); a.is_active = (a.status == "Active"); a.description = (request.form.get("description") or "").strip()
        log_audit("Area Updated","Area",a.id,old_value=str(old_name)+" / "+str(old_dept),new_value=str(a.name)+" / "+str(a.department)); db.session.commit()
        flash("✅ Updated","success"); return redirect(url_for("area_detail", area_id=a.id))
    depts = [d.name for d in Department.query.order_by(Department.name).all()]; current = (a.department or "").strip()
    if current and current not in depts and current.lower() != "unknown": depts = [current] + depts
    opts = '<option value="">Not Assigned</option>' + "".join('<option value="' + d + '"' + (' selected' if d == current else '') + '>' + d + '</option>' for d in depts)
    content = ('<div class="page-header"><div class="page-title"><h1>Edit Area</h1></div><a class="btn-primary" style="background:var(--bg-card);border:1px solid var(--border-color);" href="' + url_for("area_detail", area_id=a.id) + '">Back</a></div>'
        '<div class="card"><form method="post"><div class="row">'
        '<div class="col-md-6 mb-3"><label class="form-label">Name *</label><input type="text" class="form-control" name="name" value="' + str(a.name) + '" required></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Department</label><select class="form-select" name="department">' + opts + '</select></div>'
        '<div class="col-md-6 mb-3"><label class="form-label">Status</label><select class="form-select" name="status"><option value="Active"' + (' selected' if (a.status or "Active")=="Active" else '') + '>Active</option><option value="Inactive"' + (' selected' if (a.status or "")=="Inactive" else '') + '>Inactive</option></select></div>'
        '<div class="col-12 mb-3"><label class="form-label">Description</label><textarea class="form-control" name="description" rows="3">' + str(a.description or "") + '</textarea></div>'
        '<div class="col-12"><button type="submit" class="btn-primary">Save</button></div></div></form></div>')
    return page("Edit Area", content)

@app.route("/areas/<int:area_id>/deactivate", methods=["POST"])
@role_required("ADMIN","MANAGER")
def area_deactivate(area_id):
    a = get_or_404(Area, area_id)
    try: a.is_active = False; a.status = "Inactive"; log_audit("Area Deactivated","Area",a.id); db.session.commit(); flash("Deactivated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("areas_list"))

@app.route("/areas/<int:area_id>/activate", methods=["POST"])
@role_required("ADMIN","MANAGER")
def area_activate(area_id):
    a = get_or_404(Area, area_id)
    try: a.is_active = True; a.status = "Active"; log_audit("Area Activated","Area",a.id); db.session.commit(); flash("Activated","success")
    except Exception as e: db.session.rollback(); flash("Error: " + str(e),"danger")
    return redirect(url_for("areas_list"))

@app.route("/rooms")
@role_required("ADMIN","MANAGER")
def rooms_list():
    q = (request.args.get("q") or "").strip(); floor_f = request.args.get("floor", type=int); status_f = (request.args.get("status") or "").strip()
    base_q = Room.query
    if floor_f: base_q = base_q.filter(Room.floor == floor_f)
    if status_f: base_q = base_q.filter(Room.status == status_f)
    if q: base_q = base_q.filter(Room.room_number.like("%" + q + "%"))
    rooms = base_q.order_by(func.cast(Room.room_number, db.Integer).asc()).all()
    stats = defaultdict(lambda: {"total":0,"open":0,"in_progress":0,"completed":0,"last_date":None})
    room_ids = [r.id for r in rooms]
    if room_ids:
        reqs = MaintenanceRequest.query.filter(MaintenanceRequest.room_id.in_(room_ids)).filter_by(is_deleted=False).all()
        for r in reqs:
            s = stats[r.room_id]; s["total"] += 1
            if r.status in ("Pending","Approved","Assigned","In Progress","Overdue"): s["open"] += 1
            if r.status == "In Progress": s["in_progress"] += 1
            if r.status in ("Completed","Verified","Closed"): s["completed"] += 1
            if r.created_at and (s["last_date"] is None or r.created_at > s["last_date"]): s["last_date"] = r.created_at
    all_rooms = Room.query.all(); total_rooms = len(all_rooms)
    occupied = sum(1 for r in all_rooms if r.status == "Occupied"); available = sum(1 for r in all_rooms if r.status == "Available"); maintenance = sum(1 for r in all_rooms if r.status == "Maintenance")
    all_room_ids = [r.id for r in all_rooms]; open_reqs = 0
    if all_room_ids: open_reqs = MaintenanceRequest.query.filter(MaintenanceRequest.room_id.in_(all_room_ids)).filter_by(is_deleted=False).filter(MaintenanceRequest.status.in_(["Pending","Approved","Assigned","In Progress","Overdue"])).count()
    cards = []
    for r in rooms:
        s = stats.get(r.id) or {"total":0,"open":0,"in_progress":0,"completed":0,"last_date":None}
        status_class = {"Available":"green","Occupied":"blue","Reserved":"gold","Maintenance":"orange","Out of Service":"red"}.get(r.status, "gold")
        last = s["last_date"].strftime("%Y-%m-%d") if s["last_date"] else "—"
        open_badge = ('<span class="rpro-chip orange">' + str(s["open"]) + ' open</span>' if s["open"] else '<span class="rpro-chip green">Clear</span>')
        cards.append('<div class="rpro-room-card"><div style="display:flex;justify-content:space-between;"><div><div class="rpro-room-num">' + str(r.room_number) + '</div><div class="rpro-room-floor">Floor ' + str(r.floor) + '</div></div><span class="rpro-chip ' + status_class + '">' + str(r.status) + '</span></div>'
            '<div class="rpro-room-stats">' + open_badge + '<span class="rpro-chip">' + str(s["total"]) + ' total</span></div>'
            '<a href="' + url_for("requests_list") + '?room_id=' + str(r.id) + '" class="btn-primary" style="margin-top:.75rem;width:100%;justify-content:center;padding:.45rem;font-size:.8rem;">View</a></div>')
    all_floors = sorted({r.floor for r in all_rooms})
    floor_opts = '<option value="">All Floors</option>' + "".join('<option value="' + str(f) + '"' + (' selected' if floor_f == f else '') + '>Floor ' + str(f) + '</option>' for f in all_floors)
    status_opts = '<option value="">All Statuses</option>' + "".join('<option value="' + s + '"' + (' selected' if status_f == s else '') + '>' + s + '</option>' for s in ROOM_STATUSES)
    content = ('<div class="page-header"><div class="page-title"><h1>Rooms</h1><p>' + str(total_rooms) + ' rooms · ' + str(len(all_floors)) + ' floors</p></div></div>'
        '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-door-open"></i></div><div class="kpi-value">' + str(total_rooms) + '</div><div class="kpi-label">Total</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success)"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(available) + '</div><div class="kpi-label">Available</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--info)"><i class="fas fa-user-check"></i></div><div class="kpi-value">' + str(occupied) + '</div><div class="kpi-label">Occupied</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning)"><i class="fas fa-tools"></i></div><div class="kpi-value">' + str(maintenance) + '</div><div class="kpi-label">Maintenance</div></div>'
        '<div class="kpi-card"><div class="kpi-icon" style="color:var(--danger)"><i class="fas fa-exclamation-triangle"></i></div><div class="kpi-value">' + str(open_reqs) + '</div><div class="kpi-label">Open</div></div></div>'
        '<form method="get" class="rpro-toolbar"><input type="text" class="form-control" name="q" placeholder="Room #..." value="' + q + '">'
        '<select class="form-select" name="floor">' + floor_opts + '</select><select class="form-select" name="status">' + status_opts + '</select>'
        '<button type="submit" class="btn-primary" style="padding:.7rem 1.4rem;">Filter</button></form>'
        + ('<div class="rpro-room-grid">' + "".join(cards) + '</div>' if cards else '<div class="rpro-card" style="text-align:center;padding:3rem;">No rooms match.</div>'))
    return page("Rooms", content)

@app.route("/employees")
@role_required("ADMIN","MANAGER")
def employees_list():
    es = Employee.query.all(); rows = "".join('<tr><td>' + str(e.id) + '</td><td>' + str(e.name) + '</td><td>' + str(e.job_title) + '</td><td>' + str(e.department or "—") + '</td></tr>' for e in es)
    c = ('<div class="page-header"><div class="page-title"><h1>Employees</h1></div></div><div class="card"><table class="table"><thead><tr><th>ID</th><th>Name</th><th>Title</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Employees", c)

@app.route("/admin/users")
@role_required("ADMIN")
def admin_users():
    us = User.query.all(); rows = "".join('<tr><td>' + str(u.username) + '</td><td>' + str(u.full_name or u.username) + '</td><td>' + str(u.role) + '</td><td>' + str(u.department.name if u.department else "—") + '</td></tr>' for u in us)
    c = ('<div class="page-header"><div class="page-title"><h1>Users</h1></div></div><div class="card"><table class="table"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Dept</th></tr></thead><tbody>' + rows + '</tbody></table></div>')
    return page("Users", c)

@app.route("/admin/audit")
@role_required("ADMIN")
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    rows = "".join('<tr><td>' + str(l.user.full_name if l.user else "System") + '</td><td>' + str(l.action) + '</td><td>' + str(l.object_type or "") + '</td><td>' + (l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else "") + '</td></tr>' for l in logs)
    c = ('<div class="page-header"><div class="page-title"><h1>Audit</h1></div></div><div class="card"><table class="table"><thead><tr><th>User</th><th>Action</th><th>Object</th><th>Date</th></tr></thead><tbody>' + (rows if rows else '<tr><td colspan="4" style="text-align:center;">No logs</td></tr>') + '</tbody></table></div>')
    return page("Audit", c)

@app.route("/admin/backup")
@role_required("ADMIN")
def backup_page():
    bs = sorted([f for f in os.listdir(BACKUP_FOLDER) if f.endswith(".db")], reverse=True)
    rows = "".join('<tr><td>' + str(b) + '</td></tr>' for b in bs)
    c = ('<div class="page-header"><div class="page-title"><h1>Backups</h1></div></div>'
         '<form method="post" action="/admin/backup/now" style="margin-bottom:1.5rem;"><button class="btn-primary">Backup Now</button></form>'
         '<div class="card"><table class="table"><thead><tr><th>File</th></tr></thead><tbody>' + (rows if rows else '<tr><td style="text-align:center;">None</td></tr>') + '</tbody></table></div>')
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
    total = base.count(); pending = base.filter_by(status="Pending").count(); completed = base.filter_by(status="Completed").count(); verified = base.filter_by(status="Verified").count()
    c = ('<div class="page-header"><div class="page-title"><h1>Reports</h1></div></div>'
         '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon"><i class="fas fa-clipboard-list"></i></div><div class="kpi-value">' + str(total) + '</div><div class="kpi-label">Total</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--warning);"><i class="fas fa-clock"></i></div><div class="kpi-value">' + str(pending) + '</div><div class="kpi-label">Pending</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-circle"></i></div><div class="kpi-value">' + str(completed) + '</div><div class="kpi-label">Completed</div></div>'
         '<div class="kpi-card"><div class="kpi-icon" style="color:var(--success);"><i class="fas fa-check-double"></i></div><div class="kpi-value">' + str(verified) + '</div><div class="kpi-label">Verified</div></div></div>'
         '<div class="card"><h5 style="color:var(--rori-gold);">Full detail?</h5><p style="margin-top:.5rem;">Open <a href="' + url_for("detailed_report") + '" style="color:var(--rori-gold);font-weight:700;">Detailed Report</a>.</p></div>')
    return page("Reports", c)

@app.route("/debug")
def debug():
    la = Area.query.filter_by(name=LAUNDRY_AREA_NAME).first()
    hk = Department.query.filter_by(name=HOUSEKEEPING_DEPT_NAME).first()
    return jsonify({
        "database_backend": db.engine.dialect.name,
        "database_url_set": bool(os.environ.get("DATABASE_URL")),
        "WARNING_if_sqlite": "SQLite on Render will LOSE DATA on every deploy. Set DATABASE_URL to PostgreSQL!" if db.engine.dialect.name == "sqlite" else "OK - Using persistent DB",
        "users": User.query.count(), "departments": Department.query.count(),
        "requests_total_incl_archived": MaintenanceRequest.query.count(),
        "requests_active": MaintenanceRequest.query.filter_by(is_deleted=False).count(),
        "requests_archived": MaintenanceRequest.query.filter_by(is_deleted=True).count(),
        "hk_items_count": WorkingItem.query.filter_by(department_id=hk.id).count() if hk else 0,
        "hk_categories_count": Category.query.filter(Category.name.in_(list(HOUSEKEEPING_CATEGORY_NAMES))).count(),
        "work_orders": WorkOrder.query.count(),
        "work_orders_completed": WorkOrder.query.filter_by(status="Completed").count(),
        "work_orders_verified": WorkOrder.query.filter_by(status="Verified").count(),
        "work_order_parts_total": WorkOrderPart.query.count(),
        "notifications": Notification.query.count(),
        "rooms_total": Room.query.count(),
        "areas_total": Area.query.count(),
        "working_items_total": WorkingItem.query.count(),
        "inventory_total": InventoryPart.query.count(),
        "inventory_stock_history": InventoryStockHistory.query.count(),
        "marketing_manager_exists": bool(User.query.filter_by(username="yordanose").first()),
        "hotel_areas_configured": len(HOTEL_AREAS),
        "note": "Read-only diagnostics. No data was modified.",
    })

@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "Rori Hotel Maintenance","short_name": "RoriMaint","start_url": "/dashboard","display": "standalone","background_color": "#0f172a","theme_color": "#f59e0b","icons": []})

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
    print("="*60)
    print("RORI HOTEL MAINTENANCE — STARTUP DIAGNOSTICS")
    print("="*60)
    print(f"Database backend: {db.engine.dialect.name}")
    print(f"DATABASE_URL set: {bool(os.environ.get('DATABASE_URL'))}")
    if db.engine.dialect.name == "sqlite":
        print("⚠️  WARNING: SQLite detected!")
        print("⚠️  On Render.com, SQLite is EPHEMERAL — data WILL be wiped on every deploy/restart.")
        print("⚠️  Fix: Set DATABASE_URL env var to a PostgreSQL URL from Render dashboard.")
    else:
        print("✅ PostgreSQL detected — data will persist across deploys.")
    print("="*60)
    ensure_database_schema()
    seed_data()
    fix_room_structure()
    print("✅ Rori Hotel Maintenance System initialized — Developer: Edom Adinew")
    print("✅ Housekeeping requests flow directly to Maintenance Manager — like all other departments")
    print("✅ Production data preserved — no drops, no truncates, no destructive migrations")
    print("="*60)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)