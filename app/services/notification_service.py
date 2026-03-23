# app/services/notification_service.py
from flask_socketio import emit
import logging

logger = logging.getLogger(__name__)

class NotificationService:
    
    @staticmethod
    def notify_payroll_submitted(payroll_run):
        """Notify treasurer that payroll is ready for review"""
        try:
            emit('payroll_submitted', {
                'run_id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'amount': float(payroll_run.net_pay),
                'message': f'Payroll run {payroll_run.run_number} is ready for review'
            }, broadcast=True)
            logger.info(f"Notification sent for payroll run {payroll_run.run_number}")
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_payroll_approved(payroll_run):
        """Notify accountant that payroll is approved"""
        try:
            emit('payroll_approved', {
                'run_id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'message': f'Payroll run {payroll_run.run_number} has been approved'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_payroll_processed(payroll_run):
        """Notify treasurer that payroll is processed"""
        try:
            emit('payroll_processed', {
                'run_id': payroll_run.id,
                'run_number': payroll_run.run_number,
                'message': f'Payroll run {payroll_run.run_number} has been processed. Proof uploaded for verification.'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_leave_request_submitted(leave_request):
        """Notify admin of new leave request"""
        try:
            emit('leave_request_submitted', {
                'request_id': leave_request.id,
                'employee_name': leave_request.employee.full_name,
                'days': leave_request.days_requested,
                'message': f'Leave request from {leave_request.employee.full_name} needs review'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_leave_recommended(leave_request):
        """Notify pastor of recommended leave"""
        try:
            emit('leave_recommended', {
                'request_id': leave_request.id,
                'employee_name': leave_request.employee.full_name,
                'message': f'Leave request for {leave_request.employee.full_name} is recommended for approval'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_leave_approved(leave_request):
        """Notify employee of leave approval"""
        try:
            emit('leave_approved', {
                'request_id': leave_request.id,
                'employee_id': leave_request.employee_id,
                'message': f'Your leave request has been approved'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    @staticmethod
    def notify_leave_allowance_processed(leave_request):
        """Notify employee of leave allowance processing"""
        try:
            emit('leave_allowance_processed', {
                'request_id': leave_request.id,
                'employee_id': leave_request.employee_id,
                'amount': float(leave_request.allowance_amount),
                'message': f'Your leave allowance of GHS {float(leave_request.allowance_amount):,.2f} has been processed'
            }, broadcast=True)
        except Exception as e:
            logger.error(f"Error sending notification: {e}")