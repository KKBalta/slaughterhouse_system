# Inventory App - Detailed Design

This document details the design of the `inventory` Django app, which is responsible for managing all post-slaughter assets, including carcasses, meat cuts, offal, and other by-products, as well as tracking their disposition.

## Core Models

### 1. `StorageLocation` Model

Represents a physical location within the slaughterhouse where inventory items can be stored.

*   **Purpose:** To track the physical location of carcasses, cuts, and by-products.
*   **Key Fields:**
    *   `name` (CharField, unique): A unique name for the storage location (e.g., 'Freezer 1', 'Cooler A, Shelf 3').
    *   `location_type` (CharField with choices): Categorizes the type of storage (e.g., 'Freezer', 'Cooler', 'Dry Storage').
    *   `capacity_kg` (DecimalField, optional): The storage capacity in kilograms.
    *   `is_active` (BooleanField): Whether the location is currently in use.

### 2. `Carcass` Model

Represents the main carcass of an animal after slaughter, before any further disassembly. Its status will be managed using `django-fsm`.

*   **Purpose:** To track the primary output of the slaughter process and manage its lifecycle within inventory.
*   **Key Fields:**
    *   `animal` (OneToOneField to `processing.Animal`): The animal this carcass belongs to.
    *   `hot_carcass_weight` (DecimalField): The weight of the carcass immediately after slaughter.
    *   `cold_carcass_weight` (DecimalField, optional): The weight of the carcass after chilling.
    *   `status` (CharField with choices): Current status (e.g., 'chilling', 'disassembly_ready', 'frozen', 'dispatched'). Managed by `django-fsm`.
    *   `disposition` (CharField with choices): How the carcass will be handled (e.g., 'Returned to Owner', 'For Sale').
    *   `storage_location` (ForeignKey to `StorageLocation`, nullable): The current physical storage location of the carcass.

### 3. `MeatCut` Model

Represents specific cuts of meat derived from a carcass after disassembly.

*   **Purpose:** To track individual meat portions for sale or return to client.
*   **Key Fields:**
    *   `carcass` (ForeignKey to `Carcass`): The carcass from which this cut was derived.
    *   `cut_type` (CharField with choices): Describes the specific cut based on animal type.
        *   **Beef Cuts:** 'Whole Piece Boneless', 'Neck', 'Chuck', 'Ribeye', 'Shank', 'Knuckle', 'Striploin', 'Tenderloin', 'Flank', 'Fillet', 'Brisket', 'Ground Beef', 'Stew Meat', 'Meatball Mix', 'Sausage', 'Braised Meat'.
        *   **Lamb/Goat Cuts:** 'Whole Piece Boneless', 'Neck', 'Shoulder', 'Leg', 'Rack', 'Flank', 'Chop', 'Grilled Cutlet', 'Empty'.
    *   `weight` (DecimalField): The weight of this specific cut.
    *   `disposition` (CharField with choices): How the cut will be handled (e.g., 'Returned to Owner', 'For Sale').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this cut. (This will be managed by the `labeling` app).
    *   `storage_location` (ForeignKey to `StorageLocation`, nullable): The current physical storage location of the meat cut.

### 4. `Offal` Model

Represents edible organs and other internal parts of the animal.

*   **Purpose:** To track and manage offal products.
*   **Key Fields:**
    *   `animal` (ForeignKey to `processing.Animal`): The animal this offal came from.
    *   `offal_type` (CharField with choices): Describes the type of offal.
        *   **Beef Offal:** 'Beef Liver', 'Heart', 'Spleen', 'Head Meat', 'Caul Fat', 'Kidney Fat', 'Omentum Fat'.
        *   **Lamb/Goat Offal:** 'Lamb Liver Set', 'Head'.
    *   `weight` (DecimalField): The weight of the offal.
    *   `disposition` (CharField with choices): How the offal will be handled (e.g., 'Returned to Owner', 'For Sale', 'Discarded').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this offal. (This will be managed by the `labeling` app).
    *   `storage_location` (ForeignKey to `StorageLocation`, nullable): The current physical storage location of the offal.

### 5. `ByProduct` Model

Represents non-meat by-products of the slaughter process (e.g., skin, head, feet).

*   **Purpose:** To track and manage non-edible or non-meat by-products.
*   **Key Fields:**
    *   `animal` (ForeignKey to `processing.Animal`): The animal this by-product came from.
    *   `byproduct_type` (CharField with choices): Describes the type of by-product.
        *   **General By-products:** 'Skin', 'Head', 'Feet'.
    *   `weight` (DecimalField, optional): The weight of the by-product.
    *   `disposition` (CharField with choices): How the by-product will be handled (e.g., 'Returned to Owner', 'For Sale', 'Discarded').
    *   `label_id` (CharField, unique, optional): Reference to a physical label printed for this by-product. (This will be managed by the `labeling` app).
    *   `storage_location` (ForeignKey to `StorageLocation`, nullable): The current physical storage location of the by-product.

## App Functionality

*   **Asset Tracking:** Manages the creation and lifecycle of all post-slaughter assets.
*   **Disposition Management:** Tracks whether assets are returned to the owner, sold, or discarded.
*   **Inventory Control:** Offers a detailed view of all available and processed products, including their physical location.
*   **State Management with `django-fsm`:** The `Carcass` model will use `django-fsm` to manage its status transitions within the inventory workflow (e.g., from 'chilling' to 'disassembly_ready').
