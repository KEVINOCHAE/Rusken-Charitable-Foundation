from flask import render_template, redirect, url_for, flash, request, Blueprint
from app import db
from app.admin.models import Category, Program
from app.programs.forms import CategoryForm, EmptyForm, ProgramForm
from flask_login import login_required
from app.auth.routes import roles_required
from sqlalchemy.exc import IntegrityError
from flask_login import current_user
from app.auth.routes import roles_required

program_bp= Blueprint('program', __name__ )


@program_bp.route('/categories/create', methods=['GET', 'POST'])
@program_bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@roles_required('Admin')
@login_required
def add_category(id=None):
    category = Category.query.get_or_404(id) if id else Category()
    form = CategoryForm(obj=category)

    if form.validate_on_submit():
        form.populate_obj(category)

        try:
            db.session.add(category)
            db.session.commit()
            flash(f"Category {'updated' if id else 'created'} successfully!", "success")
            return redirect(url_for('program.list_categories'))
        except IntegrityError:
            db.session.rollback()
            flash("A category with that name already exists.", "danger")

    return render_template('admin/create_category.html', form=form)


@program_bp.route('/categories')
@login_required
def list_categories():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = Category.query.order_by(Category.name.asc()).paginate(page=page, per_page=per_page)
    categories = pagination.items
    form = EmptyForm()
    return render_template('admin/list_categories.html ', categories=categories, pagination=pagination , form=form)



@program_bp.route('/admin/program/add', methods=['GET', 'POST'])
@roles_required('Admin')
@login_required
def add_program():
    form = ProgramForm()
    if form.validate_on_submit():
        program = Program(
            title=form.title.data,
            description=form.description.data,
            story=form.story.data,
            cover_image=form.cover_image.data,
            annual_budget=form.annual_budget.data,
            category_id=form.category_id.data,
            author_id=current_user.id
        )
        db.session.add(program)
        db.session.commit()
        flash('Program created successfully.', 'success')
        return redirect(url_for('program.list_programs'))
    return render_template('admin/add_program.html', form=form)


@program_bp.route('/admin/programs')
@roles_required('Admin')
@login_required
def list_programs():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    form = ProgramForm() 
    programs = Program.query.order_by(Program.created_at.desc()).paginate(page=page, per_page=per_page)

    return render_template('admin/list_programs.html', programs=programs, form=form)


@program_bp.route('/admin/programs/edit/<int:program_id>', methods=['GET', 'POST'])
@roles_required('Admin')
@login_required
def edit_program(program_id):
    program = Program.query.get_or_404(program_id)
    form = ProgramForm(obj=program)

    if form.validate_on_submit():
        program.title = form.title.data
        program.description = form.description.data
        program.story = form.story.data
        program.cover_image = form.cover_image.data
        program.annual_budget = form.annual_budget.data
        program.category_id = form.category_id.data

        db.session.commit()
        flash('Program updated successfully.', 'success')
        return redirect(url_for('program.list_programs'))

    return render_template('admin/edit_program.html', form=form, program=program)

