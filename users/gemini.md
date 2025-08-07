# App: users

## Purpose
Handles all user management, authentication, authorization, and profiles. It distinguishes between different roles in the system.

## Core Models

- **User (Custom)**: Inherits from `AbstractUser`.
  - `role`: (Clerk, Client, Admin)
- **ClientProfile**:
  - `user`: (OneToOne to User)
  - `account_type`: (Individual, Enterprise)
  - `company_name`: (CharField, optional)
  - `contact_person`: (CharField)
  - `phone_number`: (CharField)
  - `address`: (TextField)

## Key Logic
- User registration for Clients.
- Admin interface for creating Clerk and other Admin accounts.
- Group-based permissions for controlling access to different parts of the system.