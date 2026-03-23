# app/services/payroll_service.py
from decimal import Decimal
from datetime import datetime
from app.models import PayrollRun, PayrollLine, Employee, TaxTable
import math

class PayrollService:
    
    @staticmethod
    def calculate_payroll(payroll_run_id):
        """Calculate payroll for all employees in a run"""
        payroll_run = PayrollRun.query.get(payroll_run_id)
        if not payroll_run:
            return None
        
        total_gross = Decimal('0')
        total_deductions = Decimal('0')
        total_net = Decimal('0')
        
        for line in payroll_run.lines:
            employee = Employee.query.get(line.employee_id)
            
            # Calculate gross pay
            gross = line.basic_salary + line.allowances + line.overtime + line.bonus
            
            # Calculate PAYE tax
            paye = PayrollService.calculate_paye(gross, employee)
            
            # Calculate SSNIT (employee contribution - 5.5%)
            ssnit_employee = gross * Decimal('0.055')
            
            # Calculate SSNIT (employer contribution - 13%)
            ssnit_employer = gross * Decimal('0.13')
            
            # Calculate Provident Fund (employee - 5%)
            provident_fund = gross * Decimal('0.05')
            
            # Total deductions
            deductions = paye + ssnit_employee + provident_fund + line.other_deductions
            
            # Net pay
            net = gross - deductions
            
            # Update line
            line.gross_earnings = gross
            line.paye_tax = paye
            line.ssnit_employee = ssnit_employee
            line.ssnit_employer = ssnit_employer
            line.provident_fund = provident_fund
            line.total_deductions = deductions
            line.net_pay = net
            
            total_gross += gross
            total_deductions += deductions
            total_net += net
        
        # Update payroll run totals
        payroll_run.gross_pay = total_gross
        payroll_run.total_deductions = total_deductions
        payroll_run.net_pay = total_net
        
        return payroll_run
    
    @staticmethod
    def calculate_paye(gross, employee):
        """Calculate PAYE tax based on Ghana tax brackets"""
        # Convert to float for calculation
        annual_gross = float(gross) * 12
        
        # Ghana Tax Brackets (as of 2024)
        brackets = [
            (402, 0),           # First 402 GHS: 0%
            (110, 0.05),        # Next 110 GHS: 5%
            (130, 0.10),        # Next 130 GHS: 10%
            (3000, 0.175),      # Next 3000 GHS: 17.5%
            (20000, 0.25),      # Next 20000 GHS: 25%
            (float('inf'), 0.30) # Above 27642 GHS: 30%
        ]
        
        tax = 0
        remaining = annual_gross
        
        for bracket_limit, rate in brackets:
            if remaining <= 0:
                break
            taxable = min(remaining, bracket_limit)
            tax += taxable * rate
            remaining -= bracket_limit
        
        # Return monthly tax
        return Decimal(str(tax / 12))
    
    @staticmethod
    def generate_payslip(payroll_line):
        """Generate payslip data for an employee"""
        return {
            'employee_name': payroll_line.employee.full_name,
            'employee_number': payroll_line.employee.employee_number,
            'position': payroll_line.employee.position,
            'pay_period': {
                'start': payroll_line.payroll_run.period_start.isoformat(),
                'end': payroll_line.payroll_run.period_end.isoformat()
            },
            'earnings': {
                'basic_salary': float(payroll_line.basic_salary),
                'allowances': float(payroll_line.allowances),
                'overtime': float(payroll_line.overtime),
                'bonus': float(payroll_line.bonus),
                'gross_earnings': float(payroll_line.gross_earnings)
            },
            'deductions': {
                'paye_tax': float(payroll_line.paye_tax),
                'ssnit': float(payroll_line.ssnit_employee),
                'provident_fund': float(payroll_line.provident_fund),
                'other_deductions': float(payroll_line.other_deductions),
                'total_deductions': float(payroll_line.total_deductions)
            },
            'net_pay': float(payroll_line.net_pay),
            'payment_date': payroll_line.payroll_run.payment_date.isoformat()
        }