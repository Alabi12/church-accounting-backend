from app.extensions import celery, db, logger
from app.models.transaction import Transaction
from app.models.member import Member
from app.models.budget import Budget
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor, IsolationForest
from sklearn.preprocessing import StandardScaler
from prophet import Prophet
import tensorflow as tf
from datetime import datetime, timedelta
import joblib
import os

class AIService:
    def __init__(self):
        self.model_path = os.environ.get('AI_MODEL_PATH', 'ai_models')
        self.giving_predictor = None
        self.anomaly_detector = None
        self.load_models()
    
    def load_models(self):
        """Load pre-trained models"""
        try:
            # Load giving prediction model
            model_file = os.path.join(self.model_path, 'giving_predictor.pkl')
            if os.path.exists(model_file):
                self.giving_predictor = joblib.load(model_file)
            
            # Load anomaly detection model
            anomaly_file = os.path.join(self.model_path, 'anomaly_detector.pkl')
            if os.path.exists(anomaly_file):
                self.anomaly_detector = joblib.load(anomaly_file)
        except Exception as e:
            logger.error(f"Error loading AI models: {str(e)}")
    
    @celery.task
    def analyze_transaction(self, transaction_id):
        """Analyze transaction for patterns and anomalies"""
        transaction = Transaction.query.get(transaction_id)
        if not transaction:
            return
        
        # Check for anomalies
        is_anomaly = self.detect_anomaly(transaction)
        
        if is_anomaly:
            # Create alert for unusual transaction
            self.create_anomaly_alert(transaction)
        
        # Update member giving pattern
        if transaction.member_id:
            self.update_member_pattern(transaction.member_id)
    
    def detect_anomaly(self, transaction):
        """Detect if transaction is anomalous"""
        if not self.anomaly_detector:
            return False
        
        # Prepare features
        features = self.prepare_anomaly_features(transaction)
        
        # Predict anomaly
        prediction = self.anomaly_detector.predict([features])
        return prediction[0] == -1  # -1 indicates anomaly in Isolation Forest
    
    def prepare_anomaly_features(self, transaction):
        """Prepare features for anomaly detection"""
        # Get historical data for this category
        historical = Transaction.query.filter_by(
            church_id=transaction.church_id,
            category=transaction.category,
            transaction_type=transaction.transaction_type
        ).all()
        
        if len(historical) < 10:
            return [0] * 10  # Not enough data
        
        amounts = [t.amount for t in historical]
        
        features = [
            float(transaction.amount),
            float(np.mean(amounts)),
            float(np.std(amounts)),
            (float(transaction.amount) - float(np.mean(amounts))) / (float(np.std(amounts)) + 1),
            transaction.transaction_date.hour,
            transaction.transaction_date.weekday(),
            transaction.transaction_date.day,
            transaction.transaction_date.month,
            1 if transaction.payment_method == 'CASH' else 0,
            1 if transaction.member_id else 0
        ]
        
        return features
    
    @celery.task
    def predict_giving_patterns(self, church_id, period='month'):
        """Predict future giving patterns"""
        try:
            # Get historical giving data
            transactions = Transaction.query.filter_by(
                church_id=church_id,
                transaction_type='INCOME',
                status='COMPLETED'
            ).order_by(Transaction.transaction_date).all()
            
            if len(transactions) < 30:
                return {'error': 'Insufficient data for predictions'}
            
            # Prepare data for Prophet
            df = pd.DataFrame([
                {
                    'ds': t.transaction_date,
                    'y': float(t.amount)
                }
                for t in transactions
            ])
            
            # Train Prophet model
            model = Prophet(
                yearly_seasonality=True,
                weekly_seasonality=True,
                daily_seasonality=False
            )
            model.fit(df)
            
            # Make future predictions
            future = model.make_future_dataframe(periods=30)
            forecast = model.predict(future)
            
            # Get predictions for next period
            predictions = forecast.tail(30)[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].to_dict('records')
            
            return {
                'predictions': [
                    {
                        'date': p['ds'].isoformat(),
                        'predicted': float(p['yhat']),
                        'lower_bound': float(p['yhat_lower']),
                        'upper_bound': float(p['yhat_upper'])
                    }
                    for p in predictions
                ],
                'trend': self.analyze_trend(forecast),
                'seasonality': self.get_seasonality_patterns(model)
            }
            
        except Exception as e:
            logger.error(f"Error in prediction: {str(e)}")
            return {'error': str(e)}
    
    def analyze_trend(self, forecast):
        """Analyze trend direction and strength"""
        recent = forecast.tail(7)['yhat'].values
        previous = forecast.tail(14).head(7)['yhat'].values
        
        if len(recent) == 0 or len(previous) == 0:
            return 'stable'
        
        recent_avg = np.mean(recent)
        previous_avg = np.mean(previous)
        
        change = ((recent_avg - previous_avg) / previous_avg) * 100
        
        if change > 5:
            return 'increasing'
        elif change < -5:
            return 'decreasing'
        else:
            return 'stable'
    
    def get_seasonality_patterns(self, model):
        """Extract seasonality patterns"""
        patterns = {}
        
        # Check if model has seasonality components
        if hasattr(model, 'seasonalities'):
            for name, seasonality in model.seasonalities.items():
                patterns[name] = {
                    'period': seasonality['period'],
                    'fourier_order': seasonality['fourier_order']
                }
        
        return patterns
    
    @celery.task
    def optimize_budget(self, budget_id):
        """AI-powered budget optimization"""
        budget = Budget.query.get(budget_id)
        if not budget:
            return
        
        # Get historical spending patterns
        historical = Transaction.query.filter(
            Transaction.church_id == budget.church_id,
            Transaction.transaction_date >= budget.start_date - timedelta(days=365),
            Transaction.transaction_date < budget.start_date
        ).all()
        
        if not historical:
            return
        
        # Analyze spending by category
        df = pd.DataFrame([
            {
                'category': t.category,
                'amount': float(t.amount),
                'month': t.transaction_date.month
            }
            for t in historical
        ])
        
        # Calculate optimal allocations
        category_totals = df.groupby('category')['amount'].sum()
        total_spent = category_totals.sum()
        
        recommendations = []
        for category, amount in category_totals.items():
            percentage = (amount / total_spent) * 100
            
            # Find budget item for this category
            budget_item = next(
                (item for item in budget.items if item.account.name == category),
                None
            )
            
            if budget_item:
                current_percentage = (budget_item.budget_amount / budget.total_budget) * 100
                
                if abs(percentage - current_percentage) > 5:
                    recommendations.append({
                        'category': category,
                        'current_allocation': float(budget_item.budget_amount),
                        'recommended_allocation': float(total_spent * (percentage / 100)),
                        'current_percentage': float(current_percentage),
                        'recommended_percentage': float(percentage),
                        'reason': f'Historical spending suggests {percentage:.1f}% allocation'
                    })
        
        return recommendations
    
    @celery.task
    def detect_anomalies_task(self):
        """Background task to detect anomalies"""
        # Get recent transactions
        recent = Transaction.query.filter(
            Transaction.created_at >= datetime.utcnow() - timedelta(days=1)
        ).all()
        
        anomalies = []
        for transaction in recent:
            if self.detect_anomaly(transaction):
                anomalies.append(transaction.id)
                self.create_anomaly_alert(transaction)
        
        logger.info(f"Detected {len(anomalies)} anomalies in last 24 hours")
        return anomalies
    
    def create_anomaly_alert(self, transaction):
        """Create alert for anomalous transaction"""
        from app.models.alert import Alert
        
        alert = Alert(
            church_id=transaction.church_id,
            type='ANOMALY',
            severity='MEDIUM',
            title='Unusual Transaction Detected',
            description=f'Transaction {transaction.transaction_number} for ${transaction.amount} is unusual compared to historical patterns.',
            transaction_id=transaction.id,
            created_at=datetime.utcnow()
        )
        
        db.session.add(alert)
        db.session.commit()
    
    def update_member_pattern(self, member_id):
        """Update member giving pattern"""
        member = Member.query.get(member_id)
        if not member:
            return
        
        # Get member's giving history
        transactions = Transaction.query.filter_by(
            member_id=member_id,
            transaction_type='INCOME'
        ).order_by(Transaction.transaction_date).all()
        
        if len(transactions) < 5:
            return
        
        # Calculate patterns
        amounts = [t.amount for t in transactions]
        dates = [t.transaction_date for t in transactions]
        
        # Calculate average and frequency
        avg_amount = np.mean(amounts)
        total_given = np.sum(amounts)
        
        # Calculate giving frequency (days between gifts)
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
        avg_interval = np.mean(intervals) if intervals else 0
        
        # Predict next gift
        next_gift_date = None
        if avg_interval > 0:
            next_gift_date = dates[-1] + timedelta(days=avg_interval)
        
        # Store pattern (you might want to add these fields to Member model)
        member.giving_pattern = {
            'average_amount': float(avg_amount),
            'total_given': float(total_given),
            'average_interval_days': float(avg_interval),
            'next_expected_gift': next_gift_date.isoformat() if next_gift_date else None,
            'consistency_score': self.calculate_consistency(amounts, intervals)
        }
        
        db.session.commit()
    
    def calculate_consistency(self, amounts, intervals):
        """Calculate giving consistency score (0-100)"""
        if not amounts or not intervals:
            return 0
        
        # Calculate coefficient of variation for amounts
        amount_cv = np.std(amounts) / np.mean(amounts) if np.mean(amounts) > 0 else 1
        
        # Calculate coefficient of variation for intervals
        interval_cv = np.std(intervals) / np.mean(intervals) if np.mean(intervals) > 0 else 1
        
        # Lower CV means more consistent
        amount_score = max(0, 100 - (amount_cv * 50))
        interval_score = max(0, 100 - (interval_cv * 50))
        
        # Weighted average
        consistency = (amount_score * 0.4) + (interval_score * 0.6)
        
        return min(100, max(0, consistency))