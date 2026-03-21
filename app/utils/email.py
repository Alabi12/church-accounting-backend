# app/utils/email.py
from flask import current_app
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import logging

logger = logging.getLogger(__name__)

def send_payslip_email(to_email, employee_name, payslip_pdf, payslip_number):
    """Send payslip email with PDF attachment"""
    try:
        # Get email settings from config
        smtp_server = current_app.config.get('MAIL_SERVER', 'smtp.gmail.com')
        smtp_port = current_app.config.get('MAIL_PORT', 587)
        smtp_username = current_app.config.get('MAIL_USERNAME')
        smtp_password = current_app.config.get('MAIL_PASSWORD')
        from_email = current_app.config.get('MAIL_DEFAULT_SENDER', smtp_username)
        
        if not all([smtp_username, smtp_password]):
            logger.warning("Email credentials not configured")
            return False
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = from_email
        msg['To'] = to_email
        msg['Subject'] = f"Your Payslip - {payslip_number}"
        
        # Email body
        body = f"""
        <html>
        <body>
            <h2>Dear {employee_name},</h2>
            
            <p>Please find attached your payslip <strong>{payslip_number}</strong>.</p>
            
            <p>This is an auto-generated document. Please keep it for your records.</p>
            
            <p>If you have any questions regarding your payslip, please contact the HR department.</p>
            
            <br>
            <p>Thank you,</p>
            <p>Payroll Department</p>
            
            <hr>
            <p style="font-size: 0.8em; color: #666;">
                This is an automated message. Please do not reply to this email.
            </p>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Attach PDF
        pdf_attachment = MIMEApplication(payslip_pdf, _subtype='pdf')
        pdf_attachment.add_header('Content-Disposition', 'attachment', filename=f"payslip_{payslip_number}.pdf")
        msg.attach(pdf_attachment)
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Payslip email sent to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending payslip email: {str(e)}")
        return False