# app/models/budget_comment.py
from app.extensions import db
from datetime import datetime

class BudgetComment(db.Model):
    __tablename__ = 'budget_comments'
    
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('budgets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships - make sure these are defined
    user = db.relationship('User', backref='budget_comments')
    # The budget relationship might be defined on the other side
    
    def to_dict(self):
        return {
            'id': self.id,
            'budget_id': self.budget_id,
            'user_id': self.user_id,
            'user_name': self.user.full_name if self.user else 'Unknown',
            'comment': self.comment,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }