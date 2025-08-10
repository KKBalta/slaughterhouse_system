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

## 6. Service Layer

To ensure business logic is reusable and decoupled from the views/API layer, the `users` app will have a dedicated `services.py` file.

### Planned Services

#### `create_user_with_profile(username, password, role, **profile_data) -> User`

*   **Purpose:** To handle the creation of a `User` and their associated `ClientProfile` in a single, atomic transaction. This is the primary service for registering new clients.
*   **Logic:**
    1.  Creates a `User` instance with the provided credentials and role.
    2.  If `profile_data` is provided, it creates a `ClientProfile` linked to the new user.
    3.  The entire operation is wrapped in `@transaction.atomic` to ensure data integrity.

#### `update_user_profile(user: User, **profile_data) -> ClientProfile`

*   **Purpose:** To update the `ClientProfile` for a given user.
*   **Logic:**
    1.  Fetches the `ClientProfile` associated with the user.
    2.  Updates the profile fields with the provided `profile_data`.
    3.  Saves the changes.

#### `assign_role_to_user(user: User, new_role: str) -> User`

*   **Purpose:** To handle the changing of a user's role.
*   **Logic:**
    1.  Updates the `role` field on the `User` instance.
    2.  (Future) This service can be expanded to include checks to ensure the user making the change has the permission to do so.
    3.  Saves the updated user.

#### `convert_walk_in_to_profile(phone_number: str, user_data: dict, profile_data: dict) -> ClientProfile`

*   **Purpose:** To upgrade a walk-in customer to a registered client and link their past orders to the new profile.
*   **Logic:**
    1.  Creates a new `User` and `ClientProfile` based on the provided data.
    2.  Finds all `SlaughterOrder` records that match the walk-in's `phone_number` and have no associated client profile.
    3.  Updates each of these past orders to link them to the new `ClientProfile`.
    4.  Clears the redundant `client_name` and `client_phone` from the updated orders.
    5.  The entire operation is wrapped in `@transaction.atomic` for safety.

### Lifecycle & Security Services

#### `deactivate_user(user: User) -> User`

*   **Purpose:** To safely suspend a user's access without deleting them.
*   **Logic:** Sets the `is_active` flag on the `User` model to `False`, preventing login while preserving all historical data.

#### `reactivate_user(user: User) -> User`

*   **Purpose:** To restore access for a deactivated user.
*   **Logic:** Sets the `is_active` flag on the `User` model back to `True`.

#### `change_user_password(user: User, old_password: str, new_password: str) -> bool`

*   **Purpose:** Allows a user to change their own password.
*   **Logic:** Verifies the `old_password` is correct. If so, it sets and hashes the `new_password` and returns `True`. Otherwise, returns `False`.

#### `admin_reset_user_password(user: User, new_password: str) -> User`

*   **Purpose:** Allows an administrator to reset a user's password without the old one.
*   **Logic:** Directly sets and hashes the `new_password` for the given user.

#### `archive_client_profile(client_profile: ClientProfile) -> ClientProfile`

*   **Purpose:** To formally off-board a client, hiding them from active lists while preserving their data.
*   **Logic:** Uses the `soft_delete()` method to set the `is_active` flag on the `ClientProfile` model to `False`.

## 7. Future Enhancements (v2.0)

This section lists potential future improvements for the `users` app that are out of scope for the initial version but should be considered for future releases.

*   **Merge Duplicate Client Profiles:** A service to merge two client profiles (e.g., a registered profile and a walk-in record for the same person) into a single, canonical profile, re-associating all related orders.
*   **Detailed Audit Trail:** A more granular logging system to track every change made to a user's role or a client's profile, recording who made the change and when.
*   **Two-Factor Authentication (2FA):** An enhancement to the login process to provide an extra layer of security for all user accounts.
