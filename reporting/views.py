from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from datetime import datetime, timedelta
import json
import threading
import os
from django.conf import settings

from .models import Report, GeneratedReport
from .services import ReportDataAggregator, ExcelReportGenerator, PDFReportGenerator


@login_required
def report_dashboard(request):
    """Simple dashboard for report generation"""
    return render(request, 'reporting/simple_dashboard.html')


@login_required
def generate_report(request):
    """Generate report based on form data"""
    if request.method == 'POST':
        try:
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            output_format = request.POST.get('output_format', 'excel')
            report_type = 'daily_slaughter'  # Default report type since all are the same
            
            # Convert string dates to date objects
            from datetime import datetime
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            # Generate report data
            aggregator = ReportDataAggregator(start_date_obj, end_date_obj)
            report_data = aggregator.get_all_data()
            
            # Debug: Print report data to console
            print(f"DEBUG: Report data for {start_date} to {end_date}:")
            print(f"Daily data count: {len(report_data.get('daily_data', []))}")
            print(f"Summary data: {report_data.get('summary', {})}")
            
            # If no data found, still generate the report but it will be empty
            if not report_data.get('daily_data'):
                print("DEBUG: No data found for the selected date range - generating empty report")
            
            if output_format == 'excel':
                # Generate Excel report
                excel_generator = ExcelReportGenerator(report_data)
                workbook = excel_generator.generate_daily_slaughter_excel()
                
                # Save to temporary file
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                    workbook.save(tmp_file.name)
                    
                    # Read file and return as response
                    with open(tmp_file.name, 'rb') as f:
                        response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                        response['Content-Disposition'] = f'attachment; filename="report_{start_date}_to_{end_date}.xlsx"'
                        
                    # Clean up
                    os.unlink(tmp_file.name)
                    return response
            elif output_format == 'pdf':
                # Generate PDF report
                pdf_generator = PDFReportGenerator(report_data)
                pdf_path = pdf_generator.generate_daily_slaughter_pdf()
                
                # Read file and return as response
                with open(pdf_path, 'rb') as f:
                    response = HttpResponse(f.read(), content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="report_{start_date}_to_{end_date}.pdf"'
                    
                # Clean up
                os.unlink(pdf_path)
                return response
            else:
                return HttpResponse("Invalid output format. Please select Excel or PDF.", status=400)
                
        except Exception as e:
            return HttpResponse(f"Error generating report: {str(e)}", status=500)
    
    return HttpResponse("Method not allowed", status=405)


@csrf_exempt
@require_http_methods(["POST"])
def generate_daily_reports_api(request):
    """API endpoint for Google Scheduler to trigger daily report generation"""
    try:
        # Parse request body
        data = json.loads(request.body)
        report_types = data.get('report_types', ['daily_slaughter'])
        output_format = data.get('output_format', 'excel')
        system_user = data.get('system_user', 'system')
        
        # Run management command in background
        def run_command():
            try:
                call_command(
                    'generate_daily_reports',
                    report_types=report_types,
                    output_format=output_format,
                    system_user=system_user
                )
            except CommandError as e:
                # Log error for monitoring
                print(f"Daily report generation failed: {e}")
        
        # Start background thread
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()
        
        return JsonResponse({
            'status': 'success',
            'message': 'Daily report generation started',
            'report_types': report_types
        })
        
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
def test_report_generation(request):
    """Test view for report generation (for development/testing)"""
    if request.method == 'POST':
        try:
            # Get yesterday's date
            yesterday = (timezone.now() - timedelta(days=1)).date()
            
            # Generate report data
            aggregator = ReportDataAggregator(yesterday, yesterday)
            report_data = aggregator.get_all_data()
            
            # Generate Excel
            excel_generator = ExcelReportGenerator(report_data)
            workbook = excel_generator.generate_daily_slaughter_excel()
            
            # Save to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                workbook.save(tmp_file.name)
                
                # Read file and return as response
                with open(tmp_file.name, 'rb') as f:
                    response = HttpResponse(f.read(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    response['Content-Disposition'] = f'attachment; filename="test_report_{yesterday}.xlsx"'
                    
                # Clean up
                os.unlink(tmp_file.name)
                return response
                
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=500)
    
    return render(request, 'reporting/test_report.html')


@login_required
def report_list(request):
    """List all generated reports"""
    reports = GeneratedReport.objects.all().order_by('-generated_at')
    context = {
        'reports': reports
    }
    return render(request, 'reporting/report_list.html', context)
