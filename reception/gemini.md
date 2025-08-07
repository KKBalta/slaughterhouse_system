# App: reception

## Purpose
This app manages the entire client intake process. Its primary responsibility is to create and manage "Slaughter Orders," which act as the main container for a client's batch of animals. It is designed with flexibility to handle both pre-registered clients and on-the-fly "walk-in" clients.

## Core Models

### `SlaughterOrder`
This is the central model for the app. It inherits from `core.BaseModel`.

-   **Key Fields**:
    -   `client` (ForeignKey to `users.ClientProfile`, optional): This links the order to a **registered client**. If this field is set, the client is a known entity with a user account.
    -   `client_name` (CharField): If the order is for a **walk-in client**, their name is stored here. This field should be empty for registered clients.
    -   `client_phone` (CharField): The phone number for a **walk-in client**.
    -   `order_date` (DateField): The date the order was created.
    -   `status` (CharField with choices): Tracks the current state of the order (Pending, In-Progress, Completed, Billed).

-   **Logic**: The model's design allows a clerk to either select a registered client from a search-as-you-type list or simply type in the name and phone number for a new, unregistered client.

## Admin Interface (`admin.py`)

The `SlaughterOrder` model is registered with the Django admin, providing a powerful interface for clerks.

-   **`SlaughterOrderAdmin`**:
    -   **Search & Filter**: Allows clerks to easily find orders by status, date, or client name/company.
    -   **Autocomplete for Clients**: When creating or editing an order, the `client` field is an autocomplete widget that allows for efficient searching of all registered `ClientProfile` records.

### **Custom Admin Action: `convert_to_registered_client`**

This is a key feature for improving operational workflow.

-   **Purpose**: To seamlessly convert a walk-in client into a registered client with a user account, preserving their order history.
-   **How to Use**:
    1.  In the `SlaughterOrder` admin list view, select one or more orders belonging to the *same* walk-in client.
    2.  From the "Actions" dropdown menu, select "Convert to Registered Client".
    3.  Click "Go".
-   **What it Does**:
    1.  It checks that the selected order is indeed for a walk-in (i.e., `client` is not set).
    2.  It creates a new `User` with a unique username (based on name + phone) and a secure, randomly generated password.
    3.  It creates a new `ClientProfile` linked to the new `User`, populating it with the name and phone number from the order.
    4.  It finds **all** past and present orders matching the walk-in client's name and phone number and links them to the newly created `ClientProfile`.
    5.  It displays a success message to the clerk containing the new **username and temporary password**, which can then be given to the client.
