"""
Cloud File Host
---------------
Flask app that uses Amazon S3 as a file store.
All configuration is read from a .env file (or real environment variables).
No database, no authentication.
"""

import os
import uuid
from functools import wraps

import boto3
import click
from botocore.exceptions import ClientError, BotoCoreError
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_cors import CORS
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Load .env before anything else so os.environ is populated.
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Fail fast: make sure every required variable is present.
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "S3_BUCKET_NAME",
    "FLASK_SECRET_KEY",
]

_missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
if _missing:
    raise RuntimeError(
        "Missing required environment variables: "
        + ", ".join(_missing)
        + "\nCopy .env.example to .env and fill in the real values."
    )

AWS_REGION = os.environ["AWS_DEFAULT_REGION"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]

# Only these extensions are accepted on upload.
ALLOWED_EXTENSIONS = {"txt", "pdf", "png", "jpg", "jpeg", "zip"}

# Hard cap that Flask enforces before the view function even runs.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# Maximum number of NON-admin users allowed to register.
MAX_NON_ADMIN_USERS = 3

# Absolute path to this file's folder, so the SQLite DB always lands here
# regardless of which directory the app is launched from (important on EC2).
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Flask app setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

# SQLite database lives in a single file, users.db, next to app.py.
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "users.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# ---------------------------------------------------------------------------
# Database + login manager
# ---------------------------------------------------------------------------
db = SQLAlchemy(app)

login_manager = LoginManager(app)
# If an anonymous user hits a @login_required route, send them here.
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access that page."
login_manager.login_message_category = "warning"

# ---------------------------------------------------------------------------
# CORS + API tokens (for the separate Vercel frontend)
# ---------------------------------------------------------------------------
# Which website(s) are allowed to call our /api/* endpoints from a browser.
# Comma-separated list in the .env file, e.g.
#   FRONTEND_ORIGINS=https://your-app.vercel.app,http://localhost:3000
# "*" means "allow any site" (fine here because the API uses bearer tokens,
# not cookies, so there is no cross-site cookie risk).
FRONTEND_ORIGINS = os.environ.get("FRONTEND_ORIGINS", "*")
_origins = [o.strip() for o in FRONTEND_ORIGINS.split(",")] if FRONTEND_ORIGINS != "*" else "*"

# Apply CORS only to the JSON API. The HTML UI is unaffected.
CORS(app, resources={r"/api/*": {"origins": _origins}})

# Signs/verifies API tokens using the app secret key. Tokens are stateless:
# they encode the user id and an expiry, so no server-side session is needed.
token_serializer = URLSafeTimedSerializer(app.secret_key, salt="api-token")
TOKEN_MAX_AGE_SECONDS = 60 * 60 * 12  # tokens valid for 12 hours

# ---------------------------------------------------------------------------
# boto3 S3 client — credentials come from the environment automatically.
# ---------------------------------------------------------------------------
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)

# ---------------------------------------------------------------------------
# User model — one row per account in the SQLite database.
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password: str) -> None:
        """Hash and store a password (never store the raw text)."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Return True if the supplied password matches the stored hash."""
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    """Flask-Login calls this to reload the user from the session cookie."""
    return db.session.get(User, int(user_id))


# Create the database tables on startup if they don't exist yet.
# Safe to run every time — it won't touch existing data.
with app.app_context():
    db.create_all()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def allowed_file(filename: str) -> bool:
    """Return True only when the file has an allowed extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def make_s3_key(original_filename: str) -> str:
    """Return a collision-proof S3 key: <uuid_hex>_<safe_filename>."""
    return f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"


def human_size(num_bytes: int) -> str:
    """Convert a byte count to a human-readable string (e.g. '1.4 MB')."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def public_url(key: str) -> str:
    """Build the public HTTPS URL for an S3 object."""
    return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"


def get_files() -> list:
    """Return a sorted list of file-info dicts for every object in the bucket."""
    response = s3.list_objects_v2(Bucket=S3_BUCKET)
    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
        # Strip the uuid prefix to show the original filename.
        display = key.split("_", 1)[1] if "_" in key else key
        files.append(
            {
                "key": key,
                "name": display,
                "size": human_size(obj["Size"]),
                "last_modified": obj["LastModified"].strftime("%Y-%m-%d %H:%M"),
                "url": public_url(key),
            }
        )
    # Newest first.
    files.sort(key=lambda f: f["last_modified"], reverse=True)
    return files


# ---------------------------------------------------------------------------
# Error handler: file too large (triggered by MAX_CONTENT_LENGTH)
# ---------------------------------------------------------------------------
@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    # API clients get JSON; the HTML UI gets a flash + redirect.
    if request.path.startswith("/api/"):
        return jsonify(error="File is too large. Maximum allowed size is 20 MB."), 413
    flash("File is too large. Maximum allowed size is 20 MB.", "danger")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    """Dashboard — list files stored in the S3 bucket."""
    try:
        files = get_files()
    except (ClientError, BotoCoreError) as exc:
        files = []
        flash(f"Could not load files from S3: {exc}", "danger")
    return render_template("index.html", files=files)


@app.route("/upload", methods=["POST"])
@login_required
def upload():
    """Receive a file, validate it, and stream it to S3."""

    # --- 1. Field must exist ---
    if "file" not in request.files:
        flash("No file field in the request.", "danger")
        return redirect(url_for("index"))

    file = request.files["file"]

    # --- 2. A filename must be present ---
    if not file.filename:
        flash("No file selected. Please choose a file to upload.", "danger")
        return redirect(url_for("index"))

    # --- 3. Extension check ---
    if not allowed_file(file.filename):
        flash(
            "File type not allowed. Accepted types: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
            + ".",
            "danger",
        )
        return redirect(url_for("index"))

    # --- 4. Content-length double-check (belt-and-suspenders) ---
    content_length = request.content_length
    if content_length and content_length > MAX_UPLOAD_BYTES:
        flash("File is too large. Maximum allowed size is 20 MB.", "danger")
        return redirect(url_for("index"))

    # --- 5. Upload to S3 ---
    key = make_s3_key(file.filename)
    try:
        s3.upload_fileobj(
            file,
            S3_BUCKET,
            key,
            ExtraArgs={
                "ContentType": file.mimetype or "application/octet-stream",
            },
        )
        flash(f"'{file.filename}' uploaded successfully.", "success")
    except (ClientError, BotoCoreError) as exc:
        flash(f"Upload failed: {exc}", "danger")

    return redirect(url_for("index"))


@app.route("/delete/<path:key>", methods=["POST"])
@login_required
def delete(key):
    """Delete a single object from the bucket."""
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        flash("File deleted successfully.", "success")
    except (ClientError, BotoCoreError) as exc:
        flash(f"Delete failed: {exc}", "danger")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Authentication helpers + routes
# ---------------------------------------------------------------------------

def registration_open() -> bool:
    """True while fewer than MAX_NON_ADMIN_USERS non-admin accounts exist."""
    non_admin_count = User.query.filter_by(is_admin=False).count()
    return non_admin_count < MAX_NON_ADMIN_USERS


# Make registration_open available inside every template (e.g. to hide links).
@app.context_processor
def inject_registration_status():
    return {"registration_open": registration_open()}


@app.route("/login", methods=["GET", "POST"])
def login():
    """Show the login form and authenticate the user."""
    # Already logged in? Go straight to the dashboard.
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        # Verify the user exists AND the password matches the stored hash.
        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))

        # Generic message — don't reveal whether the email or password was wrong.
        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register a new non-admin user, up to the configured limit."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    # Block registration entirely once the limit is reached.
    if not registration_open():
        flash("Registration limit reached. Please contact the administrator.", "warning")
        return render_template("register.html")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        # --- Basic validation ---
        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return render_template("register.html")

        # Re-check the limit right before writing (defends against races).
        if not registration_open():
            flash("Registration limit reached. Please contact the administrator.", "warning")
            return render_template("register.html")

        # --- Create the new non-admin user ---
        user = User(email=email, is_admin=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash("Account created. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    """End the current session."""
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# One-time CLI command to create the admin (you).
# Run:  flask --app app create-admin you@example.com YourStrongPassword
# ---------------------------------------------------------------------------
@app.cli.command("create-admin")
@click.argument("email")
@click.argument("password")
def create_admin(email, password):
    """Create (or promote) an admin user. Admins ignore the 3-user limit."""
    email = email.strip().lower()
    existing = User.query.filter_by(email=email).first()
    if existing:
        existing.is_admin = True
        existing.set_password(password)
        db.session.commit()
        click.echo(f"Updated existing user '{email}' and made them admin.")
        return

    admin = User(email=email, is_admin=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    click.echo(f"Admin user '{email}' created successfully.")


# ---------------------------------------------------------------------------
# JSON API for the Vercel frontend (token-based auth, no cookies)
# ---------------------------------------------------------------------------

def token_required(view):
    """Decorator: require a valid 'Authorization: Bearer <token>' header."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify(error="Missing or invalid Authorization header."), 401

        token = auth.split(" ", 1)[1].strip()
        try:
            user_id = token_serializer.loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
        except SignatureExpired:
            return jsonify(error="Token expired. Please log in again."), 401
        except BadSignature:
            return jsonify(error="Invalid token."), 401

        user = db.session.get(User, int(user_id))
        if user is None:
            return jsonify(error="User no longer exists."), 401

        # Stash the user for the view to use.
        g.api_user = user
        return view(*args, **kwargs)

    return wrapped


@app.get("/api/health")
def api_health():
    """Public endpoint the frontend pings to show 'backend online'."""
    return jsonify(status="ok", service="cloud-file-host")


@app.post("/api/login")
def api_login():
    """Authenticate via JSON and return a signed bearer token."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    user = User.query.filter_by(email=email).first()
    if user and user.check_password(password):
        token = token_serializer.dumps(str(user.id))
        return jsonify(token=token, email=user.email, is_admin=user.is_admin)

    return jsonify(error="Invalid email or password."), 401


@app.get("/api/me")
@token_required
def api_me():
    """Return info about the currently authenticated user."""
    user = g.api_user
    return jsonify(email=user.email, is_admin=user.is_admin)


@app.get("/api/files")
@token_required
def api_files():
    """Return the list of files in the S3 bucket as JSON."""
    try:
        return jsonify(files=get_files())
    except (ClientError, BotoCoreError) as exc:
        return jsonify(error=f"Could not load files from S3: {exc}"), 502


@app.post("/api/upload")
@token_required
def api_upload():
    """Accept a multipart file upload and store it in S3."""
    if "file" not in request.files:
        return jsonify(error="No file field in the request."), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify(error="No file selected."), 400

    if not allowed_file(file.filename):
        return jsonify(
            error="File type not allowed. Accepted: "
            + ", ".join(sorted(ALLOWED_EXTENSIONS))
        ), 400

    key = make_s3_key(file.filename)
    try:
        s3.upload_fileobj(
            file,
            S3_BUCKET,
            key,
            ExtraArgs={"ContentType": file.mimetype or "application/octet-stream"},
        )
        return jsonify(message=f"'{file.filename}' uploaded successfully."), 201
    except (ClientError, BotoCoreError) as exc:
        return jsonify(error=f"Upload failed: {exc}"), 502


@app.post("/api/delete")
@token_required
def api_delete():
    """Delete an object from S3. Expects JSON: {"key": "<s3-key>"}."""
    data = request.get_json(silent=True) or {}
    key = data.get("key")
    if not key:
        return jsonify(error="Missing 'key'."), 400

    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        return jsonify(message="File deleted successfully.")
    except (ClientError, BotoCoreError) as exc:
        return jsonify(error=f"Delete failed: {exc}"), 502


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
