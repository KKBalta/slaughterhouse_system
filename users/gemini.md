# Users App - Detailed Design

This document details the design of the `users` Django app, which is responsible for user management, authentication, authorization, and client profiles. It supports both internal staff users and external clients.

## Core Models

### 1. `User` Model

Represents a user of the system. This will likely be a custom user model extending Django's `AbstractUser` to allow for future flexibility and custom fields.

*   **Purpose:** To manage user accounts for both internal staff (clerks, processing staff) and external clients who wish to access the `portal`.
*   **Key Fields (beyond Django's default `AbstractUser` fields):**
    *   `user_type` (CharField with choices): Differentiates between internal staff and clients (e.g., 'STAFF', 'CLIENT').
    *   *(Additional custom fields as needed for staff or client-specific user attributes)*

### 2. `ClientProfile` Model

Represents the profile information for a client. This model is designed to accommodate both loyal, registered clients and one-time or walk-in clients.

*   **Purpose:** To store detailed information about a client, separate from their login credentials (if any).
*   **Key Fields:**
    *   `user` (OneToOneField to `User`, nullable): Links to a `User` account if the client is registered and logs in. Can be null for one-time clients.
    *   `company_name` (CharField, optional): The name of the client's company or organization.
    *   `contact_person` (CharField): The primary contact person for the client.
    *   `email` (EmailField, optional): Client's email address.
    *   `phone_number` (CharField, optional): Client's primary phone number.
    *   `address` (TextField, optional): Client's physical address.
    *   `tax_id` (CharField, optional): Client's tax identification number.
    *   *(Additional fields for client-specific details)*

## App Functionality

*   **User Authentication & Authorization:** Handles user login, logout, password management, and permissions for accessing different parts of the system.
*   **Client Profile Management:** Allows for the creation, retrieval, update, and deletion of client profiles, supporting both registered users and walk-in clients.
*   **Role-Based Access Control:** Enables defining different roles (e.g., clerk, processing staff, client) and assigning appropriate permissions.
*   **Integration with other Apps:** Provides `User` and `ClientProfile` models that are referenced by other apps (e.g., `reception` for `SlaughterOrder`, `inventory` for `Label` printing).
