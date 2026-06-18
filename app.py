"""
Cloud File Host - monolithic edition
------------------------------------
A single Flask app that serves BOTH the frontend UI and the API on one domain
(hosted on Render). Files are stored in Amazon S3. Because the UI and API are
same-origin, no CORS is needed and the browser sends the login cookie
automatically with every request.

Author:        SYED SULAIMAN USMAN
Last modified: April 18, 2026

Security notes:
  * No credentials are hardcoded - everything comes from environment variables.
  * The /upload pathway is protected by login; anonymous users cannot write to S3.
  * Uploads are validated (extension + 20 MB cap) before being streamed to S3.
"""

import os
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
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
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Load .env locally. On Render these come from the dashboard's Environment tab.
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Fail fast if any required secret is missing. Nothing is hardcoded.
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
        + "\nSet them in your .env file (local) or Render's Environment tab."
    )

AWS_REGION = os.environ["AWS_DEFAULT_REGION"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]

ALLOWED_EXTENSIONS = {"txt", "pdf", "png", "jpg", "jpeg", "zip"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB hard cap
MAX_NON_ADMIN_USERS = 3
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "users.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Harden the session cookie (defense in depth for a same-origin app).
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Render serves over HTTPS, so only send the cookie over secure connections.
# Toggle off automatically for local HTTP development.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("RENDER", "") != ""

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access that page."
login_manager.login_message_category = "warning"

# ---------------------------------------------------------------------------
# S3 client - credentials come exclusively from environment variables.
# ---------------------------------------------------------------------------
s3 = boto3.client(
    "s3",
    region_name=AWS_REGION,
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
)


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def make_s3_key(original_filename: str) -> str:
    return f"{uuid.uuid4().hex}_{secure_filename(original_filename)}"


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def public_url(key: str) -> str:
    return f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{key}"


def get_files() -> list:
    response = s3.list_objects_v2(Bucket=S3_BUCKET)
    files = []
    for obj in response.get("Contents", []):
        key = obj["Key"]
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
    files.sort(key=lambda f: f["last_modified"], reverse=True)
    return files


def registration_open() -> bool:
    return User.query.filter_by(is_admin=False).count() < MAX_NON_ADMIN_USERS


@app.context_processor
def inject_registration_status():
    return {"registration_open": registration_open()}


# ---------------------------------------------------------------------------
# Error handler: oversized upload
# ---------------------------------------------------------------------------
@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    # The upload form uses fetch() and expects JSON.
    if request.path == "/upload":
        return jsonify(error="File is too large. Maximum allowed size is 20 MB."), 413
    flash("File is too large. Maximum allowed size is 20 MB.", "danger")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Frontend route - serves the UI at the root
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    try:
        files = get_files()
    except (ClientError, BotoCoreError) as exc:
        files = []
        flash(f"Could not load files from S3: {exc}", "danger")
    return render_template("index.html", files=files)


# ---------------------------------------------------------------------------
# Secure upload route - streams the file straight to S3 (no disk buffering)
# ---------------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
@login_required
def upload():
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
        # Stream the incoming request body directly into S3.
        s3.upload_fileobj(
            file,
            S3_BUCKET,
            key,
            ExtraArgs={"ContentType": file.mimetype or "application/octet-stream"},
        )
        return jsonify(message=f"'{file.filename}' uploaded successfully."), 201
    except (ClientError, BotoCoreError) as exc:
        return jsonify(error=f"Upload failed: {exc}"), 502


@app.route("/delete/<path:key>", methods=["POST"])
@login_required
def delete(key):
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=key)
        flash("File deleted successfully.", "success")
    except (ClientError, BotoCoreError) as exc:
        flash(f"Delete failed: {exc}", "danger")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))
        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if not registration_open():
        flash("Registration limit reached. Please contact the administrator.", "warning")
        return render_template("register.html")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not email or not password:
            flash("Email and password are required.", "danger")
            return render_template("register.html")
        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "danger")
            return render_template("register.html")
        if not registration_open():
            flash("Registration limit reached. Please contact the administrator.", "warning")
            return render_template("register.html")

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
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# One-time admin creation:
#   flask --app app create-admin you@example.com YourStrongPassword
# ---------------------------------------------------------------------------
import click  # noqa: E402  (kept near its use for clarity)


@app.cli.command("create-admin")
@click.argument("email")
@click.argument("password")
def create_admin(email, password):
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
