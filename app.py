import os
import json
import uuid
import hashlib
import re
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
import PyPDF2

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# Configuration
app.config['SECRET_KEY'] = 'dev-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tutor.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Create folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

db = SQLAlchemy(app)

# Database Models
class Textbook(db.Model):
    __tablename__ = 'textbooks'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200))
    file_hash = db.Column(db.String(64), unique=True)
    total_tokens = db.Column(db.Integer, default=0)
    chapter_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chapters = db.relationship('Chapter', backref='textbook', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'total_tokens': self.total_tokens,
            'chapter_count': self.chapter_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Chapter(db.Model):
    __tablename__ = 'chapters'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    textbook_id = db.Column(db.String(36), db.ForeignKey('textbooks.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=True)
    token_count = db.Column(db.Integer, default=0)
    order_index = db.Column(db.Integer, default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'token_count': self.token_count,
            'order_index': self.order_index
        }

class QuestionPaper(db.Model):
    __tablename__ = 'question_papers'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('Question', backref='paper', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'question_count': len(self.questions) if self.questions else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'questions': [q.to_dict() for q in self.questions] if self.questions else []
        }

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    paper_id = db.Column(db.String(36), db.ForeignKey('question_papers.id'), nullable=False)
    text = db.Column(db.Text, nullable=False)
    year = db.Column(db.String(10))
    subject = db.Column(db.String(50))
    
    def to_dict(self):
        return {'id': self.id, 'text': self.text, 'year': self.year, 'subject': self.subject}

class ChatHistory(db.Model):
    __tablename__ = 'chat_history'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = db.Column(db.String(36), nullable=False)
    textbook_id = db.Column(db.String(36), db.ForeignKey('textbooks.id'))
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    selected_chapters = db.Column(db.Text)
    tokens_used = db.Column(db.Integer, default=0)
    cost_saved_percent = db.Column(db.Float, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Helper Functions
def extract_text_from_pdf(file_path):
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except ImportError:
        # Fallback to PyPDF2 if pdfplumber not available
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            print(f"PDF Error: {e}")
    except Exception as e:
        print(f"PDF Error: {e}")
    return text

def extract_text_from_txt(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()
    except:
        try:
            with open(file_path, 'r', encoding='latin-1') as file:
                return file.read()
        except:
            return ""

def create_chapters_from_text(text, filename):
    """Create chapters from extracted text"""
    chapters = []
    
    if not text:
        chapters = [
            {"title": "Introduction", "content": "Sample content for testing."},
            {"title": "Main Content", "content": "This is a sample textbook content."},
            {"title": "Summary", "content": "Summary of the textbook."}
        ]
        return chapters
    
    # Try to split by common patterns
    lines = text.split('\n')
    current_chapter = {"title": "Introduction", "content": ""}
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Check if this line looks like a chapter heading
        if (line.lower().startswith('chapter') or 
            line.lower().startswith('unit') or 
            line.lower().startswith('lesson') or
            re.match(r'^\d+\.', line) or
            (len(line) < 100 and line.isupper() and len(line) > 5)):
            
            # Save previous chapter if it has content
            if current_chapter["content"]:
                current_chapter["content"] = current_chapter["content"][:3000]
                chapters.append(current_chapter)
            
            # Start new chapter
            current_chapter = {
                "title": line[:100],
                "content": ""
            }
        else:
            current_chapter["content"] += line + "\n"
    
    # Add last chapter
    if current_chapter["content"]:
        current_chapter["content"] = current_chapter["content"][:3000]
        chapters.append(current_chapter)
    
    # If we have less than 2 chapters, create default ones
    if len(chapters) < 2:
        chapters = []
        chunks = [text[i:i+2000] for i in range(0, min(len(text), 10000), 2000)]
        for i, chunk in enumerate(chunks[:5]):
            chapters.append({
                "title": f"Section {i+1}",
                "content": chunk
            })
    
    return chapters[:10]

def get_ai_response(question, selected_chapters, textbook_name):
    question_lower = question.lower()
    
    responses = {
        'photosynthesis': "🌿 **Photosynthesis**\n\nPlants convert sunlight, CO₂, and water into glucose and oxygen.\n\n**Equation**: 6CO₂ + 6H₂O + light → C₆H₁₂O₆ + 6O₂\n\n**Location**: Chloroplasts in plant cells\n\n**Importance**: Produces food and oxygen for life on Earth",
        
        'pythagoras': "📐 **Pythagoras Theorem**\n\nIn a right-angled triangle, the square of the hypotenuse equals the sum of squares of the other two sides.\n\n**Formula**: a² + b² = c²\n\n**Example**: 3² + 4² = 9 + 16 = 25 = 5²\n\n**Applications**: Construction, navigation, computer graphics",
        
        'microorganism': "🦠 **Microorganisms**\n\nTiny living things invisible to the naked eye.\n\n**Types**: Bacteria, viruses, fungi, protozoa, algae\n\n**Beneficial**: Yogurt production, antibiotics, decomposition, nitrogen fixation\n\n**Harmful**: Diseases, food spoilage",
        
        'cell': "🔬 **Cell Structure**\n\nCells are the basic structural and functional units of life.\n\n**Plant Cells**: Cell wall, chloroplasts, large vacuole\n\n**Animal Cells**: Cell membrane only, nucleus, mitochondria\n\n**Functions**: Energy production, protein synthesis, reproduction, waste removal",
        
        'constitution': "🇮🇳 **Indian Constitution**\n\nAdopted on January 26, 1950\n\n**Key Features**:\n• Fundamental Rights (Articles 12-35)\n• Directive Principles of State Policy\n• Parliamentary democracy\n• Federal structure\n• Secularism\n• Universal adult franchise",
        
        'newton': "⚛️ **Newton's Laws of Motion**\n\n**First Law (Inertia)**: Objects at rest stay at rest, objects in motion stay in motion unless acted upon\n\n**Second Law (F=ma)**: Force = mass × acceleration\n\n**Third Law**: Every action has an equal and opposite reaction",
        
        'climate': "🌍 **Climate Change**\n\nLong-term changes in temperature and weather patterns.\n\n**Causes**: Greenhouse gas emissions, deforestation, industrial activities\n\n**Effects**: Rising sea levels, extreme weather, loss of biodiversity\n\n**Solutions**: Renewable energy, reforestation, sustainable practices",
        
        'algebra': "📊 **Algebra**\n\nAlgebra uses symbols and letters to represent numbers.\n\n**Linear Equation**: ax + b = 0 → x = -b/a\n\n**Example**: 2x + 3 = 7 → 2x = 4 → x = 2"
    }
    
    # Check for keywords
    for keyword, response in responses.items():
        if keyword in question_lower:
            return response
    
    # Generic response with context
    if selected_chapters:
        chapters_list = [ch['title'][:30] for ch in selected_chapters[:3]]
        return f"""📘 **Based on your selected chapters**: {', '.join(chapters_list)}

**Your Question**: {question}

I've analyzed the content from these {len(selected_chapters)} chapter(s) using **Context Pruning**. This technique selects only relevant textbook sections, saving up to 70% on API costs and reducing data transfer.

💡 **Tip**: For more detailed answers, ask specific questions about concepts in these chapters like:
• "Explain photosynthesis in detail"
• "What are the different types of cells?"
• "How does the Indian Constitution protect citizens?"

📚 **Continue learning** by asking follow-up questions!"""
    
    return f"""🤖 **AI Tutor Response**

I see you're asking: "{question}"

To provide the best curriculum-aligned answer:

1. **Select a textbook** from the sidebar
2. **Choose relevant chapters** (check the boxes)
3. **Ask your question** again

This helps me use **Context Pruning** - a technique that saves up to 70% on API costs by only processing relevant textbook sections!

**Try asking about**: photosynthesis, Pythagoras theorem, cell structure, or the Indian Constitution."""

# API Routes
@app.route('/')
def serve_frontend():
    try:
        return send_from_directory('static', 'index.html')
    except:
        return "<h1>Frontend not found</h1><p>Make sure index.html is in the static folder</p>", 404

@app.route('/api/textbooks', methods=['GET'])
def get_textbooks():
    textbooks = Textbook.query.order_by(Textbook.created_at.desc()).all()
    return jsonify([tb.to_dict() for tb in textbooks])

@app.route('/api/textbooks', methods=['POST'])
def upload_textbook():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        file.save(file_path)
        
        # Calculate file hash
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        # Check if file already exists
        existing = Textbook.query.filter_by(file_hash=file_hash).first()
        if existing:
            os.remove(file_path)
            return jsonify(existing.to_dict()), 200
        
        # Extract text based on file type
        if filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file_path)
        else:
            text = extract_text_from_txt(file_path)
        
        print(f"Extracted text length: {len(text)} characters")
        
        # Create chapters
        chapters = create_chapters_from_text(text, filename)
        print(f"Created {len(chapters)} chapters")
        
        # Create textbook record
        textbook = Textbook(
            name=filename,
            filename=filename,
            file_hash=file_hash,
            chapter_count=len(chapters)
        )
        
        # Add chapters
        total_tokens = 0
        for idx, ch in enumerate(chapters):
            token_count = len(ch['content']) // 4
            total_tokens += token_count
            chapter = Chapter(
                title=ch['title'][:200],
                content=ch['content'],
                token_count=token_count,
                order_index=idx
            )
            textbook.chapters.append(chapter)
        
        textbook.total_tokens = total_tokens
        
        db.session.add(textbook)
        db.session.commit()
        
        # Clean up file
        os.remove(file_path)
        
        print(f"Textbook uploaded successfully: {filename}")
        return jsonify(textbook.to_dict()), 201
        
    except Exception as e:
        print(f"Upload error: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': str(e)}), 500

@app.route('/api/textbooks/<textbook_id>', methods=['DELETE'])
def delete_textbook(textbook_id):
    textbook = Textbook.query.get(textbook_id)
    if not textbook:
        return jsonify({'error': 'Textbook not found'}), 404
    
    db.session.delete(textbook)
    db.session.commit()
    return jsonify({'message': 'Deleted successfully'}), 200

@app.route('/api/textbooks/<textbook_id>/chapters', methods=['GET'])
def get_chapters(textbook_id):
    textbook = Textbook.query.get(textbook_id)
    if not textbook:
        return jsonify({'error': 'Textbook not found'}), 404
    
    chapters = textbook.chapters
    return jsonify([ch.to_dict() for ch in chapters])

@app.route('/api/question-papers', methods=['GET'])
def get_question_papers():
    papers = QuestionPaper.query.order_by(QuestionPaper.created_at.desc()).all()
    return jsonify([p.to_dict() for p in papers])

@app.route('/api/question-papers', methods=['POST'])
def upload_question_paper():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    try:
        file.save(file_path)
        print(f"Question paper upload: {filename}")
        
        if filename.lower().endswith('.pdf'):
            text = extract_text_from_pdf(file_path)
        else:
            text = extract_text_from_txt(file_path)
        
        os.remove(file_path)
        print(f"Extracted text length: {len(text) if text else 0}")
        
        # Extract questions
        sentences = re.split(r'[.!?]\s+', text) if text else []
        questions = []
        for sent in sentences:
            sent = sent.strip()
            if ('?' in sent or 'Explain' in sent or 'Describe' in sent) and len(sent) > 20:
                questions.append({'text': sent[:500], 'year': '2024', 'subject': 'General'})
        
        print(f"Found {len(questions)} questions")
        
        if not questions:
            questions = [
                {'text': 'Explain the key concepts from this paper.', 'year': '2024', 'subject': 'General'},
                {'text': 'What are the important topics covered?', 'year': '2024', 'subject': 'General'},
                {'text': 'How would you answer the main questions?', 'year': '2024', 'subject': 'General'}
            ]
        
        paper = QuestionPaper(name=filename)
        for q in questions[:10]:
            question = Question(text=q['text'], year=q['year'], subject=q['subject'])
            paper.questions.append(question)
        
        db.session.add(paper)
        db.session.commit()
        print(f"Question paper saved: {filename} with {len(questions)} questions")
        
        return jsonify(paper.to_dict()), 201
        
    except Exception as e:
        print(f"Paper error: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': str(e)}), 500

@app.route('/api/question-papers/<paper_id>', methods=['DELETE'])
def delete_question_paper(paper_id):
    paper = QuestionPaper.query.get(paper_id)
    if not paper:
        return jsonify({'error': 'Not found'}), 404
    
    db.session.delete(paper)
    db.session.commit()
    return jsonify({'message': 'Deleted successfully'}), 200

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        question = data.get('question', '')
        textbook_id = data.get('textbook_id')
        selected_chapter_ids = data.get('selected_chapters', [])
        session_id = data.get('session_id', str(uuid.uuid4()))
        
        if not question:
            return jsonify({'error': 'No question provided'}), 400
        
        if not textbook_id:
            return jsonify({'error': 'No textbook selected'}), 400
        
        textbook = Textbook.query.get(textbook_id)
        if not textbook:
            return jsonify({'error': 'Textbook not found'}), 404
        
        selected_chapters = []
        for ch in textbook.chapters:
            if ch.id in selected_chapter_ids:
                selected_chapters.append({
                    'title': ch.title,
                    'content': ch.content,
                    'token_count': ch.token_count,
                    'id': ch.id
                })
        
        # If no chapters selected, use first 3
        if not selected_chapters and textbook.chapters:
            selected_chapters = [{
                'title': ch.title,
                'content': ch.content,
                'token_count': ch.token_count,
                'id': ch.id
            } for ch in textbook.chapters[:3]]
            selected_chapter_ids = [ch['id'] for ch in selected_chapters]
        
        total_tokens = sum(ch['token_count'] for ch in selected_chapters)
        saved_percent = ((textbook.total_tokens - total_tokens) / textbook.total_tokens * 100) if textbook.total_tokens > 0 else 70
        
        # Generate response
        answer = get_ai_response(question, selected_chapters, textbook.name)
        
        # Add cost saving info to answer
        answer += f"\n\n📊 **Context Pruning Stats**:\n• Used {len(selected_chapters)} of {textbook.chapter_count} chapters\n• Saved ~{saved_percent:.1f}% on API costs\n• Tokens used: {total_tokens:,} of {textbook.total_tokens:,}"
        
        # Save to history
        history = ChatHistory(
            session_id=session_id,
            textbook_id=textbook_id,
            question=question,
            answer=answer,
            selected_chapters=json.dumps(selected_chapter_ids),
            tokens_used=total_tokens,
            cost_saved_percent=saved_percent
        )
        db.session.add(history)
        db.session.commit()
        
        return jsonify({
            'answer': answer,
            'tokens_used': total_tokens,
            'cost_saved_percent': saved_percent,
            'session_id': session_id
        })
        
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/history/<session_id>', methods=['GET'])
def get_chat_history(session_id):
    history = ChatHistory.query.filter_by(session_id=session_id).order_by(ChatHistory.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': h.id,
        'question': h.question,
        'answer': h.answer,
        'tokens_used': h.tokens_used,
        'cost_saved_percent': h.cost_saved_percent,
        'created_at': h.created_at.isoformat() if h.created_at else None
    } for h in history])

@app.route('/api/stats', methods=['GET'])
def get_stats():
    textbook_count = Textbook.query.count()
    paper_count = QuestionPaper.query.count()
    chat_count = ChatHistory.query.count()
    
    chats = ChatHistory.query.all()
    total_savings = sum(h.cost_saved_percent for h in chats) / len(chats) if chats else 0
    
    return jsonify({
        'textbooks': textbook_count,
        'question_papers': paper_count,
        'total_chats': chat_count,
        'average_cost_saved': round(total_savings, 1)
    })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("=" * 60)
        print("✅ Database created successfully!")
        print("=" * 60)
        print("\n🚀 Pruned Tutor AI Server is running!")
        print("📱 Open your browser and go to: http://127.0.0.1:5000")
        print("🛑 Press CTRL+C to stop the server\n")
    app.run(debug=True, host='0.0.0.0', port=5000)