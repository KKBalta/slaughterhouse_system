#!/usr/bin/env python3
"""
Test script to verify the weight retrieval fix for animal labels
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from processing.models import Animal, WeightLog
from labeling.utils import generate_animal_label_data

def test_weight_retrieval():
    """Test weight retrieval from WeightLog model"""
    print("Testing weight retrieval from WeightLog model...")
    
    # Try to find an animal with weight logs
    animals = Animal.objects.all()[:5]
    
    for animal in animals:
        print(f"\n--- Testing Animal: {animal.identification_tag} ---")
        print(f"Status: {animal.status}")
        
        # Check weight logs
        weight_logs = animal.individual_weight_logs.all()
        print(f"Total weight logs: {weight_logs.count()}")
        
        for log in weight_logs:
            print(f"  - {log.weight_type}: {log.weight}kg (logged: {log.log_date})")
        
        # Test hot carcass weight specifically
        hot_carcass_log = animal.individual_weight_logs.filter(
            weight_type='hot_carcass_weight'
        ).order_by('-log_date').first()
        
        if hot_carcass_log:
            print(f"Hot carcass weight found: {hot_carcass_log.weight}kg")
        else:
            print("No hot carcass weight found")
        
        # Test the label data generation
        try:
            label_data = generate_animal_label_data(animal)
            print(f"Label weight value: {label_data.get('weight', 'N/A')}")
        except Exception as e:
            print(f"Label generation error: {e}")

def create_test_weight_log():
    """Create a test weight log if none exist"""
    print("\nCreating test weight log...")
    
    # Get first available animal
    animal = Animal.objects.first()
    if not animal:
        print("No animals found to test with")
        return
        
    print(f"Using animal: {animal.identification_tag}")
    
    # Check if hot carcass weight already exists
    existing_log = animal.individual_weight_logs.filter(
        weight_type='hot_carcass_weight'
    ).first()
    
    if existing_log:
        print(f"Hot carcass weight already exists: {existing_log.weight}kg")
        return existing_log
    
    # Create a test hot carcass weight log
    try:
        weight_log = WeightLog.objects.create(
            animal=animal,
            weight=185.5,  # Test weight
            weight_type='hot_carcass_weight'
        )
        print(f"Created test hot carcass weight: {weight_log.weight}kg")
        return weight_log
    except Exception as e:
        print(f"Error creating weight log: {e}")
        return None

if __name__ == "__main__":
    print("=== Weight Fix Test Script ===")
    
    # First check existing data
    test_weight_retrieval()
    
    # Create test data if needed
    test_log = create_test_weight_log()
    
    # Test again with new data
    if test_log:
        print("\n=== Testing after creating test weight log ===")
        test_weight_retrieval()
    
    print("\n=== Test Complete ===")
