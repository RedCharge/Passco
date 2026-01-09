import os
import json
from pathlib import Path
from flask import Flask, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta

# ------------------- GLOBAL OBJECTS -------------------
db = SQLAlchemy()
login_manager = LoginManager()

# ------------------- FIREBASE USER CLASS -------------------
class FirebaseUser(UserMixin):
    def __init__(self, uid, email, username, role, paid, session_id):
        self.id = uid
        self.uid = uid
        self.email = email
        self.username = username
        self.role = role
        self.paid = paid
        self.session_id = session_id
        
    def get_id(self):
        return self.id
        
    @property
    def is_authenticated(self):
        # Check if session is still valid
        user_session = session.get("user")
        if not user_session:
            return False
        
        # Check if session ID matches
        return user_session.get("session_id") == self.session_id
        
    @property
    def is_active(self):
        return True
        
    @property
    def is_anonymous(self):
        return False

# ------------------- FIREBASE CREDENTIALS HELPER -------------------
def get_firebase_credentials():
    """Get Firebase credentials from multiple sources"""
    
    # 1. Render Secret File (production)
    render_secret = Path('/etc/secrets/serviceAccountKey.json')
    if render_secret.exists():
        print(f"✅ Using Firebase credentials from Render Secret File: {render_secret}")
        return credentials.Certificate(str(render_secret))
    
    # 2. Environment variable with JSON string
    env_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if env_json:
        try:
            cred_dict = json.loads(env_json)
            print("✅ Using Firebase credentials from environment variable")
            return credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing FIREBASE_SERVICE_ACCOUNT_JSON: {e}")
    
    # 3. Local development file (relative to this file)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_paths = [
        os.path.join(base_dir, "serviceAccountKey.json"),  # Same directory
        "serviceAccountKey.json",  # Current working directory
        "/etc/secrets/serviceAccountKey.json",  # Alternative path
    ]
    
    for path in local_paths:
        if Path(path).exists():
            print(f"✅ Using Firebase credentials from local file: {path}")
            return credentials.Certificate(path)
    
    # 4. Try to construct from individual environment variables
    project_id = os.getenv('FIREBASE_PROJECT_ID')
    private_key = os.getenv('FIREBASE_PRIVATE_KEY')
    client_email = os.getenv('FIREBASE_CLIENT_EMAIL')
    
    if all([project_id, private_key, client_email]):
        try:
            cred_dict = {
                "type": "service_account",
                "project_id": project_id,
                "private_key_id": os.getenv('FIREBASE_PRIVATE_KEY_ID', ''),
                "private_key": private_key.replace('\\n', '\n'),
                "client_email": client_email,
                "client_id": os.getenv('FIREBASE_CLIENT_ID', ''),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.getenv('FIREBASE_CLIENT_X509_CERT_URL', ''),
                "universe_domain": "googleapis.com"
            }
            print("✅ Using Firebase credentials from individual env vars")
            return credentials.Certificate(cred_dict)
        except Exception as e:
            print(f"❌ Error creating credentials from env vars: {e}")
    
    # No credentials found
    raise FileNotFoundError(
        "❌ Firebase credentials not found. Please:\n"
        "1. Add serviceAccountKey.json as a Secret File in Render\n"
        "2. Or set FIREBASE_SERVICE_ACCOUNT_JSON environment variable\n"
        "3. Or add serviceAccountKey.json to your project directory\n"
        "Checked paths:\n" + "\n".join([f"  - {p}" for p in local_paths])
    )

# ------------------- CREATE APP -------------------
def create_app():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
    STATIC_FOLDER = os.path.join(BASE_DIR, "static")

    app = Flask(
        __name__,
        template_folder=TEMPLATE_FOLDER,
        static_folder=STATIC_FOLDER
    )

    # ------------------- CONFIG -------------------
    # Load from environment variables with defaults
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'supersecretkey-dev-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///passquestion.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Log configuration for debugging
    app.logger.info(f"Database URI: {app.config['SQLALCHEMY_DATABASE_URI'][:50]}...")
    app.logger.info(f"Using Firebase Project: {os.getenv('FIREBASE_PROJECT_ID', 'Not set')}")

    # ------------------- DATABASE -------------------
    db.init_app(app)

    # ------------------- FLASK-LOGIN -------------------
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # ------------------- FIREBASE -------------------
    try:
        if not firebase_admin._apps:  # prevent double init
            cred = get_firebase_credentials()
            firebase_admin.initialize_app(cred)
            app.logger.info("✅ Firebase initialized successfully")
    except Exception as e:
        app.logger.error(f"❌ Firebase initialization failed: {e}")
        # Continue without Firebase? Or raise error?
        # For now, we'll raise so you know it's broken
        raise
    
    # Initialize Firestore
    firestore_db = firestore.client()

    # ------------------- USER LOADER -------------------
    @login_manager.user_loader
    def load_user(user_id):
        try:
            # Get user from Flask session first
            user_session = session.get("user")
            
            if not user_session:
                return None
            
            # Verify session ID matches
            if user_session.get("uid") != user_id:
                return None
            
            # Get user from Firestore for latest data
            user_doc = firestore_db.collection("users").document(user_id).get()
            
            if not user_doc.exists:
                return None
            
            user_data = user_doc.to_dict()
            
            # Check if session is still valid
            active_session_id = user_data.get("active_session_id")
            session_created = user_data.get("session_created")
            
            if not active_session_id or active_session_id != user_session.get("session_id"):
                return None
            
            # Check session expiration (24 hours)
            if session_created:
                if hasattr(session_created, 'timestamp'):
                    session_time = session_created.replace(tzinfo=None)
                else:
                    session_time = session_created
                
                if datetime.now() - session_time > timedelta(hours=24):
                    return None
            
            return FirebaseUser(
                uid=user_id,
                email=user_data.get("email", ""),
                username=user_data.get("username", ""),
                role=user_data.get("role", "user"),
                paid=user_data.get("paid", False),
                session_id=active_session_id
            )
                
        except Exception as e:
            app.logger.error(f"Error loading user {user_id}: {str(e)}")
            return None

    # ------------------- PWA ROUTES -------------------
    @app.route('/manifest.json')
    def serve_manifest():
        return send_from_directory(
            STATIC_FOLDER,
            'manifest.json',
            mimetype='application/manifest+json'
        )

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(
            STATIC_FOLDER,
            'favicon.ico',
            mimetype='image/vnd.microsoft.icon'
        )

    @app.route('/apple-touch-icon.png')
    def apple_touch_icon():
        return send_from_directory(
            STATIC_FOLDER,
            'apple-touch-icon.png',
            mimetype='image/png'
        )

    @app.route('/apple-touch-icon-precomposed.png')
    def apple_touch_icon_precomposed():
        return send_from_directory(
            STATIC_FOLDER,
            'apple-touch-icon.png',
            mimetype='image/png'
        )

    @app.route('/android-chrome-<int:size>.png')
    def android_chrome_icon(size):
        filename = f'android-chrome-{size}x{size}.png'
        return send_from_directory(
            STATIC_FOLDER,
            filename,
            mimetype='image/png'
        )

    @app.route('/favicon-<int:size>.png')
    def favicon_png(size):
        filename = f'favicon-{size}x{size}.png'
        return send_from_directory(
            STATIC_FOLDER,
            filename,
            mimetype='image/png'
        )

    # ------------------- BLUEPRINTS -------------------
    from pass_questions.routes.auth_routes import auth_bp
    from pass_questions.routes.payment_routes import payment_bp
    from pass_questions.routes.admin_routes import admin_bp
    from pass_questions.routes.main_routes import main_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(main_bp, url_prefix='/')

    # ------------------- CREATE TABLES (for non-user data) -------------------
    with app.app_context():
        db.create_all()

    return app