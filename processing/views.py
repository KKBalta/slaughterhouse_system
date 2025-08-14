from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView, ListView, DetailView, View
from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse

from .models import Animal, WeightLog
from reception.models import SlaughterOrder
from .forms import AnimalFilterForm
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
            'slaughter_order', 'slaughter_order__client'
        ).order_by('-received_date')
        
        # Filter by status if provided
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)
            
        # Filter by animal type if provided
        animal_type = self.request.GET.get('animal_type')
        if animal_type:
            queryset = queryset.filter(animal_type=animal_type)
            
        # Search by identification tag
        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(identification_tag__icontains=search) |
                Q(slaughter_order__slaughter_order_no__icontains=search)
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
        return context


class MarkAnimalSlaughteredView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        
        try:
            services.mark_animal_slaughtered(animal)
            messages.success(request, f'Animal {animal.identification_tag} marked as slaughtered.')
        except Exception as e:
            messages.error(request, f'Error marking animal as slaughtered: {str(e)}')
        
        return redirect('processing:animal_detail', pk=animal.pk)


class AnimalWeightLogView(LoginRequiredMixin, View):
    def post(self, request, pk):
        animal = get_object_or_404(Animal, pk=pk)
        
        weight_type = request.POST.get('weight_type')
        weight = request.POST.get('weight')
        
        if not weight_type or not weight:
            messages.error(request, 'Weight type and weight value are required.')
            return redirect('processing:animal_detail', pk=animal.pk)
        
        try:
            weight_float = float(weight)
            services.log_individual_weight(animal, weight_type, weight_float)
            messages.success(request, f'{weight_type} weight logged for {animal.identification_tag}.')
        except (ValueError, Exception) as e:
            messages.error(request, f'Error logging weight: {str(e)}')
        
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
                services.mark_animal_slaughtered(animal)
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
        
        context['orders'] = orders
        return context
    
    def post(self, request):
        order_id = request.POST.get('order_id')
        weight_type = request.POST.get('weight_type')
        total_weight = request.POST.get('total_weight')
        animal_count = request.POST.get('animal_count')
        
        if not all([order_id, weight_type, total_weight, animal_count]):
            messages.error(request, 'All fields are required for batch weight logging.')
            return redirect('processing:batch_weights')
        
        try:
            order = get_object_or_404(SlaughterOrder, pk=order_id)
            total_weight_float = float(total_weight)
            animal_count_int = int(animal_count)
            
            services.log_group_weight(
                order, total_weight_float, weight_type, animal_count_int, total_weight_float
            )
            
            messages.success(request, f'Batch weight logged for {animal_count_int} animals.')
        except (ValueError, Exception) as e:
            messages.error(request, f'Error logging batch weight: {str(e)}')
        
        return redirect('processing:batch_weights')


class OrderStatusUpdateView(LoginRequiredMixin, View):
    def post(self, request, order_pk):
        order = get_object_or_404(SlaughterOrder, pk=order_pk)
        
        # Update order status based on animal statuses
        # This could be expanded to handle specific status updates
        
        messages.success(request, f'Order {order.slaughter_order_no} status updated.')
        return redirect('processing:dashboard')


class AnimalSearchView(LoginRequiredMixin, View):
    def get(self, request):
        query = request.GET.get('q', '').strip()
        
        if len(query) < 2:
            return JsonResponse({'animals': []})
        
        # Case-insensitive search
        animals = Animal.objects.select_related(
            'slaughter_order', 'slaughter_order__client'
        ).filter(
            Q(identification_tag__icontains=query) |
            Q(slaughter_order__slaughter_order_no__icontains=query) |
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
