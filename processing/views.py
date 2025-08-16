from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, ListView, DetailView, View
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse
from datetime import datetime

from .models import Animal, WeightLog
from reception.models import SlaughterOrder
from .forms import AnimalFilterForm, WeightLogForm, LeatherWeightForm, BatchWeightLogForm
from .services import log_group_weight, mark_animal_slaughtered, log_individual_weight, log_leather_weight, get_batch_weight_reports
from . import services


class ProcessingDashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'processing/dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get counts by status
        status_counts = Animal.objects.values('status').annotate(count=Count('id'))
        status_dict = {item['status']: item['count'] for item in status_counts}
        
        # Recent orders with animals ready for processing
        recent_orders = SlaughterOrder.objects.filter(
            animals__status__in=['received', 'slaughtered', 'carcass_ready']
        ).distinct().order_by('-order_datetime')[:10]
        
        # Animals by status for quick actions
        received_animals = Animal.objects.filter(status='received').order_by('received_date')[:20]
        slaughtered_animals = Animal.objects.filter(status='slaughtered').order_by('-slaughter_date')[:20]
        
        # Orders ready for batch operations
        orders_ready_for_slaughter = SlaughterOrder.objects.filter(
            animals__status='received'
        ).annotate(
            received_count=Count('animals', filter=Q(animals__status='received'))
        ).filter(received_count__gt=0).order_by('-order_datetime')[:10]
        
        context.update({
            'status_counts': status_dict,
            'recent_orders': recent_orders,
            'received_animals': received_animals,
            'slaughtered_animals': slaughtered_animals,
            'orders_ready_for_slaughter': orders_ready_for_slaughter,
            'total_animals_today': Animal.objects.filter(
                received_date__date=timezone.now().date()
            ).count(),
        })
        
        return context


class AnimalListView(LoginRequiredMixin, ListView):
    model = Animal
    template_name = 'processing/animal_list.html'
    context_object_name = 'animals'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = Animal.objects.select_related(
            'slaughter_order', 'slaughter_order__client', 'slaughter_order__client__user'
        ).order_by('-received_date')
        
        # Filter by status if provided
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
            
        # Filter by animal type if provided
        animal_type = self.request.GET.get('animal_type')
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)
            
        # Enhanced search by identification tag, order number, and client name
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(identification_tag__icontains=search) |
                Q(slaughter_order__slaughter_order_no__icontains=search) |
                Q(slaughter_order__client__company_name__icontains=search) |
                Q(slaughter_order__client__user__first_name__icontains=search) |
                Q(slaughter_order__client__user__last_name__icontains=search) |
                Q(slaughter_order__client__contact_person__icontains=search) |
                Q(slaughter_order__client_name__icontains=search) |  # For walk-in clients
                Q(animal_type__icontains=search)
            )
            
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Initialize form with GET parameters
        form = AnimalFilterForm(self.request.GET)
        context['form'] = form
        
        # Keep the old context for backward compatibility
        context['status_choices'] = Animal.STATUS_CHOICES
        context['animal_type_choices'] = Animal.ANIMAL_TYPES
        context['current_status'] = self.request.GET.get('status', '')
        context['current_animal_type'] = self.request.GET.get('animal_type', '')
        context['current_search'] = self.request.GET.get('search', '')
        return context


class AnimalDetailView(LoginRequiredMixin, DetailView):
    model = Animal
    template_name = 'processing/animal_detail.html'
    context_object_name = 'animal'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['weight_logs'] = self.object.individual_weight_logs.order_by('-log_date')
        context['weight_form'] = WeightLogForm(animal=self.object)
        context['leather_form'] = LeatherWeightForm(instance=self.object)
        return context


class MarkAnimalSlaughteredView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        
        try:
            mark_animal_slaughtered(animal)
            messages.success(request, f'Animal {animal.identification_tag} marked as slaughtered.')
        except Exception as e:
            messages.error(request, f'Error marking animal as slaughtered: {str(e)}')
        
        return redirect('processing:animal_detail', pk=animal.pk)


class AnimalWeightLogView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        form = WeightLogForm(request.POST, animal=animal)
        
        if form.is_valid():
            weight_type = form.cleaned_data['weight_type']
            weight = form.cleaned_data['weight']
            
            try:
                if weight_type == 'leather_weight':
                    # Handle leather weight specially
                    log_leather_weight(animal, weight)
                    messages.success(request, f'Leather weight ({weight} kg) logged for {animal.identification_tag}.')
                else:
                    # Handle regular weight logging
                    log_individual_weight(animal, weight_type, weight)
                    messages.success(request, f'{weight_type.replace("_", " ").title()} ({weight} kg) logged for {animal.identification_tag}.')
            except Exception as e:
                messages.error(request, f'Error logging weight: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        
        return redirect('processing:animal_detail', pk=animal.pk)


class BatchSlaughterView(LoginRequiredMixin, TemplateView):
    template_name = 'processing/batch_slaughter.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get orders with animals ready for slaughter
        orders = SlaughterOrder.objects.filter(
            animals__status='received'
        ).annotate(
            received_count=Count('animals', filter=Q(animals__status='received'))
        ).filter(received_count__gt=0).order_by('-order_datetime')
        
        context['orders'] = orders
        return context
    
    def post(self, request):
        order_id = request.POST.get('order_id')
        if not order_id:
            messages.error(request, 'Please select an order.')
            return redirect('processing:batch_slaughter')
        
        order = get_object_or_404(SlaughterOrder, pk=order_id)
        animals_to_slaughter = order.animals.filter(status='received')
        
        success_count = 0
        error_count = 0
        
        for animal in animals_to_slaughter:
            try:
                mark_animal_slaughtered(animal)
                success_count += 1
            except Exception as e:
                error_count += 1
        
        if success_count > 0:
            messages.success(request, f'Successfully slaughtered {success_count} animals.')
        if error_count > 0:
            messages.warning(request, f'{error_count} animals could not be processed.')
        
        return redirect('processing:batch_slaughter')


class BatchWeightLogView(LoginRequiredMixin, TemplateView):
    template_name = 'processing/batch_weights.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get orders with slaughtered animals (ready for weight logging)
        orders = SlaughterOrder.objects.filter(
            animals__status='slaughtered'
        ).annotate(
            slaughtered_count=Count('animals', filter=Q(animals__status='slaughtered'))
        ).filter(slaughtered_count__gt=0).order_by('-order_datetime')
        
        # Add batch weight progress information for each order
        orders_with_progress = []
        for order in orders:
            # Calculate progress for each weight type
            weight_progress = {}
            weight_types = ['live_weight', 'hot_carcass_weight', 'cold_carcass_weight', 'final_weight']
            
            for weight_type in weight_types:
                group_weight_type = f"{weight_type} Group"
                existing_logs = WeightLog.objects.filter(
                    slaughter_order=order,
                    weight_type=group_weight_type,
                    is_group_weight=True
                ).order_by('-log_date')
                
                # Calculate progress
                total_weighed = sum(log.group_quantity for log in existing_logs)
                remaining = order.slaughtered_count - total_weighed
                
                # Check if individual weights were auto-generated (completion)
                individual_logs_exist = WeightLog.objects.filter(
                    animal__slaughter_order=order,
                    weight_type=weight_type,
                    is_group_weight=False
                ).exists()
                
                weight_progress[weight_type] = {
                    'total_weighed': total_weighed,
                    'remaining': max(0, remaining),
                    'logs_count': existing_logs.count(),
                    'completed': individual_logs_exist or total_weighed >= order.slaughtered_count,
                    'latest_log': existing_logs.first()
                }
            
            orders_with_progress.append({
                'order': order,
                'weight_progress': weight_progress
            })
        
        context['orders_with_progress'] = orders_with_progress
        context['form'] = BatchWeightLogForm()
        
        # Add recent batch weight logs for reference
        recent_logs = WeightLog.objects.filter(
            is_group_weight=True
        ).select_related('slaughter_order').order_by('-log_date')[:10]
        context['recent_logs'] = recent_logs
        
        return context
    
    def post(self, request):
        form = BatchWeightLogForm(request.POST)
        
        if form.is_valid():
            try:
                order_id = form.cleaned_data['order_id']
                weight_type = form.cleaned_data['weight_type']
                total_weight = form.cleaned_data['total_weight']
                animal_count = form.cleaned_data['animal_count']
                
                order = get_object_or_404(SlaughterOrder, pk=order_id)
                
                # Calculate average weight per animal
                average_weight = total_weight / animal_count
                
                # Create proper weight type for group weights
                group_weight_type = f"{weight_type} Group"
                
                # Check current progress before logging
                existing_logs = WeightLog.objects.filter(
                    slaughter_order=order,
                    weight_type=group_weight_type,
                    is_group_weight=True
                )
                current_total = sum(log.group_quantity for log in existing_logs)
                
                # Call service with correct parameters
                weight_log = log_group_weight(
                    slaughter_order=order, 
                    weight=average_weight,  # Average weight per animal
                    weight_type=group_weight_type, 
                    group_quantity=animal_count, 
                    group_total_weight=total_weight  # Total weight of the group
                )
                
                # Check if this completed the weight type
                new_total = current_total + animal_count
                slaughtered_count = order.animals.filter(status='slaughtered').count()
                
                if new_total >= slaughtered_count:
                    messages.success(
                        request, 
                        f"✅ Batch weight logged successfully! All {slaughtered_count} animals for {weight_type.replace('_', ' ').title()} "
                        f"are now weighed. Individual weight logs have been automatically created with "
                        f"average weight of {average_weight:.2f}kg per animal."
                    )
                else:
                    remaining = slaughtered_count - new_total
                    messages.success(
                        request, 
                        f"Batch weight logged: {animal_count} animals weighed ({total_weight}kg total, "
                        f"{average_weight:.2f}kg average). {remaining} animals remaining for {weight_type.replace('_', ' ').title()}."
                    )
                
            except Exception as e:
                messages.error(request, f'Error logging batch weight: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        
        return redirect('processing:batch_weights')


class BatchWeightReportsView(LoginRequiredMixin, TemplateView):
    template_name = 'processing/batch_weight_reports.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get filter parameters from request
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        order_id = self.request.GET.get('order_id')
        
        # Convert date strings to datetime objects
        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                date_from = None
                
        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                date_to = None
        
        # Get comprehensive report data
        report_data = services.get_batch_weight_reports(
            date_from=date_from,
            date_to=date_to,
            order_id=order_id
        )
        
        context.update(report_data)
        context['form_data'] = {
            'date_from': date_from.strftime('%Y-%m-%d') if date_from else '',
            'date_to': date_to.strftime('%Y-%m-%d') if date_to else '',
            'order_id': order_id or ''
        }
        
        return context


class OrderStatusUpdateView(LoginRequiredMixin, View):
    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        
        # Update order status based on animal statuses
        # This could be expanded to handle specific status updates
        
        messages.success(request, f'Order {order.slaughter_order_no} status updated.')
        return redirect('processing:dashboard')


class AnimalSearchView(View):  # Temporarily removed LoginRequiredMixin for debugging
    def get(self, request):
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'animals': []})
        
        # Enhanced case-insensitive search including client name
        animals = Animal.objects.select_related(
            'slaughter_order', 'slaughter_order__client', 'slaughter_order__client__user'
        ).filter(
            Q(identification_tag__icontains=query) |
            Q(slaughter_order__slaughter_order_no__icontains=query) |
            Q(slaughter_order__client__company_name__icontains=query) |
            Q(slaughter_order__client__user__first_name__icontains=query) |
            Q(slaughter_order__client__user__last_name__icontains=query) |
            Q(slaughter_order__client__contact_person__icontains=query) |
            Q(slaughter_order__client_name__icontains=query) |  # For walk-in clients
            Q(animal_type__icontains=query)
        )[:20]  # Limit to 20 results
        
        animals_data = []
        for animal in animals:
            # Determine client info
            if animal.slaughter_order.client:
                client_info = (
                    animal.slaughter_order.client.company_name or 
                    animal.slaughter_order.client.get_full_name()
                )
            else:
                client_info = animal.slaughter_order.client_name or "Walk-in Client"
            
            animals_data.append({
                'id': str(animal.pk),
                'identification_tag': animal.identification_tag,
                'animal_type_display': animal.get_animal_type_display(),
                'order_number': animal.slaughter_order.slaughter_order_no,
                'client_info': client_info,
                'status': animal.status,
                'status_display': animal.get_status_display(),
                'received_date': animal.received_date.strftime("%b %d, %H:%M"),
                'detail_url': reverse('processing:animal_detail', kwargs={'pk': animal.pk})
            })
        
        return JsonResponse({'animals': animals_data})


class LeatherWeightLogView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        form = LeatherWeightForm(request.POST, instance=animal)
        
        if form.is_valid():
            try:
                leather_weight = form.cleaned_data['leather_weight_kg']
                log_leather_weight(animal, leather_weight)
                messages.success(request, f'Leather weight ({leather_weight} kg) logged for {animal.identification_tag}.')
            except Exception as e:
                messages.error(request, f'Error logging leather weight: {str(e)}')
        else:
            # Display form errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
        
        return redirect('processing:animal_detail', pk=animal.pk)


class AnimalSearchDebugView(View):
    """Debug view to test search functionality"""
    def get(self, request):
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'debug': 'query too short', 'animals': []})
        
        try:
            # Enhanced case-insensitive search including client name
            animals = Animal.objects.select_related(
                'slaughter_order', 'slaughter_order__client', 'slaughter_order__client__user'
            ).filter(
                Q(identification_tag__icontains=query) |
                Q(slaughter_order__slaughter_order_no__icontains=query) |
                Q(slaughter_order__client__company_name__icontains=query) |
                Q(slaughter_order__client__user__first_name__icontains=query) |
                Q(slaughter_order__client__user__last_name__icontains=query) |
                Q(slaughter_order__client__contact_person__icontains=query) |
                Q(slaughter_order__client_name__icontains=query) |  # For walk-in clients
                Q(animal_type__icontains=query)
            )[:20]  # Limit to 20 results
            
            animals_data = []
            for animal in animals:
                # Determine client info
                if animal.slaughter_order.client:
                    client_info = (
                        animal.slaughter_order.client.company_name or 
                        animal.slaughter_order.client.get_full_name()
                    )
                else:
                    client_info = animal.slaughter_order.client_name or "Walk-in Client"
                
                animals_data.append({
                    'id': str(animal.pk),
                    'identification_tag': animal.identification_tag,
                    'animal_type_display': animal.get_animal_type_display(),
                    'order_number': animal.slaughter_order.slaughter_order_no,
                    'client_info': client_info,
                    'status': animal.status,
                    'status_display': animal.get_status_display(),
                    'received_date': animal.received_date.strftime("%b %d, %H:%M"),
                    'detail_url': reverse('processing:animal_detail', kwargs={'pk': animal.pk})
                })
            
            return JsonResponse({
                'debug': f'found {len(animals_data)} results for query: {query}',
                'animals': animals_data
            })
            
        except Exception as e:
            return JsonResponse({
                'debug': f'error: {str(e)}',
                'animals': [],
                'error': str(e)
            })
