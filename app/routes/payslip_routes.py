# app/routes/payslip_routes.py
from flask import Blueprint, request, jsonify, send_file, g, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models import Payslip, PayrollItem, Employee, User, AuditLog, PayrollRun, Church  # Added Church
from app.extensions import db
from datetime import datetime
import io
import base64
import logging
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import qrcode
from io import BytesIO
import traceback

logger = logging.getLogger(__name__)
payslip_bp = Blueprint('payslip', __name__)

# ==================== HELPER FUNCTIONS ====================

def get_current_user():
    """Get current user from JWT token or g"""
    if hasattr(g, 'current_user') and g.current_user:
        return g.current_user
    
    try:
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(int(user_id))
            if user:
                g.current_user = user
                return user
    except Exception as e:
        logger.warning(f"Error getting user from JWT: {e}")
    
    return None

def ensure_user_church(user=None):
    """
    Ensure we have a valid church_id.
    Returns church_id or raises appropriate error.
    """
    try:
        # Case 1: User object provided
        if user and hasattr(user, 'church_id') and user.church_id:
            return user.church_id
        
        # Case 2: Try to get current user from context
        current_user = get_current_user()
        if current_user and current_user.church_id:
            return current_user.church_id
        
        # Case 3: Try to get default church
        default_church = Church.query.first()
        if default_church:
            # If we have a user but no church_id, assign default
            if current_user and not current_user.church_id:
                current_user.church_id = default_church.id
                db.session.add(current_user)
                db.session.commit()
                logger.info(f"Assigned default church {default_church.id} to user {current_user.id}")
            return default_church.id
        
        # Case 4: For development, return a fallback
        if current_app.debug:
            logger.warning("Using fallback church_id=1 for development")
            return 1
            
        raise ValueError("No church found in database")
        
    except Exception as e:
        logger.error(f"Error in ensure_user_church: {str(e)}")
        if current_app.debug:
            return 1  # Fallback for development
        raise

# Rest of your existing code remains the same...
# [Keep all your existing route functions exactly as they are]

def generate_payslip_pdf(payslip, payroll_item, employee, payroll_run):
    """Generate PDF payslip"""
    # [Your existing generate_payslip_pdf function remains unchanged]
    buffer = BytesIO()
    
    try:
        # Create PDF document
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        elements = []
        
        # Add custom styles
        styles.add(ParagraphStyle(
            name='CenterTitle',
            parent=styles['Heading1'],
            alignment=TA_CENTER,
            spaceAfter=30
        ))
        
        styles.add(ParagraphStyle(
            name='RightAlign',
            parent=styles['Normal'],
            alignment=TA_RIGHT
        ))
        
        # Header with church info
        church = employee.church
        church_name = church.name if church else 'Church Payroll'
        elements.append(Paragraph(f"{church_name}", styles['CenterTitle']))
        elements.append(Paragraph(f"PAYSLIP - {payslip.payslip_number}", styles['CenterTitle']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Employee Information
        data = [
            ['EMPLOYEE DETAILS', ''],
            ['Employee Name:', employee.full_name()],
            ['Employee Code:', employee.employee_code],
            ['Department:', employee.department or 'N/A'],
            ['Position:', employee.position or 'N/A'],
            ['Pay Period:', f"{payroll_run.period_start.strftime('%d-%b-%Y')} to {payroll_run.period_end.strftime('%d-%b-%Y')}"],
            ['Payment Date:', payroll_run.payment_date.strftime('%d-%b-%Y')],
        ]
        
        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Earnings
        data = [
            ['EARNINGS', 'Amount (GHS)'],
            ['Regular Pay:', f"{float(payroll_item.regular_pay):,.2f}"],
            ['Overtime Pay:', f"{float(payroll_item.overtime_pay):,.2f}"],
            ['Bonus Pay:', f"{float(payroll_item.bonus_pay):,.2f}"],
            ['Allowance Pay:', f"{float(payroll_item.allowance_pay):,.2f}"],
            ['GROSS PAY:', f"{float(payroll_item.gross_pay):,.2f}"]
        ]
        
        table = Table(data, colWidths=[3*inch, 3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.green),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.lightgreen),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lime),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.2*inch))
        
        # Deductions
        data = [
            ['DEDUCTIONS', 'Amount (GHS)'],
            ['PAYE Tax:', f"{float(payroll_item.tax_amount):,.2f}"],
            ['Pension (SSNIT):', f"{float(payroll_item.pension_amount):,.2f}"],
            ['Health Insurance:', f"{float(payroll_item.health_insurance):,.2f}"],
            ['Other Deductions:', f"{float(payroll_item.other_deductions):,.2f}"],
            ['TOTAL DEDUCTIONS:', f"{float(payroll_item.total_deductions):,.2f}"]
        ]
        
        table = Table(data, colWidths=[3*inch, 3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -2), colors.pink),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightcoral),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Net Pay
        data = [
            ['NET PAY', f"GHS {float(payroll_item.net_pay):,.2f}"]
        ]
        
        table = Table(data, colWidths=[3*inch, 3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.blue),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 14),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Bank Details
        data = [
            ['BANK DETAILS', ''],
            ['Bank Name:', employee.bank_name or 'N/A'],
            ['Account Name:', employee.bank_account_name or employee.full_name()],
            ['Account Number:', employee.bank_account_number or 'N/A'],
            ['Branch:', employee.bank_branch or 'N/A'],
        ]
        
        table = Table(data, colWidths=[2*inch, 4*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Generate QR Code for verification
        try:
            qr_data = f"Payslip:{payslip.payslip_number}|Employee:{employee.employee_code}|Net:{payroll_item.net_pay}"
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert QR code to ReportLab Image
            img_buffer = BytesIO()
            qr_img.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            qr_image = Image(img_buffer, width=1*inch, height=1*inch)
            
            # Footer with QR code
            footer_data = [[qr_image, 'This is a computer-generated document. No signature required.']]
            footer_table = Table(footer_data, colWidths=[1.5*inch, 4.5*inch])
            footer_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ]))
            elements.append(footer_table)
        except Exception as e:
            logger.error(f"Error generating QR code: {str(e)}")
            # Add simple footer without QR code
            elements.append(Paragraph("This is a computer-generated document. No signature required.", styles['Normal']))
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()
        
    except Exception as e:
        logger.error(f"Error in PDF generation: {str(e)}")
        traceback.print_exc()
        raise


# [All your existing route functions remain exactly the same]
# [Keep all the @payslip_bp.route decorators and functions as they are]

@payslip_bp.route('/generate/<int:payroll_run_id>', methods=['POST', 'OPTIONS'])
@jwt_required()
def generate_payslips(payroll_run_id):
    """Generate payslips for all employees in a payroll run"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        payroll_run = PayrollRun.query.get(payroll_run_id)
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Check church access
        if user.church_id != payroll_run.church_id and not user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        generated = []
        failed = []
        
        for item in payroll_run.items:
            try:
                # Check if payslip already exists
                existing = Payslip.query.filter_by(payroll_item_id=item.id).first()
                if existing:
                    generated.append({
                        'employee_id': item.employee_id,
                        'payslip_number': existing.payslip_number,
                        'status': 'already_exists'
                    })
                    continue
                
                # Generate payslip number
                year = payroll_run.period_start.year
                month = payroll_run.period_start.month
                count = Payslip.query.filter(
                    Payslip.payslip_number.like(f'PS-{year}-{month:02d}%')
                ).count() + 1
                
                payslip_number = f"PS-{year}-{month:02d}-{item.employee_id:04d}-{count:02d}"
                
                # Create payslip record
                payslip = Payslip(
                    payroll_item_id=item.id,
                    payslip_number=payslip_number
                )
                
                # Generate PDF
                pdf_data = generate_payslip_pdf(payslip, item, item.employee, payroll_run)
                payslip.pdf_data = pdf_data
                payslip.pdf_generated_at = datetime.utcnow()
                
                db.session.add(payslip)
                db.session.flush()
                
                generated.append({
                    'employee_id': item.employee_id,
                    'employee_name': item.employee.full_name(),
                    'payslip_number': payslip_number,
                    'status': 'generated'
                })
                
            except Exception as e:
                logger.error(f"Error generating payslip for employee {item.employee_id}: {str(e)}")
                traceback.print_exc()
                failed.append({
                    'employee_id': item.employee_id,
                    'error': str(e)
                })
        
        db.session.commit()
        
        return jsonify({
            'message': f'Generated {len(generated)} payslips',
            'generated': generated,
            'failed': failed
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error generating payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/<int:payslip_id>/download', methods=['GET', 'OPTIONS'])
@jwt_required()
def download_payslip(payslip_id):
    """Download a specific payslip PDF"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        payslip = Payslip.query.get(payslip_id)
        if not payslip or not payslip.pdf_data:
            return jsonify({'error': 'Payslip not found or PDF not generated'}), 404
        
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Allow if user is admin or the employee themselves
        payroll_item = payslip.payroll_item
        employee = payroll_item.employee
        
        # Check if user is admin or the employee (if employee has user_id)
        is_employee = employee.user_id and employee.user_id == current_user_id
        if not user.is_admin and not is_employee:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Return PDF file
        return send_file(
            io.BytesIO(payslip.pdf_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"payslip_{payslip.payslip_number}.pdf"
        )
        
    except Exception as e:
        logger.error(f"Error downloading payslip: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/employee/<int:employee_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_employee_payslips(employee_id):
    """Get all payslips for an employee"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        employee = Employee.query.get(employee_id)
        
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
        
        # Check if user is admin or the employee themselves
        is_employee = employee.user_id and employee.user_id == current_user_id
        if not user.is_admin and not is_employee:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Get payslips through payroll items
        payslips = Payslip.query.join(PayrollItem).filter(
            PayrollItem.employee_id == employee_id
        ).order_by(Payslip.created_at.desc()).all()
        
        result = []
        for p in payslips:
            p_dict = p.to_dict()
            if p.payroll_item and p.payroll_item.payroll_run:
                p_dict['payroll_period'] = {
                    'start': p.payroll_item.payroll_run.period_start.isoformat() if p.payroll_item.payroll_run.period_start else None,
                    'end': p.payroll_item.payroll_run.period_end.isoformat() if p.payroll_item.payroll_run.period_end else None
                }
            p_dict['net_pay'] = float(p.payroll_item.net_pay) if p.payroll_item and p.payroll_item.net_pay else 0
            result.append(p_dict)
        
        return jsonify({
            'employee_id': employee_id,
            'employee_name': employee.full_name(),
            'payslips': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching employee payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/<int:payslip_id>/sign', methods=['POST', 'OPTIONS'])
@jwt_required()
def sign_payslip(payslip_id):
    """Employee signs a payslip"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        payslip = Payslip.query.get(payslip_id)
        if not payslip:
            return jsonify({'error': 'Payslip not found'}), 404
        
        # Check authorization (only the employee can sign)
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        payroll_item = payslip.payroll_item
        employee = payroll_item.employee
        
        # Check if user is the employee
        if not employee.user_id or employee.user_id != current_user_id:
            return jsonify({'error': 'Only the employee can sign their payslip'}), 403
        
        data = request.get_json() or {}
        signature = data.get('signature')
        
        if not signature:
            return jsonify({'error': 'Signature is required'}), 400
        
        payslip.employee_signature = signature
        payslip.signed_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Payslip signed successfully',
            'signed_at': payslip.signed_at.isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error signing payslip: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/<int:payslip_id>/view', methods=['POST', 'OPTIONS'])
@jwt_required()
def mark_payslip_viewed(payslip_id):
    """Mark payslip as viewed by employee"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        payslip = Payslip.query.get(payslip_id)
        if not payslip:
            return jsonify({'error': 'Payslip not found'}), 404
        
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        payroll_item = payslip.payroll_item
        employee = payroll_item.employee
        
        # Check if user is admin or the employee
        is_employee = employee.user_id and employee.user_id == current_user_id
        if not user.is_admin and not is_employee:
            return jsonify({'error': 'Unauthorized'}), 403
        
        payslip.viewed_by_employee = True
        payslip.viewed_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Payslip marked as viewed',
            'viewed_at': payslip.viewed_at.isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking payslip viewed: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/bulk-email/<int:payroll_run_id>', methods=['POST', 'OPTIONS'])
@jwt_required()
def bulk_email_payslips(payroll_run_id):
    """Email payslips to all employees in a payroll run"""
    # [Your existing code stays exactly the same]
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        from app.utils.email import send_payslip_email
        
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user or not user.is_admin:
            return jsonify({'error': 'Admin access required'}), 403
        
        payroll_run = PayrollRun.query.get(payroll_run_id)
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Check church access
        if user.church_id != payroll_run.church_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        payslips = Payslip.query.join(PayrollItem).filter(
            PayrollItem.payroll_run_id == payroll_run_id
        ).all()
        
        sent = []
        failed = []
        
        for payslip in payslips:
            try:
                employee = payslip.payroll_item.employee
                
                if not employee.email:
                    failed.append({
                        'employee_id': employee.id,
                        'employee_name': employee.full_name(),
                        'error': 'No email address'
                    })
                    continue
                
                # Send email with payslip attachment
                success = send_payslip_email(
                    to_email=employee.email,
                    employee_name=employee.full_name(),
                    payslip_pdf=payslip.pdf_data,
                    payslip_number=payslip.payslip_number
                )
                
                if success:
                    payslip.emailed_to = employee.email
                    payslip.emailed_at = datetime.utcnow()
                    payslip.email_status = 'sent'
                    sent.append({
                        'employee_id': employee.id,
                        'employee_name': employee.full_name(),
                        'email': employee.email
                    })
                else:
                    payslip.email_status = 'failed'
                    failed.append({
                        'employee_id': employee.id,
                        'employee_name': employee.full_name(),
                        'error': 'Email sending failed'
                    })
                    
            except Exception as e:
                logger.error(f"Error emailing payslip: {str(e)}")
                failed.append({
                    'employee_id': employee.id,
                    'employee_name': employee.full_name(),
                    'error': str(e)
                })
        
        db.session.commit()
        
        return jsonify({
            'message': f'Sent {len(sent)} emails, {len(failed)} failed',
            'sent': sent,
            'failed': failed
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error bulk emailing payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@payslip_bp.route('/all', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_all_payslips():
    """Get all payslips (for admin view)"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        church_id = ensure_user_church()  # Now this function is defined
        
        # Get all payslips through payroll items and payroll runs
        payslips = Payslip.query.join(PayrollItem).join(PayrollRun).filter(
            PayrollRun.church_id == church_id
        ).order_by(Payslip.created_at.desc()).all()
        
        return jsonify({
            'payslips': [p.to_dict() for p in payslips]
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching all payslips: {str(e)}")
        return jsonify({'error': str(e)}), 500
    

@payslip_bp.route('/run/<int:payroll_run_id>', methods=['GET', 'OPTIONS'])
@jwt_required()
def get_payroll_run_payslips(payroll_run_id):
    """Get all payslips for a payroll run"""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Check authorization
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        payroll_run = PayrollRun.query.get(payroll_run_id)
        if not payroll_run:
            return jsonify({'error': 'Payroll run not found'}), 404
        
        # Check church access
        if user.church_id != payroll_run.church_id and not user.is_admin:
            return jsonify({'error': 'Unauthorized'}), 403
        
        payslips = Payslip.query.join(PayrollItem).filter(
            PayrollItem.payroll_run_id == payroll_run_id
        ).all()
        
        result = []
        for p in payslips:
            p_dict = p.to_dict()
            p_dict['employee'] = {
                'id': p.payroll_item.employee_id,
                'name': p.payroll_item.employee.full_name() if p.payroll_item.employee else None,
                'code': p.payroll_item.employee.employee_code if p.payroll_item.employee else None
            }
            p_dict['net_pay'] = float(p.payroll_item.net_pay) if p.payroll_item and p.payroll_item.net_pay else 0
            result.append(p_dict)
        
        return jsonify({
            'payroll_run_id': payroll_run_id,
            'run_number': payroll_run.run_number,
            'total_payslips': len(result),
            'payslips': result
        }), 200
        
    except Exception as e:
        logger.error(f"Error fetching payroll run payslips: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500