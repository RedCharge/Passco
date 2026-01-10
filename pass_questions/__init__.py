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
        user_session = session.get("user")
        if not user_session:
            return False
        return user_session.get("session_id") == self.session_id
        
    @property
    def is_active(self):
        return True
        
    @property
    def is_anonymous(self):
        return False

# ------------------- FIREBASE CREDENTIALS HELPER -------------------
def get_firebase_credentials():
    """Get Firebase credentials for Cloud Run"""
    
    # 1. Try environment variable first (Cloud Run Secret)
    env_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
    if env_json:
        try:
            cred_dict = json.loads(env_json)
            print("✅ Using Firebase credentials from environment variable")
            return credentials.Certificate(cred_dict)
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing JSON: {e}")
    
    # 2. Try Cloud Run default credentials
    if os.getenv('K_SERVICE'):  # Running on Cloud Run
        try:
            print("🚀 Running on Cloud Run - using default credentials")
            return credentials.ApplicationDefault()
        except Exception as e:
            print(f"❌ Default credentials failed: {e}")
    
    # 3. Try local file (for development)
    local_paths = [
        'serviceAccountKey.json',
        'firebase_credentials.json',
        os.path.join(os.path.dirname(__file__), 'serviceAccountKey.json'),
        '/etc/secrets/serviceAccountKey.json',  # Cloud Run Secret path
    ]
    
    for path in local_paths:
        if Path(path).exists():
            print(f"✅ Using Firebase credentials from file: {path}")
            return credentials.Certificate(path)
    
    # 4. Try individual environment variables
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
            print(f"❌ Error creating credentials: {e}")
    
    # No credentials found
    raise FileNotFoundError(
        "❌ Firebase credentials not found!\n\n"
        "Please do ONE of these:\n"
        "1. Add serviceAccountKey.json to your project root\n"
        "2. Set FIREBASE_SERVICE_ACCOUNT_JSON environment variable\n"
        "3. On Cloud Run, add the credentials as a secret"
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
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'supersecretkey-dev-change-in-production')
    
    # Database configuration - use environment variable or SQLite
    if os.getenv('DATABASE_URL'):
        app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
    else:
        # Use relative path for SQLite
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/passquestion.db'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Create instance directory for SQLite
    instance_dir = os.path.join(BASE_DIR, 'instance')
    os.makedirs(instance_dir, exist_ok=True)

    # ------------------- DATABASE -------------------
    db.init_app(app)

    # ------------------- FLASK-LOGIN -------------------
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # ------------------- FIREBASE -------------------
    try:
        if not firebase_admin._apps:
            # Set gRPC environment variables for better performance
            os.environ['GRPC_POLL_STRATEGY'] = 'poll'
            os.environ['GRPC_ENABLE_FORK_SUPPORT'] = 'false'
            
            cred = get_firebase_credentials()
            firebase_admin.initialize_app(cred)
            app.logger.info("✅ Firebase initialized successfully")
    except Exception as e:
        app.logger.error(f"❌ Firebase initialization failed: {e}")
        # Don't crash the app, but log the error
        app.logger.warning("⚠️ Continuing without Firebase - some features disabled")
    
    # Initialize Firestore
    try:
        firestore_db = firestore.client()
        app.logger.info("✅ Firestore client initialized")
    except Exception as e:
        app.logger.error(f"❌ Firestore initialization failed: {e}")
        firestore_db = None

    # ------------------- USER LOADER -------------------
    @login_manager.user_loader
    def load_user(user_id):
        try:
            user_session = session.get("user")
            
            if not user_session:
                return None
            
            if user_session.get("uid") != user_id:
                return None
            
            # Skip Firebase check if Firestore not available
            if firestore_db is None:
                # Return user from session only
                return FirebaseUser(
                    uid=user_id,
                    email=user_session.get("email", ""),
                    username=user_session.get("username", ""),
                    role=user_session.get("role", "user"),
                    paid=user_session.get("paid", False),
                    session_id=user_session.get("session_id")
                )
            
            # Get user from Firestore
            user_doc = firestore_db.collection("users").document(user_id).get()
            
            if not user_doc.exists:
                return None
            
            user_data = user_doc.to_dict()
            active_session_id = user_data.get("active_session_id")
            session_created = user_data.get("session_created")
            
            if not active_session_id or active_session_id != user_session.get("session_id"):
                return None
            
            # Check session expiration
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

    # ------------------- BLUEPRINTS -------------------
    try:
        from pass_questions.routes.auth_routes import auth_bp
        from pass_questions.routes.admin_routes import admin_bp
        from pass_questions.routes.main_routes import main_bp

        app.register_blueprint(auth_bp, url_prefix='/auth')
        app.register_blueprint(admin_bp, url_prefix='/admin')
        app.register_blueprint(main_bp, url_prefix='/')
        
        app.logger.info("✅ Blueprints registered successfully")
    except ImportError as e:
        app.logger.error(f"❌ Failed to import blueprints: {e}")
        # Create minimal routes
        @app.route('/')
        def home():
            return "App is running. Check blueprint imports."

    # ------------------- CREATE TABLES -------------------
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("✅ Database tables created/verified")
        except Exception as e:
            app.logger.error(f"❌ Database table creation failed: {e}")

    # ------------------- ERROR HANDLERS -------------------
    @app.errorhandler(404)
    def not_found(e):
        return "Page not found", 404
    
    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"Server error: {e}")
        return "Internal server error", 500

    return app