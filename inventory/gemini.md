# Inventory App - Detailed Design

This document details the design of the `inventory` Django app, which is responsible for managing all post-slaughter assets, including carcasses, meat cuts, offal, and other by-products, as well as tracking their disposition and labeling.

## Core Models

### 1. `Carcass` Model

Represents the main carcass of an animal after slaughter, before any further disassembly.

*   **Purpose:** To track the primary output of the slaughter process.
*   **Key Fields:**
    *   `animal` (OneToOneField to `processing.Animal`): The animal this carcass belongs to.
    *   `weight` (DecimalField): The weight of the carcass (e.g., hot or cold carcass weight).
    *   `status` (CharField with choices): Current status (e.g., 'Chilling', 'Disassembly Ready', 'Frozen', 'Dispatched').
    *   `disposition` (CharField with choices): How the carcass will be handled (e.g., 'Returned to Owner', 'For Sale').

### 2. `MeatCut` Model

Represents specific cuts of meat derived from a carcass after disassembly.

*   **Purpose:** To track individual meat portions for sale or return to client.
*   **Key Fields:**
    *   `carcass` (ForeignKey to `Carcass`): The carcass from which this cut was derived.
    *   `cut_type` (CharField): Describes the specific cut (e.g., 'Front Quarter', 'Hind Quarter', 'Loin', 'Rib').
    *   `weight` (DecimalField): The weight of this specific cut.
    *   `disposition` (CharField with choices): How the cut will be handled (e.g., 'Returned to Owner', 'For Sale').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this cut.

### 3. `Offal` Model

Represents edible organs and other internal parts of the animal.

*   **Purpose:** To track and manage offal products.
*   **Key Fields:**
    *   `animal` (ForeignKey to `processing.Animal`): The animal this offal came from.
    *   `offal_type` (CharField): Describes the type of offal (e.g., 'Liver', 'Kidneys', 'Heart').
    *   `weight` (DecimalField): The weight of the offal.
    *   `disposition` (CharField with choices): How the offal will be handled (e.g., 'Returned to Owner', 'For Sale', 'Discarded').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this offal.

### 4. `ByProduct` Model

Represents non-meat by-products of the slaughter process (e.g., skin, head, feet).

*   **Purpose:** To track and manage non-edible or non-meat by-products.
*   **Key Fields:**
    *   `animal` (ForeignKey to `processing.Animal`): The animal this by-product came from.
    *   `byproduct_type` (CharField): Describes the type of by-product (e.g., 'Skin', 'Head', 'Feet').
    *   `weight` (DecimalField, optional): The weight of the by-product.
    *   `disposition` (CharField with choices): How the by-product will be handled (e.g., 'Returned to Owner', 'For Sale', 'Discarded').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this by-product.

### 5. `Label` Model

Represents a physical label generated for a carcass, meat cut, offal, or by-product.

*   **Purpose:** To store information about printed labels and their association with inventory items.
*   **Key Fields:**
    *   `label_code` (CharField, unique): A unique code printed on the label (e.g., QR code, barcode).
    *   `item_type` (CharField with choices): Specifies what the label is for (e.g., 'Carcass', 'MeatCut', 'Offal', 'ByProduct').
    *   `item_id` (PositiveIntegerField): The ID of the associated inventory item (e.g., Carcass.id, MeatCut.id).
    *   `print_date` (DateTimeField): When the label was printed.
    *   `printed_by` (ForeignKey to `users.User`): The user who printed the label.

## App Functionality

*   **Asset Tracking:** Manages the creation and lifecycle of all post-slaughter assets.
*   **Disposition Management:** Tracks whether assets are returned to the owner, sold, or discarded.
*   **Labeling Integration:** Provides the data and framework for generating and associating physical labels with inventory items.
*   **Inventory Control:** Offers a detailed view of all available and processed products.
