# app/reports/payroll_reports.py
import csv
import io
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from flask import make_response

class PayrollReports:
    
    @staticmethod
    def generate_payroll_summary_csv(payroll_run):
        """Generate payroll summary CSV"""
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['PAYROLL SUMMARY'])
        writer.writerow([f'Run Number: {payroll_run.run_number}'])
        writer.writerow([f'Period: {payroll_run.period_start} to {payroll_run.period_end}'])
        writer.writerow([f'Payment Date: {payroll_run.payment_date}'])
        writer.writerow([])
        
        # Column headers
        writer.writerow([
            'Employee Number', 'Employee Name', 'Department', 'Position',
            'Basic Salary', 'Allowances', 'Overtime', 'Bonus',
            'Gross Pay', 'PAYE', 'SSNIT', 'Provident Fund',
            'Other Deductions', 'Total Deductions', 'Net Pay'
        ])
        
        # Data rows
        for line in payroll_run.lines:
            writer.writerow([
                line.employee.employee_number,
                line.employee.full_name,
                line.employee.department,
                line.employee.position,
                f"{float(line.basic_salary):,.2f}",
                f"{float(line.allowances):,.2f}",
                f"{float(line.overtime):,.2f}",
                f"{float(line.bonus):,.2f}",
                f"{float(line.gross_earnings):,.2f}",
                f"{float(line.paye_tax):,.2f}",
                f"{float(line.ssnit_employee):,.2f}",
                f"{float(line.provident_fund):,.2f}",
                f"{float(line.other_deductions):,.2f}",
                f"{float(line.total_deductions):,.2f}",
                f"{float(line.net_pay):,.2f}"
            ])
        
        # Summary row
        writer.writerow([])
        writer.writerow(['SUMMARY'])
        writer.writerow([f'Total Gross Pay: GHS {float(payroll_run.gross_pay):,.2f}'])
        writer.writerow([f'Total Deductions: GHS {float(payroll_run.total_deductions):,.2f}'])
        writer.writerow([f'Total Net Pay: GHS {float(payroll_run.net_pay):,.2f}'])
        
        output.seek(0)
        return output.getvalue()
    
    @staticmethod
    def generate_payroll_summary_pdf(payroll_run):
        """Generate payroll summary PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72,
        )
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=colors.HexColor('#1FB256')
        )
        elements.append(Paragraph('Payroll Summary Report', title_style))
        elements.append(Spacer(1, 6))
        
        # Info
        info_style = ParagraphStyle('Info', parent=styles['Normal'], fontSize=10, alignment=TA_CENTER)
        elements.append(Paragraph(f'Run Number: {payroll_run.run_number}', info_style))
        elements.append(Paragraph(f'Period: {payroll_run.period_start} to {payroll_run.period_end}', info_style))
        elements.append(Paragraph(f'Payment Date: {payroll_run.payment_date}', info_style))
        elements.append(Spacer(1, 20))
        
        # Table data
        table_data = [['Emp #', 'Employee Name', 'Dept', 'Gross Pay', 'Deductions', 'Net Pay']]
        
        for line in payroll_run.lines:
            table_data.append([
                line.employee.employee_number,
                line.employee.full_name[:20],
                line.employee.department[:15] if line.employee.department else '-',
                f"{float(line.gross_earnings):,.2f}",
                f"{float(line.total_deductions):,.2f}",
                f"{float(line.net_pay):,.2f}"
            ])
        
        # Summary row
        table_data.append([
            '', '', 'TOTAL',
            f"{float(payroll_run.gross_pay):,.2f}",
            f"{float(payroll_run.total_deductions):,.2f}",
            f"{float(payroll_run.net_pay):,.2f}"
        ])
        
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1FB256')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (3, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E5F2FF')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 20))
        
        # Footer
        footer_text = f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        elements.append(Paragraph(footer_text, styles['Normal']))
        
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()