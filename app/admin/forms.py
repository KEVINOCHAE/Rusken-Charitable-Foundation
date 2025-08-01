from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, IntegerField, TextAreaField, SelectField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, Email, EqualTo, Optional
from wtforms import  BooleanField, ValidationError
from flask_wtf.file import FileField, FileAllowed, FileRequired

class EmptyForm(FlaskForm):
    pass

class ProgramImageForm(FlaskForm):
    image = FileField(
        'Program Image',
        validators=[
            FileRequired(message="Please select an image file."),
            FileAllowed(
                ['jpg', 'jpeg', 'png', 'gif'],
                message="Only images with .jpg, .jpeg, .png, .gif extensions are allowed."
            )
        ]
    )
    is_cover = BooleanField('Set as cover image')
    submit   = SubmitField('Upload')