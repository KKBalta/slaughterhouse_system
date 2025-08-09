# Labeling App - Detailed Design

This document details the design of the `labeling` Django app, which is responsible for generating and printing labels for various assets within the Slaughterhouse System, including carcasses, meat cuts, offal, and by-products. It will support different label formats, including wristband-style labels.

## Core Models

### 1. `LabelTemplate` Model

Defines the structure and content of different label types.

*   **Purpose:** To allow for flexible and configurable label designs.
*   **Key Fields:**
    *   `name` (CharField, unique): A descriptive name for the template (e.g., "Carcass Label", "Meat Cut Wristband").
    *   `template_data` (JSONField): Stores the layout and content variables for the label (e.g., position of text, barcodes, images).
    *   `target_item_type` (CharField with choices): Specifies which type of inventory item this template is for (e.g., 'Carcass', 'MeatCut', 'Offal', 'ByProduct').
    *   `is_active` (BooleanField): Whether the template is currently active and usable.

### 2. `PrintJob` Model

Records details of each label printing request.

*   **Purpose:** To log printing activities, track print status, and facilitate reprinting if needed.
*   **Key Fields:**
    *   `label_template` (ForeignKey to `LabelTemplate`): The template used for this print job.
    *   `item_type` (CharField with choices): The type of item being labeled (e.g., 'Carcass', 'MeatCut').
    *   `item_id` (PositiveIntegerField): The ID of the specific inventory item being labeled.
    *   `quantity` (IntegerField): Number of labels printed for this job.
    *   `print_date` (DateTimeField): When the print job was initiated.
    *   `printed_by` (ForeignKey to `users.User`): The user who initiated the print job.
    *   `status` (CharField with choices): Status of the print job (e.g., 'PENDING', 'COMPLETED', 'FAILED').

### 3. `Label` Model

Represents a physical label generated for a carcass, meat cut, offal, or by-product.

*   **Purpose:** To store information about printed labels and their association with inventory items.
*   **Key Fields:**
    *   `label_code` (CharField, unique): A unique code printed on the label (e.g., QR code, barcode).
    *   `item_type` (CharField with choices): Specifies what the label is for (e.g., 'Carcass', 'MeatCut', 'Offal', 'ByProduct').
    *   `item_id` (UUIDField): The ID of the associated inventory item (e.g., Carcass.id, MeatCut.id). Changed from PositiveIntegerField to UUIDField to match BaseModel IDs.
    *   `print_date` (DateTimeField): When the label was printed.
    *   `printed_by` (ForeignKey to `users.User`): The user who printed the label.

## App Functionality

*   **Label Generation:** Dynamically generates label content based on `LabelTemplate` and data from associated inventory items.
*   **Printing Interface:** Provides an interface for users to select items and print labels.
*   **Template Management:** Allows administrators to create, edit, and manage label templates.
*   **Print Job Logging:** Records all printing activities for auditing and troubleshooting.
*   **Integration with Inventory:** Fetches necessary data from the `inventory` app to populate labels.