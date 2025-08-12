# Reception App - Detailed Design

This document details the design of the `reception` Django app, which is responsible for client intake, creating and managing slaughter orders, and defining the service packages associated with these orders.

## Core Models

### 1. `SlaughterOrder` Model

Represents a client's request for slaughter services. It serves as the central hub for an order, linking to the client, service package, and all associated animals.

*   **Purpose:** To capture and manage the details of a client's slaughter request.
*   **Key Fields:**
    *   `slaughter_order_no` (CharField, unique, optional): A human-readable, unique order number. Automatically generated if not provided.
    *   `client` (ForeignKey to `users.ClientProfile`, nullable): Links to an existing client profile for loyal customers.
    *   `client_name` (CharField, blank): For walk-in or one-time clients, their name can be recorded here.
    *   `client_phone` (CharField, blank): For walk-in or one-time clients, their phone number.
    *   `service_package` (ForeignKey to `ServicePackage`): Defines the set of services requested for this order.
    *   `order_date` (DateField): The date the order was placed.
    *   `status` (CharField with choices): Tracks the current status of the order (e.g., PENDING, IN_PROGRESS, COMPLETED, BILLED, CANCELLED).
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

## URLs and Views

The `reception` app will provide the following user-facing pages:

### 1. Create Slaughter Order

*   **URL:** `/reception/create_order/`
*   **View:** `CreateSlaughterOrderView` (Class-Based View)
    *   **Template:** `reception/create_order.html`
    *   **HTTP Methods:**
        *   `GET`: Renders the `SlaughterOrderForm` for creating a new order.
        *   `POST`: Processes the submitted form. On successful validation, it calls the `create_slaughter_order` service and redirects to a success page or back to the form.
*   **Permissions:** `LoginRequiredMixin`

### 2. Slaughter Order List

*   **URL:** `/reception/orders/`
*   **View:** `SlaughterOrderListView` (ListView)
    *   **Template:** `reception/order_list.html`
    *   **Functionality:** Displays a paginated list of all slaughter orders, showing key information like Order No., Client, Date, and Status.
*   **Permissions:** `LoginRequiredMixin`

### 3. Slaughter Order Detail

*   **URL:** `/reception/orders/<int:pk>/`
*   **View:** `SlaughterOrderDetailView` (DetailView)
    *   **Template:** `reception/order_detail.html`
    *   **Functionality:** Shows all details for a specific slaughter order, including the service package, all associated animals, and their current statuses.
*   **Permissions:** `LoginRequiredMixin`

## Service Layer

To encapsulate business logic, the `reception` app will have a `services.py` file.

### Planned Services

#### `create_slaughter_order(...) -> SlaughterOrder`
*   **Purpose:** Orchestrates the creation of a new `SlaughterOrder` and its associated `Animal` records.

#### `update_slaughter_order(order: SlaughterOrder, **update_data) -> SlaughterOrder`
*   **Purpose:** To handle changes to an existing order, such as modifying the `service_package` or `destination`.
*   **Logic:** Will contain checks to prevent invalid updates (e.g., changing the package after processing has begun).

#### `cancel_slaughter_order(order: SlaughterOrder, reason: str) -> SlaughterOrder`
*   **Purpose:** To safely cancel an order.
*   **Logic:** Will check if the order can be cancelled, change its status to `CANCELLED`, and handle the associated `Animal` records.

#### `update_order_status_from_animals(order: SlaughterOrder) -> SlaughterOrder`
*   **Purpose:** To automatically update the order's status based on the status of all animals within it.
*   **Logic:** Can be called when an animal's status changes to progress the order's status from `PENDING` to `IN_PROGRESS` to `COMPLETED`.

#### `bill_order(order: SlaughterOrder) -> SlaughterOrder`
*   **Purpose:** To mark an order as billed.
*   **Logic:** Changes the order's status to `BILLED` and can be expanded later for financial integrations.

#### `add_animal_to_order(order: SlaughterOrder, animal_data: dict) -> Animal`
*   **Purpose:** To add a new animal to a `PENDING` order.
*   **Logic:** Checks if the order status is `PENDING` before calling the `processing.services.create_animal` service.

#### `remove_animal_from_order(order: SlaughterOrder, animal: Animal)`
*   **Purpose:** To remove an animal from a `PENDING` order.
*   **Logic:** Checks if the order status is `PENDING` before deleting the `Animal` object.