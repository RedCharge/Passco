from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, session, request, jsonify, make_response
)
from werkzeug.utils import secure_filename
from firebase_admin import auth as firebase_auth, firestore
from functools import wraps
import os
from datetime import datetime, timedelta
import random
import string
import PyPDF2
import requests
import json
import traceback
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# ----------------- SETTINGS -----------------
ALLOWED_EXTENSIONS = {"pdf"}
UPLOAD_ROOT = os.path.join("static", "pdfs")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------- AUTH -----------------
def require_login(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        user = session.get("user")
        if not user:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))

        uid = user.get("uid")
        if not uid:
            flash("Invalid session. Please log in again.", "error")
            session.pop("user", None)
            return redirect(url_for("auth.login"))

        try:
            db = firestore.client()
            user_doc = db.collection("users").document(uid).get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
                role = user_data.get("role", "user")
                
                if user.get("role") != role:
                    user["role"] = role
                    user["username"] = user_data.get("username", "")
                    user["email"] = user_data.get("email", "")
                    session["user"] = user

                if role != "admin":
                    flash("Access denied: Admins only.", "danger")
                    return redirect(url_for("main.dashboard"))
            else:
                flash("User data not found.", "error")
                return redirect(url_for("auth.login"))

        except Exception as e:
            flash(f"Error checking admin rights: {e}", "error")
            session.pop("user", None)
            return redirect(url_for("auth.login"))

        return func(*args, **kwargs)
    return wrapper

def get_admin_stats():
    """Helper function to get admin statistics"""
    try:
        db = firestore.client()
        user = session.get("user")
        if not user:
            return None
            
        admin_name = user.get("username") or user.get("email", "Admin").split('@')[0]
        users_ref = db.collection("users").stream()
        all_users = list(users_ref)
        total_users = len(all_users)
        
        paid_users = 0
        for user_doc in all_users:
            user_data = user_doc.to_dict()
            if user_data.get("paid") == True:
                paid_users += 1
        
        total_resources = 0
        try:
            uploads_ref = db.collection("admin_uploads").stream()
            total_resources = len(list(uploads_ref)) * 2
        except Exception as e:
            print(f"Error counting resources from Firestore: {e}")
            if os.path.exists(UPLOAD_ROOT):
                for root, dirs, files in os.walk(UPLOAD_ROOT):
                    total_resources += len([f for f in files if f.endswith('.pdf')])

        today = datetime.now().date()
        new_signups_today = 0
        for user_doc in all_users:
            user_data = user_doc.to_dict()
            if 'created_at' in user_data:
                created_date = user_data['created_at'].date()
                if created_date == today:
                    new_signups_today += 1
            else:
                new_signups_today = total_users

        return {
            "active_members": paid_users,
            "total_resources": total_resources,
            "new_signups": new_signups_today,
            "total_users": total_users,
            "admin_name": admin_name
        }
        
    except Exception as e:
        print(f"Error getting admin stats: {e}")
        return {
            "active_members": 0,
            "total_resources": 0,
            "new_signups": 0,
            "total_users": 0,
            "admin_name": "Admin"
        }

# ----------------- ADMIN DASHBOARD -----------------
@admin_bp.route("/")
@require_login
@admin_required
def home():
    return redirect(url_for("admin.dashboard"))

@admin_bp.route("/dashboard")
@require_login
@admin_required
def dashboard():
    """Show admin dashboard with Firebase data and uploaded PDFs"""
    user = session.get("user")
    db = firestore.client()

    try:
        stats = get_admin_stats()
        
        if not user.get("username"):
            user_doc = db.collection("users").document(user.get("uid")).get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
                user["username"] = user_data.get("username", "")
                user["email"] = user_data.get("email", "")
                session["user"] = user

        members = []
        try:
            all_users = db.collection("users").stream()
            members = [doc.to_dict() for doc in all_users if doc.to_dict().get("paid") == True]
        except Exception as e:
            print(f"Error fetching members: {e}")
            members = []

        uploads = []
        try:
            if os.path.exists(UPLOAD_ROOT):
                for root, _, files in os.walk(UPLOAD_ROOT):
                    for file in files:
                        if file.endswith(".pdf"):
                            abs_path = os.path.join(root, file)
                            rel_path = os.path.relpath(abs_path, "static")
                            parts = rel_path.split(os.sep)

                            uploads.append({
                                "program": parts[1] if len(parts) > 1 else "Unknown",
                                "course": parts[2] if len(parts) > 2 else "Unknown",
                                "year": parts[3] if len(parts) > 3 else "Unknown",
                                "filename": file,
                                "path": f"/static/{rel_path.replace(os.sep, '/')}",
                                "uploaded_at": datetime.fromtimestamp(os.path.getmtime(abs_path)).strftime("%Y-%m-%d %H:%M")
                            })
        except Exception as e:
            print(f"Error scanning uploads: {e}")

        return render_template("dashboard_admin.html", 
                             user=user, 
                             members=members, 
                             uploads=uploads,
                             stats=stats)

    except Exception as e:
        flash(f"Error loading dashboard: {e}", "error")
        return render_template("dashboard_admin.html", 
                             user=user, 
                             members=[], 
                             uploads=[],
                             stats=get_admin_stats())

# ----------------- API ENDPOINT FOR STATISTICS -----------------
@admin_bp.route("/api/stats")
@require_login
@admin_required
def get_stats():
    """API endpoint to get real-time statistics"""
    try:
        stats = get_admin_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- GET UPLOADED EXAMS API -----------------
@admin_bp.route("/api/uploaded-exams")
@require_login
@admin_required
def get_uploaded_exams():
    """API endpoint to get all uploaded exams"""
    try:
        db = firestore.client()
        exams_ref = db.collection("admin_uploads").stream()
        exams = []
        
        for doc in exams_ref:
            exam_data = doc.to_dict()
            exams.append({
                "id": doc.id,
                "program": exam_data.get("program", ""),
                "course": exam_data.get("course", ""),
                "year": exam_data.get("year", ""),
                "level": exam_data.get("level", ""),
                "semester": exam_data.get("semester", ""),
                "exam_type": exam_data.get("exam_type", "final"),
                "fileName": exam_data.get("fileName", ""),
                "questionsFileName": exam_data.get("questionsFileName", ""),
                "answersFileName": exam_data.get("answersFileName", ""),
                "questionsFilePath": exam_data.get("questionsFilePath", ""),
                "answersFilePath": exam_data.get("answersFilePath", ""),
                "uploadDate": exam_data.get("uploadDate", ""),
                "uploadedByName": exam_data.get("uploadedByName", ""),
                "examName": exam_data.get("examName", f"{exam_data.get('course', '')} - {exam_data.get('year', '')}")
            })
        
        return jsonify(exams)
        
    except Exception as e:
        print(f"Error fetching uploaded exams: {e}")
        return jsonify({"error": str(e)}), 500

# ----------------- UPLOAD PDF -----------------
@admin_bp.route("/upload", methods=["POST"])
@require_login
@admin_required
def upload_exam():
    program = request.form.get("program")
    course = request.form.get("course")
    year = request.form.get("year")
    level = request.form.get("level")
    semester = request.form.get("semester")
    exam_type = request.form.get("exam_type", "final")
    questions_file = request.files.get("questionsPdf")
    answers_file = request.files.get("answersPdf")

    if not program or not course or not year or not level or not semester:
        flash("Program, course, year, level, and semester are required.", "error")
        return redirect(url_for("admin.dashboard"))

    if not questions_file or not allowed_file(questions_file.filename):
        flash("Upload a valid Questions PDF file.", "error")
        return redirect(url_for("admin.dashboard"))

    if not answers_file or not allowed_file(answers_file.filename):
        flash("Upload a valid Answers PDF file.", "error")
        return redirect(url_for("admin.dashboard"))

    try:
        base_dir = os.path.join(UPLOAD_ROOT, program, f"Level_{level}", f"Semester_{semester}", course, year)
        os.makedirs(base_dir, exist_ok=True)
        
        questions_filename = secure_filename(questions_file.filename)
        questions_path = os.path.join(base_dir, f"questions_{questions_filename}")
        questions_file.save(questions_path)
        
        answers_filename = secure_filename(answers_file.filename)
        answers_path = os.path.join(base_dir, f"answers_{answers_filename}")
        answers_file.save(answers_path)

        db = firestore.client()
        user = session.get("user")
        
        import uuid
        doc_id = f"{program[:3]}-{level}-{semester}-{course[:3]}-{str(uuid.uuid4())[:8]}"
        
        exam_data = {
            "program": program,
            "course": course,
            "year": year,
            "level": level,
            "semester": semester,
            "exam_type": exam_type,
            "examName": f"{course} - {year}",
            "questionsFileName": questions_filename,
            "answersFileName": answers_filename,
            "questionsFilePath": questions_path,
            "answersFilePath": answers_path,
            "uploadDate": datetime.now().isoformat(),
            "uploadedBy": user.get("uid"),
            "uploadedByName": user.get("username") or user.get("email", "Admin")
        }
        
        db.collection("admin_uploads").document(doc_id).set(exam_data)

        flash("Exam papers uploaded successfully! Both questions and answers saved.", "success")
        return redirect(url_for("admin.dashboard"))

    except Exception as e:
        flash(f"Error uploading files: {e}", "error")
        return redirect(url_for("admin.dashboard"))

# ----------------- USERS LIST -----------------
@admin_bp.route("/users")
@require_login
@admin_required
def users():
    try:
        db = firestore.client()
        users_ref = db.collection("users").stream()
        users_list = []
        
        for doc in users_ref:
            user_data = doc.to_dict()
            users_list.append({
                "email": user_data.get("email", ""),
                "uid": doc.id,
                "username": user_data.get("username", ""),
                "role": user_data.get("role", "user"),
                "paid": user_data.get("paid", False)
            })
    except Exception as e:
        flash(f"Error fetching users: {e}", "error")
        users_list = []

    return render_template("admin/users.html", users=users_list, user=session.get("user"))

# ----------------- USER MANAGEMENT API -----------------
@admin_bp.route("/api/users/<user_id>/role", methods=["PUT"])
@require_login
@admin_required
def update_user_role(user_id):
    """Update user role"""
    try:
        db = firestore.client()
        data = request.get_json()
        new_role = data.get('role')
        
        if new_role not in ['admin', 'user']:
            return jsonify({"error": "Invalid role"}), 400
        
        user_ref = db.collection("users").document(user_id)
        user_ref.update({"role": new_role})
        
        return jsonify({"success": True, "message": f"User role updated to {new_role}"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/users/<user_id>/payment", methods=["PUT"])
@require_login
@admin_required
def update_user_payment(user_id):
    """Update user payment status"""
    try:
        db = firestore.client()
        data = request.get_json()
        paid_status = data.get('paid')
        
        user_ref = db.collection("users").document(user_id)
        user_ref.update({"paid": paid_status})
        
        return jsonify({"success": True, "message": f"Payment status updated to {paid_status}"})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ----------------- DELETE UPLOADED EXAM -----------------
@admin_bp.route("/delete_exam/<exam_id>", methods=["DELETE"])
@require_login
@admin_required
def delete_exam(exam_id):
    """Delete an uploaded exam and its associated PDF files"""
    try:
        db = firestore.client()
        exam_doc = db.collection("admin_uploads").document(exam_id).get()
        
        if not exam_doc.exists:
            return jsonify({"error": "Exam not found"}), 404
            
        exam_data = exam_doc.to_dict()
        questions_path = exam_data.get("questionsFilePath")
        answers_path = exam_data.get("answersFilePath")
        
        deleted_files = []
        
        if questions_path and os.path.exists(questions_path):
            os.remove(questions_path)
            deleted_files.append("questions PDF")
        
        if answers_path and os.path.exists(answers_path):
            os.remove(answers_path)
            deleted_files.append("answers PDF")
        
        db.collection("admin_uploads").document(exam_id).delete()
        
        message = f"Exam deleted successfully"
        if deleted_files:
            message += f" ({', '.join(deleted_files)} removed)"
        
        return jsonify({"success": True, "message": message})
        
    except Exception as e:
        print(f"Error deleting exam: {e}")
        return jsonify({"error": str(e)}), 500

# ----------------- QUIZ QUESTION MANAGEMENT API -----------------
@admin_bp.route("/api/admin/questions", methods=["GET", "POST", "PUT", "DELETE"])
@require_login
@admin_required
def manage_questions():
    """Manage quiz questions - CRUD operations (Admin only)"""
    try:
        user = session.get("user")
        
        if not user or user.get("role") != "admin":
            return jsonify({"error": "Unauthorized - Admin access required", "success": False}), 403
        
        db_firestore = firestore.client()
        
        if request.method == "GET":
            program = request.args.get('program')
            course = request.args.get('course')
            semester = request.args.get('semester')
            level = request.args.get('level')
            difficulty = request.args.get('difficulty')
            
            questions_ref = db_firestore.collection("quiz_questions")
            
            if program:
                questions_ref = questions_ref.where("program", "==", program)
            if course:
                questions_ref = questions_ref.where("course", "==", course)
            if semester:
                questions_ref = questions_ref.where("semester", "==", semester)
            if level:
                questions_ref = questions_ref.where("level", "==", level)
            if difficulty:
                questions_ref = questions_ref.where("difficulty", "==", difficulty)
            
            questions = []
            for doc in questions_ref.stream():
                question_data = doc.to_dict()
                question_data["id"] = doc.id
                
                if "createdAt" in question_data:
                    if hasattr(question_data["createdAt"], 'timestamp'):
                        question_data["createdAt"] = question_data["createdAt"].isoformat()
                    elif hasattr(question_data["createdAt"], 'isoformat'):
                        question_data["createdAt"] = question_data["createdAt"].isoformat()
                
                if "updatedAt" in question_data:
                    if hasattr(question_data["updatedAt"], 'timestamp'):
                        question_data["updatedAt"] = question_data["updatedAt"].isoformat()
                    elif hasattr(question_data["updatedAt"], 'isoformat'):
                        question_data["updatedAt"] = question_data["updatedAt"].isoformat()
                
                questions.append(question_data)
            
            return jsonify({
                "success": True,
                "questions": questions,
                "count": len(questions)
            })
            
        elif request.method == "POST":
            if not request.is_json:
                return jsonify({"error": "Request must be JSON with Content-Type: application/json", "success": False}), 400
            
            try:
                data = request.get_json()
            except Exception as e:
                return jsonify({"error": "Invalid JSON format", "success": False}), 400
            
            required_fields = ["program", "course", "level", "semester", "question"]
            missing_fields = []
            for field in required_fields:
                if not data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                return jsonify({
                    "error": f"Missing required fields: {', '.join(missing_fields)}",
                    "success": False
                }), 400
            
            options = data.get("options")
            if options:
                if not isinstance(options, list) or len(options) != 4:
                    return jsonify({
                        "error": "Options must be an array with exactly 4 items",
                        "success": False
                    }), 400
            else:
                option_fields = ["optionA", "optionB", "optionC", "optionD"]
                missing_options = []
                options = []
                
                for field in option_fields:
                    value = data.get(field)
                    if not value:
                        missing_options.append(field)
                    else:
                        options.append(value)
                
                if missing_options:
                    return jsonify({
                        "error": f"Missing option fields: {', '.join(missing_options)}",
                        "success": False
                    }), 400
            
            correct_answer = data.get("correctAnswer")
            if correct_answer is None:
                return jsonify({"error": "Missing required field: correctAnswer", "success": False}), 400
            
            try:
                correct_answer = int(correct_answer)
            except (ValueError, TypeError):
                return jsonify({"error": "correctAnswer must be a number (0-3)", "success": False}), 400
            
            if correct_answer < 0 or correct_answer > 3:
                return jsonify({"error": "correctAnswer must be between 0 and 3", "success": False}), 400
            
            question_data = {
                "program": data.get("program"),
                "course": data.get("course"),
                "level": data.get("level"),
                "semester": data.get("semester"),
                "question": data.get("question"),
                "options": options,
                "correctAnswer": correct_answer,
                "explanation": data.get("explanation", ""),
                "difficulty": data.get("difficulty", "medium"),
                "createdBy": user.get("username") or user.get("email", "Admin"),
                "createdAt": datetime.now(),
                "updatedAt": datetime.now(),
                "active": True
            }
            
            try:
                doc_ref = db_firestore.collection("quiz_questions").add(question_data)
                question_id = doc_ref[1].id
                
                response_data = question_data.copy()
                response_data["id"] = question_id
                response_data["createdAt"] = question_data["createdAt"].isoformat()
                response_data["updatedAt"] = question_data["updatedAt"].isoformat()
                
                return jsonify({
                    "success": True, 
                    "id": question_id,
                    "message": "Question added successfully",
                    "question": response_data
                })
                
            except Exception as e:
                return jsonify({"error": f"Database error: {str(e)}", "success": False}), 500
            
        elif request.method == "PUT":
            if not request.is_json:
                return jsonify({"error": "Request must be JSON", "success": False}), 400
            
            data = request.get_json()
            question_id = data.get("id")
            
            if not question_id:
                return jsonify({"error": "Question ID required", "success": False}), 400
            
            update_data = {}
            allowed_fields = ["question", "options", "correctAnswer", "explanation", "difficulty", "active"]
            
            for field in allowed_fields:
                if field in data:
                    if field == "correctAnswer":
                        try:
                            update_data[field] = int(data[field])
                        except (ValueError, TypeError):
                            return jsonify({"error": f"Invalid {field} format", "success": False}), 400
                    else:
                        update_data[field] = data[field]
            
            if not update_data:
                return jsonify({"error": "No fields to update", "success": False}), 400
            
            update_data["updatedAt"] = datetime.now()
            update_data["updatedBy"] = user.get("username") or user.get("email", "Admin")
            
            try:
                db_firestore.collection("quiz_questions").document(question_id).update(update_data)
                return jsonify({
                    "success": True,
                    "message": "Question updated successfully",
                    "id": question_id
                })
                
            except Exception as e:
                return jsonify({"error": f"Update failed: {str(e)}", "success": False}), 500
        
        elif request.method == "DELETE":
            question_id = request.args.get('id')
            if not question_id:
                return jsonify({"error": "Question ID required", "success": False}), 400
            
            try:
                db_firestore.collection("quiz_questions").document(question_id).delete()
                return jsonify({
                    "success": True,
                    "message": "Question deleted successfully"
                })
                
            except Exception as e:
                return jsonify({"error": f"Delete failed: {str(e)}", "success": False}), 500
    
    except Exception as e:
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "success": False
        }), 500

# ----------------- DEEPSEEK AI FUNCTIONS -----------------
def extract_text_from_pdf(pdf_file):
    """Extract text from uploaded PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            text += page.extract_text()
        return text
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return None

def generate_quiz_questions_with_deepseek(text, num_questions=10, difficulty="medium"):
    """Generate quiz questions from text using DeepSeek AI"""
    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DeepSeek API key not found in environment variables")
        
        prompt = f"""
        Based on the following text content, generate {num_questions} multiple-choice quiz questions.
        Difficulty level: {difficulty}
        
        Text content:
        {text[:3000]}
        
        Generate questions in this exact JSON format:
        {{
            "questions": [
                {{
                    "question": "The question text here?",
                    "options": ["Option A", "Option B", "Option C", "Option D"],
                    "correctAnswer": 0,
                    "explanation": "Brief explanation of the correct answer",
                    "difficulty": "{difficulty}"
                }}
            ]
        }}
        
        Rules:
        1. Each question must be based on the provided text
        2. Options must be plausible but only one correct
        3. correctAnswer must be 0, 1, 2, or 3 (corresponding to options A-D)
        4. Return ONLY the JSON, no other text
        """
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a quiz question generator. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 4000
        }
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            
            try:
                start_idx = content.find('{')
                end_idx = content.rfind('}') + 1
                json_str = content[start_idx:end_idx]
                
                questions_data = json.loads(json_str)
                return questions_data.get("questions", [])
                
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON from AI response: {e}")
                print(f"Raw response: {content}")
                return []
                
        else:
            print(f"DeepSeek API error: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        print(f"Error generating questions: {e}")
        return []

# ----------------- AI QUESTION GENERATION ROUTES -----------------
@admin_bp.route("/ai-generate-questions")
@require_login
@admin_required
def ai_generate_questions_page():
    """Page for AI-generated questions from PDFs"""
    user = session.get("user")
    stats = get_admin_stats()
    
    return render_template(
        "ai_generate_questions.html",
        user=user,
        stats=stats
    )

@admin_bp.route("/api/generate-questions", methods=["POST"])
@require_login
@admin_required
def generate_questions_from_pdf():
    """Generate quiz questions from uploaded PDF using AI"""
    try:
        user = session.get("user")
        
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return jsonify({
                "success": False,
                "error": "DeepSeek API key not configured. Please add DEEPSEEK_API_KEY to .env file"
            }), 500
        
        pdf_file = request.files.get("pdf_file")
        program = request.form.get("program", "General")
        course = request.form.get("course", "General Studies")
        level = request.form.get("level", "100")
        semester = request.form.get("semester", "First")
        difficulty = request.form.get("difficulty", "medium")
        num_questions = int(request.form.get("num_questions", 10))
        
        if not pdf_file or pdf_file.filename == '':
            return jsonify({"success": False, "error": "No PDF file uploaded"}), 400
        
        if not pdf_file.filename.lower().endswith('.pdf'):
            return jsonify({"success": False, "error": "File must be a PDF"}), 400
        
        print(f"Generating {num_questions} questions from PDF: {pdf_file.filename}")
        
        text = extract_text_from_pdf(pdf_file)
        if not text:
            return jsonify({
                "success": False,
                "error": "Could not extract text from PDF. Please ensure it's a valid PDF with readable text."
            }), 400
        
        print(f"Extracted {len(text)} characters from PDF")
        
        questions = generate_quiz_questions_with_deepseek(
            text, 
            num_questions=num_questions,
            difficulty=difficulty
        )
        
        if not questions:
            return jsonify({
                "success": False,
                "error": "Failed to generate questions. The PDF content might be too short or the AI service is unavailable."
            }), 500
        
        print(f"Generated {len(questions)} questions")
        
        db = firestore.client()
        saved_questions = []
        failed_questions = []
        
        for i, q in enumerate(questions):
            try:
                question_data = {
                    "program": program,
                    "course": course,
                    "level": level,
                    "semester": semester,
                    "question": q.get("question", ""),
                    "options": q.get("options", ["", "", "", ""]),
                    "correctAnswer": q.get("correctAnswer", 0),
                    "explanation": q.get("explanation", ""),
                    "difficulty": q.get("difficulty", difficulty),
                    "createdBy": user.get("username") or user.get("email", "Admin"),
                    "createdAt": datetime.now(),
                    "updatedAt": datetime.now(),
                    "active": True,
                    "source": "ai_generated",
                    "sourceFile": pdf_file.filename
                }
                
                if (question_data["question"] and 
                    len(question_data["options"]) == 4 and 
                    all(question_data["options"]) and
                    0 <= question_data["correctAnswer"] <= 3):
                    
                    doc_ref = db.collection("quiz_questions").add(question_data)
                    question_data["id"] = doc_ref[1].id
                    saved_questions.append(question_data)
                    
                else:
                    failed_questions.append(f"Question {i+1}: Invalid format")
                    
            except Exception as e:
                failed_questions.append(f"Question {i+1}: {str(e)}")
        
        return jsonify({
            "success": True,
            "message": f"Generated {len(saved_questions)} questions successfully",
            "saved_count": len(saved_questions),
            "failed_count": len(failed_questions),
            "failed": failed_questions[:5],
            "questions": saved_questions[:10]
        })
        
    except Exception as e:
        print(f"Error in generate_questions_from_pdf: {e}")
        return jsonify({
            "success": False,
            "error": f"Internal error: {str(e)}"
        }), 500

# ----------------- MANUAL QUESTION UPLOAD PAGE -----------------
@admin_bp.route("/upload-questions")
@require_login
@admin_required
def upload_questions_page():
    """Admin page for manually uploading quiz questions"""
    user = session.get("user")
    stats = get_admin_stats()
    
    db = firestore.client()
    
    try:
        programs = set()
        exams_ref = db.collection("admin_uploads").select(["program"]).stream()
        for doc in exams_ref:
            data = doc.to_dict()
            if data.get("program"):
                programs.add(data.get("program"))
        
        if not programs:
            questions_ref = db.collection("quiz_questions").select(["program"]).stream()
            for doc in questions_ref:
                data = doc.to_dict()
                if data.get("program"):
                    programs.add(data.get("program"))
        
        courses = set()
        courses_ref = db.collection("admin_uploads").select(["course"]).stream()
        for doc in courses_ref:
            data = doc.to_dict()
            if data.get("course"):
                courses.add(data.get("course"))
        
        if not courses:
            questions_ref = db.collection("quiz_questions").select(["course"]).stream()
            for doc in questions_ref:
                data = doc.to_dict()
                if data.get("course"):
                    courses.add(data.get("course"))
        
        if not programs:
            programs = {"Computer Science", "Information Technology", "Software Engineering", "Cybersecurity"}
        
        if not courses:
            courses = {"Introduction to Programming", "Data Structures", "Database Systems", 
                      "Web Development", "Networks", "Operating Systems"}
        
        levels = ["100", "200", "300", "400", "500"]
        semesters = ["First", "Second"]
        difficulties = ["Easy", "Medium", "Hard"]
        
        return render_template(
            "upload.html",
            user=user,
            stats=stats,
            programs=sorted(list(programs)),
            courses=sorted(list(courses)),
            levels=levels,
            semesters=semesters,
            difficulties=difficulties
        )
        
    except Exception as e:
        print(f"Error loading upload questions page: {e}")
        flash(f"Error loading page: {e}", "error")
        
        return render_template(
            "upload.html",
            user=user,
            stats=stats,
            programs=["Computer Science", "Information Technology"],
            courses=["Introduction to Programming", "Data Structures"],
            levels=["100", "200", "300"],
            semesters=["First", "Second"],
            difficulties=["Easy", "Medium", "Hard"]
        )

# ----------------- VERIFICATION CODE MANAGEMENT -----------------
def generate_verification_code(prefix="PQ"):
    """Helper function to generate a verification code"""
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    random_part = ''.join(random.choices(chars, k=8))
    return f"{prefix}-{random_part[:4]}-{random_part[4:]}"

@admin_bp.route("/verification-codes")
@require_login
@admin_required
def verification_codes():
    """Admin page for managing verification codes"""
    user = session.get("user")
    stats = get_admin_stats()
    
    return render_template("admin/verification_codes.html", 
                         user=user, 
                         stats=stats)

@admin_bp.route("/api/verification-codes", methods=["GET"])
@require_login
@admin_required
def get_verification_codes():
    """API endpoint to get all verification codes with filtering"""
    try:
        db = firestore.client()
        
        status = request.args.get("status", "all")
        search = request.args.get("search", "")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 10))
        
        query_ref = db.collection("verificationCodes")
        
        if status == "used":
            query_ref = query_ref.where("used", "==", True)
        elif status == "unused":
            query_ref = query_ref.where("used", "==", False)
        
        query_ref = query_ref.order_by("createdAt", direction=firestore.Query.DESCENDING)
        
        codes = []
        now = datetime.now()
        
        for doc in query_ref.stream():
            code_data = doc.to_dict()
            code_id = doc.id
            
            created_at = code_data.get("createdAt")
            expires_at = code_data.get("expiresAt")
            used_at = code_data.get("usedAt")
            
            if hasattr(created_at, 'timestamp'):
                created_at = created_at.replace(tzinfo=None)
            
            if hasattr(expires_at, 'timestamp'):
                expires_at = expires_at.replace(tzinfo=None)
            
            if hasattr(used_at, 'timestamp'):
                used_at = used_at.replace(tzinfo=None)
            
            is_expired = expires_at and expires_at < now
            status_val = "used" if code_data.get("used", False) else "expired" if is_expired else "unused"
            
            code_str = code_data.get("code", "").lower()
            used_by = (code_data.get("usedByEmail") or "").lower()
            
            if search and search.lower() not in code_str and search.lower() not in used_by:
                continue
                
            if status == "expired" and not is_expired:
                continue
                
            codes.append({
                "id": code_id,
                "code": code_data.get("code", code_id),
                "value": code_data.get("value", 50),
                "status": status_val,
                "used": code_data.get("used", False),
                "usedBy": code_data.get("usedBy"),
                "usedByEmail": code_data.get("usedByEmail"),
                "usedAt": used_at.isoformat() if used_at else None,
                "createdAt": created_at.isoformat() if created_at else None,
                "expiresAt": expires_at.isoformat() if expires_at else None,
                "expired": is_expired,
                "createdBy": code_data.get("createdBy", "admin"),
                "prefix": code_data.get("prefix", "PQ")
            })
        
        total = len(codes)
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_codes = codes[start_idx:end_idx]
        
        return jsonify({
            "codes": paginated_codes,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if per_page > 0 else 1
        })
        
    except Exception as e:
        print(f"Error fetching verification codes: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/verification-codes/generate", methods=["POST"])
@require_login
@admin_required
def generate_verification_codes():
    """Generate new verification codes"""
    try:
        data = request.get_json()
        count = int(data.get("count", 10))
        value = int(data.get("value", 50))
        expiry_days = int(data.get("expiry_days", 30))
        prefix = data.get("prefix", "PQ")
        
        if count > 100:
            return jsonify({"error": "Cannot generate more than 100 codes at once"}), 400
            
        if count <= 0:
            return jsonify({"error": "Count must be positive"}), 400
            
        if not prefix or len(prefix) > 6:
            return jsonify({"error": "Prefix must be 1-6 characters"}), 400
            
        db = firestore.client()
        user = session.get("user")
        generated_codes = []
        
        for i in range(count):
            code = generate_verification_code(prefix)
            code_ref = db.collection("verificationCodes").document(code)
            if code_ref.get().exists:
                attempts = 0
                while code_ref.get().exists and attempts < 5:
                    code = generate_verification_code(prefix)
                    code_ref = db.collection("verificationCodes").document(code)
                    attempts += 1
                
                if code_ref.get().exists:
                    continue
            
            expires_at = datetime.now() + timedelta(days=expiry_days)
            
            code_data = {
                "code": code,
                "value": value,
                "used": False,
                "createdAt": datetime.now(),
                "expiresAt": expires_at,
                "createdBy": user.get("email") or user.get("username", "admin"),
                "prefix": prefix
            }
            
            code_ref.set(code_data)
            generated_codes.append(code)
        
        return jsonify({
            "success": True,
            "message": f"Generated {len(generated_codes)} verification codes",
            "codes": generated_codes,
            "count": len(generated_codes)
        })
        
    except Exception as e:
        print(f"Error generating codes: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/verification-codes/<code_id>", methods=["PUT", "DELETE"])
@require_login
@admin_required
def manage_verification_code(code_id):
    """Update or delete a specific verification code"""
    try:
        db = firestore.client()
        
        if request.method == "PUT":
            data = request.get_json()
            code_ref = db.collection("verificationCodes").document(code_id)
            code_doc = code_ref.get()
            
            if not code_doc.exists:
                return jsonify({"error": "Code not found"}), 404
            
            current_data = code_doc.to_dict()
            
            updates = {}
            if "used" in data:
                updates["used"] = data["used"]
                if data["used"]:
                    updates["usedAt"] = datetime.now()
                    updates["usedBy"] = data.get("usedBy") or "admin"
                    updates["usedByEmail"] = data.get("usedByEmail", "")
                else:
                    updates["usedAt"] = None
                    updates["usedBy"] = None
                    updates["usedByEmail"] = None
            
            if "expiresAt" in data and data["expiresAt"]:
                try:
                    expires_at = datetime.fromisoformat(data["expiresAt"].replace('Z', '+00:00'))
                    updates["expiresAt"] = expires_at
                except ValueError:
                    return jsonify({"error": "Invalid date format"}), 400
            
            code_ref.update(updates)
            
            return jsonify({
                "success": True, 
                "message": "Code updated successfully",
                "code": code_id
            })
            
        elif request.method == "DELETE":
            code_ref = db.collection("verificationCodes").document(code_id)
            code_doc = code_ref.get()
            
            if not code_doc.exists:
                return jsonify({"error": "Code not found"}), 404
            
            code_ref.delete()
            return jsonify({
                "success": True, 
                "message": "Code deleted successfully",
                "code": code_id
            })
            
    except Exception as e:
        print(f"Error managing verification code: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/verification-codes/bulk", methods=["POST"])
@require_login
@admin_required
def bulk_import_codes():
    """Bulk import verification codes from text"""
    try:
        data = request.get_json()
        codes_text = data.get("codes", "")
        
        if not codes_text:
            return jsonify({"error": "No codes provided"}), 400
            
        lines = [line.strip() for line in codes_text.split('\n') if line.strip()]
        db = firestore.client()
        user = session.get("user")
        
        imported = 0
        skipped = 0
        errors = []
        
        for idx, line in enumerate(lines, 1):
            parts = [p.strip() for p in line.split(',')]
            if not parts:
                continue
                
            code = parts[0]
            if not code:
                continue
                
            code = code.strip().strip('"').strip("'")
            code_ref = db.collection("verificationCodes").document(code)
            if code_ref.get().exists:
                skipped += 1
                continue
            
            value = 50
            expiry_days = 30
            
            if len(parts) > 1 and parts[1].isdigit():
                expiry_days = int(parts[1])
                if expiry_days < 1 or expiry_days > 365:
                    expiry_days = 30
            
            if len(parts) > 2 and parts[2].isdigit():
                value = int(parts[2])
                if value < 1:
                    value = 50
            
            expires_at = datetime.now() + timedelta(days=expiry_days)
            
            code_data = {
                "code": code,
                "value": value,
                "used": False,
                "createdAt": datetime.now(),
                "expiresAt": expires_at,
                "createdBy": user.get("email") or user.get("username", "admin"),
                "imported": True,
                "importedAt": datetime.now()
            }
            
            try:
                code_ref.set(code_data)
                imported += 1
            except Exception as e:
                errors.append(f"Line {idx}: {str(e)}")
        
        result = {
            "success": True,
            "message": f"Imported {imported} codes, skipped {skipped} duplicates",
            "imported": imported,
            "skipped": skipped
        }
        
        if errors:
            result["errors"] = errors[:5]
        
        return jsonify(result)
        
    except Exception as e:
        print(f"Error in bulk import: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/verification-codes/export", methods=["GET"])
@require_login
@admin_required
def export_verification_codes():
    """Export verification codes as CSV"""
    try:
        db = firestore.client()
        codes_ref = db.collection("verificationCodes").order_by("createdAt", direction=firestore.Query.DESCENDING)
        
        csv_lines = ["Code,Value (GHS),Status,Created,Expires,Used By,Used At\n"]
        
        now = datetime.now()
        
        for doc in codes_ref.stream():
            code_data = doc.to_dict()
            code = code_data.get("code", doc.id)
            
            expires_at = code_data.get("expiresAt")
            if hasattr(expires_at, 'timestamp'):
                expires_at = expires_at.replace(tzinfo=None)
            
            status = "USED" if code_data.get("used", False) else "EXPIRED" if (expires_at and expires_at < now) else "UNUSED"
            
            created_at = code_data.get("createdAt")
            if hasattr(created_at, 'timestamp'):
                created_at_str = created_at.strftime("%Y-%m-%d")
            elif created_at:
                created_at_str = created_at.strftime("%Y-%m-%d") if hasattr(created_at, 'strftime') else str(created_at)[:10]
            else:
                created_at_str = ""
            
            if hasattr(expires_at, 'timestamp'):
                expires_at_str = expires_at.strftime("%Y-%m-%d")
            elif expires_at:
                expires_at_str = expires_at.strftime("%Y-%m-%d") if hasattr(expires_at, 'strftime') else str(expires_at)[:10]
            else:
                expires_at_str = ""
            
            used_at = code_data.get("usedAt")
            if hasattr(used_at, 'timestamp'):
                used_at_str = used_at.strftime("%Y-%m-%d")
            elif used_at:
                used_at_str = used_at.strftime("%Y-%m-%d") if hasattr(used_at, 'strftime') else str(used_at)[:10]
            else:
                used_at_str = ""
            
            csv_line = [
                code,
                str(code_data.get("value", 50)),
                status,
                created_at_str,
                expires_at_str,
                code_data.get("usedByEmail", "") or "",
                used_at_str
            ]
            
            csv_line = [f'"{str(field).replace("\"", "\"\"").replace(",", " ")}"' for field in csv_line]
            csv_lines.append(','.join(csv_line) + '\n')
        
        response = make_response(''.join(csv_lines))
        filename = f"verification_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-Type"] = "text/csv"
        
        return response
        
    except Exception as e:
        print(f"Error exporting codes: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/api/verification-codes/stats", methods=["GET"])
@require_login
@admin_required
def get_verification_codes_stats():
    """Get statistics for verification codes"""
    try:
        db = firestore.client()
        codes_ref = db.collection("verificationCodes")
        
        all_codes = []
        for doc in codes_ref.stream():
            code_data = doc.to_dict()
            all_codes.append(code_data)
        
        now = datetime.now()
        
        stats = {
            "total": len(all_codes),
            "unused": 0,
            "used": 0,
            "expired": 0,
            "total_value": 0,
            "used_value": 0
        }
        
        for code in all_codes:
            value = code.get("value", 50)
            stats["total_value"] += value
            
            expires_at = code.get("expiresAt")
            if hasattr(expires_at, 'timestamp'):
                expires_at = expires_at.replace(tzinfo=None)
            
            expired = expires_at and expires_at < now
            
            if code.get("used", False):
                stats["used"] += 1
                stats["used_value"] += value
            elif expired:
                stats["expired"] += 1
            else:
                stats["unused"] += 1
        
        return jsonify(stats)
        
    except Exception as e:
        print(f"Error getting code stats: {e}")
        return jsonify({
            "total": 0,
            "unused": 0,
            "used": 0,
            "expired": 0,
            "total_value": 0,
            "used_value": 0,
            "error": str(e)
        })


# Add this to your admin_routes.py or create a new route file

@admin_bp.route("/api/questions")
@require_login
def get_questions_for_users():
    """API endpoint for users to get quiz questions"""
    try:
        db = firestore.client()
        
        # Get filter parameters
        program = request.args.get('program')
        course = request.args.get('course')
        level = request.args.get('level')
        semester = request.args.get('semester')
        difficulty = request.args.get('difficulty')
        
        questions_ref = db.collection("quiz_questions").where("active", "==", True)
        
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
        
        questions = []
        for doc in questions_ref.stream():
            question_data = doc.to_dict()
            question_data["id"] = doc.id
            questions.append(question_data)
        
        return jsonify({
            "success": True,
            "questions": questions,
            "count": len(questions)
        })
        
    except Exception as e:
        print(f"Error fetching questions for users: {e}")
        return jsonify({
            "success": False,
            "error": str(e),
            "questions": []
        }), 500

# ----------------- LOGOUT -----------------
@admin_bp.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("auth.login"))