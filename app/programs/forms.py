from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Length
from wtforms import StringField, TextAreaField, DecimalField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange
from app.admin.models import Category

class CategoryForm(FlaskForm):
    name = StringField('Category Name', validators=[
        DataRequired(), Length(min=2, max=50)
    ])
    submit = SubmitField('Create Category')
    
class EmptyForm(FlaskForm):
    pass



class ProgramForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Short Description', validators=[Length(max=500)])
    story = TextAreaField('Full Story')  # Could be rich text via JS editor
    cover_image = StringField('Cover Image Path')  # You can change to FileField if handling uploads
    annual_budget = DecimalField('Annual Budget', validators=[DataRequired(), NumberRange(min=0)])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Add Program')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.category_id.choices = [(c.id, c.name) for c in Category.query.order_by(Category.name.asc()).all()]
