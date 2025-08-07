# Core App - Detailed Design

This document details the design of the `core` Django app, which serves as a central repository for shared utilities, abstract base models, custom management commands, and static assets that are utilized across multiple other applications within the Slaughterhouse System.

## Core Models

### 1. `BaseModel` (Abstract Model)

An abstract base model that provides common fields and functionalities to other models throughout the project. All other models in the system should inherit from this `BaseModel`.

*   **Purpose:** To enforce consistency and reduce redundancy by providing standard fields like creation and modification timestamps.
*   **Key Fields:**
    *   `created_at` (DateTimeField): Automatically set to the current date and time when the object is first created.
    *   `updated_at` (DateTimeField): Automatically updated every time the object is saved.

### 2. `ServicePackage` Model (Proposed Location)

While initially considered for `reception`, placing `ServicePackage` in `core` might be more appropriate if its definition and usage are truly cross-cutting and not solely tied to `reception`'s direct responsibilities. This allows other apps (e.g., `processing` for workflow orchestration) to directly reference it without a circular dependency.

*   **Purpose:** To define and manage predefined sets of services offered by the slaughterhouse, enabling modular workflows.
*   **Key Fields:**
    *   `name` (CharField, unique): A descriptive name for the service package (e.g., "Slaughter Only", "Slaughter + Disassembly").
    *   `description` (TextField, optional): A detailed description of what the service package includes.
    *   `includes_disassembly` (BooleanField): Indicates if this package includes the disassembly process.
    *   `includes_delivery` (BooleanField): Indicates if this package includes delivery services.
    *   `is_active` (BooleanField): Whether the service package is currently available.
    *   *(Additional boolean fields for other specific services as needed)*

## App Functionality

*   **Base Model Provision:** Provides `BaseModel` for consistent timestamping and potential future common fields across all models.
*   **Shared Utilities:** Can house utility functions, helper classes, or decorators that are used by multiple apps.
*   **Custom Management Commands:** A place for Django custom management commands that perform system-wide tasks (e.g., data cleanup, reporting generation scripts).
*   **Static Assets:** Can serve as a central location for project-wide static files (CSS, JS, images) that are not specific to any single app.
*   **Cross-Cutting Concerns:** Manages models like `ServicePackage` that are fundamental to the system's modularity and are referenced by multiple other apps.