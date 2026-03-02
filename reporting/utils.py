from django.apps import apps
from django.db.models import Avg, Count, Sum
from django.utils import timezone


def generate_report_data(report_definition) -> dict:
    """
    Generates report data based on the provided Report definition.
    This is a basic implementation and can be expanded for more complex reports.
    """
    report_type = report_definition.report_type
    config = report_definition.configuration or {}

    data = {
        "report_name": report_definition.name,
        "generated_at": timezone.now().isoformat(),
        "parameters": config,
        "results": {},
    }

    if report_type == "operational":
        # Example: Daily Throughput Report
        # Get models dynamically
        SlaughterOrder = apps.get_model("reception.SlaughterOrder")
        Animal = apps.get_model("processing.Animal")
        Carcass = apps.get_model("inventory.Carcass")

        start_date = config.get("start_date")
        end_date = config.get("end_date")

        # Filter by date if provided
        orders_query = SlaughterOrder.objects.all()
        animals_query = Animal.objects.all()
        carcasses_query = Carcass.objects.all()

        if start_date:
            orders_query = orders_query.filter(order_date__gte=start_date)
            animals_query = animals_query.filter(received_date__gte=start_date)
            carcasses_query = carcasses_query.filter(created_at__gte=start_date)
        if end_date:
            orders_query = orders_query.filter(order_date__lte=end_date)
            animals_query = animals_query.filter(received_date__lte=end_date)
            carcasses_query = carcasses_query.filter(created_at__lte=end_date)

        data["results"]["total_orders"] = orders_query.count()
        data["results"]["total_animals_received"] = animals_query.count()
        data["results"]["total_carcasses_produced"] = carcasses_query.count()
        data["results"]["total_hot_carcass_weight_kg"] = (
            carcasses_query.aggregate(Sum("hot_carcass_weight"))["hot_carcass_weight__sum"] or 0
        )
        data["results"]["avg_hot_carcass_weight_kg"] = (
            carcasses_query.aggregate(Avg("hot_carcass_weight"))["hot_carcass_weight__avg"] or 0
        )

        # Example: Animals by Type
        animals_by_type = animals_query.values("animal_type").annotate(count=Count("animal_type"))
        data["results"]["animals_by_type"] = list(animals_by_type)

    elif report_type == "financial":
        # Placeholder for financial reports
        data["results"]["revenue_summary"] = "Not yet implemented"

    elif report_type == "analytics":
        # Placeholder for analytics reports
        data["results"]["yield_analysis"] = "Not yet implemented"

    return data
