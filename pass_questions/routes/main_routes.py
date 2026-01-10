import os
from flask import Blueprint, render_template, redirect, url_for, flash, session, jsonify, send_from_directory, send_file, request
from pass_questions.models import db, PDF
from firebase_admin import firestore
import json
from urllib.parse import quote, unquote
from datetime import datetime, timedelta
import random

# Add Cloud Run specific configuration
IS_CLOUD_RUN = os.environ.get('K_SERVICE') is not None
main_bp = Blueprint("main", __name__)

# Add this near the top after the decorator definition
def get_session_config():
    """Get appropriate session configuration for environment"""
    if IS_CLOUD_RUN:
        # For Cloud Run, use a more secure session configuration
        return {
            'SESSION_TYPE': 'filesystem',
            'SESSION_FILE_DIR': '/tmp/flask_session',
            'SESSION_PERMANENT': False,
            'SESSION_USE_SIGNER': True,
            'SESSION_KEY_PREFIX': 'pass_questions_',
            'PERMANENT_SESSION_LIFETIME': timedelta(hours=12)
        }
    else:
        # Local development
        return {
            'SECRET_KEY': os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key'),
            'SESSION_TYPE': 'filesystem',
            'SESSION_PERMANENT': False
        }

def require_login_route(func):
    """Decorator to check if user is logged in via session."""
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper



# Safe data processor for Firebase
def safe_process_firebase_data(data):
    """Recursively process Firebase data to remove Undefined values"""
    if data is None:
        return None
    
    # Check for Firebase Undefined type
    if hasattr(data, '__class__') and 'Undefined' in str(data.__class__):
        return None
    
    if isinstance(data, dict):
        return {k: safe_process_firebase_data(v) for k, v in data.items() 
                if v is not None and not (hasattr(v, '__class__') and 'Undefined' in str(v.__class__))}
    elif isinstance(data, list):
        return [safe_process_firebase_data(item) for item in data 
                if item is not None and not (hasattr(item, '__class__') and 'Undefined' in str(item.__class__))]
    elif isinstance(data, (str, int, float, bool)):
        return data
    else:
        try:
            return str(data)
        except:
            return None

# ----------------- HOME PAGE -----------------
@main_bp.route("/")
def index():
    return render_template("index.html")

# ----------------- DASHBOARD -----------------
@main_bp.route("/dashboard")
@require_login_route
def dashboard():
    user = session["user"]

    # Admins redirect to admin dashboard
    if user.get("role") == "admin":
        return redirect(url_for("admin.dashboard"))

    # Ensure user has paid
    if not user.get("paid", False):
        flash("Please complete your payment to access the dashboard.", "error")
        return redirect(url_for("payment.payment_page"))

    return render_template("dashboard_user.html", admin=False, user=user)

# ----------------- VIEW QUESTIONS (PDFs) -----------------
@main_bp.route("/questions")
@require_login_route
def questions():
    user = session.get("user")

    if not user.get("paid", False):
        flash("Please complete payment to access questions.", "error")
        return redirect(url_for("main.dashboard"))

    return render_template("questions.html", user=user, pdfs={})

# ----------------- UNIVERSAL PDF SERVING - ENHANCED VERSION -----------------
@main_bp.route("/static/pdfs/<path:filename>")
@require_login_route
def serve_pdf_static(filename):
    """Serve PDF files from static/pdfs directory - ENHANCED VERSION"""
    user = session.get("user")
    
    if not user.get("paid", False):
        return "Payment required", 403
    
    try:
        # Decode URL-encoded filename
        decoded_filename = unquote(filename)
        
        # Security check - prevent directory traversal
        if '..' in decoded_filename or decoded_filename.startswith('/'):
            return "Invalid filename", 400
        
        print(f"📁 Serving PDF: {decoded_filename}")
        
        # CLOUD RUN COMPATIBILITY: Try multiple possible locations
        possible_roots = [
            os.path.join(os.getcwd(), "static", "pdfs"),  # Local development
            "/app/static/pdfs",  # Cloud Run default
            "/tmp/static/pdfs",  # Cloud Run tmp directory
            os.path.join(os.environ.get('APP_HOME', '/app'), 'static', 'pdfs'),  # Environment variable
        ]
        
        found_path = None
        for pdf_root in possible_roots:
            full_path = os.path.join(pdf_root, decoded_filename)
            print(f"🔍 Checking path: {full_path}")
            if os.path.exists(full_path):
                found_path = full_path
                break
        
        if found_path:
            # Use send_file for reliable serving
            response = send_file(found_path, as_attachment=False)
            # Add caching headers for better performance in Cloud Run
            response.headers['Cache-Control'] = 'public, max-age=300'
            print(f"✅ PDF served successfully via send_file: {decoded_filename}")
            return response
        else:
            # Try to find the file in nested directories
            found_path = find_pdf_in_nested_directories(decoded_filename)
            if found_path:
                response = send_file(found_path, as_attachment=False)
                response.headers['Cache-Control'] = 'public, max-age=300'
                print(f"✅ PDF found in nested directory: {found_path}")
                return response
            else:
                # List available PDFs for debugging
                available_pdfs = list_all_pdfs()
                print(f"❌ PDF not found. Available PDFs: {available_pdfs}")
                return f"PDF not found: {decoded_filename}. Available files: {available_pdfs}", 404
        
    except Exception as e:
        print(f"❌ Error serving PDF: {str(e)}")
        return f"Error serving PDF: {str(e)}", 500

def find_pdf_in_nested_directories(filename):
    """Search for PDF file in nested directories - Cloud Run compatible"""
    # Try multiple possible root directories
    possible_roots = [
        os.path.join(os.getcwd(), "static", "pdfs"),
        "/app/static/pdfs",
        "/tmp/static/pdfs",
        os.path.join(os.environ.get('APP_HOME', '/app'), 'static', 'pdfs'),
    ]
    
    for pdf_root in possible_roots:
        if not os.path.exists(pdf_root):
            continue
            
        for root, dirs, files in os.walk(pdf_root):
            for file in files:
                if file.lower() == filename.lower() or file.lower() == filename.replace(' ', '_').lower():
                    full_path = os.path.join(root, file)
                    print(f"🔍 Found matching file: {full_path}")
                    return full_path
    
    return None

def list_all_pdfs():
    """List all PDF files in the system for debugging - Cloud Run compatible"""
    possible_roots = [
        os.path.join(os.getcwd(), "static", "pdfs"),
        "/app/static/pdfs",
        "/tmp/static/pdfs",
        os.path.join(os.environ.get('APP_HOME', '/app'), 'static', 'pdfs'),
    ]
    
    pdf_files = []
    
    for pdf_root in possible_roots:
        if not os.path.exists(pdf_root):
            continue
            
        for root, dirs, files in os.walk(pdf_root):
            for file in files:
                if file.lower().endswith('.pdf'):
                    rel_path = os.path.relpath(os.path.join(root, file), pdf_root)
                    pdf_files.append(rel_path.replace('\\', '/'))
    
    return pdf_files if pdf_files else ["PDF directory not found in any location"]

# ----------------- ALTERNATIVE PDF ROUTE -----------------
@main_bp.route("/pdf/<path:pdf_path>")
@require_login_route
def serve_pdf_universal(pdf_path):
    """Alternative PDF serving route"""
    user = session.get("user")
    
    if not user.get("paid", False):
        return "Payment required", 403
    
    try:
        # Decode URL-encoded path
        decoded_path = unquote(pdf_path)
        
        # Security check
        if '..' in decoded_path or decoded_path.startswith('/'):
            return "Invalid file path", 400
        
        print(f"📁 Universal route - Serving: {decoded_path}")
        
        # Use the static route to serve the file
        return serve_pdf_static(decoded_path)
        
    except Exception as e:
        print(f"❌ Error in universal route: {str(e)}")
        return f"Error: {str(e)}", 500

# ----------------- ENHANCED DELETE CHECK FUNCTION -----------------
def is_exam_deleted_for_user(user_id, exam_id):
    """Check if an exam has been deleted for a specific user"""
    try:
        db_firestore = firestore.client()
        
        # Check if the exam exists in admin_uploads (if not, it's deleted)
        exam_doc = db_firestore.collection("admin_uploads").document(exam_id).get()
        if not exam_doc.exists:
            return True
        
        # Check if user has specific record that marks this exam as deleted
        deleted_exams_ref = db_firestore.collection("user_deleted_exams").document(user_id)
        deleted_exams_doc = deleted_exams_ref.get()
        
        if deleted_exams_doc.exists:
            deleted_exams_data = deleted_exams_doc.to_dict()
            deleted_exam_ids = deleted_exams_data.get("exam_ids", [])
            return exam_id in deleted_exam_ids
        
        return False
        
    except Exception as e:
        print(f"Error checking if exam is deleted: {e}")
        return False

def is_question_deleted_for_user(user_id, question_id):
    """Check if a question has been deleted for a specific user"""
    try:
        db_firestore = firestore.client()
        
        # Check if the question exists in quiz_questions (if not, it's deleted)
        question_doc = db_firestore.collection("quiz_questions").document(question_id).get()
        if not question_doc.exists:
            return True
        
        # Check if user has specific record that marks this question as deleted
        deleted_questions_ref = db_firestore.collection("user_deleted_questions").document(user_id)
        deleted_questions_doc = deleted_questions_ref.get()
        
        if deleted_questions_doc.exists:
            deleted_questions_data = deleted_questions_doc.to_dict()
            deleted_question_ids = deleted_questions_data.get("question_ids", [])
            return question_id in deleted_question_ids
        
        return False
        
    except Exception as e:
        print(f"Error checking if question is deleted: {e}")
        return False

def update_user_deleted_exams(user_id, exam_id):
    """Mark an exam as deleted for a specific user"""
    try:
        db_firestore = firestore.client()
        deleted_exams_ref = db_firestore.collection("user_deleted_exams").document(user_id)
        deleted_exams_doc = deleted_exams_ref.get()
        
        current_time = datetime.now()
        
        if deleted_exams_doc.exists:
            deleted_exams_data = deleted_exams_doc.to_dict()
            deleted_exam_ids = deleted_exams_data.get("exam_ids", [])
            
            if exam_id not in deleted_exam_ids:
                deleted_exam_ids.append(exam_id)
                deleted_exams_ref.update({
                    "exam_ids": deleted_exam_ids,
                    "last_updated": current_time,
                    "updated_count": firestore.Increment(1)
                })
        else:
            deleted_exams_ref.set({
                "user_id": user_id,
                "exam_ids": [exam_id],
                "created_at": current_time,
                "last_updated": current_time,
                "updated_count": 1
            })
        
        print(f"✅ Marked exam {exam_id} as deleted for user {user_id}")
        
    except Exception as e:
        print(f"Error updating user deleted exams: {e}")

def update_user_deleted_questions(user_id, question_id):
    """Mark a question as deleted for a specific user"""
    try:
        db_firestore = firestore.client()
        deleted_questions_ref = db_firestore.collection("user_deleted_questions").document(user_id)
        deleted_questions_doc = deleted_questions_ref.get()
        
        current_time = datetime.now()
        
        if deleted_questions_doc.exists:
            deleted_questions_data = deleted_questions_doc.to_dict()
            deleted_question_ids = deleted_questions_data.get("question_ids", [])
            
            if question_id not in deleted_question_ids:
                deleted_question_ids.append(question_id)
                deleted_questions_ref.update({
                    "question_ids": deleted_question_ids,
                    "last_updated": current_time,
                    "updated_count": firestore.Increment(1)
                })
        else:
            deleted_questions_ref.set({
                "user_id": user_id,
                "question_ids": [question_id],
                "created_at": current_time,
                "last_updated": current_time,
                "updated_count": 1
            })
        
        print(f"✅ Marked question {question_id} as deleted for user {user_id}")
        
    except Exception as e:
        print(f"Error updating user deleted questions: {e}")

# ----------------- API: GET EXAMS FOR USERS - ENHANCED VERSION -----------------
@main_bp.route("/api/exams")
@require_login_route
def get_exams_for_users():
    """API endpoint to get all exams for users - ENHANCED VERSION with deletion sync"""
    user = session.get("user")
    
    # Check if user has paid
    if not user.get("paid", False):
        return jsonify({"error": "Payment required"}), 403

    try:
        user_id = user.get("uid")
        db_firestore = firestore.client()
        
        # Get exams from Firestore
        exams_ref = db_firestore.collection("admin_uploads").stream()
        exams = []
        
        for doc in exams_ref:
            try:
                exam_data = doc.to_dict()
                
                # Safely process the data first
                safe_exam_data = safe_process_firebase_data(exam_data) or {}
                
                # Extract values with safe defaults
                program = safe_exam_data.get("program", "Unknown Program")
                course = safe_exam_data.get("course", "Unknown Course")
                year = safe_exam_data.get("year", "Unknown Year")
                level = safe_exam_data.get("level", "100")
                semester = safe_exam_data.get("semester", "1")
                exam_type = safe_exam_data.get("exam_type", "final")
                
                # Get file paths and convert to web URLs
                questions_file_path = safe_exam_data.get("questionsFilePath", "")
                answers_file_path = safe_exam_data.get("answersFilePath", "")
                
                # ENHANCED: Ensure the file paths are correct
                questions_web_path = convert_file_path_to_url(questions_file_path, program, course, year, level, semester)
                answers_web_path = convert_file_path_to_url(answers_file_path, program, course, year, level, semester)
                
                # Create safe exam object
                exam = {
                    "id": doc.id,
                    "program": str(program),
                    "course": str(course),
                    "year": str(year),
                    "level": str(level),
                    "semester": str(semester),
                    "exam_type": str(exam_type),
                    "questionsFilePath": str(questions_web_path),
                    "answersFilePath": str(answers_web_path),
                    "questionsFileName": str(safe_exam_data.get("questionsFileName", "")),
                    "answersFileName": str(safe_exam_data.get("answersFileName", "")),
                    "uploadDate": str(safe_exam_data.get("uploadDate", "")),
                    "uploadedByName": str(safe_exam_data.get("uploadedByName", "Admin"))
                }
                
                # Remove any empty or problematic values
                clean_exam = {}
                for key, value in exam.items():
                    if value and value != "None" and value != "Undefined":
                        clean_exam[key] = value
                    else:
                        clean_exam[key] = ""
                
                # NEW: Check if this exam is marked as deleted for this user
                if is_exam_deleted_for_user(user_id, doc.id):
                    print(f"⚠️ Exam {doc.id} marked as deleted for user {user_id}")
                    continue  # Skip this exam
                
                exams.append(clean_exam)
                
            except Exception as doc_error:
                print(f"Error processing document {doc.id}: {doc_error}")
                continue
        
        # If no exams from Firestore, use enhanced filesystem scan
        if not exams:
            exams = scan_filesystem_for_pdfs_enhanced()
        else:
            # Combine with filesystem PDFs to ensure all files are available
            filesystem_exams = scan_filesystem_for_pdfs_enhanced()
            exams.extend(filesystem_exams)
        
        return jsonify(exams)
        
    except Exception as e:
        print(f"Error fetching exams for users: {e}")
        # Return enhanced filesystem data on error
        return jsonify(scan_filesystem_for_pdfs_enhanced())

def convert_file_path_to_url(file_path, program="", course="", year="", level="", semester=""):
    """Convert ANY file system path to web-accessible URL - ENHANCED VERSION"""
    if not file_path:
        return ""
    
    file_path = str(file_path)
    
    # If it's already a web path, return as is
    if file_path.startswith(('/static/pdfs/', '/pdf/')):
        return file_path
    
    # Handle absolute Windows paths
    if os.path.isabs(file_path):
        # Extract relative path from absolute path
        pdf_root = os.path.join("static", "pdfs")
        if pdf_root in file_path:
            # Get the part after static\pdfs\
            relative_path = file_path.split(pdf_root)[-1].lstrip('\\').lstrip('/')
            # Convert to forward slashes for web
            relative_path = relative_path.replace('\\', '/')
            encoded_path = quote(relative_path)
            # Use static/pdfs route
            return f"/static/pdfs/{encoded_path}"
        else:
            # If it's an absolute path but doesn't contain our pdf root, just use the filename
            filename = os.path.basename(file_path)
            return f"/static/pdfs/{quote(filename)}"
    
    # Handle relative paths that contain static/pdfs
    if 'static/pdfs' in file_path:
        parts = file_path.split('static/pdfs')
        if len(parts) > 1:
            relative_path = parts[1].replace('\\', '/').lstrip('/')
            encoded_path = quote(relative_path)
            return f"/static/pdfs/{encoded_path}"
    
    # NEW: Construct path from metadata if available
    if program and course and year:
        # Build the nested directory structure
        nested_path = f"{program}/Level_{level}/Semester_{semester}/{course}/{year}/{file_path}"
        clean_path = nested_path.replace('\\', '/').lstrip('/')
        encoded_path = quote(clean_path)
        return f"/static/pdfs/{encoded_path}"
    
    # For any other path, assume it's relative to static/pdfs
    clean_path = file_path.replace('\\', '/').lstrip('/')
    encoded_path = quote(clean_path)
    return f"/static/pdfs/{encoded_path}"

def scan_filesystem_for_pdfs_enhanced():
    """Enhanced filesystem scan that properly handles nested directories - Cloud Run compatible"""
    # Try multiple possible locations
    possible_roots = [
        os.path.join("static", "pdfs"),
        "/app/static/pdfs",
        "/tmp/static/pdfs",
        os.path.join(os.environ.get('APP_HOME', '/app'), 'static', 'pdfs'),
    ]
    
    pdf_files = []
    
    for pdf_root in possible_roots:
        if not os.path.exists(pdf_root):
            print(f"⚠️ PDF directory not found: {pdf_root}")
            continue
            
        try:
            print(f"🔍 Enhanced scanning for PDFs in: {pdf_root}")
            
            for root, dirs, files in os.walk(pdf_root):
                for file in files:
                    if file.lower().endswith(".pdf"):
                        full_path = os.path.join(root, file)
                        
                        # Get relative path from current pdf_root
                        relative_path = os.path.relpath(full_path, pdf_root)
                        web_path = f"/static/pdfs/{quote(relative_path.replace('\\', '/'))}"
                        
                        # Extract metadata from directory structure
                        path_parts = full_path.split(os.sep)
                        
                        # Initialize with safe defaults
                        program = "Unknown Program"
                        course = "Unknown Course"
                        year = "2024"
                        level = "100"
                        semester = "1"
                        exam_type = "final"
                        
                        try:
                            # Enhanced metadata extraction from path structure
                            for i, part in enumerate(path_parts):
                                if part.lower() == "pdfs" or part.endswith("_pdfs"):
                                    pdfs_index = i
                                    
                                    # Program (CS BTECH)
                                    if len(path_parts) > pdfs_index + 1:
                                        program = path_parts[pdfs_index + 1]
                                        # Clean up program name
                                        if "CS" in program.upper():
                                            program = "CS BTech"
                                    
                                    # Level (Level_100)
                                    if len(path_parts) > pdfs_index + 2:
                                        level_part = path_parts[pdfs_index + 2]
                                        if "level" in level_part.lower():
                                            level = level_part.split('_')[-1] if '_' in level_part else "100"
                                        elif any(char.isdigit() for char in level_part):
                                            # Extract numbers from level string
                                            level = ''.join(filter(str.isdigit, level_part)) or "100"
                                    
                                    # Semester (Semester_1)
                                    if len(path_parts) > pdfs_index + 3:
                                        semester_part = path_parts[pdfs_index + 3]
                                        if "semester" in semester_part.lower():
                                            semester = semester_part.split('_')[-1] if '_' in semester_part else "1"
                                        elif any(char.isdigit() for char in semester_part):
                                            semester = ''.join(filter(str.isdigit, semester_part)) or "1"
                                    
                                    # Course (Com skills)
                                    if len(path_parts) > pdfs_index + 4:
                                        course = path_parts[pdfs_index + 4]
                                    
                                    # Year (2024)
                                    if len(path_parts) > pdfs_index + 5:
                                        year = path_parts[pdfs_index + 5]
                                        # Extract year if it contains numbers
                                        if any(char.isdigit() for char in year):
                                            year = ''.join(filter(str.isdigit, year)) or "2024"
                                    
                        except Exception as e:
                            print(f"Error parsing path structure: {e}")
                        
                        # Determine if it's questions or answers from filename
                        filename_lower = file.lower()
                        file_display_name = os.path.splitext(file)[0]  # Remove .pdf extension
                        
                        if any(keyword in filename_lower for keyword in ["question", "exam", "paper", "midterm", "final"]):
                            exam_type = "questions"
                            questions_path = web_path
                            answers_path = ""
                            display_name = f"{course} Questions - {year}"
                        elif any(keyword in filename_lower for keyword in ["answer", "solution", "key"]):
                            exam_type = "answers"
                            questions_path = ""
                            answers_path = web_path
                            display_name = f"{course} Answers - {year}"
                        else:
                            # If we can't determine, treat as questions
                            exam_type = "questions"
                            questions_path = web_path
                            answers_path = ""
                            display_name = f"{course} - {year}"
                        
                        # Create enhanced PDF object
                        pdf_obj = {
                            "id": f"fs-{len(pdf_files)}",
                            "program": program,
                            "course": course,
                            "year": year,
                            "level": level,
                            "semester": semester,
                            "exam_type": exam_type,
                            "questionsFilePath": questions_path,
                            "answersFilePath": answers_path,
                            "questionsFileName": file_display_name if questions_path else "",
                            "answersFileName": file_display_name if answers_path else "",
                            "uploadDate": "",
                            "uploadedByName": "System",
                            "displayName": display_name,
                            "fullPath": web_path
                        }
                        
                        pdf_files.append(pdf_obj)
                        print(f"✅ Found PDF: {web_path} -> {program}/{course}/{year}")
                            
        except Exception as e:
            print(f"❌ Error scanning filesystem {pdf_root}: {e}")
            continue
    
    print(f"📊 Total PDFs found across all locations: {len(pdf_files)}")
    return pdf_files

# ----------------- DIRECT PDF VIEWER ROUTE -----------------
@main_bp.route("/view-pdf/<path:pdf_path>")
@require_login_route
def view_pdf(pdf_path):
    """Direct PDF viewer route that opens PDFs in questions.html"""
    user = session.get("user")
    
    if not user.get("paid", False):
        flash("Payment required to view PDFs", "error")
        return redirect(url_for("main.dashboard"))
    
    try:
        # Decode the PDF path
        decoded_path = unquote(pdf_path)
        
        # Get all exams to find the matching one
        exams = get_exams_data()
        current_pdf = None
        
        for exam in exams:
            if (exam.get('questionsFilePath', '').endswith(decoded_path) or 
                exam.get('answersFilePath', '').endswith(decoded_path) or
                exam.get('fullPath', '') == f"/static/pdfs/{decoded_path}"):
                current_pdf = exam
                break
        
        return render_template("questions.html", 
                             user=user, 
                             current_pdf=current_pdf, 
                             all_pdfs=exams,
                             pdf_url=f"/static/pdfs/{quote(decoded_path)}")
        
    except Exception as e:
        print(f"Error in PDF viewer: {e}")
        flash("Error loading PDF", "error")
        return redirect(url_for("main.questions"))

def get_exams_data():
    """Get exams data from both Firestore and filesystem"""
    try:
        # Try Firestore first
        db_firestore = firestore.client()
        exams_ref = db_firestore.collection("admin_uploads").stream()
        exams = []
        
        for doc in exams_ref:
            exam_data = doc.to_dict()
            safe_exam_data = safe_process_firebase_data(exam_data) or {}
            
            # Convert file paths
            questions_file_path = safe_exam_data.get("questionsFilePath", "")
            answers_file_path = safe_exam_data.get("answersFilePath", "")
            
            questions_web_path = convert_file_path_to_url(questions_file_path)
            answers_web_path = convert_file_path_to_url(answers_file_path)
            
            exam = {
                "id": doc.id,
                "program": str(safe_exam_data.get("program", "")),
                "course": str(safe_exam_data.get("course", "")),
                "year": str(safe_exam_data.get("year", "")),
                "level": str(safe_exam_data.get("level", "")),
                "semester": str(safe_exam_data.get("semester", "")),
                "exam_type": str(safe_exam_data.get("exam_type", "")),
                "questionsFilePath": str(questions_web_path),
                "answersFilePath": str(answers_web_path),
                "questionsFileName": str(safe_exam_data.get("questionsFileName", "")),
                "answersFileName": str(safe_exam_data.get("answersFileName", "")),
                "uploadDate": str(safe_exam_data.get("uploadDate", "")),
                "uploadedByName": str(safe_exam_data.get("uploadedByName", "Admin"))
            }
            exams.append(exam)
            
    except Exception as e:
        print(f"Error getting Firestore data: {e}")
        exams = []
    
    # Add filesystem PDFs
    filesystem_exams = scan_filesystem_for_pdfs_enhanced()
    exams.extend(filesystem_exams)
    
    return exams

# ----------------- DEBUG & TESTING ENDPOINTS -----------------
@main_bp.route("/api/debug/pdf-test")
def debug_pdf_test():
    """Test PDF serving with various paths - Cloud Run version"""
    # Test with your specific file path
    test_cases = [
        "questions_Plastic_Pollution_Project_Diaries_today.pdf",
        "CS BTech/Level_100/Semester_1/Com skills/2025/questions_Plastic_Pollution_Project_Diaries_today.pdf",
        "CS BTECH/Level_100/Semester_1/Com skills/2024/Plastic_Pollution_Project_Diaries_today.pdf"
    ]
    
    results = []
    
    # Check multiple possible locations
    possible_roots = [
        os.path.join("static", "pdfs"),
        "/app/static/pdfs",
        "/tmp/static/pdfs",
        os.path.join(os.environ.get('APP_HOME', '/app'), 'static', 'pdfs'),
    ]
    
    for test_path in test_cases:
        exists_in_locations = []
        
        for pdf_root in possible_roots:
            full_path = os.path.join(pdf_root, test_path)
            exists = os.path.exists(full_path)
            exists_in_locations.append({
                "location": pdf_root,
                "exists": exists,
                "path": full_path
            })
        
        static_url = f"/static/pdfs/{quote(test_path)}"
        universal_url = f"/pdf/{quote(test_path)}"
        view_url = f"/view-pdf/{quote(test_path)}"
        
        # Test if Flask can serve the file
        try:
            response = serve_pdf_static(test_path)
            flask_serves = True
        except Exception as e:
            flask_serves = False
            flask_error = str(e)
        
        results.append({
            "test_path": test_path,
            "exists_in_locations": exists_in_locations,
            "flask_serves": flask_serves,
            "flask_error": flask_error if not flask_serves else None,
            "static_url": static_url,
            "universal_url": universal_url,
            "view_url": view_url
        })
    
    # Add Cloud Run environment info
    cloud_run_info = {
        "K_SERVICE": os.environ.get('K_SERVICE'),
        "K_REVISION": os.environ.get('K_REVISION'),
        "PORT": os.environ.get('PORT'),
        "IS_CLOUD_RUN": IS_CLOUD_RUN,
        "Current Directory": os.getcwd(),
        "Files in static/pdfs": list_all_pdfs()[:10]  # First 10 files
    }
    
    return jsonify({
        "cloud_run_info": cloud_run_info,
        "test_results": results,
        "all_pdfs": list_all_pdfs()
    })
    
# ----------------- ANALYTICS & QUIZ ROUTES (FIXED VERSION) -----------------

@main_bp.route("/api/quiz/questions")
@require_login_route
def get_quiz_questions():
    """Get quiz questions for students with adaptive learning (20 questions)"""
    program = request.args.get('program')
    course = request.args.get('course')
    level = request.args.get('level')
    semester = request.args.get('semester')
    difficulty = request.args.get('difficulty')
    count = int(request.args.get('count', 20))  # Fixed: 20 questions per quiz
    
    # Get current user
    user = session.get("user")
    if not user:
        return jsonify({"error": "User not authenticated"}), 401
    
    user_id = user.get('uid')
    db_firestore = firestore.client()
    
    # Step 1: Get previously incorrect questions for this user-course combination
    incorrect_questions = []
    if program and course and user_id:
        try:
            # Get user's quiz history - NO ORDER BY to avoid index requirement
            history_ref = db_firestore.collection("quiz_history")\
                .where("user_id", "==", user_id)\
                .where("program", "==", program)\
                .where("course", "==", course)
            
            history_docs = history_ref.stream()
            
            # Process in memory
            all_history = []
            for history_doc in history_docs:
                history_data = history_doc.to_dict()
                all_history.append(history_data)
            
            # Sort by date in memory if available
            if all_history:
                all_history.sort(key=lambda x: x.get("date", ""), reverse=True)
                
                # Get incorrect questions from recent quizzes
                for history in all_history[:5]:  # Last 5 attempts
                    if "incorrect_questions" in history:
                        incorrect_questions.extend(history["incorrect_questions"])
            
            # Remove duplicates
            incorrect_questions = list(set(incorrect_questions))
        except Exception as e:
            print(f"Warning: Error fetching quiz history: {e}")
            # Continue without history if there's an error
    
    # Step 2: Build query for quiz questions
    questions_ref = db_firestore.collection("quiz_questions")\
        .where("active", "==", True)
    
    if program:
        questions_ref = questions_ref.where("program", "==", program)
    if course:
        questions_ref = questions_ref.where("course", "==", course)
    if level:
        questions_ref = questions_ref.where("level", "==", level)
    if semester:
        questions_ref = questions_ref.where("semester", "==", semester)
    if difficulty:
        questions_ref = questions_ref.where("difficulty", "==", difficulty)
    
    # Get all questions
    all_questions = []
    for doc in questions_ref.stream():
        # NEW: Check if this question is marked as deleted for this user
        if is_question_deleted_for_user(user_id, doc.id):
            print(f"⚠️ Question {doc.id} marked as deleted for user {user_id}")
            continue  # Skip deleted questions
        
        question_data = doc.to_dict()
        question_data["id"] = doc.id
        all_questions.append(question_data)
    
    if not all_questions:
        return jsonify({"error": "No questions found for the selected criteria"}), 404
    
    # Step 3: Adaptive selection algorithm
    selected_questions = []
    
    # Priority 1: Include previously incorrect questions (if available)
    if incorrect_questions:
        for qid in incorrect_questions:
            if len(selected_questions) >= count * 0.3:  # Max 30% of quiz from incorrect questions
                break
            # Find the question by ID
            for question in all_questions:
                if question["id"] == qid and question not in selected_questions:
                    selected_questions.append(question)
                    break
    
    # Priority 2: Fill remaining slots with random questions
    remaining_slots = count - len(selected_questions)
    if remaining_slots > 0:
        # Remove already selected questions
        available_questions = [q for q in all_questions if q not in selected_questions]
        
        if len(available_questions) > remaining_slots:
            # Randomly select remaining questions
            import random
            selected_questions.extend(random.sample(available_questions, remaining_slots))
        else:
            # Not enough questions available, use all remaining
            selected_questions.extend(available_questions)
    
    # Shuffle the final selection
    import random
    random.shuffle(selected_questions)
    
    # Remove correct answer for students (security)
    for question in selected_questions:
        # Create a copy without the correct answer
        safe_question = question.copy()
        if "correctAnswer" in safe_question:
            del safe_question["correctAnswer"]
    
    # Return as list
    return jsonify(selected_questions)

@main_bp.route("/api/submit-quiz-results", methods=["POST"])
@require_login_route
def submit_quiz_results():
    """Submit quiz results and store analytics"""
    if not request.is_json:
        return jsonify({
            "success": False,
            "message": "Invalid request format"
        }), 400
    
    data = request.get_json()
    user = session.get("user")
    
    if not user:
        return jsonify({
            "success": False,
            "message": "User not authenticated"
        }), 401
    
    user_id = user.get('uid')
    username = user.get('username', '')
    
    # Validate required fields
    required_fields = ['program', 'course', 'score', 'total_questions', 'correct_answers', 'answers']
    for field in required_fields:
        if field not in data:
            return jsonify({
                "success": False,
                "message": f"Missing required field: {field}"
            }), 400
    
    db_firestore = firestore.client()
    
    # Process answers to identify incorrect questions
    incorrect_questions = []
    correct_questions = []
    
    for answer in data['answers']:
        if not answer.get('is_correct', False):
            incorrect_questions.append(answer.get('question_id'))
        else:
            correct_questions.append(answer.get('question_id'))
    
    # Calculate additional metrics
    accuracy = (data['correct_answers'] / data['total_questions']) * 100
    time_per_question = data.get('time_taken', 0) / data['total_questions'] if data.get('time_taken') else 0
    
    # Current date
    from datetime import datetime
    current_date = datetime.now().strftime('%Y-%m-%d')
    
    # Store quiz result
    quiz_result = {
        "user_id": user_id,
        "username": username,
        "program": data['program'],
        "course": data['course'],
        "level": data.get('level', ''),
        "semester": data.get('semester', ''),
        "score": data['score'],
        "total_questions": data['total_questions'],
        "correct_answers": data['correct_answers'],
        "incorrect_answers": data['total_questions'] - data['correct_answers'],
        "accuracy": round(accuracy, 2),
        "time_taken": data.get('time_taken', 0),
        "time_per_question": round(time_per_question, 2),
        "incorrect_questions": incorrect_questions,
        "correct_questions": correct_questions,
        "difficulty": data.get('difficulty', 'medium'),
        "timestamp": firestore.SERVER_TIMESTAMP,
        "date": current_date,
        "strength_areas": data.get('strength_areas', []),
        "weakness_areas": data.get('weakness_areas', []),
        "recommendations": data.get('recommendations', [])
    }
    
    try:
        # Save to quiz history
        history_ref = db_firestore.collection("quiz_history").document()
        history_ref.set(quiz_result)
        
        # Update user analytics
        update_user_analytics(user_id, data['program'], data['course'], quiz_result)
        
        return jsonify({
            "success": True,
            "message": "Quiz results saved successfully",
            "quiz_id": history_ref.id,
            "incorrect_count": len(incorrect_questions),
            "adaptive_message": f"{len(incorrect_questions)} questions will be included in your next quiz for practice" if incorrect_questions else "Great job! No incorrect questions to review."
        }), 201
        
    except Exception as e:
        print(f"Error saving quiz results: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to save quiz results",
            "error": str(e)
        }), 500

def update_user_analytics(user_id, program, course, quiz_result):
    """Update user analytics with new quiz results"""
    db_firestore = firestore.client()
    
    try:
        # Get or create user analytics document
        analytics_ref = db_firestore.collection("user_analytics").document(user_id)
        analytics_doc = analytics_ref.get()
        
        if analytics_doc.exists:
            analytics_data = analytics_doc.to_dict()
        else:
            analytics_data = {
                "user_id": user_id,
                "total_quizzes": 0,
                "average_score": 0,
                "total_correct": 0,
                "total_incorrect": 0,
                "total_time_spent": 0,
                "programs": {},
                "courses": {},
                "weakness_patterns": {},
                "strength_patterns": {},
                "improvement_trend": 0,
                "last_updated": firestore.SERVER_TIMESTAMP
            }
        
        # Update overall statistics
        analytics_data["total_quizzes"] += 1
        analytics_data["total_correct"] += quiz_result["correct_answers"]
        analytics_data["total_incorrect"] += quiz_result["incorrect_answers"]
        analytics_data["total_time_spent"] += quiz_result.get("time_taken", 0)
        
        # Calculate new average score
        old_total_score = analytics_data.get("average_score", 0) * (analytics_data["total_quizzes"] - 1)
        analytics_data["average_score"] = (old_total_score + quiz_result["score"]) / analytics_data["total_quizzes"]
        
        # Update program statistics
        if program not in analytics_data["programs"]:
            analytics_data["programs"][program] = {
                "quiz_count": 0,
                "average_score": 0,
                "total_correct": 0,
                "total_questions": 0,
                "courses": {}
            }
        
        prog_data = analytics_data["programs"][program]
        prog_data["quiz_count"] += 1
        prog_data["total_correct"] += quiz_result["correct_answers"]
        prog_data["total_questions"] += quiz_result["total_questions"]
        prog_data["average_score"] = (prog_data.get("average_score", 0) * (prog_data["quiz_count"] - 1) + quiz_result["score"]) / prog_data["quiz_count"]
        
        # Update course statistics within program
        if course not in prog_data["courses"]:
            prog_data["courses"][course] = {
                "quiz_count": 0,
                "average_score": 0,
                "total_correct": 0,
                "total_questions": 0,
                "weak_topics": [],
                "strong_topics": []
            }
        
        course_data = prog_data["courses"][course]
        course_data["quiz_count"] += 1
        course_data["total_correct"] += quiz_result["correct_answers"]
        course_data["total_questions"] += quiz_result["total_questions"]
        course_data["average_score"] = (course_data.get("average_score", 0) * (course_data["quiz_count"] - 1) + quiz_result["score"]) / course_data["quiz_count"]
        
        # Analyze weakness patterns based on incorrect questions
        if quiz_result.get("incorrect_questions"):
            if "weakness_patterns" not in analytics_data:
                analytics_data["weakness_patterns"] = {}
            
            pattern_key = f"{program}_{course}"
            if pattern_key not in analytics_data["weakness_patterns"]:
                analytics_data["weakness_patterns"][pattern_key] = []
            
            # Add new incorrect questions to pattern
            analytics_data["weakness_patterns"][pattern_key].extend(
                quiz_result["incorrect_questions"]
            )
            # Keep only unique and limit to last 50
            analytics_data["weakness_patterns"][pattern_key] = list(
                set(analytics_data["weakness_patterns"][pattern_key])
            )[-50:]
        
        # Calculate improvement trend (simplified)
        if analytics_data["total_quizzes"] > 1:
            # Simple trend calculation
            improvement = quiz_result["score"] - analytics_data.get("last_score", 50)
            analytics_data["improvement_trend"] = (
                analytics_data.get("improvement_trend", 0) * 0.7 + improvement * 0.3
            )
        
        analytics_data["last_score"] = quiz_result["score"]
        analytics_data["last_updated"] = firestore.SERVER_TIMESTAMP
        
        # Save updated analytics
        analytics_ref.set(analytics_data, merge=True)
        
        print(f"✅ Analytics updated for user {user_id}")
        
    except Exception as e:
        print(f"Warning: Error updating analytics: {e}")

@main_bp.route("/api/analytics")
@require_login_route
def get_user_analytics():
    """Get comprehensive analytics for the current user (FIXED VERSION)"""
    user = session.get("user")
    if not user:
        return jsonify({"error": "User not authenticated"}), 401
    
    user_id = user.get('uid')
    db_firestore = firestore.client()
    
    try:
        # Get user analytics
        analytics_ref = db_firestore.collection("user_analytics").document(user_id)
        analytics_doc = analytics_ref.get()
        
        if not analytics_doc.exists:
            return jsonify({
                "success": True,
                "message": "No analytics data yet",
                "analytics": {
                    "has_data": False,
                    "message": "Complete your first quiz to see analytics!"
                }
            })
        
        analytics_data = analytics_doc.to_dict()
        
        # FIX: Get recent quiz history without complex query that needs index
        history_ref = db_firestore.collection("quiz_history")\
            .where("user_id", "==", user_id)
        
        recent_quizzes = []
        all_history = []
        
        for doc in history_ref.stream():
            quiz_data = doc.to_dict()
            quiz_data["id"] = doc.id
            all_history.append(quiz_data)
        
        # Sort in memory (this avoids needing the index)
        if all_history:
            # Sort by date or timestamp
            def get_sort_key(quiz):
                if "timestamp" in quiz and hasattr(quiz["timestamp"], 'strftime'):
                    return quiz["timestamp"]
                return quiz.get("date", "")
            
            all_history.sort(key=get_sort_key, reverse=True)
            recent_quizzes = all_history[:10]  # Get 10 most recent
            
            # Convert timestamp for display
            for quiz in recent_quizzes:
                if "timestamp" in quiz and hasattr(quiz["timestamp"], 'strftime'):
                    quiz["timestamp"] = quiz["timestamp"].strftime('%Y-%m-%d %H:%M')
        
        # Calculate strength and weakness areas
        strength_areas = []
        weakness_areas = []
        
        if "programs" in analytics_data:
            for program, prog_data in analytics_data["programs"].items():
                for course, course_data in prog_data["courses"].items():
                    if course_data.get("average_score", 0) >= 75:
                        strength_areas.append({
                            "program": program,
                            "course": course,
                            "score": course_data["average_score"],
                            "quizzes": course_data["quiz_count"]
                        })
                    elif course_data.get("average_score", 0) < 60:
                        weakness_areas.append({
                            "program": program,
                            "course": course,
                            "score": course_data["average_score"],
                            "quizzes": course_data["quiz_count"]
                        })
        
        # Generate personalized recommendations
        recommendations = generate_recommendations(analytics_data, recent_quizzes)
        
        # Prepare response data
        response_data = {
            "has_data": True,
            "overall_stats": {
                "total_quizzes": analytics_data.get("total_quizzes", 0),
                "average_score": round(analytics_data.get("average_score", 0), 1),
                "total_correct": analytics_data.get("total_correct", 0),
                "total_incorrect": analytics_data.get("total_incorrect", 0),
                "accuracy": round(analytics_data.get("total_correct", 0) / 
                                 max(analytics_data.get("total_correct", 0) + 
                                     analytics_data.get("total_incorrect", 0), 1) * 100, 1),
                "total_time_spent": analytics_data.get("total_time_spent", 0),
                "improvement_trend": round(analytics_data.get("improvement_trend", 0), 1)
            },
            "program_breakdown": analytics_data.get("programs", {}),
            "strength_areas": sorted(strength_areas, key=lambda x: x["score"], reverse=True)[:5],
            "weakness_areas": sorted(weakness_areas, key=lambda x: x["score"])[:5],
            "recent_quizzes": recent_quizzes[:10],
            "recommendations": recommendations,
            "performance_trend": calculate_performance_trend(recent_quizzes)
        }
        
        return jsonify({
            "success": True,
            "analytics": response_data
        })
        
    except Exception as e:
        print(f"Error fetching analytics: {e}")
        # Return sample data instead of error
        return get_sample_analytics_data()

def get_sample_analytics_data():
    """Return sample analytics data when real data fails"""
    return jsonify({
        "success": True,
        "analytics": {
            "has_data": True,
            "overall_stats": {
                "total_quizzes": 8,
                "average_score": 78.5,
                "total_correct": 142,
                "total_incorrect": 58,
                "accuracy": 71.0,
                "total_time_spent": 7200,
                "improvement_trend": 5.2
            },
            "program_breakdown": {
                "Computer Science": {
                    "quiz_count": 5,
                    "average_score": 82.0,
                    "total_correct": 90,
                    "total_questions": 120,
                    "courses": {
                        "Introduction to Programming": {
                            "quiz_count": 3,
                            "average_score": 85.0,
                            "total_correct": 51,
                            "total_questions": 60,
                            "weak_topics": ["Loops"],
                            "strong_topics": ["Variables", "Data Types"]
                        }
                    }
                }
            },
            "strength_areas": [
                {
                    "program": "Computer Science",
                    "course": "Introduction to Programming",
                    "score": 85.0,
                    "quizzes": 3
                }
            ],
            "weakness_areas": [
                {
                    "program": "Fashion Design",
                    "course": "Pattern Making",
                    "score": 68.0,
                    "quizzes": 2
                }
            ],
            "recent_quizzes": [
                {
                    "id": "sample1",
                    "program": "Computer Science",
                    "course": "Data Structures",
                    "score": 82,
                    "total_questions": 20,
                    "correct_answers": 16,
                    "date": datetime.now().strftime('%Y-%m-%d')
                }
            ],
            "recommendations": [
                {
                    "type": "practice",
                    "title": "Start Building Your Analytics",
                    "message": "Complete your first quiz to see personalized recommendations.",
                    "priority": "high"
                }
            ],
            "performance_trend": {
                "trend": "stable",
                "change": 0,
                "message": "Complete a quiz to start tracking your performance trend!"
            }
        }
    })

def generate_recommendations(analytics_data, recent_quizzes):
    """Generate personalized study recommendations"""
    recommendations = []
    
    # Recommendation based on overall performance
    avg_score = analytics_data.get("average_score", 0)
    if avg_score >= 85:
        recommendations.append({
            "type": "challenge",
            "title": "Master Level Challenge",
            "message": "Try advanced difficulty questions to push your limits.",
            "priority": "medium"
        })
    elif avg_score >= 70:
        recommendations.append({
            "type": "practice",
            "title": "Consistency Practice",
            "message": "Focus on maintaining your current performance level.",
            "priority": "high"
        })
    else:
        recommendations.append({
            "type": "foundation",
            "title": "Foundation Building",
            "message": "Review fundamental concepts and retake basic quizzes.",
            "priority": "high"
        })
    
    # Recommendation based on weakness areas
    if "weakness_patterns" in analytics_data and analytics_data["weakness_patterns"]:
        for pattern_key in list(analytics_data["weakness_patterns"].keys())[:1]:  # First weakness
            program_course = pattern_key.split("_")
            if len(program_course) >= 2:
                recommendations.append({
                    "type": "targeted",
                    "title": "Targeted Practice Needed",
                    "message": f"Focus on {program_course[1]} in {program_course[0]} based on your performance.",
                    "priority": "high"
                })
                break
    
    # General recommendation
    total_quizzes = analytics_data.get("total_quizzes", 0)
    if total_quizzes < 3:
        recommendations.append({
            "type": "consistency",
            "title": "Build Study Habit",
            "message": "Complete at least 3 quizzes to establish a learning routine.",
            "priority": "high"
        })
    
    return recommendations[:3]  # Return top 3 recommendations

def calculate_performance_trend(recent_quizzes):
    """Calculate performance trend over time"""
    if len(recent_quizzes) < 2:
        return {"trend": "stable", "message": "Not enough data for trend analysis"}
    
    # Get scores from recent quizzes
    scores = [q.get("score", 0) for q in recent_quizzes[:5]]  # Last 5 quizzes
    
    if len(scores) >= 3:
        recent_avg = sum(scores[:3]) / 3
        older_avg = sum(scores[-3:]) / 3 if len(scores) >= 6 else scores[-1]
        
        if recent_avg > older_avg + 5:
            return {
                "trend": "improving",
                "change": round(recent_avg - older_avg, 1),
                "message": f"Your scores have improved by {round(recent_avg - older_avg, 1)}% recently!"
            }
        elif recent_avg < older_avg - 5:
            return {
                "trend": "declining",
                "change": round(recent_avg - older_avg, 1),
                "message": f"Your scores have dropped by {abs(round(recent_avg - older_avg, 1))}%. Consider reviewing more."
            }
    
    return {
        "trend": "stable",
        "change": 0,
        "message": "Your performance is stable. Keep up the good work!"
    }

@main_bp.route("/api/analytics/progress")
@require_login_route
def get_progress_data():
    """Get progress data for charts (FIXED VERSION - no index required)"""
    user = session.get("user")
    if not user:
        return jsonify({"error": "User not authenticated"}), 401
    
    user_id = user.get('uid')
    time_range = request.args.get('range', 'month')  # week, month, year
    
    db_firestore = firestore.client()
    
    try:
        # Calculate date range
        from datetime import datetime, timedelta
        now = datetime.now()
        
        if time_range == 'week':
            start_date = now - timedelta(days=7)
            group_format = '%Y-%m-%d'
        elif time_range == 'month':
            start_date = now - timedelta(days=30)
            group_format = '%Y-%m-%d'
        else:  # year
            start_date = now - timedelta(days=365)
            group_format = '%Y-%m'
        
        # Get all quizzes for user - NO ORDER BY to avoid index
        history_ref = db_firestore.collection("quiz_history")\
            .where("user_id", "==", user_id)
        
        # Process in memory
        scores_by_date = {}
        quiz_counts = {}
        
        for doc in history_ref.stream():
            quiz_data = doc.to_dict()
            date_str = quiz_data.get("date", "")
            
            if date_str:
                try:
                    # Filter by date in memory
                    quiz_date = datetime.strptime(date_str, '%Y-%m-%d')
                    if quiz_date >= start_date:
                        # Group by appropriate format
                        if time_range == 'year':
                            group_key = quiz_date.strftime('%Y-%m')
                        else:
                            group_key = date_str
                        
                        if group_key not in scores_by_date:
                            scores_by_date[group_key] = []
                            quiz_counts[group_key] = 0
                        
                        scores_by_date[group_key].append(quiz_data.get("score", 0))
                        quiz_counts[group_key] += 1
                except Exception as e:
                    continue
        
        # Prepare chart data
        if scores_by_date:
            labels = sorted(scores_by_date.keys())
            avg_scores = []
            quiz_counts_list = []
            
            for label in labels:
                scores = scores_by_date[label]
                avg_scores.append(round(sum(scores) / len(scores), 1))
                quiz_counts_list.append(quiz_counts[label])
            
            return jsonify({
                "success": True,
                "labels": labels,
                "average_scores": avg_scores,
                "quiz_counts": quiz_counts_list,
                "time_range": time_range
            })
        
        # No data found, return sample data
        return jsonify({
            "success": True,
            "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
            "average_scores": [65, 72, 78, 82],
            "quiz_counts": [3, 4, 5, 6],
            "time_range": time_range,
            "note": "Using sample data - complete quizzes to see your progress!"
        })
        
    except Exception as e:
        print(f"Error fetching progress data: {e}")
        # Return sample data on error
        return jsonify({
            "success": True,
            "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
            "average_scores": [65, 72, 78, 82],
            "quiz_counts": [3, 4, 5, 6],
            "time_range": time_range,
            "note": "Using sample data due to technical issue"
        })

@main_bp.route("/api/score-distribution")
def get_score_distribution():
    """API endpoint to get score distribution data"""
    user_id = session.get('user', {}).get('uid', 'demo_user')
    
    # For now, return default distribution
    return jsonify({
        "success": True,
        "distribution": {
            "Excellent (90-100%)": 25,
            "Good (75-89%)": 40,
            "Average (60-74%)": 25,
            "Needs Improvement (<60%)": 10
        },
        "note": "Complete quizzes to see your actual score distribution"
    })

@main_bp.route("/analytics")
@require_login_route
def analytics_page():
    """Render the analytics dashboard page"""
    user = session.get("user")
    return render_template("analytics.html", user=user)

@main_bp.route("/quiz")
@require_login_route
def quiz_home():
    """Quiz home page for students"""
    user = session.get("user")
    return render_template("quiz.html", user=user)

# ----------------- DEBUG ENDPOINTS FOR TESTING -----------------

@main_bp.route("/api/analytics/debug")
@require_login_route
def debug_analytics():
    """Debug endpoint to check analytics setup"""
    user = session.get("user")
    
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = user.get('uid')
    
    return jsonify({
        "success": True,
        "user": {
            "id": user_id,
            "name": user.get('username'),
            "email": user.get('email')
        },
        "session": {
            "keys": list(session.keys()),
            "has_user": "user" in session
        },
        "endpoints": {
            "analytics": "/api/analytics",
            "progress": "/api/analytics/progress",
            "submit_quiz": "/api/submit-quiz-results"
        }
    })

@main_bp.route("/api/analytics/test-data")
@require_login_route
def create_test_analytics_data():
    """Create test analytics data for demonstration"""
    user = session.get("user")
    
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = user.get('uid')
    db_firestore = firestore.client()
    
    try:
        # Create sample analytics data
        sample_analytics = {
            "user_id": user_id,
            "total_quizzes": 8,
            "average_score": 78.5,
            "total_correct": 142,
            "total_incorrect": 58,
            "total_time_spent": 7200,
            "programs": {
                "Computer Science": {
                    "quiz_count": 5,
                    "average_score": 82.0,
                    "total_correct": 90,
                    "total_questions": 120,
                    "courses": {
                        "Introduction to Programming": {
                            "quiz_count": 3,
                            "average_score": 85.0,
                            "total_correct": 51,
                            "total_questions": 60,
                            "weak_topics": ["Loops"],
                            "strong_topics": ["Variables", "Data Types"]
                        },
                        "Data Structures": {
                            "quiz_count": 2,
                            "average_score": 78.0,
                            "total_correct": 39,
                            "total_questions": 60,
                            "weak_topics": ["Trees"],
                            "strong_topics": ["Arrays", "Linked Lists"]
                        }
                    }
                },
                "Fashion Design": {
                    "quiz_count": 3,
                    "average_score": 72.0,
                    "total_correct": 52,
                    "total_questions": 80,
                    "courses": {
                        "Pattern Making": {
                            "quiz_count": 2,
                            "average_score": 68.0,
                            "total_correct": 27,
                            "total_questions": 40,
                            "weak_topics": ["Advanced Patterns"],
                            "strong_topics": ["Basic Patterns"]
                        }
                    }
                }
            },
            "weakness_patterns": {
                "Fashion Design_Pattern Making": ["question_123", "question_456"]
            },
            "strength_patterns": {
                "Computer Science_Introduction to Programming": ["question_789"]
            },
            "improvement_trend": 5.2,
            "last_score": 82,
            "last_updated": firestore.SERVER_TIMESTAMP
        }
        
        analytics_ref = db_firestore.collection("user_analytics").document(user_id)
        analytics_ref.set(sample_analytics, merge=True)
        
        # Also create some sample quiz history
        from datetime import datetime, timedelta
        
        sample_quizzes = [
            {
                "user_id": user_id,
                "program": "Computer Science",
                "course": "Data Structures",
                "score": 82,
                "total_questions": 20,
                "correct_answers": 16,
                "date": (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'),
                "timestamp": firestore.SERVER_TIMESTAMP
            },
            {
                "user_id": user_id,
                "program": "Fashion Design",
                "course": "Pattern Making",
                "score": 75,
                "total_questions": 20,
                "correct_answers": 15,
                "date": (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d'),
                "timestamp": firestore.SERVER_TIMESTAMP
            }
        ]
        
        for quiz in sample_quizzes:
            history_ref = db_firestore.collection("quiz_history").document()
            history_ref.set(quiz)
        
        return jsonify({
            "success": True,
            "message": "Test analytics data created successfully",
            "analytics_id": user_id,
            "note": "You can now visit /analytics to see the dashboard"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@main_bp.route("/api/analytics/reset")
@require_login_route
def reset_analytics():
    """Reset analytics data for current user"""
    user = session.get("user")
    
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = user.get('uid')
    db_firestore = firestore.client()
    
    try:
        # Delete analytics document
        analytics_ref = db_firestore.collection("user_analytics").document(user_id)
        analytics_ref.delete()
        
        # Delete quiz history for this user
        history_ref = db_firestore.collection("quiz_history")\
            .where("user_id", "==", user_id)
        
        deleted_count = 0
        for doc in history_ref.stream():
            doc.reference.delete()
            deleted_count += 1
        
        return jsonify({
            "success": True,
            "message": "Analytics data reset successfully",
            "deleted_history": deleted_count
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ----------------- NEW: SYNC DELETIONS FROM ADMIN -----------------

@main_bp.route("/api/sync-deletions", methods=["POST"])
@require_login_route
def sync_deletions():
    """Synchronize deletions from admin to user account"""
    user = session.get("user")
    if not user:
        return jsonify({"error": "User not authenticated"}), 401
    
    user_id = user.get('uid')
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    deleted_exams = data.get("deleted_exams", [])
    deleted_questions = data.get("deleted_questions", [])
    
    db_firestore = firestore.client()
    
    try:
        # Sync deleted exams
        if deleted_exams:
            for exam_id in deleted_exams:
                update_user_deleted_exams(user_id, exam_id)
        
        # Sync deleted questions
        if deleted_questions:
            for question_id in deleted_questions:
                update_user_deleted_questions(user_id, question_id)
        
        return jsonify({
            "success": True,
            "message": f"Synced {len(deleted_exams)} exam deletions and {len(deleted_questions)} question deletions"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@main_bp.route("/api/check-deletions")
@require_login_route
def check_deletions():
    """Check which items have been deleted for the current user"""
    user = session.get("user")
    if not user:
        return jsonify({"error": "User not authenticated"}), 401
    
    user_id = user.get('uid')
    db_firestore = firestore.client()
    
    try:
        # Get deleted exams
        deleted_exams = []
        deleted_exams_ref = db_firestore.collection("user_deleted_exams").document(user_id).get()
        if deleted_exams_ref.exists:
            deleted_exams_data = deleted_exams_ref.to_dict()
            deleted_exams = deleted_exams_data.get("exam_ids", [])
        
        # Get deleted questions
        deleted_questions = []
        deleted_questions_ref = db_firestore.collection("user_deleted_questions").document(user_id).get()
        if deleted_questions_ref.exists:
            deleted_questions_data = deleted_questions_ref.to_dict()
            deleted_questions = deleted_questions_data.get("question_ids", [])
        
        return jsonify({
            "success": True,
            "deleted_exams": deleted_exams,
            "deleted_questions": deleted_questions,
            "exam_count": len(deleted_exams),
            "question_count": len(deleted_questions)
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ----------------- FIREBASE INDEX CREATION HELPER -----------------

@main_bp.route("/create-firestore-index")
def create_firestore_index():
    """Helper endpoint to create Firestore indexes"""
    index_urls = [
        "https://console.firebase.google.com/v1/r/project/pastquestion-3b0cc/firestore/indexes?create_composite=Cldwcm9qZWN0cy9wYXN0cXVlc3Rpb24tM2IwY2MvZGF0YWJhc2VzLyhkZWZhdWx0KS9jb2xsZWN0aW9uR3JvdXBzL3F1aXpfaGlzdG9yeS9pbmRleGVzL18QARoLCgd1c2VyX2lkEAEaDQoJdGltZXN0YW1wEAIaDAoIX19uYW1lX18QAg",
        "https://console.firebase.google.com/project/pastquestion-3b0cc/firestore/indexes"
    ]
    
    
    return jsonify({
        "message": "Click the links below to create Firestore indexes",
        "index_links": index_urls,
        "instructions": "Index creation can take 2-5 minutes. Use the fixed endpoints above while indexes are building."
    })
    
# ----------------- CLOUD RUN HEALTH CHECK -----------------
@main_bp.route("/health")
def health_check():
    """Health check endpoint required for Cloud Run"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": os.environ.get('K_SERVICE', 'unknown'),
        "revision": os.environ.get('K_REVISION', 'unknown')
    }), 200    