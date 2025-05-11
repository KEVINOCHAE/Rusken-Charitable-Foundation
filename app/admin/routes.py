from flask import Blueprint, render_template, redirect, url_for, flash,current_app as app
from app import db, csrf
from app.admin.forms import EmptyForm, ProgramImageForm 
from app.auth.routes import roles_required
from app.admin.models import User,ProgramImage, Program
from flask_login import login_required
import os
import uuid
from PIL import Image
from werkzeug.utils import secure_filename

# Create a blueprint for admin routes
admin_bp = Blueprint('admin', __name__)



@admin_bp.route('/admin/dashboard', methods=['GET'])
@roles_required('Admin')
def dashboard():
    
    return render_template('admin/dashboard.html')



@admin_bp.route('/admin/users')
@roles_required('Admin')
@login_required
def list_users():
    form= EmptyForm()
    users = User.query.all()
    return render_template('admin/list_users.html', users=users, form=form)

@admin_bp.route('/admin/programs/<int:program_id>/images', methods=['GET', 'POST'])
@login_required
def upload_program_image(program_id):
    program = Program.query.get_or_404(program_id)
    form = ProgramImageForm()

    if form.validate_on_submit():
        # 1. Grab and sanitize the file
        file = form.image.data
        orig_name = secure_filename(file.filename)
        ext = orig_name.rsplit('.', 1)[1].lower()

        # 2. Validate extension
        if ext not in app.config['ALLOWED_EXTENSIONS']:
            flash('Allowed image types: png, jpg, jpeg, gif', 'danger')
            return redirect(request.url)

        # 3. Determine absolute upload folder and ensure it exists
        upload_folder = os.path.join('/data', 'programs')  
        os.makedirs(upload_folder, exist_ok=True)

        # 4. Create a unique filename and paths
        unique_name = f"{uuid.uuid4().hex}.{ext}"
        save_path   = os.path.join(upload_folder, unique_name)
        thumb_name  = f"thumb_{unique_name}"
        thumb_path  = os.path.join(upload_folder, thumb_name)

        # 5. Save original
        file.save(save_path)

        # 6. Generate and save thumbnail
        try:
            img = Image.open(save_path)
            img.thumbnail((400, 300), Image.Resampling.LANCZOS)
            img.save(thumb_path, optimize=True, quality=85)
        except Exception:
            flash('Failed to process image.', 'danger')
            return redirect(request.url)

        # 7. Persist to database (store path for later access)
        program_image = ProgramImage(
            program_id=program.id,
            filename=f"programs/{unique_name}",  # Or just unique_name if storing pure filename
            is_cover=form.is_cover.data
        )
        db.session.add(program_image)
        db.session.commit()

        flash('Image uploaded & optimized!', 'success')
        return redirect(url_for('program.list_programs')) 

    return render_template('admin/upload_image.html', form=form, program=program)
