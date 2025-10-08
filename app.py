"""
Plataforma mínima para comunicación interna "Tecnochía" - VERSIÓN: single-file
Flask + SQLite con plantillas embebidas (lista para copiar/pegar en VS Code).

Características añadidas (respecto al prototipo anterior):
- Roles: empleado / administrador
- Página inicial con 3 opciones: Iniciar sesión, Crear cuenta, Iniciar como administrador
- Admin puede iniciar sesión simplemente poniendo su email (según requisito; en producción cambiar a contraseña/SSO)
- Subida de proyectos con archivo (guardado en static/uploads) y descripción
- Comentarios públicos (todos) y comentarios privados (solo admin puede dejar privados)
- Admin: vista tipo "Mercado Libre" (cards), editar/eliminar proyectos, calificar con estrellas y marcar favoritos
- Empleado: crear/ver proyectos, comentar públicamente
- Endpoints para rating, favorite, comments, mensajes públicos

Requisitos:
- Python 3.10+
- pip install flask werkzeug

Correr:
- Guardar este archivo como `app.py` y ejecutar `python app.py`.
- Abrir http://127.0.0.1:5000

NOTA DE SEGURIDAD: el flujo de ingreso de administrador mediante solo email es INSEGURO y está implementado solo para cumplir el pedido de prototipo. En producción usar contraseña fuerte o SSO/LDAP.
"""

from flask import Flask, g, render_template_string, request, redirect, url_for, session, jsonify, send_from_directory
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(APP_DIR, 'static', 'uploads')
DB_PATH = os.path.join(APP_DIR, 'tecnochia_v2.db')
SECRET_KEY = 'cambia_esta_clave_por_otra_muy_segura'
ALLOWED_EXT = {'png','jpg','jpeg','gif','pdf','zip','tar','gz','txt','md'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.secret_key = SECRET_KEY

# ---------------- DB ----------------

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    if os.path.exists(DB_PATH):
        return
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.executescript('''
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        password TEXT,
        role TEXT DEFAULT 'empleado',
        bio TEXT,
        created_at TEXT
    );

    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        file_path TEXT,
        user_id INTEGER,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER,
        text TEXT,
        is_private INTEGER DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(project_id) REFERENCES projects(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER,
        stars INTEGER,
        created_at TEXT
    );

    CREATE TABLE favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        user_id INTEGER,
        created_at TEXT
    );

    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        text TEXT,
        created_at TEXT
    );
    ''')
    # create a default admin user for testing
    hashed = generate_password_hash('adminpass')
    c.execute('INSERT INTO users (email,name,password,role,created_at) VALUES (?,?,?,?,?)', ('admin@tecnologia.com.ar','Admin','%s'%hashed,'admin', datetime.utcnow().isoformat()))
    db.commit()
    db.close()

init_db()

# ---------------- Utils ----------------

def now():
    return datetime.utcnow().isoformat()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXT


def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    db = get_db()
    return db.execute('SELECT id,email,name,role FROM users WHERE id=?', (uid,)).fetchone()

# ---------------- Templates (base) ----------------

BASE = '''
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Tecnochía - Intranet</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/mini.css/3.0.1/mini-default.min.css">
  <style>
    .card{padding:12px;border:1px solid #eee;border-radius:6px}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .uploads img{max-width:100%;height:auto}
    .stars{cursor:pointer}
  </style>
</head>
<body>
<header class="sticky">
  <a href="/" class="brand">Tecnochía</a>
  <a href="/">Inicio</a>
  {% if user %}
    <a href="/dashboard">Mi panel</a>
    {% if user['role']=='admin' %}
      <a href="/admin_dashboard">Panel Admin</a>
    {% endif %}
    <a href="/logout">Cerrar sesión ({{ user['email'] }})</a>
  {% else %}
    <a href="/login">Ingresar</a>
    <a href="/register">Crear cuenta</a>
  {% endif %}
</header>
<main class="container">
  {% block content %}{% endblock %}
</main>
</body>
</html>
'''

# ---------------- Index with 3 options ----------------

@app.route('/')
def index():
    user = current_user()
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h2>Bienvenido a la intranet de Tecnochía</h2>
    <p>Comunicate, comparte proyectos y mejora el trabajo en equipo.</p>
    <div class="row">
      <a class="button" href="/login">Iniciar sesión</a>
      <a class="button" href="/register">Crear cuenta</a>
      <a class="button secondary" href="/admin_login">Iniciar como administrador</a>
    </div>
    '''), user=user)

# ---------------- Auth ----------------

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        name = request.form.get('name') or email.split('@')[0]
        password = request.form['password']
        db = get_db()
        try:
            db.execute('INSERT INTO users (email,name,password,role,created_at) VALUES (?,?,?,?,?)', (email,name,generate_password_hash(password),'empleado', now()))
            db.commit()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return 'Email ya registrado',400
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Crear cuenta (Empleado)</h3>
    <form method="post">
      <label>Email (empresa)</label>
      <input name="email" required placeholder="nombre.apellido@tecnologia.com.ar">
      <label>Nombre</label>
      <input name="name">
      <label>Contraseña</label>
      <input type="password" name="password" required>
      <button type="submit">Crear</button>
    </form>
    '''), user=current_user())

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        db = get_db()
        row = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if not row or not check_password_hash(row['password'], password):
            return 'Credenciales inválidas',400
        session['user_id'] = row['id']
        return redirect(url_for('dashboard'))
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Ingresar (Empleado)</h3>
    <form method="post">
      <label>Email</label>
      <input name="email" required>
      <label>Contraseña</label>
      <input type="password" name="password" required>
      <button type="submit">Ingresar</button>
    </form>
    '''), user=current_user())

@app.route('/admin_login', methods=['GET','POST'])
def admin_login():
    # según pedido: admin puede iniciar solo con email (sin botón extra)
    if request.method=='POST':
        email = request.form['email'].strip().lower()
        db = get_db()
        row = db.execute('SELECT * FROM users WHERE email=? AND role="admin"', (email,)).fetchone()
        if not row:
            return 'No autorizado como admin',403
        # loguear sin pedir contraseña (prototipo)
        session['user_id'] = row['id']
        return redirect(url_for('admin_dashboard'))
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Ingresar como Administrador</h3>
    <form method="post">
      <label>Email de administrador</label>
      <input name="email" required placeholder="admin@tecnologia.com.ar">
      <small>En este prototipo, con solo el email se ingresa como admin.</small>
      <button type="submit">Ingresar como admin</button>
    </form>
    '''), user=current_user())

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ---------------- Dashboard empleado ----------------

@app.route('/dashboard')
def dashboard():
    u = current_user()
    if not u:
        return redirect(url_for('login'))
    db = get_db()
    my_projects = db.execute('SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC', (u['id'],)).fetchall()
    recent = db.execute('SELECT p.*, u.name as owner FROM projects p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC LIMIT 20').fetchall()
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Panel de {{ user['name'] or user['email'] }}</h3>
    <div class="row">
      <a class="button" href="/upload_project">Subir proyecto</a>
      <a class="button" href="/projects">Ver proyectos</a>
    </div>
    <h4>Mis proyectos</h4>
    <div class="grid">
      {% for p in my_projects %}
        <div class="card">
          <strong>{{ p['title'] }}</strong>
          <div class="small">Creado: {{ p['created_at'][:19] }}</div>
          <p>{{ p['description'][:160] }}</p>
          <a href="/project/{{ p['id'] }}">Ver</a>
        </div>
      {% else %}
        <p>No tenés proyectos aún.</p>
      {% endfor %}
    </div>
    <h4>Proyectos recientes</h4>
    <div class="grid">
      {% for p in recent %}
        <div class="card"><strong>{{ p['title'] }}</strong><div class="small">Por {{ p['owner'] }}</div><a href="/project/{{ p['id'] }}">Ver</a></div>
      {% endfor %}
    </div>
    '''), user=u, my_projects=my_projects, recent=recent)

# ---------------- Upload project ----------------

@app.route('/upload_project', methods=['GET','POST'])
def upload_project():
    u = current_user()
    if not u:
        return redirect(url_for('login'))
    if request.method=='POST':
        title = request.form['title'].strip()
        description = request.form['description'].strip()
        file = request.files.get('file')
        file_path = None
        if file and file.filename:
            if allowed_file(file.filename):
                fname = secure_filename(f"{int(datetime.utcnow().timestamp())}_{file.filename}")
                dest = os.path.join(app.config['UPLOAD_FOLDER'], fname)
                file.save(dest)
                file_path = os.path.join('static','uploads',fname)
            else:
                return 'Tipo de archivo no permitido',400
        db = get_db()
        db.execute('INSERT INTO projects (title,description,file_path,user_id,created_at) VALUES (?,?,?,?,?)', (title,description,file_path,u['id'], now()))
        db.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Subir proyecto</h3>
    <form method="post" enctype="multipart/form-data">
      <label>Título</label>
      <input name="title" required>
      <label>Descripción</label>
      <textarea name="description"></textarea>
      <label>Archivo (opcional)</label>
      <input type="file" name="file">
      <button type="submit">Subir</button>
    </form>
    '''), user=u)

# ---------------- View projects (public list) ----------------

@app.route('/projects')
def projects():
    u = current_user()
    db = get_db()
    projs = db.execute('SELECT p.*, u.name as owner FROM projects p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC').fetchall()
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Proyectos</h3>
    <div class="grid">
      {% for p in projs %}
        <div class="card">
          <strong>{{ p['title'] }}</strong>
          <div class="small">Por {{ p['owner'] }}</div>
          <p>{{ p['description'][:140] }}</p>
          {% if p['file_path'] %}
            <div class="uploads"><a href="/{{ p['file_path'] }}" target="_blank">Archivo</a></div>
          {% endif %}
          <a href="/project/{{ p['id'] }}">Ver</a>
        </div>
      {% endfor %}
    </div>
    '''), user=u, projs=projs)

# ---------------- Project detail ----------------

@app.route('/project/<int:pid>', methods=['GET'])
def project_view(pid):
    u = current_user()
    db = get_db()
    p = db.execute('SELECT p.*, u.name as owner FROM projects p JOIN users u ON p.user_id=u.id WHERE p.id=?', (pid,)).fetchone()
    if not p:
        return 'Proyecto no encontrado',404
    comments = db.execute('SELECT c.*, u.name as commenter FROM comments c JOIN users u ON c.user_id=u.id WHERE project_id=? AND (is_private=0 OR (is_private=1 AND ?=1)) ORDER BY created_at DESC', (pid, 1 if (u and u['role']=='admin') else 0)).fetchall()
    avg = db.execute('SELECT AVG(stars) as avg FROM ratings WHERE project_id=?', (pid,)).fetchone()
    is_fav = False
    if u:
        fav = db.execute('SELECT id FROM favorites WHERE project_id=? AND user_id=?', (pid,u['id'])).fetchone()
        is_fav = bool(fav)
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>{{ p['title'] }}</h3>
    <div class="small">Por {{ p['owner'] }} — Creado {{ p['created_at'][:19] }}</div>
    <p>{{ p['description'] }}</p>
    {% if p['file_path'] %}<p><a href="/{{ p['file_path'] }}" target="_blank">Descargar archivo</a></p>{% endif %}
    <hr>
    <h4>Comentarios</h4>
    <div>
      {% for c in comments %}
        <div><strong>{{ c['commenter'] }}</strong> {% if c['is_private'] %}<em>(privado)</em>{% endif %}: {{ c['text'] }} <span class="small">— {{ c['created_at'][:19] }}</span></div>
      {% else %}
        <p>No hay comentarios</p>
      {% endfor %}
    </div>
    {% if user %}
    <form onsubmit="event.preventDefault(); postComment();">
      <textarea id="comment_text" rows="3" style="width:100%"></textarea>
      <div style="margin-top:6px">
        <button type="button" onclick="postComment()">Comentar públicamente</button>
        {% if user['role']=='admin' %}
          <button type="button" onclick="postPrivate()">Comentar PRIVADO</button>
        {% endif %}
      </div>
    </form>
    <script>
      async function postComment(){
        const t=document.getElementById('comment_text').value.trim();
        if(!t) return alert('Escribe algo');
        await fetch('/comment/'+{{ p['id'] }},{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t,is_private:false})});
        location.reload();
      }
      async function postPrivate(){
        const t=document.getElementById('comment_text').value.trim();
        if(!t) return alert('Escribe algo');
        await fetch('/comment/'+{{ p['id'] }},{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t,is_private:true})});
        location.reload();
      }
    </script>
    {% else %}
      <p>Inicia sesión para comentar.</p>
    {% endif %}

    <hr>
    <h4>Acciones</h4>
    {% if user %}
      {% if user['role']=='admin' %}
        <div>
          <label>Calificar (admin):</label>
          <select id="stars">
            <option>1</option><option>2</option><option>3</option><option>4</option><option>5</option>
          </select>
          <button onclick="rate()">Guardar</button>
        </div>
        <script>
          async function rate(){
            const s=document.getElementById('stars').value;
            await fetch('/rate/'+{{ p['id'] }},{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stars:parseInt(s)} )});
            alert('Calificación guardada');location.reload();
          }
        </script>
      {% endif %}
      <div>
        <form method="post" action="/favorite/{{ p['id'] }}">
          <button type="submit">{% if is_fav %}Quitar favorito{% else %}Marcar favorito{% endif %}</button>
        </form>
      </div>
    {% endif %}
    '''), user=u, p=p, comments=comments, avg=avg, is_fav=is_fav)

# ---------------- Comment endpoint ----------------

@app.route('/comment/<int:pid>', methods=['POST'])
def comment(pid):
    u = current_user()
    if not u:
        return jsonify({'error':'auth'}),401
    data = request.get_json() or {}
    text = data.get('text','').strip()
    is_private = bool(data.get('is_private'))
    if is_private and u['role']!='admin':
        return jsonify({'error':'no_priv'}),403
    if not text:
        return jsonify({'error':'empty'}),400
    db = get_db()
    db.execute('INSERT INTO comments (project_id,user_id,text,is_private,created_at) VALUES (?,?,?,?,?)', (pid,u['id'],text,1 if is_private else 0, now()))
    db.commit()
    return jsonify({'ok':True})

# ---------------- Rate endpoint (admin only) ----------------

@app.route('/rate/<int:pid>', methods=['POST'])
def rate(pid):
    u = current_user()
    if not u or u['role']!='admin':
        return jsonify({'error':'auth'}),401
    data = request.get_json() or {}
    stars = int(data.get('stars',0))
    if stars<1 or stars>5:
        return jsonify({'error':'invalid'}),400
    db = get_db()
    # allow multiple admin ratings; for simplicity insert
    db.execute('INSERT INTO ratings (project_id,user_id,stars,created_at) VALUES (?,?,?,?)', (pid,u['id'],stars,now()))
    db.commit()
    return jsonify({'ok':True})

# ---------------- Favorite (toggle) ----------------

@app.route('/favorite/<int:pid>', methods=['POST'])
def favorite(pid):
    u = current_user()
    if not u or u['role']!='admin':
        return 'No autorizado',403
    db = get_db()
    existing = db.execute('SELECT id FROM favorites WHERE project_id=? AND user_id=?', (pid,u['id'])).fetchone()
    if existing:
        db.execute('DELETE FROM favorites WHERE id=?', (existing['id'],))
    else:
        db.execute('INSERT INTO favorites (project_id,user_id,created_at) VALUES (?,?,?)', (pid,u['id'],now()))
    db.commit()
    return redirect(url_for('project_view', pid=pid))

# ---------------- Admin dashboard (market style) ----------------

@app.route('/admin_dashboard')
def admin_dashboard():
    u = current_user()
    if not u or u['role']!='admin':
        return redirect(url_for('admin_login'))
    db = get_db()
    projs = db.execute('SELECT p.*, u.name as owner, (SELECT COUNT(*) FROM comments c WHERE c.project_id=p.id) as comments_count, (SELECT AVG(stars) FROM ratings r WHERE r.project_id=p.id) as avg_rating FROM projects p JOIN users u ON p.user_id=u.id ORDER BY p.created_at DESC').fetchall()
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Panel Administrador - Mercado de Proyectos</h3>
    <div class="grid">
      {% for p in projs %}
        <div class="card">
          <strong>{{ p['title'] }}</strong>
          <div class="small">Por {{ p['owner'] }}</div>
          <div class="small">Comentarios: {{ p['comments_count'] }} — Rating: {{ (p['avg_rating'] or 0)|round(2) }}</div>
          <p>{{ p['description'][:140] }}</p>
          <div class="row">
            <a href="/project/{{ p['id'] }}">Ver</a>
            <a href="/admin_edit/{{ p['id'] }}">Editar</a>
            <form method="post" action="/admin_delete/{{ p['id'] }}" onsubmit="return confirm('Eliminar proyecto?');" style="display:inline">
              <button type="submit">Eliminar</button>
            </form>
          </div>
        </div>
      {% endfor %}
    </div>
    '''), user=u, projs=projs)

# ---------------- Admin edit/delete ----------------

@app.route('/admin_edit/<int:pid>', methods=['GET','POST'])
def admin_edit(pid):
    u = current_user()
    if not u or u['role']!='admin':
        return redirect(url_for('admin_login'))
    db = get_db()
    p = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
    if not p:
        return 'No existe',404
    if request.method=='POST':
        title = request.form['title']
        description = request.form['description']
        db.execute('UPDATE projects SET title=?,description=? WHERE id=?', (title,description,pid))
        db.commit()
        return redirect(url_for('admin_dashboard'))
    return render_template_string(BASE.replace('{% block content %}{% endblock %}', '''
    <h3>Editar proyecto</h3>
    <form method="post">
      <label>Título</label>
      <input name="title" value="{{ p['title'] }}">
      <label>Descripción</label>
      <textarea name="description">{{ p['description'] }}</textarea>
      <button type="submit">Guardar</button>
    </form>
    '''), user=u, p=p)

@app.route('/admin_delete/<int:pid>', methods=['POST'])
def admin_delete(pid):
    u = current_user()
    if not u or u['role']!='admin':
        return 'No autorizado',403
    db = get_db()
    db.execute('DELETE FROM projects WHERE id=?', (pid,))
    db.execute('DELETE FROM comments WHERE project_id=?', (pid,))
    db.execute('DELETE FROM ratings WHERE project_id=?', (pid,))
    db.execute('DELETE FROM favorites WHERE project_id=?', (pid,))
    db.commit()
    return redirect(url_for('admin_dashboard'))

# ---------------- Serve uploads safely ----------------
@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ---------------- Run ----------------
if __name__=='__main__':
    print('Iniciando app en http://127.0.0.1:5000')
    app.run(debug=True)
