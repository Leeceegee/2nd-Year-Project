"""

=============================================================
  EDUSTAY BACKEND - Main Python API Server
  File: app.py
  Role: REST API layer - handles HTTP requests, business logic,
        page rendering and coordinates with the C/C++ modules.
=============================================================
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity
)
from datetime import timedelta
from werkzeug.utils import secure_filename
from datetime import datetime
import ctypes
import subprocess
import json
import os

# ──────────────────────────────────────────────
#  App Initialization
# ──────────────────────────────────────────────
app = Flask(__name__)

# MySQL connection — update username/password if needed
app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+pymysql://root:@127.0.0.1/edustay_db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = "edustay-secret-key-change-in-production"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)

db     = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt    = JWTManager(app)

# ──────────────────────────────────────────────
#  Visit Tracking (file-based)
# ──────────────────────────────────────────────
VISITS_FILE = 'visits.json'

def load_visits():
    if os.path.exists(VISITS_FILE):
        with open(VISITS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_visits(data):
    with open(VISITS_FILE, 'w') as f:
        json.dump(data, f)

# ──────────────────────────────────────────────
#  Load C shared library
# ──────────────────────────────────────────────
LIB_PATH = "./housing_utils.so"

try:
    housing_lib = ctypes.CDLL(LIB_PATH)

    housing_lib.calculate_affordability_score.argtypes = [
        ctypes.c_float,
        ctypes.c_float,
        ctypes.c_float
    ]
    housing_lib.calculate_affordability_score.restype = ctypes.c_float

    housing_lib.calculate_distance_score.argtypes = [
        ctypes.c_float,
        ctypes.c_float
    ]
    housing_lib.calculate_distance_score.restype = ctypes.c_float

    C_LIB_AVAILABLE = True
    print("[OK] C library loaded successfully")

except OSError:
    C_LIB_AVAILABLE = False
    print("[WARN] C library not found — smart matching will use Python fallback")


# ══════════════════════════════════════════════
#  DATABASE MODELS
# ══════════════════════════════════════════════

class User(db.Model):
    """Student, Landlord, Agent or Admin account."""
    __tablename__ = "users"

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), nullable=False)
    email          = db.Column(db.String(120), unique=True, nullable=False)
    password_hash  = db.Column(db.String(200), nullable=False)
    role           = db.Column(db.String(20), default="student")  # student / landlord / agent / admin
    monthly_income = db.Column(db.Float, default=0.0)
    university     = db.Column(db.String(100), default="University of Nairobi")
    phone          = db.Column(db.String(20))

    applications   = db.relationship("Application", backref="applicant", lazy=True)
    listings       = db.relationship("Listing", backref="owner", lazy=True)

    def to_dict(self):
        return {
            "id":             self.id,
            "name":           self.name,
            "email":          self.email,
            "role":           self.role,
            "monthly_income": self.monthly_income,
            "university":     self.university,
            "phone":          self.phone
        }


class Listing(db.Model):
    """A housing unit available for rent."""
    __tablename__ = "listings"

    id                 = db.Column(db.Integer, primary_key=True)
    title              = db.Column(db.String(200), nullable=False)
    description        = db.Column(db.Text)
    monthly_rent       = db.Column(db.Float, nullable=False)
    location           = db.Column(db.String(200), nullable=False)
    distance_to_campus = db.Column(db.Float, default=0.0)
    rooms_available    = db.Column(db.Integer, default=1)
    landlord_contact   = db.Column(db.String(100))
    listing_type       = db.Column(db.String(50), default="hostel")  # hostel / independent
    is_active          = db.Column(db.Boolean, default=True)
    owner_id           = db.Column(db.Integer, db.ForeignKey("users.id"))

    applications       = db.relationship("Application", backref="listing", lazy=True)

    def to_dict(self):
        return {
            "id":                    self.id,
            "title":                 self.title,
            "description":           self.description,
            "monthly_rent":          self.monthly_rent,
            "location":              self.location,
            "distance_to_campus_km": self.distance_to_campus,
            "rooms_available":       self.rooms_available,
            "landlord_contact":      self.landlord_contact,
            "listing_type":          self.listing_type,
            "is_active":             self.is_active,
            "owner_id":              self.owner_id
        }


class Application(db.Model):
    """A student's booking/application for a listing."""
    __tablename__ = "applications"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    status     = db.Column(db.String(20), default="pending")  # pending / confirmed / cancelled / completed
    message    = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=db.func.now())

    def to_dict(self):
        return {
            "id":         self.id,
            "user_id":    self.user_id,
            "listing_id": self.listing_id,
            "status":     self.status,
            "message":    self.message,
            "created_at": str(self.created_at)
        }


# ══════════════════════════════════════════════
#  PAGE RENDERING ROUTES
# ══════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/role')
def role_redirect():
    role = request.args.get('role', 'student')
    if role == 'admin':
        return redirect(url_for('admin'))
    elif role == 'student':
        return redirect(url_for('register'))
    elif role == 'landlord':
        return redirect(url_for('listings'))
    elif role == 'agent':
        return redirect(url_for('listings'))
    return redirect(url_for('index'))

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/listings')
def listings():
    return render_template('listings.html')

@app.route('/bookings')
def bookings():
    return render_template('bookings.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/listing-stats')
def listing_stats():
    return render_template('listing-stats.html')
@app.route('/login')
def login_page():
    return render_template('login.html')


# ══════════════════════════════════════════════
#  VISIT TRACKING ROUTES
# ══════════════════════════════════════════════

@app.route('/api/visit/<listing_name>', methods=['POST'])
def track_visit(listing_name):
    visits = load_visits()
    visits[listing_name] = visits.get(listing_name, 0) + 1
    save_visits(visits)
    return jsonify({'success': True, 'visits': visits[listing_name]})

@app.route('/api/popular')
def popular_listings():
    visits = load_visits()
    sorted_listings = sorted(
        visits.items(), key=lambda x: x[1], reverse=True
    )
    return jsonify([
        {'listing': k, 'visits': v}
        for k, v in sorted_listings[:10]
    ])

@app.route('/api/stats')
def stats():
    visits = load_visits()
    total_users     = User.query.count()
    total_listings  = Listing.query.filter_by(is_active=True).count()
    total_bookings  = Application.query.count()
    return jsonify({
        'listings':     total_listings,
        'students':     total_users,
        'landlords':    User.query.filter_by(role='landlord').count(),
        'total_visits': sum(visits.values()),
        'bookings':     total_bookings
    })


# ══════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════

@app.route("/api/register", methods=["POST"])
def api_register():
    """Register a new user account."""
    data = request.get_json()

    required = ["name", "email", "password", "role"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    hashed = bcrypt.generate_password_hash(data["password"]).decode("utf-8")

    user = User(
        name           = data["name"],
        email          = data["email"],
        password_hash  = hashed,
        role           = data.get("role", "student"),
        monthly_income = data.get("monthly_income", 0.0),
        university     = data.get("university", "University of Nairobi"),
        phone          = data.get("phone", "")
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "Account created", "user": user.to_dict()}), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    """Authenticate a user and return a JWT token."""
    data = request.get_json()
    user = User.query.filter_by(email=data.get("email")).first()

    if not user or not bcrypt.check_password_hash(user.password_hash, data.get("password", "")):
        return jsonify({"error": "Invalid credentials"}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({"token": token, "user": user.to_dict()}), 200


# ══════════════════════════════════════════════
#  LISTINGS API ROUTES
# ══════════════════════════════════════════════

@app.route("/api/listings", methods=["GET"])
def get_listings():
    """Return all active listings with optional filters."""
    max_rent     = request.args.get("max_rent",     type=float)
    max_distance = request.args.get("max_distance", type=float)
    listing_type = request.args.get("type")

    query = Listing.query.filter_by(is_active=True)

    if max_rent:
        query = query.filter(Listing.monthly_rent <= max_rent)
    if max_distance:
        query = query.filter(Listing.distance_to_campus <= max_distance)
    if listing_type:
        query = query.filter(Listing.listing_type == listing_type)

    listings = query.all()
    return jsonify([l.to_dict() for l in listings]), 200


@app.route("/api/listings/<int:listing_id>", methods=["GET"])
def get_listing(listing_id):
    """Fetch a single listing by ID."""
    listing = Listing.query.get_or_404(listing_id)
    return jsonify(listing.to_dict()), 200


@app.route("/api/listings", methods=["POST"])
@jwt_required()
def create_listing():
    """Create a new listing — landlord/admin only."""
    data = request.get_json()

    listing = Listing(
        title              = data["title"],
        description        = data.get("description", ""),
        monthly_rent       = data["monthly_rent"],
        location           = data["location"],
        distance_to_campus = data.get("distance_to_campus", 0.0),
        rooms_available    = data.get("rooms_available", 1),
        landlord_contact   = data.get("landlord_contact", ""),
        listing_type       = data.get("listing_type", "hostel"),
        owner_id           = int(get_jwt_identity())
    )

    db.session.add(listing)
    db.session.commit()

    return jsonify({"message": "Listing created", "listing": listing.to_dict()}), 201


# ══════════════════════════════════════════════
#  APPLICATIONS / BOOKINGS ROUTES
# ══════════════════════════════════════════════

@app.route("/api/applications", methods=["POST"])
@jwt_required()
def apply_for_listing():
    """Student applies for a listing."""
    user_id = int(get_jwt_identity())
    data    = request.get_json()

    existing = Application.query.filter_by(
        user_id=user_id,
        listing_id=data["listing_id"]
    ).first()

    if existing:
        return jsonify({"error": "Already applied for this listing"}), 409

    application = Application(
        user_id    = user_id,
        listing_id = data["listing_id"],
        message    = data.get("message", "")
    )

    db.session.add(application)
    db.session.commit()

    return jsonify({"message": "Application submitted", "application": application.to_dict()}), 201


@app.route("/api/applications", methods=["GET"])
@jwt_required()
def get_applications():
    """Get all applications — admin sees all, student sees own."""
    user_id = int(get_jwt_identity())
    user    = User.query.get(user_id)

    if user.role == "admin":
        applications = Application.query.all()
    else:
        applications = Application.query.filter_by(user_id=user_id).all()

    return jsonify([a.to_dict() for a in applications]), 200


@app.route("/api/applications/<int:app_id>", methods=["PUT"])
@jwt_required()
def update_application(app_id):
    """Update application status — admin only."""
    data        = request.get_json()
    application = Application.query.get_or_404(app_id)
    application.status = data.get("status", application.status)
    db.session.commit()
    return jsonify({"message": "Status updated", "application": application.to_dict()}), 200


# ══════════════════════════════════════════════
#  SMART MATCHING — C and C++ modules
# ══════════════════════════════════════════════

@app.route("/api/match", methods=["POST"])
@jwt_required()
def match_listings():
    """Rank listings by affordability + distance using C/C++ modules."""
    if not C_LIB_AVAILABLE:
        return jsonify({"error": "Scoring engine not compiled yet"}), 503

    user_id        = int(get_jwt_identity())
    user           = User.query.get_or_404(user_id)
    data           = request.get_json()
    max_distance   = float(data.get("max_distance_km", 10))
    living_expenses= float(data.get("living_expenses", 3000))

    active_listings = Listing.query.filter_by(is_active=True).all()

    scored = []
    for listing in active_listings:
        afford_score = housing_lib.calculate_affordability_score(
            ctypes.c_float(listing.monthly_rent),
            ctypes.c_float(user.monthly_income),
            ctypes.c_float(living_expenses)
        )
        dist_score = housing_lib.calculate_distance_score(
            ctypes.c_float(listing.distance_to_campus),
            ctypes.c_float(max_distance)
        )
        combined = (0.6 * afford_score) + (0.4 * dist_score)
        scored.append({
            **listing.to_dict(),
            "affordability_score": round(afford_score, 3),
            "distance_score":      round(dist_score, 3),
            "combined_score":      round(combined, 3)
        })

    try:
        cpp_input = json.dumps(scored)
        result    = subprocess.run(
            ["./housing_sorter"],
            input=cpp_input,
            capture_output=True,
            text=True,
            timeout=5
        )
        ranked = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        ranked = sorted(scored, key=lambda x: x["combined_score"], reverse=True)

    return jsonify({"ranked_listings": ranked}), 200


# ══════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════
# Public admin route — no JWT required for now
@app.route("/api/admin/students", methods=["GET"])
def get_students():
    """Get all students for admin page."""
    users = User.query.filter_by(role='student').all()
    return jsonify([u.to_dict() for u in users]), 200
# ── REVIEWS ──
@app.route('/reviews')
def reviews_page():
    return render_template('reviews.html')

@app.route('/api/reviews', methods=['POST'])
@jwt_required()
def add_review():
    """Submit a review for a listing."""
    user_id = int(get_jwt_identity())
    data    = request.get_json()

    if not data.get('listing_name') or not data.get('rating'):
        return jsonify({'error': 'Missing listing name or rating'}), 400

    # Check if user already reviewed this listing
    existing = Review.query.filter_by(
        user_id      = user_id,
        listing_name = data['listing_name']
    ).first()

    if existing:
        return jsonify({'error': 'You have already reviewed this listing'}), 409

    review = Review(
        user_id      = user_id,
        listing_name = data['listing_name'],
        rating       = int(data['rating']),
        review_text  = data.get('review_text', '')
    )

    db.session.add(review)
    db.session.commit()
    return jsonify({'message': 'Review submitted!', 'review': review.to_dict()}), 201


@app.route('/api/reviews/<listing_name>', methods=['GET'])
def get_reviews(listing_name):
    """Get all reviews for a listing."""
    reviews = Review.query.filter_by(listing_name=listing_name).all()
    avg     = round(sum(r.rating for r in reviews) / len(reviews), 1) if reviews else 0
    return jsonify({
        'listing_name': listing_name,
        'average':      avg,
        'total':        len(reviews),
        'reviews':      [r.to_dict() for r in reviews]
    }), 200


@app.route('/api/reviews/all', methods=['GET'])
def get_all_reviews():
    """Get all reviews — admin only."""
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return jsonify([r.to_dict() for r in reviews]), 200
class Review(db.Model):
    """Student review for a listing."""
    __tablename__ = "reviews"

    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    listing_name = db.Column(db.String(200), nullable=False)
    rating       = db.Column(db.Integer, nullable=False)
    review_text  = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=db.func.now())

    def to_dict(self):
        user = User.query.get(self.user_id)
        return {
            'id':           self.id,
            'user_id':      self.user_id,
            'student_name': user.name if user else 'Anonymous',
            'listing_name': self.listing_name,
            'rating':       self.rating,
            'review_text':  self.review_text,
            'created_at':   str(self.created_at)
        }

@app.route("/api/admin/bookings", methods=["GET"])
def get_bookings():
    """Get all bookings with student and listing details."""
    bookings = Application.query.all()
    result = []
    for b in bookings:
        student = User.query.get(b.user_id)
        listing = Listing.query.get(b.listing_id)
        result.append({
            "id":            b.id,
            "student_name":  student.name if student else "Unknown",
            "listing_title": listing.title if listing else "Unknown",
            "location":      listing.location if listing else "—",
            "amount":        listing.monthly_rent if listing else 0,
            "status":        b.status,
            "created_at":    str(b.created_at),
            "message":       b.message
        })
    return jsonify(result), 200
@app.route('/public-listings')
def public_listings():
    return render_template('public_listings.html')
@app.route("/api/users", methods=["GET"])
@jwt_required()
def get_users():
    """Get all users — admin only."""
    user_id = int(get_jwt_identity())
    user    = User.query.get(user_id)

    if user.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    users = User.query.all()
    return jsonify([u.to_dict() for u in users]), 200


# ══════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════
# ══════════════════════════════════════════════
#  IMAGE MANAGEMENT ROUTES
# ══════════════════════════════════════════════

import os
from werkzeug.utils import secure_filename
from datetime import datetime

# Create images folder if it doesn't exist
IMAGES_FOLDER = os.path.join(os.path.dirname(__file__), 'static', 'images', 'listings')
os.makedirs(IMAGES_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB in bytes

def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/listings/<int:listing_id>/images', methods=['GET'])
def get_listing_images(listing_id):
    """Get all images for a listing."""
    listing = Listing.query.get_or_404(listing_id)
    listing_folder = os.path.join(IMAGES_FOLDER, str(listing_id))
    
    images = []
    if os.path.exists(listing_folder):
        for filename in os.listdir(listing_folder):
            if allowed_file(filename):
                images.append({
                    'filename': filename,
                    'url': f'/static/images/listings/{listing_id}/{filename}'
                })
    
    return jsonify({'listing_id': listing_id, 'images': images}), 200


@app.route('/api/listings/<int:listing_id>/images/upload', methods=['POST'])
@jwt_required()
def upload_listing_image(listing_id):
    """Upload an image to a listing — landlord/agent/admin only."""
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    listing = Listing.query.get_or_404(listing_id)
    
    # Permission check: only owner, agents, or admin can upload
    if user.role not in ['admin', 'agent'] and listing.owner_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Check if file is in request
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    # Validate file
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use: jpg, jpeg, png, gif, webp, bmp"}), 400
    
    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "File too large. Maximum 5MB."}), 400
    
    # Create listing folder
    listing_folder = os.path.join(IMAGES_FOLDER, str(listing_id))
    os.makedirs(listing_folder, exist_ok=True)
    
    # Save file with timestamp to avoid duplicates
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_")
    filename = secure_filename(timestamp + file.filename)
    filepath = os.path.join(listing_folder, filename)
    
    try:
        file.save(filepath)
        return jsonify({
            "message": "Image uploaded successfully",
            "filename": filename,
            "url": f"/static/images/listings/{listing_id}/{filename}"
        }), 201
    except Exception as e:
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route('/api/listings/<int:listing_id>/images/<filename>', methods=['DELETE'])
@jwt_required()
def delete_listing_image(listing_id, filename):
    """Delete an image from a listing — landlord/agent/admin only."""
    user_id = int(get_jwt_identity())
    user = User.query.get_or_404(user_id)
    listing = Listing.query.get_or_404(listing_id)
    
    # Permission check
    if user.role not in ['admin', 'agent'] and listing.owner_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403
    
    # Validate filename to prevent path traversal
    filename = secure_filename(filename)
    filepath = os.path.join(IMAGES_FOLDER, str(listing_id), filename)
    
    # Ensure the file is in the correct directory
    if not os.path.exists(filepath):
        return jsonify({"error": "Image not found"}), 404
    
    try:
        os.remove(filepath)
        return jsonify({"message": "Image deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Delete failed: {str(e)}"}), 500

if __name__ == "__main__":

    with app.app_context():
        db.create_all()
        print("[DB] Tables initialised")

        # Re-create admin if wiped
        if not User.query.filter_by(email="admin@edustay.com").first():
            hashed = bcrypt.generate_password_hash("admin123").decode("utf-8")
            db.session.add(User(
                name="Admin",
                email="admin@edustay.com",
                password_hash=hashed,
                role="admin"
            ))
            db.session.commit()
            print("[SEED] Admin account created")
        else:
            print("[SEED] Admin already exists")

    app.run(debug=True, port=5000)