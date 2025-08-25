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
from .utils import create_animal_label, get_animal_label_download_data, generate_zpl_label, generate_pdf_label

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
    """Generate and create a new animal label."""
    
    def post(self, request, animal_id):
        animal = get_object_or_404(Animal, id=animal_id)
        label_type = request.POST.get('label_type', 'hot_carcass')
        
        # Check if animal has been slaughtered for hot carcass labels
        if label_type == 'hot_carcass' and animal.status not in ['slaughtered', 'carcass_ready', 'disassembled', 'packaged', 'delivered']:
            messages.error(request, _('Hot carcass labels can only be generated for slaughtered animals.'))
            return redirect('processing:animal_detail', pk=animal.pk)
        
        try:
            # Create the label
            animal_label = create_animal_label(
                animal=animal,
                label_type=label_type,
                user=request.user
            )
            
            messages.success(request, _('Label generated successfully!'))
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
    """Download animal label in ZPL or PDF format."""
    
    def get(self, request, label_id, format_type='zpl'):
        animal_label = get_object_or_404(AnimalLabel, id=label_id)
        
        try:
            download_data = get_animal_label_download_data(animal_label, format_type)
            
            if format_type.lower() == 'zpl':
                # Return ZPL content as text file
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
        format_type = request.GET.get('format', 'zpl')
        
        try:
            if format_type.lower() == 'zpl':
                zpl_content = generate_zpl_label(animal, label_type)
                return HttpResponse(zpl_content, content_type='text/plain')
            elif format_type.lower() == 'pdf':
                from .utils import generate_pdf_label
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
