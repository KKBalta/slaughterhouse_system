from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.views.generic import View, ListView, DetailView
from django.http import HttpResponse, JsonResponse, FileResponse
from django.contrib import messages
from django.utils.translation import gettext as _
from django.urls import reverse
from django.core.files.storage import default_storage
import os

from processing.models import Animal
from .models import AnimalLabel, LabelTemplate
from .utils import (
    create_animal_label, get_animal_label_download_data, generate_tspl_prn_label, 
    generate_pdf_label, generate_bat_file_content, generate_enhanced_printer_config_bat,
    create_printer_troubleshooting_guide
)

class AnimalLabelListView(LoginRequiredMixin, ListView):
    """List all animal labels for a specific animal."""
    model = AnimalLabel
    template_name = 'labeling/animal_label_list.html'
    context_object_name = 'labels'
    
    def get_queryset(self):
        animal_id = self.kwargs.get('animal_id')
        return AnimalLabel.objects.filter(animal_id=animal_id).order_by('-print_date')
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        animal_id = self.kwargs.get('animal_id')
        context['animal'] = get_object_or_404(Animal, id=animal_id)
        return context

class GenerateAnimalLabelView(LoginRequiredMixin, View):
    """Generate and create a new animal label with PRN and BAT file support."""
    
    def post(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        label_type = request.POST.get('label_type', 'hot_carcass')
        
        # Check if animal has been slaughtered for hot carcass labels
        if label_type == 'hot_carcass' and animal.status not in ['slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']:
            messages.error(request, _('Hot carcass labels can only be generated for slaughtered animals.'))
            return redirect('processing:animal_detail', pk=animal.pk)
        
        try:
            # Create the label with default printer settings
            animal_label = create_animal_label(
                animal=animal,
                label_type=label_type,
                user=request.user
            )

            messages.success(request, _('PRN label and BAT file generated successfully! You can now download and print the label.'))
            return redirect('labeling:animal_label_detail', pk=animal_label.pk)
            
        except Exception as e:
            messages.error(request, _('Error generating label: %(error)s') % {'error': str(e)})
            return redirect('processing:animal_detail', pk=animal.pk)

class AnimalLabelDetailView(LoginRequiredMixin, DetailView):
    """Display details of a specific animal label."""
    model = AnimalLabel
    template_name = 'labeling/animal_label_detail.html'
    context_object_name = 'label'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['animal'] = self.object.animal
        return context

class DownloadAnimalLabelView(LoginRequiredMixin, View):
    """Download animal label in BAT, PRN, or PDF format with enhanced options."""
    
    def get(self, request, label_id, format_type='bat'):
        animal_label = get_object_or_404(AnimalLabel, id=label_id)
        
        # Check for enhanced BAT file request
        enhanced = request.GET.get('enhanced', 'false').lower() == 'true'
        printer_type = request.GET.get('printer_type', 'tsc')
        
        try:
            if format_type.lower() == 'bat' and enhanced:
                # Generate enhanced BAT file with multiple printer support
                prn_content = animal_label.prn_content
                enhanced_bat_content = generate_enhanced_printer_config_bat(prn_content)
                
                filename = f"enhanced_print_label_{animal_label.animal.identification_tag}_{animal_label.label_type}.bat"
                response = HttpResponse(
                    enhanced_bat_content,
                    content_type='application/octet-stream'
                )
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                return response
                
            else:
                # Use standard download method
                download_data = get_animal_label_download_data(animal_label, format_type)
                
                if format_type.lower() in ['bat', 'prn']:
                    # Return BAT or PRN content as downloadable file
                    response = HttpResponse(
                        download_data['content'],
                        content_type=download_data['content_type']
                    )
                    response['Content-Disposition'] = f'attachment; filename="{download_data["filename"]}"'
                    return response
                    
                elif format_type.lower() == 'pdf':
                    # Return PDF file
                    if animal_label.pdf_file and default_storage.exists(animal_label.pdf_file.name):
                        response = FileResponse(
                            default_storage.open(animal_label.pdf_file.name, 'rb'),
                            content_type=download_data['content_type']
                        )
                        response['Content-Disposition'] = f'attachment; filename="{download_data["filename"]}"'
                        return response
                    else:
                        messages.error(request, _('PDF file not found.'))
                        return redirect('labeling:animal_label_detail', pk=label_id)
                    
        except Exception as e:
            messages.error(request, _('Error downloading label: %(error)s') % {'error': str(e)})
            return redirect('labeling:animal_label_detail', pk=label_id)

class PreviewAnimalLabelView(LoginRequiredMixin, View):
    """Preview animal label without creating a permanent record."""
    
    def get(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        label_type = request.GET.get('label_type', 'hot_carcass')
        format_type = request.GET.get('format', 'prn')
        
        try:
            if format_type.lower() in ['bat', 'prn']:
                prn_content = generate_tspl_prn_label(animal, label_type)
                return HttpResponse(prn_content, content_type='text/plain')
            elif format_type.lower() == 'pdf':
                
                pdf_buffer = generate_pdf_label(animal, label_type)
                response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="preview_{animal.identification_tag}_{label_type}.pdf"'
                return response
            else:
                return JsonResponse({'error': 'Unsupported format'}, status=400)
                
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

class BatchGenerateLabelsView(LoginRequiredMixin, View):
    """Generate labels for multiple animals in a slaughter order."""
    
    def post(self, request, order_id):
        from reception.models import SlaughterOrder
        
        order = get_object_or_404(SlaughterOrder, id=order_id)
        label_type = request.POST.get('label_type', 'hot_carcass')
        animal_ids = request.POST.getlist('animal_ids')
        
        if not animal_ids:
            messages.error(request, _('Please select at least one animal.'))
            return redirect('reception:slaughter_order_detail', pk=order_id)
        
        created_labels = []
        errors = []
        
        for animal_id in animal_ids:
            try:
                animal = Animal.objects.get(id=animal_id, slaughter_order=order)
                
                # Check if label already exists
                existing_label = AnimalLabel.objects.filter(
                    animal=animal,
                    label_type=label_type
                ).first()
                
                if existing_label:
                    created_labels.append(existing_label)
                else:
                    # Create new label
                    animal_label = create_animal_label(
                        animal=animal,
                        label_type=label_type,
                        user=request.user
                    )
                    created_labels.append(animal_label)
                    
            except Animal.DoesNotExist:
                errors.append(f"Animal {animal_id} not found")
            except Exception as e:
                errors.append(f"Error creating label for animal {animal_id}: {str(e)}")
        
        if created_labels:
            messages.success(request, _('Successfully generated %(count)s labels.') % {'count': len(created_labels)})
        
        if errors:
            messages.warning(request, _('Some errors occurred: %(errors)s') % {'errors': '; '.join(errors)})
        
        return redirect('reception:slaughter_order_detail', pk=order_id)

@login_required
def delete_animal_label(request, label_id):
    """Delete an animal label."""
    animal_label = get_object_or_404(AnimalLabel, id=label_id)
    animal_id = animal_label.animal.id
    
    try:
        # Delete PDF file if it exists
        if animal_label.pdf_file:
            if default_storage.exists(animal_label.pdf_file.name):
                default_storage.delete(animal_label.pdf_file.name)
        
        animal_label.delete()
        messages.success(request, _('Label deleted successfully.'))
        
    except Exception as e:
        messages.error(request, _('Error deleting label: %(error)s') % {'error': str(e)})
    
    return redirect('processing:animal_detail', pk=animal_id)

class LabelTemplateListView(LoginRequiredMixin, ListView):
    """List all available label templates."""
    model = LabelTemplate
    template_name = 'labeling/label_template_list.html'
    context_object_name = 'templates'
    
    def get_queryset(self):
        return LabelTemplate.objects.filter(target_item_type='animal')

class LabelTemplateDetailView(LoginRequiredMixin, DetailView):
    """Display details of a label template."""
    model = LabelTemplate
    template_name = 'labeling/label_template_detail.html'
    context_object_name = 'template'

class TestPRNGenerationView(LoginRequiredMixin, View):
    """Test view for PRN generation - for development/testing purposes."""
    
    def get(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        
        try:
            from .utils import generate_animal_label_data
            
            # Generate label data
            label_data = generate_animal_label_data(animal)
            
            # Generate PRN content
            prn_content = generate_tspl_prn_label(animal)
            
            # Generate dynamic filename for test
            test_filename = f"test_animal_label_{animal.identification_tag}.prn"
            
            # Generate BAT content
            bat_content = generate_bat_file_content(prn_content, filename=test_filename)
            
            # Create response with debug info
            debug_info = f"""
=== PRN GENERATION TEST ===
Animal: {animal}
Label Data Fields: {list(label_data.keys())}

Key Values:
- bowels_status: {label_data.get('bowels_status', 'N/A')}
- siparis_no (Process No): {label_data.get('siparis_no', 'N/A')}
- kupe_no: {label_data.get('kupe_no', 'N/A')}
- uretici: {label_data.get('uretici', 'N/A')}
- kesim_tarihi: {label_data.get('kesim_tarihi', 'N/A')}

PRN Content Length: {len(prn_content)} characters
BAT Content Length: {len(bat_content)} characters

Checks:
- Contains 'Proses No': {'Proses No' in prn_content}
- Contains 'İşletme No': {'İşletme No' in prn_content}
- Contains bowels_status value: {str(label_data.get('bowels_status', '')) in prn_content}
- Contains siparis_no value: {str(label_data.get('siparis_no', '')) in prn_content}

=== PRN CONTENT (First 1000 chars) ===
{prn_content[:1000]}
...

=== BAT CONTENT (First 500 chars) ===
{bat_content[:500]}
...
"""
            
            return HttpResponse(debug_info, content_type='text/plain')
            
        except Exception as e:
            import traceback
            error_info = f"Error: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            return HttpResponse(error_info, content_type='text/plain')

class DownloadTroubleshootingGuideView(LoginRequiredMixin, View):
    """Download printer troubleshooting guide."""
    
    def get(self, request):
        guide_content = create_printer_troubleshooting_guide()
        
        response = HttpResponse(
            guide_content,
            content_type='text/plain'
        )
        response['Content-Disposition'] = 'attachment; filename="carnitrack_printer_troubleshooting_guide.txt"'
        return response

class TestEnhancedBatView(LoginRequiredMixin, View):
    """Test the enhanced BAT file generation for debugging."""
    
    def get(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        
        try:
            # Generate PRN content
            prn_content = generate_tspl_prn_label(animal)
            
            # Generate enhanced BAT content
            enhanced_bat_content = generate_enhanced_printer_config_bat(prn_content)
            
            # Return as downloadable file for testing
            response = HttpResponse(
                enhanced_bat_content,
                content_type='application/octet-stream'
            )
            response['Content-Disposition'] = f'attachment; filename="test_enhanced_printer_{animal.identification_tag}.bat"'
            return response
            
        except Exception as e:
            import traceback
            error_info = f"Error generating enhanced BAT: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            return HttpResponse(error_info, content_type='text/plain')
