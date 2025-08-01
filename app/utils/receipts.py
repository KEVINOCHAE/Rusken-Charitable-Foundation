# app/utils/receipts.py
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, 
    Paragraph, 
    Spacer, 
    Image, 
    Table,
    TableStyle
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.units import mm, inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

# Register fonts (make sure to have these font files in your static/fonts directory)
def register_fonts():
    fonts_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'fonts')
    
    # Montserrat font family
    pdfmetrics.registerFont(TTFont('Montserrat-Bold', os.path.join(fonts_dir, 'Montserrat-Bold.ttf')))
    pdfmetrics.registerFont(TTFont('Montserrat-Regular', os.path.join(fonts_dir, 'Montserrat-Regular.ttf')))
    pdfmetrics.registerFont(TTFont('Montserrat-Light', os.path.join(fonts_dir, 'Montserrat-Light.ttf')))

def generate_receipt_pdf(donation):
    """Generate a professional PDF receipt"""
    register_fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                          leftMargin=20*mm, 
                          rightMargin=20*mm,
                          topMargin=15*mm,
                          bottomMargin=15*mm)
    
    # Styles
    styles = {
        'title': ParagraphStyle(
            'title',
            fontName='Montserrat-Bold',
            fontSize=18,
            leading=22,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2e7d32')  # Dark green
        ),
        'header': ParagraphStyle(
            'header',
            fontName='Montserrat-Regular',
            fontSize=10,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#455a64')  # Dark gray
        ),
        'donor': ParagraphStyle(
            'donor',
            fontName='Montserrat-Bold',
            fontSize=12,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.black
        ),
        'details': ParagraphStyle(
            'details',
            fontName='Montserrat-Regular',
            fontSize=10,
            leading=12,
            alignment=TA_LEFT,
            textColor=colors.black
        ),
        'footer': ParagraphStyle(
            'footer',
            fontName='Montserrat-Light',
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#757575')  # Gray
        ),
        'thankyou': ParagraphStyle(
            'thankyou',
            fontName='Montserrat-Bold',
            fontSize=14,
            leading=16,
            alignment=TA_CENTER,
            textColor=colors.HexColor('#2e7d32')  # Dark green
        )
    }
    
    story = []
    
    # Logo (replace with your actual logo path)
    logo_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'images', 'Rusken-Charity-Foundation.png')
    logo = Image(logo_path, width=1.2*inch, height=1.2*inch)
    story.append(logo)
    story.append(Spacer(1, 10))
    
    # Organization info
    org_info = [
        Paragraph("RUSKEN CHARITABLE FOUNDATION", styles['title']),
        Spacer(1, 5),
        Paragraph("Muindi Mbingu Street, Sixeighty Hotel Building, Office No. 630", styles['header']),
        Paragraph("Nairobi, Kenya", styles['header']),
        Spacer(1, 15),
        Paragraph("OFFICIAL DONATION RECEIPT", styles['title']),
        Spacer(1, 20)
    ]
    story.extend(org_info)
    
    # Donor information
    donor_info = [
        Paragraph("ISSUED TO:", styles['donor']),
        Spacer(1, 5),
        Paragraph(donation.donor_name, styles['details']),
        Paragraph(donation.donor_email, styles['details']),
        Spacer(1, 15)
    ]
    story.extend(donor_info)
    
    # Transaction details table
    transaction_data = [
        ["Transaction ID:", donation.gateway_reference],
        ["Date:", donation.created_at.strftime('%B %d, %Y %I:%M %p')],
        ["Payment Method:", "Card ****" + getattr(donation, 'payment_method_last4', '')],
        ["Amount:", f"{donation.amount} {donation.currency}"],
    ]
    
    if donation.program:
        transaction_data.append(["Program:", donation.program.title])
    
    t = Table(transaction_data, colWidths=[2*inch, 3*inch])
    t.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Montserrat-Regular'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (0,0), (0,-1), 'LEFT'),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('TEXTCOLOR', (0,0), (0,-1), colors.HexColor('#455a64')),  # Dark gray
        ('TEXTCOLOR', (1,0), (1,-1), colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    
    story.append(t)
    story.append(Spacer(1, 25))
    
    # Thank you message
    thankyou = Paragraph(
        "Thank you for your generous support!<br/>"
        "Your contribution helps us make a difference in the community.",
        styles['thankyou']
    )
    story.append(thankyou)
    story.append(Spacer(1, 15))
    
    # Footer
    footer = Paragraph(
        "Rusken Charitable Foundation is a registered non-profit organization.<br/>"
        "This receipt may be used for tax deduction purposes.<br/>"
        "For any inquiries, please contact: ruskencf2024@gmail.com",
        styles['footer']
    )
    story.append(footer)
    
    # Watermark (optional)
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    
    def add_watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont('Montserrat-Light', 40)
        canvas.setFillColor(colors.HexColor('#e8f5e9'))  # Very light green
        canvas.rotate(45)
        canvas.drawString(4*inch, -1*inch, "RUSKEN FOUNDATION")
        canvas.restoreState()
    
    doc.build(story, onFirstPage=add_watermark, onLaterPages=add_watermark)
    buffer.seek(0)
    return buffer