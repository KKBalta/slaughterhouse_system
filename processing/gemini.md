# Processing App - Detailed Design

This document details the design of the `processing` Django app, which is responsible for tracking individual animals through the slaughter workflow, orchestrating conditional processing steps, managing animal-specific details, and handling both individual and group weight logging.

## Core Models

### 1. `Animal` Model

Represents an individual animal within a `SlaughterOrder`. It tracks common attributes across all animal types and links to specific detail models for unique characteristics. The workflow for each animal will be managed using `django-fsm` to ensure proper state transitions.

*   **Purpose:** To uniquely identify and track each animal from intake through slaughter, enforcing valid workflow progression.
*   **Key Fields:**
    *   `slaughter_order` (ForeignKey to `reception.SlaughterOrder`): Links the animal to its parent order.
    *   `animal_type` (CharField with choices): Specifies the species (e.g., 'cattle', 'sheep', 'goat', 'lamb', 'oglak', 'calf', 'heifer', 'beef').
    *   `identification_tag` (CharField, nullable): A unique identifier for the animal. If not provided, the system will generate one. This field is not unique at the database level to allow for system-generated tags.
    *   `received_date` (DateTimeField): Date and time the animal was received. This field is editable to accommodate edge cases like night slaughter entries.
    *   `slaughter_date` (DateTimeField, nullable): Timestamp of when the animal was slaughtered.
    *   `status` (CharField): Tracks the current state of the animal in the processing workflow (e.g., 'RECEIVED', 'SLAUGHTERED', 'CARCASS_READY'). Managed by `django-fsm`.
    *   `picture` (ImageField, optional): An image of the animal.
    *   `leather_weight_kg` (DecimalField, optional): The weight of the leather in kilograms. Applicable to all animal types.

### 2. Animal Detail Models (`CattleDetails`, `SheepDetails`, `GoatDetails`, `LambDetails`, `OglakDetails`, `CalfDetails`, `HeiferDetails`)

These models store attributes specific to each animal type, linked via a `OneToOneField` to the `Animal` model. This approach ensures a clean and scalable design for diverse animal characteristics.

*   **Purpose:** To store species-specific data without cluttering the main `Animal` model.
*   **Key Fields (Examples - specific fields will vary by animal type):**
    *   `animal` (OneToOneField to `Animal`): The associated animal instance, limited by `animal_type`.
    *   `breed` (CharField): The breed of the animal.
    *   `horn_status` (CharField, for CattleDetails): Status of horns (e.g., horned, polled, dehorned).
    *   `wool_type` (CharField, for SheepDetails): Type of wool (e.g., fine, medium, coarse).
    *   `liver_status` (DecimalField, for CattleDetails): Score reflecting the usability of the liver (0: Not Usable, 0.5: Not Bad, 1: Good).
    *   `head_status` (DecimalField, for CattleDetails): Score reflecting the usability of the head (0: Not Usable, 0.5: Not Bad, 1: Good).
    *   `bowels_status` (DecimalField, for CattleDetails): Score reflecting the usability of the bowels (0: Not Usable, 0.5: Not Bad, 1: Good).

### 3. `WeightLog` Model

Records various weight measurements throughout the animal's processing, supporting both individual and group weighings.

*   **Purpose:** To log weights at different stages (e.g., live, hot carcass, cold carcass) and handle group weighing scenarios.
*   **Key Fields:**
    *   `animal` (ForeignKey to `Animal`, nullable): The animal whose weight is being logged (for individual weights).
    *   `slaughter_order` (ForeignKey to `reception.SlaughterOrder`, nullable): The slaughter order this group weight belongs to (for group weights).
    *   `weight` (DecimalField): The recorded weight. For group weights, this stores the calculated average weight per animal.
    *   `weight_type` (CharField): Describes the type of weight (e.g., 'Live', 'Hot Carcass', 'Live Group').
    *   `is_group_weight` (BooleanField): `True` if this log entry represents a group weighing.
    *   `group_quantity` (IntegerField, nullable): Number of animals in the group, if `is_group_weight` is `True`.
    *   `group_total_weight` (DecimalField, nullable): Total weight of the group, if `is_group_weight` is `True`.
    *   `log_date` (DateTimeField): Timestamp of the weight measurement.
*   **Constraints:** Ensures data consistency, requiring either `animal` or `slaughter_order` to be present, and that group-related fields are correctly populated when `is_group_weight` is `True`.

## App Functionality

*   **Animal Tracking:** Manages the lifecycle of individual animals from intake to final processing.
*   **Workflow Orchestration with `django-fsm`:** The `processing` app will leverage `django-fsm` to define and enforce state transitions for the `Animal` model. This ensures a controlled and valid progression through the slaughter workflow. Transitions can be conditional based on the `ServicePackage` selected in the `SlaughterOrder`.
*   **Weight Management:** Records and manages all weight data, accommodating both precise individual measurements and efficient group weighings with average calculations.
*   **Data Enrichment:** Stores animal-specific details through dedicated related models, allowing for tailored data capture based on species.

## Service Layer

To encapsulate business logic, the `processing` app will have a `services.py` file.

### Planned Services

#### `create_animal(...) -> Animal`
*   **Purpose:** Orchestrates the creation of a new `Animal` and its associated detail model.

#### `mark_animal_slaughtered(animal: Animal) -> Animal`
*   **Purpose:** To transition the animal's status to 'slaughtered'.
*   **Logic:** Calls the `animal.perform_slaughter()` FSM transition.

#### `create_carcass_from_slaughter(animal: Animal, hot_carcass_weight: float, disposition: str) -> Carcass`
*   **Purpose:** To create a `Carcass` record in the inventory after an animal has been slaughtered.
*   **Logic:** Creates a `Carcass` object linked to the `Animal` with the provided hot carcass weight and disposition. This service should be called after `mark_animal_slaughtered`.

#### `log_individual_weight(animal: Animal, weight_type: str, weight: float) -> WeightLog`
*   **Purpose:** Logs an individual weight measurement for an animal.

#### `disassemble_carcass(animal: Animal, meat_cuts_data: list, offal_data: list, by_products_data: list)`
*   **Purpose:** Handles the disassembly of a carcass, creating all resulting inventory items.
*   **Logic:** Creates `MeatCut` records. For `cattle`, `calf`, and `heifer` types, it also creates `Offal` and `ByProduct` records based on provided data. Raises `ValidationError` if offal/byproduct data is provided for animal types that do not track them.

#### `record_initial_byproducts(animal: Animal, offal_data: list, by_products_data: list) -> dict`

*   **Purpose:** To record the initial removal of offal and by-products that occur immediately after slaughter, before the main carcass disassembly.
*   **Logic:** For `cattle`, `calf`, and `heifer` types, it creates `Offal` and `ByProduct` records. It does NOT change the `Animal`'s status to `disassembled` or the `Carcass`'s status to `disassembly_ready`. Raises `ValidationError` if offal/byproduct data is provided for animal types that do not track them.

#### `update_animal_details(animal: Animal, details_data: dict) -> Animal`

*   **Purpose:** To update the specific details (e.g., breed, horn status) of an animal.
*   **Logic:** Identifies the correct detail model (e.g., `CattleDetails`) associated with the `Animal` and updates its fields.

#### `log_group_weight(slaughter_order: SlaughterOrder, weight: float, weight_type: str, group_quantity: int, group_total_weight: float) -> WeightLog`

*   **Purpose:** To record weight measurements for a batch of animals associated with a `SlaughterOrder`.
*   **Logic:** Creates a `WeightLog` entry, ensuring `is_group_weight` is `True` and all group-related fields are populated.

#### `package_animal_products(animal: Animal) -> Animal`

*   **Purpose:** To mark an animal's products as packaged.
*   **Logic:** Calls the `animal.perform_packaging()` FSM transition.

#### `deliver_animal_products(animal: Animal) -> Animal`

*   **Purpose:** To mark an animal's products as delivered to the client.
*   **Logic:** Calls the `animal.deliver_product()` FSM transition.

#### `return_animal_to_owner(animal: Animal) -> Animal`

*   **Purpose:** To mark an animal or its products as returned to the owner.
*   **Logic:** Calls the `animal.return_to_owner()` FSM transition.
