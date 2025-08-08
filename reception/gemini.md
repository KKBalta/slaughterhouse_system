# Reception App - Detailed Design

This document details the design of the `reception` Django app, which is responsible for client intake, creating and managing slaughter orders, and defining the service packages associated with these orders.

## Core Models

### 1. `SlaughterOrder` Model

Represents a client's request for slaughter services. It serves as the central hub for an order, linking to the client, service package, and all associated animals.

*   **Purpose:** To capture and manage the details of a client's slaughter request.
*   **Key Fields:**
    *   `client` (ForeignKey to `users.ClientProfile`, nullable): Links to an existing client profile for loyal customers.
    *   `client_name` (CharField, blank): For walk-in or one-time clients, their name can be recorded here.
    *   `client_phone` (CharField, blank): For walk-in or one-time clients, their phone number.
    *   `service_package` (ForeignKey to `ServicePackage`): Defines the set of services requested for this order.
    *   `order_date` (DateField): The date the order was placed.
    *   `status` (CharField with choices): Tracks the current status of the order (e.g., PENDING, IN_PROGRESS, COMPLETED, BILLED).
    *   `destination` (CharField, optional): Specifies the final destination or market for the animals/products in this order.

### 2. `ServicePackage` Model

Defines a collection of services that a client can request. This model is crucial for enabling the modularity of the system, allowing different workflows based on selected services.

*   **Purpose:** To define and manage predefined sets of services offered by the slaughterhouse.
*   **Key Fields:**
    *   `name` (CharField, unique): A descriptive name for the service package (e.g., "Slaughter Only", "Slaughter + Disassembly", "Full Service").
    *   `description` (TextField, optional): A detailed description of what the service package includes.
    *   `includes_disassembly` (BooleanField): Indicates if this package includes the disassembly process.
    *   `includes_delivery` (BooleanField): Indicates if this package includes delivery services.
    *   `is_active` (BooleanField): Whether the service package is currently available.
    *   *(Additional boolean fields for other specific services as needed)*

## App Functionality

*   **Order Creation & Management:** Allows clerks to create new slaughter orders, link them to existing clients or create new temporary client entries, and assign a `ServicePackage`.
*   **Service Package Definition:** Provides a mechanism to define and manage the various service packages offered.
*   **Client Intake:** Serves as the primary point of entry for client and order information into the system.
*   **Order Status Tracking:** Manages the high-level status of each slaughter order throughout its lifecycle.
