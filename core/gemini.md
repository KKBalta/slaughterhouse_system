# App: core

## Purpose
This app serves as the foundational layer of the project. It holds shared utilities, custom management commands, and base model classes that are used across all other applications. Its primary goal is to reduce code duplication and enforce project-wide standards.

## Key Components

### `models.py`
This file contains the most critical component of the `core` app: the `BaseModel`.

-   **`BaseModel`**: This is an **abstract** model that all other models in the project should inherit from. It provides the following common fields automatically:
    -   `id` (UUIDField, Primary Key): A universally unique identifier for every record. This is preferred over standard integer IDs for security and scalability.
    -   `created_at` (DateTimeField): Automatically records the timestamp when an object is first created.
    -   `updated_at` (DateTimeField): Automatically records the timestamp every time an object is saved.
    -   `is_active` (BooleanField): A flag for implementing "soft deletes." Instead of deleting a record, you can set this to `False`.

-   **Methods**:
    -   `soft_delete()`: Call this method on an instance to mark it as inactive (`is_active = False`).
    -   `restore()`: Call this method on a soft-deleted instance to mark it as active again (`is_active = True`).

#### **Usage Example for Agents:**
When creating a new model in another app (e.g., `reception`), you **must** inherit from `BaseModel` like this:

```python
# In reception/models.py
from django.db import models
from core.models import BaseModel # <-- Import BaseModel
from users.models import ClientProfile

class SlaughterOrder(BaseModel): # <-- Inherit from BaseModel
    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE)
    order_date = models.DateField()
    # ... other fields

    # Note: You do not need to add id, created_at, updated_at, or is_active.
    # They are inherited automatically.
```

### Other Files

-   **`admin.py`**: Use this file to register any models that are part of the `core` app or to define project-wide admin customizations.
-   **`views.py`**: Can be used for project-wide views that don't belong to a specific app, such as a landing page or shared API endpoints.
-   **`tests.py`**: Contains tests for the functionality within the `core` app itself (e.g., testing the `BaseModel`'s methods).
-   **`management/commands/`**: This directory (which you can create) is where you should place any custom `manage.py` commands that are not specific to a single app (e.g., `create_groups`, `seed_data`).
