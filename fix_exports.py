import re

# Read the accounting_routes.py file
with open('app/routes/accounting_routes.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find and remove all existing export_as_csv and export_as_pdf functions
# We'll replace them with a single clean version

# Pattern to match export_as_csv function
csv_pattern = r'def export_as_csv\(.*?\):.*?(?=\ndef export_as_pdf|\Z)'
pdf_pattern = r'def export_as_pdf\(.*?\):.*?(?=\ndef |\Z)'

# Remove existing functions
content = re.sub(csv_pattern, '', content, flags=re.DOTALL)
content = re.sub(pdf_pattern, '', content, flags=re.DOTALL)

# Add new complete export functions at the end
new_exports = '''
# ==================== COMPLETE EXPORT FUNCTIONS ====================

def export_as_csv(statement_data, statement_type, start_date, end_date):
    """Export statement as CSV - Handles all statement types"""
    import csv
    import io
    from flask import make_response
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([f"{statement_type.upper()} STATEMENT"])
    writer.writerow([f"Period: {start_date} to {end_date}"])
    writer.writerow([])
    
    if statement_type == 'income':
        # Income section
        writer.writerow(['INCOME'])
        writer.writerow(['Category', 'Account', 'Amount (GHS)'])
        
        for category, cat_data in statement_data.get('revenue', {}).get('categories', {}).items():
            for account in cat_data.get('accounts', []):
                writer.writerow([category, f"{account.get('code', '')} - {account.get('name', '')}", f"{account.get('amount', 0):,.2f}"])
            writer.writerow([f"Total {category}", '', f"{cat_data.get('total', 0):,.2f}"])
            writer.writerow([])
        
        writer.writerow(['TOTAL INCOME', '', f"{statement_data.get('revenue', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Expenses section
        writer.writerow(['EXPENSES'])
        writer.writerow(['Category', 'Account', 'Amount (GHS)'])
        
        for category, cat_data in statement_data.get('expenses', {}).get('categories', {}).items():
            for account in cat_data.get('accounts', []):
                writer.writerow([category, f"{account.get('code', '')} - {account.get('name', '')}", f"{account.get('amount', 0):,.2f}"])
            writer.writerow([f"Total {category}", '', f"{cat_data.get('total', 0):,.2f}"])
            writer.writerow([])
        
        writer.writerow(['TOTAL EXPENSES', '', f"{statement_data.get('expenses', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        writer.writerow(['NET INCOME', '', f"{statement_data.get('net_income', 0):,.2f}"])
        
    elif statement_type == 'balance':
        # Assets
        writer.writerow(['ASSETS'])
        writer.writerow(['Account', 'Amount (GHS)'])
        
        for asset in statement_data.get('assets', {}).get('current', []):
            writer.writerow([f"Current - {asset.get('code', '')} {asset.get('name', '')}", f"{asset.get('amount', 0):,.2f}"])
        for asset in statement_data.get('assets', {}).get('fixed', []):
            writer.writerow([f"Fixed - {asset.get('code', '')} {asset.get('name', '')}", f"{asset.get('amount', 0):,.2f}"])
        writer.writerow(['TOTAL ASSETS', f"{statement_data.get('assets', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Liabilities
        writer.writerow(['LIABILITIES'])
        writer.writerow(['Account', 'Amount (GHS)'])
        
        for liability in statement_data.get('liabilities', {}).get('current', []):
            writer.writerow([f"Current - {liability.get('code', '')} {liability.get('name', '')}", f"{liability.get('amount', 0):,.2f}"])
        for liability in statement_data.get('liabilities', {}).get('longTerm', []):
            writer.writerow([f"Long-term - {liability.get('code', '')} {liability.get('name', '')}", f"{liability.get('amount', 0):,.2f}"])
        writer.writerow(['TOTAL LIABILITIES', f"{statement_data.get('liabilities', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Equity
        writer.writerow(['EQUITY'])
        writer.writerow(['Account', 'Amount (GHS)'])
        
        for equity in statement_data.get('equity', {}).get('accounts', []):
            writer.writerow([f"{equity.get('code', '')} - {equity.get('name', '')}", f"{equity.get('amount', 0):,.2f}"])
        writer.writerow(['TOTAL EQUITY', f"{statement_data.get('equity', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        writer.writerow(['TOTAL LIABILITIES & EQUITY', f"{statement_data.get('liabilities', {}).get('total', 0) + statement_data.get('equity', {}).get('total', 0):,.2f}"])
        
    elif statement_type == 'receipt-payment':
        # Opening Balances
        writer.writerow(['OPENING BALANCES'])
        writer.writerow(['Account Name', 'Amount (GHS)'])
        
        for acc in statement_data.get('openingBalances', {}).get('cashAccounts', []):
            writer.writerow([f"Cash - {acc.get('name', '')}", f"{acc.get('openingBalance', 0):,.2f}"])
        for acc in statement_data.get('openingBalances', {}).get('bankAccounts', []):
            writer.writerow([f"Bank - {acc.get('name', '')}", f"{acc.get('openingBalance', 0):,.2f}"])
        writer.writerow(['TOTAL OPENING BALANCE', f"{statement_data.get('openingBalances', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Receipts
        writer.writerow(['RECEIPTS'])
        writer.writerow(['Category', 'Date', 'Description', 'Amount (GHS)'])
        
        for category, cat_data in statement_data.get('receipts', {}).get('categories', {}).items():
            for item in cat_data.get('items', []):
                writer.writerow([category, item.get('date', ''), item.get('description', ''), f"{item.get('amount', 0):,.2f}"])
            writer.writerow([f"Total {category}", '', '', f"{cat_data.get('total', 0):,.2f}"])
        
        writer.writerow(['TOTAL RECEIPTS', '', '', f"{statement_data.get('receipts', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Payments
        writer.writerow(['PAYMENTS'])
        writer.writerow(['Category', 'Date', 'Description', 'Amount (GHS)'])
        
        for category, cat_data in statement_data.get('payments', {}).get('categories', {}).items():
            for item in cat_data.get('items', []):
                writer.writerow([category, item.get('date', ''), item.get('description', ''), f"{item.get('amount', 0):,.2f}"])
            writer.writerow([f"Total {category}", '', '', f"{cat_data.get('total', 0):,.2f}"])
        
        writer.writerow(['TOTAL PAYMENTS', '', '', f"{statement_data.get('payments', {}).get('total', 0):,.2f}"])
        writer.writerow([])
        
        # Summary
        net_cash_flow = statement_data.get('receipts', {}).get('total', 0) - statement_data.get('payments', {}).get('total', 0)
        writer.writerow(['SUMMARY'])
        writer.writerow(['Net Cash Flow', f"{net_cash_flow:,.2f}"])
        writer.writerow(['Closing Balance', f"{statement_data.get('closingBalances', {}).get('total', 0):,.2f}"])
        
    elif statement_type == 'cashflow':
        # Operating Activities
        writer.writerow(['CASH FLOW FROM OPERATING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        
        for item in statement_data.get('operating', {}).get('items', []):
            writer.writerow([item.get('description', ''), f"{item.get('amount', 0):,.2f}"])
        writer.writerow(['Net Cash from Operating Activities', f"{statement_data.get('operating', {}).get('net', 0):,.2f}"])
        writer.writerow([])
        
        # Investing Activities
        writer.writerow(['CASH FLOW FROM INVESTING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        
        for item in statement_data.get('investing', {}).get('items', []):
            writer.writerow([item.get('description', ''), f"{item.get('amount', 0):,.2f}"])
        writer.writerow(['Net Cash from Investing Activities', f"{statement_data.get('investing', {}).get('net', 0):,.2f}"])
        writer.writerow([])
        
        # Financing Activities
        writer.writerow(['CASH FLOW FROM FINANCING ACTIVITIES'])
        writer.writerow(['Description', 'Amount (GHS)'])
        
        for item in statement_data.get('financing', {}).get('items', []):
            writer.writerow([item.get('description', ''), f"{item.get('amount', 0):,.2f}"])
        writer.writerow(['Net Cash from Financing Activities', f"{statement_data.get('financing', {}).get('net', 0):,.2f}"])
        writer.writerow([])
        
        # Summary
        writer.writerow(['NET INCREASE/(DECREASE) IN CASH', f"{statement_data.get('netIncrease', 0):,.2f}"])
        writer.writerow(['Cash at Beginning of Period', f"{statement_data.get('beginningCash', 0):,.2f}"])
        writer.writerow(['Cash at End of Period', f"{statement_data.get('endingCash', 0):,.2f}"])
    
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = f'attachment; filename={statement_type}_statement_{start_date}_to_{end_date}.csv'
    
    return response


def export_as_pdf(statement_data, statement_type, start_date, end_date):
    """Export statement as PDF - Handles all statement types"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from io import BytesIO
        from datetime import datetime
        from flask import make_response
        
        buffer = BytesIO()
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
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=12,
            textColor=colors.HexColor('#1FB256')
        )
        
        elements.append(Paragraph(f'{statement_type.upper()} STATEMENT', title_style))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(f'Period: {start_date} to {end_date}', styles['Normal']))
        elements.append(Spacer(1, 20))
        
        if statement_type == 'income':
            # Income section
            income_data = [['Category', 'Account', 'Amount (GHS)']]
            for category, cat_data in statement_data.get('revenue', {}).get('categories', {}).items():
                for account in cat_data.get('accounts', []):
                    income_data.append([category, f"{account.get('code', '')} - {account.get('name', '')}", f"{account.get('amount', 0):,.2f}"])
                income_data.append([f"Total {category}", '', f"{cat_data.get('total', 0):,.2f}"])
            
            table = Table(income_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 20))
            
            # Expenses section
            expenses_data = [['Category', 'Account', 'Amount (GHS)']]
            for category, cat_data in statement_data.get('expenses', {}).get('categories', {}).items():
                for account in cat_data.get('accounts', []):
                    expenses_data.append([category, f"{account.get('code', '')} - {account.get('name', '')}", f"{account.get('amount', 0):,.2f}"])
                expenses_data.append([f"Total {category}", '', f"{cat_data.get('total', 0):,.2f}"])
            
            table = Table(expenses_data, repeatRows=1)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dc3545')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 20))
            
            # Net Income
            net_income_data = [['NET INCOME', f"{statement_data.get('net_income', 0):,.2f}"]]
            table = Table(net_income_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007bff')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            
        elif statement_type == 'balance':
            # Assets
            assets_data = [['ASSETS', 'Amount (GHS)']]
            for asset in statement_data.get('assets', {}).get('current', []):
                assets_data.append([f"Current - {asset.get('code', '')} {asset.get('name', '')}", f"{asset.get('amount', 0):,.2f}"])
            for asset in statement_data.get('assets', {}).get('fixed', []):
                assets_data.append([f"Fixed - {asset.get('code', '')} {asset.get('name', '')}", f"{asset.get('amount', 0):,.2f}"])
            assets_data.append(['TOTAL ASSETS', f"{statement_data.get('assets', {}).get('total', 0):,.2f}"])
            
            table = Table(assets_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#007bff')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 20))
            
            # Liabilities
            liabilities_data = [['LIABILITIES', 'Amount (GHS)']]
            for liability in statement_data.get('liabilities', {}).get('current', []):
                liabilities_data.append([f"Current - {liability.get('code', '')} {liability.get('name', '')}", f"{liability.get('amount', 0):,.2f}"])
            for liability in statement_data.get('liabilities', {}).get('longTerm', []):
                liabilities_data.append([f"Long-term - {liability.get('code', '')} {liability.get('name', '')}", f"{liability.get('amount', 0):,.2f}"])
            liabilities_data.append(['TOTAL LIABILITIES', f"{statement_data.get('liabilities', {}).get('total', 0):,.2f}"])
            
            table = Table(liabilities_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fd7e14')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 20))
            
            # Equity
            equity_data = [['EQUITY', 'Amount (GHS)']]
            for equity in statement_data.get('equity', {}).get('accounts', []):
                equity_data.append([f"{equity.get('code', '')} - {equity.get('name', '')}", f"{equity.get('amount', 0):,.2f}"])
            equity_data.append(['TOTAL EQUITY', f"{statement_data.get('equity', {}).get('total', 0):,.2f}"])
            
            table = Table(equity_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6f42c1')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
            elements.append(Spacer(1, 20))
            
            # Total
            total_data = [['TOTAL LIABILITIES & EQUITY', f"{statement_data.get('liabilities', {}).get('total', 0) + statement_data.get('equity', {}).get('total', 0):,.2f}"]]
            table = Table(total_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ]))
            elements.append(table)
        
        doc.build(elements)
        
        pdf = buffer.getvalue()
        buffer.close()
        
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={statement_type}_statement_{start_date}_to_{end_date}.pdf'
        
        return response
        
    except ImportError as e:
        from flask import make_response
        response = make_response("PDF export requires reportlab. Please install: pip install reportlab")
        response.headers['Content-Type'] = 'text/plain'
        return response
    except Exception as e:
        from flask import make_response
        response = make_response(f"Error generating PDF: {str(e)}")
        response.headers['Content-Type'] = 'text/plain'
        return response
'''

# Append the new functions
content += new_exports

# Write back the file
with open('app/routes/accounting_routes.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ Updated export functions successfully!")
