# Users App – Detailed Design

This document details the design of the `users` Django app, responsible for user management, authentication, authorization, and client profile management. It supports both internal staff (administrators, managers, operators) and external clients with different permissions and data requirements.

## 1. Core Responsibilities

### User Management
*   Custom `User` model extending Django’s `AbstractUser`.
*   Role-based access control (RBAC) with predefined roles.
*   Handles authentication, password reset, and session management.

### Client Profile Management
*   Stores additional client-specific data beyond login credentials.
*   Supports individual and enterprise account types.

### System Integration
*   `ClientProfile` is referenced by:
    *   `reception` for `SlaughterOrder` creation.
    *   `portal` for client order/asset access.
    *   `reporting` for client-specific analytics.

## 2. Models

### 2.1. `User` Model

*   **Purpose:** Stores authentication data, user roles, and base identity.
*   **Base:** Extends Django’s `AbstractUser` for flexibility.
*   **Key Fields:**
    *   `role` (Choice field): Defines the user's role within the system:
        *   `ADMIN`: Full system control.
        *   `MANAGER`: Operational oversight with advanced permissions but no system configuration.
        *   `OPERATOR`: Day-to-day operations (reception, processing updates, labeling).
        *   `CLIENT`: Portal access to view own orders/assets.
    *   `base_role`: Default role assigned when creating a user without specifying one.

### 2.2. `ClientProfile` Model

*   **Purpose:** Stores detailed client information separate from authentication.
*   **Link:** One-to-one relationship with `User` (nullable for one-time clients).
*   **Account Types:**
    *   `INDIVIDUAL`: Personal clients, small-scale or one-time orders.
    *   `ENTERPRISE`: Businesses/farms with regular or bulk orders.
*   **Key Fields:**
    *   `contact_person`: Required for enterprise, optional for individual.
    *   `phone_number`: Primary contact number.
    *   `address`: Physical location (pickup/delivery address).
    *   `company_name`: Enterprise-specific.
    *   `tax_id`: Enterprise-specific.
    *   `account_type`: Controls available fields and portal UI.

## 3. RBAC (Role-Based Access Control)

RBAC defines who can do what in the system. Permissions are centrally managed, ideally in the `core` app, to avoid scattering checks across code.

### Example Role → Permission Mapping

```python
ROLE_PERMISSIONS = {
    "ADMIN": ["*"],  # full access
    "MANAGER": [
        "reception.add_slaughterorder", "reception.change_slaughterorder",
        "processing.view_animal", "processing.change_animal",
        "inventory.view_carcass", "inventory.change_carcass",
        "reporting.view_reports"
    ],
    "OPERATOR": [
        "reception.add_slaughterorder",
        "processing.change_animal", "processing.add_weightlog",
        "labeling.print_label"
    ],
    "CLIENT": [
        "portal.view_own_orders"
    ],
}
```

### RBAC Enforcement
*   Enforced via Django’s built-in permissions system and/or custom decorators.
*   Centralized helper in `core.permissions` to check roles before allowing access.

## 4. Admin Panel Features

### Custom `UserAdmin`
*   Displays role, username, email, `is_staff`.
*   Inline editing of `ClientProfile` from `User` page.

### `ClientProfileAdmin`
*   Searchable by company name, contact person, or linked username.
*   Filterable by `account_type`.

## 5. Integration Points

| App       | Usage of `users` Models                               |
| :-------- | :---------------------------------------------------- |
| `Reception` | Links `SlaughterOrder` to `ClientProfile`.            |
| `Portal`    | Filters visible orders/assets by `ClientProfile`.     |
| `Reporting` | Generates per-client analytics and history.           |
| `Core`      | Uses `User.role` for RBAC checks.                     |
